"""v0.4.6 structural-dynamics coverage.

These tests intentionally exercise mechanisms that are supposed to create
endogenous variation without injecting ideological randomness.
"""

from types import SimpleNamespace
import random

from engine.agent.agent import Agent
from engine.agent.personality import Personality
from engine.agent.ideology import Ideology
from engine.agent.resources import Resources
from engine.economy.labor import LaborMarket, create_initial_jobs
from engine.economy.population import normalize_structure, DEFAULT_STRUCTURE
from engine.politics.politics import _social_conformity


def _agent(agent_id: str, sector: str = "primary", location: str = "A") -> Agent:
    a = Agent(
        id=agent_id,
        personality=Personality({
            "openness": 0.8,
            "trust": 0.4,
            "authority_preference": 0.5,
            "agreeableness": 0.5,
            "extraversion": 0.5,
            "empathy": 0.5,
            "risk_tolerance": 0.5,
            "conscientiousness": 0.5,
            "neuroticism": 0.5,
            "aggression": 0.5,
        }),
        ideology=Ideology(0.2, -0.1, 0.1),
        resources=Resources({
            "money": 200.0, "food": 100.0, "energy": 100.0,
            "property": 100.0, "influence": 2.0, "information": 10.0,
        }),
    )
    a.sector = sector
    a.location = location
    a.employment_status = "employed" if sector != "unemployed" else "unemployed"
    a.skills = {s: 0.5 for s in ("primary", "secondary", "tertiary", "quaternary", "public")}
    return a


def _market(agents):
    structure = normalize_structure(DEFAULT_STRUCTURE)
    cfg = {"labor": {"jobs_multiplier": 2.0}}
    market = LaborMarket()
    market.job_openings = create_initial_jobs(agents, structure, cfg, random.Random(42))
    market.bootstrap_employment(agents, random.Random(1))
    return market


def test_structural_conformity_is_heterogeneous():
    conforming = _agent("a1")
    conforming.personality.values["trust"] = 0.9
    reactant = _agent("a2")
    reactant.personality.values["trust"] = 0.1
    assert _social_conformity(conforming) > _social_conformity(reactant)


def test_training_changes_skill_endogenously():
    agents = [_agent("u1", "unemployed"), _agent("u2", "unemployed")]
    market = _market(agents)
    before = [dict(a.skills) for a in agents]
    trained = market.train(agents, random.Random(2), learning_rate=0.05, max_training_share=1.0)
    assert trained > 0
    assert any(a.skills != b for a, b in zip(agents, before))


def test_migration_moves_toward_regional_job_surplus():
    agents = [_agent("u1", "unemployed", "A")]
    market = _market(agents)
    for job in market.job_openings:
        job.filled = True
    target = market.job_openings[0]
    target.filled = False
    target.region = "B"
    # Ensure the local region has no open jobs while B does.
    moved = market.migrate(agents, ["A", "B"], random.Random(3), migration_cost=10.0, max_share=1.0)
    assert moved == 1
    assert agents[0].location == "B"


def test_enterprise_capacity_expands_when_sector_is_starved():
    agents = [_agent(f"u{i}", "unemployed") for i in range(20)]
    market = _market(agents)
    for job in market.job_openings:
        job.filled = True
    market.sector_demand = {s: 0.0 for s in DEFAULT_STRUCTURE}
    market.sector_demand["secondary"] = 3.0
    before = len(market.job_openings)
    result = market.evolve_job_capacity(
        agents,
        ["A", "B", "C"],
        random.Random(4),
        creation_threshold=1.5,
        closure_threshold=0.01,
        max_changes=2,
    )
    assert result["jobs_created"] > 0
    assert len(market.job_openings) > before
