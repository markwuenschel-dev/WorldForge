#!/usr/bin/env python3
"""validate_asset_hashes.py — v1.5 hash INTEGRITY gate.

Asserts the acquisition hash chain is intact:

  * each quarantine record carries a non-empty content_sha256 (ASSET_HASH_MISSING);
  * each catalog record carries a non-empty source_hash (ASSET_HASH_MISSING);
  * where a catalog record's source_path points at a quarantined asset, the catalog
    source_hash and the quarantine content hash AGREE (ASSET_HASH_MISMATCH).

Candidate ``hash_expected`` is checked as a soft signal (candidates may legally be
pre-download). Zero-record policy: INTEGRITY gate — passes clean on zero records;
record_count reflects checks performed (>=1) so report-integrity is honoured.
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
COMMAND = "validate_asset_hashes"
REPORT_TYPE = "wf.asset.hash_report.v1"


def _rel(p):
    return p.relative_to(REPO_ROOT).as_posix()


def _norm_hash(h):
    if not h:
        return ""
    return str(h).split(":", 1)[-1].strip().lower()


def _norm_path(p):
    return str(p or "").replace("\\", "/").strip().rstrip("/").lower()


def main(argv=None):
    ap = argparse.ArgumentParser(description="v1.5 hash integrity gate.")
    ap.add_argument("--pack", default=None)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep = ValidationReport("pack", args.pack or "all", strict=strict)

    quarantine, q_errs = discover_records([_rel(asset_paths.QUARANTINE_RECORDS_DIR)])
    catalog, c_errs = discover_records([_rel(asset_paths.CATALOG_DIR)])
    candidates, cand_errs = discover_records([_rel(asset_paths.CANDIDATES_DIR)])
    for name, detail in (q_errs + c_errs + cand_errs):
        rep.check("parse::{}".format(name), False, "unparseable record: {}".format(detail),
                  code=FailureCode.ASSET_HASH_MISSING)

    all_records = quarantine + catalog + candidates
    n_records = len(all_records)
    n_pass = 0

    if not all_records and not (q_errs + c_errs + cand_errs):
        rep.check("no_hash_bearing_records_present", True,
                  "no quarantine/catalog/candidate records yet (nothing to validate)")
    else:
        # Index quarantine content hashes by normalized local path.
        quar_hash_by_path = {}
        for name, rec in quarantine:
            if not isinstance(rec, dict):
                continue
            ch = _norm_hash((rec.get("hashes") or {}).get("content_sha256"))
            ok = bool(ch)
            n_pass += 1 if rep.check("quarantine::{}::content_hash_present".format(name), ok,
                                     "quarantine content_sha256 missing/empty",
                                     code=FailureCode.ASSET_HASH_MISSING) else 0
            if ch:
                quar_hash_by_path[_norm_path(rec.get("local_quarantine_path"))] = ch

        for name, rec in catalog:
            if not isinstance(rec, dict):
                continue
            sh = _norm_hash(rec.get("source_hash"))
            ok = bool(sh)
            rec_ok = rep.check("catalog::{}::source_hash_present".format(name), ok,
                               "catalog source_hash missing/empty",
                               code=FailureCode.ASSET_HASH_MISSING)
            # Cross-check agreement with the quarantine content hash it derives from.
            qh = quar_hash_by_path.get(_norm_path(rec.get("source_path")))
            if sh and qh:
                rec_ok = rep.check("catalog::{}::hash_matches_quarantine".format(name), sh == qh,
                                   "catalog source_hash {} != quarantine content hash {}".format(sh, qh),
                                   code=FailureCode.ASSET_HASH_MISMATCH) and rec_ok
            n_pass += 1 if rec_ok else 0

        for name, rec in candidates:
            if not isinstance(rec, dict):
                continue
            # Candidates may legally be pre-download: absent hash is a soft warning.
            he = _norm_hash(rec.get("hash_expected"))
            rep.check("candidate::{}::expected_hash_present".format(name), bool(he),
                      "candidate hash_expected missing (candidate may be pre-download)",
                      warn_only=True, code=FailureCode.ASSET_HASH_MISSING)
            n_pass += 1

    rep.finalize()
    rc = n_records if n_records else len(rep.checks)
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status, record_count=rc,
        records_total=n_records, records_passed=n_pass,
        records_failed=max(0, n_records - n_pass)))
    report_dir, filename = asset_paths.report_path("assets", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
