#!/usr/bin/env python3
"""
validate_recipe.py
Validates a material recipe YAML file against the material_recipe_contract.md

Usage:
    python tools/substance/validate_recipe.py --recipe terrain_rock_desert_01
    python tools/substance/validate_recipe.py --recipe-path tests/fixtures/invalid_recipes/missing_id.yaml
    python tools/substance/validate_recipe.py --all
"""

import argparse
import sys
import yaml
from pathlib import Path
from typing import Dict, Any, List

ALLOWED_PARAMETERS = {
    "terrain_rock_strata.sbs": [
        "base_hue", "saturation", "value",
        "crack_density", "crack_depth", "strata_angle",
        "erosion_strength", "sand_overlay",
        "normal_intensity", "height_strength"
    ]
    # Add entries for other master graphs as they are created
}

REQUIRED_TOP_LEVEL_KEYS = [
    "schema_version", "id", "graph", "resolution", "parameters", "outputs", "ue"
]

REQUIRED_OUTPUT_KEYS = ["base_color", "normal", "roughness", "ambient_occlusion", "height"]

REQUIRED_UE_KEYS = [
    "parent_material", "instance_path", "texture_folder", "texture_group",
    "compression", "generate_data_asset", "data_asset_class"
]

# Optional ue keys: allowed but not required. data_asset_path lets a recipe
# pin the Data Asset output path explicitly; generate_manifest.py otherwise
# derives it (see forge_design_decisions D5).
OPTIONAL_UE_KEYS = [
    "data_asset_path",
]

REQUIRED_COMPRESSION_KEYS = ["base_color", "normal", "masks"]

TEXTURE_SUFFIX_RULES = {
    "base_color": "_BC",
    "normal": "_N",
    "roughness": "_R",
    "ambient_occlusion": "_AO",
    "height": "_H",
}

PARAMETER_RANGES = {
    "base_hue": (0.0, 1.0),
    "saturation": (0.0, 1.0),
    "value": (0.0, 1.0),
    "crack_density": (0.0, 1.0),
    "crack_depth": (0.0, 1.0),
    "strata_angle": (-180.0, 180.0),
    "erosion_strength": (0.0, 1.0),
    "sand_overlay": (0.0, 1.0),
    "normal_intensity": (0.0, 5.0),
    "height_strength": (0.0, 5.0),
}


