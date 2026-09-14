"""Agent — the atomic unit of the artificial society (§4).

An agent bundles personality, ideology, resources, memory, goals, relationships,
status and an AI level. The Simulation Engine drives all mutation; the Agent is
a passive state container plus a few convenience accessors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .personality import Personality
from .ideology import Ideology
from .resources import Resources
from ..identity.identity import Identity


@dataclass
class Agent:
    id: str
    age: int = 0
    personality: Personality = field(default_factory=Personality)
    ideology: Ideology = field(default_factory=Ideology)
    resources: Resources = field(default_factory=Resources)
    goals: list = field(default_factory=list)
    memory: list = field(default_factory=list)
    status: dict = field(default_factory=dict)
    group: Optional[str] = None
    ai_level: int = 0
    alive: bool = True
    # v0.2 dynamics fields (§4, §5, §21)
    political_inertia: float = 0.95
    political_velocity: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    recent_events: list = field(default_factory=list)
    known_events: dict = field(default_factory=dict)
    ideology_anchor: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0))
    last_forces: dict = field(default_factory=dict)
    # v0.4 social layer (§14–§24, §47)
    identity: Identity = field(default_factory=Identity)
    location: str = "A"
    beliefs: dict = field(default_factory=dict)
    # v0.4.1 resource layer (§6, §15, §25, §46)
    resource_state: dict = field(default_factory=dict)
    employment_status: str = "self_employed"
    occupation: str = "worker"
    productivity: float = 0.5
    resource_pressure_baseline: float = 0.2
    activity: object = None
    sector: str = 'unemployed'
    skills: dict = None
    education_level: float = 0.5
    employer: Optional[str] = None
    relative_deprivation: float = 0.0
    current_action: str = ""
    action_utility: float = 0.0
    action_feasibility: float = 0.0
    # v0.4.6 long-run political adaptation state
    structural_experience: float = 0.0
    structural_change_count: int = 0
    _anchor_adapt_days: float = 3650.0
    _anchor_long_run_strength: float = 0.005

    def __post_init__(self) -> None:
        self.status.setdefault("anger", 0.0)
        self.status.setdefault("trust_in_government", 0.5)
        self.status.setdefault("survival_mode", False)
        self.status.setdefault("recovery_mode", False)
        self.status.setdefault("_structural_signature", None)
        # Political anchor = initial position. The strength is now explicitly
        # prepared for long-run adaptation instead of leaving the adaptation
        # mechanism in forces.py permanently inactive.
        self.ideology_anchor = (self.ideology.x, self.ideology.y, self.ideology.z)

    def wealth(self) -> float:
        return self.resources.values.get("money", 0.0) + self.resources.values.get("property", 0.0)

    def is_survival(self) -> bool:
        return self.resources.is_starving() or self.resources.is_broke()

    def remember(self, text: str, max_len: int = 30) -> None:
        self.memory.append(text)
        if len(self.memory) > max_len:
            self.memory = self.memory[-max_len:]

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "age": self.age,
            "personality": self.personality.as_dict(),
            "ideology": self.ideology.as_dict(),
            "resources": self.resources.as_dict(),
            "goals": list(self.goals),
            "memory": list(self.memory),
            "status": dict(self.status),
            "group": self.group,
            "ai_level": self.ai_level,
            "alive": self.alive,
            "wealth": round(self.wealth(), 2),
            "political_inertia": round(self.political_inertia, 4),
            "political_velocity": [round(v, 5) for v in self.political_velocity],
            "recent_events": list(self.recent_events),
            "forces": self.last_forces,
            "identity": self.identity.as_dict(),
            "location": self.location,
            "beliefs": {k: v.as_dict() for k, v in self.beliefs.items()},
            "resource_state": dict(self.resource_state),
            "reserved_resources": {k: round(v, 2) for k, v in self.resources.reserved.items()},
            "employment": {
                "status": self.employment_status,
                "occupation": self.occupation,
                "productivity": round(self.productivity, 4),
                "employer": self.employer,
            },
            "relative_deprivation": round(self.relative_deprivation, 4),
            "structural_experience": round(self.structural_experience, 4),
            "structural_change_count": self.structural_change_count,
            "current_action": self.current_action,
            "action_utility": round(self.action_utility, 4),
            "action_feasibility": round(self.action_feasibility, 4),
        }

    def brief(self) -> dict:
        return {
            "id": self.id,
            "age": self.age,
            "x": round(self.ideology.x, 4),
            "y": round(self.ideology.y, 4),
            "z": round(self.ideology.z, 4),
            "origin_label": self.ideology.origin_label,
            "money": round(self.resources.values.get("money", 0.0), 2),
            "food": round(self.resources.values.get("food", 0.0), 2),
            "influence": round(self.resources.values.get("influence", 0.0), 2),
            "group": self.group,
            "alive": self.alive,
            "anger": round(self.status.get("anger", 0.0), 3),
            "primary_group": self.identity.primary_group,
            "group_count": self.identity.membership_count(),
            "location": self.location,
            "vx": round(self.political_velocity[0], 5),
            "vy": round(self.political_velocity[1], 5),
            "vz": round(self.political_velocity[2], 5),
            "inertia": round(self.political_inertia, 3),
            "resource_security": round(self.resource_state.get("security", 0.0), 3),
            "resource_pressure": round(self.resource_state.get("pressure", 0.0), 3),
            "structural_experience": round(self.structural_experience, 4),
        }
