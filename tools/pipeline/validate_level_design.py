#!/usr/bin/env python3
"""validate_level_design.py — WorldForge v1.0x level-design validator.

Proves each map's overlay is a *designed, playable space*: a valid player start,
a primary landmark, secondary POIs, a spawn->primary route, a primary->secondary
route, danger zones that are reachable but avoidable, safe zones that are
reachable and not enemy-filled, an orientation cue, a vista/sightline cue, no
critical route crossing invalid terrain, and a POI distribution that is not all
crammed into one corner.

All defects are tagged LEVEL_DESIGN_FAILURE.

Importable core: ``validate_pack(pack, strict, overlay_dir=None) -> ValidationReport``.
``check_overlay`` accepts an overlay dict so the negative harness can inject
broken overlays.

Usage:
    PYTHONUTF8=1 python tools/pipeline/validate_level_design.py --pack desert_mvp_world --strict
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
    load_overlay, rect_valid, point_in_rect_xy, reachable_from,
)

CODE = FailureCode.LEVEL_DESIGN_FAILURE


def _terrain_rect(overlay):
    tb = overlay.get("terrain_bounds") or {}
    if not (isinstance(tb.get("min"), list) and isinstance(tb.get("max"), list)):
        return None
    return {"min": tb["min"], "max": tb["max"]}


def _pois_by_role(overlay):
    by = {}
    for p in overlay.get("pois", []) or []:
        by.setdefault(p.get("role"), []).append(p)
    return by


def _quadrant(pos, center=(0.0, 0.0)):
    return (1 if pos[0] >= center[0] else 0, 1 if pos[1] >= center[1] else 0)


def check_overlay(rep, slice_id, overlay):
    """Add level-design checks for one overlay. Returns True if all pass."""
    def chk(name, ok, detail=""):
        return rep.check("{}::{}".format(slice_id, name), ok, detail, code=CODE)

    ok_all = True
    terrain_rect = _terrain_rect(overlay)
    by_role = _pois_by_role(overlay)

    # 1. player_start exists + valid
    ps = overlay.get("player_start") or {}
    ps_pos = ps.get("world_position")
    ps_ok = (bool(ps) and rect_valid(ps.get("bounds", {}))
             and isinstance(ps_pos, list) and len(ps_pos) >= 2
             and (terrain_rect is None or point_in_rect_xy(ps_pos, terrain_rect)))
    ok_all &= chk("player_start_valid", ps_ok,
                  "player_start must exist, have valid bounds, and sit within terrain")

    # 2. primary landmark exists (primary poi + a navigation_landmark POI)
    has_primary = bool(by_role.get("primary"))
    has_landmark = any(p.get("class") == "navigation_landmark"
                       for p in overlay.get("pois", []) or [])
    ok_all &= chk("primary_landmark_exists", has_primary and has_landmark,
                  "need a primary POI and a navigation_landmark POI")

    # 3. secondary POIs exist
    ok_all &= chk("secondary_pois_exist", bool(by_role.get("secondary")),
                  "at least one secondary POI required")

    # 4/5. routes exist (over reachable/risky edges)
    prog = reachable_from(overlay, "player_start", {"reachable", "risky"})
    ok_all &= chk("route_spawn_to_primary", "primary_poi" in prog,
                  "no spawn->primary route in graph")
    from_primary = reachable_from(overlay, "primary_poi", {"reachable", "risky"})
    ok_all &= chk("route_primary_to_secondary", "secondary_poi" in from_primary,
                  "no primary->secondary route in graph")

    # 6. danger zones reachable but avoidable
    reach_all = reachable_from(overlay, "player_start", {"reachable", "risky"})
    reach_safe = reachable_from(overlay, "player_start", {"reachable"})
    danger_ids = [z.get("id") for z in overlay.get("danger_zones", []) or []]
    danger_reachable = all(d in reach_all for d in danger_ids) if danger_ids else False
    # avoidable: progression to a primary/secondary objective exists WITHOUT any
    # risky edge (i.e. over reachable-only edges, which never touch danger here).
    avoidable = ("primary_poi" in reach_safe or "secondary_poi" in reach_safe) and \
        not any(d in reach_safe for d in danger_ids)
    ok_all &= chk("danger_reachable_but_avoidable", danger_reachable and avoidable,
                  "danger zones must be reachable yet avoidable via a reachable-only route")

    # 7. safe zones reachable and not enemy-filled
    safe_zones = overlay.get("safe_zones", []) or []
    safe_ok = bool(safe_zones) and all(
        (z.get("id") in reach_safe) and (z.get("enemy_filled") is False)
        for z in safe_zones)
    ok_all &= chk("safe_zones_reachable_clean", safe_ok,
                  "safe zones must be reachable and not enemy-filled")

    # 8. orientation cue
    ori = overlay.get("orientation_cues") or []
    ok_all &= chk("orientation_cue_exists",
                  bool(ori) or bool(ps.get("orientation_cue")),
                  "an orientation cue is required")

    # 9. vista/sightline cue
    ok_all &= chk("vista_cue_exists", bool(overlay.get("vista_cues")),
                  "a vista/sightline cue is required")

    # 10. no critical route crosses invalid terrain (all critical node positions
    #     inside the terrain rectangle -> the connecting segments stay inside the
    #     convex terrain rect too).
    crit_ids = ("player_start", "primary_poi", "secondary_poi")
    nodes = {n.get("id"): n for n in (overlay.get("graph") or {}).get("nodes", [])}
    if terrain_rect is None:
        terrain_ok = False
        detail = "terrain_bounds missing"
    else:
        bad = [nid for nid in crit_ids
               if not (nodes.get(nid) and nodes[nid].get("position")
                       and point_in_rect_xy(nodes[nid]["position"], terrain_rect))]
        terrain_ok = not bad
        detail = "critical nodes outside terrain: {}".format(bad)
    ok_all &= chk("critical_route_in_terrain", terrain_ok, detail)

    # 11. POI distribution not all-in-one-corner
    positions = [p.get("world_position") for p in overlay.get("pois", []) or []
                 if isinstance(p.get("world_position"), list)]
    quads = {_quadrant(p) for p in positions}
    ok_all &= chk("poi_distribution_spread", len(quads) >= 3,
                  "POIs clustered in {} quadrant(s); need >=3".format(len(quads)))
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
    rep.set_meta(build_meta(command="validate-level-design", pack=world_pack_id,
                            strict=strict, status=None, record_count=len(maps)))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate level design across a world pack.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = validate_pack(args.pack, strict)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_level_design_report.json")
    rep.print_summary("validate-level-design")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
