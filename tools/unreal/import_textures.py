#!/usr/bin/env python3
r"""
import_textures.py (UE5 Python)
Manifest-driven texture import with --project-root support and report output.
"""

import argparse
import json
from pathlib import Path
import unreal

COMPRESSION_MAP = {
    "Default": unreal.TextureCompressionSettings.TC_DEFAULT,
    "Normalmap": unreal.TextureCompressionSettings.TC_NORMALMAP,
    "Masks": unreal.TextureCompressionSettings.TC_MASKS,
    "Grayscale": unreal.TextureCompressionSettings.TC_GRAYSCALE,
}

# Manifest texture_group name -> candidate UE enum member names.
# Resolved lazily with getattr so differences in the Python enum spelling
# across engine versions (e.g. 5.7 vs 5.8) never crash the module at import.
TEXTURE_GROUP_CANDIDATES = {
    "World": ["TEXTUREGROUP_WORLD"],
    "WorldNormalMap": ["TEXTUREGROUP_WORLD_NORMAL_MAP", "TEXTUREGROUP_WORLDNORMALMAP"],
}


def resolve_texture_group(name):
    for attr in TEXTURE_GROUP_CANDIDATES.get(name, []):
        if hasattr(unreal.TextureGroup, attr):
            return getattr(unreal.TextureGroup, attr)
    return None


def resolve_path(p: str, root: Path) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else (root / pp).resolve()


def import_and_configure(info: dict, project_root: Path):
    source = resolve_path(info["source_file"], project_root)
    ue_path = info["ue_asset_path"]
    srgb = info["srgb"]
    comp = info["compression"]
    tgroup = info.get("texture_group", "World")

    if not source.exists():
        raise FileNotFoundError(f"Source texture missing: {source}")

    if comp not in COMPRESSION_MAP:
        raise ValueError(f"Unsupported compression: {comp}")

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    task = unreal.AssetImportTask()
    task.filename = str(source)
    task.destination_path = str(Path(ue_path).parent)
    task.destination_name = Path(ue_path).name
    task.replace_existing = True
    task.automated = True
    task.save = True
    task.factory = unreal.TextureFactory()

    asset_tools.import_asset_tasks([task])

    tex = unreal.EditorAssetLibrary.load_asset(ue_path)
    if not tex:
        raise RuntimeError(f"Failed to load texture: {ue_path}")

    tex.set_editor_property("srgb", srgb)
    tex.set_editor_property("compression_settings", COMPRESSION_MAP[comp])
    lod_group = resolve_texture_group(tgroup)
    if lod_group is not None:
        tex.set_editor_property("lod_group", lod_group)

    unreal.EditorAssetLibrary.save_loaded_asset(tex)
    return {"ue_asset_path": ue_path, "srgb": srgb, "compression": comp}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    results = []
    for tex_type, info in manifest["exports"].items():
        results.append(import_and_configure(info, root))

    report_dir = root / "procedural/reports/materials" / manifest["recipe_id"]
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {"status": "ok", "recipe_id": manifest["recipe_id"], "imported_textures": results, "errors": []}
    with open(report_dir / "import_result.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
