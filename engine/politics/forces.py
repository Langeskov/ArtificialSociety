"""Axis Force Registry — v0.3.1 校准版（连续 X / 双向 Z / 多驱动 Y）。

v0.3.1 修复（见 docs/political_dynamics_v0.3.1_audit.md）：

  * X（经济）  ← 连续 econ_bias（tanh） + deadzone + saturation，消除二值分叉 (§4–§7)
  * Y（权威）  ← 多驱动：legitimacy + security + institutional，双向压力 (§13–§15)
  * Z（集体）  ← 双向偏好：autonomy_preference vs belonging_need + group_pressure，
                消除社会联结带来的永久 Z+ 偏置 (§8–§12)

禁止用随机噪声伪造 Y/Z 运动（§24, §47）：每个力源都是可解释机制。
"""

from __future__ import annotations

import math
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

# Y 轴信号分类（§13, §14）
_SECURITY_EVENTS = {"conflict", "war", "protest"}
_INSTITUTIONAL_EVENTS = {"government_response", "leadership_change", "scandal", "reform", "recovery", "food_stabilization"}
_RECOVERY_EVENTS = {"recovery", "food_stabilization"}


def _autonomy_preference(p) -> float:
    """自主偏好（个体主义倾向）∈ [0,1]，从人格映射，非硬映射（§9）。"""
    return (p["openness"] + p["risk_tolerance"] + (1.0 - p["agreeableness"])) / 3.0


def _belonging_need(p) -> float:
    """归属需求（集体主义倾向）∈ [0,1]，从人格映射，非硬映射（§9）。"""
    return (p["agreeableness"] + p["empathy"] + p["extraversion"]) / 3.0


def _indiv_pref(a: Agent) -> float:
    """个体主义倾向 [-1,1]：v0.4 从 identity.belonging/autonomy 读取（§15），
    初始由人格映射、随后随群体身份演化。"""
    ident = getattr(a, "identity", None)
    if ident is not None:
        return ident.autonomy - ident.belonging
    p = a.personality
    return _autonomy_preference(p) - _belonging_need(p)


def _econ_bias(gov: float, sensitivity: float, deadzone: float) -> float:
    """连续经济方向响应（§4, §5）：gov=0→+1, gov=0.5→0, gov=1→−1，无二值翻转。"""
    bias = math.tanh((0.5 - gov) * sensitivity)
    # deadzone：近中心减弱（让中间人格不被微小 trust 差异强行分流）
    a = abs(bias)
    if deadzone > 0.0 and a < deadzone:
        bias *= a / deadzone
    return bias


def _pressure_response(pressure: float, saturation: float) -> float:
    """压力饱和（§6）：tanh 有界，小压力强响应、大压力饱和，不会 fx→∞。"""
    if saturation <= 0.0:
        return pressure
    return math.tanh(pressure * saturation)


def interpret_event(event_type: str, agent: Agent, sensitivity: float = 1.0, deadzone: float = 0.0) -> tuple[float, float, float]:
    """个体化事件解读（§8, §9）：同一事件对不同 Agent 产生不同甚至相反的方向。

    v0.3.1：X 方向改连续（§4），Z 方向改双向偏好（§9），不再 empathy→Z- 硬映射。
    """
    if event_type in _RECOVERY_EVENTS:
        return (0.0, 0.0, 0.0)
    sx, sy, sz = EVENT_SALIENCE.get(event_type, _DEFAULT_SALIENCE)
    p = agent.personality
    trust = p["trust"]
    authority = p["authority_preference"]
    risk = p["risk_tolerance"]

    reactivity = 0.3 + (1.0 - risk) * 0.7

    gov = (trust + authority) / 2.0
    x_bias = _econ_bias(gov, sensitivity, deadzone)  # 连续 X 方向
    conviction = 0.4 + 0.6 * abs(gov - 0.5) * 2.0
    dx = sx * x_bias * conviction

    dy = sy * (authority - 0.5) * 2.0

    # Z 方向 = 双向偏好（自主 − 归属），非硬 empathy 映射（v0.4 用 identity §15）
    indiv_pref = _indiv_pref(agent)
    dz = sz * indiv_pref

    return (dx * reactivity, dy * reactivity, dz * reactivity)


