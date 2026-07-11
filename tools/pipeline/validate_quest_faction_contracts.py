#!/usr/bin/env python3
"""validate_quest_faction_contracts.py — v2.2 quest/faction contract-spine gate.

Proves the QuestForge + FactionStateForge schema spine (quest_faction_contracts.
CONTRACTS) is coherent and constrains correctly — the always-available, runtime-free
gate that is GREEN from Wave 1 while the authoring/runtime/operator gates stay
honestly RED until real artifacts exist.

It DOGFOODS the schema registry: every valid example must pass its own validator
with zero failures, and every known-bad example must be REJECTED for its OWNING
failure code. A validator that greens its known-bad, or one that rejects the valid
example, is a fake-green vector and turns this gate RED — no real data required.

This mirrors validate_operator_contracts.py exactly (the v2.1 gate). The quest and
faction sub-gates (validate_quest_contracts.py / validate_faction_contracts.py)
import `dogfood` from here and run a subset.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_quest_faction_contracts.py --strict
Reports -> procedural/reports/quest_faction/validate_quest_faction_contracts_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import quest_faction_contracts as QF
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction"


def dogfood(rep, names=None):
    """Dogfood a subset (or all) of the CONTRACTS registry into `rep`.

    Returns the number of contracts checked. Every valid example must pass; every
    known-bad must be rejected FOR its owning code.
    """
    names = names or list(QF.CONTRACTS.keys())
    n = 0
    for name in names:
        validate, good, bad = QF.CONTRACTS[name]
        n += 1
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("dogfood::{}::valid_example_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:4]),
                  code=FailureCode.QUEST_FACTION_REPORT_INTEGRITY_FAILED)
        bfails = [c for c in validate(bad(), strict=True) if not c[1]]
        codes = {c[3] for c in bfails}
        rep.check("dogfood::{}::known_bad_rejected".format(name), len(bfails) > 0,
                  "known-bad example must be rejected",
                  code=FailureCode.QUEST_FACTION_NEGATIVE_ACCEPTED)
        owning = QF.KNOWN_BAD_OWNING_CODE.get(name)
        rep.check("dogfood::{}::rejected_for_owning_code".format(name),
                  owning in codes,
                  "known-bad must be rejected for owning code {} (got {})".format(
                      owning, sorted(str(c) for c in codes)[:4]),
                  code=FailureCode.QUEST_FACTION_NEGATIVE_ACCEPTED)
    return n


def _registry_coherent(rep):
    rep.check("dogfood::registry_nonempty", len(QF.CONTRACTS) > 0,
              "CONTRACTS registry must not be empty",
              code=FailureCode.QUEST_FACTION_REPORT_INTEGRITY_FAILED)
    grouped = [c for lane in QF.CONTRACT_GROUPS.values() for c in lane]
    rep.check("dogfood::groups_partition_registry",
              sorted(grouped) == sorted(QF.CONTRACTS.keys()),
              "CONTRACT_GROUPS must partition CONTRACTS exactly (got {} vs {})".format(
                  sorted(grouped), sorted(QF.CONTRACTS.keys())),
              code=FailureCode.QUEST_FACTION_REPORT_INTEGRITY_FAILED)
    # every known-bad has an owning code and every contract has a known-bad.
    rep.check("dogfood::known_bad_owning_complete",
              sorted(QF.KNOWN_BAD_OWNING_CODE.keys()) == sorted(QF.CONTRACTS.keys()),
              "KNOWN_BAD_OWNING_CODE must cover every contract",
              code=FailureCode.QUEST_FACTION_REPORT_INTEGRITY_FAILED)
    # the milestone owns a real WF771-850 band.
    rep.check("dogfood::owns_failure_code_band", len(QF.QUEST_FACTION_CODES) >= 30,
              "quest/faction milestone must own the WF771-804 failure band",
              code=FailureCode.QUEST_FACTION_UNKNOWN_FAILURE_CODE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 quest/faction contract-spine gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = dogfood(rep)
    _registry_coherent(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="quest-faction-contracts", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.quest_faction.contract_spine.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_quest_faction_contracts_report.json")
    rep.print_summary("quest-faction-contracts")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
