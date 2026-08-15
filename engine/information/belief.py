"""Belief — Agent 的主观信念（v0.4 §28, §34, §35）。

每个信念针对一个「主题」（subject），例如 government_caused_food_shortage。
belief_strength 是 [-1,1] 的信念强度（正 = 相信，负 = 拒绝），confidence 是
[0,1] 的置信度。同一信息对不同 Agent 产生不同信念（§34），受 source_trust、
group_identity、confirmation_bias、open_mindedness 影响（§35）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Belief:
    subject: str
    belief_strength: float = 0.0      # [-1,1]
    confidence: float = 0.0           # [0,1]
    source_trust: float = 0.5         # 最近来源的可信度
    last_updated: int = 0

    def as_dict(self) -> dict:
        return {
            "subject": self.subject,
            "belief_strength": round(self.belief_strength, 4),
            "confidence": round(self.confidence, 4),
            "source_trust": round(self.source_trust, 3),
            "last_updated": self.last_updated,
        }


def update_belief(
    belief: Belief,
    claim: float,
    reliability: float,
    source_trust: float,
    openness: float,
    tick: int,
    learning_rate: float = 0.4,
) -> Belief:
    """更新信念（§34, §35）：向 claim 靠拢，速率受来源信任、可靠度、confirmation bias 调制。

    同一信息不会让所有人得到相同信念 —— openness 高者更愿接受与己见相反的信息。
    """
    # confirmation bias：与既有信念方向一致 → 更易接受；相反 → 更易怀疑
    if belief.belief_strength == 0.0:
        alignment = 1.0
    else:
        alignment = 1.0 if (claim * belief.belief_strength) >= 0 else 0.4
    # openness 削弱 confirmation bias（高开放 → 更接近中性接受）
    bias = alignment * (1.0 - 0.6 * openness) + 0.6 * openness

    acceptance = reliability * source_trust * bias
    new_strength = belief.belief_strength + (claim - belief.belief_strength) * learning_rate * acceptance
    new_strength = max(-1.0, min(1.0, new_strength))

    new_confidence = belief.confidence * 0.8 + reliability * source_trust * 0.2
    new_confidence = max(0.0, min(1.0, new_confidence))

    belief.belief_strength = new_strength
    belief.confidence = new_confidence
    belief.source_trust = source_trust
    belief.last_updated = tick
    return belief
