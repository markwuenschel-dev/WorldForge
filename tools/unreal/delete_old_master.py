#!/usr/bin/env python3
r"""
delete_old_master.py (UE5 Python)

Cleanup after relocating the master into the CoreTerrainMaterials plugin:
removes the stale project-side master at /Game/Materials/Masters/M_Terrain_Master
and reports exactly what happened (delete return value + any remaining
referencers), so a silent failure can't masquerade as success.

Run inside the UE Python console, single line:
    exec(open(r"C:/Users/Nalakram/Documents/Unreal Projects/WorldForge/tools/unreal/delete_old_master.py").read())
"""

import unreal

OLD = "/Game/Materials/Masters/M_Terrain_Master"
FOLDER = "/Game/Materials/Masters"

if not unreal.EditorAssetLibrary.does_asset_exist(OLD):
    print("RESULT: old master already gone:", OLD)
else:
    # Who, if anyone, still points at it? (Should be empty: the MI was re-parented.)
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        referencers = ar.get_referencers(
            unreal.Name(OLD),
            unreal.AssetRegistryDependencyOptions(include_soft_package_references=True,
                                                  include_hard_package_references=True),
        )
    except Exception as exc:
        referencers = f"(could not query: {exc})"
    print("referencers of old master:", referencers)

    ok = unreal.EditorAssetLibrary.delete_asset(OLD)
    print("delete_asset returned:", ok)
    print("still exists after delete:", unreal.EditorAssetLibrary.does_asset_exist(OLD))

# Drop the folder too, but only if it's genuinely empty (no stray redirectors).
if unreal.EditorAssetLibrary.does_directory_exist(FOLDER):
    leftovers = unreal.EditorAssetLibrary.list_assets(FOLDER, recursive=True, include_folder=False)
    if not leftovers:
        unreal.EditorAssetLibrary.delete_directory(FOLDER)
        print("removed empty folder:", FOLDER)
    else:
        print("folder NOT removed, still contains:", leftovers)
