#!/usr/bin/env python3
"""combat_fuzz.py — WorldForge v1.8 CombatForge Alpha fuzz gate.

Deterministically mutates the canonical valid combat examples into malformed
records (drop a required field, null a required field, wrong type, out-of-range
number, unknown field, forbidden enum, telemetry-shape corruption) and asserts
every mutant is REJECTED under STRICT — nothing malformed is wrongly accepted and
no validator crashes on garbage. Seeded, so a fixed (--seed, --cases) is
reproducible. Mirrors [[npc_behavior_fuzz]].

Acceptance: ``PYTHONUTF8=1 STRICT=1 python tools/pipeline/combat_fuzz.py --cases 300 --seed 1337 --strict``.
Exit nonzero if any record is wrongly accepted or any validator crashes.
"""
import argparse
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode as F

# Per-contract fuzz spec: fields whose corruption is GUARANTEED to violate the
# contract, so every generated mutant is genuinely invalid (no false positives).
#   required : required, non-nullable fields (drop/null -> invalid)
#   enum     : {field: registry} (a value outside the registry -> invalid)
#   number   : numeric fields (a non-number / negative -> invalid)
# CombatTelemetry has no field schema (it validates an events list) and is
# special-cased below.
FUZZ_SPEC = {
    "CombatProfile": dict(
        validate=CC.validate_combat_profile, good=CC._example_combat_profile,
        required=[f for f in CC.COMBAT_PROFILE_REQUIRED],
        enum={"encounter_archetype": CC.ENCOUNTER_ARCHETYPES,
              "mission_completion_policy": CC.MISSION_COMPLETION_POLICIES},
        number=["player_max_health", "baseline_expected_damage"]),
    "PlayerCombatState": dict(
        validate=CC.validate_player_combat_state, good=CC._example_player_combat_state,
        required=[f for f in CC.PLAYER_COMBAT_STATE_REQUIRED if f != "last_damage_source"],
        enum={},
        number=["max_health", "current_health", "damage_taken_total", "last_damage_at"]),
    "DamageEvent": dict(
        validate=CC.validate_damage_event, good=CC._example_damage_event,
        required=[f for f in CC.DAMAGE_EVENT_REQUIRED],
        enum={"source_type": CC.DAMAGE_SOURCE_TYPES, "damage_type": CC.DAMAGE_TYPES},
        number=["at_seconds", "amount", "health_before", "health_after"]),
    "CombatCompletionReport": dict(
        validate=CC.validate_combat_completion_report, good=CC._example_combat_completion,
        required=[f for f in CC.COMBAT_COMPLETION_REQUIRED if f != "failure_owner"],
        enum={"status": CC.RESULT_STATUS, "completion_class": CC.COMBAT_COMPLETION_CLASSES,
              "survivability_band": CC.SURVIVABILITY_BANDS},
        number=["runtime_duration_seconds"]),
}


def mutate(rng, name, spec):
    """Return (malformed_record, mutation_tag) that GENUINELY violates the contract."""
    rec = dict(spec["good"]())
    choices = ["drop", "null_required", "unknown_field"]
    if spec["enum"]:
        choices.append("bad_enum")
    if spec["number"]:
        choices.append("bad_number")
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
    return rec, kind


def _telemetry_mutate(rng):
    """CombatTelemetry validates an events list — mutate that (completion-required)."""
    kind = rng.choice(["drop_events", "events_not_list", "empty_events", "bad_event_type",
                       "missing_damage"])
    if kind == "drop_events":
        return {"report_type": CC.COMBAT_TELEMETRY_SCHEMA_VERSION}, kind
    if kind == "events_not_list":
        return {"events": "not_a_list"}, kind
    if kind == "empty_events":
        return {"events": []}, kind
    if kind == "bad_event_type":
        return {"events": [{"event_type": "not.a.real.combat.event"}]}, kind
    # missing_damage: all completion events except the player-damage one.
    evs = [t for t in CC.COMPLETION_REQUIRED_COMBAT_EVENTS if t != "combat.player.damage.taken"]
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
    rep = ValidationReport("suite", "combat_fuzz", strict=strict)

    names = list(FUZZ_SPEC.keys()) + ["CombatTelemetry"]
    valid_rejected = wrongly_accepted = crashes = 0
    accepted_examples = []
    for _ in range(args.cases):
        name = rng.choice(names)
        if name == "CombatTelemetry":
            bad, kind = _telemetry_mutate(rng)
            fn = lambda o, strict=False: CC.validate_combat_telemetry(o, strict=strict, require_completion=True)
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
                      code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
            continue
        if fails:
            valid_rejected += 1
        else:
            wrongly_accepted += 1
            if len(accepted_examples) < 5:
                accepted_examples.append("{}:{}".format(name, kind))

    rep.check("fuzz::no_wrongly_accepted", wrongly_accepted == 0,
              "{} malformed record(s) wrongly accepted ({})".format(wrongly_accepted, accepted_examples),
              code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
    rep.check("fuzz::no_crashes", crashes == 0, "{} validator crash(es)".format(crashes),
              code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
    rep.check("fuzz::cases_run", valid_rejected + wrongly_accepted + crashes == args.cases,
              "ran {} cases".format(args.cases), code=F.COMBAT_REPORT_INTEGRITY_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="combat-fuzz", pack=args.pack, strict=strict,
                            status=rep.status, record_count=args.cases, report_type="wf.combat.fuzz.v1",
                            records_total=args.cases, records_failed=wrongly_accepted + crashes))
    rep.write(REPO_ROOT / "procedural/reports/combat/fuzz", "combat_fuzz_report.json")
    print("[combat-fuzz] cases={} valid_rejected={} wrongly_accepted={} crashes={}".format(
        args.cases, valid_rejected, wrongly_accepted, crashes))
    rep.print_summary("combat-fuzz")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
