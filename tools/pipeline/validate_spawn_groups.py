#!/usr/bin/env python3
"""validate_spawn_groups.py — WorldForge v1.4 spawn-group validator (Lane A).

Validates every spawn group of every generated encounter (brief §8/§9): the
spawn-group schema (no unknown / no missing fields), sane counts, positive
pressure/difficulty values, role/policy taxonomy membership, and full
cross-reference integrity — spawn anchor ids resolve to valid, positioned
spawn anchors; allowed spawn zones resolve to danger zones; the activation
condition resolves; group state keys are declared by the encounter.

Geometry gate (forbidden zones respected): every referenced spawn anchor must
keep EC.SAFE_START_CLEARANCE_CM (2D) from the linked mission's start anchor and
EC.OBJECTIVE_CLEARANCE_CM from every mission objective anchor — except
defensive_holdout, whose anchors legitimately ring the objective and only need
> 400 cm. Spawn groups in aggregate cannot exceed the encounter pressure
budget, and every group's budget class must match the encounter's.

Usage:
    python tools/pipeline/validate_spawn_groups.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_spawn_groups/validate_spawn_groups_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from encounter_catalog import load_encounter_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

HOLDOUT_OBJECTIVE_CLEARANCE_CM = 400.0


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_spawn_groups(rep, eid, enc, mission):
    """Reusable per-encounter spawn-group core (imported by the negative/fuzz harness).

    ``mission`` supplies start/objective geometry; it may be None, in which case
    only the mission-geometry clearance checks are skipped (everything else
    still runs) — main() separately fails encounters whose mission cannot load.
    """

    def c(name, ok, detail="", code=FailureCode.ENCOUNTER_SPAWN_GROUP_FAILURE):
        return rep.check("{}::{}".format(name, eid), ok, detail, code=code)

    enc = enc or {}
    groups = [g for g in enc.get("spawn_groups") or [] if isinstance(g, dict)]
    c("has_spawn_groups", bool(groups), "no spawn groups")

    anchors = {a.get("id"): a for a in enc.get("spawn_anchors") or []
               if isinstance(a, dict)}
    danger_ids = {d.get("id") for d in enc.get("danger_zones") or []
                  if isinstance(d, dict)}
    activation_ids = {a.get("condition_id") for a in enc.get("activation_conditions") or []
                      if isinstance(a, dict)}
    declared_keys = {s.get("key") for s in enc.get("state_keys") or []
                     if isinstance(s, dict) and s.get("key")}
    holdout = enc.get("encounter_archetype") == "defensive_holdout"

    start = ((mission or {}).get("start_anchor") or {}).get("world_position")
    objectives = [oa.get("world_position")
                  for oa in (mission or {}).get("objective_anchors") or []
                  if isinstance(oa, dict) and oa.get("world_position")]

    total_pressure = 0.0
    for gi, g in enumerate(groups):
        def gc(name, ok, detail=""):
            return c("group_{}_{}".format(gi, name), ok, detail)

        # schema
        unknown = EC.spawn_group_unknown_fields(g)
        gc("no_unknown_fields", not unknown, "unknown: {}".format(unknown))
        missing = EC.spawn_group_missing_fields(g)
        gc("required_fields_present", not missing, "missing: {}".format(missing))

        # counts
        cmin, cmax = g.get("count_min"), g.get("count_max")
        gc("count_bounds",
           _is_number(cmin) and _is_number(cmax) and cmin >= 1 and cmax >= 1
           and cmin <= cmax,
           "count=[{},{}] (need 1 <= min <= max)".format(cmin, cmax))

        # pressure / difficulty
        pv, dv = g.get("pressure_value"), g.get("difficulty_value")
        gc("pressure_positive", _is_number(pv) and pv > 0,
           "pressure_value={}".format(pv))
        gc("difficulty_positive", _is_number(dv) and dv > 0,
           "difficulty_value={}".format(dv))
        if _is_number(pv):
            total_pressure += pv

        # roles
        roles = g.get("role_tags") or []
        unknown_roles = sorted(set(roles) - set(EC.ROLE_TAGS))
        gc("role_tags_known", bool(roles) and not unknown_roles,
           "role_tags={} unknown={}".format(roles, unknown_roles))

        # spawn policy
        gc("spawn_policy_known", g.get("spawn_policy") in EC.SPAWN_POLICIES,
           "spawn_policy={}".format(g.get("spawn_policy")))

        # spawn anchors resolve + are spawnable + respect forbidden-zone geometry
        anchor_ids = g.get("spawn_anchor_ids") or []
        gc("has_spawn_anchor_ids", bool(anchor_ids), "no spawn_anchor_ids")
        for ai, aid in enumerate(anchor_ids):
            anchor = anchors.get(aid)
            gc("anchor_{}_resolves".format(ai), anchor is not None,
               "spawn_anchor_id={} not in spawn_anchors".format(aid))
            if anchor is None:
                continue
            pos = anchor.get("world_position")
            gc("anchor_{}_spawnable".format(ai),
               anchor.get("valid_spawn") is True and bool(pos),
               "anchor {}: valid_spawn={} world_position={}".format(
                   aid, anchor.get("valid_spawn"), pos))
            if not pos:
                continue
            if start:
                d = MC.dist2d(pos, start)
                gc("anchor_{}_start_clearance".format(ai),
                   d >= EC.SAFE_START_CLEARANCE_CM,
                   "anchor {} is {:.1f}cm from player start (min {})".format(
                       aid, d, EC.SAFE_START_CLEARANCE_CM))
            for oi, opos in enumerate(objectives):
                d = MC.dist2d(pos, opos)
                if holdout:
                    ok = d > HOLDOUT_OBJECTIVE_CLEARANCE_CM
                    detail = "anchor {} is {:.1f}cm from objective_{} (holdout min > {})".format(
                        aid, d, oi, HOLDOUT_OBJECTIVE_CLEARANCE_CM)
                else:
                    ok = d >= EC.OBJECTIVE_CLEARANCE_CM
                    detail = "anchor {} is {:.1f}cm from objective_{} (min {})".format(
                        aid, d, oi, EC.OBJECTIVE_CLEARANCE_CM)
                gc("anchor_{}_objective_{}_clearance".format(ai, oi), ok, detail)

        # allowed spawn zones resolve to danger zones
        for zi, zid in enumerate(g.get("allowed_spawn_zones") or []):
            gc("zone_{}_resolves".format(zi), zid in danger_ids,
               "allowed_spawn_zone={} not in danger_zones {}".format(
                   zid, sorted(z for z in danger_ids if z)))

        # activation condition resolves
        gc("activation_resolves", g.get("activation_condition") in activation_ids,
           "activation_condition={} not among {}".format(
               g.get("activation_condition"), sorted(a for a in activation_ids if a)))

        # group state keys declared by the encounter
        undeclared = sorted(set(g.get("state_keys") or []) - declared_keys)
        gc("state_keys_declared", not undeclared,
           "state keys not declared by encounter: {}".format(undeclared))

        # budget class coherence
        gc("budget_class_matches", g.get("budget_class") == enc.get("budget_class"),
           "group budget_class={} encounter budget_class={}".format(
               g.get("budget_class"), enc.get("budget_class")))

    # aggregate pressure within the encounter budget
    budget = enc.get("pressure_budget")
    c("pressure_within_budget",
      _is_number(budget) and total_pressure <= budget + 1e-9,
      "sum(pressure_value)={} exceeds pressure_budget={}".format(
          round(total_pressure, 3), budget))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 encounter spawn groups.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted((catalog.get("encounters") or {}).keys())
    if not eids:
        rep.error("no encounters — run 'make create-encounters' first")
    missions = {}
    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("loads::{}".format(eid), False, err,
                      code=FailureCode.ENCOUNTER_SPAWN_GROUP_FAILURE)
            continue
        mid = enc.get("mission_id")
        if mid not in missions:
            missions[mid] = MC.load_mission(mid)[0] if mid else None
        mission = missions[mid]
        rep.check("mission_loads::{}".format(eid), mission is not None,
                  "mission_id={} did not load (geometry gate needs it)".format(mid),
                  code=FailureCode.ENCOUNTER_SPAWN_GROUP_FAILURE)
        check_spawn_groups(rep, eid, enc, mission)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-spawn-groups", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_spawn_groups",
              "validate_spawn_groups_report.json")
    rep.print_summary("validate-spawn-groups")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
