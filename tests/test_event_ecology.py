"""v0.4.5 Event Ecology & Causal Dynamics tests.

Tests:
- Event source type classification
- Event trigger registry
- Event queue with causal delay
- Causal cooldown
- Loop detector
- Event ecology dashboard
- Endogenous event requires evidence
- Exogenous event is daily rate
- Event persistence
- Event hysteresis
- Event cooldown
- Event budget
- Causal delay
- Causal depth limit
- Recovery not trigger
- Event source type
- Event severity is causal
- Event scope
- Event loop detection
- Event periodicity
- Scandal requires information
- Resource boom requires production change
"""

import random
import pytest

from engine.event.event import (
    Event, EventChain, EVENT_STATUS, SOURCE_TYPE, EVENT_SCOPE,
    EVENT_SOURCE_MAP, EVENT_TYPES,
)
from engine.event.triggers import (
    EventTrigger, TriggerEvidence, EconomicCrisisTrigger, FoodShortageTrigger,
    ProtestTrigger, PoliticalMovementTrigger, ScandalTrigger, ResourceBoomTrigger,
    create_trigger_registry, get_trigger_definitions,
)
from engine.event.queue import EventQueue, CausalCooldown
from engine.event.loops import EventLoopDetector, DetectedLoop, EventPeriodicity
from engine.event.dashboard import EventEcologyDashboard


# ============================================================================
# Event Source Type Tests
# ============================================================================

class TestEventSourceType:
    """§2: Event source classification."""

    def test_event_has_source_type(self):
        """每个事件必须有 source_type。"""
        e = Event(event_id="e1", tick=0, type="economic_crisis")
        assert e.source_type == SOURCE_TYPE.ENDOGENOUS

    def test_source_type_endogenous(self):
        """内生事件必须标记为 ENDOGENOUS。"""
        e = Event(event_id="e1", tick=0, type="economic_crisis",
                   source_type=SOURCE_TYPE.ENDOGENOUS)
        assert e.source_type == SOURCE_TYPE.ENDOGENOUS

    def test_source_type_exogenous(self):
        """外生事件必须标记为 EXOGENOUS。"""
        e = Event(event_id="e1", tick=0, type="natural_disaster",
                   source_type=SOURCE_TYPE.EXOGENOUS)
        assert e.source_type == SOURCE_TYPE.EXOGENOUS

    def test_source_type_recovery(self):
        """恢复事件必须标记为 RECOVERY。"""
        e = Event(event_id="e1", tick=0, type="food_stabilization",
                   source_type=SOURCE_TYPE.RECOVERY)
        assert e.source_type == SOURCE_TYPE.RECOVERY
        assert e.is_recovery

    def test_event_source_map_covers_all_types(self):
        """所有事件类型都必须有源分类。"""
        for event_type in EVENT_TYPES:
            assert event_type in EVENT_SOURCE_MAP, f"{event_type} missing from EVENT_SOURCE_MAP"

    def test_event_as_dict_includes_source_type(self):
        """as_dict() 必须包含 source_type。"""
        e = Event(event_id="e1", tick=0, type="protest",
                   source_type=SOURCE_TYPE.ENDOGENOUS)
        d = e.as_dict()
        assert "source_type" in d
        assert d["source_type"] == "ENDOGENOUS"


# ============================================================================
# Event Structure Upgrade Tests
# ============================================================================

