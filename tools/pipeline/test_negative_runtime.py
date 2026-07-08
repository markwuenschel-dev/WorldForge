#!/usr/bin/env python3
"""test_negative_runtime.py — WorldForge v1.6 runtime negative harness (Agent 7A).

Known-bad must fail for the RIGHT reason. For each runtime contract this builds a
deliberately-broken variant of a valid fixture and asserts the contract validator
rejects it with the OWNING failure code — not just "some failure". A negative
that stops failing (or fails with the wrong code) is a regression in the
contract's teeth and turns this gate red.

Usage:
    python tools/pipeline/test_negative_runtime.py [--strict]
Writes: procedural/reports/runtime/negatives/test_negative_runtime_report.json
"""

import argparse
import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_scenario_contract as SC
import runtime_pawn_contract as PC
import runtime_route_contract as RC
import runtime_interaction_contract as IC
import runtime_completion_contract as CC
import runtime_save_load_contract as SL
import runtime_telemetry_contract as TC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

REPORTS_REL = "procedural/reports/runtime/negatives"


def _mut(fixture, **changes):
    obj = copy.deepcopy(fixture)
    for k, v in changes.items():
        if v is _DELETE:
            obj.pop(k, None)
        else:
            obj[k] = v
    return obj


class _DELETE:  # sentinel
    pass


def build_cases():
    """Return (name, failing_codes_fn, expected_code) tuples.

    failing_codes_fn() -> set of codes emitted by the owning validator over a
    known-bad object; expected_code must be in that set.
    """
    C = FailureCode
    cases = []

    def sc(obj):  # scenario validator codes
        return {c for _, ok, _, c in SC.validate_scenario(obj, strict=True) if not ok}

    def pc(obj):
        return {c for _, ok, _, c in PC.validate_pawn_profile(obj, strict=True) if not ok}

    def rc(obj):
        return {c for _, ok, _, c in RC.validate_route_plan(obj, strict=True) if not ok}

    def ic(obj):
        return {c for _, ok, _, c in IC.validate_interaction_actor(obj, strict=True) if not ok}

    def cc(obj):
        return {c for _, ok, _, c in CC.validate_completion(obj, strict=True) if not ok}

    def sl(obj):
        return {c for _, ok, _, c in SL.validate_save_load_proof(obj, strict=True) if not ok}

    S = SC._valid_fixture()
    cases.append(("scenario_missing_map_id", sc, _mut(S, map_id=_DELETE),
                  C.RUNTIME_SCENARIO_SCHEMA_FAILURE))
    cases.append(("scenario_unsupported_verb", sc,
                  _mut(S, required_interactions=[{"verb": "teleport", "expected_event": "x"}]),
                  C.INTERACTION_VERB_UNSUPPORTED))
    cases.append(("scenario_teleport_recovery", sc,
                  _mut(S, allowed_recovery_modes=["teleport_to_objective"]),
                  C.PLAYTEST_GAMMA_TELEPORT_SUCCESS_FORBIDDEN))
    cases.append(("scenario_timeout_zero", sc, _mut(S, timeout_seconds=0),
                  C.RUNTIME_ROUTE_TIMEOUT))
    cases.append(("scenario_unknown_field_strict", sc, _mut(S, bogus_field=1),
                  C.RUNTIME_SCENARIO_SCHEMA_FAILURE))

    P = PC.default_profile()
    cases.append(("pawn_missing_capsule", pc, _mut(P, capsule_radius=_DELETE),
                  C.RUNTIME_PAWN_SCHEMA_FAILURE))
    cases.append(("pawn_zero_speed", pc, _mut(P, max_walk_speed=0),
                  C.RUNTIME_PAWN_PROFILE_FAILURE))
    cases.append(("pawn_can_teleport", pc, _mut(P, can_teleport_to_objective=True),
                  C.PLAYTEST_GAMMA_TELEPORT_SUCCESS_FORBIDDEN))
    cases.append(("pawn_no_telemetry", pc, _mut(P, telemetry_channels=[]),
                  C.RUNTIME_TELEMETRY_MISSING))

    R = RC._valid_fixture()
    cases.append(("route_no_waypoints", rc, _mut(R, route_waypoints=[]),
                  C.RUNTIME_WAYPOINT_UNREACHABLE))
    cases.append(("route_zero_approach_radius", rc, _mut(R, objective_approach_radius=0),
                  C.RUNTIME_OBJECTIVE_UNREACHABLE))
    cases.append(("route_navmesh_not_bool", rc, _mut(R, navmesh_required="yes"),
                  C.RUNTIME_NAVMESH_MISSING))

    I = IC._valid_fixture()
    cases.append(("interaction_zero_radius", ic, _mut(I, interaction_radius=0),
                  C.INTERACTION_RADIUS_INVALID))
    cases.append(("interaction_unsupported_verb", ic, _mut(I, verb="explode"),
                  C.INTERACTION_VERB_UNSUPPORTED))
    cases.append(("interaction_missing_state_key", ic, _mut(I, state_key_written=_DELETE),
                  C.INTERACTION_STATE_KEY_MISSING))
    cases.append(("interaction_missing_event", ic, _mut(I, event_emitted=_DELETE),
                  C.INTERACTION_EVENT_MISSING))

    K = CC._valid_success()
    cases.append(("completion_fake_green_no_telemetry", cc,
                  _mut(K, telemetry_path=None), C.RUNTIME_REPORT_MISSING_TELEMETRY))
    cases.append(("completion_fake_green_no_events", cc,
                  _mut(K, objective_events_seen=[]), C.PLAYTEST_GAMMA_FALSE_SUCCESS))
    cases.append(("completion_failure_wrong_code", cc,
                  _mut(K, completion_class="failed_spawn", status="fail",
                       failure_code="WF999_WRONG", failure_owner="spawn"),
                  C.RUNTIME_COMPLETION_SCHEMA_FAILURE))

    V = SL._valid_verified()
    cases.append(("saveload_empty_diff", sl,
                  _mut(V, expected_state_keys=[], verified_state_keys=[]),
                  C.RUNTIME_SAVE_STATE_MISSING))
    cases.append(("saveload_lost_completion", sl,
                  _mut(V, missing_state_keys=["mission.disable_site.completed"]),
                  C.RUNTIME_COMPLETION_NOT_PERSISTED))
    return cases


