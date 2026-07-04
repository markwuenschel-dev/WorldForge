#!/usr/bin/env python3
"""validate_world_dressing.py — WorldForge v1.3.5 world-dressing gate (Agent 2 lane).

Proves the world-dressing layer is real AND readable (brief Pillar 3 + Pillar 6).
Per mission map: dressing_assets is non-empty; every dressing asset exists (mesh
catalog for generated, external catalog for Megascans) and is biome-compatible;
at least one dressing asset is near the primary POI; and — the load-bearing
readability rule — NO dressing asset blocks the mission: every dressing position
must clear every required-route waypoint and the player start by a small margin
(> 200 cm). A dressing asset on the route or start is a WORLD_DRESSING_FAILURE
("dressing blocks route"). Ownership is source-safe (generated dressing
generated_owned; Megascans third_party_owned).

Code: WORLD_DRESSING_FAILURE.

Usage:
    python tools/pipeline/validate_world_dressing.py --pack mission_loop_world [--strict]
Writes: procedural/reports/visual/validate_world_dressing/validate_world_dressing_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import visual_contract as VC
from mission_catalog import load_mission_catalog
import mission_contract as MC
from mesh_catalog import load_mesh_catalog
from external_asset_contract import load_external_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

DRESS = FailureCode.WORLD_DRESSING_FAILURE

# Readability clearance floor (must match the generator's design): every dressing
# position must be strictly farther than this from every route waypoint + start.
CLEARANCE_MIN_CM = 200.0
# A dressing asset within this of the POI counts as "near the primary POI".
NEAR_POI_MAX_CM = 4000.0


def _dist2d(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _load_plan(slice_id):
    p = REPO_ROOT / VC.DRESSING_REL / (slice_id + ".json")
    if not p.is_file():
        return None, "dressing plan not found: {}".format(p)
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, "dressing plan unparseable: {}".format(exc)


def _biome_compatible(aid, source, biome, ext_assets, mesh_assets):
    """(exists, biome_ok). source is 'mesh_catalog' or 'external_catalog'; when
    unset we accept the asset from whichever catalog holds it."""
    if source == "external_catalog":
        e = ext_assets.get(aid)
        if e is None:
            return False, False
        return True, biome in (e.get("biome_compatibility") or [])
    if source == "mesh_catalog":
        e = mesh_assets.get(aid)
        if e is None:
            return False, False
        return True, biome in (e.get("biome_compatibility") or [])
    # unknown source: look in both catalogs.
    if aid in mesh_assets:
        return True, biome in (mesh_assets[aid].get("biome_compatibility") or [])
    if aid in ext_assets:
        return True, biome in (ext_assets[aid].get("biome_compatibility") or [])
    return False, False


def _check_map(rep, slice_id, biome, plan, mission, ext_assets, mesh_assets):
    def c(name, ok, detail, code=DRESS):
        return rep.check("{}::{}".format(slice_id, name), ok, detail, code=code)

    dressing = plan.get("dressing_assets") or []
    c("dressing_non_empty", len(dressing) >= 1, "{} dressing assets".format(len(dressing)))
    if not dressing:
        return

    start = mission["start_anchor"]["world_position"]
    poi = mission["primary_poi"]["gameplay_anchor"]
    waypoints = (mission.get("required_route") or {}).get("waypoints") or [start, poi]
    clearance_pts = list(waypoints) + [start]

    near_poi = False
    for i, d in enumerate(dressing):
        aid = d.get("asset_id")
        pos = d.get("world_position")
        ownership = d.get("ownership_class")
        source = d.get("source")

        exists, biome_ok = _biome_compatible(aid, source, biome, ext_assets, mesh_assets)
        c("asset_{}_exists".format(i), exists, "asset_id={} source={}".format(aid, source))
        c("asset_{}_biome_compatible".format(i), biome_ok,
          "asset_id={} not biome-compatible with {}".format(aid, biome),
          code=FailureCode.MESH_BIOME_COMPATIBILITY_FAILURE)

        # ownership safety: external -> third_party_owned; mesh -> generated_owned.
        if source == "external_catalog" or aid in ext_assets:
            c("asset_{}_ownership".format(i), ownership == VC.OWNERSHIP_THIRD_PARTY,
              "megascans dressing ownership={} (must be {})".format(ownership, VC.OWNERSHIP_THIRD_PARTY))
        else:
            c("asset_{}_ownership".format(i), ownership == VC.OWNERSHIP_GENERATED,
              "generated dressing ownership={} (must be {})".format(ownership, VC.OWNERSHIP_GENERATED))

        # CRITICAL readability: dressing must not block the route or player start.
        if not (isinstance(pos, (list, tuple)) and len(pos) >= 2):
            c("asset_{}_position_valid".format(i), False, "invalid position {}".format(pos))
            continue
        clearance = min(_dist2d(pos, p) for p in clearance_pts)
        c("asset_{}_clears_route".format(i), clearance > CLEARANCE_MIN_CM,
          "dressing blocks route: clearance={:.1f}cm (min {})".format(clearance, CLEARANCE_MIN_CM))

        if _dist2d(pos, poi) <= NEAR_POI_MAX_CM:
            near_poi = True

    c("at_least_one_near_poi", near_poi,
      "no dressing asset within {}cm of primary POI".format(NEAR_POI_MAX_CM))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3.5 world dressing + readability.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    mission_catalog = load_mission_catalog(REPO_ROOT)
    ext_assets = (load_external_catalog(REPO_ROOT).get("assets") or {})
    mesh_assets = (load_mesh_catalog(REPO_ROOT).get("assets") or {})

    mids = sorted((mission_catalog.get("missions") or {}).keys())
    if not mids:
        rep.error("no missions — run 'make create-mission-loops' first")

    n = 0
    for mid in mids:
        mission, err = MC.load_mission(mid)
        if mission is None:
            rep.check("{}::mission_loads".format(mid), False, err, code=DRESS)
            continue
        slice_id = mission["source_map"]["slice_id"]
        biome = mission["biome_family"]

        plan, perr = _load_plan(slice_id)
        if plan is None:
            rep.check("{}::plan_exists".format(slice_id), False, perr, code=DRESS)
            continue
        rep.check("{}::plan_exists".format(slice_id), True, "plan present")

        _check_map(rep, slice_id, biome, plan, mission, ext_assets, mesh_assets)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-world-dressing", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_world_dressing",
              "validate_world_dressing_report.json")
    rep.print_summary("validate-world-dressing")
    print("[validate-world-dressing] {} maps checked".format(n))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
