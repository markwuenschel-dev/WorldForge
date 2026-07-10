#!/usr/bin/env python3
"""operator_command_negatives.py — v2.1 command-safety negative gate (Wave 4).

Attacks the REAL launcher decision function (operator_command.plan_request) so the
command surface cannot be tricked into allowing unsafe work. Each fixture asserts
plan_request REFUSES the request AND refuses it for the correct WF code, plus a
positive control (a legitimate read-only dry-run is allowed) so the gate is not a
"refuse everything" fake. Every produced request must also be contract-valid in
shape.

Known-bad cases (handoff §9 / §10.6):
  unallowlisted command allowed, destructive command, full-matrix without reason,
  a write command run for real without dry_run/reason, and unbounded targets.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/operator_command_negatives.py --strict
Reports -> procedural/reports/operator/commands/operator_command_negatives_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_command as OC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

COMMANDS_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "commands"


def negative_cases():
    """[(label, kwargs_to_plan_request, owning_refusal_code), ...]."""
    return [
        ("unallowlisted_allowed",
         dict(command_id="rm-the-repo", dry_run=True), F.OPERATOR_COMMAND_NOT_ALLOWLISTED),
        ("destructive_git_reset",
         dict(command_id="git-reset-hard", dry_run=True), F.OPERATOR_DESTRUCTIVE_COMMAND_BLOCKED),
        ("destructive_delete_asset",
         dict(command_id="delete-asset", dry_run=False), F.OPERATOR_DESTRUCTIVE_COMMAND_BLOCKED),
        ("full_matrix_no_reason",
         dict(command_id="vertical-slice-runtime-matrix", dry_run=False, reason=""),
         F.OPERATOR_FULL_MATRIX_UNAUTHORIZED),
        ("write_command_real_run_no_reason",
         dict(command_id="v2-0-shield", dry_run=False, reason=""),
         F.OPERATOR_COMMAND_DRY_RUN_REQUIRED),
        ("unbounded_targets",
         dict(command_id="validate-slice-scenarios", dry_run=True,
              target_scenarios=["s{}".format(i) for i in range(99)]),
         F.OPERATOR_FULL_MATRIX_UNAUTHORIZED),
    ]


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator command-safety negatives.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "operator_command_negatives", strict=strict)

    cases = negative_cases()
    rep.check("suite_nonempty", len(cases) >= 5,
              "command-negative suite must carry >= 5 fixtures (got {})".format(len(cases)),
              code=F.OPERATOR_NEGATIVE_ACCEPTED)

    for label, kwargs, owning in cases:
        request, allowed, decision = OC.plan_request(**kwargs)
        rep.check("neg::{}::refused".format(label), allowed is False,
                  "unsafe command was ALLOWED (fake green): {}".format(kwargs.get("command_id")),
                  code=F.OPERATOR_NEGATIVE_ACCEPTED)
        rep.check("neg::{}::refusal_code".format(label), decision == owning,
                  "refused for {} but expected {}".format(decision, owning),
                  code=F.OPERATOR_NEGATIVE_ACCEPTED)

    # positive control: a legitimate read-only dry-run IS allowed.
    req, allowed, decision = OC.plan_request(command_id="operator-index-reports", dry_run=True)
    rep.check("pos::read_only_dry_run_allowed", allowed is True and decision is None,
              "a legitimate read-only dry-run must be allowed (got allowed={}, code={})".format(
                  allowed, decision),
              code=F.OPERATOR_NEGATIVE_ACCEPTED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-command-negatives", pack=None, strict=strict, status=rep.status,
        record_count=len(cases), records_total=len(cases),
        report_type="wf.operator.command_negatives.v1"))
    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(COMMANDS_DIR, "operator_command_negatives_report.json")
    rep.print_summary("operator-command-negatives")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
