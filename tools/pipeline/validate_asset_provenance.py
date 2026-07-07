#!/usr/bin/env python3
"""validate_asset_provenance.py — v1.5 provenance INTEGRITY gate.

Over every candidate / quarantine / catalog record, asserts the provenance chain is
intact: a source URL or path is present, a source adapter is linked, publisher/
author are present where applicable (third-party content must name a publisher), a
license snapshot/URL is present where the record type carries one, and approval/
candidate linkage exists. Missing provenance is ASSET_PROVENANCE_MISSING.

Zero-record policy: INTEGRITY gate — passes clean on zero records; record_count
reflects checks performed (>=1) so report-integrity's zero-record rule is honoured.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import mesh_contract as MC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from v1_5_schema_gate import discover_records
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "validate_asset_provenance"
REPORT_TYPE = "wf.asset.provenance_report.v1"

_PC = FailureCode.ASSET_PROVENANCE_MISSING


def _rel(p):
    return p.relative_to(REPO_ROOT).as_posix()


def _nonempty(rec, *keys):
    for k in keys:
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            return True
        if v and not isinstance(v, str):
            return True
    return False


def _check_record(rep, tag, rec):
    ok = True
    # source URL / path linkage (field names differ per record type).
    ok = rep.check("{}::source_reference_present".format(tag),
                   _nonempty(rec, "source_url", "source_path", "source_url_or_path"),
                   "no source_url/source_path/source_url_or_path present", code=_PC) and ok
    # source adapter linkage.
    ok = rep.check("{}::source_adapter_linked".format(tag),
                   _nonempty(rec, "source_adapter"),
                   "no source_adapter linkage", code=_PC) and ok
    # publisher/author where applicable: third-party content must name a publisher.
    resolved = MC.resolve_ownership_class(rec)
    if resolved == MC.OWNERSHIP_THIRD_PARTY or rec.get("third_party_owned"):
        ok = rep.check("{}::third_party_publisher_present".format(tag),
                       _nonempty(rec, "publisher", "author"),
                       "third-party asset must name a publisher/author", code=_PC) and ok
    # license snapshot/url where the record type carries one.
    if any(k in rec for k in ("license_url", "license_snapshot", "license_text_snapshot_path")):
        ok = rep.check("{}::license_snapshot_present".format(tag),
                       _nonempty(rec, "license_url", "license_snapshot", "license_text_snapshot_path"),
                       "record carries a license-snapshot field but it is empty", code=_PC) and ok
    # approval/candidate linkage.
    ok = rep.check("{}::approval_or_candidate_linkage".format(tag),
                   _nonempty(rec, "candidate_id", "approval_id", "approved_at", "provenance_id"),
                   "no candidate/approval linkage", code=_PC) and ok
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="v1.5 provenance integrity gate.")
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
        rep.check("parse::{}".format(name), False, "unparseable record: {}".format(detail), code=_PC)

    n_pass = 0
    if not records and not parse_errors:
        rep.check("no_provenance_bearing_records_present", True,
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
