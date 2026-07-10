#!/usr/bin/env python3
"""validate_slice_rewards.py — v2.0 Agent-5 reward/progression runtime gate.

Proves v1.9 reward/progression consequence participates in every slice scenario:
each SliceRuntimeReport has reward_granted == true AFTER mission_completed, with a
real state mutation (inventory_mutated OR progression_mutated). A reward that
mutates no persistent state is fake reward; reward without completion is rejected.
Rewards remain the v1.9 bounded deterministic consequence substrate, not final
loot feel. Fail-closed RED until Wave R produces the runtime evidence.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_slice_rewards.py \
        --pack encounter_loop_world --strict
Reports -> procedural/reports/slice/runtime/validate_slice_rewards_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
import slice_evidence as SE
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / SX.SLICE_RUNTIME_REPORTS_REL


def _facet(doc):
    mutated = doc.get("inventory_mutated") is True or doc.get("progression_mutated") is True
    # reward requires completion (reward-without-completion is rejected)
    ok = (doc.get("mission_completed") is True
          and doc.get("reward_granted") is True and mutated)
    if doc.get("reward_granted") is True and doc.get("mission_completed") is not True:
        return False, "reward_granted without mission_completed (reward-without-completion)"
    return ok, "mission_completed + reward_granted + inventory/progression mutation required"


def _dogfood(rep):
    rep.check("dogfood::good_passes", _facet(SX._example_slice_runtime_report())[0],
              "reference reward report failed", code=F.SLICE_REPORT_INTEGRITY_FAILED)
    for label, over in (
        ("no_mutation", {"inventory_mutated": False, "progression_mutated": False}),
        ("reward_without_completion", {"mission_completed": False}),
        ("no_reward", {"reward_granted": False}),
    ):
        bad = SX._example_slice_runtime_report(**over)
        rep.check("dogfood::rejects_{}".format(label), not _facet(bad)[0],
                  "'{}' must fail the reward facet".format(label),
                  code=F.SLICE_NEGATIVE_ACCEPTED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice reward gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)
    passed = SE.facet_gate(rep, _facet, SE.EXPECTED_SCENARIOS,
                           F.SLICE_REWARD_WITHOUT_MUTATION, F.SLICE_PARTIAL_MATRIX)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-slice-rewards", pack=args.pack, strict=strict,
                            status=rep.status, record_count=passed,
                            records_total=SE.EXPECTED_SCENARIOS, records_passed=passed,
                            report_type="wf.slice.rewards.v1"))
    rep.write(REPORT_DIR, "validate_slice_rewards_report.json")
    rep.print_summary("validate-slice-rewards")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
