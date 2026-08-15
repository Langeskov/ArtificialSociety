"""Information propagation — Event → Information → Belief（v0.4 §25–§39）。

核心分离（§26）：Event（客观）≠ Information（传播中的信息）≠ Belief（主观信念）。

传播（§30, §31）：Source → Relationship → Group → Individual → Next relationship。
    P(receive) = base_spread × relationship_strength × source_trust × salience × group_modifier
失真（§32）、谣言（§33）、信念更新（§34, §35）、级联（§36）、回音室（§37）。
"""

from __future__ import annotations

import random
from typing import Optional

from .message import Information
from .belief import Belief, update_belief
from ..event.event import Event

# 事件类型 → (信念主题, 主张值方向)
EVENT_BELIEF = {
    "food_shortage": ("government_caused_crisis", 0.7),
    "economic_crisis": ("government_caused_crisis", 0.6),
    "market_panic": ("government_caused_crisis", 0.4),
    "scandal": ("government_corrupt", 0.6),
    "government_response": ("government_is_competent", 0.4),
    "reform": ("government_is_competent", 0.3),
    "recovery": ("government_is_competent", 0.3),
    "food_stabilization": ("government_is_competent", 0.3),
    "war": ("society_in_conflict", 0.7),
    "conflict": ("society_in_conflict", 0.6),
    "protest": ("public_discontent", 0.5),
    "unemployment": ("government_caused_crisis", 0.4),
    "natural_disaster": ("society_under_threat", 0.3),
    "leadership_change": ("government_is_competent", 0.2),
}

_NEUTRAL_SUBJECT = "general_condition"


def _belief_subject(event_type: str) -> tuple[str, float]:
    return EVENT_BELIEF.get(event_type, (_NEUTRAL_SUBJECT, 0.2))


def _group_id_of(agent) -> Optional[str]:
    ident = getattr(agent, "identity", None)
    if ident is None:
        return None
    return ident.primary_group


def _group_modifier(receiver, source_agent, cfg: dict) -> float:
    """群内/群外信息接受度调制（§24, §38）：同组 → 提升，异组 → 抑制。"""
    gcfg = cfg.get("information", {})
    ingroup_boost = gcfg.get("ingroup_boost", 1.3)
    outgroup_penalty = gcfg.get("outgroup_penalty", 0.6)
    rg = _group_id_of(receiver)
    sg = _group_id_of(source_agent)
    if rg is None or sg is None:
        return 1.0
    if rg == sg:
        return ingroup_boost
    return outgroup_penalty


def _learn_event(agent, event: Event, memory_size: int, knowers: set) -> None:
    """Agent 获悉事件（保留 v0.3.1 的 recent_events 机制，供 politics 使用）。"""
    if event.event_id in agent.known_events:
        return
    agent.known_events[event.event_id] = event.tick
    knowers.add(agent.id)
    agent.recent_events.append({
        "event_id": event.event_id,
        "type": event.type,
        "tick": event.tick,
        "strength": max(0.1, event.intensity),
    })
    if len(agent.recent_events) > memory_size:
        agent.recent_events = agent.recent_events[-memory_size:]


def _ensure_information_stores(society) -> None:
    if not hasattr(society, "information_messages"):
        society.information_messages = []
    if not hasattr(society, "_info_counter"):
        society._info_counter = 0


def step_information(society, cfg: dict, rng: random.Random, new_events: list[Event]) -> list[Information]:
    """推进一个 tick 的信息传播（§25–§39）。返回新创建/新级联的 Information。"""
    soc = cfg.get("social", {})
    icfg = cfg.get("information", {})
    base_spread = soc.get("information_spread", 0.10)
    information_delay = soc.get("information_delay", 3)
    memory_size = soc.get("memory_size", 20)
    distortion_rate = icfg.get("distortion_rate", 0.02)
    rumor_threshold = icfg.get("rumor_threshold", 0.35)

    network = getattr(society, "_network", None)
    if not network:
        return []
    agent_map = society.agent_map()
    _ensure_information_stores(society)

    if not hasattr(society, "_knowers"):
        society._knowers = {}

    agents = [a for a in society.agents if a.alive]
    n_alive = len(agents)
    if n_alive == 0:
        return []

    created: list[Information] = []

    # 1. 新事件 → Information（事实，§26）
    for e in new_events:
        subject, claim = _belief_subject(e.type)
        info = Information(
            id=f"info_{society._info_counter:05d}",
            source="system",
            event_id=e.event_id,
            created_tick=e.tick,
            content_type="fact",
            salience=max(0.1, e.intensity),
            reliability=0.9,
            subject=subject,
            claim=claim * max(0.1, e.severity),
        )
        society._info_counter += 1
        society.information_messages.append(info)
        created.append(info)
        # 播种：影响力最高的少数 Agent 先得知
        seeds = sorted(agents, key=lambda a: a.resources.values.get("influence", 0.0), reverse=True)[:10]
        for a in seeds:
            info.recipients.append(a.id)
            _learn_event(a, e, memory_size, society._knowers.setdefault(e.event_id, set()))

    # 2. 传播既有 Information（frontier 方式：每个接收者只传播一次，避免 O(N·degree·messages)）
    for info in society.information_messages:
        if getattr(info, "_propagated", None) is None:
            info._propagated = set()
        if len(info.recipients) >= n_alive:
            continue
        # 信息延迟：事件发生 information_delay tick 后才开始扩散
        if info.created_tick is not None and (society.clock.tick - info.created_tick) < information_delay:
            continue
        # 只传播尚未传播过的接收者（frontier）
        frontier = sorted(rid for rid in info.recipients if rid not in info._propagated)
        for rid in frontier:
            info._propagated.add(rid)
            a = agent_map.get(rid)
            if a is None or not a.alive:
                continue
            for nid in network.get(rid, []):
                nb = agent_map.get(nid)
                if nb is None or not nb.alive or nid in info.recipients:
                    continue
                p_recv = base_spread * a.personality["trust"] * info.salience
                p_recv *= _group_modifier(nb, a, cfg)
                if rng.random() < p_recv:
                    # 失真（§32）：传播中可靠性下降、主张漂移
                    info.reliability = max(0.1, info.reliability * (1.0 - distortion_rate))
                    info.distortion += distortion_rate
                    info.claim = max(-1.0, min(1.0, info.claim + rng.uniform(-1, 1) * distortion_rate))
                    info.recipients.append(nid)
                    info.reach = len(info.recipients)
                    info.propagation_chain.append((rid, nid))
                    # 信念更新（§34, §35）
                    _update_agent_belief(nb, info, a, cfg, society.clock.tick)
                    # 无法验证 + 来源信任低 + 显著性高 → 谣言（§33）
                    # 每条信息只派生一条谣言，谣言不再派生谣言，避免无限爆炸
                    if (info.content_type != "rumor" and not getattr(info, "_rumor_spawned", False)
                            and info.reliability < rumor_threshold and nb.personality["trust"] < 0.4
                            and info.salience > 0.6):
                        info._rumor_spawned = True
                        _spawn_rumor(society, info, nb, rng, cfg)

    # 3. 级联检测（§36）：触达人数快速增长
    cascades = _detect_cascades(society, cfg)
    created.extend(cascades)

    # 限制消息总量，避免无界增长拖慢传播扫描
    MAX_INFO = 500
    if len(society.information_messages) > MAX_INFO:
        society.information_messages = society.information_messages[-MAX_INFO:]

    return created


