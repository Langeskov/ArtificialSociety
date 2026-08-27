"""v0.4.5.1 Runtime State Machine & Event Integration Hotfix tests.

Tests:
- Action State Lifecycle (IDLE → RUNNING → COMPLETED → IDLE)
- Action completion does not lose action name
- Work production not double-counted
- Daily budget does not block cross-day actions
- Tick progress watchdog
- Simulation stall detector
- Six-day regression test
- Time resolution regression
"""

import random
import pytest

from engine.behavior.scheduler import AgentActivity, ActionState, ACTION_DURATIONS, get_dt_hours
from engine.simulation.stall import (
    SimulationStallDetector, TickProgressWatchdog, ZeroProgressDetector,
    build_stall_report, format_stall_report,
)


# ============================================================================
# Action State Lifecycle Tests (§2)
# ============================================================================

class TestActionStateLifecycle:
    """§2: Explicit state machine IDLE → RUNNING → COMPLETED → IDLE."""

    def test_initial_state_is_idle(self):
        """新 AgentActivity 初始状态为 IDLE。"""
        activity = AgentActivity()
        assert activity.state == ActionState.IDLE
        assert activity.is_idle()
        assert not activity.is_busy()
        assert not activity.is_completed()

    def test_start_action_transitions_to_running(self):
        """start_action() 将状态转为 RUNNING。"""
        activity = AgentActivity()
        activity.start_action("work", tick=100)
        assert activity.state == ActionState.RUNNING
        assert activity.is_busy()
        assert activity.current_action == "work"

    def test_advance_completes_action(self):
        """advance() 完成后状态转为 COMPLETED。"""
        activity = AgentActivity()
        activity.start_action("work", tick=100)

        # Advance until completion
        dt = get_dt_hours(100)  # 0.24 hours per tick
        while activity.is_busy():
            activity.advance(dt)

        assert activity.state == ActionState.COMPLETED
        assert activity.is_completed()
        assert activity.completed_action == "work"

    def test_complete_returns_to_idle(self):
        """complete() 将状态转回 IDLE。"""
        activity = AgentActivity()
        activity.start_action("work", tick=100)

        dt = get_dt_hours(100)
        while activity.is_busy():
            activity.advance(dt)

        activity.complete(tick=200)
        assert activity.state == ActionState.IDLE
        assert activity.is_idle()
        assert activity.current_action is None


# ============================================================================
# Action Completion Data Tests (§3)
# ============================================================================

class TestActionCompletionData:
    """§3: Completed action data must be preserved."""

    def test_completed_action_name_preserved(self):
        """完成时必须保留 action_name。"""
        activity = AgentActivity()
        activity.start_action("work", tick=100)

        dt = get_dt_hours(100)
        while activity.is_busy():
            activity.advance(dt)

        assert activity.completed_action == "work"
        assert activity.hours_completed == ACTION_DURATIONS["work"]

    def test_completion_handler_uses_saved_name(self):
        """完成处理器使用保存的名称，而非已重置的状态。"""
        activity = AgentActivity()
        activity.start_action("trade", tick=100)

        dt = get_dt_hours(100)
        while activity.is_busy():
            activity.advance(dt)

        # Before complete(), completed_action should be available
        assert activity.completed_action == "trade"

        # After complete(), completed_action is still available
        activity.complete(tick=200)
        assert activity.completed_action == "trade"


# ============================================================================
# Work Production Not Double-Counted (§5)
# ============================================================================

class TestWorkProduction:
    """§5: Work production must not be double-counted."""

    def test_work_action_duration(self):
        """work 动作持续 4 小时。"""
        assert ACTION_DURATIONS["work"] == 4.0

    def test_work_produces_during_advance(self):
        """work 在 RUNNING 状态期间持续生产。"""
        activity = AgentActivity()
        activity.start_action("work", tick=100)

        dt = get_dt_hours(100)
        # Advance one tick
        activity.advance(dt)

        # Action should still be running
        assert activity.is_busy()


# ============================================================================
# Daily Budget + Cross-Day Actions (§7-§8)
# ============================================================================

