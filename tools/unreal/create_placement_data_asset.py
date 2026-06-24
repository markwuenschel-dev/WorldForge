#!/usr/bin/env python3
r"""
create_placement_data_asset.py (UE5 Python)

Creates/updates the UPlacementRulesDataAsset for one FoliageSpawnRules definition
(PlacementForge, forge_design_decisions D13). Mirrors create_data_asset.py: it
reads the manifest, writes the runtime rules + provenance into the Data Asset, and
saves. The human-owned PCG graph reads Species[] from this asset and pulls live
world state per cell to modulate density.

Pure stdlib + unreal (NO pyyaml). The manifest owns the output path
(ue.data_asset_path); state values are NEVER baked here (only the response curve).
"""

import argparse
import json
from pathlib import Path

import unreal

DATA_ASSET_CLASS = unreal.PlacementRulesDataAsset

SCOPE_MAP = {
    "Global": unreal.WorldForgeStateScope.GLOBAL,
    "Region": unreal.WorldForgeStateScope.REGION,
    "Local": unreal.WorldForgeStateScope.LOCAL,
    "Settlement": unreal.WorldForgeStateScope.SETTLEMENT,
}


def _build_species_rule(entry: dict) -> unreal.PlacementSpeciesRule:
    rule = unreal.PlacementSpeciesRule()
    rule.set_editor_property("species_id", entry["id"])
    # Mesh is an FSoftObjectPath (see PlacementRulesDataAsset.h): set it from a
    # SoftObjectPath so the ref is stored even when the mesh doesn't exist in this
    # tooling-only project. (TSoftObjectPtr would reject this; FSoftObjectPath accepts it.)
    rule.set_editor_property("mesh", unreal.SoftObjectPath(entry["mesh"]))
    rule.set_editor_property("base_density", float(entry["base_density"]))
    rule.set_editor_property("scale_min", float(entry["scale_min"]))
    rule.set_editor_property("scale_max", float(entry["scale_max"]))
    rule.set_editor_property("state_scope", SCOPE_MAP.get(entry.get("state_scope", "Region"),
                                                          unreal.WorldForgeStateScope.REGION))
    state_key = entry.get("state_key", "none")
    rule.set_editor_property("state_key", unreal.Name("None") if state_key == "none" else unreal.Name(state_key))
    rule.set_editor_property("density_at_state_zero", float(entry.get("density_at_state_zero", 1.0)))
    rule.set_editor_property("density_at_state_one", float(entry.get("density_at_state_one", 1.0)))
    return rule


def create_or_update(manifest: dict):
    ue = manifest["ue"]
    if not ue.get("generate_data_asset", False):
        return {"status": "skipped", "reason": "generate_data_asset=false"}

    data_asset_path = ue.get("data_asset_path")
    if not data_asset_path:
        raise RuntimeError("missing_data_asset_path: manifest ue.data_asset_path is required")

    # Create or load the Data Asset.
    package_path, asset_name = data_asset_path.rsplit("/", 1)
    asset = unreal.EditorAssetLibrary.load_asset(data_asset_path)
    if not asset:
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        # Prefer a None factory to avoid the DataAssetFactory class-picker dialog
        # (which would block a headless commandlet); fall back if needed.
        try:
            asset = asset_tools.create_asset(asset_name, package_path, DATA_ASSET_CLASS, None)
        except Exception:
            asset = asset_tools.create_asset(asset_name, package_path, DATA_ASSET_CLASS,
                                             unreal.DataAssetFactory())
        if not asset:
            raise RuntimeError(f"data_asset_create_failed: {data_asset_path}")

    prov = manifest.get("provenance", {})

    # Identity.
    asset.set_editor_property("rules_id", manifest["definition_id"])
    asset.set_editor_property("schema_version", str(manifest.get("schema_version", "")))
    asset.set_editor_property("biome", unreal.Name(manifest.get("biome", "") or "None"))

    # Runtime rules (read by the PCG graph). State is pulled live; never baked.
    asset.set_editor_property("pcg_graph_template", unreal.SoftObjectPath(manifest.get("pcg_graph", "")))
    species = [_build_species_rule(e) for e in manifest.get("species", [])]
    asset.set_editor_property("species", species)

    # Provenance, copied verbatim from the manifest.
    asset.set_editor_property("source_recipe_path", manifest.get("source_definition", ""))
    asset.set_editor_property("manifest_path",
                              f"procedural/manifests/placement/{manifest['definition_id']}.json")
    asset.set_editor_property("generator_name", prov.get("generator_name", ""))
    asset.set_editor_property("generator_version", prov.get("generator_version", ""))
    asset.set_editor_property("generated_at_utc", prov.get("generated_at_utc", ""))
    asset.set_editor_property("source_commit", prov.get("source_commit", ""))
    asset.set_editor_property("source_tree_dirty", bool(prov.get("source_tree_dirty", False)))

    source_definition = manifest.get("source_definition", "")
    recipe_hash = prov.get("inputs", {}).get(source_definition, "")
    asset.set_editor_property("source_recipe_hash", recipe_hash)

    unreal.EditorAssetLibrary.save_loaded_asset(asset)

    return {
        "status": "ok",
        "data_asset_path": data_asset_path,
        "species_count": len(species),
        "source_commit": prov.get("source_commit", ""),
        "source_tree_dirty": bool(prov.get("source_tree_dirty", False)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    result = create_or_update(manifest)

    report_dir = root / "procedural/reports/placement" / manifest["definition_id"]
    report_dir.mkdir(parents=True, exist_ok=True)
    with open(report_dir / "data_asset_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
