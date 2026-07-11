#!/usr/bin/env python3
"""quest_faction_fuzz.py — v2.2 deterministic quest/faction schema fuzz (Wave R).

Generates CASES mutated quest/faction records from the contract registry — each
mutation breaks a valid example in exactly one way (drop a required field,
wrong-type a field, inject an unknown field, corrupt schema_version, or apply the
registered known-bad) — and asserts the schema REJECTS every one under STRICT. Zero
invalid cases may be accepted. Deterministic: the mutation stream is seeded
(--seed), so a failing case is reproducible.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/quest_faction_fuzz.py --cases 300 --seed 1337 --strict
Reports -> procedural/reports/quest_faction/negatives/quest_faction_fuzz_report.json
"""

import argparse
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import quest_faction_contracts as QF
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "negatives"

REQUIRED = {
    "QuestDefinition": QF.QUEST_DEF_REQUIRED,
    "QuestStep": QF.QUEST_STEP_REQUIRED,
    "QuestRuntimeState": QF.QUEST_RT_REQUIRED,
    "FactionDefinition": QF.FACTION_DEF_REQUIRED,
    "FactionState": QF.FACTION_STATE_REQUIRED,
    "FactionDelta": QF.FACTION_DELTA_REQUIRED,
    "ConsequenceLedger": QF.LEDGER_REQUIRED,
    "QuestFactionRuntimeReport": QF.RUNTIME_REPORT_REQUIRED,
    "QuestFactionEvidenceIndex": QF.EVIDENCE_INDEX_REQUIRED,
    "OperatorQuestView": QF.OP_QUEST_VIEW_REQUIRED,
    "OperatorFactionView": QF.OP_FACTION_VIEW_REQUIRED,
}
# Several quest/faction required fields ARE dicts (resources, relationships,
# resources_delta, relationship_deltas, completion/failure_predicate), so a plain
# dict is not automatically a type violation. This sentinel is a dict whose only
# entry has a non-numeric, non-predicate value — invalid for a scalar/list/enum
# field (it's a dict) AND for a bounded-number dict (the value is not a number) AND
# for a predicate dict (no 'claim' key).
_WRONG_TYPE_VALUE = {"__wf_fuzz__": "not_a_valid_scalar_or_bounded_entry"}


def _mutate(rng, name, good_fn, bad_fn):
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
        rec["schema_version"] = "wf.quest_faction.bogus.v{}".format(rng.randint(2, 9))
        return ("bad_schema_version", rec)
    return ("known_bad", bad_fn())


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 quest/faction schema fuzz.")
    ap.add_argument("--cases", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "quest_faction_fuzz", strict=strict)
    rng = random.Random(args.seed)

    names = list(QF.CONTRACTS.keys())
    accepted_invalid = 0
    for i in range(args.cases):
        name = names[i % len(names)]
        validate, good_fn, bad_fn = QF.CONTRACTS[name]
        label, rec = _mutate(rng, name, good_fn, bad_fn)
        fails = [c for c in validate(rec, strict=True) if not c[1]]
        if not fails:
            accepted_invalid += 1
            rep.check("fuzz::case{}::{}::{}".format(i, name, label), False,
                      "mutated {} record was ACCEPTED (fake green)".format(name),
                      code=F.QUEST_FACTION_FUZZ_ACCEPTED)

    rep.check("fuzz::zero_invalid_accepted", accepted_invalid == 0,
              "{} invalid case(s) accepted".format(accepted_invalid),
              code=F.QUEST_FACTION_FUZZ_ACCEPTED)
    rep.check("fuzz::case_count", args.cases > 0, "must run > 0 cases",
              code=F.QUEST_FACTION_FUZZ_ACCEPTED)
    for name, (validate, good_fn, _bad) in QF.CONTRACTS.items():
        gfails = [c for c in validate(good_fn(), strict=True) if not c[1]]
        rep.check("fuzz::valid::{}".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:3]),
                  code=F.QUEST_FACTION_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="quest-faction-fuzz", pack=None, strict=strict, status=rep.status,
        record_count=args.cases, records_total=args.cases,
        report_type="wf.quest_faction.fuzz.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "quest_faction_fuzz_report.json")
    rep.print_summary("quest-faction-fuzz")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
