#!/usr/bin/env python3
r"""
create_biome_terrain_mis.py (UE5 Python) -- WorldForge v1.1 BiomeForge.

Creates the five biome terrain material instances the biome slice specs reference
(MI_Terrain_Forest/Alpine/Ashlands/Wetland/AlienCrystal_01) plus a shared,
WorldForge-owned biome terrain master material. Mirrors the desert render-proof
terrain wiring: base color is lerp(PreviewBaseColor, SOOT, MPC.IndustrialPressure),
a VECTOR parameter (vector overrides render correctly in the headless path). Each
MI carries its biome's representative terrain tint so the maps are visibly distinct.

Owned under /Game/WorldForge/Generated/Materials/Terrain so package-check ownership
holds. Run headless via run_ue_recipe-style launch; writes a small JSON report.

Report: procedural/reports/materials/biome_terrain_mis_report.json
"""

import json
import os
import traceback

import unreal

TERRAIN_DIR = "/Game/WorldForge/Generated/Materials/Terrain"
MASTER_PATH = TERRAIN_DIR + "/M_WF_TerrainBiome"
MPC_PATH = "/CoreTerrainMaterials/State/MPC_WorldState"
MPC_PRESSURE_PARAM = "IndustrialPressure"
SOOT_COLOR = (0.05, 0.045, 0.04)

# (mi_name, representative terrain tint, roughness)
BIOME_MIS = [
    ("MI_Terrain_Forest_01",      (0.22, 0.28, 0.14), 0.90),
    ("MI_Terrain_Alpine_01",      (0.90, 0.93, 0.97), 0.55),
    ("MI_Terrain_Ashlands_01",    (0.10, 0.09, 0.08), 0.85),
    ("MI_Terrain_Wetland_01",     (0.20, 0.16, 0.11), 0.60),
    ("MI_Terrain_AlienCrystal_01", (0.35, 0.20, 0.55), 0.40),
]


def log(m):
    unreal.log("[biome-terrain-mis] {}".format(m))


def build_master():
    """Create the shared biome terrain master (PreviewBaseColor vector -> base color,
    state-darkened via MPC soot lerp). Rebuilt so a stale asset can't shadow it."""
    at = unreal.AssetToolsHelpers.get_asset_tools()
    mel = unreal.MaterialEditingLibrary
    if unreal.EditorAssetLibrary.does_asset_exist(MASTER_PATH):
        unreal.EditorAssetLibrary.delete_asset(MASTER_PATH)
    mat = at.create_asset("M_WF_TerrainBiome", TERRAIN_DIR, unreal.Material,
                          unreal.MaterialFactoryNew())
    vp = mel.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -700, -120)
    vp.set_editor_property("parameter_name", "PreviewBaseColor")
    vp.set_editor_property("default_value", unreal.LinearColor(0.5, 0.5, 0.5, 1.0))
    soot = mel.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -700, 120)
    soot.set_editor_property("constant", unreal.LinearColor(SOOT_COLOR[0], SOOT_COLOR[1], SOOT_COLOR[2], 1.0))
    cp = mel.create_material_expression(mat, unreal.MaterialExpressionCollectionParameter, -700, 320)
    mpc = unreal.EditorAssetLibrary.load_asset(MPC_PATH)
    if mpc:
        cp.set_editor_property("collection", mpc)
        cp.set_editor_property("parameter_name", MPC_PRESSURE_PARAM)
    else:
        log("MPC {} not found; terrain will not state-darken".format(MPC_PATH))
    lerp = mel.create_material_expression(mat, unreal.MaterialExpressionLinearInterpolate, -350, 0)
    mel.connect_material_expressions(vp, "", lerp, "A")
    mel.connect_material_expressions(soot, "", lerp, "B")
    if mpc:
        mel.connect_material_expressions(cp, "", lerp, "Alpha")
    mel.connect_material_property(lerp, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = mel.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -350, 240)
    rough.set_editor_property("parameter_name", "Roughness")
    rough.set_editor_property("default_value", 0.85)
    mel.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    mel.recompile_material(mat)
    unreal.EditorAssetLibrary.save_loaded_asset(mat)
    log("biome terrain master built: {}".format(MASTER_PATH))
    return mat


def build_mi(mat, mi_name, color, roughness):
    at = unreal.AssetToolsHelpers.get_asset_tools()
    mel = unreal.MaterialEditingLibrary
    mi_path = TERRAIN_DIR + "/" + mi_name
    if unreal.EditorAssetLibrary.does_asset_exist(mi_path):
        unreal.EditorAssetLibrary.delete_asset(mi_path)
    mic = at.create_asset(mi_name, TERRAIN_DIR, unreal.MaterialInstanceConstant,
                          unreal.MaterialInstanceConstantFactoryNew())
    mic.set_editor_property("parent", mat)
    mel.set_material_instance_vector_parameter_value(
        mic, "PreviewBaseColor", unreal.LinearColor(color[0], color[1], color[2], 1.0))
    mel.set_material_instance_scalar_parameter_value(mic, "Roughness", roughness)
    unreal.EditorAssetLibrary.save_loaded_asset(mic)
    log("MI built: {} tint={}".format(mi_path, color))
    return mi_path


def main():
    root = os.path.normpath(unreal.Paths.project_dir())
    out_dir = os.path.join(root, "procedural", "reports", "materials")
    os.makedirs(out_dir, exist_ok=True)
    report = {"master": MASTER_PATH, "mis": [], "errors": []}
    try:
        mat = build_master()
        for mi_name, color, roughness in BIOME_MIS:
            p = build_mi(mat, mi_name, color, roughness)
            report["mis"].append({"path": p, "tint": list(color), "roughness": roughness})
        report["status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        report["status"] = "error"
        report["errors"].append(str(exc))
        report["traceback"] = traceback.format_exc()
        log("ERROR: {}".format(exc))
    with open(os.path.join(out_dir, "biome_terrain_mis_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    log("report written; status={} mis={}".format(report.get("status"), len(report["mis"])))


if __name__ == "__main__":
    main()
