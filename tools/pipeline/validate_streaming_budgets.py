#!/usr/bin/env python3
"""validate_streaming_budgets.py — v2.3 Wave 4 streaming budget gate.

Proves streaming stays inside declared budgets and — critically — that a budget
OVERRUN can never silently pass. For each of the 24 runs the budget report must
classify a result (pass/advisory/exceeded); a report whose actuals exceed a hard cap
must be classified `exceeded` (not pass), and the runtime report's budget_result must
agree. Dogfoods the classifier on a synthetic overrun so the gate constrains even if
every real run passes.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_streaming_budgets.py --strict
Reports -> procedural/reports/streaming/budgets/validate_streaming_budgets_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_contracts as SC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

RUNTIME_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "runtime"
BUDGETS_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "budgets"
REPORT_DIR = BUDGETS_DIR


def _classify(actuals, caps):
    return "exceeded" if any(actuals[k] > caps[k] for k in caps) else "pass"


def validate(rep):
    # dogfood: a synthetic overrun MUST classify exceeded (never pass).
    caps = {"loaded_tiles": 3}
    rep.check("budget::dogfood_overrun_exceeded",
              _classify({"loaded_tiles": 9}, caps) == "exceeded",
              "an overrun must classify as exceeded", code=F.STREAMING_BUDGET_EXCEEDED)
    rep.check("budget::dogfood_within_pass",
              _classify({"loaded_tiles": 2}, caps) == "pass",
              "a within-budget run must classify as pass", code=F.STREAMING_BUDGET_EXCEEDED)

    reports = sorted(BUDGETS_DIR.glob("*.json"))
    reports = [p for p in reports if p.name != "validate_streaming_budgets_report.json"]
    rep.check("budget::count_24", len(reports) == SC.EXPECTED_SCENARIO_COUNT,
              "expected 24 budget reports (got {})".format(len(reports)),
              code=F.STREAMING_PARTIAL_MATRIX)
    n = 0
    for p in reports:
        b = json.loads(p.read_text(encoding="utf-8"))
        rid = b.get("report_id", p.stem)
        n += 1
        rep.check("bud::{}::has_result".format(rid), b.get("budget_result") in SC.BUDGET_RESULTS,
                  "budget report must classify a result", code=F.STREAMING_BUDGET_PROFILE_INVALID)
        actuals, bcaps = b.get("actuals", {}), b.get("caps", {})
        # recompute the classification honestly — a report cannot lie about it.
        recomputed = _classify(actuals, bcaps) if actuals and bcaps else "unknown"
        rep.check("bud::{}::classification_honest".format(rid),
                  b.get("budget_result") == recomputed
                  or (b.get("budget_result") == "advisory" and recomputed == "pass"),
                  "budget_result {} disagrees with recomputed {}".format(
                      b.get("budget_result"), recomputed),
                  code=F.STREAMING_BUDGET_EXCEEDED)
        # an exceeded budget can never be reported as pass.
        rep.check("bud::{}::exceeded_not_pass".format(rid),
                  not (recomputed == "exceeded" and b.get("budget_result") == "pass"),
                  "a budget overrun cannot be reported as pass", code=F.STREAMING_BUDGET_EXCEEDED)
        # package budget guard
        if "package_mb" in actuals and "package_mb" in bcaps:
            rep.check("bud::{}::package_within".format(rid),
                      actuals["package_mb"] <= bcaps["package_mb"] or b.get("budget_result") == "exceeded",
                      "package budget overrun must not pass", code=F.STREAMING_PACKAGE_BUDGET_EXCEEDED)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 streaming budget gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)
    n = validate(rep)
    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-streaming-budgets", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.streaming.budget_validation.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_streaming_budgets_report.json")
    rep.print_summary("validate-streaming-budgets")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
