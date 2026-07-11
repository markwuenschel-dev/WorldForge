#!/usr/bin/env python3
"""generate_quests.py — v2.2 Wave 2 quest authoring generator (Agent 3).

Generates one bounded QuestDefinition (+ its ordered QuestStep records) for each of
the 24 v2.0 vertical-slice scenarios, mapping the v2.0 mission archetype onto the
v2.2 quest archetype (survey_landmark->Survey, recover_resource->Recovery,
clear_hazard->HazardClearance). Deterministic: derived purely from the slice
scenario files + quest_faction_spec; no wall-clock, no randomness.

Each quest is a validated state machine over the scenario's actions:
  step1 reach_objective (required)  -> step2 archetype action (required)
  -> stepN extract_reward (required); "high" pressure adds an optional
  survive_pressure step. Every generated record is validated against
  quest_faction_contracts before it is written — generation never emits a record
  its own contract would reject.

Deliverables (handoff §12 Agent 3):
    procedural/generated/quests/*.json                 (quest definitions)
    procedural/generated/quests/steps/*.json           (quest steps)
    procedural/generated/quests/quest_matrix.json      (index)
    procedural/reports/quest_faction/authoring/quest_authoring_report.json

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_quests.py --strict
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


def _load_slice_scenarios():
    scns = []
    for p in sorted(SLICE_SCN_DIR.glob("*.json")):
        scns.append(json.loads(p.read_text(encoding="utf-8")))
    return scns


def _steps_for(quest_id, scn, archetype):
    """Build the ordered QuestStep records for one quest."""
    map_id = scn["map_id"]
    sid = scn["slice_scenario_id"]
    high = scn.get("encounter_profile") == "high"
    steps = []

    def step(order, obj_type, claims, comp, fail, optional=False):
        return QF._example_quest_step(
            step_id="{}_step{}".format(quest_id, order),
            quest_id=quest_id, step_order=order, objective_type=obj_type,
            target_scenario_id=sid, target_map_id=map_id,
            required_runtime_claims=claims,
            completion_predicate=comp, failure_predicate=fail, optional=optional)

    steps.append(step(1, "reach_objective", ["traversal", "objective"],
                      {"claim": "objective", "op": "==", "value": "reached"},
                      {"claim": "objective", "op": "==", "value": "unreached"}))
    obj_type, claim_cat, value = SPEC.ARCHETYPE_ACTION[archetype]
    claims = [claim_cat] if claim_cat == "objective" else [claim_cat, "objective"]
    steps.append(step(2, obj_type, claims,
                      {"claim": claim_cat, "op": "==", "value": value},
                      {"claim": claim_cat, "op": "==", "value": "failed"}))
    steps.append(step(3, "extract_reward", ["reward", "save_load"],
                      {"claim": "reward", "op": "==", "value": "granted"},
                      {"claim": "reward", "op": "==", "value": "withheld"}))
    if high:
        steps.append(step(4, "survive_pressure", ["pressure"],
                          {"claim": "pressure", "op": ">=", "value": 1},
                          {"claim": "pressure", "op": "==", "value": 0},
                          optional=True))
    return steps


def _quest_for(scn):
    archetype = SPEC.MISSION_TO_QUEST_ARCHETYPE[scn["mission_archetype"]]
    sid = scn["slice_scenario_id"]
    quest_id = "qf_" + sid[len("vs_"):] if sid.startswith("vs_") else "qf_" + sid
    fac = SPEC.ARCHETYPE_FACTIONS[archetype]
    steps = _steps_for(quest_id, scn, archetype)
    quest = QF._example_quest_definition(
        quest_id=quest_id,
        quest_archetype=archetype,
        title_key="quest.{}.{}".format(archetype.lower(), scn["map_id"].lower()),
        requesting_faction_id=fac["requesting"],
        affected_faction_ids=list(fac["affected"]),
        scenario_bindings=[sid],
        quest_steps=[s["step_id"] for s in steps],
        success_conditions=["all_required_steps_completed"],
        failure_conditions=["required_step_failed", "pawn_incapacitated"],
        reward_binding=scn["expected_reward_table_id"],
        faction_delta_rules=SPEC.delta_rules_for(archetype),
        next_mission_hooks=["unlock_followup_{}_{}".format(archetype.lower(), scn["biome"])],
        biome=scn["biome"],
        pressure_profile=scn["encounter_profile"],
        seed=scn["seed"])
    return quest, steps


def generate(rep):
    scns = _load_slice_scenarios()
    rep.check("slice_matrix_complete", len(scns) == QF.EXPECTED_SCENARIO_COUNT,
              "expected {} slice scenarios (got {})".format(
                  QF.EXPECTED_SCENARIO_COUNT, len(scns)),
              code=F.QUEST_SCENARIO_BINDING_MISSING)

    QUESTS_DIR.mkdir(parents=True, exist_ok=True)
    STEPS_DIR.mkdir(parents=True, exist_ok=True)
    matrix = {"schema_version": "wf.quest_faction.quest_matrix.v1",
              "report_type": "wf.quest_faction.quest_matrix.v1",
              "created_by": "worldforge.v2.2", "quest_count": 0,
              "archetypes": {}, "quests": []}
    archetypes_seen = set()

    for scn in scns:
        quest, steps = _quest_for(scn)
        # validate before writing — generation must never emit a rejectable record.
        qfails = [c for c in QF.validate_quest_definition(quest, strict=True) if not c[1]]
        rep.check("quest::{}::valid".format(quest["quest_id"]), len(qfails) == 0,
                  "generated quest invalid: {}".format([c[0] for c in qfails][:4]),
                  code=F.QUEST_CONTRACT_INVALID)
        for st in steps:
            sfails = [c for c in QF.validate_quest_step(st, strict=True) if not c[1]]
            rep.check("step::{}::valid".format(st["step_id"]), len(sfails) == 0,
                      "generated step invalid: {}".format([c[0] for c in sfails][:4]),
                      code=F.QUEST_STEP_INVALID)
            (STEPS_DIR / (st["step_id"] + ".json")).write_text(
                json.dumps(st, indent=2, sort_keys=True), encoding="utf-8")
        (QUESTS_DIR / (quest["quest_id"] + ".json")).write_text(
            json.dumps(quest, indent=2, sort_keys=True), encoding="utf-8")
        archetypes_seen.add(quest["quest_archetype"])
        matrix["quests"].append({
            "quest_id": quest["quest_id"],
            "quest_archetype": quest["quest_archetype"],
            "scenario_id": scn["slice_scenario_id"],
            "requesting_faction_id": quest["requesting_faction_id"],
            "step_ids": quest["quest_steps"],
            "reward_binding": quest["reward_binding"],
        })

    matrix["quest_count"] = len(matrix["quests"])
    for a in archetypes_seen:
        matrix["archetypes"][a] = sum(1 for q in matrix["quests"]
                                      if q["quest_archetype"] == a)
    (QUESTS_DIR / "quest_matrix.json").write_text(
        json.dumps(matrix, indent=2, sort_keys=True), encoding="utf-8")

    # coverage guarantees (handoff §12 Agent 3 required proof).
    rep.check("quests::count_24", matrix["quest_count"] == QF.EXPECTED_SCENARIO_COUNT,
              "must generate {} quests (got {})".format(
                  QF.EXPECTED_SCENARIO_COUNT, matrix["quest_count"]),
              code=F.QUEST_FACTION_PARTIAL_MATRIX)
    rep.check("quests::3_archetypes",
              set(archetypes_seen) == set(SPEC.MISSION_TO_QUEST_ARCHETYPE.values()),
              "all 3 core quest archetypes must be represented (got {})".format(
                  sorted(archetypes_seen)),
              code=F.QUEST_UNKNOWN_ARCHETYPE)
    return matrix["quest_count"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 quest authoring generator.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = generate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="generate-quests", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.quest_faction.quest_authoring.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "quest_authoring_report.json")
    rep.print_summary("generate-quests")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
