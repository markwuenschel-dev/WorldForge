#!/usr/bin/env python3
"""validate_ground_traversal_schemas.py — WorldForge v1.6z contract-spine gate.

Dogfoods every GroundTraversalForge contract: for each, the canonical valid
example MUST pass under STRICT, and a known-bad example MUST fail. This proves the
schemas actually constrain — a contract that accepts its own known-bad is a
fake-green vector and fails the gate. Also runs the completion contract self-check.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import ground_contracts as GX
import ground_completion_contract as GC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    for name, (validate, good_fn, bad_fn) in GX.CONTRACTS.items():
        good = good_fn()
        bad = bad_fn()
        good_fails = [c for c in validate(good, strict=True) if not c[1]]
        bad_fails = [c for c in validate(bad, strict=True) if not c[1]]
        rep.check("{}::valid_passes".format(name), not good_fails,
                  "valid {} passes strict ({} checks)".format(name, "0 fail" if not good_fails
                  else [c[0] for c in good_fails][:4]),
                  code=FailureCode.GROUND_TRAVERSAL_SCHEMA_FAILURE)
        rep.check("{}::known_bad_fails".format(name), len(bad_fails) > 0,
                  "known-bad {} is rejected".format(name),
                  code=FailureCode.GROUND_TRAVERSAL_SCHEMA_FAILURE)

    # completion contract self-check (grounded valid passes; flight/teleport reject)
    good_c = [c for c in GC.validate_completion(
        GC._example(GC.SUCCESS_CLASS, "grounded_worldforge_route", grounded=True), strict=True) if not c[1]]
    bad_c = [c for c in GC.validate_completion(
        GC._example(GC.SUCCESS_CLASS, "continuous_flight", grounded=True, flight=True), strict=True) if not c[1]]
    rep.check("GroundCompletionReport::valid_passes", not good_c,
              "valid grounded completion passes", code=FailureCode.GROUND_COMPLETION_FAILURE)
    rep.check("GroundCompletionReport::flight_rejected", len(bad_c) > 0,
              "flight-as-grounded-success rejected", code=FailureCode.GROUND_FLIGHT_COUNTED_AS_SUCCESS)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-ground-traversal-schemas", pack=args.pack,
                            strict=strict, status=rep.status, record_count=len(GX.CONTRACTS) + 1,
                            report_type="wf.ground.schema_check.v1"))
    out = REPO_ROOT / "procedural/reports/ground/schema"
    rep.write(out, "validate_ground_traversal_schemas_report.json")
    rep.print_summary("validate-ground-traversal-schemas")
    print("[validate-ground-traversal-schemas] {} contracts dogfooded".format(len(GX.CONTRACTS) + 1))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
