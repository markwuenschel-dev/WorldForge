#!/usr/bin/env python3
"""
generate_manifest.py
Produces a stable JSON manifest from a validated material recipe.
This is the contract handed to UE Python scripts.

The manifest carries a provenance block (git commit, dirty flag, timestamp,
generator identity, input hashes) stamped here at generation time. Provenance is
recorded honestly: a dirty input tree is flagged, never hidden (see
forge_design_decisions D4). Use --strict to hard-fail on dirty inputs (CI/agents).
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

from provenance import build_provenance

# The export lane writes this sidecar naming the tool that produced the PNGs.
# Without it a stopgap render and a real Substance render are byte-
# indistinguishable at these paths, and the manifest cannot tell them apart.
# Absent => no synthesis block => validate_generative_sources reports WF023.
SYNTHESIS_SIDECAR = "_synthesis.json"


def read_synthesis(repo_root, manifest_exports):
    """Read the producer sidecar sitting beside the exports, if the lane wrote one.

    Returns None when absent -- deliberately NOT a default block. A fabricated
    "unknown producer" entry would satisfy the shape of the question while
    answering none of it, which is the failure mode this whole field exists to
    close.
    """
    for info in manifest_exports.values():
        sidecar = (repo_root / info["source_file"]).parent / SYNTHESIS_SIDECAR
        if sidecar.is_file():
            try:
                data = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception:
                return None
            return {
                "producer": data.get("producer"),
                "producer_version": data.get("producer_version"),
                "mode": data.get("mode"),
                "is_stopgap": data.get("is_stopgap"),
                "recorded_at_utc": data.get("generated_at_utc"),
                "sidecar": sidecar.relative_to(repo_root).as_posix(),
            }
        break
    return None

GENERATOR_NAME = "worldforge-generate-manifest"
GENERATOR_VERSION = "1.0.0"

REPO_ROOT = Path(__file__).parent.parent.parent

# Explicit mapping to avoid bad names like Base_colorTexture
TEXTURE_PARAMETER_NAMES = {
    "base_color": "BaseColorTexture",
    "normal": "NormalTexture",
    "roughness": "RoughnessTexture",
    "ambient_occlusion": "AOTexture",
    "height": "HeightTexture",
}


def derive_data_asset_path(ue: dict) -> str:
    """Manifest owns the Data Asset output path (D5).

    Use ue.data_asset_path if the recipe specifies it; otherwise derive it next
    to the Material Instance by swapping the MI_ prefix for DA_.
    """
    explicit = ue.get("data_asset_path")
    if explicit:
        return explicit
    instance_path = ue.get("instance_path", "")
    package, name = instance_path.rsplit("/", 1)
    if name.startswith("MI_"):
        name = "DA_" + name[len("MI_"):]
    else:
        name = "DA_" + name
    return f"{package}/{name}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", required=True)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Hard-fail if the source inputs are dirty (uncommitted). For CI/agents.",
    )
    args = parser.parse_args()

    recipes_dir = REPO_ROOT / "procedural" / "substance" / "recipes"
    recipe_path = recipes_dir / f"{args.recipe}.yaml"

    if not recipe_path.exists():
        print(f"ERROR: Recipe not found: {recipe_path}", file=sys.stderr)
        sys.exit(1)

    with open(recipe_path, "r", encoding="utf-8") as f:
        recipe = yaml.safe_load(f)

    for key in ["id", "schema_version", "graph", "resolution", "outputs", "ue"]:
        if key not in recipe:
            print(f"ERROR: Missing required key '{key}'", file=sys.stderr)
            sys.exit(1)

    ue = recipe["ue"]
    outputs = recipe["outputs"]
    texture_folder = ue.get("texture_folder", "Textures/Terrain")

    graph_path = REPO_ROOT / "procedural" / "substance" / "graphs" / recipe["graph"]
    provenance = build_provenance(
        REPO_ROOT, [recipe_path, graph_path], GENERATOR_NAME, GENERATOR_VERSION
    )

    if provenance["source_tree_dirty"]:
        msg = (
            f"Source inputs are dirty (uncommitted) for recipe '{recipe['id']}'. "
            "Provenance will record source_tree_dirty=true."
        )
        if args.strict:
            print(f"ERROR (--strict): {msg}", file=sys.stderr)
            sys.exit(2)
        print(f"WARNING: {msg}", file=sys.stderr)

    manifest = {
        "recipe_id": recipe["id"],
        "schema_version": recipe["schema_version"],
        "graph": recipe["graph"],
        "resolution": recipe["resolution"],
        "source_recipe": recipe_path.relative_to(REPO_ROOT).as_posix(),
        "substance_graph_path": (Path("procedural/substance/graphs") / recipe["graph"]).as_posix(),
        "provenance": provenance,
        # Stamped after exports are resolved, from the export lane's sidecar.
        "synthesis": None,
        "exports": {},
        "ue": {
            "parent_material": ue.get("parent_material"),
            "instance_path": ue.get("instance_path"),
            "texture_folder": f"/Game/{texture_folder}",
            "generate_data_asset": ue.get("generate_data_asset", False),
            "data_asset_class": ue.get("data_asset_class"),
            "data_asset_path": derive_data_asset_path(ue),
        },
        "material_parameters": {
            "textures": {},
            "scalars": recipe.get("parameters", {}),
            "vectors": {}
        }
    }

    for tex_type, tex_name in outputs.items():
        source_file = f"procedural/substance/exports/{args.recipe}/{tex_name}.png"
        ue_asset_path = f"/Game/{texture_folder}/{tex_name}"

        manifest["exports"][tex_type] = {
            "name": tex_name,
            "source_file": source_file,
            "ue_asset_path": ue_asset_path,
            "srgb": tex_type == "base_color",
            "compression": ue.get("compression", {}).get(tex_type, ue.get("compression", {}).get("masks", "Default")),
            "texture_group": ue.get("texture_group", "World")
        }

        param_name = TEXTURE_PARAMETER_NAMES.get(tex_type, f"{tex_type}Texture")
        manifest["material_parameters"]["textures"][param_name] = ue_asset_path

    # Who actually produced the PNGs this manifest points at. Read from the
    # export lane's sidecar; left None when the lane recorded nothing, so the
    # gap is visible in the manifest instead of being papered over.
    manifest["synthesis"] = read_synthesis(REPO_ROOT, manifest["exports"])
    if manifest["synthesis"] is None:
        print("WARNING: no export producer sidecar found; manifest records "
              "synthesis=null and validate_generative_sources will report "
              "WF023 for this recipe", file=sys.stderr)

    manifests_dir = REPO_ROOT / "procedural" / "manifests" / "materials"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    output_path = manifests_dir / f"{args.recipe}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated manifest: {output_path}")


if __name__ == "__main__":
    main()
