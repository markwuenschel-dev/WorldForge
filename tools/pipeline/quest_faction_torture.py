#!/usr/bin/env python3
"""quest_faction_torture.py — v2.2 hostile torture battery (Wave R).

Proves the quest/faction honesty detectors reject the ways a consequence report can
fake success. Dogfood-based: it constructs the hostile states in-code and asserts
they are caught for their OWNING code, so it certifies the DETECTORS (not the live
evidence) and is meaningfully GREEN even on an empty tree. Each mode is the
quest/faction form of a fake-green from handoff §7/§10.7.

Torture modes:
  quest completes without runtime evidence, quest outcome without a ledger, state
  hash unchanged after a claimed delta, save/load claimed without round-trip,
  malformed next-mission hook, faction delta out of bounds / not bounded, unknown
  faction class, out-of-bounds faction state, same quest active AND completed,
  partial 23/24 matrix claiming complete, stale git_sha, operator view with a broken
  ledger link, faction view with mutation history but no state path, and a clean
  runtime report with an abandoned (non-outcome-bearing) outcome.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/quest_faction_torture.py --strict
Reports -> procedural/reports/quest_faction/negatives/quest_faction_torture_report.json
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


def modes():
    """Return [(label, validate, hostile_record, owning_code), ...]."""
    e = QF
    return [
        ("quest_completed_no_evidence", e.validate_quest_runtime_state,
         e._example_quest_runtime_state(completed_steps=[
             "qf_alpine_snow_survey_landmark_baseline_s1_step1"]),
         F.QUEST_OUTCOME_EVIDENCE_MISSING),
        ("outcome_success_no_deltas", e.validate_quest_runtime_state,
         e._example_quest_runtime_state(faction_deltas_applied=False),
         F.FACTION_STATE_NOT_MUTATED),
        ("ledger_hash_unchanged", e.validate_consequence_ledger,
         e._example_consequence_ledger(post_faction_state_hash="sha256:pre_aaaa"),
         F.FACTION_STATE_NOT_MUTATED),
        ("report_clean_roundtrip_failed", e.validate_runtime_report,
         e._example_runtime_report(save_load_result="roundtrip_failed"),
         F.QUEST_FACTION_SAVE_LOAD_FAILED),
        ("report_clean_no_ledger", e.validate_runtime_report,
         e._example_runtime_report(consequence_ledger_path=""),
         F.CONSEQUENCE_LEDGER_MISSING),
        ("report_clean_abandoned", e.validate_runtime_report,
         e._example_runtime_report(quest_outcome="abandoned"),
         F.QUEST_OUTCOME_EVIDENCE_MISSING),
        ("report_clean_no_mutation", e.validate_runtime_report,
         e._example_runtime_report(faction_state_mutated=False),
         F.FACTION_STATE_NOT_MUTATED),
        ("delta_unbounded", e.validate_faction_delta,
         e._example_faction_delta(standing_delta=999), F.FACTION_DELTA_UNBOUNDED),
        ("delta_not_bounded_flag", e.validate_faction_delta,
         e._example_faction_delta(bounded=False), F.FACTION_DELTA_UNBOUNDED),
        ("unknown_faction_class", e.validate_faction_definition,
         e._example_faction_definition(faction_class="megacorp"),
         F.FACTION_CONTRACT_INVALID),
        ("faction_state_out_of_bounds", e.validate_faction_state,
         e._example_faction_state(standing=9999), F.FACTION_BOUNDS_INVALID),
        ("quest_active_and_completed", e.validate_faction_state,
         e._example_faction_state(active_quest_ids=["qf_x"], completed_quest_ids=["qf_x"]),
         F.FACTION_STATE_INVALID),
        ("partial_matrix_claims_complete", e.validate_evidence_index,
         e._example_evidence_index(scenario_count_seen=23),
         F.QUEST_FACTION_PARTIAL_MATRIX),
        ("stale_git_sha", e.validate_evidence_index,
         e._example_evidence_index(git_sha="unknown"), F.QUEST_FACTION_STALE_EVIDENCE),
        ("operator_view_broken_ledger", e.validate_operator_quest_view,
         e._example_operator_quest_view(consequence_ledger_paths=[]),
         F.CONSEQUENCE_LEDGER_MISSING),
        ("faction_view_history_no_state", e.validate_operator_faction_view,
         e._example_operator_faction_view(state_paths=[]), F.FACTION_STATE_INVALID),
        ("malformed_next_hook", e.validate_quest_definition,
         e._example_quest_definition(next_mission_hooks=["a", "b", "c", "d", "e"]),
         F.QUEST_NEXT_MISSION_HOOK_INVALID),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 quest/faction torture battery.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "quest_faction_torture", strict=strict)
    ms = modes()
    rep.check("torture::nonempty", len(ms) >= 12,
              "torture battery must carry >= 12 modes (got {})".format(len(ms)),
              code=F.QUEST_FACTION_TORTURE_FAILED)
    for label, validate, rec, owning in ms:
        fails = [c for c in validate(rec, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("torture::{}::caught".format(label), len(fails) > 0,
                  "hostile state was ACCEPTED (fake green)",
                  code=F.QUEST_FACTION_TORTURE_FAILED)
        rep.check("torture::{}::owning_code".format(label), owning in codes,
                  "must be caught for {} (got {})".format(
                      owning, sorted(str(x) for x in codes)[:4]),
                  code=F.QUEST_FACTION_TORTURE_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="quest-faction-torture", pack=None, strict=strict, status=rep.status,
        record_count=len(ms), records_total=len(ms),
        report_type="wf.quest_faction.torture.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "quest_faction_torture_report.json")
    rep.print_summary("quest-faction-torture")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
