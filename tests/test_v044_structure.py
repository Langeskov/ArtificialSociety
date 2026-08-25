"""v0.4.4 Population Structure & Labor Market tests.

Tests:
- Population structure normalization
- Sector assignment
- Skill computation
- Labor market operations
- Sector distribution convergence
- Structural change index
"""

import random
import pytest

from engine.economy.population import (
    SECTORS, DEFAULT_STRUCTURE, PRESETS,
    normalize_structure, assign_sector, compute_skills,
    PopulationSnapshot, SECTOR_PRODUCTIVITY, SECTOR_WAGE_MODIFIER,
)
from engine.economy.labor import LaborMarket, JobOpening, create_initial_jobs
from engine.economy.production_unit import ProductionUnit, create_initial_units, assign_workers_to_units


class TestPopulationStructure:
    """§2-3: Population structure basics."""

    def test_sectors_defined(self):
        """6个部门必须定义。"""
        assert len(SECTORS) == 6
        assert "primary" in SECTORS
        assert "unemployed" in SECTORS

    def test_default_structure_sums_to_one(self):
        """默认结构总和=1.0。"""
        total = sum(DEFAULT_STRUCTURE.values())
        assert abs(total - 1.0) < 0.01

    def test_normalize_structure(self):
        """归一化后总和=1.0。"""
        raw = {"primary": 0.3, "secondary": 0.6, "tertiary": 0.9}
        normed = normalize_structure(raw)
        assert abs(sum(normed.values()) - 1.0) < 0.01

    def test_presets_all_sum_to_one(self):
        """所有preset总和=1.0。"""
        for name, preset in PRESETS.items():
            total = sum(preset.values())
            assert abs(total - 1.0) < 0.01, f"Preset {name} sums to {total}"

    def test_sector_productivity_defined(self):
        """每个sector有productivity。"""
        for s in SECTORS:
            assert s in SECTOR_PRODUCTIVITY
            assert s in SECTOR_WAGE_MODIFIER


class TestSectorAssignment:
    """§6: Initial sector assignment."""

    def test_assign_sector_returns_valid(self):
        """返回值必须是合法sector。"""
        rng = random.Random(42)
        personality = {"conscientiousness": 0.5, "openness": 0.5}
        sector = assign_sector(personality, 0.5, {}, rng)
        assert sector in SECTORS

    def test_high_education_prefers_quaternary(self):
        """高教育→更可能quaternary。"""
        rng = random.Random(42)
        personality = {"conscientiousness": 0.5, "openness": 0.5}
        counts = {"quaternary": 0}
        for _ in range(1000):
            s = assign_sector(personality, 0.9, {}, rng)
            if s == "quaternary":
                counts["quaternary"] += 1
        assert counts["quaternary"] > 100  # Should be significantly higher than random

    def test_high_openness_prefers_quaternary(self):
        """高openness→更可能quaternary。"""
        rng = random.Random(42)
        personality = {"conscientiousness": 0.5, "openness": 0.9}
        counts = {"quaternary": 0}
        for _ in range(1000):
            s = assign_sector(personality, 0.5, {}, rng)
            if s == "quaternary":
                counts["quaternary"] += 1
        assert counts["quaternary"] > 50

    def test_agrarian_preset_favors_primary(self):
        """agrarian preset→更多primary。"""
        rng = random.Random(42)
        personality = {"conscientiousness": 0.5, "openness": 0.5}
        counts = {"primary": 0}
        for _ in range(1000):
            s = assign_sector(personality, 0.3, {}, rng, PRESETS["agrarian"])
            if s == "primary":
                counts["primary"] += 1
        assert counts["primary"] > 200  # Should be ~45%


