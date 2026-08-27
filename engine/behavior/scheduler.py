"""Action Scheduler (v0.4.5.1 — Runtime State Machine Hotfix).

Actions have duration in simulated hours. Agent has 24-hour daily budget.
Can't re-choose action while current one is in progress.

Key change v0.4.5.1:
  - Explicit state machine: IDLE → RUNNING → COMPLETED → IDLE
  - advance() no longer resets current_action on completion
  - Completion handler uses saved action name, not post-reset state
  - Daily budget reset does NOT cancel in-progress actions
  - Cross-day actions continue past midnight
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ActionState(str, Enum):
    """v0.4.5.1 §2: Explicit action lifecycle states."""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


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
    """Agent's current activity state.

    v0.4.5.1: Explicit state machine instead of None-based inference.
    """
    # Current state
    state: ActionState = ActionState.IDLE

    # Current action info (valid when state == RUNNING or COMPLETED)
    current_action: Optional[str] = None
    action_started_tick: int = 0
    hours_committed: float = 0.0  # total duration of the action
    hours_remaining: float = 0.0  # hours left to complete

    # Completion data (valid when state == COMPLETED)
    completed_action: Optional[str] = None
    completed_tick: int = 0
    hours_completed: float = 0.0  # actual hours spent

    # Daily budget tracking
    daily_hours_used: float = 0.0
    daily_reset_tick: int = 0

    # Stall detection
    last_state_change_tick: int = 0

    def is_busy(self) -> bool:
        """Agent is currently performing an action."""
        return self.state == ActionState.RUNNING

    def is_idle(self) -> bool:
        """Agent is idle and can choose a new action."""
        return self.state == ActionState.IDLE

    def is_completed(self) -> bool:
        """Action just completed, waiting for completion handler."""
        return self.state == ActionState.COMPLETED

    def available_hours(self) -> float:
        """Hours remaining in daily budget (24h - used).

        v0.4.5.1 §7: This only affects NEW action eligibility, not in-progress actions.
        """
        return max(0.0, 24.0 - self.daily_hours_used)

    def advance(self, dt_hours: float) -> bool:
        """Advance current action by dt_hours.

        Returns True if action completed this tick.

        v0.4.5.1 §1: Does NOT reset current_action. State transitions to COMPLETED.
        Completion handler must call complete() to return to IDLE.
        """
        if self.state != ActionState.RUNNING:
            return False

        self.hours_remaining -= dt_hours
        self.daily_hours_used += dt_hours

        if self.hours_remaining <= 0:
            # Action completed
            self.completed_action = self.current_action
            self.completed_tick = self.last_state_change_tick
            self.hours_completed = self.hours_committed
            self.state = ActionState.COMPLETED
            self.hours_remaining = 0.0
            return True

        return False

    def start_action(self, action_name: str, tick: int) -> None:
        """Start a new action. Must be IDLE or COMPLETED."""
        duration = ACTION_DURATIONS.get(action_name, 1.0)
        self.current_action = action_name
        self.action_started_tick = tick
        self.hours_committed = duration
        self.hours_remaining = duration
        self.state = ActionState.RUNNING
        self.last_state_change_tick = tick

    def complete(self, tick: int) -> None:
        """Mark completion as processed. Returns to IDLE.

        v0.4.5.1 §1: Called after completion handler has run.
        """
        self.current_action = None
        self.hours_remaining = 0.0
        self.hours_committed = 0.0
        self.state = ActionState.IDLE
        self.last_state_change_tick = tick

    def reset_daily(self, tick: int) -> None:
        """Reset daily hour budget.

        v0.4.5.1 §7-§8: Does NOT cancel in-progress actions.
        Only resets the budget for NEW action eligibility.
        """
        self.daily_hours_used = 0.0
        self.daily_reset_tick = tick
        # Note: does NOT modify current_action, hours_remaining, or state

    def snapshot(self) -> dict:
        """Diagnostic snapshot."""
        return {
            "state": self.state.value,
            "current_action": self.current_action,
            "hours_remaining": round(self.hours_remaining, 2),
            "hours_committed": round(self.hours_committed, 2),
            "daily_hours_used": round(self.daily_hours_used, 2),
            "completed_action": self.completed_action,
            "last_state_change_tick": self.last_state_change_tick,
        }


def get_dt_hours(ticks_per_day: int) -> float:
    """Convert ticks_per_day to hours per tick."""
    return 24.0 / ticks_per_day
