#!/usr/bin/env python3
"""create_mesh_assets.py — WorldForge v1.2 MeshForge Intake generator (Agent 2 lane).

Source-agnostic intake entrypoint. Deterministically synthesizes the v1.2 mesh
asset matrix — 6 families x 4 variants = 24 generated mesh assets across 3 source
types (internal_recipe, ue_generated, imported_generated_stub) — writing for each:

  * a definition YAML   procedural/definitions/mesh_assets/<asset_id>.yaml
  * a descriptor JSON   procedural/generated/mesh_assets/<asset_id>/descriptor.json
  * a source manifest   (embedded in the descriptor's source_metadata block)
  * a catalog record    procedural/generated/worldforge_mesh_catalog.json

Everything is derived deterministically from the (family, variant, source_type)
tuple via stable hashing, so re-running with the same inputs yields identical
source hashes (brief §8.1 determinism). No live editor is required: this is the
INTAKE contract. ue_generated assets additionally reference a materialization
report that the editor pass produces later (skip-when-absent, exactly like the
v0.8 generated-asset validator).

Usage:
    python tools/pipeline/create_mesh_assets.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/create_mesh_assets.py --pack biome_expansion_world --strict

Writes report: procedural/reports/mesh/create_mesh_assets/create_mesh_assets_report.json
Exit 0 = ok, 1 = fail.
"""

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC
from mesh_catalog import (
    compute_catalog_input_hash, load_mesh_catalog, save_mesh_catalog,
    upsert_catalog_entry,
)
from provenance import build_provenance
from report_meta import build_meta, hash_obj, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

GENERATOR_NAME = "create_mesh_assets"
GENERATOR_VERSION = "1.2.0"

# How many variants per family to materialize (>=4 required by the brief). We
# materialize all 6 canonical variants per family = 36 assets, which the brief
# explicitly welcomes (§4 "intentionally exceeds the older minimum") and which
# guarantees every v1.1 biome family — including alien_crystal_badlands and
# wetland_mire — has generated-mesh coverage for future MissionForge consumption.
VARIANTS_PER_FAMILY = 6

# Canonical variant -> biome family. Covers all 36 variants so bumping
# VARIANTS_PER_FAMILY stays correct. Industrial + generic covers are multi-biome.
BIOME_BY_VARIANT = {
    # rock_outcrop
    "desert_eroded_rock": ["desert"],
    "forest_mossy_boulder": ["temperate_forest"],
    "alpine_granite_outcrop": ["alpine_snow"],
    "volcanic_basalt_spire": ["volcanic_ashlands"],
    "wetland_slick_stone": ["wetland_mire"],
    "alien_crystal_rock": ["alien_crystal_badlands"],
    # industrial_debris — compatible with industrial-flavoured biomes (brief §7.2)
    "broken_pipe_cluster": ["desert", "volcanic_ashlands"],
    "rusted_panel_stack": ["desert", "volcanic_ashlands"],
    "collapsed_support_beam": ["desert", "volcanic_ashlands"],
    "scrap_barrier": ["desert", "volcanic_ashlands"],
    "forge_debris_chunk": ["volcanic_ashlands"],
    "industrial_cable_spool": ["desert", "volcanic_ashlands"],
    # traversal_marker
    "trail_post": ["temperate_forest", "desert"],
    "hazard_marker": ["desert", "volcanic_ashlands"],
    "route_stone": ["desert", "temperate_forest"],
    "snow_flag": ["alpine_snow"],
    "marsh_stake": ["wetland_mire"],
    "alien_waypoint_crystal": ["alien_crystal_badlands"],
    # biome_landmark
    "desert_arch": ["desert"],
    "forest_dead_tree_cluster": ["temperate_forest"],
    "alpine_ice_monolith": ["alpine_snow"],
    "volcanic_basaltshell": ["volcanic_ashlands"],
    "wetland_root_tower": ["wetland_mire"],
    "alien_crystal_obelisk": ["alien_crystal_badlands"],
    # resource_node
    "ore_cluster": ["desert", "volcanic_ashlands"],
    "scrap_cache": ["desert", "volcanic_ashlands"],
    "herb_patch_proxy": ["temperate_forest", "wetland_mire"],
    "ice_crystal_node": ["alpine_snow"],
    "sulfur_deposit": ["volcanic_ashlands"],
    "alien_resonance_cluster": ["alien_crystal_badlands"],
    # encounter_cover
    "low_rock_cover": ["desert", "volcanic_ashlands"],
    "scrap_cover_wall": ["desert", "volcanic_ashlands"],
    "snow_drift_cover": ["alpine_snow"],
    "fallen_tree_cover": ["temperate_forest", "wetland_mire"],
    "basalt_cover_ridge": ["volcanic_ashlands"],
    "crystal_cover_cluster": ["alien_crystal_badlands"],
}

