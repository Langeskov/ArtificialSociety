"""Population Structure & Sector System (v0.4.4 §2-6).

Initial population structure defines sector distribution at tick 0.
Sectors: primary/secondary/tertiary/quaternary/public/unemployed

Key distinction: Sector ≠ Occupation
- Sector = macro social structure (e.g., Secondary)
- Occupation = specific labor role (e.g., Factory Worker)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional
import random


SECTORS = ("primary", "secondary", "tertiary", "quaternary", "public", "unemployed")

DEFAULT_STRUCTURE = {
    "primary": 0.12,
    "secondary": 0.25,
    "tertiary": 0.38,
    "quaternary": 0.10,
    "public": 0.08,
    "unemployed": 0.07,
}

PRESETS = {
    "agrarian": {"primary": 0.45, "secondary": 0.15, "tertiary": 0.25, "quaternary": 0.03, "public": 0.05, "unemployed": 0.07},
    "industrial": {"primary": 0.15, "secondary": 0.50, "tertiary": 0.25, "quaternary": 0.04, "public": 0.04, "unemployed": 0.02},
    "service": {"primary": 0.08, "secondary": 0.22, "tertiary": 0.52, "quaternary": 0.08, "public": 0.07, "unemployed": 0.03},
    "knowledge": {"primary": 0.05, "secondary": 0.15, "tertiary": 0.35, "quaternary": 0.30, "public": 0.10, "unemployed": 0.05},
    "mixed": DEFAULT_STRUCTURE.copy(),
}

SECTOR_PRODUCTIVITY = {"primary": 1.0, "secondary": 1.2, "tertiary": 0.9, "quaternary": 1.4, "public": 0.8, "unemployed": 0.0}
SECTOR_WAGE_MODIFIER = {"primary": 0.8, "secondary": 1.0, "tertiary": 1.1, "quaternary": 1.5, "public": 1.0, "unemployed": 0.0}


def normalize_structure(s: Dict[str, float]) -> Dict[str, float]:
    total = sum(max(0, s.get(k, 0)) for k in SECTORS)
    if total <= 0:
        return DEFAULT_STRUCTURE.copy()
    return {k: max(0, s.get(k, 0)) / total for k in SECTORS}


def assign_sector(personality, edu: float, region_endow: Dict, rng: random.Random, structure: Dict = None) -> str:
    """Assign initial sector based on personality + education + region (§6)."""
    if structure is None:
        structure = DEFAULT_STRUCTURE
    weights = {s: max(0.01, structure.get(s, 0.01)) for s in SECTORS}
    # Education: high edu -> quaternary/tertiary boost
    weights["quaternary"] *= (1.0 + edu * 2.0)
    weights["tertiary"] *= (1.0 + edu * 1.0)
    weights["primary"] *= (1.0 + (1.0 - edu) * 0.5)
    # Personality
    p = personality.values if (hasattr(personality, "values") and not isinstance(personality, dict)) else personality
    c = p.get("conscientiousness", 0.5)
    o = p.get("openness", 0.5)
    weights["primary"] *= (1.0 + c * 0.3)
    weights["secondary"] *= (1.0 + c * 0.2)
    weights["quaternary"] *= (1.0 + o * 0.5)
    weights["public"] *= (1.0 + (1.0 - o) * 0.2)
    # Region endowment
    weights["primary"] *= (0.5 + region_endow.get("food", 1.0) * 0.5)
    weights["secondary"] *= (0.5 + region_endow.get("energy", 1.0) * 0.5)
    weights["tertiary"] *= (0.5 + region_endow.get("services", 1.0) * 0.5)
    # Weighted random
    total = sum(weights.values())
    r = rng.random() * total
    cum = 0.0
    for s, w in weights.items():
        cum += w
        if r <= cum:
            return s
    return "unemployed"


def compute_skills(sector: str, personality, rng: random.Random) -> Dict[str, float]:
    """Compute initial skill profile (§7). Skills 0~1, higher in assigned sector."""
    p = personality.values if (hasattr(personality, "values") and not isinstance(personality, dict)) else personality
    base = 0.3 + p.get("conscientiousness", 0.5) * 0.4
    skills = {}
    for s in SECTORS:
        if s == "unemployed":
            skills[s] = 0.0
        elif s == sector:
            skills[s] = min(1.0, base + rng.gauss(0.1, 0.05))
        else:
            skills[s] = max(0.0, base * 0.3 + rng.gauss(0.0, 0.05))
    return skills


@dataclass
class PopulationSnapshot:
    primary: float = 0.0
    secondary: float = 0.0
    tertiary: float = 0.0
    quaternary: float = 0.0
    public: float = 0.0
    unemployed: float = 0.0

    @classmethod
    def from_agents(cls, agents) -> "PopulationSnapshot":
        counts = {s: 0 for s in SECTORS}
        total = 0
        for a in agents:
            if not a.alive:
                continue
            counts[getattr(a, "sector", "unemployed")] += 1
            total += 1
        if total == 0:
            return cls()
        return cls(**{s: counts[s] / total for s in SECTORS})

    def to_dict(self) -> Dict[str, float]:
        return {s: getattr(self, s) for s in SECTORS}

    def structural_change(self, initial: "PopulationSnapshot") -> float:
        """L1 distance / 2 (§37)."""
        return sum(abs(getattr(self, s) - getattr(initial, s)) for s in SECTORS) / 2.0


