"""Politics — 三轴政治动力学。"""

from __future__ import annotations

import random
from typing import Optional

from ..agent.agent import Agent
from ..dynamics.stability import extremism
from .forces import compute_forces, make_force_params, interpret_event, _resource_pressure  # noqa: F401


def _adapted_resource_pressure(agent: Agent, pressure: float, dt_days: float, pol_cfg: Optional[dict] = None) -> float:
    """Turn sustained scarcity into a bounded shock instead of endless drift."""
    status = agent.status
    previous = float(status.get("_political_resource_pressure", pressure))
    rising_edge = max(0.0, pressure - previous)
    exposure = float(status.get("_political_resource_exposure", 0.0))
    exposure += pressure * max(dt_days, 0.0)
    exposure = min(1.0, exposure * 0.999)
    status["_political_resource_pressure"] = pressure
    status["_political_resource_exposure"] = exposure
    pol_cfg = pol_cfg or {}
    baseline = float(pol_cfg.get("resource_pressure_baseline", 0.20))
    persistent_scale = float(pol_cfg.get("resource_pressure_persistent_scale", 0.12))
    rising_edge_gain = float(pol_cfg.get("resource_pressure_rising_edge_gain", 1.5))
    persistent = max(0.0, pressure - baseline)
    return min(1.0, persistent_scale * persistent * (1.0 - 0.75 * exposure) + rising_edge_gain * rising_edge)


def _update_structural_experience(agent: Agent, dt_days: float) -> bool:
    """Turn employment/sector/location changes into durable experience, not noise."""
    signature = (
        getattr(agent, "sector", "unemployed"),
        getattr(agent, "location", "A"),
        getattr(agent, "employer", None),
    )
    previous = agent.status.get("_structural_signature")
    changed = previous is not None and previous != signature
    agent.status["_structural_signature"] = signature

    experience = float(getattr(agent, "structural_experience", 0.0))
    experience *= 0.998 ** max(dt_days, 0.0)
    if changed:
        experience = min(1.0, experience + 0.08)
        agent.structural_change_count = int(getattr(agent, "structural_change_count", 0)) + 1
        current = (agent.ideology.x, agent.ideology.y, agent.ideology.z)
        ax, ay, az = agent.ideology_anchor
        blend = 0.04
        agent.ideology_anchor = (
            ax * (1.0 - blend) + current[0] * blend,
            ay * (1.0 - blend) + current[1] * blend,
            az * (1.0 - blend) + current[2] * blend,
        )
    agent.structural_experience = experience
    return changed


def _social_conformity(agent: Agent) -> float:
    """Per-agent social influence multiplier with bounded reactance."""
    trust = float(agent.personality.get("trust", 0.5))
    openness = float(agent.personality.get("openness", 0.5))
    authority = float(agent.personality.get("authority_preference", 0.5))
    reactance = max(0.0, openness - trust)
    conformity = 0.25 + 0.75 * trust
    conformity -= 0.20 * reactance
    if trust < 0.30 and openness > 0.70 and authority < 0.45:
        conformity -= 0.08
    return max(-0.15, min(1.25, conformity))


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

        _update_structural_experience(a, getattr(society.clock, "dt_days", 0.01))
        pressure = _resource_pressure(a)
        pressure_signal = _adapted_resource_pressure(a, pressure, getattr(society.clock, "dt_days", 0.01), pol)

        base_influence = params.influence_strength
        params.influence_strength = base_influence * _social_conformity(a)
        try:
            (tx, ty, tz), breakdown = compute_forces(a, society, params, rng, pressure_signal, build_breakdown)
        finally:
            params.influence_strength = base_influence

        target_x = max(-1.0, min(1.0, a.ideology.x + tx))
        target_y = max(-1.0, min(1.0, a.ideology.y + ty))
        target_z = max(-1.0, min(1.0, a.ideology.z + tz))

        inertia = a.political_inertia
        mf = 1.0 - max(0.0, min(1.0, inertia))
        vx = a.political_velocity[0] * damping + (target_x - a.ideology.x) * mf
        vy = a.political_velocity[1] * damping + (target_y - a.ideology.y) * mf
        vz = a.political_velocity[2] * damping + (target_z - a.ideology.z) * mf
        vx = max(-max_movement, min(max_movement, vx))
        vy = max(-max_movement, min(max_movement, vy))
        vz = max(-max_movement, min(max_movement, vz))
        a.ideology.x += vx
        a.ideology.y += vy
        a.ideology.z += vz
        a.political_velocity[:] = [vx, vy, vz]

        ext = extremism(a.ideology.x, a.ideology.y, a.ideology.z)
        a.status["extremism"] = ext
        if ext > extremism_threshold:
            friction = (ext - extremism_threshold) / max(1e-9, 1.0 - extremism_threshold)
            a.status["social_friction"] = friction
            a.ideology.x += -a.ideology.x * 0.002 * friction
            a.ideology.y += -a.ideology.y * 0.002 * friction
            a.ideology.z += -a.ideology.z * 0.002 * friction
        else:
            a.status["social_friction"] = 0.0

        a.ideology.x = max(-1.0, min(1.0, a.ideology.x))
        a.ideology.y = max(-1.0, min(1.0, a.ideology.y))
        a.ideology.z = max(-1.0, min(1.0, a.ideology.z))

        target_anger = 0.15 + pressure * 0.7
        a.status["anger"] += (target_anger - a.status["anger"]) * (1.0 - inertia) * 2.0
        target_trust_gov = 0.5 - a.status["anger"] * 0.5 + a.personality["authority_preference"] * 0.2
        a.status["trust_in_government"] += (target_trust_gov - a.status["trust_in_government"]) * (1.0 - inertia)
        a.status["trust_in_government"] = max(0.0, min(1.0, a.status["trust_in_government"]))

        if breakdown is not None:
            a.last_forces = {
                "x": {k: round(v, 5) for k, v in breakdown["x"].items()},
                "y": {k: round(v, 5) for k, v in breakdown["y"].items()},
                "z": {k: round(v, 5) for k, v in breakdown["z"].items()},
                "social_conformity": round(_social_conformity(a), 4),
                "structural_experience": round(a.structural_experience, 4),
            }
