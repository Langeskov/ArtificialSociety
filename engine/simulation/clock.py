"""Simulation clock — unified simulation time (v0.4.2 §2–§4).

All subsystems must use the same time understanding:
    100 ticks = 1 simulated day (configurable via ticks_per_day)

v0.4.2 adds:
    simulated_days  (float) — continuous day count (tick / ticks_per_day)
    dt_days         (float) — delta-time in days per tick (1 / ticks_per_day)
    simulated_hours (float) — continuous hour count
    hour_of_day     (int)   — 0–23 within the current simulated day
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
            "simulated_days": round(self.simulated_days, 4),
            "simulated_hours": round(self.simulated_hours, 2),
            "hour_of_day": self.hour_of_day,
            "dt_days": self.dt_days,
        }

    @property
    def simulated_days(self) -> float:
        """Continuous simulated day count (v0.4.2 §4): tick 2769 → 27.69 days."""
        return self.tick / self.ticks_per_day

    @property
    def dt_days(self) -> float:
        """Delta-time in days per tick (v0.4.2 §6): 1 / ticks_per_day."""
        return 1.0 / self.ticks_per_day

    @property
    def simulated_hours(self) -> float:
        """Continuous simulated hour count."""
        return self.simulated_days * 24.0

    @property
    def hour_of_day(self) -> int:
        """Current hour within the simulated day (0–23)."""
        return int((self.tick % self.ticks_per_day) / self.ticks_per_day * 24)
