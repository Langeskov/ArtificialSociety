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
    ai_level: int = 0            # 0 rule, 1 statistical, 2 small model, 3 LLM, 4 high-intelligence
    alive: bool = True
    # v0.2 dynamics fields (§4, §5, §21)
    political_inertia: float = 0.95
    political_velocity: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    recent_events: list = field(default_factory=list)   # [{event_id, type, tick, strength}]
    known_events: dict = field(default_factory=dict)     # event_id -> tick the agent learned it
    ideology_anchor: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0))  # 个人政治锚点
    last_forces: dict = field(default_factory=dict)       # v0.3: 最近一次力分解（可解释性 §5）
    # v0.4 social layer (§14–§24, §47)
    identity: Identity = field(default_factory=Identity)  # 社会身份（≠ ideology §14）
    location: str = "A"                                    # region_id（§47）
    beliefs: dict = field(default_factory=dict)            # subject -> Belief（§28）
    # v0.4.1 resource layer (§6, §15, §25, §46)
    resource_state: dict = field(default_factory=dict)     # security/pressure/surplus/deficit/各资源压力
    employment_status: str = "self_employed"               # employed/unemployed/self_employed/dependent（§15）
    occupation: str = "worker"                             # worker/producer/trader/service/government（§15）
    productivity: float = 0.5                              # 生产效率（§14, §15）
    employer: Optional[str] = None                         # 雇主 id（§15）
    relative_deprivation: float = 0.0                      # 相对剥夺（§25, §26）
    current_action: str = ""                               # 本 tick 行为（Inspector §46）
    action_utility: float = 0.0
    action_feasibility: float = 0.0

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
            # v0.4: 社会身份（§59）
            "identity": self.identity.as_dict(),
            "location": self.location,
            "beliefs": {k: v.as_dict() for k, v in self.beliefs.items()},
            # v0.4.1: 资源层（§6, §7, §15, §25, §46）
            "resource_state": dict(self.resource_state),
            "reserved_resources": {k: round(v, 2) for k, v in self.resources.reserved.items()},
            "employment": {
                "status": self.employment_status,
                "occupation": self.occupation,
                "productivity": round(self.productivity, 4),
                "employer": self.employer,
            },
            "relative_deprivation": round(self.relative_deprivation, 4),
            "current_action": self.current_action,
            "action_utility": round(self.action_utility, 4),
            "action_feasibility": round(self.action_feasibility, 4),
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
            # v0.4: 群体归属（§58 group layer）
            "primary_group": self.identity.primary_group,
            "group_count": self.identity.membership_count(),
            "location": self.location,
            # v0.2: 政治速度向量，用于 3D 视图的移动方向可视化 (§28, §29)
            "vx": round(self.political_velocity[0], 5),
            "vy": round(self.political_velocity[1], 5),
            "vz": round(self.political_velocity[2], 5),
            "inertia": round(self.political_inertia, 3),
            # v0.4.1: 资源安全/压力（§45 动力学诊断着色）
            "resource_security": round(self.resource_state.get("security", 0.0), 3),
            "resource_pressure": round(self.resource_state.get("pressure", 0.0), 3),
        }
