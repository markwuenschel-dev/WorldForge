#!/usr/bin/env python3
"""operator_torture.py — v2.1 OperatorForge hostile torture battery (Wave R).

Proves the operator honesty detectors reject the ways an operator view can fake
success. Dogfood-based: it constructs the hostile states in-code and asserts they
are caught, so it certifies the DETECTORS (not the live evidence) and is
meaningfully GREEN. Each mode is the operator-facing form of a fake-green.

Torture modes:
  fake-pass index (integrity=pass over missing/stale evidence), stale index
  (live + unknown sha), over-claim scenario card (runtime pass, no report paths),
  proved-navmesh route (headless honest-limit claimed proved), collapsed ownership
  (third-party marked regenerate), fake command-result (nonzero exit = pass),
  self-diff (left==right run), unallowlisted/destructive/full-matrix command
  allowed, and a fake-pass evidence trace (verdict pass, no supporting report).

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/operator_torture.py --strict
Reports -> procedural/reports/operator/negatives/operator_torture_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_command as OC
import operator_contracts as OX
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "negatives"


def _rejected_for(validate, record, code):
    fails = [c for c in validate(record, strict=True) if not c[1]]
    return any(c[3] == code for c in fails), [c[0] for c in fails][:3]


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator torture battery.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "operator_torture", strict=strict)

    # 1. fake-pass index: integrity=pass but missing evidence.
    ok, _ = _rejected_for(OX.validate_report_index,
                          OX._example_report_index(missing_evidence=["x.json"]),
                          F.OPERATOR_MISSING_EVIDENCE)
    rep.check("torture::fake_pass_index_rejected", ok,
              "integrity=pass over missing evidence must reject", code=F.OPERATOR_TORTURE_FAILED)

    # 2. stale index: live + unknown sha.
    ok, _ = _rejected_for(OX.validate_report_index,
                          OX._example_report_index(git_sha="unknown"),
                          F.OPERATOR_STALE_EVIDENCE)
    rep.check("torture::stale_index_rejected", ok,
              "live index with unknown sha must reject", code=F.OPERATOR_TORTURE_FAILED)

    # 3. over-claim scenario card: runtime pass, no report paths.
    ok, _ = _rejected_for(OX.validate_scenario_card,
                          OX._example_scenario_card(report_paths=[]),
                          F.OPERATOR_REPORT_PATH_MISSING)
    rep.check("torture::overclaim_card_rejected", ok,
              "runtime-pass card with no report paths must reject", code=F.OPERATOR_TORTURE_FAILED)

    # 4. proved-navmesh route (honest headless limit claimed proved).
    ok, _ = _rejected_for(OX.validate_route_walkability_view,
                          OX._example_route_walkability_view(traversal_mode="grounded_navmesh"),
                          F.OPERATOR_ROUTE_VIEW_INVALID)
    rep.check("torture::proved_navmesh_rejected", ok,
              "proved grounded_navmesh must reject", code=F.OPERATOR_TORTURE_FAILED)

    # 5. collapsed ownership: third-party marked regenerate.
    ok, _ = _rejected_for(OX.validate_asset_ownership_view,
                          OX._example_asset_ownership_view(ownership_class="third_party_owned",
                                                           repair_destroy_policy="regenerate"),
                          F.OPERATOR_ASSET_OWNERSHIP_INVALID)
    rep.check("torture::collapsed_ownership_rejected", ok,
              "third-party regenerate must reject", code=F.OPERATOR_TORTURE_FAILED)

    # 6. fake command-result: nonzero exit but status pass.
    ok, _ = _rejected_for(OX.validate_command_result,
                          OX._example_command_result(exit_code=1, status="pass"),
                          F.OPERATOR_COMMAND_RESULT_INVALID)
    rep.check("torture::fake_command_result_rejected", ok,
              "nonzero-exit pass result must reject", code=F.OPERATOR_TORTURE_FAILED)

    # 7. self-diff: left run == right run.
    ok, _ = _rejected_for(OX.validate_diff_report,
                          OX._example_diff_report(right_run_id="run0001"),
                          F.OPERATOR_DIFF_INVALID)
    rep.check("torture::self_diff_rejected", ok,
              "diff of a run against itself must reject", code=F.OPERATOR_TORTURE_FAILED)

    # 8. fake-pass evidence trace: verdict pass, no supporting report.
    ok, _ = _rejected_for(OX.validate_evidence_trace,
                          OX._example_evidence_trace(supporting_reports=[]),
                          F.OPERATOR_EVIDENCE_TRACE_INVALID)
    rep.check("torture::fake_pass_trace_rejected", ok,
              "verdict-pass trace with no supporting report must reject",
              code=F.OPERATOR_TORTURE_FAILED)

    # 9-11. command launcher refuses unsafe commands.
    for label, kwargs, code in (
        ("unallowlisted", dict(command_id="rm-repo", dry_run=True),
         F.OPERATOR_COMMAND_NOT_ALLOWLISTED),
        ("destructive", dict(command_id="git-clean", dry_run=True),
         F.OPERATOR_DESTRUCTIVE_COMMAND_BLOCKED),
        ("full_matrix", dict(command_id="vertical-slice-runtime-matrix", dry_run=False, reason=""),
         F.OPERATOR_FULL_MATRIX_UNAUTHORIZED)):
        _req, allowed, decision = OC.plan_request(**kwargs)
        rep.check("torture::command_{}_refused".format(label),
                  allowed is False and decision == code,
                  "unsafe command {} must be refused for {}".format(kwargs["command_id"], code),
                  code=F.OPERATOR_TORTURE_FAILED)

    # reverse control: the canonical valid examples still pass (no over-rejection).
    for name, (validate, good_fn, _bad) in OX.CONTRACTS.items():
        gfails = [c for c in validate(good_fn(), strict=True) if not c[1]]
        rep.check("torture::valid::{}".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:3]),
                  code=F.OPERATOR_TORTURE_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-torture", pack=None, strict=strict, status=rep.status,
        record_count=11, records_total=11, report_type="wf.operator.torture.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "operator_torture_report.json")
    rep.print_summary("operator-torture")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
