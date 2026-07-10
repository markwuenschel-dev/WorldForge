#!/usr/bin/env python3
"""operator_fuzz.py — v2.1 OperatorForge deterministic schema fuzz (Wave R).

Generates CASES mutated operator records from the contract registry — each
mutation breaks a valid example in exactly one way (drop a required field,
wrong-type a field, inject an unknown field, corrupt schema_version, or apply the
registered known-bad) — and asserts the schema REJECTS every one under STRICT.
Zero invalid cases may be accepted. Deterministic: the mutation stream is seeded
(--seed), so a failing case is reproducible.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/operator_fuzz.py --cases 300 --seed 1337 --strict
Reports -> procedural/reports/operator/negatives/operator_fuzz_report.json
"""

import argparse
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_contracts as OX
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "negatives"

# contract name -> its REQUIRED field tuple (dropping any of these must reject).
REQUIRED = {
    "OperatorReportIndex": OX.REPORT_INDEX_REQUIRED,
    "OperatorPackCard": OX.PACK_CARD_REQUIRED,
    "OperatorScenarioCard": OX.SCENARIO_CARD_REQUIRED,
    "EvidenceTrace": OX.EVIDENCE_TRACE_REQUIRED,
    "FailureCodeIndex": OX.FAILURE_CODE_INDEX_REQUIRED,
    "AssetOwnershipView": OX.ASSET_OWNERSHIP_REQUIRED,
    "RouteWalkabilityView": OX.ROUTE_VIEW_REQUIRED,
    "OperatorCommandRequest": OX.COMMAND_REQUEST_REQUIRED,
    "OperatorCommandResult": OX.COMMAND_RESULT_REQUIRED,
    "OperatorDiffReport": OX.DIFF_REPORT_REQUIRED,
    "KnownRegressionRegistry": OX.KNOWN_REGRESSION_REQUIRED,
}

# A non-empty dict is never a valid value for any required operator field (all are
# str/int/bool/list/enum), so it is a type violation regardless of the field.
_WRONG_TYPE_VALUE = {"__wrong_type__": 1}


def _mutate(rng, name, validate, good_fn, bad_fn):
    """Return (label, mutated_record) that must be rejected under strict."""
    strat = rng.choice(("drop_required", "wrong_type", "unknown_field",
                        "bad_schema_version", "known_bad"))
    rec = good_fn()
    req = REQUIRED[name]
    if strat == "drop_required":
        f = rng.choice(req)
        rec.pop(f, None)
        return ("drop:{}".format(f), rec)
    if strat == "wrong_type":
        f = rng.choice(req)
        rec[f] = dict(_WRONG_TYPE_VALUE)
        return ("wrongtype:{}".format(f), rec)
    if strat == "unknown_field":
        rec["__fuzz_unknown__{}".format(rng.randint(0, 9))] = "x"
        return ("unknown_field", rec)
    if strat == "bad_schema_version":
        rec["schema_version"] = "wf.operator.bogus.v{}".format(rng.randint(2, 9))
        return ("bad_schema_version", rec)
    return ("known_bad", bad_fn())


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator schema fuzz.")
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "operator_fuzz", strict=strict)
    rng = random.Random(args.seed)

    names = list(OX.CONTRACTS.keys())
    accepted_invalid = 0
    for i in range(args.cases):
        name = names[i % len(names)]
        validate, good_fn, bad_fn = OX.CONTRACTS[name]
        label, rec = _mutate(rng, name, validate, good_fn, bad_fn)
        fails = [c for c in validate(rec, strict=True) if not c[1]]
        if not fails:
            accepted_invalid += 1
            rep.check("fuzz::case{}::{}::{}".format(i, name, label), False,
                      "mutated {} record was ACCEPTED (fake green)".format(name),
                      code=F.OPERATOR_FUZZ_ACCEPTED)

    rep.check("fuzz::zero_invalid_accepted", accepted_invalid == 0,
              "{} invalid case(s) accepted".format(accepted_invalid),
              code=F.OPERATOR_FUZZ_ACCEPTED)
    rep.check("fuzz::case_count", args.cases > 0, "must run > 0 cases",
              code=F.OPERATOR_FUZZ_ACCEPTED)
    # reverse: every valid example must still pass (no reject-everything fake).
    for name, (validate, good_fn, _bad) in OX.CONTRACTS.items():
        gfails = [c for c in validate(good_fn(), strict=True) if not c[1]]
        rep.check("fuzz::valid::{}".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:3]),
                  code=F.OPERATOR_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-fuzz", pack=None, strict=strict, status=rep.status,
        record_count=args.cases, records_total=args.cases,
        report_type="wf.operator.fuzz.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "operator_fuzz_report.json")
    rep.print_summary("operator-fuzz")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
