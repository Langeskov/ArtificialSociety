"""Action System（v0.4.1 §9–§14）。

将 rule-based 行为升级为「候选行为 → 可行性 → 效用 → 风险 → 社会成本 → 选择」。
每个 Action 明确成本、需求、预期收益、风险、时长、社会/资源效果（§11）。
所有参数配置化（config.actions 可覆盖默认值）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 12 种候选行为（§10）
ACTION_NAMES = (
    "work", "trade", "save", "consume", "share", "cooperate",
    "protest", "migrate", "join_group", "leave_group", "communicate", "rest",
)


@dataclass
class Action:
    name: str
    cost: dict = field(default_factory=dict)            # 资源成本（§11）
    requirements: dict = field(default_factory=dict)    # 最低资源需求（§11）
    expected_return: dict = field(default_factory=dict)  # 预期收益（§11）
    risk: float = 0.0
    duration: int = 1
    social_effect: dict = field(default_factory=dict)   # 社会效果（anger/trust/identity 等）
    resource_effect: dict = field(default_factory=dict)  # 资源效果（生产等）


# 默认 action 参数（§10, §11）。config.actions 可覆盖。
_DEFAULT_ACTION_SPECS: dict[str, dict] = {
    "work":        {"cost": {"energy": 2.0, "food": 0.02}, "requirements": {"energy": 2.0},
                    "risk": 0.02, "expected_return": {"money": 3.0, "food": 0.15}},
    "trade":       {"cost": {"energy": 1.0}, "requirements": {"energy": 1.0},
                    "risk": 0.05},
    "save":        {"cost": {}, "requirements": {"money": 1.0},
                    "risk": 0.0, "expected_return": {"property": 1.0}},
    "consume":     {"cost": {"money": 2.0}, "requirements": {"money": 2.0},
                    "risk": 0.0, "expected_return": {"food": 1.0, "energy": 1.0}},
    "share":       {"cost": {"energy": 1.0}, "requirements": {"energy": 1.0},
                    "risk": 0.02},
    "cooperate":   {"cost": {"energy": 1.0}, "requirements": {"energy": 1.0},
                    "risk": 0.01, "social_effect": {"anger": -0.02, "trust_in_government": 0.005}},
    "protest":     {"cost": {"energy": 5.0}, "requirements": {"energy": 5.0},
                    "risk": 0.30, "social_effect": {"anger": -0.1}},
    "migrate":     {"cost": {"money": 30.0, "energy": 15.0}, "requirements": {"money": 30.0, "energy": 15.0},
                    "risk": 0.20},
    "join_group":  {"cost": {}, "requirements": {}, "risk": 0.0},
    "leave_group": {"cost": {}, "requirements": {}, "risk": 0.05},
    "communicate": {"cost": {"energy": 0.5}, "requirements": {"energy": 0.5},
                    "risk": 0.01},
    "rest":        {"cost": {}, "requirements": {}, "risk": 0.0,
                    "expected_return": {"energy": 5.0}},
}


def default_actions(cfg: dict) -> dict[str, Action]:
    """构建 12 种 action 的默认参数表，config.actions 深合并覆盖（§11 参数配置化）。"""
    acfg = cfg.get("actions", {})
    actions: dict[str, Action] = {}
    for name in ACTION_NAMES:
        spec = dict(_DEFAULT_ACTION_SPECS.get(name, {}))
        over = acfg.get(name, {})
        # 深合并子字典
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(spec.get(k), dict):
                spec[k] = {**spec[k], **v}
            else:
                spec[k] = v
        actions[name] = Action(name=name, **spec)
    return actions
