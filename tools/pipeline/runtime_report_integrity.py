#!/usr/bin/env python3
"""runtime_report_integrity.py — WorldForge v1.6 runtime report-integrity gate (Agent 7C).

Scans every v1.6 runtime report on disk and rejects the ways a report can lie:

  * missing required metadata (report can't prove it isn't stale/fabricated)
  * status inconsistent with counts (status=ok while failure_count>0)
  * a broken tally (records_total != passed+failed+skipped)
  * zero-record success (status ok/warn with records_total==0 — nothing was
    actually checked, but it reads as green)
  * a completed_runtime completion report with no telemetry path (fake green)

It complements validate_playtest_gamma_no_fake_green (which scans completion
class evidence) by auditing the report *envelopes* themselves.

Usage:
    python tools/pipeline/runtime_report_integrity.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/runtime/integrity/runtime_report_integrity_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from report_meta import build_meta, missing_v1_5_meta_keys, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

RUNTIME_REPORTS_ROOT = "procedural/reports/runtime"
# Report files that are raw artifacts (telemetry streams, gamma rollup, manifests)
# rather than ValidationReport envelopes — audited by their own gates, skipped here.
RAW_SUFFIXES = ("gamma_rollup.json", "_runtime_driver_rollup.json")


def _iter_reports():
    root = REPO_ROOT / RUNTIME_REPORTS_ROOT
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*.json")):
        if p.name.endswith(RAW_SUFFIXES):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            yield p, None
            continue
        yield p, data


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 runtime report-integrity gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    n_env = 0
    for path, data in _iter_reports():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if data is None:
            rep.check("{}::parses".format(rel), False, "unparseable report",
                      code=C.RUNTIME_REPORT_INTEGRITY_FAILURE)
            continue
        meta = data.get("meta") if isinstance(data, dict) else None
        # Only ValidationReport envelopes (they carry meta + status) are audited.
        if not isinstance(meta, dict):
            continue
        n_env += 1
        # 1) required metadata present
        miss = missing_v1_5_meta_keys(meta)
        rep.check("{}::meta_complete".format(rel), not miss,
                  "missing meta keys: {}".format(miss), code=C.RUNTIME_REPORT_INTEGRITY_FAILURE)
        # 2) status consistent with counts
        status = data.get("status")
        fc = int(meta.get("failure_count") or 0)
        rep.check("{}::status_consistent".format(rel),
                  not (status == "ok" and fc > 0),
                  "status=ok but failure_count={}".format(fc),
                  code=C.RUNTIME_REPORT_PARTIAL_SUCCESS)
        # 3) tally consistency
        rt = int(meta.get("records_total") or 0)
        rp = int(meta.get("records_passed") or 0)
        rfa = int(meta.get("records_failed") or 0)
        rs = int(meta.get("records_skipped") or 0)
        rep.check("{}::tally_consistent".format(rel), rt == rp + rfa + rs,
                  "records_total={} != passed({})+failed({})+skipped({})".format(rt, rp, rfa, rs),
                  code=C.RUNTIME_REPORT_INTEGRITY_FAILURE)
        # 4) zero-record success
        rep.check("{}::no_zero_record_success".format(rel),
                  not (status in ("ok", "warn") and rt == 0),
                  "status={} but records_total=0 (nothing checked)".format(status),
                  code=C.RUNTIME_REPORT_ZERO_RECORD_SUCCESS)
        # 5) completion report claiming success must carry telemetry
        if meta.get("report_type") == "wf.runtime.completion_report.v1" \
                and data.get("completion_class") == "completed_runtime":
            rep.check("{}::success_has_telemetry".format(rel),
                      bool(data.get("telemetry_path")),
                      "completed_runtime report without telemetry_path",
                      code=C.RUNTIME_REPORT_MISSING_TELEMETRY)

    rep.check("runtime_reports_present", n_env > 0,
              "{} runtime report envelopes audited".format(n_env),
              code=C.RUNTIME_REPORT_EMPTY)
    rep.finalize()
    rep.set_meta(build_meta(command="runtime-report-integrity", pack=args.pack, strict=strict,
                            status=rep.status, record_count=n_env,
                            report_type="wf.runtime.report_integrity.v1",
                            extra={"envelopes_audited": n_env}))
    rep.write(REPO_ROOT / RUNTIME_REPORTS_ROOT / "integrity",
              "runtime_report_integrity_report.json")
    rep.print_summary("runtime-report-integrity")
    print("[runtime-report-integrity] {} report envelopes audited".format(n_env))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
