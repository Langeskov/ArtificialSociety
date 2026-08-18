"""Group — 社会中间层（v0.4 §4, §13）。

Group 是「一群具有稳定社会互动和共同身份的 Agent」，由行为涌现产生，而非
配置直接生成（§5, §80）。Group 不等于政治党派，也不等于 political cluster
（§13, §57）：政治位置（x/y/z）与成员身份是独立变量。

生命周期（§4, §12）：
    FORMING → ACTIVE → FRAGMENTING → DISSOLVED
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class GROUP_STATE:
    FORMING = "forming"
    ACTIVE = "active"
    FRAGMENTING = "fragmenting"
    DISSOLVED = "dissolved"


@dataclass
class Group:
    id: str
    created_tick: int
    state: str = GROUP_STATE.FORMING
    members: set = field(default_factory=set)          # agent ids
    center_x: float = 0.0
    center_y: float = 0.0
    center_z: float = 0.0
    cohesion: float = 0.5
    trust: float = 0.5
    influence: float = 0.1
    shared_identity: float = 0.0
    resources: dict = field(default_factory=dict)       # 共享资源池（§49）
    age: int = 0
    recent_events: list = field(default_factory=list)
    # v0.4 扩展
    type: str = "emergent"                              # §13：第一版不分类
    region: str = ""                                    # 主导区域（§48，可跨区域）
    variance_x: float = 0.0                             # §22：内部多样性
    variance_y: float = 0.0
    variance_z: float = 0.0
    formation_ticks: int = 0                            # 连续满足条件时长（§8）
    low_cohesion_ticks: int = 0                         # 低凝聚力持续时长（§12）

    def size(self) -> int:
        return len(self.members)

    def is_alive(self) -> bool:
        return self.state in (GROUP_STATE.FORMING, GROUP_STATE.ACTIVE, GROUP_STATE.FRAGMENTING)

    def political_distance_to(self, other: "Group") -> float:
        dx = self.center_x - other.center_x
        dy = self.center_y - other.center_y
        dz = self.center_z - other.center_z
        return (dx * dx + dy * dy + dz * dz) ** 0.5

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "created_tick": self.created_tick,
            "state": self.state,
            "size": self.size(),
            "center_x": round(self.center_x, 4),
            "center_y": round(self.center_y, 4),
            "center_z": round(self.center_z, 4),
            "cohesion": round(self.cohesion, 4),
            "trust": round(self.trust, 4),
            "influence": round(self.influence, 4),
            "shared_identity": round(self.shared_identity, 4),
            "resources": dict(self.resources),
            "age": self.age,
            "type": self.type,
            "region": self.region,
            "variance_x": round(self.variance_x, 4),
            "variance_y": round(self.variance_y, 4),
            "variance_z": round(self.variance_z, 4),
        }


class GroupRegistry:
    """一个 Society 的所有 Group 的注册表（§70：groups / group_members / group_history）。"""

    def __init__(self) -> None:
        self.groups: dict[str, Group] = {}
        self.history: list[dict] = []      # 生命周期事件：GROUP_FORMED / MERGED / SPLIT / DISSOLVED
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"group_{self._counter:05d}"

    def add(self, g: Group) -> Group:
        self.groups[g.id] = g
        return g

    def get(self, gid: str) -> Optional[Group]:
        return self.groups.get(gid)

    def active(self) -> list[Group]:
        return [g for g in self.groups.values() if g.is_alive()]

    def purge_dissolved(self) -> int:
        """从注册表移除已解散的 Group（history 保留记录）。

        v0.4.1：行为系统引入 leave_group/join_group 后群体处于动态 churn，
        死亡群体不清除会让 merge 的 O(A²) 配对成本随时间平方增长（实测
        800 tick 累积 2268 个注册群体 → 每 tick 数百万次配对计算）。
        """
        dead = [gid for gid, g in self.groups.items() if g.state == GROUP_STATE.DISSOLVED]
        for gid in dead:
            del self.groups[gid]
        return len(dead)

    def record(self, event_type: str, **kwargs) -> None:
        self.history.append({"type": event_type, **kwargs})

    def as_list(self) -> list[dict]:
        return [g.as_dict() for g in self.active()]
