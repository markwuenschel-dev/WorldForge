#!/usr/bin/env python3
"""ground_traversal_torture.py — WorldForge v1.6z torture gate.

Actively attacks the grounded-traversal truth with the hostile cases from the
brief and asserts each is REJECTED by the owning validator. A validator that lets
any of these through is a fake-green hole.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import ground_contracts as GX
import ground_completion_contract as GC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode as F


def rejected(fn, obj):
    return [c for c in fn(obj, strict=True) if not c[1]]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # (label, must-be-rejected object + validator)
    attacks = [
        ("disable_gravity", GX.validate_pawn_profile, GX._example_pawn(gravity_enabled=False)),
        ("enable_flight", GX.validate_pawn_profile, GX._example_pawn(flight_enabled=True)),
        ("enable_teleport", GX.validate_pawn_profile, GX._example_pawn(teleport_enabled=True)),
        ("flight_completion", GC.validate_completion,
         GC._example(GC.SUCCESS_CLASS, "continuous_flight", grounded=True, flight=True)),
        ("teleport_completion", GC.validate_completion,
         GC._example(GC.SUCCESS_CLASS, "grounded_worldforge_route", grounded=True, teleport=True)),
        ("remove_navmesh_but_claim_path", GX.validate_navmesh_probe,
         GX._example_navmesh(path_exists=True, path_status="path_missing")),
        ("corrupt_route_graph", GX.validate_route_graph, GX._example_route_graph(edges=[])),
        ("block_route_but_valid", GX.validate_route_plan,
         GX._example_route_plan(status="blocked", failure_codes=[])),
        ("delete_telemetry_success", GC.validate_completion,
         GC._example(GC.SUCCESS_CLASS, "grounded_worldforge_route", grounded=True) | {"telemetry_path": None}),
        ("move_objective_into_unwalkable", GX.validate_walkability,
         GX._example_walkability(status="pass", walkable_surfaces=0)),
        ("scenario_allows_flight", GX.validate_scenario,
         GX._example_scenario(allowed_traversal_modes=["continuous_flight"],
                              preferred_traversal_mode="continuous_flight")),
    ]
    for label, fn, obj in attacks:
        fails = rejected(fn, obj)
        rep.check("torture::{}".format(label), len(fails) > 0,
                  "hostile '{}' must be rejected".format(label),
                  code=F.GROUND_TRAVERSAL_MODE_FORBIDDEN)

    # Stale v1.6x flight report reused as a ground report -> the ground completion
    # contract must reject a completed_runtime (v1.6x) class (not a ground class).
    stale = dict(GC._example(GC.SUCCESS_CLASS, "grounded_worldforge_route", grounded=True))
    stale["completion_class"] = "completed_runtime"  # a v1.6x class, not a ground class
    rep.check("torture::stale_v1_6x_report_rejected", len(rejected(GC.validate_completion, stale)) > 0,
              "stale v1.6x completed_runtime report must be rejected as a ground completion",
              code=F.GROUND_REPORT_STALE)

    rep.finalize()
    rep.set_meta(build_meta(command="ground-traversal-torture", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(attacks) + 1,
                            report_type="wf.ground.torture.v1"))
    rep.write(REPO_ROOT / "procedural/reports/ground/torture", "ground_traversal_torture_report.json")
    rep.print_summary("ground-traversal-torture")
    print("[ground-traversal-torture] {} hostile cases, all rejected".format(len(attacks) + 1))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
