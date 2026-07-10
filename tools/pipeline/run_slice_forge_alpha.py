#!/usr/bin/env python3
"""run_slice_forge_alpha.py — v2.0 Agent-3/4/5 integrated runtime matrix gate.

The runtime slice matrix: one SliceRuntimeReport per scenario proving the FULL
integrated loop (launch -> traverse -> NPC -> combat -> complete -> reward ->
save/load). This module's --gate mode is the shield's runtime gate: it validates
every SliceRuntimeReport against the strict schema and requires 24/24 to be
slice_completed_runtime with clean failure_codes. Until the UE run produces that
evidence, the runtime tree is empty and the gate fail-closes RED (never green).

The actual headless UE run that PRODUCES the evidence is a separate engine step
(Wave R) — this file does not fabricate runtime results; it only certifies real
ones. A --gate over an empty tree is honestly RED.

Acceptance (gate):
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/run_slice_forge_alpha.py \
        --gate --pack encounter_loop_world --scenarios 24 --strict
Reports -> procedural/reports/slice/runtime/run_slice_forge_alpha_report.json
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


def _dogfood(rep):
    """Prove the completed-slice checker rejects fake-green runtime reports."""
    good = SX._example_slice_runtime_report()
    gfails = [c for c in SX.validate_slice_runtime_report(good, strict=True) if not c[1]]
    rep.check("dogfood::good_runtime_report_passes", len(gfails) == 0,
              "reference runtime report rejected: {}".format([c[0] for c in gfails][:4]),
              code=F.SLICE_REPORT_INTEGRITY_FAILED)
    for label, over in (
        ("no_state_mutation", {"inventory_mutated": False, "progression_mutated": False}),
        ("mission_incomplete", {"mission_completed": False}),
        ("forbidden_slot", {"save_slot": "WFCombat_State"}),
        ("dirty_failure_codes", {"failure_codes": ["WF677_SLICE_LAUNCH_FAILED"]}),
    ):
        bad = SX._example_slice_runtime_report(**over)
        bfails = [c for c in SX.validate_slice_runtime_report(bad, strict=True) if not c[1]]
        rep.check("dogfood::rejects_{}".format(label), len(bfails) > 0,
                  "fake-green runtime report '{}' must be rejected".format(label),
                  code=F.SLICE_NEGATIVE_ACCEPTED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 runtime slice matrix gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--gate", action="store_true", help="certify existing runtime evidence")
    ap.add_argument("--scenarios", default="24")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)

    expected_ids = set(SE.manifest_scenario_ids())
    reports = SE.runtime_reports()
    try:
        need = int(args.scenarios)
    except ValueError:
        need = SE.EXPECTED_SCENARIOS

    completed = 0
    seen_ids = []
    for path, doc in reports:
        if doc is None:
            rep.check("runtime::{}::parses".format(path.stem), False,
                      "unparseable runtime report", code=F.SLICE_RUNTIME_REPORT_MISSING)
            continue
        ssid = doc.get("slice_scenario_id", path.stem)
        seen_ids.append(ssid)
        fails = [c for c in SX.validate_slice_runtime_report(doc, strict=True) if not c[1]]
        ok = len(fails) == 0 and doc.get("slice_completed_runtime") is True
        rep.check("runtime::{}::completed".format(ssid), ok,
                  "not a clean slice_completed_runtime: {}".format([c[0] for c in fails][:4]),
                  code=F.SLICE_RUNTIME_REPORT_MISSING)
        rep.check("runtime::{}::known_scenario".format(ssid),
                  (not expected_ids) or ssid in expected_ids,
                  "runtime report scenario id not in manifest", code=F.SLICE_UNKNOWN_SCENARIO_ID)
        if ok:
            completed += 1

    # fail-closed: the FULL matrix must be present and completed.
    rep.check("runtime::matrix_complete", completed >= need,
              "runtime matrix {}/{} slice_completed_runtime (needs {}) — "
              "run the UE headless slice matrix (Wave R) to produce evidence"
              .format(completed, len(reports), need),
              code=F.SLICE_PARTIAL_MATRIX)
    rep.check("runtime::no_duplicate_scenarios", len(seen_ids) == len(set(seen_ids)),
              "duplicate scenario runtime reports", code=F.SLICE_DUPLICATE_SCENARIO_REPORT)

    rep.finalize()
    rep.set_meta(build_meta(command="run-vertical-slice-runtime", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(reports),
                            records_total=need, records_passed=completed,
                            report_type="wf.slice.runtime_matrix.v1"))
    rep.write(REPORT_DIR, "run_slice_forge_alpha_report.json")
    rep.print_summary("run-vertical-slice-runtime")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
