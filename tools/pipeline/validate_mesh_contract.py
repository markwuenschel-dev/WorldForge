#!/usr/bin/env python3
"""validate_mesh_contract.py — WorldForge v1.2 mesh-contract validator (Agent 1 lane).

Validates that every generated mesh asset conforms to the v1.2 mesh contract
(brief §5): required fields present, no unknown fields in STRICT=1, family/source
taxonomy valid, ownership flags correct, final path shape sane, and the nested
material-bindings / bounds / rendering-budget blocks structurally complete. This
is the schema gate — deeper per-dimension checks live in the sibling validators
(paths, materials, collision, pcg, biome, budgets).

It reads the DESCRIPTORS produced by create_mesh_assets.py (the materialized
record), falling back to the definition YAML if a descriptor is absent. A single
--asset scopes to one asset; default validates the whole catalog.

Usage:
    python tools/pipeline/validate_mesh_contract.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_mesh_contract.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_mesh_contract/validate_mesh_contract_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def _load_record(asset_id, repo_root=REPO_ROOT):
    """Prefer the descriptor; fall back to the raw definition YAML."""
    desc = MC.mesh_descriptor_path(asset_id, repo_root)
    if desc.is_file():
        try:
            return json.loads(desc.read_text(encoding="utf-8")), None
        except Exception as exc:
            return None, "descriptor unparseable: {}".format(exc)
    data, err = MC.load_mesh_definition(MC.mesh_definition_path(asset_id, repo_root))
    return data, err


def check_asset(rep, asset_id, record, strict):
    """Run all contract checks for one asset, prefixing check names with the id."""
    def c(name, ok, detail="", code=FailureCode.MESH_CONTRACT_FAILURE, warn_only=False):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=code, warn_only=warn_only)

    # -- required fields ----------------------------------------------------
    missing = MC.missing_required_fields(record)
    c("required_fields_present", not missing,
      "missing/empty required fields: {}".format(missing))

    # -- unknown fields (strict only, brief §5 "unknown fields fail") -------
    unknown = MC.unknown_fields(record)
    c("no_unknown_fields", not unknown,
      "unknown top-level fields: {}".format(unknown),
      code=FailureCode.UNKNOWN_SCHEMA_FIELD, warn_only=not strict)

    # -- taxonomy -----------------------------------------------------------
    family = record.get("mesh_family")
    c("mesh_family_known", family in MC.MESH_FAMILIES,
      "mesh_family={}".format(family))
    source_type = record.get("source_type")
    c("source_type_known", source_type in MC.SOURCE_TYPES,
      "source_type={}".format(source_type), code=FailureCode.MESH_SOURCE_FAILURE)
    c("source_hash_present", bool(record.get("source_hash")),
      "source_hash missing", code=FailureCode.MESH_SOURCE_FAILURE)

    # -- ownership (brief §5 strict rules) ----------------------------------
    c("generated_owned_true", record.get("generated_owned") is True,
      "generated_owned={}".format(record.get("generated_owned")),
      code=FailureCode.MESH_OWNERSHIP_FAILURE)
    c("human_owned_false", record.get("human_owned") is False,
      "human_owned={}".format(record.get("human_owned")),
      code=FailureCode.MESH_OWNERSHIP_FAILURE)

    # -- final path shape (deep policy is validate_mesh_final_paths) ---------
    final_path = record.get("final_asset_path", "")
    c("final_path_present", bool(final_path), "final_asset_path missing",
      code=FailureCode.MESH_FINAL_PATH_FAILURE)

    # -- material bindings block --------------------------------------------
    bindings = record.get("material_bindings")
    if isinstance(bindings, list) and bindings:
        for i, b in enumerate(bindings):
            miss = [k for k in MC.MATERIAL_BINDING_REQUIRED if k not in (b or {})]
            c("material_binding_{}_complete".format(i), not miss,
              "binding {} missing keys: {}".format(i, miss),
              code=FailureCode.MESH_MATERIAL_BINDING_FAILURE)
    else:
        c("material_bindings_present", False, "material_bindings absent or empty",
          code=FailureCode.MESH_MATERIAL_BINDING_FAILURE)

    # -- bounds block -------------------------------------------------------
    bounds = record.get("bounds")
    if isinstance(bounds, dict):
        miss = [k for k in MC.BOUNDS_REQUIRED if k not in bounds]
        c("bounds_complete", not miss, "bounds missing keys: {}".format(miss),
          code=FailureCode.MESH_BOUNDS_FAILURE)
    else:
        c("bounds_present", False, "bounds absent", code=FailureCode.MESH_BOUNDS_FAILURE)

    # -- enumerations -------------------------------------------------------
    c("budget_class_valid", record.get("budget_class") in MC.BUDGET_CLASSES,
      "budget_class={}".format(record.get("budget_class")),
      code=FailureCode.MESH_RENDERING_BUDGET_FAILURE)
    c("pcg_eligibility_valid", record.get("pcg_eligibility") in MC.PCG_ELIGIBILITY_VALUES,
      "pcg_eligibility={}".format(record.get("pcg_eligibility")),
      code=FailureCode.MESH_PCG_ELIGIBILITY_FAILURE)
    biomes = record.get("biome_compatibility")
    c("biome_compatibility_declared", isinstance(biomes, list) and bool(biomes),
      "biome_compatibility={}".format(biomes),
      code=FailureCode.MESH_BIOME_COMPATIBILITY_FAILURE)
    if isinstance(biomes, list):
        bad = [b for b in biomes if b not in MC.BIOME_FAMILIES]
        c("biome_compatibility_known", not bad, "unknown biomes: {}".format(bad),
          code=FailureCode.MESH_BIOME_COMPATIBILITY_FAILURE)

    # -- pivot / scale policy -----------------------------------------------
    c("pivot_policy_valid", record.get("pivot_policy") in MC.PIVOT_POLICIES,
      "pivot_policy={}".format(record.get("pivot_policy")),
      code=FailureCode.MESH_PIVOT_FAILURE)
    c("scale_policy_valid", record.get("scale_policy") in MC.SCALE_POLICIES,
      "scale_policy={}".format(record.get("scale_policy")),
      code=FailureCode.MESH_SCALE_FAILURE)


def validate(pack, strict, asset=None):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    asset_ids = [asset] if asset else [aid for aid, _ in
                                       sorted((catalog.get("assets") or {}).items())]
    if not asset_ids:
        rep.error("no mesh assets found — run 'make create-mesh-assets' first")
        return rep, 0

    n = 0
    for aid in asset_ids:
        record, err = _load_record(aid)
        if record is None:
            rep.check("{}::record_loads".format(aid), False, err or "no record",
                      code=FailureCode.MESH_CONTRACT_FAILURE)
            continue
        check_asset(rep, aid, record, strict)
        n += 1
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate WorldForge v1.2 mesh contract.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--asset", default=None, help="Validate a single asset id")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict, asset=args.asset)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mesh-contract", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_mesh_contract"
    rep.write(report_dir, "validate_mesh_contract_report.json")
    rep.print_summary("validate-mesh-contract")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
