#!/usr/bin/env python3
"""slice_report_integrity.py — v2.0 Agent-7 slice report-integrity gate.

Attacks the slice evidence so partial, stale, fake, orphan, or duplicate reports
cannot pass. Single source-of-truth predicate ``runtime_integrity_violations``
(empty == clean) checks: schema validity, telemetry_path points at a real file,
live evidence carries a real sha, and the scenario id is in the manifest (no
orphan). It dogfoods the predicate on synthetic records first (so it constrains
even when the tree is empty), then scans the real runtime tree with a non-vacuous
floor — so an empty tree fails ("nothing to prove"). Fail-closed RED until Wave R.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/slice_report_integrity.py \
        --pack encounter_loop_world --strict
Reports -> procedural/reports/slice/integrity/slice_report_integrity_report.json
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

REPORT_DIR = REPO_ROOT / SX.SLICE_INTEGRITY_REPORTS_REL


def runtime_integrity_violations(doc, manifest_ids):
    """Return a list of integrity problems for one runtime report ([] == clean)."""
    problems = []
    if not isinstance(doc, dict):
        return ["not a mapping"]
    fails = [c for c in SX.validate_slice_runtime_report(doc, strict=True) if not c[1]]
    if fails:
        problems.append("schema: {}".format([c[0] for c in fails][:3]))
    # telemetry paths must resolve to real files
    tp = doc.get("telemetry_paths")
    if not (isinstance(tp, list) and tp and all(SE.telemetry_path_exists(x) for x in tp)):
        problems.append("telemetry_paths missing or not-on-disk")
    # live evidence must carry a real sha
    if doc.get("created_at") == "live":
        sha = doc.get("git_commit")
        if not (isinstance(sha, str) and sha and sha != "unknown"):
            problems.append("created_at='live' but git_commit not a real sha")
    # no orphan: scenario id must be in the manifest
    if manifest_ids and doc.get("slice_scenario_id") not in manifest_ids:
        problems.append("orphan: scenario id not in manifest")
    return problems


def _dogfood(rep):
    ids = ["vs_desert_reach_objective_baseline_s1"]
    good = SX._example_slice_runtime_report(
        slice_scenario_id=ids[0],
        telemetry_paths=["procedural/generated/slice/manifest.json"],
        created_at="live", git_commit="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    rep.check("dogfood::clean_passes", runtime_integrity_violations(good, ids) == [],
              "clean runtime report flagged: {}".format(runtime_integrity_violations(good, ids)),
              code=F.SLICE_REPORT_INTEGRITY_FAILED)
    for label, over, idset in (
        ("telemetry_missing", {"telemetry_paths": ["does/not/exist.json"]}, ids),
        ("live_no_sha", {"git_commit": "unknown"}, ids),
        ("orphan", {"slice_scenario_id": "vs_not_in_manifest"}, ids),
        ("fake_completed", {"inventory_mutated": False, "progression_mutated": False}, ids),
    ):
        bad = SX._example_slice_runtime_report(
            slice_scenario_id=ids[0],
            telemetry_paths=["procedural/generated/slice/manifest.json"],
            created_at="live", git_commit="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
        bad.update(over)
        rep.check("dogfood::flags_{}".format(label),
                  runtime_integrity_violations(bad, idset) != [],
                  "'{}' must be flagged".format(label), code=F.SLICE_NEGATIVE_ACCEPTED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice report-integrity gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)

    manifest_ids = set(SE.manifest_scenario_ids())
    reports = SE.runtime_reports()
    seen = []
    for path, doc in reports:
        ssid = doc.get("slice_scenario_id", path.stem) if isinstance(doc, dict) else path.stem
        seen.append(ssid)
        probs = runtime_integrity_violations(doc, manifest_ids)
        rep.check("integrity::{}".format(ssid), not probs, "; ".join(probs),
                  code=F.SLICE_REPORT_INTEGRITY_FAILED)
    rep.check("integrity::no_duplicate_scenarios", len(seen) == len(set(seen)),
              "duplicate scenario runtime reports", code=F.SLICE_DUPLICATE_SCENARIO_REPORT)
    # non-vacuous floor: an empty runtime tree cannot pass integrity.
    rep.check("integrity::non_vacuous",
              len(reports) >= SE.EXPECTED_SCENARIOS,
              "{} runtime reports present, need {} — nothing to prove until Wave R"
              .format(len(reports), SE.EXPECTED_SCENARIOS), code=F.SLICE_RUNTIME_REPORT_MISSING)

    rep.finalize()
    rep.set_meta(build_meta(command="vertical-slice-report-integrity", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(reports),
                            report_type="wf.slice.report_integrity.v1"))
    rep.write(REPORT_DIR, "slice_report_integrity_report.json")
    rep.print_summary("vertical-slice-report-integrity")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
