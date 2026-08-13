"""Simulation clock — independent system time with four layers.

tick → day → month → year. Ratios are configurable per society.

Default (matching the project plan §3):
    100 ticks  = 1 day
    30 days    = 1 month
    3000 ticks = 1 year
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Clock:
    tick: int = 0
    ticks_per_day: int = 100
    days_per_month: int = 30
    months_per_year: int = 12

    @property
    def day(self) -> int:
        return (self.tick // self.ticks_per_day) % self.days_per_month + 1

    @property
    def month(self) -> int:
        return (self.tick // (self.ticks_per_day * self.days_per_month)) % self.months_per_year + 1

    @property
    def year(self) -> int:
        return self.tick // (self.ticks_per_day * self.days_per_month * self.months_per_year)

    def advance(self, n: int = 1) -> None:
        self.tick += n

    def is_new_day(self, before: int) -> bool:
        return before // self.ticks_per_day != self.tick // self.ticks_per_day

    def snapshot(self) -> dict:
        return {
            "tick": self.tick,
            "day": self.day,
            "month": self.month,
            "year": self.year,
            "ticks_per_day": self.ticks_per_day,
        }
