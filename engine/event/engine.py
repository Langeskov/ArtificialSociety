"""Event Engine — v0.4.5.2: Crisis State Synchronization.

Key changes from v0.4.5.1:
  - CrisisManager is Single Source of Truth for crisis state
  - Event Engine consumes CrisisTransition (not compares states itself)
  - Recovery notifications at RECOVERING start (not just COOLDOWN)
  - Resolved notifications at RECOVERING→COOLDOWN
  - Per-society trigger registry (no global singleton state)
  - Triggers are stateless scoring functions
"""

from __future__ import annotations

import random
from typing import Optional, Sequence

from ..agent.agent import Agent
from ..metrics.metrics import compute_social_temperature
from .event import Event, EventChain, SOURCE_TYPE, EVENT_SCOPE, EVENT_SOURCE_MAP
from .triggers import (
    EventTrigger, TriggerEvidence, create_trigger_registry,
)
from .queue import EventQueue, CausalCooldown
from ..crisis.tracker import CrisisTransition


# Recovery notification event types
RECOVERY_EVENT_TYPES = {"recovery", "food_stabilization", "economic_recovery",
                        "resource_stabilization", "protest_resolved",
                        "economic_crisis_resolved", "food_crisis_resolved",
                        "economic_recovery_started", "food_stabilization_started",
                        "recovery_started"}

# Event type → lifecycle duration (ticks)
DURATION: dict[str, int] = {
    "food_shortage": 40,
    "economic_crisis": 60,
    "protest": 20,
    "political_movement": 30,
    "government_response": 15,
    "natural_disaster": 30,
    "war": 60,
    "conflict": 40,
    "scandal": 15,
    "resource_boom": 30,
    "technology_breakthrough": 30,
    "alliance": 40,
    "market_panic": 20,
    "unemployment": 40,
    "migration": 40,
    "election": 15,
    "leadership_change": 20,
    "reform": 25,
    "recovery": 20,
    "food_stabilization": 20,
    "economic_recovery": 25,
    "resource_stabilization": 20,
    "group_split": 25,
    "pandemic": 50,
    "external_shock": 30,
    # v0.4.5.2: Recovery lifecycle events
    "economic_recovery_started": 15,
    "food_stabilization_started": 15,
    "recovery_started": 15,
    "economic_crisis_resolved": 10,
    "food_crisis_resolved": 10,
    "protest_resolved": 10,
}

TYPE_LABEL = {
    "natural_disaster": "自然灾害",
    "technology_breakthrough": "技术突破",
    "resource_boom": "资源繁荣",
    "scandal": "丑闻",
    "protest": "抗议",
    "economic_crisis": "经济危机",
    "food_shortage": "粮食短缺",
    "political_movement": "政治运动",
    "government_response": "政府应对",
    "conflict": "冲突",
    "war": "战争",
    "alliance": "结盟",
    "market_panic": "市场恐慌",
    "unemployment": "失业上升",
    "migration": "迁移",
    "election": "选举",
    "leadership_change": "领导更替",
    "reform": "改革",
    "recovery": "恢复",
    "food_stabilization": "粮食企稳",
    "economic_recovery": "经济恢复",
    "resource_stabilization": "资源企稳",
    "group_split": "群体分裂",
    "pandemic": "瘟疫",
    "external_shock": "外部冲击",
    # v0.4.5.2
    "economic_recovery_started": "经济恢复开始",
    "food_stabilization_started": "粮食企稳开始",
    "recovery_started": "恢复开始",
    "economic_crisis_resolved": "经济危机解决",
    "food_crisis_resolved": "粮食危机解决",
    "protest_resolved": "抗议平息",
}


def _has_active(chain: EventChain, event_type: str) -> bool:
    return any(e.type == event_type and e.is_active for e in chain.events)


