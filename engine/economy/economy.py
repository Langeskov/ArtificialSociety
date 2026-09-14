"""Economy — resource metabolism plus structural labor dynamics (v0.4.6)."""

from __future__ import annotations

import random
from typing import Optional, Sequence

from ..agent.agent import Agent


def _labor_market(agents: Sequence[Agent]):
    for agent in agents:
        market = getattr(agent, "_labor_market", None)
        if market is not None:
            return market
    return None


def _labor_pressure(agents: Sequence[Agent]) -> float:
    alive = [a for a in agents if a.alive]
    if not alive:
        return 0.0
    avg_pressure = sum(getattr(a, "resource_state", {}).get("pressure", 0.0) for a in alive) / len(alive)
    unemployment = sum(1 for a in alive if getattr(a, "sector", "unemployed") == "unemployed") / len(alive)
    return min(1.0, 0.70 * avg_pressure + 0.30 * unemployment)


def _rebalance_labor(agents: Sequence[Agent], cfg: dict, rng: random.Random) -> dict:
    market = _labor_market(agents)
    if market is None:
        return {"laid_off": 0, "hired": 0}
    pressure = _labor_pressure(agents)
    labor_cfg = cfg.get("labor", {})
    return market.rebalance(
        list(agents),
        rng,
        pressure=pressure,
        layoff_threshold=float(labor_cfg.get("layoff_pressure_threshold", 0.65)),
        layoff_fraction=float(labor_cfg.get("layoff_fraction", 0.10)),
    )


def _structural_labor_step(agents: Sequence[Agent], cfg: dict, rng: random.Random) -> dict:
    """One daily structural pass: training, migration, enterprise capacity."""
    market = _labor_market(agents)
    if market is None:
        return {"trained": 0, "migrated": 0, "jobs_created": 0, "jobs_closed": 0}

    labor_cfg = cfg.get("labor", {})
    regions = cfg.get("regions", {}).get("list", ["A", "B", "C"])
    trained = market.train(
        list(agents), rng,
        learning_rate=float(labor_cfg.get("training_rate", 0.01)),
        max_training_share=float(labor_cfg.get("training_share", 0.08)),
    )
    migrated = market.migrate(
        list(agents), regions, rng,
        migration_cost=float(labor_cfg.get("migration_cost", 30.0)),
        max_share=float(labor_cfg.get("migration_share", 0.02)),
    )
    enterprise = market.evolve_job_capacity(
        list(agents), regions, rng,
        creation_threshold=float(labor_cfg.get("enterprise_creation_demand", 1.5)),
        closure_threshold=float(labor_cfg.get("enterprise_closure_demand", 0.10)),
        max_changes=int(labor_cfg.get("enterprise_max_changes_per_day", 5)),
    )
    return {
        "trained": trained,
        "migrated": migrated,
        "jobs_created": enterprise.get("jobs_created", 0),
        "jobs_closed": enterprise.get("jobs_closed", 0),
    }


def step_economy(
    agents: Sequence[Agent],
    cfg: dict,
    rng: random.Random,
    production_multiplier: Optional[float] = None,
    collect_tax: bool = False,
    dt_days: float = 0.01,
) -> dict:
    """应用一 tick 的经济更新；结构性劳动力变化仅在日边界发生。"""
    econ = cfg.get("economy", {})
    daily = econ.get("daily", {})
    food_consumption_day = daily.get("food_consumption_per_agent", 5.0)
    energy_consumption_day = daily.get("energy_consumption_per_agent", 3.0)
    food_cons_tick = food_consumption_day * dt_days
    energy_cons_tick = energy_consumption_day * dt_days

    tax_rate = econ.get("tax_rate", 0.01)
    redistribution = econ.get("redistribution", 0.5)
    food_critical = econ.get("food_critical", 20.0)

    tax_pool = 0.0
    flow = {
        "food_consumed": 0.0,
        "energy_consumed": 0.0,
        "food_produced": 0.0,
        "energy_produced": 0.0,
        "money_taxed": 0.0,
        "money_redistributed": 0.0,
        "labor_laid_off": 0,
        "labor_hired": 0,
        "labor_trained": 0,
        "labor_migrated": 0,
        "jobs_created": 0,
        "jobs_closed": 0,
    }

    if collect_tax:
        labor_result = _rebalance_labor(agents, cfg, rng)
        flow["labor_laid_off"] = labor_result.get("laid_off", 0)
        flow["labor_hired"] = labor_result.get("hired", 0)
        structural = _structural_labor_step(agents, cfg, rng)
        flow.update({
            "labor_trained": structural["trained"],
            "labor_migrated": structural["migrated"],
            "jobs_created": structural["jobs_created"],
            "jobs_closed": structural["jobs_closed"],
        })

    for a in agents:
        if not a.alive:
            continue
        a.resources.add("food", -food_cons_tick)
        a.resources.add("energy", -energy_cons_tick)
        flow["food_consumed"] += food_cons_tick
        flow["energy_consumed"] += energy_cons_tick
        a.status["survival_mode"] = a.resources.available("food") < food_critical
        a.resources.add("information", 0.05 if rng.random() < a.personality["openness"] else 0.0)

        if collect_tax:
            tax = a.resources.available("money") * tax_rate
            a.resources.add("money", -tax)
            tax_pool += tax
            flow["money_taxed"] += tax

    if collect_tax and redistribution > 0 and tax_pool > 0:
        poor = [a for a in agents if a.alive and a.resources.is_broke()]
        if poor:
            share = (tax_pool * redistribution) / len(poor)
            for a in poor:
                a.resources.add("money", share)
                a.resources.add("food", food_consumption_day * 0.2 * dt_days)
                flow["money_redistributed"] += share

    return flow


def step_production_recovery(society, cfg: dict, dt_days: float = 0.01) -> None:
    """v0.4.2: production_multiplier recovery + disruption decay."""
    econ = cfg.get("economy", {})
    recovery_cfg = econ.get("recovery", {})
    damping = recovery_cfg.get("damping", 0.85)
    max_rate_day = recovery_cfg.get("max_rate_per_day", 0.15)
    if "disruption_decay_per_day" in recovery_cfg:
        daily_retention = float(recovery_cfg["disruption_decay_per_day"])
        disruption_decay = daily_retention ** max(dt_days, 1e-9)
    else:
        disruption_decay = float(recovery_cfg.get("disruption_decay", 0.92))

    pm = getattr(society, "production_multiplier", 1.0)
    disruption = getattr(society, "production_disruption", 0.0)
    disruption *= disruption_decay
    if disruption < 0.001:
        disruption = 0.0
    society.production_disruption = disruption

    gap = 1.0 - pm
    if gap > 0.001:
        recovery = gap * damping * max_rate_day * dt_days
        pm = min(1.0, pm + recovery)
    elif gap < -0.001:
        pm += gap * 0.05 * dt_days
    society.production_multiplier = pm
