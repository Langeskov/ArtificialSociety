"""Recovery — 生产与资源恢复机制 (§13, §15).

抗议 / 冲突 / 危机会暂时压低社会生产（production_multiplier），随后按
recovery_rate 逐步恢复到 1.0。粮食危机触发 resource_recovery_mode，通过
提高生产 + 释放储备 + 降低奢侈消费来避免不可逆崩溃。
"""

from __future__ import annotations

from typing import Sequence

from ..agent.agent import Agent


def step_recovery(society, cfg: dict) -> None:
    """推进社会生产乘数向 1.0 恢复（抗议后的生产恢复，§13）。"""
    econ = cfg.get("economy", {})
    recovery_rate = econ.get("recovery_rate", 0.05)
    pm = getattr(society, "production_multiplier", 1.0)
    pm += (1.0 - pm) * recovery_rate
    society.production_multiplier = min(1.0, pm)


def apply_resource_recovery(agents: Sequence[Agent], cfg: dict) -> None:
    """粮食危机的恢复模式 (§15)：饥饿 Agent 降低奢侈消费并补充食物储备。"""
    econ = cfg.get("economy", {})
    food_critical = econ.get("food_critical", 20.0)
    food_production = econ.get("food_production", 0.12)

    for a in agents:
        if not a.alive:
            continue
        food = a.resources.values.get("food", 0.0)
        if food < food_critical:
            # 恢复模式：额外生产 + 从储备中释放（用信息/财产换取食物）。
            a.resources.add("food", food_production * 0.5)
            # 降低奢侈消费：不再额外消耗能源
            a.status["recovery_mode"] = True
        else:
            a.status["recovery_mode"] = False
