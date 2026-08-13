"""3D political spectrum — the ideological core of the project.

Three axes, all in [-1, +1] (project §7):
    X = Economic Freedom (+) ↔ Economic Control (-)
    Y = Liberty (-) ↔ Authority (+)
    Z = Individualism (+) ↔ Collectivism (-)

"Ideologies" are only *generation templates* (centroids + spread), never hard
labels — an agent's true position drifts over time (§8).
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Optional

# Ideology generation templates: a 3D centroid plus a gaussian spread.
# These are initial-condition priors, not absolute definitions (§8).
IDEOLOGY_TEMPLATES: dict[str, dict] = {
    "liberal":        {"center": (-0.35, -0.45,  0.10), "sigma": 0.18, "color": "#3b82f6"},
    "conservative":   {"center": ( 0.35,  0.40,  0.20), "sigma": 0.18, "color": "#ef4444"},
    "libertarian":    {"center": ( 0.50, -0.65,  0.55), "sigma": 0.18, "color": "#f59e0b"},
    "socialist":      {"center": (-0.70,  0.10, -0.35), "sigma": 0.18, "color": "#10b981"},
    "authoritarian":  {"center": ( 0.20,  0.80, -0.40), "sigma": 0.18, "color": "#8b5cf6"},
    "communitarian":  {"center": (-0.30,  0.20, -0.60), "sigma": 0.20, "color": "#14b8a6"},
    "anarchist":      {"center": ( 0.40, -0.80,  0.45), "sigma": 0.20, "color": "#f43f5e"},
    "centrist":       {"center": ( 0.00,  0.00,  0.00), "sigma": 0.12, "color": "#94a3b8"},
}

# Default axis definitions; user-editable at runtime (§10).
DEFAULT_AXES = {
    "x": {"name": "经济自由 ↔ 经济管控", "positive": "经济自由", "negative": "经济管控"},
    "y": {"name": "自由 ↔ 权威", "positive": "权威", "negative": "自由"},
    "z": {"name": "个人主义 ↔ 集体主义", "positive": "个人主义", "negative": "集体主义"},
}

# Chinese display names for ideology templates (UI / inspector / legend).
IDEOLOGY_LABELS: dict[str, str] = {
    "liberal": "自由派",
    "conservative": "保守派",
    "socialist": "社会主义",
    "libertarian": "自由意志",
    "authoritarian": "威权主义",
    "communitarian": "社群主义",
    "anarchist": "无政府主义",
    "centrist": "中间派",
}


def clamp_axis(v: float) -> float:
    return max(-1.0, min(1.0, v))


@dataclass
class Ideology:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    origin_label: str = "centrist"  # generation template only, not a live label

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def as_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "z": self.z, "origin_label": self.origin_label}

    def distance(self, other: "Ideology") -> float:
        dx = self.x - other.x
        dy = self.y - other.y
        dz = self.z - other.z
        return (dx * dx + dy * dy + dz * dz) ** 0.5

    def drift_toward(self, target: tuple[float, float, float], strength: float) -> None:
        """Move this position toward a target by a bounded fraction."""
        s = max(0.0, min(1.0, strength))
        self.x = clamp_axis(self.x + (target[0] - self.x) * s)
        self.y = clamp_axis(self.y + (target[1] - self.y) * s)
        self.z = clamp_axis(self.z + (target[2] - self.z) * s)


def sample_ideology(label: str, rng: random.Random) -> Ideology:
    """Sample an ideology position from a template centroid + gaussian."""
    tmpl = IDEOLOGY_TEMPLATES.get(label, IDEOLOGY_TEMPLATES["centrist"])
    cx, cy, cz = tmpl["center"]
    s = tmpl["sigma"]
    return Ideology(
        x=clamp_axis(rng.gauss(cx, s)),
        y=clamp_axis(rng.gauss(cy, s)),
        z=clamp_axis(rng.gauss(cz, s)),
        origin_label=label,
    )
