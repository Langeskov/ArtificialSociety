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
    s = engine.get(society_id)
    if s is None:
        raise HTTPException(404, "society not found")
    groups = {}
    for a in s.agents:
        g = a.group or a.ideology.origin_label
        groups.setdefault(g, []).append(a.id)
    return {"groups": [{"group": g, "members": m, "size": len(m)} for g, m in groups.items()]}


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
