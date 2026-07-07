#!/usr/bin/env python3
"""create_visual_environment_kits.py — WorldForge v1.5 VisualEnvironmentForge (Wave-3).

Compose ONE VisualEnvironmentKit per pack biome from the EXISTING v1.3.5 profile
system. This does NOT invent new sky/fog/lighting/atmosphere/post-process
profiles — it COMPOSES the ones a biome already binds:

  * The biome's primary bound environment_profile composite (first entry of the
    biome_family ``environment_profiles`` allow-list) is resolved via profiles.py,
    and its constituent sky/fog/lighting/atmosphere/post_process CHILD profile
    NAMES become the kit's profile references — every one a real yaml under
    procedural/definitions/profiles/.
  * terrain_material_profile / decal_profile are taken from the biome's declared
    material_families / placement_profiles allow-lists (real declared names).
  * dressing_asset_sets reference real generated-owned mesh-catalog asset ids that
    declare biome_compatibility for this biome.
  * density_budget / performance_budget are derived FROM the biome's budget_caps,
    so a kit can never declare fidelity above what the biome permits.
  * hazard / safe-zone / danger-zone visual_language are DISTINCT marker specs and
    route_readability_rules pin the readability thresholds (from visual_contract).

Every kit passes visual_kit_contract.validate_record(strict=True). Written to
asset_paths.VISUAL_KITS_DIR/<visual_kit_id>.json. Fail-closed: if any of the 5
pack biomes lacks a kit, that is VISUAL_KIT_MISSING_BIOME.

Determinism: no datetime.now()/random — provenance stamps derive from git sha and
content only. Report: wf.visual.environment_kit_report.v1.

Usage:
    python tools/pipeline/create_visual_environment_kits.py --pack encounter_loop_world [--strict]
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import asset_paths
import biomes as B
import profiles as P
import visual_contract as VC
import visual_kit_contract as KC
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, git_sha, hash_obj, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

# The 5 pack biomes VisualEnvironmentForge composes kits for (desert_borderlands
# is validated by the pre-existing desert lane, not part of the biome pack).
PACK_BIOMES = (
    "temperate_forest",
    "alpine_snow",
    "volcanic_ashlands",
    "wetland_mire",
    "alien_crystal_badlands",
)

# How many biome-compatible dressing assets to reference per kit (a real subset).
MAX_DRESSING_ASSETS = 8


def _biome_dressing_asset_ids(mesh_assets, biome):
    """Return sorted generated-owned mesh-catalog asset ids compatible with biome."""
    out = []
    for aid in sorted(mesh_assets):
        rec = mesh_assets.get(aid) or {}
        compat = rec.get("biome_compatibility") or []
        if isinstance(compat, str):
            compat = [compat]
        if biome in compat:
            out.append(aid)
    return out


def _zone_visual_language():
    """Distinct per-zone visual marker specs. hazard != safe != danger — different
    marker_type AND color so a player reads each zone class differently."""
    hazard = {
        "marker_type": "pulsing_emissive_decal",
        "color_rgb": [1.0, 0.15, 0.05],
        "pulse_hz": 1.5,
        "priority": "high",
        "readable_at_distance_cm": 4000,
    }
    safe = {
        "marker_type": "steady_cool_ambient",
        "color_rgb": [0.35, 0.65, 1.0],
        "pulse_hz": 0.0,
        "priority": "ambient",
        "readable_at_distance_cm": 6000,
    }
    danger = {
        "marker_type": "warm_haze_vignette",
        "color_rgb": [1.0, 0.55, 0.10],
        "pulse_hz": 0.5,
        "priority": "elevated",
        "readable_at_distance_cm": 5000,
    }
    return hazard, safe, danger


def _route_readability_rules():
    """Pin the readability thresholds the kit is authored against (from
    visual_contract), so the readability validator can prove the kit's maps honour
    them rather than re-deriving numbers."""
    return {
        "min_fog_visibility_fraction_of_route": VC.MIN_FOG_VISIBILITY_FRACTION_OF_ROUTE,
        "exposure_ev_min": VC.EXPOSURE_EV_MIN,
        "exposure_ev_max": VC.EXPOSURE_EV_MAX,
        "dressing_clearance_min_cm": 200.0,
        "min_route_contrast": 0.30,
        "objective_must_be_visible": True,
    }


def _density_budget_from_caps(caps):
    """Density budget derived FROM the biome budget_caps (never above them)."""
    return {
        "vegetation_density": caps.get("vegetation_density"),
        "dynamic_light_count": caps.get("dynamic_light_count"),
        "fog_volume_count": caps.get("fog_volume_count"),
        "emissive_material_count": caps.get("emissive_material_count"),
        "volumetric_effect_class": caps.get("volumetric_effect_class"),
        "poi_count": caps.get("poi_count"),
        "entity_anchor_count": caps.get("entity_anchor_count"),
    }


def _performance_budget_from_caps(caps):
    return {
        "dynamic_light_count": caps.get("dynamic_light_count"),
        "fog_volume_count": caps.get("fog_volume_count"),
        "emissive_material_count": caps.get("emissive_material_count"),
        "material_complexity": caps.get("material_complexity"),
        "volumetric_effect_class": caps.get("volumetric_effect_class"),
        "package_footprint_class": caps.get("package_footprint_class"),
    }


def compose_kit(biome_id, pack, mesh_assets):
    """Compose one VisualEnvironmentKit for a biome. Returns (kit, error)."""
    try:
        biome = B.load_biome(biome_id)
    except B.BiomeError as exc:
        return None, "biome family unloadable: {}".format(exc)

    env_profiles = biome.get("environment_profiles") or []
    if not env_profiles:
        return None, "biome {} declares no environment_profiles".format(biome_id)
    env_name = env_profiles[0]  # the biome's primary bound environment composite

    try:
        resolved = P.resolve_environment(env_name)
    except P.ProfileError as exc:
        return None, "environment composite {!r} does not resolve: {}".format(env_name, exc)
    env = resolved["environment"]

    materials = biome.get("material_families") or []
    placements = biome.get("placement_profiles") or []
    if not materials or not placements:
        return None, "biome {} missing material/placement allow-lists".format(biome_id)

    caps = biome.get("budget_caps") or {}
    dressing_ids = _biome_dressing_asset_ids(mesh_assets, biome_id)
    dressing_sets = [{
        "set_id": "{}_dressing".format(biome_id),
        "ownership_class": VC.OWNERSHIP_GENERATED,
        "asset_ids": dressing_ids[:MAX_DRESSING_ASSETS],
    }]

    hazard, safe, danger = _zone_visual_language()

    kit = {
        "schema_version": KC.SCHEMA_VERSION,
        "visual_kit_id": "vk_{}_standard".format(biome_id),
        "display_name": "{} — standard visual kit".format(biome.get("display_name", biome_id)),
        "biome": biome_id,
        "environment_mode": env.get("class") or "balanced",
        # Composed profile references — every one a real existing profile name.
        "sky_profile": env.get("sky"),
        "fog_profile": env.get("fog"),
        "lighting_profile": env.get("lighting"),
        "atmosphere_profile": env.get("atmosphere"),
        "postprocess_profile": env.get("post_process"),
        "terrain_material_profile": materials[0],
        "decal_profile": placements[0],
        "dressing_asset_sets": dressing_sets,
        "hazard_visual_language": hazard,
        "safe_zone_visual_language": safe,
        "danger_zone_visual_language": danger,
        "route_readability_rules": _route_readability_rules(),
        "density_budget": _density_budget_from_caps(caps),
        "performance_budget": _performance_budget_from_caps(caps),
        "screenshot_requirements": [
            "biome_overview", "mission_route", "hazard_zone",
            "safe_zone", "poi_objective",
        ],
        "validation_requirements": [
            "route_readability", "density_budget",
            "zone_visual_language_distinct", "inspection_screenshot_report",
        ],
        "provenance": {
            "generator": "create_visual_environment_kits",
            "generator_version": KC.SCHEMA_VERSION,
            "pack": pack,
            "git_sha": git_sha(),
            "environment_profile": env_name,
            "profile_class": env.get("class"),
            "composed_from": {
                "sky": env.get("sky"), "fog": env.get("fog"),
                "lighting": env.get("lighting"), "atmosphere": env.get("atmosphere"),
                "post_process": env.get("post_process"),
                "weather": env.get("weather"),
            },
        },
        "notes": ("Composed from existing v1.3.5 profile system. Screenshots are "
                  "EVIDENCE captured by the tools/unreal driver; per TICKET-001 they "
                  "must come from PIE/-game, not headless SceneCapture."),
    }
    # Content-derived provenance id (deterministic; no timestamps).
    kit["provenance_id"] = "vkprov:" + hash_obj(
        {k: v for k, v in kit.items() if k != "provenance"})[:16]
    return kit, None


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Compose one VisualEnvironmentKit per pack biome (v1.5).")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    mesh_assets = load_mesh_catalog(REPO_ROOT).get("assets") or {}
    kits_dir = asset_paths.ensure(asset_paths.VISUAL_KITS_DIR)

    written = {}
    for biome_id in PACK_BIOMES:
        kit, err = compose_kit(biome_id, args.pack, mesh_assets)
        if kit is None:
            rep.check("{}::composed".format(biome_id), False,
                      err, code=FailureCode.VISUAL_KIT_MISSING_BIOME)
            continue

        # Every kit MUST pass the strict schema contract before it is written.
        contract_ok = True
        for cname, ok, detail, code in KC.validate_record(kit, strict=True):
            rep.check("{}::{}".format(biome_id, cname), ok, detail, code=code)
            contract_ok = contract_ok and ok
        if not contract_ok:
            continue

        path = kits_dir / "{}.json".format(kit["visual_kit_id"])
        path.write_text(json.dumps(kit, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        written[biome_id] = kit["visual_kit_id"]
        rep.check("{}::written".format(biome_id), True, str(path))

    # Fail-closed: every one of the 5 pack biomes must have produced a kit.
    for biome_id in PACK_BIOMES:
        rep.check("biome_has_kit::{}".format(biome_id), biome_id in written,
                  "no visual kit composed for biome {}".format(biome_id),
                  code=FailureCode.VISUAL_KIT_MISSING_BIOME)
    rep.check("all_pack_biomes_covered", len(written) == len(PACK_BIOMES),
              "composed {}/{} biome kits: {}".format(
                  len(written), len(PACK_BIOMES), sorted(written.values())),
              code=FailureCode.VISUAL_KIT_MISSING_BIOME)

    rep.finalize()
    rep.set_meta(build_meta(
        command="create-visual-environment-kits", pack=args.pack, strict=strict,
        report_type="wf.visual.environment_kit_report.v1", status=rep.status,
        record_count=len(written), records_total=len(PACK_BIOMES),
        records_passed=len(written), records_failed=len(PACK_BIOMES) - len(written),
        extra={"kits": written, "kits_dir": str(kits_dir.relative_to(REPO_ROOT))}))
    d, fname = asset_paths.report_path("visual", "create_visual_environment_kits")
    rep.write(d, fname)
    rep.print_summary("create-visual-environment-kits")
    print("[create-visual-environment-kits] {}/{} biome kits -> {}".format(
        len(written), len(PACK_BIOMES), kits_dir))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
