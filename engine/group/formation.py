"""Group formation — 群体由行为自然涌现（v0.4 §5–§9）。

formation_score（§7）：
    political_similarity × interaction_strength × trust × shared_experience × belonging

必须归一化、必须连续满足 N ticks 才形成（§8），不得单条件触发（§7），不得 O(N²)
全对比较（§69）——只沿关系网络邻域计算。
"""

from __future__ import annotations

import random
from typing import Optional

from .group import Group, GROUP_STATE
from ..agent.agent import Agent


def _clamp01(x: float, floor: float = 0.0) -> float:
    return max(floor, min(1.0, x))


def formation_score(agent: Agent, network: dict, agent_map: dict, avg_degree: float) -> float:
    """计算单个 Agent 的群体形成得分（§7）。各因子归一化到 [0,1]。"""
    nbrs = network.get(agent.id, [])
    live = [agent_map.get(nid) for nid in nbrs]
    live = [b for b in live if b is not None and b.alive]
    n = len(live)
    if n == 0:
        return 0.0

    ix, iy, iz = agent.ideology.x, agent.ideology.y, agent.ideology.z
    total_dist = 0.0
    total_shared = 0.0
    total_trust = 0.0
    for b in live:
        d2 = (ix - b.ideology.x) ** 2 + (iy - b.ideology.y) ** 2 + (iz - b.ideology.z) ** 2
        total_dist += d2 ** 0.5
        shared = len(set(agent.known_events).intersection(b.known_events))
        total_shared += shared
        total_trust += b.personality["trust"]

    avg_dist = total_dist / n
    # 政治相似度：距离 0 → 1，距离 2.5 → 0
    political_sim = _clamp01(1.0 - avg_dist / 2.5, floor=0.05)
    # 互动强度：邻居数 / 平均度
    interaction = _clamp01(n / max(1.0, avg_degree), floor=0.1)
    # 信任
    trust = _clamp01(agent.personality["trust"], floor=0.1)
    # 共享经验（事件重叠 + 邻居信任），floor 避免冷启动永不形成
    shared_exp = _clamp01(total_shared / (n * 4.0), floor=0.3)
    # 归属感（来自 identity，§15）
    belonging = _clamp01(getattr(agent.identity, "belonging", 0.5), floor=0.3)

    # 归一化（§7）：乘积的几何平均，保持 [0,1] 且可达（纯乘积会趋近 0）
    product = political_sim * interaction * trust * shared_exp * belonging
    return product ** (1.0 / 5.0)


def step_formation(society, cfg: dict, rng: random.Random) -> list[Group]:
    """推进群体形成：计算得分 → 累积持久性 → 满足条件则成组（§8, §9）。"""
    gcfg = cfg.get("groups", {})
    threshold = gcfg.get("formation", {}).get("threshold", 0.65)
    persistence_ticks = gcfg.get("formation", {}).get("persistence_ticks", 20)
    min_size = gcfg.get("min_size", 3)
    max_size = gcfg.get("max_size", 200)
    avg_degree = cfg.get("relationships", {}).get("avg_degree", 6)

    network = getattr(society, "_network", None)
    if not network:
        return []
    agent_map = society.agent_map()
    registry = getattr(society, "groups", None)
    if registry is None:
        return []

    if not hasattr(society, "_formation_counter"):
        society._formation_counter = {}   # agent_id -> 连续满足 tick 数

    counter = society._formation_counter
    seeds: list[Agent] = []

    for a in society.agents:
        if not a.alive:
            continue
        # 已在组中的 Agent 不再作为种子（可加入新组，但先由现有组吸收）
        if a.identity and a.identity.membership_count() >= 2:
            counter.pop(a.id, None)
            continue
        score = formation_score(a, network, agent_map, avg_degree)
        if score >= threshold:
            counter[a.id] = counter.get(a.id, 0) + 1
            if counter[a.id] >= persistence_ticks:
                seeds.append(a)
        else:
            counter.pop(a.id, None)

    new_groups: list[Group] = []
    # 限制每 tick 成组数量，避免一次性爆发（§8）
    for seed in seeds[: max(1, len(seeds) // 4)]:
        if seed.identity and seed.identity.membership_count() >= 1:
            continue
        members = _gather_members(seed, network, agent_map, rng, min_size, max_size)
        if len(members) < min_size:
            continue
        g = _create_group(registry, society.clock.tick, members, agent_map)
        new_groups.append(g)

    return new_groups


def _gather_members(seed: Agent, network: dict, agent_map: dict, rng: random.Random,
                    min_size: int, max_size: int) -> list[Agent]:
    """以种子为中心，收集政治相近且未入其他组的邻居组成 Group（§9）。"""
    members = [seed]
    nbrs = network.get(seed.id, [])
    candidates = []
    for nid in nbrs:
        nb = agent_map.get(nid)
        if nb is None or not nb.alive or nb is seed:
            continue
        if nb.identity and nb.identity.membership_count() >= 1:
            continue
        d = seed.ideology.distance(nb.ideology)
        candidates.append((d, nb))
    candidates.sort(key=lambda t: t[0])
    for _, nb in candidates:
        if len(members) >= max_size:
            break
        members.append(nb)
    return members


def _create_group(registry, tick: int, members: list[Agent], agent_map: dict) -> Group:
    gid = registry.new_id()
    g = Group(id=gid, created_tick=tick, state=GROUP_STATE.FORMING, members={m.id for m in members})
    _recenter(g, agent_map)
    registry.add(g)
    registry.record("GROUP_FORMED", group_id=gid, tick=tick, size=g.size())
    for m in members:
        m.identity.add_group(gid)
    return g


def recenter(g: Group, agent_map: dict) -> None:
    """根据成员当前政治位置重算 group 中心与内部方差（§22）。"""
    _recenter(g, agent_map)


def _recenter(g: Group, agent_map: dict) -> None:
    ms = [agent_map.get(mid) for mid in g.members]
    ms = [m for m in ms if m is not None and m.alive]
    n = len(ms)
    if n == 0:
        return
    cx = sum(m.ideology.x for m in ms) / n
    cy = sum(m.ideology.y for m in ms) / n
    cz = sum(m.ideology.z for m in ms) / n
    g.center_x, g.center_y, g.center_z = cx, cy, cz
    g.variance_x = sum((m.ideology.x - cx) ** 2 for m in ms) / n
    g.variance_y = sum((m.ideology.y - cy) ** 2 for m in ms) / n
    g.variance_z = sum((m.ideology.z - cz) ** 2 for m in ms) / n
