#!/usr/bin/env python3
"""validate_vertical_slice_contracts.py — v2.0 Agent-1 contract-spine gate.

Proves the VerticalSliceForge schema spine (slice_contracts.py) is coherent and
constrains correctly — the always-available, runtime-free gate that is GREEN from
Wave 1 while the runtime/package gates stay honestly RED until real evidence
exists.

It does two things:

  1. DOGFOOD the schema registry (slice_contracts.CONTRACTS): every valid example
     must pass its own validator with zero failures, and every known-bad example
     must be REJECTED for its OWNING failure code. A validator that greens its
     known-bad, or one that rejects the valid example, is a fake-green vector and
     turns this gate RED — no real data required.

  2. VALIDATE REAL AUTHORED FILES IF PRESENT: once Wave 2 writes
     procedural/generated/slice/vertical_slice_contract.json,
     .../manifest.json and .../scenarios/*.json, this gate additionally validates
     each against its contract. Absent files are not an error here (their presence
     is proven by validate_slice_scenarios.py); this keeps the contract gate green
     on schema soundness alone, per the Wave-1 fail-closed design.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_vertical_slice_contracts.py \
        --pack encounter_loop_world --strict
Reports -> procedural/reports/slice/validate_vertical_slice_contracts_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "slice"


def _dogfood(rep):
    """Every valid example passes; every known-bad is rejected for its owning code."""
    n = 0
    for name, (validate, good, bad) in SX.CONTRACTS.items():
        n += 1
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("dogfood::{}::valid_example_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:4]),
                  code=FailureCode.SLICE_REPORT_INTEGRITY_FAILED)
        bfails = [c for c in validate(bad(), strict=True) if not c[1]]
        codes = {c[3] for c in bfails}
        rep.check("dogfood::{}::known_bad_rejected".format(name), len(bfails) > 0,
                  "known-bad example must be rejected", code=FailureCode.SLICE_NEGATIVE_ACCEPTED)
        owning = SX.KNOWN_BAD_OWNING_CODE.get(name)
        rep.check("dogfood::{}::rejected_for_owning_code".format(name),
                  owning in codes,
                  "known-bad must be rejected for owning code {} (got {})".format(
                      owning, sorted(str(c) for c in codes)[:4]),
                  code=FailureCode.SLICE_NEGATIVE_ACCEPTED)
    rep.check("dogfood::registry_nonempty", n > 0,
              "CONTRACTS registry must not be empty", code=FailureCode.SLICE_CONTRACT_INVALID)
    return n


def _validate_if_present(rep, strict):
    """Validate real authored slice files against their contracts, if they exist."""
    contract_path = REPO_ROOT / SX.SLICE_CONTRACT_REL
    manifest_path = REPO_ROOT / SX.SLICE_MANIFEST_REL
    scenarios_dir = REPO_ROOT / SX.SLICE_SCENARIOS_REL

    if contract_path.is_file():
        try:
            obj = json.loads(contract_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rep.check("real::contract_parses", False, "contract JSON unparseable: {}".format(e),
                      code=FailureCode.SLICE_CONTRACT_INVALID)
        else:
            for name, ok, detail, code in SX.validate_vertical_slice_contract(obj, strict=strict):
                rep.check("real::contract::{}".format(name), ok, detail, code=code)

    if manifest_path.is_file():
        try:
            obj = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rep.check("real::manifest_parses", False, "manifest JSON unparseable: {}".format(e),
                      code=FailureCode.SLICE_MANIFEST_INVALID)
        else:
            for name, ok, detail, code in SX.validate_slice_manifest(obj, strict=strict):
                rep.check("real::manifest::{}".format(name), ok, detail, code=code)

    if scenarios_dir.is_dir():
        for f in sorted(scenarios_dir.glob("*.json")):
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                rep.check("real::scenario::{}::parses".format(f.stem), False,
                          "scenario JSON unparseable: {}".format(e),
                          code=FailureCode.SLICE_SCENARIO_INVALID)
                continue
            sfails = [c for c in SX.validate_slice_scenario(obj, strict=strict) if not c[1]]
            rep.check("real::scenario::{}::valid".format(f.stem), len(sfails) == 0,
                      "{} failing checks: {}".format(len(sfails), [c[0] for c in sfails][:4]),
                      code=FailureCode.SLICE_SCENARIO_INVALID)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 vertical-slice contract spine gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = _dogfood(rep)
    _validate_if_present(rep, strict)

    rep.finalize()
    rep.set_meta(build_meta(
        command="vertical-slice-contracts", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.slice.contract_spine.v1"))
    rep.write(REPORT_DIR, "validate_vertical_slice_contracts_report.json")
    rep.print_summary("vertical-slice-contracts")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
