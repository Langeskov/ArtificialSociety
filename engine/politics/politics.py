"""Politics — 意识形态漂移，v0.3 三轴独立动力学重构（§3, §4, §5）。

政治状态是三维动力系统：每轴拥有 position / velocity / inertia / damping /
anchor / external force。所有力源经 `forces.compute_forces` 统一计算，输出
可解释的力分解（Axis Contribution Breakdown）。

更新公式（§3）：
    target = position + Σ forces(经济/权威/社区/事件/社会/锚点/中心/耦合/噪声)
    position, velocity = spring_damper(position, velocity, target, inertia, damping)
"""

from __future__ import annotations

import random
from typing import Optional

from ..agent.agent import Agent
from ..dynamics.damping import spring_damper_update
from ..dynamics.stability import extremism
from .forces import compute_forces, make_force_params, interpret_event, _resource_pressure  # noqa: F401


def _adapted_resource_pressure(agent: Agent, pressure: float, dt_days: float, pol_cfg: Optional[dict] = None) -> float:
    """Turn sustained scarcity into a bounded shock instead of an endless drift.

    Resource pressure is a social condition, not a vote repeated every tick.
    Keep the rising edge strong, then adapt toward a small residual response;
    this prevents a long food shortage from integrating into an artificial X
    boundary attractor while still preserving crisis-driven movement.
    """
    status = agent.status
    previous = float(status.get("_political_resource_pressure", pressure))
    rising_edge = max(0.0, pressure - previous)
    exposure = float(status.get("_political_resource_exposure", 0.0))
    exposure += pressure * max(dt_days, 0.0)
    exposure = min(1.0, exposure * 0.999)
    status["_political_resource_pressure"] = pressure
    status["_political_resource_exposure"] = exposure
    # Resource pressure has a normal operating baseline: a new Agent with
    # roughly 500 money already has about 0.2 pressure under the legacy
    # resource scale.  Treating that baseline as a political shock creates a
    # constant X-axis drift even when the society is healthy.  Only scarcity
    # above the baseline and the rising edge should move politics.
    pol_cfg = pol_cfg or {}
    baseline = float(pol_cfg.get("resource_pressure_baseline", 0.20))
    persistent_scale = float(pol_cfg.get("resource_pressure_persistent_scale", 0.12))
    rising_edge_gain = float(pol_cfg.get("resource_pressure_rising_edge_gain", 1.5))
    persistent = max(0.0, pressure - baseline)
    return min(
        1.0,
        persistent_scale * persistent * (1.0 - 0.75 * exposure)
        + rising_edge_gain * rising_edge,
    )


def step_politics(
    society,
    cfg: dict,
    rng: random.Random,
    relationships: Optional[dict[str, list[str]]] = None,
) -> None:
    """推进一个 tick 的政治更新（三轴独立 + 弱耦合）。"""
    agents = society.agents

    pol = cfg.get("politics", {})
    damping = pol.get("damping", 0.92)
    max_movement = pol.get("max_movement_per_tick", 0.03)
    extremism_threshold = pol.get("extremism_threshold", 0.7)
    params = make_force_params(cfg)
    build_breakdown = (society.clock.tick % 10 == 0)

    for a in agents:
        if not a.alive:
            continue

        # ---- 1. 统一力计算（Axis Force Registry） ------------------------
        pressure = _resource_pressure(a)
        pressure_signal = _adapted_resource_pressure(
            a, pressure, getattr(society.clock, "dt_days", 0.01), pol)
        (tx, ty, tz), breakdown = compute_forces(a, society, params, rng, pressure_signal, build_breakdown)

        # ---- 2. 目标 = 当前位置 + 总力（裁剪到 [-1,1]） -------------------
        target_x = max(-1.0, min(1.0, a.ideology.x + tx))
        target_y = max(-1.0, min(1.0, a.ideology.y + ty))
        target_z = max(-1.0, min(1.0, a.ideology.z + tz))

        # ---- 3. 惯性 + 阻尼更新（内联，§4, §5） --------------------------
        inertia = a.political_inertia
        mf = 1.0 - max(0.0, min(1.0, inertia))
        vx = a.political_velocity[0] * damping + (target_x - a.ideology.x) * mf
        vy = a.political_velocity[1] * damping + (target_y - a.ideology.y) * mf
        vz = a.political_velocity[2] * damping + (target_z - a.ideology.z) * mf
        if vx > max_movement:
            vx = max_movement
        elif vx < -max_movement:
            vx = -max_movement
        if vy > max_movement:
            vy = max_movement
        elif vy < -max_movement:
            vy = -max_movement
        if vz > max_movement:
            vz = max_movement
        elif vz < -max_movement:
            vz = -max_movement
        a.ideology.x += vx
        a.ideology.y += vy
        a.ideology.z += vz
        a.political_velocity[0] = vx
        a.political_velocity[1] = vy
        a.political_velocity[2] = vz

        # ---- 4. 极端化代价（§7）：社会摩擦 + 轻微去极端化（非强制） --------
        ext = extremism(a.ideology.x, a.ideology.y, a.ideology.z)
        a.status["extremism"] = ext
        if ext > extremism_threshold:
            friction = (ext - extremism_threshold) / (1.0 - extremism_threshold)
            a.status["social_friction"] = friction
            a.ideology.x += -a.ideology.x * 0.002 * friction
            a.ideology.y += -a.ideology.y * 0.002 * friction
            a.ideology.z += -a.ideology.z * 0.002 * friction
        else:
            a.status["social_friction"] = 0.0

        # ---- 5. 边界裁剪（§36：允许极端，只裁剪数值不重置） -------------
        a.ideology.x = max(-1.0, min(1.0, a.ideology.x))
        a.ideology.y = max(-1.0, min(1.0, a.ideology.y))
        a.ideology.z = max(-1.0, min(1.0, a.ideology.z))

        # ---- 6. 愤怒 / 政府信任：惯性平滑，避免瞬间锁死 ------------------
        target_anger = 0.15 + pressure * 0.7
        a.status["anger"] += (target_anger - a.status["anger"]) * (1.0 - inertia) * 2.0
        target_trust_gov = 0.5 - a.status["anger"] * 0.5 + a.personality["authority_preference"] * 0.2
        a.status["trust_in_government"] += (target_trust_gov - a.status["trust_in_government"]) * (1.0 - inertia)
        a.status["trust_in_government"] = max(0.0, min(1.0, a.status["trust_in_government"]))

        # ---- 7. 保存力分解（供 Inspector 可解释性 §5, §37） --------------
        if breakdown is not None:
            a.last_forces = {
                "x": {k: round(v, 5) for k, v in breakdown["x"].items()},
                "y": {k: round(v, 5) for k, v in breakdown["y"].items()},
                "z": {k: round(v, 5) for k, v in breakdown["z"].items()},
            }
