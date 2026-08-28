"""Event Trigger Registry — v0.4.5.2.

Triggers only provide score() and evidence. They do NOT maintain crisis state.
CrisisManager is the Single Source of Truth for crisis lifecycle.

v0.4.5.2 changes:
  - Removed _is_active, _cooldown_remaining, _above_threshold_ticks from triggers
  - should_trigger() removed — CrisisManager decides state transitions
  - Triggers are stateless scoring functions
  - Registry is per-society (not global singleton)
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
    """Stateless scoring function for an event type.

    v0.4.5.2: Only provides score() and evidence. No state maintenance.
    CrisisManager is the Single Source of Truth for crisis lifecycle.
    """
    event_type: str = ""
    source_type: SOURCE_TYPE = SOURCE_TYPE.ENDOGENOUS

    # Thresholds (used by CrisisManager, not by trigger itself)
    trigger_threshold: float = 0.60
    resolve_threshold: float = 0.40

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        """Compute trigger score and evidence from society state.

        Returns (score, evidence). Override in subclasses.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Concrete triggers — all stateless
# ---------------------------------------------------------------------------

class EconomicCrisisTrigger(EventTrigger):
    """v0.4.5.2 §7: Economic crisis scoring."""
    event_type = "economic_crisis"
    trigger_threshold = 0.68
    resolve_threshold = 0.45

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        agents = [a for a in society.agents if a.alive]
        if not agents:
            return 0.0, TriggerEvidence()

        production_gap = context.get("production_gap", 0.0)
        unemployed = sum(1 for a in agents if getattr(a, 'sector', '') == 'unemployed')
        unemployment = unemployed / len(agents)
        price_pressure = context.get("price_pressure", 0.0)
        broke = sum(1 for a in agents if a.resources.is_broke())
        liquidity_stress = broke / len(agents)
        starving = sum(1 for a in agents if a.resources.is_starving())
        resource_shortage = starving / len(agents)

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
            confidence=min(1.0, len(agents) / 100),
        )
        return min(1.0, score), evidence


class FoodShortageTrigger(EventTrigger):
    """v0.4.5.2 §8: Food crisis scoring."""
    event_type = "food_shortage"
    trigger_threshold = 0.25
    resolve_threshold = 0.12

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        agents = [a for a in society.agents if a.alive]
        if not agents:
            return 0.0, TriggerEvidence()

        starving = sum(1 for a in agents if a.resources.is_starving())
        hungry_ratio = starving / len(agents)
        avg_food = sum(a.resources.values.get("food", 0) for a in agents) / len(agents)
        food_critical = context.get("food_critical", 20.0)
        low_stock = max(0.0, 1.0 - avg_food / max(food_critical, 1.0))
        production_gap = context.get("food_production_gap", 0.0)

        score = 0.40 * hungry_ratio + 0.30 * low_stock + 0.30 * production_gap
        evidence = TriggerEvidence(
            indicators={"hungry_ratio": hungry_ratio, "low_stock": low_stock,
                        "food_production_gap": production_gap},
            confidence=min(1.0, len(agents) / 50),
        )
        return min(1.0, score), evidence


class ProtestTrigger(EventTrigger):
    """v0.4.5.2 §9: Protest scoring."""
    event_type = "protest"
    trigger_threshold = 0.40
    resolve_threshold = 0.20

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        agents = [a for a in society.agents if a.alive]
        if not agents:
            return 0.0, TriggerEvidence()

        angry = sum(1 for a in agents if a.status.get("anger", 0.0) > 0.3)
        grievance = angry / len(agents)
        mobile = sum(1 for a in agents if a.resources.values.get("energy", 0) > 10)
        mobilization = mobile / len(agents)
        information_reach = context.get("information_spread", 0.3)
        groups = society.groups.active() if hasattr(society, 'groups') else []
        group_support = min(1.0, len(groups) / max(1, len(agents) / 50))

        score = (grievance * mobilization * information_reach * group_support) ** 0.5
        evidence = TriggerEvidence(
            indicators={"grievance": grievance, "mobilization": mobilization,
                        "information_reach": information_reach, "group_support": group_support},
            confidence=min(1.0, len(agents) / 50),
        )
        return min(1.0, score), evidence


