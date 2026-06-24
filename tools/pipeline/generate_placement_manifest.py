#!/usr/bin/env python3
"""
generate_placement_manifest.py
Produces a stable JSON manifest from a validated FoliageSpawnRules definition.
This is the contract handed to the UE Python step (create_placement_data_asset.py).

PlacementForge mirrors MaterialForge's recipe->manifest->DataAsset->validate
contract (forge_design_decisions D13). The manifest carries the same honest
provenance block (git commit, dirty flag, timestamp, generator identity, input
hash) as the material lane, stamped here via the shared provenance helper.

Use --strict to hard-fail on dirty inputs (CI/agents).
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

from provenance import build_provenance

GENERATOR_NAME = "worldforge-generate-placement-manifest"
GENERATOR_VERSION = "1.0.0"

REPO_ROOT = Path(__file__).parent.parent.parent
DEFINITIONS_DIR = REPO_ROOT / "procedural" / "definitions" / "placement"
MANIFESTS_DIR = REPO_ROOT / "procedural" / "manifests" / "placement"

SPECIES_FIELDS = (
    "id", "mesh", "base_density", "scale_min", "scale_max",
    "state_scope", "state_key", "density_at_state_zero", "density_at_state_one",
)


def derive_data_asset_path(ue: dict, definition_id: str) -> str:
    """Manifest owns the Data Asset output path (mirrors D5).

    Use ue.data_asset_path if specified; otherwise derive a default under
    /Game/Procedural/Placement from the definition id.
    """
    explicit = ue.get("data_asset_path")
    if explicit:
        return explicit
    parts = "".join(w.capitalize() for w in definition_id.split("_"))
    return f"/Game/Procedural/Placement/DA_{parts}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--definition", required=True,
                        help="Definition name without .yaml (e.g. reclaimed_desert_foliage)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Hard-fail if the source inputs are dirty (uncommitted). For CI/agents.",
    )
    args = parser.parse_args()

    def_path = DEFINITIONS_DIR / f"{args.definition}.yaml"
    if not def_path.exists():
        print(f"ERROR: Definition not found: {def_path}", file=sys.stderr)
        sys.exit(1)

    with open(def_path, "r", encoding="utf-8") as f:
        definition = yaml.safe_load(f)

    for key in ["id", "schema_version", "species", "ue"]:
        if key not in definition:
            print(f"ERROR: Missing required key '{key}'", file=sys.stderr)
            sys.exit(1)

    ue = definition["ue"]
    provenance = build_provenance(REPO_ROOT, [def_path], GENERATOR_NAME, GENERATOR_VERSION)

    if provenance["source_tree_dirty"]:
        msg = (
            f"Source inputs are dirty (uncommitted) for definition '{definition['id']}'. "
            "Provenance will record source_tree_dirty=true."
        )
        if args.strict:
            print(f"ERROR (--strict): {msg}", file=sys.stderr)
            sys.exit(2)
        print(f"WARNING: {msg}", file=sys.stderr)

    species = []
    for entry in definition["species"]:
        species.append({
            "id": entry["id"],
            "mesh": entry["mesh"],
            "base_density": float(entry["base_density"]),
            "scale_min": float(entry["scale_min"]),
            "scale_max": float(entry["scale_max"]),
            "state_scope": entry.get("state_scope", "Region"),
            "state_key": entry.get("state_key", "none"),
            "density_at_state_zero": float(entry.get("density_at_state_zero", 1.0)),
            "density_at_state_one": float(entry.get("density_at_state_one", 1.0)),
        })

    manifest = {
        "definition_id": definition["id"],
        "schema_version": definition["schema_version"],
        "biome": definition.get("biome", ""),
        "pcg_graph": definition.get("pcg_graph", ""),
        "source_definition": def_path.relative_to(REPO_ROOT).as_posix(),
        "provenance": provenance,
        "ue": {
            "data_asset_path": derive_data_asset_path(ue, definition["id"]),
            "data_asset_class": ue.get("data_asset_class", "PlacementRulesDataAsset"),
            "generate_data_asset": ue.get("generate_data_asset", False),
        },
        "species": species,
    }

    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MANIFESTS_DIR / f"{args.definition}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated manifest: {output_path}")


if __name__ == "__main__":
    main()
