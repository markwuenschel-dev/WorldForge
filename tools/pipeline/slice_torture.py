#!/usr/bin/env python3
"""slice_torture.py — v2.0 Agent-7 hostile torture battery.

Proves the slice's honesty detectors reject the ways a slice can fake success —
this machinery is what stops partial/stale/duplicate/fake evidence from passing.
It is dogfood-based (constructs the hostile states in-code and asserts they are
caught), so it is meaningfully GREEN before runtime evidence exists: it certifies
the detectors, not the evidence. The evidence-presence gates
(run_slice_forge_alpha / validate_slice_* / slice_report_integrity) stay RED until
Wave R — this gate proves they will catch fakes when evidence does arrive.

Torture modes:
    partial-matrix, stale-evidence, duplicate-scenario, fake-completed (all-true
    but no state mutation / empty telemetry / dirty failure_codes / wrong save
    slot), orphan-scenario, package-without-artifact.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/slice_torture.py \
        --pack encounter_loop_world --strict
Reports -> procedural/reports/slice/integrity/slice_torture_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
import slice_report_integrity as SRI
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / SX.SLICE_INTEGRITY_REPORTS_REL


def _rejected(validate, rec):
    return len([c for c in validate(rec, strict=True) if not c[1]]) > 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice torture battery.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "slice_torture", strict=strict)

    # 1. partial matrix (evidence index claims ok but 23/24) must be rejected
    rep.check("torture::partial_matrix_rejected",
              _rejected(SX.validate_slice_evidence_index,
                        SX._example_slice_evidence_index(scenario_count_expected=24,
                                                         scenario_count_seen=23,
                                                         runtime_reports=["s"] * 23)),
              "23/24 evidence index must be rejected", code=F.SLICE_TORTURE_FAILED)

    # 2. stale package (live without real sha) must be rejected
    rep.check("torture::stale_package_rejected",
              _rejected(SX.validate_slice_package_report,
                        SX._example_slice_package_report(git_sha="unknown")),
              "live package without real sha must be rejected", code=F.SLICE_TORTURE_FAILED)

    # 3. duplicate scenario in manifest must be rejected
    rep.check("torture::duplicate_scenario_rejected",
              _rejected(SX.validate_slice_manifest,
                        SX._example_slice_manifest(scenarios=["vs_a", "vs_a"])),
              "duplicate scenario manifest must be rejected", code=F.SLICE_TORTURE_FAILED)

    # 4. fake-completed runtime reports (various) must be rejected
    for label, over in (
        ("no_state_mutation", {"inventory_mutated": False, "progression_mutated": False}),
        ("empty_telemetry", {"telemetry_paths": []}),
        ("dirty_failure_codes", {"failure_codes": ["WF677_SLICE_LAUNCH_FAILED"]}),
        ("wrong_save_slot", {"save_slot": "WFCombat_State"}),
        ("mission_incomplete", {"mission_completed": False}),
    ):
        rep.check("torture::fake_completed_{}_rejected".format(label),
                  _rejected(SX.validate_slice_runtime_report,
                            SX._example_slice_runtime_report(**over)),
                  "fake-completed '{}' must be rejected".format(label),
                  code=F.SLICE_TORTURE_FAILED)

    # 5. orphan scenario id must be flagged by report-integrity
    ids = ["vs_real_1"]
    orphan = SX._example_slice_runtime_report(
        slice_scenario_id="vs_orphan",
        telemetry_paths=["procedural/generated/slice/manifest.json"],
        created_at="live", git_commit="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    rep.check("torture::orphan_scenario_flagged",
              SRI.runtime_integrity_violations(orphan, ids) != [],
              "orphan scenario id must be flagged", code=F.SLICE_TORTURE_FAILED)

    # 6. package report with no artifact must be rejected
    rep.check("torture::package_without_artifact_rejected",
              _rejected(SX.validate_slice_package_report,
                        SX._example_slice_package_report(package_exists=False,
                                                         package_size_bytes=0)),
              "passing package report with no package must be rejected",
              code=F.SLICE_TORTURE_FAILED)

    # non-vacuous guard
    rep.check("torture::battery_nonempty", True, "", code=F.SLICE_TORTURE_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(command="vertical-slice-torture", pack=args.pack, strict=strict,
                            torture=True, status=rep.status, record_count=1,
                            report_type="wf.slice.torture.v1"))
    rep.write(REPORT_DIR, "slice_torture_report.json")
    rep.print_summary("vertical-slice-torture")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
