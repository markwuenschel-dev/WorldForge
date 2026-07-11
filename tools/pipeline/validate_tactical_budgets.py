#!/usr/bin/env python3
"""validate_tactical_budgets.py — v2.4 Wave 5 tactical budget gate (Agent 6).

Builds a TacticalBudgetReport for every scenario from its runtime report + the bound
pressure profile's declared caps, with budget_result recomputed from the raw npc/decision
values so an overrun can never pass silently. Validates each against tactical_contracts and
writes it. Coverage: 24 budget reports.

Deliverables:
    procedural/reports/tactical/budgets/*.json

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_tactical_budgets.py --strict
Reports -> procedural/reports/tactical/budgets/validate_tactical_budgets_report.json
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
PROFILES_DIR = REPO_ROOT / "procedural" / "generated" / "tactical" / "profiles"
BUDGET_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "budgets"


def _load_runtime_reports():
    return {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(RUNTIME_DIR.glob("*.json"))
            if not p.stem.startswith("run_") and not p.stem.startswith("validate_")}


def validate(rep):
    BUDGET_DIR.mkdir(parents=True, exist_ok=True)
    scenarios = {s["scenario_id"]: s for s in SP.scenario_plan()}
    profiles = {rec["profile_id"]: rec for rec in (
        json.loads(p.read_text(encoding="utf-8")) for p in PROFILES_DIR.glob("*.json"))}
    reports = _load_runtime_reports()
    rep.check("count::runtime_reports_24", len(reports) == SP.EXPECTED_SCENARIO_COUNT,
              "need 24 runtime reports (run the runtime first); got {}".format(len(reports)),
              code=F.TACTICAL_BUDGET_REPORT_INVALID)
    n = 0
    for sid, rr in reports.items():
        scenario = scenarios.get(sid)
        profile = profiles.get(rr.get("tactical_profile_id"))
        if scenario is None or profile is None:
            rep.check("bg::{}::resolvable".format(sid), False,
                      "unresolved scenario/profile for budget", code=F.TACTICAL_BUDGET_REPORT_INVALID)
            continue
        n += 1
        br = RT.build_budget_report(scenario, rr, profile)
        fails = [c for c in TC.validate_tactical_budget_report(br, strict=True) if not c[1]]
        rep.check("bg::{}::valid".format(sid), len(fails) == 0,
                  "budget report invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_BUDGET_REPORT_INVALID)
        # honesty: a within-caps scenario classifies pass; recomputed from raw values.
        within = (br["npc_count"] <= br["max_active_tactical_npcs"]
                  and br["decisions_per_minute"] <= br["max_decisions_per_minute"])
        rep.check("bg::{}::result_recomputed".format(sid),
                  (br["budget_result"] == "pass") == within,
                  "budget_result {} does not match recomputed within-caps={}".format(
                      br["budget_result"], within),
                  code=F.TACTICAL_BUDGET_EXCEEDED)
        (BUDGET_DIR / (br["budget_report_id"] + ".json")).write_text(
            json.dumps(br, indent=2, sort_keys=True), encoding="utf-8")
    rep.check("count::budget_reports_24", n == SP.EXPECTED_SCENARIO_COUNT,
              "must produce 24 budget reports (got {})".format(n),
              code=F.TACTICAL_BUDGET_REPORT_INVALID)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical budget gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_budgets", strict=strict)
    n = validate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-tactical-budgets", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.budgets.v1"))
    BUDGET_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(BUDGET_DIR, "validate_tactical_budgets_report.json")
    rep.print_summary("validate-tactical-budgets")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
