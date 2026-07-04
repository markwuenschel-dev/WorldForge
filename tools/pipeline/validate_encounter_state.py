#!/usr/bin/env python3
"""validate_encounter_state.py — WorldForge v1.4 encounter state-machine validator (Lane C).

Proves brief §8 "encounter state actually resolves": every generated encounter
declares an honest state machine — numeric state keys whose expected_final is
the real arithmetic result of initial+delta, encounter-namespaced key names,
activation conditions that resolve against declared encounter OR linked-mission
state, and completion/failure conditions that behave correctly under the
simulated resolution transition. An encounter whose completion never fires,
fires from the initial state (fake resolution), or fails itself on success is
dishonest and blocks with ENCOUNTER_STATE_FAILURE.

State simulation reuses playtest_contract.simulate_state / completion_resolves /
failure_fires so this validator agrees byte-for-byte with the playtest harness.

Usage:
    python tools/pipeline/validate_encounter_state.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_state/validate_encounter_state_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
import playtest_contract as PC
from encounter_catalog import load_encounter_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

_EPS = 1e-6


def check_state(rep, eid, enc, mission):
    """Importable core: add state-machine checks for one encounter to ``rep``."""
    code = FailureCode.ENCOUNTER_STATE_FAILURE

    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(eid, name), ok, detail, code=code)

    # --- declared encounter state keys: shape, honesty, namespace hygiene ----
    state_keys = enc.get("state_keys") or []
    c("state_keys_present", bool(state_keys),
      "no state keys — encounter is stateless")

    declared = set()
    names = []
    for i, s in enumerate(state_keys):
        shape_ok = isinstance(s, dict) and all(
            k in s for k in ("key", "initial", "delta", "expected_final"))
        c("state_{}_shape".format(i), shape_ok,
          "state key {} missing key/initial/delta/expected_final".format(i))
        if not shape_ok:
            continue
        key = s["key"]
        names.append(key)
        declared.add(key)
        c("state_{}_namespaced".format(i),
          isinstance(key, str) and key.startswith(eid),
          "state key '{}' not prefixed with encounter_id '{}'".format(key, eid))
        try:
            initial = float(s["initial"])
            delta = float(s["delta"])
            expected = float(s["expected_final"])
        except (TypeError, ValueError):
            c("state_{}_numeric".format(i), False,
              "initial/delta not numeric: {}".format(s))
            continue
        c("state_{}_numeric".format(i), True)
        # expected_final must be the honest arithmetic result, not fabricated.
        c("state_{}_final_honest".format(i),
          abs(expected - (initial + delta)) <= _EPS,
          "expected_final {} != initial+delta {}".format(expected, initial + delta))

    c("state_key_names_unique", len(names) == len(set(names)),
      "duplicate state key names: {}".format(
          sorted({n for n in names if names.count(n) > 1})))

    mission_keys = {s.get("key") for s in (mission or {}).get("state_keys") or []
                    if isinstance(s, dict)}
    resolvable = declared | mission_keys

    # --- activation conditions: shape + resolvable against declared state ----
    acts = enc.get("activation_conditions") or []
    c("activation_conditions_present", bool(acts),
      "no activation conditions — encounter can never activate")
    for i, a in enumerate(acts):
        shape_ok = isinstance(a, dict) and all(k in a for k in EC.CONDITION_REQUIRED)
        c("activation_{}_shape".format(i), shape_ok,
          "activation condition {} missing {}".format(i, EC.CONDITION_REQUIRED))
        if not shape_ok:
            continue
        c("activation_{}_operator_known".format(i),
          a.get("operator") in MC.COMPLETION_OPERATORS,
          "unknown operator '{}'".format(a.get("operator")))
        c("activation_{}_key_resolvable".format(i),
          a.get("state_key") in resolvable,
          "activation state_key '{}' not in encounter or mission state keys".format(
              a.get("state_key")))

    # --- completion conditions: encounter-owned keys + honest resolution -----
    comps = enc.get("completion_conditions") or []
    c("completion_conditions_present", bool(comps),
      "no completion conditions — encounter can never resolve")
    for i, cc in enumerate(comps):
        shape_ok = isinstance(cc, dict) and all(k in cc for k in EC.CONDITION_REQUIRED)
        c("completion_{}_shape".format(i), shape_ok,
          "completion condition {} missing {}".format(i, EC.CONDITION_REQUIRED))
        if not shape_ok:
            continue
        c("completion_{}_key_is_encounter_state".format(i),
          cc.get("state_key") in declared,
          "completion state_key '{}' is not a declared encounter state key".format(
              cc.get("state_key")))

    # --- simulate the resolution transition (initial + delta) ----------------
    initial_state = {}
    for s in state_keys:
        if isinstance(s, dict) and "key" in s:
            try:
                initial_state[s["key"]] = float(s.get("initial", 0))
            except (TypeError, ValueError):
                initial_state[s["key"]] = None
    final = PC.simulate_state(enc)

    resolves = PC.completion_resolves(enc, final)
    c("resolution_satisfies_completion", resolves,
      "simulated final {} does not satisfy every completion condition — "
      "encounter completion state never fires".format(final))

    # Failure conditions must exist and must NOT fire on the resolved state.
    fails = enc.get("failure_conditions") or []
    c("failure_conditions_present", bool(fails),
      "no failure conditions — encounter cannot fail")
    fires = PC.failure_fires(enc, final)
    c("no_failure_on_resolved_state", not fires,
      "a failure condition fires on the resolved state: final={}".format(final))

    # The INITIAL state must not already satisfy completion (fake resolution).
    c("initial_state_not_complete",
      not PC.completion_resolves(enc, initial_state),
      "completion already satisfied by initial state {} — "
      "fires without resolution".format(initial_state))

    # bypass_allowed does not excuse a broken state machine: completion must
    # still be reachable through the declared transition.
    if enc.get("bypass_allowed"):
        c("bypass_completion_still_reachable", resolves,
          "bypass_allowed but completion threshold unreachable: final={}".format(final))

    # --- spawn groups must reference declared encounter state ----------------
    for gi, g in enumerate(enc.get("spawn_groups") or []):
        gkeys = (g or {}).get("state_keys") or []
        unknown = [k for k in gkeys if k not in declared]
        c("spawn_group_{}_state_keys_declared".format(gi), not unknown,
          "spawn group state_keys not declared on the encounter: {}".format(unknown))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate v1.4 encounter state machines (brief §8).")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted((catalog.get("encounters") or {}).keys())
    if not eids:
        rep.error("no encounters — run 'make create-encounters' first")
    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("{}::loads".format(eid), False, err,
                      code=FailureCode.ENCOUNTER_STATE_FAILURE)
            continue
        mission, merr = MC.load_mission(enc.get("mission_id") or "")
        rep.check("{}::mission_loads".format(eid), mission is not None,
                  merr or "", code=FailureCode.ENCOUNTER_STATE_FAILURE)
        check_state(rep, eid, enc, mission)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-state", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_state",
              "validate_encounter_state_report.json")
    rep.print_summary("validate-encounter-state")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