class PoliticalMovementTrigger(EventTrigger):
    event_type = "political_movement"
    trigger_threshold = 0.55
    resolve_threshold = 0.35

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        agents = [a for a in society.agents if a.alive]
        if not agents:
            return 0.0, TriggerEvidence()
        persistent_grievance = context.get("persistent_grievance", 0.0)
        groups = society.groups.active() if hasattr(society, 'groups') else []
        if not groups:
            return 0.0, TriggerEvidence(indicators={"group_count": 0})
        max_cohesion = max((g.cohesion for g in groups), default=0.0)
        information_cascade = context.get("information_cascade", 0.0)
        political_opportunity = context.get("political_opportunity", 0.0)
        score = (persistent_grievance * max_cohesion * information_cascade * political_opportunity) ** 0.5
        evidence = TriggerEvidence(
            indicators={"persistent_grievance": persistent_grievance,
                        "group_cohesion": max_cohesion,
                        "information_cascade": information_cascade,
                        "political_opportunity": political_opportunity},
            confidence=min(1.0, len(groups) / 3),
        )
        return min(1.0, score), evidence


class ScandalTrigger(EventTrigger):
    event_type = "scandal"
    trigger_threshold = 0.50
    resolve_threshold = 0.30

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        violation_detected = context.get("violation_detected", 0.0)
        information_exposure = context.get("information_exposure", 0.0)
        trust = context.get("public_trust", 0.5)
        if violation_detected < 0.1:
            return 0.0, TriggerEvidence(indicators={"violation_detected": 0.0})
        score = violation_detected * information_exposure * (1.0 - trust)
        evidence = TriggerEvidence(
            indicators={"violation_detected": violation_detected,
                        "information_exposure": information_exposure,
                        "public_trust": trust},
            confidence=violation_detected * information_exposure,
        )
        return min(1.0, score), evidence


class ResourceBoomTrigger(EventTrigger):
    event_type = "resource_boom"
    trigger_threshold = 0.55
    resolve_threshold = 0.35

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        production_increase = context.get("production_increase", 0.0)
        technology_boost = context.get("technology_boost", 0.0)
        trade_expansion = context.get("trade_expansion", 0.0)
        score = 0.40 * production_increase + 0.35 * technology_boost + 0.25 * trade_expansion
        evidence = TriggerEvidence(
            indicators={"production_increase": production_increase,
                        "technology_boost": technology_boost,
                        "trade_expansion": trade_expansion},
            confidence=score,
        )
        return min(1.0, score), evidence


class UnemploymentTrigger(EventTrigger):
    event_type = "unemployment"
    trigger_threshold = 0.35
    resolve_threshold = 0.20

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        agents = [a for a in society.agents if a.alive]
        if not agents:
            return 0.0, TriggerEvidence()
        unemployed = sum(1 for a in agents if getattr(a, 'sector', '') == 'unemployed')
        unemployment_rate = unemployed / len(agents)
        young = [a for a in agents if getattr(a, 'age', 30) < 30]
        young_unemployed = sum(1 for a in young if getattr(a, 'sector', '') == 'unemployed') if young else 0
        youth_unemployment = young_unemployed / max(len(young), 1)
        score = 0.7 * unemployment_rate + 0.3 * youth_unemployment
        evidence = TriggerEvidence(
            indicators={"unemployment_rate": unemployment_rate,
                        "youth_unemployment": youth_unemployment},
            confidence=min(1.0, len(agents) / 100),
        )
        return min(1.0, score), evidence


