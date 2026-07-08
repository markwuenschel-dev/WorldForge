#!/usr/bin/env python3
"""generate_ground_route_plans.py — WorldForge v1.6z per-scenario grounded route plans.

Turns each map's route graph into a per-scenario multi-node GroundRoutePlan
(spawn -> corridor nodes -> objective) with the runtime waypoints the grounded
driver follows and the corridor/cover/hazard/approach checks a route must pass.
One plan per runtime scenario (120), traversal_mode grounded_worldforge_route.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import ground_contracts as GX
import run_ground_runtime_batch as RB
from report_meta import build_meta
from validation_report import ValidationReport
from failure_codes import FailureCode

GRAPH_DIR = REPO_ROOT / GX.ROUTE_GRAPH_GENERATED_REL
OUT_DIR = REPO_ROOT / GX.ROUTE_PLAN_GENERATED_REL


def plan_from_graph(rec, graph):
    seq = ["spawn"] + [n["node_id"] for n in graph["nodes"] if n["kind"] == "walkable"] + ["obj"]
    node_by_id = {n["node_id"]: n for n in graph["nodes"]}
    wps = [{"x": node_by_id[nid]["x"], "y": node_by_id[nid]["y"], "z": node_by_id[nid]["z"]}
           for nid in seq]
    dist = sum(e["distance"] for e in graph["edges"])
    valid = graph["validation_status"] == "valid"
    return {
        "route_plan_id": "grp:%s" % rec["scenario_id"], "scenario_id": rec["scenario_id"],
        "map_id": rec["map_id"], "mission_id": rec["mission_id"], "encounter_id": rec["encounter_id"],
        "traversal_mode": "grounded_worldforge_route", "route_nodes": seq, "runtime_waypoints": wps,
        "expected_distance": dist, "max_allowed_detour_ratio": 1.6, "objective_approach_radius": 200.0,
        "line_trace_checks": ["ground", "objective_los"], "capsule_sweep_checks": ["corridor"],
        "slope_checks": ["<=44"], "step_checks": ["<=45"], "cover_avoidance_checks": ["clear"],
        "hazard_avoidance_checks": ["clear"], "status": "valid" if valid else "blocked",
        "failure_codes": [] if valid else [FailureCode.GROUND_ROUTE_UNREACHABLE],
        "created_by": "worldforge.v1.6z.route_plan_generator", "created_at": "2026-07-08T00:00:00+00:00",
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    rep = ValidationReport("pack", args.pack, strict=args.strict)

    recs = RB.scenarios()
    graphs = {}
    if GRAPH_DIR.is_dir():
        for p in GRAPH_DIR.glob("*.json"):
            if p.name.startswith("generate_"):
                continue
            graphs[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    rep.check("route_graphs_available", len(graphs) > 0,
              "{} route graphs present (run generate-ground-route-graph first)".format(len(graphs)),
              code=FailureCode.GROUND_ROUTE_GRAPH_MISSING, warn_only=False)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    for rec in recs:
        g = graphs.get(rec["map_id"])
        if not g:
            rep.check("{}::graph_present".format(rec["scenario_id"]), False,
                      "no route graph for map {}".format(rec["map_id"]),
                      code=FailureCode.GROUND_ROUTE_GRAPH_MISSING)
            continue
        plan = plan_from_graph(rec, g)
        bad = [c for c in GX.validate_route_plan(plan, strict=True) if not c[1]]
        rep.check("{}::route_plan_valid".format(rec["scenario_id"]), not bad,
                  "route plan {}".format("ok" if not bad else [c[0] for c in bad][:3]),
                  code=FailureCode.GROUND_ROUTE_GRAPH_FAILURE)
        (OUT_DIR / "{}.json".format(rec["scenario_id"])).write_text(
            json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        if not bad:
            n_ok += 1

    rep.finalize()
    rep.set_meta(build_meta(command="generate-ground-route-plans", pack=args.pack, strict=args.strict,
                            status=rep.status, record_count=len(recs),
                            report_type="wf.ground.route_plan.v1", extra={"plans": n_ok}))
    rep.write(OUT_DIR, "generate_ground_route_plans_report.json")
    rep.print_summary("generate-ground-route-plans")
    print("[generate-ground-route-plans] {}/{} route plans".format(n_ok, len(recs)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
