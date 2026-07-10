#!/usr/bin/env python3
"""operator_report_integrity.py — v2.1 OperatorForge report-integrity gate (Wave R).

Attacks the operator reports so an incomplete, unstamped, or vacuous report cannot
pass as evidence. Single source-of-truth predicate ``operator_integrity_violations``
(empty == clean) checks each operator report carries a real meta block (git_sha,
timestamp, a wf.operator/wf.* report_type, a records tally), an explicit status,
and a non-empty checks list. It dogfoods the predicate on synthetic records first
(so it constrains even on an empty tree), then scans the REAL operator report tree
with a non-vacuous floor — an empty/too-small tree fails ("nothing to prove").

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/operator_report_integrity.py --strict
Reports -> procedural/reports/operator/operator_report_integrity_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

OPERATOR_DIR = REPO_ROOT / "procedural" / "reports" / "operator"
MIN_REPORTS = 6  # non-vacuous floor: the gate must have real reports to scan.


def operator_integrity_violations(obj):
    """Return a list of integrity problems for one operator validation report."""
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
            "meta": {"git_sha": "0" * 40, "timestamp": "2026-07-10T00:00:00+00:00",
                     "report_type": "wf.operator.x.v1", "records_total": 1}}


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator report-integrity gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("operator", "report_integrity", strict=strict)

    # --- dogfood the predicate first (constrains even on an empty tree) --------
    rep.check("dogfood::clean_passes", operator_integrity_violations(_clean_report()) == [],
              "clean synthetic report must pass", code=F.OPERATOR_REPORT_INTEGRITY_FAILED)
    for label, mut in (
        ("no_meta", lambda r: r.pop("meta")),
        ("unknown_sha", lambda r: r["meta"].__setitem__("git_sha", "unknown")),
        ("no_timestamp", lambda r: r["meta"].pop("timestamp")),
        ("bad_report_type", lambda r: r["meta"].__setitem__("report_type", "nope")),
        ("no_status", lambda r: r.__setitem__("status", "green")),
        ("no_checks", lambda r: r.pop("checks"))):
        bad = _clean_report()
        mut(bad)
        rep.check("dogfood::flags_{}".format(label),
                  operator_integrity_violations(bad) != [],
                  "tampered report ({}) must be flagged".format(label),
                  code=F.OPERATOR_REPORT_INTEGRITY_FAILED)

    # --- scan the real operator report tree with a non-vacuous floor ----------
    reports = [p for p in OPERATOR_DIR.rglob("*_report.json")]
    scanned = 0
    for p in sorted(reports):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rep.check("integrity::{}::parses".format(p.name), False,
                      "unparseable operator report: {}".format(e),
                      code=F.OPERATOR_REPORT_PARSE_FAILED)
            continue
        if "meta" not in obj:
            continue  # a produced data artifact (index/cards), not a validation report
        scanned += 1
        probs = operator_integrity_violations(obj)
        rep.check("integrity::{}".format(p.name), not probs, "; ".join(probs),
                  code=F.OPERATOR_REPORT_INTEGRITY_FAILED)

    rep.check("integrity::non_vacuous", scanned >= MIN_REPORTS,
              "scanned only {} operator reports (< {} floor)".format(scanned, MIN_REPORTS),
              code=F.OPERATOR_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-report-integrity", pack=None, strict=strict, status=rep.status,
        record_count=scanned, records_total=scanned,
        report_type="wf.operator.report_integrity.v1"))
    OPERATOR_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(OPERATOR_DIR, "operator_report_integrity_report.json")
    rep.print_summary("operator-report-integrity")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
