"""Economy — resource dynamics: income, consumption, tax, redistribution (§12).

v0.2 (§14, §15): food/energy are *produced* as well as consumed, so a crisis is
recoverable. Tax is collected once per DAY (not per tick) to avoid draining
wealth into a sink — the v0.1 collapse was driven by 8%-per-tick taxation.
"""

from __future__ import annotations

import random
from typing import Optional, Sequence

from ..agent.agent import Agent


def step_economy(
    agents: Sequence[Agent],
    cfg: dict,
    rng: random.Random,
    production_multiplier: Optional[float] = None,
    collect_tax: bool = False,
) -> None:
    """Apply one tick of economic update to every agent.

    collect_tax=True at day boundaries (tax is a daily levy, §12).
    """
    econ = cfg.get("economy", {})
    base_income = econ.get("base_income", 3.0)
    income_sigma = econ.get("income_sigma", 2.0)
    food_consumption = econ.get("food_consumption", 0.05)
    energy_consumption = econ.get("energy_consumption", 0.03)
    tax_rate = econ.get("tax_rate", 0.08)
    redistribution = econ.get("redistribution", 0.5)  # fraction of tax pool redistributed
    food_production = econ.get("food_production", 0.12)   # v0.2: per-agent food income
    energy_production = econ.get("energy_production", 0.06)  # v0.2: per-agent energy income
    food_critical = econ.get("food_critical", 20.0)         # v0.2: survival threshold

    pm = production_multiplier if production_multiplier is not None else 1.0
    tax_pool = 0.0

    # Production + consumption
    for a in agents:
        if not a.alive:
            continue
        productivity = 0.5 + a.personality["conscientiousness"] * 0.5
        property_bonus = a.resources.values["property"] * 0.001

        # v0.2: production scaled by the society production multiplier.
        income = max(0.0, rng.gauss(base_income, income_sigma)) * productivity * pm
        income += property_bonus
        a.resources.add("money", income)

        # Food + energy production (§14): replenish stocks, scaled by productivity.
        a.resources.add("food", food_production * productivity * pm)
        a.resources.add("energy", energy_production * productivity * pm)

        # Consumption (food / energy).
        a.resources.add("food", -food_consumption)
        a.resources.add("energy", -energy_consumption)

        # Recovery mode (§15): below critical food → release storage + reduce luxury.
        if a.resources.values["food"] < food_critical:
            a.status["recovery_mode"] = True
            a.status["survival_mode"] = True
            a.resources.add("food", food_production * 0.5)
        else:
            a.status["recovery_mode"] = False
            a.status["survival_mode"] = a.resources.is_starving()

        # Tax is a daily levy (§12): collected at day boundaries only.
        if collect_tax:
            tax = a.resources.values["money"] * tax_rate
            a.resources.add("money", -tax)
            tax_pool += tax

        # Information decays / grows slowly
        a.resources.add("information", 0.05 if rng.random() < a.personality["openness"] else 0.0)

    # Redistribution of the tax pool (basic safety net, daily)
    if collect_tax and redistribution > 0 and tax_pool > 0:
        poor = [a for a in agents if a.alive and a.resources.is_broke()]
        if poor:
            share = (tax_pool * redistribution) / len(poor)
            for a in poor:
                a.resources.add("money", share)
                a.resources.add("food", food_consumption * 20)  # survival ration
