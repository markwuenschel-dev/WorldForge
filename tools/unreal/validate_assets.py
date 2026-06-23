#!/usr/bin/env python3
r"""
validate_assets.py (UE5 Python)

Tier-3 generated-asset validation (forge_design_decisions D6): correctness of the
assets a recipe produced - texture budgets, import settings, reference integrity,
naming, and the Data Asset's provenance linkage. Shader-cost budgets are NOT here;
Material Instances inherit the master's cost, so that lives in Tier-2 (the master).

Manifest-driven, with report output. Exits non-zero on any error.
"""

import argparse
import json
from pathlib import Path

import unreal

MAX_TEXTURE_SIZE = 2048

COMPRESSION_MAP = {
    "Default": unreal.TextureCompressionSettings.TC_DEFAULT,
    "Normalmap": unreal.TextureCompressionSettings.TC_NORMALMAP,
    "Masks": unreal.TextureCompressionSettings.TC_MASKS,
}

GROUP_MAP = {
    "World": unreal.TextureGroup.TEXTUREGROUP_WORLD,
}


def _short_name(object_path: str) -> str:
    """'/Game/Foo/T_Bar' or '/Game/Foo/T_Bar.T_Bar' -> 'T_Bar'."""
    return object_path.split(".")[0].rsplit("/", 1)[-1]


def validate_textures(exports: dict, errors: list, warnings: list):
    for tex_type, info in exports.items():
        ue_path = info["ue_asset_path"]
        tex = unreal.EditorAssetLibrary.load_asset(ue_path)
        if not tex:
            errors.append({"category": "missing_texture_asset", "message": ue_path})
            continue

        # Naming: terrain textures use the T_ prefix.
        if not _short_name(ue_path).startswith("T_"):
            errors.append({"category": "naming_violation",
                           "message": f"texture not T_-prefixed: {ue_path}"})

        # sRGB.
        if tex.get_editor_property("srgb") != info["srgb"]:
            errors.append({"category": "texture_setting_mismatch",
                           "message": f"{tex_type} sRGB expected {info['srgb']}"})

        # Resolution budget (<= 2048).
        size_x = tex.blueprint_get_size_x()
        size_y = tex.blueprint_get_size_y()
        if size_x > MAX_TEXTURE_SIZE or size_y > MAX_TEXTURE_SIZE:
            errors.append({"category": "texture_budget_exceeded",
                           "message": f"{tex_type} is {size_x}x{size_y} > {MAX_TEXTURE_SIZE}"})

        # Compression setting.
        expected_comp = COMPRESSION_MAP.get(info.get("compression"))
        if expected_comp is not None:
            actual_comp = tex.get_editor_property("compression_settings")
            if actual_comp != expected_comp:
                errors.append({"category": "texture_setting_mismatch",
                               "message": f"{tex_type} compression expected {info['compression']}"})

        # Texture (LOD) group.
        expected_group = GROUP_MAP.get(info.get("texture_group"))
        if expected_group is not None:
            actual_group = tex.get_editor_property("lod_group")
            if actual_group != expected_group:
                errors.append({"category": "texture_setting_mismatch",
                               "message": f"{tex_type} texture group expected {info['texture_group']}"})

        # Mips: terrain textures should have a mip chain (warn, don't fail).
        mip_settings = tex.get_editor_property("mip_gen_settings")
        if mip_settings == unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS:
            warnings.append({"category": "no_mipmaps",
                             "message": f"{tex_type} has no mipmaps"})


