"""Political calibration tests — v0.3.1 验收（§41）。

验证：X 连续/双向/有界、Z 无系统性正漂移/双向/不等价于社会联结、
Y 响应/双向、三轴独立、耦合弱、noise 非必需、力分解求和正确。
"""

import random
import statistics
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.agent.agent import Agent                                  # noqa: E402
from engine.agent.personality import Personality                      # noqa: E402
from engine.agent.ideology import Ideology                            # noqa: E402
from engine.simulation.engine import SimulationEngine                 # noqa: E402
from configs.loader import default_society_config                     # noqa: E402
from engine.identity.update import init_identity                      # noqa: E402
from engine.politics.forces import (                                  # noqa: E402
    _econ_bias,
    _autonomy_preference,
    _belonging_need,
    compute_forces,
    make_force_params,
)


class _FakeSociety:
    """compute_forces 需要的最小 society 桩：空网络。"""

    def __init__(self):
        self._network = {}

    def agent_map(self):
        return {}


def _make_agent(trust=0.5, authority=0.5, empathy=0.5, openness=0.5, risk=0.5,
                agreeableness=0.5, extraversion=0.5, x=0.0, y=0.0, z=0.0,
                trust_gov=0.5, events=None):
    p = Personality(values={
        "openness": openness, "conscientiousness": 0.5, "extraversion": extraversion,
        "agreeableness": agreeableness, "neuroticism": 0.5, "risk_tolerance": risk,
        "trust": trust, "aggression": 0.5, "empathy": empathy, "authority_preference": authority,
    })
    a = Agent(id="t", personality=p, ideology=Ideology(x=x, y=y, z=z))
    a.identity = init_identity(a)     # v0.4：从人格初始化身份（§16）
    a.status["trust_in_government"] = trust_gov
    if events:
        a.recent_events = events
    return a


_PARAMS = None


def _params():
    global _PARAMS
    if _PARAMS is None:
        _PARAMS = make_force_params(default_society_config())
    return _PARAMS


def _forces(a, pressure=0.0, breakdown=False):
    return compute_forces(a, _FakeSociety(), _params(), random.Random(0), pressure, breakdown)


class TestXResponse(unittest.TestCase):
    """§33, §41：X 连续、双向、有界。"""

    def test_x_response_is_continuous(self):
        # gov 0.0..1.0 的 econ_bias 应单调递减且无突变
        biases = [_econ_bias(g / 10.0, 1.0, 0.0) for g in range(11)]
        for i in range(len(biases) - 1):
            self.assertGreaterEqual(biases[i], biases[i + 1], "econ_bias 非单调")
        # 相邻差值有界（无 0.49→0.51 式突变）
        for i in range(len(biases) - 1):
            self.assertLess(abs(biases[i] - biases[i + 1]), 0.3, "econ_bias 突变")

    def test_x_response_is_bidirectional(self):
        b_pos = _econ_bias(0.25, 1.0, 0.0)   # gov<0.5 → X+
        b_neg = _econ_bias(0.75, 1.0, 0.0)   # gov>0.5 → X-
        self.assertGreater(b_pos, 0.0)
        self.assertLess(b_neg, 0.0)
        # 对称（允许小误差）
        self.assertLess(abs(abs(b_pos) - abs(b_neg)), 0.05, "X 双向幅度不对称")

    def test_x_response_is_bounded(self):
        # 高 sensitivity 下 econ_bias 仍 ∈ [-1, 1]
        for g in (0.0, 0.25, 0.5, 0.75, 1.0):
            b = _econ_bias(g, 5.0, 0.0)
            self.assertTrue(-1.0 <= b <= 1.0)
        # 高压力不导致 fx 无限增长
        a = _make_agent(trust=0.0, authority=0.0, x=0.0)
        (t, _) = _forces(a, pressure=1.0)
        self.assertTrue(abs(t[0]) < 0.5, f"fx 未饱和: {t[0]}")


