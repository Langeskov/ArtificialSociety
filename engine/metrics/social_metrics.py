"""Social emergence metrics — v0.4 社会涌现指标（§54–§56, §75–§78）。

Group / Identity / Information 的宏观统计，以及 fragmentation / integration /
social_state 诊断。social_state 是诊断分类而非控制器（§54）。
"""

from __future__ import annotations

import math


def group_metrics(society) -> dict:
    """群体指标（§55, §75）。"""
    registry = getattr(society, "groups", None)
    if registry is None:
        return _empty_group()
    groups = registry.active()
    n = len(groups)
    sizes = [g.size() for g in groups]
    cohesions = [g.cohesion for g in groups]
    avg_size = sum(sizes) / n if n else 0.0
    avg_cohesion = sum(cohesions) / n if n else 0.0
    return {
        "group_count": len(registry.groups),
        "active_group_count": n,
        "average_group_size": round(avg_size, 3),
        "group_cohesion": round(avg_cohesion, 4),
        "group_fragmentation": round(_group_fragmentation(groups, society.agents), 4),
        "group_entropy": round(_size_entropy(sizes), 4),
    }


def identity_metrics(society) -> dict:
    """身份指标（§55, §75）。"""
    alive = [a for a in society.agents if a.alive]
    n = len(alive)
    if n == 0:
        return {"identity_strength": 0.0, "belonging": 0.0, "autonomy": 0.0,
                "identity_entropy": 0.0, "multi_membership": 0.0}
    ident_strength = sum(a.identity.social_identity_strength for a in alive) / n
    belonging = sum(a.identity.belonging for a in alive) / n
    autonomy = sum(a.identity.autonomy for a in alive) / n
    multi = sum(1 for a in alive if a.identity.membership_count() >= 2) / n
    return {
        "identity_strength": round(ident_strength, 4),
        "belonging": round(belonging, 4),
        "autonomy": round(autonomy, 4),
        "multi_membership": round(multi, 4),
        "identity_entropy": round(_identity_entropy(alive), 4),
    }


def information_metrics(society) -> dict:
    """信息指标（§55, §75）。"""
    msgs = getattr(society, "information_messages", [])
    rumors = [m for m in msgs if m.content_type == "rumor"]
    reaches = [m.reach for m in msgs if m.reach > 0]
    avg_reach = sum(reaches) / len(reaches) if reaches else 0.0
    cascades = sum(1 for m in msgs if getattr(m, "_cascade_recorded", False))
    return {
        "information_count": len(msgs),
        "rumor_count": len(rumors),
        "information_reach": round(avg_reach, 1),
        "information_cascade_count": cascades,
        "echo_chamber_score": _echo_chamber(society),
        "belief_divergence": round(_belief_divergence(society), 4),
    }


def fragmentation_score(society) -> float:
    """社会碎片化（§76）：群体数 + 群间信任 + 政治距离 + 信息隔离 + 流动。"""
    registry = getattr(society, "groups", None)
    if registry is None:
        return 0.0
    groups = registry.active()
    n = len(groups)
    if n < 2:
        return 0.0
    # 群间平均政治距离（跨组距离越大越碎片化）
    dists = []
    for i in range(n):
        for j in range(i + 1, n):
            dists.append(groups[i].political_distance_to(groups[j]))
    avg_dist = sum(dists) / len(dists) if dists else 0.0
    # 群间信任（越低越碎片化）
    avg_trust = sum(g.trust for g in groups) / n
    fragmentation = (avg_dist / 3.0) * 0.5 + (1.0 - avg_trust) * 0.5
    return round(max(0.0, min(1.0, fragmentation)), 4)


def integration_score(society) -> float:
    """社会整合（§77）：跨群互动 + 信任 + 共享事件（不等于 1 - fragmentation）。"""
    registry = getattr(society, "groups", None)
    if registry is None:
        return 0.0
    groups = registry.active()
    if not groups:
        return 1.0
    network = getattr(society, "_network", None) or {}
    # 跨群互动占比
    cross = 0
    internal = 0
    for g in groups:
        for mid in g.members:
            for nid in network.get(mid, []):
                if nid in g.members:
                    internal += 1
                else:
                    cross += 1
    total = cross + internal
    cross_ratio = cross / total if total else 0.0
    avg_trust = sum(g.trust for g in groups) / len(groups)
    return round(max(0.0, min(1.0, cross_ratio * 0.6 + avg_trust * 0.4)), 4)


def classify_social_state(society, metrics: dict | None = None) -> str:
    """社会状态诊断分类（§54）：NORMAL / TENSION / FRAGMENTATION / CRISIS / RECOVERY / REORGANIZATION。

    诊断而非控制器：不强制切换，只反映当前状态。metrics 可选传入，避免重复计算。
    """
    active_types = {e.type for e in society.events.active()}
    if active_types & {"war", "economic_crisis", "food_shortage"}:
        return "CRISIS"
    if "recovery" in active_types or "food_stabilization" in active_types:
        return "RECOVERY"
    fragmentation = fragmentation_score(society)
    if fragmentation > 0.6:
        return "FRAGMENTATION"
    if metrics is None:
        try:
            metrics = society.metrics()
        except Exception:
            metrics = {}
    temp = metrics.get("social_temperature", 0.0)
    if temp > 0.6:
        return "TENSION"
    return "NORMAL"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _empty_group() -> dict:
    return {"group_count": 0, "active_group_count": 0, "average_group_size": 0.0,
            "group_cohesion": 0.0, "group_fragmentation": 0.0, "group_entropy": 0.0}


def _size_entropy(sizes: list[int]) -> float:
    total = sum(sizes)
    if total <= 0:
        return 0.0
    e = 0.0
    for s in sizes:
        p = s / total
        if p > 0:
            e -= p * math.log(p)
    return e


def _group_fragmentation(groups: list, agents: list) -> float:
    """群体碎片化：成员分布越分散（小群多）越碎片化。"""
    alive = [a for a in agents if a.alive]
    n = len(alive)
    if n == 0 or not groups:
        return 0.0
    in_group = set()
    for g in groups:
        in_group |= g.members
    # 未入群比例 + 小群数量占比
    unaffiliated = 1.0 - len(in_group) / n
    small = sum(1 for g in groups if g.size() <= 5) / max(1, len(groups))
    return max(0.0, min(1.0, unaffiliated * 0.5 + small * 0.5))


def _identity_entropy(alive: list) -> float:
    """身份熵：成员分布越均匀熵越高。"""
    counts: dict[str, int] = {}
    for a in alive:
        gid = a.identity.primary_group or "unaffiliated"
        counts[gid] = counts.get(gid, 0) + 1
    return _size_entropy(list(counts.values()))


def _echo_chamber(society) -> float:
    from ..information.propagation import echo_chamber_score
    return echo_chamber_score(society)


def _belief_divergence(society) -> float:
    """信念分歧（§75）：同一主题下 Agent 信念的方差。"""
    subjects: dict[str, list[float]] = {}
    for a in society.agents:
        if not a.alive:
            continue
        for subj, b in getattr(a, "beliefs", {}).items():
            subjects.setdefault(subj, []).append(b.belief_strength)
    if not subjects:
        return 0.0
    variances = []
    for vals in subjects.values():
        if len(vals) < 2:
            continue
        mean = sum(vals) / len(vals)
        variances.append(sum((v - mean) ** 2 for v in vals) / len(vals))
    if not variances:
        return 0.0
    return sum(variances) / len(variances)
