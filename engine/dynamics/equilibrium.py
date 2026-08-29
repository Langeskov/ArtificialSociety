"""Long-Run Dynamic Equilibrium Monitor (v0.4.5.3 §19-§24).

Monitors:
  - political_variance, resource_variance
  - group_turnover, employment_turnover, information_turnover
  - event_rate
  - political_freeze_score

Classifies:
  - DYNAMIC_EQUILIBRIUM: events + turnover remain bounded
  - STATIC_EQUILIBRIUM: all indicators near zero for N days
  - STAGNANT: low variance + no turnover (vs STABLE: low variance + turnover)
  - POLITICAL_FREEZE: political velocity and variance change near zero
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class EquilibriumSnapshot:
    tick: int = 0
    day: float = 0.0
    event_rate: float = 0.0
    political_variance: float = 0.0
    political_velocity: float = 0.0
    resource_variance: float = 0.0
    group_turnover: float = 0.0
    employment_turnover: float = 0.0
    political_freeze_score: float = 0.0
    classification: str = "UNKNOWN"


class DynamicEquilibriumMonitor:
    """v0.4.5.3 §19: Monitors long-run dynamics to detect equilibrium states."""

    def __init__(self, window_days: int = 30, static_threshold_days: int = 60) -> None:
        self.window_days = window_days
        self.static_threshold_days = static_threshold_days
        self._window_events: deque = deque(maxlen=10000)
        self._window_pol_var: deque = deque(maxlen=10000)
        self._window_pol_vel: deque = deque(maxlen=10000)
        self._window_res_var: deque = deque(maxlen=10000)
        self._window_grp_turn: deque = deque(maxlen=10000)
        self._window_emp_turn: deque = deque(maxlen=10000)
        self._consecutive_static_ticks: int = 0
        self._last_classification: str = "UNKNOWN"
        self._snapshots: list[EquilibriumSnapshot] = []

    def update(self, tick: int, ticks_per_day: int, event_count: int,
               political_variance: float, political_velocity: float,
               resource_variance: float, group_turnover: float,
               employment_turnover: float) -> str:
        """Update monitor and return classification."""
        day = tick / ticks_per_day
        self._window_events.append(event_count)
        self._window_pol_var.append(political_variance)
        self._window_pol_vel.append(political_velocity)
        self._window_res_var.append(resource_variance)
        self._window_grp_turn.append(group_turnover)
        self._window_emp_turn.append(employment_turnover)

        # Compute freeze score (§23)
        freeze_score = self._compute_freeze_score()

        # Check for static equilibrium (§20)
        is_static = self._check_static(freeze_score, event_count)
        if is_static:
            self._consecutive_static_ticks += 1
        else:
            self._consecutive_static_ticks = 0

        # Classify
        if self._consecutive_static_ticks >= self.static_threshold_days * ticks_per_day:
            classification = "STATIC_EQUILIBRIUM"
        elif freeze_score < 0.01 and event_count == 0:
            classification = "POLITICAL_FREEZE"
        elif self._check_dynamic(ticks_per_day):
            classification = "DYNAMIC_EQUILIBRIUM"
        else:
            classification = "ACTIVE"

        self._last_classification = classification

        snap = EquilibriumSnapshot(
            tick=tick, day=round(day, 2),
            event_rate=self._mean(self._window_events),
            political_variance=political_variance,
            political_velocity=political_velocity,
            resource_variance=resource_variance,
            group_turnover=group_turnover,
            employment_turnover=employment_turnover,
            political_freeze_score=round(freeze_score, 4),
            classification=classification,
        )
        self._snapshots.append(snap)
        if len(self._snapshots) > 2000:
            self._snapshots = self._snapshots[-2000:]

        return classification

    def _compute_freeze_score(self) -> float:
        """§23: political_freeze_score from velocity + variance change."""
        if len(self._window_pol_vel) < 10:
            return 1.0  # not enough data
        vel_mean = self._mean(abs(v) for v in self._window_pol_vel)
        var_list = list(self._window_pol_var)
        var_change = abs(var_list[-1] - var_list[0]) / max(len(var_list), 1) if len(var_list) > 1 else 0
        return min(1.0, vel_mean * 10 + var_change * 100)

    def _check_static(self, freeze_score: float, event_count: int) -> bool:
        """§20: All indicators near zero."""
        if len(self._window_events) < 10:
            return False
        return (freeze_score < 0.005 and event_count == 0 and
                self._mean(self._window_grp_turn) < 0.001 and
                self._mean(self._window_emp_turn) < 0.001)

    def _check_dynamic(self, ticks_per_day: int) -> bool:
        """§21: Events + turnover remain bounded (not zero)."""
        if len(self._window_events) < ticks_per_day:
            return False
        event_rate = self._mean(self._window_events)
        grp_turn = self._mean(self._window_grp_turn)
        return event_rate > 0.01 or grp_turn > 0.005

    @staticmethod
    def _mean(iterable) -> float:
        items = list(iterable)
        return sum(items) / len(items) if items else 0.0

    def snapshot(self) -> dict:
        if not self._snapshots:
            return {"classification": "UNKNOWN"}
        s = self._snapshots[-1]
        return {
            "classification": s.classification,
            "event_rate": round(s.event_rate, 4),
            "political_variance": round(s.political_variance, 4),
            "political_velocity": round(s.political_velocity, 4),
            "political_freeze_score": s.political_freeze_score,
            "group_turnover": round(s.group_turnover, 4),
            "employment_turnover": round(s.employment_turnover, 4),
            "consecutive_static_ticks": self._consecutive_static_ticks,
        }

    def get_history(self, limit: int = 100) -> list[dict]:
        return [
            {"tick": s.tick, "day": s.day, "classification": s.classification,
             "event_rate": round(s.event_rate, 4), "freeze_score": s.political_freeze_score}
            for s in self._snapshots[-limit:]
        ]
