"""Regional Resource Economy（v0.4.1 §31–§33）。

正式启用 v0.4 的 Agent.location / regions。每个 Region 拥有资源禀赋、就业、
市场活动、资源价格与存储（§39）。Region 级资源冲击（§32）只影响局部，
通过 trade/migration/information 传播到其它 region，而非瞬间全局。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..agent.agent import Agent


@dataclass
class Region:
    id: str
    food_supply: float = 100.0        # 食物供给（§31）
    energy_supply: float = 100.0      # 能量供给
    jobs: float = 0.5                 # 就业机会 [0,1]
    market_activity: float = 0.5      # 市场活跃度 [0,1]
    storage: dict = field(default_factory=dict)  # 存储缓冲（§39）
    population: int = 0
    food_price: float = 1.0           # 资源价格（§31, §20）
    energy_price: float = 1.0
    _food_shock: float = 1.0          # §32 冲击因子（1.0 = 无冲击）
    _energy_shock: float = 1.0

    def apply_shock(self, resource: str, factor: float) -> None:
        """§32：region 级资源冲击（factor < 1 表示减产）。"""
        if resource == "food":
            self._food_shock = factor
        elif resource == "energy":
            self._energy_shock = factor

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "food_supply": round(self.food_supply, 2),
            "energy_supply": round(self.energy_supply, 2),
            "jobs": round(self.jobs, 3),
            "market_activity": round(self.market_activity, 3),
            "storage": {k: round(v, 2) for k, v in self.storage.items()},
            "population": self.population,
            "food_price": round(self.food_price, 3),
            "energy_price": round(self.energy_price, 3),
        }


class RegionRegistry:
    def __init__(self, region_ids: list[str]) -> None:
        self.regions: dict[str, Region] = {rid: Region(id=rid) for rid in region_ids}

    def get(self, rid: str) -> Optional[Region]:
        return self.regions.get(rid)

    def all(self) -> list[Region]:
        return list(self.regions.values())

    def as_list(self) -> list[dict]:
        return [r.as_dict() for r in self.regions.values()]


def update_regions(society, cfg: dict) -> None:
    """每 tick 更新各 region 的统计与价格（§31）。"""
    regions = getattr(society, "regions", None)
    if regions is None:
        return
    econ = cfg.get("economy", {})
    food_critical = econ.get("food_critical", 20.0)

    # 按 location 聚合
    agg: dict[str, list[float]] = {rid: [] for rid in regions.regions}
    for a in society.agents:
        if a.alive:
            loc = getattr(a, "location", "A")
            agg.setdefault(loc, []).append(a.resources.available("food"))

    for rid, region in regions.regions.items():
        foods = agg.get(rid, [])
        region.population = len(foods)
        mean_food = sum(foods) / len(foods) if foods else food_critical
        # 供给 = 区域食物均值 × 冲击因子（§32）
        region.food_supply = mean_food * region._food_shock
        region.energy_supply = 100.0 * region._energy_shock
        # 价格 = base × scarcity（§20）：食物越少越贵
        scarcity = food_critical / max(mean_food, 1.0)
        region.food_price = max(0.5, min(3.0, scarcity))


def apply_regional_shock(society, region_id: str, resource: str, factor: float) -> None:
    """§32：对单个 region 施加资源冲击。"""
    regions = getattr(society, "regions", None)
    if regions is None:
        return
    r = regions.get(region_id)
    if r is not None:
        r.apply_shock(resource, factor)
