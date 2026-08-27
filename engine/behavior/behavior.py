"""Behavior → Event 反向闭环（v0.4 §40–§44 → v0.4.1 §9–§20 重构）。

v0.4.5.1: Runtime State Machine Hotfix
  - Action completion uses saved action name, not post-reset state
  - _do_work_tick() is the ONLY work production path
  - _complete_work() only handles stats/employment/wage, NOT resource production
  - Daily budget reset does NOT cancel in-progress actions
  - Cross-day actions (e.g. migrate 24h) continue past midnight
"""

from __future__ import annotations

import random
from typing import Optional

from ..agent.agent import Agent
from ..economy.transaction import reserve, commit, release, transfer
from .actions import default_actions
from .utility import compute_feasibility, compute_utility, select_action
from .scheduler import ActionState


def _build_ctx(society, cfg: dict) -> dict:
    return {
        "society": society,
        "cfg": cfg,
        "agent_map": society.agent_map(),
        "network": getattr(society, "_network", {}) or {},
        "groups": getattr(society, "groups", None),
    }


def step_behavior(society, cfg: dict, rng: random.Random) -> list:
    """v0.4.5.1: Action scheduler with explicit state machine."""
    from .scheduler import AgentActivity, get_dt_hours

    bcfg = cfg.get("behavior", {})
    protest_event_threshold = bcfg.get("protest_threshold", 0.10)
    conflict_event_threshold = bcfg.get("conflict_threshold", 0.05)
    migration_event_threshold = bcfg.get("migration_threshold", 0.08)

    agents = [a for a in society.agents if a.alive]
    n_alive = len(agents)
    if n_alive == 0:
        return []

    ticks_per_day = cfg.get("ticks_per_day", 100)
    dt_hours = get_dt_hours(ticks_per_day)
    tick = society.clock.tick

    # Initialize activity for all agents
    for a in agents:
        if a.activity is None:
            a.activity = AgentActivity()

    # Daily reset — only resets budget, NOT in-progress actions (§7-§8)
    if tick % ticks_per_day == 0:
        for a in agents:
            a.activity.reset_daily(tick)

    actions = default_actions(cfg)
    ctx = _build_ctx(society, cfg)
    ctx["food_price"] = _food_price(ctx)
    ledger = getattr(society, "resource_ledger", None)

    # Occupation assignment (daily)
    from ..economy.occupation import choose_occupation
    if tick % ticks_per_day == 0:
        regions = getattr(society, "regions", None)
        for a in agents:
            region = regions.get(getattr(a, "location", "A")) if regions else None
            a.occupation = choose_occupation(a, region, cfg).value

    counters = {"protest": 0, "conflict": 0, "migrate": 0, "trade": 0,
                "share": 0, "hoard": 0, "work": 0, "cooperate": 0}
    micro_events: list = []

    for a in agents:
        act_state = a.activity

        # v0.4.5.1 §1: Handle completed actions FIRST
        if act_state.is_completed():
            # Use saved completion data (not post-reset state)
            completed_action = act_state.completed_action
            if completed_action:
                _apply_completion(a, act_state, ctx, rng, ledger, tick, counters)
            act_state.complete(tick)  # Return to IDLE

        # Advance current action if running
        if act_state.is_busy():
            completed = act_state.advance(dt_hours)
            # v0.4.5.1 §4: Produce gradually during work (ONLY production path)
            if act_state.current_action == "work":
                _do_work_tick(a, ctx, ledger, tick, dt_hours)
            if not completed:
                # Still busy, skip to next agent
                continue
            # Action completed this tick — will be handled on next iteration
            # But we need to handle it now for non-work actions
            completed_action = act_state.completed_action
            if completed_action and completed_action != "work":
                _apply_completion(a, act_state, ctx, rng, ledger, tick, counters)
                act_state.complete(tick)
            continue

        # Agent is idle — choose new action if budget allows
        # v0.4.5.1 §7: available_hours only affects NEW action eligibility
        if act_state.available_hours() < 0.5:
            continue

        sel = select_action(a, actions, ctx, rng)
        if sel is None:
            a.current_action = ""
            continue
        act, u, f = sel
        a.current_action = act.name
        a.action_utility = round(u, 4)
        a.action_feasibility = round(f, 4)

        # Start action with duration
        act_state.start_action(act.name, tick)
        # Pay costs immediately
        _execute_cost(a, act, ctx, rng, ledger, tick)

    # Inter-group conflict
    counters["conflict"] += _inter_group_conflict(society, ctx["groups"], ctx["agent_map"], rng, cfg)

    # Aggregate to macro events
    crisis_manager = getattr(society, "crisis_manager", None)
    protest_tracker = getattr(crisis_manager, "protest", None)
    protest_gate_open = protest_tracker is None or protest_tracker.state.value == "NORMAL"
    if (n_alive > 0 and counters["protest"] / n_alive >= protest_event_threshold
            and not _has_active(society, "protest") and protest_gate_open):
        micro_events.append(_emit(society, "protest", source="behavior", severity=0.6,
                                  description=f"行为涌现：{counters['protest']} 名 Agent 参与抗议"))
        society.production_disruption = min(0.4, getattr(society, "production_disruption", 0.0) + 0.08)
    if n_alive > 0 and counters["conflict"] / n_alive >= conflict_event_threshold and not _has_active(society, "conflict"):
        micro_events.append(_emit(society, "conflict", source="behavior", severity=0.5,
                                  description=f"行为涌现：群体间冲突 {counters['conflict']} 起"))
    if n_alive > 0 and counters["migrate"] / n_alive >= migration_event_threshold and not _has_active(society, "migration"):
        micro_events.append(_emit(society, "migration", source="behavior", severity=0.4,
                                  description=f"行为涌现：{counters['migrate']} 名 Agent 迁移"))

    return micro_events


