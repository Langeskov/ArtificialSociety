"""Population generator — turn a *social-structure* config into N agents.

When N is small the user can hand-edit agents; above a threshold the system
generates agents from distributions (§6): "the user configures population
structure, not individual agents."

Config (the `population` section of a society config):
    {
      "count": 1000,
      "ideology_distribution": {"liberal": 0.3, "conservative": 0.3, "socialist": 0.2,
                                "libertarian": 0.1, "authoritarian": 0.1},
      "personality_distribution": {"agreeableness": {"high": 0.3, "neutral": 0.4, "low": 0.3}},
      "initial_resources": {"money": {"mean": 500, "sigma": 200}},
      "age_range": [18, 75],
      "ai_levels": {"level0": 0.90, "level1": 0.09, "level2": 0.0, "level3": 0.01},
    }
"""

from __future__ import annotations

import random
from typing import Optional

from .agent import Agent
from .personality import generate as gen_personality
from .ideology import sample_ideology, IDEOLOGY_TEMPLATES
from .resources import generate as gen_resources
from ..identity.update import init_identity
from ..economy.population import assign_sector, compute_skills, DEFAULT_STRUCTURE, normalize_structure


def _pick_ideology(distribution: Optional[dict], rng: random.Random) -> str:
    if not distribution:
        return "centrist"
    labels = list(distribution.keys())
    weights = [float(distribution.get(l, 0.0)) for l in labels]
    total = sum(weights)
    if total <= 0:
        return "centrist"
    r = rng.random() * total
    acc = 0.0
    for label, w in zip(labels, weights):
        acc += w
        if r < acc:
            return label
    return labels[-1]


def _pick_ai_level(ai_levels: Optional[dict], rng: random.Random) -> int:
    if not ai_levels:
        # Default: 90% rule-based, 9% statistical, 1% LLM (§26)
        ai_levels = {"level0": 0.90, "level1": 0.09, "level2": 0.0, "level3": 0.01}
    r = rng.random()
    acc = 0.0
    for lvl in range(5):
        acc += float(ai_levels.get(f"level{lvl}", 0.0))
        if r < acc:
            return lvl
    return 0


def generate_population(pop_cfg: dict, seed: int = 0, dynamics_cfg: dict | None = None) -> list[Agent]:
    """Generate the full agent population for one society."""
    rng = random.Random(seed)
    count = int(pop_cfg.get("count", 1000))
    ideology_dist = pop_cfg.get("ideology_distribution")
    personality_dist = pop_cfg.get("personality_distribution")
    initial_resources = pop_cfg.get("initial_resources")
    age_lo, age_hi = pop_cfg.get("age_range", [18, 75])
    ai_levels = pop_cfg.get("ai_levels")

    # v0.2: political inertia sampled per agent (§4)
    pol = (dynamics_cfg or {}).get("politics", {})
    inertia_lo, inertia_hi = pol.get("inertia_range", [0.85, 0.98])

    # v0.4: 区域分配（§47）— 用独立 RNG，避免扰动人口生成主 RNG 序列（保持 v0.3.1 确定性）
    regions = (dynamics_cfg or {}).get("regions", {}).get("list", ["A", "B", "C"])
    loc_rng = random.Random(seed + 987654)

    agents: list[Agent] = []
    for i in range(count):
        label = _pick_ideology(ideology_dist, rng)
        a = Agent(
            id=f"agent_{i:06d}",
            age=rng.randint(int(age_lo), int(age_hi)),
            personality=gen_personality(personality_dist, rng),
            ideology=sample_ideology(label, rng),
            resources=gen_resources(initial_resources, rng),
            ai_level=_pick_ai_level(ai_levels, rng),
            political_inertia=rng.uniform(inertia_lo, inertia_hi),
        )
        a.identity = init_identity(a)          # v0.4: 从人格初始化身份（§16，无 RNG）
        a.location = loc_rng.choice(regions)    # v0.4: 初始区域（§47，独立 RNG）
        # v0.4.4: sector + skills + education
        pop_structure = (dynamics_cfg or {}).get('society', {}).get('population_structure', DEFAULT_STRUCTURE)
        pop_structure = normalize_structure(pop_structure)
        region_endow = (dynamics_cfg or {}).get('regions', {}).get('endowments', {}).get(a.location, {})
        a.education_level = max(0.0, min(1.0, rng.gauss(0.5, 0.2)))
        a.sector = assign_sector(a.personality, a.education_level, region_endow, rng, pop_structure)
        a.skills = compute_skills(a.sector, a.personality, rng)
        if a.sector != 'unemployed':
            a.employment_status = 'employed'
        agents.append(a)
    return agents


# Re-export for convenience
__all__ = ["generate_population", "IDEOLOGY_TEMPLATES"]
