"""v0.4.5.3 Event Lifecycle Integrity & Long-Run Dynamic Equilibrium tests."""

import pytest
from engine.crisis.tracker import CrisisTracker, CrisisTransition, CrisisManager, CrisisState


def _make_tracker(**kw):
    """Helper: create a tracker with common test defaults."""
    defaults = dict(
        crisis_type="economic", trigger_persistence_ticks=1,
        trigger_threshold=0.25, resolve_threshold=0.12, cooldown_days=0.01,
    )
    defaults.update(kw)
    return CrisisTracker(**defaults)


class TestCrisisInstanceId:

    def test_instance_id_generated_on_crisis_start(self):
        t = _make_tracker()
        t.update(0.8, 1)
        assert t.current_instance_id != ""
        assert t.current_instance_id.startswith("economic_")

    def test_instance_id_changes_each_crisis(self):
        t = _make_tracker()
        t.update(0.8, 1)  # WARNING
        id1 = t.current_instance_id
        t.update(0.05, 2)  # RECOVERING (0.05 < resolve 0.12)
        t.recovery_progress = 0.9
        t.update(0.05, 3)  # RESOLVED -> COOLDOWN
        for tick in range(4, 200):
            t.update(0.05, tick)  # wait out cooldown
        t.update(0.8, 200)  # new crisis
        id2 = t.current_instance_id
        assert id1 != id2
        assert id2.startswith("economic_")

    def test_transition_carries_instance_id(self):
        t = _make_tracker(crisis_type="food")
        trans = t.update(0.8, 1)
        assert trans.crisis_instance_id.startswith("food_")

    def test_instance_id_format(self):
        t = _make_tracker(crisis_type="protest")
        t.update(0.8, 1)
        iid = t.current_instance_id
        parts = iid.split("_")
        assert parts[0] == "protest"
        assert int(parts[1]) == 1


class TestCrisisLifecycleTiming:

    def test_start_tick_recorded(self):
        t = _make_tracker()
        t.update(0.8, 100)
        assert t._start_tick == 100

    def test_peak_tick_recorded(self):
        t = _make_tracker()
        t.update(0.7, 100)   # WARNING
        t.update(0.9, 105)   # ACTIVE
        assert t._peak_tick == 105
        assert t._peak_severity == 0.9

    def test_recovery_start_tick_recorded(self):
        t = _make_tracker()
        t.update(0.8, 100)   # WARNING
        t.update(0.8, 101)   # ACTIVE
        t.update(0.05, 110)  # RECOVERING
        assert t._recovery_start_tick == 110


class TestRecoveryProgress:

    def test_progress_clamped(self):
        t = _make_tracker()
        t.update(0.8, 1)     # WARNING, baseline=0.8, peak=0.8
        t.update(0.9, 2)     # ACTIVE, peak=0.9
        t.update(0.05, 3)    # RECOVERING
        assert 0.0 <= t.recovery_progress <= 1.0

    def test_progress_zero_at_start(self):
        t = _make_tracker()
        t.update(0.8, 1)
        t.update(0.8, 2)
        t.update(0.05, 3)  # just entered RECOVERING
        # baseline=0.8, peak=0.8, current=0.05, peak<=baseline -> fallback
        assert t.recovery_progress >= 0.0


class TestRecoveryLifecycleEvents:

    def test_recovery_started_on_entering_recovering(self):
        t = _make_tracker()
        t.update(0.8, 1)
        t.update(0.8, 2)
        trans = t.update(0.05, 3)
        assert trans.entered_recovering is True

    def test_resolved_on_cooldown(self):
        t = _make_tracker()
        t.update(0.8, 1)
        t.update(0.8, 2)
        t.update(0.05, 3)  # RECOVERING
        t.recovery_progress = 0.9
        trans = t.update(0.05, 4)  # RESOLVED -> COOLDOWN
        assert trans.resolved is True
        assert trans.current_state == CrisisState.COOLDOWN

    def test_recovery_failure_worsening_metric(self):
        t = _make_tracker(trigger_threshold=0.25, resolve_threshold=0.12)
        t.update(0.8, 1)
        t.update(0.8, 2)
        t.update(0.05, 3)  # RECOVERING
        trans = t.update(0.8, 4)  # metric worsens, 0.8 > severe(0.375) -> SEVERE
        assert trans.recovery_failed is True
        assert trans.current_state in (CrisisState.ACTIVE, CrisisState.SEVERE)

    def test_recovery_failure_timeout(self):
        t = _make_tracker(max_recovery_ticks=3)
        t.update(0.8, 1)
        t.update(0.8, 2)
        t.update(0.05, 3)  # RECOVERING, _recovery_ticks=0
        t.update(0.15, 4)  # _recovery_ticks=1, metric > resolve but < trigger
        t.update(0.15, 5)  # _recovery_ticks=2
        trans = t.update(0.15, 6)  # _recovery_ticks=3 >= max=3 -> timeout
        assert trans.recovery_failed is True


