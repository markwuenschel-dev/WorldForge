#!/usr/bin/env python3
"""ground_completion_contract.py — WorldForge v1.6y GroundCompletionReport.

PlaytestForge Delta classifies each grounded runtime scenario into exactly one
completion class and records the TRAVERSAL MODE that was actually used. The whole
point of v1.6y is that flight and teleport can never launder into success:

  * grounded_completed_runtime REQUIRES grounded_success=True, flight_used=False,
    teleport_used=False, actual_traversal_mode in the grounded set, a telemetry
    stream, and a verified save/load — otherwise it is not a grounded success.
  * A report that claims grounded success while flight_used/teleport_used is true,
    or whose actual_traversal_mode is continuous_flight/teleport_diagnostic, is a
    FORBIDDEN success and fails with its owning code.
  * A failed report MUST carry an owning failure code.

This module owns the ground completion vocabulary; the taxonomy + validators
import from here.
"""

from pathlib import Path

from failure_codes import FailureCode
import runtime_schema as RS

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "wf.ground.completion_report.v1"
REPORT_TYPE = "wf.ground.completion_report.v1"
COMPLETION_REPORTS_REL = "procedural/reports/ground/completion"
TELEMETRY_REPORTS_REL = "procedural/reports/ground/telemetry"

# Traversal modes (brief §"TraversalMode").
TRAVERSAL_MODES = (
    "grounded_navmesh",
    "grounded_worldforge_route",
    "grounded_manual_waypoint",
    "continuous_flight",
    "teleport_diagnostic",
    "failed",
)
# Only grounded modes may satisfy v1.6y.
GROUNDED_SUCCESS_MODES = frozenset(
    {"grounded_navmesh", "grounded_worldforge_route", "grounded_manual_waypoint"})
FORBIDDEN_SUCCESS_MODES = frozenset({"continuous_flight", "teleport_diagnostic", "failed"})

# Completion classes (brief §"Completion classes").
COMPLETION_CLASSES = (
    "grounded_completed_runtime",
    "failed_ground_spawn",
    "failed_ground_possession",
    "failed_navmesh",
    "failed_route_graph",
    "failed_walkability",
    "failed_capsule_clearance",
    "failed_slope",
    "failed_step",
    "failed_route_blocked",
    "failed_objective_approach",
    "failed_interaction",
    "failed_state_transition",
    "failed_save_load",
    "failed_report_integrity",
    "forbidden_flight_success",
    "forbidden_teleport_success",
)
SUCCESS_CLASS = "grounded_completed_runtime"

FAILURE_OWNERS = (
    "ground_spawn", "ground_possession", "navmesh", "route_graph", "walkability",
    "capsule_clearance", "slope", "step", "route", "objective_approach",
    "interaction", "state", "save_load", "report_integrity", "mode",
)
RESULT_STATUS = ("pass", "fail", "skipped")

REQUIRED_FIELDS = (
    "report_id",
    "report_type",
    "schema_version",
    "pack",
    "scenario_id",
    "runtime_scenario_id",
    "map_id",
    "mission_id",
    "encounter_id",
    "biome",
    "mission_archetype",
    "pressure_profile",
    "seed",
    "requested_traversal_mode",
    "actual_traversal_mode",
    "grounded_success",
    "flight_used",
    "teleport_used",
    "navmesh_result",
    "route_graph_result",
    "walkability_result",
    "pawn_result",
    "route_result",
    "interaction_result",
    "state_result",
    "save_load_result",
    "telemetry_path",
    "evidence_paths",
    "completion_class",
    "failure_owner",
    "failure_codes",
    "runtime_duration_seconds",
    "distance_traveled",
    "created_at",
    "git_commit",
)
ALLOWED_FIELDS = REQUIRED_FIELDS + ("meta", "grounded_samples", "airborne_samples")


def _b(obj, k):
    return obj.get(k) is True if isinstance(obj, dict) else False


def is_grounded_mode(m):
    """Hashable-guarded membership (fuzzed input may be an unhashable dict)."""
    return isinstance(m, str) and m in GROUNDED_SUCCESS_MODES


def is_forbidden_mode(m):
    return isinstance(m, str) and m in FORBIDDEN_SUCCESS_MODES


