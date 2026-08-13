"""Event + EventChain — the causality backbone of the simulation (§15, §16).

v0.2: events carry a full lifecycle (§10, §11) — intensity/duration/age/decay
so they are *not* permanent states. event_links still encode cause → effect.
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


EVENT_TYPES: tuple[str, ...] = (
    "economic_crisis",
    "food_shortage",
    "market_panic",
    "unemployment",
    "protest",
    "government_response",
    "political_movement",
    "leadership_change",
    "alliance",
    "conflict",
    "resource_boom",
    "scandal",
    "natural_disaster",
    "technology_breakthrough",
    "migration",
    "election",
    "war",
    "reform",
    "recovery",
    "food_stabilization",
)


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

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            self.status = EVENT_STATUS(self.status)
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

    def as_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "tick": self.tick,
            "type": self.type,
            "source": self.source,
            "targets": list(self.targets),
            "severity": round(self.severity, 3),
            "effects": dict(self.effects),
            "description": self.description,
            "cause_event_id": self.cause_event_id,
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
    ) -> Event:
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
