"""v0.4.5.5 employment lifecycle tests.

These tests cover the new connection layer only. Full long-run validation remains
an explicit local-machine task, per the project's testing workflow.
"""

import random

from engine.economy.labor import LaborMarket, create_initial_jobs
from engine.economy.population import DEFAULT_STRUCTURE, normalize_structure


class DummyResources:
    def __init__(self):
        self.values = {"money": 100.0, "food": 100.0, "energy": 80.0}


class DummyAgent:
    def __init__(self, agent_id, sector="unemployed", location="A"):
        self.id = agent_id
        self.alive = True
        self.sector = sector
        self.location = location
        self.skills = {
            "primary": 0.8,
            "secondary": 0.8,
            "tertiary": 0.8,
            "quaternary": 0.8,
            "public": 0.8,
            "unemployed": 0.0,
        }
        self.employment_status = "unemployed" if sector == "unemployed" else "self_employed"
        self.occupation = "worker"
        self.employer = None
        self.status = {}
        self.resources = DummyResources()


def _market(agents):
    structure = normalize_structure(DEFAULT_STRUCTURE)
    cfg = {"labor": {"jobs_multiplier": 2.0}}
    market = LaborMarket()
    market.job_openings = create_initial_jobs(agents, structure, cfg, random.Random(42))
    return market


def test_bootstrap_binds_existing_workers():
    agents = [DummyAgent("a1", "primary"), DummyAgent("a2", "secondary"), DummyAgent("u1")]
    market = _market(agents)

    assignments = market.bootstrap_employment(agents, random.Random(1))

    assert "a1" in assignments
    assert "a2" in assignments
    assert agents[0].employment_status == "employed"
    assert agents[0].employer is not None
    assert agents[0].occupation == "farmer"
    assert agents[1].occupation == "manufacturer"
    assert agents[2].employment_status == "unemployed"


def test_hire_reopens_unemployment_path():
    agents = [DummyAgent("u1")]
    market = _market(agents)

    hires = market.hire(agents, random.Random(2))

    assert hires
    assert agents[0].employment_status == "employed"
    assert agents[0].sector != "unemployed"
    assert agents[0].employer is not None


def test_market_stress_causes_limited_layoffs_and_reemployment():
    agents = [DummyAgent(f"a{i}", "primary") for i in range(10)]
    market = _market(agents)
    market.bootstrap_employment(agents, random.Random(3))

    result = market.apply_market_stress(
        agents, random.Random(4), pressure=0.9,
        layoff_threshold=0.65, layoff_fraction=0.2,
    )

    assert result["laid_off"] > 0
    unemployed = [a for a in agents if a.sector == "unemployed"]
    assert unemployed

    hires = market.hire(agents, random.Random(5))
    assert len(hires) == len(unemployed)
    assert all(a.sector != "unemployed" for a in agents)


def test_rebalance_has_contraction_and_recovery_hysteresis():
    agents = [DummyAgent(f"a{i}", "primary") for i in range(10)]
    market = _market(agents)
    market.bootstrap_employment(agents, random.Random(6))

    stressed = market.rebalance(agents, random.Random(7), pressure=0.9)
    assert stressed["laid_off"] > 0
    assert stressed["hired"] == 0
    unemployment_after_stress = sum(a.sector == "unemployed" for a in agents)
    assert unemployment_after_stress > 0

    neutral = market.rebalance(agents, random.Random(8), pressure=0.55)
    assert neutral["hired"] == 0
    assert sum(a.sector == "unemployed" for a in agents) == unemployment_after_stress

    recovering = market.rebalance(agents, random.Random(9), pressure=0.30)
    assert recovering["hired"] > 0
    assert sum(a.sector == "unemployed" for a in agents) < unemployment_after_stress
