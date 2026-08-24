"""Behavior → Event 反向闭环（v0.4 §40–§44 → v0.4.1 §9–§20 重构）。

v0.4.1 将 rule-based 硬阈值行为升级为 Action System：
  候选行为 → 可行性（§12）→ 效用（§13）→ 概率选择 → 成本结算（§60）→ 执行。

资源不再是行为「读取的状态变量」，而是「约束可行动空间」的真实约束：
  - 行为有成本（§1）：work 耗能、migrate 耗钱耗能；
  - 交易/迁移/分享必须通过 Transaction Layer（§8），守恒（§61）；
  - 工作产出与 productivity 相关（§14）。
"""

from __future__ import annotations

import random
from typing import Optional

from ..agent.agent import Agent
from ..economy.transaction import reserve, commit, release, transfer
from .actions import default_actions
from .utility import compute_feasibility, compute_utility, select_action


def _build_ctx(society, cfg: dict) -> dict:
    return {
        "society": society,
        "cfg": cfg,
        "agent_map": society.agent_map(),
        "network": getattr(society, "_network", {}) or {},
        "groups": getattr(society, "groups", None),
    }


def step_behavior(society, cfg: dict, rng: random.Random) -> list:
    """推进行为：候选→选择→成本结算→执行→聚合为事件（§9–§14, §44）。"""
    bcfg = cfg.get("behavior", {})
    protest_event_threshold = bcfg.get("protest_threshold", 0.10)
    conflict_event_threshold = bcfg.get("conflict_threshold", 0.05)
    migration_event_threshold = bcfg.get("migration_threshold", 0.08)

    agents = [a for a in society.agents if a.alive]
    n_alive = len(agents)
    if n_alive == 0:
        return []

    actions = default_actions(cfg)
    ctx = _build_ctx(society, cfg)
    ctx["food_price"] = _food_price(ctx)  # §20 价格每 tick 计算一次，而非每次交易重算全局均值
    ledger = getattr(society, "resource_ledger", None)
    tick = society.clock.tick

    # v0.4.3 §1: 职业分配（每天更新一次）
    from ..economy.occupation import choose_occupation
    if tick % cfg.get("ticks_per_day", 100) == 0:
        regions = getattr(society, "regions", None)
        for a in agents:
            region = regions.get(getattr(a, "location", "A")) if regions else None
            a.occupation = choose_occupation(a, region, cfg).value

    counters = {"protest": 0, "conflict": 0, "migrate": 0, "trade": 0,
                "share": 0, "hoard": 0, "work": 0, "cooperate": 0}
    micro_events: list = []

    for a in agents:
        sel = select_action(a, actions, ctx, rng)
        if sel is None:
            a.current_action = ""
            continue
        act, u, f = sel
        # 记录选择（Inspector §46：Agent 为什么做这个行为）——直接复用 select_action 的评估结果
        a.current_action = act.name
        a.action_utility = round(u, 4)
        a.action_feasibility = round(f, 4)
        _execute(a, act, ctx, rng, ledger, tick, counters)

    # 跨群体冲突（§50, §78）
    counters["conflict"] += _inter_group_conflict(society, ctx["groups"], ctx["agent_map"], rng, cfg)

    # 聚合为宏观事件（§44）
    # v0.4.4: behavior-level aggregation must share the CrisisTracker with
    # step_events.  Previously the two producers could emit independent
    # protests in adjacent ticks, bypassing persistence/cooldown and adding
    # repeated production shocks.
    crisis_manager = getattr(society, "crisis_manager", None)
    protest_tracker = getattr(crisis_manager, "protest", None)
    protest_gate_open = protest_tracker is None or protest_tracker.state.value == "NORMAL"
    if (n_alive > 0 and counters["protest"] / n_alive >= protest_event_threshold
            and not _has_active(society, "protest") and protest_gate_open):
        micro_events.append(_emit(society, "protest", source="behavior", severity=0.6,
                                  description=f"行为涌现：{counters['protest']} 名 Agent 参与抗议"))
        # v0.4.2 §19: 使用临时干扰而非永久 ratchet
        # 原: society.production_multiplier = max(0.5, pm - 0.1)
        # 新: 累加临时干扰，由 step_production_recovery 自动衰减
        society.production_disruption = min(0.4, getattr(society, "production_disruption", 0.0) + 0.08)
    if n_alive > 0 and counters["conflict"] / n_alive >= conflict_event_threshold and not _has_active(society, "conflict"):
        micro_events.append(_emit(society, "conflict", source="behavior", severity=0.5,
                                  description=f"行为涌现：群体间冲突 {counters['conflict']} 起"))
    if n_alive > 0 and counters["migrate"] / n_alive >= migration_event_threshold and not _has_active(society, "migration"):
        micro_events.append(_emit(society, "migration", source="behavior", severity=0.4,
                                  description=f"行为涌现：{counters['migrate']} 名 Agent 迁移"))

    return micro_events