def build_telemetry_cases():
    """Telemetry stream negatives use validate_stream (different signature)."""
    stream = [TC._valid_event(et) for et in TC.REQUIRED_COMPLETION_EVENTS]
    for i, ev in enumerate(stream):
        ev["event_id"] = "ev_%04d" % i
        ev["frame"] = i
    broken = [e for e in stream if e["event_type"] != "mission.completed"]
    codes = {c for _, ok, _, c in TC.validate_stream(broken, strict=True)[0] if not ok}
    return [("telemetry_missing_mission_completed", codes,
             FailureCode.RUNTIME_TELEMETRY_INVALID)]


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 runtime negative harness.")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "runtime_negatives", strict=strict)
    n = 0
    for name, fn, bad, expected in build_cases():
        codes = fn(bad)
        rep.check("negative::{}".format(name), expected in codes,
                  "expected owning code {} in {}".format(expected, sorted(codes)),
                  code=FailureCode.RUNTIME_NEGATIVE_FIXTURE_FAILURE)
        n += 1
    for name, codes, expected in build_telemetry_cases():
        rep.check("negative::{}".format(name), expected in codes,
                  "expected owning code {} in {}".format(expected, sorted(codes)),
                  code=FailureCode.RUNTIME_NEGATIVE_FIXTURE_FAILURE)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="runtime-negative-validators", pack=None, strict=strict,
                            status=rep.status, record_count=n,
                            report_type="wf.runtime.negative_suite.v1",
                            extra={"negative_cases": n}))
    rep.write(REPO_ROOT / REPORTS_REL, "test_negative_runtime_report.json")
    rep.print_summary("runtime-negative-validators")
    print("[runtime-negative-validators] {} known-bad cases, each must fail for its owning code".format(n))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
