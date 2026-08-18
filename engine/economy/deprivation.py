"""Relative Deprivation（v0.4.1 §25–§27）。

相对剥夺 ≠ 绝对贫困（§26）：
  - 贫困：我绝对资源不足；
  - 相对剥夺：我比「我认为应该拥有的」少。

reference 取同 region 的财富中位数（不同 Agent 可有不同 reference group，§26）。
deprivation = sigmoid(reference - own)。它影响 anger/group behavior/sharing/
protest/migration，但**不直接修改 ideology**（§25, §27）。
"""

from __future__ import annotations

import math
from collections import defaultdict

from ..agent.agent import Agent


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    e = math.exp(x)
    return e / (1.0 + e)


def deprivation_of(own: float, reference: float) -> float:
    """连续相对剥夺 ∈ [0,1]：own << reference → 1，own == reference → 0.5。"""
    scale = max(reference, 1.0)
    return _sigmoid((reference - own) / scale)


def update_relative_deprivation(agents: list[Agent], cfg: dict) -> None:
    """为所有 Agent 更新 relative_deprivation（按 region 中位数，§26）。"""
    by_region: dict[str, list[Agent]] = defaultdict(list)
    for a in agents:
        if a.alive:
            by_region[getattr(a, "location", "A")].append(a)

    for members in by_region.values():
        if not members:
            continue
        wealths = sorted(a.wealth() for a in members)
        median = wealths[len(wealths) // 2] if wealths else 0.0
        for a in members:
            a.relative_deprivation = round(deprivation_of(a.wealth(), median), 4)


def society_gini(agents: list[Agent]) -> float:
    """财富基尼系数（§43）。"""
    wealths = sorted(a.wealth() for a in agents if a.alive)
    n = len(wealths)
    if n < 2:
        return 0.0
    total = sum(wealths)
    if total <= 0:
        return 0.0
    cum = 0.0
    gini_sum = 0.0
    for i, w in enumerate(wealths):
        cum += w
        gini_sum += (i + 1) * w
    # gini = (2 * gini_sum / (n * total)) - (n + 1) / n
    gini = (2.0 * gini_sum / (n * total)) - (n + 1) / n
    return max(0.0, min(1.0, gini))
