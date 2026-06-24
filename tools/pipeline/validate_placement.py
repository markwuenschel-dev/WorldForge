#!/usr/bin/env python3
"""
validate_placement.py
Validates a FoliageSpawnRules definition YAML against placement_rules_contract.md
(PlacementForge, forge_design_decisions D13).

Mirrors validate_recipe.py: strict schema, whitelisted fields, performance-budget
caps, and an agent-safe state-key whitelist. Adding a new state key or raising a
budget requires a human contract update (Tier 2), exactly like adding a material
graph parameter.

Usage:
    python tools/pipeline/validate_placement.py --definition reclaimed_desert_foliage
    python tools/pipeline/validate_placement.py --definition-path tests/fixtures/invalid_placement/bad.yaml
    python tools/pipeline/validate_placement.py --all
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

REQUIRED_TOP_LEVEL_KEYS = ["schema_version", "id", "pcg_graph", "biome", "species", "ue"]

REQUIRED_SPECIES_KEYS = ["id", "mesh", "base_density", "scale_min", "scale_max"]
OPTIONAL_SPECIES_KEYS = ["state_scope", "state_key", "density_at_state_zero", "density_at_state_one"]

REQUIRED_UE_KEYS = ["data_asset_class", "generate_data_asset"]
OPTIONAL_UE_KEYS = ["data_asset_path"]

VALID_STATE_SCOPES = {"Global", "Region", "Local", "Settlement"}

# Agent-safe state-key whitelist. Mirrors the curated world-state keys
# (UWorldStateSubsystem::GetCuratedMpcParams) plus "none" for unmodulated species.
# Expanding this requires a human contract update (Tier 2).
KNOWN_STATE_KEYS = {
    "industrial_pressure",
    "corruption_level",
    "restoration_level",
    "wetness",
    "ashfall",
    "none",
}

# --- Performance budgets (see docs/validation/performance_budgets.md) ---
MAX_SPECIES = 12
MAX_BASE_DENSITY = 50.0          # target instances per 100 m^2
MAX_DENSITY_MULTIPLIER = 5.0     # density_at_state_* ceiling
MAX_SCALE = 100.0


def load_definition(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _validate_species(species: List[Any], errors: List[str]) -> None:
    if not isinstance(species, list) or not species:
        errors.append("species must be a non-empty list")
        return

    if len(species) > MAX_SPECIES:
        errors.append(f"too many species: {len(species)} > {MAX_SPECIES}")

    seen_ids = set()
    for i, entry in enumerate(species):
        where = f"species[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{where} must be an object/map")
            continue

        missing = set(REQUIRED_SPECIES_KEYS) - set(entry.keys())
        if missing:
            errors.append(f"{where} missing required keys: {missing}")
        unknown = set(entry.keys()) - set(REQUIRED_SPECIES_KEYS) - set(OPTIONAL_SPECIES_KEYS)
        if unknown:
            errors.append(f"{where} unknown keys: {unknown}")

        sid = entry.get("id")
        if not isinstance(sid, str) or not sid:
            errors.append(f"{where} id must be a non-empty string")
        elif sid in seen_ids:
            errors.append(f"{where} duplicate species id: '{sid}'")
        else:
            seen_ids.add(sid)

        mesh = entry.get("mesh", "")
        if not isinstance(mesh, str) or not mesh.startswith("/Game/"):
            errors.append(f"{where} mesh must be a /Game/ path (got {mesh!r})")

        base_density = entry.get("base_density")
        if not isinstance(base_density, (int, float)):
            errors.append(f"{where} base_density must be a number")
        elif not (0.0 < base_density <= MAX_BASE_DENSITY):
            errors.append(f"{where} base_density out of range (0, {MAX_BASE_DENSITY}] (got {base_density})")

        smin = entry.get("scale_min")
        smax = entry.get("scale_max")
        for key, val in (("scale_min", smin), ("scale_max", smax)):
            if not isinstance(val, (int, float)):
                errors.append(f"{where} {key} must be a number")
            elif not (0.0 < val <= MAX_SCALE):
                errors.append(f"{where} {key} out of range (0, {MAX_SCALE}] (got {val})")
        if isinstance(smin, (int, float)) and isinstance(smax, (int, float)) and smin > smax:
            errors.append(f"{where} scale_min ({smin}) must be <= scale_max ({smax})")

        scope = entry.get("state_scope", "Region")
        if scope not in VALID_STATE_SCOPES:
            errors.append(f"{where} state_scope must be one of {sorted(VALID_STATE_SCOPES)} (got {scope})")

        state_key = entry.get("state_key", "none")
        if state_key not in KNOWN_STATE_KEYS:
            errors.append(
                f"{where} state_key '{state_key}' is not on the allowed list "
                f"{sorted(KNOWN_STATE_KEYS)} (contract update required to add one)"
            )

        for key in ("density_at_state_zero", "density_at_state_one"):
            if key in entry:
                v = entry[key]
                if not isinstance(v, (int, float)):
                    errors.append(f"{where} {key} must be a number")
                elif not (0.0 <= v <= MAX_DENSITY_MULTIPLIER):
                    errors.append(f"{where} {key} out of range [0, {MAX_DENSITY_MULTIPLIER}] (got {v})")


def validate_definition(definition: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    if not isinstance(definition, dict):
        return ["top-level document must be a YAML mapping"]

    if definition.get("schema_version") != "1.1":
        errors.append(f"schema_version must be exactly \"1.1\" (got {definition.get('schema_version')})")

    unknown_top = set(definition.keys()) - set(REQUIRED_TOP_LEVEL_KEYS)
    if unknown_top:
        errors.append(f"Unknown top-level keys: {unknown_top}")

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in definition:
            errors.append(f"Missing required top-level key: '{key}'")

    if errors:
        return errors  # Early exit on critical structural issues

    if not isinstance(definition.get("id"), str):
        errors.append("id must be a string")
    if not isinstance(definition.get("biome"), str):
        errors.append("biome must be a string")

    pcg_graph = definition.get("pcg_graph", "")
    if not isinstance(pcg_graph, str) or not pcg_graph.startswith("/Game/"):
        errors.append("pcg_graph must be a /Game/ path to the human-owned PCG template")

    _validate_species(definition.get("species"), errors)

    ue = definition.get("ue", {})
    if not isinstance(ue, dict):
        errors.append("ue must be an object/map")
    else:
        missing_ue = set(REQUIRED_UE_KEYS) - set(ue.keys())
        if missing_ue:
            errors.append(f"Missing required ue keys: {missing_ue}")
        unknown_ue = set(ue.keys()) - set(REQUIRED_UE_KEYS) - set(OPTIONAL_UE_KEYS)
        if unknown_ue:
            errors.append(f"Unknown ue keys: {unknown_ue}")
        if ue.get("data_asset_class") != "PlacementRulesDataAsset":
            errors.append("ue.data_asset_class must be 'PlacementRulesDataAsset'")
        if "generate_data_asset" in ue and not isinstance(ue["generate_data_asset"], bool):
            errors.append("ue.generate_data_asset must be a boolean")
        da_path = ue.get("data_asset_path")
        if da_path is not None and not str(da_path).startswith("/Game/"):
            errors.append("ue.data_asset_path must start with /Game/")

    return errors


def _report(name: str, errors: List[str]) -> bool:
    # ASCII-only output: stays deterministic when piped on a Windows cp1252 console,
    # so the negative-test subprocess can't crash-and-look-like-a-rejection.
    if errors:
        print(f"FAIL: validation failed for {name}")
        for e in errors:
            print(f"   - {e}")
        return False
    print(f"OK: {name} is valid")
    return True


def main():
    parser = argparse.ArgumentParser(description="Validate FoliageSpawnRules definition YAML files")
    parser.add_argument("--definition", help="Definition name without .yaml (e.g. reclaimed_desert_foliage)")
    parser.add_argument("--definition-path", help="Path to an arbitrary definition YAML (e.g. a test fixture)")
    parser.add_argument("--all", action="store_true", help="Validate all definitions in the placement folder")
    args = parser.parse_args()

    definitions_dir = Path(__file__).parent.parent.parent / "procedural" / "definitions" / "placement"

    if args.definition_path:
        path = Path(args.definition_path)
        if not path.exists():
            print(f"Definition not found: {path}")
            sys.exit(1)
        ok = _report(path.name, validate_definition(load_definition(path)))
        sys.exit(0 if ok else 1)

    if args.all:
        files = sorted(definitions_dir.glob("*.yaml"))
        if not files:
            print("No definition files found.")
            return
        all_passed = True
        for f in files:
            if not _report(f.name, validate_definition(load_definition(f))):
                all_passed = False
        print("\nValidation complete." if all_passed else "\nSome definitions failed validation.")
        sys.exit(0 if all_passed else 1)

    if args.definition:
        path = definitions_dir / f"{args.definition}.yaml"
        if not path.exists():
            print(f"Definition not found: {path}")
            sys.exit(1)
        ok = _report(f"{args.definition}.yaml", validate_definition(load_definition(path)))
        sys.exit(0 if ok else 1)

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
