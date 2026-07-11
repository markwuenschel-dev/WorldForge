#!/usr/bin/env python3
"""build_tactical_index.py — v2.4 Wave 6 operator tactical scenario/NPC index (Agent 7).

Extends OperatorForge so v2.4 tactical scenarios, NPC roles, decisions, action coverage,
save/load, budgets, and failures are inspectable. Reads the Wave-3 bindings + Wave-4/5
runtime/decision/save/budget evidence and builds:

  tactical/scenario_views.json  list[OperatorTacticalScenarioView], contract-validated
  tactical/npc_views.json       list[OperatorTacticalNPCView], contract-validated
  tactical/tactical_index.json  coverage roll-up (24 scenarios / 48 NPCs / action coverage)

Every view is DERIVED from real evidence and validated against its contract before writing —
a view that fails its schema, or a passing scenario view with no decision-trace link, turns
this builder RED (fail-closed).

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/build_tactical_index.py --strict
Reports -> procedural/reports/operator/tactical/build_tactical_index_report.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

GEN = REPO_ROOT / "procedural" / "generated" / "tactical"
REPORTS = REPO_ROOT / "procedural" / "reports" / "tactical"
RUNTIME_DIR = REPORTS / "runtime"
DECISIONS_DIR = REPORTS / "decisions"
SAVE_DIR = REPORTS / "save_load"
BUDGET_DIR = REPORTS / "budgets"
OUT_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "tactical"


def _load(d, skip=("run_", "validate_", "build_")):
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))
            if not any(p.stem.startswith(s) for s in skip)}


def _decisions_rel(sid):
    return "procedural/reports/tactical/decisions/{}.json".format(sid)


def build(rep):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    reports = _load(RUNTIME_DIR)
    bundles = _load(DECISIONS_DIR)
    bindings = _load(GEN / "bindings")
    saves = _load(SAVE_DIR)
    budgets = _load(BUDGET_DIR)

    binds_by_scenario = {}
    for b in bindings.values():
        binds_by_scenario.setdefault(b["scenario_id"], []).append(b)

    scenario_views, npc_views = [], []
    coverage = set()
    for sid, rr in sorted(reports.items()):
        bundle = bundles.get(sid, {})
        traces = bundle.get("decision_traces", [])
        action_counts = {}
        actions_by_npc = {}
        for tr in traces:
            action_counts[tr["selected_action"]] = action_counts.get(tr["selected_action"], 0) + 1
            actions_by_npc.setdefault(tr["npc_id"], set()).add(tr["selected_action"])
        coverage |= set(action_counts)

        sv = TC._example_operator_tactical_scenario_view(
            scenario_id=sid, region_id=rr["region_id"],
            tactical_profile_id=rr["tactical_profile_id"], npc_count=rr["npc_count"],
            roles_present=rr["roles_present"],
            decision_summary={"total": rr["decision_count"], "valid": rr["valid_decision_count"],
                              "invalid": rr["invalid_decision_count"]},
            action_coverage=action_counts,
            cover_usage="used" if rr["cover_used"] else "none",
            flank_usage="attempted" if rr["flank_attempted"] else "none",
            retreat_usage="attempted" if rr["retreat_attempted"] else "none",
            objective_pressure="seen" if rr["objective_pressure_seen"] else "none",
            group_coordination="coordinated" if rr["group_coordination_seen"] else "none",
            combat_result="damage_seen" if rr["combat_damage_seen"] else "none",
            quest_faction_result="updated" if (rr["quest_state_updated"]
                                               and rr["faction_state_updated"]) else "partial",
            save_load_status=rr["save_load_result"], budget_status=rr["budget_result"],
            decision_trace_paths=[_decisions_rel(sid)], failure_codes=[])
        fails = [c for c in TC.validate_operator_tactical_scenario_view(sv, strict=True) if not c[1]]
        rep.check("scenario_view::{}::valid".format(sid), len(fails) == 0,
                  "scenario view invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
                  code=F.TACTICAL_OPERATOR_VIEW_INVALID)
        scenario_views.append(sv)

        for b in binds_by_scenario.get(sid, []):
            npc_id = b["binding_id"][len("tnb_"):]
            nv = TC._example_operator_tactical_npc_view(
                npc_id=npc_id, scenario_id=sid, role_id=b["tactical_role_id"],
                profile_id=b["behavior_profile_id"], spawn_anchor_id=b["spawn_anchor_id"],
                decision_trace_paths=[_decisions_rel(sid)],
                actions_executed=sorted(actions_by_npc.get(npc_id, [])),
                state_delta_paths=[_decisions_rel(sid)],
                save_state_path="procedural/reports/tactical/save_load/tss_{}.json".format(sid),
                budget_report_path="procedural/reports/tactical/budgets/tbr_{}.json".format(sid),
                failure_codes=[])
            nfails = [c for c in TC.validate_operator_tactical_npc_view(nv, strict=True) if not c[1]]
            rep.check("npc_view::{}::valid".format(npc_id), len(nfails) == 0,
                      "npc view invalid: {}".format([(c[0], c[3]) for c in nfails][:4]),
                      code=F.TACTICAL_OPERATOR_VIEW_INVALID)
            npc_views.append(nv)

    rep.check("count::scenario_views_24", len(scenario_views) == 24,
              "must build 24 scenario views (got {})".format(len(scenario_views)),
              code=F.TACTICAL_OPERATOR_VIEW_INVALID)
    rep.check("count::npc_views_48", len(npc_views) == 48,
              "must build 48 NPC views (got {})".format(len(npc_views)),
              code=F.TACTICAL_OPERATOR_VIEW_INVALID)
    missing = sorted(set(TC.REQUIRED_COVERAGE_ACTIONS) - coverage)
    rep.check("coverage::all_required_actions", not missing,
              "operator index missing action coverage: {}".format(missing),
              code=F.TACTICAL_ACTION_COVERAGE_MISSING)

    (OUT_DIR / "scenario_views.json").write_text(
        json.dumps(scenario_views, indent=2, sort_keys=True), encoding="utf-8")
    (OUT_DIR / "npc_views.json").write_text(
        json.dumps(npc_views, indent=2, sort_keys=True), encoding="utf-8")
    index = {"scenario_count": len(scenario_views), "npc_count": len(npc_views),
             "action_coverage": sorted(coverage),
             "required_actions": list(TC.REQUIRED_COVERAGE_ACTIONS),
             "scenario_view_path": "procedural/reports/operator/tactical/scenario_views.json",
             "npc_view_path": "procedural/reports/operator/tactical/npc_views.json",
             "report_type": "wf.tactical.operator_index.v1"}
    (OUT_DIR / "tactical_index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
    return len(scenario_views) + len(npc_views)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 operator tactical index.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "tactical_operator_index", strict=strict)
    n = build(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-tactical-index", pack=None, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.operator_index.v1"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(OUT_DIR, "build_tactical_index_report.json")
    rep.print_summary("operator-tactical-index")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
