"""Event Trigger Registry — v0.4.5 §6.

Each endogenous event type registers an EventTrigger that computes a trigger
score from society state. The registry also manages persistence, hysteresis,
cooldown, and causal evidence collection.

Key design:
  - score(society, context) -> float: compute trigger score from social state
  - should_trigger(score, state, history) -> bool: persistence + hysteresis + cooldown
  - Each trigger has trigger_threshold / resolve_threshold (hysteresis)
  - Each trigger has persistence_ticks (must exceed threshold for N ticks)
  - Each trigger has cooldown_ticks (no re-trigger after resolution)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .event import SOURCE_TYPE


@dataclass
class TriggerEvidence:
    """Evidence collected for a trigger evaluation."""
    indicators: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0


class EventTrigger:
    """Single event trigger definition.

    score() computes a [0,1] score from society state.
    should_trigger() applies persistence + hysteresis + cooldown.
    """
    # Override in subclasses
    event_type: str = ""
    source_type: SOURCE_TYPE = SOURCE_TYPE.ENDOGENOUS

    # Hysteresis (§17)
    trigger_threshold: float = 0.60
    resolve_threshold: float = 0.40

    # Persistence (§16): score must exceed threshold for N ticks
    persistence_ticks: int = 12

    # Cooldown (§18): no re-trigger for N ticks after resolution
    cooldown_ticks: int = 50

    def __init__(self) -> None:
        self._above_threshold_ticks: int = 0
        self._cooldown_remaining: int = 0
        self._is_active: bool = False
        self._last_trigger_tick: int = -10**9

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        """Compute trigger score and evidence from society state.

        Returns (score, evidence). Override in subclasses.
        """
        raise NotImplementedError

    def should_trigger(self, score: float, tick: int) -> bool:
        """Apply persistence + hysteresis + cooldown logic.

        Returns True if this trigger should fire now.
        """
        # Cooldown check
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            return False

        # Persistence check (§16)
        if score > self.trigger_threshold:
            self._above_threshold_ticks += 1
        else:
            self._above_threshold_ticks = 0

        # Hysteresis resolution (§17)
        if self._is_active and score < self.resolve_threshold:
            self._is_active = False
            self._cooldown_remaining = self.cooldown_ticks
            return False

        # Trigger when persistence threshold met
        if (not self._is_active
                and self._above_threshold_ticks >= self.persistence_ticks):
            self._is_active = True
            self._last_trigger_tick = tick
            self._above_threshold_ticks = 0
            return True

        return False

    def reset(self) -> None:
        """Reset trigger state (for testing)."""
        self._above_threshold_ticks = 0
        self._cooldown_remaining = 0
        self._is_active = False


# ---------------------------------------------------------------------------
# Concrete triggers for each endogenous event type
# ---------------------------------------------------------------------------

class EconomicCrisisTrigger(EventTrigger):
    """v0.4.5 §7: Economic crisis from production gap + unemployment + price pressure + liquidity stress."""
    event_type = "economic_crisis"
    trigger_threshold = 0.68
    resolve_threshold = 0.45
    persistence_ticks = 100
    cooldown_ticks = 500  # 5 days @ 100 ticks/day

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        agents = [a for a in society.agents if a.alive]
        if not agents:
            return 0.0, TriggerEvidence()

        # Production gap: how far production is below consumption
        production_gap = context.get("production_gap", 0.0)

        # Unemployment ratio
        unemployed = sum(1 for a in agents if getattr(a, 'sector', '') == 'unemployed')
        unemployment = unemployed / len(agents)

        # Price pressure: food price relative to baseline
        price_pressure = context.get("price_pressure", 0.0)

        # Liquidity stress: agents with very low money
        broke = sum(1 for a in agents if a.resources.is_broke())
        liquidity_stress = broke / len(agents)

        # Resource shortage: starving agents
        starving = sum(1 for a in agents if a.resources.is_starving())
        resource_shortage = starving / len(agents)

        # Weighted combination (§7)
        score = (
            0.30 * production_gap
            + 0.25 * unemployment
            + 0.20 * price_pressure
            + 0.15 * liquidity_stress
            + 0.10 * resource_shortage
        )

        evidence = TriggerEvidence(
            indicators={
                "production_gap": production_gap,
                "unemployment": unemployment,
                "price_pressure": price_pressure,
                "liquidity_stress": liquidity_stress,
                "resource_shortage": resource_shortage,
            },
            confidence=min(1.0, len(agents) / 100),  # more agents = more confidence
        )
        return min(1.0, score), evidence


class FoodShortageTrigger(EventTrigger):
    """v0.4.5 §8: Food crisis from stock, supply days, hunger, production gap."""
    event_type = "food_shortage"
    trigger_threshold = 0.25
    resolve_threshold = 0.12
    persistence_ticks = 50
    cooldown_ticks = 200

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        agents = [a for a in society.agents if a.alive]
        if not agents:
            return 0.0, TriggerEvidence()

        starving = sum(1 for a in agents if a.resources.is_starving())
        hungry_ratio = starving / len(agents)

        # Low food stock buffer
        avg_food = sum(a.resources.values.get("food", 0) for a in agents) / len(agents)
        food_critical = context.get("food_critical", 20.0)
        low_stock = max(0.0, 1.0 - avg_food / max(food_critical, 1.0))

        # Production gap for food
        production_gap = context.get("food_production_gap", 0.0)

        score = (
            0.40 * hungry_ratio
            + 0.30 * low_stock
            + 0.30 * production_gap
        )

        evidence = TriggerEvidence(
            indicators={
                "hungry_ratio": hungry_ratio,
                "low_stock": low_stock,
                "food_production_gap": production_gap,
            },
            confidence=min(1.0, len(agents) / 50),
        )
        return min(1.0, score), evidence


class ProtestTrigger(EventTrigger):
    """v0.4.5 §9: Protest from grievance × mobilization × information × group support."""
    event_type = "protest"
    trigger_threshold = 0.40
    resolve_threshold = 0.20
    persistence_ticks = 30
    cooldown_ticks = 200

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        agents = [a for a in society.agents if a.alive]
        if not agents:
            return 0.0, TriggerEvidence()

        # Grievance: anger + low trust
        angry = sum(1 for a in agents if a.status.get("anger", 0.0) > 0.3)
        grievance = angry / len(agents)

        # Mobilization: agents with high energy and social connections
        mobile = sum(1 for a in agents if a.resources.values.get("energy", 0) > 10)
        mobilization = mobile / len(agents)

        # Information reach: how spread information is
        information_reach = context.get("information_spread", 0.3)

        # Group support: number of active groups with high cohesion
        groups = society.groups.active() if hasattr(society, 'groups') else []
        group_support = min(1.0, len(groups) / max(1, len(agents) / 50))

        # Multiplicative model (§9): all factors must be present
        score = (
            grievance
            * mobilization
            * information_reach
            * group_support
        ) ** 0.5  # geometric mean-ish for stability

        evidence = TriggerEvidence(
            indicators={
                "grievance": grievance,
                "mobilization": mobilization,
                "information_reach": information_reach,
                "group_support": group_support,
            },
            confidence=min(1.0, len(agents) / 50),
        )
        return min(1.0, score), evidence


class PoliticalMovementTrigger(EventTrigger):
    """v0.4.5 §10: Political movement — stricter than protest."""
    event_type = "political_movement"
    trigger_threshold = 0.55
    resolve_threshold = 0.35
    persistence_ticks = 80
    cooldown_ticks = 500

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        agents = [a for a in society.agents if a.alive]
        if not agents:
            return 0.0, TriggerEvidence()

        # Persistent grievance: must have had protests or high anger for a while
        persistent_grievance = context.get("persistent_grievance", 0.0)

        # Group cohesion: at least one cohesive group required
        groups = society.groups.active() if hasattr(society, 'groups') else []
        if not groups:
            return 0.0, TriggerEvidence(indicators={"group_count": 0})
        max_cohesion = max((g.cohesion for g in groups), default=0.0)
        group_cohesion = max_cohesion

        # Information cascade: how spread political information is
        information_cascade = context.get("information_cascade", 0.0)

        # Political opportunity: based on political dynamics
        political_opportunity = context.get("political_opportunity", 0.0)

        score = (
            persistent_grievance
            * group_cohesion
            * information_cascade
            * political_opportunity
        ) ** 0.5

        evidence = TriggerEvidence(
            indicators={
                "persistent_grievance": persistent_grievance,
                "group_cohesion": group_cohesion,
                "information_cascade": information_cascade,
                "political_opportunity": political_opportunity,
            },
            confidence=min(1.0, len(groups) / 3),
        )
        return min(1.0, score), evidence


class ScandalTrigger(EventTrigger):
    """v0.4.5 §11/§44: Scandal must come from agent/group behavior + information exposure."""
    event_type = "scandal"
    trigger_threshold = 0.50
    resolve_threshold = 0.30
    persistence_ticks = 20
    cooldown_ticks = 300

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        # Scandal requires violation + information exposure (§11)
        violation_detected = context.get("violation_detected", 0.0)
        information_exposure = context.get("information_exposure", 0.0)
        trust = context.get("public_trust", 0.5)

        # If no violation detected, no scandal possible
        if violation_detected < 0.1:
            return 0.0, TriggerEvidence(indicators={"violation_detected": 0.0})

        score = violation_detected * information_exposure * (1.0 - trust)

        evidence = TriggerEvidence(
            indicators={
                "violation_detected": violation_detected,
                "information_exposure": information_exposure,
                "public_trust": trust,
            },
            confidence=violation_detected * information_exposure,
        )
        return min(1.0, score), evidence


class ResourceBoomTrigger(EventTrigger):
    """v0.4.5 §12/§42: Resource boom from production increase / technology / trade expansion."""
    event_type = "resource_boom"
    trigger_threshold = 0.55
    resolve_threshold = 0.35
    persistence_ticks = 30
    cooldown_ticks = 400

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        production_increase = context.get("production_increase", 0.0)
        technology_boost = context.get("technology_boost", 0.0)
        trade_expansion = context.get("trade_expansion", 0.0)

        score = (
            0.40 * production_increase
            + 0.35 * technology_boost
            + 0.25 * trade_expansion
        )

        evidence = TriggerEvidence(
            indicators={
                "production_increase": production_increase,
                "technology_boost": technology_boost,
                "trade_expansion": trade_expansion,
            },
            confidence=score,
        )
        return min(1.0, score), evidence


class UnemploymentTrigger(EventTrigger):
    """v0.4.5: Unemployment crisis trigger."""
    event_type = "unemployment"
    trigger_threshold = 0.35
    resolve_threshold = 0.20
    persistence_ticks = 40
    cooldown_ticks = 300

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        agents = [a for a in society.agents if a.alive]
        if not agents:
            return 0.0, TriggerEvidence()

        unemployed = sum(1 for a in agents if getattr(a, 'sector', '') == 'unemployed')
        unemployment_rate = unemployed / len(agents)

        # Youth unemployment (younger agents)
        young = [a for a in agents if getattr(a, 'age', 30) < 30]
        young_unemployed = sum(1 for a in young if getattr(a, 'sector', '') == 'unemployed') if young else 0
        youth_unemployment = young_unemployed / max(len(young), 1)

        score = 0.7 * unemployment_rate + 0.3 * youth_unemployment

        evidence = TriggerEvidence(
            indicators={
                "unemployment_rate": unemployment_rate,
                "youth_unemployment": youth_unemployment,
            },
            confidence=min(1.0, len(agents) / 100),
        )
        return min(1.0, score), evidence


class ConflictTrigger(EventTrigger):
    """v0.4.5: Group conflict trigger."""
    event_type = "conflict"
    trigger_threshold = 0.50
    resolve_threshold = 0.30
    persistence_ticks = 25
    cooldown_ticks = 300

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        agents = [a for a in society.agents if a.alive]
        if not agents:
            return 0.0, TriggerEvidence()

        # Inter-group tension
        groups = society.groups.active() if hasattr(society, 'groups') else []
        if len(groups) < 2:
            return 0.0, TriggerEvidence(indicators={"group_count": len(groups)})

        # Polarization: how far apart groups are politically
        group_positions = []
        for g in groups:
            if hasattr(g, 'centroid'):
                group_positions.append(g.centroid)
        if len(group_positions) < 2:
            return 0.0, TriggerEvidence()

        # Max distance between any two groups
        max_dist = 0.0
        for i in range(len(group_positions)):
            for j in range(i + 1, len(group_positions)):
                d = sum((a - b) ** 2 for a, b in zip(group_positions[i], group_positions[j])) ** 0.5
                max_dist = max(max_dist, d)
        polarization = min(1.0, max_dist / 2.0)

        # Resource competition
        resource_competition = context.get("resource_competition", 0.0)

        score = 0.6 * polarization + 0.4 * resource_competition

        evidence = TriggerEvidence(
            indicators={
                "polarization": polarization,
                "resource_competition": resource_competition,
                "group_count": len(groups),
            },
            confidence=min(1.0, len(groups) / 3),
        )
        return min(1.0, score), evidence


class MarketPanicTrigger(EventTrigger):
    """v0.4.5: Market panic trigger."""
    event_type = "market_panic"
    trigger_threshold = 0.55
    resolve_threshold = 0.35
    persistence_ticks = 15
    cooldown_ticks = 300

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        # Market panic from price volatility + trust collapse
        price_volatility = context.get("price_volatility", 0.0)
        trust_collapse = context.get("trust_collapse", 0.0)
        bank_run_signal = context.get("bank_run_signal", 0.0)

        score = (
            0.40 * price_volatility
            + 0.35 * trust_collapse
            + 0.25 * bank_run_signal
        )

        evidence = TriggerEvidence(
            indicators={
                "price_volatility": price_volatility,
                "trust_collapse": trust_collapse,
                "bank_run_signal": bank_run_signal,
            },
            confidence=score,
        )
        return min(1.0, score), evidence


class GroupSplitTrigger(EventTrigger):
    """v0.4.5: Group split trigger."""
    event_type = "group_split"
    trigger_threshold = 0.60
    resolve_threshold = 0.40
    persistence_ticks = 30
    cooldown_ticks = 200

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        groups = society.groups.active() if hasattr(society, 'groups') else []
        if not groups:
            return 0.0, TriggerEvidence()

        # Internal variance in groups
        max_variance = max((getattr(g, 'internal_variance', 0.0) for g in groups), default=0.0)
        low_cohesion_groups = sum(1 for g in groups if getattr(g, 'cohesion', 1.0) < 0.4)
        low_cohesion_ratio = low_cohesion_groups / len(groups)

        score = 0.6 * max_variance + 0.4 * low_cohesion_ratio

        evidence = TriggerEvidence(
            indicators={
                "max_variance": max_variance,
                "low_cohesion_ratio": low_cohesion_ratio,
            },
            confidence=min(1.0, len(groups) / 3),
        )
        return min(1.0, score), evidence


class MigrationWaveTrigger(EventTrigger):
    """v0.4.5: Migration wave trigger."""
    event_type = "migration"
    trigger_threshold = 0.50
    resolve_threshold = 0.30
    persistence_ticks = 30
    cooldown_ticks = 300

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        # Migration from regional inequality + push factors
        regional_inequality = context.get("regional_inequality", 0.0)
        resource_pressure = context.get("resource_pressure", 0.0)
        safety_concern = context.get("safety_concern", 0.0)

        score = (
            0.40 * regional_inequality
            + 0.35 * resource_pressure
            + 0.25 * safety_concern
        )

        evidence = TriggerEvidence(
            indicators={
                "regional_inequality": regional_inequality,
                "resource_pressure": resource_pressure,
                "safety_concern": safety_concern,
            },
            confidence=score,
        )
        return min(1.0, score), evidence


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Global registry of all triggers
_TRIGGER_REGISTRY: dict[str, EventTrigger] = {}


def register_trigger(trigger: EventTrigger) -> None:
    """Register an event trigger."""
    _TRIGGER_REGISTRY[trigger.event_type] = trigger


def get_trigger(event_type: str) -> Optional[EventTrigger]:
    """Get a registered trigger by event type."""
    return _TRIGGER_REGISTRY.get(event_type)


def get_all_triggers() -> dict[str, EventTrigger]:
    """Get all registered triggers."""
    return dict(_TRIGGER_REGISTRY)


def get_endogenous_triggers() -> dict[str, EventTrigger]:
    """Get only endogenous triggers."""
    return {
        k: v for k, v in _TRIGGER_REGISTRY.items()
        if v.source_type == SOURCE_TYPE.ENDOGENOUS
    }


# Auto-register all default triggers
def _register_defaults() -> None:
    register_trigger(EconomicCrisisTrigger())
    register_trigger(FoodShortageTrigger())
    register_trigger(ProtestTrigger())
    register_trigger(PoliticalMovementTrigger())
    register_trigger(ScandalTrigger())
    register_trigger(ResourceBoomTrigger())
    register_trigger(UnemploymentTrigger())
    register_trigger(ConflictTrigger())
    register_trigger(MarketPanicTrigger())
    register_trigger(GroupSplitTrigger())
    register_trigger(MigrationWaveTrigger())


_register_defaults()
