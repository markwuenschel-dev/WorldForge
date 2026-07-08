#!/usr/bin/env python3
"""generate_runtime_route_plans.py — WorldForge v1.6 route plan generator (Agent 4C).

Derives one RuntimeRoutePlan per (map, mission archetype) from the mission graph
plus the materialized interaction actors: the route's goal waypoint is the actual
objective actor's transform, so the plan describes reaching the real objective,
not an abstract anchor. navmesh/collision are REQUIRED on every plan — the plan is
the traversal contract the live run must satisfy; the plan itself never proves
traversal (that is the Gamma runner's job against a live editor). Each plan is
validated against the frozen runtime_route_contract before write.

Usage:
    python tools/pipeline/generate_runtime_route_plans.py --pack encounter_loop_world [--strict]
Writes: procedural/generated/runtime/routes/<route_plan_id>.json  (one per map/archetype)
        procedural/generated/worldforge_runtime_route_catalog.json
        procedural/reports/runtime/routes/generate_runtime_route_plans_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_interaction_contract as IC
import runtime_route_contract as RC
from report_meta import build_meta, hash_obj, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

MISSION_CATALOG_REL = "procedural/generated/worldforge_mission_catalog.json"
CREATED_AT = "2026-07-06T00:00:00+00:00"


def _spawn_transform(map_id):
    # Mirrors generate_runtime_scenarios._stable_transform(map_id) so the route
    # start matches the scenario start_transform for the same map.
    h = int(hash_obj({"m": map_id, "s": 0})[:8], 16)
    return {"x": float(512 + (h % 4096)), "y": float(512 + ((h >> 12) % 4096)), "z": 120.0}


def _midpoint(a, b):
    return {"x": (a["x"] + b["x"]) / 2.0, "y": (a["y"] + b["y"]) / 2.0,
            "z": (a["z"] + b["z"]) / 2.0}


def load_actors_by_map():
    d = REPO_ROOT / IC.INTERACTION_GENERATED_REL
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            a = json.loads(p.read_text(encoding="utf-8"))
            out[(a.get("map_id"), a.get("mission_archetype"))] = a
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 route plan generator.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    missions = (json.loads((REPO_ROOT / MISSION_CATALOG_REL).read_text(encoding="utf-8"))
                .get("missions") or {})
    actors = load_actors_by_map()
    if not actors:
        rep.error("no interaction actors — run 'make runtime-interaction-actors' first")

    out_dir = REPO_ROOT / RC.ROUTE_GENERATED_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog = {"schema_version": RC.SCHEMA_VERSION, "pack": args.pack, "routes": {}}
    n_ok, seen = 0, set()

    for mid in sorted(missions):
        m = missions[mid]
        map_id = m.get("source_map")
        archetype = m.get("mission_archetype")
        actor = actors.get((map_id, archetype))
        rpid = "route_{}__{}".format(map_id, archetype)
        if rpid in seen:
            continue
        if actor is None:
            rep.check("{}::actor_present".format(rpid), False,
                      "no interaction actor for {} / {}".format(map_id, archetype),
                      code=C.RUNTIME_ROUTE_PLAN_FAILURE)
            continue
        start = _spawn_transform(map_id)
        goal = {k: actor["world_transform"][k] for k in ("x", "y", "z")}
        plan = {
            "schema_version": RC.SCHEMA_VERSION,
            "route_plan_id": rpid,
            "map_id": map_id,
            "mission_id": mid,
            "encounter_id": "n/a",
            "start_anchor_id": "spawn_player_primary",
            "goal_anchor_ids": [actor["objective_id"]],
            "route_waypoints": [start, _midpoint(start, goal), goal],
            "navmesh_required": True,
            "collision_required": True,
            "line_trace_checks": ["ground", "objective_los"],
            "route_width_required": 120.0,
            "max_allowed_detour_ratio": 1.6,
            "objective_approach_radius": actor.get("interaction_radius", 175.0),
            "hazard_avoidance_rules": [],
            "safe_zone_rules": [],
            "timeout_seconds": 180.0,
            "biome": m.get("biome_family"),
            "mission_archetype": archetype,
            "created_by": "worldforge.v1.6.route_plan_generator",
            "created_at": CREATED_AT,
        }
        checks = RC.validate_route_plan(plan, strict=strict)
        bad = [c for c in checks if not c[1]]
        rep.check("{}::valid".format(rpid), not bad,
                  "invalid route plan: {}".format([c[0] for c in bad][:5]) if bad else "valid",
                  code=C.RUNTIME_ROUTE_PLAN_FAILURE)
        if bad:
            continue
        (out_dir / "{}.json".format(rpid)).write_text(
            json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        catalog["routes"][rpid] = {"map_id": map_id, "mission_id": mid,
                                   "mission_archetype": archetype}
        seen.add(rpid)
        n_ok += 1

    catalog["route_count"] = n_ok
    (REPO_ROOT / RC.ROUTE_CATALOG_REL).write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rep.check("routes_generated", n_ok == len(missions) and n_ok > 0,
              "{}/{} route plans generated".format(n_ok, len(missions)),
              code=C.RUNTIME_ROUTE_PLAN_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="runtime-route-plans", pack=args.pack, strict=strict,
                            status=rep.status, record_count=n_ok,
                            report_type="wf.runtime.route_plan.v1",
                            output_manifest_hash=hash_obj(catalog),
                            extra={"routes": n_ok}))
    rep.write(REPO_ROOT / RC.ROUTE_REPORTS_REL, "generate_runtime_route_plans_report.json")
    rep.print_summary("runtime-route-plans")
    print("[runtime-route-plans] {}/{} route plans generated".format(n_ok, len(missions)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
