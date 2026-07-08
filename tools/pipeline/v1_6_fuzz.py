#!/usr/bin/env python3
"""v1_6_fuzz.py — WorldForge v1.6 runtime contract fuzzer (Agent 7D).

Throws deterministic, seeded, randomly-corrupted runtime artifacts at every
contract validator and asserts two robustness invariants for each case:

  1. the validator NEVER raises (a crash on hostile input is a bug), and
  2. a corrupted artifact is REJECTED (a mutation that still validates clean is a
     hole in the contract's teeth).

Deterministic: a fixed --seed reproduces the exact case set, so the determinism
gate is satisfied and a failure is reproducible. Stdlib only.

Usage:
    python tools/pipeline/v1_6_fuzz.py --cases 300 [--seed 1337] [--strict]
Writes: procedural/reports/runtime/fuzz/v1_6_fuzz_report.json
"""

import argparse
import copy
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_scenario_contract as SC
import runtime_pawn_contract as PC
import runtime_route_contract as RC
import runtime_interaction_contract as IC
import runtime_completion_contract as CC
import runtime_save_load_contract as SL
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

# (name, validator, valid-fixture, required-fields) per contract. Nullable
# required fields (present-but-may-be-None) are excluded from the drop-must-reject
# assertion where the contract genuinely allows None — we only assert rejection
# for a dropped NON-nullable required field or an injected unknown field.
_NULLABLE = {"failure_code", "failure_owner", "replay_path", "telemetry_path"}
TARGETS = [
    ("scenario", lambda o: SC.validate_scenario(o, strict=True), SC._valid_fixture,
     SC.REQUIRED_FIELDS, SC.ALLOWED_FIELDS),
    ("pawn", lambda o: PC.validate_pawn_profile(o, strict=True), PC.default_profile,
     PC.REQUIRED_FIELDS, PC.ALLOWED_FIELDS),
    ("route", lambda o: RC.validate_route_plan(o, strict=True), RC._valid_fixture,
     RC.REQUIRED_FIELDS, RC.ALLOWED_FIELDS),
    ("interaction", lambda o: IC.validate_interaction_actor(o, strict=True), IC._valid_fixture,
     IC.REQUIRED_FIELDS, IC.ALLOWED_FIELDS),
    ("completion", lambda o: CC.validate_completion(o, strict=True), CC._valid_success,
     CC.REQUIRED_FIELDS, CC.ALLOWED_FIELDS),
    ("save_load", lambda o: SL.validate_save_load_proof(o, strict=True), SL._valid_verified,
     SL.REQUIRED_FIELDS, SL.ALLOWED_FIELDS),
]


def _must_reject(bad, required, allowed):
    """Compute from the ACTUAL corrupted object whether STRICT validation is
    GUARANTEED to reject it: a non-nullable required field is missing/None, or an
    unknown field is present. Predicting from the op attempted mis-fires when a
    mutation is a benign no-op — so we read the real end-state instead."""
    if not isinstance(bad, dict):
        return True
    missing_req = [k for k in required
                   if k not in _NULLABLE and (k not in bad or bad.get(k) is None)]
    unknown = [k for k in bad if k not in set(allowed)]
    return bool(missing_req or unknown)

_JUNK = [None, "", 0, -1, -999.0, [], {}, True, False, "💥", "../../etc",
         {"nested": {"deep": [1, 2, 3]}}, [None, None], 1e18, "NaN", " "]


def _corrupt(rng, obj, required):
    """Apply 1-3 random corruptions to a copy of a valid fixture. Returns the
    corrupted object; whether it MUST be rejected is computed afterward from the
    object's actual end-state (see _must_reject), not from the op attempted."""
    o = copy.deepcopy(obj)
    keys = list(o.keys())
    req_droppable = [k for k in required if k not in _NULLABLE]
    n = rng.randint(1, 3)
    for _ in range(n):
        op = rng.choice(("drop_req", "junk", "type", "extra", "empty"))
        if op == "drop_req" and req_droppable:
            o.pop(rng.choice(req_droppable), None)
        elif op == "junk" and keys:
            o[rng.choice(keys)] = rng.choice(_JUNK)
        elif op == "type" and keys:
            k = rng.choice(keys)
            v = o.get(k)
            o[k] = (str(v) + "_x") if not isinstance(v, str) else 12345
        elif op == "extra":
            o["__fuzz_%d__" % rng.randint(0, 9999)] = rng.choice(_JUNK)
        elif op == "empty" and keys:
            o[rng.choice(keys)] = rng.choice(([], {}, "", None))
    return o


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 runtime contract fuzzer.")
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rng = random.Random(args.seed)
    rep = ValidationReport("suite", "v1_6_fuzz", strict=strict)
    crashes = 0
    accepted_bad = 0
    n = 0
    for i in range(args.cases):
        name, validate, fixture, required, allowed = TARGETS[i % len(TARGETS)]
        bad = _corrupt(rng, fixture(), required)
        must_reject = _must_reject(bad, required, allowed)
        n += 1
        try:
            checks = validate(bad)
        except Exception as e:  # a crash on hostile input is a hard fail
            crashes += 1
            rep.check("fuzz[{}]::{}::no_crash".format(i, name), False,
                      "validator raised on corrupted input: {!r}".format(e),
                      code=FailureCode.V1_6_FUZZ_FAILURE)
            continue
        failed = any(not ok for _, ok, _, _ in checks)
        # A guaranteed-invalid corruption MUST be rejected.
        if must_reject and not failed:
            accepted_bad += 1
            rep.check("fuzz[{}]::{}::rejected".format(i, name), False,
                      "corrupted {} artifact validated clean: {}".format(
                          name, {k: bad.get(k) for k in list(bad)[:4]}),
                      code=FailureCode.V1_6_FUZZ_FAILURE)

    rep.check("no_validator_crashes", crashes == 0,
              "{} validator crash(es) on hostile input".format(crashes),
              code=FailureCode.V1_6_FUZZ_FAILURE)
    rep.check("no_corrupted_accepted", accepted_bad == 0,
              "{} corrupted artifacts validated clean".format(accepted_bad),
              code=FailureCode.V1_6_FUZZ_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="v1-6-fuzz", pack=None, strict=strict,
                            status=rep.status, record_count=n, seeds=args.seed,
                            report_type="wf.runtime.fuzz.v1",
                            extra={"cases": n, "seed": args.seed,
                                   "crashes": crashes, "accepted_bad": accepted_bad}))
    rep.write(REPO_ROOT / "procedural/reports/runtime/fuzz", "v1_6_fuzz_report.json")
    rep.print_summary("v1-6-fuzz")
    print("[v1-6-fuzz] {} cases, seed={}, {} crashes, {} corrupted-accepted".format(
        n, args.seed, crashes, accepted_bad))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
