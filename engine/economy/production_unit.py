"""Production Unit (v0.4.4 §17-26).

Production Units represent organized production: farms, factories, offices, etc.
Each unit has workers, inputs, outputs, capacity, and lifecycle.

Key: production happens at unit level, not individual agent level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import random

from .population import SECTORS, SECTOR_PRODUCTIVITY


# Unit lifecycle states (§19)
UNIT_STATES = ("FORMING", "ACTIVE", "CONTRACTING", "CLOSED")

# Unit sizes (§21)
UNIT_SIZES = {
    "small":  {"capacity": 10,  "overhead": 0.05},
    "medium": {"capacity": 40,  "overhead": 0.08},
    "large":  {"capacity": 100, "overhead": 0.12},
}

# Input-output matrix (§28): what each sector needs as input
SECTOR_INPUTS = {
    "primary":    {"energy": 0.3, "labor": 1.0},
    "secondary":  {"energy": 0.5, "labor": 1.0, "raw_material": 0.3},
    "tertiary":   {"energy": 0.2, "labor": 1.0, "goods": 0.2},
    "quaternary": {"energy": 0.3, "labor": 1.0, "information": 0.2},
    "public":     {"energy": 0.1, "labor": 1.0, "money": 0.3},
}

# What each sector produces
SECTOR_OUTPUTS = {
    "primary":    {"food": 1.0, "raw_material": 0.3},
    "secondary":  {"goods": 1.0, "energy": 0.1},
    "tertiary":   {"services": 1.0},
    "quaternary": {"information": 1.0, "services": 0.3},
    "public":     {"services": 0.5, "order": 0.5},
}


@dataclass
class ProductionUnit:
    """A production unit: farm, factory, office, etc. (§18)."""
    id: str
    region: str = "A"
    sector: str = "primary"
    unit_type: str = "generic"
    size: str = "medium"
    status: str = "ACTIVE"
    owner_type: str = "individual"   # individual / group / public
    owner_id: str = ""
    # Workers
    worker_ids: List[str] = field(default_factory=list)
    worker_capacity: int = 40
    # Production
    capacity: float = 1.0            # 0~1
    productivity: float = 1.0
    efficiency: float = 1.0
    # Economics
    wage_bill: float = 0.0
    revenue: float = 0.0

    def labor_factor(self) -> float:
        """Labor factor = workers / capacity (§23)."""
        if self.worker_capacity <= 0:
            return 0.0
        ratio = len(self.worker_ids) / self.worker_capacity
        # Diminishing returns above capacity
        if ratio > 1.0:
            return 1.0 / ratio
        return ratio

    def compute_output(self, dt_hours: float, input_availability: float = 1.0) -> Dict[str, float]:
        """Compute production output (§22).
        
        output = base_capacity * labor_factor * input_factor * skill_factor * efficiency * sector_productivity * dt_hours
        """
        if self.status == "CLOSED":
            return {}

        lf = self.labor_factor()
        sp = SECTOR_PRODUCTIVITY.get(self.sector, 1.0)
        base = self.capacity * lf * input_availability * self.efficiency * sp
        if base <= 0:
            return {}

        outputs = SECTOR_OUTPUTS.get(self.sector, {})
        return {res: qty * base * dt_hours for res, qty in outputs.items()}

    def compute_input_needs(self, dt_hours: float) -> Dict[str, float]:
        """Compute required inputs for full production (§25)."""
        inputs = SECTOR_INPUTS.get(self.sector, {})
        lf = self.labor_factor()
        return {res: qty * self.capacity * lf * dt_hours for res, qty in inputs.items()}


def create_initial_units(
    agents: List,
    structure: Dict[str, float],
    regions: List[str],
    cfg: Dict,
    rng: random.Random,
) -> List[ProductionUnit]:
    """Create initial production units proportional to sector size."""
    units = []
    n = len(agents)
    unit_cfg = cfg.get("production_units", {})
    agents_per_unit = unit_cfg.get("agents_per_unit", 20)

    uid = 0
    for sector, prop in structure.items():
        if sector == "unemployed":
            continue
        n_units = max(1, int(n * prop / agents_per_unit))
        for i in range(n_units):
            size = rng.choice(["small", "medium", "large"])
            cap = UNIT_SIZES[size]["capacity"]
            region = rng.choice(regions)
            owner_type = "public" if sector == "public" else rng.choice(["individual", "group"])
            units.append(ProductionUnit(
                id=f"unit_{uid}",
                region=region,
                sector=sector,
                unit_type=f"{sector}_unit",
                size=size,
                worker_capacity=cap,
                owner_type=owner_type,
                capacity=0.8 + rng.random() * 0.2,
            ))
            uid += 1
    return units


def assign_workers_to_units(
    agents: List,
    units: List[ProductionUnit],
    rng: random.Random,
) -> Dict[str, str]:
    """Assign employed agents to production units (§6).
    
    Returns {agent_id: unit_id}.
    """
    assignments = {}
    # Group units by sector
    units_by_sector = {}
    for u in units:
        if u.status != "ACTIVE":
            continue
        units_by_sector.setdefault(u.sector, []).append(u)

    for a in agents:
        if not a.alive:
            continue
        sector = getattr(a, "sector", "unemployed")
        if sector == "unemployed":
            continue
        sector_units = units_by_sector.get(sector, [])
        if not sector_units:
            continue
        # Find unit with space
        for u in sector_units:
            if len(u.worker_ids) < u.worker_capacity:
                u.worker_ids.append(a.id)
                assignments[a.id] = u.id
                break

    return assignments
