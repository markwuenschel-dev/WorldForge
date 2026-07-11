#!/usr/bin/env python3
"""quest_faction_negatives.py — v2.2 QuestForge/FactionStateForge negative suite.

Proves the quest/faction schema spine REJECTS known-bad records — and rejects each
one for its OWNING failure code, because a validator that fails for the wrong reason
is not real coverage. Fixtures are generated in-code (no stored files): each is a
canonical quest_faction_contracts._example_* with a single targeted override that
violates exactly one honesty invariant.

Two assertions per fixture: (1) the record IS rejected, and (2) it is rejected for
its owning WF77x-80x code. Plus a reverse dogfood (every valid example still passes
— guards against a "reject everything" fake) and a vacuous-suite guard.

These are the known-bad cases from handoff §7/§10.7: quest with a missing step,
quest with an unknown scenario binding, quest completing without runtime evidence,
quest outcome without a ledger, faction delta out of bounds, unknown faction class,
relationship target invalid, state hash unchanged after a claimed delta, save/load
claimed without proof, malformed next-mission hook, operator view with a broken
ledger link, a partial 23/24 matrix claiming complete, an unknown failure code, and
a stale git_sha.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/quest_faction_negatives.py --strict
Reports -> procedural/reports/quest_faction/negatives/quest_faction_negatives_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import quest_faction_contracts as QF
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "negatives"

QD = QF.validate_quest_definition
QS = QF.validate_quest_step
QR = QF.validate_quest_runtime_state
FD = QF.validate_faction_definition
FS = QF.validate_faction_state
FX = QF.validate_faction_delta
CL = QF.validate_consequence_ledger
RR = QF.validate_runtime_report
QI = QF.validate_evidence_index
OQ = QF.validate_operator_quest_view
OF = QF.validate_operator_faction_view


def cases():
    """Return [(label, validate_fn, known_bad_record, owning_failure_code), ...]."""
    c = []
    e_qd = QF._example_quest_definition
    e_qs = QF._example_quest_step
    e_qr = QF._example_quest_runtime_state
    e_fd = QF._example_faction_definition
    e_fs = QF._example_faction_state
    e_fx = QF._example_faction_delta
    e_cl = QF._example_consequence_ledger
    e_rr = QF._example_runtime_report
    e_qi = QF._example_evidence_index
    e_oq = QF._example_operator_quest_view
    e_of = QF._example_operator_faction_view

    # --- QuestDefinition ---
    c.append(("qd:missing_steps", QD, e_qd(quest_steps=[]), F.QUEST_STEP_INVALID))
    c.append(("qd:no_scenario_binding", QD, e_qd(scenario_bindings=[]),
              F.QUEST_SCENARIO_BINDING_MISSING))
    c.append(("qd:unknown_archetype", QD, e_qd(quest_archetype="EscortConvoy"),
              F.QUEST_UNKNOWN_ARCHETYPE))
    c.append(("qd:no_failure_conditions", QD, e_qd(failure_conditions=[]),
              F.QUEST_COMPLETION_PREDICATE_INVALID))
    c.append(("qd:unbounded_next_hooks", QD,
              e_qd(next_mission_hooks=["h1", "h2", "h3", "h4", "h5"]),
              F.QUEST_NEXT_MISSION_HOOK_INVALID))
    c.append(("qd:too_many_steps", QD,
              e_qd(quest_steps=["s{}".format(i) for i in range(9)]),
              F.QUEST_STEP_INVALID))

    # --- QuestStep ---
    c.append(("qs:unknown_claim_predicate", QS,
              e_qs(completion_predicate={"claim": "vibes", "op": "==", "value": "good"}),
              F.QUEST_COMPLETION_PREDICATE_INVALID))
    c.append(("qs:non_machine_predicate", QS,
              e_qs(completion_predicate="reach the top"),
              F.QUEST_COMPLETION_PREDICATE_INVALID))
    c.append(("qs:bad_objective_type", QS, e_qs(objective_type="negotiate"),
              F.QUEST_STEP_INVALID))
    c.append(("qs:zero_step_order", QS, e_qs(step_order=0), F.QUEST_STEP_ORDER_INVALID))
    c.append(("qs:empty_runtime_claims", QS, e_qs(required_runtime_claims=[]),
              F.QUEST_COMPLETION_PREDICATE_INVALID))

    # --- QuestRuntimeState ---
    c.append(("qr:success_no_deltas", QR, e_qr(faction_deltas_applied=False),
              F.FACTION_STATE_NOT_MUTATED))
    c.append(("qr:completed_missing_required", QR,
              e_qr(completed_steps=["qf_alpine_snow_survey_landmark_baseline_s1_step1"]),
              F.QUEST_OUTCOME_EVIDENCE_MISSING))
    c.append(("qr:reward_granted_no_binding", QR,
              e_qr(reward_granted=True, reward_binding="none"),
              F.QUEST_REWARD_BINDING_INVALID))
    c.append(("qr:bad_state", QR, e_qr(state="winning"), F.QUEST_RUNTIME_STATE_INVALID))

    # --- FactionDefinition ---
    c.append(("fd:unknown_class", FD, e_fd(faction_class="megacorp"),
              F.FACTION_CONTRACT_INVALID))
    c.append(("fd:bad_bounds", FD, e_fd(standing_bounds=[100, -100]),
              F.FACTION_BOUNDS_INVALID))
    c.append(("fd:pref_opp_overlap", FD,
              e_fd(preferred_quest_archetypes=["Survey"], opposed_quest_archetypes=["Survey"]),
              F.FACTION_CONTRACT_INVALID))
    c.append(("fd:unnormalized_tags", FD, e_fd(territory_tags=["Alpine Snow"]),
              F.FACTION_CONTRACT_INVALID))

    # --- FactionState ---
    c.append(("fs:standing_out_of_bounds", FS, e_fs(standing=9999),
              F.FACTION_BOUNDS_INVALID))
    c.append(("fs:bad_relationships", FS, e_fs(relationships={"wardens": 9999}),
              F.FACTION_RELATIONSHIP_INVALID))
    c.append(("fs:active_completed_overlap", FS,
              e_fs(active_quest_ids=["qf_x"], completed_quest_ids=["qf_x"]),
              F.FACTION_STATE_INVALID))
    c.append(("fs:resources_out_of_bounds", FS, e_fs(resources={"survey_data": 99999}),
              F.FACTION_BOUNDS_INVALID))

    # --- FactionDelta ---
    c.append(("fx:standing_over_cap", FX, e_fx(standing_delta=999),
              F.FACTION_DELTA_UNBOUNDED))
    c.append(("fx:bounded_false", FX, e_fx(bounded=False), F.FACTION_DELTA_UNBOUNDED))
    c.append(("fx:unknown_reason", FX, e_fx(reason_code="because"),
              F.FACTION_DELTA_INVALID))
    c.append(("fx:resources_delta_over_cap", FX, e_fx(resources_delta={"survey_data": 9999}),
              F.FACTION_DELTA_UNBOUNDED))

    # --- ConsequenceLedger ---
    c.append(("cl:hash_unchanged_with_deltas", CL,
              e_cl(post_faction_state_hash="sha256:pre_aaaa"),
              F.FACTION_STATE_NOT_MUTATED))
    c.append(("cl:bad_save_load", CL, e_cl(save_load_result="maybe"),
              F.QUEST_FACTION_SAVE_LOAD_FAILED))

    # --- QuestFactionRuntimeReport ---
    c.append(("rr:clean_roundtrip_failed", RR, e_rr(save_load_result="roundtrip_failed"),
              F.QUEST_FACTION_SAVE_LOAD_FAILED))
    c.append(("rr:clean_no_ledger", RR, e_rr(consequence_ledger_path=""),
              F.CONSEQUENCE_LEDGER_MISSING))
    c.append(("rr:clean_abandoned_outcome", RR, e_rr(quest_outcome="abandoned"),
              F.QUEST_OUTCOME_EVIDENCE_MISSING))
    c.append(("rr:clean_no_faction_mutation", RR, e_rr(faction_state_mutated=False),
              F.FACTION_STATE_NOT_MUTATED))
    c.append(("rr:clean_no_next_state", RR, e_rr(next_mission_state_available=False),
              F.QUEST_FACTION_NEXT_STATE_MISSING))
    c.append(("rr:malformed_failure_code", RR, e_rr(failure_codes=["NOT_A_CODE"]),
              F.QUEST_FACTION_UNKNOWN_FAILURE_CODE))

    # --- QuestFactionEvidenceIndex ---
    c.append(("qi:partial_matrix_pass", QI, e_qi(scenario_count_seen=23),
              F.QUEST_FACTION_PARTIAL_MATRIX))
    c.append(("qi:stale_sha", QI, e_qi(git_sha="unknown"),
              F.QUEST_FACTION_STALE_EVIDENCE))
    c.append(("qi:pass_with_missing", QI, e_qi(missing_evidence=["x.json"]),
              F.CONSEQUENCE_LEDGER_MISSING))
    c.append(("qi:pass_with_stale", QI, e_qi(stale_evidence=["old.json"]),
              F.QUEST_FACTION_STALE_EVIDENCE))

    # --- OperatorQuestView ---
    c.append(("oq:clean_no_ledger_link", OQ, e_oq(consequence_ledger_paths=[]),
              F.CONSEQUENCE_LEDGER_MISSING))
    c.append(("oq:no_scenarios", OQ, e_oq(scenario_ids=[]),
              F.QUEST_FACTION_OPERATOR_VIEW_INVALID))

    # --- OperatorFactionView ---
    c.append(("of:history_no_state_path", OF, e_of(state_paths=[]),
              F.FACTION_STATE_INVALID))
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 quest/faction negative-fixture suite.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "quest_faction_negatives", strict=strict)
    cs = cases()

    # vacuous-suite guard: an empty fixture set is itself a failure.
    rep.check("suite_nonempty", len(cs) >= 24,
              "negative suite must carry >= 24 fixtures (got {})".format(len(cs)),
              code=F.QUEST_FACTION_NEGATIVE_ACCEPTED)

    for label, validate, bad, owning in cs:
        fails = [ck for ck in validate(bad, strict=True) if not ck[1]]
        codes = {ck[3] for ck in fails}
        rep.check("neg::{}::rejected".format(label), len(fails) > 0,
                  "known-bad fixture was ACCEPTED (fake green)",
                  code=F.QUEST_FACTION_NEGATIVE_ACCEPTED)
        rep.check("neg::{}::owning_code".format(label), owning in codes,
                  "must be rejected for {} (got {})".format(
                      owning, sorted(str(x) for x in codes)[:4]),
                  code=F.QUEST_FACTION_NEGATIVE_ACCEPTED)

    # reverse dogfood: every valid example must STILL pass (no reject-everything fake).
    for name, (validate, good, _bad) in QF.CONTRACTS.items():
        gfails = [ck for ck in validate(good(), strict=True) if not ck[1]]
        rep.check("reverse::{}::valid_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([ck[0] for ck in gfails][:4]),
                  code=F.QUEST_FACTION_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="quest-faction-negative-fixtures", pack=None, strict=strict,
        status=rep.status, record_count=len(cs), records_total=len(cs),
        report_type="wf.quest_faction.negatives.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "quest_faction_negatives_report.json")
    rep.print_summary("quest-faction-negative-fixtures")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
