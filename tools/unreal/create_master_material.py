#!/usr/bin/env python3
r"""
create_master_material.py (UE5 Python)

Creates (or rebuilds) the master Material declared by a pipeline manifest,
e.g. /Game/Materials/Masters/M_Terrain_Master, with the texture and scalar
parameters the manifest lists.

RUN INSIDE UNREAL: this imports `unreal`, so it must run in the editor's
Python, not a plain interpreter. Either:

  * make create-master RECIPE=terrain_rock_desert_01      (UE_PYTHON set to the
    editor-cmd runner), or
  * from the UE Python console:
        import sys
        sys.argv = ["create_master_material.py",
                    "--manifest", r"<ABS>/procedural/manifests/materials/terrain_rock_desert_01.json",
                    "--project-root", r"<ABS>"]
        exec(open(r"<ABS>/tools/unreal/create_master_material.py").read())

It is manifest-driven so it works for any future master: parent path, texture
parameter names, and scalar parameters all come from the manifest. Each texture
parameter is routed to the right material output by name.

Note: scalar parameters (and HeightTexture) are added but left unconnected -
they exist so material instances can carry their values. They do not affect
shading until they are wired into the graph (a deliberate future step).
"""

import argparse
import json
from pathlib import Path

import unreal


# name-substring -> (material property name | None, texture output pin, sampler type)
# First match wins, so order from most- to least-specific.
TEXTURE_ROUTING = [
    ("basecolor", ("MP_BASE_COLOR", "RGB", "SAMPLERTYPE_COLOR")),
    ("albedo",    ("MP_BASE_COLOR", "RGB", "SAMPLERTYPE_COLOR")),
    ("normal",    ("MP_NORMAL", "RGB", "SAMPLERTYPE_NORMAL")),
    ("rough",     ("MP_ROUGHNESS", "R", "SAMPLERTYPE_LINEAR_COLOR")),
    ("metal",     ("MP_METALLIC", "R", "SAMPLERTYPE_LINEAR_COLOR")),
    ("ao",        ("MP_AMBIENT_OCCLUSION", "R", "SAMPLERTYPE_LINEAR_COLOR")),
    ("occlusion", ("MP_AMBIENT_OCCLUSION", "R", "SAMPLERTYPE_LINEAR_COLOR")),
    ("height",    (None, "R", "SAMPLERTYPE_LINEAR_COLOR")),  # no standard output
]

DEFAULT_TEXTURE = "/Engine/EngineResources/WhiteSquareTexture"


def _route_for(param_name):
    key = param_name.lower()
    for needle, routing in TEXTURE_ROUTING:
        if needle in key:
            return routing
    return (None, "RGB", "SAMPLERTYPE_COLOR")


def build_master(manifest, force):
    parent_path = manifest["ue"]["parent_material"]
    package_path, asset_name = parent_path.rsplit("/", 1)

    if unreal.EditorAssetLibrary.does_asset_exist(parent_path):
        if not force:
            print(f"Master already exists (pass --force to rebuild): {parent_path}")
            return parent_path
        unreal.EditorAssetLibrary.delete_asset(parent_path)

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = asset_tools.create_asset(
        asset_name, package_path, unreal.Material, unreal.MaterialFactoryNew()
    )
    if not material:
        raise RuntimeError(f"failed_to_create_material: {parent_path}")

    default_tex = unreal.load_asset(DEFAULT_TEXTURE)

    # --- Texture parameters ---
    y = -300
    for param_name in manifest["material_parameters"]["textures"].keys():
        prop_name, output_pin, sampler_name = _route_for(param_name)
        node = unreal.MaterialEditingLibrary.create_material_expression(
            material, unreal.MaterialExpressionTextureSampleParameter2D, -450, y
        )
        node.set_editor_property("parameter_name", param_name)
        try:
            node.set_editor_property("sampler_type", getattr(unreal.MaterialSamplerType, sampler_name))
        except Exception as exc:  # sampler enum names occasionally differ across versions
            print(f"  (warn) sampler_type {sampler_name} on {param_name}: {exc}")
        if default_tex:
            node.set_editor_property("texture", default_tex)

        if prop_name:
            wired = unreal.MaterialEditingLibrary.connect_material_property(
                node, output_pin, getattr(unreal.MaterialProperty, prop_name)
            )
            print(f"  texture {param_name} ({output_pin}) -> {prop_name}: {wired}")
        else:
            print(f"  texture {param_name}: added (not wired to a standard output)")
        y += 220

    # --- Scalar parameters (exposed for instance overrides / provenance) ---
    y = -300
    for name, value in manifest["material_parameters"].get("scalars", {}).items():
        s = unreal.MaterialEditingLibrary.create_material_expression(
            material, unreal.MaterialExpressionScalarParameter, -950, y
        )
        s.set_editor_property("parameter_name", name)
        try:
            s.set_editor_property("default_value", float(value))
        except Exception:
            pass
        print(f"  scalar {name} = {value}")
        y += 130

    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(parent_path)
    print(f"Saved master material: {parent_path}")
    return parent_path


def main():
    parser = argparse.ArgumentParser(description="Create the master material from a manifest.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--force", action="store_true", help="Rebuild even if it already exists.")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = Path(args.project_root).resolve() / manifest_path
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    build_master(manifest, args.force)


if __name__ == "__main__":
    main()
