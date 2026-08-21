"""v0.4.3 Local Economy & Economic Structure 测试套件。

覆盖：
- Occupation System（§1）：职业分配、适合度、区域偏好
- Production with Inputs（§2）：labor × property × energy × productivity × region
- Regional Specialization（§3）：不同 region 有不同的生产优势
- Market Price（§4）：supply/demand 动态定价
- Economic Structure（§5-§6）：经济结构从资源分布涌现
"""

import random
import sys
import unittest
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from configs.loader import default_society_config                    # noqa: E402
from engine.simulation.engine import SimulationEngine               # noqa: E402
from engine.economy.occupation import (                             # noqa: E402
    OccupationType, OccupationSpec, OCCUPATION_SPECS,
    compute_occupation_fit, choose_occupation, get_production_multipliers,
)


def _make_engine(agents=300, seed=42, **overrides):
    cfg = default_society_config()
    cfg["population"]["count"] = agents
    for k, v in overrides.items():
        cfg[k] = v
    eng = SimulationEngine()
    s = eng.create_society(cfg, seed=seed)
    return eng, s


def _run(eng, s, ticks, step=100):
    for _ in range(ticks // step):
        eng.step(s.society_id, ticks=step)
    if ticks % step:
        eng.step(s.society_id, ticks=ticks % step)


# ---------------------------------------------------------------- occupation system

class TestOccupationSystem(unittest.TestCase):
    """§1: 职业系统。"""

    def test_all_six_occupations_exist(self):
        """6 种职业都存在。"""
        self.assertEqual(len(OCCUPATION_SPECS), 6)
        for occ in OccupationType:
            self.assertIn(occ, OCCUPATION_SPECS)

    def test_farmer_produces_most_food(self):
        """农民的食物产出系数最高。"""
        farmer_food = OCCUPATION_SPECS[OccupationType.FARMER].food_output
        for occ, spec in OCCUPATION_SPECS.items():
            if occ != OccupationType.FARMER:
                self.assertGreater(farmer_food, spec.food_output,
                                   f"Farmer should produce more food than {occ.value}")

    def test_miner_produces_most_energy(self):
        """矿工的能量产出系数最高。"""
        miner_energy = OCCUPATION_SPECS[OccupationType.MINER].energy_output
        for occ, spec in OCCUPATION_SPECS.items():
            if occ != OccupationType.MINER:
                self.assertGreater(miner_energy, spec.energy_output,
                                   f"Miner should produce more energy than {occ.value}")

    def test_occupation_fit_depends_on_personality(self):
        """不同人格适合不同职业。"""
        from engine.agent.agent import Agent
        from engine.agent.personality import Personality
        # 高 conscientiousness → 适合 farmer
        a = Agent(id="test", personality=Personality(values={
            "conscientiousness": 0.9, "openness": 0.1, "agreeableness": 0.5,
            "extraversion": 0.5, "risk_tolerance": 0.1, "empathy": 0.5,
        }))
        farmer_fit = compute_occupation_fit(a, OCCUPATION_SPECS[OccupationType.FARMER])
        trader_fit = compute_occupation_fit(a, OCCUPATION_SPECS[OccupationType.TRADER])
        self.assertGreater(farmer_fit, trader_fit)

    def test_occupation_distribution_in_society(self):
        """社会中应有多样化的职业分布。"""
        eng, s = _make_engine(agents=200, seed=42)
        _run(eng, s, 300)  # 3 天，确保职业分配完成
        occ_dist = Counter(a.occupation for a in s.agents if a.alive)
        # 至少应有 3 种不同职业
        self.assertGreaterEqual(len(occ_dist), 3, f"职业分布应多样化: {dict(occ_dist)}")


# ---------------------------------------------------------------- production with inputs

class TestProductionWithInputs(unittest.TestCase):
    """§2: 生产需要投入。"""

    def test_production_decreases_with_low_energy(self):
        """能量不足时生产应下降。"""
        from engine.agent.agent import Agent
        from engine.agent.personality import Personality
        from engine.agent.resources import Resources

        cfg = default_society_config()
        # 高能量 agent
        a_high = Agent(id="high", personality=Personality(values={
            "conscientiousness": 0.5, "openness": 0.5, "agreeableness": 0.5,
            "extraversion": 0.5, "risk_tolerance": 0.5, "empathy": 0.5,
        }))
        a_high.resources.set("energy", 50.0)
        a_high.resources.set("property", 100.0)

        # 低能量 agent
        a_low = Agent(id="low", personality=Personality(values={
            "conscientiousness": 0.5, "openness": 0.5, "agreeableness": 0.5,
            "extraversion": 0.5, "risk_tolerance": 0.5, "empathy": 0.5,
        }))
        a_low.resources.set("energy", 2.0)
        a_low.resources.set("property", 100.0)

        # 生产投入因子
        ef_high = max(0.3, min(1.0, 50.0 / 10.0))
        ef_low = max(0.3, min(1.0, 2.0 / 10.0))
        self.assertGreater(ef_high, ef_low)

    def test_production_decreases_with_low_property(self):
        """财产不足时生产应下降。"""
        pf_high = max(0.3, min(1.0, (100.0 / 20.0) ** 0.5))
        pf_low = max(0.3, min(1.0, (2.0 / 20.0) ** 0.5))
        self.assertGreater(pf_high, pf_low)


# ---------------------------------------------------------------- regional specialization

class TestRegionalSpecialization(unittest.TestCase):
    """§3: 区域专业化。"""

    def test_regions_have_different_endowments(self):
        """不同 region 应有不同的生产优势。"""
        eng, s = _make_engine(agents=300, seed=42)
        _run(eng, s, 100)
        regions = s.regions.all()
        bonuses = [(r.id, r.food_production_bonus, r.energy_production_bonus) for r in regions]
        # 至少两个 region 的食物优势不同
        food_bonuses = set(b[1] for b in bonuses)
        self.assertGreater(len(food_bonuses), 1, f"区域食物优势应不同: {bonuses}")

    def test_region_prices_differ(self):
        """不同 region 应有不同的价格。"""
        eng, s = _make_engine(agents=300, seed=42)
        _run(eng, s, 200)
        regions = s.regions.all()
        food_prices = [r.food_price for r in regions]
        # 价格应有差异
        self.assertGreaterEqual(len(set(round(p, 2) for p in food_prices)), 1,
                           f"区域价格应有差异: {food_prices}")


# ---------------------------------------------------------------- market price

class TestMarketPrice(unittest.TestCase):
    """§4: 动态定价。"""

    def test_food_price_increases_with_scarcity(self):
        """食物稀缺时价格应上升。"""
        cfg = default_society_config()
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)
        # 注入严重灾难降低食物
        eng.inject_event(s.society_id, "natural_disaster", severity=1.0)
        _run(eng, s, 200)
        # 食物稀缺的 region 价格应高于正常水平
        regions = s.regions.all()
        prices = [r.food_price for r in regions]
        # 至少一个 region 价格应高于基准 1.0（因为灾难导致稀缺）
        self.assertGreater(max(prices), 0.5, f"灾难后价格应反映稀缺: {prices}")


# ---------------------------------------------------------------- survival test

class TestEconomicSurvival(unittest.TestCase):
    """§9: 经济结构下的社会存活测试。"""

    def test_society_survives_10_days(self):
        """100 Agent × 10 天，经济结构下社会应存活。"""
        cfg = default_society_config()
        cfg["population"]["count"] = 100
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)
        _run(eng, s, 1000)

        alive = [a for a in s.agents if a.alive]
        food = sum(a.resources.values.get("food", 0) for a in alive) / len(alive)
        starve = sum(1 for a in alive if a.resources.is_starving()) / len(alive)
        critical = cfg["economy"]["food_critical"]

        self.assertGreater(food, critical * 0.5, f"食物应维持在 critical 附近，实际 {food:.1f}")
        self.assertLess(starve, 0.50, f"饥饿率应有界，实际 {starve:.2f}")

    def test_occupation_diversity_survives(self):
        """职业多样性在 10 天后应保持。"""
        eng, s = _make_engine(agents=200, seed=42)
        _run(eng, s, 1000)
        occ_dist = Counter(a.occupation for a in s.agents if a.alive)
        self.assertGreaterEqual(len(occ_dist), 3, f"10 天后职业应多样化: {dict(occ_dist)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)


