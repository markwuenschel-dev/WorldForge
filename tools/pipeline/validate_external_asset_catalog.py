#!/usr/bin/env python3
"""validate_external_asset_catalog.py — WorldForge v1.2 addendum external-catalog integrity.

Catalog-integrity lane (addendum §7) for the THIRD-PARTY external asset catalog
(procedural/generated/worldforge_external_asset_catalog.json). This validator does
NOT re-scan the source cache; it audits the committed catalog itself: it must be
non-empty, every record must carry the full external-asset field taxonomy, no
record may claim generated_owned, and — the load-bearing check — no record's
committed ``source_path`` may leak an absolute machine path. A leaked absolute
path (a drive-letter colon ``X:\\...`` or a UNC ``\\\\host`` lead) means
the intake wrote a machine-specific, non-portable, potentially destroy-targetable
path into the ledger, which is a MEGASCANS_CATALOG_FAILURE.

Usage:
    python tools/pipeline/validate_external_asset_catalog.py --lib megascans
    STRICT=1 python tools/pipeline/validate_external_asset_catalog.py --lib megascans --strict
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

COMMAND = "validate-external-asset-catalog"
REPORT_SUBDIR = "validate_external_asset_catalog"
REPORT_FILENAME = "validate_external_asset_catalog_report.json"

# Tokens that must never appear in a committed, portable source_path. Generic
# absolute-path indicators only (drive-colon ':' catches any "X:\..." machine
# root); no specific machine/cache name is hardcoded here.
ABSOLUTE_PATH_TOKENS = (":", "\\\\")  # drive/URI colon, or a UNC "\\host" lead


def _looks_absolute(source_path):
    """True if a committed source_path leaks an absolute/machine-specific path."""
    if not isinstance(source_path, str) or not source_path.strip():
        return True  # missing / empty is handled separately, but treat as unsafe
    p = source_path
    if any(tok in p for tok in ABSOLUTE_PATH_TOKENS):
        return True
    # POSIX absolute or UNC leak.
    if p.startswith("/") or p.startswith("\\\\"):
        return True
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate external asset catalog integrity.")
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
              code=FailureCode.MEGASCANS_CATALOG_FAILURE)

    for aid in ids:
        rec = assets[aid] or {}

        # Full external-asset field taxonomy present (addendum §6/§7).
        missing = [f for f in EAC.EXTERNAL_REQUIRED_FIELDS
                   if f not in rec or rec.get(f) in (None, "")]
        rep.check("{}::required_fields_present".format(aid), not missing,
                  "missing required external fields: {}".format(missing),
                  code=FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE)

        # A referenced descriptor path (if declared) must resolve on disk.
        dpath = rec.get("descriptor_path")
        if dpath:
            resolved = (REPO_ROOT / dpath).is_file()
            rep.check("{}::descriptor_path_resolves".format(aid), resolved,
                      "descriptor_path does not resolve: {}".format(dpath),
                      code=FailureCode.MEGASCANS_CATALOG_FAILURE)

        # source_path present and NOT an absolute / machine-specific leak.
        sp = rec.get("source_path")
        rep.check("{}::source_path_present".format(aid),
                  isinstance(sp, str) and bool(sp.strip()),
                  "source_path missing/empty",
                  code=FailureCode.MEGASCANS_CATALOG_FAILURE)
        rep.check("{}::source_path_not_absolute".format(aid),
                  isinstance(sp, str) and bool(sp.strip()) and not _looks_absolute(sp),
                  "source_path leaks an absolute/machine path: {!r}".format(sp),
                  code=FailureCode.MEGASCANS_CATALOG_FAILURE)

        # source_path_hash present (portable integrity anchor).
        rep.check("{}::source_path_hash_present".format(aid),
                  bool(rec.get("source_path_hash")),
                  "source_path_hash missing",
                  code=FailureCode.MEGASCANS_CATALOG_FAILURE)

        # No external record may claim generated ownership.
        rep.check("{}::not_generated_owned".format(aid),
                  rec.get("generated_owned") is False,
                  "generated_owned must be False for an external record (got {!r})".format(
                      rec.get("generated_owned")),
                  code=FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE)

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