def _update_agent_belief(agent, info: Information, source_agent, cfg: dict, tick: int) -> None:
    """接收信息后更新信念（§34, §35）：受来源信任、开放度（反 confirmation bias）调制。"""
    beliefs = getattr(agent, "beliefs", None)
    if beliefs is None:
        agent.beliefs = {}
        beliefs = agent.beliefs
    b = beliefs.get(info.subject)
    if b is None:
        b = Belief(subject=info.subject)
        beliefs[info.subject] = b
    source_trust = _source_trust(agent, source_agent, info)
    update_belief(b, info.claim, info.reliability, source_trust, agent.personality["openness"], tick)


def _source_trust(agent, source_agent, info: Information) -> float:
    """来源信任（§29）：朋友/同组高、异组低、未知中等。"""
    if source_agent is None:
        return 0.6
    trust = agent.personality["trust"]
    gm = _group_modifier(agent, source_agent, {})
    return max(0.1, min(1.0, trust * gm))


def _spawn_rumor(society, info: Information, agent, rng: random.Random, cfg: dict) -> None:
    """从无法验证的高显著性信息生成谣言（§33）。"""
    _ensure_information_stores(society)
    rumor = Information(
        id=f"info_{society._info_counter:05d}",
        source=agent.id,
        event_id=info.event_id,
        created_tick=society.clock.tick,
        content_type="rumor",
        salience=info.salience,
        reliability=max(0.1, info.reliability * 0.5),
        subject=info.subject,
        claim=info.claim,
    )
    society._info_counter += 1
    society.information_messages.append(rumor)
    # 谣言同样沿网络传播（失真更大）
    for nid in getattr(society, "_network", {}).get(agent.id, []):
        nb = society.agent_map().get(nid)
        if nb is not None and rng.random() < 0.3:
            rumor.recipients.append(nid)


def _detect_cascades(society, cfg: dict) -> list[Information]:
    """信息级联检测（§36）：短时间内大量 Agent 接受相同信念。"""
    icfg = cfg.get("information", {})
    cascade_ratio = icfg.get("cascade_ratio", 0.25)
    n_alive = max(1, sum(1 for a in society.agents if a.alive))
    cascades = []
    for info in society.information_messages:
        if info.reach >= n_alive * cascade_ratio and not getattr(info, "_cascade_recorded", False):
            info._cascade_recorded = True
            society.events.make(
                society.clock.tick, "political_movement",
                source=info.id,
                severity=0.6,
                description=f"信息级联：{info.subject} 信息触达 {info.reach} 名 Agent",
                duration=20,
                intensity=0.6,
            )
            cascades.append(info)
    return cascades


def echo_chamber_score(society) -> float:
    """回音室分数（§37）：高信任 + 高群体身份 + 组内信息隔离。"""
    registry = getattr(society, "groups", None)
    if registry is None:
        return 0.0
    groups = registry.active()
    if not groups:
        return 0.0
    # 组内信息同质性：成员信念方差越低 → 回音室越强
    scores = []
    for g in groups:
        members = [society.agent_map().get(mid) for mid in g.members]
        members = [m for m in members if m is not None and m.alive]
        if len(members) < 2:
            continue
        beliefs = []
        for m in members:
            for b in getattr(m, "beliefs", {}).values():
                beliefs.append(b.belief_strength)
        if not beliefs:
            continue
        mean = sum(beliefs) / len(beliefs)
        var = sum((b - mean) ** 2 for b in beliefs) / len(beliefs)
        segregation = max(0.0, 1.0 - var * 3.0)
        scores.append(g.cohesion * g.trust * segregation)
    if not scores:
        return 0.0
    return round(max(0.0, min(1.0, sum(scores) / len(scores))), 4)
