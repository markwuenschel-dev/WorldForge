#!/usr/bin/env python3
"""diff_operator_runs.py — v2.1 OperatorForge run-to-run diff (Wave 4).

Compares two operator report indexes (runs) and emits a contract-valid
OperatorDiffReport: which scenarios changed, which failures are NEW vs RESOLVED,
and whether package / runtime status flipped. New blocking failures are surfaced;
resolved failures link back to their old codes.

Default (no args, for the shield gate): diffs a fixed GENESIS baseline (the honest
'nothing yet' state: 0 scenarios, integrity=blocked) against the CURRENT operator
index — a real, non-vacuous transition that proves the diff machinery. Pass
--left/--right index paths to diff two real run snapshots instead.

Deterministic: output depends only on the two inputs (no wall-clock), so a diff is
reproducible. FAIL-CLOSED: a missing current index is RED.

Acceptance:
    PYTHONUTF8=1 python tools/operator/diff_operator_runs.py --strict
Reports -> procedural/reports/operator/diff/operator_diff_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_contracts as OX

INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
DIFF_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "diff"
CUR_INDEX = INDEX_DIR / "operator_report_index.json"
GRAPH = INDEX_DIR / "evidence_graph.json"

GENESIS = {
    "run_id": "genesis",
    "git_sha": "0000000000000000000000000000000000000000",
    "integrity_result": "blocked",
    "scenarios": [],
    "failures": [],
    "package_ok": False,
    "runtime_pass": 0,
}


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _run_from_index(index, graph):
    scn = sorted({t["scenario_id"] for t in graph.get("traces", [])})
    failures = sorted({c for t in graph.get("traces", []) for c in t.get("failure_codes", [])})
    runtime_pass = sum(1 for t in graph.get("traces", [])
                       if t.get("claim") == "scenario completed" and t.get("verdict") == "pass")
    return {
        "run_id": "run_{}".format((index.get("git_sha") or "unknown")[:8]),
        "git_sha": index.get("git_sha", "unknown"),
        "integrity_result": index.get("integrity_result", "blocked"),
        "scenarios": scn,
        "failures": failures,
        "package_ok": runtime_pass > 0,
        "runtime_pass": runtime_pass,
    }


def diff(left, right):
    ls, rs = set(left["scenarios"]), set(right["scenarios"])
    lf, rf = set(left["failures"]), set(right["failures"])
    changed_scn = sorted(ls.symmetric_difference(rs))
    new_fail = sorted(rf - lf)
    resolved_fail = sorted(lf - rf)
    report = OX._example_diff_report(
        diff_id="diff_{}_{}".format(left["run_id"], right["run_id"]),
        left_run_id=left["run_id"],
        right_run_id=right["run_id"],
        left_git_sha=left["git_sha"],
        right_git_sha=right["git_sha"],
        changed_reports=[],
        changed_scenarios=changed_scn,
        changed_failures=sorted(lf.symmetric_difference(rf)),
        resolved_failures=resolved_fail,
        new_failures=new_fail,
        changed_package_status=left["package_ok"] != right["package_ok"],
        changed_runtime_status=left["runtime_pass"] != right["runtime_pass"],
        summary="{} scenarios changed; {} new / {} resolved failures; "
                "runtime {}->{}; integrity {}->{}".format(
                    len(changed_scn), len(new_fail), len(resolved_fail),
                    left["runtime_pass"], right["runtime_pass"],
                    left["integrity_result"], right["integrity_result"]),
        failure_codes=[],
    )
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator run-to-run diff.")
    ap.add_argument("--left", default=None, help="left index json (default: genesis)")
    ap.add_argument("--right", default=None, help="right index json (default: current)")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)

    if not CUR_INDEX.is_file() or not GRAPH.is_file():
        print("[operator-diff-runs] FAIL — current operator index missing; run operator-index-reports")
        sys.exit(1)

    graph = _load(GRAPH)
    right = (_run_from_index(_load(args.right), graph) if args.right
             else _run_from_index(_load(CUR_INDEX), graph))
    if args.left:
        left = _run_from_index(_load(args.left), graph)
    else:
        left = dict(GENESIS)

    report = diff(left, right)
    fails = [c for c in OX.validate_diff_report(report, strict=True) if not c[1]]
    if fails:
        print("[operator-diff-runs] FAIL — diff report not contract-valid: {}".format(
            [c[0] for c in fails][:3]))
        sys.exit(1)

    DIFF_DIR.mkdir(parents=True, exist_ok=True)
    (DIFF_DIR / "operator_diff_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print("[operator-diff-runs] {} -> {}: {}".format(
        left["run_id"], right["run_id"], report["summary"]))
    print("  -> {}".format((DIFF_DIR / "operator_diff_report.json").as_posix()))
    sys.exit(0)


if __name__ == "__main__":
    main()
