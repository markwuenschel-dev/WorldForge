#!/usr/bin/env python3
"""validate_streaming_authoring.py — v2.3 Wave 2 generated-authoring gate.

Re-validates every generated region/tile/anchor/route/binding from disk against
streaming_contracts AND performs the cross-record resolution the schema-only
contracts cannot: region tile_ids resolve to real tile files, neighbor links are
RECIPROCAL, anchor links resolve + reciprocate, route anchors/tiles resolve, no
navmesh overclaim, binding tiles/anchors/routes resolve, quest_ids resolve to real
v2.2 quests, and NPC scopes stay inside allowed tiles. Coverage: 2 regions, 6 tiles,
24 mission + 24 NPC bindings over all 24 scenarios.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_streaming_authoring.py --strict
Reports -> procedural/reports/streaming/authoring/validate_streaming_authoring_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_contracts as SC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

GEN = REPO_ROOT / "procedural" / "generated"
REGIONS_DIR = GEN / "regions"
TILES_DIR = GEN / "tiles"
ANCHORS_DIR = GEN / "anchors"
ROUTES_DIR = GEN / "routes"
MISSION_DIR = GEN / "streaming" / "mission_bindings"
NPC_DIR = GEN / "streaming" / "npc_bindings"
QUESTS_DIR = GEN / "quests"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "authoring"


def _load_all(d):
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))}


def validate(rep):
    regions = _load_all(REGIONS_DIR)
    tiles = _load_all(TILES_DIR)
    anchors = _load_all(ANCHORS_DIR)
    routes = _load_all(ROUTES_DIR)
    missions = _load_all(MISSION_DIR)
    npcs = _load_all(NPC_DIR)
    quest_ids = {p.stem for p in QUESTS_DIR.glob("qf_*.json")}
    tile_ids, anchor_ids = set(tiles), set(anchors)

    rep.check("count::regions_2", len(regions) == SC.EXPECTED_REGION_COUNT,
              "expected 2 regions (got {})".format(len(regions)),
              code=F.STREAMING_REGION_CONTRACT_INVALID)
    rep.check("count::tiles_6", len(tiles) == 6, "expected 6 tiles (got {})".format(len(tiles)),
              code=F.STREAMING_TILE_CONTRACT_INVALID)

    # --- regions ---
    for rid, r in regions.items():
        fails = [c for c in SC.validate_region_definition(r, strict=True) if not c[1]]
        rep.check("region::{}::contract".format(rid), len(fails) == 0,
                  "region invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_REGION_CONTRACT_INVALID)
        for t in r.get("tile_ids", []):
            rep.check("region::{}::tile_resolves::{}".format(rid, t), t in tile_ids,
                      "region tile {} does not resolve".format(t),
                      code=F.STREAMING_TILE_GRAPH_DISCONNECTED)

    # --- tiles: reciprocal neighbors + anchors resolve + ownership manifest exists ---
    for tid, t in tiles.items():
        fails = [c for c in SC.validate_tile_definition(t, strict=True) if not c[1]]
        rep.check("tile::{}::contract".format(tid), len(fails) == 0,
                  "tile invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_TILE_CONTRACT_INVALID)
        for n in t.get("neighbor_tile_ids", []):
            rep.check("tile::{}::neighbor_resolves::{}".format(tid, n), n in tile_ids,
                      "neighbor {} does not resolve".format(n),
                      code=F.STREAMING_TILE_GRAPH_DISCONNECTED)
            back = tiles.get(n, {}).get("neighbor_tile_ids", [])
            rep.check("tile::{}::neighbor_reciprocal::{}".format(tid, n), tid in back,
                      "neighbor {} must list {} back (reciprocity)".format(n, tid),
                      code=F.STREAMING_NEIGHBOR_NOT_RECIPROCAL)
        for a in t.get("anchor_ids", []):
            rep.check("tile::{}::anchor_resolves::{}".format(tid, a), a in anchor_ids,
                      "tile anchor {} does not resolve".format(a), code=F.STREAMING_ANCHOR_INVALID)
        omp = t.get("ownership_manifest_path", "")
        rep.check("tile::{}::ownership_manifest_exists".format(tid),
                  bool(omp) and (REPO_ROOT / omp).is_file(),
                  "ownership_manifest_path does not resolve: {}".format(omp),
                  code=F.STREAMING_TILE_CONTRACT_INVALID)

    # --- anchors: links resolve + reciprocate + tile resolves ---
    for aid, a in anchors.items():
        fails = [c for c in SC.validate_cross_tile_anchor(a, strict=True) if not c[1]]
        rep.check("anchor::{}::contract".format(aid), len(fails) == 0,
                  "anchor invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_ANCHOR_INVALID)
        rep.check("anchor::{}::tile_resolves".format(aid), a.get("tile_id") in tile_ids,
                  "anchor tile {} does not resolve".format(a.get("tile_id")),
                  code=F.STREAMING_ANCHOR_INVALID)
        for linked in a.get("linked_anchor_ids", []):
            rep.check("anchor::{}::link_resolves::{}".format(aid, linked), linked in anchor_ids,
                      "linked anchor {} does not resolve".format(linked),
                      code=F.STREAMING_ANCHOR_LINK_BROKEN)
            rep.check("anchor::{}::link_reciprocal::{}".format(aid, linked),
                      aid in anchors.get(linked, {}).get("linked_anchor_ids", []),
                      "linked anchor {} must link back".format(linked),
                      code=F.STREAMING_ANCHOR_LINK_BROKEN)

    # --- routes: anchors + tiles resolve, no navmesh overclaim ---
    for rtid, rt in routes.items():
        fails = [c for c in SC.validate_cross_tile_route(rt, strict=True) if not c[1]]
        rep.check("route::{}::contract".format(rtid), len(fails) == 0,
                  "route invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_ROUTE_INVALID)
        for f in ("source_anchor_id", "target_anchor_id"):
            rep.check("route::{}::{}_resolves".format(rtid, f), rt.get(f) in anchor_ids,
                      "route {} {} does not resolve".format(rtid, f),
                      code=F.STREAMING_ANCHOR_LINK_BROKEN)
        for t in rt.get("tile_sequence", []):
            rep.check("route::{}::tile_resolves::{}".format(rtid, t), t in tile_ids,
                      "route tile {} does not resolve".format(t),
                      code=F.STREAMING_ROUTE_TILE_SEQUENCE_INVALID)
        rep.check("route::{}::no_navmesh_overclaim".format(rtid),
                  not (rt.get("objective_access_status") == "pass"
                       and rt.get("traversal_mode") not in SC.PROVED_TRAVERSAL_MODES),
                  "route claims proved access without a proved grounded mode",
                  code=F.STREAMING_NAVMESH_OVERCLAIM)

    # --- bindings ---
    rep.check("count::mission_bindings_24", len(missions) == 24,
              "expected 24 mission bindings (got {})".format(len(missions)),
              code=F.STREAMING_PARTIAL_MATRIX)
    rep.check("count::npc_bindings_24", len(npcs) == 24,
              "expected 24 npc bindings (got {})".format(len(npcs)),
              code=F.STREAMING_PARTIAL_MATRIX)
    scenarios_seen = set()
    for bid, m in missions.items():
        fails = [c for c in SC.validate_streamed_mission_binding(m, strict=True) if not c[1]]
        rep.check("mission::{}::contract".format(bid), len(fails) == 0,
                  "mission invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_MISSION_BINDING_INVALID)
        scenarios_seen.add(m.get("scenario_id"))
        for t in m.get("required_tile_ids", []):
            rep.check("mission::{}::tile_resolves::{}".format(bid, t), t in tile_ids,
                      "required tile {} does not resolve".format(t),
                      code=F.STREAMING_MISSION_BINDING_INVALID)
        for a in [m.get("start_anchor_id"), m.get("completion_anchor_id")] + m.get("objective_anchor_ids", []):
            rep.check("mission::{}::anchor_resolves::{}".format(bid, a), a in anchor_ids,
                      "mission anchor {} does not resolve".format(a),
                      code=F.STREAMING_ANCHOR_INVALID)
        for rt in m.get("required_cross_tile_routes", []):
            rep.check("mission::{}::route_resolves::{}".format(bid, rt), rt in routes,
                      "required route {} does not resolve".format(rt),
                      code=F.STREAMING_ROUTE_INVALID)
        rep.check("mission::{}::quest_resolves".format(bid), m.get("quest_id") in quest_ids,
                  "quest_id {} does not resolve to a v2.2 quest".format(m.get("quest_id")),
                  code=F.STREAMING_QUEST_STATE_MISSING)
    for bid, npc in npcs.items():
        fails = [c for c in SC.validate_streamed_npc_binding(npc, strict=True) if not c[1]]
        rep.check("npc::{}::contract".format(bid), len(fails) == 0,
                  "npc invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_NPC_BINDING_INVALID)
        rep.check("npc::{}::spawn_anchor_resolves".format(bid),
                  npc.get("spawn_anchor_id") in anchor_ids,
                  "npc spawn anchor does not resolve", code=F.STREAMING_ANCHOR_INVALID)
        for t in npc.get("allowed_tile_ids", []):
            rep.check("npc::{}::allowed_tile_resolves::{}".format(bid, t), t in tile_ids,
                      "npc allowed tile {} does not resolve".format(t),
                      code=F.STREAMING_NPC_BINDING_INVALID)

    rep.check("coverage::24_scenarios", len(scenarios_seen) == SC.EXPECTED_SCENARIO_COUNT,
              "bindings must cover 24 scenarios (got {})".format(len(scenarios_seen)),
              code=F.STREAMING_PARTIAL_MATRIX)
    return len(regions) + len(tiles) + len(anchors) + len(routes) + len(missions) + len(npcs)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 generated-authoring gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = validate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-streaming-authoring", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.streaming.authoring_validation.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_streaming_authoring_report.json")
    rep.print_summary("validate-streaming-authoring")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