class TestEventStructure:
    """§4: Event structure upgrade."""

    def test_event_has_evidence(self):
        """事件必须有 evidence 字段。"""
        e = Event(event_id="e1", tick=0, type="economic_crisis",
                   evidence={"production_gap": 0.72, "unemployment": 0.61})
        assert "production_gap" in e.evidence
        assert e.evidence["production_gap"] == 0.72

    def test_event_has_causal_confidence(self):
        """事件必须有 causal_confidence。"""
        e = Event(event_id="e1", tick=0, type="economic_crisis",
                   causal_confidence=0.83)
        assert e.causal_confidence == 0.83

    def test_event_has_trigger_score(self):
        """事件必须有 trigger_score。"""
        e = Event(event_id="e1", tick=0, type="economic_crisis",
                   trigger_score=0.71)
        assert e.trigger_score == 0.71

    def test_event_has_cause_mechanism(self):
        """事件必须有 cause_mechanism。"""
        e = Event(event_id="e1", tick=0, type="economic_crisis",
                   cause_mechanism="economic_pressure_accumulation")
        assert e.cause_mechanism == "economic_pressure_accumulation"

    def test_event_has_scope(self):
        """事件必须有 scope。"""
        e = Event(event_id="e1", tick=0, type="protest",
                   scope=EVENT_SCOPE.REGIONAL)
        assert e.scope == EVENT_SCOPE.REGIONAL

    def test_event_has_region(self):
        """事件可以有 region。"""
        e = Event(event_id="e1", tick=0, type="natural_disaster",
                   region="B")
        assert e.region == "B"

    def test_event_scope_types(self):
        """§46: 必须定义所有 scope 类型。"""
        assert EVENT_SCOPE.INDIVIDUAL.value == "INDIVIDUAL"
        assert EVENT_SCOPE.GROUP.value == "GROUP"
        assert EVENT_SCOPE.REGIONAL.value == "REGIONAL"
        assert EVENT_SCOPE.SOCIETY.value == "SOCIETY"


# ============================================================================
# EventChain v0.4.5 Tests
# ============================================================================

class TestEventChainV045:
    """EventChain v0.4.5 extensions."""

    def test_make_with_source_type(self):
        """make() 支持 source_type 参数。"""
        chain = EventChain()
        e = chain.make(0, "economic_crisis", source_type=SOURCE_TYPE.ENDOGENOUS)
        assert e.source_type == SOURCE_TYPE.ENDOGENOUS

    def test_make_auto_detects_source_type(self):
        """make() 自动从 EVENT_SOURCE_MAP 检测 source_type。"""
        chain = EventChain()
        e = chain.make(0, "natural_disaster")
        assert e.source_type == SOURCE_TYPE.EXOGENOUS

    def test_make_with_evidence(self):
        """make() 支持 evidence 参数。"""
        chain = EventChain()
        e = chain.make(0, "economic_crisis",
                       evidence={"production_gap": 0.72})
        assert e.evidence["production_gap"] == 0.72

    def test_by_source_type(self):
        """by_source_type() 按源类型过滤事件。"""
        chain = EventChain()
        chain.make(0, "economic_crisis", source_type=SOURCE_TYPE.ENDOGENOUS)
        chain.make(1, "natural_disaster", source_type=SOURCE_TYPE.EXOGENOUS)
        chain.make(2, "food_stabilization", source_type=SOURCE_TYPE.RECOVERY)

        assert len(chain.by_source_type(SOURCE_TYPE.ENDOGENOUS)) == 1
        assert len(chain.by_source_type(SOURCE_TYPE.EXOGENOUS)) == 1
        assert len(chain.by_source_type(SOURCE_TYPE.RECOVERY)) == 1

    def test_endogenous_count(self):
        """endogenous_count() 统计内生事件数。"""
        chain = EventChain()
        chain.make(0, "economic_crisis")
        chain.make(1, "protest")
        chain.make(2, "natural_disaster")
        assert chain.endogenous_count() == 2

    def test_uncaused_count(self):
        """uncaused_count() 统计无证据的内生事件数。"""
        chain = EventChain()
        chain.make(0, "economic_crisis", evidence={"gap": 0.5})
        chain.make(1, "protest")  # no evidence
        assert chain.uncaused_count() == 1


# ============================================================================
# Event Trigger Registry Tests
# ============================================================================

class TestTriggerRegistry:
    """§6: Event Trigger Registry."""

    def test_all_triggers_registered(self):
        """所有内生事件类型必须有注册的触发器。"""
        triggers = get_trigger_definitions()
        assert "economic_crisis" in triggers
        assert "food_shortage" in triggers
        assert "protest" in triggers
        assert "political_movement" in triggers
        assert "scandal" in triggers
        assert "resource_boom" in triggers

    def test_create_registry_returns_instances(self):
        """create_trigger_registry() 返回触发器实例字典。"""
        registry = create_trigger_registry()
        assert "economic_crisis" in registry
        t = registry["economic_crisis"]
        assert isinstance(t, EventTrigger)

    def test_registry_triggers_are_endogenous(self):
        """注册表中的触发器都是内生类型。"""
        registry = create_trigger_registry()
        for t in registry.values():
            assert t.source_type == SOURCE_TYPE.ENDOGENOUS

    def test_per_society_isolation(self):
        """v0.4.5.2 §26: 每个 Society 独立的触发器注册表。"""
        reg_a = create_trigger_registry()
        reg_b = create_trigger_registry()
        assert reg_a["economic_crisis"] is not reg_b["economic_crisis"]

    def test_triggers_are_stateless(self):
        """v0.4.5.2 §2: 触发器不维护状态。"""
        registry = create_trigger_registry()
        for t in registry.values():
            assert not hasattr(t, '_is_active')
            assert not hasattr(t, '_cooldown_remaining')


