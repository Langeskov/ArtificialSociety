"""Labor Market (v0.4.4 §11-16).

Handles job openings, hiring, unemployment, wages, sector demand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import random

from .population import SECTORS, SECTOR_WAGE_MODIFIER


@dataclass
class JobOpening:
    id: str
    sector: str
    occupation: str
    required_skill: float = 0.3
    wage: float = 1.0
    region: str = "A"
    employer_id: str = ""
    filled: bool = False
    worker_id: Optional[str] = None


@dataclass
class LaborMarket:
    job_openings: List[JobOpening] = field(default_factory=list)
    base_wage: float = 1.0
    wage_adjustment_rate: float = 0.02
    sector_demand: Dict[str, float] = field(default_factory=dict)

    def update_demand(self, agents: List) -> None:
        """Update sector demand = open_jobs / workers (§16)."""
        workers = {s: 0 for s in SECTORS}
        for a in agents:
            if a.alive:
                workers[getattr(a, "sector", "unemployed")] += 1
        openings = {s: 0 for s in SECTORS}
        for j in self.job_openings:
            if not j.filled:
                openings[j.sector] += 1
        for s in SECTORS:
            w = max(1, workers[s])
            self.sector_demand[s] = openings[s] / w

    def compute_wage(self, sector: str, skill: float) -> float:
        """wage = base * skill * sector_mod * demand_mod (§15)."""
        smod = SECTOR_WAGE_MODIFIER.get(sector, 1.0)
        dmod = self.sector_demand.get(sector, 1.0)
        df = 1.0 + (dmod - 1.0) * self.wage_adjustment_rate * 10
        return self.base_wage * max(0.1, skill) * smod * max(0.5, min(2.0, df))

    def find_jobs(self, agent, rng: random.Random) -> List[JobOpening]:
        """Find available jobs for agent based on skill match (§13)."""
        skills = getattr(agent, "skills", {}) or {}
        available = []
        for j in self.job_openings:
            if j.filled:
                continue
            sk = skills.get(j.sector, 0.0)
            if sk >= j.required_skill * 0.5:
                available.append(j)
        return available

    def hire(self, agents: List, rng: random.Random) -> Dict[str, str]:
        """Match unemployed agents to jobs (§14). Returns {agent_id: job_id}."""
        hires = {}
        unemployed = [a for a in agents if a.alive and getattr(a, "sector", "unemployed") == "unemployed"]
        for a in unemployed:
            jobs = self.find_jobs(a, rng)
            if not jobs:
                continue
            best = max(jobs, key=lambda j: j.wage)
            if not best.filled:
                best.filled = True
                best.worker_id = a.id
                hires[a.id] = best.id
        return hires


def create_initial_jobs(agents: List, structure: Dict, cfg: Dict, rng: random.Random) -> List[JobOpening]:
    """Create initial job openings proportional to sector size (§12)."""
    jobs = []
    n = len(agents)
    mult = cfg.get("labor", {}).get("jobs_multiplier", 1.2)
    jid = 0
    for sector, prop in structure.items():
        if sector == "unemployed":
            continue
        n_jobs = max(1, int(n * prop * mult))
        for i in range(n_jobs):
            jobs.append(JobOpening(
                id=f"job_{jid}", sector=sector, occupation=f"{sector}_worker",
                required_skill=0.2 + rng.random() * 0.3,
                wage=1.0 * SECTOR_WAGE_MODIFIER.get(sector, 1.0),
                region=rng.choice(["A", "B", "C"]),
                employer_id=f"employer_{sector}_{i}",
            ))
            jid += 1
    return jobs
