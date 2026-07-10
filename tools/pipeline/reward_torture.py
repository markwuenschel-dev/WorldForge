#!/usr/bin/env python3
"""reward_torture.py — WorldForge v1.9 Reward/Progression lifecycle-torture gate.

Mirror of [[combat_torture]] for the v1.9 reward/progression contract + model
layer. Attacks the honesty of the reward record schema AND the reward_forge
classification/persistence model so a corrupted / partial / exploitable verdict
cannot slip through as green. It operates on SYNTHETIC records built from the
frozen ``reward_contracts._example_*`` factories and the ``reward_forge`` model
helpers, so it runs and is fully green NOW, without any UE runtime evidence.

Adversarial scenarios that MUST be caught (contract §"honesty invariants"):

  (a) duplicate grant_once — the same grant_once entry granted twice must
      classify ``exploit_suspected`` (RF.classify_risk_reward(duplicate_grant_once=True)).
  (b) over-reward — reward_value > budget_max must classify ``over_rewarded``.
  (c) save/load drift — a state whose stored hash was tampered must fail
      RF.save_load_roundtrip (ok=False).
  (d) capacity overflow — an inventory with items > capacity must fail
      RX.validate_inventory_state owning INVENTORY_CAPACITY_EXCEEDED.
  (e) reward-without-completion — a grant with an empty source_completion_report
      must be rejected owning REWARD_WITHOUT_COMPLETION.
  (f) completion-without-reward — a success completion with no state mutation must
      be rejected owning COMPLETION_WITHOUT_REWARD.

Plus the standard torture breadth: every canonical example validates clean; every
registry known-bad is rejected; verdicts are deterministic; and partial (missing a
required field) never validates as full. Nothing may pass; the suite must not crash.

Acceptance: PYTHONUTF8=1 STRICT=1 python tools/pipeline/reward_torture.py --strict
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
import reward_forge as RF
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


# The flat-schema contracts and the REQUIRED field tuple that defines "full" for
# each — used by the partial-vs-full mode. (RewardTelemetry is events-shaped, not
# a flat required-field record, so it is exercised separately below.)
_SCHEMA_REQUIRED = {
    "LoadoutProfile": (RX.validate_loadout_profile, RX._example_loadout_profile,
                       tuple(f for f in RX.LOADOUT_PROFILE_REQUIRED if f != "secondary_slot")),
    "EquipmentItem": (RX.validate_equipment_item, RX._example_equipment_item,
                      RX.EQUIPMENT_ITEM_REQUIRED),
    "RewardTable": (RX.validate_reward_table, RX._example_reward_table, RX.REWARD_TABLE_REQUIRED),
    "RewardGrantEvent": (RX.validate_reward_grant_event, RX._example_reward_grant_event,
                         tuple(f for f in RX.REWARD_GRANT_EVENT_REQUIRED
                               if f not in ("granted_item_id", "unlock_id", "source_combat_report"))),
    "RewardCompletionReport": (RX.validate_reward_completion_report, RX._example_reward_completion,
                               tuple(f for f in RX.REWARD_COMPLETION_REQUIRED if f != "failure_owner")),
    "InventoryState": (RX.validate_inventory_state, RX._example_inventory_state,
                       RX.INVENTORY_STATE_REQUIRED),
    "ProgressionState": (RX.validate_progression_state, RX._example_progression_state,
                         RX.PROGRESSION_STATE_REQUIRED),
    "UnlockState": (RX.validate_unlock_state, RX._example_unlock_state, RX.UNLOCK_STATE_REQUIRED),
}


def _adversarial(rep):
    """The six adversarial reward scenarios (a)-(f) that MUST be caught. Each is
    wrapped so a raised exception is reported as a torture failure, never a crash."""

    # (a) duplicate grant_once -> exploit_suspected
    try:
        cls, exploit = RF.classify_risk_reward("baseline", 100.0, 50.0, 200.0,
                                               duplicate_grant_once=True)
        ok = cls == "exploit_suspected"
    except Exception as e:  # noqa: BLE001
        ok, cls, exploit = False, "CRASH:{}".format(e), None
    rep.check("torture::adversarial::duplicate_grant_once", ok,
              "duplicate grant_once must classify exploit_suspected (got {})".format(cls),
              code=F.REWARD_EXPLOIT_DETECTED)

    # (b) over-reward -> over_rewarded
    try:
        cls, _ = RF.classify_risk_reward("baseline", 9999.0, 50.0, 200.0)
        ok = cls == "over_rewarded"
    except Exception as e:  # noqa: BLE001
        ok, cls = False, "CRASH:{}".format(e)
    rep.check("torture::adversarial::over_reward", ok,
              "reward_value > budget_max must classify over_rewarded (got {})".format(cls),
              code=F.REWARD_BUDGET_EXCEEDED)

    # (c) save/load drift on a tampered state hash -> ok=False (both kinds)
    for kind, good, hashkey in (
        ("inventory", RX._example_inventory_state, "inventory_hash"),
        ("progression", RX._example_progression_state, "progression_hash"),
    ):
        try:
            clean = good()
            ok_clean, _ = RF.save_load_roundtrip(clean, kind)
            drifted = dict(good())
            drifted[hashkey] = "tampered:not_the_real_hash"
            ok_drift, _ = RF.save_load_roundtrip(drifted, kind)
            caught = ok_clean and (not ok_drift)
        except Exception as e:  # noqa: BLE001
            caught = False
            ok_clean = ok_drift = "CRASH:{}".format(e)
        rep.check("torture::adversarial::save_load_drift::{}".format(kind), caught,
                  "{} save/load drift must be caught (clean={}, drifted={})".format(
                      kind, ok_clean, ok_drift),
                  code=F.REWARD_SAVE_LOAD_FAILED)

    # (d) capacity overflow -> validate_inventory_state rejects owning capacity code
    try:
        nf, codes = _failing(RX.validate_inventory_state, RX._example_inventory_state(capacity=0))
        caught = nf > 0 and F.INVENTORY_CAPACITY_EXCEEDED in codes
    except Exception as e:  # noqa: BLE001
        caught, codes = False, "CRASH:{}".format(e)
    rep.check("torture::adversarial::capacity_overflow", caught,
              "inventory items > capacity must be rejected owning INVENTORY_CAPACITY_EXCEEDED "
              "(codes={})".format(codes),
              code=F.INVENTORY_CAPACITY_EXCEEDED)

    # (e) reward-without-completion -> grant with empty source_completion_report rejected
    try:
        nf, codes = _failing(RX.validate_reward_grant_event,
                             RX._example_reward_grant_event(source_completion_report=""))
        caught = nf > 0 and F.REWARD_WITHOUT_COMPLETION in codes
    except Exception as e:  # noqa: BLE001
        caught, codes = False, "CRASH:{}".format(e)
    rep.check("torture::adversarial::reward_without_completion", caught,
              "grant without source_completion_report must be rejected owning "
              "REWARD_WITHOUT_COMPLETION (codes={})".format(codes),
              code=F.REWARD_WITHOUT_COMPLETION)

    # (f) completion classified success but state unmutated -> rejected
    try:
        nf, codes = _failing(RX.validate_reward_completion_report,
                             RX._example_reward_completion(inventory_mutated=False,
                                                           progression_mutated=False))
        caught = nf > 0 and F.COMPLETION_WITHOUT_REWARD in codes
    except Exception as e:  # noqa: BLE001
        caught, codes = False, "CRASH:{}".format(e)
    rep.check("torture::adversarial::completion_without_reward", caught,
              "success completion with no state mutation must be rejected owning "
              "COMPLETION_WITHOUT_REWARD (codes={})".format(codes),
              code=F.COMPLETION_WITHOUT_REWARD)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # ---- baseline sanity: every canonical example must validate clean ----
    for name, (fn, good, _bad) in RX.CONTRACTS.items():
        nf, _ = _failing(fn, good())
        rep.check("torture::example_valid::{}".format(name), nf == 0,
                  "canonical {} example must validate clean, got {} failing check(s)".format(name, nf),
                  code=F.REWARD_TORTURE_FAILED)

    # ---- the six adversarial reward scenarios (a)-(f) ----
    _adversarial(rep)

    # ---- corrupt-real-record via the registry's known-bad examples ----
    # Every contract ships a known-bad that MUST be rejected; a contract that
    # accepts its own known-bad is fake green.
    for name, (fn, _good, bad) in RX.CONTRACTS.items():
        nf, _ = _failing(fn, bad())
        rep.check("torture::known_bad_rejected::{}".format(name), nf > 0,
                  "{} known-bad example must be rejected".format(name),
                  code=F.REWARD_TORTURE_FAILED)

    # ---- determinism: same input -> identical verdict (twice) ----
    for name, (fn, good, bad) in RX.CONTRACTS.items():
        g = good()
        b = bad()
        rep.check("torture::determinism::valid::{}".format(name),
                  _verdict(fn, g) == _verdict(fn, g),
                  "{} validator verdict on valid record is non-deterministic".format(name),
                  code=F.REWARD_TORTURE_FAILED)
        rep.check("torture::determinism::bad::{}".format(name),
                  _verdict(fn, b) == _verdict(fn, b),
                  "{} validator verdict on known-bad record is non-deterministic".format(name),
                  code=F.REWARD_TORTURE_FAILED)

    # ---- partial != full: dropping any required field must break validation ----
    for name, (fn, good, required) in _SCHEMA_REQUIRED.items():
        full = good()
        nf_full, _ = _failing(fn, full)
        rep.check("torture::full_valid::{}".format(name), nf_full == 0,
                  "full {} record must validate clean".format(name),
                  code=F.REWARD_TORTURE_FAILED)
        all_partials_rejected = True
        for field in required:
            partial = {k: v for k, v in full.items() if k != field}
            nf_partial, _ = _failing(fn, partial)
            if nf_partial == 0:
                all_partials_rejected = False
                break
        rep.check("torture::partial_not_full::{}".format(name), all_partials_rejected,
                  "a {} record missing a required field must not validate as full".format(name),
                  code=F.REWARD_TORTURE_FAILED)

    # RewardTelemetry (events-shaped): completion telemetry missing the grant.applied
    # event must not pass the completion-strength validator.
    partial_tel = {"events": [{"event_type": "reward.scenario.started"},
                              {"event_type": "reward.scenario.completed"}]}
    nf_tel, _ = _failing(
        lambda o, strict=True: RX.validate_reward_telemetry(o, strict=strict, require_completion=True),
        partial_tel)
    rep.check("torture::partial_not_full::RewardTelemetry", nf_tel > 0,
              "completion telemetry missing required events must not pass as complete",
              code=F.REWARD_TELEMETRY_MISSING)

    rep.finalize()
    rep.set_meta(build_meta(command="reward-torture", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(RX.CONTRACTS),
                            report_type="wf.reward.torture.v1", records_total=len(RX.CONTRACTS)))
    rep.write(REPO_ROOT / "procedural/reports/rewards/torture", "reward_torture_report.json")
    rep.print_summary("reward-torture")
    print("[reward-torture] adversarial (dup-grant/over-reward/save-load-drift/capacity/"
          "reward-without-completion/completion-without-reward) + determinism + partial!=full "
          "(synthetic, {} contracts)".format(len(RX.CONTRACTS)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
