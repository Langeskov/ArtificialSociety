"""Social emergence tests — v0.4 §73, §74（社会涌现闭环）。

覆盖：行为产生事件、事件产生信息、信息改变行为、群体改变行为、
以及最重要的「无预设群体的社会能否自然涌现结构」。
"""

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.simulation.engine import SimulationEngine          # noqa: E402
from configs.loader import default_society_config                # noqa: E402
from engine.metrics.social_metrics import (                     # noqa: E402
    group_metrics, identity_metrics, information_metrics, fragmentation_score, integration_score,
)


def _make(agents=300, seed=42):
    cfg = default_society_config()
    cfg["population"]["count"] = agents
    eng = SimulationEngine()
    s = eng.create_society(cfg, seed=seed)
    return eng, s


def _run(eng, s, ticks, step=100):
    for _ in range(ticks // step):
        eng.step(s.society_id, ticks=step)
    if ticks % step:
        eng.step(s.society_id, ticks=ticks % step)


class TestFeedbackLoop(unittest.TestCase):
    def test_behavior_creates_event(self):
        """§44：行为可产生事件（反向闭环）。"""
        eng, s = _make(agents=300, seed=42)
        # 制造高愤怒 + 低政府信任 → 触发 protest 行为
        for a in s.agents:
            a.status["anger"] = 0.9
            a.status["trust_in_government"] = 0.1
        _run(eng, s, 500)
        behavior_events = [e for e in s.events.events if e.source == "behavior"]
        self.assertGreater(len(behavior_events), 0, "行为应产生事件")

    def test_event_creates_information(self):
        """§26：事件产生信息。"""
        eng, s = _make(agents=300, seed=42)
        eng.inject_event(s.society_id, "food_shortage", severity=0.8)
        _run(eng, s, 500)
        self.assertGreater(len(s.information_messages), 0, "事件应产生 Information")

    def test_information_changes_belief(self):
        """§38：信息改变信念（再影响行为/身份）。"""
        eng, s = _make(agents=300, seed=42)
        eng.inject_event(s.society_id, "food_shortage", severity=0.9)
        _run(eng, s, 3000)
        believers = 0
        for a in s.agents:
            if a.beliefs and any(b.belief_strength > 0.1 for b in a.beliefs.values()):
                believers += 1
        self.assertGreater(believers, 0, "信息应使部分 Agent 形成信念")

    def test_group_changes_behavior(self):
        """§20：群体影响成员行为（合作/身份）。"""
        eng, s = _make(agents=300, seed=42)
        _run(eng, s, 5000)
        in_group = [a for a in s.agents if a.identity.membership_count() > 0]
        self.assertGreater(len(in_group), 0)
        for a in in_group[:20]:
            self.assertGreaterEqual(a.identity.belonging, 0.3, "群体成员归属感应升高")


class TestSocialEmergence(unittest.TestCase):
    def test_emergence_without_preset_groups(self):
        """§74, §82：无预设群体时，社会自然涌现结构。"""
        eng, s = _make(agents=400, seed=42)
        _run(eng, s, 8000)   # 80 天
        gm = group_metrics(s)
        im = identity_metrics(s)
        info_m = information_metrics(s)
        # 群体形成机制活跃（不强制「必须 5 个」，只验证机制存在）
        self.assertGreater(gm["active_group_count"], 0, "应有群体自然形成")
        self.assertGreaterEqual(gm["average_group_size"], 3.0, "群体规模应 >= min_size")
        # 身份强度非零（群体成员形成了身份）
        self.assertGreater(im["identity_strength"], 0.0, "身份强度应非零")
        # 指标可计算
        self.assertTrue(0.0 <= info_m["echo_chamber_score"] <= 1.0)
        self.assertTrue(0.0 <= fragmentation_score(s) <= 1.0)
        self.assertTrue(0.0 <= integration_score(s) <= 1.0)

    def test_different_seeds_produce_different_structures(self):
        """§82：不同 seed 出现不同宏观结构。"""
        results = []
        for seed in (1, 2, 3):
            eng, s = _make(agents=350, seed=seed)
            _run(eng, s, 5000)
            gm = group_metrics(s)
            results.append((gm["active_group_count"], round(gm["average_group_size"], 1),
                            round(fragmentation_score(s), 2)))
        # 至少有两个 seed 产生不同结构（不要求全部不同，但不应完全一致）
        self.assertGreater(len(set(results)), 1, f"不同 seed 应产生不同结构: {results}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
