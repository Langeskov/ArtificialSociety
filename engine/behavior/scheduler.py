"""Action Scheduler (v0.4.3.1 P0).

Actions have duration in simulated hours. Agent has 24-hour daily budget.
Can't re-choose action while current one is in progress.

Key change: Tick ≠ One complete action. Tick = One time slice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# Action durations in simulated hours
ACTION_DURATIONS = {
    "work": 4.0,        # Work session (4h)
    "trade": 2.0,       # Market transaction
    "rest": 4.0,        # Rest session (4h)
    "consume": 1.0,     # Eating
    "share": 1.0,       # Resource sharing
    "cooperate": 2.0,   # Group cooperation
    "protest": 4.0,     # Political action
    "migrate": 24.0,    # Full day travel
    "join_group": 1.0,  # Administrative
    "leave_group": 0.5, # Administrative
    "communicate": 1.0, # Information spread
    "save": 0.5,        # Financial management
}


@dataclass
class AgentActivity:
    """Agent's current activity state."""
    current_action: Optional[str] = None
    action_started_tick: int = 0
    hours_remaining: float = 0.0
    hours_committed: float = 0.0
    # Daily budget tracking
    daily_hours_used: float = 0.0
    daily_reset_tick: int = 0

    def is_busy(self) -> bool:
        """Agent is currently performing an action."""
        return self.current_action is not None and self.hours_remaining > 0

    def available_hours(self) -> float:
        """Hours remaining in daily budget (24h - used)."""
        return max(0.0, 24.0 - self.daily_hours_used)

    def advance(self, dt_hours: float) -> bool:
        """Advance current action by dt_hours. Returns True if action completed."""
        if not self.is_busy():
            return True
        self.hours_remaining -= dt_hours
        self.daily_hours_used += dt_hours
        if self.hours_remaining <= 0:
            self.current_action = None
            self.hours_remaining = 0.0
            return True
        return False

    def start_action(self, action_name: str, tick: int) -> None:
        """Start a new action."""
        duration = ACTION_DURATIONS.get(action_name, 1.0)
        self.current_action = action_name
        self.action_started_tick = tick
        self.hours_committed = duration
        self.hours_remaining = duration

    def reset_daily(self, tick: int) -> None:
        """Reset daily hour budget."""
        self.daily_hours_used = 0.0
        self.daily_reset_tick = tick


def get_dt_hours(ticks_per_day: int) -> float:
    """Convert ticks_per_day to hours per tick."""
    return 24.0 / ticks_per_day
