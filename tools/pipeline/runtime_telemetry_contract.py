#!/usr/bin/env python3
"""runtime_telemetry_contract.py — WorldForge v1.6 RuntimeTelemetryEvent.

LiveRuntimeForge Alpha proves runtime truth through a structured event stream,
not a screenshot. This module owns RUNTIME_EVENT_TYPES (the vocabulary a live
run must emit) and the per-event schema. A completion is only believable if the
telemetry stream contains the required lifecycle events in order: the scenario
started, the map loaded, the pawn spawned and was possessed, the route ran,
waypoints were reached, an interaction succeeded, mission state changed, and the
scenario completed. Owns RUNTIME_EVENT_TYPES; the taxonomy imports it here.
"""

from pathlib import Path

from failure_codes import FailureCode
import runtime_schema as RS

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "wf.runtime.telemetry.v1"

TELEMETRY_GENERATED_REL = "procedural/generated/runtime/telemetry"
TELEMETRY_REPORTS_REL = "procedural/reports/runtime/telemetry"

# Required event types (brief §"RuntimeTelemetryEvent"). Ordering matters for
# completion: see REQUIRED_COMPLETION_EVENTS below.
RUNTIME_EVENT_TYPES = (
    "scenario.started",
    "map.loaded",
    "pawn.spawned",
    "pawn.possessed",
    "route.started",
    "waypoint.reached",
    "route.blocked",
    "route.completed",
    "interaction.started",
    "interaction.failed",
    "interaction.succeeded",
    "objective.state_changed",
    "mission.completed",
    "save.started",
    "save.completed",
    "load.started",
    "load.completed",
    "post_load_state_verified",
    "scenario.completed",
    "scenario.failed",
)

# The minimal set of events that MUST appear (in this relative order) for a
# scenario to be classified completed_runtime. A run missing any of these cannot
# be called complete — this is the anti-fake-green backbone.
REQUIRED_COMPLETION_EVENTS = (
    "scenario.started",
    "map.loaded",
    "pawn.spawned",
    "pawn.possessed",
    "route.started",
    "route.completed",
    "interaction.succeeded",
    "objective.state_changed",
    "mission.completed",
    "scenario.completed",
)

REQUIRED_FIELDS = (
    "event_id",
    "runtime_scenario_id",
    "timestamp",
    "frame",
    "event_type",
    "actor",
    "location",
    "rotation",
    "state_snapshot",
    "details",
)

OPTIONAL_FIELDS = ("schema_version",)
ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def validate_event(obj, strict=False):
    """Return check tuples for one telemetry event."""
    C = FailureCode
    checks = []
    checks += RS.check_required(obj, REQUIRED_FIELDS, C.RUNTIME_TELEMETRY_SCHEMA_FAILURE)
    checks += RS.check_no_unknown(obj, ALLOWED_FIELDS, C.RUNTIME_TELEMETRY_SCHEMA_FAILURE, strict)
    checks += RS.check_enum(obj, "event_type", RUNTIME_EVENT_TYPES, C.RUNTIME_TELEMETRY_INVALID)
    checks += RS.check_type(obj, "frame", int, C.RUNTIME_TELEMETRY_SCHEMA_FAILURE)
    checks += RS.check_transform(obj, "location", C.RUNTIME_TELEMETRY_SCHEMA_FAILURE)
    return checks


def validate_stream(events, strict=False):
    """Validate a whole event stream and prove the required completion events
    are present in order. Returns (checks, completed_bool)."""
    C = FailureCode
    checks = []
    if not isinstance(events, list) or not events:
        return ([("telemetry::non_empty", False, "event stream is empty",
                  C.RUNTIME_TELEMETRY_MISSING)], False)
    for i, ev in enumerate(events):
        for name, ok, detail, code in validate_event(ev, strict):
            checks.append(("event[{}]::{}".format(i, name), ok, detail, code))
    seq = [ev.get("event_type") for ev in events if isinstance(ev, dict)]
    # Required completion events present and in relative order.
    idx, ordered, present_all = 0, True, True
    for want in REQUIRED_COMPLETION_EVENTS:
        try:
            j = seq.index(want, idx)
            idx = j + 1
        except ValueError:
            present_all = False
            ordered = False
            break
    checks.append(("telemetry::required_completion_events", present_all and ordered,
                   "required completion events present and ordered" if present_all and ordered
                   else "missing/out-of-order completion events (need {})".format(
                       REQUIRED_COMPLETION_EVENTS),
                   C.RUNTIME_TELEMETRY_INVALID))
    return checks, (present_all and ordered)


def _valid_event(et="scenario.started"):
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": "ev_0001",
        "runtime_scenario_id": "rt_demo",
        "timestamp": "2026-07-06T00:00:00+00:00",
        "frame": 0,
        "event_type": et,
        "actor": "WF_RuntimeTestPawn",
        "location": {"x": 0.0, "y": 0.0, "z": 0.0},
        "rotation": {"pitch": 0.0, "yaw": 0.0, "roll": 0.0},
        "state_snapshot": {},
        "details": {},
    }


if __name__ == "__main__":
    stream = [_valid_event(et) for et in REQUIRED_COMPLETION_EVENTS]
    for i, ev in enumerate(stream):
        ev["event_id"] = "ev_%04d" % i
        ev["frame"] = i
    checks, completed = validate_stream(stream, strict=True)
    fails = [c for c in checks if not c[1]]
    assert not fails, "valid stream failed: {}".format(fails)
    assert completed, "valid stream not classified completed"
    # A stream missing mission.completed must NOT classify complete.
    broken = [e for e in stream if e["event_type"] != "mission.completed"]
    _, completed2 = validate_stream(broken, strict=True)
    assert not completed2, "stream missing mission.completed still completed"
    print("OK runtime_telemetry_contract self-check: {} event types, "
          "ordered-completion enforced".format(len(RUNTIME_EVENT_TYPES)))
