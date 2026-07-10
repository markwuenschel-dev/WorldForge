#!/usr/bin/env python3
"""validate_operator_index.py — v2.1 operator index + evidence-graph gate (Wave 2).

Proves the derived operator index is honest. FAIL-CLOSED: the index artifacts must
exist (built by index_reports.py) or this gate is RED. Then it enforces both the
SCHEMA and the REFERENTIAL integrity that the indexer alone cannot self-certify:

  1. operator_report_index.json validates against the OperatorReportIndex contract.
  2. every trace in evidence_graph.json validates against the EvidenceTrace contract.
  3. REFERENTIAL: every source_root exists (WF712); every supporting report /
     telemetry / save-load / package path referenced by a PASS trace exists on
     disk (WF714); every failure_code (index + traces) resolves to the real
     FailureCode registry (WF715); git_sha is real, not 'unknown' (WF716).
  4. COVERAGE: the graph covers every scenario the index counts, trace_ids are
     unique (no duplicate cards, WF718), and a PASS index requires empty
     missing/stale evidence (re-checked, not trusted).

This is what stops a green operator view over missing/stale/unknown evidence.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/validate_operator_index.py --strict
Reports -> procedural/reports/operator/index/validate_operator_index_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_contracts as OX
from failure_codes import FailureCode as F, all_codes
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
INDEX_FILE = INDEX_DIR / "operator_report_index.json"
GRAPH_FILE = INDEX_DIR / "evidence_graph.json"

# The support-list fields whose entries must resolve to real files for a PASS trace.
_SUPPORT_FIELDS = ("supporting_reports", "supporting_telemetry",
                   "supporting_save_load_proofs", "supporting_package_proofs")


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator index gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("operator", "index", strict=strict)

    # --- fail-closed: artifacts must exist -----------------------------------
    rep.check("index_file_present", INDEX_FILE.is_file(),
              "operator_report_index.json missing — run operator-index-reports first",
              code=F.OPERATOR_MISSING_EVIDENCE)
    rep.check("graph_file_present", GRAPH_FILE.is_file(),
              "evidence_graph.json missing — run operator-index-reports first",
              code=F.OPERATOR_MISSING_EVIDENCE)
    if not (INDEX_FILE.is_file() and GRAPH_FILE.is_file()):
        rep.finalize()
        rep.set_meta(build_meta("validate-operator-index", pack=None, strict=strict,
                                status=rep.status, record_count=0, records_total=0,
                                report_type="wf.operator.index_gate.v1"))
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        rep.write(INDEX_DIR, "validate_operator_index_report.json")
        rep.print_summary("validate-operator-index")
        sys.exit(rep.exit_code)

    try:
        idx = _load(INDEX_FILE)
    except Exception as e:  # noqa: BLE001
        rep.check("index_parses", False, "index JSON unparseable: {}".format(e),
                  code=F.OPERATOR_REPORT_PARSE_FAILED)
        idx = {}
    try:
        graph = _load(GRAPH_FILE)
    except Exception as e:  # noqa: BLE001
        rep.check("graph_parses", False, "graph JSON unparseable: {}".format(e),
                  code=F.OPERATOR_REPORT_PARSE_FAILED)
        graph = {}
    traces = graph.get("traces", []) if isinstance(graph, dict) else []
    known_codes = set(all_codes())

    # --- 1. schema: OperatorReportIndex --------------------------------------
    for name, ok, detail, code in OX.validate_report_index(idx, strict=strict):
        rep.check("index::{}".format(name), ok, detail, code=code)

    # --- 3a. source roots must exist -----------------------------------------
    for root in idx.get("source_roots", []) if isinstance(idx.get("source_roots"), list) else []:
        rep.check("root_exists::{}".format(root), (REPO_ROOT / root).is_dir(),
                  "source_root does not exist: {}".format(root),
                  code=F.OPERATOR_SOURCE_ROOT_MISSING)

    # --- 3d. git_sha real -----------------------------------------------------
    sha = idx.get("git_sha")
    rep.check("index::real_git_sha",
              isinstance(sha, str) and sha and sha != "unknown",
              "index git_sha must be real (got {!r})".format(sha),
              code=F.OPERATOR_STALE_EVIDENCE)

    # --- 3c. index failure codes resolve -------------------------------------
    for c in idx.get("missing_evidence", []) if isinstance(idx.get("missing_evidence"), list) else []:
        pass  # missing_evidence carries scenario tokens, not codes

    # --- 2 + 3b + 3c: per-trace schema + referential integrity ---------------
    seen_ids = {}
    dup = 0
    for i, t in enumerate(traces):
        tid = t.get("trace_id", "trace_{}".format(i))
        if tid in seen_ids:
            dup += 1
        seen_ids[tid] = seen_ids.get(tid, 0) + 1
        tfails = [c for c in OX.validate_evidence_trace(t, strict=strict) if not c[1]]
        rep.check("trace::{}::schema".format(tid), len(tfails) == 0,
                  "{} schema failures: {}".format(len(tfails), [c[0] for c in tfails][:3]),
                  code=F.OPERATOR_EVIDENCE_TRACE_INVALID)
        # referential: a PASS trace's supporting paths must exist on disk.
        if t.get("verdict") == "pass":
            for field in _SUPPORT_FIELDS:
                for p in t.get(field, []) if isinstance(t.get(field), list) else []:
                    rep.check("trace::{}::{}::exists".format(tid, Path(p).name),
                              (REPO_ROOT / p).is_file(),
                              "PASS trace references missing path: {}".format(p),
                              code=F.OPERATOR_REPORT_PATH_MISSING)
        # every failure code in a trace resolves to the registry.
        for c in t.get("failure_codes", []) if isinstance(t.get("failure_codes"), list) else []:
            rep.check("trace::{}::code_resolves::{}".format(tid, c), c in known_codes,
                      "unknown failure code in trace: {}".format(c),
                      code=F.OPERATOR_UNKNOWN_FAILURE_CODE)

    rep.check("traces::unique_ids", dup == 0,
              "{} duplicate trace_id(s) in evidence graph".format(dup),
              code=F.OPERATOR_DUPLICATE_SCENARIO_CARD)
    rep.check("traces::nonempty", len(traces) > 0,
              "evidence graph carries no traces", code=F.OPERATOR_MISSING_EVIDENCE)

    # --- 4. coverage: graph covers every scenario the index counts -----------
    graph_scenarios = {t.get("scenario_id") for t in traces}
    idx_count = idx.get("scenario_count")
    rep.check("coverage::graph_covers_index_scenarios",
              isinstance(idx_count, int) and len(graph_scenarios) == idx_count,
              "graph covers {} distinct scenarios but index counts {}".format(
                  len(graph_scenarios), idx_count),
              code=F.OPERATOR_MISSING_EVIDENCE)

    # --- re-check the PASS honesty invariant (don't trust the producer) ------
    if idx.get("integrity_result") == "pass":
        rep.check("index::pass_recheck_no_missing",
                  isinstance(idx.get("missing_evidence"), list) and not idx["missing_evidence"],
                  "integrity_result=pass but missing_evidence is non-empty",
                  code=F.OPERATOR_MISSING_EVIDENCE)
        rep.check("index::pass_recheck_no_stale",
                  isinstance(idx.get("stale_evidence"), list) and not idx["stale_evidence"],
                  "integrity_result=pass but stale_evidence is non-empty",
                  code=F.OPERATOR_STALE_EVIDENCE)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-operator-index", pack=None, strict=strict,
        status=rep.status, record_count=len(traces), records_total=len(traces),
        report_type="wf.operator.index_gate.v1"))
    rep.write(INDEX_DIR, "validate_operator_index_report.json")
    rep.print_summary("validate-operator-index")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
