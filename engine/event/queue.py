"""Event Queue — v0.4.5 §52.

Instead of immediately processing all events, the queue supports:
  - Deferred execution (events scheduled for future ticks)
  - Causal depth limiting (max_causal_depth_per_tick, §51)
  - Priority ordering (EXOGENOUS > CRITICAL ENDOGENOUS > ENDOGENOUS > RECOVERY, §53)
  - Causal delay (min_ticks between cause and effect, §24)
  - Causal memory (prevents A→B→A loops, §25)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import heapq

from .event import Event, SOURCE_TYPE


# Priority values (lower = higher priority, §53)
PRIORITY: dict[SOURCE_TYPE, int] = {
    SOURCE_TYPE.EXOGENOUS: 0,
    SOURCE_TYPE.ENDOGENOUS: 1,
    SOURCE_TYPE.RECOVERY: 2,
}

# Critical endogenous events get priority 0 (same as exogenous)
CRITICAL_EVENTS = {"natural_disaster", "war", "pandemic", "economic_crisis"}


@dataclass(order=True)
class QueuedEvent:
    """An event waiting in the queue."""
    priority: int
    scheduled_tick: int = field(compare=True)
    causal_depth: int = field(default=0, compare=False)
    event_data: dict = field(default_factory=dict, compare=False)


class EventQueue:
    """Manages deferred event creation with causal delay and depth limits.

    v0.4.5 §24: minimum causal delay prevents immediate recursive triggers.
    v0.4.5 §51: max causal depth per tick prevents event explosion.
    v0.4.5 §25: causal memory prevents A→B→A loops.
    """

    def __init__(self, min_causal_delay: int = 5, max_causal_depth: int = 2) -> None:
        self._queue: list[QueuedEvent] = []
        self.min_causal_delay = min_causal_delay  # §24
        self.max_causal_depth = max_causal_depth  # §51
        # §25: causal memory — records source→target→tick
        self._causal_memory: list[tuple[str, str, int]] = []
        self._causal_memory_window: int = 200  # ticks to remember

    def enqueue(
        self,
        event_data: dict,
        tick: int,
        source_type: SOURCE_TYPE = SOURCE_TYPE.ENDOGENOUS,
        causal_depth: int = 0,
        cause_event_type: Optional[str] = None,
    ) -> bool:
        """Add an event to the queue.

        Returns False if the event is rejected (causal loop or depth limit).
        """
        event_type = event_data.get("type", "unknown")

        # §51: Check causal depth limit
        if causal_depth > self.max_causal_depth:
            return False

        # §25: Check causal memory (prevent A→B→A)
        if cause_event_type:
            for src, tgt, mem_tick in self._causal_memory:
                if (tgt == event_type and src == cause_event_type
                        and tick - mem_tick < self._causal_memory_window):
                    # This would create a reverse edge — reject
                    return False

        # §24: Apply minimum causal delay
        scheduled_tick = tick
        if causal_depth > 0:
            scheduled_tick = tick + self.min_causal_delay

        # §53: Assign priority
        priority = PRIORITY.get(source_type, 1)
        if event_type in CRITICAL_EVENTS:
            priority = 0

        entry = QueuedEvent(
            priority=priority,
            scheduled_tick=scheduled_tick,
            causal_depth=causal_depth,
            event_data=event_data,
        )
        heapq.heappush(self._queue, entry)

        # Record in causal memory
        if cause_event_type:
            self._causal_memory.append((cause_event_type, event_type, tick))

        return True

    def dequeue(self, current_tick: int) -> list[dict]:
        """Dequeue all events scheduled for this tick or earlier."""
        ready = []
        while self._queue and self._queue[0].scheduled_tick <= current_tick:
            entry = heapq.heappop(self._queue)
            ready.append(entry.event_data)
        return ready

    def cleanup_causal_memory(self, current_tick: int) -> None:
        """Remove old causal memory entries."""
        cutoff = current_tick - self._causal_memory_window
        self._causal_memory = [
            (src, tgt, t) for src, tgt, t in self._causal_memory
            if t > cutoff
        ]

    def size(self) -> int:
        return len(self._queue)

    def pending_types(self) -> dict[str, int]:
        """Count pending events by type."""
        counts: dict[str, int] = {}
        for entry in self._queue:
            t = entry.event_data.get("type", "unknown")
            counts[t] = counts.get(t, 0) + 1
        return counts


class CausalCooldown:
    """v0.4.5 §25: Prevents event A from being re-triggered by its own effect B
    within a short window.

    Records causal chains and blocks reverse triggers.
    """

    def __init__(self, cooldown_ticks: int = 50) -> None:
        self.cooldown_ticks = cooldown_ticks
        self._edges: list[tuple[str, str, int]] = []  # (source_type, target_type, tick)

    def record(self, source_type: str, target_type: str, tick: int) -> None:
        """Record a causal edge."""
        self._edges.append((source_type, target_type, tick))

    def is_blocked(self, source_type: str, target_type: str, tick: int) -> bool:
        """Check if target→source would create a reverse edge within cooldown."""
        for src, tgt, t in self._edges:
            if (src == target_type and tgt == source_type
                    and tick - t < self.cooldown_ticks):
                return True
        return False

    def cleanup(self, current_tick: int) -> None:
        """Remove expired entries."""
        cutoff = current_tick - self.cooldown_ticks
        self._edges = [(s, t, tk) for s, t, tk in self._edges if tk > cutoff]