def _compute_trigger_context(society, agents: Sequence[Agent], cfg: dict) -> dict:
    """Compute context variables needed by triggers."""
    if not agents:
        return {}

    tick = society.clock.tick
    ticks_per_day = cfg.get("ticks_per_day", 100)

    production_disruption = getattr(society, "production_disruption", 0.0)
    production_gap = min(1.0, max(0.0, production_disruption))

    unemployed = sum(1 for a in agents if getattr(a, 'sector', '') == 'unemployed')
    unemployment = unemployed / len(agents)

    broke = sum(1 for a in agents if a.resources.is_broke()) / len(agents)
    starving = sum(1 for a in agents if a.resources.is_starving()) / len(agents)

    avg_food = sum(a.resources.values.get("food", 0) for a in agents) / len(agents)
    food_critical = cfg.get("economy", {}).get("food_critical", 20.0)

    information_spread = 0.3
    if hasattr(society, 'information_messages') and society.information_messages:
        recent_count = 0
        for m in society.information_messages:
            msg_tick = getattr(m, 'created_tick', None) or (m.get("tick", 0) if isinstance(m, dict) else 0)
            if tick - msg_tick < ticks_per_day * 5:
                recent_count += 1
        information_spread = min(1.0, recent_count / max(len(agents), 1))

    crisis_memory = getattr(society, "crisis_memory", None)
    persistent_grievance = crisis_memory.protest_memory if crisis_memory else 0.0
    information_cascade = min(1.0, information_spread * 1.5)

    temperature = compute_social_temperature(agents, society.events, cfg)
    political_opportunity = min(1.0, temperature * 1.2)
    resource_competition = min(1.0, (broke + starving) * 0.5)
    price_pressure = min(1.0, production_gap * 0.5 + unemployment * 0.3)

    avg_anger = sum(a.status.get("anger", 0.0) for a in agents) / len(agents)
    public_trust = max(0.0, 1.0 - avg_anger * 2)

    violation_detected = 0.0
    for a in agents:
        if (a.status.get("corruption", 0.0) > 0.5
                and a.resources.values.get("influence", 0) > 10):
            violation_detected = min(1.0, violation_detected + 0.01)

    regional_inequality = 0.0
    if hasattr(society, 'regions') and society.regions:
        region_stats = []
        for r in society.regions.as_list():
            if isinstance(r, dict):
                region_stats.append(r.get("food", 1.0))
        if region_stats:
            regional_inequality = max(region_stats) - min(region_stats)

    food_production_gap = min(1.0, max(0.0, starving - production_gap))
    safety_concern = min(1.0, avg_anger + production_disruption * 0.5)

    return {
        "production_gap": production_gap,
        "unemployment": unemployment,
        "broke": broke,
        "starving": starving,
        "avg_food": avg_food,
        "food_critical": food_critical,
        "information_spread": information_spread,
        "persistent_grievance": persistent_grievance,
        "information_cascade": information_cascade,
        "political_opportunity": political_opportunity,
        "resource_competition": resource_competition,
        "price_pressure": price_pressure,
        "public_trust": public_trust,
        "violation_detected": violation_detected,
        "information_exposure": information_spread,
        "regional_inequality": regional_inequality,
        "food_production_gap": food_production_gap,
        "safety_concern": safety_concern,
        "temperature": temperature,
        "ticks_per_day": ticks_per_day,
    }


def _apply_effects(society, event: Event, agents: Sequence[Agent], rng: random.Random) -> None:
    """Event effects on society."""
    et = event.type
    sev = max(0.2, event.severity)
    if et == "natural_disaster":
        society.production_disruption = min(0.5, getattr(society, "production_disruption", 0.0) + 0.2 * sev)
        for a in agents:
            if a.alive:
                a.resources.add("food", -a.resources.values.get("food", 0.0) * 0.85 * sev)
    elif et == "economic_crisis":
        society.production_disruption = min(0.4, getattr(society, "production_disruption", 0.0) + 0.15 * sev)
        for a in agents:
            if a.alive:
                a.resources.add("money", -a.resources.values.get("money", 0.0) * 0.2 * sev)
    elif et == "war":
        society.production_disruption = min(0.5, getattr(society, "production_disruption", 0.0) + 0.25 * sev)
        for a in agents:
            if a.alive:
                a.resources.add("food", -a.resources.values.get("food", 0.0) * 0.2 * sev)
    elif et == "conflict":
        society.production_disruption = min(0.3, getattr(society, "production_disruption", 0.0) + 0.1 * sev)
    elif et == "resource_boom":
        for a in agents:
            if a.alive:
                a.resources.add("money", a.resources.values.get("money", 0.0) * 0.15 * sev)
    elif et == "technology_breakthrough":
        society.production_disruption = max(-0.2, getattr(society, "production_disruption", 0.0) - 0.1 * sev)


