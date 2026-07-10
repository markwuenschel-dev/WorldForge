#!/usr/bin/env python3
"""operator_command.py — v2.1 OperatorForge safe command launcher (Wave 4).

Lets an operator plan and (for read-only commands) run bounded, allowlisted
validation/rerun/index commands — and NOTHING else. Every request is built as an
OperatorCommandRequest and validated against its contract before anything runs, so
the safety policy (handoff §9) is enforced at the schema layer, not by ad-hoc ifs:

  * command_id must be on the allowlist                       -> WF726
  * destructive commands are forbidden (never allowed)        -> WF729
  * a full-matrix rerun requires an explicit reason           -> WF728
  * a non-read-only command run for real needs dry_run/reason -> WF727

Dry-run (--dry-run) produces the exact planned command WITHOUT executing it. A
read-only command may run for real; its stdout/stderr are captured to run-scoped
files and an OperatorCommandResult is written. Non-read-only / authorization /
full-matrix commands are planned but NOT auto-executed here (they need explicit
operator authorization) — v2.1 never launches a full 120 rerun or a destructive
op on its own.

The plan_request() function is the single decision point, reused by
operator_command_negatives.py so the negatives attack the real launcher logic.

Acceptance:
    PYTHONUTF8=1 python tools/operator/operator_command.py --dry-run --command operator-index-reports
Reports -> procedural/reports/operator/commands/<request_id>.json (+ result/stdout/stderr)
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_contracts as OX
from failure_codes import FailureCode as F

COMMANDS_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "commands"
PY = sys.executable

# allowlisted command_id -> (script relpath, fixed args, expected_output rel).
# Only commands whose real invocation is known are mapped; an allowlisted command
# with no mapping can still be PLANNED (dry-run) but not executed.
COMMAND_MAP = {
    "operator-index-reports": ("tools/operator/index_reports.py", ["--strict"],
                               "procedural/reports/operator/index/operator_report_index.json"),
    "validate-operator-index": ("tools/operator/validate_operator_index.py", ["--strict"],
                                "procedural/reports/operator/index/validate_operator_index_report.json"),
    "operator-dashboard": ("tools/operator/build_dashboard.py", ["--strict"],
                           "procedural/reports/operator/dashboard/index.html"),
    "operator-failure-index": ("tools/operator/build_failure_index.py", ["--strict"],
                               "procedural/reports/operator/index/failure_code_index.json"),
    "operator-asset-ownership": ("tools/operator/build_asset_ownership.py", ["--strict"],
                                 "procedural/reports/operator/index/asset_ownership_views.json"),
    "operator-route-view": ("tools/operator/build_route_view.py", ["--strict"],
                            "procedural/reports/operator/index/route_walkability_views.json"),
    "operator-smoke": ("tools/operator/operator_smoke.py", ["--strict"],
                       "procedural/reports/operator/dashboard/operator_smoke_report.json"),
    "v2-1-shield": ("tools/pipeline/v2_1_shield.py", ["--strict", "--operator"], ""),
    "v2-0-shield": ("tools/pipeline/v2_0_shield.py", ["--strict"], ""),
    "vertical-slice-runtime-matrix": ("tools/pipeline/run_slice_forge_alpha.py",
                                      ["--gate", "--scenarios", "24", "--strict"], ""),
}


def plan_request(command_id, dry_run=True, reason="", target_scenarios=None,
                 target_pack="worldforge_vertical_slice", requested_by="operator"):
    """The single decision point. Returns (request_dict, allowed, decision_code).

    allowed reflects whether the request MAY proceed under §9 policy. decision_code
    is None when allowed, else the WF code explaining refusal. The returned request
    is contract-valid in shape (whether allowed or not).
    """
    target_scenarios = list(target_scenarios or [])
    reason = reason or ""
    mapped = COMMAND_MAP.get(command_id)
    args = list(mapped[1]) if mapped else []
    expected = [mapped[2]] if (mapped and mapped[2]) else []

    allowed = True
    decision = None
    if command_id in OX.OPERATOR_DESTRUCTIVE_COMMANDS:
        allowed, decision = False, F.OPERATOR_DESTRUCTIVE_COMMAND_BLOCKED
    elif command_id not in OX.OPERATOR_COMMAND_ALLOWLIST:
        allowed, decision = False, F.OPERATOR_COMMAND_NOT_ALLOWLISTED
    elif command_id in OX.OPERATOR_FULL_MATRIX_COMMANDS and not reason.strip():
        allowed, decision = False, F.OPERATOR_FULL_MATRIX_UNAUTHORIZED
    elif (command_id not in OX.OPERATOR_READ_ONLY_COMMANDS and not dry_run
          and not reason.strip()):
        allowed, decision = False, F.OPERATOR_COMMAND_DRY_RUN_REQUIRED
    elif (command_id not in OX.OPERATOR_FULL_MATRIX_COMMANDS
          and len(target_scenarios) > OX.MAX_TARGET_SCENARIOS):
        allowed, decision = False, F.OPERATOR_FULL_MATRIX_UNAUTHORIZED

    request = OX._example_command_request(
        request_id="req_{}_{}".format(command_id.replace("-", "_"),
                                      "dryrun" if dry_run else "run"),
        created_at="live",
        requested_by=requested_by,
        command_id=command_id,
        command_args=args,
        target_pack=target_pack,
        target_scenarios=target_scenarios,
        dry_run=bool(dry_run),
        allowed=bool(allowed),
        reason=reason,
        expected_outputs=expected,
    )
    return request, allowed, decision


def _execute(command_id, request):
    """Execute a read-only mapped command, capturing stdout/stderr."""
    mapped = COMMAND_MAP[command_id]
    script = REPO_ROOT / mapped[0]
    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    rid = request["request_id"]
    out_p = COMMANDS_DIR / "{}.stdout.txt".format(rid)
    err_p = COMMANDS_DIR / "{}.stderr.txt".format(rid)
    proc = subprocess.run([PY, str(script), *mapped[1]], cwd=str(REPO_ROOT),
                          capture_output=True, text=True)
    out_p.write_text(proc.stdout or "", encoding="utf-8")
    err_p.write_text(proc.stderr or "", encoding="utf-8")
    created = [request["expected_outputs"][0]] if request["expected_outputs"] else []
    result = OX._example_command_result(
        result_id="res_{}".format(rid),
        request_id=rid,
        started_at="live", ended_at="live",
        exit_code=int(proc.returncode),
        stdout_path=str(out_p.relative_to(REPO_ROOT).as_posix()),
        stderr_path=str(err_p.relative_to(REPO_ROOT).as_posix()),
        created_outputs=created if proc.returncode == 0 else [],
        updated_indexes=["operator_report_index"] if proc.returncode == 0 else [],
        status="pass" if proc.returncode == 0 else "failed",
        failure_codes=[] if proc.returncode == 0 else ["WF730_OPERATOR_COMMAND_RESULT_INVALID"],
    )
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator safe command launcher.")
    ap.add_argument("--command", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reason", default="")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--scenarios", nargs="*", default=[])
    ap.add_argument("--requested-by", default="operator")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)

    request, allowed, decision = plan_request(
        args.command, dry_run=args.dry_run, reason=args.reason,
        target_scenarios=args.scenarios, target_pack=args.pack,
        requested_by=args.requested_by)

    # the request must be contract-valid in shape regardless of the decision.
    rfails = [c for c in OX.validate_command_request(request, strict=True) if not c[1]]

    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    (COMMANDS_DIR / "{}.json".format(request["request_id"])).write_text(
        json.dumps(request, indent=2, sort_keys=True), encoding="utf-8")

    if rfails:
        print("[operator-command] FAIL — request is not contract-valid: {}".format(
            [c[0] for c in rfails][:3]))
        sys.exit(1)
    if not allowed:
        print("[operator-command] REFUSED — {} ({})".format(args.command, decision))
        sys.exit(2)

    if args.dry_run:
        print("[operator-command] DRY-RUN OK — would run '{}' -> {}".format(
            args.command,
            " ".join([str(COMMAND_MAP[args.command][0])] + COMMAND_MAP[args.command][1])
            if args.command in COMMAND_MAP else "(no mapped invocation)"))
        print("  request -> {}".format(
            (COMMANDS_DIR / "{}.json".format(request["request_id"])).as_posix()))
        sys.exit(0)

    # real run — read-only commands only (others need explicit authorization).
    if args.command not in OX.OPERATOR_READ_ONLY_COMMANDS or args.command not in COMMAND_MAP:
        print("[operator-command] REFUSED — '{}' is not a read-only mapped command; "
              "plan it with --dry-run and authorize explicitly".format(args.command))
        sys.exit(2)
    result = _execute(args.command, request)
    (COMMANDS_DIR / "{}.json".format(result["result_id"])).write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print("[operator-command] {} — '{}' exit={} -> {}".format(
        result["status"].upper(), args.command, result["exit_code"], result["result_id"]))
    sys.exit(0 if result["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
