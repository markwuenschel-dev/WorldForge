#!/usr/bin/env python3
r"""
validate_placement_assets.py (UE5 Python)

Tier-3 generated-asset validation for PlacementForge (forge_design_decisions D6,
D13): correctness of the UPlacementRulesDataAsset a definition produced - class,
naming, provenance linkage, staleness, density budgets, and reference integrity of
the scattered meshes.

Manifest-driven, with report output. Exits non-zero on any error. Missing meshes
are WARNINGS, not errors: WorldForge is the tooling layer (not the game), so the
actual foliage meshes live in the consuming project (see README).
"""

import argparse
import json
from pathlib import Path

import unreal

MAX_BASE_DENSITY = 50.0
MAX_DENSITY_MULTIPLIER = 5.0


def _short_name(object_path: str) -> str:
    return object_path.split(".")[0].rsplit("/", 1)[-1]


def _soft_path_str(soft) -> str:
    """Best-effort extraction of a /Game/... path string from a SoftObjectPath."""
    s = str(soft).strip()
    # SoftObjectPath str can include a class wrapper; keep the /Game asset path.
    if "'" in s:
        s = s.split("'")[-2] if s.count("'") >= 2 else s
    return s.split(".")[0]


def validate_data_asset(manifest: dict, errors: list, warnings: list):
    ue = manifest["ue"]
    if not ue.get("generate_data_asset", False):
        return

    da_path = ue.get("data_asset_path")
    if not da_path:
        errors.append({"category": "missing_data_asset_path",
                       "message": "manifest ue.data_asset_path is required"})
        return

    da = unreal.EditorAssetLibrary.load_asset(da_path)
    if not da:
        errors.append({"category": "missing_data_asset", "message": da_path})
        return

    if not isinstance(da, unreal.PlacementRulesDataAsset):
        errors.append({"category": "data_asset_wrong_class", "message": da_path})
        return

    if not _short_name(da_path).startswith("DA_"):
        errors.append({"category": "naming_violation",
                       "message": f"data asset not DA_-prefixed: {da_path}"})

    if str(da.get_editor_property("rules_id")) != manifest["definition_id"]:
        errors.append({"category": "data_asset_provenance_mismatch", "message": "rules_id mismatch"})

    # Rules integrity: species count matches the manifest.
    species = da.get_editor_property("species")
    expected = manifest.get("species", [])
    if len(species) != len(expected):
        errors.append({"category": "data_asset_linkage_failure",
                       "message": f"species count {len(species)} != {len(expected)}"})

    # Density budget (defensive re-check) + reference integrity of scattered meshes.
    for rule in species:
        sid = str(rule.get_editor_property("species_id"))
        bd = float(rule.get_editor_property("base_density"))
        if not (0.0 < bd <= MAX_BASE_DENSITY):
            errors.append({"category": "placement_budget_exceeded",
                           "message": f"{sid} base_density {bd} out of (0, {MAX_BASE_DENSITY}]"})
        for prop in ("density_at_state_zero", "density_at_state_one"):
            v = float(rule.get_editor_property(prop))
            if not (0.0 <= v <= MAX_DENSITY_MULTIPLIER):
                errors.append({"category": "placement_budget_exceeded",
                               "message": f"{sid} {prop} {v} out of [0, {MAX_DENSITY_MULTIPLIER}]"})

        mesh_path = _soft_path_str(rule.get_editor_property("mesh"))
        if mesh_path and not unreal.EditorAssetLibrary.does_asset_exist(mesh_path):
            warnings.append({"category": "mesh_reference_unresolved",
                             "message": f"{sid} mesh not found in this project: {mesh_path}"})

    # Provenance copied verbatim from the manifest.
    prov = manifest.get("provenance", {})
    for da_field, prov_key in (
        ("source_commit", "source_commit"),
        ("generated_at_utc", "generated_at_utc"),
        ("generator_name", "generator_name"),
    ):
        if str(da.get_editor_property(da_field)) != str(prov.get(prov_key, "")):
            errors.append({"category": "data_asset_provenance_mismatch",
                           "message": f"{da_field} does not match manifest provenance"})

    # Staleness: recorded hash must match the manifest's current input hash.
    source_definition = manifest.get("source_definition", "")
    expected_hash = prov.get("inputs", {}).get(source_definition, "")
    if str(da.get_editor_property("source_recipe_hash")) != str(expected_hash):
        errors.append({"category": "stale_provenance",
                       "message": "source_recipe_hash does not match manifest (regenerate)"})


def validate(manifest: dict):
    errors = []
    warnings = []
    validate_data_asset(manifest, errors, warnings)
    return {
        "status": "ok" if not errors else "failed",
        "definition_id": manifest["definition_id"],
        "errors": errors,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    result = validate(manifest)

    report_dir = root / "procedural/reports/placement" / manifest["definition_id"]
    report_dir.mkdir(parents=True, exist_ok=True)
    with open(report_dir / "asset_validation_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))

    if result["status"] != "ok":
        raise RuntimeError("Validation failed")


if __name__ == "__main__":
    main()
