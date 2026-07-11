#!/usr/bin/env python3
"""validate_tactical_contracts.py — v2.4 tactical contract-spine gate.

Proves the AdvancedAIForge / TacticalBehaviorForge schema spine (tactical_contracts.
CONTRACTS) is coherent and constrains correctly — the always-available, runtime-free
gate that is GREEN from Wave 1 while the authoring/runtime/operator gates stay honestly
RED until real artifacts exist.

DOGFOODS the registry: every valid example passes its own validator with zero failures;
every known-bad is REJECTED for its OWNING failure code. A validator that greens its
known-bad, or rejects the valid example, is a fake-green vector and turns this gate RED.
Mirrors validate_streaming_contracts.py exactly.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_tactical_contracts.py --strict
Reports -> procedural/reports/tactical/validate_tactical_contracts_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "tactical"


def dogfood(rep, names=None):
    names = names or list(TC.CONTRACTS.keys())
    n = 0
    for name in names:
        validate, good, bad = TC.CONTRACTS[name]
        n += 1
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("dogfood::{}::valid_example_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:4]),
                  code=FailureCode.TACTICAL_REPORT_INTEGRITY_FAILED)
        bfails = [c for c in validate(bad(), strict=True) if not c[1]]
        codes = {c[3] for c in bfails}
        rep.check("dogfood::{}::known_bad_rejected".format(name), len(bfails) > 0,
                  "known-bad example must be rejected",
                  code=FailureCode.TACTICAL_NEGATIVE_ACCEPTED)
        owning = TC.KNOWN_BAD_OWNING_CODE.get(name)
        rep.check("dogfood::{}::rejected_for_owning_code".format(name), owning in codes,
                  "known-bad must be rejected for owning code {} (got {})".format(
                      owning, sorted(str(c) for c in codes)[:4]),
                  code=FailureCode.TACTICAL_NEGATIVE_ACCEPTED)
    return n


def _registry_coherent(rep):
    rep.check("dogfood::registry_nonempty", len(TC.CONTRACTS) >= 15,
              "CONTRACTS registry must carry the 15 tactical contracts",
              code=FailureCode.TACTICAL_REPORT_INTEGRITY_FAILED)
    grouped = [c for lane in TC.CONTRACT_GROUPS.values() for c in lane]
    rep.check("dogfood::groups_partition_registry",
              sorted(grouped) == sorted(TC.CONTRACTS.keys()),
              "CONTRACT_GROUPS must partition CONTRACTS exactly",
              code=FailureCode.TACTICAL_REPORT_INTEGRITY_FAILED)
    rep.check("dogfood::known_bad_owning_complete",
              sorted(TC.KNOWN_BAD_OWNING_CODE.keys()) == sorted(TC.CONTRACTS.keys()),
              "KNOWN_BAD_OWNING_CODE must cover every contract",
              code=FailureCode.TACTICAL_REPORT_INTEGRITY_FAILED)
    rep.check("dogfood::owns_failure_band", len(TC.TACTICAL_CODES) >= 40,
              "tactical milestone must own the WF931-974 failure band",
              code=FailureCode.TACTICAL_UNKNOWN_FAILURE_CODE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical contract-spine gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = dogfood(rep)
    _registry_coherent(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="tactical-contracts", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.tactical.contract_spine.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_tactical_contracts_report.json")
    rep.print_summary("tactical-contracts")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
