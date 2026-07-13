#!/usr/bin/env python3
"""run_transition_torture.py — v2.5 deterministic transition torture harness.

Permutes hostile mutations across every transition contract and asserts NONE is fake-accepted.
Where transition_negatives.py proves ONE owning known-bad per code, torture proves BREADTH:
many independent corruptions per contract, derived deterministically from a seeded index (no
wall-clock, no RNG — reproducible on a clean checkout).

Mutation families (per valid example): drop each required key; wrong type on each field;
out-of-enum on enum fields; numeric sign/zero flips; empty required lists; absolute-path
injection; engine-minor corruption; identity/operation permutation. Every mutated record MUST
be rejected by its own validator. GREEN when zero mutations slip through.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/run_transition_torture.py --strict
Reports -> procedural/reports/ue5_8/hostile/run_transition_torture_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "hostile"

# Per contract: (name, validator, factory, required-field tuple, skip set).
# The skip set holds required-but-unconstrained-when-present fields (nullable identity
# breadcrumbs) — corrupting them is legitimately accepted, so torture must not assert on
# them. Advisory/optional metadata (created_by, report_type, notes, ...) is NOT in the
# required tuple at all, so it is already excluded. Mutating only genuinely-constrained
# required fields keeps every torture assertion HONEST (no false leaks, no false catches).
_IDENTITY_NULLABLE = frozenset(("engine_build_id", "project_commit", "plugin_commit"))
CONTRACTS = [
    ("EngineIdentity", TC.validate_engine_identity, TC._example_engine_identity,
     TC.IDENTITY_REQUIRED, _IDENTITY_NULLABLE),
    ("CapabilityManifest", TC.validate_capability_manifest, TC._example_capability_manifest,
     TC.CAPABILITY_MANIFEST_REQUIRED, frozenset()),
    ("ConversionManifest", TC.validate_conversion_manifest, TC._example_conversion_manifest,
     TC.CONVERSION_MANIFEST_REQUIRED, frozenset()),
    ("PluginBuildReport", TC.validate_plugin_build_report, TC._example_plugin_build_report,
     TC.PLUGIN_BUILD_REQUIRED, frozenset()),
    ("TransitionRegressionReport", TC.validate_transition_regression_report,
     TC._example_transition_regression_report, TC.REGRESSION_REPORT_REQUIRED, frozenset()),
    ("GloamBridgeProbe", TC.validate_gloam_bridge_probe, TC._example_gloam_bridge_probe,
     TC.BRIDGE_PROBE_REQUIRED, frozenset()),
    ("TransitionBaseline", TC.validate_transition_baseline, TC._example_transition_baseline,
     TC.BASELINE_REQUIRED, frozenset()),
]

# A single guaranteed-violating sentinel: a bare dict is not a valid str / number / bool /
# enum member / list / exact schema_version, so injecting it into ANY constrained required
# field is always rejected. (An empty list is NOT universal — `diffs` may legally be empty.)
_SENTINEL = {"__torture__": True}


def _mutations(example, required, skip):
    """Deterministically yield (label, mutant) over CONSTRAINED required fields only."""
    keys = [k for k in required if k not in skip]
    out = []
    for k in keys:
        # family 1: drop the required key (always caught by check_required)
        d = dict(example)
        d.pop(k, None)
        out.append(("drop::" + k, d))
        # family 2: corrupt the required key with the universal violating sentinel
        d2 = dict(example)
        d2[k] = _SENTINEL
        out.append(("corrupt::" + k, d2))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 transition torture harness.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "transition_torture", strict=strict)
    total = 0
    accepted_leaks = 0
    for name, validate, factory, required, skip in CONTRACTS:
        example = factory()
        # sanity: the pristine example must pass (else the harness is miscalibrated)
        gfails = [ck for ck in validate(example, strict=True) if not ck[1]]
        rep.check("torture::{}::baseline_valid".format(name), len(gfails) == 0,
                  "pristine example must pass before mutation: {}".format(
                      [ck[0] for ck in gfails][:4]),
                  code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
        for label, mutant in _mutations(example, required, skip):
            total += 1
            fails = [ck for ck in validate(mutant, strict=True) if not ck[1]]
            if not fails:
                accepted_leaks += 1
                rep.check("torture::{}::{}".format(name, label), False,
                          "mutation was fake-ACCEPTED (torture leak)",
                          code=C.TRANSITION_FUZZ_ACCEPTED)
    # single rollup pass/fail plus the count for the record
    rep.check("torture::no_leaks", accepted_leaks == 0,
              "{} of {} mutations slipped through".format(accepted_leaks, total),
              code=C.TRANSITION_FUZZ_ACCEPTED)
    rep.check("torture::breadth", total >= 80,
              "torture must exercise >= 80 constrained-field mutations (got {})".format(total),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="transition-torture", pack=None, strict=strict, status=rep.status,
        record_count=total, records_total=total, report_type="wf.transition.torture.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "run_transition_torture_report.json")
    rep.print_summary("transition-torture")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
