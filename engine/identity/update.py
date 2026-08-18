"""Identity update — 身份随时间演化（v0.4 §16, §53）。

Identity 来源：personality、relationships、group membership、shared events、
social status、resource position、experience、memory（§16）。身份可以重组（§53）：
长期失业 → 职业身份下降 → 社区身份增强；反复群体冲突 → 忠诚下降。
"""

from __future__ import annotations

from .identity import Identity


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def identity_targets(p) -> tuple[float, float]:
    """群体成员身份的人格化目标（§19 不锁死）：(target_belonging, target_autonomy)。

    群体社会化使归属向集体靠拢、自主性略降，但目标随人格基线变化——
    高开放/高自主人格在群体中保留更多自主性。

    v0.4.1 修复：原固定 0.65/0.35 目标让所有成员收敛到同一身份（indiv_pref
    恒为 -0.3），在微型组全覆盖的生态下 Z 轴失去双向性（实测 285:3 全员 Z-）。
    人格化目标恢复 indiv_pref 的个体差异，同时保留「入组平均偏集体」的方向。
    """
    base_bel = (p["agreeableness"] + p["empathy"] + p["extraversion"]) / 3.0
    base_aut = (p["openness"] + p["risk_tolerance"] + (1.0 - p["agreeableness"])) / 3.0
    return 0.35 + 0.5 * base_bel, 0.15 + 0.5 * base_aut


def init_identity(agent) -> Identity:
    """从人格初始化身份（§16）：belonging/autonomy 初始由人格映射，但随后演化。"""
    p = agent.personality
    autonomy = (p["openness"] + p["risk_tolerance"] + (1.0 - p["agreeableness"])) / 3.0
    belonging = (p["agreeableness"] + p["empathy"] + p["extraversion"]) / 3.0
    status = _clamp01(0.5 + (agent.resources.values.get("influence", 0.0) - 5.0) / 40.0)
    return Identity(belonging=belonging, autonomy=autonomy, status=status)


def step_identity(society, cfg: dict) -> None:
    """每个 tick 更新所有 Agent 的身份（§16, §53）。"""
    idcfg = cfg.get("identity", {})
    autonomy_decay = idcfg.get("group_autonomy_decay", 0.005)   # 群体社会化对自主性的削弱
    identity_decay = idcfg.get("identity_decay", 0.95)           # 无群体时身份强度衰减

    for a in society.agents:
        if not a.alive:
            continue
        ident = a.identity
        if ident is None:
            continue

        # 社会地位（§16 social status / resource position）：影响力 + 财富
        influence = a.resources.values.get("influence", 0.0)
        wealth = a.wealth()
        ident.status = _clamp01(0.5 + (influence - 5.0) / 40.0 + (wealth - 700.0) / 3000.0)

        n_groups = ident.membership_count()
        if n_groups > 0:
            # 群体成员 → 身份强度由归属+忠诚决定（§18），归属/自主向人格化目标靠拢（§19 不锁死）
            target_bel, target_aut = identity_targets(a.personality)
            ident.social_identity_strength = _clamp01(
                0.25 + 0.5 * ident.belonging + 0.25 * ident.group_loyalty
            )
            ident.belonging = _clamp01(ident.belonging + (target_bel - ident.belonging) * 0.01)
            ident.autonomy = _clamp01(ident.autonomy + (target_aut - ident.autonomy) * autonomy_decay)
        else:
            # 无群体 → 身份强度与忠诚衰减，归属/自主回归人格基线（§53 身份重组）
            ident.social_identity_strength *= identity_decay
            ident.group_loyalty *= identity_decay
            p = a.personality
            baseline_belonging = (p["agreeableness"] + p["empathy"] + p["extraversion"]) / 3.0
            baseline_autonomy = (p["openness"] + p["risk_tolerance"] + (1.0 - p["agreeableness"])) / 3.0
            ident.belonging = _clamp01(ident.belonging * 0.98 + baseline_belonging * 0.02)
            ident.autonomy = _clamp01(ident.autonomy * 0.98 + baseline_autonomy * 0.02)
