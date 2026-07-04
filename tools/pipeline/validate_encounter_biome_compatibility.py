#!/usr/bin/env python3
"""validate_encounter_biome_compatibility.py — WorldForge v1.4 biome-compat validator (Lane B).

Proves every encounter is native to its biome (brief §7/§13/§25) — no mission
needed: the biome family is a known v1.3 family; every encounter hazard zone
uses a hazard type the biome actually produces (a lava hazard in a wetland is a
failure, not flavor); required cover mesh families are drawn from the biome's
compatible v1.2 cover substrate; every hazard zone is readable — it carries a
visual_marker AND a matching visual_marker_requirements entry; and the
biome-specific rules hold: alpine whiteout demands a visibility minimum (cover
or safe zones), volcanic ashlands demand an escape route through the hostile
zone, wetland mire only tolerates water-native hazard types, and alien crystal
resonance must be announced by a readable stylized marker.

Usage:
    python tools/pipeline/validate_encounter_biome_compatibility.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_biome_compatibility/validate_encounter_biome_compatibility_report.json
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


def _fmt(items, n=4):
    items = list(items)
    shown = ", ".join(str(x) for x in items[:n])
    return shown + (" …(+{})".format(len(items) - n) if len(items) > n else "")


def _marker_matches(enc, hz):
    """True if a visual_marker_requirements entry targets this hazard zone."""
    for v in enc.get("visual_marker_requirements") or []:
        if v.get("target_id") == hz.get("id") and v.get("marker_class"):
            return True
    return False


def check_biome(rep, eid, enc):
    """Core biome-compatibility checks for one encounter (importable)."""
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(name, eid), ok, detail,
                         code=FailureCode.ENCOUNTER_BIOME_COMPATIBILITY_FAILURE)

    biome = enc.get("biome_family")
    hazards = enc.get("hazard_zones") or []
    hazard_types = [h.get("hazard_type") for h in hazards]

    # 1. Biome family is a known v1.3 family.
    c("biome_family_known", biome in MC.BIOME_FAMILIES,
      "biome_family={} (known: {})".format(biome, ", ".join(MC.BIOME_FAMILIES)))

    # 2. Every hazard type is one the biome actually produces.
    allowed = set(EC.BIOME_HAZARD_TYPES.get(biome, ()))
    alien_h = [(h.get("id"), h.get("hazard_type")) for h in hazards
               if h.get("hazard_type") not in allowed]
    c("hazard_types_biome_allowed", not alien_h,
      "biome-inappropriate hazards for {}: {} (allowed: {})".format(
          biome, _fmt(alien_h), ", ".join(sorted(allowed))))

    # 3. Required cover families come from the biome's compatible substrate.
    fams = (enc.get("mesh_dependencies") or {}).get("required_families") or []
    cover_ok = set(EC.BIOME_COVER_FAMILIES.get(biome, ()))
    foreign = sorted(set(fams) - cover_ok)
    c("cover_families_biome_compatible", not foreign,
      "required_families outside {} cover substrate: {} (allowed: {})".format(
          biome, _fmt(foreign), ", ".join(sorted(cover_ok))))

    # 4. Every hazard zone is readable: visual_marker + matching requirement.
    unreadable = [h.get("id") for h in hazards
                  if not h.get("visual_marker") or not _marker_matches(enc, h)]
    c("hazard_zones_visually_marked", not unreadable,
      "hazard zones lacking visual_marker or a matching "
      "visual_marker_requirements entry: {}".format(_fmt(unreadable)))

    # 5. alpine_snow: whiteout pressure demands a visibility minimum.
    whiteout = biome == "alpine_snow" and "whiteout_exposure" in hazard_types
    c("alpine_whiteout_visibility_minimum",
      (not whiteout) or bool(enc.get("cover_anchors") or enc.get("safe_zones")),
      "whiteout_exposure hazard with no cover_anchors and no safe_zones"
      if whiteout else "n/a (biome={}, no whiteout hazard)".format(biome))

    # 6. volcanic_ashlands: a safe route through hostile zones must exist.
    volcanic = biome == "volcanic_ashlands"
    c("volcanic_escape_route_present",
      (not volcanic) or bool(enc.get("escape_routes")),
      "volcanic_ashlands encounter with no escape_routes"
      if volcanic else "n/a (biome={})".format(biome))

    # 7. wetland_mire: only water-native hazard types (water-safe anchors are
    #    proven in the anchors lane; here the hazard vocabulary must be native).
    wetland = biome == "wetland_mire"
    wet_allowed = set(EC.BIOME_HAZARD_TYPES.get("wetland_mire", ()))
    non_water = [(h.get("id"), h.get("hazard_type")) for h in hazards
                 if h.get("hazard_type") not in wet_allowed]
    c("wetland_water_native_hazards", (not wetland) or not non_water,
      "non-water-native hazards in wetland_mire: {}".format(_fmt(non_water))
      if wetland else "n/a (biome={})".format(biome))

    # 8. alien_crystal_badlands: crystal_resonance must be readably announced.
    crystal = [h for h in hazards if h.get("hazard_type") == "crystal_resonance"]
    unannounced = [h.get("id") for h in crystal if not _marker_matches(enc, h)]
    c("crystal_resonance_marked",
      biome != "alien_crystal_badlands" or not crystal or not unannounced,
      "crystal_resonance hazards without a visual_marker_requirements entry: {}"
      .format(_fmt(unannounced)) if crystal
      else "n/a (biome={}, no crystal_resonance hazard)".format(biome))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate v1.4 encounter biome compatibility.")
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
                      code=FailureCode.ENCOUNTER_BIOME_COMPATIBILITY_FAILURE)
            continue
        check_biome(rep, eid, enc)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-biome-compatibility",
                            pack=args.pack, strict=strict, status=rep.status,
                            record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL
              / "validate_encounter_biome_compatibility",
              "validate_encounter_biome_compatibility_report.json")
    rep.print_summary("validate-encounter-biome-compatibility")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
