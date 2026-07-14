#!/usr/bin/env python3
"""validate_transition_regression.py — v2.5 TransitionRegressionReport dogfood gate.

Two jobs:

1. DOGFOOD the ``TransitionRegressionReport`` contract (transition_contracts) so a
   fake-green regression report cannot pass:
     * the canonical valid example passes its validator with zero failures;
     * the registry known-bad (regression_free with a worldforge_regression diff) is
       rejected for REGRESSION_WORLDFORGE_REGRESSION;
     * three additional inline known-bads prove each honesty rail:
         - regression_free=True with a worldforge_regression diff -> WF1022
         - regression_free=True with maps_loaded < maps_checked   -> WF1020 (map load)
         - regression_free=True with an unclassified diff         -> WF1021
   Each known-bad MUST be rejected for its owning code, else this gate is RED.

2. Validate the emitted regression report if present
   (procedural/reports/ue5_8/regression/transition_regression_report.json):
     * run the contract validator over it;
     * a report with ``runtime_executed=False`` or ``regression_free=False`` is
       HONESTLY INCOMPLETE -> gate RED (correct this wave — no UE 5.8 run yet);
     * an absent report is fail-closed RED.

Dogfoods are GREEN this wave; the present-report honesty rails are RED — the overall
gate is honestly RED until a real 5.8 regression run lands. Never green a report whose
runtime_executed is not True.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_transition_regression.py --strict
Report -> procedural/reports/ue5_8/regression/validate_transition_regression_report.json
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

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "regression"
PAYLOAD_PATH = REPORT_DIR / "transition_regression_report.json"


# Inline known-bad fixtures (name, factory, owning_code) proving each honesty rail.
def _known_bads():
    ex = TC._example_transition_regression_report
    return (
        ("regression_free_with_worldforge_regression",
         lambda: ex(regression_free=True, diffs=[
             {"map_path": "Content/Maps/encounter_loop_world.umap",
              "classification": "worldforge_regression"}]),
         C.REGRESSION_WORLDFORGE_REGRESSION),
        ("regression_free_with_maps_loaded_short",
         lambda: ex(regression_free=True, maps_checked=24, maps_loaded=23),
         C.MAP_LOAD_FAILED),
        ("regression_free_with_unclassified_diff",
         lambda: ex(regression_free=True, diffs=[
             {"map_path": "Content/Maps/alpine_snow.umap",
              "classification": "unclassified"}]),
         C.REGRESSION_UNCLASSIFIED_DIFF),
    )


def dogfood(rep, strict):
    # Registry valid example passes; registry known-bad rejected for owning code.
    validate, good, bad = TC.CONTRACTS["TransitionRegressionReport"]
    gfails = [c for c in validate(good(), strict=True) if not c[1]]
    rep.check("dogfood::valid_example_passes", len(gfails) == 0,
              "valid regression example rejected: {}".format([c[0] for c in gfails][:4]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    bcodes = {c[3] for c in validate(bad(), strict=True) if not c[1]}
    owning = TC.KNOWN_BAD_OWNING_CODE["TransitionRegressionReport"]
    rep.check("dogfood::registry_known_bad_rejected_for_owning_code", owning in bcodes,
              "registry known-bad must be rejected for {} (got {})".format(
                  owning, sorted(str(c) for c in bcodes)[:4]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)

    # Inline honesty-rail known-bads.
    for name, factory, code in _known_bads():
        codes = {c[3] for c in validate(factory(), strict=True) if not c[1]}
        rep.check("dogfood::known_bad::{}".format(name), code in codes,
                  "known-bad {!r} must be rejected for {} (got {})".format(
                      name, code, sorted(str(c) for c in codes)[:4]),
                  code=C.TRANSITION_NEGATIVE_ACCEPTED)


def validate_present_report(rep, strict):
    """Validate the emitted regression payload if present; else fail-closed RED."""
    if not PAYLOAD_PATH.is_file():
        rep.check("present::report_exists", False,
                  "no regression report at {} — run transition_regression.py first "
                  "(fail-closed RED)".format(PAYLOAD_PATH.relative_to(REPO_ROOT)),
                  code=C.TRANSITION_REGRESSION_FAILED)
        return
    rep.check("present::report_exists", True, str(PAYLOAD_PATH.relative_to(REPO_ROOT)),
              code=C.TRANSITION_REGRESSION_FAILED)
    try:
        payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        rep.check("present::report_parseable", False,
                  "regression report unparseable: {}".format(exc),
                  code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
        return
    rep.check("present::report_parseable", True, "parsed", code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    for name, ok, detail, code in TC.validate_transition_regression_report(payload, strict=strict):
        rep.check("present::" + name, ok, detail, code=code)

    meta = payload.get("meta") if isinstance(payload, dict) else None
    runtime_executed = bool(meta.get("runtime_executed")) if isinstance(meta, dict) else False
    rep.check("present::runtime_executed", runtime_executed,
              "regression report has runtime_executed=False — honest RED (no UE 5.8 run)",
              code=C.TRANSITION_REGRESSION_FAILED)
    rep.check("present::regression_free", bool(payload.get("regression_free")),
              "regression report regression_free=False — honest RED",
              code=C.TRANSITION_REGRESSION_FAILED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 transition regression dogfood gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    dogfood(rep, strict)
    validate_present_report(rep, strict)

    # Reflect the ACTUAL present-report runtime state in this gate's own meta (do not
    # hard-code False — a real completed regression report sets runtime_executed=True).
    present = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8")) if PAYLOAD_PATH.is_file() else {}
    present_executed = bool((present.get("meta") or {}).get("runtime_executed"))

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-transition-regression", pack=args.pack, strict=strict,
        status=rep.status, record_count=len(rep.checks), records_total=len(rep.checks),
        report_type="wf.transition.regression_validate.v1",
        extra={**engine_identity(), "declared_target_engine": "5.8",
               "observed_runtime_engine": 8 if present_executed else None,
               "runtime_execution_required": True, "runtime_executed": present_executed}))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_transition_regression_report.json")
    rep.print_summary("validate-transition-regression")
    print("[validate-transition-regression] dogfoods GREEN; present regression report "
          "runtime_executed={}.".format(present_executed))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
