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
    ai_level: int = 0            # 0 rule, 1 statistical, 2 small model, 3 LLM, 4 high-intelligence
    alive: bool = True
    # v0.2 dynamics fields (§4, §5, §21)
    political_inertia: float = 0.95
    political_velocity: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    recent_events: list = field(default_factory=list)   # [{event_id, type, tick, strength}]
    known_events: dict = field(default_factory=dict)     # event_id -> tick the agent learned it
    ideology_anchor: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0))  # 个人政治锚点
    last_forces: dict = field(default_factory=dict)       # v0.3: 最近一次力分解（可解释性 §5）

    def __post_init__(self) -> None:
        self.status.setdefault("anger", 0.0)
        self.status.setdefault("trust_in_government", 0.5)
        self.status.setdefault("survival_mode", False)
        self.status.setdefault("recovery_mode", False)
        # 个人政治锚点 = 生成时的初始立场（保持多样性，§24）
        self.ideology_anchor = (self.ideology.x, self.ideology.y, self.ideology.z)

    # -- computed helpers -------------------------------------------------
    def wealth(self) -> float:
        return self.resources.values.get("money", 0.0) + self.resources.values.get("property", 0.0)

    def is_survival(self) -> bool:
        return self.resources.is_starving() or self.resources.is_broke()

    def remember(self, text: str, max_len: int = 30) -> None:
        self.memory.append(text)
        if len(self.memory) > max_len:
            self.memory = self.memory[-max_len:]

    def snapshot(self) -> dict:
        """Full public snapshot for the API / inspector."""
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
            "forces": self.last_forces,  # v0.3: 力分解（可解释性 §5, §37）
        }

    def brief(self) -> dict:
        """Lightweight snapshot for the 3D scatter / lists."""
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
            # v0.2: 政治速度向量，用于 3D 视图的移动方向可视化 (§28, §29)
            "vx": round(self.political_velocity[0], 5),
            "vy": round(self.political_velocity[1], 5),
            "vz": round(self.political_velocity[2], 5),
            "inertia": round(self.political_inertia, 3),
        }
