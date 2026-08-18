"""Resource Security Layer（v0.4.1 §2–§6）。

为每个 Agent 计算连续的 resource_security / resource_pressure，以及各资源
独立压力。资源从「简单状态变量」升级为「约束可行动空间」的连续信号。

原则（§3, §5）：
  - 不简单平均，按「生存 / 经济 / 活动 / 决策」四类加权；
  - 用 sigmoid 连续映射，禁止 19.9→20.1 式的硬阈值突变。
"""

from __future__ import annotations

import math

from ..agent.agent import Agent

# 默认权重（§3）：survival + economic + activity + decision = 1.0
DEFAULT_WEIGHTS = {
    "survival": 0.35,   # food
    "economic": 0.25,   # money + property
    "activity": 0.20,   # energy
    "decision": 0.20,   # information
}


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def _security_of(value: float, critical: float, scale: float) -> float:
    """连续资源安全度 ∈ [0,1]：critical 处为 0.5，远离 critical 平滑饱和。"""
    if critical <= 0:
        return 1.0 if value > 0 else 0.0
    return _sigmoid((value - critical) / max(critical * scale, 1e-6))


def compute_resource_security(a: Agent, cfg: dict) -> dict:
    """计算 Agent 的 resource_state（§6）。"""
    econ = cfg.get("economy", {})
    sec_cfg = cfg.get("resource_security", {})
    crit = sec_cfg.get("critical", {})
    food_c = crit.get("food", econ.get("food_critical", 20.0))
    money_c = crit.get("money", 15.0)
    energy_c = crit.get("energy", 10.0)
    info_c = crit.get("information", 20.0)
    scale = sec_cfg.get("scale", 0.5)
    weights = {**DEFAULT_WEIGHTS, **(sec_cfg.get("weights", {}))}

    food = a.resources.available("food")
    money = a.resources.available("money")
    energy = a.resources.available("energy")
    info = a.resources.available("information")
    prop = a.resources.available("property")

    survival = _security_of(food, food_c, scale)
    economic = _security_of(money + prop, money_c + 50.0, scale)
    activity = _security_of(energy, energy_c, scale)
    decision = _security_of(info, info_c, scale)

    security = (
        weights["survival"] * survival
        + weights["economic"] * economic
        + weights["activity"] * activity
        + weights["decision"] * decision
    )
    security = max(0.0, min(1.0, security))

    return {
        "security": round(security, 4),
        "pressure": round(1.0 - security, 4),
        "surplus": round(max(0.0, security - 0.5) * 2.0, 4),
        "deficit": round(max(0.0, 0.5 - security) * 2.0, 4),
        "food_pressure": round(1.0 - survival, 4),
        "money_pressure": round(1.0 - economic, 4),
        "energy_pressure": round(1.0 - activity, 4),
        "information_pressure": round(1.0 - decision, 4),
    }


def update_resource_state(a: Agent, cfg: dict) -> dict:
    """更新并写回 Agent.resource_state（§6，每 tick）。"""
    state = compute_resource_security(a, cfg)
    a.resource_state = state
    return state
