"""Crisis State Machine (v0.4.2 §12–§16, §29).

统一危机生命周期：NORMAL → WARNING → ACTIVE → SEVERE → RECOVERING → COOLDOWN → NORMAL

关键设计：
  - Hysteresis (§14): trigger_threshold > resolve_threshold，防止在阈值附近反复开关
  - Persistence (§15): 条件必须持续 N ticks 才触发，短暂波动不升级为危机
  - Cooldown (§16): 解决后 N 天内不重新触发同类危机
  - 三层聚合 (§25–§27): Agent → Region → Society

适用于 food / energy / economic / protest 四类危机。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CrisisState(str, Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    ACTIVE = "ACTIVE"
    SEVERE = "SEVERE"
    RECOVERING = "RECOVERING"
    COOLDOWN = "COOLDOWN"


@dataclass
class CrisisTracker:
    """单类危机的状态追踪器。"""
    crisis_type: str
    trigger_threshold: float = 0.25
    resolve_threshold: float = 0.12
    trigger_persistence_ticks: int = 50
    cooldown_days: float = 2.0

    state: CrisisState = CrisisState.NORMAL
    severity: float = 0.0
    duration_ticks: int = 0
    recovery_progress: float = 0.0

    # 内部计数器
    _above_trigger_ticks: int = 0
    _cooldown_remaining_ticks: int = 0
    _peak_severity: float = 0.0
    _start_tick: int = 0
    _peak_tick: int = 0

    # 历史记录
    crisis_count: int = 0
    total_crisis_ticks: int = 0
    last_crisis_end_tick: int = -10**9

    def update(self, metric: float, tick: int, ticks_per_day: int = 100) -> CrisisState:
        """更新危机状态机。metric 是危机指标（如 hunger_ratio），越高越严重。"""
        cooldown_tick_cost = int(self.cooldown_days * ticks_per_day)

        if self.state == CrisisState.NORMAL:
            if metric > self.trigger_threshold:
                self._above_trigger_ticks += 1
            else:
                self._above_trigger_ticks = 0

            # 持续性检查 (§15)
            if self._above_trigger_ticks >= self.trigger_persistence_ticks:
                self.state = CrisisState.WARNING
                self._start_tick = tick
                self._above_trigger_ticks = 0
                self.severity = metric
                self._peak_severity = metric
                self._peak_tick = tick

        elif self.state == CrisisState.WARNING:
            self.duration_ticks += 1
            self.severity = metric
            self._peak_severity = max(self._peak_severity, metric)
            if metric > self.trigger_threshold * 1.5:
                self.state = CrisisState.SEVERE
                self._peak_tick = tick
            elif metric > self.trigger_threshold:
                self.state = CrisisState.ACTIVE
                self._peak_tick = tick
            elif metric < self.resolve_threshold:
                self.state = CrisisState.RECOVERING

        elif self.state == CrisisState.ACTIVE:
            self.duration_ticks += 1
            self.severity = metric
            self._peak_severity = max(self._peak_severity, metric)
            if metric > self.trigger_threshold * 1.5:
                self.state = CrisisState.SEVERE
                self._peak_tick = tick
            elif metric < self.resolve_threshold:
                self.state = CrisisState.RECOVERING
                self.recovery_progress = 0.0

        elif self.state == CrisisState.SEVERE:
            self.duration_ticks += 1
            self.severity = metric
            self._peak_severity = max(self._peak_severity, metric)
            if metric < self.trigger_threshold:
                self.state = CrisisState.RECOVERING
                self.recovery_progress = 0.0

        elif self.state == CrisisState.RECOVERING:
            self.duration_ticks += 1
            # 渐进恢复 (§17): 不瞬间归零
            self.recovery_progress = min(1.0, self.recovery_progress + 0.02)
            self.severity = metric
            if metric < self.resolve_threshold and self.recovery_progress >= 0.8:
                # 危机解决
                self.crisis_count += 1
                self.total_crisis_ticks += self.duration_ticks
                self.last_crisis_end_tick = tick
                self.state = CrisisState.COOLDOWN
                self._cooldown_remaining_ticks = cooldown_tick_cost
                self.duration_ticks = 0
                self.recovery_progress = 0.0
            elif metric > self.trigger_threshold:
                # 恶化回 ACTIVE
                self.state = CrisisState.ACTIVE
                self.recovery_progress = 0.0

        elif self.state == CrisisState.COOLDOWN:
            self._cooldown_remaining_ticks -= 1
            if self._cooldown_remaining_ticks <= 0:
                self.state = CrisisState.NORMAL
                self.severity = 0.0
                self._peak_severity = 0.0

        return self.state

    def is_crisis(self) -> bool:
        return self.state in (CrisisState.ACTIVE, CrisisState.SEVERE)

    def is_recovering(self) -> bool:
        return self.state == CrisisState.RECOVERING

    def snapshot(self) -> dict:
        return {
            "type": self.crisis_type,
            "state": self.state.value,
            "severity": round(self.severity, 4),
            "duration_ticks": self.duration_ticks,
            "recovery_progress": round(self.recovery_progress, 4),
            "crisis_count": self.crisis_count,
            "total_crisis_ticks": self.total_crisis_ticks,
            "peak_severity": round(self._peak_severity, 4),
        }


@dataclass
class CrisisManager:
    """管理所有类型的危机状态机。"""
    food: CrisisTracker = field(default_factory=lambda: CrisisTracker("food"))
    protest: CrisisTracker = field(default_factory=lambda: CrisisTracker("protest"))
    economic: CrisisTracker = field(default_factory=lambda: CrisisTracker("economic"))

    def configure(self, cfg: dict) -> None:
        """Load per-crisis thresholds without making the engine depend on config shape."""
        crisis_cfg = cfg.get("events", {}).get("crisis", {})
        for name, tracker in (("food", self.food), ("protest", self.protest),
                              ("economic", self.economic)):
            values = crisis_cfg.get(name, {})
            if not isinstance(values, dict):
                continue
            tracker.trigger_threshold = values.get("trigger_threshold", tracker.trigger_threshold)
            tracker.resolve_threshold = values.get("resolve_threshold", tracker.resolve_threshold)
            tracker.trigger_persistence_ticks = int(values.get(
                "trigger_persistence_ticks", tracker.trigger_persistence_ticks))
            tracker.cooldown_days = values.get("cooldown_days", tracker.cooldown_days)

    def update(self, hunger_ratio: float, protest_ratio: float,
               tick: int, ticks_per_day: int = 100,
               economic_pressure: float = 0.0) -> None:
        self.food.update(hunger_ratio, tick, ticks_per_day)
        self.protest.update(protest_ratio, tick, ticks_per_day)
        self.economic.update(economic_pressure, tick, ticks_per_day)

    def any_crisis(self) -> bool:
        return self.food.is_crisis() or self.protest.is_crisis() or self.economic.is_crisis()

    def snapshot(self) -> dict:
        return {
            "food": self.food.snapshot(),
            "protest": self.protest.snapshot(),
            "economic": self.economic.snapshot(),
        }
