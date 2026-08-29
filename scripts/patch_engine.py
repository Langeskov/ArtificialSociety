"""Patch engine.py for v0.4.5.3 crisis_instance_id binding."""
import re

with open("engine/event/engine.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace the _emit_crisis_transition_events function
# Find start and end
pattern = r'(def _emit_crisis_transition_events\(.*?\n)(.*?)(?=\ndef [a-z_])'
match = re.search(pattern, content, re.DOTALL)
if not match:
    print("ERROR: Could not find function")
    exit(1)

new_func_body = '''def _emit_crisis_transition_events(
    society, chain: EventChain, transitions: dict[str, CrisisTransition],
    tick: int, context: dict,
) -> list[Event]:
    """v0.4.5.3: Convert CrisisTransitions into Event notifications.

    All notifications carry crisis_instance_id for causal chain integrity.
    Recovery notification at RECOVERING start, resolved notification at COOLDOWN.
    """
    new_events = []

    RECOVERY_STARTED_MAP = {
        "economic": "economic_recovery_started",
        "food": "food_stabilization_started",
        "protest": "recovery_started",
    }
    RESOLVED_MAP = {
        "economic": "economic_crisis_resolved",
        "food": "food_crisis_resolved",
        "protest": "protest_resolved",
    }
    CRISIS_EVENT_MAP = {
        "economic": "economic_crisis",
        "food": "food_shortage",
        "protest": "protest",
    }

    def find_crisis_event(ct: str, iid: str):
        """v0.4.5.3: Find crisis event by instance_id (not is_active)."""
        type_name = CRISIS_EVENT_MAP.get(ct, "")
        for e in reversed(chain.events):
            if e.type == type_name and e.effects.get("crisis_instance_id", "") == iid:
                return e
        for e in reversed(chain.events):
            if e.type == type_name:
                return e
        return None

    for crisis_type, trans in transitions.items():
        if not trans.has_transition:
            continue

        iid = trans.crisis_instance_id
        orig_crisis = find_crisis_event(crisis_type, iid)

        if trans.entered_recovering:
            recovery_type = RECOVERY_STARTED_MAP.get(crisis_type, "recovery_started")
            recovery_ev = chain.make(
                tick, recovery_type,
                severity=trans.severity * 0.5,
                description=f"{TYPE_LABEL.get(CRISIS_EVENT_MAP.get(crisis_type, ''), crisis_type)}恢复开始",
                cause_event_id=orig_crisis.event_id if orig_crisis else None,
                cause_mechanism="metric_improvement",
                evidence={
                    "crisis_instance_id": iid,
                    "metric_value": round(trans.metric_value, 4),
                    "peak_metric": round(trans.peak_metric, 4),
                    "baseline_metric": round(trans.baseline_metric, 4),
                    "recovery_progress": round(trans.recovery_progress, 4),
                },
                source_type=SOURCE_TYPE.RECOVERY,
                trigger_score=trans.metric_value,
                causal_confidence=0.9,
            )
            new_events.append(recovery_ev)

        if trans.resolved:
            resolved_type = RESOLVED_MAP.get(crisis_type, "protest_resolved")
            recovery_ev = next(
                (e for e in reversed(chain.events)
                 if e.type in (RECOVERY_STARTED_MAP.get(crisis_type, ""), "recovery")
                 and e.effects.get("crisis_instance_id", "") == iid),
                None,
            )
            resolved_ev = chain.make(
                tick, resolved_type,
                severity=0.3,
                description=f"{TYPE_LABEL.get(CRISIS_EVENT_MAP.get(crisis_type, ''), crisis_type)}危机解决",
                cause_event_id=recovery_ev.event_id if recovery_ev else (orig_crisis.event_id if orig_crisis else None),
                cause_mechanism="crisis_resolution",
                evidence={
                    "crisis_instance_id": iid,
                    "peak_severity": round(trans.peak_metric, 4),
                    "recovery_progress": 1.0,
                    "crisis_start_tick": trans.crisis_start_tick,
                    "resolution_tick": trans.resolution_tick,
                },
                source_type=SOURCE_TYPE.RECOVERY,
            )
            new_events.append(resolved_ev)

    return new_events


'''

content = content[:match.start()] + new_func_body + content[match.end():]

# Also add crisis_instance_id to crisis event creation
# Find the line: evidence={"metric_value": round(trans.metric_value, 4)},
# that's inside the "Apply effects for new ACTIVE/SEVERE crises" block
old_evidence = '                    evidence={"metric_value": round(trans.metric_value, 4)},'
new_evidence = '                    evidence={"crisis_instance_id": trans.crisis_instance_id, "metric_value": round(trans.metric_value, 4)},'
content = content.replace(old_evidence, new_evidence)

with open("engine/event/engine.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Patched engine.py successfully")