class ConflictTrigger(EventTrigger):
    event_type = "conflict"
    trigger_threshold = 0.50
    resolve_threshold = 0.30

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        agents = [a for a in society.agents if a.alive]
        if not agents:
            return 0.0, TriggerEvidence()
        groups = society.groups.active() if hasattr(society, 'groups') else []
        if len(groups) < 2:
            return 0.0, TriggerEvidence(indicators={"group_count": len(groups)})
        group_positions = [g.centroid for g in groups if hasattr(g, 'centroid')]
        if len(group_positions) < 2:
            return 0.0, TriggerEvidence()
        max_dist = 0.0
        for i in range(len(group_positions)):
            for j in range(i + 1, len(group_positions)):
                d = sum((a - b) ** 2 for a, b in zip(group_positions[i], group_positions[j])) ** 0.5
                max_dist = max(max_dist, d)
        polarization = min(1.0, max_dist / 2.0)
        resource_competition = context.get("resource_competition", 0.0)
        score = 0.6 * polarization + 0.4 * resource_competition
        evidence = TriggerEvidence(
            indicators={"polarization": polarization,
                        "resource_competition": resource_competition,
                        "group_count": len(groups)},
            confidence=min(1.0, len(groups) / 3),
        )
        return min(1.0, score), evidence


class MarketPanicTrigger(EventTrigger):
    event_type = "market_panic"
    trigger_threshold = 0.55
    resolve_threshold = 0.35

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        price_volatility = context.get("price_volatility", 0.0)
        trust_collapse = context.get("trust_collapse", 0.0)
        bank_run_signal = context.get("bank_run_signal", 0.0)
        score = 0.40 * price_volatility + 0.35 * trust_collapse + 0.25 * bank_run_signal
        evidence = TriggerEvidence(
            indicators={"price_volatility": price_volatility,
                        "trust_collapse": trust_collapse,
                        "bank_run_signal": bank_run_signal},
            confidence=score,
        )
        return min(1.0, score), evidence


class GroupSplitTrigger(EventTrigger):
    event_type = "group_split"
    trigger_threshold = 0.60
    resolve_threshold = 0.40

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        groups = society.groups.active() if hasattr(society, 'groups') else []
        if not groups:
            return 0.0, TriggerEvidence()
        max_variance = max((getattr(g, 'internal_variance', 0.0) for g in groups), default=0.0)
        low_cohesion_groups = sum(1 for g in groups if getattr(g, 'cohesion', 1.0) < 0.4)
        low_cohesion_ratio = low_cohesion_groups / len(groups)
        score = 0.6 * max_variance + 0.4 * low_cohesion_ratio
        evidence = TriggerEvidence(
            indicators={"max_variance": max_variance,
                        "low_cohesion_ratio": low_cohesion_ratio},
            confidence=min(1.0, len(groups) / 3),
        )
        return min(1.0, score), evidence


class MigrationWaveTrigger(EventTrigger):
    event_type = "migration"
    trigger_threshold = 0.50
    resolve_threshold = 0.30

    def score(self, society, context: dict) -> tuple[float, TriggerEvidence]:
        regional_inequality = context.get("regional_inequality", 0.0)
        resource_pressure = context.get("resource_pressure", 0.0)
        safety_concern = context.get("safety_concern", 0.0)
        score = 0.40 * regional_inequality + 0.35 * resource_pressure + 0.25 * safety_concern
        evidence = TriggerEvidence(
            indicators={"regional_inequality": regional_inequality,
                        "resource_pressure": resource_pressure,
                        "safety_concern": safety_concern},
            confidence=score,
        )
        return min(1.0, score), evidence


# ---------------------------------------------------------------------------
# Registry — per-society, not global singleton
# ---------------------------------------------------------------------------

# Template definitions (no state)
_TRIGGER_DEFS: dict[str, type] = {
    "economic_crisis": EconomicCrisisTrigger,
    "food_shortage": FoodShortageTrigger,
    "protest": ProtestTrigger,
    "political_movement": PoliticalMovementTrigger,
    "scandal": ScandalTrigger,
    "resource_boom": ResourceBoomTrigger,
    "unemployment": UnemploymentTrigger,
    "conflict": ConflictTrigger,
    "market_panic": MarketPanicTrigger,
    "group_split": GroupSplitTrigger,
    "migration": MigrationWaveTrigger,
}


def create_trigger_registry() -> dict[str, EventTrigger]:
    """Create a fresh per-society trigger registry.

    v0.4.5.2 §26: Each society gets its own trigger instances.
    """
    return {name: cls() for name, cls in _TRIGGER_DEFS.items()}


def get_trigger_definitions() -> dict[str, type]:
    """Get trigger class definitions (for testing)."""
    return dict(_TRIGGER_DEFS)
