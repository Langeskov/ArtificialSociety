"""Occupation System (v0.4.3 §1).

Agent 拥有动态职业，由 personality + skill + region + resource + group 共同决定。
不是永久标签 —— Agent 可以根据环境变化切换职业。

职业类型：
  farmer       → 食物生产为主
  miner        → 能源生产为主
  manufacturer → 财产/工具生产为主
  trader       → 资源转移/市场活动
  service      → 金钱/影响力
  government   → 稳定/税收/公共服务

每个职业有不同的生产函数（投入→产出比）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class OccupationType(str, Enum):
    FARMER = "farmer"
    MINER = "miner"
    MANUFACTURER = "manufacturer"
    TRADER = "trader"
    SERVICE = "service"
    GOVERNMENT = "government"


@dataclass
class OccupationSpec:
    """职业规格：定义该职业的生产函数参数。"""
    name: OccupationType
    # 生产系数：该职业产出各资源的乘数
    food_output: float = 0.0
    energy_output: float = 0.0
    money_output: float = 0.0
    property_output: float = 0.0
    influence_output: float = 0.0
    # 输入需求：该职业消耗各资源的乘数
    energy_input: float = 1.0
    property_input: float = 0.5
    # 技能要求：哪些人格特质对该职业有利
    skill_weights: dict = field(default_factory=lambda: {
        "conscientiousness": 0.5, "openness": 0.2, "agreeableness": 0.1,
    })
    # 区域偏好：该职业在哪些区域有加成
    region_preference: list = field(default_factory=list)


# 默认职业规格
OCCUPATION_SPECS: dict[OccupationType, OccupationSpec] = {
    OccupationType.FARMER: OccupationSpec(
        name=OccupationType.FARMER,
        food_output=1.0, energy_output=0.2, money_output=0.4,
        energy_input=0.8, property_input=0.6,
        skill_weights={"conscientiousness": 0.6, "openness": 0.1, "agreeableness": 0.2},
    ),
    OccupationType.MINER: OccupationSpec(
        name=OccupationType.MINER,
        food_output=0.35, energy_output=1.0, money_output=0.5,
        energy_input=1.2, property_input=0.8,
        skill_weights={"conscientiousness": 0.5, "risk_tolerance": 0.3, "openness": 0.1},
    ),
    OccupationType.MANUFACTURER: OccupationSpec(
        name=OccupationType.MANUFACTURER,
        food_output=0.2, energy_output=0.1, money_output=0.7, property_output=0.8,
        energy_input=1.5, property_input=1.0,
        skill_weights={"conscientiousness": 0.7, "openness": 0.2},
    ),
    OccupationType.TRADER: OccupationSpec(
        name=OccupationType.TRADER,
        food_output=0.35, energy_output=0.1, money_output=1.0,
        energy_input=0.5, property_input=0.2,
        skill_weights={"openness": 0.4, "risk_tolerance": 0.4, "extraversion": 0.2},
    ),
    OccupationType.SERVICE: OccupationSpec(
        name=OccupationType.SERVICE,
        food_output=0.35, energy_output=0.1, money_output=0.8, influence_output=0.3,
        energy_input=0.6, property_input=0.3,
        skill_weights={"extraversion": 0.5, "agreeableness": 0.3, "empathy": 0.2},
    ),
    OccupationType.GOVERNMENT: OccupationSpec(
        name=OccupationType.GOVERNMENT,
        food_output=0.35, energy_output=0.1, money_output=0.5, influence_output=0.5,
        energy_input=0.4, property_input=0.1,
        skill_weights={"conscientiousness": 0.4, "agreeableness": 0.3, "openness": 0.2},
    ),
}


def compute_occupation_fit(agent, occ: OccupationSpec, region_bonus: dict = None) -> float:
    """计算 Agent 对某职业的适合度 [0, 1]。

    由 personality + region + resource_state 共同决定。
    """
    p = agent.personality.values
    fit = 0.0
    total_weight = 0.0
    for trait, weight in occ.skill_weights.items():
        val = p.get(trait, 0.5)
        fit += val * weight
        total_weight += weight
    if total_weight > 0:
        fit /= total_weight

    # 区域加成
    if region_bonus and occ.name.value in region_bonus:
        fit *= (0.5 + 0.5 * region_bonus[occ.name.value])

    # 资源状态影响：资源紧张时倾向高产出职业
    st = getattr(agent, "resource_state", {}) or {}
    food_pressure = st.get("food_pressure", 0.0)
    if food_pressure > 0.5 and occ.food_output > 0.3:
        fit *= (1.0 + food_pressure * 0.5)

    return max(0.0, min(1.0, fit))


def choose_occupation(agent, region, cfg: dict) -> OccupationType:
    """为 Agent 选择最适合的职业。

    综合考虑 personality、region endowment、当前资源状态。
    """
    region_bonus = {}
    if region:
        endow = cfg.get("regions", {}).get("endowments", {}).get(region.id, {})
        # 将 endowment 映射到职业偏好
        region_bonus = {
            "farmer": endow.get("food", 1.0),
            "miner": endow.get("energy", 1.0),
            "trader": endow.get("jobs", 0.5) * 1.5,
            "service": endow.get("jobs", 0.5) * 1.2,
            "government": 0.5,
            "manufacturer": endow.get("energy", 1.0) * 0.8,
        }

    best_occ = OccupationType.FARMER
    best_fit = 0.0
    for occ_type, spec in OCCUPATION_SPECS.items():
        fit = compute_occupation_fit(agent, spec, region_bonus)
        # 加入少量随机性（探索）
        rng_val = hash(agent.id + str(occ_type)) % 1000 / 1000.0
        fit_with_noise = fit * (0.8 + 0.4 * rng_val)
        if fit_with_noise > best_fit:
            best_fit = fit_with_noise
            best_occ = occ_type

    return best_occ


def get_production_multipliers(occ: OccupationType) -> dict:
    """获取职业的生产乘数。"""
    spec = OCCUPATION_SPECS.get(occ, OCCUPATION_SPECS[OccupationType.FARMER])
    return {
        "food": spec.food_output,
        "energy": spec.energy_output,
        "money": spec.money_output,
        "property": spec.property_output,
        "influence": spec.influence_output,
        "energy_input": spec.energy_input,
        "property_input": spec.property_input,
    }


