"""Decay — 事件生命周期衰减与记忆衰减 (§10, §11, §21).

事件不能是永久状态：每个事件拥有 intensity/duration/age/decay_rate，随 tick
自然衰减到 RESOLVED。Agent 记忆同样随 tick 衰减，越久远的事件影响越弱。
"""

from __future__ import annotations

from typing import Optional

from ..event.event import EventChain, EVENT_STATUS


def decay_events(chain: EventChain, cfg: dict) -> list:
    """推进所有活跃事件的生命周期：age += 1，越过 peak 后强度按 decay_rate 衰减。

    只衰减 TRIGGERED/GROWING/PEAK/DECAYING 状态的事件；RESOLVED 不再改变。
    返回本 tick 新进入 RESOLVED 状态的事件列表（用于产生恢复型事件）。
    """
    ev = cfg.get("events", {})
    decay_rate = ev.get("decay_rate", 0.03)
    resolution_threshold = ev.get("resolution_threshold", 0.05)
    resolved = []

    for e in chain.events:
        if e.status == EVENT_STATUS.RESOLVED:
            continue
        e.age += 1

        if e.status == EVENT_STATUS.TRIGGERED:
            e.status = EVENT_STATUS.GROWING
        elif e.status == EVENT_STATUS.GROWING:
            # 生长阶段：强度向 max_intensity 爬升
            e.intensity = min(e.max_intensity, e.intensity + 0.05)
            if e.age >= e.duration * 0.4 or e.intensity >= e.max_intensity:
                e.status = EVENT_STATUS.PEAK
        elif e.status in (EVENT_STATUS.PEAK, EVENT_STATUS.DECAYING):
            e.status = EVENT_STATUS.DECAYING
            e.intensity -= decay_rate
            if e.intensity <= resolution_threshold:
                e.intensity = 0.0
                e.status = EVENT_STATUS.RESOLVED
                resolved.append(e)
    return resolved


def decay_memory(agent, memory_decay: float, memory_size: int) -> None:
    """衰减 Agent 近期事件记忆的强度，并裁剪到 memory_size 条。"""
    for m in agent.recent_events:
        m["strength"] *= memory_decay
    # 移除已基本失效的记忆
    agent.recent_events = [
        m for m in agent.recent_events if m.get("strength", 0.0) > 0.02
    ]
    if len(agent.recent_events) > memory_size:
        agent.recent_events = agent.recent_events[-memory_size:]