def _apply_completion(a: Agent, act_state, ctx: dict, rng: random.Random,
                      ledger, tick: int, counters: dict) -> None:
    """v0.4.5.1: Action completion handler.

    Uses saved completion data from act_state.completed_action.
    For work: _do_work_tick() already produced resources during RUNNING.
    Completion only handles stats/employment/wage settlement.
    """
    action_name = act_state.completed_action
    if action_name is None:
        return

    if action_name == "work":
        # v0.4.5.1 §4: _complete_work only handles stats, NOT production
        _complete_work(a, ctx, ledger, tick)
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
        a.resources.add("energy", 5.0 * (act_state.hours_committed / 8.0))
    elif action_name == "join_group":
        _do_join_group(a, ctx, rng)
    elif action_name == "leave_group":
        _do_leave_group(a, ctx, tick)
    elif action_name == "communicate":
        pass


def _execute_cost(a: Agent, act, ctx: dict, rng: random.Random, ledger, tick: int) -> None:
    """v0.4.3: 动作启动时预扣成本（能量、金钱等）。"""
    for res, amt in act.cost.items():
        if amt <= 0:
            continue
        if not reserve(a, res, amt):
            return
        commit(a, res, amt, ledger, f"action:{act.name}", tick)


def _do_work_tick(a: Agent, ctx: dict, ledger, tick: int, dt_hours: float) -> None:
    """v0.4.5.1 §4: The ONLY work production path.

    Produces food/energy/money gradually during work action.
    This is called every tick while the work action is RUNNING.
    """
    from ..economy.occupation import get_production_multipliers, OccupationType

    econ = ctx["cfg"].get("economy", {})
    pm = getattr(ctx["society"], "production_multiplier", 1.0)
    disruption = getattr(ctx["society"], "production_disruption", 0.0)
    effective_pm = max(0.3, pm - disruption)

    base_productivity = 0.5 + a.personality["conscientiousness"] * 0.5
    a.productivity = base_productivity

    prop = a.resources.available("property")
    property_factor = max(0.3, min(1.0, (prop / 20.0) ** 0.5))
    energy = a.resources.available("energy")
    energy_factor = max(0.3, min(1.0, energy / 10.0))

    region_bonus = 1.0
    regions = getattr(ctx["society"], "regions", None)
    if regions:
        loc = getattr(a, "location", "A")
        region = regions.get(loc)
        if region:
            endow = ctx["cfg"].get("regions", {}).get("endowments", {}).get(loc, {})
            region_bonus = 0.7 + 0.3 * endow.get("food", 1.0)

    occ = getattr(a, "occupation", "farmer")
    try:
        occ_type = OccupationType(occ)
    except ValueError:
        occ_type = OccupationType.FARMER
    occ_mult = get_production_multipliers(occ_type)

    input_factor = property_factor * energy_factor * region_bonus

    production_cfg = econ.get("production", {})
    food_rate = production_cfg.get("food", {}).get("per_hour", 6.0)
    energy_rate = production_cfg.get("energy", {}).get("per_hour", 0.12)
    wage_rate = production_cfg.get("money", {}).get("wage_per_hour", 1.50)

    food_prod = food_rate * occ_mult["food"] * dt_hours * base_productivity * input_factor * effective_pm
    energy_prod = energy_rate * occ_mult["energy"] * dt_hours * base_productivity * input_factor * effective_pm
    wage = wage_rate * occ_mult["money"] * dt_hours * base_productivity * input_factor * effective_pm

    a.resources.add("food", food_prod)
    a.resources.add("energy", energy_prod)
    a.resources.add("money", wage)


