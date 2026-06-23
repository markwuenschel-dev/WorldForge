#!/usr/bin/env python3
r"""
create_world_state_mpc.py (UE5 Python)

Creates/updates MPC_WorldState - the curated render mirror that materials sample to
react to world state (forge_design_decisions D10). UWorldStateSubsystem pushes
render-facing values into this collection; materials read ONLY this collection,
never the subsystem.

It lives in the CoreTerrainMaterials plugin (next to M_Terrain_Master) so the master
can sample it without a plugin -> /Game content dependency. The scalar parameters
here MUST stay in sync with UWorldStateSubsystem::GetCuratedMpcParams().

This script creates the asset only; wiring the master material to SAMPLE
IndustrialPressure is a human Tier-2 edit (it touches the .uasset master).
"""

import argparse
import json

import unreal

MPC_PACKAGE_PATH = "/CoreTerrainMaterials/State"
MPC_ASSET_NAME = "MPC_WorldState"

# Keep in sync with UWorldStateSubsystem::GetCuratedMpcParams() (MPC param names).
SCALAR_PARAMS = [
    ("IndustrialPressure", 0.0),
    ("CorruptionLevel", 0.0),
    ("RestorationLevel", 0.0),
    ("Wetness", 0.0),
    ("Ashfall", 0.0),
]
VECTOR_PARAMS = [
    ("FactionTint", unreal.LinearColor(1.0, 1.0, 1.0, 1.0)),
]


def _new_guid():
    try:
        return unreal.GuidLibrary.new_guid()
    except Exception:
        return None


def _make_scalar(name, default):
    p = unreal.CollectionScalarParameter()
    p.set_editor_property("parameter_name", name)
    p.set_editor_property("default_value", float(default))
    guid = _new_guid()
    if guid is not None:
        try:
            p.set_editor_property("id", guid)
        except Exception:
            pass
    return p


def _make_vector(name, default):
    p = unreal.CollectionVectorParameter()
    p.set_editor_property("parameter_name", name)
    p.set_editor_property("default_value", default)
    guid = _new_guid()
    if guid is not None:
        try:
            p.set_editor_property("id", guid)
        except Exception:
            pass
    return p


def create_or_update():
    asset_path = f"{MPC_PACKAGE_PATH}/{MPC_ASSET_NAME}"
    mpc = unreal.EditorAssetLibrary.load_asset(asset_path)
    if not mpc:
        asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
        factory = unreal.MaterialParameterCollectionFactoryNew()
        mpc = asset_tools.create_asset(
            MPC_ASSET_NAME, MPC_PACKAGE_PATH, unreal.MaterialParameterCollection, factory)
        if not mpc:
            raise RuntimeError(f"mpc_create_failed: {asset_path}")

    mpc.set_editor_property("scalar_parameters",
                            [_make_scalar(n, d) for n, d in SCALAR_PARAMS])
    mpc.set_editor_property("vector_parameters",
                            [_make_vector(n, d) for n, d in VECTOR_PARAMS])

    unreal.EditorAssetLibrary.save_loaded_asset(mpc)

    return {
        "status": "ok",
        "mpc_path": asset_path,
        "scalar_parameters": [n for n, _ in SCALAR_PARAMS],
        "vector_parameters": [n for n, _ in VECTOR_PARAMS],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    result = create_or_update()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