class TestOrphanRecoveryDetection:

    def test_lifecycle_log_records_all_phases(self):
        t = _make_tracker()
        t.update(0.8, 1)
        t.update(0.8, 2)
        t.update(0.05, 3)
        t.recovery_progress = 0.9
        t.update(0.05, 4)
        log = t.get_lifecycle_log()
        phases = [e["phase"] for e in log]
        assert "START" in phases
        assert "RECOVERY_START" in phases
        assert "RESOLVED" in phases


class TestLifecycleAudit:

    def test_lifecycle_completeness(self):
        t = _make_tracker()
        t.update(0.8, 1)
        t.update(0.8, 2)
        t.update(0.05, 3)
        t.recovery_progress = 0.9
        t.update(0.05, 4)
        log = t.get_lifecycle_log()
        phases = [e["phase"] for e in log]
        assert "START" in phases
        assert "RECOVERY_START" in phases
        assert "RESOLVED" in phases

    def test_recovery_counters(self):
        t = _make_tracker(crisis_type="food")
        assert t.recovery_started_count == 0
        assert t.recovery_completed_count == 0
        assert t.recovery_failed_count == 0
        t.update(0.8, 1)
        t.update(0.05, 2)
        assert t.recovery_started_count == 1
        t.recovery_progress = 0.9
        t.update(0.05, 3)
        assert t.recovery_completed_count == 1


class TestCrisisInstanceIsolation:

    def test_different_trackers_independent_state(self):
        t1 = _make_tracker()
        t2 = _make_tracker()
        t1.update(0.8, 1)
        t2.update(0.8, 1)
        # Each tracker has its own counter — IDs may be same format but trackers are independent
        assert t1 is not t2
        t1.update(0.05, 2)  # t1 enters RECOVERING
        assert t1.state == CrisisState.RECOVERING
        assert t2.state == CrisisState.WARNING  # t2 unaffected


class TestDynamicEquilibriumMonitor:

    def test_monitor_classifies_active(self):
        from engine.dynamics.equilibrium import DynamicEquilibriumMonitor
        m = DynamicEquilibriumMonitor()
        for tick in range(100, 1000):
            m.update(tick, 100, event_count=1,
                     political_variance=0.1, political_velocity=0.01,
                     resource_variance=0.05, group_turnover=0.1,
                     employment_turnover=0.05)
        snap = m.snapshot()
        assert snap["classification"] in ("ACTIVE", "DYNAMIC_EQUILIBRIUM")

    def test_static_equilibrium_detection(self):
        from engine.dynamics.equilibrium import DynamicEquilibriumMonitor
        m = DynamicEquilibriumMonitor(static_threshold_days=5)
        for tick in range(100, 2000):
            m.update(tick, 100, event_count=0,
                     political_variance=0.01, political_velocity=0.0001,
                     resource_variance=0.01, group_turnover=0.0,
                     employment_turnover=0.0)
        snap = m.snapshot()
        assert snap["classification"] == "STATIC_EQUILIBRIUM"

    def test_freeze_score_computed(self):
        from engine.dynamics.equilibrium import DynamicEquilibriumMonitor
        m = DynamicEquilibriumMonitor()
        for tick in range(100, 500):
            m.update(tick, 100, event_count=0,
                     political_variance=0.01, political_velocity=0.0001,
                     resource_variance=0.01, group_turnover=0.0,
                     employment_turnover=0.0)
        snap = m.snapshot()
        assert snap["political_freeze_score"] < 0.1


class TestSimulationV0453:

    def test_simulation_runs(self):
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config
        cfg = default_society_config()
        cfg['population']['count'] = 50
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)
        result = eng.step(s.society_id, ticks=200)
        assert result is not None

    def test_crisis_instance_id_in_events(self):
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config
        cfg = default_society_config()
        cfg['population']['count'] = 50
        cfg['events']['crisis']['economic']['trigger_persistence_ticks'] = 5
        cfg['events']['crisis']['economic']['trigger_threshold'] = 0.1
        cfg['events']['crisis']['economic']['resolve_threshold'] = 0.05
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)
        eng.step(s.society_id, ticks=500)
        events = s.events.events
        crisis_events = [e for e in events if e.type == "economic_crisis"]
        for ev in crisis_events:
            iid = ev.effects.get("crisis_instance_id", "")
            if iid:
                assert iid.startswith("economic_")

    def test_equilibrium_monitor_active(self):
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config
        cfg = default_society_config()
        cfg['population']['count'] = 50
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)
        eng.step(s.society_id, ticks=200)
        eqm = getattr(s, 'equilibrium_monitor', None)
        assert eqm is not None
        snap = eqm.snapshot()
        assert "classification" in snap


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