def validate_material_instance(manifest: dict, errors: list):
    ue = manifest["ue"]
    mi = unreal.EditorAssetLibrary.load_asset(ue["instance_path"])
    if not mi:
        errors.append({"category": "missing_material_instance", "message": ue["instance_path"]})
        return None

    if not _short_name(ue["instance_path"]).startswith("MI_"):
        errors.append({"category": "naming_violation",
                       "message": f"material instance not MI_-prefixed: {ue['instance_path']}"})

    parent = mi.get_editor_property("parent")
    parent_path = parent.get_path_name().split(".")[0] if parent else None
    if parent_path != ue["parent_material"]:
        errors.append({"category": "material_parameter_wiring_failure",
                       "message": f"Wrong parent: {parent_path}"})

    # Reference integrity: MI texture params resolve to the manifest's textures.
    for param_name, tex_path in manifest["material_parameters"]["textures"].items():
        bound = unreal.MaterialEditingLibrary.get_material_instance_texture_parameter_value(
            mi, param_name)
        bound_path = bound.get_path_name().split(".")[0] if bound else None
        if bound_path != tex_path:
            errors.append({"category": "material_parameter_wiring_failure",
                           "message": f"{param_name} bound to {bound_path}, expected {tex_path}"})
    return mi


def validate_data_asset(manifest: dict, mi, errors: list):
    ue = manifest["ue"]
    if not ue.get("generate_data_asset", False):
        return

    da_path = ue.get("data_asset_path")
    if not da_path:
        errors.append({"category": "missing_data_asset_path",
                       "message": "manifest ue.data_asset_path is required"})
        return

    da = unreal.EditorAssetLibrary.load_asset(da_path)
    if not da:
        errors.append({"category": "missing_data_asset", "message": da_path})
        return

    if not isinstance(da, unreal.MaterialRecipeDataAsset):
        errors.append({"category": "data_asset_wrong_class", "message": da_path})
        return

    if not _short_name(da_path).startswith("DA_"):
        errors.append({"category": "naming_violation",
                       "message": f"data asset not DA_-prefixed: {da_path}"})

    if str(da.get_editor_property("recipe_id")) != manifest["recipe_id"]:
        errors.append({"category": "data_asset_provenance_mismatch",
                       "message": "recipe_id mismatch"})

    # Linkage integrity.
    linked_mi = da.get_editor_property("material_instance")
    if mi is not None and linked_mi != mi:
        errors.append({"category": "data_asset_linkage_failure",
                       "message": "material_instance does not point at the produced MI"})

    linked_textures = da.get_editor_property("texture_outputs")
    expected_textures = manifest["material_parameters"]["textures"]
    if len(linked_textures) != len(expected_textures):
        errors.append({"category": "data_asset_linkage_failure",
                       "message": f"texture_outputs count {len(linked_textures)} != {len(expected_textures)}"})

    # Provenance copied verbatim from the manifest.
    prov = manifest.get("provenance", {})
    for da_field, prov_key in (
        ("source_commit", "source_commit"),
        ("generated_at_utc", "generated_at_utc"),
        ("generator_name", "generator_name"),
    ):
        if str(da.get_editor_property(da_field)) != str(prov.get(prov_key, "")):
            errors.append({"category": "data_asset_provenance_mismatch",
                           "message": f"{da_field} does not match manifest provenance"})

    # Staleness: recorded recipe hash must match the manifest's current input hash.
    source_recipe = manifest.get("source_recipe", "")
    expected_hash = prov.get("inputs", {}).get(source_recipe, "")
    if str(da.get_editor_property("source_recipe_hash")) != str(expected_hash):
        errors.append({"category": "stale_provenance",
                       "message": "source_recipe_hash does not match manifest (regenerate)"})


def validate(manifest: dict, project_root: Path):
    errors = []
    warnings = []

    validate_textures(manifest["exports"], errors, warnings)
    mi = validate_material_instance(manifest, errors)
    validate_data_asset(manifest, mi, errors)

    status = "ok" if not errors else "failed"
    return {
        "status": status,
        "recipe_id": manifest["recipe_id"],
        "errors": errors,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    result = validate(manifest, root)

    report_dir = root / "procedural/reports/materials" / manifest["recipe_id"]
    report_dir.mkdir(parents=True, exist_ok=True)
    with open(report_dir / "asset_validation_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))

    if result["status"] != "ok":
        raise RuntimeError("Validation failed")


if __name__ == "__main__":
    main()
