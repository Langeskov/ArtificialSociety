"""Event Loop Detector — v0.4.5 §31-§33.

Detects:
  - Causal loops: A → B → A, A → B → C → A
  - Loop strength: product of edge strengths
  - Event periodicity: recurring events with stable intervals
  - Event dominance: when two event types dominate >80% of events
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .event import Event, EventChain, SOURCE_TYPE


@dataclass
class DetectedLoop:
    """A detected causal loop."""
    event_types: list[str]       # e.g. ["food_crisis", "protest", "production_loss"]
    period_ticks: float = 0.0    # average period between loop completions
    strength: float = 0.0        # product of edge strengths
    occurrences: int = 0         # how many times this loop has fired
    last_tick: int = 0


@dataclass
class EventPeriodicity:
    """Periodicity analysis for a single event type."""
    event_type: str
    mean_delta: float = 0.0      # mean ticks between occurrences
    std_delta: float = 0.0       # standard deviation
    count: int = 0               # total occurrences
    is_periodic: bool = False    # true if std/mean < 0.3 (stable period)


class EventLoopDetector:
    """Detects causal loops and periodic patterns in event chains.

    Uses rolling window analysis to avoid scanning full history.
    """

    def __init__(self, window_size: int = 500) -> None:
        self.window_size = window_size
        self._detected_loops: list[DetectedLoop] = []
        self._periodicity_cache: dict[str, EventPeriodicity] = {}

    def analyze(self, chain: EventChain, current_tick: int) -> dict:
        """Run full analysis on the event chain.

        Returns a diagnostics dict with loops, periodicity, dominance.
        """
        recent = [e for e in chain.events if current_tick - e.tick <= self.window_size]

        loops = self._detect_loops(chain, recent)
        periodicity = self._detect_periodicity(recent)
        dominance = self._detect_dominance(recent)

        self._detected_loops = loops

        return {
            "loops": [
                {
                    "types": l.event_types,
                    "period": round(l.period_ticks, 1),
                    "strength": round(l.strength, 4),
                    "occurrences": l.occurrences,
                }
                for l in loops
            ],
            "loop_count": len(loops),
            "strong_loops": sum(1 for l in loops if l.strength > 0.8),
            "periodicity": {
                t: {
                    "mean_delta": round(p.mean_delta, 1),
                    "std_delta": round(p.std_delta, 1),
                    "is_periodic": p.is_periodic,
                }
                for t, p in periodicity.items()
                if p.count >= 3
            },
            "dominance": dominance,
            "event_diversity": self._compute_diversity(recent),
        }

    def _detect_loops(self, chain: EventChain, recent: list[Event]) -> list[DetectedLoop]:
        """Detect causal loops in the event chain.

        Looks for patterns where event type A leads to B leads back to A.
        """
        loops = []
        # Build type-level causal graph from links
        type_edges: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        type_to_event: dict[str, list[Event]] = defaultdict(list)

        for e in recent:
            type_to_event[e.type].append(e)

        for cause_id, effect_id in chain.links:
            cause = chain.get(cause_id)
            effect = chain.get(effect_id)
            if cause and effect and cause in recent and effect in recent:
                type_edges[cause.type][effect.type] += 1.0

        # Normalize edge weights
        for src in type_edges:
            total = sum(type_edges[src].values())
            if total > 0:
                for tgt in type_edges[src]:
                    type_edges[src][tgt] /= total

        # Find cycles of length 2 and 3
        all_types = list(type_edges.keys())

        # Length-2 cycles: A → B → A
        for a in all_types:
            for b in type_edges.get(a, {}):
                if b in type_edges and a in type_edges[b]:
                    strength = type_edges[a][b] * type_edges[b][a]
                    # Count occurrences: how many times A appeared after B
                    a_events = sorted(type_to_event.get(a, []), key=lambda e: e.tick)
                    b_events = sorted(type_to_event.get(b, []), key=lambda e: e.tick)
                    occurrences = 0
                    periods = []
                    last_b_tick = -10**9
                    for ae in a_events:
                        # Find most recent B before this A
                        for be in reversed(b_events):
                            if be.tick < ae.tick:
                                if ae.tick - last_b_tick > 5:  # avoid double counting
                                    occurrences += 1
                                    periods.append(ae.tick - last_b_tick)
                                last_b_tick = ae.tick
                                break

                    avg_period = sum(periods) / len(periods) if periods else 0.0

                    if strength > 0.1:
                        loops.append(DetectedLoop(
                            event_types=[a, b],
                            period_ticks=avg_period,
                            strength=strength,
                            occurrences=max(occurrences, 1),
                        ))

        # Length-3 cycles: A → B → C → A
        for a in all_types:
            for b in type_edges.get(a, {}):
                for c in type_edges.get(b, {}):
                    if a in type_edges.get(c, {}):
                        strength = type_edges[a][b] * type_edges[b][c] * type_edges[c][a]
                        if strength > 0.05:
                            loops.append(DetectedLoop(
                                event_types=[a, b, c],
                                period_ticks=0.0,  # would need more analysis
                                strength=strength,
                                occurrences=1,
                            ))

        return loops

    def _detect_periodicity(self, recent: list[Event]) -> dict[str, EventPeriodicity]:
        """Detect periodic patterns in event occurrences."""
        result = {}
        by_type: dict[str, list[int]] = defaultdict(list)

        for e in recent:
            by_type[e.type].append(e.tick)

        for event_type, ticks in by_type.items():
            if len(ticks) < 3:
                continue

            ticks.sort()
            deltas = [ticks[i+1] - ticks[i] for i in range(len(ticks) - 1)]
            mean_delta = sum(deltas) / len(deltas)
            variance = sum((d - mean_delta) ** 2 for d in deltas) / len(deltas)
            std_delta = variance ** 0.5

            # Periodic if coefficient of variation < 0.3
            is_periodic = (std_delta / max(mean_delta, 1)) < 0.3 and len(deltas) >= 3

            result[event_type] = EventPeriodicity(
                event_type=event_type,
                mean_delta=mean_delta,
                std_delta=std_delta,
                count=len(ticks),
                is_periodic=is_periodic,
            )
            self._periodicity_cache[event_type] = result[event_type]

        return result

    def _detect_dominance(self, recent: list[Event]) -> dict:
        """Detect if two event types dominate >80% of events."""
        if not recent:
            return {"dominant_types": [], "dominance_ratio": 0.0}

        counts: dict[str, int] = defaultdict(int)
        for e in recent:
            counts[e.type] += 1

        total = len(recent)
        sorted_types = sorted(counts.items(), key=lambda x: x[1], reverse=True)

        if len(sorted_types) >= 2:
            top2_count = sorted_types[0][1] + sorted_types[1][1]
            ratio = top2_count / total
            if ratio > 0.8:
                return {
                    "dominant_types": [sorted_types[0][0], sorted_types[1][0]],
                    "dominance_ratio": round(ratio, 3),
                }

        return {"dominant_types": [], "dominance_ratio": 0.0}

    def _compute_diversity(self, recent: list[Event]) -> float:
        """Compute event type diversity (0-1, higher = more diverse)."""
        if not recent:
            return 0.0

        counts: dict[str, int] = defaultdict(int)
        for e in recent:
            counts[e.type] += 1

        n = len(recent)
        # Shannon entropy normalized
        import math
        entropy = 0.0
        for count in counts.values():
            p = count / n
            if p > 0:
                entropy -= p * math.log(p)

        max_entropy = math.log(len(counts)) if len(counts) > 1 else 1.0
        return entropy / max_entropy if max_entropy > 0 else 0.0

    def get_detected_loops(self) -> list[DetectedLoop]:
        return list(self._detected_loops)

    def get_periodicity(self, event_type: str) -> Optional[EventPeriodicity]:
        return self._periodicity_cache.get(event_type)
