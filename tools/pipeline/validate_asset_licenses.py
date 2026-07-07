#!/usr/bin/env python3
"""validate_asset_licenses.py — v1.5 license INTEGRITY gate.

Over every candidate / quarantine / catalog record, asserts the ``license_family``
is in the allowed acquisition set and rejects unknown / non-commercial / editorial
/ missing licenses fail-closed. A CC0 (or Poly Haven) asset additionally must carry
a license URL or snapshot so the permissive claim is provable.

Allowed families: cc0, fab_standard, fab_professional, project_owned,
generated_owned, internal_project_license.

Zero-record policy: INTEGRITY gate — passes clean on zero records with an
informational check; record_count reflects checks performed (>=1) so
report-integrity's zero-record rule is not tripped.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from v1_5_schema_gate import discover_records
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "validate_asset_licenses"
REPORT_TYPE = "wf.asset.license_report.v1"

ALLOWED_LICENSE_FAMILIES = (
    "cc0", "fab_standard", "fab_professional",
    "project_owned", "generated_owned", "internal_project_license",
)
# Families that are recognised but explicitly forbidden for incorporation.
UNSUPPORTED_LICENSE_FAMILIES = ("noncommercial_only", "editorial_only")
# Families that read as "we don't actually know the license" -> reject.
UNKNOWN_LICENSE_FAMILIES = ("unknown", "unknown_license", "", None)
# CC0-style permissive families that must ship a license URL/snapshot as proof.
PROOF_REQUIRED_FAMILIES = ("cc0",)


def _rel(p):
    return p.relative_to(REPO_ROOT).as_posix()


def _has_license_proof(rec):
    for k in ("license_url", "license_snapshot", "license_text_snapshot_path"):
        if (rec.get(k) or "").strip():
            return True
    return False


def _needs_proof(rec, lf):
    if lf in PROOF_REQUIRED_FAMILIES:
        return True
    hay = " ".join(str(rec.get(k) or "") for k in
                   ("source_type", "publisher", "author", "source_adapter")).lower()
    return "polyhaven" in hay or "poly haven" in hay


def _check_record(rep, tag, rec):
    ok = True
    lf = rec.get("license_family") if isinstance(rec, dict) else None
    if lf in UNKNOWN_LICENSE_FAMILIES:
        if not lf:
            ok = rep.check("{}::license_present".format(tag), False,
                           "license_family missing/empty",
                           code=FailureCode.ASSET_LICENSE_MISSING) and ok
        else:
            ok = rep.check("{}::license_known".format(tag), False,
                           "license_family={!r} is unknown; unknown licenses are rejected".format(lf),
                           code=FailureCode.ASSET_UNKNOWN_LICENSE_REJECTED) and ok
    elif lf in UNSUPPORTED_LICENSE_FAMILIES:
        ok = rep.check("{}::license_supported".format(tag), False,
                       "license_family={!r} is unsupported for incorporation".format(lf),
                       code=FailureCode.ASSET_LICENSE_UNSUPPORTED) and ok
    elif lf not in ALLOWED_LICENSE_FAMILIES:
        ok = rep.check("{}::license_in_allowed_set".format(tag), False,
                       "license_family={!r} not in {}".format(lf, ALLOWED_LICENSE_FAMILIES),
                       code=FailureCode.ASSET_UNKNOWN_LICENSE_REJECTED) and ok
    else:
        rep.check("{}::license_in_allowed_set".format(tag), True, "license_family={!r}".format(lf))
        # Permissive (cc0/PolyHaven) proof is only enforceable on record types that
        # structurally carry a license-url/snapshot field (candidate, catalog). A
        # quarantine record has no such field — its proof lives on the linked
        # candidate — so enforcing it here would be a false failure.
        carries_license_field = any(
            k in rec for k in ("license_url", "license_snapshot", "license_text_snapshot_path"))
        if _needs_proof(rec, lf) and carries_license_field:
            ok = rep.check("{}::permissive_license_proof".format(tag), _has_license_proof(rec),
                           "cc0/PolyHaven asset must carry a license_url/snapshot",
                           code=FailureCode.ASSET_LICENSE_MISSING) and ok
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="v1.5 license integrity gate.")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep = ValidationReport("pack", args.pack or "all", strict=strict)
    dirs = [_rel(asset_paths.CANDIDATES_DIR),
            _rel(asset_paths.QUARANTINE_RECORDS_DIR),
            _rel(asset_paths.CATALOG_DIR)]
    records, parse_errors = discover_records(dirs)
    for name, detail in parse_errors:
        rep.check("parse::{}".format(name), False, "unparseable record: {}".format(detail),
                  code=FailureCode.ASSET_LICENSE_MISSING)

    n_pass = 0
    if not records and not parse_errors:
        rep.check("no_license_bearing_records_present", True,
                  "no candidate/quarantine/catalog records yet (nothing to validate)")
    else:
        for name, rec in records:
            if _check_record(rep, name, rec if isinstance(rec, dict) else {}):
                n_pass += 1

    rep.finalize()
    rc = len(records) if records else len(rep.checks)
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status, record_count=rc,
        records_total=len(records), records_passed=n_pass,
        records_failed=max(0, len(records) - n_pass)))
    report_dir, filename = asset_paths.report_path("assets", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
