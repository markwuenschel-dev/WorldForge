#!/usr/bin/env python3
"""validate_conversion_manifest.py — v2.5 shield ``--conversion`` gate (fail-closed).

Two jobs, one honest verdict:

1. DOGFOOD the ConversionManifest contract (transition_contracts.CONVERSION_MANIFEST).
   The canonical valid example must pass its own validator with zero failures, and the
   registered known-bad (a map that loses an actor with no accounted deletion) must be
   REJECTED for its owning code CONVERSION_ACTOR_LOSS. This proves the contract that will
   gate the commander's authoritative manifest actually constrains — a validator that
   greens actor loss is a fake-green vector.

2. Require a COMPLETED authoritative conversion manifest on disk before greening the gate.
   The authoritative manifest is the commander's SERIAL job (open UE 5.8, resave every
   map, record REAL per-map actor counts). Until that file exists at the canonical path
   AND is marked complete AND validates against the contract, this gate FAILS CLOSED with
   an explicit "authoritative conversion not yet performed" message.

   The pre-conversion inventory (build_conversion_manifest.py) is NOT accepted as a
   substitute: it carries actors_before=null by design and cannot prove no actor loss.
   Greening off the inventory would launder an unperformed conversion into a pass.

THIS GATE IS EXPECTED RED for the entire inventory wave. That RED is correct and honest —
it means the authoritative 5.7 -> 5.8 conversion has not run yet. It flips GREEN only when
the commander writes the authoritative manifest (see acceptance below).

Acceptance (flips GREEN):
    procedural/manifests/ue5_8_conversion/conversion_manifest.json exists,
    carries top-level "conversion_status": "complete", and passes
    transition_contracts.validate_conversion_manifest with zero failures.

Usage:
    PYTHONUTF8=1 python tools/pipeline/validate_conversion_manifest.py [--strict]
Reports -> procedural/reports/ue5_8/validate_conversion_manifest_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC  # noqa: E402
from engine_identity import engine_identity  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8"

# The canonical path + completeness flag the commander's authoritative conversion
# MUST write to flip this gate GREEN. Documented here as the single source of truth.
AUTHORITATIVE_MANIFEST = (REPO_ROOT / "procedural" / "manifests" /
                          "ue5_8_conversion" / "conversion_manifest.json")
COMPLETENESS_FLAG_KEY = "conversion_status"
COMPLETENESS_FLAG_VALUE = "complete"


def dogfood_conversion_contract(rep):
    """Prove the ConversionManifest contract constrains (valid passes, bad rejected)."""
    validate, good, bad = TC.CONTRACTS["ConversionManifest"]
    gfails = [c for c in validate(good(), strict=True) if not c[1]]
    rep.check("dogfood::ConversionManifest::valid_example_passes", len(gfails) == 0,
              "canonical valid manifest rejected: {}".format([c[0] for c in gfails][:4]),
              code=FailureCode.TRANSITION_REPORT_INTEGRITY_FAILED)
    bfails = [c for c in validate(bad(), strict=True) if not c[1]]
    codes = {c[3] for c in bfails}
    rep.check("dogfood::ConversionManifest::actor_loss_rejected", len(bfails) > 0,
              "actor-loss known-bad must be rejected",
              code=FailureCode.TRANSITION_NEGATIVE_ACCEPTED)
    rep.check("dogfood::ConversionManifest::rejected_for_actor_loss",
              FailureCode.CONVERSION_ACTOR_LOSS in codes,
              "actor-loss known-bad must be rejected for {} (got {})".format(
                  FailureCode.CONVERSION_ACTOR_LOSS,
                  sorted(str(c) for c in codes)[:4]),
              code=FailureCode.TRANSITION_NEGATIVE_ACCEPTED)


def gate_authoritative_conversion(rep):
    """Fail closed unless a COMPLETED authoritative conversion manifest exists.

    Returns the loaded manifest dict (or None). The gate is intentionally RED while
    the authoritative conversion is unperformed.
    """
    present = AUTHORITATIVE_MANIFEST.is_file()
    rel = AUTHORITATIVE_MANIFEST.relative_to(REPO_ROOT).as_posix()
    rep.check("conversion::authoritative_manifest_present", present,
              "authoritative conversion not yet performed: expected {} (commander's "
              "serial UE 5.8 resave job). The pre-conversion inventory is NOT a "
              "substitute.".format(rel),
              code=FailureCode.CONVERSION_MANIFEST_INCOMPLETE)
    if not present:
        return None

    try:
        manifest = json.loads(AUTHORITATIVE_MANIFEST.read_text(encoding="utf-8"))
    except Exception as exc:
        rep.check("conversion::authoritative_manifest_parses", False,
                  "authoritative manifest unreadable: {}".format(exc),
                  code=FailureCode.CONVERSION_MANIFEST_INCOMPLETE)
        return None
    rep.check("conversion::authoritative_manifest_parses", True, "parsed")

    flag = manifest.get(COMPLETENESS_FLAG_KEY) if isinstance(manifest, dict) else None
    rep.check("conversion::marked_complete", flag == COMPLETENESS_FLAG_VALUE,
              "authoritative manifest {} must be {!r} (got {!r})".format(
                  COMPLETENESS_FLAG_KEY, COMPLETENESS_FLAG_VALUE, flag),
              code=FailureCode.CONVERSION_MANIFEST_INCOMPLETE)

    # It must additionally satisfy the ConversionManifest contract (no actor loss,
    # no unaccounted churn, complete map coverage, engine edge 5.7 -> 5.8).
    cfails = [c for c in TC.validate_conversion_manifest(manifest, strict=True) if not c[1]]
    rep.check("conversion::authoritative_manifest_valid", len(cfails) == 0,
              "authoritative manifest fails ConversionManifest contract: {}".format(
                  [(c[0], c[3]) for c in cfails][:6]),
              code=(cfails[0][3] if cfails else FailureCode.CONVERSION_MANIFEST_INCOMPLETE))
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 conversion-manifest gate (fail-closed).")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    dogfood_conversion_contract(rep)
    gate_authoritative_conversion(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-conversion-manifest", pack=args.pack, strict=strict,
        status=rep.status, record_count=len(rep.checks), records_total=len(rep.checks),
        report_type="wf.transition.conversion_gate.v1",
        extra=dict(engine_identity(), **{
            "declared_target_engine": "5.8",
            "observed_runtime_engine": None,
            "runtime_execution_required": False,
            "runtime_executed": False,
            "authoritative_manifest_path":
                AUTHORITATIVE_MANIFEST.relative_to(REPO_ROOT).as_posix(),
            "completeness_flag": "{}={}".format(COMPLETENESS_FLAG_KEY,
                                                COMPLETENESS_FLAG_VALUE),
        })))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_conversion_manifest_report.json")
    rep.print_summary("conversion-gate")
    if not rep.passed:
        print("[conversion-gate] EXPECTED RED: the authoritative UE 5.7 -> 5.8 "
              "conversion has not been performed. This is the honest pre-conversion "
              "state, not a defect.")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
