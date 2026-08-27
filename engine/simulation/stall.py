"""Simulation Stall Detector — v0.4.5.1 §10-§12.

Detects when the simulation runtime is stuck:
  - Zero-Progress Detector: per-agent stall detection
  - Society-Level Stall Detector: no state changes for N ticks
  - Tick Progress Watchdog: clock must advance each step
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentStallInfo:
    """Diagnostic info for a stalled agent."""
    agent_id: str
    current_action: Optional[str]
    action_state: str
    hours_remaining: float
    daily_hours_used: float
    last_state_change_tick: int
    stalled_ticks: int


@dataclass
class StallReport:
    """Full stall diagnostic report."""
    tick: int
    simulated_day: float
    active_agents: int
    busy_agents: int
    idle_agents: int
    completed_agents: int
    stalled_agents: int
    actions_started: int
    actions_completed: int
    resource_changes: int
    events_created: int
    events_executed: int
    active_crises: int
    queued_events: int
    mean_food: float
    mean_money: float
    mean_energy: float
    production_disruption: float


class SimulationStallDetector:
    """v0.4.5.1 §11: Detects when simulation makes no progress.

    Tracks per-tick state changes and raises alarm when N consecutive ticks
    show no agent state changes, no events, and no resource changes.
    """

    def __init__(self, stall_threshold_ticks: int = 100) -> None:
        self.stall_threshold = stall_threshold_ticks
        self._consecutive_idle_ticks: int = 0
        self._last_report: Optional[StallReport] = None
        self._is_stalled: bool = False

    def update(self, agent_state_changes: int, events_created: int,
               resource_changes: int) -> None:
        """Check if this tick showed any progress."""
        if agent_state_changes == 0 and events_created == 0 and resource_changes == 0:
            self._consecutive_idle_ticks += 1
        else:
            self._consecutive_idle_ticks = 0

        if self._consecutive_idle_ticks >= self.stall_threshold:
            self._is_stalled = True

    @property
    def is_stalled(self) -> bool:
        return self._is_stalled

    @property
    def idle_ticks(self) -> int:
        return self._consecutive_idle_ticks

    def reset(self) -> None:
        """Manual reset (NOT automatic per §11)."""
        self._consecutive_idle_ticks = 0
        self._is_stalled = False


class TickProgressWatchdog:
    """v0.4.5.1 §12: Ensures simulation clock advances each step.

    Raises RuntimeError if clock did not advance.
    """

    def __init__(self) -> None:
        self._last_tick: int = -1

    def check(self, current_tick: int) -> None:
        """Verify clock has advanced since last check."""
        if current_tick <= self._last_tick:
            raise RuntimeError(
                f"Simulation clock did not advance: "
                f"last_tick={self._last_tick}, current_tick={current_tick}"
            )
        self._last_tick = current_tick

    def reset(self) -> None:
        self._last_tick = -1


class ZeroProgressDetector:
    """v0.4.5.1 §10: Per-agent stall detection.

    If an agent's state hasn't changed for N ticks, flag it as stalled.
    """

    def __init__(self, stall_threshold_ticks: int = 500) -> None:
        self.stall_threshold = stall_threshold_ticks

    def detect_stalled(self, agents: list, current_tick: int) -> list[AgentStallInfo]:
        """Find agents that haven't changed state in too long."""
        stalled = []
        for a in agents:
            if not a.alive:
                continue
            act_state = getattr(a, "activity", None)
            if act_state is None:
                continue
            ticks_since_change = current_tick - act_state.last_state_change_tick
            if ticks_since_change > self.stall_threshold:
                stalled.append(AgentStallInfo(
                    agent_id=a.id,
                    current_action=act_state.current_action,
                    action_state=act_state.state.value,
                    hours_remaining=act_state.hours_remaining,
                    daily_hours_used=act_state.daily_hours_used,
                    last_state_change_tick=act_state.last_state_change_tick,
                    stalled_ticks=ticks_since_change,
                ))
        return stalled


def build_stall_report(society, tick: int) -> StallReport:
    """Build a comprehensive stall diagnostic report."""
    agents = [a for a in society.agents if a.alive]
    ticks_per_day = society.config.get("ticks_per_day", 100)
    day = tick / ticks_per_day

    busy = 0
    idle = 0
    completed = 0
    for a in agents:
        act_state = getattr(a, "activity", None)
        if act_state is None:
            idle += 1
            continue
        if act_state.is_busy():
            busy += 1
        elif act_state.is_completed():
            completed += 1
        else:
            idle += 1

    mean_food = sum(a.resources.values.get("food", 0) for a in agents) / max(len(agents), 1)
    mean_money = sum(a.resources.values.get("money", 0) for a in agents) / max(len(agents), 1)
    mean_energy = sum(a.resources.values.get("energy", 0) for a in agents) / max(len(agents), 1)

    cm = getattr(society, "crisis_manager", None)
    active_crises = 0
    if cm:
        if cm.food.is_crisis():
            active_crises += 1
        if cm.protest.is_crisis():
            active_crises += 1
        if cm.economic.is_crisis():
            active_crises += 1

    queue = getattr(society, "_event_queue", None)
    queued_events = queue.size() if queue else 0

    return StallReport(
        tick=tick,
        simulated_day=round(day, 2),
        active_agents=len(agents),
        busy_agents=busy,
        idle_agents=idle,
        completed_agents=completed,
        stalled_agents=0,
        actions_started=0,
        actions_completed=0,
        resource_changes=0,
        events_created=0,
        events_executed=0,
        active_crises=active_crises,
        queued_events=queued_events,
        mean_food=round(mean_food, 2),
        mean_money=round(mean_money, 2),
        mean_energy=round(mean_energy, 2),
        production_disruption=round(getattr(society, "production_disruption", 0.0), 4),
    )


def format_stall_report(report: StallReport) -> str:
    """Format a human-readable stall report."""
    return (
        f"═══ STALL DIAGNOSTICS ═══\n"
        f"Tick: {report.tick}  Day: {report.simulated_day}\n"
        f"Agents: {report.active_agents} active, {report.busy_agents} busy, "
        f"{report.idle_agents} idle, {report.completed_agents} completed\n"
        f"Crises: {report.active_crises} active, {report.queued_events} queued events\n"
        f"Resources: food={report.mean_food}, money={report.mean_money}, "
        f"energy={report.mean_energy}\n"
        f"Production disruption: {report.production_disruption}\n"
    )
