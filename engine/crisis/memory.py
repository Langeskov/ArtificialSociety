"""Crisis & Protest Memory (v0.4.2 §22–§23).

社会不会立即忘记危机发生过。危机结束后，记忆以指数衰减影响后续行为：
  - recent_protest_memory: 影响抗议阈值、政府信任、群体凝聚力
  - food_crisis_memory: 影响囤积倾向、预防性储蓄、信任变化

衰减公式：memory(t+1) = memory(t) × decay_rate
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CrisisMemory:
    """社会级危机记忆。"""
    # 抗议记忆（§22）
    protest_memory: float = 0.0
    protest_decay: float = 0.995  # per tick，约 5 天半衰期

    # 粮食危机记忆（§23）
    food_crisis_memory: float = 0.0
    food_crisis_decay: float = 0.998  # per tick，约 12 天半衰期

    # 经济危机记忆
    economic_crisis_memory: float = 0.0
    economic_crisis_decay: float = 0.997

    def record_protest(self, severity: float = 0.5) -> None:
        """记录一次抗议事件。"""
        self.protest_memory = min(1.0, self.protest_memory + severity * 0.3)

    def record_food_crisis(self, severity: float = 0.5) -> None:
        """记录一次粮食危机。"""
        self.food_crisis_memory = min(1.0, self.food_crisis_memory + severity * 0.2)

    def record_economic_crisis(self, severity: float = 0.5) -> None:
        """记录一次经济危机。"""
        self.economic_crisis_memory = min(1.0, self.economic_crisis_memory + severity * 0.2)

    def decay(self) -> None:
        """每 tick 衰减所有记忆。"""
        self.protest_memory *= self.protest_decay
        self.food_crisis_memory *= self.food_crisis_decay
        self.economic_crisis_memory *= self.economic_crisis_decay

        # 清理极小值
        if self.protest_memory < 0.001:
            self.protest_memory = 0.0
        if self.food_crisis_memory < 0.001:
            self.food_crisis_memory = 0.0
        if self.economic_crisis_memory < 0.001:
            self.economic_crisis_memory = 0.0

    @property
    def overall_tension(self) -> float:
        """综合紧张度（0-1）。"""
        return min(1.0, self.protest_memory * 0.4
                   + self.food_crisis_memory * 0.35
                   + self.economic_crisis_memory * 0.25)

    def snapshot(self) -> dict:
        return {
            "protest_memory": round(self.protest_memory, 4),
            "food_crisis_memory": round(self.food_crisis_memory, 4),
            "economic_crisis_memory": round(self.economic_crisis_memory, 4),
            "overall_tension": round(self.overall_tension, 4),
        }