def _complete_work(a: Agent, ctx: dict, ledger, tick: int) -> None:
    """v0.4.5.1 §4: Work completion — stats/employment only, NO production.

    Production already happened in _do_work_tick() during RUNNING state.
    This only handles: productivity update, employment update, ledger record.
    """
    # Update productivity stat
    base_productivity = 0.5 + a.personality["conscientiousness"] * 0.5
    a.productivity = base_productivity

    # Ledger record for the completed work session
    if ledger is not None:
        ledger.record(source="work_session", target=a.id, resource="labor",
                      amount=1.0, reason="work_complete", tick=tick)


def _do_trade(a: Agent, ctx: dict, rng: random.Random, ledger, tick: int) -> bool:
    """交易（§18–§20）：找 counterparty，按稀缺性定价，守恒转移。"""
    agent_map = ctx["agent_map"]
    nbrs = ctx["network"].get(a.id, [])
    if not nbrs:
        return False
    st = getattr(a, "resource_state", {}) or {}
    price = ctx.get("food_price")
    if price is None:
        price = _food_price(ctx)
    qty = 5.0

    if st.get("food_pressure", 0.0) > 0.5 and a.resources.available("money") > 10:
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
    """储蓄（§10, §40）：money → property（长期安全）。"""
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
    """分享（§21–§24）：向群体资源池或低资源邻居转移。"""
    groups = ctx["groups"]
    ident = getattr(a, "identity", None)
    if groups is not None and ident is not None and ident.primary_group:
        g = groups.get(ident.primary_group)
        if g is not None and g.is_alive():
            pool_per_member = g.resources.get("food", 0.0) / max(g.size(), 1)
            if pool_per_member < 40.0:
                amt = min(a.resources.available("food") * 0.1, 5.0)
                if amt > 0:
                    a.resources.add("food", -amt)
                    g.resources["food"] = g.resources.get("food", 0.0) + amt
                    if ledger is not None:
                        ledger.record(source=a.id, target=g.id, resource="food",
                                      amount=amt, reason="group_share", tick=tick)
                    return True
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
    """加入群体（§10）：优先加入同区域的活跃群体。"""
    groups = ctx["groups"]
    ident = getattr(a, "identity", None)
    if groups is None or ident is None:
        return
    if ident.membership_count() >= 3:
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
    ident.add_group(g.id)


def _do_leave_group(a: Agent, ctx: dict, tick: int = 0) -> None:
    """离开群体（§10）：退出 primary group。"""
    groups = ctx["groups"]
    ident = getattr(a, "identity", None)
    if groups is None or ident is None:
        return
    if not ident.primary_group:
        return
    g = groups.get(ident.primary_group)
    if g is not None:
        g.members.discard(a.id)
    ident.remove_group(ident.primary_group)


def _do_work(a: Agent, ctx: dict, ledger, tick: int, hours: float = 4.0) -> None:
    """v0.4.5.1: DEPRECATED — kept for backward compatibility only.

    Production is now handled by _do_work_tick() during RUNNING state.
    This function is only called from legacy code paths.
    """
    # In v0.4.5.1, this should NOT be called for normal work actions.
    # Production happens in _do_work_tick().
    pass


def _has_active(society, event_type: str) -> bool:
    """Check if an event type is currently active."""
    chain = getattr(society, "events", None)
    if chain is None:
        return False
    return any(e.type == event_type and e.is_active for e in chain.events)


def _emit(society, event_type: str, source: str = "behavior", severity: float = 0.5,
          description: str = "") -> object:
    """Emit a behavior-emergent event."""
    from ..event.event import SOURCE_TYPE
    chain = society.events
    return chain.make(
        society.clock.tick, event_type,
        source=source, severity=severity, description=description,
        source_type=SOURCE_TYPE.ENDOGENOUS,
    )


def _inter_group_conflict(society, groups, agent_map: dict, rng: random.Random, cfg: dict) -> int:
    """Inter-group conflict detection."""
    if groups is None:
        return 0
    active = groups.active()
    if len(active) < 2:
        return 0
    conflict_count = 0
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            g1, g2 = active[i], active[j]
            if hasattr(g1, 'centroid') and hasattr(g2, 'centroid'):
                dist = sum((a - b) ** 2 for a, b in zip(g1.centroid, g2.centroid)) ** 0.5
                if dist > 1.5 and rng.random() < 0.01:
                    conflict_count += 1
    return conflict_count
