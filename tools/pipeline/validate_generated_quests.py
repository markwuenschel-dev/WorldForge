#!/usr/bin/env python3
"""validate_generated_quests.py — v2.2 Wave 2 generated-quest authoring gate.

Re-validates every generated QuestDefinition + QuestStep from disk against
quest_faction_contracts AND performs the cross-record resolution the schema-only
contracts cannot: scenario bindings resolve to real v2.0 slice scenarios, faction
references resolve to the roster, reward bindings resolve to the scenario's reward
table, step files exist with contiguous order, and delta-rule targets resolve.

This is the gate that catches an orphan reward binding, a quest pointing at a
scenario that does not exist, or a step whose file was never written — none of which
the in-record contract can see.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_generated_quests.py --strict
Reports -> procedural/reports/quest_faction/authoring/validate_generated_quests_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import quest_faction_contracts as QF
import quest_faction_spec as SPEC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

SLICE_SCN_DIR = REPO_ROOT / "procedural" / "generated" / "slice" / "scenarios"
QUESTS_DIR = REPO_ROOT / "procedural" / "generated" / "quests"
STEPS_DIR = QUESTS_DIR / "steps"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "authoring"


def _slice_index():
    idx = {}
    for p in sorted(SLICE_SCN_DIR.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        idx[d["slice_scenario_id"]] = d
    return idx


def validate(rep):
    scn_idx = _slice_index()
    roster = set(SPEC.FACTION_IDS)
    quest_files = [p for p in sorted(QUESTS_DIR.glob("*.json"))
                   if p.name != "quest_matrix.json"]
    rep.check("quests::present", len(quest_files) == QF.EXPECTED_SCENARIO_COUNT,
              "expected {} quest files (got {})".format(
                  QF.EXPECTED_SCENARIO_COUNT, len(quest_files)),
              code=F.QUEST_FACTION_PARTIAL_MATRIX)

    archetypes = set()
    bound_scenarios = set()
    n = 0
    for qp in quest_files:
        q = json.loads(qp.read_text(encoding="utf-8"))
        n += 1
        qid = q.get("quest_id", qp.stem)
        # 1. schema contract
        fails = [c for c in QF.validate_quest_definition(q, strict=True) if not c[1]]
        rep.check("q::{}::contract".format(qid), len(fails) == 0,
                  "quest fails contract: {}".format([c[0] for c in fails][:4]),
                  code=F.QUEST_CONTRACT_INVALID)
        archetypes.add(q.get("quest_archetype"))
        # 2. scenario bindings resolve to real v2.0 scenarios
        for sid in q.get("scenario_bindings", []):
            bound_scenarios.add(sid)
            rep.check("q::{}::binding_resolves::{}".format(qid, sid), sid in scn_idx,
                      "scenario binding {} does not resolve to a v2.0 slice scenario".format(sid),
                      code=F.QUEST_SCENARIO_BINDING_MISSING)
        # 3. faction references resolve to the roster
        rep.check("q::{}::requesting_resolves".format(qid),
                  q.get("requesting_faction_id") in roster,
                  "requesting_faction_id {} not in roster".format(q.get("requesting_faction_id")),
                  code=F.FACTION_UNKNOWN_ID)
        for fid in q.get("affected_faction_ids", []):
            rep.check("q::{}::affected_resolves::{}".format(qid, fid), fid in roster,
                      "affected faction {} not in roster".format(fid),
                      code=F.FACTION_UNKNOWN_ID)
        # 4. reward binding resolves to the scenario's reward table (no orphan)
        binds = q.get("scenario_bindings", [])
        if binds and binds[0] in scn_idx:
            expected_rwt = scn_idx[binds[0]].get("expected_reward_table_id")
            rep.check("q::{}::reward_binding_resolves".format(qid),
                      q.get("reward_binding") == expected_rwt,
                      "reward_binding {!r} != scenario reward table {!r}".format(
                          q.get("reward_binding"), expected_rwt),
                      code=F.QUEST_REWARD_BINDING_INVALID)
        # 5. step files exist, contiguous order, bound to this quest + scenario
        step_ids = q.get("quest_steps", [])
        orders = []
        for st_id in step_ids:
            sp = STEPS_DIR / (st_id + ".json")
            if not sp.is_file():
                rep.check("q::{}::step_file::{}".format(qid, st_id), False,
                          "step file missing: {}".format(sp.name),
                          code=F.QUEST_STEP_INVALID)
                continue
            st = json.loads(sp.read_text(encoding="utf-8"))
            sfails = [c for c in QF.validate_quest_step(st, strict=True) if not c[1]]
            rep.check("q::{}::step_contract::{}".format(qid, st_id), len(sfails) == 0,
                      "step fails contract: {}".format([c[0] for c in sfails][:4]),
                      code=F.QUEST_STEP_INVALID)
            rep.check("q::{}::step_quest_link::{}".format(qid, st_id),
                      st.get("quest_id") == qid,
                      "step {} quest_id mismatch".format(st_id),
                      code=F.QUEST_STEP_INVALID)
            rep.check("q::{}::step_scenario_link::{}".format(qid, st_id),
                      st.get("target_scenario_id") in binds,
                      "step {} target_scenario_id not in quest bindings".format(st_id),
                      code=F.QUEST_SCENARIO_BINDING_MISSING)
            orders.append(st.get("step_order"))
        # contiguous 1..N
        rep.check("q::{}::step_order_contiguous".format(qid),
                  sorted(orders) == list(range(1, len(orders) + 1)) and len(orders) > 0,
                  "step_order must be contiguous 1..N (got {})".format(sorted(orders)),
                  code=F.QUEST_STEP_ORDER_INVALID)
        # 6. at least one required (non-optional) step, and success needs required steps
        req_steps = []
        for st_id in step_ids:
            sp = STEPS_DIR / (st_id + ".json")
            if sp.is_file() and not json.loads(sp.read_text(encoding="utf-8")).get("optional"):
                req_steps.append(st_id)
        rep.check("q::{}::has_required_step".format(qid), len(req_steps) >= 1,
                  "quest must have >=1 required (non-optional) step",
                  code=F.QUEST_STEP_INVALID)
        # 7. delta-rule targets resolve + are in requesting/affected set
        allowed_targets = {q.get("requesting_faction_id")} | set(q.get("affected_faction_ids", []))
        for rule in q.get("faction_delta_rules", []):
            tid = rule.get("target_faction_id")
            rep.check("q::{}::delta_target::{}".format(qid, tid),
                      tid in roster and tid in allowed_targets,
                      "delta rule target {} not in roster/affected set".format(tid),
                      code=F.FACTION_UNKNOWN_ID)

    # coverage
    rep.check("quests::3_core_archetypes",
              set(archetypes) == set(SPEC.MISSION_TO_QUEST_ARCHETYPE.values()),
              "all 3 core archetypes must be represented (got {})".format(sorted(archetypes)),
              code=F.QUEST_UNKNOWN_ARCHETYPE)
    rep.check("quests::all_24_scenarios_bound",
              bound_scenarios == set(scn_idx.keys()),
              "quests must bind all 24 v2.0 scenarios (missing {})".format(
                  sorted(set(scn_idx.keys()) - bound_scenarios)[:4]),
              code=F.QUEST_FACTION_PARTIAL_MATRIX)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 generated-quest authoring gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = validate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-generated-quests", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.quest_faction.generated_quest_validation.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_generated_quests_report.json")
    rep.print_summary("validate-generated-quests")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
