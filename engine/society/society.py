"""Society — one independent artificial-society instance (§2.1).

A Society owns its clock, agents, event chain, config and metrics history.
Multiple societies run concurrently inside the SimulationEngine.

v0.2: additionally owns a persistent RNG (determinism §33), a production
multiplier (recovery §13), and a CollapseDetector (§26).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import random
import time
from typing import Optional

from ..simulation.clock import Clock
from ..agent.agent import Agent
from ..agent.generator import generate_population
from ..event.event import EventChain
from ..metrics.metrics import compute_metrics
from ..dynamics.stability import CollapseDetector
from ..group.group import GroupRegistry


@dataclass
class Society:
    society_id: str
    config: dict = field(default_factory=dict)
    seed: int = 0
    clock: Clock = field(default_factory=Clock)
    agents: list[Agent] = field(default_factory=list)
    events: EventChain = field(default_factory=EventChain)
    status: str = "created"     # created | running | paused | finished
    speed: float = 1.0          # ticks per engine step
    metrics_history: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    # v0.2 dynamics state
    production_multiplier: float = 1.0
    rng: Optional[random.Random] = None
    collapse_detector: Optional[CollapseDetector] = None
    _network: Optional[dict] = None
    _agent_map: Optional[dict] = None
    # v0.4 social layer
    groups: GroupRegistry = field(default_factory=GroupRegistry)      # §70
    information_messages: list = field(default_factory=list)          # §70
    social_state: str = "NORMAL"                                      # §54 诊断分类

    def __post_init__(self) -> None:
        self.clock = Clock(
            ticks_per_day=self.config.get("ticks_per_day", 100),
            days_per_month=self.config.get("days_per_month", 30),
            months_per_year=self.config.get("months_per_year", 12),
        )
        # Persistent, seed-derived RNG → deterministic replay (§33).
        self.rng = random.Random(self.seed)
        if not self.agents and self.config.get("population"):
            self.agents = generate_population(self.config["population"], self.seed, self.config)
        self._agent_map = {a.id: a for a in self.agents}

        # Collapse detector configured from the stability section (§26).
        stab = self.config.get("stability", {})
        self.collapse_detector = CollapseDetector(
            variance_threshold=stab.get("collapse_variance_threshold", 0.02),
            consecutive_ticks=stab.get("collapse_consecutive_ticks", 20),
            temperature_critical=stab.get("temperature_critical", 0.85),
        )

    def id(self) -> str:
        return self.society_id

    def agent_map(self) -> dict[str, Agent]:
        if self._agent_map is None:
            self._agent_map = {a.id: a for a in self.agents}
        return self._agent_map

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        return self.agent_map().get(agent_id)

    def metrics(self) -> dict:
        return compute_metrics(self.agents, self.events, self.clock.tick, self.config)

    def snapshot(self) -> dict:
        return {
            "society_id": self.society_id,
            "seed": self.seed,
            "status": self.status,
            "speed": self.speed,
            "clock": self.clock.snapshot(),
            "agent_count": len(self.agents),
            "alive_count": sum(1 for a in self.agents if a.alive),
            "event_count": len(self.events.events),
            "production_multiplier": round(self.production_multiplier, 4),
            "group_count": len(self.groups.active()),
            "information_count": len(self.information_messages),
            "social_state": self.social_state,
            "metrics": self.metrics(),
            "config": self.config,
        }
