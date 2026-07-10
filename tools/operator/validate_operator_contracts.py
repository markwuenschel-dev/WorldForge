#!/usr/bin/env python3
"""validate_operator_contracts.py — v2.1 OperatorForge contract-spine gate.

Proves the OperatorForge schema spine (operator_contracts.CONTRACTS) is coherent
and constrains correctly — the always-available, runtime-free gate that is GREEN
from Wave 1 while the index/dashboard/command gates stay honestly RED until real
artifacts exist.

It DOGFOODS the schema registry: every valid example must pass its own validator
with zero failures, and every known-bad example must be REJECTED for its OWNING
failure code. A validator that greens its known-bad, or one that rejects the valid
example, is a fake-green vector and turns this gate RED — no real data required.

This mirrors validate_vertical_slice_contracts.py exactly (the v2.0 gate); the
operator command allowlist is additionally sanity-checked for internal coherence
(the three policy subsets must partition the allowlist, and destructive commands
must never leak into it).

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/validate_operator_contracts.py --strict
Reports -> procedural/reports/operator/validate_operator_contracts_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_contracts as OX
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "operator"


def _dogfood(rep):
    """Every valid example passes; every known-bad is rejected for its owning code."""
    n = 0
    for name, (validate, good, bad) in OX.CONTRACTS.items():
        n += 1
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("dogfood::{}::valid_example_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:4]),
                  code=FailureCode.OPERATOR_REPORT_INTEGRITY_FAILED)
        bfails = [c for c in validate(bad(), strict=True) if not c[1]]
        codes = {c[3] for c in bfails}
        rep.check("dogfood::{}::known_bad_rejected".format(name), len(bfails) > 0,
                  "known-bad example must be rejected",
                  code=FailureCode.OPERATOR_NEGATIVE_ACCEPTED)
        owning = OX.KNOWN_BAD_OWNING_CODE.get(name)
        rep.check("dogfood::{}::rejected_for_owning_code".format(name),
                  owning in codes,
                  "known-bad must be rejected for owning code {} (got {})".format(
                      owning, sorted(str(c) for c in codes)[:4]),
                  code=FailureCode.OPERATOR_NEGATIVE_ACCEPTED)
    rep.check("dogfood::registry_nonempty", n > 0,
              "CONTRACTS registry must not be empty",
              code=FailureCode.OPERATOR_INDEX_SCHEMA_INVALID)
    # every contract must appear in exactly one CONTRACT_GROUPS lane.
    grouped = [c for lane in OX.CONTRACT_GROUPS.values() for c in lane]
    rep.check("dogfood::groups_partition_registry",
              sorted(grouped) == sorted(OX.CONTRACTS.keys()),
              "CONTRACT_GROUPS must partition CONTRACTS exactly (got {} vs {})".format(
                  sorted(grouped), sorted(OX.CONTRACTS.keys())),
              code=FailureCode.OPERATOR_INDEX_SCHEMA_INVALID)
    return n


def _command_policy_coherent(rep):
    """The command allowlist policy subsets must be internally coherent."""
    allow = set(OX.OPERATOR_COMMAND_ALLOWLIST)
    ro = set(OX.OPERATOR_READ_ONLY_COMMANDS)
    tg = set(OX.OPERATOR_TARGETED_COMMANDS)
    au = set(OX.OPERATOR_AUTHORIZATION_COMMANDS)
    fm = set(OX.OPERATOR_FULL_MATRIX_COMMANDS)
    dz = set(OX.OPERATOR_DESTRUCTIVE_COMMANDS)

    rep.check("policy::allowlist_is_union",
              allow == (ro | tg | au),
              "OPERATOR_COMMAND_ALLOWLIST must be read_only | targeted | authorization",
              code=FailureCode.OPERATOR_COMMAND_NOT_ALLOWLISTED)
    rep.check("policy::subsets_disjoint",
              not (ro & tg) and not (ro & au) and not (tg & au),
              "read_only / targeted / authorization subsets must be disjoint",
              code=FailureCode.OPERATOR_COMMAND_NOT_ALLOWLISTED)
    rep.check("policy::full_matrix_in_authorization",
              fm <= au,
              "every full-matrix command must be an authorization command",
              code=FailureCode.OPERATOR_FULL_MATRIX_UNAUTHORIZED)
    rep.check("policy::destructive_never_allowlisted",
              not (dz & allow),
              "destructive commands must never appear on the allowlist (leak: {})".format(
                  sorted(dz & allow)),
              code=FailureCode.OPERATOR_DESTRUCTIVE_COMMAND_BLOCKED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator contract-spine gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = _dogfood(rep)
    _command_policy_coherent(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-contracts", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.operator.contract_spine.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_operator_contracts_report.json")
    rep.print_summary("operator-contracts")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
