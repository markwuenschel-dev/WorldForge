#!/usr/bin/env python3
"""validate_streaming_contracts.py — v2.3 streaming contract-spine gate.

Proves the StreamingForge / WorldScaleForge schema spine (streaming_contracts.
CONTRACTS) is coherent and constrains correctly — the always-available, runtime-free
gate that is GREEN from Wave 1 while the authoring/runtime/operator gates stay
honestly RED until real artifacts exist.

DOGFOODS the registry: every valid example passes its own validator with zero
failures; every known-bad is REJECTED for its OWNING failure code. A validator that
greens its known-bad, or rejects the valid example, is a fake-green vector and turns
this gate RED. Mirrors validate_quest_faction_contracts.py exactly.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_streaming_contracts.py --strict
Reports -> procedural/reports/streaming/validate_streaming_contracts_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_contracts as SC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "streaming"


def dogfood(rep, names=None):
    names = names or list(SC.CONTRACTS.keys())
    n = 0
    for name in names:
        validate, good, bad = SC.CONTRACTS[name]
        n += 1
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("dogfood::{}::valid_example_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:4]),
                  code=FailureCode.STREAMING_REPORT_INTEGRITY_FAILED)
        bfails = [c for c in validate(bad(), strict=True) if not c[1]]
        codes = {c[3] for c in bfails}
        rep.check("dogfood::{}::known_bad_rejected".format(name), len(bfails) > 0,
                  "known-bad example must be rejected",
                  code=FailureCode.STREAMING_NEGATIVE_ACCEPTED)
        owning = SC.KNOWN_BAD_OWNING_CODE.get(name)
        rep.check("dogfood::{}::rejected_for_owning_code".format(name), owning in codes,
                  "known-bad must be rejected for owning code {} (got {})".format(
                      owning, sorted(str(c) for c in codes)[:4]),
                  code=FailureCode.STREAMING_NEGATIVE_ACCEPTED)
    return n


def _registry_coherent(rep):
    rep.check("dogfood::registry_nonempty", len(SC.CONTRACTS) >= 13,
              "CONTRACTS registry must carry the 13 streaming contracts",
              code=FailureCode.STREAMING_REPORT_INTEGRITY_FAILED)
    grouped = [c for lane in SC.CONTRACT_GROUPS.values() for c in lane]
    rep.check("dogfood::groups_partition_registry",
              sorted(grouped) == sorted(SC.CONTRACTS.keys()),
              "CONTRACT_GROUPS must partition CONTRACTS exactly",
              code=FailureCode.STREAMING_REPORT_INTEGRITY_FAILED)
    rep.check("dogfood::known_bad_owning_complete",
              sorted(SC.KNOWN_BAD_OWNING_CODE.keys()) == sorted(SC.CONTRACTS.keys()),
              "KNOWN_BAD_OWNING_CODE must cover every contract",
              code=FailureCode.STREAMING_REPORT_INTEGRITY_FAILED)
    rep.check("dogfood::owns_failure_band", len(SC.STREAMING_CODES) >= 40,
              "streaming milestone must own the WF851-894 failure band",
              code=FailureCode.STREAMING_UNKNOWN_FAILURE_CODE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 streaming contract-spine gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = dogfood(rep)
    _registry_coherent(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="streaming-contracts", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.streaming.contract_spine.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_streaming_contracts_report.json")
    rep.print_summary("streaming-contracts")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
