#!/usr/bin/env python3
r"""
wire_terrain_soot.py (UE5 Python)

Closes the thin StateForge spine (forge_design_decisions D9-D11): wires
M_Terrain_Master to SAMPLE MPC_WorldState.IndustrialPressure and lerp its base
color (and roughness) toward a sooted look, so a
`WorldForge.SetState ... industrial_pressure X` push produces a visible terrain
reaction.

This automates what adaptive_world_state_system.md called a "human Tier-2 edit".
It still mutates the master .uasset, so it is a Tier-2 change: human-run / reviewed,
NOT an agent-safe Tier-0/1 step.

RUN INSIDE UNREAL (imports `unreal`):
  * make wire-terrain-soot, or
  * UnrealEditor-cmd <uproject> -ExecutePythonScript="<abs>/wire_terrain_soot.py"

Prerequisite: MPC_WorldState must exist (run create_world_state_mpc.py first).

Splices, using the UE5.7 MaterialEditingLibrary API, between the node currently
feeding a property and the property itself:

    CollectionParameter(MPC_WorldState.IndustrialPressure) --.
                                                             v
    <current BaseColor source> --A-->  Lerp(A,B,Alpha) --> BaseColor
              SOOT_COLOR        --B-->
    <current Roughness source>  --A-->  Lerp(A,B,Alpha) --> Roughness
              SOOT_ROUGHNESS    --B-->

Idempotent: if BaseColor is already fed by a LinearInterpolate (our prior wiring),
it is left alone unless --force is passed.
"""

import argparse
import json

import unreal

# Master lives in the CoreTerrainMaterials plugin (NOT /Game) so it can sample the
# plugin-local MPC without a plugin -> /Game content dependency (D10).
MASTER_PATH = "/CoreTerrainMaterials/Materials/Masters/M_Terrain_Master"
MPC_PATH = "/CoreTerrainMaterials/State/MPC_WorldState"
MPC_PARAM = "IndustrialPressure"

# Sooted targets: near-black warm grey base color, fully rough.
SOOT_COLOR = (0.045, 0.040, 0.035)
SOOT_ROUGHNESS = 1.0
# Fallback roughness baseline if nothing currently feeds the Roughness pin.
DEFAULT_CLEAN_ROUGHNESS = 0.6

MEL = unreal.MaterialEditingLibrary


def _prop(name):
    return getattr(unreal.MaterialProperty, name)


def _input_node(material, prop_name):
    """(expression, output_name) currently feeding a material property, or (None, '')."""
    prop = _prop(prop_name)
    node = MEL.get_material_property_input_node(material, prop)
    if not node:
        return None, ""
    out = MEL.get_material_property_input_node_output_name(material, prop)
    return node, (out or "")


def wire(force):
    if not unreal.EditorAssetLibrary.does_asset_exist(MASTER_PATH):
        raise RuntimeError(f"master_not_found: {MASTER_PATH}")
    if not unreal.EditorAssetLibrary.does_asset_exist(MPC_PATH):
        raise RuntimeError(f"mpc_not_found: {MPC_PATH} (run create_world_state_mpc.py first)")

    material = unreal.load_asset(MASTER_PATH)
    if not material:
        raise RuntimeError(f"failed_to_load_master: {MASTER_PATH}")

    base_node, base_out = _input_node(material, "MP_BASE_COLOR")

    if isinstance(base_node, unreal.MaterialExpressionLinearInterpolate) and not force:
        unreal.log(f"Soot reaction already wired on {MASTER_PATH} (pass --force to rebuild).")
        return {"status": "skipped", "master": MASTER_PATH}

    mpc = unreal.load_asset(MPC_PATH)

    # --- Alpha: MPC_WorldState.IndustrialPressure (scalar, 0..1 by contract) ---
    collection = MEL.create_material_expression(
        material, unreal.MaterialExpressionCollectionParameter, -760, 600)
    collection.set_editor_property("collection", mpc)
    collection.set_editor_property("parameter_name", MPC_PARAM)

    # --- Base color: lerp(current source, SOOT_COLOR, alpha) ---
    soot = MEL.create_material_expression(
        material, unreal.MaterialExpressionConstant3Vector, -520, 760)
    soot.set_editor_property("constant", unreal.LinearColor(*SOOT_COLOR, 1.0))

    color_lerp = MEL.create_material_expression(
        material, unreal.MaterialExpressionLinearInterpolate, -280, 600)
    if base_node:
        MEL.connect_material_expressions(base_node, base_out, color_lerp, "A")
    else:
        # Nothing currently feeds BaseColor: lerp from a neutral terrain grey so the
        # reaction is still visible.
        clean = MEL.create_material_expression(
            material, unreal.MaterialExpressionConstant3Vector, -520, 600)
        clean.set_editor_property("constant", unreal.LinearColor(0.5, 0.42, 0.34, 1.0))
        MEL.connect_material_expressions(clean, "", color_lerp, "A")
    MEL.connect_material_expressions(soot, "", color_lerp, "B")
    MEL.connect_material_expressions(collection, "", color_lerp, "Alpha")
    MEL.connect_material_property(color_lerp, "", _prop("MP_BASE_COLOR"))

    # --- Roughness: lerp(current source, SOOT_ROUGHNESS, alpha) ---
    rough_node, rough_out = _input_node(material, "MP_ROUGHNESS")
    rough_soot = MEL.create_material_expression(
        material, unreal.MaterialExpressionConstant, -520, 960)
    rough_soot.set_editor_property("r", float(SOOT_ROUGHNESS))

    rough_lerp = MEL.create_material_expression(
        material, unreal.MaterialExpressionLinearInterpolate, -280, 920)
    if rough_node:
        MEL.connect_material_expressions(rough_node, rough_out, rough_lerp, "A")
    else:
        rough_clean = MEL.create_material_expression(
            material, unreal.MaterialExpressionConstant, -520, 920)
        rough_clean.set_editor_property("r", float(DEFAULT_CLEAN_ROUGHNESS))
        MEL.connect_material_expressions(rough_clean, "", rough_lerp, "A")
    MEL.connect_material_expressions(rough_soot, "", rough_lerp, "B")
    MEL.connect_material_expressions(collection, "", rough_lerp, "Alpha")
    MEL.connect_material_property(rough_lerp, "", _prop("MP_ROUGHNESS"))

    MEL.layout_material_expressions(material)
    MEL.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(MASTER_PATH)

    # Verify: BaseColor should now be fed by our Lerp.
    after, _ = _input_node(material, "MP_BASE_COLOR")
    ok = isinstance(after, unreal.MaterialExpressionLinearInterpolate)
    unreal.log(f"Wired soot reaction into {MASTER_PATH} <- {MPC_PATH}.{MPC_PARAM} "
               f"(base_had_source={base_node is not None}, verify_lerp={ok})")
    return {
        "status": "ok" if ok else "wired_but_unverified",
        "master": MASTER_PATH,
        "mpc": MPC_PATH,
        "param": MPC_PARAM,
        "base_had_source": base_node is not None,
        "roughness_had_source": rough_node is not None,
    }


def main():
    parser = argparse.ArgumentParser(description="Wire M_Terrain_Master soot reaction to MPC_WorldState.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--force", action="store_true", help="Rewire even if already wired.")
    args = parser.parse_args()

    result = wire(args.force)
    out = unreal.Paths.project_saved_dir() + "wire_terrain_soot_result.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    unreal.log("wire_terrain_soot result: " + json.dumps(result))


if __name__ == "__main__":
    main()