def load_recipe(recipe_path: Path) -> Dict[str, Any]:
    with open(recipe_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_recipe(recipe: Dict[str, Any], recipe_name: str) -> List[str]:
    errors: List[str] = []

    # 1. schema_version must be "1.1"
    if recipe.get("schema_version") != "1.1":
        errors.append(f"schema_version must be exactly \"1.1\" (got {recipe.get('schema_version')})")

    # 2. No unknown top-level keys
    unknown_top = set(recipe.keys()) - set(REQUIRED_TOP_LEVEL_KEYS)
    if unknown_top:
        errors.append(f"Unknown top-level keys: {unknown_top}")

    # 3. Required top-level keys
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in recipe:
            errors.append(f"Missing required top-level key: '{key}'")

    if errors:
        return errors  # Early exit on critical structural issues

    # 4 & 5. Outputs validation
    outputs = recipe.get("outputs", {})
    missing_outputs = set(REQUIRED_OUTPUT_KEYS) - set(outputs.keys())
    if missing_outputs:
        errors.append(f"Missing required output keys: {missing_outputs}")

    unknown_outputs = set(outputs.keys()) - set(REQUIRED_OUTPUT_KEYS)
    if unknown_outputs:
        errors.append(f"Unknown output keys: {unknown_outputs}")

    # Texture suffix validation
    for key, suffix in TEXTURE_SUFFIX_RULES.items():
        if key in outputs and not outputs[key].endswith(suffix):
            errors.append(f"Output '{key}' must end with '{suffix}' (got {outputs[key]})")

    # 6, 7, 8. UE block validation
    ue = recipe.get("ue", {})
    missing_ue = set(REQUIRED_UE_KEYS) - set(ue.keys())
    if missing_ue:
        errors.append(f"Missing required ue keys: {missing_ue}")

    unknown_ue = set(ue.keys()) - set(REQUIRED_UE_KEYS) - set(OPTIONAL_UE_KEYS)
    if unknown_ue:
        errors.append(f"Unknown ue keys: {unknown_ue}")

    compression = ue.get("compression", {})
    missing_comp = set(REQUIRED_COMPRESSION_KEYS) - set(compression.keys())
    if missing_comp:
        errors.append(f"Missing required compression keys: {missing_comp}")

    # 9. Resolution
    res = recipe.get("resolution")
    if res not in (512, 1024, 2048, 4096):
        errors.append(f"resolution must be 512, 1024, 2048 or 4096 (got {res})")

    # 10 & 11. Parameter whitelist + range validation
    graph_name = recipe["graph"]
    allowed_params = ALLOWED_PARAMETERS.get(graph_name, [])
    params = recipe.get("parameters", {})

    for param_name, value in params.items():
        if param_name not in allowed_params:
            errors.append(f"Parameter '{param_name}' is not allowed for graph '{graph_name}'")
            continue
        if param_name in PARAMETER_RANGES:
            min_val, max_val = PARAMETER_RANGES[param_name]
            if not (min_val <= value <= max_val):
                errors.append(f"Parameter '{param_name}' out of range [{min_val}, {max_val}] (got {value})")

    # 13. UE path validation (basic)
    # parent_material is a master that may live in project content (/Game/) or in a
    # shared plugin content root (the terrain master was migrated to the
    # CoreTerrainMaterials plugin -- see relocate_master_to_plugin.py). Instances and
    # textures still live in /Game/.
    PARENT_ROOTS = ("/Game/", "/CoreTerrainMaterials/")
    if not ue.get("parent_material", "").startswith(PARENT_ROOTS):
        errors.append("ue.parent_material must start with one of {}".format(PARENT_ROOTS))
    if not ue.get("instance_path", "").startswith("/Game/"):
        errors.append("ue.instance_path must start with /Game/")
    if ue.get("texture_folder", "").startswith("/Game/"):
        errors.append("ue.texture_folder should not start with /Game/ (import script prepends it)")

    # 14. Type validation (basic)
    if not isinstance(recipe.get("id"), str):
        errors.append("id must be a string")
    if not isinstance(recipe.get("graph"), str):
        errors.append("graph must be a string")
    if not isinstance(res, int):
        errors.append("resolution must be an integer")
    if not isinstance(params, dict):
        errors.append("parameters must be an object/map")
    if not isinstance(outputs, dict):
        errors.append("outputs must be an object/map")
    if not isinstance(ue, dict):
        errors.append("ue must be an object/map")
    if "generate_data_asset" in ue and not isinstance(ue["generate_data_asset"], bool):
        errors.append("ue.generate_data_asset must be a boolean")

    # Graph exists check
    graphs_dir = Path(__file__).parent.parent.parent / "procedural" / "substance" / "graphs"
    graph_path = graphs_dir / recipe["graph"]
    if not graph_path.exists():
        errors.append(f"Master graph not found: {graph_path} (place a placeholder .sbs if testing)")

    return errors

def main():
    parser = argparse.ArgumentParser(description="Validate material recipe YAML files")
    parser.add_argument("--recipe", help="Recipe name without .yaml (e.g. terrain_rock_desert_01)")
    parser.add_argument(
        "--recipe-path",
        help="Path to an arbitrary recipe YAML to validate in place (e.g. a test fixture)",
    )
    parser.add_argument("--all", action="store_true", help="Validate all recipes in the recipes folder")
    args = parser.parse_args()

    recipes_dir = Path(__file__).parent.parent.parent / "procedural" / "substance" / "recipes"

    if args.recipe_path:
        recipe_path = Path(args.recipe_path)
        if not recipe_path.exists():
            print(f"Recipe not found: {recipe_path}")
            sys.exit(1)

        recipe = load_recipe(recipe_path)
        errors = validate_recipe(recipe, recipe_path.stem)

        if errors:
            print(f"❌ Validation failed for {recipe_path.name}")
            for e in errors:
                print(f"   - {e}")
            sys.exit(1)
        else:
            print(f"✅ {recipe_path.name} is valid")
            sys.exit(0)

    if args.all:
        recipe_files = list(recipes_dir.glob("*.yaml"))
        if not recipe_files:
            print("No recipe files found.")
            return
        all_passed = True
        for rf in recipe_files:
            recipe = load_recipe(rf)
            errors = validate_recipe(recipe, rf.stem)
            if errors:
                all_passed = False
                print(f"❌ {rf.name}")
                for e in errors:
                    print(f"   - {e}")
            else:
                print(f"✅ {rf.name}")
        print("\nValidation complete." if all_passed else "\nSome recipes failed validation.")
        sys.exit(0 if all_passed else 1)

    elif args.recipe:
        recipe_path = recipes_dir / f"{args.recipe}.yaml"
        if not recipe_path.exists():
            print(f"Recipe not found: {recipe_path}")
            sys.exit(1)

        recipe = load_recipe(recipe_path)
        errors = validate_recipe(recipe, args.recipe)

        if errors:
            print(f"❌ Validation failed for {args.recipe}.yaml")
            for e in errors:
                print(f"   - {e}")
            sys.exit(1)
        else:
            print(f"✅ {args.recipe}.yaml is valid")
            sys.exit(0)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()