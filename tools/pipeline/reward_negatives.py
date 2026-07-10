#!/usr/bin/env python3
"""reward_negatives.py — WorldForge v1.9 Reward/Progression Alpha negative-fixture gate.

Known-bad reward records must be REJECTED, and rejected for the RIGHT owning
failure code — a validator that fails for the wrong reason is not real coverage.
Each fixture is built from a canonical ``RX._example_*`` factory with a single
override so it violates exactly ONE reward invariant, mirroring
[[combat_negatives]]. Covers every reward contract (LoadoutProfile /
EquipmentItem / RewardTable / RewardGrantEvent / RewardCompletionReport /
InventoryState / ProgressionState / UnlockState / RewardTelemetry) and the
anti-fake-green honesty invariants (reward-without-completion, completion-without-
mutation, duplicate grant-once, no_reward-that-mutates, inventory over-capacity,
inventory/progression hash mismatch, level-off-curve, non-bool affects_generation,
telemetry missing grant.applied).

Acceptance: ``PYTHONUTF8=1 STRICT=1 python tools/pipeline/reward_negatives.py --strict``.
Exit 0 iff EVERY negative was rejected for its owning code.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode as F


def cases():
    """Each case: (label, validate_fn, known_bad_record, owning_failure_code).

    The known-bad is the valid example with a single targeted override so it
    violates exactly one invariant; the validator MUST reject it, and the owning
    code MUST appear among the failing checks' codes.
    """
    LP = RX._example_loadout_profile
    EQ = RX._example_equipment_item
    RT = RX._example_reward_table
    RE = RX._example_reward_entry
    RGE = RX._example_reward_grant_event
    RCR = RX._example_reward_completion
    INV = RX._example_inventory_state
    PRG = RX._example_progression_state
    UNL = RX._example_unlock_state
    # Telemetry validator needs require_completion=True to enforce the honesty set.
    v_tel = lambda o, strict=False: RX.validate_reward_telemetry(o, strict=strict, require_completion=True)

    return [
        # ---- LoadoutProfile negatives ----
        ("loadout_duplicate_exclusive", RX.validate_loadout_profile,
         LP(tool_slot="eq_rifle_std"), F.LOADOUT_CONTRACT_INVALID),
        ("loadout_unknown_archetype", RX.validate_loadout_profile,
         LP(allowed_mission_archetypes=["not_a_real_archetype"]), F.LOADOUT_CONTRACT_INVALID),
        ("loadout_zero_power_budget", RX.validate_loadout_profile,
         LP(power_budget=0.0), F.LOADOUT_CONTRACT_INVALID),
        ("loadout_missing_primary", RX.validate_loadout_profile,
         {k: v for k, v in LP().items() if k != "primary_slot"}, F.LOADOUT_CONTRACT_INVALID),

        # ---- EquipmentItem negatives ----
        ("equipment_missing_provenance", RX.validate_equipment_item,
         EQ(provenance=None), F.EQUIPMENT_ITEM_INVALID),
        ("equipment_unknown_slot", RX.validate_equipment_item,
         EQ(slot="backpack"), F.EQUIPMENT_ITEM_INVALID),
        ("equipment_unknown_item_type", RX.validate_equipment_item,
         EQ(item_type="grenade"), F.EQUIPMENT_ITEM_INVALID),
        ("equipment_unknown_ownership", RX.validate_equipment_item,
         EQ(ownership_class="borrowed"), F.EQUIPMENT_ITEM_INVALID),

        # ---- RewardTable negatives ----
        ("reward_table_budget_inverted", RX.validate_reward_table,
         RT(budget_min=500.0, budget_max=100.0), F.REWARD_TABLE_INVALID),
        ("reward_table_empty_entries", RX.validate_reward_table,
         RT(reward_entries=[]), F.REWARD_TABLE_INVALID),
        ("reward_table_unknown_archetype", RX.validate_reward_table,
         RT(mission_archetype="loot_run"), F.REWARD_TABLE_INVALID),
        # Honesty: duplicate grant-once — two entries share a reward_entry_id.
        ("reward_table_duplicate_entry_id", RX.validate_reward_table,
         RT(reward_entries=[RE(reward_entry_id="re_dup"),
                            RE(reward_entry_id="re_dup", reward_type="item",
                               item_id="eq_rifle_std", xp_amount=0.0, grant_once=True,
                               max_repeat_count=1)]),
         F.REWARD_DUPLICATE_GRANT),
        # Honesty: grant_once entry with no stable id.
        ("reward_table_grant_once_no_id", RX.validate_reward_table,
         RT(reward_entries=[RE(reward_entry_id="", reward_type="item", item_id="eq_rifle_std",
                               xp_amount=0.0, grant_once=True, max_repeat_count=1)]),
         F.REWARD_DUPLICATE_GRANT),

        # ---- RewardGrantEvent negatives ----
        # Honesty: reward-without-completion — grant with empty source completion.
        ("grant_without_completion", RX.validate_reward_grant_event,
         RGE(source_completion_report=""), F.REWARD_WITHOUT_COMPLETION),
        # Honesty: rewarding grant that mutates NO state (pre==post on both) = fake reward.
        ("grant_no_state_mutation", RX.validate_reward_grant_event,
         RGE(pre_progression_hash="prog:0001", post_progression_hash="prog:0001"),
         F.REWARD_GRANT_INVALID),
        # Honesty: no_reward grant that DOES mutate progression = hidden grant.
        ("grant_no_reward_but_mutates", RX.validate_reward_grant_event,
         RGE(reward_type="no_reward"), F.REWARD_GRANT_EVENT_INVALID),

        # ---- RewardCompletionReport fake-green negatives ----
        # Honesty: completion-without-mutation — success but state unmutated.
        ("completion_success_no_mutation", RX.validate_reward_completion_report,
         RCR(inventory_mutated=False, progression_mutated=False), F.COMPLETION_WITHOUT_REWARD),
        ("completion_success_zero_events", RX.validate_reward_completion_report,
         RCR(reward_events_seen=0), F.REWARD_GRANT_INVALID),
        ("completion_success_mission_not_done", RX.validate_reward_completion_report,
         RCR(mission_completed=False), F.REWARD_WITHOUT_COMPLETION),
        ("completion_success_save_load_fail", RX.validate_reward_completion_report,
         RCR(save_load_result="fail"), F.REWARD_SAVE_LOAD_FAILED),
        ("completion_success_missing_telemetry", RX.validate_reward_completion_report,
         RCR(telemetry_path=""), F.REWARD_TELEMETRY_MISSING),
        ("completion_failed_class_no_code", RX.validate_reward_completion_report,
         RCR(completion_class="failed_reward_grant", status="pass"),
         F.REWARD_REPORT_INTEGRITY_FAILED),

        # ---- InventoryState negatives ----
        # Honesty: inventory over-capacity — an item present but capacity 0.
        ("inventory_over_capacity", RX.validate_inventory_state,
         INV(capacity=0), F.INVENTORY_CAPACITY_EXCEEDED),
        # Honesty: inventory hash mismatch.
        ("inventory_hash_mismatch", RX.validate_inventory_state,
         INV(inventory_hash="inv:deadbeefdeadbeef"), F.INVENTORY_HASH_MISMATCH),
        ("inventory_forbidden_save_slot", RX.validate_inventory_state,
         INV(save_load_key="WFCombat_State"), F.INVENTORY_SAVE_LOAD_FAILED),

        # ---- ProgressionState negatives ----
        # Honesty: level off the XP curve.
        ("progression_level_off_curve", RX.validate_progression_state,
         PRG(level=9), F.LEVEL_CURVE_MISMATCH),
        # Honesty: progression hash mismatch.
        ("progression_hash_mismatch", RX.validate_progression_state,
         PRG(progression_hash="prog:deadbeefdeadbeef"), F.PROGRESSION_HASH_MISMATCH),
        ("progression_forbidden_save_slot", RX.validate_progression_state,
         PRG(save_load_key="WFNPC_State"), F.PROGRESSION_SAVE_LOAD_FAILED),

        # ---- UnlockState negatives ----
        # Honesty: affects_generation must be an explicit bool.
        ("unlock_affects_generation_non_bool", RX.validate_unlock_state,
         UNL(affects_generation="yes"), F.UNLOCK_STATE_INVALID),
        ("unlock_unknown_type", RX.validate_unlock_state,
         UNL(unlock_type="cheat_code"), F.UNLOCK_STATE_INVALID),
        ("unlock_unsourced", RX.validate_unlock_state,
         UNL(source_reward_event=""), F.UNLOCK_SOURCE_UNRESOLVED),

        # ---- RewardTelemetry negatives ----
        # Honesty: completion telemetry missing the grant.applied event.
        ("telemetry_missing_grant_applied", v_tel,
         {"events": [{"event_type": t} for t in RX.COMPLETION_REQUIRED_REWARD_EVENTS
                     if t != "reward.grant.applied"]}, F.REWARD_TELEMETRY_MISSING),
        ("telemetry_empty_events", v_tel,
         {"events": []}, F.REWARD_TELEMETRY_MISSING),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "reward_negatives", strict=strict)

    cs = cases()
    for label, fn, bad, code in cs:
        fails = [c for c in fn(bad, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("neg::{}::rejected".format(label), len(fails) > 0,
                  "known-bad '{}' must be rejected".format(label), code=F.REWARD_NEGATIVE_ACCEPTED)
        rep.check("neg::{}::owning_code".format(label), code in codes,
                  "'{}' rejected for owning code {} (got {})".format(
                      label, code, sorted(str(x) for x in codes)[:4]),
                  code=F.REWARD_NEGATIVE_ACCEPTED)

    # Dogfood the other direction: every valid example MUST pass its own validator,
    # so a "reject everything" validator can't fake coverage.
    for name, (validate, good, _bad) in RX.CONTRACTS.items():
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("pos::{}::valid_example_passes".format(name), len(gfails) == 0,
                  "valid {} example must pass ({})".format(name, gfails[:2]),
                  code=F.REWARD_REPORT_INTEGRITY_FAILED)

    rep.check("neg::case_count_nonzero", len(cs) > 0,
              "negative suite must run > 0 cases (a vacuous suite is a failure)",
              code=F.REWARD_NEGATIVE_ACCEPTED)

    rep.finalize()
    rep.set_meta(build_meta(command="reward-negative-validators", pack=args.pack,
                            strict=strict, status=rep.status, record_count=len(cs),
                            report_type="wf.reward.negatives.v1", records_total=len(cs)))
    rep.write(REPO_ROOT / "procedural/reports/rewards/negatives", "reward_negatives_report.json")
    rep.print_summary("reward-negative-validators")
    print("[reward-negative-validators] {} negative fixtures, each rejected for its owning code".format(len(cs)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
