"""Group system tests — v0.4 §73。

覆盖：群体形成、持久性要求、解散、分裂、合并。
"""

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.simulation.engine import SimulationEngine          # noqa: E402
from configs.loader import default_society_config                # noqa: E402
from engine.group.group import GROUP_STATE                       # noqa: E402


def _make(agents=300, seed=42, **overrides):
    cfg = default_society_config()
    cfg["population"]["count"] = agents
    cfg["events"]["frequency"] = 0.02
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


class TestGroupFormation(unittest.TestCase):
    def test_group_forms(self):
        eng, s = _make(agents=300, seed=42)
        _run(eng, s, 5000)
        active = s.groups.active()
        self.assertGreater(len(active), 0, "5000 tick 后应有群体自然形成")

    def test_group_requires_persistence(self):
        # 形成阈值调高 → 短期不应形成
        eng, s = _make(agents=300, seed=42)
        s.config["groups"]["formation"]["threshold"] = 0.99
        _run(eng, s, 1000)
        self.assertEqual(len(s.groups.active()), 0, "阈值过高时不应形成群体")

    def test_group_respects_min_size(self):
        eng, s = _make(agents=300, seed=42)
        s.config["groups"]["min_size"] = 5
        _run(eng, s, 5000)
        for g in s.groups.active():
            self.assertGreaterEqual(g.size(), 5, "群体规模应 >= min_size")


class TestGroupLifecycle(unittest.TestCase):
    def test_group_dissolves(self):
        eng, s = _make(agents=300, seed=42)
        s.config["groups"]["dissolve"]["cohesion_threshold"] = 0.9   # 几乎必然解散
        s.config["groups"]["dissolve"]["persistence_ticks"] = 5
        _run(eng, s, 6000)
        dissolved = [h for h in s.groups.history if h["type"] == "GROUP_DISSOLVED"]
        self.assertGreater(len(dissolved), 0, "低凝聚力持续后应解散")

    def test_group_splits(self):
        # 构造内部方差大 + 低凝聚力的群体，触发分裂
        eng, s = _make(agents=300, seed=42)
        s.config["groups"]["split"]["variance_threshold"] = 0.05   # 低阈值触发分裂
        s.config["groups"]["split"]["cohesion_threshold"] = 0.99
        _run(eng, s, 6000)
        splits = [h for h in s.groups.history if h["type"] == "GROUP_SPLIT"]
        self.assertGreater(len(splits), 0, "内部方差大且低凝聚力时应分裂")

    def test_group_merges(self):
        eng, s = _make(agents=300, seed=42)
        s.config["groups"]["merge"]["distance_threshold"] = 1.0   # 高阈值易合并
        _run(eng, s, 6000)
        merges = [h for h in s.groups.history if h["type"] == "GROUP_MERGED"]
        self.assertGreater(len(merges), 0, "政治距离近的群体应合并")


class TestGroupNotPoliticalCluster(unittest.TestCase):
    def test_group_has_internal_diversity(self):
        """§22, §57：群体内部允许政治分歧，不等于 political cluster。"""
        eng, s = _make(agents=300, seed=42)
        _run(eng, s, 5000)
        for g in s.groups.active():
            if g.size() >= 10:
                # 内部方差不必为 0（允许分歧）
                self.assertGreater(g.variance_x + g.variance_y + g.variance_z, 0.0,
                                   "群体内部应有政治方差（非完全一致）")


if __name__ == "__main__":
    unittest.main(verbosity=2)