# Material family per biome (brief §12 — material must be biome-compatible).
MATERIAL_FAMILY_BY_BIOME = {
    "desert": "rock_desert",
    "temperate_forest": "rock_forest",
    "alpine_snow": "rock_alpine",
    "volcanic_ashlands": "rock_volcanic",
    "wetland_mire": "rock_wetland",
    "alien_crystal_badlands": "crystal_alien",
}

# POI classes each family is eligible for (brief §11 mesh_asset x POI class).
POI_CLASSES_BY_FAMILY = {
    "rock_outcrop": ["landmark", "dressing"],
    "industrial_debris": ["outpost", "industrial", "ruin"],
    "traversal_marker": ["route", "boundary", "navigation"],
    "biome_landmark": ["landmark", "vista", "orientation"],
    "resource_node": ["resource", "harvest"],
    "encounter_cover": ["encounter", "cover"],
}

# Budget class per family (brief §14). Landmarks are heaviest.
BUDGET_BY_FAMILY = {
    "rock_outcrop": "balanced",
    "industrial_debris": "performance_safe",
    "traversal_marker": "performance_safe",
    "biome_landmark": "cinematic",
    "resource_node": "balanced",
    "encounter_cover": "performance_safe",
}

# PCG eligibility per family (brief §10). Landmarks are conditional (large
# silhouettes must not occlude critical routes); markers are conditional
# (route-graph aware); the rest are allowed.
PCG_BY_FAMILY = {
    "rock_outcrop": MC.PCG_ALLOWED,
    "industrial_debris": MC.PCG_ALLOWED,
    "traversal_marker": MC.PCG_CONDITIONAL,
    "biome_landmark": MC.PCG_CONDITIONAL,
    "resource_node": MC.PCG_CONDITIONAL,
    "encounter_cover": MC.PCG_ALLOWED,
}

COLLISION_BY_FAMILY = {
    "rock_outcrop": "BlockAll",
    "industrial_debris": "BlockAllDynamic",
    "traversal_marker": "OverlapAll",
    "biome_landmark": "BlockAll",
    "resource_node": "OverlapAll",
    "encounter_cover": "BlockAll",
}

# Deterministic bounds (cm) per family, safely inside FAMILY_BOUNDS_LIMITS_CM.
BOUNDS_BY_FAMILY = {
    "rock_outcrop": (320.0, 280.0, 240.0),
    "industrial_debris": (260.0, 180.0, 150.0),
    "traversal_marker": (60.0, 60.0, 220.0),
    "biome_landmark": (1600.0, 1400.0, 3200.0),
    "resource_node": (240.0, 240.0, 180.0),
    "encounter_cover": (360.0, 200.0, 180.0),
}


def _short_family(family):
    return {
        "rock_outcrop": "rock", "industrial_debris": "ind", "traversal_marker": "trav",
        "biome_landmark": "lmk", "resource_node": "res", "encounter_cover": "cov",
    }[family]


def _pascal(name):
    return "".join(part.capitalize() for part in name.split("_"))


