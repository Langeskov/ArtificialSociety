"""Axis Force Registry — 统一计算三轴政治力（项目计划书 v0.3 §4, §5, §6, §7, §9).

每个政治力源显式标注其作用轴与强度，输出可解释的力分解（Axis Contribution
Breakdown）。三轴拥有**不同的主要驱动力**：

  * X（经济/分配）  ← 资源稀缺、财富、税收、不平等
  * Y（社会/权威）  ← 政府合法性、信任、冲突、权威偏好
  * Z（个体/集体）  ← 社会联结、隔离、互助、群体归属

禁止用随机噪声伪造 Y/Z 运动（§47）：每个力源都是可解释的机制。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..agent.agent import Agent

# 轴索引
X, Y, Z = 0, 1, 2

_DEFAULT_SALIENCE = (0.1, 0.1, 0.1)

# 每个事件类型对三轴的政治「显著性」幅度（§8, §9）。方向由 Agent 个体特征决定。
EVENT_SALIENCE: dict[str, tuple[float, float, float]] = {
    # 稀缺类：经济 / 权威 / 集体
    "food_shortage":       (0.6, 0.3, 0.4),
    "economic_crisis":     (0.5, 0.2, 0.2),
    "market_panic":        (0.4, 0.1, 0.1),
    "unemployment":        (0.4, 0.2, 0.3),
    # 权威类
    "protest":             (0.2, 0.6, 0.3),
    "political_movement":  (0.2, 0.5, 0.3),
    "scandal":             (0.1, 0.5, 0.1),
    "government_response": (0.2, 0.5, 0.1),
    "leadership_change":   (0.1, 0.4, 0.1),
    # 集体 / 权威集结
    "natural_disaster":    (0.4, 0.3, 0.6),
    "war":                 (0.3, 0.6, 0.5),
    "conflict":            (0.2, 0.5, 0.4),
    # 积极 / 自由
    "resource_boom":       (0.4, 0.1, 0.2),
    "technology_breakthrough": (0.3, 0.1, 0.3),
    "alliance":            (0.1, 0.1, 0.3),
    # 恢复 / 稳定
    "reform":              (0.2, 0.2, 0.1),
    "recovery":            (0.2, 0.1, 0.1),
    "food_stabilization":  (0.1, 0.1, 0.2),
}


def interpret_event(event_type: str, agent: Agent) -> tuple[float, float, float]:
    """个体化事件解读（§8, §9）：同一事件对不同 Agent 产生不同甚至相反的方向。"""
    sx, sy, sz = EVENT_SALIENCE.get(event_type, (0.1, 0.1, 0.1))
    p = agent.personality
    trust = p["trust"]
    authority = p["authority_preference"]
    empathy = p["empathy"]
    risk = p["risk_tolerance"]

    reactivity = 0.3 + (1.0 - risk) * 0.7

    gov = (trust + authority) / 2.0
    x_dir = -1.0 if gov >= 0.5 else 1.0
    conviction = 0.4 + 0.6 * abs(gov - 0.5) * 2.0
    dx = sx * x_dir * conviction

    dy = sy * (authority - 0.5) * 2.0
    dz = sz * -(empathy - 0.5) * 2.0

    return (dx * reactivity, dy * reactivity, dz * reactivity)


def _resource_pressure(a: Agent) -> float:
    v = a.resources.values
    food = v["food"]
    money = v["money"]
    p_food = 1.0 - food / 100.0
    if p_food < 0.0:
        p_food = 0.0
    elif p_food > 1.0:
        p_food = 1.0
    p_money = 1.0 - money / 1000.0
    if p_money < 0.0:
        p_money = 0.0
    elif p_money > 1.0:
        p_money = 1.0
    return 0.6 * p_food + 0.4 * p_money


def economic_force_x(a: Agent, cfg: dict) -> float:
    """X 轴经济驱动（§9）：稀缺 → 亲政府者求管控（x-），反政府者求自由（x+）。"""
    pol = cfg.get("politics", {})
    w = pol.get("axis_weights", {}).get("x", 1.0)
    pressure = _resource_pressure(a)
    gov = (a.personality["trust"] + a.personality["authority_preference"]) / 2.0
    econ_dir = -1.0 if gov >= 0.5 else 1.0
    return pressure * 0.4 * econ_dir * w


def authority_force_y(a: Agent, cfg: dict) -> float:
    """Y 轴权威/合法性驱动（§9）：低政府信任 → 权威轴极化。

    合法性压力 = 0.5 − trust_in_government。信任越低，亲权威者越倾向权威（y+）、
    反权威者越倾向自由（y-），形成 Y 轴两极分化——而非向中心塌缩。
    """
    pol = cfg.get("politics", {})
    w = pol.get("axis_weights", {}).get("y", 1.0)
    strength = pol.get("authority_dynamics_strength", 0.03)
    trust_gov = a.status.get("trust_in_government", 0.5)
    authority = a.personality["authority_preference"]
    legitimacy_stress = 0.5 - trust_gov          # 低信任 → 高压力（≈0..0.5）
    return legitimacy_stress * (authority - 0.5) * 2.0 * strength * w


def community_force_z(a: Agent, society, cfg: dict) -> float:
    """Z 轴集体/个体驱动（§9）：社会联结 → 个人主义，孤立 + 高同理心 → 集体主义。"""
    pol = cfg.get("politics", {})
    w = pol.get("axis_weights", {}).get("z", 1.0)
    strength = pol.get("community_dynamics_strength", 0.02)
    avg_degree = cfg.get("relationships", {}).get("avg_degree", 6)
    net = getattr(society, "_network", None)
    n_friends = len(net.get(a.id, [])) if net else 0
    isolation = 1.0 - min(1.0, n_friends / max(avg_degree, 1))
    empathy = a.personality["empathy"]
    # 联结良好 → 个人主义（z+）；孤立且高同理心 → 集体主义（z-）
    return ((1.0 - isolation) * 0.5 - isolation * empathy) * strength * w


def coupling_force(a: Agent, cfg: dict) -> tuple[float, float, float]:
    """弱轴耦合（§7）：coupling_force = C_cross × velocity，只取交叉项。

    交叉项保持 |c| < 0.05，避免三轴重新同步（§47）。
    """
    c = cfg.get("politics", {}).get("coupling", {})
    vx, vy, vz = a.political_velocity
    # 非线性调制（§8）：开放性高的 Agent 耦合更强
    mod = 0.5 + 0.5 * a.personality["openness"]
    cx = c.get("xy", 0.0) * vy + c.get("xz", 0.0) * vz
    cy = c.get("yx", 0.0) * vx + c.get("yz", 0.0) * vz
    cz = c.get("zx", 0.0) * vx + c.get("zy", 0.0) * vy
    return (cx * mod, cy * mod, cz * mod)


@dataclass(slots=True)
class ForceParams:
    """每个 tick 从 cfg 预读一次的力参数（避免逐 Agent 重复 dict.get）。"""

    wx: float
    wy: float
    wz: float
    anchor_strength: float
    center_stability: float
    influence_strength: float
    echo2: float            # echo_threshold^2（平方距离比较，省 sqrt）
    far2: float             # (echo_threshold*2)^2
    noise: float
    authority_strength: float
    community_strength: float
    cxy: float
    cxz: float
    cyx: float
    cyz: float
    czx: float
    czy: float
    avg_degree: float


def make_force_params(cfg: dict) -> ForceParams:
    pol = cfg.get("politics", {})
    soc_cfg = cfg.get("social", {})
    aw = pol.get("axis_weights", {})
    coupling = pol.get("coupling", {})
    echo = soc_cfg.get("echo_threshold", 0.4)
    return ForceParams(
        wx=aw.get("x", 1.0),
        wy=aw.get("y", 1.0),
        wz=aw.get("z", 1.0),
        anchor_strength=pol.get("ideology_anchor_strength", 0.02),
        center_stability=pol.get("center_stability", 0.005),
        influence_strength=soc_cfg.get("influence_strength", pol.get("influence_strength", 0.01)),
        echo2=echo * echo,
        far2=(echo * 2.0) * (echo * 2.0),
        noise=pol.get("noise", 0.004),
        authority_strength=pol.get("authority_dynamics_strength", 0.03),
        community_strength=pol.get("community_dynamics_strength", 0.02),
        cxy=coupling.get("xy", 0.0),
        cxz=coupling.get("xz", 0.0),
        cyx=coupling.get("yx", 0.0),
        cyz=coupling.get("yz", 0.0),
        czx=coupling.get("zx", 0.0),
        czy=coupling.get("zy", 0.0),
        avg_degree=cfg.get("relationships", {}).get("avg_degree", 6),
    )


def compute_forces(a: Agent, society, params: ForceParams, rng, pressure: float, build_breakdown: bool = False):
    """计算单个 Agent 的三轴总力，可选构建力分解 dict（§5，仅在调试/采样时构建）。

    热路径返回 (total_tuple, None)，避免每 tick 分配 dict；build_breakdown=True
    时返回 (total_tuple, breakdown_dict)。参数经 ForceParams 预读，避免逐 Agent
    重复 cfg.get。
    """
    p = a.personality
    trust = p["trust"]
    authority = p["authority_preference"]
    empathy = p["empathy"]
    openness = p["openness"]
    risk = p["risk_tolerance"]

    gov = (trust + authority) / 2.0
    net = getattr(society, "_network", None)
    agent_map = society.agent_map()

    # X：经济驱动（稀缺 → 亲政府求管控，反政府求自由）
    fx_eco = pressure * 0.4 * (-1.0 if gov >= 0.5 else 1.0) * params.wx

    # Y：权威/合法性驱动（低信任 → 权威轴极化）
    trust_gov = a.status.get("trust_in_government", 0.5)
    fy_auth = (0.5 - trust_gov) * (authority - 0.5) * 2.0 * params.authority_strength * params.wy

    # Z：社区/联结驱动（联结→个人主义，孤立且高同理心→集体主义）
    n_friends = len(net.get(a.id, [])) if net else 0
    isolation = 1.0 - min(1.0, n_friends / params.avg_degree) if params.avg_degree > 1 else 0.0
    fz_comm = ((1.0 - isolation) * 0.5 - isolation * empathy) * params.community_strength * params.wz

    # 事件压力（内联 interpret_event，避免逐事件重复读 personality）
    reactivity = 0.3 + (1.0 - risk) * 0.7
    x_dir = -1.0 if gov >= 0.5 else 1.0
    conviction = 0.4 + 0.6 * abs(gov - 0.5) * 2.0
    dy_factor = (authority - 0.5) * 2.0
    dz_factor = -(empathy - 0.5) * 2.0
    fx_ev = fy_ev = fz_ev = 0.0
    for m in a.recent_events:
        sx, sy, sz = EVENT_SALIENCE.get(m["type"], _DEFAULT_SALIENCE)
        s = m.get("strength", 0.0)
        fx_ev += sx * x_dir * conviction * reactivity * s
        fy_ev += sy * dy_factor * reactivity * s
        fz_ev += sz * dz_factor * reactivity * s

    # 社会影响（弱，回音室；平方距离比较，省 sqrt）
    fx_soc = fy_soc = fz_soc = 0.0
    if net and params.influence_strength > 0:
        nbrs = net.get(a.id)
        if nbrs:
            ix = a.ideology.x
            iy = a.ideology.y
            iz = a.ideology.z
            echo2 = params.echo2
            far2 = params.far2
            hi_trust = trust > 0.5
            ax_soc = ay_soc = az_soc = 0.0
            wsum = 0.0
            for nid in nbrs:
                other = agent_map.get(nid)
                if other is None or not other.alive:
                    continue
                ox = other.ideology.x
                oy = other.ideology.y
                oz = other.ideology.z
                dx = ix - ox
                dy = iy - oy
                dz = iz - oz
                d2 = dx * dx + dy * dy + dz * dz
                w = 1.0
                if d2 < echo2 and hi_trust:
                    w = 1.6
                elif d2 > far2:
                    w = 0.3
                ax_soc += ox * w
                ay_soc += oy * w
                az_soc += oz * w
                wsum += w
            if wsum > 0:
                fx_soc = (ax_soc / wsum - ix) * params.influence_strength
                fy_soc = (ay_soc / wsum - iy) * params.influence_strength
                fz_soc = (az_soc / wsum - iz) * params.influence_strength

    # 个人锚点
    ax, ay, az = a.ideology_anchor
    fx_anchor = (ax - a.ideology.x) * params.anchor_strength
    fy_anchor = (ay - a.ideology.y) * params.anchor_strength
    fz_anchor = (az - a.ideology.z) * params.anchor_strength

    # 中心稳定力
    fx_center = -a.ideology.x * params.center_stability
    fy_center = -a.ideology.y * params.center_stability
    fz_center = -a.ideology.z * params.center_stability

    # 弱轴耦合
    vx, vy, vz = a.political_velocity
    mod = 0.5 + 0.5 * openness
    fx_coup = (params.cxy * vy + params.cxz * vz) * mod
    fy_coup = (params.cyx * vx + params.cyz * vz) * mod
    fz_coup = (params.czx * vx + params.czy * vy) * mod

    # 微小随机波动
    n = params.noise
    fx_noise = rng.uniform(-n, n)
    fy_noise = rng.uniform(-n, n)
    fz_noise = rng.uniform(-n, n)

    tx = fx_eco + fx_ev + fx_soc + fx_anchor + fx_center + fx_coup + fx_noise
    ty = fy_auth + fy_ev + fy_soc + fy_anchor + fy_center + fy_coup + fy_noise
    tz = fz_comm + fz_ev + fz_soc + fz_anchor + fz_center + fz_coup + fz_noise

    if not build_breakdown:
        return (tx, ty, tz), None

    br = {
        "x": {"economic": fx_eco, "authority": 0.0, "community": 0.0, "event": fx_ev,
              "social": fx_soc, "anchor": fx_anchor, "center": fx_center,
              "coupling": fx_coup, "noise": fx_noise},
        "y": {"economic": 0.0, "authority": fy_auth, "community": 0.0, "event": fy_ev,
              "social": fy_soc, "anchor": fy_anchor, "center": fy_center,
              "coupling": fy_coup, "noise": fy_noise},
        "z": {"economic": 0.0, "authority": 0.0, "community": fz_comm, "event": fz_ev,
              "social": fz_soc, "anchor": fz_anchor, "center": fz_center,
              "coupling": fz_coup, "noise": fz_noise},
    }
    return (tx, ty, tz), br