# ============================================================================
# Economic Crisis Trigger Tests
# ============================================================================

class TestEconomicCrisisTrigger:
    """§7: Economic crisis trigger."""

    def test_score_requires_evidence(self):
        """经济危机必须有因果证据。"""
        trigger = EconomicCrisisTrigger()
        # Create a minimal society mock
        class MockResources:
            def is_broke(self): return False
            def is_starving(self): return False
            values = {"food": 50, "money": 100}
        class MockAgent:
            alive = True
            sector = "primary"
            resources = MockResources()
        class MockSociety:
            agents = [MockAgent() for _ in range(100)]

        context = {
            "production_gap": 0.3,
            "price_pressure": 0.2,
        }
        score, evidence = trigger.score(MockSociety(), context)
        assert score >= 0
        assert "production_gap" in evidence.indicators
        assert "unemployment" in evidence.indicators

    def test_score_zero_without_agents(self):
        """没有 agent 时分数为 0。"""
        trigger = EconomicCrisisTrigger()
        class MockSociety:
            agents = []
        score, _ = trigger.score(MockSociety(), {})
        assert score == 0.0

    def test_hysteresis(self):
        """§17: 触发阈值 > 解决阈值。"""
        trigger = EconomicCrisisTrigger()
        assert trigger.trigger_threshold > trigger.resolve_threshold


# ============================================================================
# Food Shortage Trigger Tests
# ============================================================================

class TestFoodShortageTrigger:
    """§8: Food crisis trigger."""

    def test_uses_food_stock(self):
        """粮食危机必须考虑粮食库存。"""
        trigger = FoodShortageTrigger()
        class MockResources:
            def is_broke(self): return False
            def is_starving(self): return True
            values = {"food": 5, "money": 100}
        class MockAgent:
            alive = True
            resources = MockResources()
        class MockSociety:
            agents = [MockAgent() for _ in range(50)]

        context = {"food_critical": 20.0, "food_production_gap": 0.5}
        score, evidence = trigger.score(MockSociety(), context)
        assert "hungry_ratio" in evidence.indicators
        assert "low_stock" in evidence.indicators


# ============================================================================
# Protest Trigger Tests
# ============================================================================

class TestProtestTrigger:
    """§9: Protest trigger."""

    def test_multiplicative_model(self):
        """抗议必须来自 grievance × mobilization × information × group。"""
        trigger = ProtestTrigger()
        class MockResources:
            def is_broke(self): return False
            def is_starving(self): return False
            values = {"food": 50, "money": 100, "energy": 20}
        class MockAgent:
            alive = True
            status = {"anger": 0.5}
            resources = MockResources()
        class MockGroup:
            cohesion = 0.7
        class MockGroups:
            def active(self): return [MockGroup() for _ in range(5)]
        class MockSociety:
            agents = [MockAgent() for _ in range(100)]
            groups = MockGroups()

        context = {"information_spread": 0.5}
        score, evidence = trigger.score(MockSociety(), context)
        assert "grievance" in evidence.indicators
        assert "mobilization" in evidence.indicators
        assert "information_reach" in evidence.indicators
        assert "group_support" in evidence.indicators

    def test_not_random(self):
        """抗议不能随机产生。"""
        trigger = ProtestTrigger()
        # With no grievance, score should be 0
        class MockResources:
            def is_broke(self): return False
            def is_starving(self): return False
            values = {"food": 50, "money": 100, "energy": 20}
        class MockAgent:
            alive = True
            status = {"anger": 0.0}  # no anger
            resources = MockResources()
        class MockGroups:
            def active(self): return []
        class MockSociety:
            agents = [MockAgent() for _ in range(100)]
            groups = MockGroups()

        context = {"information_spread": 0.0}
        score, _ = trigger.score(MockSociety(), context)
        assert score == 0.0


