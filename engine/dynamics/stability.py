"""Stability — 中心稳定力、极端化代价、边界集中检测与崩溃检测 (§6, §7, §26, §27).

核心原则（v0.2 §36）：不能靠"强制拉回中心"或"到阈值就重置"来掩盖塌缩。
这里提供的是弱稳定力（让极端化需要持续压力维持）与只读的检测器（帮助发现异常，
不自动干预模拟）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


def center_force(position: float, strength: float) -> float:
    """弱中心稳定力：接近中心几乎无影响，远离中心轻微回拉 (§6)."""
    return -position * strength


def extremism(x: float, y: float, z: float) -> float:
    """极端化程度 = 三轴绝对值的平均 (§7)."""
    return (abs(x) + abs(y) + abs(z)) / 3.0


def boundary_concentration(agents: Sequence, threshold: float = 0.95) -> dict:
    """统计贴近各政治边界的 Agent 比例 (§27).

    返回 {axis_min/max: ratio}，例如 agents_at_x_min = 靠近 x=-1 的比例。
    """
    alive = [a for a in agents if getattr(a, "alive", True)]
    n = len(alive)
    if n == 0:
        return {}
    counts = {
        "x_min": 0, "x_max": 0,
        "y_min": 0, "y_max": 0,
        "z_min": 0, "z_max": 0,
    }
    for a in alive:
        i = a.ideology
        if i.x <= -threshold:
            counts["x_min"] += 1
        if i.x >= threshold:
            counts["x_max"] += 1
        if i.y <= -threshold:
            counts["y_min"] += 1
        if i.y >= threshold:
            counts["y_max"] += 1
        if i.z <= -threshold:
            counts["z_min"] += 1
        if i.z >= threshold:
            counts["z_max"] += 1
    return {k: round(v / n, 4) for k, v in counts.items()}


@dataclass
class CollapseDetector:
    """连续 tick 检测政治方差塌缩 + 高温 + 资源临界 (§26).

    只标记 SYSTEM_COLLAPSE_WARNING，不自动重置模拟。
    """

    variance_threshold: float = 0.02
    consecutive_ticks: int = 20
    temperature_critical: float = 0.85
    _streak: int = 0
    warning: bool = False
    _boundary_warning: bool = False
    _boundary_critical: bool = False

    def update(
        self,
        political_variance: float,
        social_temperature: float,
        resource_critical: bool,
        boundary_ratio: float,
        boundary_warning_ratio: float,
        boundary_critical_ratio: float,
    ) -> None:
        # 边界集中检测 (§27)
        self._boundary_warning = boundary_ratio >= boundary_warning_ratio
        self._boundary_critical = boundary_ratio >= boundary_critical_ratio

        # 社会崩溃检测 (§26)
        collapsed = (
            political_variance < self.variance_threshold
            and resource_critical
            and social_temperature > self.temperature_critical
        )
        if collapsed:
            self._streak += 1
        else:
            self._streak = 0
        self.warning = self._streak >= self.consecutive_ticks

    def flags(self) -> dict:
        return {
            "collapse_warning": self.warning,
            "boundary_warning": self._boundary_warning,
            "boundary_critical": self._boundary_critical,
        }
