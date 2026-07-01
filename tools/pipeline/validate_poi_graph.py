#!/usr/bin/env python3
"""validate_poi_graph.py — WorldForge v1.0x POI graph structural validator.

Structural integrity of each overlay's POI/level graph:
  * node ids are unique;
  * every node has a valid role/type;
  * every required node role is present
    (player_start, primary_poi, secondary_poi, safe_zone, danger_zone,
     resource_site, exit_or_edge_route);
  * every edge references existing nodes (no dangling edges);
  * every edge kind is in {reachable, blocked, risky, optional}.

All defects are tagged POI_GRAPH_FAILURE.

Importable core: ``validate_pack(pack, strict, overlay_dir=None) -> ValidationReport``.
``check_overlay`` accepts an overlay dict so the negative harness can inject
broken overlays.

Usage:
    PYTHONUTF8=1 python tools/pipeline/validate_poi_graph.py --pack desert_mvp_world --strict
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta
from world_pack_maps import enumerate_maps, report_dir_for
from generate_level_design import (
    load_overlay, graph_nodes, graph_edges, REQUIRED_NODE_ROLES, EDGE_KINDS,
)

CODE = FailureCode.POI_GRAPH_FAILURE
VALID_ROLES = set(REQUIRED_NODE_ROLES)


def check_overlay(rep, slice_id, overlay):
    """Add POI-graph structural checks for one overlay. Returns True if all pass."""
    def chk(name, ok, detail=""):
        return rep.check("{}::{}".format(slice_id, name), ok, detail, code=CODE)

    ok_all = True
    graph = overlay.get("graph")
    if not isinstance(graph, dict):
        return chk("graph_present", False, "overlay has no graph object")

    nodes = graph_nodes(overlay)
    edges = graph_edges(overlay)

    # nodes are dicts with an id
    node_id_list = [n.get("id") for n in nodes if isinstance(n, dict)]
    ok_all &= chk("nodes_have_ids",
                  len(node_id_list) == len(nodes) and all(node_id_list),
                  "every node must be a dict with a non-empty id")

    # unique node ids
    ok_all &= chk("node_ids_unique",
                  len(node_id_list) == len(set(node_id_list)),
                  "duplicate node ids: {}".format(
                      sorted({x for x in node_id_list if node_id_list.count(x) > 1})))

    # node roles valid
    bad_roles = [n.get("id") for n in nodes
                 if isinstance(n, dict) and n.get("role") not in VALID_ROLES]
    ok_all &= chk("node_roles_valid", not bad_roles,
                  "nodes with invalid role: {}".format(bad_roles))

    # required roles present
    present_roles = {n.get("role") for n in nodes if isinstance(n, dict)}
    missing = [r for r in REQUIRED_NODE_ROLES if r not in present_roles]
    ok_all &= chk("required_roles_present", not missing,
                  "missing required node roles: {}".format(missing))

    # edges reference existing nodes (no dangling)
    idset = set(node_id_list)
    dangling = [(e.get("from"), e.get("to")) for e in edges
                if not (isinstance(e, dict) and e.get("from") in idset and e.get("to") in idset)]
    ok_all &= chk("edges_reference_existing_nodes", not dangling,
                  "dangling edges (endpoint not a node): {}".format(dangling))

    # edge kinds valid
    bad_kinds = [(e.get("from"), e.get("to"), e.get("kind")) for e in edges
                 if not (isinstance(e, dict) and e.get("kind") in EDGE_KINDS)]
    ok_all &= chk("edge_kinds_valid", not bad_kinds,
                  "edges with invalid kind (allowed {}): {}".format(sorted(EDGE_KINDS), bad_kinds))

    return ok_all


def validate_pack(pack, strict, overlay_dir=None):
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)
    for m in maps:
        if not m.spec_exists:
            rep.check("{}::spec_present".format(m.slice_id or "<missing>"), False,
                      m.get("spec_error") or "spec missing", code=CODE)
            continue
        overlay, err = load_overlay(m.slice_id, overlay_dir)
        if overlay is None:
            rep.check("{}::overlay_present".format(m.slice_id), False, err, code=CODE)
            continue
        check_overlay(rep, m.slice_id, overlay)
    rep.set_meta(build_meta(command="validate-poi-graph", pack=world_pack_id,
                            strict=strict, status=None, record_count=len(maps)))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate POI graph structure across a world pack.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = validate_pack(args.pack, strict)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_poi_graph_report.json")
    rep.print_summary("validate-poi-graph")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