def _source_hash(family, variant, source_type, params):
    payload = json.dumps(
        {"family": family, "variant": variant, "source_type": source_type, "params": params},
        sort_keys=True, ensure_ascii=False,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_metadata(source_type, family, variant, source_hash):
    """Per-source-type provenance/manifest block (brief §8)."""
    recipe_id = "recipe_{}_{}".format(family, variant)
    if source_type == "internal_recipe":
        return {
            "source_type": source_type,
            "recipe_id": recipe_id,
            "recipe_version": "1.2.0",
            "recipe_hash": source_hash,
            "parameters": {"family": family, "variant": variant, "seed": 12},
            "determinism_key": "{}:{}".format(family, variant),
        }
    if source_type == "ue_generated":
        return {
            "source_type": source_type,
            "ue_script": "tools/unreal/materialize_mesh_asset.py",
            "ue_script_version": "1.2.0",
            "input_spec": recipe_id,
            "editor_version": None,
            "source_hash": source_hash,
            # Editor pass writes this; validators skip-when-absent (v0.8 convention).
            "materialization_report": "procedural/reports/mesh_assets/{}/ue_materialize_report.json".format(recipe_id),
        }
    # imported_generated_stub — controlled source-agnostic intake (brief §8.3).
    return {
        "source_type": source_type,
        "source_manifest": "procedural/generated/mesh_assets/{}__{}/import_manifest.json".format(family, variant),
        "declared_source_tool": "external_generator_stub",
        "declared_source_version": "0.1.0",
        "input_artifact_hash": source_hash,
        "import_report": "quarantine_import_ok",
        # Imported assets flow through quarantine BEFORE the final path (brief §8.3).
        "quarantine_path": "/Game/HoudiniEngine/Temp/Imported/{}_{}".format(family, variant),
        "final_asset_path": None,  # filled in by caller
    }


def build_asset(family, variant, source_type):
    """Return a fully-populated mesh-asset definition dict for one asset."""
    biomes = BIOME_BY_VARIANT[variant]
    asset_id = "mesh_{}_{}".format(_short_family(family), variant)
    final_path = "/Game/WorldForge/Generated/Meshes/{}/SM_{}".format(
        _pascal(family), _pascal(variant))
    params = {"family": family, "variant": variant, "seed": 12}
    source_hash = _source_hash(family, variant, source_type, params)
    bx, by, bz = BOUNDS_BY_FAMILY[family]
    budget = BUDGET_BY_FAMILY[family]

    # Material bindings — one slot per asset, biome-compatible material family.
    primary_biome = biomes[0]
    mat_family = MATERIAL_FAMILY_BY_BIOME[primary_biome]
    material_bindings = [{
        "slot_name": "MI_Body",
        "material_asset_path": "/Game/WorldForge/Generated/Materials/{}/MI_{}_{}".format(
            _pascal(family), _pascal(variant), _pascal(mat_family)),
        "material_family": mat_family,
        "biome_compatibility": biomes,
        "rendering_budget_class": budget,
        "fallback_allowed": False,
    }]

    # Family-specific geometry metadata (brief §13).
    geometry = {}
    if family == "traversal_marker":
        geometry["route_blocking"] = False
    elif family == "encounter_cover":
        geometry["cover_height_class"] = "half"
    elif family == "biome_landmark":
        geometry["landmark_budget"] = "cinematic_silhouette"
    elif family == "resource_node":
        geometry["interaction_clearance_cm"] = 120.0
    elif family == "industrial_debris":
        geometry["blocking_collision_declared"] = True

    pcg_elig = PCG_BY_FAMILY[family]
    definition = {
        "schema_version": MC.MESH_SCHEMA_VERSION,
        "asset_id": asset_id,
        "display_name": "{} — {}".format(_pascal(family), _pascal(variant)),
        "mesh_family": family,
        "source_type": source_type,
        "source_recipe": "recipe_{}_{}".format(family, variant),
        "source_hash": source_hash,
        "source_tool_version": "1.2.0",
        "final_asset_path": final_path,
        "intermediate_paths": [],
        "quarantine_paths": [],
        "generated_owned": True,
        "human_owned": False,
        "material_bindings": material_bindings,
        "collision_profile": COLLISION_BY_FAMILY[family],
        "bounds": {"x_cm": bx, "y_cm": by, "z_cm": bz},
        "pivot_policy": "base_center",
        "scale_policy": "uniform",
        "budget_class": budget,
        "pcg_eligibility": pcg_elig,
        "biome_compatibility": biomes,
        "poi_compatibility": POI_CLASSES_BY_FAMILY[family],
        "placement_compatibility": {
            "allowed_placement_profiles": ["scatter_default", "scatter_sparse"],
        },
        "nanite_policy": "nanite_enabled" if budget != "performance_safe" else "nanite_disabled",
        "lod_policy": "lod_auto",
        "shadow_policy": "shadow_default",
        "raytracing_policy": "raytracing_forced" if budget == "raytraced_high" else "raytracing_default",
        "rendering_budget": {
            "triangle_class": "high" if family == "biome_landmark" else "medium",
            "material_complexity_class": "medium",
            "texture_class": "medium",
            "collision_complexity_class": "simple",
            "nanite_policy": "nanite_enabled" if budget != "performance_safe" else "nanite_disabled",
            "lod_policy": "lod_auto",
            "shadow_policy": "shadow_default",
            "raytracing_policy": "raytracing_forced" if budget == "raytraced_high" else "raytracing_default",
            "pcg_density_class": "sparse" if pcg_elig != MC.PCG_ALLOWED else "medium",
            "package_size_class": "large" if family == "biome_landmark" else "medium",
        },
        "geometry": geometry,
        "package_rules": {"include_material_dependencies": True},
        "repair_policy": "regenerate_from_recipe",
        "destroy_policy": "generated_owned_only",
    }

    # PCG placement rules for allowed/conditional assets (brief §10).
    if pcg_elig in (MC.PCG_ALLOWED, MC.PCG_CONDITIONAL):
        definition["placement_compatibility"]["pcg_rules"] = {
            "allowed_biomes": biomes,
            "allowed_poi_classes": POI_CLASSES_BY_FAMILY[family],
            "allowed_placement_profiles": ["scatter_default", "scatter_sparse"],
            "slope_limits": {"min_deg": 0, "max_deg": 35 if family != "biome_landmark" else 12},
            "height_limits": {"min_cm": -50000, "max_cm": 50000},
            "density_class": "sparse" if pcg_elig == MC.PCG_CONDITIONAL else "medium",
            "collision_policy": COLLISION_BY_FAMILY[family],
            "avoid_critical_routes": True,
            "avoid_player_start": True,
        }
        if pcg_elig == MC.PCG_CONDITIONAL:
            definition["placement_compatibility"]["pcg_rules"]["conditions"] = [
                "requires_route_graph_clearance",
            ]

    source_meta = _source_metadata(source_type, family, variant, source_hash)
    if source_type == "imported_generated_stub":
        source_meta["final_asset_path"] = final_path
        definition["quarantine_paths"] = [source_meta["quarantine_path"]]
        definition["intermediate_paths"] = [source_meta["quarantine_path"]]
    definition["source_metadata"] = source_meta
    return definition


def enumerate_matrix():
    """Yield (family, variant, source_type) for the full 24-asset matrix."""
    idx = 0
    for family in MC.MESH_FAMILIES:
        for variant in MC.FAMILY_VARIANTS[family][:VARIANTS_PER_FAMILY]:
            source_type = MC.SOURCE_TYPES_REQUIRED[idx % len(MC.SOURCE_TYPES_REQUIRED)]
            idx += 1
            yield family, variant, source_type


def write_asset(definition, repo_root):
    """Write definition YAML + descriptor JSON + catalog entry for one asset."""
    asset_id = definition["asset_id"]
    def_path = MC.mesh_definition_path(asset_id, repo_root)
    def_path.parent.mkdir(parents=True, exist_ok=True)
    with def_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(definition, fh, sort_keys=False, allow_unicode=True)

    out_dir = Path(repo_root) / MC.MESH_GENERATED_REL / asset_id
    out_dir.mkdir(parents=True, exist_ok=True)
    prov = build_provenance(Path(repo_root), [def_path], GENERATOR_NAME, GENERATOR_VERSION)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    provenance_id = "prov_{}".format(asset_id)

    descriptor = dict(definition)
    descriptor["definition_path"] = def_path.relative_to(repo_root).as_posix()
    descriptor["descriptor_path"] = (out_dir / "descriptor.json").relative_to(repo_root).as_posix()
    descriptor["generated_at_utc"] = now_iso
    descriptor["provenance"] = prov
    descriptor["provenance_id"] = provenance_id
    descriptor["registry_id"] = "mesh_catalog:{}".format(asset_id)
    descriptor["registry_owner"] = "worldforge_mesh_catalog"

    desc_path = out_dir / "descriptor.json"
    with desc_path.open("w", encoding="utf-8") as fh:
        json.dump(descriptor, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    # imported_generated_stub: write the source manifest into the quarantine record.
    manifest_path = out_dir / "import_manifest.json"
    if definition["source_type"] != "imported_generated_stub":
        # Not a stub: remove any stale manifest left by a prior regeneration where
        # this asset_id was assigned a different (stub) source type.
        if manifest_path.is_file():
            manifest_path.unlink()
    if definition["source_type"] == "imported_generated_stub":
        with manifest_path.open("w", encoding="utf-8") as fh:
            json.dump({
                "asset_id": asset_id,
                "declared_source_tool": descriptor["source_metadata"]["declared_source_tool"],
                "declared_source_version": descriptor["source_metadata"]["declared_source_version"],
                "input_artifact_hash": descriptor["source_hash"],
                "quarantine_path": descriptor["source_metadata"]["quarantine_path"],
                "final_asset_path": descriptor["final_asset_path"],
            }, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    entry = {
        "asset_id": asset_id,
        "mesh_family": definition["mesh_family"],
        "source_type": definition["source_type"],
        "final_asset_path": definition["final_asset_path"],
        "registry_id": descriptor["registry_id"],
        "provenance_id": provenance_id,
        "biome_compatibility": definition["biome_compatibility"],
        "poi_compatibility": definition["poi_compatibility"],
        "pcg_eligibility": definition["pcg_eligibility"],
        "placement_tags": definition["placement_compatibility"].get("allowed_placement_profiles", []),
        "material_bindings": definition["material_bindings"],
        "collision_profile": definition["collision_profile"],
        "bounds": definition["bounds"],
        "budget_class": definition["budget_class"],
        "package_status": "pending",
        "validation_status": "pending",
        "lifecycle_status": "created",
        "descriptor_path": descriptor["descriptor_path"],
        "source_hash": definition["source_hash"],
    }
    entry["input_hash"] = compute_catalog_input_hash(entry)
    return entry


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.2 MeshForge Intake generator.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    assets_written = []
    families_seen = set()
    sources_seen = set()

    for family, variant, source_type in enumerate_matrix():
        definition = build_asset(family, variant, source_type)
        entry = write_asset(definition, REPO_ROOT)
        catalog = upsert_catalog_entry(catalog, entry)
        assets_written.append(entry["asset_id"])
        families_seen.add(family)
        sources_seen.add(source_type)

    save_mesh_catalog(REPO_ROOT, catalog)

    rep.check("asset_count_at_least_24", len(assets_written) >= 24,
              "created {} assets".format(len(assets_written)),
              code=FailureCode.MESH_CONTRACT_FAILURE)
    rep.check("families_at_least_6", len(families_seen) >= 6,
              "families: {}".format(sorted(families_seen)),
              code=FailureCode.MESH_CONTRACT_FAILURE)
    rep.check("source_types_at_least_3", len(sources_seen) >= 3,
              "source types: {}".format(sorted(sources_seen)),
              code=FailureCode.MESH_SOURCE_FAILURE)
    rep.check("catalog_written", MC.mesh_definition_path(assets_written[0]).is_file(),
              "definitions written", code=FailureCode.MESH_CATALOG_FAILURE)

    rep.finalize()
    meta = build_meta(command="create-mesh-assets", pack=args.pack, strict=strict,
                      status=rep.status, record_count=len(assets_written),
                      output_manifest_hash=hash_obj(sorted(assets_written)),
                      extra={"families": sorted(families_seen),
                             "source_types": sorted(sources_seen),
                             "asset_ids": assets_written})
    rep.set_meta(meta)
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "create_mesh_assets"
    rep.write(report_dir, "create_mesh_assets_report.json")
    rep.print_summary("create-mesh-assets")
    print("[create-mesh-assets] {} assets, {} families, {} source types".format(
        len(assets_written), len(families_seen), len(sources_seen)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