class TestZResponse(unittest.TestCase):
    """§11, §12, §41：Z 无系统性正漂移、双向、不等价于社会联结。"""

    def test_z_force_direction_from_preference_not_connection(self):
        # 同一连接（孤立），不同偏好 → 相反 Z 方向
        hi_autonomy = _make_agent(openness=0.9, risk=0.9, agreeableness=0.1, empathy=0.1, extraversion=0.1)
        hi_belonging = _make_agent(openness=0.1, risk=0.1, agreeableness=0.9, empathy=0.9, extraversion=0.9)
        (t1, _) = _forces(hi_autonomy)
        (t2, _) = _forces(hi_belonging)
        # Z 社区力方向由偏好决定（t1 Z+、t2 Z-）
        self.assertGreater(_autonomy_preference(hi_autonomy.personality), _belonging_need(hi_autonomy.personality))
        self.assertLess(_autonomy_preference(hi_belonging.personality), _belonging_need(hi_belonging.personality))
        # 净 Z 力符号相反（允许噪声/中心力扰动，但方向应相反）
        self.assertGreater(t1[2], t2[2], "Z 方向未随偏好变化")

    def test_z_can_move_both_directions(self):
        eng, s = _make_engine(agents=300, seed=3)
        _run(eng, s, 3000)
        moved_pos = sum(1 for a in s.agents if a.ideology.z > a.ideology_anchor[2] + 0.02)
        moved_neg = sum(1 for a in s.agents if a.ideology.z < a.ideology_anchor[2] - 0.02)
        self.assertGreater(moved_pos, 10, "无 Agent 向 Z+ 移动")
        self.assertGreater(moved_neg, 10, "无 Agent 向 Z- 移动")

    def test_z_has_no_systematic_positive_drift(self):
        # 无事件 + 中性资源 + 平衡人格 → mean Z drift ≈ 0（§11, §12）
        # v0.4: 关闭群体/身份，隔离测试 v0.3.1 Z 校准（群体会产生合法的 Z- 漂移）
        cfg = default_society_config()
        cfg["population"]["count"] = 400
        cfg["events"]["frequency"] = 0.0
        cfg["groups"]["enabled"] = False
        cfg["identity"]["enabled"] = False
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=11)
        z0 = statistics.mean(a.ideology.z for a in s.agents)
        _run(eng, s, 5000)
        z1 = statistics.mean(a.ideology.z for a in s.agents)
        drift = z1 - z0
        self.assertLess(abs(drift), 0.08, f"Z 系统性漂移: {drift:.4f}")


class TestYResponse(unittest.TestCase):
    """§34, §41：Y 响应、双向。"""

    def test_y_is_responsive_and_bidirectional(self):
        # 低信任 + 反权威 → Y-；低信任 + 亲权威 → Y+
        anti = _make_agent(authority=0.2, trust_gov=0.2)
        pro = _make_agent(authority=0.8, trust_gov=0.2)
        (t1, _) = _forces(anti)
        (t2, _) = _forces(pro)
        self.assertLess(t1[1], 0.0, "反权威低信任应 Y-")
        self.assertGreater(t2[1], 0.0, "亲权威低信任应 Y+")

    def test_y_responds_to_conflict_events(self):
        # 注入冲突事件后，Y 力幅值增大（§13 security driver）
        events = [{"type": "conflict", "strength": 0.8}]
        a0 = _make_agent(authority=0.8, trust_gov=0.5, events=None)
        a1 = _make_agent(authority=0.8, trust_gov=0.5, events=events)
        (t0, _) = _forces(a0)
        (t1, _) = _forces(a1)
        self.assertGreater(abs(t1[1]), abs(t0[1]), "冲突事件未增强 Y 力")


class TestAxisIndependence(unittest.TestCase):
    """§23, §41：三轴独立、耦合弱。"""

    def test_axes_remain_independent(self):
        eng, s = _make_engine(agents=400, seed=7)
        _run(eng, s, 3000)
        m = s.metrics()
        vars_ = [m["political_variance_x"], m["political_variance_y"], m["political_variance_z"]]
        # 三轴方差不能全相等（不能同步）
        self.assertFalse(vars_[0] == vars_[1] == vars_[2], "三轴方差完全相等（同步）")

    def test_coupling_is_weak(self):
        eng, s = _make_engine(agents=400, seed=2)
        _run(eng, s, 3000)
        m = s.metrics()
        for k in ("axis_correlation_xy", "axis_correlation_xz", "axis_correlation_yz"):
            self.assertLess(abs(m[k]), 0.8, f"{k} 相关性过高: {m[k]}")


class TestNoiseNotRequired(unittest.TestCase):
    """§24, §41：noise=0 仍不塌缩、不偏置。"""

    def test_noise_is_not_required_for_diversity(self):
        cfg = default_society_config()
        cfg["population"]["count"] = 400
        cfg["politics"]["noise"] = 0.0
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=5)
        _run(eng, s, 3000)
        m = s.metrics()
        # 无噪声下仍有三轴方差（多样性来自真实机制，非噪声）
        self.assertGreater(m["political_variance_x"], 0.02)
        self.assertGreater(m["political_variance_y"], 0.02)
        self.assertGreater(m["political_variance_z"], 0.01)


class TestForceBreakdown(unittest.TestCase):
    """§41：力分解求和正确。"""

    def test_force_breakdown_sums_correctly(self):
        a = _make_agent(trust=0.4, authority=0.7, empathy=0.6, events=[{"type": "protest", "strength": 0.5}])
        (total, br) = _forces(a, pressure=0.3, breakdown=True)
        tx, ty, tz = total
        for ax, tot in (("x", tx), ("y", ty), ("z", tz)):
            s = sum(br[ax].values())
            self.assertAlmostEqual(s, tot, places=9, msg=f"{ax} 力分解求和 != 总力")


def _make_engine(agents=400, seed=42):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
