#!/usr/bin/env python3
"""validate_mission_contract.py — WorldForge v1.3 mission contract validator (Agent 1).

Validates every generated mission against the v1.3 contract (brief §2): required
fields present, no unknown fields in STRICT, archetype/biome in the frozen
taxonomy, and the nested sub-contracts (route, completion, reward, save-load,
playtest, state) structurally complete. The schema gate — deeper per-dimension
checks live in the sibling validators (graph/placement/state/save-load/rewards/
dependencies) and the PlaytestForge harness.

Usage:
    python tools/pipeline/validate_mission_contract.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/validate_mission_contract/validate_mission_contract_report.json
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


def check_mission(rep, mid, m, strict):
    def c(name, ok, detail="", code=FailureCode.MISSION_CONTRACT_FAILURE, warn_only=False):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=code, warn_only=warn_only)

    missing = MC.missing_required_fields(m)
    c("required_fields_present", not missing, "missing: {}".format(missing))
    unknown = MC.unknown_fields(m)
    c("no_unknown_fields", not unknown, "unknown: {}".format(unknown),
      code=FailureCode.UNKNOWN_SCHEMA_FIELD, warn_only=not strict)

    c("archetype_known", m.get("mission_archetype") in MC.MISSION_ARCHETYPES,
      "archetype={}".format(m.get("mission_archetype")))
    c("biome_known", m.get("biome_family") in MC.BIOME_FAMILIES,
      "biome={}".format(m.get("biome_family")),
      code=FailureCode.MISSION_BIOME_COMPATIBILITY_FAILURE)
    c("ownership_generated", m.get("ownership_class") == "generated_owned",
      "ownership={}".format(m.get("ownership_class")))

    # route
    route = m.get("required_route") or {}
    miss = [k for k in MC.ROUTE_REQUIRED if k not in route]
    c("route_complete", not miss, "route missing: {}".format(miss), code=FailureCode.MISSION_ROUTE_FAILURE)

    # completion
    comps = m.get("completion_conditions") or []
    c("has_completion", bool(comps), "no completion conditions", code=FailureCode.MISSION_OBJECTIVE_FAILURE)
    for i, comp in enumerate(comps):
        cm = [k for k in MC.COMPLETION_REQUIRED if k not in comp]
        c("completion_{}_complete".format(i), not cm, "missing {}".format(cm),
          code=FailureCode.MISSION_OBJECTIVE_FAILURE)
        c("completion_{}_operator".format(i), comp.get("operator") in MC.COMPLETION_OPERATORS,
          "operator={}".format(comp.get("operator")), code=FailureCode.MISSION_OBJECTIVE_FAILURE)

    # rewards
    rewards = m.get("reward_outputs") or []
    c("has_reward", bool(rewards), "no rewards", code=FailureCode.MISSION_REWARD_FAILURE)
    for i, r in enumerate(rewards):
        rm = [k for k in MC.REWARD_REQUIRED if k not in r]
        c("reward_{}_complete".format(i), not rm, "missing {}".format(rm), code=FailureCode.MISSION_REWARD_FAILURE)
        c("reward_{}_type".format(i), r.get("reward_type") in MC.REWARD_TYPES,
          "type={}".format(r.get("reward_type")), code=FailureCode.MISSION_REWARD_FAILURE)

    # save/load
    sl = m.get("save_load_contract") or {}
    slm = [k for k in MC.SAVE_LOAD_REQUIRED if k not in sl]
    c("save_load_complete", not slm, "missing {}".format(slm), code=FailureCode.MISSION_SAVE_LOAD_FAILURE)
    c("save_load_persists", bool(sl.get("persist_keys")), "no persist_keys",
      code=FailureCode.MISSION_SAVE_LOAD_FAILURE)

    # playtest
    pt = m.get("playtest_contract") or {}
    ptm = [k for k in MC.PLAYTEST_REQUIRED if k not in pt]
    c("playtest_complete", not ptm, "missing {}".format(ptm), code=FailureCode.PLAYTEST_CONTRACT_FAILURE)
    c("playtest_has_modes", bool(pt.get("modes")), "no modes", code=FailureCode.PLAYTEST_CONTRACT_FAILURE)

    # state
    sk = m.get("state_keys") or []
    c("has_state_keys", bool(sk), "no state keys", code=FailureCode.MISSION_STATE_FAILURE)
    for i, s in enumerate(sk):
        c("state_{}_shape".format(i), all(k in s for k in ("key", "initial", "delta", "expected_final")),
          "state key {} incomplete".format(i), code=FailureCode.MISSION_STATE_FAILURE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 mission contract.")
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
            rep.check("{}::loads".format(mid), False, err, code=FailureCode.MISSION_CONTRACT_FAILURE)
            continue
        check_mission(rep, mid, m, strict)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mission-contract", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_mission_contract",
              "validate_mission_contract_report.json")
    rep.print_summary("validate-mission-contract")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
