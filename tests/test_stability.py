"""Stability test suite — v0.2 验收测试 (§33, §34, §35).

覆盖：确定性复现、正常社会无塌缩、温和/严重粮食危机、个体化事件响应、长跑不塌缩。
"""

import statistics
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.simulation.engine import SimulationEngine          # noqa: E402
from configs.loader import default_society_config                # noqa: E402


def make_engine(agents=500, seed=42):
    cfg = default_society_config()
    cfg["population"]["count"] = agents
    # v0.4: 本文件是 v0.3.1 稳定性测试，关闭 v0.4 特性以隔离 v0.3.1 动力学
    for key in ("behavior", "groups", "identity", "information"):
        cfg.setdefault(key, {})["enabled"] = False
    eng = SimulationEngine()
    s = eng.create_society(cfg, seed=seed)
    return eng, s


def run(eng, s, ticks, step=50):
    for _ in range(ticks // step):
        eng.step(s.society_id, ticks=step)
    if ticks % step:
        eng.step(s.society_id, ticks=ticks % step)


class TestDeterminism(unittest.TestCase):
    """§33: 相同 seed + 参数 → 可复现结果。"""

    def test_same_seed_reproduces(self):
        eng1, s1 = make_engine(agents=200, seed=12345)
        eng2, s2 = make_engine(agents=200, seed=12345)
        run(eng1, s1, 300)
        run(eng2, s2, 300)
        m1 = s1.metrics()
        m2 = s2.metrics()
        self.assertAlmostEqual(m1["social_temperature"], m2["social_temperature"], places=6)
        self.assertAlmostEqual(m1["average_wealth"], m2["average_wealth"], places=4)
        self.assertEqual(m1["population"], m2["population"])

    def test_different_seed_diverges(self):
        eng1, s1 = make_engine(agents=200, seed=1)
        eng2, s2 = make_engine(agents=200, seed=2)
        run(eng1, s1, 300)
        run(eng2, s2, 300)
        # 不同 seed 的意识形态分布不应完全一致
        xs1 = [a.ideology.x for a in s1.agents]
        xs2 = [a.ideology.x for a in s2.agents]
        self.assertNotEqual(round(statistics.mean(xs1), 3), round(statistics.mean(xs2), 3))


class TestNormalSociety(unittest.TestCase):
    """Test A: 正常社会无塌缩，资源 > 0，无永久抗议。"""

    def test_no_collapse_and_resources_positive(self):
        eng, s = make_engine(agents=400, seed=42)
        run(eng, s, 1000)  # 10 天
        m = s.metrics()
        # 政治多样性未塌缩（方差没有趋零）
        avg_var = (m["political_variance_x"] + m["political_variance_y"] + m["political_variance_z"]) / 3
        self.assertGreater(avg_var, 0.01, "政治方差塌缩，社会趋同")
        # 资源保持为正
        for a in s.agents:
            if a.alive:
                self.assertGreaterEqual(a.resources["food"], 0.0)
                self.assertGreaterEqual(a.resources["money"], 0.0)
        # 无永久抗议（所有 protest 事件最终解决）
        active_protests = [e for e in s.events.events if e.type == "protest" and e.is_active]
        self.assertEqual(len(active_protests), 0)


class TestFoodCrisis(unittest.TestCase):
    """Test B: 温和粮食危机 → 食物下降、温度上升、最终恢复。"""

    def test_mild_food_crisis_recovers(self):
        eng, s = make_engine(agents=400, seed=7)
        run(eng, s, 200)
        food_before = statistics.mean(a.resources["food"] for a in s.agents)
        temp_before = s.metrics()["social_temperature"]

        # 注入粮食危机（温和）
        eng.inject_event(s.society_id, "natural_disaster", severity=0.7)
        run(eng, s, 50)
        food_low = statistics.mean(a.resources["food"] for a in s.agents)
        # 危机应造成食物下降
        self.assertLess(food_low, food_before)

        # 危机峰值：温度上升（信息传播 + 极化 + 抗议需要时间发酵）
        run(eng, s, 150)
        temp_peak = s.metrics()["social_temperature"]
        self.assertGreater(temp_peak, temp_before)

        # 恢复：长时间后食物回升、温度从峰值回落
        run(eng, s, 300)
        food_after = statistics.mean(a.resources["food"] for a in s.agents)
        temp_after = s.metrics()["social_temperature"]
        self.assertGreater(food_after, food_low, "食物未恢复")
        self.assertLess(temp_after, temp_peak, "温度未从峰值回落")

        # 事件最终衰减解决
        self.assertFalse(any(e.type == "natural_disaster" and e.is_active for e in s.events.events))


class TestIndividualizedResponse(unittest.TestCase):
    """Test D: 同一事件对不同 Agent 产生不同响应（§9）。"""

    def test_same_event_different_responses(self):
        eng, s = make_engine(agents=400, seed=99)
        run(eng, s, 100)

        # 记录事件前的政治速度方向
        before_x = {a.id: a.ideology.x for a in s.agents}

        eng.inject_event(s.society_id, "food_shortage", severity=0.9)
        run(eng, s, 20)

        dxs = []
        for a in s.agents:
            if a.alive:
                dxs.append(a.ideology.x - before_x[a.id])
        # 应有 Agent 朝不同方向移动（x 位移既有正也有负）
        self.assertGreater(max(dxs), 0.0)
        self.assertLess(min(dxs), 0.0)
        # 位移存在明显个体差异
        self.assertGreater(statistics.pstdev(dxs), 1e-4)


class TestLongRun(unittest.TestCase):
    """Test E: 长跑不塌缩 — 意识形态不全部相等（§24, §35）。"""

    def test_long_run_no_uniform_collapse(self):
        eng, s = make_engine(agents=400, seed=2026)
        run(eng, s, 2000)  # 20 天
        m = s.metrics()
        # 所有 Agent 的坐标不能完全相等
        xs = [a.ideology.x for a in s.agents]
        ys = [a.ideology.y for a in s.agents]
        zs = [a.ideology.z for a in s.agents]
        self.assertGreater(statistics.pstdev(xs) + statistics.pstdev(ys) + statistics.pstdev(zs), 0.05)
        # 边界集中不能达到崩溃阈值（60%）
        self.assertLess(m["boundary_concentration"], 0.6)


class TestEventLifecycle(unittest.TestCase):
    """§10, §11: 事件拥有生命周期并能衰减解决。"""

    def test_events_resolve_over_time(self):
        eng, s = make_engine(agents=300, seed=5)
        eng.inject_event(s.society_id, "protest", severity=0.8)
        run(eng, s, 200)
        # 抗议应在持续时间结束后解决
        active = [e for e in s.events.events if e.type == "protest" and e.is_active]
        self.assertEqual(len(active), 0, "抗议事件未自行结束")


if __name__ == "__main__":
    unittest.main(verbosity=2)
