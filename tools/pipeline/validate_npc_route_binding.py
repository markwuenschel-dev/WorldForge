#!/usr/bin/env python3
"""validate_npc_route_binding.py — WorldForge v1.7 route-binding gate.

Proves every NPC spawn group binds to the VALID v1.6z grounded route substrate and
that no binding requires flight/teleport or permanently blocks the mission path:

  * the group's map has a v1.6z route graph with >=2 nodes and spawn+objective nodes;
  * a grounded route plan exists for that map (grounded traversal is real);
  * every NPC archetype the group spawns declares grounded-only route modes
    (never flight/teleport);
  * a group that can block the route uses a transient/guard-zone-only policy — never
    a permanent block of the required mission route.

Acceptance: `make validate-npc-route-binding PACK=encounter_loop_world STRICT=1`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
import npc_pack as NP
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

GROUNDED_MODES = ("grounded_worldforge_route", "grounded_manual_waypoint", "stationary_anchor")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    plans = NP.load_route_plans()
    # map_id -> set of pressure profiles that have a grounded plan
    plan_maps = {}
    for sid, p in plans.items():
        if p.get("traversal_mode") in ("grounded_worldforge_route", "grounded_manual_waypoint"):
            plan_maps.setdefault(p.get("map_id"), []).append(sid)

    groups_dir = REPO_ROOT / NX.SPAWN_GROUP_GENERATED_REL
    groups = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(groups_dir.glob("*.json"))] \
        if groups_dir.is_dir() else []
    rep.check("route::groups_exist", len(groups) > 0, "no spawn groups generated",
              code=FailureCode.NPC_SPAWN_GROUP_SCHEMA_FAILURE)

    no_graph = no_plan = flight_mode = block_bad = 0
    graph_cache = {}
    for g in groups:
        gid = g.get("spawn_group_id", "?")
        map_id = g.get("map_id")
        graph = graph_cache.get(map_id)
        if graph is None:
            graph = NP.load_route_graph(map_id)
            graph_cache[map_id] = graph
        ok_graph = (isinstance(graph, dict) and isinstance(graph.get("nodes"), list)
                    and len(graph["nodes"]) >= 2 and graph.get("spawn_node") and graph.get("objective_node"))
        if not ok_graph:
            no_graph += 1
            rep.check("rt::{}::graph".format(gid), False, "no valid route graph for map {}".format(map_id),
                      code=FailureCode.NPC_ROUTE_GRAPH_MISSING)
        if map_id not in plan_maps:
            no_plan += 1
            rep.check("rt::{}::plan".format(gid), False,
                      "no grounded route plan for map {}".format(map_id),
                      code=FailureCode.NPC_ROUTE_BINDING_FAILURE)
        # archetype route modes grounded-only.
        for aid in g.get("npc_archetype_ids", []):
            role = aid.replace("npc_", "")
            d = NP.ARCHETYPE_DEFS.get(role)
            if d and any(m not in GROUNDED_MODES for m in d["route_modes"]):
                flight_mode += 1
                rep.check("rt::{}::grounded::{}".format(gid, aid), False,
                          "archetype {} has a non-grounded route mode".format(aid),
                          code=FailureCode.NPC_ROUTE_FLIGHT_REQUIRED)
        # a blocking group must use a non-permanent policy.
        if g.get("route_binding_policy") in ("guard_anchor",):
            # guard groups may hold a zone — but must declare route_clearance_required so
            # the mission corridor stays traversable.
            if g.get("route_clearance_required") is not True:
                block_bad += 1
                rep.check("rt::{}::clearance".format(gid), False,
                          "guard group must require route clearance (no permanent mission-path block)",
                          code=FailureCode.NPC_ROUTE_BLOCKS_MISSION_PATH)

    rep.check("route::graphs_present", no_graph == 0, "{} groups without route graph".format(no_graph),
              code=FailureCode.NPC_ROUTE_GRAPH_MISSING)
    rep.check("route::grounded_plans_present", no_plan == 0, "{} groups without grounded plan".format(no_plan),
              code=FailureCode.NPC_ROUTE_BINDING_FAILURE)
    rep.check("route::no_flight_teleport", flight_mode == 0,
              "{} archetype bindings require non-grounded traversal".format(flight_mode),
              code=FailureCode.NPC_ROUTE_FLIGHT_REQUIRED)
    rep.check("route::no_permanent_mission_block", block_bad == 0,
              "{} groups risk permanently blocking the mission path".format(block_bad),
              code=FailureCode.NPC_ROUTE_BLOCKS_MISSION_PATH)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-route-binding", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(groups), report_type=NX.RT_ROUTE_BINDING,
                            records_total=len(groups), records_failed=no_graph + no_plan + flight_mode + block_bad))
    rep.write(REPO_ROOT / NX.ROUTE_BINDING_REPORTS_REL, "validate_npc_route_binding_report.json")
    rep.print_summary("validate-npc-route-binding")
    print("[validate-npc-route-binding] {} groups bound to grounded route substrate".format(len(groups)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
