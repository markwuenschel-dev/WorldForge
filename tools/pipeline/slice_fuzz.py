#!/usr/bin/env python3
"""slice_fuzz.py — v2.0 Agent-7 deterministic schema fuzz.

Generates CASES mutated slice records from the contract registry — each mutation
breaks the record in exactly one way (drop a required field, wrong-type a field,
inject an unknown field, or violate a known invariant) — and asserts the schema
REJECTS every one under STRICT. Zero invalid cases may be accepted. Deterministic:
the mutation stream is seeded (--seed), so a failing case is reproducible.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/slice_fuzz.py --cases 300 --seed 1337 --strict
Reports -> procedural/reports/slice/negatives/slice_fuzz_report.json
"""

import argparse
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "slice" / "negatives"

# per-contract required fields whose removal/corruption must break validation.
_REQUIRED = {
    "VerticalSliceContract": SX.VERTICAL_SLICE_CONTRACT_REQUIRED,
    "SliceScenario": SX.SLICE_SCENARIO_REQUIRED,
    "SliceManifest": SX.SLICE_MANIFEST_REQUIRED,
    "SliceRuntimeReport": SX.SLICE_RUNTIME_REPORT_REQUIRED,
    "SlicePackageReport": SX.SLICE_PACKAGE_REPORT_REQUIRED,
    "SliceEvidenceIndex": SX.SLICE_EVIDENCE_INDEX_REQUIRED,
}
def _wrong_typed_value(rng, good_val):
    """Return a value of a DEFINITELY-wrong type for good_val, so the mutation is
    guaranteed to violate the field's type/enum/non-empty rule (no false rejects).
    bool is checked before int since bool is an int subclass in Python."""
    if isinstance(good_val, bool):
        return rng.choice(("not_a_bool", 5, [], {}))
    if isinstance(good_val, str):
        return rng.choice((123, [], {}, True, None))
    if isinstance(good_val, list):
        return rng.choice(("not_a_list", 7, {}, True))
    if isinstance(good_val, (int, float)):
        return rng.choice(("not_a_number", [], {}, None))
    return None  # unknown/None good value -> None reliably fails "required, not None"


def _mutate(rng, name, good):
    """Return (label, mutated_record) that MUST fail validation under STRICT.

    Every mode is guaranteed-invalid: drop a required field, assign a
    definitely-wrong-typed value, inject an unknown field (STRICT rejects), or
    corrupt schema_version (must match exactly). No mode can coincidentally
    produce a still-valid record.
    """
    good_rec = good()
    rec = dict(good_rec)
    req = [f for f in _REQUIRED[name] if f != "schema_version"]
    mode = rng.choice(("drop_required", "wrong_type", "unknown_field", "schemaver"))
    if mode == "drop_required" and req:
        f = rng.choice(req)
        rec.pop(f, None)
        return "drop:{}:{}".format(name, f), rec
    if mode == "wrong_type" and req:
        f = rng.choice(req)
        rec[f] = _wrong_typed_value(rng, good_rec.get(f))
        return "type:{}:{}".format(name, f), rec
    if mode == "unknown_field":
        rec["__fuzz_unknown_{}".format(rng.randint(0, 9999))] = 1
        return "unknown:{}".format(name), rec
    rec["schema_version"] = rng.choice(("wf.slice.bogus.v9", "", None, 42))
    return "schemaver:{}".format(name), rec


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice schema fuzz.")
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rng = random.Random(args.seed)
    rep = ValidationReport("suite", "slice_fuzz", strict=strict)
    names = list(SX.CONTRACTS.keys())

    accepted_invalid = 0
    for i in range(args.cases):
        name = rng.choice(names)
        validate, good, _bad = SX.CONTRACTS[name]
        label, rec = _mutate(rng, name, good)
        fails = [c for c in validate(rec, strict=True) if not c[1]]
        if not fails:
            accepted_invalid += 1
            rep.check("fuzz::case{}::{}".format(i, label), False,
                      "mutated record accepted (should reject): {}".format(rec),
                      code=F.SLICE_FUZZ_ACCEPTED)

    rep.check("fuzz::zero_invalid_accepted", accepted_invalid == 0,
              "{} invalid fuzz cases accepted".format(accepted_invalid),
              code=F.SLICE_FUZZ_ACCEPTED)
    rep.check("fuzz::case_count", args.cases > 0, "must run >0 cases",
              code=F.SLICE_FUZZ_ACCEPTED)
    # reverse guard: a clean valid example of every contract still passes.
    for name, (validate, good, _bad) in SX.CONTRACTS.items():
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("fuzz::valid::{}".format(name), len(gfails) == 0,
                  "valid example rejected", code=F.SLICE_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(command="slice-fuzz", pack=None, strict=strict,
                            seeds=[args.seed], status=rep.status, record_count=args.cases,
                            records_total=args.cases, report_type="wf.slice.fuzz.v1"))
    rep.write(REPORT_DIR, "slice_fuzz_report.json")
    rep.print_summary("slice-fuzz")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
