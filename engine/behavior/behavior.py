"""Behavior → Event — Agent 行为产生事件的反向闭环（v0.4 §40–§44）。

当前系统只有 Event → Agent；v0.4 增加 Agent → Behavior → Event。第一版用
rule-based 行为选择（§41），不需要复杂规划。行为聚合为微事件，微事件升级为
宏观事件（§44）：behavior → micro event → macro event。
"""

from __future__ import annotations

import random
from typing import Optional

from ..agent.agent import Agent


def _select_behavior(a: Agent, society, cfg: dict, rng: random.Random) -> str:
    """规则式行为选择（§41, §42）：按资源/愤怒/群体/信息状态选最合理行为。"""
    p = a.personality
    anger = a.status.get("anger", 0.0)
    trust_gov = a.status.get("trust_in_government", 0.5)
    starving = a.resources.is_starving()
    broke = a.resources.is_broke()

    # 生存优先：饥饿/破产 → 工作或迁移
    if starving or broke:
        if rng.random() < p["risk_tolerance"] * 0.5:
            return "migrate"
        return "work"

    # 愤怒 + 低政府信任 → 抗议
    if anger > 0.6 and trust_gov < 0.4 and rng.random() < anger * 0.3:
        return "protest"

    # 群体成员 + 高凝聚力 → 合作；跨群体紧张 → 冲突
    ident = getattr(a, "identity", None)
    if ident is not None and ident.membership_count() > 0:
        if rng.random() < 0.4:
            return "cooperate"

    # 资源不平衡 → 交易
    money = a.resources.values.get("money", 0.0)
    food = a.resources.values.get("food", 0.0)
    if money > 600 and food < 40:
        return "trade"
    if food > 80 and money < 200:
        return "trade"

    # 默认工作
    return "work"


def step_behavior(society, cfg: dict, rng: random.Random) -> list[dict]:
    """推进行为：选择 + 执行 + 聚合为事件（§41–§44）。返回产生的微事件列表。"""
    bcfg = cfg.get("behavior", {})
    protest_event_threshold = bcfg.get("protest_threshold", 0.10)   # 抗议人数占比
    conflict_event_threshold = bcfg.get("conflict_threshold", 0.05)
    migration_event_threshold = bcfg.get("migration_threshold", 0.08)

    agents = [a for a in society.agents if a.alive]
    n_alive = len(agents)
    if n_alive == 0:
        return []

    registry = getattr(society, "groups", None)
    agent_map = society.agent_map()

    protests = 0
    conflicts = 0
    migrations = 0
    micro_events: list[dict] = []

    for a in agents:
        action = _select_behavior(a, society, cfg, rng)
        if action == "work":
            a.resources.add("money", 1.0)
        elif action == "trade":
            _do_trade(a, society, rng, agent_map)
        elif action == "cooperate":
            a.status["anger"] = max(0.0, a.status.get("anger", 0.0) - 0.02)
            a.status["trust_in_government"] = min(1.0, a.status.get("trust_in_government", 0.5) + 0.005)
        elif action == "protest":
            protests += 1
            a.status["anger"] = max(0.0, a.status.get("anger", 0.0) - 0.1)   # 宣泄
        elif action == "migrate":
            migrations += 1
            _do_migrate(a, society, cfg, rng)
        # conflict 行为由跨群体张力在下方聚合触发

    # 跨群体冲突（§50, §78）：随机采样群体对，低信任 → 冲突
    conflicts += _inter_group_conflict(society, registry, agent_map, rng, cfg)

    # 聚合为宏观事件（§44）
    if n_alive > 0 and protests / n_alive >= protest_event_threshold and not _has_active(society, "protest"):
        micro_events.append(_emit(society, "protest", source="behavior", severity=0.6,
                                  description=f"行为涌现：{protests} 名 Agent 参与抗议"))
        society.production_multiplier = max(0.5, society.production_multiplier - 0.1)
    if n_alive > 0 and conflicts / n_alive >= conflict_event_threshold and not _has_active(society, "conflict"):
        micro_events.append(_emit(society, "conflict", source="behavior", severity=0.5,
                                  description=f"行为涌现：群体间冲突 {conflicts} 起"))
    if n_alive > 0 and migrations / n_alive >= migration_event_threshold and not _has_active(society, "migration"):
        micro_events.append(_emit(society, "migration", source="behavior", severity=0.4,
                                  description=f"行为涌现：{migrations} 名 Agent 迁移"))

    return micro_events


def _do_trade(a: Agent, society, rng: random.Random, agent_map: dict) -> None:
    network = getattr(society, "_network", None) or {}
    nbrs = network.get(a.id, [])
    if not nbrs:
        return
    nid = rng.choice(nbrs)
    b = agent_map.get(nid)
    if b is None or not b.alive:
        return
    # 食物换钱
    a.resources.add("food", -5.0)
    a.resources.add("money", 5.0)
    b.resources.add("food", 5.0)
    b.resources.add("money", -5.0)


def _do_migrate(a: Agent, society, cfg: dict, rng: random.Random) -> None:
    """Agent 迁移到另一个 region（§47）。"""
    regions = cfg.get("regions", {}).get("list", ["A", "B", "C"])
    cur = getattr(a, "location", "A")
    others = [r for r in regions if r != cur]
    if others:
        a.location = rng.choice(others)


def _inter_group_conflict(society, registry, agent_map: dict, rng: random.Random, cfg: dict) -> int:
    """跨群体冲突（§50, §78）：低信任群体对之间采样冲突。"""
    if registry is None:
        return 0
    groups = registry.active()
    if len(groups) < 2:
        return 0
    conflicts = 0
    # 采样若干群体对（避免 O(G²) 全量）
    for i in range(min(len(groups) - 1, 3)):
        a_g = groups[i]
        for j in range(i + 1, min(len(groups), i + 3)):
            b_g = groups[j]
            if a_g.trust < 0.35 and b_g.trust < 0.35 and rng.random() < 0.1:
                conflicts += 1
                a_g.trust = max(0.1, a_g.trust - 0.02)
                b_g.trust = max(0.1, b_g.trust - 0.02)
    return conflicts


def _has_active(society, event_type: str) -> bool:
    return any(e.type == event_type and e.is_active for e in society.events.events)


def _emit(society, event_type: str, source: str, severity: float, description: str):
    """产生宏观事件，返回 Event 对象（供信息传播继续使用）。"""
    ev = society.events.make(
        society.clock.tick, event_type,
        source=source,
        severity=severity,
        description=description,
        duration=20,
        intensity=severity,
    )
    return ev
