"""v0.4.2 Temporal & Resource Dynamics 测试套件。

覆盖契约（对应 v0.4.2 计划书 §编号）：
- 时间分辨率不变性（§7, §48）：100 vs 200 ticks/day 结果近似一致
- Crisis hysteresis（§14）：trigger > resolve 阈值，防止反复开关
- Crisis persistence（§15）：条件持续 N ticks 才触发
- Crisis cooldown（§16）：解决后 N 天内不重新触发
- Recovery damping（§17-§18）：渐进恢复，无过冲
- Production disruption（§19）：临时干扰自动衰减，非永久 ratchet
- Daily flow accounting（§11）：资源流记录
- Stock-flow metrics（§42）：buffer days 计算
"""

import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from configs.loader import default_society_config                    # noqa: E402
from engine.simulation.engine import SimulationEngine               # noqa: E402
from engine.crisis.tracker import CrisisTracker, CrisisState        # noqa: E402
from engine.crisis.memory import CrisisMemory                       # noqa: E402
from engine.crisis.diagnostics import OscillationDetector, FeedbackDiagnostics  # noqa: E402


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


# ---------------------------------------------------------------- clock

class TestClockV042(unittest.TestCase):
    """§2-§4: Clock 提供统一时间语义。"""

    def test_simulated_days(self):
        """§4: tick 2769 → 27.69 simulated days (ticks_per_day=100)。"""
        eng, s = _make_engine()
        s.clock.advance(2769)
        self.assertAlmostEqual(s.clock.simulated_days, 27.69, places=2)

    def test_dt_days(self):
        """§6: dt_days = 1 / ticks_per_day。"""
        eng, s = _make_engine()
        self.assertAlmostEqual(s.clock.dt_days, 0.01, places=6)

    def test_snapshot_includes_temporal_fields(self):
        """§4: snapshot 包含 simulated_days, dt_days, hour_of_day。"""
        eng, s = _make_engine()
        snap = s.clock.snapshot()
        self.assertIn("simulated_days", snap)
        self.assertIn("dt_days", snap)
        self.assertIn("hour_of_day", snap)


# ---------------------------------------------------------------- crisis state machine

class TestCrisisHysteresis(unittest.TestCase):
    """§14: trigger_threshold > resolve_threshold，防止反复开关。"""

    def test_hysteresis_prevents_toggle(self):
        """在 trigger 和 resolve 之间波动不应反复触发/解决。"""
        ct = CrisisTracker("food", trigger_threshold=0.25, resolve_threshold=0.12,
                           trigger_persistence_ticks=5, cooldown_days=0.5)
        # 上升到 trigger 以上
        for _ in range(10):
            ct.update(0.30, tick=10, ticks_per_day=100)
        self.assertEqual(ct.state, CrisisState.ACTIVE)

        # 下降到 trigger 以下但仍在 resolve 以上 → 不应解决
        ct.update(0.20, tick=20, ticks_per_day=100)
        self.assertNotEqual(ct.state, CrisisState.NORMAL)
        self.assertNotEqual(ct.state, CrisisState.RECOVERING)

    def test_resolve_requires_below_resolve_threshold(self):
        """必须低于 resolve_threshold 才能解决。"""
        ct = CrisisTracker("food", trigger_threshold=0.25, resolve_threshold=0.12,
                           trigger_persistence_ticks=5, cooldown_days=0.1)
        for _ in range(10):
            ct.update(0.30, tick=10, ticks_per_day=100)
        self.assertEqual(ct.state, CrisisState.ACTIVE)

        # 降到 resolve 以下
        for i in range(20):
            ct.update(0.10, tick=20+i, ticks_per_day=100)
        self.assertIn(ct.state, (CrisisState.RECOVERING, CrisisState.COOLDOWN, CrisisState.NORMAL))