def _execute(a: Agent, act, ctx: dict, rng: random.Random, ledger, tick: int, counters: dict) -> None:
    """执行单个行为：先 reserve 成本，成功后 commit；具体效果按 action 分发（§59, §60）。"""
    # 1. 成本预扣（§60）
    reserved: dict = {}
    for res, amt in act.cost.items():
        if amt <= 0:
            continue
        if not reserve(a, res, amt):
            for r2, a2 in reserved.items():
                release(a, r2, a2)
            return
        reserved[res] = amt
    # 2. 成本结算
    for res, amt in reserved.items():
        commit(a, res, amt, ledger, f"action:{act.name}", tick)

    # 3. 具体效果
    name = act.name
    if name == "work":
        _do_work(a, ctx, ledger, tick)
        counters["work"] += 1
    elif name == "trade":
        if _do_trade(a, ctx, rng, ledger, tick):
            counters["trade"] += 1
    elif name == "save":
        _do_save(a, ctx, ledger, tick)
        counters["hoard"] += 1
    elif name == "consume":
        _do_consume(a, ctx, ledger, tick)
    elif name == "share":
        if _do_share(a, ctx, rng, ledger, tick):
            counters["share"] += 1
    elif name == "cooperate":
        a.status["anger"] = max(0.0, a.status.get("anger", 0.0) - 0.02)
        a.status["trust_in_government"] = min(1.0, a.status.get("trust_in_government", 0.5) + 0.005)
        counters["cooperate"] += 1
    elif name == "protest":
        a.status["anger"] = max(0.0, a.status.get("anger", 0.0) - 0.1)
        counters["protest"] += 1
    elif name == "migrate":
        if _do_migrate(a, ctx, rng):
            counters["migrate"] += 1
    elif name == "rest":
        a.resources.add("energy", act.expected_return.get("energy", 5.0))
    elif name == "join_group":
        _do_join_group(a, ctx, rng)
    elif name == "leave_group":
        _do_leave_group(a, ctx, tick)
    elif name == "communicate":
        pass  # 信息传播由 information 层处理（§29）


# -- 各 action 的具体实现 ------------------------------------------------

def _apply_completion(a: Agent, act_state, ctx: dict, rng: random.Random,
                      ledger, tick: int, counters: dict) -> None:
    """v0.4.3: 动作完成时应用结果。Production = rate × hours."""
    action_name = act_state.current_action
    if action_name is None:
        return
    hours = act_state.hours_committed

    # 临时设置 current_action 以复用现有逻辑
    old_action = a.current_action
    a.current_action = action_name

    if action_name == "work":
        _do_work_hourly(a, ctx, ledger, tick, hours)
        counters["work"] += 1
    elif action_name == "trade":
        if _do_trade(a, ctx, rng, ledger, tick):
            counters["trade"] += 1
    elif action_name == "save":
        _do_save(a, ctx, ledger, tick)
        counters["hoard"] += 1
    elif action_name == "consume":
        _do_consume(a, ctx, ledger, tick)
    elif action_name == "share":
        if _do_share(a, ctx, rng, ledger, tick):
            counters["share"] += 1
    elif action_name == "cooperate":
        a.status["anger"] = max(0.0, a.status.get("anger", 0.0) - 0.02)
        a.status["trust_in_government"] = min(1.0, a.status.get("trust_in_government", 0.5) + 0.005)
        counters["cooperate"] += 1
    elif action_name == "protest":
        a.status["anger"] = max(0.0, a.status.get("anger", 0.0) - 0.1)
        counters["protest"] += 1
    elif action_name == "migrate":
        if _do_migrate(a, ctx, rng):
            counters["migrate"] += 1
    elif action_name == "rest":
        a.resources.add("energy", 5.0 * (hours / 8.0))  # 按比例恢复
    elif action_name == "join_group":
        _do_join_group(a, ctx, rng)
    elif action_name == "leave_group":
        _do_leave_group(a, ctx, tick)
    elif action_name == "communicate":
        pass

    a.current_action = old_action


