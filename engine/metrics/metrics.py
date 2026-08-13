"""Macro social metrics (§21, §25) — 包括 v0.2 新增的稳定性指标。

新增：social_temperature（§17）、political diversity / variance（§24）、
agent synchronization、boundary concentration（§27）、event persistence、
system stability、resource recovery rate。
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Sequence

from ..agent.agent import Agent
from ..dynamics.stability import boundary_concentration as _boundary_concentration
from ..politics.observability import (  # noqa: F401
    polarization_per_axis,
    axis_correlation,
    detect_axis_dominance,
)


def _gini(values: list[float]) -> float:
    """Gini coefficient, O(n log n)."""
    n = len(values)
    if n == 0:
        return 0.0
    v = sorted(values)
    s = sum(v)
    if s == 0:
        return 0.0
    weighted = sum((i + 1) * x for i, x in enumerate(v))
    gini = (2.0 * weighted) / (n * s) - (n + 1) / n
    return max(0.0, min(1.0, gini))


def _variance(values: Sequence[float]) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    mean = sum(values) / n
    return sum((x - mean) ** 2 for x in values) / n


def _std(values: Sequence[float]) -> float:
    return math.sqrt(_variance(values))


def _polarization_pairwise(agents: Sequence[Agent], sample_size: int = 300) -> float:
    """Mean pairwise ideological distance over a fixed sample, normalized to [0,1]."""
    n = len(agents)
    if n == 0:
        return 0.0
    step = max(1, n // sample_size)
    sample = agents[::step][:sample_size]
    m = len(sample)
    if m < 2:
        return 0.0
    total = 0.0
    pairs = 0
    for i in range(m):
        ai = sample[i].ideology
        for j in range(i + 1, m):
            aj = sample[j].ideology
            dx = ai.x - aj.x
            dy = ai.y - aj.y
            dz = ai.z - aj.z
            total += math.sqrt(dx * dx + dy * dy + dz * dz)
            pairs += 1
    return (total / pairs) / (2.0 * math.sqrt(3.0))


def _agent_synchronization(agents: Sequence[Agent]) -> float:
    """平均单位速度向量的模长：0 = 各方向随机，1 = 全体同步漂移 (§24)."""
    sx = sy = sz = 0.0
    count = 0
    for a in agents:
        vx, vy, vz = a.political_velocity
        mag = math.sqrt(vx * vx + vy * vy + vz * vz)
        if mag < 1e-6:
            continue
        sx += vx / mag
        sy += vy / mag
        sz += vz / mag
        count += 1
    if count == 0:
        return 0.0
    mx, my, mz = sx / count, sy / count, sz / count
    return math.sqrt(mx * mx + my * my + mz * mz)


def compute_social_temperature(
    agents: Sequence[Agent], events, cfg: dict | None = None
) -> float:
    """社会温度（§17）：资源短缺 + 不平等 + 冲突 + 极化 + 失业 − 信任，clamp [0,1]。"""
    alive = [a for a in agents if a.alive]
    n = len(alive)
    if n == 0:
        return 0.0

    starving = sum(1 for a in alive if a.resources.is_starving())
    shortage = starving / n

    inequality = _gini([a.wealth() for a in alive])

    # 极化用方差代理（便宜）：三轴 std 归一化
    std_x = _std([a.ideology.x for a in alive])
    std_y = _std([a.ideology.y for a in alive])
    std_z = _std([a.ideology.z for a in alive])
    polarization = (std_x + std_y + std_z) / 3.0 / 0.577

    broke = sum(1 for a in alive if a.resources.is_broke())
    unemployment = broke / n

    recent = events.recent(200)
    conflict_types = {"conflict", "war", "protest", "scandal"}
    conflict = sum(1 for e in recent if e.type in conflict_types) / max(len(recent), 1)

    trust = sum(a.personality["trust"] for a in alive) / n

    temp = (
        shortage * 0.25
        + inequality * 0.20
        + conflict * 0.20
        + polarization * 0.20
        + unemployment * 0.10
        - trust * 0.15
    )
    return max(0.0, min(1.0, temp))


def compute_metrics(agents: Sequence[Agent], events, tick: int, cfg: dict | None = None) -> dict:
    alive = [a for a in agents if a.alive]
    n = len(alive)
    if n == 0:
        base = {
            "tick": tick, "population": 0, "average_wealth": 0.0, "median_wealth": 0.0,
            "resource_inequality": 0.0, "political_polarization": 0.0, "political_entropy": 0.0,
            "social_trust": 0.0, "conflict_rate": 0.0, "cooperation_rate": 0.0,
            "faction_count": 0, "government_stability": 0.0, "average_anger": 0.0,
            "social_temperature": 0.0, "political_diversity": 0.0,
            "political_variance_x": 0.0, "political_variance_y": 0.0, "political_variance_z": 0.0,
            "agent_synchronization": 0.0, "boundary_concentration": 0.0,
            "event_persistence": 0.0, "system_stability": 1.0, "resource_recovery_rate": 0.0,
            "feedback_positive": 0, "feedback_negative": 0,
        }
        return base

    wealth = [a.wealth() for a in alive]
    wealth_sorted = sorted(wealth)
    median = wealth_sorted[n // 2]
    avg_wealth = sum(wealth) / n

    # Political variance / diversity (§24)
    xs = [a.ideology.x for a in alive]
    ys = [a.ideology.y for a in alive]
    zs = [a.ideology.z for a in alive]
    var_x = _variance(xs)
    var_y = _variance(ys)
    var_z = _variance(zs)
    diversity = (math.sqrt(var_x) + math.sqrt(var_y) + math.sqrt(var_z)) / 3.0 / 0.577

    # Political entropy over origin labels
    label_counts = Counter(a.ideology.origin_label for a in alive)
    entropy = 0.0
    for c in label_counts.values():
        p = c / n
        if p > 0:
            entropy -= p * math.log(p)
    k = max(len(label_counts), 1)
    max_entropy = math.log(k) if k > 1 else 1.0
    political_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

    trust = sum(a.personality["trust"] for a in alive) / n
    anger = sum(a.status.get("anger", 0.0) for a in alive) / n
    gov_trust = sum(a.status.get("trust_in_government", 0.5) for a in alive) / n

    recent = events.recent(200)
    conflict_types = {"conflict", "war", "protest", "scandal"}
    cooperation_types = {"alliance", "resource_boom", "technology_breakthrough", "recovery", "food_stabilization"}
    conflict_n = sum(1 for e in recent if e.type in conflict_types)
    coop_n = sum(1 for e in recent if e.type in cooperation_types)
    denom = max(len(recent), 1)
    conflict_rate = conflict_n / denom
    cooperation_rate = coop_n / denom

    # Event persistence (§25): active events / total events
    active = events.active()
    event_persistence = len(active) / max(len(events.events), 1)

    # Boundary concentration (§27): max boundary ratio
    bc = _boundary_concentration(alive, threshold=0.95)
    boundary = max(bc.values()) if bc else 0.0

    # Feedback summary (§31)
    from ..dynamics.feedback import summarize as _feedback_summarize
    fb = _feedback_summarize(events)

    # System stability: inverse of temperature
    temperature = compute_social_temperature(alive, events, cfg)
    system_stability = 1.0 - temperature

    # v0.3: per-axis polarization / correlation / dominance (§12, §15, §16)
    pol = polarization_per_axis(alive)
    corr = axis_correlation(alive)
    dominance = detect_axis_dominance(alive, cfg.get("stability", {}).get("collapse_variance_threshold", 0.02))

    return {
        "tick": tick,
        "population": n,
        "average_wealth": round(avg_wealth, 2),
        "median_wealth": round(median, 2),
        "resource_inequality": round(_gini(wealth), 4),
        "political_polarization": round(_polarization_pairwise(alive), 4),
        "political_entropy": round(political_entropy, 4),
        "social_trust": round(trust, 4),
        "conflict_rate": round(conflict_rate, 4),
        "cooperation_rate": round(cooperation_rate, 4),
        "faction_count": len(label_counts),
        "government_stability": round(gov_trust, 4),
        "average_anger": round(anger, 4),
        # v0.2 stability metrics
        "social_temperature": round(temperature, 4),
        "political_diversity": round(diversity, 4),
        "political_variance_x": round(var_x, 6),
        "political_variance_y": round(var_y, 6),
        "political_variance_z": round(var_z, 6),
        "agent_synchronization": round(_agent_synchronization(alive), 4),
        "boundary_concentration": round(boundary, 4),
        "event_persistence": round(event_persistence, 4),
        "system_stability": round(system_stability, 4),
        "resource_recovery_rate": round(1.0 - event_persistence, 4),  # proxy: events resolving
        "feedback_positive": fb["positive"],
        "feedback_negative": fb["negative"],
        # v0.3 observability metrics (§12, §15, §16)
        "x_polarization": pol["x_polarization"],
        "y_polarization": pol["y_polarization"],
        "z_polarization": pol["z_polarization"],
        "polarization_3d": pol["polarization_3d"],
        "x_bimodality": pol["x_bimodality"],
        "y_bimodality": pol["y_bimodality"],
        "z_bimodality": pol["z_bimodality"],
        "axis_correlation_xy": corr["xy"],
        "axis_correlation_xz": corr["xz"],
        "axis_correlation_yz": corr["yz"],
        "axis_dominance": dominance,
    }
