"""Event Engine — v0.4.5: Event Ecology & Causal Dynamics.

Major changes from v0.4.4:
  - All endogenous events use Trigger Registry with causal evidence
  - Exogenous events use daily probability (not per-tick)
  - Events carry source_type (ENDOGENOUS/EXOGENOUS/RECOVERY)
  - Event Queue with causal delay prevents immediate recursion
  - Causal memory prevents A→B→A loops
  - Recovery events are state transition notifications, not new shocks
  - No random event roulette (natural_disaster/technology_breakthrough/resource_boom/scandal)
"""

from __future__ import annotations

import random
from typing import Optional, Sequence

from ..agent.agent import Agent
from ..metrics.metrics import compute_social_temperature
from .event import Event, EventChain, SOURCE_TYPE, EVENT_SCOPE, EVENT_SOURCE_MAP
from .triggers import (
    EventTrigger, TriggerEvidence, get_trigger, get_endogenous_triggers,
)
from .queue import EventQueue, CausalCooldown


# Recovery notifications — must not push political coordinates or re-trigger crises
RECOVERY_EVENT_TYPES = {"recovery", "food_stabilization", "economic_recovery", "resource_stabilization"}

# 事件类型 → 生命周期时长（tick）
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
}


def _temp_modifier(temperature: float) -> float:
    """社会温度映射为事件概率倍率：低温 → 0，高温 → 放大。"""
    if temperature < 0.30:
        return 0.0
    if temperature > 0.90:
        return 3.0
    return (temperature - 0.30) / 0.60 * 3.0


def _has_active(chain: EventChain, event_type: str) -> bool:
    return any(e.type == event_type and e.is_active for e in chain.events)


def _has_recent(chain: EventChain, event_type: str, tick: int, window: int) -> bool:
    """Whether a notification of this type was emitted recently."""
    return any(e.type == event_type and tick - e.tick <= window for e in chain.events)


def _compute_trigger_context(society, agents: Sequence[Agent], cfg: dict) -> dict:
    """Compute context variables needed by multiple triggers.

    This avoids recomputing expensive metrics for each trigger separately.
    """
    if not agents:
        return {}

    tick = society.clock.tick
    ticks_per_day = cfg.get("ticks_per_day", 100)

    # Production gap: difference between production capacity and consumption
    production_disruption = getattr(society, "production_disruption", 0.0)
    production_gap = min(1.0, max(0.0, production_disruption))

    # Unemployment
    unemployed = sum(1 for a in agents if getattr(a, 'sector', '') == 'unemployed')
    unemployment = unemployed / len(agents)

    # Broke / starving
    broke = sum(1 for a in agents if a.resources.is_broke()) / len(agents)
    starving = sum(1 for a in agents if a.resources.is_starving()) / len(agents)

    # Average food stock
    avg_food = sum(a.resources.values.get("food", 0) for a in agents) / len(agents)
    food_critical = cfg.get("economy", {}).get("food_critical", 20.0)

    # Information spread (from information system)
    information_spread = 0.3
    if hasattr(society, 'information_messages') and society.information_messages:
        recent_msgs = [m for m in society.information_messages
                       if tick - m.get("tick", 0) < ticks_per_day * 5]
        information_spread = min(1.0, len(recent_msgs) / max(len(agents), 1))

    # Persistent grievance: from crisis memory
    crisis_memory = getattr(society, "crisis_memory", None)
    persistent_grievance = crisis_memory.protest_memory if crisis_memory else 0.0

    # Information cascade
    information_cascade = min(1.0, information_spread * 1.5)

    # Political opportunity: based on social temperature
    temperature = compute_social_temperature(agents, society.events, cfg)
    political_opportunity = min(1.0, temperature * 1.2)

    # Resource competition (from regional economics)
    resource_competition = min(1.0, (broke + starving) * 0.5)

    # Price pressure
    price_pressure = min(1.0, production_gap * 0.5 + unemployment * 0.3)

    # Public trust (inverse of anger)
    avg_anger = sum(a.status.get("anger", 0.0) for a in agents) / len(agents)
    public_trust = max(0.0, 1.0 - avg_anger * 2)

    # Violation detection (for scandal): agents with suspicious behavior
    violation_detected = 0.0
    for a in agents:
        # High corruption or low integrity + high influence
        if (a.status.get("corruption", 0.0) > 0.5
                and a.resources.values.get("influence", 0) > 10):
            violation_detected = min(1.0, violation_detected + 0.01)
    information_exposure = information_spread

    # Regional inequality
    regional_inequality = 0.0
    if hasattr(society, 'regions') and society.regions:
        region_stats = []
        for r in society.regions.as_list():
            if isinstance(r, dict):
                region_stats.append(r.get("food", 1.0))
        if region_stats:
            regional_inequality = max(region_stats) - min(region_stats)

    # Food production gap
    food_production_gap = min(1.0, max(0.0, starving - production_gap))

    # Safety concern
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
        "information_exposure": information_exposure,
        "regional_inequality": regional_inequality,
        "food_production_gap": food_production_gap,
        "safety_concern": safety_concern,
        "temperature": temperature,
        "ticks_per_day": ticks_per_day,
    }