class TestSkillComputation:
    """§7: Skill profile."""

    def test_skills_cover_all_sectors(self):
        """技能覆盖所有sector。"""
        rng = random.Random(42)
        personality = {"conscientiousness": 0.5, "openness": 0.5}
        skills = compute_skills("tertiary", personality, rng)
        for s in SECTORS:
            assert s in skills

    def test_assigned_sector_higher_skill(self):
        """assigned sector的技能应该更高。"""
        rng = random.Random(42)
        personality = {"conscientiousness": 0.5, "openness": 0.5}
        skills = compute_skills("secondary", personality, rng)
        assert skills["secondary"] > skills["primary"]
        assert skills["secondary"] > skills["quaternary"]

    def test_unemployed_skill_zero(self):
        """unemployed sector技能=0。"""
        rng = random.Random(42)
        personality = {"conscientiousness": 0.5, "openness": 0.5}
        skills = compute_skills("unemployed", personality, rng)
        assert skills["unemployed"] == 0.0

    def test_skills_in_range(self):
        """技能范围0~1。"""
        rng = random.Random(42)
        personality = {"conscientiousness": 0.5, "openness": 0.5}
        for sector in SECTORS:
            skills = compute_skills(sector, personality, rng)
            for s, v in skills.items():
                assert 0.0 <= v <= 1.0, f"{sector}/{s}={v}"


class TestLaborMarket:
    """§11-16: Labor market operations."""

    def test_create_initial_jobs(self):
        """初始job openings数量合理。"""
        rng = random.Random(42)
        agents = [type("A", (), {"alive": True, "sector": "primary", "skills": {"primary": 0.5}})() for _ in range(100)]
        jobs = create_initial_jobs(agents, DEFAULT_STRUCTURE, {}, rng)
        assert len(jobs) > 50  # Should have many jobs

    def test_job_opening_fields(self):
        """Job opening有所有必要字段。"""
        job = JobOpening(id="test", sector="primary", occupation="farmer", required_skill=0.3, wage=1.0)
        assert job.sector == "primary"
        assert not job.filled

    def test_labor_market_compute_wage(self):
        """工资计算合理。"""
        market = LaborMarket()
        market.sector_demand = {"primary": 1.0, "secondary": 1.0, "tertiary": 1.0, "quaternary": 1.0, "public": 1.0, "unemployed": 0.0}
        wage = market.compute_wage("primary", 0.5)
        assert wage > 0
        assert wage < 10

    def test_labor_market_hire(self):
        """hiring能匹配unemployed agents。"""
        rng = random.Random(42)
        market = LaborMarket()
        market.job_openings = [
            JobOpening(id=f"j{i}", sector="primary", occupation="farmer", required_skill=0.2, wage=1.0)
            for i in range(10)
        ]
        agents = []
        for i in range(5):
            a = type("A", (), {
                "id": f"a{i}", "alive": True, "sector": "unemployed",
                "skills": {"primary": 0.5, "secondary": 0.1, "tertiary": 0.1, "quaternary": 0.0, "public": 0.0, "unemployed": 0.0}
            })()
            agents.append(a)
        hires = market.hire(agents, rng)
        assert len(hires) > 0


class TestPopulationSnapshot:
    """§30, §37: Snapshot and structural change."""

    def test_snapshot_from_agents(self):
        """从agents计算分布。"""
        agents = []
        for sector in ["primary", "primary", "secondary", "tertiary"]:
            a = type("A", (), {"alive": True, "sector": sector})()
            agents.append(a)
        snap = PopulationSnapshot.from_agents(agents)
        assert abs(snap.primary - 0.5) < 0.01
        assert abs(snap.secondary - 0.25) < 0.01

    def test_structural_change_zero_for_same(self):
        """相同结构→change=0。"""
        s1 = PopulationSnapshot(primary=0.5, secondary=0.5)
        s2 = PopulationSnapshot(primary=0.5, secondary=0.5)
        assert s1.structural_change(s2) == 0.0

    def test_structural_change_nonzero(self):
        """不同结构→change>0。"""
        s1 = PopulationSnapshot(primary=0.5, secondary=0.5)
        s2 = PopulationSnapshot(primary=0.3, secondary=0.7)
        assert s1.structural_change(s2) > 0.0


class TestSectorProductivity:
    """§24: Sector productivity modifiers."""

    def test_quaternary_highest_productivity(self):
        """quaternary生产率最高。"""
        assert SECTOR_PRODUCTIVITY["quaternary"] > SECTOR_PRODUCTIVITY["primary"]

    def test_secondary_higher_than_primary(self):
        """secondary生产率>primary。"""
        assert SECTOR_PRODUCTIVITY["secondary"] > SECTOR_PRODUCTIVITY["primary"]


