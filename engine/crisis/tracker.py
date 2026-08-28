"""Crisis State Machine (v0.4.5.2 — Crisis State Synchronization).

Single Source of Truth for crisis lifecycle:
  NORMAL → WARNING → ACTIVE → SEVERE → RECOVERING → COOLDOWN → NORMAL

v0.4.5.2 changes:
  - update() returns CrisisTransition (not just the new state)
  - Recovery progress based on actual metric improvement
  - Recovery timeout (max_recovery_ticks) prevents infinite RECOVERING
  - CrisisManager.update_all() is the unified entry point
  - EventTrigger no longer maintains parallel state
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
class CrisisTransition:
    """v0.4.5.2 §4: Result of a CrisisTracker.update() call.

    Event Engine consumes this to generate notifications, instead of
    comparing states itself.
    """
    crisis_type: str = ""
    previous_state: CrisisState = CrisisState.NORMAL
    current_state: CrisisState = CrisisState.NORMAL
    severity: float = 0.0
    tick: int = 0

    # Transition flags
    entered_warning: bool = False
    entered_active: bool = False
    entered_severe: bool = False
    entered_recovering: bool = False
    entered_cooldown: bool = False
    resolved: bool = False
    recovery_failed: bool = False

    # Evidence for the transition
    metric_value: float = 0.0
    recovery_progress: float = 0.0

    @property
    def has_transition(self) -> bool:
        """True if any state change occurred."""
        return (self.entered_warning or self.entered_active or
                self.entered_severe or self.entered_recovering or
                self.entered_cooldown or self.resolved or self.recovery_failed)


@dataclass
class CrisisTracker:
    """Single crisis type state tracker.

    v0.4.5.2: update() returns CrisisTransition.
    """
    crisis_type: str
    trigger_threshold: float = 0.25
    resolve_threshold: float = 0.12
    severe_threshold_multiplier: float = 1.5
    trigger_persistence_ticks: int = 50
    cooldown_days: float = 2.0

    # v0.4.5.2 §10: Recovery timeout
    max_recovery_ticks: int = 500

    # v0.4.5.2 §11: Recovery rates
    base_recovery_rate: float = 0.02
    metric_worsen_penalty: float = 0.5  # progress rate multiplier when metric worsens

    state: CrisisState = CrisisState.NORMAL
    severity: float = 0.0
    duration_ticks: int = 0
    recovery_progress: float = 0.0

    # Internal counters
    _above_trigger_ticks: int = 0
    _cooldown_remaining_ticks: int = 0
    _peak_severity: float = 0.0
    _start_tick: int = 0
    _peak_tick: int = 0
    _recovery_start_tick: int = 0
    _recovery_ticks: int = 0

    # Previous severity for improvement tracking
    _prev_metric: float = 0.0

    # History
    crisis_count: int = 0
    total_crisis_ticks: int = 0
    last_crisis_end_tick: int = -10**9

    # v0.4.5.2 §23: Recovery counters
    recovery_started_count: int = 0
    recovery_completed_count: int = 0
    recovery_failed_count: int = 0

    def update(self, metric: float, tick: int, ticks_per_day: int = 100) -> CrisisTransition:
        """Update crisis state machine. Returns CrisisTransition.

        metric is the crisis indicator (e.g. hunger_ratio), higher = worse.
        """
        transition = CrisisTransition(
            crisis_type=self.crisis_type,
            previous_state=self.state,
            severity=self.severity,
            tick=tick,
            metric_value=metric,
        )

        cooldown_tick_cost = int(self.cooldown_days * ticks_per_day)
        severe_threshold = self.trigger_threshold * self.severe_threshold_multiplier

        if self.state == CrisisState.NORMAL:
            if metric > self.trigger_threshold:
                self._above_trigger_ticks += 1
            else:
                self._above_trigger_ticks = 0

            if self._above_trigger_ticks >= self.trigger_persistence_ticks:
                self.state = CrisisState.WARNING
                self._start_tick = tick
                self._above_trigger_ticks = 0
                self.severity = metric
                self._peak_severity = metric
                self._peak_tick = tick
                transition.entered_warning = True

        elif self.state == CrisisState.WARNING:
            self.duration_ticks += 1
            self.severity = metric
            self._peak_severity = max(self._peak_severity, metric)
            if metric > severe_threshold:
                self.state = CrisisState.SEVERE
                self._peak_tick = tick
                transition.entered_severe = True
            elif metric > self.trigger_threshold:
                self.state = CrisisState.ACTIVE
                self._peak_tick = tick
                transition.entered_active = True
            elif metric < self.resolve_threshold:
                self.state = CrisisState.RECOVERING
                self._start_recovery(tick)
                transition.entered_recovering = True

        elif self.state == CrisisState.ACTIVE:
            self.duration_ticks += 1
            self.severity = metric
            self._peak_severity = max(self._peak_severity, metric)
            if metric > severe_threshold:
                self.state = CrisisState.SEVERE
                self._peak_tick = tick
                transition.entered_severe = True
            elif metric < self.resolve_threshold:
                self.state = CrisisState.RECOVERING
                self._start_recovery(tick)
                transition.entered_recovering = True

        elif self.state == CrisisState.SEVERE:
            self.duration_ticks += 1
            self.severity = metric
            self._peak_severity = max(self._peak_severity, metric)
            if metric < self.trigger_threshold:
                self.state = CrisisState.RECOVERING
                self._start_recovery(tick)
                transition.entered_recovering = True

        elif self.state == CrisisState.RECOVERING:
            self.duration_ticks += 1
            self._recovery_ticks += 1
            self.severity = metric

            # v0.4.5.2 §11: Recovery progress based on actual improvement
            metric_improvement = self._compute_improvement(metric)
            effective_rate = self.base_recovery_rate * metric_improvement
            self.recovery_progress = min(1.0, self.recovery_progress + effective_rate)
            self._prev_metric = metric

            # v0.4.5.2 §12: Recovery hysteresis — metric worsens → back to ACTIVE/SEVERE
            if metric > severe_threshold:
                self.state = CrisisState.SEVERE
                self._peak_tick = tick
                self.recovery_progress = 0.0
                self._recovery_ticks = 0
                transition.recovery_failed = True
                transition.entered_severe = True
            elif metric > self.trigger_threshold:
                self.state = CrisisState.ACTIVE
                self.recovery_progress = 0.0
                self._recovery_ticks = 0
                transition.recovery_failed = True
                transition.entered_active = True
            elif metric < self.resolve_threshold and self.recovery_progress >= 0.8:
                # Crisis resolved
                self._resolve_crisis(tick, cooldown_tick_cost)
                transition.entered_cooldown = True
                transition.resolved = True
            # v0.4.5.2 §10: Recovery timeout
            elif self._recovery_ticks >= self.max_recovery_ticks:
                # Timeout — re-enter ACTIVE
                self.state = CrisisState.ACTIVE
                self.recovery_progress = 0.0
                self._recovery_ticks = 0
                transition.recovery_failed = True
                transition.entered_active = True

        elif self.state == CrisisState.COOLDOWN:
            self._cooldown_remaining_ticks -= 1
            if self._cooldown_remaining_ticks <= 0:
                self.state = CrisisState.NORMAL
                self.severity = 0.0
                self._peak_severity = 0.0

        transition.current_state = self.state
        transition.recovery_progress = self.recovery_progress
        return transition

    def _start_recovery(self, tick: int) -> None:
        """Initialize recovery phase."""
        self.recovery_progress = 0.0
        self._recovery_start_tick = tick
        self._recovery_ticks = 0
        self._prev_metric = self.severity
        self.recovery_started_count += 1

    def _resolve_crisis(self, tick: int, cooldown_tick_cost: int) -> None:
        """Transition from RECOVERING to COOLDOWN."""
        self.crisis_count += 1
        self.total_crisis_ticks += self.duration_ticks
        self.last_crisis_end_tick = tick
        self.state = CrisisState.COOLDOWN
        self._cooldown_remaining_ticks = cooldown_tick_cost
        self.duration_ticks = 0
        self.recovery_progress = 0.0
        self._recovery_ticks = 0
        self.recovery_completed_count += 1

    def _compute_improvement(self, metric: float) -> float:
        """v0.4.5.2 §11: Compute recovery speed factor from metric improvement.

        Returns a multiplier for the base recovery rate:
        - >1.0 if metric is improving (decreasing)
        - 1.0 if stable
        - <1.0 if metric is worsening
        """
        if self._prev_metric <= 0:
            return 1.0
        delta = self._prev_metric - metric  # positive = improving
        if delta > 0:
            # Improving: faster recovery
            return 1.0 + min(delta / max(self._prev_metric, 0.01), 2.0)
        elif delta < 0:
            # Worsening: slower recovery
            return max(0.1, self.metric_worsen_penalty)
        return 1.0

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
            "recovery_ticks": self._recovery_ticks,
            "crisis_count": self.crisis_count,
            "total_crisis_ticks": self.total_crisis_ticks,
            "peak_severity": round(self._peak_severity, 4),
            "recovery_started_count": self.recovery_started_count,
            "recovery_completed_count": self.recovery_completed_count,
            "recovery_failed_count": self.recovery_failed_count,
        }


@dataclass
class CrisisManager:
    """Manages all types of crisis state machines.

    v0.4.5.2 §14: update_all() is the unified entry point.
    """
    food: CrisisTracker = field(default_factory=lambda: CrisisTracker("food"))
    protest: CrisisTracker = field(default_factory=lambda: CrisisTracker("protest"))
    economic: CrisisTracker = field(default_factory=lambda: CrisisTracker("economic"))

    def configure(self, cfg: dict) -> None:
        """Load per-crisis thresholds from config."""
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
            # v0.4.5.2: Recovery params from config
            recovery_cfg = crisis_cfg.get("recovery", {})
            if recovery_cfg:
                tracker.max_recovery_ticks = int(recovery_cfg.get(
                    "max_recovery_ticks", tracker.max_recovery_ticks))
                tracker.base_recovery_rate = recovery_cfg.get(
                    "base_recovery_rate", tracker.base_recovery_rate)

    def update_all(self, hunger_ratio: float, protest_ratio: float,
                   economic_pressure: float, tick: int,
                   ticks_per_day: int = 100) -> dict[str, CrisisTransition]:
        """v0.4.5.2 §14: Unified update entry point.

        Returns transitions for all crisis types.
        Event Engine should consume these instead of comparing states itself.
        """
        return {
            "food": self.food.update(hunger_ratio, tick, ticks_per_day),
            "protest": self.protest.update(protest_ratio, tick, ticks_per_day),
            "economic": self.economic.update(economic_pressure, tick, ticks_per_day),
        }

    def update(self, hunger_ratio: float, protest_ratio: float,
               tick: int, ticks_per_day: int = 100,
               economic_pressure: float = 0.0) -> None:
        """Backward-compatible update (used by older code paths)."""
        self.update_all(hunger_ratio, protest_ratio, economic_pressure, tick, ticks_per_day)

    def any_crisis(self) -> bool:
        return self.food.is_crisis() or self.protest.is_crisis() or self.economic.is_crisis()

    def snapshot(self) -> dict:
        return {
            "food": self.food.snapshot(),
            "protest": self.protest.snapshot(),
            "economic": self.economic.snapshot(),
        }
