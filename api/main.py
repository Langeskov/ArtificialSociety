"""FastAPI application — REST API + WebSocket for the simulation (§30, §31).

This is the operator-facing surface: create societies, run/pause/step/reset,
inspect agents/events/metrics, and stream live updates to the frontend.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.simulation.engine import SimulationEngine
from configs.loader import default_society_config, load_config
from storage.db import Storage


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
STATIC_DIR = ROOT / "visualization" / "static"

engine = SimulationEngine()
storage = Storage(DATA_DIR)

app = FastAPI(title="Artificial Society", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Background simulation loop (per-society asyncio tasks)
# --------------------------------------------------------------------------
class RunLoop:
    """Coordinates the background ticking of running societies."""

    def __init__(self) -> None:
        self.running: dict[str, "asyncio.Future"] = {}
        self.speed: dict[str, float] = {}
        self.paused: set[str] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop) -> None:
        self._loop = loop

    async def _run(self, society_id: str, speed: float) -> None:
        try:
            while True:
                if society_id in self.paused:
                    await asyncio.sleep(0.05)
                    continue
                s = engine.get(society_id)
                if s is None:
                    break
                summary = await asyncio.to_thread(engine.step, society_id)
                # Persist metrics + events periodically
                if summary:
                    tick = summary["clock"]["tick"]
                    await asyncio.to_thread(storage.save_metrics, society_id, tick, summary["metrics"])
                    if summary.get("new_events"):
                        await asyncio.to_thread(storage.save_events, society_id, s.events.recent(50))
                        await asyncio.to_thread(storage.append_event_log, society_id, s.events.recent(50))
                    # Sample agent ideological positions every 20 ticks for history/trajectory.
                    if tick % 20 == 0:
                        await asyncio.to_thread(storage.save_agent_states, society_id, s.agents, tick)
                await self._broadcast(society_id, {"type": "tick", **summary})
                await asyncio.sleep(max(0.0, 0.02 / max(speed, 0.1)))
        except asyncio.CancelledError:
            pass

    async def _broadcast(self, society_id: str, message: dict) -> None:
        subs = [ws for ws, sid in clients.items() if sid == society_id]
        payload = json.dumps(message, ensure_ascii=False)
        for ws in subs:
            try:
                await ws.send_text(payload)
            except Exception:
                pass

    def start(self, society_id: str, speed: float) -> None:
        self.speed[society_id] = speed
        self.paused.discard(society_id)
        s = engine.get(society_id)
        if s:
            s.status = "running"
            s.speed = speed
        if self._loop is None:
            return
        existing = self.running.get(society_id)
        if existing is None or existing.done():
            # Schedule onto the main event loop from any thread.
            fut = asyncio.run_coroutine_threadsafe(self._run(society_id, speed), self._loop)
            self.running[society_id] = fut

    def pause(self, society_id: str) -> None:
        self.paused.add(society_id)
        s = engine.get(society_id)
        if s:
            s.status = "paused"

    def resume(self, society_id: str, speed: Optional[float] = None) -> None:
        self.paused.discard(society_id)
        s = engine.get(society_id)
        if s:
            s.status = "running"
            if speed:
                s.speed = speed
                self.speed[society_id] = speed

    def stop(self, society_id: str) -> None:
        self.paused.add(society_id)
        s = engine.get(society_id)
        if s:
            s.status = "finished"


runloop = RunLoop()
clients: dict[WebSocket, str] = {}


@app.on_event("startup")
async def _startup() -> None:
    runloop.set_loop(asyncio.get_running_loop())


# --------------------------------------------------------------------------
# Request models
# --------------------------------------------------------------------------
class SocietyCreate(BaseModel):
    config: Optional[dict] = None
    seed: Optional[int] = None


class ModelChat(BaseModel):
    model: str = ""
    messages: list = []
    temperature: float = 0.7


class ExperimentCreate(BaseModel):
    config: Optional[dict] = None
    society_count: int = 1
    seed_start: int = 0


# --------------------------------------------------------------------------
# Society endpoints
# --------------------------------------------------------------------------
@app.post("/api/society/create")
def society_create(body: SocietyCreate):
    cfg = body.config or default_society_config()
    s = engine.create_society(cfg, seed=body.seed)
    storage.save_society(s)
    storage.save_agents(s.society_id, s.agents)
    return s.snapshot()


@app.get("/api/society/{society_id}")
def society_get(society_id: str):
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    return s.snapshot()


@app.post("/api/society/{society_id}/start")
def society_start(society_id: str, speed: float = 1.0):
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    runloop.start(society_id, speed)
    return {"status": "running", "society_id": society_id}


@app.post("/api/society/{society_id}/pause")
def society_pause(society_id: str):
    if engine.get(society_id) is None:
        raise HTTPException(404, "society not found")
    runloop.pause(society_id)
    return {"status": "paused"}


@app.post("/api/society/{society_id}/resume")
def society_resume(society_id: str, speed: Optional[float] = None):
    if engine.get(society_id) is None:
        raise HTTPException(404, "society not found")
    runloop.resume(society_id, speed)
    return {"status": "running"}


@app.post("/api/society/{society_id}/step")
def society_step(society_id: str, ticks: int = 1):
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    summary = engine.step(society_id, ticks=ticks)
    storage.save_metrics(society_id, summary["clock"]["tick"], summary["metrics"])
    if summary["clock"]["tick"] % 20 == 0:
        storage.save_agent_states(society_id, s.agents, summary["clock"]["tick"])
    return summary


@app.post("/api/society/{society_id}/reset")
def society_reset(society_id: str):
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    runloop.pause(society_id)
    engine.delete(society_id)
    ns = engine.create_society(s.config, society_id=society_id, seed=s.seed)
    storage.save_society(ns)
    storage.save_agents(ns.society_id, ns.agents)
    return ns.snapshot()


@app.post("/api/society/{society_id}/speed")
def society_speed(society_id: str, speed: float = 1.0):
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    s.speed = speed
    runloop.speed[society_id] = speed
    return {"speed": speed}


@app.post("/api/society/{society_id}/inject")
def society_inject(society_id: str, event_type: str = "natural_disaster", severity: float = 0.8):
    """注入一个外生事件（用于演示 / 稳定性测试 §34）。"""
    ev = engine.inject_event(society_id, event_type, severity)
    if ev is None:
        raise HTTPException(404, "society not found")
    return {"event": ev}


@app.get("/api/society/{society_id}/agents")
def society_agents(society_id: str, brief: bool = True, limit: int = 5000):
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    agents = s.agents[:limit]
    return {"count": len(s.agents), "agents": [a.brief() if brief else a.snapshot() for a in agents]}


@app.get("/api/society/{society_id}/groups")
def society_groups(society_id: str):
    """群体列表（v0.4 §71）：由行为涌现的 Group，而非 ideology 标签（§1 禁止 ideology=group）。"""
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    return {"groups": s.groups.as_list(), "history": s.groups.history[-100:]}


@app.get("/api/society/{society_id}/ledger")
def society_ledger(society_id: str, limit: int = 200):
    """资源流水账（v0.4.1 §62）：跨主体资源变化的可审计记录。"""
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    limit = max(1, min(limit, 2000))
    return {"count": len(s.resource_ledger.entries), "entries": s.resource_ledger.recent(limit)}


@app.get("/api/society/{society_id}/regions")
def society_regions(society_id: str):
    """区域资源经济（v0.4.1 §31–§33）：各 region 的供给/价格/人口/就业。"""
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    return {"regions": s.regions.as_list() if s.regions else []}


@app.get("/api/society/{society_id}/events")
def society_events(society_id: str, limit: int = 200):
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    events = s.events.recent(limit)
    return {"count": len(s.events.events), "events": [e.as_dict() for e in events]}


@app.get("/api/society/{society_id}/metrics")
def society_metrics(society_id: str, limit: int = 500):
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    hist = s.metrics_history[-limit:]
    return {"current": s.metrics(), "history": hist}


# --------------------------------------------------------------------------
# v0.3: politics observability endpoints (§38)
# --------------------------------------------------------------------------
@app.get("/api/society/{society_id}/politics")
def society_politics(society_id: str):
    """政治状态空间概览：极化度、相关矩阵、轴主导、簇数。"""
    from engine.politics.observability import polarization_per_axis, axis_correlation, detect_axis_dominance, detect_clusters
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    pol = polarization_per_axis(s.agents)
    corr = axis_correlation(s.agents)
    clusters = detect_clusters(s.agents)
    return {
        "polarization": pol,
        "correlation": corr,
        "axis_dominance": detect_axis_dominance(s.agents),
        "cluster_count": len(clusters),
        "clusters": clusters,
    }


@app.get("/api/society/{society_id}/politics/distribution")
def society_politics_distribution(society_id: str, bins: int = 20):
    """X/Y/Z 分布直方图（§18）。"""
    from engine.politics.observability import distribution_histogram
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    return {
        "x": distribution_histogram(s.agents, "x", bins),
        "y": distribution_histogram(s.agents, "y", bins),
        "z": distribution_histogram(s.agents, "z", bins),
    }


@app.get("/api/society/{society_id}/politics/clusters")
def society_politics_clusters(society_id: str, radius: float = 0.35, min_size: int = 10):
    """政治簇检测（§14）。"""
    from engine.politics.observability import detect_clusters
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    return {"clusters": detect_clusters(s.agents, radius, min_size)}


@app.get("/api/society/{society_id}/politics/correlation")
def society_politics_correlation(society_id: str):
    """X/Y/Z 相关矩阵（§16）。"""
    from engine.politics.observability import axis_correlation
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    return axis_correlation(s.agents)


@app.get("/api/society/{society_id}/politics/attractors")
def society_politics_attractors(society_id: str):
    """吸引子检测（§21）。"""
    from engine.politics.observability import detect_attractors
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    return {"attractors": detect_attractors(s.agents)}


# --------------------------------------------------------------------------
# v0.3.1: dynamics diagnostics endpoints (§39)
# --------------------------------------------------------------------------
def _get_society(society_id: str):
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    return s


@app.get("/api/society/{society_id}/dynamics")
def society_dynamics(society_id: str):
    """动力学诊断总览（§29）：mean / drift / variance / polarization / correlation / boundary / force / dominance。"""
    from engine.politics.observability import (
        axis_mean, axis_velocity, polarization_per_axis, axis_correlation,
        boundary_per_direction, classify_axes, axis_dominance_force, force_budget_percent,
    )
    s = _get_society(society_id)
    return {
        "mean": axis_mean(s.agents),
        "velocity": axis_velocity(s.agents),
        "polarization": polarization_per_axis(s.agents),
        "correlation": axis_correlation(s.agents),
        "boundaries": boundary_per_direction(s.agents),
        "shapes": classify_axes(s.agents),
        "dominance_force": axis_dominance_force(s.agents),
        "force_budget_percent": force_budget_percent(s.agents),
    }


@app.get("/api/society/{society_id}/dynamics/forces")
def society_dynamics_forces(society_id: str):
    """人口级力预算（§16, §28）。"""
    from engine.politics.observability import force_budget, force_budget_percent
    s = _get_society(society_id)
    return {"budget": force_budget(s.agents), "percent": force_budget_percent(s.agents)}


@app.get("/api/society/{society_id}/dynamics/drift")
def society_dynamics_drift(society_id: str):
    """轴漂移（§18）。"""
    from engine.politics.observability import axis_velocity
    s = _get_society(society_id)
    return axis_velocity(s.agents)


@app.get("/api/society/{society_id}/dynamics/variance")
def society_dynamics_variance(society_id: str):
    """轴方差（§19）：当前值 + 历史演化（dVar/dt）。"""
    from engine.politics.observability import polarization_per_axis
    s = _get_society(society_id)
    pol = polarization_per_axis(s.agents)
    # 从 metrics_history 计算方差演化
    hist = s.metrics_history[-50:]
    evol = []
    for m in hist:
        evol.append({
            "tick": m.get("tick", 0),
            "x_var": m.get("political_variance_x", 0.0),
            "y_var": m.get("political_variance_y", 0.0),
            "z_var": m.get("political_variance_z", 0.0),
        })
    return {"current": {"x": pol["x_variance"], "y": pol["y_variance"], "z": pol["z_variance"]}, "evolution": evol}


@app.get("/api/society/{society_id}/dynamics/correlation")
def society_dynamics_correlation(society_id: str):
    """轴相关矩阵（§21）。"""
    from engine.politics.observability import axis_correlation
    s = _get_society(society_id)
    return axis_correlation(s.agents)


@app.get("/api/society/{society_id}/dynamics/boundaries")
def society_dynamics_boundaries(society_id: str):
    """六方向边界集中（§30）。"""
    from engine.politics.observability import boundary_per_direction
    s = _get_society(society_id)
    return boundary_per_direction(s.agents)


# --------------------------------------------------------------------------
# v0.4: groups / identity / information / social-dynamics endpoints (§71)
# --------------------------------------------------------------------------
@app.get("/api/group/{group_id}")
def group_detail(group_id: str, society_id: str):
    """单个群体详情（§58）。"""
    s = _get_society(society_id)
    g = s.groups.get(group_id)
    if g is None:
        raise HTTPException(404, "group not found")
    d = g.as_dict()
    d["members"] = sorted(g.members)
    return d


@app.get("/api/group/{group_id}/members")
def group_members(group_id: str, society_id: str):
    """群体成员列表（§71）。"""
    s = _get_society(society_id)
    g = s.groups.get(group_id)
    if g is None:
        raise HTTPException(404, "group not found")
    members = [s.get_agent(mid).brief() for mid in sorted(g.members) if s.get_agent(mid)]
    return {"group_id": group_id, "members": members}


@app.get("/api/agent/{agent_id}/identity")
def agent_identity(agent_id: str, society_id: str):
    """Agent 身份（§59）。"""
    s = _get_society(society_id)
    a = s.get_agent(agent_id)
    if a is None:
        raise HTTPException(404, "agent not found")
    return a.identity.as_dict()


@app.get("/api/society/{society_id}/information")
def society_information(society_id: str):
    """信息消息列表（§71）。"""
    s = _get_society(society_id)
    msgs = getattr(s, "information_messages", [])
    return {"information": [m.as_dict() for m in msgs[-200:]]}


@app.get("/api/information/{info_id}")
def information_detail(info_id: str, society_id: str):
    """单条信息详情（§60）。"""
    s = _get_society(society_id)
    for m in getattr(s, "information_messages", []):
        if m.id == info_id:
            return m.as_dict()
    raise HTTPException(404, "information not found")


@app.get("/api/information/{info_id}/propagation")
def information_propagation(info_id: str, society_id: str):
    """信息传播路径（§60, §61）。"""
    s = _get_society(society_id)
    for m in getattr(s, "information_messages", []):
        if m.id == info_id:
            return {"id": info_id, "chain": m.propagation_chain, "reach": m.reach}
    raise HTTPException(404, "information not found")


@app.get("/api/society/{society_id}/beliefs")
def society_beliefs(society_id: str):
    """信念分布（§60）。"""
    s = _get_society(society_id)
    subjects: dict[str, list[float]] = {}
    for a in s.agents:
        if not a.alive:
            continue
        for subj, b in getattr(a, "beliefs", {}).items():
            subjects.setdefault(subj, []).append(round(b.belief_strength, 4))
    result = {}
    for subj, vals in subjects.items():
        n = len(vals)
        result[subj] = {
            "count": n,
            "believe": round(sum(1 for v in vals if v > 0.3) / n * 100, 1) if n else 0,
            "neutral": round(sum(1 for v in vals if -0.3 <= v <= 0.3) / n * 100, 1) if n else 0,
            "reject": round(sum(1 for v in vals if v < -0.3) / n * 100, 1) if n else 0,
        }
    return result


@app.get("/api/society/{society_id}/social-dynamics")
def society_social_dynamics(society_id: str):
    """社会动力学总览（§55, §75–§78）。"""
    from engine.metrics.social_metrics import (
        group_metrics, identity_metrics, information_metrics, fragmentation_score, integration_score,
    )
    s = _get_society(society_id)
    return {
        "social_state": s.social_state,
        "groups": group_metrics(s),
        "identity": identity_metrics(s),
        "information": information_metrics(s),
        "fragmentation": fragmentation_score(s),
        "integration": integration_score(s),
    }


@app.post("/api/experiment/ablation")
def experiment_ablation(body: dict):
    """消融实验（§66, §67）：分别关闭 groups/identity/information/behavior 运行。"""
    from configs.loader import default_society_config
    agents = body.get("agents", 500)
    days = body.get("days", 50)
    seed = body.get("seed", 42)
    ablations = body.get("ablations", ["none", "no_groups", "no_identity", "no_information", "no_behavior"])

    def run_ablation(disable: list):
        cfg = default_society_config()
        cfg["population"]["count"] = agents
        for key in disable:
            cfg.setdefault(key, {})["enabled"] = False
        e = SimulationEngine()
        s = e.create_society(cfg, seed=seed)
        for _ in range(days):
            e.step(s.society_id, ticks=100)
        from engine.metrics.social_metrics import group_metrics, fragmentation_score
        from engine.politics.observability import polarization_per_axis
        return {
            "group_count": group_metrics(s)["active_group_count"],
            "fragmentation": fragmentation_score(s),
            "polarization": polarization_per_axis(s)["x_polarization"],
        }

    results = {}
    for name in ablations:
        disable = {
            "no_groups": ["groups"],
            "no_identity": ["identity"],
            "no_information": ["information"],
            "no_behavior": ["behavior"],
            "none": [],
        }.get(name)
        if disable is None:
            continue
        results[name] = run_ablation(disable)
    return {"agents": agents, "days": days, "seed": seed, "results": results}


# --------------------------------------------------------------------------
# Agent endpoints
# --------------------------------------------------------------------------
@app.get("/api/agent/{agent_id}")
def agent_get(agent_id: str, society_id: str):
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    a = s.get_agent(agent_id)
    if a is None:
        raise HTTPException(404, "agent not found")
    return a.snapshot()


@app.get("/api/agent/{agent_id}/history")
def agent_history(agent_id: str, society_id: str, limit: int = 500):
    return {"history": storage.agent_history(society_id, agent_id, limit)}


@app.get("/api/agent/{agent_id}/relationships")
def agent_relationships(agent_id: str, society_id: str):
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    net = getattr(s, "_network", {})
    return {"friends": net.get(agent_id, [])}


@app.get("/api/society/{society_id}/trajectory")
def society_trajectory(society_id: str, agents: int = 50, limit: int = 500):
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    # Deterministic sample: first N alive agents (spread across the population).
    sample = [a.id for a in s.agents if a.alive][:: max(1, len(s.agents) // agents)][:agents]
    return {"trajectories": storage.agent_histories(society_id, sample, limit)}


# --------------------------------------------------------------------------
# Model endpoints
# --------------------------------------------------------------------------
@app.post("/api/model/chat")
def model_chat(body: ModelChat):
    from models.external.provider import make_provider
    # Use the first society's model config, or rule-based if none.
    cfg = default_society_config()
    if engine.societies:
        cfg = next(iter(engine.societies.values())).config
    provider = make_provider(cfg)
    return provider.chat(body.model or cfg["model"].get("model_name", ""), body.messages, body.temperature)


# --------------------------------------------------------------------------
# Experiment endpoints
# --------------------------------------------------------------------------
@app.post("/api/experiment/create")
def experiment_create(body: ExperimentCreate):
    spec = {"config": body.config or default_society_config(),
            "society_count": body.society_count, "seed_start": body.seed_start}
    exp_id = engine.create_experiment(spec)
    storage.save_experiment(exp_id, spec, engine.experiments[exp_id]["society_ids"])
    return {"experiment_id": exp_id, "society_ids": engine.experiments[exp_id]["society_ids"]}


@app.post("/api/experiment/{exp_id}/run")
def experiment_run(exp_id: str, speed: float = 1.0):
    exp = engine.experiment(exp_id)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    for sid in exp["society_ids"]:
        runloop.start(sid, speed)
    return {"status": "running", "society_ids": exp["society_ids"]}


@app.get("/api/experiment/{exp_id}")
def experiment_get(exp_id: str):
    exp = engine.experiment(exp_id)
    if exp is None:
        raise HTTPException(404, "experiment not found")
    return {
        "experiment_id": exp_id,
        "society_ids": exp["society_ids"],
        "societies": [engine.get(sid).snapshot() for sid in exp["society_ids"] if engine.get(sid)],
    }


# --------------------------------------------------------------------------
# Config endpoint
# --------------------------------------------------------------------------
@app.get("/api/config/default")
def config_default():
    return default_society_config()


@app.get("/api/config/ideologies")
def config_ideologies():
    from engine.agent.ideology import IDEOLOGY_TEMPLATES, DEFAULT_AXES, IDEOLOGY_LABELS
    return {"templates": IDEOLOGY_TEMPLATES, "axes": DEFAULT_AXES, "labels": IDEOLOGY_LABELS}


# --------------------------------------------------------------------------
# WebSocket
# --------------------------------------------------------------------------
@app.websocket("/ws/simulation/{society_id}")
async def ws_simulation(websocket: WebSocket, society_id: str):
    await websocket.accept()
    clients[websocket] = society_id
    try:
        while True:
            msg = await websocket.receive_text()
            # Optional client control messages (JSON): {"cmd": "pause"} etc.
            try:
                data = json.loads(msg)
                cmd = data.get("cmd")
                if cmd == "pause":
                    runloop.pause(society_id)
                elif cmd == "resume":
                    runloop.resume(society_id, data.get("speed"))
                elif cmd == "step":
                    await asyncio.to_thread(engine.step, society_id)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        clients.pop(websocket, None)


# --------------------------------------------------------------------------
# Static frontend
# --------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
