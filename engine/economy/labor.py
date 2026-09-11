"""Labor Market (v0.4.5.5).

The project already has occupations, job openings and production units. This
module keeps the existing abstractions and makes the LaborMarket the source of
truth for employment state instead of creating a second job system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import random

from .population import SECTORS, SECTOR_WAGE_MODIFIER

SECTOR_OCCUPATION = {
    "primary": "farmer",
    "secondary": "manufacturer",
    "tertiary": "service",
    "quaternary": "trader",
    "public": "government",
}


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
        """Update sector demand = open jobs / workers."""
        workers = {s: 0 for s in SECTORS}
        for a in agents:
            if a.alive:
                sector = getattr(a, "sector", "unemployed")
                workers[sector if sector in workers else "unemployed"] += 1

        openings = {s: 0 for s in SECTORS}
        for job in self.job_openings:
            if not job.filled and job.sector in openings:
                openings[job.sector] += 1

        for sector in SECTORS:
            self.sector_demand[sector] = openings[sector] / max(1, workers[sector])

    def compute_wage(self, sector: str, skill: float) -> float:
        """Wage = base × skill × sector modifier × demand modifier."""
        smod = SECTOR_WAGE_MODIFIER.get(sector, 1.0)
        demand = self.sector_demand.get(sector, 1.0)
        demand_factor = 1.0 + (demand - 1.0) * self.wage_adjustment_rate * 10
        return self.base_wage * max(0.1, skill) * smod * max(0.5, min(2.0, demand_factor))

    def find_jobs(self, agent, rng: random.Random) -> List[JobOpening]:
        """Find available jobs for an agent based on skill and region."""
        skills = getattr(agent, "skills", {}) or {}
        available = []
        for job in self.job_openings:
            if job.filled:
                continue
            region_penalty = 1.0 if job.region == getattr(agent, "location", "A") else 0.8
            skill = skills.get(job.sector, 0.0)
            if skill * region_penalty >= job.required_skill * 0.5:
                available.append(job)
        return available

    @staticmethod
    def _set_employed(agent, job: JobOpening) -> None:
        agent.sector = job.sector
        agent.employment_status = "employed"
        agent.employer = job.employer_id
        agent.occupation = job.occupation
        agent.status["wage_rate"] = round(job.wage, 4)

    @staticmethod
    def _set_unemployed(agent) -> None:
        agent.sector = "unemployed"
        agent.employment_status = "unemployed"
        agent.employer = None
        agent.occupation = "worker"
        agent.status["wage_rate"] = 0.0

    def bootstrap_employment(self, agents: List, rng: random.Random) -> Dict[str, str]:
        """Bind initially employed agents to real jobs once at simulation start."""
        self.update_demand(agents)
        assignments: Dict[str, str] = {}
        candidates = [
            a for a in agents
            if a.alive
            and getattr(a, "sector", "unemployed") != "unemployed"
            and not getattr(a, "employer", None)
        ]
        rng.shuffle(candidates)
        for agent in candidates:
            jobs = [j for j in self.find_jobs(agent, rng) if j.sector == getattr(agent, "sector", "")]
            if not jobs:
                continue
            skill = (getattr(agent, "skills", {}) or {}).get(agent.sector, 0.0)
            for job in jobs:
                job.wage = self.compute_wage(job.sector, skill)
            job = max(jobs, key=lambda j: j.wage)
            job.filled = True
            job.worker_id = agent.id
            self._set_employed(agent, job)
            assignments[agent.id] = job.id
        self.update_demand(agents)
        return assignments

    def hire(self, agents: List, rng: random.Random) -> Dict[str, str]:
        """Match unemployed agents to open jobs and synchronize employment."""
        self.update_demand(agents)
        hires: Dict[str, str] = {}
        unemployed = [
            a for a in agents
            if a.alive and getattr(a, "sector", "unemployed") == "unemployed"
        ]
        rng.shuffle(unemployed)

        for agent in unemployed:
            jobs = self.find_jobs(agent, rng)
            if not jobs:
                continue
            for job in jobs:
                skill = (getattr(agent, "skills", {}) or {}).get(job.sector, 0.0)
                job.wage = self.compute_wage(job.sector, skill)
            best = max(jobs, key=lambda j: j.wage)
            if best.filled:
                continue
            best.filled = True
            best.worker_id = agent.id
            self._set_employed(agent, best)
            hires[agent.id] = best.id

        self.update_demand(agents)
        return hires

    def release_worker(self, agent, agents_by_id: Optional[dict] = None) -> bool:
        """Release one worker and reopen their job."""
        for job in self.job_openings:
            if job.filled and job.worker_id == agent.id:
                job.filled = False
                job.worker_id = None
                self._set_unemployed(agent)
                return True
        return False

    def apply_market_stress(self, agents: List, rng: random.Random,
                            pressure: float,
                            layoff_threshold: float = 0.65,
                            layoff_fraction: float = 0.10) -> Dict[str, int]:
        """Apply small layoffs during sustained resource/economic stress."""
        result = {"laid_off": 0, "hired": 0}
        if pressure < layoff_threshold:
            return result

        employed = [a for a in agents if a.alive and a.employer]
        candidates = [a for a in employed if getattr(a, "sector", "") != "public"]
        rng.shuffle(candidates)
        count = max(1, int(len(candidates) * layoff_fraction)) if candidates else 0
        for agent in candidates[:count]:
            if self.release_worker(agent):
                result["laid_off"] += 1
        return result

    def rebalance(self, agents: List, rng: random.Random,
                  pressure: float, layoff_threshold: float = 0.65,
                  layoff_fraction: float = 0.10,
                  recovery_threshold: float = 0.45) -> Dict[str, int]:
        """Update the labor market without cancelling its own contraction.

        High pressure contracts employment. Hiring resumes only after pressure
        falls below a lower recovery threshold, producing real hysteresis.
        """
        if pressure >= layoff_threshold:
            return self.apply_market_stress(
                agents, rng, pressure, layoff_threshold, layoff_fraction
            )
        if pressure <= recovery_threshold:
            result = {"laid_off": 0, "hired": len(self.hire(agents, rng))}
            return result
        return {"laid_off": 0, "hired": 0}


def create_initial_jobs(agents: List, structure: Dict, cfg: Dict,
                        rng: random.Random) -> List[JobOpening]:
    """Create initial job openings proportional to sector size."""
    jobs = []
    n = len(agents)
    mult = cfg.get("labor", {}).get("jobs_multiplier", 1.2)
    jid = 0
    for sector, proportion in structure.items():
        if sector == "unemployed":
            continue
        n_jobs = max(1, int(n * proportion * mult))
        occupation = SECTOR_OCCUPATION.get(sector, "service")
        for i in range(n_jobs):
            jobs.append(JobOpening(
                id=f"job_{jid}",
                sector=sector,
                occupation=occupation,
                required_skill=0.2 + rng.random() * 0.3,
                wage=SECTOR_WAGE_MODIFIER.get(sector, 1.0),
                region=rng.choice(["A", "B", "C"]),
                employer_id=f"employer_{sector}_{i}",
            ))
            jid += 1
    return jobs
