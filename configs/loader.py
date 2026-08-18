"""Config — default society config + YAML/JSON loading.

The `default_society_config()` mirrors the project plan's tunable parameters
(§34): population, ideology distribution, personality distribution, resources,
time scale, event frequency, movement/influence strength, and model provider.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import yaml


def default_society_config() -> dict:
    return {
        "name": "Unnamed Society",
        "seed": 0,
        "ticks_per_day": 100,
        "days_per_month": 30,
        "months_per_year": 12,
        "population": {
            "count": 1000,
            "age_range": [18, 75],
            "ideology_distribution": {
                "liberal": 0.30,
                "conservative": 0.30,
                "socialist": 0.20,
                "libertarian": 0.10,
                "authoritarian": 0.10,
            },
            "personality_distribution": {
                "agreeableness": {"high": 0.3, "neutral": 0.4, "low": 0.3},
                "risk_tolerance": {"high": 0.2, "neutral": 0.5, "low": 0.3},
            },
            "initial_resources": {
                "money": {"mean": 500, "sigma": 200},
                "food": {"mean": 100, "sigma": 20},
                "energy": {"mean": 80, "sigma": 20},
                "property": {"mean": 200, "sigma": 150},
                "influence": {"mean": 5, "sigma": 5},
                "information": {"mean": 20, "sigma": 10},
            },
            "ai_levels": {"level0": 0.90, "level1": 0.09, "level2": 0.0, "level3": 0.01},
        },
        "economy": {
            "base_income": 3.0,
            "income_sigma": 2.0,
            "food_consumption": 0.05,
            "energy_consumption": 0.03,
            "tax_rate": 0.01,            # 按日税率（v0.4.1：收入来自 work，8%/日在无固定收入下会抽干流动性）
            "redistribution": 0.5,
            # v0.2: resource production / recovery (§14, §15)
            # v0.4.1：产出挂在 work 行为上（非每 tick 固定发放），系数按
            # 「~15% 工作率即可养活全队」校准：0.6×0.75×15 ≈ 6.8 food/day > 5 代谢
            "food_production": 0.6,        # work 行为的食物产出系数（v0.4.1 移入行为）
            "energy_production": 0.06,     # work 行为的能量产出系数
            "food_critical": 20.0,         # below this → survival/recovery mode
            "recovery_rate": 0.05,         # production recovery per tick after shocks
            "trade_base_price": 1.0,       # v0.4.1 §20：食物基础价格
        },
        "politics": {
            "movement_strength": 0.01,
            "influence_strength": 0.01,
            # v0.2: political inertia + damping (§4, §5, §6, §7)
            "inertia": 0.95,
            "inertia_range": [0.85, 0.98],
            "damping": 0.92,
            "center_stability": 0.005,
            "ideology_anchor_strength": 0.02,
            "max_movement_per_tick": 0.03,
            "extremism_threshold": 0.7,
            "noise": 0.001,
            # v0.3: 三轴独立驱动力 + 弱耦合 (§7, §8, §9)
            "authority_dynamics_strength": 0.03,   # 旧字段，向后兼容
            "community_dynamics_strength": 0.02,   # 旧字段，向后兼容
            "axis_weights": {"x": 1.0, "y": 1.0, "z": 1.0},
            # v0.3.1: 三轴独立校准参数 (§37)
            "x_axis": {"economic_strength": 0.40, "sensitivity": 1.0, "deadzone": 0.05, "saturation": 1.0},
            "y_axis": {"authority_strength": 0.03, "security_strength": 0.02, "legitimacy_strength": 0.03},
            "z_axis": {"autonomy_strength": 0.02, "belonging_strength": 0.02, "group_pressure_strength": 0.02},
            "coupling": {"mode": "velocity", "xy": 0.03, "xz": -0.02, "yx": 0.02, "yz": 0.03, "zx": -0.02, "zy": 0.02},
        },
        "social": {
            # v0.2: information propagation + memory (§19, §20, §21, §22, §23)
            "influence_strength": 0.01,
            "echo_threshold": 0.4,
            "information_spread": 0.10,
            "information_delay": 3,
            "memory_decay": 0.97,
            "memory_size": 20,
        },
        "relationships": {
            "avg_degree": 6,
        },
        # v0.4: 群体系统（§8, §9, §10, §11, §12；enabled=false 用于 ablation §67）
        "groups": {
            "enabled": True,
            "formation": {"threshold": 0.55, "persistence_ticks": 20},
            "min_size": 3,
            "max_size": 200,
            "dissolve": {"cohesion_threshold": 0.25, "persistence_ticks": 15},
            "split": {"variance_threshold": 0.35, "cohesion_threshold": 0.45},
            "merge": {"distance_threshold": 0.45},
            "influence": {"anchor_pull": 0.002, "identity_gain": 0.01},
        },
        # v0.4: 身份系统（§53）
        "identity": {
            "enabled": True,
            "group_autonomy_decay": 0.005,
            "identity_decay": 0.95,
        },
        # v0.4: 信息系统（§32, §33, §36）
        "information": {
            "enabled": True,
            "distortion_rate": 0.02,
            "rumor_threshold": 0.35,
            "ingroup_boost": 1.3,
            "outgroup_penalty": 0.6,
            "cascade_ratio": 0.25,
        },
        # v0.4: 行为系统（§44）
        "behavior": {
            "enabled": True,
            "protest_threshold": 0.10,
            "conflict_threshold": 0.05,
            "migration_threshold": 0.08,
        },
        # v0.4: 社会地理（§47）
        "regions": {
            "list": ["A", "B", "C"],
            # v0.4.1 §31：不同资源禀赋
            "endowments": {
                "A": {"food": 1.0, "energy": 1.0, "jobs": 0.6},
                "B": {"food": 1.2, "energy": 0.8, "jobs": 0.5},
                "C": {"food": 0.8, "energy": 1.2, "jobs": 0.5},
            },
        },
        # v0.4.1: 资源安全层（§2–§6）
        "resource_security": {
            "critical": {"food": 20.0, "money": 15.0, "energy": 10.0, "information": 20.0},
            "scale": 0.5,
            "weights": {"survival": 0.35, "economic": 0.25, "activity": 0.20, "decision": 0.20},
        },
        # v0.4.1: 行为参数（§10–§14，可覆盖 actions.py 默认值）
        "actions": {
            "work": {"cost": {"energy": 2.0, "food": 0.02}},
            "migrate": {"cost": {"money": 30.0, "energy": 15.0}},
            "protest": {"cost": {"energy": 5.0}},
        },
        # v0.4.1: 群体资源池（§21–§24）
        # distribution 0.5：池子必须及时回流，否则成为食物黑洞（v0.4.1 实测教训）
        "group_resources": {
            "contribution_probability": 0.1,
            "distribution_probability": 0.5,
        },
        "events": {
            "frequency": 0.02,
            # v0.2: event lifecycle (§10, §11)
            "decay_rate": 0.03,
            "default_duration": 20,
            "resolution_threshold": 0.05,
        },
        "stability": {
            # v0.2: collapse / boundary detection (§26, §27)
            "collapse_variance_threshold": 0.02,
            "collapse_consecutive_ticks": 20,
            "boundary_warning_ratio": 0.30,
            "boundary_critical_ratio": 0.60,
            "temperature_critical": 0.85,
        },
        "model": {
            "provider": "rule_based",       # rule_based | openai | ollama | compatible
            "base_url": "http://127.0.0.1:11434/v1",
            "api_key": "",
            "model_name": "",
        },
        "axes": {
            "x": {"name": "经济自由 ↔ 经济管控", "positive": "经济自由", "negative": "经济管控"},
            "y": {"name": "自由 ↔ 权威", "positive": "权威", "negative": "自由"},
            "z": {"name": "个人主义 ↔ 集体主义", "positive": "个人主义", "negative": "集体主义"},
        },
    }


def load_config(path: Optional[Path] = None) -> dict:
    """Load a config file (YAML or JSON). Returns default config if absent."""
    if path is None:
        return default_society_config()
    path = Path(path)
    if not path.exists():
        return default_society_config()
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    cfg = default_society_config()
    _deep_merge(cfg, data)
    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base
