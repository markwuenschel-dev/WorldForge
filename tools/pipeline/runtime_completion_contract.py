#!/usr/bin/env python3
"""runtime_completion_contract.py — WorldForge v1.6 RuntimeCompletionReport.

PlaytestForge Gamma classifies each runtime scenario into exactly one completion
class. This module owns COMPLETION_CLASSES and the completion-report schema, plus
the sub-result vocabularies (spawn/possession/route/interaction/state/save-load).
A report that claims ``completed_runtime`` MUST carry a telemetry path, evidence,
non-empty objective/state event lists, and a failure_code of None; a failed
report MUST carry an owning failure_code. Owns COMPLETION_CLASSES + FAILURE_OWNERS
+ RESULT_STATUS; the taxonomy imports them here.
"""

from pathlib import Path

from failure_codes import FailureCode
import runtime_schema as RS

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "wf.runtime.completion_report.v1"

COMPLETION_GENERATED_REL = "procedural/generated/runtime/completion"
COMPLETION_REPORTS_REL = "procedural/reports/runtime/completion"

# Completion classes (brief §"Completion classes").
COMPLETION_CLASSES = (
    "completed_runtime",
    "failed_spawn",
    "failed_possession",
    "failed_navmesh",
    "failed_collision",
    "failed_route_blocked",
    "failed_timeout",
    "failed_interaction_missing",
    "failed_interaction",
    "failed_state_transition",
    "failed_save_load",
    "failed_report_integrity",
    # v1.6 honest staging: the authoring substrate is proven but the live UE run
    # has not been executed (editor/NeoStack bridge offline). NEVER counts as
    # completion — it is a distinct, non-green, non-fake class.
    "staged_live_run_pending",
)

SUCCESS_CLASS = "completed_runtime"

# Which owning subsystem a failure belongs to (brief §"failure_owner").
FAILURE_OWNERS = (
    "scenario",
    "map_load",
    "spawn",
    "possession",
    "navmesh",
    "collision",
    "route",
    "interaction",
    "state",
    "save_load",
    "driver",
    "report_integrity",
    "runtime_bridge",
)

# Per-sub-result status vocabulary.
RESULT_STATUS = ("pass", "fail", "skipped", "pending")

# completion_class -> the owning failure_code (None for success/staged).
CLASS_FAILURE_CODE = {
    "completed_runtime": None,
    "failed_spawn": FailureCode.RUNTIME_PAWN_SPAWN_FAILURE,
    "failed_possession": FailureCode.RUNTIME_PAWN_POSSESSION_FAILURE,
    "failed_navmesh": FailureCode.RUNTIME_NAVMESH_MISSING,
    "failed_collision": FailureCode.RUNTIME_COLLISION_BLOCKED,
    "failed_route_blocked": FailureCode.RUNTIME_ROUTE_BLOCKED,
    "failed_timeout": FailureCode.RUNTIME_ROUTE_TIMEOUT,
    "failed_interaction_missing": FailureCode.INTERACTION_ACTOR_MISSING,
    "failed_interaction": FailureCode.INTERACTION_EVENT_MISSING,
    "failed_state_transition": FailureCode.INTERACTION_STATE_MUTATION_FAILURE,
    "failed_save_load": FailureCode.RUNTIME_COMPLETION_NOT_PERSISTED,
    "failed_report_integrity": FailureCode.RUNTIME_REPORT_INTEGRITY_FAILURE,
    "staged_live_run_pending": FailureCode.RUNTIME_LIVE_RUN_PENDING,
}

REQUIRED_FIELDS = (
    "report_id",
    "report_type",
    "schema_version",
    "pack",
    "runtime_scenario_id",
    "map_id",
    "mission_id",
    "encounter_id",
    "biome",
    "status",
    "completion_class",
    "failure_code",
    "failure_owner",
    "spawn_result",
    "possession_result",
    "route_result",
    "interaction_result",
    "state_result",
    "save_load_result",
    "telemetry_path",
    "screenshot_paths",
    "replay_path",
    "runtime_duration_seconds",
    "distance_traveled",
    "objective_events_seen",
    "state_transitions_seen",
    "created_at",
    "git_commit",
)

ALLOWED_FIELDS = REQUIRED_FIELDS + ("meta",)


