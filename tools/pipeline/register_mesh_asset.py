#!/usr/bin/env python3
"""register_mesh_asset.py — WorldForge v1.2 single mesh-asset intake gate.

The source-agnostic choke-point: any source (internal recipe, UE script, imported
stub, Blender, Houdini) ultimately produces a mesh-asset DEFINITION; this gate is
what earns that definition WorldForge ownership. It runs the load-bearing intake
refusals BEFORE writing anything, then materializes the descriptor + catalog
record. It refuses (non-zero exit, no catalog mutation) when:

  * a required contract field is missing (brief §5)
  * an unknown top-level field is present (STRICT=1)
  * final_asset_path is a forbidden Temp/Bake/plugin/human-owned path (brief §6)
  * final_asset_path is not under a WorldForge-owned generated root
  * generated_owned is not True or human_owned is not False (brief §6)
  * mesh_family / source_type are outside the frozen taxonomy
  * source_hash is absent

This mirrors register_generated_asset.py and is the target of the v1.2 negative
fixture harness (tests/fixtures/invalid_mesh_assets/*.yaml must all be REJECTED).

Usage:
    python tools/pipeline/register_mesh_asset.py --asset mesh_rock_desert_eroded_rock
    python tools/pipeline/register_mesh_asset.py --definition-path <fixture.yaml> [--strict]
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC
from mesh_catalog import (
    compute_catalog_input_hash, load_mesh_catalog, save_mesh_catalog,
    upsert_catalog_entry,
)
from provenance import build_provenance
from validation_report import strict_from_env

GENERATOR_NAME = "register_mesh_asset"
GENERATOR_VERSION = "1.2.0"


def _refuse(msg):
    sys.stderr.write("ERROR: {}\n".format(msg))
    return 1


def register(definition, def_path, strict):
    """Run refusals; on success write descriptor + catalog entry. Return exit code."""
    asset_id = definition.get("asset_id")
    if not asset_id:
        return _refuse("definition has no asset_id")

    # -- hard contract refusals (no writes before these pass) ---------------
    missing = MC.missing_required_fields(definition)
    if missing:
        return _refuse("{}: missing required field(s): {}".format(asset_id, missing))
    if strict:
        unknown = MC.unknown_fields(definition)
        if unknown:
            return _refuse("{}: unknown field(s) in STRICT mode: {}".format(asset_id, unknown))
    if definition.get("mesh_family") not in MC.MESH_FAMILIES:
        return _refuse("{}: unknown mesh_family {}".format(asset_id, definition.get("mesh_family")))
    if definition.get("source_type") not in MC.SOURCE_TYPES:
        return _refuse("{}: unknown source_type {}".format(asset_id, definition.get("source_type")))
    if not definition.get("source_hash"):
        return _refuse("{}: source_hash missing".format(asset_id))
    if definition.get("generated_owned") is not True:
        return _refuse("{}: generated_owned must be true".format(asset_id))
    if definition.get("human_owned") is not False:
        return _refuse("{}: human_owned must be false".format(asset_id))

    final_path = definition.get("final_asset_path", "")
    if MC.is_forbidden_final_path(final_path):
        return _refuse("{}: forbidden final path (Temp/Bake/plugin/human-owned): {}".format(
            asset_id, final_path))
    if not MC.is_allowed_final_path(final_path):
        return _refuse("{}: final path must be under a WorldForge-owned generated root: {}".format(
            asset_id, final_path))

    # -- materialize --------------------------------------------------------
    out_dir = Path(REPO_ROOT) / MC.MESH_GENERATED_REL / asset_id
    out_dir.mkdir(parents=True, exist_ok=True)
    prov = build_provenance(Path(REPO_ROOT), [def_path], GENERATOR_NAME, GENERATOR_VERSION)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    descriptor = dict(definition)
    descriptor["definition_path"] = Path(def_path).resolve().relative_to(REPO_ROOT).as_posix() \
        if str(Path(def_path).resolve()).startswith(str(REPO_ROOT)) else str(def_path)
    descriptor["descriptor_path"] = (out_dir / "descriptor.json").relative_to(REPO_ROOT).as_posix()
    descriptor["generated_at_utc"] = now_iso
    descriptor["provenance"] = prov
    descriptor["provenance_id"] = "prov_{}".format(asset_id)
    descriptor["registry_id"] = "mesh_catalog:{}".format(asset_id)
    descriptor["registry_owner"] = "worldforge_mesh_catalog"

    with (out_dir / "descriptor.json").open("w", encoding="utf-8") as fh:
        json.dump(descriptor, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    catalog = load_mesh_catalog(REPO_ROOT)
    entry = {
        "asset_id": asset_id,
        "mesh_family": definition["mesh_family"],
        "source_type": definition["source_type"],
        "final_asset_path": final_path,
        "registry_id": descriptor["registry_id"],
        "provenance_id": descriptor["provenance_id"],
        "biome_compatibility": definition.get("biome_compatibility", []),
        "poi_compatibility": definition.get("poi_compatibility", []),
        "pcg_eligibility": definition.get("pcg_eligibility"),
        "placement_tags": (definition.get("placement_compatibility") or {}).get(
            "allowed_placement_profiles", []),
        "material_bindings": definition.get("material_bindings", []),
        "collision_profile": definition.get("collision_profile"),
        "bounds": definition.get("bounds"),
        "budget_class": definition.get("budget_class"),
        "package_status": "pending",
        "validation_status": "pending",
        "lifecycle_status": "created",
        "descriptor_path": descriptor["descriptor_path"],
        "source_hash": definition["source_hash"],
    }
    entry["input_hash"] = compute_catalog_input_hash(entry)
    catalog = upsert_catalog_entry(catalog, entry)
    save_mesh_catalog(REPO_ROOT, catalog)
    print("[register-mesh-asset] registered {} -> {}".format(asset_id, final_path))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Register one WorldForge-owned generated mesh asset.")
    ap.add_argument("--asset", help="Asset id (procedural/definitions/mesh_assets/<id>.yaml)")
    ap.add_argument("--definition-path", help="Explicit definition YAML (overrides --asset).")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    if args.definition_path:
        def_path = Path(args.definition_path)
    elif args.asset:
        def_path = MC.mesh_definition_path(args.asset)
    else:
        ap.error("one of --asset or --definition-path is required")

    definition, err = MC.load_mesh_definition(def_path)
    if definition is None:
        return _refuse(err or "definition unloadable")
    return register(definition, def_path, strict)


if __name__ == "__main__":
    sys.exit(main())