def _execute_cost(a: Agent, act, ctx: dict, rng: random.Random,
                  ledger, tick: int, counters: dict) -> None:
    """v0.4.3: 动作启动时预扣成本（能量、金钱等）。"""
    for res, amt in act.cost.items():
        if amt <= 0:
            continue
        if not reserve(a, res, amt):
            # 成本不足，动作无法启动
            return
        commit(a, res, amt, ledger, f"action:{act.name}", tick)


def _do_work_hourly(a: Agent, ctx: dict, ledger, tick: int, hours: float) -> None:
    """v0.4.3 §7: 按小时生产，不是 per-action batch。

    production = rate_per_hour × effective_hours × productivity × inputs
    """
    from ..economy.occupation import get_production_multipliers, OccupationType

    econ = ctx["cfg"].get("economy", {})
    pm = getattr(ctx["society"], "production_multiplier", 1.0)
    disruption = getattr(ctx["society"], "production_disruption", 0.0)
    effective_pm = max(0.3, pm - disruption)

    base_productivity = 0.5 + a.personality["conscientiousness"] * 0.5
    a.productivity = base_productivity

    # 生产投入因子
    prop = a.resources.available("property")
    property_factor = max(0.3, min(1.0, (prop / 20.0) ** 0.5))
    energy = a.resources.available("energy")
    energy_factor = max(0.3, min(1.0, energy / 10.0))

    # 区域加成
    region_bonus = 1.0
    regions = getattr(ctx["society"], "regions", None)
    if regions:
        loc = getattr(a, "location", "A")
        region = regions.get(loc)
        if region:
            endow = ctx["cfg"].get("regions", {}).get("endowments", {}).get(loc, {})
            region_bonus = 0.7 + 0.3 * endow.get("food", 1.0)

    # 职业生产乘数
    occ = getattr(a, "occupation", "farmer")
    try:
        occ_type = OccupationType(occ)
    except ValueError:
        occ_type = OccupationType.FARMER
    occ_mult = get_production_multipliers(occ_type)

    input_factor = property_factor * energy_factor * region_bonus

    # v0.4.3 §7: 按小时计算产出（不是 per-action batch）
    # rate_per_hour × hours × productivity × input × pm
    production_cfg = econ.get("production", {})
    food_rate = production_cfg.get("food", {}).get("per_hour", 0.12)
    energy_rate = production_cfg.get("energy", {}).get("per_hour", 0.02)
    wage_rate = production_cfg.get("money", {}).get("wage_per_hour", 0.60)

    food_prod = food_rate * occ_mult["food"] * hours * base_productivity * input_factor * effective_pm
    energy_prod = energy_rate * occ_mult["energy"] * hours * base_productivity * input_factor * effective_pm
    wage = wage_rate * occ_mult["money"] * hours * base_productivity * input_factor * effective_pm
    prop_prod = 0.005 * occ_mult.get("property", 0.0) * hours * base_productivity * input_factor * effective_pm

    a.resources.add("money", wage)
    a.resources.add("food", food_prod)
    a.resources.add("energy", energy_prod)
    if prop_prod > 0:
        a.resources.add("property", prop_prod)

    if ledger is not None:
        ledger.record(source="production", target=a.id, resource="money",
                      amount=round(wage, 4), reason="work", tick=tick)


