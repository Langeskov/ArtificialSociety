"""Event Engine — v0.2 重构 (§10–§18, §30).

关键变化：
  * 事件拥有生命周期（duration/decay），不再是永久状态；
  * 抗议是临时的，并产生临时生产/流动性代价（§12），随后恢复（§13）；
  * 社会温度只调节事件「概率」，不制造硬阈值（§18）；
  * 危机解决后产生恢复型事件（negative feedback），形成 CAUSE→EFFECT→REACTION→RECOVERY 链。
"""

from __future__ import annotations

import random
from typing import Optional, Sequence

from ..agent.agent import Agent
from ..metrics.metrics import compute_social_temperature
from .event import Event, EventChain


# Recovery notifications are useful in the causal graph, but are not new
# shocks.  They must not be allowed to push political coordinates again.
RECOVERY_EVENT_TYPES = {"recovery", "food_stabilization"}


# 事件类型 → 生命周期时长（tick）
DURATION: dict[str, int] = {
    "food_shortage": 40,
    "economic_crisis": 60,
    "protest": 20,
    "political_movement": 30,
    "government_response": 15,
    "natural_disaster": 30,
    "war": 60,
    "conflict": 40,
    "scandal": 15,
    "resource_boom": 30,
    "technology_breakthrough": 30,
    "alliance": 40,
    "market_panic": 20,
    "unemployment": 40,
    "migration": 40,
    "election": 15,
    "leadership_change": 20,
    "reform": 25,
    "recovery": 20,
    "food_stabilization": 20,
    "economic_recovery": 25,
}

TYPE_LABEL = {
    "natural_disaster": "自然灾害",
    "technology_breakthrough": "技术突破",
    "resource_boom": "资源繁荣",
    "scandal": "丑闻",
    "protest": "抗议",
    "economic_crisis": "经济危机",
    "food_shortage": "粮食短缺",
    "political_movement": "政治运动",
    "government_response": "政府应对",
    "conflict": "冲突",
    "war": "战争",
    "alliance": "结盟",
    "market_panic": "市场恐慌",
    "unemployment": "失业上升",
    "migration": "迁移",
    "election": "选举",
    "leadership_change": "领导更替",
    "reform": "改革",
    "recovery": "恢复",
    "food_stabilization": "粮食企稳",
    "economic_recovery": "经济恢复",
}


def _temp_modifier(temperature: float) -> float:
    """把社会温度映射为事件概率倍率（§18）：低温 → 0，高温 → 放大。"""
    if temperature < 0.30:
        return 0.0
    if temperature > 0.90:
        return 3.0
    return (temperature - 0.30) / 0.60 * 3.0


def _has_active(chain: EventChain, event_type: str) -> bool:
    return any(e.type == event_type and e.is_active for e in chain.events)


def _has_recent(chain: EventChain, event_type: str, tick: int, window: int) -> bool:
    """Whether a notification of this type was emitted recently."""
    return any(e.type == event_type and tick - e.tick <= window for e in chain.events)


def _economic_pressure(agents: Sequence[Agent]) -> float:
    """Resource-only economic stress signal.

    Do not use social_temperature here: temperature already contains
    polarization, conflict history, and protest outcomes. Feeding it back as
    the economic-crisis trigger creates a politics → crisis → politics loop.
    """
    if not agents:
        return 0.0
    broke = sum(1 for a in agents if a.resources.is_broke()) / len(agents)
    hungry = sum(1 for a in agents if a.resources.is_starving()) / len(agents)
    wealth = sorted(max(0.0, a.wealth()) for a in agents)
    if len(wealth) < 2 or wealth[-1] <= 0.0:
        inequality = 0.0
    else:
        n = len(wealth)
        total = sum(wealth)
        weighted = sum((i + 1) * value for i, value in enumerate(wealth))
        inequality = max(0.0, min(1.0, (2.0 * weighted) / (n * total) - (n + 1) / n))
    return max(0.0, min(1.0, 0.45 * broke + 0.25 * hungry + 0.30 * inequality))