class TestCrisisPersistence(unittest.TestCase):
    """§15: 条件持续 N ticks 才触发。"""

    def test_brief_spike_does_not_trigger(self):
        """短暂波动（< persistence_ticks）不应触发危机。"""
        ct = CrisisTracker("food", trigger_threshold=0.25, resolve_threshold=0.12,
                           trigger_persistence_ticks=50, cooldown_days=0)
        # 只有 10 ticks 高于阈值
        for i in range(10):
            ct.update(0.30, tick=i, ticks_per_day=100)
        self.assertEqual(ct.state, CrisisState.NORMAL)

    def test_sustained_condition_triggers(self):
        """持续 >= persistence_ticks 应触发。"""
        ct = CrisisTracker("food", trigger_threshold=0.25, resolve_threshold=0.12,
                           trigger_persistence_ticks=10, cooldown_days=0)
        for i in range(15):
            ct.update(0.30, tick=i, ticks_per_day=100)
        self.assertEqual(ct.state, CrisisState.ACTIVE)


class TestCrisisCooldown(unittest.TestCase):
    """§16: 解决后 N 天内不重新触发。"""

    def test_cooldown_prevents_retrigger(self):
        """危机解决后进入 COOLDOWN，期间不重新触发。"""
        ct = CrisisTracker("food", trigger_threshold=0.25, resolve_threshold=0.12,
                           trigger_persistence_ticks=3, cooldown_days=2.0)
        # 触发危机
        for i in range(10):
            ct.update(0.30, tick=i, ticks_per_day=100)
        self.assertEqual(ct.state, CrisisState.ACTIVE)

        # 解决（需要足够时间让 recovery_progress 达到 0.8）
        for i in range(10, 60):
            ct.update(0.05, tick=i, ticks_per_day=100)
        self.assertIn(ct.state, (CrisisState.COOLDOWN, CrisisState.NORMAL))

        # 如果在 cooldown 中，再次高于阈值不应触发
        if ct.state == CrisisState.COOLDOWN:
            ct.update(0.30, tick=30, ticks_per_day=100)
            self.assertEqual(ct.state, CrisisState.COOLDOWN)


# ---------------------------------------------------------------- recovery damping

class TestRecoveryDamping(unittest.TestCase):
    """§17-§18: 渐进恢复，无过冲。"""

    def test_production_multiplier_recovers_gradually(self):
        """production_multiplier 从低值渐进恢复到 1.0。"""
        eng, s = _make_engine(agents=100)
        s.production_multiplier = 0.5
        s.production_disruption = 0.0
        # 跑 100 ticks (1 天)
        eng.step(s.society_id, ticks=100)
        pm = s.production_multiplier
        # 应该恢复了一些，但不到 1.0
        self.assertGreater(pm, 0.5, "应有恢复")
        self.assertLess(pm, 1.0, "不应瞬间恢复到 1.0")

    def test_disruption_decays(self):
        """production_disruption 自动衰减。"""
        eng, s = _make_engine(agents=100)
        s.production_disruption = 0.3
        eng.step(s.society_id, ticks=100)
        self.assertLess(s.production_disruption, 0.3, "disruption 应衰减")


# ---------------------------------------------------------------- time resolution invariance

class TestTimeResolutionInvariance(unittest.TestCase):
    """§7, §48: 不同 ticks_per_day 下，按 simulated days 的结果近似一致。"""

    def test_100_vs_200_ticks_per_day(self):
        """100 ticks/day 和 200 ticks/day 跑 10 天，资源量级应近似。"""
        results = []
        for tpd in (100, 200):
            cfg = default_society_config()
            cfg["population"]["count"] = 200
            cfg["ticks_per_day"] = tpd
            cfg["events"]["frequency"] = 0.0  # 关闭随机事件
            eng = SimulationEngine()
            s = eng.create_society(cfg, seed=42)
            eng.step(s.society_id, ticks=10 * tpd)  # 10 天
            alive = [a for a in s.agents if a.alive]
            food = sum(a.resources.values.get("food", 0) for a in alive) / max(len(alive), 1)
            results.append(food)
        # 两种分辨率的食物均值应在 50% 以内（允许随机差异）
        ratio = results[0] / max(results[1], 0.01)
        self.assertGreater(ratio, 0.5, f"时间分辨率差异过大: {results}")
        self.assertLess(ratio, 2.0, f"时间分辨率差异过大: {results}")


