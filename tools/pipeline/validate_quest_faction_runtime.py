#!/usr/bin/env python3
"""validate_quest_faction_runtime.py — v2.2 Wave 3 runtime-evidence gate.

Reads every produced runtime report + quest state + consequence ledger from disk and
proves the runtime matrix is real and complete: 24/24 scenarios, each report
contract-valid with empty failure_codes, its consequence_ledger_path exists on disk,
the ledger shows a real mutation (post hash != pre hash), the faction state mutated,
and next-mission state is available. Also proves world faction state PERSISTED
(differs from the initial roster state).

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_quest_faction_runtime.py --strict
Reports -> procedural/reports/quest_faction/runtime/validate_quest_faction_runtime_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import quest_faction_contracts as QF
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

RUNTIME_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "runtime"
FACTIONS_DIR = REPO_ROOT / "procedural" / "generated" / "factions"
SLICE_SCN_DIR = REPO_ROOT / "procedural" / "generated" / "slice" / "scenarios"
REPORT_DIR = RUNTIME_DIR


def validate(rep):
    slice_ids = {json.loads(p.read_text(encoding="utf-8"))["slice_scenario_id"]
                 for p in SLICE_SCN_DIR.glob("*.json")}
    run_dirs = sorted([d for d in RUNTIME_DIR.iterdir()
                       if d.is_dir() and (d / "report.json").is_file()])
    rep.check("runtime::count_24", len(run_dirs) == QF.EXPECTED_SCENARIO_COUNT,
              "expected {} runtime runs (got {})".format(
                  QF.EXPECTED_SCENARIO_COUNT, len(run_dirs)),
              code=F.QUEST_FACTION_PARTIAL_MATRIX)

    seen_scenarios, outcomes = set(), {}
    n = 0
    for d in run_dirs:
        n += 1
        report = json.loads((d / "report.json").read_text(encoding="utf-8"))
        rid = report.get("run_id", d.name)
        fails = [c for c in QF.validate_runtime_report(report, strict=True) if not c[1]]
        rep.check("rt::{}::report_valid".format(rid), len(fails) == 0,
                  "runtime report invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.QUEST_FACTION_RUNTIME_REPORT_INVALID)
        rep.check("rt::{}::no_failure_codes".format(rid),
                  report.get("failure_codes") == [],
                  "clean report must carry empty failure_codes",
                  code=F.QUEST_OUTCOME_EVIDENCE_MISSING)
        seen_scenarios.add(report.get("scenario_id"))
        outcomes[report.get("quest_outcome")] = outcomes.get(report.get("quest_outcome"), 0) + 1

        # quest state present + valid
        qs = json.loads((d / "quest_state.json").read_text(encoding="utf-8"))
        qfails = [c for c in QF.validate_quest_runtime_state(qs, strict=True) if not c[1]]
        rep.check("rt::{}::quest_state_valid".format(rid), len(qfails) == 0,
                  "quest state invalid: {}".format([c[0] for c in qfails][:4]),
                  code=F.QUEST_RUNTIME_STATE_INVALID)

        # ledger path resolves on disk + ledger valid + real mutation
        lp = report.get("consequence_ledger_path", "")
        lpath = REPO_ROOT / lp
        rep.check("rt::{}::ledger_exists".format(rid), bool(lp) and lpath.is_file(),
                  "consequence_ledger_path does not resolve: {}".format(lp),
                  code=F.CONSEQUENCE_LEDGER_MISSING)
        if lpath.is_file():
            ledger = json.loads(lpath.read_text(encoding="utf-8"))
            lfails = [c for c in QF.validate_consequence_ledger(ledger, strict=True) if not c[1]]
            rep.check("rt::{}::ledger_valid".format(rid), len(lfails) == 0,
                      "ledger invalid: {}".format([c[0] for c in lfails][:4]),
                      code=F.CONSEQUENCE_LEDGER_INVALID)
            rep.check("rt::{}::ledger_mutation".format(rid),
                      ledger.get("pre_faction_state_hash") != ledger.get("post_faction_state_hash"),
                      "ledger must show post != pre faction hash",
                      code=F.FACTION_STATE_NOT_MUTATED)
            rep.check("rt::{}::ledger_run_link".format(rid),
                      ledger.get("run_id") == rid,
                      "ledger run_id must match report run_id",
                      code=F.CONSEQUENCE_LEDGER_INVALID)

        rep.check("rt::{}::faction_mutated".format(rid),
                  report.get("faction_state_mutated") is True,
                  "outcome-bearing report must mutate faction state",
                  code=F.FACTION_STATE_NOT_MUTATED)
        rep.check("rt::{}::next_state".format(rid),
                  report.get("next_mission_state_available") is True,
                  "next-mission state must be available",
                  code=F.QUEST_FACTION_NEXT_STATE_MISSING)

    # coverage: all 24 slice scenarios seen
    rep.check("runtime::all_scenarios_seen", seen_scenarios == slice_ids,
              "runtime must cover all 24 slice scenarios (missing {})".format(
                  sorted(slice_ids - seen_scenarios)[:4]),
              code=F.QUEST_FACTION_PARTIAL_MATRIX)
    # at least the three outcome-bearing outcomes exercised
    rep.check("runtime::outcome_variety",
              set(outcomes.keys()) >= {"success", "partial_success", "failure"},
              "runtime must exercise success/partial_success/failure (got {})".format(outcomes),
              code=F.QUEST_OUTCOME_EVIDENCE_MISSING)

    # persistence: cumulative world state differs from the initial roster state
    wpath = RUNTIME_DIR / "world_faction_state.json"
    ipath = FACTIONS_DIR / "initial_faction_state.json"
    rep.check("runtime::world_state_present", wpath.is_file(),
              "world_faction_state.json missing", code=F.QUEST_FACTION_NEXT_STATE_MISSING)
    if wpath.is_file() and ipath.is_file():
        world = json.loads(wpath.read_text(encoding="utf-8"))["states"]
        initial = json.loads(ipath.read_text(encoding="utf-8"))["states"]
        mutated = any(world[f].get("standing") != initial[f].get("standing")
                      or world[f].get("completed_quest_ids") != initial[f].get("completed_quest_ids")
                      for f in initial)
        rep.check("runtime::world_state_persisted", mutated,
                  "world faction state must differ from initial (persistence)",
                  code=F.FACTION_STATE_NOT_MUTATED)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 runtime-evidence gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = validate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-quest-faction-runtime", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.quest_faction.runtime_validation.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_quest_faction_runtime_report.json")
    rep.print_summary("validate-quest-faction-runtime")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
