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
from ..economy.transaction import ResourceLedger
from ..economy.region import RegionRegistry
from ..crisis.tracker import CrisisManager
from ..crisis.memory import CrisisMemory
from ..crisis.diagnostics import OscillationDetector, FeedbackDiagnostics


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
    # v0.4.1 resource layer
    resource_ledger: ResourceLedger = field(default_factory=ResourceLedger)  # §62
    regions: Optional[RegionRegistry] = None                            # §31
    # v0.4.2: crisis state machine + resource flow accounting
    crisis_manager: CrisisManager = field(default_factory=CrisisManager)
    crisis_memory: CrisisMemory = field(default_factory=CrisisMemory)
    oscillation_detector: OscillationDetector = field(default_factory=OscillationDetector)
    feedback_diagnostics: FeedbackDiagnostics = field(default_factory=FeedbackDiagnostics)
    production_disruption: float = 0.0  # v0.4.2 §19: 临时干扰（非永久 ratchet）
    resource_flow: dict = field(default_factory=lambda: {
        "food_produced": 0.0, "food_consumed": 0.0,
        "food_traded_in": 0.0, "food_traded_out": 0.0,
        "energy_produced": 0.0, "energy_consumed": 0.0,
        "money_earned": 0.0, "money_taxed": 0.0,
    })

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

        # v0.4.1: 区域资源模型（§31）
        region_ids = self.config.get("regions", {}).get("list", ["A", "B", "C"])
        self.regions = RegionRegistry(region_ids)

        # v0.4.4: crisis thresholds/cooldowns are config-driven, including
        # economic_crisis (which previously had no stateful cooldown).
        self.crisis_manager.configure(self.config)

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
            # v0.4.1: 区域资源（§50）
            "regions": self.regions.as_list() if self.regions else [],
            "metrics": self.metrics(),
            "config": self.config,
        }
