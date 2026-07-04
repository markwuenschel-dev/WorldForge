#!/usr/bin/env python3
"""validate_encounter_cover.py — WorldForge v1.4 encounter cover validator (Lane D).

Proves cover is REAL, USABLE and NON-OBSTRUCTIVE (brief §12/§27):

  * cover density near pressure — when the encounter has spawn anchors and
    pacing_target.min_cover_per_pressure_point > 0, the fraction of spawn
    anchors with a cover anchor within EC.COVER_NEAR_CM must reach that minimum
  * every cover anchor has a world_position, a legal height_class
    ("low"/"half_height"/"full_height") and collision True
  * cover must not block the required route: no cover anchor may sit within
    COVER_ROUTE_CLEAR_CM (600cm) of any densified mission required_route
    waypoint (EC.densify_route)
  * no orphan cover: every cover anchor lies within COVER_ORPHAN_MAX_CM
    (4000cm) of at least one spawn anchor
  * cover anchor ids are unique

Usage:
    python tools/pipeline/validate_encounter_cover.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_cover/validate_encounter_cover_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from encounter_catalog import load_encounter_catalog
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

CODE = FailureCode.ENCOUNTER_ANCHOR_FAILURE
PACING_CODE = FailureCode.ENCOUNTER_PACING_FAILURE

HEIGHT_CLASSES = ("low", "half_height", "full_height")
COVER_ROUTE_CLEAR_CM = 600.0   # cover this close to the required route blocks it
COVER_ORPHAN_MAX_CM = 4000.0   # cover farther than this from every spawn is orphaned


def check_cover(rep, eid, enc, mission, mesh_assets):
    """Core cover checks for one encounter (namespace '<check>::<eid>').

    ``mesh_assets`` is part of the shared Lane D core API (the pack-level
    driver guards the empty-catalog case); the geometric checks here are
    anchor-only.
    """
    del mesh_assets  # lane API parity; cover geometry needs no catalog lookups

    def c(name, ok, detail="", code=CODE):
        return rep.check("{}::{}".format(name, eid), ok, detail, code=code)

    covers = enc.get("cover_anchors") or []
    spawns = [a.get("world_position") for a in enc.get("spawn_anchors") or []
              if a.get("world_position")]

    # Per-anchor geometry contract.
    seen = set()
    cover_positions = []
    for cov in covers:
        cid = cov.get("id") or "<no-id>"
        c("cover_id_unique[{}]".format(cid), cid not in seen,
          "duplicate cover anchor id '{}'".format(cid))
        seen.add(cid)
        pos = cov.get("world_position")
        c("cover_has_world_position[{}]".format(cid), bool(pos),
          "cover anchor '{}' has no world_position".format(cid))
        if pos:
            cover_positions.append(pos)
        c("cover_height_class_valid[{}]".format(cid),
          cov.get("height_class") in HEIGHT_CLASSES,
          "height_class {!r} not in {}".format(cov.get("height_class"),
                                               list(HEIGHT_CLASSES)))
        c("cover_collision_enabled[{}]".format(cid), cov.get("collision") is True,
          "cover anchor '{}' collision must be True, got {!r}".format(
              cid, cov.get("collision")))

    # Cover density near pressure points (pacing_target.min_cover_per_pressure_point).
    mcpp = (enc.get("pacing_target") or {}).get("min_cover_per_pressure_point") or 0.0
    if spawns and mcpp > 0:
        near = sum(1 for s in spawns
                   if any(MC.dist2d(s, cp) <= EC.COVER_NEAR_CM
                          for cp in cover_positions))
        frac = near / len(spawns)
        c("cover_density_near_pressure", frac >= mcpp,
          "only {:.3f} of spawn anchors have cover within {:.0f}cm; "
          "pacing_target requires >= {}".format(frac, EC.COVER_NEAR_CM, mcpp),
          code=PACING_CODE)

    # Cover must not block the mission's required route.
    waypoints = EC.densify_route(
        ((mission or {}).get("required_route") or {}).get("waypoints"))
    if waypoints:
        for cov in covers:
            pos = cov.get("world_position")
            if not pos:
                continue
            dmin = min(MC.dist2d(pos, wp) for wp in waypoints)
            c("cover_clear_of_required_route[{}]".format(cov.get("id")),
              dmin >= COVER_ROUTE_CLEAR_CM,
              "cover anchor '{}' is {:.1f}cm from the densified required route "
              "(minimum clearance {:.0f}cm) — cover blocks the route".format(
                  cov.get("id"), dmin, COVER_ROUTE_CLEAR_CM))

    # No orphan cover: every cover anchor near at least one spawn anchor.
    if spawns:
        for cov in covers:
            pos = cov.get("world_position")
            if not pos:
                continue
            dmin = min(MC.dist2d(pos, s) for s in spawns)
            c("cover_not_orphaned[{}]".format(cov.get("id")),
              dmin <= COVER_ORPHAN_MAX_CM,
              "cover anchor '{}' is {:.1f}cm from the nearest spawn anchor "
              "(max {:.0f}cm) — orphan cover".format(
                  cov.get("id"), dmin, COVER_ORPHAN_MAX_CM))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 encounter cover anchors.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    mesh_assets = (load_mesh_catalog(REPO_ROOT) or {}).get("assets") or {}
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted(eid for eid, e in (catalog.get("encounters") or {}).items()
                  if (e or {}).get("pack_id") == args.pack)
    if not eids:
        rep.error("no encounters in pack '{}' — run 'make create-encounters' first".format(args.pack))
    if not mesh_assets:
        rep.error("no generated mesh catalog — run the v1.2 MeshForge intake first")

    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("loads::{}".format(eid), False, err, code=CODE)
            continue
        mission, merr = MC.load_mission(enc.get("mission_id") or "")
        if mission is None:
            rep.check("mission_loads::{}".format(eid), False, merr, code=CODE)
            continue
        check_cover(rep, eid, enc, mission, mesh_assets)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-cover", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_cover",
              "validate_encounter_cover_report.json")
    rep.print_summary("validate-encounter-cover")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
