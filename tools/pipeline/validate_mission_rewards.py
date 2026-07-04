#!/usr/bin/env python3
"""validate_mission_rewards.py — WorldForge v1.3 mission reward/progression validator (Agent 3).

Proves brief §1/§2 "reward / progression": completing a mission actually GRANTS
something. Each reward output must be well-formed and of a known type, must fire
on a REAL completion condition (not a dangling id), and the mission's completions
must be covered by rewards — a mission that can be completed but grants no
reward/output is too weak. Any of these fails with MISSION_REWARD_FAILURE.

Usage:
    python tools/pipeline/validate_mission_rewards.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/validate_mission_rewards/validate_mission_rewards_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
from mission_catalog import load_mission_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def check_mission(rep, mid, m):
    code = FailureCode.MISSION_REWARD_FAILURE

    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=code)

    rewards = m.get("reward_outputs") or []
    c("rewards_present", bool(rewards), "no reward_outputs — completing grants nothing")

    comps = m.get("completion_conditions") or []
    comp_ids = [c0.get("condition_id") for c0 in comps]
    comp_id_set = set(comp_ids)

    # Shape + type + fires_on references a real completion condition.
    for i, r in enumerate(rewards):
        missing = [k for k in MC.REWARD_REQUIRED if k not in r]
        c("reward_{}_complete".format(i), not missing, "reward {} missing: {}".format(i, missing))
        c("reward_{}_type".format(i), r.get("reward_type") in MC.REWARD_TYPES,
          "reward {} type={}".format(i, r.get("reward_type")))
        c("reward_{}_fires_on_real_completion".format(i), r.get("fires_on") in comp_id_set,
          "reward {} fires_on={} not in completion ids {}".format(i, r.get("fires_on"), sorted(comp_id_set)))

    if not rewards or not comps:
        return

    # Completion coverage: every completion has a reward that fires on it, OR at
    # least one reward fires on the primary (first) completion. Either way the
    # mission's completion actually yields an output.
    fires = {r.get("fires_on") for r in rewards}
    all_covered = all(cid in fires for cid in comp_ids)
    primary_covered = comp_ids[0] in fires
    c("completion_rewarded", all_covered or primary_covered,
      "no reward fires on any/primary completion (completions={}, reward fires_on={})".format(
          sorted(comp_id_set), sorted(f for f in fires if f is not None)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 mission reward/progression outputs.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_mission_catalog(REPO_ROOT)
    mids = sorted((catalog.get("missions") or {}).keys())
    if not mids:
        rep.error("no missions — run 'make create-mission-loops' first")
    n = 0
    for mid in mids:
        m, err = MC.load_mission(mid)
        if m is None:
            rep.check("{}::loads".format(mid), False, err, code=FailureCode.MISSION_REWARD_FAILURE)
            continue
        check_mission(rep, mid, m)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mission-rewards", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_mission_rewards",
              "validate_mission_rewards_report.json")
    rep.print_summary("validate-mission-rewards")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
