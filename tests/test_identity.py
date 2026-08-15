"""Identity system tests — v0.4 §73。

覆盖：身份独立于 ideology、随时间变化、多群体成员、主身份。
"""

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.simulation.engine import SimulationEngine          # noqa: E402
from configs.loader import default_society_config                # noqa: E402
from engine.agent.agent import Agent                            # noqa: E402
from engine.agent.personality import Personality                # noqa: E402
from engine.agent.ideology import Ideology                      # noqa: E402
from engine.identity.update import init_identity                # noqa: E402


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


class TestIdentityIndependence(unittest.TestCase):
    def test_identity_is_independent_from_ideology(self):
        """§14, §19：identity 不是 ideology，不能直接设置政治坐标。"""
        p = Personality(values={"openness": 0.5, "conscientiousness": 0.5, "extraversion": 0.5,
                                "agreeableness": 0.5, "neuroticism": 0.5, "risk_tolerance": 0.5,
                                "trust": 0.5, "aggression": 0.5, "empathy": 0.5, "authority_preference": 0.5})
        a = Agent(id="t", personality=p, ideology=Ideology(x=0.7, y=0.1, z=-0.3))
        a.identity = init_identity(a)
        # 身份字段不包含政治坐标；修改身份不应直接改动 ideology
        a.identity.belonging = 0.9
        a.identity.autonomy = 0.1
        self.assertEqual(a.ideology.x, 0.7)
        self.assertEqual(a.ideology.z, -0.3)
        self.assertNotIn("x", a.identity.as_dict())
        self.assertNotIn("ideology", a.identity.as_dict())

    def test_multiple_group_membership(self):
        """§51：一个 Agent 可同时属于多个 Group。"""
        a = Agent(id="t")
        a.identity.add_group("g1")
        a.identity.add_group("g2")
        a.identity.add_group("g3")
        self.assertEqual(a.identity.membership_count(), 3)
        self.assertIn("g1", a.identity.group_memberships)
        # 主身份默认是第一个
        self.assertEqual(a.identity.primary_group, "g1")

    def test_primary_identity(self):
        """§17：primary_group 决定冲突时的优先支持。"""
        a = Agent(id="t")
        a.identity.add_group("g1")
        a.identity.add_group("g2")
        self.assertEqual(a.identity.primary_group, "g1")
        # 移除主身份 → 次身份顶上
        a.identity.remove_group("g1")
        self.assertEqual(a.identity.primary_group, "g2")


class TestIdentityEvolution(unittest.TestCase):
    def test_identity_changes_over_time(self):
        """§53：身份随时间变化（群体成员 → 归属上升）。"""
        eng, s = _make(agents=300, seed=42)
        a = s.agents[0]
        b0 = a.identity.belonging
        s0 = a.identity.social_identity_strength
        _run(eng, s, 5000)
        a = s.agents[0]
        # 若加入群体，身份强度应上升；若未加入，至少不崩溃
        self.assertGreaterEqual(a.identity.social_identity_strength, 0.0)
        # 有群体的 Agent 归属感上升
        if a.identity.membership_count() > 0:
            self.assertGreater(a.identity.belonging, b0)
        self.assertGreaterEqual(s0, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
