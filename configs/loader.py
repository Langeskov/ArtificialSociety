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
            "tax_rate": 0.08,
            "redistribution": 0.5,
            # v0.2: resource production / recovery (§14, §15)
            "food_production": 0.12,       # per-agent food income per tick
            "energy_production": 0.06,     # per-agent energy income per tick
            "food_critical": 20.0,         # below this → survival/recovery mode
            "recovery_rate": 0.05,         # production recovery per tick after shocks
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
            "noise": 0.004,
            # v0.3: 三轴独立驱动力 + 弱耦合 (§7, §8, §9)
            "authority_dynamics_strength": 0.03,
            "community_dynamics_strength": 0.02,
            "axis_weights": {"x": 1.0, "y": 1.0, "z": 1.0},
            "coupling": {"xy": 0.03, "xz": -0.02, "yx": 0.02, "yz": 0.03, "zx": -0.02, "zy": 0.02},
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
