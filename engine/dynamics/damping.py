"""Damping — 政治惯性与阻尼的弹簧-阻尼更新 (§4, §5).

政治立场不再被直接赋值，而是作为一个有惯性的动力系统：

    movement_factor = 1 - inertia
    velocity = velocity * damping + (target - position) * movement_factor
    position = position + velocity

`inertia` 高 → 朝目标移动慢；`damping` < 1 → 速度随时间衰减，避免
"+0.02 +0.02 +0.02…" 的无限累加。
"""

from __future__ import annotations


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def spring_damper_update(
    position: float,
    velocity: float,
    target: float,
    inertia: float,
    damping: float,
    max_movement: float | None = None,
) -> tuple[float, float]:
    """Advance one axis of the political state by one tick.

    Returns (new_position, new_velocity).
    """
    movement_factor = 1.0 - max(0.0, min(1.0, inertia))
    new_velocity = velocity * damping + (target - position) * movement_factor
    if max_movement is not None:
        new_velocity = clamp(new_velocity, -max_movement, max_movement)
    return position + new_velocity, new_velocity
