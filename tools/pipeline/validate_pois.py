#!/usr/bin/env python3
"""validate_pois.py — WorldForge v1.0x POI usability validator.

Proves each map's level-design overlay places *usable* POIs, not decorative
markers. Per POI: bounds valid; not floating; not buried; within terrain; not
overlapping forbidden (danger) zones; not intersecting critical routes; has
approach + exit vectors; has a gameplay anchor; carries inspection metadata;
carries ownership/provenance; declares biome + style compatibility; declares a
budget classification.

Placement/geometry defects are tagged POI_PLACEMENT_INVALID; metadata/usability
defects are tagged POI_USABILITY_FAILURE.

Importable core: ``validate_pack(pack, strict, overlay_dir=None) -> ValidationReport``.
The per-overlay logic (``check_overlay``) accepts an overlay dict directly, so the
negative harness can inject broken overlays without touching disk layout.

Usage:
    PYTHONUTF8=1 python tools/pipeline/validate_pois.py --pack desert_mvp_world --strict
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
    load_overlay, rect_valid, rect_within_rect_xy, rects_overlap_xy,
    seg_point_dist_xy, PATH_CLEARANCE_CM, Z_TOL_CM, BUDGET_CLASSES,
)


def _terrain_rect(overlay):
    tb = overlay.get("terrain_bounds") or {}
    if not (isinstance(tb.get("min"), list) and isinstance(tb.get("max"), list)):
        return None
    return {"min": tb["min"], "max": tb["max"]}


def _nonzero_vec(v):
    return isinstance(v, list) and len(v) >= 2 and any(abs(float(x)) > 1e-6 for x in v[:2])


def _crit_segments(overlay):
    nodes = {n.get("id"): n for n in (overlay.get("graph") or {}).get("nodes", [])}
    segs = []
    for a, b in (("player_start", "primary_poi"), ("primary_poi", "secondary_poi")):
        na, nb = nodes.get(a), nodes.get(b)
        if na and nb and na.get("position") and nb.get("position"):
            segs.append((na["position"], nb["position"]))
    return segs


def _placement_ok(poi, terrain_rect, height_range, danger_zones, crit_segs, is_endpoint):
    reasons = []
    b = poi.get("bounds")
    if not rect_valid(b):
        return False, "bounds invalid/degenerate"
    if terrain_rect is None:
        reasons.append("terrain_bounds missing")
    elif not rect_within_rect_xy(b, terrain_rect):
        reasons.append("bounds not within terrain")
    pos = poi.get("world_position")
    if not (isinstance(pos, list) and len(pos) >= 3):
        return False, "world_position missing/short"
    z = float(pos[2])
    lo, hi = float(height_range[0]), float(height_range[1])
    if z < lo - Z_TOL_CM:
        reasons.append("buried (z={} < {})".format(z, lo))
    if z > hi + Z_TOL_CM:
        reasons.append("floating (z={} > {})".format(z, hi))
    if len(b["min"]) > 2 and float(b["min"][2]) < lo - Z_TOL_CM:
        reasons.append("bounds floor below terrain")
    for dz in danger_zones:
        if rects_overlap_xy(b, dz.get("bounds", {})):
            reasons.append("overlaps forbidden zone {}".format(dz.get("id")))
    if not is_endpoint and crit_segs:
        dmin = min(seg_point_dist_xy(a, bb, pos) for a, bb in crit_segs)
        if dmin < PATH_CLEARANCE_CM:
            reasons.append("intersects critical path (dist={:.0f} < {:.0f})".format(
                dmin, PATH_CLEARANCE_CM))
    return (not reasons), "; ".join(reasons)


def _usability_ok(poi, biome):
    reasons = []
    if not _nonzero_vec(poi.get("approach_vector")):
        reasons.append("missing/zero approach_vector")
    if not _nonzero_vec(poi.get("exit_vector")):
        reasons.append("missing/zero exit_vector")
    ga = poi.get("gameplay_anchor")
    if not (isinstance(ga, list) and len(ga) >= 3):
        reasons.append("missing gameplay_anchor")
    insp = poi.get("inspection")
    if not (isinstance(insp, dict) and insp.get("inspectable")):
        reasons.append("missing inspection metadata")
    prov = poi.get("provenance")
    if not (isinstance(prov, dict) and (prov.get("generator") or prov.get("generator_name"))):
        reasons.append("missing ownership/provenance")
    bc = poi.get("biome_compat")
    if not (isinstance(bc, list) and biome in bc):
        reasons.append("biome_compat does not include '{}'".format(biome))
    sc = poi.get("style_compat")
    if not (isinstance(sc, list) and sc):
        reasons.append("empty style_compat")
    if poi.get("budget_class") not in BUDGET_CLASSES:
        reasons.append("invalid budget_class '{}'".format(poi.get("budget_class")))
    return (not reasons), "; ".join(reasons)


def check_overlay(rep, slice_id, overlay):
    """Add POI-usability checks for one overlay to ``rep``. Returns True if all pass."""
    pois = overlay.get("pois")
    if not (isinstance(pois, list) and pois):
        rep.check("{}::pois_present".format(slice_id), False,
                  "overlay has no pois list", code=FailureCode.POI_USABILITY_FAILURE)
        return False
    terrain_rect = _terrain_rect(overlay)
    height_range = (overlay.get("terrain_bounds") or {}).get("height_range_cm", [0.0, 2000.0])
    danger_zones = overlay.get("danger_zones") or []
    crit_segs = _crit_segments(overlay)
    endpoints = {"player_start", "primary_poi", "secondary_poi"}
    biome = overlay.get("biome")
    all_ok = True
    for poi in pois:
        pid = poi.get("id", "<unnamed>")
        geo_ok, geo_detail = _placement_ok(
            poi, terrain_rect, height_range, danger_zones, crit_segs, pid in endpoints)
        rep.check("{}::poi[{}]_placement".format(slice_id, pid), geo_ok,
                  geo_detail, code=FailureCode.POI_PLACEMENT_INVALID)
        use_ok, use_detail = _usability_ok(poi, biome)
        rep.check("{}::poi[{}]_usability".format(slice_id, pid), use_ok,
                  use_detail, code=FailureCode.POI_USABILITY_FAILURE)
        all_ok = all_ok and geo_ok and use_ok
    return all_ok


def validate_pack(pack, strict, overlay_dir=None):
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)
    for m in maps:
        if not m.spec_exists:
            rep.check("{}::spec_present".format(m.slice_id or "<missing>"), False,
                      m.get("spec_error") or "spec missing",
                      code=FailureCode.POI_USABILITY_FAILURE)
            continue
        overlay, err = load_overlay(m.slice_id, overlay_dir)
        if overlay is None:
            rep.check("{}::overlay_present".format(m.slice_id), False, err,
                      code=FailureCode.POI_USABILITY_FAILURE)
            continue
        check_overlay(rep, m.slice_id, overlay)
    rep.set_meta(build_meta(command="validate-pois", pack=world_pack_id, strict=strict,
                            status=None, record_count=len(maps)))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate POI usability across a world pack.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = validate_pack(args.pack, strict)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_pois_report.json")
    rep.print_summary("validate-pois")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
