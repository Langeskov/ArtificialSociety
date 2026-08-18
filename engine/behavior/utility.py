"""Action Feasibility / Utility / Selection（v0.4.1 §12–§14）。

候选行为 → 可行性（§12）→ 效用（§13）→ 概率选择（§13 有限随机性）。
效用 = 目标对齐 + 资源需求 + 人格契合 + 身份契合 + 群体压力 + 信息效应
      − 资源成本 − 风险成本 − 社会成本。

性能说明：select_action 每 tick 对每个 Agent 评估全部候选行为，
per-agent 的标量信号（人格/资源压力/情绪/身份）通过 _signals() 只提取一次，
避免在 12 个 action 的评估中重复 getattr/dict 链（实测热点）。
"""

from __future__ import annotations

import math
import random

from ..agent.agent import Agent


def _signals(a: Agent) -> dict:
    """提取 Agent 的评估标量（每 agent 每 tick 一次）。

    默认值与直接在空 resource_state / 无 identity 时逐 action 求值的结果一致，
    保证不传 sig 的外部调用（含测试）语义不变。
    """
    p = a.personality.values
    st = a.resource_state or {}
    ident = getattr(a, "identity", None)
    status = a.status
    return {
        "pressure": st.get("pressure", 0.5),
        "money_pressure": st.get("money_pressure", 0.5),
        "food_pressure": st.get("food_pressure", 0.0),
        "energy_pressure": st.get("energy_pressure", 0.0),
        "information_pressure": st.get("information_pressure", 0.0),
        "surplus": st.get("surplus", 0.0),
        "anger": status.get("anger", 0.0),
        "trust_gov": status.get("trust_in_government", 0.5),
        "risk_tol": p["risk_tolerance"],
        "agreeableness": p["agreeableness"],
        "conscientiousness": p["conscientiousness"],
        "empathy": p["empathy"],
        "belonging": getattr(ident, "belonging", 0.0) if ident is not None else 0.0,
        "autonomy": getattr(ident, "autonomy", 0.0) if ident is not None else 0.0,
        "loyalty": getattr(ident, "group_loyalty", 0.0) if ident is not None else 0.0,
        "memberships": ident.membership_count() if ident is not None else 0,
        "energy": a.resources.available("energy"),
    }


def compute_feasibility(a: Agent, action, ctx: dict, sig: dict | None = None) -> float:
    """行为可行性 ∈ [0,1]（§12）。资源需求不足 → 0（禁止执行）。"""
    # 1. 资源硬门槛（§12：requirements 未满足 → 不可行）
    for res, req in action.requirements.items():
        if a.resources.available(res) < req:
            return 0.0

    if sig is None:
        sig = _signals(a)
    factors = 1.0

    # 2. 能量充足度（连续，§12 例子 energy sufficient 0.8）
    # v0.4.1：req×2 → req×4。原系数下能量低于 2×需求才衰减，导致所有耗能行为
    # 在能量贴地板时仍满权重竞争，工作率被社交行为挤占（能量预算不约束）。
    req_e = action.requirements.get("energy", 0.0)
    if req_e > 0:
        factors *= min(1.0, sig["energy"] / (req_e * 4.0))

    # 3. 群体忠诚惩罚（迁移/退群：高忠诚者更不愿离开）
    if action.name in ("migrate", "leave_group"):
        factors *= 1.0 - 0.6 * sig["loyalty"]

    # 4. 风险容忍（高风险行为，低风险容忍者可行性低）
    factors *= 1.0 - action.risk * (1.0 - sig["risk_tol"])

    # 5. 成员/动机前提（§12 扩展：约束可行动空间）
    # 无群体可退 / 无群体可加入 → 不可行
    if action.name == "leave_group" and sig["memberships"] == 0:
        return 0.0
    if action.name == "join_group":
        # 多身份有上限（§51 有界版：≤3）。无上限时 membership 累积到 50+，
        # group_pressure 效用项被打满，share 永远压过 work（实测失稳）。
        if sig["memberships"] >= 3:
            return 0.0
        groups = ctx.get("groups")
        ident = getattr(a, "identity", None)
        if groups is None or ident is None:
            return 0.0
        if not any(not ident.in_group(g.id) and g.size() < 200 for g in groups.active()):
            return 0.0
    # 无不满的抗议是噪声：anger 低且信任不低 → 不可行（protest 耗能 5，噪声抗议会烧光社会能量）
    if action.name == "protest" and sig["anger"] < 0.15 and sig["trust_gov"] > 0.4:
        return 0.0
    # 货币不足时不储蓄（防止流动性死亡：原实现把 20% 余额/action 冻结进 illiquid property）
    if action.name == "save" and sig["money_pressure"] > 0.4:
        return 0.0
    # 自己都快饿死时不分享（分享应是盈余行为，而非饥饿转让）
    if action.name == "share" and sig["food_pressure"] > 0.8:
        return 0.0

    # 6. 生存压力门控（§5/§12 连续版）：食物压力越高，非生存行为可行性越低。
    # 不用硬阈值（§5 禁止 19.9→20.1 式跳变），用 food_pressure 连续衰减。
    # 这是「资源约束可行动空间」的核心机制：危机时社会行为让位于生存行为。
    # v0.4.1 hotfix：share 不是生产行为（纯转移），不应享受生存豁免。
    # 原列表含 share → 食物危机时 share 不受门控，而 work 产出食物但 share 效用更高。
    _SURVIVAL = ("work", "rest", "consume", "trade")
    fp = sig["food_pressure"]
    if fp > 0.5 and action.name not in _SURVIVAL:
        factors *= max(0.05, 1.0 - (fp - 0.5) * 1.9)  # fp=0.5 → 1.0；fp→1.0 → 0.05

    return max(0.0, min(1.0, factors))


