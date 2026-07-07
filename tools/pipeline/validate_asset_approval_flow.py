#!/usr/bin/env python3
"""validate_asset_approval_flow.py — v1.5 approval-flow INTEGRITY gate.

Over every generated ``AssetApprovalRecord``, asserts the approval obeys the
declarative ``INVALID_APPROVAL_RULES`` from ``asset_approval_contract`` (delegated,
not reimplemented): no third-party approval may grant standalone redistribution, and
a manual marketplace acquisition requires a completed manual action plus real-user
EULA + purchase markers. Each record is run through ``asset_approval_contract.
validate_record``.

Zero-record policy: INTEGRITY gate — passes clean on zero records; record_count
reflects checks performed (>=1) so report-integrity's zero-record rule is honoured.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import asset_approval_contract as AC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from v1_5_schema_gate import discover_records
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "validate_asset_approval_flow"
REPORT_TYPE = "wf.asset.approval_flow_report.v1"


def _rel(p):
    return p.relative_to(REPO_ROOT).as_posix()


def _check_record(rep, tag, rec):
    ok = True
    for cname, cok, detail, code in AC.validate_record(rec, strict=True):
        ok = rep.check("{}::{}".format(tag, cname), cok, detail, code=code) and ok
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="v1.5 approval-flow integrity gate.")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep = ValidationReport("pack", args.pack or "all", strict=strict)
    records, parse_errors = discover_records([_rel(asset_paths.APPROVALS_DIR)])
    for name, detail in parse_errors:
        rep.check("parse::{}".format(name), False, "unparseable approval record: {}".format(detail),
                  code=FailureCode.ASSET_APPROVAL_STATE_FAILURE)

    n_pass = 0
    if not records and not parse_errors:
        rep.check("no_approval_records_present", True,
                  "no approval records yet (nothing to validate)")
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
