"""Regional Resource Economy（v0.4.3 §3）。

v0.4.1: 基础区域模型（禀赋/价格/冲击）。
v0.4.3: 区域专业化——不同 region 有不同的生产优势，天然产生贸易依赖。

Region A: Food +++  (农业区)
Region B: Energy ++ (工业/矿业区)
Region C: Services ++ (商业/服务中心)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..agent.agent import Agent


@dataclass
class Region:
    id: str
    food_supply: float = 100.0
    energy_supply: float = 100.0
    jobs: float = 0.5
    market_activity: float = 0.5
    storage: dict = field(default_factory=dict)
    population: int = 0
    food_price: float = 1.0
    energy_price: float = 1.0
    _food_shock: float = 1.0
    _energy_shock: float = 1.0

    # v0.4.3 §3: 区域生产优势（由 endowment 驱动）
    food_production_bonus: float = 1.0    # 食物生产乘数
    energy_production_bonus: float = 1.0  # 能源生产乘数
    trade_activity: float = 0.5           # 贸易活跃度

    def apply_shock(self, resource: str, factor: float) -> None:
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
            "food_production_bonus": round(self.food_production_bonus, 3),
            "energy_production_bonus": round(self.energy_production_bonus, 3),
            "trade_activity": round(self.trade_activity, 3),
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
    """每 tick 更新各 region 的统计、价格与生产优势（§31, v0.4.3 §3）。"""
    regions = getattr(society, "regions", None)
    if regions is None:
        return
    econ = cfg.get("economy", {})
    food_critical = econ.get("food_critical", 20.0)
    endowments = cfg.get("regions", {}).get("endowments", {})

    # 按 location 聚合
    agg: dict[str, list[float]] = {rid: [] for rid in regions.regions}
    energy_agg: dict[str, list[float]] = {rid: [] for rid in regions.regions}
    money_agg: dict[str, list[float]] = {rid: [] for rid in regions.regions}
    for a in society.agents:
        if a.alive:
            loc = getattr(a, "location", "A")
            agg.setdefault(loc, []).append(a.resources.available("food"))
            energy_agg.setdefault(loc, []).append(a.resources.available("energy"))
            money_agg.setdefault(loc, []).append(a.resources.available("money"))

    for rid, region in regions.regions.items():
        foods = agg.get(rid, [])
        energies = energy_agg.get(rid, [])
        moneys = money_agg.get(rid, [])
        region.population = len(foods)

        mean_food = sum(foods) / len(foods) if foods else food_critical
        mean_energy = sum(energies) / len(energies) if energies else 30.0
        mean_money = sum(moneys) / len(moneys) if moneys else 100.0

        # 供给 = 区域资源均值 × 冲击因子
        region.food_supply = mean_food * region._food_shock
        region.energy_supply = mean_energy * region._energy_shock

        # 价格 = base × scarcity（§20）
        scarcity_food = food_critical / max(mean_food, 1.0)
        region.food_price = max(0.5, min(3.0, scarcity_food))
        scarcity_energy = 10.0 / max(mean_energy, 1.0)
        region.energy_price = max(0.5, min(3.0, scarcity_energy))

        # v0.4.3 §3: 区域生产优势（由 endowment 驱动）
        endow = endowments.get(rid, {})
        region.food_production_bonus = 0.5 + 0.5 * endow.get("food", 1.0)
        region.energy_production_bonus = 0.5 + 0.5 * endow.get("energy", 1.0)
        region.jobs = endow.get("jobs", 0.5)
        region.market_activity = min(1.0, mean_money / 300.0)
        region.trade_activity = region.market_activity * 0.8 + 0.2


def apply_regional_shock(society, region_id: str, resource: str, factor: float) -> None:
    regions = getattr(society, "regions", None)
    if regions is None:
        return
    r = regions.get(region_id)
    if r is not None:
        r.apply_shock(resource, factor)