def _apply_effects(society, event: Event, agents: Sequence[Agent], rng: random.Random) -> None:
    """事件的实际后果（v0.4.2 §19: 临时干扰而非永久 ratchet）。"""
    et = event.type
    sev = max(0.2, event.severity)
    if et == "natural_disaster":
        society.production_disruption = min(0.5, getattr(society, "production_disruption", 0.0) + 0.2 * sev)
        for a in agents:
            if a.alive:
                a.resources.add("food", -a.resources.values.get("food", 0.0) * 0.85 * sev)
    elif et == "economic_crisis":
        society.production_disruption = min(0.4, getattr(society, "production_disruption", 0.0) + 0.15 * sev)
        for a in agents:
            if a.alive:
                a.resources.add("money", -a.resources.values.get("money", 0.0) * 0.2 * sev)
    elif et == "war":
        society.production_disruption = min(0.5, getattr(society, "production_disruption", 0.0) + 0.25 * sev)
        for a in agents:
            if a.alive:
                a.resources.add("food", -a.resources.values.get("food", 0.0) * 0.2 * sev)
    elif et == "conflict":
        society.production_disruption = min(0.3, getattr(society, "production_disruption", 0.0) + 0.1 * sev)
    elif et == "resource_boom":
        for a in agents:
            if a.alive:
                a.resources.add("money", a.resources.values.get("money", 0.0) * 0.15 * sev)
    elif et == "technology_breakthrough":
        # 技术突破：临时提升生产效率
        society.production_disruption = max(-0.2, getattr(society, "production_disruption", 0.0) - 0.1 * sev)


