"""Economy — 基础代谢、税收、再分配（v0.4.1 §1, §2, §59）。

v0.4.1 关键变更：**不再每 tick 给所有 Agent 固定收入作为唯一经济来源**（§1 禁止）。
收入改由 `work` 行为（生产，§14/§16）产生；本模块只负责：

  - 基础代谢消费（food / energy）
  - 极端状态标记（§5 保留，但行为系统不依赖硬阈值）
  - 按日税收 + 再分配（§12）
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
    """应用一 tick 的经济更新（基础代谢 + 税收）。"""
    econ = cfg.get("economy", {})
    food_consumption = econ.get("food_consumption", 0.05)
    energy_consumption = econ.get("energy_consumption", 0.03)
    tax_rate = econ.get("tax_rate", 0.08)
    redistribution = econ.get("redistribution", 0.5)
    food_critical = econ.get("food_critical", 20.0)

    tax_pool = 0.0

    for a in agents:
        if not a.alive:
            continue

        # 1. 基础代谢消费（§2）
        a.resources.add("food", -food_consumption)
        a.resources.add("energy", -energy_consumption)

        # 2. 极端状态标记（§5：保留作为标记，行为系统改用连续 resource_pressure）
        a.status["survival_mode"] = a.resources.available("food") < food_critical

        # 3. 信息缓慢积累（自然学习，开放度调制）
        a.resources.add("information", 0.05 if rng.random() < a.personality["openness"] else 0.0)

        # 4. 税收（按日征收 §12）
        if collect_tax:
            tax = a.resources.available("money") * tax_rate
            a.resources.add("money", -tax)
            tax_pool += tax

    # 5. 再分配（基本安全网，按日）
    if collect_tax and redistribution > 0 and tax_pool > 0:
        poor = [a for a in agents if a.alive and a.resources.is_broke()]
        if poor:
            share = (tax_pool * redistribution) / len(poor)
            for a in poor:
                a.resources.add("money", share)
                a.resources.add("food", food_consumption * 20)  # 生存口粮
