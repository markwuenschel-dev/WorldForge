#!/usr/bin/env python3
"""validate_megascans_catalog.py — WorldForge v1.2 addendum Megascans catalog rules.

Megascans-specific catalog lane (addendum §6 strict rules). Where
validate_external_asset_catalog covers generic external-catalog integrity, this
validator enforces the Megascans-library shape every record must have: it is a
megascans_library record, biome-compatible against the v1.1 biome families,
PCG-classified, and — critically — carries a package_policy that only permits
INCORPORATED project content (never a standalone raw redistributable pack). Deep
per-biome environment checks are owned by the biome lane; here biome_compatibility
must merely be non-empty and drawn from the known families.

Usage:
    python tools/pipeline/validate_megascans_catalog.py --lib megascans
    STRICT=1 python tools/pipeline/validate_megascans_catalog.py --lib megascans --strict
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import external_asset_contract as EAC
import mesh_contract as MC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

COMMAND = "validate-megascans-catalog"
REPORT_SUBDIR = "validate_megascans_catalog"
REPORT_FILENAME = "validate_megascans_catalog_report.json"

CODE = FailureCode.MEGASCANS_CATALOG_FAILURE


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate Megascans-specific catalog rules.")
    ap.add_argument("--lib", default="megascans")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    catalog = EAC.load_external_catalog(REPO_ROOT)
    assets = catalog.get("assets") or {}
    ids = sorted(assets)

    rep = ValidationReport("library", args.lib, strict=strict)
    rep.check("catalog_non_empty", len(ids) > 0,
              "megascans catalog has {} record(s); expected >=1".format(len(ids)),
              code=CODE)

    for aid in ids:
        rec = assets[aid] or {}

        rep.check("{}::source_type_megascans_library".format(aid),
                  rec.get("source_type") == "megascans_library",
                  "source_type={!r}, expected 'megascans_library'".format(rec.get("source_type")),
                  code=CODE)
        rep.check("{}::library_id_megascans".format(aid),
                  rec.get("library_id") == "megascans",
                  "library_id={!r}, expected 'megascans'".format(rec.get("library_id")),
                  code=CODE)
        rep.check("{}::asset_name_present".format(aid),
                  bool(rec.get("asset_name")),
                  "asset_name missing", code=CODE)
        rep.check("{}::asset_type_present".format(aid),
                  bool(rec.get("asset_type")),
                  "asset_type missing", code=CODE)
        rep.check("{}::asset_category_present".format(aid),
                  bool(rec.get("asset_category")),
                  "asset_category missing", code=CODE)

        # biome_compatibility non-empty and all within the known biome families.
        biomes = rec.get("biome_compatibility")
        biomes_ok = (isinstance(biomes, list) and len(biomes) > 0
                     and all(b in MC.BIOME_FAMILIES for b in biomes))
        rep.check("{}::biome_compatibility_valid".format(aid), biomes_ok,
                  "biome_compatibility={!r}; must be non-empty and in {}".format(
                      biomes, MC.BIOME_FAMILIES),
                  code=CODE)

        rep.check("{}::pcg_eligibility_present".format(aid),
                  bool(rec.get("pcg_eligibility")),
                  "pcg_eligibility missing", code=CODE)

        # package_policy present, complete, and incorporated-only.
        pp = rec.get("package_policy")
        pp_ok = isinstance(pp, dict)
        rep.check("{}::package_policy_present".format(aid), pp_ok,
                  "package_policy missing or not an object", code=CODE)
        if pp_ok:
            pp_missing = [k for k in EAC.PACKAGE_POLICY_REQUIRED if k not in pp]
            rep.check("{}::package_policy_complete".format(aid), not pp_missing,
                      "package_policy missing keys: {}".format(pp_missing), code=CODE)
            rep.check("{}::package_usage_incorporated".format(aid),
                      pp.get("package_usage") == EAC.PACKAGE_USAGE_INCORPORATED,
                      "package_usage={!r}, expected {!r}".format(
                          pp.get("package_usage"), EAC.PACKAGE_USAGE_INCORPORATED),
                      code=CODE)

        rep.check("{}::provenance_record_present".format(aid),
                  bool(rec.get("provenance_record")),
                  "provenance_record missing", code=CODE)
        rep.check("{}::catalog_record_present".format(aid),
                  bool(rec.get("catalog_record")),
                  "catalog_record missing", code=CODE)

    rep.finalize()
    rep.set_meta(build_meta(command=COMMAND, pack=args.lib, strict=strict,
                            status=rep.status, record_count=len(ids),
                            output_manifest_hash=EAC.external_catalog_content_hash(catalog)))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / REPORT_SUBDIR
    rep.write(report_dir, REPORT_FILENAME)
    rep.print_summary(COMMAND)
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
