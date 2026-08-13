"""Personality model — multi-dimensional, independent from political stance.

Ten dimensions, each in [0, 1]. Personality is *not* ideology (project §5);
a high-Authority person may still hold any political view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Optional

DIMENSIONS: tuple[str, ...] = (
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
    "risk_tolerance",
    "trust",
    "aggression",
    "empathy",
    "authority_preference",
)

# Human-readable labels for the UI / inspector.
LABELS: dict[str, str] = {
    "openness": "Openness",
    "conscientiousness": "Conscientiousness",
    "extraversion": "Extraversion",
    "agreeableness": "Agreeableness",
    "neuroticism": "Neuroticism",
    "risk_tolerance": "Risk Tolerance",
    "trust": "Trust",
    "aggression": "Aggression",
    "empathy": "Empathy",
    "authority_preference": "Authority Preference",
}


@dataclass
class Personality:
    values: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for d in DIMENSIONS:
            self.values.setdefault(d, 0.5)

    def __getitem__(self, key: str) -> float:
        return self.values[key]

    def as_dict(self) -> dict:
        return dict(self.values)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def sample_from_bucket(rng: random.Random, bucket: str) -> float:
    """Map a high/neutral/low bucket to a [0,1] sample.

    high   → 0.75 (σ 0.12)
    neutral→ 0.50 (σ 0.18)
    low    → 0.25 (σ 0.12)
    """
    if bucket == "high":
        return clamp01(rng.gauss(0.75, 0.12))
    if bucket == "low":
        return clamp01(rng.gauss(0.25, 0.12))
    return clamp01(rng.gauss(0.50, 0.18))


def generate(distribution: Optional[dict], rng: random.Random) -> Personality:
    """Generate a personality from a population-level distribution config.

    distribution: {"agreeableness": {"high": 0.3, "neutral": 0.4, "low": 0.3}, ...}
    Missing dimensions default to a neutral bell curve.
    """
    values: dict[str, float] = {}
    for d in DIMENSIONS:
        conf = (distribution or {}).get(d)
        if conf and isinstance(conf, dict):
            high = conf.get("high", 0.0)
            neutral = conf.get("neutral", 0.0)
            low = conf.get("low", 0.0)
            total = high + neutral + low
            if total <= 0:
                values[d] = clamp01(rng.gauss(0.5, 0.18))
                continue
            r = rng.random() * total
            if r < high:
                bucket = "high"
            elif r < high + neutral:
                bucket = "neutral"
            else:
                bucket = "low"
            values[d] = sample_from_bucket(rng, bucket)
        else:
            values[d] = clamp01(rng.gauss(0.5, 0.18))
    return Personality(values=values)