def _do_work(a: Agent, ctx: dict, ledger, tick: int) -> None:
    """v0.4.3 §7: hourly production (rate × dt_hours), not per-action batch.

    This ensures time resolution invariance: ticks_per_day=100 and 200
    produce the same total resources per simulated day.
    """
    from ..economy.occupation import get_production_multipliers, OccupationType

    econ = ctx["cfg"].get("economy", {})
    pm = getattr(ctx["society"], "production_multiplier", 1.0)
    disruption = getattr(ctx["society"], "production_disruption", 0.0)
    effective_pm = max(0.3, pm - disruption)

    base_productivity = 0.5 + a.personality["conscientiousness"] * 0.5
    a.productivity = base_productivity

    # v0.4.3 §2: production inputs
    prop = a.resources.available("property")
    property_factor = max(0.3, min(1.0, (prop / 20.0) ** 0.5))
    energy = a.resources.available("energy")
    energy_factor = max(0.3, min(1.0, energy / 10.0))

    # Regional bonus
    region_bonus = 1.0
    regions = getattr(ctx["society"], "regions", None)
    if regions:
        loc = getattr(a, "location", "A")
        region = regions.get(loc)
        if region:
            endow = ctx["cfg"].get("regions", {}).get("endowments", {}).get(loc, {})
            region_bonus = 0.7 + 0.3 * endow.get("food", 1.0)

    # Occupation multipliers
    occ = getattr(a, "occupation", "farmer")
    try:
        occ_type = OccupationType(occ)
    except ValueError:
        occ_type = OccupationType.FARMER
    occ_mult = get_production_multipliers(occ_type)

    input_factor = property_factor * energy_factor * region_bonus

    # v0.4.3 §7: hourly rates × dt_hours (time resolution invariant)
    tpd = ctx["cfg"].get("ticks_per_day", 100)
    dt_hours = 24.0 / tpd  # hours per tick

    production_cfg = econ.get("production", {})
    food_rate = production_cfg.get("food", {}).get("per_hour", 0.12)
    energy_rate = production_cfg.get("energy", {}).get("per_hour", 0.02)
    wage_rate = production_cfg.get("money", {}).get("wage_per_hour", 0.60)

    food_prod = food_rate * occ_mult["food"] * dt_hours * base_productivity * input_factor * effective_pm
    energy_prod = energy_rate * occ_mult["energy"] * dt_hours * base_productivity * input_factor * effective_pm
    wage = wage_rate * occ_mult["money"] * dt_hours * base_productivity * input_factor * effective_pm
    prop_prod = 0.005 * occ_mult.get("property", 0.0) * dt_hours * base_productivity * input_factor * effective_pm

    a.resources.add("money", wage)
    a.resources.add("food", food_prod)
    a.resources.add("energy", energy_prod)
    if prop_prod > 0:
        a.resources.add("property", prop_prod)

    if ledger is not None:
        ledger.record(source="production", target=a.id, resource="money",
                      amount=round(wage, 4), reason="work", tick=tick)

def _do_trade(a: Agent, ctx: dict, rng: random.Random, ledger, tick: int) -> bool:
    """交易（§18–§20）：找 counterparty，按稀缺性定价，守恒转移。"""
    agent_map = ctx["agent_map"]
    nbrs = ctx["network"].get(a.id, [])
    if not nbrs:
        return False
    st = getattr(a, "resource_state", {}) or {}
    price = ctx.get("food_price")
    if price is None:  # 单测直接调用时的回退路径
        price = _food_price(ctx)
    qty = 5.0

    if st.get("food_pressure", 0.0) > 0.5 and a.resources.available("money") > 10:
        # 买方：用钱买食物
        sellers = [agent_map[n] for n in nbrs if n in agent_map and agent_map[n].alive
                   and (agent_map[n].resource_state or {}).get("food_pressure", 0.0) < 0.4
                   and agent_map[n].resources.available("food") > 30]
        if not sellers:
            return False
        b = rng.choice(sellers)
        cost = price * qty
        if transfer(a, b, "money", cost, ledger, "trade_buy", tick):
            transfer(b, a, "food", qty, ledger, "trade_sell", tick)
            return True
        return False
    elif st.get("food_pressure", 0.0) < 0.3 and a.resources.available("food") > 40:
        # 卖方：卖食物换钱
        buyers = [agent_map[n] for n in nbrs if n in agent_map and agent_map[n].alive
                  and (agent_map[n].resource_state or {}).get("food_pressure", 0.0) > 0.5
                  and agent_map[n].resources.available("money") > 10]
        if not buyers:
            return False
        b = rng.choice(buyers)
        if transfer(a, b, "food", qty, ledger, "trade_sell", tick):
            transfer(b, a, "money", price * qty, ledger, "trade_buy", tick)
            return True
    return False


def _food_price(ctx: dict) -> float:
    """价格（§20）：base × scarcity。全局食物越稀缺，价格越高。"""
    cfg = ctx["cfg"]
    base = cfg.get("economy", {}).get("trade_base_price", 1.0)
    agents = [x for x in ctx["society"].agents if x.alive]
    mean_food = sum(x.resources.available("food") for x in agents) / max(len(agents), 1)
    food_critical = cfg.get("economy", {}).get("food_critical", 20.0)
    scarcity = food_critical / max(mean_food, 1.0)
    return base * max(0.5, min(3.0, scarcity))


def _do_save(a: Agent, ctx: dict, ledger, tick: int) -> None:
    """储蓄（§10, §40）：money → property（长期安全）。

    v0.4.1：单次上限 20%→5%、绝对上限 10→2。原速率下储蓄把流通货币
    全部冻结进 illiquid property（money 5 天内 500→2），是流动性死亡主因。
    """
    amt = min(a.resources.available("money") * 0.05, 2.0)
    if amt > 0:
        a.resources.add("money", -amt)
        a.resources.add("property", amt)
        if ledger is not None:
            ledger.record(source=a.id, target=a.id, resource="money",
                          amount=amt, reason="save", tick=tick)


