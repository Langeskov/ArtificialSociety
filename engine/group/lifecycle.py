"""Group lifecycle — cohesion 更新、合并、分裂、解散（v0.4 §10–§12, §23）。

cohesion 不能简化为政治距离（§23）：由 trust、interaction、shared events、
identity strength、resource cooperation、political similarity 共同决定。
"""

from __future__ import annotations

import random

from .group import Group, GROUP_STATE
from .formation import recenter


def update_cohesion(g: Group, agent_map: dict, network: dict) -> float:
    """重算凝聚力（§23）：政治相似 + 信任 + 身份强度 + 内部互动密度。"""
    ms = [agent_map.get(mid) for mid in g.members]
    ms = [m for m in ms if m is not None and m.alive]
    n = len(ms)
    if n < 2:
        g.cohesion = 0.2
        return g.cohesion

    recenter(g, agent_map)
    # 政治相似度：内部方差越小越相似
    pol_sim = max(0.0, 1.0 - (g.variance_x + g.variance_y + g.variance_z) / 1.5)
    trust = sum(m.personality["trust"] for m in ms) / n
    ident = sum(getattr(m.identity, "social_identity_strength", 0.0) for m in ms) / n
    # 内部互动密度（组内边 / 可能边）
    internal = 0
    for m in ms:
        for nid in network.get(m.id, []):
            if nid in g.members:
                internal += 1
    density = internal / (n * (n - 1)) if n > 1 else 0.0

    g.cohesion = max(0.0, min(1.0, 0.4 * pol_sim + 0.2 * trust + 0.2 * ident + 0.2 * min(1.0, density * 3.0)))
    g.trust = trust
    return g.cohesion


def step_lifecycle(society, cfg: dict, rng: random.Random) -> list[dict]:
    """推进所有 Group 的生命周期：合并、分裂、解散（§10–§12）。返回生命周期事件列表。"""
    gcfg = cfg.get("groups", {})
    dissolve_cohesion = gcfg.get("dissolve", {}).get("cohesion_threshold", 0.25)
    dissolve_ticks = gcfg.get("dissolve", {}).get("persistence_ticks", 15)
    split_variance = gcfg.get("split", {}).get("variance_threshold", 0.35)
    split_cohesion = gcfg.get("split", {}).get("cohesion_threshold", 0.45)
    merge_distance = gcfg.get("merge", {}).get("distance_threshold", 0.45)

    registry = getattr(society, "groups", None)
    if registry is None:
        return []
    agent_map = society.agent_map()
    network = getattr(society, "_network", None) or {}

    events: list[dict] = []
    for g in registry.active():
        g.age += 1
        update_cohesion(g, agent_map, network)
        # FORMING → ACTIVE（经过一段稳定期）
        if g.state == GROUP_STATE.FORMING and g.age >= 10:
            g.state = GROUP_STATE.ACTIVE

        # --- 解散（§12）：凝聚力/信任持续低于阈值 --------------------------
        if g.cohesion < dissolve_cohesion:
            g.low_cohesion_ticks += 1
        else:
            g.low_cohesion_ticks = 0
        if g.low_cohesion_ticks >= dissolve_ticks:
            _dissolve(g, registry, agent_map, society.clock.tick)
            events.append({"type": "GROUP_DISSOLVED", "group_id": g.id, "tick": society.clock.tick})
            continue

        # --- 分裂（§11）：内部政治方差高 + 凝聚力低 ------------------------
        max_var = max(g.variance_x, g.variance_y, g.variance_z)
        if g.state == GROUP_STATE.ACTIVE and max_var > split_variance and g.cohesion < split_cohesion and g.size() >= 6:
            _split(g, registry, agent_map, society.clock.tick)
            events.append({"type": "GROUP_SPLIT", "group_id": g.id, "tick": society.clock.tick})

    # --- 合并（§10）：政治距离近 + 存在互动 ---------------------------------
    _merge_close_groups(registry, agent_map, network, merge_distance, society.clock.tick, events)

    return events


def _dissolve(g: Group, registry, agent_map: dict, tick: int) -> None:
    g.state = GROUP_STATE.DISSOLVED
    registry.record("GROUP_DISSOLVED", group_id=g.id, tick=tick, size=g.size())
    for mid in g.members:
        m = agent_map.get(mid)
        if m is not None:
            m.identity.remove_group(g.id)


def _split(g: Group, registry, agent_map: dict, tick: int) -> None:
    """沿方差最大的轴把成员分成两派（§11）。"""
    ms = [agent_map.get(mid) for mid in g.members]
    ms = [m for m in ms if m is not None and m.alive]
    axis = max(range(3), key=lambda i: (g.variance_x, g.variance_y, g.variance_z)[i])
    getter = [lambda m: m.ideology.x, lambda m: m.ideology.y, lambda m: m.ideology.z][axis]
    ms.sort(key=getter)
    half = len(ms) // 2
    a_members = {m.id for m in ms[:half]}
    b_members = {m.id for m in ms[half:]}

    # 原组保留一派，另一派成为新组
    g.members = a_members
    g.state = GROUP_STATE.ACTIVE
    for mid in b_members:
        agent_map[mid].identity.remove_group(g.id)

    new_g = Group(id=registry.new_id(), created_tick=tick, state=GROUP_STATE.ACTIVE, members=b_members)
    registry.add(new_g)
    for mid in b_members:
        agent_map[mid].identity.add_group(new_g.id)

    registry.record("GROUP_SPLIT", group_id=g.id, new_group_id=new_g.id, tick=tick, axis=axis)
    recenter(g, agent_map)
    recenter(new_g, agent_map)


def _merge_close_groups(registry, agent_map: dict, network: dict, distance_threshold: float, tick: int, events: list) -> None:
    """合并政治距离近且有跨组互动的 Group（§10）。"""
    active = registry.active()
    if len(active) < 2:
        return
    # 找距离最近的一对
    best = None
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a, b = active[i], active[j]
            d = a.political_distance_to(b)
            if d < distance_threshold:
                cross = _cross_interaction(a, b, network)
                if best is None or (d < best[0]):
                    best = (d, a, b, cross)
    if best is None:
        return
    _, a, b, cross = best
    # 合并（小组合并到大组，或随机）
    if a.size() >= b.size():
        keep, gone = a, b
    else:
        keep, gone = b, a
    keep.members |= gone.members
    keep.state = GROUP_STATE.ACTIVE
    for mid in gone.members:
        agent_map[mid].identity.remove_group(gone.id)
        agent_map[mid].identity.add_group(keep.id)
    gone.state = GROUP_STATE.DISSOLVED
    registry.record("GROUP_MERGED", group_id=keep.id, merged_group_id=gone.id, tick=tick, size=keep.size())
    events.append({"type": "GROUP_MERGED", "group_id": keep.id, "merged_group_id": gone.id, "tick": tick})
    recenter(keep, agent_map)


def _cross_interaction(a: Group, b: Group, network: dict) -> int:
    """两个 Group 之间的跨组互动边数（§10 merge 信号）。"""
    cross = 0
    for mid in a.members:
        for nid in network.get(mid, []):
            if nid in b.members:
                cross += 1
    return cross
