#!/usr/bin/env python3
r"""
validate_assets.py (UE5 Python)
Manifest-driven validation with report output.
"""

import argparse
import json
from pathlib import Path
import unreal


def validate(manifest: dict, project_root: Path):
    errors = []
    recipe_id = manifest["recipe_id"]
    ue = manifest["ue"]
    exports = manifest["exports"]

    for tex_type, info in exports.items():
        ue_path = info["ue_asset_path"]
        tex = unreal.EditorAssetLibrary.load_asset(ue_path)
        if not tex:
            errors.append({"category": "missing_texture_asset", "message": ue_path})
            continue
        if tex.get_editor_property("srgb") != info["srgb"]:
            errors.append({"category": "texture_setting_mismatch", "message": f"{tex_type} sRGB"})

    mi = unreal.EditorAssetLibrary.load_asset(ue["instance_path"])
    if not mi:
        errors.append({"category": "missing_material_instance", "message": ue["instance_path"]})
    else:
        parent = mi.get_editor_property("parent")
        # get_path_name() returns "/Game/.../Name.Name"; compare the package path
        # (before the object-name suffix) against the manifest's parent_material.
        parent_path = parent.get_path_name().split(".")[0] if parent else None
        if parent_path != ue["parent_material"]:
            errors.append({"category": "material_parameter_wiring_failure",
                           "message": f"Wrong parent: {parent_path}"})

    status = "ok" if not errors else "failed"
    result = {
        "status": status,
        "recipe_id": recipe_id,
        "errors": errors
    }
    return result


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
