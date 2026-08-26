"""Event Ecology Dashboard — v0.4.5 §29, §30, §34, §55.

Provides diagnostics for the event ecosystem:
  - Event counts by source type (ENDOGENOUS/EXOGENOUS/RECOVERY)
  - Uncaused event count (should be 0 for endogenous)
  - Loop detection results
  - Event diversity and dominance
  - Periodicity analysis
  - Causal chain statistics
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .event import Event, EventChain, SOURCE_TYPE
from .loops import EventLoopDetector


@dataclass
class EventEcologyStats:
    """Statistics about the event ecosystem."""
    total_events: int = 0
    endogenous_count: int = 0
    exogenous_count: int = 0
    recovery_count: int = 0
    uncaused_count: int = 0

    loop_count: int = 0
    strong_loop_count: int = 0
    periodic_event_count: int = 0

    event_diversity: float = 0.0
    dominant_types: list = field(default_factory=list)
    dominance_ratio: float = 0.0

    mean_causal_chain_length: float = 0.0
    max_causal_chain_length: int = 0

    endogenous_ratio: float = 0.0
    exogenous_ratio: float = 0.0
    recovery_ratio: float = 0.0


class EventEcologyDashboard:
    """Computes and reports event ecology diagnostics."""

    def __init__(self) -> None:
        self.loop_detector = EventLoopDetector()
        self._last_stats: Optional[EventEcologyStats] = None

    def compute(self, chain: EventChain, current_tick: int) -> EventEcologyStats:
        """Compute full ecology statistics."""
        total = len(chain.events)
        if total == 0:
            return EventEcologyStats()

        endogenous = chain.endogenous_count()
        exogenous = chain.exogenous_count()
        recovery = chain.recovery_count()
        uncaused = chain.uncaused_count()

        # Loop analysis
        loop_analysis = self.loop_detector.analyze(chain, current_tick)

        # Causal chain analysis
        chain_stats = self._analyze_causal_chains(chain)

        stats = EventEcologyStats(
            total_events=total,
            endogenous_count=endogenous,
            exogenous_count=exogenous,
            recovery_count=recovery,
            uncaused_count=uncaused,
            loop_count=loop_analysis.get("loop_count", 0),
            strong_loop_count=loop_analysis.get("strong_loops", 0),
            periodic_event_count=sum(
                1 for p in loop_analysis.get("periodicity", {}).values()
                if p.get("is_periodic", False)
            ),
            event_diversity=loop_analysis.get("event_diversity", 0.0),
            dominant_types=loop_analysis.get("dominance", {}).get("dominant_types", []),
            dominance_ratio=loop_analysis.get("dominance", {}).get("dominance_ratio", 0.0),
            mean_causal_chain_length=chain_stats["mean_length"],
            max_causal_chain_length=chain_stats["max_length"],
            endogenous_ratio=endogenous / total if total > 0 else 0.0,
            exogenous_ratio=exogenous / total if total > 0 else 0.0,
            recovery_ratio=recovery / total if total > 0 else 0.0,
        )

        self._last_stats = stats
        return stats

    def _analyze_causal_chains(self, chain: EventChain) -> dict:
        """Analyze causal chain lengths."""
        if not chain.links:
            return {"mean_length": 0.0, "max_length": 0}

        # Build adjacency list
        children: dict[str, list[str]] = defaultdict(list)
        for cause, effect in chain.links:
            children[cause].append(effect)

        # Find root events (no cause)
        caused = {e for _, e in chain.links}
        roots = [e.event_id for e in chain.events if e.event_id not in caused]

        # BFS to find longest chain from each root
        def chain_length(start: str) -> int:
            visited = set()
            queue = [(start, 0)]
            max_depth = 0
            while queue:
                node, depth = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                max_depth = max(max_depth, depth)
                for child in children.get(node, []):
                    queue.append((child, depth + 1))
            return max_depth

        lengths = [chain_length(r) for r in roots]
        if not lengths:
            return {"mean_length": 0.0, "max_length": 0}

        return {
            "mean_length": sum(lengths) / len(lengths),
            "max_length": max(lengths),
        }

    def format_report(self, stats: Optional[EventEcologyStats] = None) -> str:
        """Format a human-readable report."""
        if stats is None:
            stats = self._last_stats
        if stats is None:
            return "No event ecology data available."

        lines = [
            "═══ EVENT ECOLOGY ═══",
            "",
            f"Total Events:       {stats.total_events}",
            f"  Endogenous:       {stats.endogenous_count}  ({stats.endogenous_ratio:.0%})",
            f"  Exogenous:        {stats.exogenous_count}  ({stats.exogenous_ratio:.0%})",
            f"  Recovery:         {stats.recovery_count}  ({stats.recovery_ratio:.0%})",
            "",
            f"Uncaused Events:    {stats.uncaused_count}",
            "",
            f"Causal Events:      {stats.endogenous_count - stats.uncaused_count}",
            f"Active Loops:       {stats.loop_count}",
            f"Strong Loops:       {stats.strong_loop_count}",
            f"Periodic Events:    {stats.periodic_event_count}",
            "",
            f"Event Diversity:    {stats.event_diversity:.2f}",
        ]

        if stats.dominant_types:
            lines.append(f"Event Dominance:    {', '.join(stats.dominant_types)} ({stats.dominance_ratio:.0%})")

        lines.extend([
            "",
            f"Mean Chain Length:   {stats.mean_causal_chain_length:.1f}",
            f"Max Chain Length:    {stats.max_causal_chain_length}",
        ])

        return "\n".join(lines)

    def format_causality_scorecard(self, chain: EventChain) -> str:
        """§38: Generate Event Causality Scorecard."""
        by_type: dict[str, list[Event]] = defaultdict(list)
        for e in chain.events:
            by_type[e.type].append(e)

        lines = ["═══ EVENT CAUSALITY ═══", ""]

        for event_type, events in sorted(by_type.items()):
            total = len(events)
            endogenous = sum(1 for e in events if e.source_type == SOURCE_TYPE.ENDOGENOUS)
            exogenous = sum(1 for e in events if e.source_type == SOURCE_TYPE.EXOGENOUS)
            unclear = sum(1 for e in events if e.source_type == SOURCE_TYPE.ENDOGENOUS and not e.evidence)

            if total == 0:
                continue

            lines.append(f"{event_type}:")
            lines.append(f"  endogenous: {endogenous/total:.0%}")
            if exogenous > 0:
                lines.append(f"  exogenous:  {exogenous/total:.0%}")
            if unclear > 0:
                lines.append(f"  unclear:    {unclear/total:.0%}")
            lines.append("")

        return "\n".join(lines)
