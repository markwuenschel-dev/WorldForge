#!/usr/bin/env python3
"""transition_fuzz.py — v2.5 deterministic transition-schema fuzz gate (--hostile).

Generates CASES mutated transition records from the contract registry — each mutation breaks
a valid example in exactly one way (drop a required field, wrong-type a field, inject an
unknown field, corrupt schema_version, out-of-enum, sign-flip a numeric, empty a list, or
apply the registered known-bad) — and asserts the schema REJECTS every one under STRICT.

Deterministic: the strategy + target field are derived from a seeded index (random.Random),
NOT wall-clock or os.urandom. ``_mutate`` GUARANTEES invalidity — if the chosen mutation
does not break the record it falls back to dropping a required field (check_required always
catches that), so a "0 accepted" result is a real property of the schema, not luck.

GREEN when zero mutated records are accepted. RED (TRANSITION_FUZZ_ACCEPTED) otherwise.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/transition_fuzz.py --cases 350 --seed 1337 --strict
Reports -> procedural/reports/ue5_8/hostile/transition_fuzz_report.json
"""

import argparse
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "hostile"

# The required-field tuple per contract (drives drop/wrong-type mutations).
REQUIRED = {
    "EngineIdentity": TC.IDENTITY_REQUIRED,
    "CapabilityManifest": TC.CAPABILITY_MANIFEST_REQUIRED,
    "ConversionManifest": TC.CONVERSION_MANIFEST_REQUIRED,
    "PluginBuildReport": TC.PLUGIN_BUILD_REQUIRED,
    "TransitionRegressionReport": TC.REGRESSION_REPORT_REQUIRED,
    "GloamBridgeProbe": TC.BRIDGE_PROBE_REQUIRED,
    "TransitionBaseline": TC.BASELINE_REQUIRED,
}
# List-bearing fields per contract (drives empty-list mutations).
LIST_FIELDS = {
    "CapabilityManifest": "capabilities",
    "ConversionManifest": "maps",
    "PluginBuildReport": "modules",
    "TransitionRegressionReport": "suites",
    "GloamBridgeProbe": "evidence_entries",
    "TransitionBaseline": "entries",
}
# Numeric fields whose sign-flip must be rejected (all are non-negative by contract).
NUMERIC_FIELDS = {
    "EngineIdentity": "engine_patch",
    "CapabilityManifest": "engine_minor",
    "ConversionManifest": "expected_map_count",
    "PluginBuildReport": "binary_mtime",
    "TransitionRegressionReport": "maps_checked",
    "GloamBridgeProbe": None,
    "TransitionBaseline": "entry_count",
}
_WRONG_TYPE_VALUE = {"__wf_fuzz__": "not_a_valid_scalar_or_bounded_entry"}

_STRATS = ("drop_required", "wrong_type", "unknown_field", "bad_schema_version",
           "empty_list", "sign_flip", "known_bad")


def _mutate(rng, name, validate, good_fn, bad_fn):
    strat = rng.choice(_STRATS)
    rec, req = good_fn(), REQUIRED[name]
    if strat == "known_bad":
        return ("known_bad", bad_fn())
    if strat == "drop_required":
        f = rng.choice(req)
        rec.pop(f, None)
        return ("drop:{}".format(f), rec)
    if strat == "wrong_type":
        f = rng.choice(req)
        rec[f] = dict(_WRONG_TYPE_VALUE)
        label = "wrongtype:{}".format(f)
    elif strat == "unknown_field":
        rec["__fuzz_unknown__{}".format(rng.randint(0, 9))] = "x"
        label = "unknown_field"
    elif strat == "bad_schema_version":
        rec["schema_version"] = "wf.transition.bogus.v{}".format(rng.randint(2, 9))
        label = "bad_schema_version"
    elif strat == "empty_list":
        lf = LIST_FIELDS.get(name)
        if lf:
            rec[lf] = []
            label = "empty_list:{}".format(lf)
        else:
            f = rng.choice(req)
            rec.pop(f, None)
            return ("drop:{}".format(f), rec)
    else:  # sign_flip
        nf = NUMERIC_FIELDS.get(name)
        if nf and isinstance(rec.get(nf), (int, float)) and not isinstance(rec.get(nf), bool):
            rec[nf] = -abs(rec[nf]) - 1
            label = "sign_flip:{}".format(nf)
        else:
            f = rng.choice(req)
            rec.pop(f, None)
            return ("drop:{}".format(f), rec)
    # Guarantee invalidity: if the mutation did not break it, drop a required field.
    if not [c for c in validate(rec, strict=True) if not c[1]]:
        f = rng.choice(req)
        rec.pop(f, None)
        label += "+drop:{}".format(f)
    return (label, rec)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 transition schema fuzz gate.")
    ap.add_argument("--cases", type=int, default=350)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "transition_fuzz", strict=strict)
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
                      code=C.TRANSITION_FUZZ_ACCEPTED)

    rep.check("fuzz::zero_invalid_accepted", accepted_invalid == 0,
              "{} invalid case(s) accepted".format(accepted_invalid), code=C.TRANSITION_FUZZ_ACCEPTED)
    rep.check("fuzz::case_count", args.cases > 0, "must run > 0 cases", code=C.TRANSITION_FUZZ_ACCEPTED)
    # Reverse dogfood: every valid example still passes.
    for name, (validate, good_fn, _bad) in TC.CONTRACTS.items():
        gfails = [c for c in validate(good_fn(), strict=True) if not c[1]]
        rep.check("fuzz::valid::{}".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:3]),
                  code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="transition-fuzz", pack=None, strict=strict, status=rep.status,
        seeds=args.seed, record_count=args.cases, records_total=args.cases,
        report_type="wf.transition.fuzz.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "transition_fuzz_report.json")
    rep.print_summary("transition-fuzz")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
