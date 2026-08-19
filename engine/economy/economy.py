"""Economy — 基础代谢、税收、再分配（v0.4.2 §5–§6 delta-time 重构）。

v0.4.2 关键变更：
  - 所有资源率统一为 per-day（§5），引擎按 dt_days = 1/ticks_per_day 换算
  - 这样改变 ticks_per_day 不会改变社会真实资源流量（§7 时间分辨率不变性）
  - production_multiplier 恢复改为阻尼渐进（§18 防过冲）
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
    dt_days: float = 0.01,
) -> dict:
    """应用一 tick 的经济更新（基础代谢 + 税收），返回 flow 统计。

    v0.4.2 §5：所有资源率统一为 per-day，按 dt_days 换算到 per-tick。
    返回 dict 包含本 tick 的资源流量（§11 food flow budget）。
    """
    econ = cfg.get("economy", {})
    daily = econ.get("daily", {})

    # v0.4.2 §5: per-day rates × dt_days = per-tick rates
    food_consumption_day = daily.get("food_consumption_per_agent", 5.0)
    energy_consumption_day = daily.get("energy_consumption_per_agent", 3.0)
    food_cons_tick = food_consumption_day * dt_days
    energy_cons_tick = energy_consumption_day * dt_days

    tax_rate = econ.get("tax_rate", 0.01)
    redistribution = econ.get("redistribution", 0.5)
    food_critical = econ.get("food_critical", 20.0)

    tax_pool = 0.0
    # v0.4.2 §11: flow accounting
    flow = {
        "food_consumed": 0.0,
        "energy_consumed": 0.0,
        "food_produced": 0.0,
        "energy_produced": 0.0,
        "money_taxed": 0.0,
        "money_redistributed": 0.0,
    }

    for a in agents:
        if not a.alive:
            continue

        # 1. 基础代谢消费（§2）— per-day rate × dt_days
        a.resources.add("food", -food_cons_tick)
        a.resources.add("energy", -energy_cons_tick)
        flow["food_consumed"] += food_cons_tick
        flow["energy_consumed"] += energy_cons_tick

        # 2. 极端状态标记（§5：保留作为标记，行为系统改用连续 resource_pressure）
        a.status["survival_mode"] = a.resources.available("food") < food_critical

        # 3. 信息缓慢积累（自然学习，开放度调制）
        a.resources.add("information", 0.05 if rng.random() < a.personality["openness"] else 0.0)

        # 4. 税收（按日征收 §12）
        if collect_tax:
            tax = a.resources.available("money") * tax_rate
            a.resources.add("money", -tax)
            tax_pool += tax
            flow["money_taxed"] += tax

    # 5. 再分配（基本安全网，按日）
    if collect_tax and redistribution > 0 and tax_pool > 0:
        poor = [a for a in agents if a.alive and a.resources.is_broke()]
        if poor:
            share = (tax_pool * redistribution) / len(poor)
            for a in poor:
                a.resources.add("money", share)
                a.resources.add("food", food_consumption_day * 0.2 * dt_days)  # 生存口粮
                flow["money_redistributed"] += share

    return flow


def step_production_recovery(society, cfg: dict, dt_days: float = 0.01) -> None:
    """v0.4.2 §17–§19: production_multiplier 阻尼渐进恢复 + 临时干扰衰减。

    关键设计：
      - production_multiplier 是基础乘数，向 1.0 阻尼恢复
      - production_disruption 是临时干扰，自动衰减
      - 有效乘数 = max(0.3, multiplier - disruption)
      - 两者分开存储，避免干扰被"固化"到乘数中
    """
    econ = cfg.get("economy", {})
    recovery_cfg = econ.get("recovery", {})
    damping = recovery_cfg.get("damping", 0.85)
    max_rate_day = recovery_cfg.get("max_rate_per_day", 0.15)
    disruption_decay = recovery_cfg.get("disruption_decay", 0.92)

    pm = getattr(society, "production_multiplier", 1.0)
    disruption = getattr(society, "production_disruption", 0.0)

    # 临时干扰衰减（§19：protest 效率损失是临时的，不是永久 ratchet）
    disruption *= disruption_decay
    if disruption < 0.001:
        disruption = 0.0
    society.production_disruption = disruption

    # 阻尼恢复：gap × damping × max_rate × dt_days
    gap = 1.0 - pm
    if gap > 0.001:
        recovery = gap * damping * max_rate_day * dt_days
        pm = min(1.0, pm + recovery)
    elif gap < -0.001:
        # 过冲回落（技术突破等）
        pm += gap * 0.05 * dt_days

    society.production_multiplier = pm
