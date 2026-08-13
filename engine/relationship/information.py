"""Information propagation — 事件信息沿社会网络传播，带延迟 (§19, §20).

事件发生后不会瞬间被所有 Agent 知晓。信息沿关系网络扩散，接收概率：
    P(receive) = information_spread × trust × visibility

Agent 得知事件后写入 recent_events（记忆），记忆强度随事件强度初始化，
随后由 decay.memory 逐 tick 衰减。
"""

from __future__ import annotations

import random
from typing import Optional


def _learn(agent, event, knowers: set, memory_size: int) -> None:
    """Agent 获悉事件：记录已知 + 写入记忆。"""
    if event.event_id in agent.known_events:
        return
    agent.known_events[event.event_id] = event.tick
    knowers.add(agent.id)
    agent.recent_events.append({
        "event_id": event.event_id,
        "type": event.type,
        "tick": event.tick,
        "strength": max(0.1, event.intensity),  # 初始记忆强度 = 事件强度
    })
    if len(agent.recent_events) > memory_size:
        agent.recent_events = agent.recent_events[-memory_size:]


def propagate_information(society, cfg: dict, rng: random.Random) -> None:
    """推进一个 tick 的信息传播：播种新事件 + 沿网络扩散。"""
    soc = cfg.get("social", {})
    information_spread = soc.get("information_spread", 0.10)
    information_delay = soc.get("information_delay", 3)
    memory_size = soc.get("memory_size", 20)

    network = getattr(society, "_network", None)
    if not network:
        return

    if not hasattr(society, "_knowers"):
        society._knowers = {}

    agents = [a for a in society.agents if a.alive]
    n_alive = len(agents)
    if n_alive == 0:
        return
    agent_map = society.agent_map()

    for e in society.events.active():
        # 信息传播延迟：事件发生 information_delay tick 后才开始传播
        if e.age < information_delay:
            continue
        knowers = society._knowers.setdefault(e.event_id, set())

        # 播种：若尚无人知晓，让最有影响力的少数 Agent 先得知
        if not knowers:
            seeds = sorted(agents, key=lambda a: a.resources.values.get("influence", 0.0),
                           reverse=True)[:10]
            for a in seeds:
                _learn(a, e, knowers, memory_size)
            if not knowers:  # 兜底
                for a in agents[:5]:
                    _learn(a, e, knowers, memory_size)

        # 扩散：已知者把信息传给邻居（按 id 排序迭代，保证确定性 §33）
        if len(knowers) >= n_alive:
            continue
        for aid in sorted(knowers):
            a = agent_map.get(aid)
            if a is None:
                continue
            for nid in network.get(aid, []):
                nb = agent_map.get(nid)
                if nb is None or not nb.alive:
                    continue
                if e.event_id in nb.known_events:
                    continue
                p_recv = information_spread * a.personality["trust"]
                if rng.random() < p_recv:
                    _learn(nb, e, knowers, memory_size)
