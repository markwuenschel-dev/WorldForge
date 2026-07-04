#!/usr/bin/env python3
"""validate_external_asset_ownership.py — WorldForge v1.2 addendum ownership guard.

THE load-bearing external-asset lane (addendum §3/§6/§9). Megascans is a
THIRD-PARTY licensed library: every catalog record — and the library config block
itself — must resolve to third_party_owned, must NOT be generated_owned, must be
external_licensed with a recognised license family, and must be BOTH
repair_destroy_protected AND raw_asset_destroy_allowed=False. The most dangerous
bug in the whole intake is a source cache asset that lifecycle could treat as
generated output and destroy; this validator fails loudly (THIRD_PARTY_ASSET_DESTROY_RISK)
on any record where a source asset could be destroyed.

Usage:
    python tools/pipeline/validate_external_asset_ownership.py --lib megascans
    STRICT=1 python tools/pipeline/validate_external_asset_ownership.py --lib megascans --strict
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import asset_config
import external_asset_contract as EAC
import mesh_contract as MC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

COMMAND = "validate-external-asset-ownership"
REPORT_SUBDIR = "validate_external_asset_ownership"
REPORT_FILENAME = "validate_external_asset_ownership_report.json"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate external-asset ownership / license / destroy-protection.")
    ap.add_argument("--lib", default="megascans")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    catalog = EAC.load_external_catalog(REPO_ROOT)
    assets = catalog.get("assets") or {}
    ids = sorted(assets)

    rep = ValidationReport("library", args.lib, strict=strict)
    rep.check("catalog_non_empty", len(ids) > 0,
              "external catalog has {} record(s); expected >=1".format(len(ids)),
              code=FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE)

    # -- Library-level ownership guard (the whole cache is protected) -----------
    lib_block = asset_config.external_library(args.lib)
    rep.check("library_ownership_third_party",
              lib_block.get("ownership_class") == MC.OWNERSHIP_THIRD_PARTY,
              "library ownership_class={!r}, expected {!r}".format(
                  lib_block.get("ownership_class"), MC.OWNERSHIP_THIRD_PARTY),
              code=FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE)
    rep.check("library_not_generated_owned",
              lib_block.get("generated_owned") is False,
              "library generated_owned must be False (got {!r})".format(
                  lib_block.get("generated_owned")),
              code=FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE)
    rep.check("library_repair_destroy_protected",
              asset_config.is_repair_destroy_protected(args.lib) is True,
              "library must be repair_destroy_protected",
              code=FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE)

    # -- Per-record ownership / license / destroy-protection --------------------
    for aid in ids:
        rec = assets[aid] or {}

        # Ownership: explicit field AND resolver both say third_party_owned.
        oc = rec.get("ownership_class")
        resolved = MC.resolve_ownership_class(rec)
        rep.check("{}::ownership_class_third_party".format(aid),
                  oc == MC.OWNERSHIP_THIRD_PARTY and resolved == MC.OWNERSHIP_THIRD_PARTY,
                  "ownership_class={!r}, resolved={!r}, expected {!r}".format(
                      oc, resolved, MC.OWNERSHIP_THIRD_PARTY),
                  code=FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE)

        rep.check("{}::not_generated_owned".format(aid),
                  rec.get("generated_owned") is False,
                  "generated_owned must be False (got {!r})".format(rec.get("generated_owned")),
                  code=FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE)

        # License metadata.
        rep.check("{}::external_licensed".format(aid),
                  rec.get("external_licensed") is True,
                  "external_licensed must be True (got {!r})".format(rec.get("external_licensed")),
                  code=FailureCode.EXTERNAL_LICENSE_METADATA_FAILURE)
        lf = rec.get("license_family")
        rep.check("{}::license_family_known".format(aid),
                  bool(lf) and lf in EAC.LICENSE_FAMILIES,
                  "license_family={!r}; must be in {}".format(lf, EAC.LICENSE_FAMILIES),
                  code=FailureCode.EXTERNAL_LICENSE_METADATA_FAILURE)

        # Destroy-protection: a source asset must never be destroyable.
        rep.check("{}::repair_destroy_protected".format(aid),
                  rec.get("repair_destroy_protected") is True,
                  "repair_destroy_protected must be True (got {!r})".format(
                      rec.get("repair_destroy_protected")),
                  code=FailureCode.THIRD_PARTY_ASSET_DESTROY_RISK)
        rep.check("{}::raw_asset_destroy_disallowed".format(aid),
                  rec.get("raw_asset_destroy_allowed") is False,
                  "raw_asset_destroy_allowed must be False — a source asset could be destroyed (got {!r})".format(
                      rec.get("raw_asset_destroy_allowed")),
                  code=FailureCode.THIRD_PARTY_ASSET_DESTROY_RISK)

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
