#!/usr/bin/env python3
"""ground_traversal_fuzz.py — WorldForge v1.6z fuzz harness.

Deterministic, seeded mutation fuzzing of every ground contract. For each case it
takes a valid example, applies a mutation, and asserts:
  * the validator NEVER raises (robustness), and
  * a CORRUPTING mutation (dropped required field / wrong type / unknown key /
    forbidden traversal mode) is REJECTED under STRICT — corruption is never
    laundered into a pass.
Same seed => same cases, so failures are reproducible.
"""
import argparse
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import ground_contracts as GX
import ground_completion_contract as GC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

# name -> dict(validate, example, required, nullable, numbers, enums, mode_field)
def _T(validate, example, required, numbers=(), enums=(), mode_field=None, nullable=()):
    return {"validate": validate, "example": example, "required": required,
            "numbers": numbers, "enums": enums, "mode_field": mode_field, "nullable": set(nullable)}


TARGETS = {
    "scenario": _T(GX.validate_scenario, GX._example_scenario, GX.SCENARIO_REQUIRED,
                   numbers=("capsule_radius", "max_slope_degrees", "max_step_height",
                            "min_route_width", "objective_approach_radius", "timeout_seconds"),
                   enums=("preferred_traversal_mode", "fallback_policy"),
                   mode_field="preferred_traversal_mode"),
    "pawn": _T(GX.validate_pawn_profile, GX._example_pawn, GX.PAWN_REQUIRED,
               numbers=("capsule_radius", "max_walk_speed", "max_slope_degrees",
                        "nav_agent_radius", "nav_agent_height")),
    "walkability": _T(GX.validate_walkability, GX._example_walkability, GX.WALKABILITY_REQUIRED,
                      enums=("status",)),
    "navmesh": _T(GX.validate_navmesh_probe, GX._example_navmesh, GX.NAVMESH_REQUIRED,
                  enums=("status", "path_status", "navmesh_runtime_generation_mode")),
    "route_graph": _T(GX.validate_route_graph, GX._example_route_graph, GX.ROUTE_GRAPH_REQUIRED,
                      enums=("validation_status",)),
    "route_plan": _T(GX.validate_route_plan, GX._example_route_plan, GX.ROUTE_PLAN_REQUIRED,
                     enums=("traversal_mode", "status"), mode_field="traversal_mode"),
    "completion": _T(lambda o, strict: GC.validate_completion(o, strict),
                     lambda: GC._example(GC.SUCCESS_CLASS, "grounded_worldforge_route", grounded=True),
                     GC.REQUIRED_FIELDS, enums=("completion_class", "actual_traversal_mode"),
                     mode_field="actual_traversal_mode", nullable=("failure_owner", "telemetry_path")),
}


def mutate(t, rng):
    """Apply one mutation. Returns (obj, op, corrupting): corrupting=True only when
    the mutation violates a DECLARED contract constraint, so 'accepted' is a real
    laundering bug — free-form fields the contract doesn't type are never asserted."""
    o = json.loads(json.dumps(t["example"]()))  # deep copy
    ops = ["drop_required", "unknown_key", "wrong_type_freeform", "flip_bool"]
    if t["numbers"]:
        ops.append("neg_number")
    if t["enums"]:
        ops.append("bad_enum")
    if t["mode_field"]:
        ops.append("forbidden_mode")
    op = rng.choice(ops)
    if op == "drop_required":
        f = rng.choice([f for f in t["required"] if f not in t["nullable"]])
        o.pop(f, None)
        return o, op, True                                   # non-nullable required -> must reject
    if op == "unknown_key":
        o["__fuzz_unknown__"] = 1
        return o, op, True                                   # strict no-unknown -> must reject
    if op == "neg_number":
        o[rng.choice(t["numbers"])] = -5.0
        return o, op, True                                   # positive-number check -> must reject
    if op == "bad_enum":
        o[rng.choice(t["enums"])] = "BOGUS_ENUM_VALUE"
        return o, op, True                                   # enum check -> must reject
    if op == "forbidden_mode":
        o[t["mode_field"]] = "continuous_flight"
        if "flight_used" in o:
            o["flight_used"] = True
        return o, op, True                                   # grounded-mode rule -> must reject
    if op == "wrong_type_freeform":
        # A free-form (untyped) field; the contract does not promise to reject a
        # type change here, so assert only robustness (no crash), not rejection.
        o["created_at"] = {"not": "a scalar"}
        return o, op, False
    # flip_bool
    for f in ("flight_used", "grounded_success", "gravity_enabled", "navmesh_present"):
        if f in o:
            o[f] = not o[f]
            break
    return o, op, False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rng = random.Random(args.seed)
    rep = ValidationReport("suite", "ground_traversal_fuzz", strict=strict)

    names = list(TARGETS)
    crashes = laundered = 0
    for i in range(args.cases):
        kind = names[i % len(names)]
        t = TARGETS[kind]
        obj, op, corrupting = mutate(t, rng)
        try:
            checks = t["validate"](obj, True)
        except Exception as e:  # noqa: BLE001
            crashes += 1
            rep.check("fuzz::{}::{}::no_crash".format(i, kind), False,
                      "validator crashed on {} mutation: {!r}".format(op, e),
                      code=FailureCode.V1_6_FUZZ_FAILURE)
            continue
        failed = [c for c in checks if not c[1]]
        if corrupting and not failed:
            laundered += 1
            rep.check("fuzz::{}::{}::corruption_rejected".format(i, kind), False,
                      "corrupting mutation '{}' on {} was ACCEPTED".format(op, kind),
                      code=FailureCode.V1_6_FUZZ_FAILURE)

    rep.check("fuzz::no_crashes", crashes == 0, "{} validator crashes".format(crashes),
              code=FailureCode.V1_6_FUZZ_FAILURE)
    rep.check("fuzz::no_laundered_corruption", laundered == 0,
              "{} corrupting mutations laundered into a pass".format(laundered),
              code=FailureCode.V1_6_FUZZ_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="ground-traversal-fuzz", pack="encounter_loop_world",
                            strict=strict, status=rep.status, record_count=args.cases,
                            report_type="wf.ground.fuzz.v1",
                            extra={"cases": args.cases, "seed": args.seed, "crashes": crashes,
                                   "laundered": laundered}))
    rep.write(REPO_ROOT / "procedural/reports/ground/fuzz", "ground_traversal_fuzz_report.json")
    rep.print_summary("ground-traversal-fuzz")
    print("[ground-traversal-fuzz] {} cases seed={} — {} crashes, {} laundered".format(
        args.cases, args.seed, crashes, laundered))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
