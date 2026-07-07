#!/usr/bin/env python3
"""validate_biome_visual_readability.py — WorldForge v1.5 VisualEnvironmentForge.

For each pack-biome VisualEnvironmentKit + its maps, prove the composed visuals
stay LEGIBLE:

  * Route legibility — delegate per map to validate_visual_readability.check_map
    (fog-vs-route visibility, exposure EV window, dressing clearance vs waypoints,
    and the map's existing PlaytestForge completion). We do NOT re-implement that
    math; we call the v1.3.5 gate's own check helper so the readability floor is
    one definition.
  * Hazard zones carry a DISTINCT visual marker (VISUAL_HAZARD_READABILITY_FAILURE
    if absent).
  * Safe vs danger zones use DIFFERENT visual language — identical marker specs are
    VISUAL_SAFE/DANGER_ZONE_READABILITY_FAILURE (a player must be able to tell a
    safe zone from a danger zone by look).
  * POI / objective stays readable (the mission's primary POI carries a gameplay
    anchor).

Fail-closed: a biome with no kit, or a kit whose biome has no maps, fails. Report:
wf.visual.biome_readability_report.v1.

Usage:
    python tools/pipeline/validate_biome_visual_readability.py --pack encounter_loop_world [--strict]
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import asset_paths
import visual_contract as VC
import validate_visual_readability as R
import mission_contract as MC
from visual_catalog import load_visual_catalog
from mission_catalog import load_mission_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

PACK_BIOMES = (
    "temperate_forest", "alpine_snow", "volcanic_ashlands",
    "wetland_mire", "alien_crystal_badlands",
)

ROUTE_CODE = FailureCode.VISUAL_ROUTE_READABILITY_FAILURE
HAZARD_CODE = FailureCode.VISUAL_HAZARD_READABILITY_FAILURE
SAFE_CODE = FailureCode.VISUAL_SAFE_ZONE_READABILITY_FAILURE
DANGER_CODE = FailureCode.VISUAL_DANGER_ZONE_READABILITY_FAILURE


def _load_kits():
    kits = {}
    d = asset_paths.VISUAL_KITS_DIR
    if not d.is_dir():
        return kits
    for p in sorted(d.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(rec, dict) and rec.get("biome"):
            kits[rec["biome"]] = rec
    return kits


def _marker_signature(zone):
    """A comparable signature of a zone's visual language (marker_type + color)."""
    zone = zone or {}
    return (zone.get("marker_type"), tuple(zone.get("color_rgb") or []))


def check_kit_zones(rep, biome, kit):
    """Per-zone visual-language checks for one biome kit."""
    def c(name, ok, detail, code):
        return rep.check("{}::{}".format(biome, name), ok, detail, code=code)

    hazard = kit.get("hazard_visual_language") or {}
    safe = kit.get("safe_zone_visual_language") or {}
    danger = kit.get("danger_zone_visual_language") or {}

    c("hazard_marker_distinct", bool(hazard.get("marker_type")),
      "hazard zone has no distinct visual marker", HAZARD_CODE)

    sig_hazard, sig_safe, sig_danger = (
        _marker_signature(hazard), _marker_signature(safe), _marker_signature(danger))

    c("safe_zone_distinct_from_danger", sig_safe != sig_danger,
      "safe and danger zones share identical visual language {}".format(sig_safe),
      SAFE_CODE)
    c("danger_zone_distinct_from_safe", sig_danger != sig_safe,
      "danger and safe zones share identical visual language {}".format(sig_danger),
      DANGER_CODE)
    c("safe_zone_distinct_from_hazard", sig_safe != sig_hazard,
      "safe and hazard zones share identical visual language {}".format(sig_safe),
      SAFE_CODE)

    rr = kit.get("route_readability_rules") or {}
    c("route_readability_rules_present",
      bool(rr) and rr.get("objective_must_be_visible") is True,
      "route_readability_rules missing objective-visibility rule: {}".format(rr),
      ROUTE_CODE)


def check_biome_maps(rep, biome, kit, maps, sid2mid):
    """Route/exposure/dressing/playtest legibility over every map of a biome,
    delegated to the v1.3.5 readability gate's own check_map."""
    biome_maps = sorted(sid for sid, e in maps.items() if (e or {}).get("biome") == biome)
    rep.check("{}::has_maps".format(biome), bool(biome_maps),
              "no materialized maps for biome {}".format(biome), code=ROUTE_CODE)

    n = 0
    for sid in biome_maps:
        entry = maps.get(sid) or {}
        rig_rel = entry.get("rig_path") or "{}/{}.json".format(VC.ENV_RIGS_REL, sid)
        rig, rerr = R._read_json(REPO_ROOT / rig_rel)
        if rig is None:
            rep.check("{}::rig_loads".format(sid), False, rerr or rig_rel, code=ROUTE_CODE)
            continue
        mission_id = sid2mid.get(sid)
        if not mission_id:
            rep.check("{}::mission_bound".format(sid), False,
                      "no mission carries source_map={}".format(sid), code=ROUTE_CODE)
            continue
        mission, merr = MC.load_mission(mission_id, REPO_ROOT)
        if mission is None:
            rep.check("{}::mission_loads".format(sid), False, merr, code=ROUTE_CODE)
            continue
        dress_rel = entry.get("dressing_path") or "{}/{}.json".format(VC.DRESSING_REL, sid)
        dressing, _ = R._read_json(REPO_ROOT / dress_rel)

        # Delegate the full fog/exposure/dressing/playtest legibility math.
        R.check_map(rep, sid, rig, mission, mission_id, dressing)

        # POI / objective readability: the mission's primary POI must carry an anchor.
        poi = (mission.get("primary_poi") or {}).get("gameplay_anchor")
        rep.check("{}::poi_objective_readable".format(sid), bool(poi),
                  "mission {} primary POI has no gameplay anchor".format(mission_id),
                  code=ROUTE_CODE)
        n += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate v1.5 biome visual readability (route/zone legibility).")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    kits = _load_kits()
    maps = (load_visual_catalog(REPO_ROOT).get("maps") or {})
    sid2mid = R._slice_to_mission(load_mission_catalog(REPO_ROOT))

    if not kits:
        rep.error("no visual kits found — run create_visual_environment_kits.py first")
    if not maps:
        rep.error("no materialized visual maps — run the v1.3.5 visual materialization")

    total_maps = 0
    for biome in PACK_BIOMES:
        kit = kits.get(biome)
        if kit is None:
            rep.check("biome_has_kit::{}".format(biome), False,
                      "no visual kit for biome {}".format(biome),
                      code=FailureCode.VISUAL_KIT_MISSING_BIOME)
            continue
        check_kit_zones(rep, biome, kit)
        total_maps += check_biome_maps(rep, biome, kit, maps, sid2mid)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-biome-visual-readability", pack=args.pack, strict=strict,
        report_type="wf.visual.biome_readability_report.v1", status=rep.status,
        record_count=len(kits), records_total=len(PACK_BIOMES),
        records_passed=sum(1 for b in PACK_BIOMES if b in kits),
        records_failed=sum(1 for b in PACK_BIOMES if b not in kits),
        extra={"maps_checked": total_maps}))
    d, fname = asset_paths.report_path("visual", "validate_biome_visual_readability")
    rep.write(d, fname)
    rep.print_summary("validate-biome-visual-readability")
    print("[validate-biome-visual-readability] {} kits, {} maps checked".format(
        len(kits), total_maps))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