def validate_completion(obj, strict=False):
    """Check tuples for one grounded completion report. Enforces the no-flight /
    no-teleport invariants between completion_class, traversal mode, and evidence."""
    C = FailureCode
    checks = []
    checks += RS.check_required(obj, REQUIRED_FIELDS, C.GROUND_TRAVERSAL_SCHEMA_FAILURE,
                                nullable=("failure_owner", "telemetry_path"))
    checks += RS.check_no_unknown(obj, ALLOWED_FIELDS, C.GROUND_TRAVERSAL_SCHEMA_FAILURE, strict)
    checks += RS.check_enum(obj, "completion_class", COMPLETION_CLASSES,
                            C.GROUND_TRAVERSAL_SCHEMA_FAILURE)
    checks += RS.check_enum(obj, "requested_traversal_mode", TRAVERSAL_MODES,
                            C.GROUND_MODE_SELECTION_FAILURE)
    checks += RS.check_enum(obj, "actual_traversal_mode", TRAVERSAL_MODES,
                            C.GROUND_MODE_SELECTION_FAILURE)
    checks += RS.check_enum(obj, "failure_owner", FAILURE_OWNERS,
                            C.GROUND_TRAVERSAL_SCHEMA_FAILURE, required=False)

    if not isinstance(obj, dict):
        return checks

    cclass = obj.get("completion_class")
    mode = obj.get("actual_traversal_mode")
    fcodes = obj.get("failure_codes")
    flight = _b(obj, "flight_used")
    teleport = _b(obj, "teleport_used")
    grounded = _b(obj, "grounded_success")

    # failure_codes must be a list.
    checks.append(("ground::failure_codes_is_list", isinstance(fcodes, list),
                   "failure_codes must be a list", C.GROUND_TRAVERSAL_SCHEMA_FAILURE))

    if cclass == SUCCESS_CLASS:
        # The heart of v1.6y: a grounded success can never be flight or teleport.
        checks.append(("ground::success_not_flight", not flight,
                       "grounded_completed_runtime with flight_used=true",
                       C.GROUND_FLIGHT_COUNTED_AS_SUCCESS))
        checks.append(("ground::success_not_teleport", not teleport,
                       "grounded_completed_runtime with teleport_used=true",
                       C.GROUND_TELEPORT_COUNTED_AS_SUCCESS))
        checks.append(("ground::success_mode_grounded", is_grounded_mode(mode),
                       "grounded success actual_traversal_mode={!r} not a grounded mode".format(mode),
                       C.GROUND_TRAVERSAL_MODE_FORBIDDEN))
        checks.append(("ground::success_flag", grounded,
                       "grounded_completed_runtime must have grounded_success=true",
                       C.GROUND_COMPLETION_FAILURE))
        checks.append(("ground::success_has_telemetry", bool(obj.get("telemetry_path")),
                       "grounded success must reference a telemetry stream",
                       C.GROUND_REPORT_MISSING_TELEMETRY))
        checks.append(("ground::success_saved", obj.get("save_load_result") == "pass",
                       "grounded success must have save_load_result=pass",
                       C.GROUND_COMPLETION_FAILURE))
        checks.append(("ground::success_interacted", obj.get("interaction_result") == "pass",
                       "grounded success must have interaction_result=pass",
                       C.GROUND_INTERACTION_UNREACHABLE))
        checks.append(("ground::success_no_codes",
                       isinstance(fcodes, list) and len(fcodes) == 0,
                       "grounded success must carry zero failure_codes; got {!r}".format(fcodes),
                       C.GROUND_COMPLETION_FAILURE))
    elif cclass in COMPLETION_CLASSES:
        # Any non-success class must own at least one failure code.
        checks.append(("ground::failure_has_code",
                       isinstance(fcodes, list) and len(fcodes) > 0,
                       "non-success class {!r} must carry >=1 failure_code".format(cclass),
                       C.GROUND_COMPLETION_FAILURE))

    # Independent of class: a report can never assert grounded_success while using
    # flight or teleport. This catches a mislabeled class too.
    if grounded:
        checks.append(("ground::grounded_flag_not_flight", not flight,
                       "grounded_success=true with flight_used=true",
                       C.GROUND_FLIGHT_COUNTED_AS_SUCCESS))
        checks.append(("ground::grounded_flag_not_teleport", not teleport,
                       "grounded_success=true with teleport_used=true",
                       C.GROUND_TELEPORT_COUNTED_AS_SUCCESS))
        checks.append(("ground::grounded_flag_mode", is_grounded_mode(mode),
                       "grounded_success=true but mode {!r} is not grounded".format(mode),
                       C.GROUND_TRAVERSAL_MODE_FORBIDDEN))
    return checks


# Self-check: a valid grounded success passes; known-bad flight/teleport success fails.
def _self_check():
    good = _example(SUCCESS_CLASS, "grounded_worldforge_route", grounded=True)
    bad_flight = _example(SUCCESS_CLASS, "continuous_flight", grounded=True, flight=True)
    bad_tp = _example(SUCCESS_CLASS, "grounded_worldforge_route", grounded=True, teleport=True)
    g = [c for c in validate_completion(good, strict=True) if not c[1]]
    bf = [c for c in validate_completion(bad_flight, strict=True) if not c[1]]
    bt = [c for c in validate_completion(bad_tp, strict=True) if not c[1]]
    assert not g, "valid grounded report should pass: {}".format([c[0] for c in g])
    assert bf, "flight-as-grounded-success must fail"
    assert bt, "teleport-as-grounded-success must fail"
    return True


def _example(cclass, mode, grounded=False, flight=False, teleport=False):
    return {
        "report_id": "x:completion", "report_type": REPORT_TYPE, "schema_version": SCHEMA_VERSION,
        "pack": "encounter_loop_world", "scenario_id": "x", "runtime_scenario_id": "x",
        "map_id": "M", "mission_id": "m", "encounter_id": "n/a", "biome": "b",
        "mission_archetype": "disable_site", "pressure_profile": "light_pressure", "seed": 0,
        "requested_traversal_mode": "grounded_worldforge_route", "actual_traversal_mode": mode,
        "grounded_success": grounded, "flight_used": flight, "teleport_used": teleport,
        "navmesh_result": "unavailable", "route_graph_result": "pass", "walkability_result": "pass",
        "pawn_result": "pass", "route_result": "pass", "interaction_result": "pass",
        "state_result": "pass", "save_load_result": "pass",
        "telemetry_path": "procedural/reports/ground/telemetry/x.json", "evidence_paths": [],
        "completion_class": cclass, "failure_owner": None,
        "failure_codes": [] if cclass == SUCCESS_CLASS else [FailureCode.GROUND_COMPLETION_FAILURE],
        "runtime_duration_seconds": 2.0, "distance_traveled": 900.0,
        "created_at": "live", "git_commit": "live",
    }


if __name__ == "__main__":
    _self_check()
    print("[ground_completion_contract] self-check OK: grounded valid passes; "
          "flight/teleport success rejected")