def _resource_pressure(a: Agent) -> float:
    """v0.4.2.1 P0-8/9: resource pressure as deviation from personal baseline.

    Long-poor agents adapt their baseline; only sudden deterioration creates
    a political shock. This prevents perpetual X-axis drift from chronic poverty.
    """
    v = a.resources.values
    food = v["food"]
    money = v["money"]
    p_food = max(0.0, min(1.0, 1.0 - food / 100.0))
    p_money = max(0.0, min(1.0, 1.0 - money / 1000.0))
    current_pressure = 0.6 * p_food + 0.4 * p_money

    # P0-9: personal baseline adapts slowly to current pressure
    baseline = getattr(a, "resource_pressure_baseline", 0.2)
    a.resource_pressure_baseline = baseline * 0.999 + current_pressure * 0.001

    # P0-8: political reaction is shock (deviation from baseline), not state
    shock = current_pressure - a.resource_pressure_baseline
    return max(0.0, shock)


@dataclass(slots=True)
class ForceParams:
    """每个 tick 从 cfg 预读一次的力参数（避免逐 Agent 重复 dict.get）。"""

    # axis weights
    wx: float
    wy: float
    wz: float
    # X axis (§4–§7)
    economic_strength: float
    sensitivity: float
    deadzone: float
    saturation: float
    # Y axis (§13–§15)
    authority_strength: float
    security_strength: float
    legitimacy_strength: float
    # Z axis (§8–§12)
    autonomy_strength: float
    belonging_strength: float
    group_pressure_strength: float
    # shared dynamics
    anchor_strength: float
    center_stability: float
    influence_strength: float
    echo2: float            # echo_threshold^2（平方距离比较，省 sqrt）
    far2: float             # (echo_threshold*2)^2
    noise: float
    # coupling (§22)
    coupling_mode: str      # velocity | state | hybrid
    cxy: float
    cxz: float
    cyx: float
    cyz: float
    czx: float
    czy: float
    avg_degree: float


def make_force_params(cfg: dict) -> ForceParams:
    """从配置构造力参数（§37, §38 兼容：旧字段回退）。"""
    pol = cfg.get("politics", {})
    soc_cfg = cfg.get("social", {})
    aw = pol.get("axis_weights", {})
    echo = soc_cfg.get("echo_threshold", 0.4)

    # X axis（§37 新结构，回退到默认连续参数）
    xc = pol.get("x_axis", {})
    # Y axis（新结构，回退到旧的 authority_dynamics_strength）
    yc = pol.get("y_axis", {})
    yc_authority = yc.get("authority_strength", pol.get("authority_dynamics_strength", 0.03))
    # Z axis（新结构，回退到旧的 community_dynamics_strength）
    zc = pol.get("z_axis", {})
    zc_autonomy = zc.get("autonomy_strength", pol.get("community_dynamics_strength", 0.02))

    # coupling：支持旧 dict（纯交叉项）与新 dict（含 mode）
    coupling = pol.get("coupling", {})
    coupling_mode = coupling.get("mode", "velocity") if isinstance(coupling, dict) else "velocity"

    # noise：§24 降到 0.001；支持 float 或 {enabled, strength}
    noise = pol.get("noise", 0.001)
    if isinstance(noise, dict):
        noise = noise.get("strength", 0.001) if noise.get("enabled", True) else 0.0

    return ForceParams(
        wx=aw.get("x", 1.0),
        wy=aw.get("y", 1.0),
        wz=aw.get("z", 1.0),
        economic_strength=xc.get("economic_strength", 0.40),
        sensitivity=xc.get("sensitivity", 1.0),
        deadzone=xc.get("deadzone", 0.05),
        saturation=xc.get("saturation", 1.0),
        authority_strength=yc_authority,
        security_strength=yc.get("security_strength", 0.02),
        legitimacy_strength=yc.get("legitimacy_strength", 0.03),
        autonomy_strength=zc_autonomy,
        belonging_strength=zc.get("belonging_strength", 0.02),
        group_pressure_strength=zc.get("group_pressure_strength", 0.02),
        anchor_strength=pol.get("ideology_anchor_strength", 0.02),
        center_stability=pol.get("center_stability", 0.005),
        influence_strength=soc_cfg.get("influence_strength", pol.get("influence_strength", 0.01)),
        echo2=echo * echo,
        far2=(echo * 2.0) * (echo * 2.0),
        noise=noise,
        coupling_mode=coupling_mode,
        cxy=coupling.get("xy", 0.01),
        cxz=coupling.get("xz", 0.01),
        cyx=coupling.get("yx", 0.01),
        cyz=coupling.get("yz", 0.01),
        czx=coupling.get("zx", 0.01),
        czy=coupling.get("zy", 0.01),
        avg_degree=cfg.get("relationships", {}).get("avg_degree", 6),
    )


