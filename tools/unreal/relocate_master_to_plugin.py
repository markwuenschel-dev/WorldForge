#!/usr/bin/env python3
r"""
relocate_master_to_plugin.py (UE5 Python)

One-off migration: build the terrain master at its new home inside the
CoreTerrainMaterials *plugin* (the manifest's parent_material now points at
/CoreTerrainMaterials/Materials/Masters/M_Terrain_Master), re-parent the
material instance onto it, validate, then delete the stale project-side master
at /Game/Materials/Masters/M_Terrain_Master.

RUN INSIDE UNREAL, as a single line in the Python console (avoids multi-line
paste indentation problems):

    exec(open(r"C:/Users/Nalakram/Documents/Unreal Projects/WorldForge/tools/unreal/relocate_master_to_plugin.py").read())
"""

import sys
import unreal

BASE = r"C:/Users/Nalakram/Documents/Unreal Projects/WorldForge"
RECIPE = "terrain_rock_desert_01"
MANIFEST = BASE + "/procedural/manifests/materials/" + RECIPE + ".json"
OLD_MASTER = "/Game/Materials/Masters/M_Terrain_Master"


def run(script):
    sys.argv = [script, "--manifest", MANIFEST, "--project-root", BASE]
    exec(open(BASE + "/tools/unreal/" + script).read(), {"__name__": "__main__"})


run("create_master_material.py")        # builds master at the plugin path (new -> no --force needed)
run("create_material_instances.py")     # re-parents MI_Terrain_Rock_Desert_01 onto the plugin master
run("validate_assets.py")               # expect status: ok

# Only now that the instance points at the plugin master, remove the old one.
if unreal.EditorAssetLibrary.does_asset_exist(OLD_MASTER):
    unreal.EditorAssetLibrary.delete_asset(OLD_MASTER)
    print("removed old master:", OLD_MASTER)
else:
    print("old master already gone:", OLD_MASTER)
