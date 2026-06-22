#!/usr/bin/env python3
r"""
create_material_instances.py (UE5 Python)
Manifest-driven with --project-root and basic report output.
"""

import argparse
import json
from pathlib import Path
import unreal


def resolve_path(p: str, root: Path) -> str:
    pp = Path(p)
    return str(pp if pp.is_absolute() else (root / pp).resolve())


def create_or_update(manifest: dict, project_root: Path):
    ue = manifest["ue"]
    parent_path = ue["parent_material"]
    instance_path = ue["instance_path"]
    texture_params = manifest["material_parameters"]["textures"]
    scalar_params = manifest.get("material_parameters", {}).get("scalars", {})
    vector_params = manifest.get("material_parameters", {}).get("vectors", {})

    parent = unreal.load_asset(parent_path)
    if not parent:
        raise RuntimeError(f"missing_parent_material: {parent_path}")

    package_path, asset_name = instance_path.rsplit("/", 1)
    existing = unreal.EditorAssetLibrary.load_asset(instance_path)

    if existing:
        instance = existing
    else:
        factory = unreal.MaterialInstanceConstantFactoryNew()
        # 'initial_parent' is not exposed on the factory in UE 5.7+ Python, so
        # try it (older engines) and otherwise set the parent on the instance.
        try:
            factory.set_editor_property("initial_parent", parent)
        except Exception:
            pass
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        instance = asset_tools.create_asset(asset_name, package_path, unreal.MaterialInstanceConstant, factory)

    if instance.get_editor_property("parent") != parent:
        instance.set_editor_property("parent", parent)

    for param_name, tex_path in texture_params.items():
        tex = unreal.load_asset(tex_path)
        if not tex:
            raise RuntimeError(f"missing_texture_asset: {tex_path}")
        unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(instance, param_name, tex)

    for param_name, value in scalar_params.items():
        unreal.MaterialEditingLibrary.set_material_instance_scalar_parameter_value(instance, param_name, float(value))

    unreal.EditorAssetLibrary.save_loaded_asset(instance)

    return {"status": "ok", "material_instance_path": instance_path}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    result = create_or_update(manifest, root)

    report_dir = root / "procedural/reports/materials" / manifest["recipe_id"]
    report_dir.mkdir(parents=True, exist_ok=True)
    with open(report_dir / "material_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
