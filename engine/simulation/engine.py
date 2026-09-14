"""Simulation Engine — the orchestrator (project §1, §28).

v0.4.5.1: Runtime State Machine Hotfix
  - Tick Progress Watchdog: clock must advance each step
  - SimulationStallDetector: detect N ticks with no state changes
  - Event Queue properly integrated into main loop
  - Tick order per v0.4.5.1 §28

Tick order:
  1. Advance Clock
  2. Complete / Advance current Actions
  3. Resource production / consumption
  4. Market / transfers
  5. Resource state update
  6. Information propagation
  7. Group / Identity update
  8. Evaluate Event Triggers
  9. Schedule / execute event queue
  10. Political Dynamics
  11. Region updates
  12. Diagnostics
"""

from __future__ import annotations

import random
import threading
import uuid
from typing import Optional

from ..society.society import Society
from ..agent.agent import Agent
from ..economy.economy import step_economy
from ..economy.security import update_resource_state
from ..economy.deprivation import update_relative_deprivation
from ..economy.region import update_regions
from ..politics.politics import step_politics
from ..event.engine import step_events
from ..event.dashboard import EventEcologyDashboard
from ..relationship.relationship import build_network
from ..dynamics.decay import decay_events, decay_memory
from ..economy.economy import step_production_recovery
from ..dynamics.stability import boundary_concentration
from ..group.formation import step_formation
from ..group.lifecycle import step_lifecycle
from ..group.influence import apply_group_influence
from ..group.resources import step_group_resources
from ..identity.update import step_identity
from ..information.propagation import step_information
from ..behavior.behavior import step_behavior
from ..relationship.information import propagate_information
from ..metrics.social_metrics import classify_social_state
from .stall import (
    SimulationStallDetector, TickProgressWatchdog, ZeroProgressDetector,
    build_stall_report, format_stall_report,
)
from models.external.provider import ModelProvider, make_provider


