#!/usr/bin/env python3
"""validate_slice_save_load.py — v2.0 Agent-5 save/load runtime gate.

Proves the slice's state persists through save/load in every scenario: each
SliceRuntimeReport has save_load_result == roundtrip_ok using a v1.9 reward save
slot (WFReward_State / WFInventory_State / WFProgression_State), NEVER the
mission/NPC/combat slots. Save/load is independent proof — a completed slice
cannot claim persistence it did not exercise. Fail-closed RED until Wave R.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_slice_save_load.py \
        --pack encounter_loop_world --strict
Reports -> procedural/reports/slice/runtime/validate_slice_save_load_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
import slice_evidence as SE
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / SX.SLICE_RUNTIME_REPORTS_REL


def _facet(doc):
    slot = doc.get("save_slot")
    slot_ok = slot in SX.SLICE_SAVE_SLOTS and slot not in SX.FORBIDDEN_SAVE_SLOTS
    if slot in SX.FORBIDDEN_SAVE_SLOTS:
        return False, "save_slot {!r} is a mission/combat slot, not a v1.9 reward slot".format(slot)
    ok = doc.get("save_load_result") == SX.SAVE_LOAD_ROUNDTRIP_OK and slot_ok
    return ok, "save_load_result==roundtrip_ok using a v1.9 reward slot required"


def _dogfood(rep):
    rep.check("dogfood::good_passes", _facet(SX._example_slice_runtime_report())[0],
              "reference save/load report failed", code=F.SLICE_REPORT_INTEGRITY_FAILED)
    for label, over in (("failed_roundtrip", {"save_load_result": "failed"}),
                        ("not_run", {"save_load_result": "not_run"}),
                        ("wrong_slot", {"save_slot": "WFCombat_State"})):
        bad = SX._example_slice_runtime_report(**over)
        rep.check("dogfood::rejects_{}".format(label), not _facet(bad)[0],
                  "'{}' must fail the save/load facet".format(label),
                  code=F.SLICE_NEGATIVE_ACCEPTED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice save/load gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)
    passed = SE.facet_gate(rep, _facet, SE.EXPECTED_SCENARIOS,
                           F.SLICE_SAVE_LOAD_FAILED, F.SLICE_PARTIAL_MATRIX)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-slice-save-load", pack=args.pack, strict=strict,
                            status=rep.status, record_count=passed,
                            records_total=SE.EXPECTED_SCENARIOS, records_passed=passed,
                            report_type="wf.slice.save_load.v1"))
    rep.write(REPORT_DIR, "validate_slice_save_load_report.json")
    rep.print_summary("validate-slice-save-load")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
