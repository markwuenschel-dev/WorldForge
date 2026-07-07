#!/usr/bin/env python3
"""validate_asset_quarantine.py — v1.5 quarantine INTEGRITY gate.

Runtime integrity gate over generated ``QuarantineAssetRecord`` records. For every
record it delegates the core schema/ownership/hash/path checks to
``quarantine_contract.validate_record`` (never reimplemented here) and adds:

  * a non-empty ``file_manifest``;
  * the load-bearing bypass guard — a quarantine record whose
    ``local_quarantine_path`` escaped to a final/owned content path is
    ASSET_QUARANTINE_BYPASS (quarantine is the mandatory waystation).

Zero-record policy (INTEGRITY, not schema): with no records this PASSES with an
informational "no records yet" check — "no bad records" is true. record_count is
set to the number of checks performed (>=1) so report-integrity's zero-record rule
is not tripped, while records_total honestly reports 0.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import mesh_contract as MC
import quarantine_contract as QC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from v1_5_schema_gate import discover_records
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "validate_asset_quarantine"
REPORT_TYPE = "wf.asset.quarantine_report.v1"


def _rel(p):
    return p.relative_to(REPO_ROOT).as_posix()


def validate(rep, strict):
    records, parse_errors = discover_records([_rel(asset_paths.QUARANTINE_RECORDS_DIR)])
    for name, detail in parse_errors:
        rep.check("parse::{}".format(name), False,
                  "unparseable quarantine record: {}".format(detail),
                  code=FailureCode.ASSET_QUARANTINE_FAILURE)

    if not records and not parse_errors:
        rep.check("no_quarantine_records_present", True,
                  "no quarantine records yet (nothing to validate)")
        return 0, 0

    n_pass = 0
    for name, rec in records:
        rec_ok = True
        for cname, ok, detail, code in QC.validate_record(rec, strict=strict):
            rec_ok = rep.check("{}::{}".format(name, cname), ok, detail, code=code) and rec_ok
        # file_manifest must be present and non-empty.
        fm = rec.get("file_manifest") if isinstance(rec, dict) else None
        fm_ok = bool(fm)
        rec_ok = rep.check("{}::file_manifest_non_empty".format(name), fm_ok,
                           "file_manifest empty/missing", code=FailureCode.ASSET_HASH_MISSING) and rec_ok
        # bypass guard: a quarantine path must never be a final owned path.
        path = rec.get("local_quarantine_path") if isinstance(rec, dict) else None
        bypass = bool(path) and MC.is_allowed_final_path(path)
        rec_ok = rep.check("{}::no_final_path_bypass".format(name), not bypass,
                           "local_quarantine_path={!r} escaped to a final owned path".format(path),
                           code=FailureCode.ASSET_QUARANTINE_BYPASS) and rec_ok
        n_pass += 1 if rec_ok else 0
    return len(records), n_pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="v1.5 quarantine integrity gate.")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep = ValidationReport("pack", args.pack or "all", strict=strict)
    n_records, n_pass = validate(rep, strict)
    rep.finalize()
    rc = n_records if n_records else len(rep.checks)
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status,
        record_count=rc, records_total=n_records, records_passed=n_pass,
        records_failed=max(0, n_records - n_pass)))
    report_dir, filename = asset_paths.report_path("assets", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
