#!/usr/bin/env python3
"""combat_negatives.py — WorldForge v1.8 CombatForge Alpha negative-fixture gate.

Known-bad combat records must be REJECTED, and rejected for the RIGHT owning
failure code — a validator that fails for the wrong reason is not real coverage.
Each fixture is built from a canonical ``_example_*`` factory with a single
override so it violates exactly ONE combat invariant, mirroring
[[npc_behavior_negatives]]. Covers every combat contract (CombatProfile /
PlayerCombatState / DamageEvent / CombatTelemetry / CombatCompletionReport) and
the anti-fake-green honesty invariants (zero-damage, no-mutation, unwinnable,
mission-not-completed, save/load-fail, missing damage telemetry).

Acceptance: ``PYTHONUTF8=1 STRICT=1 python tools/pipeline/combat_negatives.py --strict``.
Exit 0 iff EVERY negative was rejected for its owning code.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode as F


def cases():
    """Each case: (label, validate_fn, known_bad_record, owning_failure_code).

    The known-bad is the valid example with a single targeted override so it
    violates exactly one invariant; the validator MUST reject it, and the owning
    code MUST appear among the failing checks' codes.
    """
    CP = CC._example_combat_profile
    PCS = CC._example_player_combat_state
    DE = CC._example_damage_event
    CMP = CC._example_combat_completion
    # Telemetry validator needs require_completion=True to enforce the honesty set.
    v_tel = lambda o, strict=False: CC.validate_combat_telemetry(o, strict=strict, require_completion=True)

    return [
        # ---- CombatProfile negatives ----
        ("profile_baseline_unwinnable", CC.validate_combat_profile,
         CP(baseline_expected_damage=120.0), F.COMBAT_UNWINNABLE_BASELINE),
        ("profile_baseline_zero_damage", CC.validate_combat_profile,
         CP(baseline_expected_damage=0.0), F.COMBAT_NO_DAMAGE_EVENTS),
        ("profile_environment_only_source", CC.validate_combat_profile,
         CP(damage_sources=["environment"]), F.PLAYER_DAMAGE_NOT_APPLIED),
        ("profile_unknown_damage_source", CC.validate_combat_profile,
         CP(damage_sources=["laser_beam"]), F.COMBAT_PROFILE_SCHEMA_FAILURE),
        ("profile_missing_player_max_health", CC.validate_combat_profile,
         {k: v for k, v in CP().items() if k != "player_max_health"},
         F.COMBAT_PROFILE_SCHEMA_FAILURE),
        ("profile_unknown_encounter_archetype", CC.validate_combat_profile,
         CP(encounter_archetype="not_an_archetype"), F.COMBAT_PROFILE_SCHEMA_FAILURE),
        ("profile_bad_completion_policy", CC.validate_combat_profile,
         CP(mission_completion_policy="opt_out"), F.COMBAT_MISSION_COMPLETION_BLOCKED),
        ("profile_unknown_field_strict", CC.validate_combat_profile,
         dict(CP(), bogus_field=1), F.COMBAT_PROFILE_SCHEMA_FAILURE),

        # ---- PlayerCombatState negatives ----
        ("player_alive_at_zero_health", CC.validate_player_combat_state,
         PCS(current_health=0.0, is_alive=True), F.PLAYER_COMBAT_STATE_SCHEMA_FAILURE),
        ("player_health_over_max", CC.validate_player_combat_state,
         PCS(current_health=150.0), F.PLAYER_COMBAT_STATE_SCHEMA_FAILURE),
        ("player_negative_health", CC.validate_player_combat_state,
         PCS(current_health=-5.0, is_alive=False), F.PLAYER_COMBAT_STATE_SCHEMA_FAILURE),
        ("player_empty_save_load_key", CC.validate_player_combat_state,
         PCS(save_load_key=""), F.COMBAT_STATE_SAVE_LOAD_FAILURE),

        # ---- DamageEvent negatives ----
        ("damage_zero_amount", CC.validate_damage_event,
         DE(amount=0.0, health_after=72.0), F.COMBAT_ZERO_DAMAGE_FAKE),
        ("damage_accounting_inconsistent", CC.validate_damage_event,
         DE(health_after=50.0), F.DAMAGE_ACCOUNTING_INCONSISTENT),
        ("damage_health_not_decreased", CC.validate_damage_event,
         DE(amount=4.0, health_before=72.0, health_after=76.0), F.DAMAGE_ACCOUNTING_INCONSISTENT),
        ("damage_unknown_source_type", CC.validate_damage_event,
         DE(source_type="weapon"), F.DAMAGE_EVENT_SCHEMA_FAILURE),
        ("damage_unknown_damage_type", CC.validate_damage_event,
         DE(damage_type="explosion"), F.DAMAGE_EVENT_SCHEMA_FAILURE),

        # ---- CombatTelemetry negatives ----
        ("telemetry_missing_damage_event", v_tel,
         {"events": [{"event_type": t} for t in CC.COMPLETION_REQUIRED_COMBAT_EVENTS
                     if t != "combat.player.damage.taken"]}, F.COMBAT_NO_DAMAGE_EVENTS),
        ("telemetry_empty_events", v_tel,
         {"events": []}, F.COMBAT_DAMAGE_TELEMETRY_MISSING),

        # ---- CombatCompletionReport fake-green negatives ----
        ("completion_success_zero_damage", CC.validate_combat_completion_report,
         CMP(damage_events_seen=0), F.COMBAT_NO_DAMAGE_EVENTS),
        ("completion_success_no_mutation", CC.validate_combat_completion_report,
         CMP(player_min_health=100.0), F.PLAYER_HEALTH_NO_MUTATION),
        ("completion_success_mission_not_done", CC.validate_combat_completion_report,
         CMP(mission_completed=False), F.COMBAT_MISSION_COMPLETION_BLOCKED),
        ("completion_success_save_load_fail", CC.validate_combat_completion_report,
         CMP(save_load_result="fail"), F.COMBAT_STATE_SAVE_LOAD_FAILURE),
        ("completion_success_did_not_survive", CC.validate_combat_completion_report,
         CMP(player_final_health=0.0), F.COMBAT_UNWINNABLE_BASELINE),
        ("completion_success_band_not_survivable", CC.validate_combat_completion_report,
         CMP(survivability_band="too_low"), F.COMBAT_BALANCE_REPORT_FAILURE),
        ("completion_failed_class_no_code", CC.validate_combat_completion_report,
         CMP(completion_class="failed_combat_spawn"), F.COMBAT_REPORT_INTEGRITY_FAILURE),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "combat_negatives", strict=strict)

    cs = cases()
    for label, fn, bad, code in cs:
        fails = [c for c in fn(bad, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("neg::{}::rejected".format(label), len(fails) > 0,
                  "known-bad '{}' must be rejected".format(label), code=code)
        rep.check("neg::{}::owning_code".format(label), code in codes,
                  "'{}' rejected for owning code {} (got {})".format(label, code, sorted(str(x) for x in codes)[:4]),
                  code=code)

    # Dogfood the other direction: every valid example MUST pass its own validator,
    # so a "reject everything" validator can't fake coverage.
    for name, (validate, good, _bad) in CC.CONTRACTS.items():
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("pos::{}::valid_example_passes".format(name), len(gfails) == 0,
                  "valid {} example must pass ({})".format(name, gfails[:2]),
                  code=F.COMBAT_REPORT_INTEGRITY_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="combat-negative-validators", pack=args.pack,
                            strict=strict, status=rep.status, record_count=len(cs),
                            report_type="wf.combat.negatives.v1"))
    rep.write(REPO_ROOT / "procedural/reports/combat/negatives", "combat_negatives_report.json")
    rep.print_summary("combat-negative-validators")
    print("[combat-negative-validators] {} negative fixtures, each rejected for its owning code".format(len(cs)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
