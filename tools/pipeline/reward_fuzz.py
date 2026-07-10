#!/usr/bin/env python3
"""reward_fuzz.py — WorldForge v1.9 Reward/Progression Alpha fuzz gate.

Deterministically mutates the canonical valid reward examples into malformed
records (drop a required field, null a required field, wrong type, out-of-range
number, unknown field, forbidden enum, broken hash, exceeded capacity, negative
xp, telemetry-shape corruption) and asserts every mutant is REJECTED under STRICT
— nothing malformed is wrongly accepted and no validator crashes on garbage.
Seeded, so a fixed (--seed, --cases) is reproducible. Mirrors [[combat_fuzz]].

Acceptance: ``PYTHONUTF8=1 STRICT=1 python tools/pipeline/reward_fuzz.py --cases 300 --seed 1337 --strict``.
Exit nonzero if any record is wrongly accepted or any validator crashes.
"""
import argparse
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode as F

# Per-contract fuzz spec: fields whose corruption is GUARANTEED to violate the
# contract, so every generated mutant is genuinely invalid (no false positives).
#   required : required, non-nullable fields (drop/null -> invalid)
#   enum     : {field: registry} (a value outside the registry -> invalid)
#   number   : numeric fields (a non-number / negative -> invalid)
#   special  : contract-specific one-field corruptions guaranteed invalid
# RewardTelemetry has no field schema (it validates an events list) and is
# special-cased below.
FUZZ_SPEC = {
    "LoadoutProfile": dict(
        validate=RX.validate_loadout_profile, good=RX._example_loadout_profile,
        required=[f for f in RX.LOADOUT_PROFILE_REQUIRED if f != "secondary_slot"],
        enum={},
        number=["power_budget", "risk_budget"]),
    "EquipmentItem": dict(
        validate=RX.validate_equipment_item, good=RX._example_equipment_item,
        required=[f for f in RX.EQUIPMENT_ITEM_REQUIRED],
        enum={"item_type": RX.ITEM_TYPES, "slot": RX.EQUIPMENT_SLOTS,
              "rarity_band": RX.RARITY_BANDS, "ownership_class": RX.OWNERSHIP_CLASSES},
        number=["power_value", "risk_value"]),
    "RewardTable": dict(
        validate=RX.validate_reward_table, good=RX._example_reward_table,
        required=[f for f in RX.REWARD_TABLE_REQUIRED],
        enum={"mission_archetype": RX.MISSION_ARCHETYPES, "risk_band": RX.RISK_BANDS},
        number=["budget_min", "budget_max"],
        special=["inverted_budget"]),
    "RewardGrantEvent": dict(
        validate=RX.validate_reward_grant_event, good=RX._example_reward_grant_event,
        required=[f for f in RX.REWARD_GRANT_EVENT_REQUIRED
                  if f not in ("granted_item_id", "unlock_id", "source_combat_report")],
        enum={"reward_type": RX.REWARD_TYPES},
        number=["xp_amount"],
        special=["empty_completion_ref"]),
    "RewardCompletionReport": dict(
        validate=RX.validate_reward_completion_report, good=RX._example_reward_completion,
        required=[f for f in RX.REWARD_COMPLETION_REQUIRED if f != "failure_owner"],
        enum={"status": RX.RESULT_STATUS, "completion_class": RX.REWARD_COMPLETION_CLASSES,
              "risk_reward_class": RX.RISK_REWARD_CLASSES, "exploit_result": RX.EXPLOIT_RESULTS},
        number=[],
        special=["no_mutation_success", "zero_events_success"]),
    "InventoryState": dict(
        validate=RX.validate_inventory_state, good=RX._example_inventory_state,
        required=[f for f in RX.INVENTORY_STATE_REQUIRED],
        enum={},
        number=[],
        special=["over_capacity", "hash_break"]),
    "ProgressionState": dict(
        validate=RX.validate_progression_state, good=RX._example_progression_state,
        required=[f for f in RX.PROGRESSION_STATE_REQUIRED],
        enum={},
        number=["xp_total", "xp_delta"],
        special=["level_off_curve", "hash_break"]),
    "UnlockState": dict(
        validate=RX.validate_unlock_state, good=RX._example_unlock_state,
        required=[f for f in RX.UNLOCK_STATE_REQUIRED],
        enum={"unlock_type": RX.UNLOCK_TYPES},
        number=[],
        special=["affects_generation_non_bool"]),
}


def _apply_special(rec, name, tag):
    """Apply a contract-specific one-field corruption guaranteed to be invalid."""
    if tag == "inverted_budget":
        rec["budget_min"], rec["budget_max"] = 900.0, 10.0
    elif tag == "empty_completion_ref":
        rec["source_completion_report"] = ""
    elif tag == "no_mutation_success":
        rec["inventory_mutated"] = False
        rec["progression_mutated"] = False
    elif tag == "zero_events_success":
        rec["reward_events_seen"] = 0
    elif tag == "over_capacity":
        rec["capacity"] = 0
    elif tag == "hash_break":
        if name == "InventoryState":
            rec["inventory_hash"] = "inv:fuzzbrokenhash01"
        else:
            rec["progression_hash"] = "prog:fuzzbrokenhash1"
    elif tag == "level_off_curve":
        rec["level"] = 9
    elif tag == "affects_generation_non_bool":
        rec["affects_generation"] = "definitely_not_a_bool"
    return rec


