"""v0.4.5.4 regression tests for crisis -> recovery event chaining."""

from engine.crisis.tracker import CrisisTransition
from engine.event.engine import _emit_crisis_transition_events
from engine.event.event import EventChain, SOURCE_TYPE


def test_crisis_instance_id_survives_event_serialization():
    chain = EventChain()
    crisis = chain.make(
        10,
        "economic_crisis",
        severity=0.8,
        evidence={"crisis_instance_id": "economic_000001", "metric_value": 0.8},
    )

    assert crisis.evidence["crisis_instance_id"] == "economic_000001"
    assert crisis.effects["crisis_instance_id"] == "economic_000001"


def test_recovery_event_links_to_the_matching_crisis_instance():
    chain = EventChain()
    crisis = chain.make(
        10,
        "economic_crisis",
        severity=0.8,
        evidence={"crisis_instance_id": "economic_000001", "metric_value": 0.8},
    )

    transition = CrisisTransition(
        crisis_type="economic",
        crisis_instance_id="economic_000001",
        previous_state="ACTIVE",
        current_state="RECOVERING",
        severity=0.5,
        tick=20,
        entered_recovering=True,
        metric_value=0.15,
        peak_metric=0.8,
        baseline_metric=0.25,
        recovery_progress=0.75,
        crisis_start_tick=10,
        peak_tick=12,
        recovery_start_tick=20,
    )

    emitted = _emit_crisis_transition_events(
        society=None,
        chain=chain,
        transitions={"economic": transition},
        tick=20,
        context={},
    )

    assert len(emitted) == 1
    recovery = emitted[0]
    assert recovery.source_type == SOURCE_TYPE.RECOVERY
    assert recovery.cause_event_id == crisis.event_id
    assert recovery.effects["crisis_instance_id"] == "economic_000001"
    assert (crisis.event_id, recovery.event_id) in chain.links