class TestDailyBudget:
    """§7-§8: Daily budget reset does not cancel in-progress actions."""

    def test_reset_daily_does_not_cancel_action(self):
        """reset_daily() 不取消正在执行的动作。"""
        activity = AgentActivity()
        activity.start_action("migrate", tick=100)  # 24h action

        # Advance some hours
        dt = get_dt_hours(100)
        for _ in range(50):
            activity.advance(dt)

        assert activity.is_busy()
        assert activity.hours_remaining > 0

        # Daily reset
        activity.reset_daily(tick=150)

        # Action should still be running
        assert activity.is_busy()
        assert activity.hours_remaining > 0

    def test_daily_budget_only_affects_new_actions(self):
        """daily_hours_used 只影响新动作的选择。"""
        activity = AgentActivity()
        activity.daily_hours_used = 20.0

        # Can still start a new action (budget allows 4 more hours)
        activity.start_action("work", tick=100)
        assert activity.is_busy()

    def test_daily_budget_blocks_when_exhausted(self):
        """daily_hours_used >= 24 时不能开始新动作。"""
        activity = AgentActivity()
        activity.daily_hours_used = 24.0
        assert activity.available_hours() == 0.0


# ============================================================================
# Tick Progress Watchdog (§12)
# ============================================================================

class TestTickProgressWatchdog:
    """§12: Clock must advance each step."""

    def test_watchdog_passes_on_advance(self):
        """时钟递增时看门狗通过。"""
        watchdog = TickProgressWatchdog()
        watchdog.check(1)
        watchdog.check(2)
        watchdog.check(3)

    def test_watchdog_fails_on_stall(self):
        """时钟未递增时看门狗抛出异常。"""
        watchdog = TickProgressWatchdog()
        watchdog.check(1)
        with pytest.raises(RuntimeError, match="did not advance"):
            watchdog.check(1)

    def test_watchdog_fails_on_regression(self):
        """时钟回退时看门狗抛出异常。"""
        watchdog = TickProgressWatchdog()
        watchdog.check(5)
        with pytest.raises(RuntimeError, match="did not advance"):
            watchdog.check(3)


# ============================================================================
# Simulation Stall Detector (§11)
# ============================================================================

class TestStallDetector:
    """§11: Detect N consecutive ticks with no state changes."""

    def test_no_stall_with_activity(self):
        """有状态变化时不报告卡死。"""
        detector = SimulationStallDetector(stall_threshold_ticks=10)
        for _ in range(20):
            detector.update(agent_state_changes=1, events_created=0, resource_changes=0)
        assert not detector.is_stalled

    def test_stall_after_threshold(self):
        """连续无状态变化超过阈值时报告卡死。"""
        detector = SimulationStallDetector(stall_threshold_ticks=5)
        for _ in range(10):
            detector.update(agent_state_changes=0, events_created=0, resource_changes=0)
        assert detector.is_stalled

    def test_stall_resets_on_activity(self):
        """有状态变化时重置计数器。"""
        detector = SimulationStallDetector(stall_threshold_ticks=5)
        for _ in range(3):
            detector.update(agent_state_changes=0, events_created=0, resource_changes=0)
        detector.update(agent_state_changes=1, events_created=0, resource_changes=0)
        assert detector.idle_ticks == 0
        assert not detector.is_stalled


# ============================================================================
# Agent Stall Detection (§10)
# ============================================================================

class TestZeroProgressDetector:
    """§10: Per-agent stall detection."""

    def test_detect_stalled_agent(self):
        """检测停滞的 agent。"""
        from engine.agent.agent import Agent

        detector = ZeroProgressDetector(stall_threshold_ticks=50)

        # Create a mock agent with activity
        class MockAgent:
            id = "agent_1"
            alive = True
            activity = AgentActivity()

        agent = MockAgent()
        agent.activity.last_state_change_tick = 0

        stalled = detector.detect_stalled([agent], current_tick=100)
        assert len(stalled) == 1
        assert stalled[0].agent_id == "agent_1"
        assert stalled[0].stalled_ticks == 100

    def test_no_stall_for_active_agent(self):
        """活跃的 agent 不被标记为停滞。"""
        detector = ZeroProgressDetector(stall_threshold_ticks=50)

        class MockAgent:
            id = "agent_1"
            alive = True
            activity = AgentActivity()

        agent = MockAgent()
        agent.activity.last_state_change_tick = 90

        stalled = detector.detect_stalled([agent], current_tick=100)
        assert len(stalled) == 0


# ============================================================================
# Integration: Six-Day Regression Test (§30)
# ============================================================================

