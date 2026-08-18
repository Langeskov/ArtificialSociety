"""Group Resource Pool（v0.4.1 §21–§24）。

真正启用 Group.resources（v0.4 只是空 dict）。提供 deposit/withdraw，以及
成员贡献（§22）、贫困成员分配（§23）、资源反馈（§24）。

资源反馈（§24）是本版本最重要的新回路之一：
  群体资源充裕 → cohesion/trust ↑ → 更稳定
  群体资源危机 → competition ↑ → trust ↓ → fragmentation ↑
"""

from __future__ import annotations

import random

from .group import Group
from ..agent.agent import Agent


def deposit(g: Group, resource: str, amount: float) -> None:
    g.resources[resource] = g.resources.get(resource, 0.0) + max(0.0, amount)


def withdraw(g: Group, resource: str, amount: float) -> float:
    """从 pool 提取；不足则取剩余。返回实际提取量。"""
    have = g.resources.get(resource, 0.0)
    take = min(have, amount)
    g.resources[resource] = have - take
    return take


def group_resource_security(g: Group, cfg: dict) -> float:
    """Group 资源安全度（§47）：共享食物相对成员规模。"""
    crit = cfg.get("economy", {}).get("food_critical", 20.0)
    per_member = g.resources.get("food", 0.0) / max(g.size(), 1)
    return max(0.0, min(1.0, per_member / max(crit, 1e-6)))


def step_group_resources(society, cfg: dict, rng: random.Random) -> None:
    """每 tick：成员贡献 + 贫困成员分配 + 资源反馈（§22–§24）。"""
    groups = getattr(society, "groups", None)
    if groups is None:
        return
    gcfg = cfg.get("group_resources", {})
    contrib_prob = gcfg.get("contribution_probability", 0.1)
    distrib_prob = gcfg.get("distribution_probability", 0.5)
    ledger = getattr(society, "resource_ledger", None)
    tick = society.clock.tick
    agent_map = society.agent_map()

    for g in groups.active():
        members = [agent_map[mid] for mid in g.members if mid in agent_map and agent_map[mid].alive]
        if not members:
            continue

        # 1. 成员贡献（§22）：高忠诚 + 高 surplus + 高信任 → 贡献概率↑
        for a in members:
            ident = getattr(a, "identity", None)
            loyalty = getattr(ident, "group_loyalty", 0.0) if ident else 0.0
            st = getattr(a, "resource_state", {}) or {}
            surplus = st.get("surplus", 0.0)
            prob = contrib_prob * (0.3 + 0.7 * loyalty) * (0.3 + 0.7 * surplus) * (0.5 + 0.5 * a.personality["trust"])
            if rng.random() < prob:
                amt = min(a.resources.available("food") * 0.1, 3.0)
                if amt > 0:
                    a.resources.add("food", -amt)
                    deposit(g, "food", amt)
                    if ledger is not None:
                        ledger.record(source=a.id, target=g.id, resource="food",
                                      amount=amt, reason="contribution", tick=tick)

        # 2. 贫困成员分配（§23）：向低资源成员分配。
        # v0.4.1：概率 0.2→0.5、贫困线 0.7→0.5——原参数下池子只进不出，
        # 群体池变成食物黑洞（成员挨饿、池里囤粮），分配必须及时回流。
        if rng.random() < distrib_prob and g.resources.get("food", 0.0) > 0:
            poor = [a for a in members if (a.resource_state or {}).get("food_pressure", 0.0) > 0.5]
            if poor:
                share = g.resources.get("food", 0.0) / len(poor)
                for a in poor:
                    amt = min(share, g.resources.get("food", 0.0))
                    if amt > 0:
                        got = withdraw(g, "food", amt)
                        a.resources.add("food", got)
                        if ledger is not None:
                            ledger.record(source=g.id, target=a.id, resource="food",
                                          amount=got, reason="distribution", tick=tick)

    # 3. 资源反馈（§24）
    _apply_resource_feedback(groups.active(), cfg)


def _apply_resource_feedback(groups: list[Group], cfg: dict) -> None:
    """§24：群体资源危机 → cohesion/trust ↓；资源充裕 → cohesion ↑。"""
    for g in groups:
        sec = group_resource_security(g, cfg)
        if sec < 0.3:
            g.cohesion = max(0.1, g.cohesion - 0.005)
            g.trust = max(0.1, g.trust - 0.003)
        else:
            g.cohesion = min(1.0, g.cohesion + 0.002)
