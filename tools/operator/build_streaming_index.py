#!/usr/bin/env python3
"""build_streaming_index.py — v2.3 Wave 5 operator region/tile index (Agent 7).

Extends OperatorForge so v2.3 regions, tiles, anchors, routes, lifecycle, budgets,
and failures are inspectable. Reads the generated authoring + Wave-3/4 runtime
evidence and builds:

  index/region_views.json   list[OperatorRegionView], contract-validated
  index/tile_views.json     list[OperatorTileView], contract-validated
  index/streaming_index.json  coverage roll-up (2 regions / 6 tiles / 24 scenarios)

Every view is DERIVED from real evidence and validated against its contract before
writing — a view that fails its schema, or a passing tile view with no lifecycle
report, turns this builder RED (fail-closed).

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/build_streaming_index.py --strict
Reports -> procedural/reports/operator/index/build_streaming_index_report.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import streaming_contracts as SC
import streaming_spec as SPEC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

GEN = REPO_ROOT / "procedural" / "generated"
RUNTIME_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "runtime"
LIFECYCLE_REL = "procedural/reports/streaming/lifecycle"
INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
REPORT_DIR = INDEX_DIR


def _load_all(d, pat="*.json"):
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob(pat))}


def _git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
                              capture_output=True, text=True).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def build(rep, sha):
    regions = _load_all(GEN / "regions")
    tiles = _load_all(GEN / "tiles")
    routes = _load_all(GEN / "routes")
    run_reports = [json.loads((d / "report.json").read_text(encoding="utf-8"))
                   for d in sorted(RUNTIME_DIR.iterdir())
                   if d.is_dir() and (d / "report.json").is_file()]
    runs_by_region, lifecycle_by_tile = {}, {}
    for r in run_reports:
        runs_by_region.setdefault(r["region_id"], []).append(r)
        for tile_id in r["tile_sequence_seen"]:
            lifecycle_by_tile.setdefault(tile_id, []).append(
                "{}/{}__{}.json".format(LIFECYCLE_REL, r["run_id"], tile_id))

    # --- region views ---
    region_views = []
    for rid, region in regions.items():
        runs = runs_by_region.get(rid, [])
        scenarios = [r["scenario_id"] for r in runs]
        clean = all(not r["failure_codes"] for r in runs) and len(runs) > 0
        graph = {t: tiles[t]["neighbor_tile_ids"] for t in region["tile_ids"] if t in tiles}
        anchors = sorted({a for t in region["tile_ids"] if t in tiles
                          for a in tiles[t]["anchor_ids"]})
        rroutes = sorted(rt for rt, rd in routes.items() if rd["region_id"] == rid)
        rv = SC._example_operator_region_view(
            region_id=rid,
            region_definition_path="procedural/generated/regions/{}.json".format(rid),
            tile_ids=list(region["tile_ids"]), tile_graph=graph, anchors=anchors,
            cross_tile_routes=rroutes, streaming_scenarios=sorted(scenarios),
            runtime_status_summary="pass" if clean else "blocked",
            budget_status_summary="pass" if all(r["budget_result"] in ("pass", "advisory")
                                                for r in runs) else "exceeded",
            save_load_status_summary="roundtrip_ok" if all(
                r["cross_tile_save_load_result"] == "roundtrip_ok" for r in runs) else "roundtrip_failed",
            quest_faction_status_summary="updated" if all(
                r["quest_state_updated"] and r["faction_state_updated"] for r in runs) else "missing",
            failure_codes=[])
        fails = [c for c in SC.validate_operator_region_view(rv, strict=True) if not c[1]]
        rep.check("rv::{}::valid".format(rid), len(fails) == 0,
                  "region view invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_OPERATOR_VIEW_INVALID)
        region_views.append(rv)

    # --- tile views ---
    tile_views = []
    for tid, tile in tiles.items():
        lrs = sorted(set(lifecycle_by_tile.get(tid, [])))
        troutes = sorted(rt for rt, rd in routes.items() if tid in rd["tile_sequence"])
        tv = SC._example_operator_tile_view(
            tile_id=tid, region_id=tile["region_id"], map_id=tile["map_id"],
            tile_role=tile["tile_role"], neighbors=list(tile["neighbor_tile_ids"]),
            anchors=list(tile["anchor_ids"]), lifecycle_reports=lrs,
            route_reports=troutes, budget_reports=[tile["budget_profile_id"]],
            asset_ownership_paths=[tile["ownership_manifest_path"]],
            runtime_status="pass" if lrs else "not_run", failure_codes=[])
        fails = [c for c in SC.validate_operator_tile_view(tv, strict=True) if not c[1]]
        rep.check("tv::{}::valid".format(tid), len(fails) == 0,
                  "tile view invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_OPERATOR_VIEW_INVALID)
        tile_views.append(tv)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    (INDEX_DIR / "region_views.json").write_text(
        json.dumps(region_views, indent=2, sort_keys=True), encoding="utf-8")
    (INDEX_DIR / "tile_views.json").write_text(
        json.dumps(tile_views, indent=2, sort_keys=True), encoding="utf-8")
    (INDEX_DIR / "streaming_index.json").write_text(
        json.dumps({"schema_version": "wf.streaming.operator_index.v1",
                    "report_type": "wf.streaming.operator_index.v1",
                    "created_by": "worldforge.v2.3", "created_at": "live", "git_sha": sha,
                    "region_view_count": len(region_views), "tile_view_count": len(tile_views),
                    "region_view_path": "procedural/reports/operator/index/region_views.json",
                    "tile_view_path": "procedural/reports/operator/index/tile_views.json"},
                   indent=2, sort_keys=True), encoding="utf-8")

    rep.check("index::2_region_views", len(region_views) == SC.EXPECTED_REGION_COUNT,
              "expected 2 region views (got {})".format(len(region_views)),
              code=F.STREAMING_OPERATOR_VIEW_INVALID)
    rep.check("index::6_tile_views", len(tile_views) == 6,
              "expected 6 tile views (got {})".format(len(tile_views)),
              code=F.STREAMING_OPERATOR_VIEW_INVALID)
    return len(region_views) + len(tile_views)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 operator streaming index builder.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "streaming_operator_index", strict=strict)
    n = build(rep, _git_sha())
    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-streaming-index", pack=None, strict=strict, status=rep.status,
        record_count=n, records_total=n, report_type="wf.streaming.operator_index.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "build_streaming_index_report.json")
    rep.print_summary("operator-streaming-index")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