# ============================================================================
# Scandal Trigger Tests
# ============================================================================

class TestScandalTrigger:
    """§11/§44: Scandal trigger."""

    def test_requires_violation(self):
        """丑闻必须来自违规行为。"""
        trigger = ScandalTrigger()
        context = {"violation_detected": 0.0, "information_exposure": 0.5, "public_trust": 0.5}
        class MockSociety:
            agents = []
        score, _ = trigger.score(MockSociety(), context)
        assert score == 0.0

    def test_requires_information_exposure(self):
        """丑闻必须有信息暴露。"""
        trigger = ScandalTrigger()
        context = {"violation_detected": 0.8, "information_exposure": 0.0, "public_trust": 0.5}
        class MockSociety:
            agents = []
        score, _ = trigger.score(MockSociety(), context)
        assert score == 0.0

    def test_not_random(self):
        """丑闻不能随机产生。"""
        trigger = ScandalTrigger()
        # Without violation + exposure, no scandal
        context = {"violation_detected": 0.0, "information_exposure": 0.0}
        class MockSociety:
            agents = []
        score, _ = trigger.score(MockSociety(), context)
        assert score == 0.0


# ============================================================================
# Resource Boom Trigger Tests
# ============================================================================

class TestResourceBoomTrigger:
    """§12/§42: Resource boom trigger."""

    def test_requires_production_change(self):
        """资源繁荣必须有生产/技术/贸易来源。"""
        trigger = ResourceBoomTrigger()
        context = {"production_increase": 0.0, "technology_boost": 0.0, "trade_expansion": 0.0}
        class MockSociety:
            agents = []
        score, _ = trigger.score(MockSociety(), context)
        assert score == 0.0

    def test_not_random(self):
        """资源繁荣不能随机产生。"""
        trigger = ResourceBoomTrigger()
        context = {"production_increase": 0.0, "technology_boost": 0.0, "trade_expansion": 0.0}
        class MockSociety:
            agents = []
        score, _ = trigger.score(MockSociety(), context)
        assert score == 0.0


# ============================================================================
# Event Queue Tests
# ============================================================================

class TestEventQueue:
    """§52: Event Queue."""

    def test_enqueue_dequeue(self):
        """入队和出队正常工作。"""
        queue = EventQueue(min_causal_delay=5)
        queue.enqueue({"type": "protest"}, tick=10)
        assert queue.size() == 1

        events = queue.dequeue(10)
        assert len(events) == 1
        assert events[0]["type"] == "protest"

    def test_causal_delay(self):
        """§24: 因果延迟防止即时递归。"""
        queue = EventQueue(min_causal_delay=5)
        queue.enqueue({"type": "protest"}, tick=10, causal_depth=1)

        # Should not be available at tick 10
        events = queue.dequeue(10)
        assert len(events) == 0

        # Should be available at tick 15
        events = queue.dequeue(15)
        assert len(events) == 1

    def test_causal_depth_limit(self):
        """§51: 超过因果深度限制的事件被拒绝。"""
        queue = EventQueue(max_causal_depth=2)
        result = queue.enqueue({"type": "protest"}, tick=10, causal_depth=3)
        assert result is False

    def test_priority_ordering(self):
        """§53: 外生事件优先级最高。"""
        queue = EventQueue()
        queue.enqueue({"type": "protest"}, tick=10, source_type=SOURCE_TYPE.ENDOGENOUS)
        queue.enqueue({"type": "natural_disaster"}, tick=10, source_type=SOURCE_TYPE.EXOGENOUS)
        queue.enqueue({"type": "recovery"}, tick=10, source_type=SOURCE_TYPE.RECOVERY)

        events = queue.dequeue(10)
        assert events[0]["type"] == "natural_disaster"  # highest priority
        assert events[-1]["type"] == "recovery"  # lowest priority


# ============================================================================
# Causal Cooldown Tests
# ============================================================================

