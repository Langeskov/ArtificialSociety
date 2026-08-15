"""Information — 与 Event 分离的信息对象（v0.4 §26–§33）。

关键架构变化（§26）：Event 与 Information 彻底分离。
    Event:      Food shortage = 100 units        （客观事实）
    Information: "Food shortage is severe"        （Agent 接收到的信息）
    Belief:     government_caused_food_shortage=0.72  （Agent 的主观信念）

三者不是同一个对象。Information 有可靠性（reliability）、失真（distortion）、
来源（source），支持 fact / rumor / opinion / propaganda / personal_report。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Information:
    id: str
    source: str                                   # agent id | "system" | group id
    event_id: Optional[str]
    created_tick: int
    content_type: str = "fact"                    # fact | rumor | opinion | propaganda | personal_report
    salience: float = 0.5
    reliability: float = 0.5                      # [0,1]（§29）
    distortion: float = 0.0                       # 累计失真（§32）
    recipients: list = field(default_factory=list)  # 已接收的 agent id（§27）
    subject: str = ""                             # 信念主题（§28）
    claim: float = 0.0                            # 主张值 [-1,1]，如「政府导致短缺」强度
    propagation_chain: list = field(default_factory=list)  # 传播路径（§60）
    reach: int = 0                                # 累计触达人数

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "event_id": self.event_id,
            "created_tick": self.created_tick,
            "content_type": self.content_type,
            "salience": round(self.salience, 3),
            "reliability": round(self.reliability, 3),
            "distortion": round(self.distortion, 4),
            "subject": self.subject,
            "claim": round(self.claim, 3),
            "reach": self.reach,
            "recipients_count": len(self.recipients),
        }
