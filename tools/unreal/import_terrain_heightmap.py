#!/usr/bin/env python3
r"""
import_terrain_heightmap.py (UE5 Python) — TerrainForge Lite UE bridge.

Reads the staged terrain descriptor and verifies/creates the UE-side terrain
representation for TerrainForge Lite.  For v0.6 Lite, the "terrain" in UE is
a tagged terrain preview map that references the heightmap and masks from the
descriptor.  Full Landscape import is a post-Lite scope item.

What this script does:
  - Loads the descriptor staged by run_terrain_ue.py
  - Verifies the terrain MI (ue_terrain.landscape_material) exists in UE
  - Creates a preview map at /Game/WorldForge/Terrain/<terrain_name>_Preview
  - Spawns a tagged ground plane with ue_terrain metadata tags
  - Writes procedural/reports/terrain/<NAME>/ue_terrain_report.json

Run via:
    make import-terrain NAME=Terrain_AshFlats_01
"""

import json
import os
import traceback

import unreal

TAG_TERRAIN_FORGE = "wf_terrain_forge"
PREVIEW_MAP_ROOT = "/Game/WorldForge/Terrain"
ACTIVE_DESCRIPTOR = "procedural/reports/terrain/_active_terrain_descriptor.json"
PLANE = "/Engine/BasicShapes/Plane"
PLANE_SCALE = 40.0


def log(m):
    unreal.log("[import-terrain] {}".format(m))


def _les():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def _eas():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _spawn_mesh(mesh_path, loc):
    mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
    try:
        a = _eas().spawn_actor_from_object(mesh, loc, unreal.Rotator(0, 0, 0))
    except Exception:
        a = unreal.EditorLevelLibrary.spawn_actor_from_object(mesh, loc, unreal.Rotator(0, 0, 0))
    return a


def main():
    root = os.path.normpath(unreal.Paths.project_dir())
    desc_path = os.path.join(root, ACTIVE_DESCRIPTOR)
    if not os.path.isfile(desc_path):
        raise SystemExit("[import-terrain] descriptor not staged: {}".format(desc_path))

    with open(desc_path, "r", encoding="utf-8") as f:
        descriptor = json.load(f)

    terrain_name = descriptor["terrain_name"]
    recipe_id = descriptor.get("recipe_id", "unknown")
    ue_terrain = descriptor.get("ue_terrain", {})
    mi_path = ue_terrain.get("landscape_material", "")
    outputs = descriptor.get("outputs", {})

    report_dir = os.path.join(root, "procedural", "reports", "terrain", terrain_name)
    os.makedirs(report_dir, exist_ok=True)

    report = {
        "terrain_name": terrain_name,
        "recipe_id": recipe_id,
        "checks": {},
        "failures": [],
        "warnings": [],
    }

    def check(name, ok, detail="", warn_only=False):
        report["checks"][name] = {"ok": bool(ok), "detail": str(detail)}
        if not ok:
            if warn_only:
                report["warnings"].append("{}: {}".format(name, detail or "warn"))
            else:
                report["failures"].append("{}: {}".format(name, detail or "failed"))
        return bool(ok)

    try:
        # Check landscape MI exists in UE
        mi_exists = bool(mi_path) and unreal.EditorAssetLibrary.does_asset_exist(mi_path)
        check("landscape_material_exists", mi_exists,
              "mi_path={}".format(mi_path))

        # Check descriptor output paths exist on disk (UE can reference them)
        for key, rel_path in outputs.items():
            full = os.path.join(root, rel_path.replace("/", os.sep))
            check("output_{}_on_disk".format(key), os.path.isfile(full), rel_path)

        # Create preview map
        preview_map = "{}/{}".format(PREVIEW_MAP_ROOT, terrain_name + "_Preview")
        if unreal.EditorAssetLibrary.does_asset_exist(preview_map):
            unreal.EditorAssetLibrary.delete_asset(preview_map)
        map_ok = _les().new_level(preview_map)
        check("preview_map_created", bool(map_ok), preview_map)

        if map_ok:
            # Spawn terrain ground plane
            ground = _spawn_mesh(PLANE, unreal.Vector(0, 0, 0))
            ground.set_actor_label("TerrainForge_{}".format(terrain_name))
            ground.set_actor_scale3d(unreal.Vector(PLANE_SCALE, PLANE_SCALE, 1.0))

            # Tag with TerrainForge metadata
            tags = [
                TAG_TERRAIN_FORGE,
                "wf_terrain_name:{}".format(terrain_name),
                "wf_terrain_recipe:{}".format(recipe_id),
                "wf_terrain_heightmap:{}".format(outputs.get("heightmap", "")),
                "wf_terrain_placement_mask:{}".format(outputs.get("placement_mask", "")),
                "wf_terrain_nav_mask:{}".format(outputs.get("nav_safe_mask", "")),
            ]
            ground.tags = tags

            # Apply MI if it exists
            if mi_exists:
                mi = unreal.EditorAssetLibrary.load_asset(mi_path)
                if mi:
                    ground.static_mesh_component.set_material(0, mi)
                    log("applied MI: {}".format(mi_path))

            _les().save_current_level()
            log("preview map saved: {}".format(preview_map))

        report["passed"] = len(report["failures"]) == 0
        report["status"] = "ok" if report["passed"] else "error"

    except Exception as exc:  # noqa: BLE001
        report["passed"] = False
        report["status"] = "error"
        report["failures"].append(str(exc))
        report["traceback"] = traceback.format_exc()
        log("ERROR: {}".format(exc))

    with open(os.path.join(report_dir, "ue_terrain_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    verdict = "PASS" if report.get("passed") else "FAIL"
    log("import_terrain: {} ({} failure(s))".format(verdict, len(report["failures"])))


if __name__ == "__main__":
    main()