def compute_utility(a: Agent, action, ctx: dict, sig: dict | None = None) -> float:
    """行为效用（§13）。"""
    if sig is None:
        sig = _signals(a)
    pressure = sig["pressure"]
    anger = sig["anger"]
    trust_gov = sig["trust_gov"]
    name = action.name

    # 1. 目标对齐（资源压力/情绪驱动的行为倾向）
    goal_alignment = 0.0
    if name == "work":
        # work 同时产出 money+food（§14/§16），应对任一稀缺强响应；
        # 原公式只看 money_pressure，食物危机时工作率上不去 → 全员慢性饿死
        # v0.4.1 hotfix：食物紧急乘数——当食物压力高时，工作效用显著上升，
        # 否则 share（无产出，纯转移）的 identity/group 加成让它无脑优于 work，
        # 社会总工作率仅 5-9%（需要 ~15%），食物单调下降。
        fp = sig["food_pressure"]
        food_urgency = 1.0 + fp * 1.5  # fp=0 → 1.0；fp=0.5 → 1.75；fp=1.0 → 2.5
        goal_alignment = (pressure * 0.3 + max(sig["money_pressure"], fp) * 0.7) * food_urgency
    elif name == "migrate":
        goal_alignment = pressure * 0.9
    elif name == "protest":
        goal_alignment = anger * 0.7 + (1.0 - trust_gov) * 0.5
    elif name == "rest":
        # 能量越枯竭越需要休息（v0.4.1 修复：原 (1-pressure)*0.3 方向相反，
        # 枯竭 Agent 反而不休息，是全员能量死亡螺旋的根因之一）
        # 平方项让「接近枯竭」时的休息 urgency 非线性上升
        ep = sig["energy_pressure"]
        goal_alignment = ep * ep * 1.0 + (1.0 - pressure) * 0.1
    elif name == "consume":
        goal_alignment = sig["food_pressure"] * 0.6

    # 2. 资源需求
    resource_need = 0.0
    if name == "work":
        resource_need = sig["money_pressure"] * 0.5
    elif name == "save":
        resource_need = sig["surplus"] * 0.5
    elif name == "consume":
        resource_need = sig["food_pressure"] * 0.6

    # 3. 人格契合
    personality_fit = 0.0
    if name == "protest":
        personality_fit = sig["risk_tol"] * 0.5 + (1.0 - sig["agreeableness"]) * 0.3
    elif name == "save":
        personality_fit = (1.0 - sig["risk_tol"]) * 0.4 + sig["conscientiousness"] * 0.3
    elif name == "share":
        # v0.4.1 hotfix：降低 share 人格加成——原 0.5a+0.3e 让高亲和力 agent
        # 无条件选 share 而非 work，即使食物在下降。
        personality_fit = sig["agreeableness"] * 0.3 + sig["empathy"] * 0.15

    # 4. 身份契合
    identity_fit = 0.0
    if name in ("share", "cooperate", "join_group"):
        # v0.4.1 hotfix：降低 share 的身份加成——原 0.4 让 share 在有群体身份时
        # 无条件优于 work（belonging≈0.6 → 0.24 免费加分），工作率崩溃。
        identity_fit = sig["belonging"] * 0.2
    elif name in ("migrate", "leave_group"):
        identity_fit = sig["autonomy"] * 0.4

    # 5. 群体压力
    group_pressure = 0.0
    if name in ("share", "cooperate"):
        # v0.4.1 hotfix：降低 share 群体压力——原 min(0.5, mem*0.1) 在 3 组时=0.3，
        # 叠加 identity_fit 后 share 效用可达 1.0+，远超 work。
        group_pressure = min(0.2, sig["memberships"] * 0.04)

    # 6. 信息效应（资源匮乏 → 信息需求 ↑，此处简化为压力信号，§29）
    information_effect = 0.0
    if name == "communicate":
        information_effect = sig["information_pressure"] * 0.4

    # 成本项
    resource_cost = sum(action.cost.values()) * 0.02
    risk_cost = action.risk * (1.0 - sig["risk_tol"]) * 0.5
    social_cost = 0.0
    if name == "protest":
        social_cost = (1.0 - trust_gov) * 0.1

    return (goal_alignment + resource_need + personality_fit + identity_fit
            + group_pressure + information_effect
            - resource_cost - risk_cost - social_cost)


def select_action(a: Agent, actions: dict, ctx: dict, rng: random.Random):
    """概率选择行为（§13 有限随机性，不总是选固定最高效用）。

    返回 (action, utility, feasibility) 三元组；无可行行为返回 None。
    调用方应直接使用返回的 utility/feasibility，避免对选中行为重复求值。
    """
    sig = _signals(a)
    candidates = []
    weights = []
    utils = []
    feass = []
    for act in actions.values():
        f = compute_feasibility(a, act, ctx, sig)
        if f <= 0.0:
            continue
        u = compute_utility(a, act, ctx, sig)
        # 权重 = 可行性 × exp(效用)（softmax 风格）
        w = f * math.exp(min(u, 20.0))
        candidates.append(act)
        weights.append(max(w, 1e-9))
        utils.append(u)
        feass.append(f)

    if not candidates:
        return None

    total = sum(weights)
    r = rng.random() * total
    acc = 0.0
    for act, w, u, f in zip(candidates, weights, utils, feass):
        acc += w
        if r <= acc:
            return act, u, f
    return candidates[-1], utils[-1], feass[-1]