def step_events(society, cfg: dict, rng: random.Random, resolved: Optional[list] = None) -> list:
    """检测并产生新事件（带生命周期）。返回新创建的事件列表。"""
    ev = cfg.get("events", {})
    frequency = ev.get("frequency", 0.02)
    default_duration = ev.get("default_duration", 20)

    agents = [a for a in society.agents if a.alive]
    if not agents:
        return []

    tick = society.clock.tick
    chain: EventChain = society.events
    new_events: list[Event] = []

    # 社会温度（§18）：只调节概率，不制造硬阈值
    temperature = compute_social_temperature(agents, chain, cfg)
    modifier = _temp_modifier(temperature)

    # --- 粮食短缺（v0.4.2 §14–§16: 使用 CrisisManager 的状态机） ---
    starving = sum(1 for a in agents if a.resources.is_starving())
    starving_ratio = starving / len(agents) if len(agents) > 0 else 0.0
    cm = getattr(society, "crisis_manager", None)
    if cm is not None:
        previous_food_state = cm.food.state
        cm.food.update(starving_ratio, tick, cfg.get("ticks_per_day", 100))
        # A lifecycle expiry is not proof of recovery.  Emit one causal
        # notification only when the tracker itself reaches COOLDOWN.
        if (previous_food_state.name == "RECOVERING"
                and cm.food.state.name == "COOLDOWN"
                and not _has_recent(chain, "food_stabilization", tick,
                                    int(2 * cfg.get("ticks_per_day", 100)))):
            cause = next((e for e in reversed(chain.events)
                          if e.type in ("food_shortage", "economic_crisis")), None)
            new_events.append(chain.make(
                tick, "food_stabilization", severity=0.4,
                description="粮食供给重新企稳",
                cause_event_id=cause.event_id if cause else None,
                duration=DURATION["food_stabilization"], intensity=0.4))
        # 只在状态转换时产生事件（不是每 tick 检查阈值）
        if cm.food.state.value == "ACTIVE" and cm.food.duration_ticks == 1:
            new_events.append(chain.make(
                tick, "food_shortage",
                severity=min(1.0, starving_ratio),
                description=f"粮食短缺：{starving}/{len(agents)} 名成员处于饥饿状态",
                effects={"starving_ratio": round(starving_ratio, 3)},
                duration=DURATION["food_shortage"],
            ))
    else:
        # fallback: 旧逻辑
        if starving_ratio > 0.25 and not _has_active(chain, "food_shortage") and rng.random() < 0.15 + starving_ratio * 0.5:
            new_events.append(chain.make(
                tick, "food_shortage",
                severity=min(1.0, starving_ratio),
                description=f"粮食短缺：{starving}/{len(agents)} 名成员处于饥饿状态",
                effects={"starving_ratio": round(starving_ratio, 3)},
                duration=DURATION["food_shortage"],
            ))

    # --- 经济危机（有状态的稀有事件） --------------------------------------
    # v0.4.4: 原实现每 tick 以随机概率检查，经济危机没有自己的
    # persistence/hysteresis/cooldown，容易在高温阶段反复生成。
    if cm is not None:
        previous_state = cm.economic.state
        economic_pressure = _economic_pressure(agents)
        cm.economic.update(economic_pressure, tick, cfg.get("ticks_per_day", 100))
        if (cm.economic.state.value == "ACTIVE"
                and cm.economic.duration_ticks == 1
                and not _has_active(chain, "economic_crisis")):
            crisis = chain.make(
                tick, "economic_crisis",
                severity=max(0.2, economic_pressure),
                description="高不平等与经济压力引发的经济危机",
                duration=DURATION["economic_crisis"],
            )
            new_events.append(crisis)
            _apply_effects(society, crisis, agents, rng)
    elif not _has_active(chain, "economic_crisis") and temperature > 0.5 and rng.random() < 0.01 * modifier:
        # 兼容没有 CrisisManager 的轻量测试桩。
        crisis = chain.make(tick, "economic_crisis", severity=temperature,
                            description="高不平等与经济压力引发的经济危机",
                            duration=DURATION["economic_crisis"])
        new_events.append(crisis)
        _apply_effects(society, crisis, agents, rng)

    # --- 抗议（§12：临时，产生生产代价） -----------------------------------
    # v0.4.2: 使用 CrisisManager 状态机 + 临时干扰
    protest_ratio = 0.0
    if cm is not None:
        # 计算抗议比例（基于 anger + 低信任）
        angry_ratio = sum(1 for a in agents if a.status.get("anger", 0.0) > 0.3) / max(len(agents), 1)
        protest_ratio = angry_ratio
        previous_protest_state = cm.protest.state
        cm.protest.update(angry_ratio, tick, cfg.get("ticks_per_day", 100))
        if cm.protest.state.value == "ACTIVE" and cm.protest.duration_ticks == 1:
            new_events.append(chain.make(
                tick, "protest",
                severity=temperature,
                description="不满情绪上升引发公众抗议",
                duration=rng.randint(10, 30),
            ))
            # v0.4.2 §19: 临时干扰而非永久 ratchet
            society.production_disruption = min(0.4, getattr(society, "production_disruption", 0.0) + 0.08)
        elif (previous_protest_state.name == "RECOVERING"
              and cm.protest.state.name == "COOLDOWN"
              and not _has_recent(chain, "recovery", tick,
                                  int(2 * cfg.get("ticks_per_day", 100)))):
            cause = next((e for e in reversed(chain.events)
                          if e.type == "protest"), None)
            new_events.append(chain.make(
                tick, "recovery", severity=0.4,
                description="抗议平息，生产逐步恢复",
                cause_event_id=cause.event_id if cause else None,
                duration=DURATION["recovery"], intensity=0.4))
    else:
        # fallback: 旧逻辑
        if not _has_active(chain, "protest") and temperature > 0.45:
            p = 0.01 * modifier
            if rng.random() < p:
                new_events.append(chain.make(
                    tick, "protest",
                    severity=temperature,
                    description="不满情绪上升引发公众抗议",
                    duration=rng.randint(10, 30),
                ))
                society.production_disruption = min(0.4, getattr(society, "production_disruption", 0.0) + 0.08)

    # --- 政治运动（当存在长期不满但尚无运动时） ----------------------------
    if not _has_active(chain, "political_movement") and temperature > 0.4 and rng.random() < 0.005 * modifier:
        new_events.append(chain.make(
            tick, "political_movement",
            severity=temperature,
            description="一场政治运动开始组织起来",
            duration=DURATION["political_movement"],
        ))

    # --- 外生冲击（罕见，但会产生真实后果） --------------------------------
    if rng.random() < frequency * 0.15:
        shock_type = rng.choice(["natural_disaster", "technology_breakthrough", "resource_boom", "scandal"])
        shock = chain.make(
            tick, shock_type,
            severity=rng.random(),
            description=f"外生冲击：{TYPE_LABEL.get(shock_type, shock_type)}",
            duration=DURATION.get(shock_type, default_duration),
        )
        new_events.append(shock)
        _apply_effects(society, shock, agents, rng)

    # --- 政府应对（对危机的反应，形成因果链 §30） --------------------------
    for e in new_events:
        if e.type in ("protest", "economic_crisis", "food_shortage"):
            if rng.random() < 0.6:
                chain.make(
                    tick + rng.randint(1, 5), "government_response",
                    severity=e.severity * 0.7,
                    description=f"政府针对「{TYPE_LABEL.get(e.type, e.type)}」作出应对",
                    cause_event_id=e.event_id,
                    duration=DURATION["government_response"],
                    intensity=e.severity * 0.7,
                )

    return new_events

