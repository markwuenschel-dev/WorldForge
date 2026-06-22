#!/usr/bin/env python3
"""
generate_manifest.py
Produces a stable JSON manifest from a validated material recipe.
This is the contract handed to UE Python scripts.
"""

import argparse
import json
import sys
import yaml
from pathlib import Path

# Explicit mapping to avoid bad names like Base_colorTexture
TEXTURE_PARAMETER_NAMES = {
    "base_color": "BaseColorTexture",
    "normal": "NormalTexture",
    "roughness": "RoughnessTexture",
    "ambient_occlusion": "AOTexture",
    "height": "HeightTexture",
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", required=True)
    args = parser.parse_args()

    recipes_dir = Path(__file__).parent.parent.parent / "procedural" / "substance" / "recipes"
    recipe_path = recipes_dir / f"{args.recipe}.yaml"

    if not recipe_path.exists():
        print(f"ERROR: Recipe not found: {recipe_path}", file=sys.stderr)
        sys.exit(1)

    with open(recipe_path, "r", encoding="utf-8") as f:
        recipe = yaml.safe_load(f)

    for key in ["id", "schema_version", "graph", "resolution", "outputs", "ue"]:
        if key not in recipe:
            print(f"ERROR: Missing required key '{key}'", file=sys.stderr)
            sys.exit(1)

    ue = recipe["ue"]
    outputs = recipe["outputs"]
    texture_folder = ue.get("texture_folder", "Textures/Terrain")

    manifest = {
        "recipe_id": recipe["id"],
        "schema_version": recipe["schema_version"],
        "graph": recipe["graph"],
        "resolution": recipe["resolution"],
        "source_recipe": str(recipe_path.relative_to(Path(__file__).parent.parent.parent)),
        "substance_graph_path": str(Path("procedural/substance/graphs") / recipe["graph"]),
        "exports": {},
        "ue": {
            "parent_material": ue.get("parent_material"),
            "instance_path": ue.get("instance_path"),
            "texture_folder": f"/Game/{texture_folder}",
            "generate_data_asset": ue.get("generate_data_asset", False),
            "data_asset_class": ue.get("data_asset_class"),
        },
        "material_parameters": {
            "textures": {},
            "scalars": recipe.get("parameters", {}),
            "vectors": {}
        }
    }

    for tex_type, tex_name in outputs.items():
        source_file = f"procedural/substance/exports/{args.recipe}/{tex_name}.png"
        ue_asset_path = f"/Game/{texture_folder}/{tex_name}"

        manifest["exports"][tex_type] = {
            "name": tex_name,
            "source_file": source_file,
            "ue_asset_path": ue_asset_path,
            "srgb": tex_type == "base_color",
            "compression": ue.get("compression", {}).get(tex_type, ue.get("compression", {}).get("masks", "Default")),
            "texture_group": ue.get("texture_group", "World")
        }

        param_name = TEXTURE_PARAMETER_NAMES.get(tex_type, f"{tex_type}Texture")
        manifest["material_parameters"]["textures"][param_name] = ue_asset_path

    manifests_dir = Path(__file__).parent.parent.parent / "procedural" / "manifests" / "materials"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    output_path = manifests_dir / f"{args.recipe}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated manifest: {output_path}")

if __name__ == "__main__":
    main()
