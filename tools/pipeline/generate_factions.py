#!/usr/bin/env python3
"""generate_factions.py — v2.2 Wave 2 faction authoring generator (Agent 4).

Generates the 4-faction roster (FactionDefinition), the initial FactionState vector
for each (bounded values + a relationship matrix), and a quest-linked delta-rule
index derived from the generated quests. Deterministic: derived purely from
quest_faction_spec + the quest matrix; no wall-clock, no randomness, no
economy/diplomacy expansion.

Deliverables (handoff §12 Agent 4):
    procedural/generated/factions/*.json                   (definitions)
    procedural/generated/factions/faction_roster.json      (index)
    procedural/generated/factions/initial_faction_state.json
    procedural/generated/factions/faction_delta_rules.json (quest-linked index)
    procedural/reports/quest_faction/authoring/faction_authoring_report.json

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_factions.py --strict
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

FACTIONS_DIR = REPO_ROOT / "procedural" / "generated" / "factions"
QUESTS_DIR = REPO_ROOT / "procedural" / "generated" / "quests"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "authoring"

# Symmetric initial relationship matrix (bounded [-100, 100]).
INITIAL_RELATIONSHIPS = {
    ("wardens", "surveyors"): 10,
    ("wardens", "salvagers"): -5,
    ("wardens", "outriders"): 15,
    ("surveyors", "salvagers"): -10,
    ("surveyors", "outriders"): 5,
    ("salvagers", "outriders"): 0,
}
# Initial influence per faction class (bounded [0, 100]).
CLASS_INFLUENCE = {"protector": 45, "explorer": 35, "extractor": 40,
                   "stabilizer": 40, "opportunist": 30}


def _rel(a, b):
    return INITIAL_RELATIONSHIPS.get((a, b), INITIAL_RELATIONSHIPS.get((b, a), 0))


def _definition(entry):
    return QF._example_faction_definition(
        faction_id=entry["faction_id"],
        display_key=entry["display_key"],
        faction_class=entry["faction_class"],
        preferred_quest_archetypes=list(entry["preferred_quest_archetypes"]),
        opposed_quest_archetypes=list(entry["opposed_quest_archetypes"]),
        standing_bounds=list(QF.STANDING_BOUNDS),
        influence_bounds=list(QF.INFLUENCE_BOUNDS),
        relationship_bounds=list(QF.RELATIONSHIP_BOUNDS),
        risk_profile=entry["risk_profile"],
        territory_tags=list(entry["territory_tags"]),
        resource_tags=list(entry["resource_tags"]),
        hazard_tags=list(entry["hazard_tags"]),
        hazard_sensitivity=entry["hazard_sensitivity"])


def _initial_state(entry):
    fid = entry["faction_id"]
    relationships = {o: _rel(fid, o) for o in SPEC.FACTION_IDS if o != fid}
    resources = {tag: 10 for tag in entry["resource_tags"]}
    return QF._example_faction_state(
        faction_id=fid,
        run_id="initial_faction_state",
        standing=0,
        influence=CLASS_INFLUENCE[entry["faction_class"]],
        trust=50,
        alarm=5,
        resources=resources,
        territory_pressure=10,
        relationships=relationships,
        active_quest_ids=[],
        completed_quest_ids=[],
        failed_quest_ids=[],
        state_hash="sha256:initial:" + fid,
        created_at=QF.AUTHORING_TS)


def _delta_rule_index():
    """Which quests emit deltas onto each faction (derived from quest defs)."""
    idx = {fid: [] for fid in SPEC.FACTION_IDS}
    for qp in sorted(QUESTS_DIR.glob("*.json")):
        if qp.name == "quest_matrix.json":
            continue
        q = json.loads(qp.read_text(encoding="utf-8"))
        for rule in q.get("faction_delta_rules", []):
            tid = rule.get("target_faction_id")
            if tid in idx:
                idx[tid].append({"quest_id": q["quest_id"],
                                 "on_outcome": rule.get("on_outcome"),
                                 "reason_code": rule.get("reason_code")})
    return idx


def generate(rep):
    FACTIONS_DIR.mkdir(parents=True, exist_ok=True)
    roster = {"schema_version": "wf.quest_faction.faction_roster.v1",
              "report_type": "wf.quest_faction.faction_roster.v1",
              "created_by": "worldforge.v2.2", "faction_count": 0, "factions": []}
    initial = {"schema_version": "wf.quest_faction.initial_faction_state.v1",
               "report_type": "wf.quest_faction.initial_faction_state.v1",
               "created_by": "worldforge.v2.2", "states": {}}

    n = 0
    for entry in SPEC.FACTION_ROSTER:
        fid = entry["faction_id"]
        n += 1
        d = _definition(entry)
        dfails = [c for c in QF.validate_faction_definition(d, strict=True) if not c[1]]
        rep.check("faction::{}::definition_valid".format(fid), len(dfails) == 0,
                  "faction definition invalid: {}".format([c[0] for c in dfails][:4]),
                  code=F.FACTION_CONTRACT_INVALID)
        (FACTIONS_DIR / (fid + ".json")).write_text(
            json.dumps(d, indent=2, sort_keys=True), encoding="utf-8")

        st = _initial_state(entry)
        sfails = [c for c in QF.validate_faction_state(st, strict=True) if not c[1]]
        rep.check("faction::{}::initial_state_valid".format(fid), len(sfails) == 0,
                  "initial faction state invalid: {}".format([c[0] for c in sfails][:4]),
                  code=F.FACTION_STATE_INVALID)
        initial["states"][fid] = st
        roster["factions"].append({
            "faction_id": fid, "faction_class": entry["faction_class"],
            "preferred_quest_archetypes": entry["preferred_quest_archetypes"],
            "definition_path": "procedural/generated/factions/{}.json".format(fid)})

    roster["faction_count"] = n
    (FACTIONS_DIR / "faction_roster.json").write_text(
        json.dumps(roster, indent=2, sort_keys=True), encoding="utf-8")
    (FACTIONS_DIR / "initial_faction_state.json").write_text(
        json.dumps(initial, indent=2, sort_keys=True), encoding="utf-8")

    # quest-linked delta-rule index (requires quests already generated).
    delta_idx = _delta_rule_index()
    (FACTIONS_DIR / "faction_delta_rules.json").write_text(
        json.dumps({"schema_version": "wf.quest_faction.faction_delta_rules.v1",
                    "report_type": "wf.quest_faction.faction_delta_rules.v1",
                    "created_by": "worldforge.v2.2", "by_faction": delta_idx},
                   indent=2, sort_keys=True), encoding="utf-8")

    # coverage guarantees (handoff §12 Agent 4 required proof).
    rep.check("factions::count_in_range",
              QF.MIN_FACTIONS <= n <= QF.MAX_FACTIONS,
              "must generate {}-{} factions (got {})".format(
                  QF.MIN_FACTIONS, QF.MAX_FACTIONS, n),
              code=F.FACTION_CONTRACT_INVALID)
    # every relationship target resolves to the roster.
    roster_ids = set(SPEC.FACTION_IDS)
    for fid, st in initial["states"].items():
        for other in st["relationships"]:
            rep.check("factions::{}::rel_resolves::{}".format(fid, other),
                      other in roster_ids,
                      "relationship target {} not in roster".format(other),
                      code=F.FACTION_RELATIONSHIP_INVALID)
    # every faction is a delta target for >=1 quest (no inert faction).
    for fid, rules in delta_idx.items():
        rep.check("factions::{}::has_quest_link".format(fid), len(rules) >= 1,
                  "faction {} is never a quest delta target".format(fid),
                  code=F.FACTION_STATE_NOT_MUTATED)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 faction authoring generator.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = generate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="generate-factions", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.quest_faction.faction_authoring.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "faction_authoring_report.json")
    rep.print_summary("generate-factions")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