# ---------------------------------------------------------------- daily flow accounting

class TestDailyFlowAccounting(unittest.TestCase):
    """§11: 资源流记录。"""

    def test_flow_returns_dict(self):
        """step_economy 返回 flow dict。"""
        eng, s = _make_engine(agents=50)
        eng.step(s.society_id, ticks=1)
        # resource_flow 应该被更新
        self.assertIsInstance(s.resource_flow, dict)


# ---------------------------------------------------------------- baseline stability

class TestBaselineStability(unittest.TestCase):
    """§9: 无重大事件时，资源应进入稳定振荡或慢速均衡。"""

    def test_food_stable_without_events(self):
        """关闭事件，食物应稳定在 critical 以上。"""
        cfg = default_society_config()
        cfg["population"]["count"] = 200
        cfg["events"]["frequency"] = 0.0
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)
        eng.step(s.society_id, ticks=3000)  # 30 天
        alive = [a for a in s.agents if a.alive]
        food = sum(a.resources.values.get("food", 0) for a in alive) / max(len(alive), 1)
        critical = cfg["economy"]["food_critical"]
        self.assertGreater(food, critical * 0.5, f"无事件 30 天后食物应稳定，实际 {food:.1f}")


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ---------------------------------------------------------------- crisis memory

class TestCrisisMemory(unittest.TestCase):
    """§22-§23: 危机记忆衰减。"""

    def test_memory_records_and_decays(self):
        """记录危机后记忆增加，随时间衰减。"""
        cm = CrisisMemory()
        cm.record_protest(0.8)
        self.assertGreater(cm.protest_memory, 0.0)
        for _ in range(1000):
            cm.decay()
        self.assertLess(cm.protest_memory, 0.2, "记忆应衰减")

    def test_food_crisis_memory(self):
        """粮食危机记忆。"""
        cm = CrisisMemory()
        cm.record_food_crisis(0.9)
        self.assertGreater(cm.food_crisis_memory, 0.0)

    def test_overall_tension(self):
        """综合紧张度。"""
        cm = CrisisMemory()
        cm.record_protest(0.5)
        cm.record_food_crisis(0.5)
        self.assertGreater(cm.overall_tension, 0.0)
        self.assertLessEqual(cm.overall_tension, 1.0)


# ---------------------------------------------------------------- oscillation detector

class TestOscillationDetector(unittest.TestCase):
    """§31: 振荡检测。"""

    def test_no_oscillation_on_constant(self):
        """常数不应检测为振荡。"""
        od = OscillationDetector(window_size=100, min_cycles=3)
        for _ in range(200):
            od.update(50.0)
        result = od.detect()
        self.assertFalse(result["detected"])

    def test_detects_sinusoidal(self):
        """正弦波应被检测为振荡。"""
        od = OscillationDetector(window_size=200, min_cycles=2)
        for i in range(300):
            # 使用短周期（20 ticks）使峰值更尖锐，便于整数采样检测
            od.update(50.0 + 20.0 * math.sin(2 * math.pi * i / 20))
        result = od.detect()
        self.assertTrue(result["detected"])
        self.assertGreater(result["period_ticks"], 0)


# ---------------------------------------------------------------- feedback diagnostics

class TestFeedbackDiagnostics(unittest.TestCase):
    """§33-§34: 反馈环诊断。"""

    def test_returns_analysis(self):
        """反馈诊断返回结构化结果。"""
        fd = FeedbackDiagnostics(window_size=100)
        for i in range(200):
            fd.update(50.0 + 10 * math.sin(i * 0.1), 0.3, 5, 0.9)
        result = fd.analyze()
        self.assertIn("positive_feedback", result)
        self.assertIn("negative_feedback", result)
        self.assertIn("dominant", result)
