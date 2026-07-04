#!/usr/bin/env python3
"""validate_encounter_anchors.py — WorldForge v1.4 encounter anchor validator (Lane B).

Proves every encounter's anchor layer is geometrically honest against its linked
mission (brief §7/§25): anchors are well-formed and uniquely identified; spawn
anchors are valid spawns that keep the contracted clearances from the player
start and the objective interaction anchors (defensive_holdout rings the
objective by design and gets a reduced floor); no spawn sits inside a mission
hazard zone (spawn in invalid terrain); cover hugs the pressure points instead
of being scattered noise; patrol and ambush anchors actually flank the mission's
required-route corridor; every spawn anchor lies inside its spawn group's
allowed danger zone; and at least one declared safe zone is genuinely outside
the pressure bubble.

Usage:
    python tools/pipeline/validate_encounter_anchors.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_anchors/validate_encounter_anchors_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from encounter_catalog import load_encounter_catalog
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

# Anchor collections this validator owns (id + world_position carriers).
ANCHOR_COLLECTIONS = ("spawn_anchors", "cover_anchors", "patrol_anchors",
                      "ambush_anchors")

# Tolerances / clearances (cm).
COVER_NEAR_SPAWN_CM = 3000.0        # cover must support a pressure point
PATROL_CORRIDOR_CM = EC.PRESSURE_RADIUS_CM * 1.5   # patrol stays connected
AMBUSH_CORRIDOR_CM = 2500.0         # ambush anchors flank the corridor
SAFE_ZONE_CLEARANCE_CM = 3000.0     # >=1 safe zone outside the pressure bubble
HOLDOUT_OBJECTIVE_FLOOR_CM = 400.0  # defensive_holdout rings the objective


def _fmt(items, n=4):
    items = list(items)
    shown = ", ".join(str(x) for x in items[:n])
    return shown + (" …(+{})".format(len(items) - n) if len(items) > n else "")


def _is_pos(p):
    return (isinstance(p, (list, tuple)) and len(p) == 3
            and all(isinstance(v, (int, float)) for v in p))


def _min_dist_to_poly(pt, poly):
    return min((MC.dist2d(pt, w) for w in poly), default=None)


def check_anchors(rep, eid, enc, mission):
    """Core anchor checks for one encounter + its linked mission (importable)."""
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(name, eid), ok, detail,
                         code=FailureCode.ENCOUNTER_ANCHOR_FAILURE)

    start = ((mission or {}).get("start_anchor") or {}).get("world_position")
    objectives = [(o.get("id"), o.get("world_position"))
                  for o in (mission or {}).get("objective_anchors") or []
                  if _is_pos(o.get("world_position"))]
    corridor = EC.densify_route(
        ((mission or {}).get("required_route") or {}).get("waypoints"))

    # 1. Every anchor entry is well-formed: id + world_position (3 floats).
    malformed, all_ids = [], []
    for coll in ANCHOR_COLLECTIONS:
        for a in enc.get(coll) or []:
            aid = (a or {}).get("id")
            if not aid or not _is_pos((a or {}).get("world_position")):
                malformed.append("{}:{}".format(coll, aid))
            if aid:
                all_ids.append(aid)
    c("anchors_well_formed", not malformed,
      "malformed anchors (id/world_position): {}".format(_fmt(malformed)))

    # 2. Anchor ids unique across ALL anchor collections.
    dupes = sorted({i for i in all_ids if all_ids.count(i) > 1})
    c("anchor_ids_unique", not dupes, "duplicate anchor ids: {}".format(_fmt(dupes)))

    spawns = [a for a in enc.get("spawn_anchors") or []
              if _is_pos(a.get("world_position"))]
    spawn_pos = [a["world_position"] for a in spawns]

    # 3. Spawn anchors are flagged as valid spawns.
    invalid = [a.get("id") for a in enc.get("spawn_anchors") or []
               if a.get("valid_spawn") is not True]
    c("spawn_anchors_valid_spawn", not invalid,
      "spawn anchors without valid_spawn=true: {}".format(_fmt(invalid)))

    # 4. Player start is not ambushed immediately.
    near_start = [(a["id"], round(MC.dist2d(a["world_position"], start), 1))
                  for a in spawns
                  if start and MC.dist2d(a["world_position"], start)
                  < EC.SAFE_START_CLEARANCE_CM]
    c("spawn_start_clearance", start is not None and not near_start,
      "spawns within {}cm of mission start: {}".format(
          EC.SAFE_START_CLEARANCE_CM, _fmt(near_start))
      if start else "mission start_anchor position missing")

    # 5. Objective interaction anchors keep their clearance
    #    (defensive_holdout rings the objective — reduced floor).
    floor = HOLDOUT_OBJECTIVE_FLOOR_CM \
        if enc.get("encounter_archetype") == "defensive_holdout" \
        else EC.OBJECTIVE_CLEARANCE_CM
    crowding = [(a["id"], oid, round(MC.dist2d(a["world_position"], op), 1))
                for a in spawns for oid, op in objectives
                if MC.dist2d(a["world_position"], op) < floor]
    c("spawn_objective_clearance", not crowding,
      "spawns within {}cm of an objective anchor: {}".format(floor, _fmt(crowding)))

    # 6. No spawn anchor inside any mission hazard zone (invalid terrain).
    in_hazard = [(a["id"], hz.get("id"))
                 for a in spawns
                 for hz in (mission or {}).get("hazard_zones") or []
                 if MC.point_in_bounds(a["world_position"], hz.get("bounds") or {})]
    c("spawn_outside_mission_hazards", not in_hazard,
      "spawns inside mission hazard zones: {}".format(_fmt(in_hazard)))

    # 7/8. Cover anchors (when present) support pressure and are usable cover.
    covers = enc.get("cover_anchors") or []
    scattered = [(a.get("id"),
                  round(_min_dist_to_poly(a["world_position"], spawn_pos) or -1, 1))
                 for a in covers if _is_pos(a.get("world_position"))
                 and ((_min_dist_to_poly(a["world_position"], spawn_pos) is None)
                      or _min_dist_to_poly(a["world_position"], spawn_pos)
                      > COVER_NEAR_SPAWN_CM)]
    c("cover_near_pressure", not scattered,
      "cover anchors farther than {}cm from every spawn anchor: {}".format(
          COVER_NEAR_SPAWN_CM, _fmt(scattered)) if covers else "no cover anchors")
    unusable = [a.get("id") for a in covers
                if not a.get("height_class") or a.get("collision") is not True]
    c("cover_fields_valid", not unusable,
      "cover anchors missing height_class/collision: {}".format(_fmt(unusable)))

    # 9. Patrol anchors (when present) stay connected to the route corridor.
    off_patrol = [(a.get("id"),
                   round(_min_dist_to_poly(a["world_position"], corridor) or -1, 1))
                  for a in enc.get("patrol_anchors") or []
                  if _is_pos(a.get("world_position"))
                  and ((_min_dist_to_poly(a["world_position"], corridor) is None)
                       or _min_dist_to_poly(a["world_position"], corridor)
                       > PATROL_CORRIDOR_CM)]
    c("patrol_on_corridor", not off_patrol,
      "patrol anchors farther than {}cm from the required-route corridor: {}".format(
          PATROL_CORRIDOR_CM, _fmt(off_patrol)))

    # 10. Ambush anchors (when present) actually flank the corridor.
    off_ambush = [(a.get("id"),
                   round(_min_dist_to_poly(a["world_position"], corridor) or -1, 1))
                  for a in enc.get("ambush_anchors") or []
                  if _is_pos(a.get("world_position"))
                  and ((_min_dist_to_poly(a["world_position"], corridor) is None)
                       or _min_dist_to_poly(a["world_position"], corridor)
                       > AMBUSH_CORRIDOR_CM)]
    c("ambush_flanks_corridor", not off_ambush,
      "ambush anchors farther than {}cm from the required-route corridor: {}".format(
          AMBUSH_CORRIDOR_CM, _fmt(off_ambush)))

    # 11. Every spawn anchor lies inside its group's allowed danger zone bounds.
    zones = {z.get("id"): z.get("bounds") or {}
             for z in enc.get("danger_zones") or []}
    by_id = {a.get("id"): a for a in spawns}
    unzoned = []
    for g in enc.get("spawn_groups") or []:
        allowed = [zones[zid] for zid in g.get("allowed_spawn_zones") or []
                   if zid in zones]
        for aid in g.get("spawn_anchor_ids") or []:
            a = by_id.get(aid)
            if a is None or not allowed or not any(
                    MC.point_in_bounds(a["world_position"], b) for b in allowed):
                unzoned.append("{}:{}".format(g.get("spawn_group_id"), aid))
    c("spawns_inside_allowed_danger_zones", not unzoned,
      "spawn anchors outside their group's allowed danger zones: {}".format(
          _fmt(unzoned)))

    # 12. At least one safe zone genuinely outside the pressure bubble.
    safes = [z.get("world_position") for z in enc.get("safe_zones") or []
             if _is_pos(z.get("world_position"))]
    clear = [z for z in safes
             if all(MC.dist2d(z, s) >= SAFE_ZONE_CLEARANCE_CM for s in spawn_pos)]
    c("safe_zone_outside_pressure", bool(clear),
      "no safe zone at least {}cm from every spawn anchor ({} safe zones)".format(
          SAFE_ZONE_CLEARANCE_CM, len(safes)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 encounter anchors.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted((catalog.get("encounters") or {}).keys())
    if not eids:
        rep.error("no encounters — run 'make create-encounters' first")
    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("loads::{}".format(eid), False, err,
                      code=FailureCode.ENCOUNTER_ANCHOR_FAILURE)
            continue
        mission, merr = MC.load_mission(enc.get("mission_id") or "")
        if mission is None:
            rep.check("mission_loads::{}".format(eid), False, merr,
                      code=FailureCode.ENCOUNTER_ANCHOR_FAILURE)
            continue
        check_anchors(rep, eid, enc, mission)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-anchors", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_anchors",
              "validate_encounter_anchors_report.json")
    rep.print_summary("validate-encounter-anchors")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
