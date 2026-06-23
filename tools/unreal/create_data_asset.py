#!/usr/bin/env python3
r"""
create_data_asset.py (UE5 Python)

Creates/updates the UMaterialRecipeDataAsset provenance + linkage record for one
recipe. Runs AFTER create-material in the pipeline. It reads the manifest, loads
the already-created Material Instance and textures, copies provenance verbatim
from the manifest, and saves the Data Asset.

It does NOT create or mutate the Material Instance or textures - provenance can be
regenerated/repaired without touching the produced assets (forge_design_decisions
D5). The manifest owns the output path (ue.data_asset_path).
"""

import argparse
import json
from pathlib import Path

import unreal

DATA_ASSET_CLASS = unreal.MaterialRecipeDataAsset


def create_or_update(manifest: dict):
    ue = manifest["ue"]
    if not ue.get("generate_data_asset", False):
        return {"status": "skipped", "reason": "generate_data_asset=false"}

    data_asset_path = ue.get("data_asset_path")
    if not data_asset_path:
        raise RuntimeError("missing_data_asset_path: manifest ue.data_asset_path is required")

    # Load the produced Material Instance (created by create_material_instances.py).
    mi = unreal.load_asset(ue["instance_path"])
    if not mi:
        raise RuntimeError(f"missing_material_instance: {ue['instance_path']}")

    # Load the produced textures, keyed by material parameter name.
    texture_outputs = {}
    for param_name, tex_path in manifest["material_parameters"]["textures"].items():
        tex = unreal.load_asset(tex_path)
        if not tex:
            raise RuntimeError(f"missing_texture_asset: {tex_path}")
        texture_outputs[param_name] = tex

    scalar_params = {k: float(v) for k, v in
                     manifest["material_parameters"].get("scalars", {}).items()}

    # Create or load the Data Asset.
    package_path, asset_name = data_asset_path.rsplit("/", 1)
    asset = unreal.EditorAssetLibrary.load_asset(data_asset_path)
    if not asset:
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        # Prefer a None factory: for a plain UDataAsset subclass this creates the
        # object directly and avoids the DataAssetFactory class-picker dialog (which
        # would block a headless commandlet). Fall back to the factory if needed.
        try:
            asset = asset_tools.create_asset(asset_name, package_path, DATA_ASSET_CLASS, None)
        except Exception:
            asset = asset_tools.create_asset(asset_name, package_path, DATA_ASSET_CLASS,
                                             unreal.DataAssetFactory())
        if not asset:
            raise RuntimeError(f"data_asset_create_failed: {data_asset_path}")

    prov = manifest.get("provenance", {})

    # Identity + provenance, copied verbatim from the manifest.
    asset.set_editor_property("recipe_id", manifest["recipe_id"])
    asset.set_editor_property("schema_version", str(manifest.get("schema_version", "")))
    asset.set_editor_property("source_recipe_path", manifest.get("source_recipe", ""))
    asset.set_editor_property("manifest_path",
                              f"procedural/manifests/materials/{manifest['recipe_id']}.json")
    asset.set_editor_property("generator_name", prov.get("generator_name", ""))
    asset.set_editor_property("generator_version", prov.get("generator_version", ""))
    asset.set_editor_property("generated_at_utc", prov.get("generated_at_utc", ""))
    asset.set_editor_property("source_commit", prov.get("source_commit", ""))
    asset.set_editor_property("source_tree_dirty", bool(prov.get("source_tree_dirty", False)))

    # Record the source recipe hash so validation can detect stale provenance.
    source_recipe = manifest.get("source_recipe", "")
    recipe_hash = prov.get("inputs", {}).get(source_recipe, "")
    asset.set_editor_property("source_recipe_hash", recipe_hash)

    # Linkage (hard refs).
    asset.set_editor_property("material_instance", mi)
    asset.set_editor_property("texture_outputs", texture_outputs)
    asset.set_editor_property("parameters", scalar_params)

    unreal.EditorAssetLibrary.save_loaded_asset(asset)

    return {
        "status": "ok",
        "data_asset_path": data_asset_path,
        "material_instance_path": ue["instance_path"],
        "texture_count": len(texture_outputs),
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

    report_dir = root / "procedural/reports/materials" / manifest["recipe_id"]
    report_dir.mkdir(parents=True, exist_ok=True)
    with open(report_dir / "data_asset_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
