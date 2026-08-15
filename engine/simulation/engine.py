"""Simulation Engine — the orchestrator (project §1, §28).

The engine owns all societies, runs the tick loop (single-tick debug is
supported), and hands mutation work to the sub-modules. Hermes-Agent sits
*above* this engine as operator/orchestrator; the engine itself is the
deterministic core that does Agent/Resource/Event/Relationship updates.

v0.2: deterministic persistent RNG per society (§33), and a stability-aware
tick order — economy → recovery → event decay → event detection → information
propagation → political update → memory decay → metrics → collapse detection.
"""

from __future__ import annotations

import random
import threading
import uuid
from typing import Optional

from ..society.society import Society
from ..agent.agent import Agent
from ..economy.economy import step_economy
from ..politics.politics import step_politics
from ..event.engine import step_events
from ..relationship.relationship import build_network
from ..dynamics.decay import decay_events, decay_memory
from ..dynamics.recovery import step_recovery
from ..dynamics.stability import boundary_concentration
from ..group.formation import step_formation
from ..group.lifecycle import step_lifecycle
from ..group.influence import apply_group_influence
from ..identity.update import step_identity
from ..information.propagation import step_information, echo_chamber_score
from ..behavior.behavior import step_behavior
from ..relationship.information import propagate_information
from ..metrics.social_metrics import classify_social_state
from models.external.provider import ModelProvider, make_provider