def _emit_crisis_transition_events(
    society, chain: EventChain, transitions: dict[str, CrisisTransition],
    tick: int, context: dict,
) -> list[Event]:
    """v0.4.5.3: Convert CrisisTransitions into Event notifications.

    All notifications carry crisis_instance_id for causal chain integrity.
    Recovery notification at RECOVERING start, resolved notification at COOLDOWN.
    """
    new_events = []

    RECOVERY_STARTED_MAP = {
        "economic": "economic_recovery_started",
        "food": "food_stabilization_started",
        "protest": "recovery_started",
    }
    RESOLVED_MAP = {
        "economic": "economic_crisis_resolved",
        "food": "food_crisis_resolved",
        "protest": "protest_resolved",
    }
    CRISIS_EVENT_MAP = {
        "economic": "economic_crisis",
        "food": "food_shortage",
        "protest": "protest",
    }

    def find_crisis_event(ct: str, iid: str):
        """v0.4.5.3: Find crisis event by instance_id (not is_active)."""
        type_name = CRISIS_EVENT_MAP.get(ct, "")
        for e in reversed(chain.events):
            if e.type == type_name and e.effects.get("crisis_instance_id", "") == iid:
                return e
        for e in reversed(chain.events):
            if e.type == type_name:
                return e
        return None

    for crisis_type, trans in transitions.items():
        if not trans.has_transition:
            continue

        iid = trans.crisis_instance_id
        orig_crisis = find_crisis_event(crisis_type, iid)

        if trans.entered_recovering:
            recovery_type = RECOVERY_STARTED_MAP.get(crisis_type, "recovery_started")
            recovery_ev = chain.make(
                tick, recovery_type,
                severity=trans.severity * 0.5,
                description=f"{TYPE_LABEL.get(CRISIS_EVENT_MAP.get(crisis_type, ''), crisis_type)}恢复开始",
                cause_event_id=orig_crisis.event_id if orig_crisis else None,
                cause_mechanism="metric_improvement",
                evidence={
                    "crisis_instance_id": iid,
                    "metric_value": round(trans.metric_value, 4),
                    "peak_metric": round(trans.peak_metric, 4),
                    "baseline_metric": round(trans.baseline_metric, 4),
                    "recovery_progress": round(trans.recovery_progress, 4),
                },
                source_type=SOURCE_TYPE.RECOVERY,
                trigger_score=trans.metric_value,
                causal_confidence=0.9,
            )
            new_events.append(recovery_ev)

        if trans.resolved:
            resolved_type = RESOLVED_MAP.get(crisis_type, "protest_resolved")
            recovery_ev = next(
                (e for e in reversed(chain.events)
                 if e.type in (RECOVERY_STARTED_MAP.get(crisis_type, ""), "recovery")
                 and e.effects.get("crisis_instance_id", "") == iid),
                None,
            )
            resolved_ev = chain.make(
                tick, resolved_type,
                severity=0.3,
                description=f"{TYPE_LABEL.get(CRISIS_EVENT_MAP.get(crisis_type, ''), crisis_type)}危机解决",
                cause_event_id=recovery_ev.event_id if recovery_ev else (orig_crisis.event_id if orig_crisis else None),
                cause_mechanism="crisis_resolution",
                evidence={
                    "crisis_instance_id": iid,
                    "peak_severity": round(trans.peak_metric, 4),
                    "recovery_progress": 1.0,
                    "crisis_start_tick": trans.crisis_start_tick,
                    "resolution_tick": trans.resolution_tick,
                },
                source_type=SOURCE_TYPE.RECOVERY,
            )
            new_events.append(resolved_ev)

    return new_events



def _evaluate_endogenous_triggers(society, agents: Sequence[Agent], cfg: dict,
                                   context: dict, chain: EventChain, tick: int,
                                   triggers: dict[str, EventTrigger]) -> list[tuple[EventTrigger, float, TriggerEvidence]]:
    """Evaluate endogenous triggers. Returns (trigger, score, evidence) tuples.

    v0.4.5.2: Triggers are stateless — just scoring. No should_trigger().
    """
    results = []
    cm = getattr(society, "crisis_manager", None)

    for event_type, trigger in triggers.items():
        # Skip if already active
        if _has_active(chain, event_type):
            continue

        # For crisis types managed by CrisisManager, don't re-trigger if crisis is active
        if cm and event_type in ("economic_crisis", "food_shortage", "protest"):
            tracker = getattr(cm, {"economic_crisis": "economic", "food_shortage": "food", "protest": "protest"}[event_type], None)
            if tracker and tracker.state.value in ("ACTIVE", "SEVERE", "RECOVERING", "WARNING"):
                continue

        score, evidence = trigger.score(society, context)

        # For non-crisis triggers, use a simple threshold check
        if score > trigger.trigger_threshold:
            results.append((trigger, score, evidence))

    return results


