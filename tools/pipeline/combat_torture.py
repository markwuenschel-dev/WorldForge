#!/usr/bin/env python3
"""combat_torture.py — WorldForge v1.8 CombatForge lifecycle-torture gate.

Mirror of [[npc_behavior_torture]] for the v1.8 combat contract layer. Attacks the
honesty of the combat record schema so a corrupted / partial / non-deterministic
verdict cannot slip through as green. It operates entirely on SYNTHETIC records
built from the frozen ``combat_contracts._example_*`` factories, so it runs and is
fully green NOW, without any UE runtime evidence.

Torture modes (all must hold):

  * corrupt-real-record — take a VALID record (chiefly a CombatCompletionReport,
    the success-bearing contract) and flip a single field in each dangerous way;
    assert the owning validator rejects it AND owns the right failure code. A
    validator that still passes a corrupted success record is a fake-green vector.
  * determinism — the same input yields the same validator verdict every time (no
    run-to-run drift in pass/fail or in the emitted failure codes).
  * partial != full — a record missing a required field must never validate as a
    complete record; the full valid record must validate. Partial-as-full is the
    classic "looks done" fake.

Acceptance: PYTHONUTF8=1 STRICT=1 python tools/pipeline/combat_torture.py --strict
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


def _failing(fn, obj):
    """Run a contract validator and return (num_failing_checks, set_of_failure_codes)."""
    fails = [c for c in fn(obj, strict=True) if not c[1]]
    return len(fails), {c[3] for c in fails}


def _verdict(fn, obj):
    """A stable, comparable verdict tuple: sorted (name, ok, code) triples. Two runs
    of the same validator on the same input must produce identical tuples."""
    return tuple(sorted((c[0], c[1], c[3]) for c in fn(obj, strict=True)))


# The dict-schema contracts and the REQUIRED field tuple that defines "full" for
# each — used by the partial-vs-full mode. (CombatTelemetry is events-shaped, not
# a flat required-field record, so it is exercised separately below.)
_SCHEMA_REQUIRED = {
    "CombatProfile": (CC.validate_combat_profile, CC._example_combat_profile, CC.COMBAT_PROFILE_REQUIRED),
    "PlayerCombatState": (CC.validate_player_combat_state, CC._example_player_combat_state,
                          CC.PLAYER_COMBAT_STATE_REQUIRED),
    "DamageEvent": (CC.validate_damage_event, CC._example_damage_event, CC.DAMAGE_EVENT_REQUIRED),
    "CombatCompletionReport": (CC.validate_combat_completion_report, CC._example_combat_completion,
                               CC.COMBAT_COMPLETION_REQUIRED),
}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # ---- baseline sanity: every canonical example must validate clean ----
    for name, (fn, good, _bad) in CC.CONTRACTS.items():
        nf, _ = _failing(fn, good())
        rep.check("torture::example_valid::{}".format(name), nf == 0,
                  "canonical {} example must validate clean, got {} failing check(s)".format(name, nf),
                  code=F.COMBAT_REPORT_INTEGRITY_FAILURE)

    # ---- corrupt-real-record: flip a field in a VALID completion report ----
    # The success-bearing contract is where fake-green lives, so it gets the most
    # corruption pressure. Each corruption must be rejected AND own its code.
    valid = CC._example_combat_completion
    corruptions = [
        # A success report claiming pass while status says fail -> COMBAT_FAKE_SUCCESS.
        ("completion_status_flipped", CC.validate_combat_completion_report,
         valid(status="fail"), F.COMBAT_FAKE_SUCCESS),
        # Success with zero damage events -> no real combat.
        ("completion_zero_damage", CC.validate_combat_completion_report,
         valid(damage_events_seen=0), F.COMBAT_NO_DAMAGE_EVENTS),
        # Success where health never mutated (min == max) -> no mutation.
        ("completion_no_health_mutation", CC.validate_combat_completion_report,
         valid(player_min_health=100.0), F.PLAYER_HEALTH_NO_MUTATION),
        # Success but the player died (final health 0) -> unwinnable / not survived.
        ("completion_player_dead", CC.validate_combat_completion_report,
         valid(player_final_health=0.0), F.COMBAT_UNWINNABLE_BASELINE),
        # Success but mission not actually completed -> completion blocked.
        ("completion_mission_incomplete", CC.validate_combat_completion_report,
         valid(mission_completed=False), F.COMBAT_MISSION_COMPLETION_BLOCKED),
        # Unknown completion_class -> report-integrity failure.
        ("completion_bad_class", CC.validate_combat_completion_report,
         valid(completion_class="totally_made_up"), F.COMBAT_REPORT_INTEGRITY_FAILURE),
        # Cross-contract corruptions on the other records.
        ("profile_unwinnable_baseline", CC.validate_combat_profile,
         CC._example_combat_profile(baseline_expected_damage=120.0), F.COMBAT_UNWINNABLE_BASELINE),
        ("damage_zero_amount", CC.validate_damage_event,
         CC._example_damage_event(amount=0.0, health_after=72.0), F.COMBAT_ZERO_DAMAGE_FAKE),
        ("pcs_alive_at_zero_health", CC.validate_player_combat_state,
         CC._example_player_combat_state(current_health=0.0, is_alive=True),
         F.PLAYER_COMBAT_STATE_SCHEMA_FAILURE),
    ]
    for label, fn, bad, code in corruptions:
        nf, codes = _failing(fn, bad)
        rep.check("torture::corrupt::{}".format(label), nf > 0 and code in codes,
                  "corruption '{}' must be rejected owning {} (got {} fail(s), codes={})".format(
                      label, code, nf, sorted(str(c) for c in codes)),
                  code=code)

    # ---- corrupt-real-record via the registry's known-bad examples ----
    # Every contract ships a known-bad that MUST be rejected; a contract that
    # accepts its own known-bad is fake green.
    for name, (fn, _good, bad) in CC.CONTRACTS.items():
        nf, _ = _failing(fn, bad())
        rep.check("torture::known_bad_rejected::{}".format(name), nf > 0,
                  "{} known-bad example must be rejected".format(name),
                  code=F.COMBAT_REPORT_INTEGRITY_FAILURE)

    # ---- determinism: same input -> identical verdict (twice) ----
    for name, (fn, good, bad) in CC.CONTRACTS.items():
        g = good()
        b = bad()
        rep.check("torture::determinism::valid::{}".format(name),
                  _verdict(fn, g) == _verdict(fn, g),
                  "{} validator verdict on valid record is non-deterministic".format(name),
                  code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
        rep.check("torture::determinism::bad::{}".format(name),
                  _verdict(fn, b) == _verdict(fn, b),
                  "{} validator verdict on known-bad record is non-deterministic".format(name),
                  code=F.COMBAT_REPORT_INTEGRITY_FAILURE)

    # ---- partial != full: dropping any required field must break validation ----
    for name, (fn, good, required) in _SCHEMA_REQUIRED.items():
        full = good()
        nf_full, _ = _failing(fn, full)
        rep.check("torture::full_valid::{}".format(name), nf_full == 0,
                  "full {} record must validate clean".format(name),
                  code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
        all_partials_rejected = True
        for field in required:
            partial = {k: v for k, v in full.items() if k != field}
            nf_partial, _ = _failing(fn, partial)
            if nf_partial == 0:
                all_partials_rejected = False
                break
        rep.check("torture::partial_not_full::{}".format(name), all_partials_rejected,
                  "a {} record missing a required field must not validate as full".format(name),
                  code=F.COMBAT_REPORT_INTEGRITY_FAILURE)

    # CombatTelemetry (events-shaped): a completion telemetry missing the required
    # completion events must not pass the completion-strength validator.
    partial_tel = {"events": [{"event_type": "combat.scenario.started"},
                              {"event_type": "combat.scenario.completed"}]}
    nf_tel, _ = _failing(
        lambda o, strict=True: CC.validate_combat_telemetry(o, strict=strict, require_completion=True),
        partial_tel)
    rep.check("torture::partial_not_full::CombatTelemetry", nf_tel > 0,
              "completion telemetry missing required events must not pass as complete",
              code=F.COMBAT_DAMAGE_TELEMETRY_MISSING)

    rep.finalize()
    rep.set_meta(build_meta(command="combat-torture", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(CC.CONTRACTS),
                            report_type="wf.combat.torture.v1", records_total=len(CC.CONTRACTS)))
    rep.write(REPO_ROOT / "procedural/reports/combat/torture", "combat_torture_report.json")
    rep.print_summary("combat-torture")
    print("[combat-torture] corrupt-real-record + determinism + partial!=full "
          "(synthetic, {} contracts)".format(len(CC.CONTRACTS)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
