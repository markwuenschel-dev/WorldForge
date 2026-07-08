#!/usr/bin/env python3
"""ground_traversal_negatives.py — WorldForge v1.6z negative-fixture gate.

Known-bad inputs must be REJECTED, and rejected for the RIGHT owning failure code
(a validator that fails for the wrong reason is not real coverage). Covers the
mode / walkability / navmesh / route-graph / completion negatives the brief lists.
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

# (label, validate_fn, bad_object, expected_owning_code)
def cases():
    return [
        ("scenario_allows_flight", GX.validate_scenario,
         GX._example_scenario(allowed_traversal_modes=["continuous_flight"],
                              preferred_traversal_mode="continuous_flight"),
         F.GROUND_TRAVERSAL_MODE_FORBIDDEN),
        ("pawn_flight_enabled", GX.validate_pawn_profile,
         GX._example_pawn(flight_enabled=True), F.GROUND_FLIGHT_COUNTED_AS_SUCCESS),
        ("pawn_gravity_off", GX.validate_pawn_profile,
         GX._example_pawn(gravity_enabled=False), F.GROUND_PAWN_PROFILE_FAILURE),
        ("pawn_teleport_enabled", GX.validate_pawn_profile,
         GX._example_pawn(teleport_enabled=True), F.GROUND_TELEPORT_COUNTED_AS_SUCCESS),
        ("walkability_pass_zero_walkable", GX.validate_walkability,
         GX._example_walkability(status="pass", walkable_surfaces=0), F.GROUND_SURFACE_NOT_WALKABLE),
        ("walkability_zero_checked", GX.validate_walkability,
         GX._example_walkability(terrain_surfaces_checked=0), F.GROUND_WALKABILITY_ANALYSIS_FAILURE),
        ("navmesh_path_true_but_missing", GX.validate_navmesh_probe,
         GX._example_navmesh(path_exists=True, path_status="path_missing"), F.GROUND_NAVMESH_PROBE_FAILURE),
        ("navmesh_no_path_no_code", GX.validate_navmesh_probe,
         GX._example_navmesh(path_exists=False, failure_codes=[]), F.GROUND_NAVMESH_PATH_MISSING),
        ("route_graph_no_edges", GX.validate_route_graph,
         GX._example_route_graph(edges=[]), F.GROUND_ROUTE_EDGE_INVALID),
        ("route_graph_bad_spawn_node", GX.validate_route_graph,
         GX._example_route_graph(spawn_node="ghost"), F.GROUND_ROUTE_NODE_INVALID),
        ("route_plan_flight_valid", GX.validate_route_plan,
         GX._example_route_plan(traversal_mode="continuous_flight", status="valid"),
         F.GROUND_TRAVERSAL_MODE_FORBIDDEN),
        ("completion_flight_success", GC.validate_completion,
         GC._example(GC.SUCCESS_CLASS, "continuous_flight", grounded=True, flight=True),
         F.GROUND_FLIGHT_COUNTED_AS_SUCCESS),
        ("completion_teleport_success", GC.validate_completion,
         GC._example(GC.SUCCESS_CLASS, "grounded_worldforge_route", grounded=True, teleport=True),
         F.GROUND_TELEPORT_COUNTED_AS_SUCCESS),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "ground_traversal_negatives", strict=strict)

    for label, fn, bad, code in cases():
        fails = [c for c in fn(bad, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("neg::{}::rejected".format(label), len(fails) > 0,
                  "known-bad '{}' must be rejected".format(label),
                  code=F.GROUND_TRAVERSAL_SCHEMA_FAILURE)
        rep.check("neg::{}::owning_code".format(label), code in codes,
                  "'{}' rejected for owning code {} (got {})".format(
                      label, code, sorted(codes)[:3]),
                  code=code)

    rep.finalize()
    rep.set_meta(build_meta(command="ground-traversal-negatives", pack="encounter_loop_world",
                            strict=strict, status=rep.status, record_count=len(cases()),
                            report_type="wf.ground.negatives.v1"))
    rep.write(REPO_ROOT / "procedural/reports/ground/negatives", "ground_traversal_negatives_report.json")
    rep.print_summary("ground-traversal-negatives")
    print("[ground-traversal-negatives] {} negative fixtures, each rejected for its owning code".format(
        len(cases())))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
