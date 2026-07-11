#!/usr/bin/env python3
"""validate_tactical_runtime.py — v2.4 Wave 4 tactical runtime gate.

Re-validates every emitted runtime report + decision bundle from disk against
tactical_contracts AND performs the cross-record proof the schema-only contracts cannot:
each scenario has NPC decisions; each decision trace resolves to a real decision input;
each selected option exists in the scenario's options AND is valid; each trace's state
delta resolves; runtime report decision_count equals the trace count; runtime mode is
labeled honestly (no live overclaim); mission completes; and the 24-scenario matrix as a
whole covers every required tactical-action class. Coverage: 24 runtime reports + 24
decision bundles.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_tactical_runtime.py --strict
Reports -> procedural/reports/tactical/runtime/validate_tactical_runtime_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

RUNTIME_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "runtime"
DECISIONS_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "decisions"
HONEST_MODES = ("deterministic_tactical_simulation", "live_tactical_runtime")


def _load_scenario_reports(d):
    return {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(d.glob("*.json")) if not p.stem.startswith("run_")
            and not p.stem.startswith("validate_")}


def validate(rep):
    reports = _load_scenario_reports(RUNTIME_DIR)
    bundles = {p.stem: json.loads(p.read_text(encoding="utf-8"))
               for p in sorted(DECISIONS_DIR.glob("*.json"))
               if not p.stem.startswith("validate_")}

    rep.check("count::runtime_reports_24", len(reports) == TC.EXPECTED_SCENARIO_COUNT,
              "must have 24 runtime reports (got {})".format(len(reports)),
              code=F.TACTICAL_PARTIAL_MATRIX)
    rep.check("count::decision_bundles_24", len(bundles) == TC.EXPECTED_SCENARIO_COUNT,
              "must have 24 decision bundles (got {})".format(len(bundles)),
              code=F.TACTICAL_PARTIAL_MATRIX)

    coverage = set()
    n = 0
    for sid, rr in reports.items():
        n += 1
        fails = [c for c in TC.validate_tactical_runtime_report(rr, strict=True) if not c[1]]
        rep.check("rt::{}::report_valid".format(sid), len(fails) == 0,
                  "runtime report invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_RUNTIME_REPORT_INVALID)
        rep.check("rt::{}::mode_honest".format(sid), rr.get("runtime_mode") in HONEST_MODES,
                  "runtime_mode must be honestly labeled (got {})".format(rr.get("runtime_mode")),
                  code=F.TACTICAL_NAVMESH_OVERCLAIM)
        rep.check("rt::{}::mission_completed".format(sid), rr.get("mission_completed") is True,
                  "mission must complete", code=F.TACTICAL_RUNTIME_REPORT_INVALID)
        coverage |= set(rr.get("actions_executed") or [])

        bundle = bundles.get(sid)
        rep.check("rt::{}::has_bundle".format(sid), bundle is not None,
                  "runtime report has no decision bundle", code=F.TACTICAL_DECISION_TRACE_INVALID)
        if not bundle:
            continue
        inputs = {i["decision_input_id"]: i for i in bundle.get("decision_inputs", [])}
        options = {o["option_id"]: o for o in bundle.get("decision_options", [])}
        deltas = {d["delta_id"]: d for d in bundle.get("state_deltas", [])}
        traces = bundle.get("decision_traces", [])

        # each record validates against its contract
        for kind, fn, code in (
            ("decision_inputs", TC.validate_tactical_decision_input, F.TACTICAL_DECISION_INPUT_INVALID),
            ("decision_options", TC.validate_tactical_decision_option, F.TACTICAL_DECISION_OPTION_INVALID),
            ("decision_traces", TC.validate_tactical_decision_trace, F.TACTICAL_DECISION_TRACE_INVALID),
            ("state_deltas", TC.validate_tactical_state_delta, F.TACTICAL_STATE_DELTA_INVALID),
        ):
            bad = 0
            for rec in bundle.get(kind, []):
                if [c for c in fn(rec, strict=True) if not c[1]]:
                    bad += 1
            rep.check("rt::{}::{}_valid".format(sid, kind), bad == 0,
                      "{} invalid records: {}".format(kind, bad), code=code)

        rep.check("rt::{}::has_decisions".format(sid), len(traces) > 0,
                  "scenario has no decisions", code=F.TACTICAL_DECISION_TRACE_INVALID)
        rep.check("rt::{}::decision_count_matches".format(sid),
                  rr.get("decision_count") == len(traces),
                  "runtime report decision_count {} != trace count {}".format(
                      rr.get("decision_count"), len(traces)),
                  code=F.TACTICAL_RUNTIME_REPORT_INVALID)

        # each trace: input resolves, selected option exists + is valid, delta resolves,
        # options considered non-empty
        for tr in traces:
            tid = tr.get("trace_id")
            rep.check("rt::{}::{}::input_resolves".format(sid, tid),
                      tr.get("decision_input_id") in inputs,
                      "trace input unresolved", code=F.TACTICAL_DECISION_TRACE_INVALID)
            rep.check("rt::{}::{}::options_considered".format(sid, tid),
                      len(tr.get("options_considered") or []) >= 1,
                      "trace considered no options", code=F.TACTICAL_DECISION_TRACE_INVALID)
            sel = tr.get("selected_option_id")
            rep.check("rt::{}::{}::selected_exists".format(sid, tid), sel in options,
                      "selected option {} not in scenario options".format(sel),
                      code=F.TACTICAL_DECISION_TRACE_INVALID)
            rep.check("rt::{}::{}::selected_valid".format(sid, tid),
                      sel not in options or options[sel].get("valid") is True,
                      "selected option is not valid", code=F.TACTICAL_SELECTED_INVALID_OPTION)
            rep.check("rt::{}::{}::delta_resolves".format(sid, tid),
                      tr.get("state_delta_id") in deltas,
                      "trace state delta unresolved", code=F.TACTICAL_STATE_NOT_MUTATED)

    missing = sorted(set(TC.REQUIRED_COVERAGE_ACTIONS) - coverage)
    rep.check("matrix::action_coverage", not missing,
              "matrix must cover every required action class (missing: {})".format(missing),
              code=F.TACTICAL_ACTION_COVERAGE_MISSING)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical runtime gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_runtime", strict=strict)
    n = validate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-tactical-runtime", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.runtime_validation.v1"))
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(RUNTIME_DIR, "validate_tactical_runtime_report.json")
    rep.print_summary("validate-tactical-runtime")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