def mutate(rng, name, spec):
    """Return (malformed_record, mutation_tag) that GENUINELY violates the contract."""
    rec = dict(spec["good"]())
    choices = ["drop", "null_required", "unknown_field"]
    if spec["enum"]:
        choices.append("bad_enum")
    if spec["number"]:
        choices.append("bad_number")
    if spec.get("special"):
        choices.append("special")
    kind = rng.choice(choices)
    if kind == "drop":
        rec.pop(rng.choice(spec["required"]), None)
    elif kind == "null_required":
        rec[rng.choice(spec["required"])] = None
    elif kind == "unknown_field":
        rec["fuzz_unknown_{}".format(rng.randint(0, 9999))] = rng.random()
    elif kind == "bad_enum":
        f = rng.choice(list(spec["enum"].keys()))
        rec[f] = "fuzz_not_a_valid_enum_value"
    elif kind == "bad_number":
        rec[rng.choice(spec["number"])] = rng.choice([-999999, "not_a_number", None])
    elif kind == "special":
        tag = rng.choice(spec["special"])
        rec = _apply_special(rec, name, tag)
        kind = "special:{}".format(tag)
    return rec, kind


def _telemetry_mutate(rng):
    """RewardTelemetry validates an events list — mutate that (completion-required)."""
    kind = rng.choice(["drop_events", "events_not_list", "empty_events", "bad_event_type",
                       "missing_grant"])
    if kind == "drop_events":
        return {"report_type": RX.RT_REWARD_TELEMETRY, "scenario_id": "fuzz"}, kind
    if kind == "events_not_list":
        return {"events": "not_a_list"}, kind
    if kind == "empty_events":
        return {"events": []}, kind
    if kind == "bad_event_type":
        return {"events": [{"event_type": "not.a.real.reward.event"}]}, kind
    # missing_grant: all completion events except the grant-applied one.
    evs = [t for t in RX.COMPLETION_REQUIRED_REWARD_EVENTS if t != "reward.grant.applied"]
    return {"events": [{"event_type": t} for t in evs]}, kind


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rng = random.Random(args.seed)
    rep = ValidationReport("suite", "reward_fuzz", strict=strict)

    names = list(FUZZ_SPEC.keys()) + ["RewardTelemetry"]
    valid_rejected = wrongly_accepted = crashes = 0
    accepted_examples = []
    for _ in range(args.cases):
        name = rng.choice(names)
        if name == "RewardTelemetry":
            bad, kind = _telemetry_mutate(rng)
            fn = lambda o, strict=False: RX.validate_reward_telemetry(o, strict=strict, require_completion=True)
        else:
            spec = FUZZ_SPEC[name]
            fn = spec["validate"]
            bad, kind = mutate(rng, name, spec)
        try:
            fails = [c for c in fn(bad, strict=True) if not c[1]]
        except Exception as e:  # a validator must never crash on garbage input
            crashes += 1
            rep.check("fuzz::{}::no_crash".format(name), False,
                      "validator crashed on fuzz input ({}): {}".format(kind, e),
                      code=F.REWARD_FUZZ_ACCEPTED)
            continue
        if fails:
            valid_rejected += 1
        else:
            wrongly_accepted += 1
            if len(accepted_examples) < 5:
                accepted_examples.append("{}:{}".format(name, kind))

    rep.check("fuzz::no_wrongly_accepted", wrongly_accepted == 0,
              "{} malformed record(s) wrongly accepted ({})".format(wrongly_accepted, accepted_examples),
              code=F.REWARD_FUZZ_ACCEPTED)
    rep.check("fuzz::no_crashes", crashes == 0, "{} validator crash(es)".format(crashes),
              code=F.REWARD_FUZZ_ACCEPTED)
    rep.check("fuzz::cases_run", valid_rejected + wrongly_accepted + crashes == args.cases and args.cases > 0,
              "ran {} cases".format(args.cases), code=F.REWARD_FUZZ_ACCEPTED)

    rep.finalize()
    rep.set_meta(build_meta(command="reward-fuzz", pack=args.pack, strict=strict,
                            status=rep.status, record_count=args.cases, report_type="wf.reward.fuzz.v1",
                            records_total=args.cases, records_failed=wrongly_accepted + crashes))
    rep.write(REPO_ROOT / "procedural/reports/rewards/fuzz", "reward_fuzz_report.json")
    print("[reward-fuzz] cases={} valid_rejected={} wrongly_accepted={} crashes={}".format(
        args.cases, valid_rejected, wrongly_accepted, crashes))
    rep.print_summary("reward-fuzz")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