class SimulationEngine:
    def __init__(self) -> None:
        self.societies: dict[str, Society] = {}
        self.experiments: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create_society(self, config: dict, society_id: Optional[str] = None, seed: Optional[int] = None) -> Society:
        sid = society_id or f"society_{uuid.uuid4().hex[:8]}"
        s = Society(society_id=sid, config=config, seed=seed if seed is not None else config.get("seed", 0))
        stall_cfg = config.get("stall_detection", {})
        s._stall_detector = SimulationStallDetector(stall_threshold_ticks=stall_cfg.get("stall_threshold_ticks", 100))
        s._zero_progress = ZeroProgressDetector(stall_threshold_ticks=stall_cfg.get("agent_stall_threshold_ticks", 500))
        s._watchdog = TickProgressWatchdog()
        with self._lock:
            self.societies[sid] = s
        return s

    def get(self, society_id: str) -> Optional[Society]:
        return self.societies.get(society_id)

    def delete(self, society_id: str) -> bool:
        with self._lock:
            return self.societies.pop(society_id, None) is not None

    def step(self, society_id: str, ticks: Optional[int] = None) -> dict:
        s = self.get(society_id)
        if s is None:
            return {}
        n = ticks or int(s.speed) or 1
        provider = make_provider(s.config)
        rng = s.rng or random.Random(s.seed)

        if not s._network:
            s._network = build_network(s.agents, s.config, rng)

        memory_decay = s.config.get("social", {}).get("memory_decay", 0.97)
        memory_size = s.config.get("social", {}).get("memory_size", 20)
        events_emitted = []
        agent_state_changes = 0
        resource_changes = 0

        for _ in range(n):
            s.clock.advance(1)
            tick_after = s.clock.tick
            watchdog = getattr(s, "_watchdog", None)
            if watchdog:
                watchdog.check(tick_after)

            behavior_events = step_behavior(s, s.config, rng)
            events_emitted.extend(behavior_events)

            collect_tax = (s.clock.tick % s.clock.ticks_per_day == 0)
            dt_days = s.clock.dt_days
            flow = step_economy(s.agents, s.config, rng, s.production_multiplier, collect_tax, dt_days)
            step_production_recovery(s, s.config, dt_days)

            for a in s.agents:
                if a.alive:
                    update_resource_state(a, s.config)
            update_relative_deprivation(s.agents, s.config)

            if s.config.get("information", {}).get("enabled", True):
                # Pending events include externally injected events that were
                # created between ticks (inject_event is an operator action,
                # not an event-trigger wheel). Consume exactly once.
                pending = list(getattr(s, "_pending_information_events", []))
                s._pending_information_events = []
                pending.extend(behavior_events)
                if pending or getattr(s, "information_messages", None):
                    step_information(s, s.config, rng, pending)
            else:
                propagate_information(s, s.config, rng)

            if s.config.get("groups", {}).get("enabled", True):
                step_group_resources(s, s.config, rng)
                step_formation(s, s.config, rng)
                step_lifecycle(s, s.config, rng)
                apply_group_influence(s, s.config)
            if s.config.get("identity", {}).get("enabled", True):
                step_identity(s, s.config)

            resolved = decay_events(s.events, s.config)
            new_events = step_events(s, s.config, rng, resolved)
            events_emitted.extend(new_events)

            # Triggered/exogenous events are also facts that must enter the
            # information layer on the same simulation tick.
            if s.config.get("information", {}).get("enabled", True) and new_events:
                step_information(s, s.config, rng, new_events)

            step_politics(s, s.config, rng, s._network)
            update_regions(s, s.config)
            self._maybe_llm_decisions(s, provider, rng)

            for a in s.agents:
                if a.alive and a.recent_events:
                    decay_memory(a, memory_decay, memory_size)
            s.crisis_memory.decay()
            cm = s.crisis_manager
            if cm.food.is_crisis():
                s.crisis_memory.record_food_crisis(cm.food.severity)
            if cm.protest.is_crisis():
                s.crisis_memory.record_protest_crisis(cm.protest.severity)
            if cm.economic.is_crisis():
                s.crisis_memory.record_economic_crisis(cm.economic.severity)

            alive_agents = [a for a in s.agents if a.alive]
            if alive_agents:
                avg_food = sum(a.resources.values.get("food", 0) for a in alive_agents) / len(alive_agents)
                avg_anger = sum(a.status.get("anger", 0) for a in alive_agents) / len(alive_agents)
                s.oscillation_detector.update(avg_food)
                s.feedback_diagnostics.update(avg_food, avg_anger, 0, s.production_multiplier)

            tick_state_changes = 0
            for a in alive_agents:
                act_state = getattr(a, "activity", None)
                if act_state and act_state.last_state_change_tick == tick_after:
                    tick_state_changes += 1
            agent_state_changes += tick_state_changes
            stall_detector = getattr(s, "_stall_detector", None)
            if stall_detector:
                stall_detector.update(
                    agent_state_changes=tick_state_changes,
                    events_created=len(new_events) + len(behavior_events),
                    resource_changes=1 if flow else 0,
                )

        metrics = s.metrics()
        s.metrics_history.append(metrics)
        if len(s.metrics_history) > 2000:
            s.metrics_history = s.metrics_history[-2000:]
        s.social_state = classify_social_state(s, metrics)

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

        result = {
            "society_id": society_id,
            "clock": s.clock.snapshot(),
            "metrics": metrics,
            "new_events": [e.as_dict() for e in events_emitted],
            "agent_count": len(s.agents),
            "agent_state_changes": agent_state_changes,
            "collapse_flags": s.collapse_detector.flags() if s.collapse_detector else {},
        }
        stall_detector = getattr(s, "_stall_detector", None)
        if stall_detector and stall_detector.is_stalled:
            report = build_stall_report(s, s.clock.tick)
            result["stall_warning"] = format_stall_report(report)
        return result

    def inject_event(self, society_id: str, event_type: str, severity: float = 0.8) -> Optional[dict]:
        """Inject an exogenous event and feed it into the information layer on the next tick."""
        from ..event.engine import _apply_effects, DURATION, TYPE_LABEL
        from ..event.event import SOURCE_TYPE, EVENT_SOURCE_MAP, EVENT_SCOPE
        s = self.get(society_id)
        if s is None:
            return None
        rng = s.rng or random.Random(s.seed)
        source_type = EVENT_SOURCE_MAP.get(event_type, SOURCE_TYPE.EXOGENOUS)
        event = s.events.make(
            s.clock.tick, event_type,
            severity=severity,
            description=f"注入事件：{TYPE_LABEL.get(event_type, event_type)}",
            duration=DURATION.get(event_type, 20),
            intensity=severity,
            source_type=source_type,
            scope=EVENT_SCOPE.SOCIETY,
        )
        _apply_effects(s, event, [a for a in s.agents if a.alive], rng)
        if not hasattr(s, "_pending_information_events"):
            s._pending_information_events = []
        s._pending_information_events.append(event)
        return event.as_dict()

    def get_event_ecology(self, society_id: str) -> Optional[dict]:
        s = self.get(society_id)
        if s is None:
            return None
        dashboard = EventEcologyDashboard()
        stats = dashboard.compute(s.events, s.clock.tick)
        return {
            "report": dashboard.format_report(stats),
            "causality_scorecard": dashboard.format_causality_scorecard(s.events),
            "stats": {
                "total_events": stats.total_events,
                "endogenous_count": stats.endogenous_count,
                "exogenous_count": stats.exogenous_count,
                "recovery_count": stats.recovery_count,
                "uncaused_count": stats.uncaused_count,
                "loop_count": stats.loop_count,
                "strong_loop_count": stats.strong_loop_count,
                "event_diversity": round(stats.event_diversity, 4),
                "endogenous_ratio": round(stats.endogenous_ratio, 4),
                "exogenous_ratio": round(stats.exogenous_ratio, 4),
                "recovery_ratio": round(stats.recovery_ratio, 4),
            },
        }

    def get_stall_diagnostics(self, society_id: str) -> Optional[dict]:
        s = self.get(society_id)
        if s is None:
            return None
        report = build_stall_report(s, s.clock.tick)
        stall_detector = getattr(s, "_stall_detector", None)
        zero_progress = getattr(s, "_zero_progress", None)
        stalled_agents = []
        if zero_progress:
            stalled_info = zero_progress.detect_stalled(s.agents, s.clock.tick)
            stalled_agents = [
                {"agent_id": info.agent_id, "current_action": info.current_action,
                 "action_state": info.action_state, "hours_remaining": info.hours_remaining,
                 "stalled_ticks": info.stalled_ticks}
                for info in stalled_info[:10]
            ]
        return {
            "report": format_stall_report(report),
            "is_stalled": stall_detector.is_stalled if stall_detector else False,
            "idle_ticks": stall_detector.idle_ticks if stall_detector else 0,
            "stalled_agents": stalled_agents,
        }

    def _maybe_llm_decisions(self, s: Society, provider: ModelProvider, rng: random.Random) -> None:
        model_cfg = s.config.get("model", {})
        if model_cfg.get("provider", "rule_based") == "rule_based":
            return
        llm_agents = [a for a in s.agents if a.alive and a.ai_level >= 3]
        sample = llm_agents[:5]
        for a in sample:
            decision = provider.decide(a.snapshot(), f"Society {s.society_id} tick {s.clock.tick}")
            action = decision.get("action")
            if action == "express_discontent":
                a.status["anger"] = min(1.0, a.status.get("anger", 0.0) + 0.1 * decision.get("confidence", 0.5))
            elif action == "seek_resources" and a.resources.is_broke():
                a.resources.add("money", 5.0)
            a.remember(f"llm:{action}")

    def create_experiment(self, spec: dict) -> str:
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
