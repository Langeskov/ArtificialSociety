"""Agent resources — numeric pools that drive behavior (§11, §12).

Initial six resources; extensible. Resources are the primary driver of
political drift: scarcity pushes survival behavior, affluence relaxes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Optional

RESOURCE_KEYS: tuple[str, ...] = (
    "money",
    "food",
    "energy",
    "property",
    "influence",
    "information",
)

LABELS: dict[str, str] = {
    "money": "Money",
    "food": "Food",
    "energy": "Energy",
    "property": "Property",
    "influence": "Influence",
    "information": "Information",
}

# Low thresholds: when a resource drops below this, the agent enters pressure.
SURVIVAL_THRESHOLD = {"food": 20.0, "money": 15.0, "energy": 10.0}


@dataclass
class Resources:
    values: dict = field(default_factory=dict)       # available（可用资源）
    reserved: dict = field(default_factory=dict)      # reserved（已预扣未结算，§7）

    def __post_init__(self) -> None:
        for k in RESOURCE_KEYS:
            self.values.setdefault(k, 0.0)
            self.reserved.setdefault(k, 0.0)

    def __getitem__(self, key: str) -> float:
        return self.values.get(key, 0.0)

    def set(self, key: str, value: float) -> None:
        self.values[key] = value if value > 0.0 else 0.0

    def add(self, key: str, value: float) -> None:
        v = self.values
        nv = v[key] + value
        v[key] = nv if nv > 0.0 else 0.0

    # -- commitment / transaction primitives (§7, §8) ----------------------
    def available(self, key: str) -> float:
        return self.values.get(key, 0.0)

    def reserve(self, key: str, amount: float) -> bool:
        """从 available 预扣到 reserved；不足则失败（返回 False）。"""
        if amount <= 0:
            return True
        if self.values.get(key, 0.0) < amount:
            return False
        self.values[key] -= amount
        self.reserved[key] = self.reserved.get(key, 0.0) + amount
        return True

    def commit(self, key: str, amount: float) -> None:
        """结算：从 reserved 中实际扣除（行为成本，§60 commit once）。"""
        self.reserved[key] = max(0.0, self.reserved.get(key, 0.0) - amount)

    def release(self, key: str, amount: float) -> None:
        """回滚：reserved 退回 available（交易失败恢复，§60）。"""
        amt = min(amount, self.reserved.get(key, 0.0))
        self.reserved[key] = self.reserved.get(key, 0.0) - amt
        self.values[key] = self.values.get(key, 0.0) + amt

    def as_dict(self) -> dict:
        return {k: round(v, 2) for k, v in self.values.items()}

    def total(self) -> float:
        return sum(self.values.values())

    def is_starving(self) -> bool:
        return self.values["food"] < SURVIVAL_THRESHOLD["food"]

    def is_broke(self) -> bool:
        return self.values["money"] < SURVIVAL_THRESHOLD["money"]


def generate(initial: Optional[dict], rng: random.Random) -> Resources:
    """Generate initial resources from a config template.

    initial: {"money": {"mean": 500, "sigma": 200}, "food": {...}, ...}
    or a flat number, which is treated as the mean with default sigma.
    """
    res = Resources()
    for k in RESOURCE_KEYS:
        spec = (initial or {}).get(k)
        if isinstance(spec, dict):
            mean = spec.get("mean", 100.0)
            sigma = spec.get("sigma", mean * 0.4)
            val = max(0.0, rng.gauss(mean, sigma))
        elif isinstance(spec, (int, float)):
            val = max(0.0, rng.gauss(spec, spec * 0.4))
        else:
            val = max(0.0, rng.gauss(100.0, 40.0))
        res.values[k] = round(val, 2)
    return res
