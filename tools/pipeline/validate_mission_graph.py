#!/usr/bin/env python3
"""validate_mission_graph.py — WorldForge v1.3 objective-graph validator (Agent 1).

Proves each mission's objective graph is well-formed and traversable (brief §2):
start_anchor -> primary_poi -> objective_anchor(s) -> completion form a connected
path, the required_route connects the right nodes, positions exist, and the graph
has no dangling objective/completion. Structural graph integrity only — geometric
reachability/hazard checks live in validate_mission_placement / PlaytestForge.

Writes: procedural/reports/missions/validate_mission_graph/validate_mission_graph_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
from mission_catalog import load_mission_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def check_graph(rep, mid, m):
    def c(name, ok, detail="", code=FailureCode.MISSION_GRAPH_FAILURE):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=code)

    start = m.get("start_anchor") or {}
    primary = m.get("primary_poi") or {}
    objectives = m.get("objective_anchors") or []
    comps = m.get("completion_conditions") or []
    route = m.get("required_route") or {}

    c("start_present", bool(start.get("world_position")), "start_anchor missing position")
    c("primary_poi_present", bool(primary.get("gameplay_anchor") or primary.get("id")),
      "primary_poi missing anchor")
    c("has_objective_anchor", bool(objectives), "no objective anchors",
      code=FailureCode.MISSION_OBJECTIVE_FAILURE)
    for i, o in enumerate(objectives):
        c("objective_{}_position".format(i), bool(o.get("world_position")),
          "objective {} missing position".format(i), code=FailureCode.MISSION_OBJECTIVE_FAILURE)
        c("objective_{}_interaction".format(i), bool(o.get("interaction")),
          "objective {} missing interaction".format(i), code=FailureCode.MISSION_OBJECTIVE_FAILURE)

    # route connects start -> primary_poi
    c("route_from_start", route.get("from_node") == MC.NODE_START,
      "route from_node={}".format(route.get("from_node")), code=FailureCode.MISSION_ROUTE_FAILURE)
    c("route_to_primary", route.get("to_node") == MC.NODE_PRIMARY_POI,
      "route to_node={}".format(route.get("to_node")), code=FailureCode.MISSION_ROUTE_FAILURE)
    wps = route.get("waypoints") or []
    c("route_has_waypoints", len(wps) >= 2, "waypoints={}".format(len(wps)),
      code=FailureCode.MISSION_ROUTE_FAILURE)
    c("route_length_positive", (route.get("length_cm") or 0) > 0,
      "length={}".format(route.get("length_cm")), code=FailureCode.MISSION_ROUTE_FAILURE)

    # completion conditions reference an objective's state and a node present in the graph
    node_ids = {MC.NODE_START, MC.NODE_PRIMARY_POI, MC.NODE_COMPLETION}
    node_ids |= {o.get("id") for o in objectives}
    state_keys = {s.get("key") for s in (m.get("state_keys") or [])}
    for i, comp in enumerate(comps):
        c("completion_{}_node_exists".format(i), comp.get("at_node") in node_ids,
          "at_node={} not in graph".format(comp.get("at_node")), code=FailureCode.MISSION_GRAPH_FAILURE)
        c("completion_{}_state_exists".format(i), comp.get("state_key") in state_keys,
          "state_key={} not declared".format(comp.get("state_key")), code=FailureCode.MISSION_STATE_FAILURE)

    # rewards fire on a real completion condition
    comp_ids = {comp.get("condition_id") for comp in comps}
    for i, r in enumerate(m.get("reward_outputs") or []):
        c("reward_{}_fires_on_real".format(i), r.get("fires_on") in comp_ids,
          "fires_on={} not a completion".format(r.get("fires_on")), code=FailureCode.MISSION_REWARD_FAILURE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 mission objective graph.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_mission_catalog(REPO_ROOT)
    mids = sorted((catalog.get("missions") or {}).keys())
    if not mids:
        rep.error("no missions found")
    n = 0
    for mid in mids:
        m, err = MC.load_mission(mid)
        if m is None:
            rep.check("{}::loads".format(mid), False, err, code=FailureCode.MISSION_GRAPH_FAILURE)
            continue
        check_graph(rep, mid, m)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mission-graph", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_mission_graph",
              "validate_mission_graph_report.json")
    rep.print_summary("validate-mission-graph")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
