#!/usr/bin/env python3
"""validate_transition_topology.py — v2.5 shield ``--topology`` gate (Lane 2).

Proves the transition contract REGISTRY (transition_contracts) is topologically
sound — a structural check over the registry itself, independent of any 5.8
artifact, so it is GREEN from Wave 1:

  * CONTRACT_GROUPS PARTITIONS CONTRACTS exactly (every contract in exactly one
    group, no contract missing, no group naming a non-contract, no duplicate);
  * KNOWN_BAD_OWNING_CODE covers every contract, and each owning code is one the
    contract's validator actually emits;
  * every owning code, and every code in TRANSITION_CODES, is a REAL FailureCode;
  * TRANSITION_CODES is a SUPERSET of the WF1011-1033 codes each contract's
    validator references (no contract leans on a code the milestone doesn't own).

Runtime-free gate. Report -> procedural/reports/ue5_8/validate_transition_topology_report.json
Acceptance: PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_transition_topology.py --strict
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from transition_identity import transition_identity  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8"

# Every real FailureCode string value.
_ALL_FAILURE_CODES = {
    v for k, v in vars(C).items()
    if not k.startswith("_") and isinstance(v, str)}


def _band(code):
    """Extract the WFxxxx numeric band from a code string, or None."""
    if not isinstance(code, str) or len(code) < 6 or not code.startswith("WF"):
        return None
    digits = code[2:6].rstrip("_")
    return int(digits) if digits.isdigit() else None


def _referenced_codes(name):
    """The set of failure codes a contract's validator references (all examples)."""
    validate, good, bad = TC.CONTRACTS[name]
    codes = set()
    for ex in (good(), bad()):
        for check in validate(ex, strict=True):
            codes.add(check[3])
    return codes


def run(rep):
    names = sorted(TC.CONTRACTS.keys())

    # 1. Registry non-empty and holds the seven transition contracts.
    rep.check("topology::registry_has_seven", len(TC.CONTRACTS) >= 7,
              "CONTRACTS must carry >= 7 transition contracts (got {})".format(len(TC.CONTRACTS)),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    # 2. CONTRACT_GROUPS partitions CONTRACTS exactly.
    grouped = [c for lane in TC.CONTRACT_GROUPS.values() for c in lane]
    rep.check("topology::groups_cover_registry", sorted(grouped) == names,
              "CONTRACT_GROUPS must name exactly the registry contracts (got {})".format(
                  sorted(grouped)),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    rep.check("topology::groups_no_duplicates", len(grouped) == len(set(grouped)),
              "a contract appears in more than one group (not a partition): {}".format(grouped),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    # 3. KNOWN_BAD_OWNING_CODE covers every contract.
    rep.check("topology::owning_covers_registry",
              sorted(TC.KNOWN_BAD_OWNING_CODE.keys()) == names,
              "KNOWN_BAD_OWNING_CODE must cover exactly the registry contracts",
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    # 4. Every owning code is a real FailureCode, and its validator emits it.
    for name in names:
        owning = TC.KNOWN_BAD_OWNING_CODE.get(name)
        rep.check("topology::owning_is_real_code::{}".format(name),
                  owning in _ALL_FAILURE_CODES,
                  "owning code for {} is not a real FailureCode: {!r}".format(name, owning),
                  code=C.TRANSITION_UNKNOWN_FAILURE_CODE)
        rep.check("topology::owning_referenced_by_validator::{}".format(name),
                  owning in _referenced_codes(name),
                  "validator for {} never references its owning code {!r}".format(name, owning),
                  code=C.TRANSITION_UNKNOWN_FAILURE_CODE)

    # 5. TRANSITION_CODES is a set of real codes and supersets the WF1011-1033
    #    codes each contract references.
    for code in TC.TRANSITION_CODES:
        rep.check("topology::transition_code_real::{}".format(code),
                  code in _ALL_FAILURE_CODES,
                  "TRANSITION_CODES holds a non-FailureCode: {!r}".format(code),
                  code=C.TRANSITION_UNKNOWN_FAILURE_CODE)
    transition_set = set(TC.TRANSITION_CODES)
    referenced_in_band = set()
    for name in names:
        for code in _referenced_codes(name):
            b = _band(code)
            if b is not None and 1011 <= b <= 1033:
                referenced_in_band.add(code)
    missing = sorted(referenced_in_band - transition_set)
    rep.check("topology::transition_codes_superset_referenced", not missing,
              "TRANSITION_CODES missing referenced WF1011-1033 code(s): {}".format(missing),
              code=C.TRANSITION_UNKNOWN_FAILURE_CODE)
    rep.check("topology::transition_band_nonempty", len(transition_set) >= 25,
              "transition milestone must own the WF1011-1060 band (got {})".format(len(transition_set)),
              code=C.TRANSITION_UNKNOWN_FAILURE_CODE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 transition registry topology gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("gate", "transition_topology", strict=strict)
    run(rep)
    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-transition-topology", pack=args.pack, strict=strict,
        status=rep.status, record_count=len(rep.checks), records_total=len(rep.checks),
        report_type="wf.transition.topology_gate.v1",
        extra=transition_identity("5.8", runtime_required=False,
                                  runtime_executed=False, observed_runtime_engine=None)))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_transition_topology_report.json")
    rep.print_summary("transition-topology")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