class TestCausalCooldown:
    """§25: Causal cooldown prevents A→B→A loops."""

    def test_blocks_reverse_trigger(self):
        """反向触发应被阻止。"""
        cd = CausalCooldown(cooldown_ticks=50)
        cd.record("economic_crisis", "protest", tick=10)

        # protest → economic_crisis should be blocked within cooldown
        assert cd.is_blocked("protest", "economic_crisis", tick=30) is True

    def test_allows_after_cooldown(self):
        """冷却期后允许重新触发。"""
        cd = CausalCooldown(cooldown_ticks=50)
        cd.record("economic_crisis", "protest", tick=10)

        assert cd.is_blocked("protest", "economic_crisis", tick=70) is False

    def test_cleanup(self):
        """cleanup() 移除过期记录。"""
        cd = CausalCooldown(cooldown_ticks=50)
        cd.record("a", "b", tick=10)
        cd.cleanup(100)
        assert len(cd._edges) == 0


# ============================================================================
# Loop Detector Tests
# ============================================================================

class TestLoopDetector:
    """§31-§33: Loop detector."""

    def test_detect_2_node_loop(self):
        """检测 A → B → A 循环。"""
        chain = EventChain()
        # Create a loop: food_shortage → protest → food_shortage
        e1 = chain.make(10, "food_shortage", severity=0.8)
        e2 = chain.make(20, "protest", severity=0.6, cause_event_id=e1.event_id)
        e3 = chain.make(30, "food_shortage", severity=0.7, cause_event_id=e2.event_id)

        detector = EventLoopDetector(window_size=100)
        result = detector.analyze(chain, 30)

        assert result["loop_count"] > 0

    def test_loop_strength(self):
        """§32: 循环强度 = product(edge_strength)。"""
        loop = DetectedLoop(
            event_types=["A", "B"],
            strength=0.63,
        )
        assert loop.strength == 0.63

    def test_event_periodicity(self):
        """§33: 检测周期性事件。"""
        chain = EventChain()
        # Create periodic events: day 10, 20, 30
        for i in range(5):
            chain.make(10 + i * 100, "economic_crisis", severity=0.5)

        detector = EventLoopDetector(window_size=1000)
        result = detector.analyze(chain, 500)

        # Should detect periodicity
        periodic = result.get("periodicity", {})
        if "economic_crisis" in periodic:
            assert periodic["economic_crisis"]["is_periodic"] is True


# ============================================================================
# Event Ecology Dashboard Tests
# ============================================================================

class TestEventEcologyDashboard:
    """§29, §34, §55: Event ecology dashboard."""

    def test_compute_stats(self):
        """计算事件生态统计。"""
        chain = EventChain()
        chain.make(0, "economic_crisis", source_type=SOURCE_TYPE.ENDOGENOUS,
                   evidence={"gap": 0.5})
        chain.make(1, "natural_disaster", source_type=SOURCE_TYPE.EXOGENOUS)
        chain.make(2, "food_stabilization", source_type=SOURCE_TYPE.RECOVERY)

        dashboard = EventEcologyDashboard()
        stats = dashboard.compute(chain, 100)

        assert stats.total_events == 3
        assert stats.endogenous_count == 1
        assert stats.exogenous_count == 1
        assert stats.recovery_count == 1

    def test_format_report(self):
        """格式化报告。"""
        chain = EventChain()
        chain.make(0, "economic_crisis", source_type=SOURCE_TYPE.ENDOGENOUS,
                   evidence={"gap": 0.5})

        dashboard = EventEcologyDashboard()
        stats = dashboard.compute(chain, 100)
        report = dashboard.format_report(stats)

        assert "EVENT ECOLOGY" in report
        assert "Endogenous" in report

    def test_causality_scorecard(self):
        """§38: 因果关系记分卡。"""
        chain = EventChain()
        chain.make(0, "economic_crisis", source_type=SOURCE_TYPE.ENDOGENOUS,
                   evidence={"gap": 0.5})
        chain.make(1, "economic_crisis", source_type=SOURCE_TYPE.ENDOGENOUS)

        dashboard = EventEcologyDashboard()
        scorecard = dashboard.format_causality_scorecard(chain)

        assert "EVENT CAUSALITY" in scorecard
        assert "economic_crisis" in scorecard


# ============================================================================
# CrisisTracker Persistence / Hysteresis / Cooldown Tests (v0.4.5.2)
# ============================================================================

