"""Identity — Agent 的社会身份（v0.4 §14–§24, §51–§53）。

Identity 绝不等于 ideology（§14, §19）：ideology 是政治位置（x/y/z），Identity 是
社会身份（属于谁、归属感、自主性、忠诚度）。Identity 只改变「响应倾向」，不直接
设置政治坐标；政治状态仍由 v0.3.1 dynamics engine 更新。

Identity 来源（§16）：personality、relationships、group membership、shared events、
social status、resource position、experience、memory —— 而非 origin_label / ideology。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Identity:
    primary_group: Optional[str] = None            # 主要身份（§17）：冲突时优先支持
    group_memberships: list = field(default_factory=list)   # 所属 group id 列表（§51 多身份）
    roles: list = field(default_factory=list)      # worker / community_member / friend ...
    belonging: float = 0.5                          # 归属感 [0,1]（Z 轴上游变量 §15）
    autonomy: float = 0.5                           # 自主性 [0,1]（Z 轴上游变量 §15）
    status: float = 0.5                             # 社会地位 [0,1]
    group_loyalty: float = 0.0                      # 群体忠诚 [0,1]（§52）
    social_identity_strength: float = 0.0           # 身份强度 [0,1]（§18）

    def membership_count(self) -> int:
        return len(self.group_memberships)

    def in_group(self, gid: str) -> bool:
        return gid in self.group_memberships

    def add_group(self, gid: str) -> None:
        if gid not in self.group_memberships:
            self.group_memberships.append(gid)
        if self.primary_group is None:
            self.primary_group = gid

    def remove_group(self, gid: str) -> None:
        if gid in self.group_memberships:
            self.group_memberships.remove(gid)
        if self.primary_group == gid:
            self.primary_group = self.group_memberships[0] if self.group_memberships else None

    def as_dict(self) -> dict:
        return {
            "primary_group": self.primary_group,
            "group_memberships": list(self.group_memberships),
            "roles": list(self.roles),
            "belonging": round(self.belonging, 4),
            "autonomy": round(self.autonomy, 4),
            "status": round(self.status, 4),
            "group_loyalty": round(self.group_loyalty, 4),
            "social_identity_strength": round(self.social_identity_strength, 4),
        }