def _do_consume(a: Agent, ctx: dict, ledger, tick: int) -> None:
    """消费（§10）：money → food/energy。"""
    amt = min(a.resources.available("money"), 2.0)
    if amt > 0:
        a.resources.add("money", -amt)
        a.resources.add("food", amt * 0.4)
        a.resources.add("energy", amt * 0.4)


def _do_share(a: Agent, ctx: dict, rng: random.Random, ledger, tick: int) -> bool:
    """分享（§21–§24）：向群体资源池或低资源邻居转移。

    v0.4.1：群体池按人均存量封顶——池子充裕时改为直接帮助邻居。
    原实现无视池存量持续注入，群体池成为食物黑洞（Agent 挨饿、池里囤粮）。
    """
    groups = ctx["groups"]
    ident = getattr(a, "identity", None)
    if groups is not None and ident is not None and ident.primary_group:
        g = groups.get(ident.primary_group)
        if g is not None and g.is_alive():
            pool_per_member = g.resources.get("food", 0.0) / max(g.size(), 1)
            if pool_per_member < 40.0:  # 池子还缺粮才存入
                amt = min(a.resources.available("food") * 0.1, 5.0)
                if amt > 0:
                    a.resources.add("food", -amt)
                    g.resources["food"] = g.resources.get("food", 0.0) + amt
                    if ledger is not None:
                        ledger.record(source=a.id, target=g.id, resource="food",
                                      amount=amt, reason="group_share", tick=tick)
                    return True
    # 无群体 → 向低资源邻居分享
    agent_map = ctx["agent_map"]
    nbrs = ctx["network"].get(a.id, [])
    for nid in nbrs:
        b = agent_map.get(nid)
        if b is None or not b.alive:
            continue
        if (b.resource_state or {}).get("food_pressure", 0.0) > 0.7:
            amt = min(a.resources.available("food") * 0.1, 3.0)
            if amt > 0 and transfer(a, b, "food", amt, ledger, "share", tick):
                return True
    return False


def _do_migrate(a: Agent, ctx: dict, rng: random.Random) -> bool:
    """迁移（§31–§33）：成本已在 _execute 结算（money/energy）。"""
    regions = ctx["cfg"].get("regions", {}).get("list", ["A", "B", "C"])
    cur = getattr(a, "location", "A")
    others = [r for r in regions if r != cur]
    if not others:
        return False
    a.location = rng.choice(others)
    return True


def _do_join_group(a: Agent, ctx: dict, rng: random.Random) -> None:
    """加入群体（§10）：优先加入同区域的活跃群体；已在的群体跳过。"""

    groups = ctx["groups"]
    ident = getattr(a, "identity", None)
    if groups is None or ident is None:
        return
    if ident.membership_count() >= 3:  # 与 compute_feasibility 的上限一致（§51 有界多身份）
        return
    loc = getattr(a, "location", "A")
    cands = [g for g in groups.active()
             if not ident.in_group(g.id) and g.size() < 200 and g.region == loc]
    if not cands:
        cands = [g for g in groups.active() if not ident.in_group(g.id) and g.size() < 200]
    if not cands:
        return
    g = rng.choice(cands)
    g.members.add(a.id)
    ident.add_group(g.id)  # 走 Identity 通道，保证 group_memberships/primary_group 一致


def _do_leave_group(a: Agent, ctx: dict, tick: int = 0) -> None:
    """离开群体（§10）：退出 primary group，memberships 同步更新，记录退群时刻。"""
    ident = getattr(a, "identity", None)
    groups = ctx["groups"]
    if ident is None or groups is None or not ident.primary_group:
        return
    gid = ident.primary_group
    g = groups.get(gid)
    if g is not None:
        g.members.discard(a.id)
    ident.remove_group(gid)  # 自动把 primary 切换到其余 membership（如有）
    a.status["last_leave_group_tick"] = tick  # 供 formation 退群冷却使用


def _inter_group_conflict(society, registry, agent_map: dict, rng: random.Random, cfg: dict) -> int:
    """跨群体冲突（§50, §78）：低信任群体对之间采样冲突。"""
    if registry is None:
        return 0
    groups = registry.active()
    if len(groups) < 2:
        return 0
    conflicts = 0
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