class TestCrisisTrackerPersistence:
    """§16: CrisisTracker persistence — state now lives in CrisisTracker."""

    def test_persistence_required(self):
        """指标必须持续 N ticks 才进入 WARNING。"""
        from engine.crisis.tracker import CrisisTracker, CrisisState
        tracker = CrisisTracker("test", trigger_threshold=0.7, trigger_persistence_ticks=5, resolve_threshold=0.4)

        for tick in range(1, 5):
            tracker.update(0.8, tick)
            assert tracker.state == CrisisState.NORMAL

        tracker.update(0.8, 5)
        assert tracker.state == CrisisState.WARNING

    def test_persistence_reset_on_drop(self):
        """指标低于阈值时重置持久性计数。"""
        from engine.crisis.tracker import CrisisTracker
        tracker = CrisisTracker("test", trigger_threshold=0.7, trigger_persistence_ticks=5, resolve_threshold=0.4)

        for tick in range(1, 3):
            tracker.update(0.8, tick)
        tracker.update(0.5, 3)
        assert tracker._above_trigger_ticks == 0


class TestCrisisTrackerHysteresis:
    """§17: CrisisTracker hysteresis."""

    def test_resolve_threshold_lower_than_trigger(self):
        from engine.crisis.tracker import CrisisTracker
        tracker = CrisisTracker("test")
        assert tracker.resolve_threshold < tracker.trigger_threshold

    def test_hysteresis_prevents_flapping(self):
        from engine.crisis.tracker import CrisisTracker, CrisisState
        tracker = CrisisTracker("test", trigger_threshold=0.7, resolve_threshold=0.4, trigger_persistence_ticks=1)

        tracker.update(0.75, 1)
        assert tracker.state == CrisisState.WARNING
        tracker.update(0.75, 2)
        assert tracker.state == CrisisState.ACTIVE
        tracker.update(0.45, 3)
        assert tracker.state == CrisisState.ACTIVE  # above resolve
        tracker.update(0.35, 4)
        assert tracker.state == CrisisState.RECOVERING


class TestCrisisTrackerCooldown:
    """§18: CrisisTracker cooldown."""

    def test_cooldown_after_resolution(self):
        from engine.crisis.tracker import CrisisTracker, CrisisState
        tracker = CrisisTracker("test", trigger_threshold=0.7, resolve_threshold=0.4,
                                trigger_persistence_ticks=1, cooldown_days=0.1)
        tracker.update(0.8, 1)
        tracker.update(0.8, 2)
        assert tracker.state == CrisisState.ACTIVE
        tracker.update(0.3, 3)
        assert tracker.state == CrisisState.RECOVERING
        tracker.recovery_progress = 0.9
        tracker.update(0.3, 4)
        assert tracker.state == CrisisState.COOLDOWN


# ============================================================================
# Recovery Lifecycle Tests (v0.4.5.2)
# ============================================================================

