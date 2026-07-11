#!/usr/bin/env python3
"""quest_faction_negative_validators.py — v2.2 aggregate negative-validator gate (Wave R).

The envelope gate that proves the FULL handoff §7/§10.7 known-bad catalog is
rejected — the contract-fixture negatives (quest_faction_negatives.cases) AND the
evidence-layer fake-proofs (quest_faction_torture.modes) together — each for its
owning code, with a non-vacuous floor so the catalog cannot silently shrink. This is
the single gate an operator runs to answer "can any known way of faking a green
quest/faction consequence slip through?" — the answer must be no.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/quest_faction_negative_validators.py --strict
Reports -> procedural/reports/quest_faction/negatives/quest_faction_negative_validators_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import quest_faction_contracts as QF
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from quest_faction_negatives import cases as contract_cases
from quest_faction_torture import modes as evidence_modes

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "negatives"


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 aggregate negative-validator gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "quest_faction_negative_validators", strict=strict)
    catalog = []
    for label, validate, rec, owning in contract_cases():
        catalog.append(("contract::" + label, validate, rec, owning))
    for label, validate, rec, owning in evidence_modes():
        catalog.append(("evidence::" + label, validate, rec, owning))

    rep.check("catalog::non_vacuous", len(catalog) >= 40,
              "known-bad catalog must carry >= 40 cases (got {})".format(len(catalog)),
              code=F.QUEST_FACTION_NEGATIVE_ACCEPTED)

    for label, validate, rec, owning in catalog:
        fails = [c for c in validate(rec, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("nv::{}::rejected".format(label), len(fails) > 0,
                  "known-bad was ACCEPTED (fake green)",
                  code=F.QUEST_FACTION_NEGATIVE_ACCEPTED)
        rep.check("nv::{}::owning_code".format(label), owning in codes,
                  "must be rejected for {} (got {})".format(
                      owning, sorted(str(x) for x in codes)[:4]),
                  code=F.QUEST_FACTION_NEGATIVE_ACCEPTED)

    # reverse dogfood: every valid example still passes.
    for name, (validate, good, _bad) in QF.CONTRACTS.items():
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("reverse::{}::valid_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:4]),
                  code=F.QUEST_FACTION_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="quest-faction-negative-validators", pack=None, strict=strict,
        status=rep.status, record_count=len(catalog), records_total=len(catalog),
        report_type="wf.quest_faction.negative_validators.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "quest_faction_negative_validators_report.json")
    rep.print_summary("quest-faction-negative-validators")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
