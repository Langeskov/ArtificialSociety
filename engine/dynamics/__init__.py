"""engine.dynamics — Simulation Stability Layer (项目计划书 v0.2 §2).

集中处理系统稳定性：政治阻尼、事件衰减、资源恢复、反馈追踪与崩溃检测。
"""

from . import damping, decay, recovery, stability, feedback  # noqa: F401

__all__ = ["damping", "decay", "recovery", "stability", "feedback"]