class TestSectorWageModifier:
    """§15: Sector wage modifiers."""

    def test_quaternary_highest_wage(self):
        """quaternary工资最高。"""
        assert SECTOR_WAGE_MODIFIER["quaternary"] > SECTOR_WAGE_MODIFIER["primary"]

    def test_unemployed_zero_wage(self):
        """unemployed工资=0。"""
        assert SECTOR_WAGE_MODIFIER["unemployed"] == 0.0

class TestProductionUnit:
    """§17-26: Production units."""

    def test_create_initial_units(self):
        """Initial units created proportional to sector size."""
        rng = random.Random(42)
        agents = [type("A", (), {"alive": True})() for _ in range(100)]
        units = create_initial_units(agents, DEFAULT_STRUCTURE, ["A", "B", "C"], {}, rng)
        assert len(units) > 0
        sectors = set(u.sector for u in units)
        assert "primary" in sectors
        assert "tertiary" in sectors

    def test_unit_labor_factor(self):
        """labor_factor = workers / capacity."""
        u = ProductionUnit(id="test", sector="primary", worker_capacity=10)
        assert u.labor_factor() == 0.0
        u.worker_ids = ["a1", "a2", "a3", "a4", "a5"]
        lf = u.labor_factor()
        assert abs(lf - 0.5) < 0.01

    def test_unit_output_proportional_to_labor(self):
        """More workers = more output."""
        u1 = ProductionUnit(id="u1", sector="primary", worker_capacity=10, status="ACTIVE")
        u2 = ProductionUnit(id="u2", sector="primary", worker_capacity=10, status="ACTIVE")
        u1.worker_ids = ["a1"]
        u2.worker_ids = ["a1", "a2", "a3", "a4", "a5"]
        out1 = u1.compute_output(1.0)
        out2 = u2.compute_output(1.0)
        assert out2.get("food", 0) > out1.get("food", 0)

    def test_unit_closed_no_output(self):
        """Closed units produce nothing."""
        u = ProductionUnit(id="test", sector="primary", status="CLOSED", worker_capacity=10)
        u.worker_ids = ["a1", "a2"]
        assert u.compute_output(1.0) == {}

    def test_assign_workers_to_units(self):
        """Employed agents get assigned to units."""
        rng = random.Random(42)
        agents = []
        for i in range(20):
            a = type("A", (), {"id": f"a{i}", "alive": True, "sector": "primary" if i < 10 else "tertiary"})()
            agents.append(a)
        units = [
            ProductionUnit(id="u1", sector="primary", worker_capacity=15, status="ACTIVE"),
            ProductionUnit(id="u2", sector="tertiary", worker_capacity=15, status="ACTIVE"),
        ]
        assignments = assign_workers_to_units(agents, units, rng)
        assert len(assignments) == 20

    def test_sector_input_needs(self):
        """Each sector has input requirements."""
        for sector in ["primary", "secondary", "tertiary", "quaternary", "public"]:
            u = ProductionUnit(id="test", sector=sector, worker_capacity=10, status="ACTIVE")
            u.worker_ids = ["a1"]
            inputs = u.compute_input_needs(1.0)
            assert "labor" in inputs or "energy" in inputs


class TestSectorIntegration:
    """Integration: sector assignment + production units + simulation."""

    def test_simulation_with_sectors(self):
        """Simulation runs with sector-assigned agents."""
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config
        cfg = default_society_config()
        cfg['population']['count'] = 50
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)
        eng.step(s.society_id, ticks=50)
        alive = [a for a in s.agents if a.alive]
        assert len(alive) > 0
        # Check sectors are assigned
        sectors = set(a.sector for a in alive)
        assert len(sectors) > 1

    def test_structure_snapshot_after_simulation(self):
        """PopulationSnapshot works after simulation."""
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config
        cfg = default_society_config()
        cfg['population']['count'] = 50
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)
        snap = PopulationSnapshot.from_agents(s.agents)
        total = sum(snap.to_dict().values())
        assert abs(total - 1.0) < 0.01



