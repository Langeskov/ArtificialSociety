"""Group influence — Group 对成员的影响（v0.4 §20–§21, §52）。

group_pressure（§21）= group_cohesion × group_trust × identity_strength × group_influence

Group influence 必须有限（§20）：individual influence + group influence，而非
group 覆盖 individual。政治位置仍由 v0.3.1 dynamics engine 更新 —— 这里只通过
「身份强化」和「微弱锚点牵引」改变响应倾向（§19：不得直接设置 x/y/z）。
"""

from __future__ import annotations

from .group import Group
from ..agent.agent import Agent
from ..identity.update import identity_targets


def group_pressure(g: Group, agent: Agent) -> float:
    """单个 Agent 受到的群体压力（§21）。"""
    ident = getattr(agent.identity, "social_identity_strength", 0.0)
    return max(0.0, min(1.0, g.cohesion * g.trust * ident * g.influence))


def apply_group_influence(society, cfg: dict) -> None:
    """每个 tick 对每个 Group 成员施加影响：身份强化 + 微弱政治锚点牵引。"""
    registry = getattr(society, "groups", None)
    if registry is None:
        return
    gcfg = cfg.get("groups", {})
    anchor_pull = gcfg.get("influence", {}).get("anchor_pull", 0.002)
    identity_gain = gcfg.get("influence", {}).get("identity_gain", 0.01)

    agent_map = society.agent_map()
    for g in registry.active():
        for mid in list(g.members):
            m = agent_map.get(mid)
            if m is None or not m.alive:
                continue
            pressure = group_pressure(g, m)
            # 身份强化（§20, §52）：归属向人格化目标靠拢、忠诚向 0.8 靠拢（保留多样性 §19）
            # v0.4.1：belonging 目标不再固定 0.65（否则全员收敛同一身份，Z 轴单极化）
            ident = m.identity
            target_bel, _ = identity_targets(m.personality)
            ident.belonging = max(0.0, min(1.0, ident.belonging + (target_bel - ident.belonging) * identity_gain * pressure))
            ident.group_loyalty = max(0.0, min(1.0, ident.group_loyalty + (0.8 - ident.group_loyalty) * identity_gain * pressure))
            # 微弱锚点牵引：长期偏好缓慢向群体中心靠拢（不直接改 x/y/z，§19）
            ax, ay, az = m.ideology_anchor
            pull = anchor_pull * pressure
            m.ideology_anchor = (
                ax + (g.center_x - ax) * pull,
                ay + (g.center_y - ay) * pull,
                az + (g.center_z - az) * pull,
            )