def compute_forces(a: Agent, society, params: ForceParams, rng, pressure: float, build_breakdown: bool = False):
    """计算单个 Agent 的三轴总力（v0.3.1 校准公式）。

    热路径返回 (total_tuple, None)；build_breakdown=True 时返回
    (total_tuple, breakdown_dict)。参数经 ForceParams 预读。
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

    # Z 双向偏好（§9, v0.4 §15）：autonomy vs belonging，来自 identity（随群体演化）
    ident = getattr(a, "identity", None)
    if ident is not None:
        autonomy_pref = ident.autonomy
        belonging_need = ident.belonging
    else:
        autonomy_pref = _autonomy_preference(p)
        belonging_need = _belonging_need(p)
    indiv_pref = autonomy_pref - belonging_need  # [-1, +1]

    # ---- X：连续经济驱动（§4–§7） ----------------------------------------
    econ_bias = _econ_bias(gov, params.sensitivity, params.deadzone)
    fx_eco = _pressure_response(pressure, params.saturation) * params.economic_strength * econ_bias * params.wx

    # ---- Y：多驱动（§13–§15） ---------------------------------------------
    trust_gov = a.status.get("trust_in_government", 0.5)
    legitimacy_stress = 0.5 - trust_gov  # 低信任 → 合法性压力

    # ---- Z：双向偏好（§8–§12） ---------------------------------------------
    n_friends = len(net.get(a.id, [])) if net else 0
    isolation = 1.0 - min(1.0, n_friends / params.avg_degree) if params.avg_degree > 1 else 0.0
    connectedness = 1.0 - isolation

    # 自主 → Z+，归属 → Z-（方向由偏好决定，联结只调制幅度，非单向）
    fz_comm = (autonomy_pref * params.autonomy_strength - belonging_need * params.belonging_strength) * params.wz
    fz_comm *= (1.0 + params.group_pressure_strength * connectedness)

    # ---- 事件压力（连续 X + 双向 Z + Y 信号） -----------------------------
    reactivity = 0.3 + (1.0 - risk) * 0.7
    conviction = 0.4 + 0.6 * abs(gov - 0.5) * 2.0
    dy_factor = (authority - 0.5) * 2.0
    security_signal = 0.0
    institutional_signal = 0.0
    fx_ev = fy_ev = fz_ev = 0.0
    for m in a.recent_events:
        etype = m["type"]
        # Recovery is an accounting/causal marker, not a fresh political
        # shock.  Feeding it back into X/Y/Z made every protest resolution
        # create another political impulse and helped form a limit cycle.
        if etype in _RECOVERY_EVENTS:
            continue
        s = m.get("strength", 0.0)
        sx, sy, sz = EVENT_SALIENCE.get(etype, _DEFAULT_SALIENCE)
        fx_ev += sx * econ_bias * conviction * reactivity * s
        fy_ev += sy * dy_factor * reactivity * s
        fz_ev += sz * indiv_pref * reactivity * s
        # Y 独立信号（§13, §14）
        if etype in _SECURITY_EVENTS:
            security_signal += sy * s
        elif etype in _INSTITUTIONAL_EVENTS:
            institutional_signal += sy * s

    # Y 总权威力（legitimacy + security + institutional，个体方向调制）
    fy_auth = (
        legitimacy_stress * params.authority_strength
        + security_signal * params.security_strength
        + institutional_signal * params.legitimacy_strength
    ) * dy_factor * params.wy

    # ---- 社会影响（弱，回音室；平方距离比较，省 sqrt） --------------------
    fx_soc = fy_soc = fz_soc = 0.0
    fz_group = 0.0
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
                # Z group pressure（§9）：归属需求强 → 顺从邻居 Z 均值
                fz_group = params.group_pressure_strength * belonging_need * (az_soc / wsum - iz) * params.wz

    # 社区力 = 个人偏好 + 群体压力（合并计入 breakdown 的 community 源）
    fz_community = fz_comm + fz_group

    # ---- 个人锚点 ----------------------------------------------------------
    ax, ay, az = a.ideology_anchor
    # v0.4.5.3 §26: Anchor adaptation — strength weakens over time
    # Early: identity inertia stronger; Long run: social experience can reshape
    adapted_anchor = params.anchor_strength
    if hasattr(a, '_anchor_adapt_days') and a._anchor_adapt_days > 0:
        days = getattr(a, '_simulated_days', 0)
        initial = params.anchor_strength
        long_run = getattr(a, '_anchor_long_run_strength', initial * 0.25)
        adapt_days = a._anchor_adapt_days
        t = min(1.0, days / adapt_days)
        adapted_anchor = initial * (1 - t) + long_run * t
    fx_anchor = (ax - a.ideology.x) * adapted_anchor
    fy_anchor = (ay - a.ideology.y) * adapted_anchor
    fz_anchor = (az - a.ideology.z) * adapted_anchor

    # ---- 中心稳定力 --------------------------------------------------------
    fx_center = -a.ideology.x * params.center_stability
    fy_center = -a.ideology.y * params.center_stability
    fz_center = -a.ideology.z * params.center_stability

    # ---- 弱轴耦合（§22：velocity | state | hybrid） ------------------------
    vx, vy, vz = a.political_velocity
    mod = 0.5 + 0.5 * openness
    mode = params.coupling_mode
    if mode == "state":
        fx_coup = (params.cxy * a.ideology.y + params.cxz * a.ideology.z) * mod
        fy_coup = (params.cyx * a.ideology.x + params.cyz * a.ideology.z) * mod
        fz_coup = (params.czx * a.ideology.x + params.czy * a.ideology.y) * mod
    elif mode == "hybrid":
        fx_coup = (params.cxy * (vy + a.ideology.y) + params.cxz * (vz + a.ideology.z)) * mod
        fy_coup = (params.cyx * (vx + a.ideology.x) + params.cyz * (vz + a.ideology.z)) * mod
        fz_coup = (params.czx * (vx + a.ideology.x) + params.czy * (vy + a.ideology.y)) * mod
    else:  # velocity
        fx_coup = (params.cxy * vy + params.cxz * vz) * mod
        fy_coup = (params.cyx * vx + params.cyz * vz) * mod
        fz_coup = (params.czx * vx + params.czy * vy) * mod

    # ---- 微小随机波动（§24：noise << systematic，非伪造） ------------------
    n = params.noise
    if n > 0:
        fx_noise = rng.uniform(-n, n)
        fy_noise = rng.uniform(-n, n)
        fz_noise = rng.uniform(-n, n)
    else:
        fx_noise = fy_noise = fz_noise = 0.0

    tx = fx_eco + fx_ev + fx_soc + fx_anchor + fx_center + fx_coup + fx_noise
    ty = fy_auth + fy_ev + fy_soc + fy_anchor + fy_center + fy_coup + fy_noise
    tz = fz_community + fz_ev + fz_soc + fz_anchor + fz_center + fz_coup + fz_noise

    if not build_breakdown:
        return (tx, ty, tz), None

    br = {
        "x": {"economic": fx_eco, "authority": 0.0, "community": 0.0, "event": fx_ev,
              "social": fx_soc, "anchor": fx_anchor, "center": fx_center,
              "coupling": fx_coup, "noise": fx_noise},
        "y": {"economic": 0.0, "authority": fy_auth, "community": 0.0, "event": fy_ev,
              "social": fy_soc, "anchor": fy_anchor, "center": fy_center,
              "coupling": fy_coup, "noise": fy_noise},
        "z": {"economic": 0.0, "authority": 0.0, "community": fz_community, "event": fz_ev,
              "social": fz_soc, "anchor": fz_anchor, "center": fz_center,
              "coupling": fz_coup, "noise": fz_noise},
    }
    return (tx, ty, tz), br