def validate_completion(obj, strict=False):
    """Return check tuples for one completion report, enforcing the no-fake-green
    invariants between completion_class and the evidence it must carry."""
    C = FailureCode
    checks = []
    # telemetry_path/replay_path are present-but-nullable: a non-success run has
    # no telemetry stream. completed_runtime's non-null telemetry is enforced by
    # the success branch below, not here.
    checks += RS.check_required(obj, REQUIRED_FIELDS, C.RUNTIME_COMPLETION_SCHEMA_FAILURE,
                                nullable=("failure_code", "failure_owner",
                                          "replay_path", "telemetry_path"))
    checks += RS.check_no_unknown(obj, ALLOWED_FIELDS, C.RUNTIME_COMPLETION_SCHEMA_FAILURE, strict)
    checks += RS.check_enum(obj, "completion_class", COMPLETION_CLASSES,
                            C.RUNTIME_COMPLETION_SCHEMA_FAILURE)
    checks += RS.check_enum(obj, "failure_owner", FAILURE_OWNERS,
                            C.RUNTIME_COMPLETION_SCHEMA_FAILURE, required=False)

    cclass = obj.get("completion_class") if isinstance(obj, dict) else None
    fcode = obj.get("failure_code") if isinstance(obj, dict) else None

    if cclass == SUCCESS_CLASS:
        # A real completion must carry telemetry, evidence, seen events, no code.
        checks.append(("completion::success_no_failure_code", fcode in (None, "", "null"),
                       "completed_runtime carries failure_code={!r}".format(fcode),
                       C.PLAYTEST_GAMMA_FALSE_SUCCESS))
        checks.append(("completion::success_has_telemetry", bool(obj.get("telemetry_path")),
                       "completed_runtime must reference a telemetry stream",
                       C.RUNTIME_REPORT_MISSING_TELEMETRY))
        oes = obj.get("objective_events_seen")
        sts = obj.get("state_transitions_seen")
        checks.append(("completion::success_saw_objective_events",
                       isinstance(oes, list) and len(oes) > 0,
                       "completed_runtime must have >=1 objective event seen",
                       C.PLAYTEST_GAMMA_FALSE_SUCCESS))
        checks.append(("completion::success_saw_state_transitions",
                       isinstance(sts, list) and len(sts) > 0,
                       "completed_runtime must have >=1 state transition seen",
                       C.PLAYTEST_GAMMA_FALSE_SUCCESS))
    elif cclass in COMPLETION_CLASSES:
        # Any non-success class must own a failure_code (staged included).
        checks.append(("completion::failure_has_code", bool(fcode),
                       "non-success class {!r} must carry a failure_code".format(cclass),
                       C.RUNTIME_COMPLETION_SCHEMA_FAILURE))
        expected = CLASS_FAILURE_CODE.get(cclass)
        if expected is not None and fcode:
            checks.append(("completion::failure_code_matches_class",
                           fcode == expected,
                           "class {!r} expects owning code {} (got {})".format(
                               cclass, expected, fcode),
                           C.RUNTIME_COMPLETION_SCHEMA_FAILURE))
    return checks


def _valid_success():
    return {
        "report_id": "rt_demo:completion",
        "report_type": "wf.runtime.completion_report.v1",
        "schema_version": SCHEMA_VERSION,
        "pack": "encounter_loop_world",
        "runtime_scenario_id": "rt_demo",
        "map_id": "wetland_seed02",
        "mission_id": "mission_disable_site_wetland_seed02",
        "encounter_id": "enc_wetland_seed02",
        "biome": "wetland_mire",
        "status": "ok",
        "completion_class": "completed_runtime",
        "failure_code": None,
        "failure_owner": None,
        "spawn_result": "pass",
        "possession_result": "pass",
        "route_result": "pass",
        "interaction_result": "pass",
        "state_result": "pass",
        "save_load_result": "pass",
        "telemetry_path": "procedural/reports/runtime/telemetry/rt_demo.json",
        "screenshot_paths": ["procedural/reports/runtime/evidence/rt_demo_start.png"],
        "replay_path": None,
        "runtime_duration_seconds": 42.0,
        "distance_traveled": 1820.0,
        "objective_events_seen": ["objective.disabled"],
        "state_transitions_seen": ["mission.disable_site.completed"],
        "created_at": "2026-07-06T00:00:00+00:00",
        "git_commit": "deadbeef",
    }


if __name__ == "__main__":
    ok = [c for c in validate_completion(_valid_success(), strict=True) if not c[1]]
    assert not ok, "valid success failed: {}".format(ok)
    # A "success" with no telemetry must be rejected as false success.
    fake = _valid_success()
    fake["telemetry_path"] = None
    fake["objective_events_seen"] = []
    fails = [c for c in validate_completion(fake, strict=True) if not c[1]]
    assert any("telemetry" in c[0] for c in fails), "fake success (no telemetry) not caught"
    assert set(CLASS_FAILURE_CODE) == set(COMPLETION_CLASSES)
    # A staged (non-success) report has null telemetry/replay but must still be
    # schema-valid — the key is present, only its value is null.
    staged = _valid_success()
    staged.update({"completion_class": "staged_live_run_pending", "status": "warn",
                   "failure_code": FailureCode.RUNTIME_LIVE_RUN_PENDING,
                   "failure_owner": "runtime_bridge", "telemetry_path": None,
                   "objective_events_seen": [], "state_transitions_seen": []})
    sfail = [c for c in validate_completion(staged, strict=True) if not c[1]]
    assert not sfail, "valid staged report failed: {}".format(sfail)
    print("OK runtime_completion_contract self-check: {} classes, "
          "false-success rejected, staged-report valid".format(len(COMPLETION_CLASSES)))
