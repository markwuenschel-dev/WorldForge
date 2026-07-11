#!/usr/bin/env python3
"""run_tactical_behavior_alpha.py — v2.4 Wave 4 tactical runtime runner (Agent 5).

Drives the deterministic tactical decision engine (tactical_runtime) over the 24-scenario
matrix and writes the decision evidence + runtime reports. Runtime mode is
`deterministic_tactical_simulation` (handoff §12) — labeled honestly in every report; it is
NOT live UE AI. Every emitted record is validated against tactical_contracts before it is
written — the runner never emits a record its own contract would reject.

Modes:
    --smoke                    run one scenario end-to-end (fast precondition gate)
    --gate --scenarios 24      run the full bounded matrix

Deliverables:
    procedural/reports/tactical/runtime/*.json     (per-scenario TacticalRuntimeReport)
    procedural/reports/tactical/decisions/*.json   (inputs/options/traces/state deltas)
    procedural/reports/tactical/runtime/run_tactical_behavior_report.json  (batch)

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/run_tactical_behavior_alpha.py --gate --scenarios 24 --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
import tactical_runtime as RT
import tactical_spec as SP
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

RUNTIME_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "runtime"
DECISIONS_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "decisions"

_RECORD_VALIDATORS = {
    "decision_inputs": (TC.validate_tactical_decision_input, F.TACTICAL_DECISION_INPUT_INVALID),
    "decision_options": (TC.validate_tactical_decision_option, F.TACTICAL_DECISION_OPTION_INVALID),
    "decision_traces": (TC.validate_tactical_decision_trace, F.TACTICAL_DECISION_TRACE_INVALID),
    "state_deltas": (TC.validate_tactical_state_delta, F.TACTICAL_STATE_DELTA_INVALID),
}


def _run_scenario(rep, scenario, write):
    out = RT.simulate_scenario(scenario)
    sid = scenario["scenario_id"]
    for kind, (fn, code) in _RECORD_VALIDATORS.items():
        for rec in out[kind]:
            fails = [c for c in fn(rec, strict=True) if not c[1]]
            rep.check("run::{}::{}::valid".format(sid, kind), len(fails) == 0,
                      "{} record invalid: {}".format(kind, [(c[0], c[3]) for c in fails][:3]),
                      code=code)
    rr = out["runtime_report"]
    rfails = [c for c in TC.validate_tactical_runtime_report(rr, strict=True) if not c[1]]
    rep.check("run::{}::report_valid".format(sid), len(rfails) == 0,
              "runtime report invalid: {}".format([(c[0], c[3]) for c in rfails][:3]),
              code=F.TACTICAL_RUNTIME_REPORT_INVALID)
    if write:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
        (RUNTIME_DIR / (sid + ".json")).write_text(
            json.dumps(rr, indent=2, sort_keys=True), encoding="utf-8")
        bundle = {k: out[k] for k in ("decision_inputs", "decision_options",
                                      "decision_traces", "state_deltas")}
        bundle["scenario_id"] = sid
        (DECISIONS_DIR / (sid + ".json")).write_text(
            json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    return rr


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical runtime runner.")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--scenarios", type=int, default=24)
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    scenarios = SP.scenario_plan()
    if args.smoke and not args.gate:
        scenarios = scenarios[:1]
        tag, write = "run-tactical-smoke", False
    else:
        scenarios = scenarios[:args.scenarios]
        tag, write = "run-tactical-runtime", True

    rep = ValidationReport("suite", "tactical_runtime", strict=strict)
    coverage = set()
    for s in scenarios:
        rr = _run_scenario(rep, s, write)
        coverage |= set(rr["actions_executed"])
    if not args.smoke or args.gate:
        rep.check("matrix::count", len(scenarios) == SP.EXPECTED_SCENARIO_COUNT,
                  "runtime matrix must be 24 scenarios (got {})".format(len(scenarios)),
                  code=F.TACTICAL_PARTIAL_MATRIX)
        missing = sorted(set(TC.REQUIRED_COVERAGE_ACTIONS) - coverage)
        rep.check("matrix::action_coverage", not missing,
                  "matrix must cover every required action class (missing: {})".format(missing),
                  code=F.TACTICAL_ACTION_COVERAGE_MISSING)

    rep.finalize()
    rep.set_meta(build_meta(
        command=tag, pack=None, strict=strict, status=rep.status,
        record_count=len(scenarios), records_total=len(scenarios),
        report_type="wf.tactical.runtime_run.v1"))
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(RUNTIME_DIR, "run_tactical_behavior_report.json")
    rep.print_summary(tag)
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
