#!/usr/bin/env python3
"""validate_mission_state.py — WorldForge v1.3 mission stateful-response validator (Agent 3).

Proves brief §3 "stateful world response": every mission genuinely CHANGES the
world state and that change is what satisfies the objective. A mission that
"completes" without moving any state, or whose declared expected_final was
fabricated (not initial+delta), or whose completion references an undeclared
state key, is too weak / dishonest and fails with MISSION_STATE_FAILURE.

State simulation reuses playtest_contract.simulate_state / completion_resolves /
failure_fires so this validator agrees byte-for-byte with the PlaytestForge harness.

Usage:
    python tools/pipeline/validate_mission_state.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/validate_mission_state/validate_mission_state_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
import playtest_contract as PC
from mission_catalog import load_mission_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

_EPS = 1e-6


def check_mission(rep, mid, m):
    code = FailureCode.MISSION_STATE_FAILURE

    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=code)

    state_keys = m.get("state_keys") or []
    c("state_keys_present", bool(state_keys), "no state keys — mission is stateless")
    if not state_keys:
        return

    # Shape + honesty of every declared state key.
    declared = set()
    changes = False
    for i, s in enumerate(state_keys):
        shape_ok = isinstance(s, dict) and all(k in s for k in ("key", "initial", "delta", "expected_final"))
        c("state_{}_shape".format(i), shape_ok,
          "state key {} missing key/initial/delta/expected_final".format(i))
        if not shape_ok:
            continue
        declared.add(s["key"])
        try:
            initial = float(s["initial"])
            delta = float(s["delta"])
            expected = float(s["expected_final"])
        except (TypeError, ValueError):
            c("state_{}_numeric".format(i), False,
              "initial/delta/expected_final not numeric: {}".format(s))
            continue
        # expected_final must be the honest arithmetic result, not fabricated.
        c("state_{}_final_honest".format(i), abs(expected - (initial + delta)) <= _EPS,
          "expected_final {} != initial+delta {}".format(expected, initial + delta))
        if abs(delta) > _EPS:
            changes = True

    # The mission must genuinely change state (delta != 0 for at least one key).
    c("state_changes", changes,
      "no state key has a non-zero delta — mission completes with no world change")

    # Every completion condition must reference a DECLARED state key.
    comps = m.get("completion_conditions") or []
    undeclared = [c0.get("state_key") for c0 in comps if c0.get("state_key") not in declared]
    c("completion_keys_declared", not undeclared,
      "completion references undeclared state keys: {}".format(undeclared))

    # The simulated state change must actually satisfy the objective (and not
    # trip a failure condition such as 'state never changed').
    final = PC.simulate_state(m)
    resolves = PC.completion_resolves(m, final)
    c("state_change_resolves_completion", resolves,
      "simulated final {} does not resolve completion".format(final))
    fires = PC.failure_fires(m, final)
    c("no_failure_after_transition", not fires,
      "a failure condition fires after the successful transition: final={}".format(final))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 mission stateful world response.")
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
            rep.check("{}::loads".format(mid), False, err, code=FailureCode.MISSION_STATE_FAILURE)
            continue
        check_mission(rep, mid, m)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mission-state", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_mission_state",
              "validate_mission_state_report.json")
    rep.print_summary("validate-mission-state")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
