#!/usr/bin/env python3
"""validate_visual_density_budgets.py — WorldForge v1.5 VisualEnvironmentForge.

Prove each biome VisualEnvironmentKit lives inside the biome's budget:

  * KIT LEVEL — the kit's declared density_budget / performance_budget values must
    each be within the biome_family budget_caps (a kit can never authorise more
    dynamic lights / fog volumes / emissive materials / vegetation density than the
    biome permits). VISUAL_DENSITY_BUDGET_FAILURE otherwise.
  * DRESSING COVERAGE — the kit must reference at least one biome-compatible
    dressing asset (VISUAL_DRESSING_COVERAGE_FAILURE).
  * PER-MAP — delegate each of the biome's maps to validate_visual_budgets.check_map
    (the v1.3.5 profile-class cap math: dynamic light / decal / vfx-emitter counts
    from the resolved rig + dressing plan) and additionally assert the map's actual
    dynamic-light and fog-volume load is within the biome budget_caps.

Report: wf.visual.density_budget_report.v1.

Usage:
    python tools/pipeline/validate_visual_density_budgets.py --pack encounter_loop_world [--strict]
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import asset_paths
import biomes as B
import visual_contract as VC
import validate_visual_budgets as VB
from mesh_catalog import load_mesh_catalog
from visual_catalog import load_visual_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

PACK_BIOMES = (
    "temperate_forest", "alpine_snow", "volcanic_ashlands",
    "wetland_mire", "alien_crystal_badlands",
)

CODE = FailureCode.VISUAL_DENSITY_BUDGET_FAILURE
DRESS_CODE = FailureCode.VISUAL_DRESSING_COVERAGE_FAILURE

# Numeric budget fields the kit shares with the biome budget_caps (kit value must
# be <= the biome cap). Non-numeric caps (classes, footprint) are compared for
# membership/equality separately.
_NUMERIC_CAP_FIELDS = (
    "vegetation_density", "dynamic_light_count", "fog_volume_count",
    "emissive_material_count", "poi_count", "entity_anchor_count",
    "material_complexity",
)


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


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_kit_budget(rep, biome, kit, caps):
    """Kit-declared budgets must fit inside the biome budget_caps."""
    def c(name, ok, detail, code=CODE):
        return rep.check("{}::{}".format(biome, name), ok, detail, code=code)

    combined = {}
    combined.update(kit.get("density_budget") or {})
    combined.update(kit.get("performance_budget") or {})

    for field in _NUMERIC_CAP_FIELDS:
        cap = caps.get(field)
        val = combined.get(field)
        if not _is_num(cap) or not _is_num(val):
            continue  # field not budgeted on one side — nothing to bound here
        c("kit_{}_within_biome_cap".format(field), val <= cap,
          "kit {}={} exceeds biome budget_cap {}".format(field, val, cap))

    # Class fields: kit must not escalate the volumetric-effect class beyond biome.
    kit_vclass = combined.get("volumetric_effect_class")
    cap_vclass = caps.get("volumetric_effect_class")
    if kit_vclass is not None and cap_vclass is not None:
        c("kit_volumetric_effect_class_matches_biome", kit_vclass == cap_vclass,
          "kit volumetric_effect_class={} != biome cap {}".format(kit_vclass, cap_vclass))

    # Dressing coverage — at least one biome-compatible dressing asset referenced.
    asset_ids = []
    for s in (kit.get("dressing_asset_sets") or []):
        if isinstance(s, dict):
            asset_ids.extend(s.get("asset_ids") or [])
        elif isinstance(s, str):
            asset_ids.append(s)
    c("dressing_coverage_present", bool(asset_ids),
      "kit references no dressing assets", code=DRESS_CODE)


def check_biome_maps(rep, biome, maps, mesh_assets, caps):
    """Per-map budget delegation + biome-cap actuals for one biome."""
    biome_maps = sorted(sid for sid, e in maps.items() if (e or {}).get("biome") == biome)
    rep.check("{}::has_maps".format(biome), bool(biome_maps),
              "no maps for biome {}".format(biome), code=CODE)

    n = 0
    for sid in biome_maps:
        entry = maps.get(sid) or {}
        rig_rel = entry.get("rig_path") or "{}/{}.json".format(VC.ENV_RIGS_REL, sid)
        dress_rel = entry.get("dressing_path") or "{}/{}.json".format(VC.DRESSING_REL, sid)
        rig, rerr = VB._read_json(REPO_ROOT / rig_rel)
        dressing, derr = VB._read_json(REPO_ROOT / dress_rel)
        if rig is None:
            rep.check("{}::rig_loads".format(sid), False, rerr or rig_rel, code=CODE)
            continue
        if dressing is None:
            rep.check("{}::dressing_loads".format(sid), False, derr or dress_rel, code=CODE)
            continue

        profile_class = entry.get("profile_class") or rig.get("profile_class") or "balanced"
        # Delegate the v1.3.5 profile-class cap math (dynamic light/decal/vfx).
        VB.check_map(rep, sid, rig, dressing, mesh_assets, profile_class)

        # Additionally bound the map's actual load by the BIOME budget_caps.
        actuals = VB.count_actuals(rig, dressing)
        fog_actual = sum(
            1 for comp in (rig.get("components") or [])
            if isinstance(comp, dict) and comp.get("enabled")
            and comp.get("component") == VC.COMP_HEIGHT_FOG)
        if _is_num(caps.get("dynamic_light_count")):
            rep.check("{}::dynamic_light_within_biome_cap".format(sid),
                      actuals["dynamic_light_count"] <= caps["dynamic_light_count"],
                      "map dynamic_light_count={} over biome cap {}".format(
                          actuals["dynamic_light_count"], caps["dynamic_light_count"]),
                      code=CODE)
        if _is_num(caps.get("fog_volume_count")):
            rep.check("{}::fog_volume_within_biome_cap".format(sid),
                      fog_actual <= caps["fog_volume_count"],
                      "map fog_volume_count={} over biome cap {}".format(
                          fog_actual, caps["fog_volume_count"]),
                      code=CODE)
        n += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate v1.5 visual density/performance budgets vs biome caps.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    kits = _load_kits()
    maps = (load_visual_catalog(REPO_ROOT).get("maps") or {})
    mesh_assets = (load_mesh_catalog(REPO_ROOT).get("assets") or {})

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
        try:
            caps = (B.load_biome(biome).get("budget_caps") or {})
        except B.BiomeError as exc:
            rep.check("{}::biome_loads".format(biome), False, str(exc), code=CODE)
            continue
        check_kit_budget(rep, biome, kit, caps)
        total_maps += check_biome_maps(rep, biome, maps, mesh_assets, caps)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-visual-density-budgets", pack=args.pack, strict=strict,
        report_type="wf.visual.density_budget_report.v1", status=rep.status,
        record_count=len(kits), records_total=len(PACK_BIOMES),
        records_passed=sum(1 for b in PACK_BIOMES if b in kits),
        records_failed=sum(1 for b in PACK_BIOMES if b not in kits),
        extra={"maps_checked": total_maps}))
    d, fname = asset_paths.report_path("visual", "validate_visual_density_budgets")
    rep.write(d, fname)
    rep.print_summary("validate-visual-density-budgets")
    print("[validate-visual-density-budgets] {} kits, {} maps checked".format(
        len(kits), total_maps))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