class SimulationEngine:
    def __init__(self) -> None:
        self.societies: dict[str, Society] = {}
        self.experiments: dict[str, dict] = {}
        self._lock = threading.Lock()

    # -- society lifecycle -------------------------------------------------
    def create_society(self, config: dict, society_id: Optional[str] = None, seed: Optional[int] = None) -> Society:
        sid = society_id or f"society_{uuid.uuid4().hex[:8]}"
        s = Society(society_id=sid, config=config, seed=seed if seed is not None else config.get("seed", 0))
        with self._lock:
            self.societies[sid] = s
        return s

    def get(self, society_id: str) -> Optional[Society]:
        return self.societies.get(society_id)

    def delete(self, society_id: str) -> bool:
        with self._lock:
            return self.societies.pop(society_id, None) is not None

    # -- stepping ----------------------------------------------------------
    def step(self, society_id: str, ticks: Optional[int] = None) -> dict:
        """Advance one society. Returns a change summary dict (or {} if missing)."""
        s = self.get(society_id)
        if s is None:
            return {}
        n = ticks or int(s.speed) or 1
        provider = make_provider(s.config)
        rng = s.rng or random.Random(s.seed)  # persistent deterministic RNG (§33)

        # Build the relationship network once, lazily.
        if not s._network:
            s._network = build_network(s.agents, s.config, rng)

        memory_decay = s.config.get("social", {}).get("memory_decay", 0.97)
        memory_size = s.config.get("social", {}).get("memory_size", 20)

        events_emitted = []

        for _ in range(n):
            s.clock.advance(1)
            # 1. 经济 + 资源恢复（§14, §15）— 税收按日征收（§12）
            collect_tax = (s.clock.tick % s.clock.ticks_per_day == 0)
            step_economy(s.agents, s.config, rng, s.production_multiplier, collect_tax)
            # 2. 生产恢复（§13）
            step_recovery(s, s.config)
            # 3. 事件生命周期衰减（§10, §11），返回本 tick 解决的事件
            resolved = decay_events(s.events, s.config)
            # 4. 事件检测（含恢复型事件，§30）
            new_events = step_events(s, s.config, rng, resolved)
            events_emitted.extend(new_events)
            # 5. 行为 → 事件（v0.4 §40–§44 反向闭环）
            if s.config.get("behavior", {}).get("enabled", True):
                behavior_events = step_behavior(s, s.config, rng)
            else:
                behavior_events = []
            events_emitted.extend(behavior_events)
            # 6. 信息传播（v0.4 §25–§39：Event → Information → Belief）
            #    information.enabled=false 时回退到 v0.3.1 核心事件学习（recent_events → politics）
            if s.config.get("information", {}).get("enabled", True):
                step_information(s, s.config, rng, list(new_events) + behavior_events)
            else:
                propagate_information(s, s.config, rng)
            # 7. 群体形成 + 生命周期（v0.4 §5–§12）
            if s.config.get("groups", {}).get("enabled", True):
                step_formation(s, s.config, rng)
                step_lifecycle(s, s.config, rng)
            # 8. 群体影响 + 身份更新（v0.4 §20–§21, §16, §53）
            if s.config.get("groups", {}).get("enabled", True):
                apply_group_influence(s, s.config)
            if s.config.get("identity", {}).get("enabled", True):
                step_identity(s, s.config)
            # 9. 政治更新（惯性 + 阻尼 + 个体化响应，§3–§9；使用 v0.4 identity）
            step_politics(s, s.config, rng, s._network)
            # 10. LLM 决策（默认关闭 §32）
            self._maybe_llm_decisions(s, provider, rng)
            # 11. 记忆衰减（§21）
            for a in s.agents:
                if a.alive and a.recent_events:
                    decay_memory(a, memory_decay, memory_size)

        metrics = s.metrics()
        s.metrics_history.append(metrics)
        if len(s.metrics_history) > 2000:
            s.metrics_history = s.metrics_history[-2000:]

        # 12. 社会状态诊断（v0.4 §54，每 step 一次，不每 tick）
        s.social_state = classify_social_state(s, metrics)

        # 9. 崩溃检测 + 边界集中检测（§26, §27）
        stab = s.config.get("stability", {})
        bc = boundary_concentration(s.agents, threshold=0.95)
        boundary_ratio = max(bc.values()) if bc else 0.0
        avg_var = (metrics["political_variance_x"] + metrics["political_variance_y"] + metrics["political_variance_z"]) / 3.0
        food = sum(a.resources.values.get("food", 0.0) for a in s.agents if a.alive) / max(metrics["population"], 1)
        resource_critical = food < s.config.get("economy", {}).get("food_critical", 20.0) * 0.5
        if s.collapse_detector is not None:
            s.collapse_detector.update(
                political_variance=avg_var,
                social_temperature=metrics["social_temperature"],
                resource_critical=resource_critical,
                boundary_ratio=boundary_ratio,
                boundary_warning_ratio=stab.get("boundary_warning_ratio", 0.30),
                boundary_critical_ratio=stab.get("boundary_critical_ratio", 0.60),
            )

        return {
            "society_id": society_id,
            "clock": s.clock.snapshot(),
            "metrics": metrics,
            "new_events": [e.as_dict() for e in events_emitted],
            "agent_count": len(s.agents),
            "collapse_flags": s.collapse_detector.flags() if s.collapse_detector else {},
        }

    def inject_event(self, society_id: str, event_type: str, severity: float = 0.8) -> Optional[dict]:
        """Inject an exogenous event (for tests / demonstrations, §34)."""
        from ..event.engine import _apply_effects, DURATION, TYPE_LABEL
        s = self.get(society_id)
        if s is None:
            return None
        rng = s.rng or random.Random(s.seed)
        event = s.events.make(
            s.clock.tick, event_type,
            severity=severity,
            description=f"注入事件：{TYPE_LABEL.get(event_type, event_type)}",
            duration=DURATION.get(event_type, 20),
            intensity=severity,
        )
        _apply_effects(s, event, [a for a in s.agents if a.alive], rng)
        return event.as_dict()

    def _maybe_llm_decisions(self, s: Society, provider: ModelProvider, rng: random.Random) -> None:
        """Let a small fraction of LLM-level agents make a structured decision."""
        model_cfg = s.config.get("model", {})
        if model_cfg.get("provider", "rule_based") == "rule_based":
            return
        # Sample a bounded number of high-intelligence agents per tick to bound cost.
        llm_agents = [a for a in s.agents if a.alive and a.ai_level >= 3]
        sample = llm_agents[:5]
        for a in sample:
            decision = provider.decide(a.snapshot(), f"Society {s.society_id} tick {s.clock.tick}")
            # Apply a validated, bounded effect (engine decides the consequences).
            action = decision.get("action")
            if action == "express_discontent":
                a.status["anger"] = min(1.0, a.status.get("anger", 0.0) + 0.1 * decision.get("confidence", 0.5))
            elif action == "seek_resources" and a.resources.is_broke():
                a.resources.add("money", 5.0)
            a.remember(f"llm:{action}")

    # -- experiments -------------------------------------------------------
    def create_experiment(self, spec: dict) -> str:
        """Create a batch of societies (multi-society experiment, §19)."""
        exp_id = f"experiment_{uuid.uuid4().hex[:8]}"
        base_cfg = spec.get("config", {})
        society_count = spec.get("society_count", 1)
        seed_start = spec.get("seed_start", 0)
        ids = []
        for i in range(society_count):
            sid = f"{exp_id}_society_{i:03d}"
            self.create_society(base_cfg, society_id=sid, seed=seed_start + i)
            ids.append(sid)
        self.experiments[exp_id] = {"id": exp_id, "society_ids": ids, "spec": spec}
        return exp_id

    def experiment(self, exp_id: str) -> Optional[dict]:
        return self.experiments.get(exp_id)
