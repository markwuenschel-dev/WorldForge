#!/usr/bin/env python3
"""operator_negatives.py — v2.1 OperatorForge hostile negative-fixture suite.

Proves the operator schema spine REJECTS known-bad records — and rejects each one
for its OWNING failure code, because a validator that fails for the wrong reason
is not real coverage. Fixtures are generated in-code (no stored files): each is a
canonical operator_contracts._example_* with a single targeted override that
violates exactly one honesty invariant.

Two assertions per fixture: (1) the record IS rejected, and (2) it is rejected for
its owning WF7xx code. Plus a reverse dogfood (every valid example still passes —
guards against a "reject everything" fake) and a vacuous-suite guard.

These are the known-bad cases from handoff §7/§10.7: fake-pass evidence, missing
report/telemetry/package proof, unknown failure codes, stale git_sha, unallowlisted
and destructive commands, unauthorized full-matrix, collapsed ownership classes,
and a claimed navmesh traversal that the headless engine cannot prove.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/operator_negatives.py --strict
Reports -> procedural/reports/operator/negatives/operator_negatives_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_contracts as OX
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "negatives"

IDX = OX.validate_report_index
PACK = OX.validate_pack_card
SCN = OX.validate_scenario_card
TRC = OX.validate_evidence_trace
FCI = OX.validate_failure_code_index
AOV = OX.validate_asset_ownership_view
RTV = OX.validate_route_walkability_view
REQ = OX.validate_command_request
RES = OX.validate_command_result
DIF = OX.validate_diff_report
REG = OX.validate_known_regression


def cases():
    """Return [(label, validate_fn, known_bad_record, owning_failure_code), ...]."""
    c = []
    e_idx = OX._example_report_index
    e_pack = OX._example_pack_card
    e_scn = OX._example_scenario_card
    e_trc = OX._example_evidence_trace
    e_fci = OX._example_failure_code_index
    e_aov = OX._example_asset_ownership_view
    e_rtv = OX._example_route_walkability_view
    e_req = OX._example_command_request
    e_res = OX._example_command_result
    e_dif = OX._example_diff_report
    e_reg = OX._example_known_regression

    # --- OperatorReportIndex ---
    c.append(("idx:pass_with_missing_evidence", IDX,
              e_idx(missing_evidence=["procedural/reports/slice/runtime/x.json"]),
              F.OPERATOR_MISSING_EVIDENCE))
    c.append(("idx:pass_with_stale_evidence", IDX,
              e_idx(stale_evidence=["procedural/reports/slice/runtime/old.json"]),
              F.OPERATOR_STALE_EVIDENCE))
    c.append(("idx:live_without_real_sha", IDX, e_idx(git_sha="unknown"),
              F.OPERATOR_STALE_EVIDENCE))
    c.append(("idx:no_source_roots", IDX, e_idx(source_roots=[]),
              F.OPERATOR_SOURCE_ROOT_MISSING))
    c.append(("idx:bad_integrity_result", IDX, e_idx(integrity_result="green"),
              F.OPERATOR_INDEX_SCHEMA_INVALID))

    # --- OperatorPackCard ---
    c.append(("pack:v2_0_no_package", PACK, e_pack(package_exists=False, package_size_bytes=0),
              F.OPERATOR_PACKAGE_PROOF_MISSING))
    c.append(("pack:v2_0_zero_size", PACK, e_pack(package_size_bytes=0),
              F.OPERATOR_PACKAGE_PROOF_MISSING))
    c.append(("pack:empty_biomes", PACK, e_pack(biomes=[]),
              F.OPERATOR_PACK_INDEX_INVALID))

    # --- OperatorScenarioCard ---
    c.append(("scn:runtime_pass_no_reports", SCN, e_scn(report_paths=[]),
              F.OPERATOR_REPORT_PATH_MISSING))
    c.append(("scn:runtime_pass_no_telemetry", SCN, e_scn(telemetry_paths=[]),
              F.OPERATOR_REPORT_PATH_MISSING))
    c.append(("scn:bad_facet_status", SCN, e_scn(combat_status="green"),
              F.OPERATOR_SCENARIO_CARD_INVALID))

    # --- EvidenceTrace ---
    c.append(("trc:pass_no_supporting_report", TRC, e_trc(supporting_reports=[]),
              F.OPERATOR_EVIDENCE_TRACE_INVALID))
    c.append(("trc:pass_with_missing_inputs", TRC, e_trc(missing_inputs=["x.json"]),
              F.OPERATOR_MISSING_EVIDENCE))
    c.append(("trc:stale_not_blocked", TRC, e_trc(stale_inputs=["old.json"], verdict="pass"),
              F.OPERATOR_STALE_EVIDENCE))

    # --- FailureCodeIndex ---
    c.append(("fci:blocking_no_next_action", FCI, e_fci(suggested_next_actions=[]),
              F.OPERATOR_FAILURE_INDEX_INVALID))
    c.append(("fci:malformed_code", FCI, e_fci(failure_code="NOT_A_CODE"),
              F.OPERATOR_UNKNOWN_FAILURE_CODE))
    c.append(("fci:bad_severity", FCI, e_fci(severity="critical"),
              F.OPERATOR_FAILURE_INDEX_INVALID))

    # --- AssetOwnershipView ---
    c.append(("aov:third_party_regenerate", AOV,
              e_aov(ownership_class="third_party_owned", repair_destroy_policy="regenerate"),
              F.OPERATOR_ASSET_OWNERSHIP_INVALID))
    c.append(("aov:human_regenerate", AOV,
              e_aov(ownership_class="human_owned", repair_destroy_policy="regenerate"),
              F.OPERATOR_ASSET_OWNERSHIP_INVALID))
    c.append(("aov:bad_ownership_class", AOV, e_aov(ownership_class="mixed"),
              F.OPERATOR_ASSET_OWNERSHIP_INVALID))

    # --- RouteWalkabilityView ---
    c.append(("rtv:navmesh_claimed_proved", RTV, e_rtv(traversal_mode="grounded_navmesh"),
              F.OPERATOR_ROUTE_VIEW_INVALID))
    c.append(("rtv:flight_claimed_proved", RTV, e_rtv(traversal_mode="flight"),
              F.OPERATOR_ROUTE_VIEW_INVALID))
    c.append(("rtv:teleport_claimed_proved", RTV, e_rtv(traversal_mode="teleport"),
              F.OPERATOR_ROUTE_VIEW_INVALID))

    # --- OperatorCommandRequest ---
    c.append(("req:allowed_not_allowlisted", REQ, e_req(command_id="rm-the-repo", allowed=True),
              F.OPERATOR_COMMAND_NOT_ALLOWLISTED))
    c.append(("req:destructive_allowed", REQ,
              e_req(command_id="git-reset-hard", allowed=True),
              F.OPERATOR_DESTRUCTIVE_COMMAND_BLOCKED))
    c.append(("req:full_matrix_no_reason", REQ,
              e_req(command_id="vertical-slice-runtime-matrix", allowed=True,
                    dry_run=False, reason=""),
              F.OPERATOR_FULL_MATRIX_UNAUTHORIZED))
    c.append(("req:real_run_no_reason", REQ,
              e_req(command_id="v2-0-shield", allowed=True, dry_run=False, reason=""),
              F.OPERATOR_COMMAND_DRY_RUN_REQUIRED))
    c.append(("req:unbounded_targets", REQ,
              e_req(command_id="validate-slice-scenarios", allowed=True, dry_run=True,
                    target_scenarios=["s{}".format(i) for i in range(99)]),
              F.OPERATOR_FULL_MATRIX_UNAUTHORIZED))

    # --- OperatorCommandResult ---
    c.append(("res:nonzero_exit_pass", RES, e_res(exit_code=1, status="pass"),
              F.OPERATOR_COMMAND_RESULT_INVALID))
    c.append(("res:pass_no_outputs", RES, e_res(created_outputs=[]),
              F.OPERATOR_COMMAND_RESULT_INVALID))
    c.append(("res:pass_with_failure_codes", RES,
              e_res(failure_codes=["WF711_OPERATOR_INDEX_SCHEMA_INVALID"]),
              F.OPERATOR_COMMAND_RESULT_INVALID))

    # --- OperatorDiffReport ---
    c.append(("dif:same_run", DIF, e_dif(right_run_id="run0001"),
              F.OPERATOR_DIFF_INVALID))
    c.append(("dif:malformed_new_failure", DIF, e_dif(new_failures=["oops"]),
              F.OPERATOR_UNKNOWN_FAILURE_CODE))

    # --- KnownRegressionRegistry ---
    c.append(("reg:active_no_repro", REG, e_reg(reproduction_command=""),
              F.OPERATOR_REGRESSION_REGISTRY_INVALID))
    c.append(("reg:resolved_no_notes", REG,
              e_reg(status="resolved", resolution_notes="", reproduction_command="x"),
              F.OPERATOR_REGRESSION_REGISTRY_INVALID))
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator negative-fixture suite.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "operator_negatives", strict=strict)
    cs = cases()

    # vacuous-suite guard: an empty fixture set is itself a failure.
    rep.check("suite_nonempty", len(cs) >= 20,
              "negative suite must carry >= 20 fixtures (got {})".format(len(cs)),
              code=F.OPERATOR_NEGATIVE_ACCEPTED)

    for label, validate, bad, owning in cs:
        fails = [c for c in validate(bad, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("neg::{}::rejected".format(label), len(fails) > 0,
                  "known-bad fixture was ACCEPTED (fake green)",
                  code=F.OPERATOR_NEGATIVE_ACCEPTED)
        rep.check("neg::{}::owning_code".format(label), owning in codes,
                  "must be rejected for {} (got {})".format(
                      owning, sorted(str(x) for x in codes)[:4]),
                  code=F.OPERATOR_NEGATIVE_ACCEPTED)

    # reverse dogfood: every valid example must STILL pass (no reject-everything fake).
    for name, (validate, good, _bad) in OX.CONTRACTS.items():
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("reverse::{}::valid_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:4]),
                  code=F.OPERATOR_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-negative-fixtures", pack=None, strict=strict,
        status=rep.status, record_count=len(cs), records_total=len(cs),
        report_type="wf.operator.negatives.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "operator_negatives_report.json")
    rep.print_summary("operator-negative-fixtures")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