def _evaluate_exogenous_events(society, agents: Sequence[Agent], cfg: dict,
                                rng: random.Random, chain: EventChain, tick: int,
                                ticks_per_day: int) -> list[Event]:
    """Exogenous events use daily probability."""
    ev = cfg.get("events", {})
    exo_cfg = ev.get("exogenous", {})

    if not exo_cfg.get("enabled", True):
        return []

    new_events = []
    if tick % ticks_per_day != 0:
        return []

    for event_type in ["natural_disaster", "pandemic", "external_shock"]:
        daily_prob = exo_cfg.get(event_type, {}).get("daily_probability", 0.001)
        if rng.random() < daily_prob:
            regions = cfg.get("regions", {}).get("list", ["A", "B", "C"])
            region = rng.choice(regions) if regions else None
            severity = 0.3 + rng.random() * 0.5
            event = chain.make(
                tick, event_type,
                severity=severity,
                description=f"外生冲击：{TYPE_LABEL.get(event_type, event_type)}",
                duration=DURATION.get(event_type, 30),
                source_type=SOURCE_TYPE.EXOGENOUS,
                scope=EVENT_SCOPE.REGIONAL,
                region=region,
            )
            new_events.append(event)
            _apply_effects(society, event, agents, rng)

    return new_events


def step_events(society, cfg: dict, rng: random.Random, resolved: Optional[list] = None) -> list:
    """v0.4.5.2: Event detection using CrisisManager as Single Source of Truth.

    Tick order (§15):
    1. Compute trigger context
    2. CrisisManager.update_all() → transitions
    3. Convert transitions → recovery/resolved notifications
    4. Evaluate new endogenous event candidates (non-crisis)
    5. Evaluate exogenous events
    6. Government response
    7. Event budget
    """
    ev = cfg.get("events", {})
    agents = [a for a in society.agents if a.alive]
    if not agents:
        return []

    tick = society.clock.tick
    ticks_per_day = cfg.get("ticks_per_day", 100)
    chain: EventChain = society.events
    new_events: list[Event] = []

    # Ensure per-society trigger registry
    if not hasattr(society, '_trigger_registry'):
        society._trigger_registry = create_trigger_registry()
    triggers: dict[str, EventTrigger] = society._trigger_registry

    # Ensure event queue and causal cooldown
    if not hasattr(society, '_event_queue'):
        min_delay = ev.get("causal_delay", {}).get("min_ticks", 5)
        max_depth = ev.get("max_causal_depth_per_tick", 2)
        society._event_queue = EventQueue(min_causal_delay=min_delay, max_causal_depth=max_depth)
    if not hasattr(society, '_causal_cooldown'):
        society._causal_cooldown = CausalCooldown(cooldown_ticks=50)

    queue: EventQueue = society._event_queue
    causal_cd: CausalCooldown = society._causal_cooldown

    if tick % 100 == 0:
        queue.cleanup_causal_memory(tick)
        causal_cd.cleanup(tick)

    # Process deferred events from queue
    ready_events = queue.dequeue(tick)
    for event_data in ready_events:
        event_type = event_data.get("type", "unknown")
        event = chain.make(
            tick, event_type,
            severity=event_data.get("severity", 0.5),
            description=event_data.get("description", TYPE_LABEL.get(event_type, event_type)),
            duration=event_data.get("duration", DURATION.get(event_type, 20)),
            source_type=event_data.get("source_type", SOURCE_TYPE.ENDOGENOUS),
            cause_event_id=event_data.get("cause_event_id"),
            cause_mechanism=event_data.get("cause_mechanism", ""),
            evidence=event_data.get("evidence", {}),
            trigger_score=event_data.get("trigger_score", 0.0),
            causal_confidence=event_data.get("causal_confidence", 0.0),
            scope=event_data.get("scope", EVENT_SCOPE.REGIONAL),
            region=event_data.get("region"),
        )
        new_events.append(event)
        _apply_effects(society, event, agents, rng)

    # Compute trigger context
    context = _compute_trigger_context(society, agents, cfg)

    # v0.4.5.2 §15: CrisisManager.update_all() — unified crisis state update
    cm = getattr(society, "crisis_manager", None)
    if cm is not None:
        starving_ratio = context.get("starving", 0.0)
        economic_pressure = _economic_pressure(agents, context)
        protest_ratio = _protest_ratio(agents)

        transitions = cm.update_all(
            hunger_ratio=starving_ratio,
            protest_ratio=protest_ratio,
            economic_pressure=economic_pressure,
            tick=tick,
            ticks_per_day=ticks_per_day,
        )

        # v0.4.5.2 §5/§7: Convert transitions → event notifications
        crisis_events = _emit_crisis_transition_events(society, chain, transitions, tick, context)
        new_events.extend(crisis_events)

        # Apply effects for new ACTIVE/SEVERE crises
        for crisis_type, trans in transitions.items():
            if trans.entered_active or trans.entered_severe:
                crisis_event_type = {"economic": "economic_crisis", "food": "food_shortage", "protest": "protest"}[crisis_type]
                if not _has_active(chain, crisis_event_type):
                    severity = max(0.2, trans.metric_value)
                    crisis_ev = chain.make(
                        tick, crisis_event_type,
                        severity=severity,
                        description=TYPE_LABEL.get(crisis_event_type, crisis_event_type),
                        duration=DURATION.get(crisis_event_type, 40),
                        trigger_score=trans.metric_value,
                        causal_confidence=0.9,
                        evidence={"crisis_instance_id": trans.crisis_instance_id, "metric_value": round(trans.metric_value, 4)},
                        cause_mechanism="crisis_state_machine",
                    )
                    new_events.append(crisis_ev)
                    _apply_effects(society, crisis_ev, agents, rng)

    # Evaluate non-crisis endogenous triggers
    endogenous_results = _evaluate_endogenous_triggers(society, agents, cfg, context, chain, tick, triggers)
    for trigger, score, evidence in endogenous_results:
        if trigger.event_type in ("economic_crisis", "food_shortage", "protest"):
            continue  # Already handled by CrisisManager

        severity = max(0.2, min(1.0, score + rng.gauss(0, 0.05)))
        event = chain.make(
            tick, trigger.event_type,
            severity=severity,
            description=TYPE_LABEL.get(trigger.event_type, trigger.event_type),
            duration=DURATION.get(trigger.event_type, 20),
            trigger_score=score,
            causal_confidence=evidence.confidence,
            evidence=evidence.indicators,
            cause_mechanism=f"trigger_{trigger.event_type}",
            scope=EVENT_SCOPE.GROUP if trigger.event_type in ("conflict", "group_split") else EVENT_SCOPE.REGIONAL,
        )
        new_events.append(event)
        _apply_effects(society, event, agents, rng)

    # Exogenous events
    exo_events = _evaluate_exogenous_events(society, agents, cfg, rng, chain, tick, ticks_per_day)
    new_events.extend(exo_events)

    # Government response (not for recovery events)
    for e in new_events:
        if e.source_type == SOURCE_TYPE.RECOVERY:
            continue
        if e.type in ("protest", "economic_crisis", "food_shortage"):
            if rng.random() < 0.6:
                chain.make(
                    tick + rng.randint(1, 5), "government_response",
                    severity=e.severity * 0.7,
                    description=f"政府针对「{TYPE_LABEL.get(e.type, e.type)}」作出应对",
                    cause_event_id=e.event_id,
                    cause_mechanism="government_reaction",
                    duration=DURATION["government_response"],
                    intensity=e.severity * 0.7,
                    source_type=SOURCE_TYPE.ENDOGENOUS,
                    evidence={"trigger_event_severity": e.severity},
                )

    # Event budget
    daily_budget = ev.get("daily_major_event_budget", 2)
    endogenous_today = [e for e in new_events if e.source_type == SOURCE_TYPE.ENDOGENOUS and e.severity > 0.5]
    if len(endogenous_today) > daily_budget:
        endogenous_today.sort(key=lambda e: e.trigger_score, reverse=True)
        for excess in endogenous_today[daily_budget:]:
            if excess in chain.events:
                chain.events.remove(excess)
            queue.enqueue(
                excess.as_dict(),
                tick=tick + ticks_per_day,
                source_type=SOURCE_TYPE.ENDOGENOUS,
                cause_event_type=excess.type,
            )

    return new_events


def _economic_pressure(agents: Sequence[Agent], context: dict) -> float:
    """Compute economic pressure from context."""
    return min(1.0, (
        0.30 * context.get("production_gap", 0)
        + 0.25 * context.get("unemployment", 0)
        + 0.20 * context.get("price_pressure", 0)
        + 0.15 * context.get("broke", 0)
        + 0.10 * context.get("starving", 0)
    ))


def _protest_ratio(agents: Sequence[Agent]) -> float:
    """Compute protest ratio from agent anger."""
    if not agents:
        return 0.0
    angry = sum(1 for a in agents if a.status.get("anger", 0.0) > 0.3)
    return angry / len(agents)
