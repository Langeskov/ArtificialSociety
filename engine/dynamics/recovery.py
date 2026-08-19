"""Recovery — v0.4.2: 重定向到 economy.step_production_recovery。

原 step_recovery 已合并到 engine/economy/economy.py 的阻尼恢复机制。
保留此模块向后兼容。
"""

from __future__ import annotations


def step_recovery(society, cfg: dict) -> None:
    """向后兼容包装：调用新的阻尼恢复。"""
    from ..economy.economy import step_production_recovery
    # 使用默认 dt_days=0.01 (100 ticks/day)
    step_production_recovery(society, cfg, dt_days=0.01)


def apply_resource_recovery(agents, cfg: dict) -> None:
    """向后兼容：粮食危机恢复模式（已被 CrisisManager 替代）。"""
    pass
