#!/usr/bin/env python3
"""build_failure_index.py — v2.1 OperatorForge failure-code explorer (Wave 3/4).

Builds one contract-valid FailureCodeIndex row per code in the v2.0 SLICE band
(WF671-710) and the v2.1 OPERATOR band (WF711-740) — the codes the operator
surface can actually surface — enriched from the real FailureCode registry
(SEVERITY) and cross-checked against the evidence graph so each row's status is
honest: 'active' if the code appears in live evidence, else 'expected_negative'
(defined and proven by the negative suite, not currently firing).

Every row is validated against the FailureCodeIndex contract before it is written;
a row that violates its schema (e.g. a blocking code with no suggested next action)
turns this builder RED. Unknown codes referenced by any report but ABSENT from the
registry fail the gate (WF715) — that is the operator promise that every failure
code resolves.

Deliverables:
  index/failure_code_index.json          (list[FailureCodeIndex])
  dashboard/failures/index.html          (explorer table)

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/build_failure_index.py --strict
Reports -> procedural/reports/operator/index/build_failure_index_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_contracts as OX
import operator_view as V
from failure_codes import FailureCode, SEVERITY, all_codes, code_number
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
GRAPH_FILE = INDEX_DIR / "evidence_graph.json"

# SEVERITY buckets ("fail"/"warn") -> FailureCodeIndex severity vocabulary.
_SEV_MAP = {"fail": "blocking", "warn": "warning"}


def _humanize(code):
    # WF704_SLICE_REWARD_WITHOUT_MUTATION -> "slice reward without mutation"
    return code.split("_", 1)[1].replace("_", " ").lower()


def _rows(graph):
    seen = {c for t in graph.get("traces", []) for c in t.get("failure_codes", [])}
    by_num = {}
    for name, val in vars(FailureCode).items():
        if name.startswith("_") or not isinstance(val, str):
            continue
        n = code_number(val)
        if 671 <= n <= 740:
            by_num[n] = val
    rows = []
    for n in sorted(by_num):
        code = by_num[n]
        band_op = n >= 711
        severity = _SEV_MAP.get(SEVERITY.get(code, "fail"), "unknown")
        row = OX._example_failure_code_index(
            failure_code=code,
            namespace="OPERATOR" if band_op else "SLICE",
            milestone="v2.1" if band_op else "v2.0",
            severity=severity,
            meaning=_humanize(code),
            owning_validator="operator_contracts" if band_op else "slice_contracts",
            known_causes=["see {} taxonomy".format("v2.1" if band_op else "v2.0")],
            suggested_next_actions=[
                "run {} --strict and inspect the failing check".format(
                    "tools/pipeline/v2_1_shield.py --operator" if band_op
                    else "tools/pipeline/v2_0_shield.py")],
            related_reports=["procedural/reports/operator" if band_op
                             else "procedural/reports/slice"],
            first_seen="2026-07-10",
            last_seen="2026-07-10",
            status="active" if code in seen else "expected_negative",
        )
        rows.append(row)
    return rows, seen


def _render(rows, sha):
    body = '<h2>Failure-code explorer ({} codes)</h2>'.format(len(rows))
    body += '<div class="scroll"><table><tr><th>code</th><th>ns</th><th>sev</th>'\
            '<th>status</th><th>meaning</th></tr>'
    for r in rows:
        body += "<tr><td><code>{}</code></td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            V.esc(r["failure_code"]), V.esc(r["namespace"]),
            V.badge("fail" if r["severity"] in ("blocking", "fatal") else "blocked"),
            V.badge("pass" if r["status"] == "expected_negative" else "fail"),
            V.esc(r["meaning"]))
    body += "</table></div>"
    return V.page("Failure-code explorer", body,
                  subtitle="v2.0 SLICE (WF671-710) + v2.1 OPERATOR (WF711-740) bands",
                  git_sha=sha, back=("../index.html", "dashboard"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator failure-code explorer.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("operator", "failure_index", strict=strict)

    graph = json.loads(GRAPH_FILE.read_text(encoding="utf-8")) if GRAPH_FILE.is_file() else {"traces": []}
    known = set(all_codes())
    rows, seen = _rows(graph)

    rep.check("failure_index_nonempty", len(rows) >= 60,
              "expected >= 60 rows across the two bands (got {})".format(len(rows)),
              code=FailureCode.OPERATOR_FAILURE_INDEX_INVALID)
    # every code seen in the graph must resolve to the registry.
    for c in sorted(seen):
        rep.check("seen_code_resolves::{}".format(c), c in known,
                  "failure code in evidence graph does not resolve: {}".format(c),
                  code=FailureCode.OPERATOR_UNKNOWN_FAILURE_CODE)
    # every row must validate against its contract.
    for r in rows:
        fails = [c for c in OX.validate_failure_code_index(r, strict=strict) if not c[1]]
        rep.check("row::{}::schema".format(r["failure_code"]), len(fails) == 0,
                  "row schema failures: {}".format([c[0] for c in fails][:3]),
                  code=FailureCode.OPERATOR_FAILURE_INDEX_INVALID)

    if rep.passed:
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        (INDEX_DIR / "failure_code_index.json").write_text(
            json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
        sha = ""
        idx = INDEX_DIR / "operator_report_index.json"
        if idx.is_file():
            sha = json.loads(idx.read_text(encoding="utf-8")).get("git_sha", "")
        V.write_page("failures/index.html", _render(rows, sha))

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-failure-index", pack=None, strict=strict, status=rep.status,
        record_count=len(rows), records_total=len(rows),
        report_type="wf.operator.failure_index.v1"))
    rep.write(INDEX_DIR, "build_failure_index_report.json")
    rep.print_summary("operator-failure-index")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
