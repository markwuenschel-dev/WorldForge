#!/usr/bin/env python3
"""npc_behavior_fuzz.py — WorldForge v1.7 NPCForge fuzz gate.

Deterministically mutates the canonical valid examples into malformed records
(drop a required field, wrong type, out-of-range number, unknown field, forbidden
enum) and asserts every mutant is REJECTED under STRICT — nothing malformed is
wrongly accepted, and no validator crashes. Seeded, so a fixed (--seed, --cases)
is reproducible.

Acceptance: `make npc-fuzz STRICT=1 CASES=300`.
"""
import argparse
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

# Per-contract fuzz spec: the fields whose corruption is GUARANTEED to violate the
# contract, so every generated mutant is genuinely invalid (no false positives).
#   required : required, non-nullable fields (drop/null -> invalid)
#   enum     : {field: registry} (a value outside the registry -> invalid)
#   number   : positive-number fields (a non-number / negative -> invalid)
# Telemetry has no field schema (it validates an events list) and is special-cased.
FUZZ_SPEC = {
    "NPCArchetype": dict(
        validate=NX.validate_archetype, good=NX._example_archetype,
        required=[f for f in NX.ARCHETYPE_REQUIRED],
        enum={"behavior_role": NX.NPC_ARCHETYPES, "movement_model": NX.MOVEMENT_MODELS,
              "pressure_model": NX.PRESSURE_MODELS, "route_blocking_policy": NX.ROUTE_BLOCKING_POLICIES},
        number=["capsule_radius", "capsule_half_height", "engagement_radius", "disengagement_radius"]),
    "NPCSpawnGroup": dict(
        validate=NX.validate_spawn_group, good=NX._example_spawn_group,
        required=[f for f in NX.SPAWN_GROUP_REQUIRED],
        enum={"formation_policy": NX.FORMATION_POLICIES, "route_binding_policy": NX.ROUTE_BINDING_POLICIES,
              "spawn_zone_policy": NX.SPAWN_ZONE_POLICIES},
        number=["max_density", "min_distance_from_objective", "min_distance_from_player_spawn"]),
    "PerceptionModel": dict(
        validate=NX.validate_perception_model, good=NX._example_perception,
        required=[f for f in NX.PERCEPTION_REQUIRED], enum={"occlusion_policy": NX.OCCLUSION_POLICIES},
        number=["radius", "update_interval_seconds"]),
    "PressureModel": dict(
        validate=NX.validate_pressure_model, good=NX._example_pressure,
        required=[f for f in NX.PRESSURE_REQUIRED], enum={"pressure_type": NX.PRESSURE_TYPES},
        number=["radius", "tick_interval_seconds", "max_pressure_duration"]),
    "BehaviorProfile": dict(
        validate=NX.validate_behavior_profile, good=NX._example_behavior_profile,
        required=[f for f in NX.BEHAVIOR_PROFILE_REQUIRED],
        enum={"encounter_archetype": NX.ENCOUNTER_ARCHETYPES}, number=[]),
    "NPCBehaviorState": dict(
        validate=NX.validate_behavior_state, good=NX._example_behavior_state,
        required=[f for f in NX.BEHAVIOR_STATE_REQUIRED if f not in ("current_route_node", "current_target")],
        enum={"current_state": NX.BEHAVIOR_STATES}, number=["spawned_at", "last_state_change"]),
    "BehaviorScenario": dict(
        validate=NX.validate_behavior_scenario, good=NX._example_behavior_scenario,
        required=[f for f in NX.BEHAVIOR_SCENARIO_REQUIRED], enum={}, number=["timeout_seconds"]),
    "BehaviorCompletionReport": dict(
        validate=NX.validate_completion_report, good=NX._example_completion,
        required=[f for f in NX.COMPLETION_REQUIRED if f != "failure_owner"],
        enum={"status": NX.RESULT_STATUS, "completion_class": NX.COMPLETION_CLASSES},
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
    """Telemetry validates an events list — mutate that (completion-required)."""
    kind = rng.choice(["drop_events", "events_not_list", "empty_events", "bad_event_type",
                       "missing_pressure"])
    if kind == "drop_events":
        return {"report_type": NX.TELEMETRY_SCHEMA_VERSION}, kind
    if kind == "events_not_list":
        return {"events": "not_a_list"}, kind
    if kind == "empty_events":
        return {"events": []}, kind
    if kind == "bad_event_type":
        return {"events": [{"event_type": "not.a.real.event"}]}, kind
    # missing_pressure: all completion events except the pressure one.
    evs = [t for t in NX.COMPLETION_REQUIRED_EVENTS if t != "behavior.pressure.applied"]
    return {"events": [{"event_type": t} for t in evs]}, kind


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rng = random.Random(args.seed)
    rep = ValidationReport("suite", "npc_behavior_fuzz", strict=strict)

    names = list(FUZZ_SPEC.keys()) + ["BehaviorTelemetry"]
    valid_rejected = wrongly_accepted = crashes = 0
    accepted_examples = []
    for _ in range(args.cases):
        name = rng.choice(names)
        if name == "BehaviorTelemetry":
            bad, kind = _telemetry_mutate(rng)
            fn = lambda o, strict=False: NX.validate_telemetry(o, strict=strict, require_completion=True)
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
                      code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)
            continue
        if fails:
            valid_rejected += 1
        else:
            wrongly_accepted += 1
            if len(accepted_examples) < 5:
                accepted_examples.append("{}:{}".format(name, kind))

    rep.check("fuzz::no_wrongly_accepted", wrongly_accepted == 0,
              "{} malformed record(s) wrongly accepted ({})".format(wrongly_accepted, accepted_examples),
              code=FailureCode.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE)
    rep.check("fuzz::no_crashes", crashes == 0, "{} validator crash(es)".format(crashes),
              code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)
    rep.check("fuzz::cases_run", valid_rejected + wrongly_accepted + crashes == args.cases,
              "ran {} cases".format(args.cases), code=FailureCode.NPC_REPORT_INTEGRITY_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="npc-fuzz", pack="encounter_loop_world", strict=strict,
                            status=rep.status, record_count=args.cases, report_type="wf.npc.fuzz.v1",
                            records_total=args.cases, records_failed=wrongly_accepted + crashes))
    rep.write(REPO_ROOT / "procedural/reports/npc/fuzz", "npc_behavior_fuzz_report.json")
    print("[fuzz] cases={} valid_rejected={} wrongly_accepted={} crashes={}".format(
        args.cases, valid_rejected, wrongly_accepted, crashes))
    rep.print_summary("npc-fuzz")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