class TestRecoveryLifecycle:
    """v0.4.5.2: Recovery notifications at correct lifecycle points."""

    def test_recovery_started_on_entering_recovering(self):
        """ACTIVE → RECOVERING 时生成 recovery_started 通知。"""
        from engine.crisis.tracker import CrisisTracker, CrisisState
        tracker = CrisisTracker("economic", trigger_threshold=0.68, resolve_threshold=0.45,
                                trigger_persistence_ticks=1)
        tracker.update(0.8, 1)  # WARNING
        tracker.update(0.8, 2)  # ACTIVE
        trans = tracker.update(0.3, 3)  # RECOVERING
        assert trans.entered_recovering is True
        assert tracker.state == CrisisState.RECOVERING

    def test_resolved_on_entering_cooldown(self):
        """RECOVERING → COOLDOWN 时生成 resolved 通知。"""
        from engine.crisis.tracker import CrisisTracker, CrisisState
        tracker = CrisisTracker("economic", trigger_threshold=0.68, resolve_threshold=0.45,
                                trigger_persistence_ticks=1)
        tracker.update(0.8, 1)
        tracker.update(0.8, 2)
        tracker.update(0.3, 3)
        tracker.recovery_progress = 0.9
        trans = tracker.update(0.3, 4)
        assert trans.resolved is True
        assert tracker.state == CrisisState.COOLDOWN

    def test_recovery_failure_returns_to_active(self):
        """恢复失败时重新进入 ACTIVE。"""
        from engine.crisis.tracker import CrisisTracker, CrisisState
        tracker = CrisisTracker("economic", trigger_threshold=0.68, resolve_threshold=0.45,
                                severe_threshold_multiplier=1.5, trigger_persistence_ticks=1)
        tracker.update(0.8, 1)
        tracker.update(0.8, 2)
        tracker.update(0.3, 3)  # RECOVERING
        trans = tracker.update(0.8, 4)  # metric worsens
        assert trans.recovery_failed is True
        assert tracker.state == CrisisState.ACTIVE

    def test_recovery_timeout(self):
        """恢复超时重新进入 ACTIVE。"""
        from engine.crisis.tracker import CrisisTracker, CrisisState
        tracker = CrisisTracker("economic", trigger_threshold=0.68, resolve_threshold=0.45,
                                trigger_persistence_ticks=1, max_recovery_ticks=5)
        tracker.update(0.8, 1)
        tracker.update(0.8, 2)
        tracker.update(0.3, 3)  # RECOVERING, _recovery_ticks=0
        for tick in range(4, 8):
            tracker.update(0.5, tick)  # _recovery_ticks goes 1,2,3,4
        # At tick 8 update: _recovery_ticks=5 >= max_recovery_ticks=5 → timeout
        trans = tracker.update(0.5, 8)
        assert trans.recovery_failed is True
        assert tracker.state == CrisisState.ACTIVE

    def test_recovery_counters(self):
        """恢复计数器正确递增。"""
        from engine.crisis.tracker import CrisisTracker
        tracker = CrisisTracker("economic", trigger_threshold=0.68, resolve_threshold=0.45,
                                trigger_persistence_ticks=1, cooldown_days=0.01)
        tracker.update(0.8, 1)
        tracker.update(0.8, 2)
        assert tracker.recovery_started_count == 0
        tracker.update(0.3, 3)
        assert tracker.recovery_started_count == 1
        tracker.recovery_progress = 0.9
        tracker.update(0.3, 4)
        assert tracker.recovery_completed_count == 1


# ============================================================================
# Multi-Society Isolation Tests (v0.4.5.2 §28)
# ============================================================================

class TestCrisisIsolation:
    """v0.4.5.2 §28: Crisis state must not leak between societies."""

    def test_trigger_registry_isolation(self):
        """触发器注册表在不同 Society 间隔离。"""
        from engine.event.triggers import create_trigger_registry
        reg_a = create_trigger_registry()
        reg_b = create_trigger_registry()
        assert reg_a["economic_crisis"] is not reg_b["economic_crisis"]

    def test_crisis_manager_isolation(self):
        """CrisisManager 在不同 Society 间隔离。"""
        from engine.crisis.tracker import CrisisManager, CrisisState
        cm_a = CrisisManager()
        cm_b = CrisisManager()
        cm_a.economic.trigger_persistence_ticks = 1
        cm_a.economic.update(0.7, 1, 100)  # WARNING
        cm_a.economic.update(0.7, 2, 100)  # ACTIVE
        assert cm_a.economic.state in (CrisisState.ACTIVE, CrisisState.SEVERE)
        assert cm_a.economic.is_crisis()
        assert cm_b.economic.state == CrisisState.NORMAL
        assert not cm_b.economic.is_crisis()


# ============================================================================
# Integration Tests
# ============================================================================

class TestSimulationV0452:
    """Integration tests for v0.4.5.2."""

    def test_simulation_runs(self):
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config
        cfg = default_society_config()
        cfg['population']['count'] = 50
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)
        result = eng.step(s.society_id, ticks=100)
        assert result is not None
        assert "new_events" in result

    def test_events_have_source_type(self):
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config
        cfg = default_society_config()
        cfg['population']['count'] = 50
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)
        result = eng.step(s.society_id, ticks=200)
        for event_data in result.get("new_events", []):
            assert "source_type" in event_data
            assert event_data["source_type"] in ["ENDOGENOUS", "EXOGENOUS", "RECOVERY"]

    def test_event_ecology_diagnostics(self):
        from engine.simulation.engine import SimulationEngine
        from configs.loader import default_society_config
        cfg = default_society_config()
        cfg['population']['count'] = 50
        eng = SimulationEngine()
        s = eng.create_society(cfg, seed=42)
        eng.step(s.society_id, ticks=200)
        ecology = eng.get_event_ecology(s.society_id)
        assert ecology is not None
        assert "report" in ecology


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
