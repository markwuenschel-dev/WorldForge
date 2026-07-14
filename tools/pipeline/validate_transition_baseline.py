#!/usr/bin/env python3
"""validate_transition_baseline.py — v2.5 shield ``--baseline`` gate.

Two jobs:

1. DOGFOOD the ``TransitionBaseline`` contract (transition_contracts) so a poisoned 5.8
   baseline index cannot pass:
     * the canonical valid example passes with zero failures;
     * the registry known-bad (a 5.7-tagged entry laundered into a 5.8 baseline) is
       rejected for EVIDENCE_5_7_CONTAMINATION;
     * four additional inline known-bads prove each contamination rail:
         - an entry tagged engine_minor != 8 (here 9)  -> WF1031 engine mismatch
         - an entry whose report_path is under procedural/reports/ue5_7 -> WF1033
         - entry_count != len(entries)                 -> WF1034 integrity
         - an absolute report_path                      -> WF1034 integrity
   Each known-bad MUST be rejected for its owning code, else this gate is RED.

2. Validate the baseline index if present
   (procedural/reports/ue5_8/baseline/baseline_index.json):
     * run the contract validator over it;
     * an absent index is fail-closed RED (correct this wave — no baseline built yet;
       the builder is Wave-8-gated).

Dogfoods are GREEN this wave; the present-index rail is RED (absent) — the overall gate is
honestly RED until the Wave-8 baseline is built. Never green an absent or 5.7-contaminated
baseline.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_transition_baseline.py --strict
Report -> procedural/reports/ue5_8/baseline/validate_transition_baseline_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC  # noqa: E402
from engine_identity import engine_identity  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

BASELINE_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "baseline"
INDEX_PATH = BASELINE_DIR / "baseline_index.json"


def _known_bads():
    ex = TC._example_transition_baseline
    rt = TC.RT_PLUGIN_BUILD
    return (
        ("entry_engine_minor_not_8",
         lambda: ex(entry_count=1, entries=[
             {"report_path": "procedural/reports/ue5_8/foo.json",
              "engine_minor": 9, "report_type": rt}]),
         C.EVIDENCE_ENGINE_MISMATCH),
        ("entry_path_under_ue5_7_tree",
         lambda: ex(entry_count=1, entries=[
             {"report_path": "procedural/reports/ue5_7/pluginbuild_report.json",
              "engine_minor": 8, "report_type": rt}]),
         C.EVIDENCE_COPIED_FROM_OLD_ENGINE),
        ("entry_count_mismatch",
         lambda: ex(entry_count=5),   # example carries 2 entries
         C.TRANSITION_REPORT_INTEGRITY_FAILED),
        ("entry_absolute_path",
         lambda: ex(entry_count=1, entries=[
             {"report_path": "D:/Unreal Projects/WorldForge-UE58/foo.json",
              "engine_minor": 8, "report_type": rt}]),
         C.TRANSITION_REPORT_INTEGRITY_FAILED),
    )


def dogfood(rep):
    validate, good, bad = TC.CONTRACTS["TransitionBaseline"]
    gfails = [c for c in validate(good(), strict=True) if not c[1]]
    rep.check("dogfood::valid_example_passes", len(gfails) == 0,
              "valid baseline example rejected: {}".format([c[0] for c in gfails][:4]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    bcodes = {c[3] for c in validate(bad(), strict=True) if not c[1]}
    owning = TC.KNOWN_BAD_OWNING_CODE["TransitionBaseline"]
    rep.check("dogfood::registry_known_bad_rejected_for_owning_code", owning in bcodes,
              "registry known-bad must be rejected for {} (got {})".format(
                  owning, sorted(str(c) for c in bcodes)[:4]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)
    for name, factory, code in _known_bads():
        codes = {c[3] for c in validate(factory(), strict=True) if not c[1]}
        rep.check("dogfood::known_bad::{}".format(name), code in codes,
                  "known-bad {!r} must be rejected for {} (got {})".format(
                      name, code, sorted(str(c) for c in codes)[:4]),
                  code=C.TRANSITION_NEGATIVE_ACCEPTED)


def validate_present_index(rep, strict):
    if not INDEX_PATH.is_file():
        rep.check("present::baseline_exists", False,
                  "no baseline index at {} — build is Wave-8-gated (fail-closed RED)".format(
                      INDEX_PATH.relative_to(REPO_ROOT)),
                  code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
        return
    rep.check("present::baseline_exists", True, str(INDEX_PATH.relative_to(REPO_ROOT)),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    try:
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        rep.check("present::baseline_parseable", False,
                  "baseline index unparseable: {}".format(exc),
                  code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
        return
    rep.check("present::baseline_parseable", True, "parsed",
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    for name, ok, detail, code in TC.validate_transition_baseline(index, strict=strict):
        rep.check("present::" + name, ok, detail, code=code)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 transition baseline gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    dogfood(rep)
    validate_present_index(rep, strict)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-transition-baseline", pack=args.pack, strict=strict,
        status=rep.status, record_count=len(rep.checks), records_total=len(rep.checks),
        report_type="wf.transition.baseline_validate.v1",
        extra={**engine_identity(), "declared_target_engine": "5.8",
               "observed_runtime_engine": None,
               "runtime_execution_required": True, "runtime_executed": False}))
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(BASELINE_DIR, "validate_transition_baseline_report.json")
    rep.print_summary("validate-transition-baseline")
    print("[validate-transition-baseline] dogfoods GREEN; baseline absent -> fail-closed RED "
          "this wave (build is Wave-8-gated).")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
