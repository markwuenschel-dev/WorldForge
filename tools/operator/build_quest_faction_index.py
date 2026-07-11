#!/usr/bin/env python3
"""build_quest_faction_index.py — v2.2 Wave 4 operator quest/faction index (Agent 6).

Extends OperatorForge so v2.2 quests, factions, deltas, and consequence ledgers are
inspectable. Reads the Wave-3 runtime evidence and builds:

  index/quest_views.json    list[OperatorQuestView], contract-validated
  index/faction_views.json  list[OperatorFactionView], contract-validated
  index/quest_faction_index.json  coverage roll-up (24 quests / 4 factions)

Every view is DERIVED from real evidence (runtime reports, quest states, ledgers,
per-run faction states) and validated against its contract before it is written — a
view that fails its schema, or that would claim a passing outcome without a real
ledger link, turns this builder RED (fail-closed). OperatorForge INDEXES evidence;
it never makes stale/missing evidence true.

FAIL-CLOSED: absent runtime evidence -> RED (run run-quest-faction-runtime first).

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/build_quest_faction_index.py --strict
Reports -> procedural/reports/operator/index/build_quest_faction_index_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import quest_faction_contracts as QF
import quest_faction_spec as SPEC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

RUNTIME_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "runtime"
FACTIONS_DIR = REPO_ROOT / "procedural" / "generated" / "factions"
INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
REPORT_DIR = INDEX_DIR
RUNTIME_REL = "procedural/reports/quest_faction/runtime"


def _run_records():
    """Yield (run_id, report, quest_state, faction_post, ledger) for each run, in order."""
    for d in sorted(p for p in RUNTIME_DIR.iterdir()
                    if p.is_dir() and (p / "report.json").is_file()):
        report = json.loads((d / "report.json").read_text(encoding="utf-8"))
        qs = json.loads((d / "quest_state.json").read_text(encoding="utf-8"))
        fp = json.loads((d / "faction_state_post.json").read_text(encoding="utf-8"))
        ledger_path = REPO_ROOT / report["consequence_ledger_path"]
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.is_file() else {}
        yield d.name, report, qs, fp, ledger


def _quest_view(report, qs, ledger):
    steps = [{"step_id": s, "status": "completed"} for s in qs.get("completed_steps", [])]
    steps += [{"step_id": s, "status": "failed"} for s in qs.get("failed_steps", [])]
    return QF._example_operator_quest_view(
        quest_id=report["quest_id"], quest_archetype=report["quest_archetype"],
        requesting_faction_id=report["requesting_faction_id"],
        affected_faction_ids=report["affected_faction_ids"],
        scenario_ids=[report["scenario_id"]], step_statuses=steps,
        runtime_outcomes=[report["quest_outcome"]],
        faction_deltas=ledger.get("applied_deltas", []),
        consequence_ledger_paths=[report["consequence_ledger_path"]],
        save_load_status=report["save_load_result"],
        next_mission_hooks=ledger.get("next_mission_hooks", []),
        failure_codes=report["failure_codes"])


def build(rep, git_sha):
    runs = list(_run_records())
    rep.check("index::runtime_present", len(runs) == QF.EXPECTED_SCENARIO_COUNT,
              "expected {} runtime runs (got {})".format(QF.EXPECTED_SCENARIO_COUNT, len(runs)),
              code=F.QUEST_FACTION_PARTIAL_MATRIX)

    # --- quest views -----------------------------------------------------------
    quest_views = []
    for run_id, report, qs, fp, ledger in runs:
        qv = _quest_view(report, qs, ledger)
        fails = [c for c in QF.validate_operator_quest_view(qv, strict=True) if not c[1]]
        rep.check("qview::{}::valid".format(qv["quest_id"]), len(fails) == 0,
                  "quest view invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.QUEST_FACTION_OPERATOR_VIEW_INVALID)
        quest_views.append(qv)

    # --- faction views (histories replayed across runs in order) ---------------
    initial = json.loads((FACTIONS_DIR / "initial_faction_state.json").read_text(encoding="utf-8"))["states"]
    hist = {fid: {"standing": [initial[fid]["standing"]],
                  "influence": [initial[fid]["influence"]],
                  "trust": [initial[fid]["trust"]],
                  "alarm": [initial[fid]["alarm"]],
                  "relationship": [dict(initial[fid]["relationships"])],
                  "quests": [], "state_paths": []} for fid in SPEC.FACTION_IDS}
    for run_id, report, qs, fp, ledger in runs:
        state_path = "{}/{}/faction_state_post.json".format(RUNTIME_REL, run_id)
        for fid, st in fp.items():
            h = hist[fid]
            h["standing"].append(st["standing"])
            h["influence"].append(st["influence"])
            h["trust"].append(st["trust"])
            h["alarm"].append(st["alarm"])
            h["relationship"].append(dict(st["relationships"]))
            h["quests"].append(report["quest_id"])
            h["state_paths"].append(state_path)

    faction_views = []
    for fid in SPEC.FACTION_IDS:
        h = hist[fid]
        state_paths = h["state_paths"] + ["{}/world_faction_state.json".format(RUNTIME_REL)]
        fv = QF._example_operator_faction_view(
            faction_id=fid,
            definition_path="procedural/generated/factions/{}.json".format(fid),
            state_paths=state_paths,
            standing_history=h["standing"], influence_history=h["influence"],
            trust_history=h["trust"], alarm_history=h["alarm"],
            quest_history=h["quests"], relationship_history=h["relationship"],
            active_failure_codes=[])
        fails = [c for c in QF.validate_operator_faction_view(fv, strict=True) if not c[1]]
        rep.check("fview::{}::valid".format(fid), len(fails) == 0,
                  "faction view invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.QUEST_FACTION_OPERATOR_VIEW_INVALID)
        faction_views.append(fv)

    # --- persist index files ---------------------------------------------------
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    (INDEX_DIR / "quest_views.json").write_text(
        json.dumps(quest_views, indent=2, sort_keys=True), encoding="utf-8")
    (INDEX_DIR / "faction_views.json").write_text(
        json.dumps(faction_views, indent=2, sort_keys=True), encoding="utf-8")
    coverage = {
        "schema_version": "wf.quest_faction.operator_index.v1",
        "report_type": "wf.quest_faction.operator_index.v1",
        "created_by": "worldforge.v2.2", "created_at": "live", "git_sha": git_sha,
        "quest_view_count": len(quest_views), "faction_view_count": len(faction_views),
        "quest_view_path": "procedural/reports/operator/index/quest_views.json",
        "faction_view_path": "procedural/reports/operator/index/faction_views.json",
    }
    (INDEX_DIR / "quest_faction_index.json").write_text(
        json.dumps(coverage, indent=2, sort_keys=True), encoding="utf-8")

    rep.check("index::24_quest_views", len(quest_views) == QF.EXPECTED_SCENARIO_COUNT,
              "expected 24 quest views (got {})".format(len(quest_views)),
              code=F.QUEST_FACTION_PARTIAL_MATRIX)
    rep.check("index::4_faction_views", len(faction_views) == len(SPEC.FACTION_IDS),
              "expected {} faction views (got {})".format(len(SPEC.FACTION_IDS), len(faction_views)),
              code=F.QUEST_FACTION_OPERATOR_VIEW_INVALID)
    return len(quest_views) + len(faction_views)


def _git_sha():
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
                              capture_output=True, text=True).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 operator quest/faction index builder.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "quest_faction_operator_index", strict=strict)
    n = build(rep, _git_sha())

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-quest-faction-index", pack=None, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.quest_faction.operator_index.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "build_quest_faction_index_report.json")
    rep.print_summary("operator-quest-faction-index")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
