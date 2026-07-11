#!/usr/bin/env python3
"""streaming_report_integrity.py — v2.3 report-integrity gate (Wave R).

Attacks the streaming reports so an incomplete, unstamped, or vacuous report cannot
pass as evidence. Single source-of-truth predicate ``streaming_integrity_violations``
(empty == clean) checks each report carries a real meta block (git_sha, timestamp, a
wf.* report_type, a records tally), an explicit status, and a non-empty checks list.
Dogfoods the predicate on synthetic records, then scans the REAL streaming report
tree with a non-vacuous floor.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/streaming_report_integrity.py --strict
Reports -> procedural/reports/streaming/streaming_report_integrity_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

STREAM_DIR = REPO_ROOT / "procedural" / "reports" / "streaming"
MIN_REPORTS = 6


def streaming_integrity_violations(obj):
    probs = []
    if not isinstance(obj, dict):
        return ["not_an_object"]
    meta = obj.get("meta")
    if not isinstance(meta, dict):
        return ["missing_meta"]
    sha = meta.get("git_sha")
    if not (isinstance(sha, str) and sha and sha != "unknown"):
        probs.append("bad_git_sha")
    if not (isinstance(meta.get("timestamp"), str) and meta.get("timestamp")):
        probs.append("missing_timestamp")
    rt = meta.get("report_type")
    if not (isinstance(rt, str) and rt.startswith("wf.")):
        probs.append("bad_report_type")
    if not isinstance(meta.get("records_total"), int):
        probs.append("missing_records_total")
    if obj.get("status") not in ("ok", "fail", "warn", "error"):
        probs.append("bad_status")
    checks = obj.get("checks")
    if not (isinstance(checks, (list, dict)) and len(checks) > 0):
        probs.append("missing_checks")
    return probs


def _clean_report():
    return {"status": "ok", "checks": [{"name": "x", "verdict": "pass"}],
            "meta": {"git_sha": "0" * 40, "timestamp": "2026-07-11T00:00:00+00:00",
                     "report_type": "wf.streaming.x.v1", "records_total": 1}}


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 streaming report-integrity gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "streaming_report_integrity", strict=strict)

    rep.check("dogfood::clean_passes", streaming_integrity_violations(_clean_report()) == [],
              "clean synthetic report must pass", code=F.STREAMING_REPORT_INTEGRITY_FAILED)
    for label, mut in (
        ("no_meta", lambda r: r.pop("meta")),
        ("unknown_sha", lambda r: r["meta"].__setitem__("git_sha", "unknown")),
        ("no_timestamp", lambda r: r["meta"].pop("timestamp")),
        ("bad_report_type", lambda r: r["meta"].__setitem__("report_type", "nope")),
        ("no_status", lambda r: r.__setitem__("status", "green")),
        ("no_checks", lambda r: r.pop("checks"))):
        bad = _clean_report()
        mut(bad)
        rep.check("dogfood::flags_{}".format(label), streaming_integrity_violations(bad) != [],
                  "tampered report ({}) must be flagged".format(label),
                  code=F.STREAMING_REPORT_INTEGRITY_FAILED)

    scanned = 0
    for p in sorted(STREAM_DIR.rglob("*_report.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rep.check("integrity::{}::parses".format(p.name), False,
                      "unparseable report: {}".format(e), code=F.STREAMING_REPORT_INTEGRITY_FAILED)
            continue
        if "meta" not in obj:
            continue
        probs = streaming_integrity_violations(obj)
        rep.check("integrity::{}".format(p.relative_to(STREAM_DIR)), probs == [],
                  "report integrity problems: {}".format(probs),
                  code=F.STREAMING_REPORT_INTEGRITY_FAILED)
        scanned += 1
    rep.check("integrity::non_vacuous", scanned >= MIN_REPORTS,
              "must scan >= {} real reports (got {})".format(MIN_REPORTS, scanned),
              code=F.STREAMING_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="streaming-report-integrity", pack=None, strict=strict, status=rep.status,
        record_count=scanned, records_total=scanned, report_type="wf.streaming.report_integrity.v1"))
    STREAM_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(STREAM_DIR, "streaming_report_integrity_report.json")
    rep.print_summary("streaming-report-integrity")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
