"""Crisis State Machine (v0.4.5.3 — Event Lifecycle Integrity).

Single Source of Truth for crisis lifecycle:
  NORMAL → WARNING → ACTIVE → SEVERE → RECOVERING → COOLDOWN → NORMAL

v0.4.5.3 changes:
  - Crisis Instance ID: each crisis gets a unique id (economic_000017)
  - CrisisTransition carries crisis_instance_id for event binding
  - Recovery progress from actual metrics (peak/current/baseline)
  - Lifecycle timing: crisis_start_tick, peak_tick, recovery_start_tick, resolution_tick
  - Recovery cause classification
  - Orphan recovery detection support
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
    """Result of a CrisisTracker.update() call.

    Event Engine consumes this to generate notifications.
    """
    crisis_type: str = ""
    crisis_instance_id: str = ""  # v0.4.5.3 §1: unique crisis instance
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

    # Evidence
    metric_value: float = 0.0
    recovery_progress: float = 0.0
    peak_metric: float = 0.0
    baseline_metric: float = 0.0

    # Lifecycle timing
    crisis_start_tick: int = 0
    peak_tick: int = 0
    recovery_start_tick: int = 0
    resolution_tick: int = 0

    @property
    def has_transition(self) -> bool:
        return (self.entered_warning or self.entered_active or
                self.entered_severe or self.entered_recovering or
                self.entered_cooldown or self.resolved or self.recovery_failed)


@dataclass
class CrisisTracker:
    """Single crisis type state tracker.

    v0.4.5.3: Each crisis instance gets a unique ID.
    """
    crisis_type: str
    trigger_threshold: float = 0.25
    resolve_threshold: float = 0.12
    severe_threshold_multiplier: float = 1.5
    trigger_persistence_ticks: int = 50
    cooldown_days: float = 2.0
    max_recovery_ticks: int = 500
    base_recovery_rate: float = 0.02
    metric_worsen_penalty: float = 0.5

    state: CrisisState = CrisisState.NORMAL
    severity: float = 0.0
    duration_ticks: int = 0
    recovery_progress: float = 0.0

    # v0.4.5.3 §1: Crisis instance tracking
    current_instance_id: str = ""
    _instance_counter: int = 0

    # Internal counters
    _above_trigger_ticks: int = 0
    _cooldown_remaining_ticks: int = 0
    _peak_severity: float = 0.0
    _start_tick: int = 0
    _peak_tick: int = 0
    _recovery_start_tick: int = 0
    _recovery_ticks: int = 0
    _prev_metric: float = 0.0
    _baseline_metric: float = 0.0  # v0.4.5.3 §7: metric before crisis

    # History
    crisis_count: int = 0
    total_crisis_ticks: int = 0
    last_crisis_end_tick: int = -10**9
    recovery_started_count: int = 0
    recovery_completed_count: int = 0
    recovery_failed_count: int = 0

    # v0.4.5.3 §39: Lifecycle audit
    _lifecycle_log: list = field(default_factory=list)

    def _next_instance_id(self) -> str:
        self._instance_counter += 1
        return f"{self.crisis_type}_{self._instance_counter:06d}"

    def update(self, metric: float, tick: int, ticks_per_day: int = 100) -> CrisisTransition:
        """Update crisis state machine. Returns CrisisTransition."""
        transition = CrisisTransition(
            crisis_type=self.crisis_type,
            crisis_instance_id=self.current_instance_id,
            previous_state=self.state,
            severity=self.severity,
            tick=tick,
            metric_value=metric,
            peak_metric=self._peak_severity,
            baseline_metric=self._baseline_metric,
            crisis_start_tick=self._start_tick,
            peak_tick=self._peak_tick,
            recovery_start_tick=self._recovery_start_tick,
        )

        cooldown_tick_cost = int(self.cooldown_days * ticks_per_day)
        severe_threshold = self.trigger_threshold * self.severe_threshold_multiplier

        if self.state == CrisisState.NORMAL:
            if metric > self.trigger_threshold:
                self._above_trigger_ticks += 1
            else:
                self._above_trigger_ticks = 0

            if self._above_trigger_ticks >= self.trigger_persistence_ticks:
                self.current_instance_id = self._next_instance_id()
                self.state = CrisisState.WARNING
                self._start_tick = tick
                self._above_trigger_ticks = 0
                self.severity = metric
                self._peak_severity = metric
                self._peak_tick = tick
                self._baseline_metric = metric  # v0.4.5.3 §7
                transition.entered_warning = True
                transition.crisis_instance_id = self.current_instance_id
                self._log_lifecycle("START", tick, metric)

        elif self.state == CrisisState.WARNING:
            self.duration_ticks += 1
            self.severity = metric
            self._peak_severity = max(self._peak_severity, metric)
            if metric > severe_threshold:
                self.state = CrisisState.SEVERE
                self._peak_tick = tick
                transition.entered_severe = True
                self._log_lifecycle("SEVERE", tick, metric)
            elif metric > self.trigger_threshold:
                self.state = CrisisState.ACTIVE
                self._peak_tick = tick
                transition.entered_active = True
                self._log_lifecycle("ACTIVE", tick, metric)
            elif metric < self.resolve_threshold:
                self._start_recovery_phase(tick)
                transition.entered_recovering = True

        elif self.state == CrisisState.ACTIVE:
            self.duration_ticks += 1
            self.severity = metric
            if metric > self._peak_severity:
                self._peak_severity = metric
                self._peak_tick = tick
            if metric > severe_threshold:
                self.state = CrisisState.SEVERE
                self._peak_tick = tick
                transition.entered_severe = True
                self._log_lifecycle("SEVERE", tick, metric)
            elif metric < self.resolve_threshold:
                self._start_recovery_phase(tick)
                transition.entered_recovering = True

        elif self.state == CrisisState.SEVERE:
            self.duration_ticks += 1
            self.severity = metric
            if metric > self._peak_severity:
                self._peak_severity = metric
                self._peak_tick = tick
            if metric < self.trigger_threshold:
                self._start_recovery_phase(tick)
                transition.entered_recovering = True

        elif self.state == CrisisState.RECOVERING:
            self.duration_ticks += 1
            self._recovery_ticks += 1
            self.severity = metric

            # v0.4.5.3 §7: Recovery progress from actual metrics
            self.recovery_progress = self._compute_recovery_progress(metric)
            self._prev_metric = metric

            if metric > severe_threshold:
                self.state = CrisisState.SEVERE
                self._peak_tick = tick
                self._abort_recovery(tick)
                transition.recovery_failed = True
                transition.entered_severe = True
                self._log_lifecycle("RECOVERY_FAILED_SEVERE", tick, metric)
            elif metric > self.trigger_threshold:
                self.state = CrisisState.ACTIVE
                self._abort_recovery(tick)
                transition.recovery_failed = True
                transition.entered_active = True
                self._log_lifecycle("RECOVERY_FAILED_ACTIVE", tick, metric)
            elif metric < self.resolve_threshold and self.recovery_progress >= 0.8:
                self._resolve_crisis(tick, cooldown_tick_cost)
                transition.entered_cooldown = True
                transition.resolved = True
                transition.resolution_tick = tick
            elif self._recovery_ticks >= self.max_recovery_ticks:
                self.state = CrisisState.ACTIVE
                self._abort_recovery(tick)
                transition.recovery_failed = True
                transition.entered_active = True
                self._log_lifecycle("RECOVERY_TIMEOUT", tick, metric)

        elif self.state == CrisisState.COOLDOWN:
            self._cooldown_remaining_ticks -= 1
            if self._cooldown_remaining_ticks <= 0:
                self.state = CrisisState.NORMAL
                self.severity = 0.0
                self._peak_severity = 0.0
                self.current_instance_id = ""

        transition.current_state = self.state
        transition.recovery_progress = self.recovery_progress
        transition.peak_metric = self._peak_severity
        return transition

    def _start_recovery_phase(self, tick: int) -> None:
        self.state = CrisisState.RECOVERING
        self.recovery_progress = 0.0
        self._recovery_start_tick = tick
        self._recovery_ticks = 0
        self._prev_metric = self.severity
        self.recovery_started_count += 1
        self._log_lifecycle("RECOVERY_START", tick, self.severity)

    def _abort_recovery(self, tick: int) -> None:
        self.recovery_progress = 0.0
        self._recovery_ticks = 0
        self.recovery_failed_count += 1

    def _resolve_crisis(self, tick: int, cooldown_tick_cost: int) -> None:
        self.crisis_count += 1
        self.total_crisis_ticks += self.duration_ticks
        self.last_crisis_end_tick = tick
        self.state = CrisisState.COOLDOWN
        self._cooldown_remaining_ticks = cooldown_tick_cost
        self.duration_ticks = 0
        self.recovery_progress = 0.0
        self._recovery_ticks = 0
        self.recovery_completed_count += 1
        self._log_lifecycle("RESOLVED", tick, self.severity)

    def _compute_recovery_progress(self, metric: float) -> float:
        """v0.4.5.3 §7: Recovery progress from actual metrics.

        progress = (peak - current) / (peak - baseline)
        """
        peak = self._peak_severity
        baseline = self._baseline_metric
        if peak <= baseline:
            return min(1.0, self.recovery_progress + self.base_recovery_rate)
        raw = (peak - metric) / (peak - baseline)
        return max(0.0, min(1.0, raw))

    def _log_lifecycle(self, phase: str, tick: int, metric: float) -> None:
        self._lifecycle_log.append({
            "instance_id": self.current_instance_id,
            "phase": phase,
            "tick": tick,
            "metric": round(metric, 4),
        })

    def get_lifecycle_log(self) -> list[dict]:
        return list(self._lifecycle_log)

    def get_current_lifecycle(self) -> dict:
        """v0.4.5.3 §40: Current crisis lifecycle summary."""
        return {
            "instance_id": self.current_instance_id,
            "state": self.state.value,
            "crisis_type": self.crisis_type,
            "start_tick": self._start_tick,
            "peak_tick": self._peak_tick,
            "peak_severity": round(self._peak_severity, 4),
            "recovery_start_tick": self._recovery_start_tick,
            "recovery_progress": round(self.recovery_progress, 4),
            "duration_ticks": self.duration_ticks,
        }

    def is_crisis(self) -> bool:
        return self.state in (CrisisState.ACTIVE, CrisisState.SEVERE)

    def is_recovering(self) -> bool:
        return self.state == CrisisState.RECOVERING

    def snapshot(self) -> dict:
        return {
            "type": self.crisis_type,
            "state": self.state.value,
            "current_instance_id": self.current_instance_id,
            "severity": round(self.severity, 4),
            "duration_ticks": self.duration_ticks,
            "recovery_progress": round(self.recovery_progress, 4),
            "recovery_ticks": self._recovery_ticks,
            "peak_severity": round(self._peak_severity, 4),
            "baseline_metric": round(self._baseline_metric, 4),
            "crisis_count": self.crisis_count,
            "total_crisis_ticks": self.total_crisis_ticks,
            "recovery_started_count": self.recovery_started_count,
            "recovery_completed_count": self.recovery_completed_count,
            "recovery_failed_count": self.recovery_failed_count,
        }


@dataclass
class CrisisManager:
    """Manages all types of crisis state machines."""
    food: CrisisTracker = field(default_factory=lambda: CrisisTracker("food"))
    protest: CrisisTracker = field(default_factory=lambda: CrisisTracker("protest"))
    economic: CrisisTracker = field(default_factory=lambda: CrisisTracker("economic"))

    def configure(self, cfg: dict) -> None:
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
            recovery_cfg = crisis_cfg.get("recovery", {})
            if recovery_cfg:
                tracker.max_recovery_ticks = int(recovery_cfg.get(
                    "max_recovery_ticks", tracker.max_recovery_ticks))
                tracker.base_recovery_rate = recovery_cfg.get(
                    "base_recovery_rate", tracker.base_recovery_rate)

    def update_all(self, hunger_ratio: float, protest_ratio: float,
                   economic_pressure: float, tick: int,
                   ticks_per_day: int = 100) -> dict[str, CrisisTransition]:
        return {
            "food": self.food.update(hunger_ratio, tick, ticks_per_day),
            "protest": self.protest.update(protest_ratio, tick, ticks_per_day),
            "economic": self.economic.update(economic_pressure, tick, ticks_per_day),
        }

    def update(self, hunger_ratio: float, protest_ratio: float,
               tick: int, ticks_per_day: int = 100,
               economic_pressure: float = 0.0) -> None:
        self.update_all(hunger_ratio, protest_ratio, economic_pressure, tick, ticks_per_day)

    def any_crisis(self) -> bool:
        return self.food.is_crisis() or self.protest.is_crisis() or self.economic.is_crisis()

    def snapshot(self) -> dict:
        return {
            "food": self.food.snapshot(),
            "protest": self.protest.snapshot(),
            "economic": self.economic.snapshot(),
        }

    def get_all_lifecycle_logs(self) -> dict[str, list[dict]]:
        return {
            "food": self.food.get_lifecycle_log(),
            "protest": self.protest.get_lifecycle_log(),
            "economic": self.economic.get_lifecycle_log(),
        }
