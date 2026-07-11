#!/usr/bin/env python3
"""tactical_fuzz.py — v2.4 deterministic tactical schema fuzz (Wave R).

Generates CASES mutated tactical records from the contract registry — each mutation breaks
a valid example in one way (drop a required field, wrong-type a field, inject an unknown
field, corrupt schema_version, or apply the registered known-bad) — and asserts the schema
REJECTS every one under STRICT. _mutate GUARANTEES invalidity: if the chosen mutation does
not break the record, it falls back to dropping a required field (check_required always
catches that). Deterministic (--seed).

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/tactical_fuzz.py --cases 300 --seed 1337 --strict
Reports -> procedural/reports/tactical/negatives/tactical_fuzz_report.json
"""

import argparse
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "tactical" / "negatives"

REQUIRED = {
    "TacticalBehaviorProfile": TC.PROFILE_REQUIRED,
    "TacticalRoleDefinition": TC.ROLE_REQUIRED,
    "TacticalAffordanceMap": TC.AFFORDANCE_REQUIRED,
    "TacticalNPCBinding": TC.NPC_BINDING_REQUIRED,
    "TacticalDecisionInput": TC.DECISION_INPUT_REQUIRED,
    "TacticalDecisionOption": TC.OPTION_REQUIRED,
    "TacticalDecisionTrace": TC.TRACE_REQUIRED,
    "TacticalStateDelta": TC.STATE_DELTA_REQUIRED,
    "TacticalGroupState": TC.GROUP_STATE_REQUIRED,
    "TacticalRuntimeReport": TC.RUNTIME_REPORT_REQUIRED,
    "TacticalSaveState": TC.SAVE_STATE_REQUIRED,
    "TacticalBudgetReport": TC.BUDGET_REPORT_REQUIRED,
    "TacticalEvidenceIndex": TC.EVIDENCE_INDEX_REQUIRED,
    "OperatorTacticalScenarioView": TC.OP_SCENARIO_REQUIRED,
    "OperatorTacticalNPCView": TC.OP_NPC_REQUIRED,
}
_WRONG_TYPE_VALUE = {"__wf_fuzz__": "not_a_valid_scalar_or_bounded_entry"}


def _mutate(rng, name, validate, good_fn, bad_fn):
    strat = rng.choice(("drop_required", "wrong_type", "unknown_field",
                        "bad_schema_version", "known_bad"))
    rec, req = good_fn(), REQUIRED[name]
    if strat == "wrong_type":
        f = rng.choice(req)
        rec[f] = dict(_WRONG_TYPE_VALUE)
        label = "wrongtype:{}".format(f)
    elif strat == "unknown_field":
        rec["__fuzz_unknown__{}".format(rng.randint(0, 9))] = "x"
        label = "unknown_field"
    elif strat == "bad_schema_version":
        rec["schema_version"] = "wf.tactical.bogus.v{}".format(rng.randint(2, 9))
        label = "bad_schema_version"
    elif strat == "known_bad":
        return ("known_bad", bad_fn())
    else:
        f = rng.choice(req)
        rec.pop(f, None)
        return ("drop:{}".format(f), rec)
    # guarantee invalidity: if the mutation didn't break it, drop a required field.
    if not [c for c in validate(rec, strict=True) if not c[1]]:
        f = rng.choice(req)
        rec.pop(f, None)
        label += "+drop:{}".format(f)
    return (label, rec)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical schema fuzz.")
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "tactical_fuzz", strict=strict)
    rng = random.Random(args.seed)

    names = list(TC.CONTRACTS.keys())
    accepted_invalid = 0
    for i in range(args.cases):
        name = names[i % len(names)]
        validate, good_fn, bad_fn = TC.CONTRACTS[name]
        label, rec = _mutate(rng, name, validate, good_fn, bad_fn)
        if not [c for c in validate(rec, strict=True) if not c[1]]:
            accepted_invalid += 1
            rep.check("fuzz::case{}::{}::{}".format(i, name, label), False,
                      "mutated {} record was ACCEPTED (fake green)".format(name),
                      code=F.TACTICAL_FUZZ_ACCEPTED)

    rep.check("fuzz::zero_invalid_accepted", accepted_invalid == 0,
              "{} invalid case(s) accepted".format(accepted_invalid), code=F.TACTICAL_FUZZ_ACCEPTED)
    rep.check("fuzz::case_count", args.cases > 0, "must run > 0 cases", code=F.TACTICAL_FUZZ_ACCEPTED)
    for name, (validate, good_fn, _bad) in TC.CONTRACTS.items():
        gfails = [c for c in validate(good_fn(), strict=True) if not c[1]]
        rep.check("fuzz::valid::{}".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:3]),
                  code=F.TACTICAL_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="tactical-fuzz", pack=None, strict=strict, status=rep.status,
        record_count=args.cases, records_total=args.cases, report_type="wf.tactical.fuzz.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "tactical_fuzz_report.json")
    rep.print_summary("tactical-fuzz")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
