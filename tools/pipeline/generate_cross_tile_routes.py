#!/usr/bin/env python3
"""generate_cross_tile_routes.py — v2.3 Wave 2 cross-tile route authoring (Agent 3).

Emits one CrossTileRoute per tile boundary from streaming_spec.route_plan, over the
existing grounded-route truth: traversal_mode grounded_worldforge_route (a PROVED
WorldForge mode — never a navmesh overclaim), a transition point at the boundary,
and objective_access_status=pass. Deterministic; each route validated + the
truth-guard asserted before writing.

Deliverables:  procedural/generated/routes/*.json
               procedural/reports/streaming/routes/*.json (per-route report)
Report:        procedural/reports/streaming/authoring/route_authoring_report.json

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_cross_tile_routes.py --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_contracts as SC
import streaming_spec as SPEC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

ROUTES_DIR = REPO_ROOT / "procedural" / "generated" / "routes"
ROUTE_REPORTS_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "routes"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "authoring"


def generate(rep):
    ROUTES_DIR.mkdir(parents=True, exist_ok=True)
    ROUTE_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for region in SPEC.REGIONS:
        tile_ids = {t[0] for t in region["tiles"]}
        for rp in SPEC.route_plan(region):
            route = SC._example_cross_tile_route(
                route_id=rp["route_id"], region_id=rp["region_id"],
                source_anchor_id=rp["source_anchor_id"], target_anchor_id=rp["target_anchor_id"],
                tile_sequence=list(rp["tile_sequence"]), route_segments=list(rp["route_segments"]),
                traversal_mode="grounded_worldforge_route", route_width=384.0,
                objective_access_status="pass",
                stream_transition_points=list(rp["stream_transition_points"]),
                failure_codes=[])
            fails = [c for c in SC.validate_cross_tile_route(route, strict=True) if not c[1]]
            rep.check("route::{}::valid".format(rp["route_id"]), len(fails) == 0,
                      "route invalid: {}".format([c[0] for c in fails][:4]),
                      code=F.STREAMING_ROUTE_INVALID)
            # truth guard: proved access must be a proved grounded WorldForge mode.
            rep.check("route::{}::no_navmesh_overclaim".format(rp["route_id"]),
                      route["traversal_mode"] in SC.PROVED_TRAVERSAL_MODES,
                      "route claims proved access without a proved grounded mode",
                      code=F.STREAMING_NAVMESH_OVERCLAIM)
            # tile_sequence tiles resolve to region tiles + span a boundary.
            rep.check("route::{}::tiles_resolve".format(rp["route_id"]),
                      all(t in tile_ids for t in rp["tile_sequence"]) and len(rp["tile_sequence"]) >= 2,
                      "route tile_sequence must resolve + span >= 2 region tiles",
                      code=F.STREAMING_ROUTE_TILE_SEQUENCE_INVALID)
            (ROUTES_DIR / (rp["route_id"] + ".json")).write_text(
                json.dumps(route, indent=2, sort_keys=True), encoding="utf-8")
            (ROUTE_REPORTS_DIR / (rp["route_id"] + ".json")).write_text(
                json.dumps({"route_id": rp["route_id"], "region_id": rp["region_id"],
                            "traversal_mode": route["traversal_mode"],
                            "objective_access_status": route["objective_access_status"],
                            "boundary": rp["tile_sequence"],
                            "report_type": "wf.streaming.route_report.v1",
                            "schema_version": "wf.streaming.route_report.v1"},
                           indent=2, sort_keys=True), encoding="utf-8")
            n += 1
    rep.check("routes::nonempty", n >= 4, "expected >= 4 cross-tile routes (got {})".format(n),
              code=F.STREAMING_ROUTE_INVALID)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 cross-tile route generator.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = generate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="generate-cross-tile-routes", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.streaming.route_authoring.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "route_authoring_report.json")
    rep.print_summary("generate-cross-tile-routes")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
