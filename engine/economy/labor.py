"""Labor Market (v0.4.6).

Employment is the first structural layer: jobs, wages, training, migration and
endogenous expansion/contraction of job capacity.
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
    next_job_id: int = 0

    def update_demand(self, agents: List) -> None:
        workers = {s: 0 for s in SECTORS}
        for a in agents:
            if getattr(a, "alive", True):
                sector = getattr(a, "sector", "unemployed")
                workers[sector if sector in workers else "unemployed"] += 1
        openings = {s: 0 for s in SECTORS}
        for job in self.job_openings:
            if not job.filled and job.sector in openings:
                openings[job.sector] += 1
        for sector in SECTORS:
            self.sector_demand[sector] = openings[sector] / max(1, workers[sector])

    def compute_wage(self, sector: str, skill: float) -> float:
        smod = SECTOR_WAGE_MODIFIER.get(sector, 1.0)
        demand = self.sector_demand.get(sector, 1.0)
        demand_factor = 1.0 + (demand - 1.0) * self.wage_adjustment_rate * 10
        return self.base_wage * max(0.1, skill) * smod * max(0.5, min(2.0, demand_factor))

    def find_jobs(self, agent, rng: random.Random) -> List[JobOpening]:
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
        if not hasattr(agent, "status") or agent.status is None:
            agent.status = {}
        agent.sector = job.sector
        agent.employment_status = "employed"
        agent.employer = job.employer_id
        agent.occupation = job.occupation
        agent.status["wage_rate"] = round(job.wage, 4)

    @staticmethod
    def _set_unemployed(agent) -> None:
        if not hasattr(agent, "status") or agent.status is None:
            agent.status = {}
        agent.sector = "unemployed"
        agent.employment_status = "unemployed"
        agent.employer = None
        agent.occupation = "worker"
        agent.status["wage_rate"] = 0.0

    def bootstrap_employment(self, agents: List, rng: random.Random) -> Dict[str, str]:
        self.next_job_id = max(self.next_job_id, len(self.job_openings))
        self.update_demand(agents)
        assignments: Dict[str, str] = {}
        candidates = [a for a in agents if getattr(a, "alive", True) and getattr(a, "sector", "unemployed") != "unemployed" and not getattr(a, "employer", None)]
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
        self.update_demand(agents)
        hires: Dict[str, str] = {}
        unemployed = [a for a in agents if getattr(a, "alive", True) and getattr(a, "sector", "unemployed") == "unemployed"]
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
        for job in self.job_openings:
            if job.filled and job.worker_id == agent.id:
                job.filled = False
                job.worker_id = None
                self._set_unemployed(agent)
                return True
        return False

    def apply_market_stress(self, agents: List, rng: random.Random, pressure: float,
                            layoff_threshold: float = 0.65,
                            layoff_fraction: float = 0.10) -> Dict[str, int]:
        result = {"laid_off": 0, "hired": 0}
        if pressure < layoff_threshold:
            return result
        employed = [a for a in agents if getattr(a, "alive", True) and getattr(a, "employer", None)]
        candidates = [a for a in employed if getattr(a, "sector", "") != "public"]
        rng.shuffle(candidates)
        count = max(1, int(len(candidates) * layoff_fraction)) if candidates else 0
        for agent in candidates[:count]:
            if self.release_worker(agent):
                result["laid_off"] += 1
        return result

    def rebalance(self, agents: List, rng: random.Random, pressure: float,
                  layoff_threshold: float = 0.65,
                  layoff_fraction: float = 0.10,
                  recovery_threshold: float = 0.45) -> Dict[str, int]:
        if pressure >= layoff_threshold:
            return self.apply_market_stress(agents, rng, pressure, layoff_threshold, layoff_fraction)
        if pressure <= recovery_threshold:
            return {"laid_off": 0, "hired": len(self.hire(agents, rng))}
        return {"laid_off": 0, "hired": 0}

    def train(self, agents: List, rng: random.Random, learning_rate: float = 0.01,
              max_training_share: float = 0.08) -> int:
        self.update_demand(agents)
        candidates = [a for a in agents if getattr(a, "alive", True) and (getattr(a, "sector", "unemployed") == "unemployed" or getattr(a, "education_level", 0.5) < 0.7)]
        rng.shuffle(candidates)
        limit = max(1, int(len(agents) * max_training_share)) if candidates else 0
        trained = 0
        for agent in candidates[:limit]:
            skills = getattr(agent, "skills", None)
            if skills is None:
                agent.skills = {}
                skills = agent.skills
            sector_scores = sorted(
                ((s, self.sector_demand.get(s, 0.0) * 0.7 + skills.get(s, 0.0) * 0.3) for s in SECTORS if s != "unemployed"),
                key=lambda item: item[1], reverse=True,
            )
            if not sector_scores:
                continue
            target = sector_scores[0][0]
            current = float(skills.get(target, 0.0))
            if current >= 1.0:
                continue
            skills[target] = min(1.0, current + learning_rate)
            agent.education_level = min(1.0, float(getattr(agent, "education_level", 0.5)) + learning_rate * 0.5)
            trained += 1
        return trained

    def migrate(self, agents: List, regions: List[str], rng: random.Random,
                migration_cost: float = 30.0, max_share: float = 0.02) -> int:
        """Move a small share of unemployed/underemployed agents toward open regional jobs."""
        self.update_demand(agents)
        open_by_region = {r: 0 for r in regions}
        for job in self.job_openings:
            if not job.filled and job.region in open_by_region:
                open_by_region[job.region] += 1
        candidates = [a for a in agents if getattr(a, "alive", True) and getattr(a, "sector", "unemployed") == "unemployed"]
        rng.shuffle(candidates)
        moved = 0
        limit = max(1, int(len(agents) * max_share)) if candidates else 0
        for agent in candidates:
            if moved >= limit:
                break
            here = getattr(agent, "location", regions[0])
            best = max(open_by_region, key=open_by_region.get) if open_by_region else here
            if best == here or open_by_region.get(best, 0) <= open_by_region.get(here, 0):
                continue
            money = agent.resources.available("money")
            if money < migration_cost:
                continue
            agent.resources.add("money", -migration_cost)
            agent.location = best
            moved += 1
        return moved

    def evolve_job_capacity(self, agents: List, regions: List[str], rng: random.Random,
                            creation_threshold: float = 1.5, closure_threshold: float = 0.10,
                            max_changes: int = 5) -> Dict[str, int]:
        """Endogenous enterprise capacity: add jobs where demand is high and close idle capacity.

        Preserve an explicitly supplied demand signal for this decision. The
        daily simulation normally refreshes sector_demand before calling this,
        while isolated mechanism tests may intentionally seed it directly.
        """
        had_demand = bool(self.sector_demand)
        if not had_demand:
            self.update_demand(agents)

        created = 0
        closed = 0
        sector_rank = sorted(
            ((s, self.sector_demand.get(s, 0.0)) for s in SECTORS if s != "unemployed"),
            key=lambda item: item[1], reverse=True,
        )
        for sector, demand in sector_rank:
            if created >= max_changes or demand < creation_threshold:
                continue
            region = rng.choice(regions)
            idx = self.next_job_id
            self.next_job_id += 1
            self.job_openings.append(JobOpening(
                id=f"job_{idx}",
                sector=sector,
                occupation=SECTOR_OCCUPATION.get(sector, "service"),
                required_skill=0.25 + rng.random() * 0.25,
                wage=SECTOR_WAGE_MODIFIER.get(sector, 1.0),
                region=region,
                employer_id=f"enterprise_{sector}_{idx}",
            ))
            created += 1

        idle_by_sector = {s: [] for s in SECTORS}
        for job in self.job_openings:
            if not job.filled and job.sector in idle_by_sector:
                idle_by_sector[job.sector].append(job)
        for sector, idle_jobs in idle_by_sector.items():
            if closed >= max_changes or self.sector_demand.get(sector, 0.0) > closure_threshold:
                continue
            for job in idle_jobs[:-1] if len(idle_jobs) > 1 else []:
                if closed >= max_changes:
                    break
                try:
                    self.job_openings.remove(job)
                    closed += 1
                except ValueError:
                    pass

        self.next_job_id = max(self.next_job_id, len(self.job_openings))
        if not had_demand:
            self.update_demand(agents)
        return {"jobs_created": created, "jobs_closed": closed}


def create_initial_jobs(agents: List, structure: Dict, cfg: Dict,
                        rng: random.Random) -> List[JobOpening]:
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
