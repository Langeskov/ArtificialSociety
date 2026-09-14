"""Society — one independent artificial-society instance (§2.1)."""

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
from ..dynamics.equilibrium import DynamicEquilibriumMonitor
from ..economy.population import DEFAULT_STRUCTURE, normalize_structure, PopulationSnapshot
from ..economy.labor import LaborMarket, create_initial_jobs
from ..economy.production_unit import create_initial_units, assign_workers_to_units


@dataclass
class Society:
    society_id: str
    config: dict = field(default_factory=dict)
    seed: int = 0
    clock: Clock = field(default_factory=Clock)
    agents: list[Agent] = field(default_factory=list)
    events: EventChain = field(default_factory=EventChain)
    status: str = "created"
    speed: float = 1.0
    metrics_history: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    production_multiplier: float = 1.0
    rng: Optional[random.Random] = None
    collapse_detector: Optional[CollapseDetector] = None
    _network: Optional[dict] = None
    _agent_map: Optional[dict] = None
    groups: GroupRegistry = field(default_factory=GroupRegistry)
    information_messages: list = field(default_factory=list)
    social_state: str = "NORMAL"
    resource_ledger: ResourceLedger = field(default_factory=ResourceLedger)
    regions: Optional[RegionRegistry] = None
    crisis_manager: CrisisManager = field(default_factory=CrisisManager)
    labor_market: object = None
    production_units: list = field(default_factory=list)
    initial_structure: object = None
    agent_unit_map: dict = field(default_factory=dict)
    crisis_memory: CrisisMemory = field(default_factory=CrisisMemory)
    oscillation_detector: OscillationDetector = field(default_factory=OscillationDetector)
    feedback_diagnostics: FeedbackDiagnostics = field(default_factory=FeedbackDiagnostics)
    production_disruption: float = 0.0
    equilibrium_monitor: object = None
    resource_flow: dict = field(default_factory=lambda: {
        "food_produced": 0.0, "food_consumed": 0.0,
        "food_traded_in": 0.0, "food_traded_out": 0.0,
        "energy_produced": 0.0, "energy_consumed": 0.0,
        "money_earned": 0.0, "money_taxed": 0.0,
    })
    _equilibrium_last_tick: int = -1
    _equilibrium_last_event_count: int = 0
    _equilibrium_group_state: dict = field(default_factory=dict)
    _equilibrium_employment_state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.clock = Clock(
            ticks_per_day=self.config.get("ticks_per_day", 100),
            days_per_month=self.config.get("days_per_month", 30),
            months_per_year=self.config.get("months_per_year", 12),
        )
        self.rng = random.Random(self.seed)
        if not self.agents and self.config.get("population"):
            self.agents = generate_population(self.config["population"], self.seed, self.config)
        self._agent_map = {a.id: a for a in self.agents}

        anchor_cfg = self.config.get("politics", {}).get("anchor", {})
        anchor_days = float(anchor_cfg.get("adaptation_days", 3650))
        anchor_long = float(anchor_cfg.get("long_run_strength", 0.005))
        for agent in self.agents:
            agent._anchor_adapt_days = max(1.0, anchor_days)
            agent._anchor_long_run_strength = max(0.0, anchor_long)
            agent.status["_structural_signature"] = (
                getattr(agent, "sector", "unemployed"),
                getattr(agent, "location", "A"),
                getattr(agent, "employer", None),
            )

        region_ids = self.config.get("regions", {}).get("list", ["A", "B", "C"])
        self.regions = RegionRegistry(region_ids)

        if self.agents:
            pop_s = self.config.get("society", {}).get("population_structure", DEFAULT_STRUCTURE)
            pop_s = normalize_structure(pop_s)
            self.initial_structure = PopulationSnapshot.from_agents(self.agents)
            self.labor_market = LaborMarket()
            self.labor_market.job_openings = create_initial_jobs(self.agents, pop_s, self.config, self.rng)
            self.production_units = create_initial_units(self.agents, pop_s, region_ids, self.config, self.rng)
            self.agent_unit_map = assign_workers_to_units(self.agents, self.production_units, self.rng)
            self.labor_market.bootstrap_employment(self.agents, self.rng)
            self.labor_market.update_demand(self.agents)
            for agent in self.agents:
                agent._labor_market = self.labor_market
                agent.status["_structural_signature"] = (
                    getattr(agent, "sector", "unemployed"),
                    getattr(agent, "location", "A"),
                    getattr(agent, "employer", None),
                )

        self.crisis_manager.configure(self.config)
        self.equilibrium_monitor = DynamicEquilibriumMonitor()

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

    def _update_equilibrium(self, metrics: dict) -> None:
        """Update the long-run monitor exactly once per simulation tick."""
        if self.equilibrium_monitor is None or self.clock.tick <= self._equilibrium_last_tick:
            return
        alive = [a for a in self.agents if a.alive]
        n = len(alive)
        if n == 0:
            return
        event_delta = max(0, len(self.events.events) - self._equilibrium_last_event_count)
        group_changed = 0
        employment_changed = 0
        next_groups = {}
        next_employment = {}
        for a in alive:
            group_sig = getattr(a.identity, "primary_group", None)
            emp_sig = (getattr(a, "sector", "unemployed"), getattr(a, "employer", None), getattr(a, "location", "A"))
            next_groups[a.id] = group_sig
            next_employment[a.id] = emp_sig
            if a.id in self._equilibrium_group_state and self._equilibrium_group_state[a.id] != group_sig:
                group_changed += 1
            if a.id in self._equilibrium_employment_state and self._equilibrium_employment_state[a.id] != emp_sig:
                employment_changed += 1

        resource_values = [a.wealth() for a in alive]
        mean_resource = sum(resource_values) / n
        resource_variance = sum((v - mean_resource) ** 2 for v in resource_values) / n
        resource_variance = resource_variance / max(mean_resource * mean_resource, 1.0)
        political_velocity = (
            metrics.get("x_abs_velocity", 0.0)
            + metrics.get("y_abs_velocity", 0.0)
            + metrics.get("z_abs_velocity", 0.0)
        ) / 3.0
        self.equilibrium_monitor.update(
            tick=self.clock.tick,
            ticks_per_day=self.clock.ticks_per_day,
            event_count=event_delta,
            political_variance=(
                metrics.get("political_variance_x", 0.0)
                + metrics.get("political_variance_y", 0.0)
                + metrics.get("political_variance_z", 0.0)
            ) / 3.0,
            political_velocity=political_velocity,
            resource_variance=resource_variance,
            group_turnover=group_changed / n,
            employment_turnover=employment_changed / n,
        )
        self._equilibrium_last_tick = self.clock.tick
        self._equilibrium_last_event_count = len(self.events.events)
        self._equilibrium_group_state = next_groups
        self._equilibrium_employment_state = next_employment

    def metrics(self) -> dict:
        metrics = compute_metrics(self.agents, self.events, self.clock.tick, self.config)
        self._update_equilibrium(metrics)
        eq = self.equilibrium_monitor.snapshot() if self.equilibrium_monitor else {"classification": "UNKNOWN"}
        metrics["equilibrium_classification"] = eq.get("classification", "UNKNOWN")
        metrics["political_freeze_score"] = eq.get("political_freeze_score", 0.0)
        return metrics

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
            "equilibrium": self.equilibrium_monitor.snapshot() if self.equilibrium_monitor else {"classification": "UNKNOWN"},
            "regions": self.regions.as_list() if self.regions else [],
            "metrics": self.metrics(),
            "config": self.config,
        }
