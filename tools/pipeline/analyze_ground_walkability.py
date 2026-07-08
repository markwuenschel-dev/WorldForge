#!/usr/bin/env python3
"""analyze_ground_walkability.py — WorldForge v1.6z deep walkability analysis.

Runs the C++ game-world walkability probe (a grid of complex line traces on the
REAL collision the grounded pawn falls onto) over every unique map and writes a
WalkabilityReport per map. Editor-world traces do not hit the procedural terrain's
per-poly collision headlessly, so the probe runs in `-game` (the same physics the
pawn uses). --analyze prepares the grounded pawn on all maps, drives one `-game`
process per map, parses the WF_WALK / WF_GNAV markers, and writes validated
WalkabilityReports.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import ground_contracts as GX
import run_ground_runtime_batch as RB  # reuse prepare + run_game
from failure_codes import FailureCode

WALK_DIR = REPO_ROOT / GX.WALKABILITY_REPORTS_REL
RE_WALK = re.compile(
    r"WF_WALK checked=(\d+) walkable=(\d+) blocked=(\d+) unknown=(\d+) slopeF=(\d+) "
    r"stepF=(\d+) clearF=(\d+) spawnW=(\d) objW=(\d) corridorW=(\d)")
RE_NAV = re.compile(r"WF_GNAV navmesh_present=(\d) path_exists=(\d)")


def build_report(map_id, biome, text):
    m = RE_WALK.search(text)
    if not m:
        return None, "no WF_WALK marker"
    checked, walkable, blocked, unknown, slopeF, stepF, clearF, spawnW, objW, corr = (
        int(x) for x in m.groups())
    nav = RE_NAV.search(text)
    nav_present = bool(nav) and nav.group(1) == "1"
    access_ok = bool(spawnW and objW and corr)
    status = "pass" if (access_ok and walkable > 0) else ("degraded" if walkable > 0 else "fail")
    codes = []
    if not access_ok:
        codes.append(FailureCode.GROUND_OBJECTIVE_ACCESS_FAILURE)
    if status == "fail":
        codes.append(FailureCode.GROUND_SURFACE_NOT_WALKABLE)
    report = {
        "report_id": "walk:%s" % map_id, "report_type": GX.WALKABILITY_SCHEMA_VERSION,
        "schema_version": GX.WALKABILITY_SCHEMA_VERSION, "map_id": map_id, "biome": biome,
        "terrain_surfaces_checked": checked, "walkable_surfaces": walkable,
        "blocked_surfaces": blocked, "unknown_surfaces": unknown, "slope_failures": slopeF,
        "step_failures": stepF, "capsule_clearance_failures": clearF, "cover_intrusions": 0,
        "hazard_intrusions": 0, "objective_access_failures": 0 if access_ok else 1,
        "safe_zone_access_failures": 0, "danger_zone_access_failures": 0,
        "navmesh_presence": nav_present, "navmesh_coverage_ratio": 0.0,
        "worldforge_route_coverage_ratio": round(walkable / checked, 4) if checked else 0.0,
        "status": status, "failure_codes": codes, "created_at": "live",
        "spawn_walkable": bool(spawnW), "objective_walkable": bool(objW),
        "spawn_to_objective_walkable": access_ok,
    }
    bad = [c for c in GX.validate_walkability(report, strict=True) if not c[1]]
    if bad:
        return None, "invalid: {}".format([c[0] for c in bad][:4])
    return report, "ok"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-prepare", action="store_true")
    args = ap.parse_args(argv)

    recs = RB.scenarios()
    biome_by_map = {r["map_id"]: r["biome"] for r in recs}
    maps = sorted(biome_by_map)
    if args.limit:
        maps = maps[:args.limit]

    if not args.skip_prepare:
        print("[walkability] preparing grounded pawn on {} maps...".format(len(maps)))
        RB.do_prepare(args.limit)

    WALK_DIR.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    for i, mid in enumerate(maps, 1):
        _, text = RB.run_game(mid)
        report, msg = build_report(mid, biome_by_map[mid], text)
        if report:
            (WALK_DIR / "{}.json".format(mid)).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            ok += 1
            print("[{:3d}/{}] walk {:48s} walkable={}/{} status={}".format(
                i, len(maps), mid, report["walkable_surfaces"], report["terrain_surfaces_checked"],
                report["status"]))
        else:
            fail += 1
            print("[{:3d}/{}] WALK-FAIL {:44s} {}".format(i, len(maps), mid, msg))
    print("[walkability] {} reports written, {} failed".format(ok, fail))


if __name__ == "__main__":
    main()