def _apply_effects(society, event: Event, agents: Sequence[Agent], rng: random.Random) -> None:
    """事件的实际后果（v0.4.2 §19: 临时干扰而非永久 ratchet）。

    v0.4.5: severity is now computed from trigger strength, not random.
    """
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


def _evaluate_endogenous_triggers(society, agents: Sequence[Agent], cfg: dict,
                                   context: dict, chain: EventChain, tick: int) -> list[tuple[EventTrigger, float, TriggerEvidence]]:
    """Evaluate all endogenous triggers and return (trigger, score, evidence) tuples."""
    results = []
    triggers = get_endogenous_triggers()

    for event_type, trigger in triggers.items():
        # Skip if already active
        if _has_active(chain, event_type):
            continue

        # Compute score
        score, evidence = trigger.score(society, context)

        # Check if should trigger (persistence + hysteresis + cooldown)
        if trigger.should_trigger(score, tick):
            results.append((trigger, score, evidence))

    return results


def _evaluate_exogenous_events(society, agents: Sequence[Agent], cfg: dict,
                                rng: random.Random, chain: EventChain, tick: int,
                                ticks_per_day: int) -> list[Event]:
    """v0.4.5 §13-§14: Exogenous events use daily probability, not per-tick."""
    ev = cfg.get("events", {})
    exo_cfg = ev.get("exogenous", {})

    if not exo_cfg.get("enabled", True):
        return []

    new_events = []

    # Only check once per simulated day (at day boundary)
    if tick % ticks_per_day != 0:
        return []

    for event_type in ["natural_disaster", "pandemic", "external_shock"]:
        daily_prob = exo_cfg.get(event_type, {}).get("daily_probability", 0.001)
        if rng.random() < daily_prob:
            # §15: Assign region scope
            regions = cfg.get("regions", {}).get("list", ["A", "B", "C"])
            region = rng.choice(regions) if regions else None

            severity = 0.3 + rng.random() * 0.5  # Exogenous severity is partially random

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
    """v0.4.5: Detect and produce new events using causal triggers.

    Returns new events created this tick.
    """
    ev = cfg.get("events", {})
    agents = [a for a in society.agents if a.alive]
    if not agents:
        return []

    tick = society.clock.tick
    ticks_per_day = cfg.get("ticks_per_day", 100)
    chain: EventChain = society.events
    new_events: list[Event] = []

    # Ensure society has event queue and causal cooldown
    if not hasattr(society, '_event_queue'):
        min_delay = ev.get("causal_delay", {}).get("min_ticks", 5)
        max_depth = ev.get("max_causal_depth_per_tick", 2)
        society._event_queue = EventQueue(min_causal_delay=min_delay, max_causal_depth=max_depth)
    if not hasattr(society, '_causal_cooldown'):
        society._causal_cooldown = CausalCooldown(cooldown_ticks=50)

    queue: EventQueue = society._event_queue
    causal_cd: CausalCooldown = society._causal_cooldown

    # Clean up old causal memory periodically
    if tick % 100 == 0:
        queue.cleanup_causal_memory(tick)
        causal_cd.cleanup(tick)

    # --- Process deferred events from queue ---
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

    # --- Compute trigger context (once, shared by all triggers) ---
    context = _compute_trigger_context(society, agents, cfg)

    # --- Handle crisis state machine for food (existing logic with v0.4.5 structure) ---
    cm = getattr(society, "crisis_manager", None)
    if cm is not None:
        # Food crisis state machine
        starving_ratio = context.get("starving", 0.0)
        previous_food_state = cm.food.state
        cm.food.update(starving_ratio, tick, ticks_per_day)

        # Recovery notification: only when tracker reaches COOLDOWN
        if (previous_food_state.name == "RECOVERING"
                and cm.food.state.name == "COOLDOWN"
                and not _has_recent(chain, "food_stabilization", tick, int(2 * ticks_per_day))):
            cause = next((e for e in reversed(chain.events)
                          if e.type in ("food_shortage", "economic_crisis")), None)
            new_events.append(chain.make(
                tick, "food_stabilization", severity=0.4,
                description="粮食供给重新企稳",
                cause_event_id=cause.event_id if cause else None,
                cause_mechanism="crisis_state_machine_recovery",
                duration=DURATION["food_stabilization"],
                source_type=SOURCE_TYPE.RECOVERY,
                intensity=0.4))

        # Food shortage event: only when crisis state becomes ACTIVE for first tick
        if cm.food.state.value == "ACTIVE" and cm.food.duration_ticks == 1:
            food_trigger = get_trigger("food_shortage")
            score, evidence = food_trigger.score(society, context) if food_trigger else (starving_ratio, TriggerEvidence())
            new_events.append(chain.make(
                tick, "food_shortage",
                severity=min(1.0, starving_ratio),
                description=f"粮食短缺：{sum(1 for a in agents if a.resources.is_starving())}/{len(agents)} 名成员处于饥饿状态",
                effects={"starving_ratio": round(starving_ratio, 3)},
                duration=DURATION["food_shortage"],
                trigger_score=score,
                causal_confidence=evidence.confidence,
                evidence=evidence.indicators,
                cause_mechanism="food_stock_depletion",
            ))

    # --- Economic crisis: use trigger registry ---
    economic_trigger = get_trigger("economic_crisis")
    if economic_trigger:
        eco_score, eco_evidence = economic_trigger.score(society, context)
        if cm is not None:
            # Update crisis state machine
            cm.economic.update(eco_score, tick, ticks_per_day)

            if (cm.economic.state.value == "ACTIVE"
                    and cm.economic.duration_ticks == 1
                    and not _has_active(chain, "economic_crisis")):
                crisis = chain.make(
                    tick, "economic_crisis",
                    severity=max(0.2, eco_score),
                    description="经济压力引发的经济危机",
                    duration=DURATION["economic_crisis"],
                    trigger_score=eco_score,
                    causal_confidence=eco_evidence.confidence,
                    evidence=eco_evidence.indicators,
                    cause_mechanism="economic_pressure_accumulation",
                )
                new_events.append(crisis)
                _apply_effects(society, crisis, agents, rng)
        elif economic_trigger.should_trigger(eco_score, tick):
            # Fallback without CrisisManager
            crisis = chain.make(
                tick, "economic_crisis",
                severity=max(0.2, eco_score),
                description="经济压力引发的经济危机",
                duration=DURATION["economic_crisis"],
                trigger_score=eco_score,
                causal_confidence=eco_evidence.confidence,
                evidence=eco_evidence.indicators,
                cause_mechanism="economic_pressure_accumulation",
            )
            new_events.append(crisis)
            _apply_effects(society, crisis, agents, rng)

    # --- Protest: use trigger registry ---
    protest_trigger = get_trigger("protest")
    if protest_trigger:
        prot_score, prot_evidence = protest_trigger.score(society, context)
        if cm is not None:
            previous_protest_state = cm.protest.state
            cm.protest.update(prot_score, tick, ticks_per_day)

            if cm.protest.state.value == "ACTIVE" and cm.protest.duration_ticks == 1:
                new_events.append(chain.make(
                    tick, "protest",
                    severity=context.get("temperature", 0.5),
                    description="不满情绪上升引发公众抗议",
                    duration=rng.randint(10, 30),
                    trigger_score=prot_score,
                    causal_confidence=prot_evidence.confidence,
                    evidence=prot_evidence.indicators,
                    cause_mechanism="grievance_mobilization",
                ))
                society.production_disruption = min(0.4, getattr(society, "production_disruption", 0.0) + 0.08)

            # Recovery notification
            if (previous_protest_state.name == "RECOVERING"
                    and cm.protest.state.name == "COOLDOWN"
                    and not _has_recent(chain, "recovery", tick, int(2 * ticks_per_day))):
                cause = next((e for e in reversed(chain.events) if e.type == "protest"), None)
                new_events.append(chain.make(
                    tick, "recovery", severity=0.4,
                    description="抗议平息，生产逐步恢复",
                    cause_event_id=cause.event_id if cause else None,
                    cause_mechanism="protest_resolution",
                    duration=DURATION["recovery"],
                    source_type=SOURCE_TYPE.RECOVERY,
                    intensity=0.4))
        elif protest_trigger.should_trigger(prot_score, tick):
            new_events.append(chain.make(
                tick, "protest",
                severity=context.get("temperature", 0.5),
                description="不满情绪上升引发公众抗议",
                duration=rng.randint(10, 30),
                trigger_score=prot_score,
                causal_confidence=prot_evidence.confidence,
                evidence=prot_evidence.indicators,
                cause_mechanism="grievance_mobilization",
            ))
            society.production_disruption = min(0.4, getattr(society, "production_disruption", 0.0) + 0.08)

    # --- Other endogenous triggers ---
    # Political movement, scandal, resource boom, unemployment, conflict, etc.
    endogenous_results = _evaluate_endogenous_triggers(society, agents, cfg, context, chain, tick)
    for trigger, score, evidence in endogenous_results:
        # Skip if already handled above
        if trigger.event_type in ("economic_crisis", "food_shortage", "protest"):
            continue

        # Compute severity from trigger score + small noise
        severity = max(0.2, min(1.0, score + rng.gauss(0, 0.05)))

        event = chain.make(
            tick, trigger.event_type,
            severity=severity,
            description=TYPE_LABEL.get(trigger.event_type, trigger.event_type),
            duration=DURATION.get(trigger.event_type, 20),
            trigger_score=score,
            causal_confidence=evidence.confidence,
            evidence=evidence.indicators,
            cause_mechanism=f"trigger_registry_{trigger.event_type}",
            scope=EVENT_SCOPE.GROUP if trigger.event_type in ("conflict", "group_split") else EVENT_SCOPE.REGIONAL,
        )
        new_events.append(event)
        _apply_effects(society, event, agents, rng)

    # --- Exogenous events (daily probability) ---
    exo_events = _evaluate_exogenous_events(society, agents, cfg, rng, chain, tick, ticks_per_day)
    new_events.extend(exo_events)

    # --- Government response to new events ---
    for e in new_events:
        if e.source_type == SOURCE_TYPE.RECOVERY:
            continue  # §26: recovery does not trigger government response
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
                    evidence={"trigger_event": e.event_id},
                )

    # --- Event budget (§19): limit major events per day ---
    daily_budget = ev.get("daily_major_event_budget", 2)
    endogenous_today = [
        e for e in new_events
        if e.source_type == SOURCE_TYPE.ENDOGENOUS and e.severity > 0.5
    ]
    if len(endogenous_today) > daily_budget:
        # Keep top N by trigger_score, defer rest
        endogenous_today.sort(key=lambda e: e.trigger_score, reverse=True)
        for excess in endogenous_today[daily_budget:]:
            # Remove from chain and defer to queue
            if excess in chain.events:
                chain.events.remove(excess)
            queue.enqueue(
                excess.as_dict(),
                tick=tick + ticks_per_day,  # defer to next day
                source_type=SOURCE_TYPE.ENDOGENOUS,
                cause_event_type=excess.type,
            )

    return new_events