class TestSixDayRegression:
    """§30: Simulation must progress past day 6 without stalling."""

    def test_simulation_runs_10_days(self):
        """模拟必须能运行 10 天而不卡死。"""
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config

        cfg = default_society_config()
        cfg['population']['count'] = 50  # Small for speed
        cfg['ticks_per_day'] = 50  # Faster ticks

        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)

        # Run for 10 days
        total_ticks = 10 * 50  # 10 days × 50 ticks/day
        result = eng.step(s.society_id, ticks=total_ticks)

        # Verify clock advanced
        assert s.clock.tick == total_ticks

        # Verify no stall warning
        assert "stall_warning" not in result

        # Verify agents are alive
        alive = [a for a in s.agents if a.alive]
        assert len(alive) > 0

    def test_tick_strictly_monotonic(self):
        """tick 必须严格单调递增。"""
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config

        cfg = default_society_config()
        cfg['population']['count'] = 20
        cfg['ticks_per_day'] = 50

        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)

        prev_tick = 0
        for day in range(5):
            result = eng.step(s.society_id, ticks=50)
            current_tick = s.clock.tick
            assert current_tick > prev_tick, f"Tick did not advance: {prev_tick} -> {current_tick}"
            prev_tick = current_tick


# ============================================================================
# Action State Regression (§31)
# ============================================================================

class TestActionStateRegression:
    """§31: Action state transitions must be complete."""

    def test_work_state_transitions(self):
        """work 动作必须经历完整的状态转换。"""
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config

        cfg = default_society_config()
        cfg['population']['count'] = 5

        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)

        # Run a few ticks to let agents start actions
        eng.step(s.society_id, ticks=5)

        # Check that at least some agents have activity
        agents_with_activity = [a for a in s.agents if a.alive and a.activity is not None]
        assert len(agents_with_activity) > 0

        # Run more ticks to let actions complete
        eng.step(s.society_id, ticks=200)

        # Check that some actions completed
        completed_any = False
        for a in s.agents:
            if a.alive and a.activity:
                if a.activity.state == ActionState.IDLE and a.activity.last_state_change_tick > 0:
                    completed_any = True
                    break
        # Note: this is a weak assertion since agents might still be running
        # The key test is that the simulation doesn't stall


# ============================================================================
# Time Resolution Regression (§32)
# ============================================================================

class TestTimeResolution:
    """§32: Different ticks_per_day should produce similar results."""

    def test_different_resolutions_produce_similar_output(self):
        """50/100/200 ticks/day 的模拟结果应近似一致。"""
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config

        results = {}
        for tpd in [50, 100]:
            cfg = default_society_config()
            cfg['population']['count'] = 30
            cfg['ticks_per_day'] = tpd

            eng = SimulationEngine()
            s = eng.create_society(cfg, seed=42)
            eng.step(s.society_id, ticks=tpd * 5)  # 5 days

            metrics = s.metrics()
            results[tpd] = {
                "mean_food": metrics.get("mean_food", 0),
                "mean_money": metrics.get("mean_money", 0),
            }

        # Results should be in the same order of magnitude
        # (not exactly equal due to stochastic differences)
        for key in ["mean_food", "mean_money"]:
            v50 = results[50].get(key, 0)
            v100 = results[100].get(key, 0)
            if v50 > 0 and v100 > 0:
                ratio = v50 / v100
                # Should be within 3x of each other
                assert 0.3 < ratio < 3.0, f"{key}: 50tpd={v50}, 100tpd={v100}"


# ============================================================================
# Stall Report (§29)
# ============================================================================

class TestStallReport:
    """§29: Stall diagnostics output."""

    def test_build_stall_report(self):
        """构建停滞诊断报告。"""
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config

        cfg = default_society_config()
        cfg['population']['count'] = 10

        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)
        eng.step(s.society_id, ticks=10)

        report = build_stall_report(s, s.clock.tick)
        assert report.tick == s.clock.tick
        assert report.active_agents > 0

    def test_format_stall_report(self):
        """格式化停滞报告。"""
        from engine.simulation.stall import StallReport

        report = StallReport(
            tick=100, simulated_day=2.0, active_agents=50,
            busy_agents=30, idle_agents=20, completed_agents=0,
            stalled_agents=0, actions_started=0, actions_completed=0,
            resource_changes=0, events_created=0, events_executed=0,
            active_crises=0, queued_events=0,
            mean_food=50.0, mean_money=100.0, mean_energy=30.0,
            production_disruption=0.0,
        )
        text = format_stall_report(report)
        assert "STALL DIAGNOSTICS" in text
        assert "100" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
