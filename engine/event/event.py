"""Event + EventChain — the causality backbone of the simulation (§15, §16).

v0.2: events carry a full lifecycle (§10, §11) — intensity/duration/age/decay
so they are *not* permanent states. event_links still encode cause → effect.

v0.4.5: events now carry source_type (ENDOGENOUS/EXOGENOUS/RECOVERY),
evidence, causal_confidence, trigger_score, cause_mechanism,
scope (INDIVIDUAL/GROUP/REGIONAL/SOCIETY), region, affected_agents, affected_groups.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class EVENT_STATUS(str, Enum):
    TRIGGERED = "triggered"
    GROWING = "growing"
    PEAK = "peak"
    DECAYING = "decaying"
    RESOLVED = "resolved"


class SOURCE_TYPE(str, Enum):
    """v0.4.5 §2: Event source classification."""
    ENDOGENOUS = "ENDOGENOUS"
    EXOGENOUS = "EXOGENOUS"
    RECOVERY = "RECOVERY"


class EVENT_SCOPE(str, Enum):
    """v0.4.5 §46: Event spatial scope."""
    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"
    REGIONAL = "REGIONAL"
    SOCIETY = "SOCIETY"


# v0.4.5 §2: Event type → source classification
EVENT_SOURCE_MAP: dict[str, SOURCE_TYPE] = {
    # ENDOGENOUS — from society internal state
    "economic_crisis": SOURCE_TYPE.ENDOGENOUS,
    "food_shortage": SOURCE_TYPE.ENDOGENOUS,
    "protest": SOURCE_TYPE.ENDOGENOUS,
    "political_movement": SOURCE_TYPE.ENDOGENOUS,
    "unemployment": SOURCE_TYPE.ENDOGENOUS,
    "conflict": SOURCE_TYPE.ENDOGENOUS,
    "market_panic": SOURCE_TYPE.ENDOGENOUS,
    "scandal": SOURCE_TYPE.ENDOGENOUS,
    "group_split": SOURCE_TYPE.ENDOGENOUS,
    "migration": SOURCE_TYPE.ENDOGENOUS,
    # EXOGENOUS — from outside the system
    "natural_disaster": SOURCE_TYPE.EXOGENOUS,
    "pandemic": SOURCE_TYPE.EXOGENOUS,
    "external_shock": SOURCE_TYPE.EXOGENOUS,
    "technology_breakthrough": SOURCE_TYPE.EXOGENOUS,
    "war": SOURCE_TYPE.EXOGENOUS,
    # RECOVERY — state transition notifications
    "economic_recovery": SOURCE_TYPE.RECOVERY,
    "food_stabilization": SOURCE_TYPE.RECOVERY,
    "recovery": SOURCE_TYPE.RECOVERY,
    "resource_stabilization": SOURCE_TYPE.RECOVERY,
    # Other
    "resource_boom": SOURCE_TYPE.ENDOGENOUS,
    "government_response": SOURCE_TYPE.ENDOGENOUS,
    "alliance": SOURCE_TYPE.ENDOGENOUS,
    "election": SOURCE_TYPE.ENDOGENOUS,
    "leadership_change": SOURCE_TYPE.ENDOGENOUS,
    "reform": SOURCE_TYPE.ENDOGENOUS,
}


EVENT_TYPES: tuple[str, ...] = tuple(EVENT_SOURCE_MAP.keys())


@dataclass
class Event:
    event_id: str
    tick: int
    type: str
    source: str = "system"          # "system" | agent id | group id
    targets: list = field(default_factory=list)
    severity: float = 0.0
    effects: dict = field(default_factory=dict)
    description: str = ""
    cause_event_id: Optional[str] = None   # for the causality chain
    # v0.2 lifecycle (§10, §11)
    intensity: float = 0.0
    max_intensity: float = 0.0
    duration: int = 20
    age: int = 0
    decay_rate: float = 0.03
    status: EVENT_STATUS = EVENT_STATUS.TRIGGERED

    # v0.4.5: Event Ecology & Causal Dynamics
    source_type: SOURCE_TYPE = SOURCE_TYPE.ENDOGENOUS  # §2: ENDOGENOUS/EXOGENOUS/RECOVERY
    trigger_score: float = 0.0          # §5: why it now could happen
    causal_confidence: float = 0.0      # §21: confidence from evidence
    cause_mechanism: str = ""           # §5: which social mechanism pushed it
    evidence: dict = field(default_factory=dict)  # §21: {indicator: value}
    scope: EVENT_SCOPE = EVENT_SCOPE.REGIONAL    # §46: INDIVIDUAL/GROUP/REGIONAL/SOCIETY
    region: Optional[str] = None        # §15: affected region
    affected_agents: list = field(default_factory=list)
    affected_groups: list = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = EVENT_STATUS(self.status)
        if isinstance(self.source_type, str):
            self.source_type = SOURCE_TYPE(self.source_type)
        if isinstance(self.scope, str):
            self.scope = EVENT_SCOPE(self.scope)
        if self.max_intensity <= 0.0:
            self.max_intensity = self.intensity or self.severity
        if self.intensity <= 0.0:
            self.intensity = self.max_intensity * 0.3  # start below peak

    @property
    def is_active(self) -> bool:
        return self.status in (
            EVENT_STATUS.TRIGGERED,
            EVENT_STATUS.GROWING,
            EVENT_STATUS.PEAK,
            EVENT_STATUS.DECAYING,
        )

    @property
    def is_recovery(self) -> bool:
        """v0.4.5 §26: Recovery events cannot participate in political/economic pressure."""
        return self.source_type == SOURCE_TYPE.RECOVERY

    def as_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "tick": self.tick,
            "type": self.type,
            "source": self.source,
            "source_type": self.source_type.value,
            "targets": list(self.targets),
            "severity": round(self.severity, 3),
            "effects": dict(self.effects),
            "description": self.description,
            "cause_event_id": self.cause_event_id,
            "cause_mechanism": self.cause_mechanism,
            "trigger_score": round(self.trigger_score, 4),
            "causal_confidence": round(self.causal_confidence, 4),
            "evidence": {k: round(v, 4) for k, v in self.evidence.items()},
            "scope": self.scope.value,
            "region": self.region,
            "affected_agents": list(self.affected_agents),
            "affected_groups": list(self.affected_groups),
            "intensity": round(self.intensity, 3),
            "max_intensity": round(self.max_intensity, 3),
            "duration": self.duration,
            "age": self.age,
            "decay_rate": self.decay_rate,
            "status": self.status.value,
        }


class EventChain:
    """A registry of events + causal links for one society."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.links: list[tuple[str, str]] = []  # (cause_event_id, effect_event_id)
        self._counter = 0

    def add(self, event: Event) -> Event:
        if not event.event_id:
            self._counter += 1
            event.event_id = f"event_{self._counter:05d}"
        self.events.append(event)
        if event.cause_event_id:
            self.links.append((event.cause_event_id, event.event_id))
        return event

    def make(
        self,
        tick: int,
        type: str,
        *,
        source: str = "system",
        targets: Optional[list] = None,
        severity: float = 0.0,
        effects: Optional[dict] = None,
        description: str = "",
        cause_event_id: Optional[str] = None,
        duration: Optional[int] = None,
        intensity: Optional[float] = None,
        source_type: Optional[SOURCE_TYPE] = None,
        trigger_score: float = 0.0,
        causal_confidence: float = 0.0,
        cause_mechanism: str = "",
        evidence: Optional[dict] = None,
        scope: Optional[EVENT_SCOPE] = None,
        region: Optional[str] = None,
    ) -> Event:
        # Auto-detect source_type from event type if not provided
        if source_type is None:
            source_type = EVENT_SOURCE_MAP.get(type, SOURCE_TYPE.ENDOGENOUS)
        # Auto-detect scope if not provided
        if scope is None:
            scope = EVENT_SCOPE.REGIONAL

        return self.add(
            Event(
                event_id="",
                tick=tick,
                type=type,
                source=source,
                targets=targets or [],
                severity=severity,
                effects=effects or {},
                description=description or type,
                cause_event_id=cause_event_id,
                intensity=intensity if intensity is not None else severity,
                max_intensity=severity if severity > 0 else 0.5,
                duration=duration if duration is not None else 20,
                source_type=source_type,
                trigger_score=trigger_score,
                causal_confidence=causal_confidence,
                cause_mechanism=cause_mechanism,
                evidence=evidence or {},
                scope=scope,
                region=region,
            )
        )

    def recent(self, n: int = 100) -> list[Event]:
        return self.events[-n:]

    def active(self) -> list[Event]:
        """All events still in an active lifecycle state."""
        return [e for e in self.events if e.is_active]

    def descendants(self, event_id: str, depth: int = 0) -> list[dict]:
        """Return the causality sub-tree rooted at event_id (for the chain UI)."""
        if depth > 12:
            return []
        children = []
        for cause, effect in self.links:
            if cause == event_id:
                ev = self.get(effect)
                if ev:
                    node = {
                        "event_id": ev.event_id,
                        "type": ev.type,
                        "tick": ev.tick,
                        "severity": ev.severity,
                        "status": ev.status.value,
                        "description": ev.description,
                        "children": self.descendants(ev.event_id, depth + 1),
                    }
                    children.append(node)
        return children

    def get(self, event_id: str) -> Optional[Event]:
        for e in self.events:
            if e.event_id == event_id:
                return e
        return None

    def as_graph(self) -> dict:
        nodes = [
            {"id": e.event_id, "type": e.type, "tick": e.tick,
             "severity": e.severity, "status": e.status.value}
            for e in self.events
        ]
        edges = [{"source": c, "target": e} for c, e in self.links]
        return {"nodes": nodes, "edges": edges}

    # v0.4.5: Event ecology queries
    def by_source_type(self, source_type: SOURCE_TYPE) -> list[Event]:
        """Return events of a given source type."""
        return [e for e in self.events if e.source_type == source_type]

    def endogenous_count(self) -> int:
        return len(self.by_source_type(SOURCE_TYPE.ENDOGENOUS))

    def exogenous_count(self) -> int:
        return len(self.by_source_type(SOURCE_TYPE.EXOGENOUS))

    def recovery_count(self) -> int:
        return len(self.by_source_type(SOURCE_TYPE.RECOVERY))

    def uncaused_count(self) -> int:
        """v0.4.5 §29: Endogenous events without causal evidence (should be 0)."""
        return sum(
            1 for e in self.events
            if e.source_type == SOURCE_TYPE.ENDOGENOUS and not e.cause_event_id and not e.evidence
        )
