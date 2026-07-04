#!/usr/bin/env python3
"""validate_encounter_contract.py — WorldForge v1.4 encounter contract validator (Lane A).

Schema gate for generated encounters (brief §8): required fields present, no
unknown fields, taxonomy membership (archetype/profile/band), the mission +
biome link, the pressure budget, and the nested sub-contracts (pacing, state,
activation/completion/failure conditions, rewards, save-load, playtest,
approach/escape routes) structurally complete. Implicit defaults fail: spawn
groups, spawn anchors, and objective links must be explicitly non-empty.

Deeper per-dimension checks live in the sibling validators
(validate_encounter_archetypes / validate_spawn_groups / pressure / pacing).

Usage:
    python tools/pipeline/validate_encounter_contract.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_contract/validate_encounter_contract_report.json
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

STATE_KEY_SHAPE = ("key", "initial", "delta", "expected_final")


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_encounter(rep, eid, enc, strict, pack="encounter_loop_world"):
    """Reusable per-encounter contract core (imported by the negative/fuzz harness)."""

    def c(name, ok, detail="", code=FailureCode.ENCOUNTER_CONTRACT_FAILURE):
        return rep.check("{}::{}".format(name, eid), ok, detail, code=code)

    enc = enc or {}

    # --- field-level schema ---------------------------------------------------
    missing = EC.missing_required_fields(enc)
    c("required_fields_present", not missing, "missing: {}".format(missing))
    unknown = EC.unknown_fields(enc)
    c("no_unknown_fields", not unknown, "unknown: {}".format(unknown))

    c("schema_version", enc.get("schema_version") == EC.ENCOUNTER_SCHEMA_VERSION,
      "schema_version={} expected {}".format(enc.get("schema_version"),
                                             EC.ENCOUNTER_SCHEMA_VERSION))
    c("encounter_id_matches", enc.get("encounter_id") == eid,
      "encounter_id={} catalog/dir key={}".format(enc.get("encounter_id"), eid))
    c("pack_id_matches", enc.get("pack_id") == pack,
      "pack_id={} expected {}".format(enc.get("pack_id"), pack))

    # --- mission link -----------------------------------------------------------
    mid = enc.get("mission_id")
    mission, merr = (None, "mission_id missing")
    if mid:
        mission, merr = MC.load_mission(mid)
    c("mission_link", mission is not None,
      "mission_id={} ({})".format(mid, merr if mission is None else "ok"))

    # --- biome link ---------------------------------------------------------------
    biome = enc.get("biome_family")
    c("biome_known", biome in MC.BIOME_FAMILIES, "biome={}".format(biome))
    c("biome_matches_mission",
      mission is not None and biome == mission.get("biome_family"),
      "encounter biome={} mission biome={}".format(
          biome, (mission or {}).get("biome_family")))

    # --- taxonomy -------------------------------------------------------------
    c("archetype_known", enc.get("encounter_archetype") in EC.ENCOUNTER_ARCHETYPES,
      "encounter_archetype={}".format(enc.get("encounter_archetype")))
    profile = enc.get("encounter_profile")
    c("profile_known", profile in EC.ENCOUNTER_PROFILES, "profile={}".format(profile))
    band = enc.get("difficulty_band")
    c("band_known", band in EC.DIFFICULTY_BANDS and band != "invalid",
      "difficulty_band={}".format(band))

    # --- pressure budget ------------------------------------------------------
    budget = enc.get("pressure_budget")
    expected_budget = EC.PROFILE_PRESSURE_BUDGETS.get(profile)
    c("pressure_budget",
      _is_number(budget) and budget > 0 and budget == expected_budget,
      "pressure_budget={} expected {} (profile={})".format(budget, expected_budget, profile))

    # --- playtest contract ------------------------------------------------------
    pt = enc.get("playtest_contract") or {}
    ptm = [k for k in EC.PLAYTEST_REQUIRED if k not in pt]
    c("playtest_complete", not ptm, "missing {}".format(ptm))
    c("playtest_has_modes", bool(pt.get("modes")), "no playtest modes")
    c("playtest_expects_completion", pt.get("expected_completion") is True,
      "expected_completion={}".format(pt.get("expected_completion")))

    # --- pacing target ----------------------------------------------------------
    pac = enc.get("pacing_target") or {}
    pacm = [k for k in EC.PACING_TARGET_REQUIRED if k not in pac]
    c("pacing_target_complete", not pacm, "missing {}".format(pacm))

    # --- state keys ---------------------------------------------------------------
    sks = [s for s in enc.get("state_keys") or [] if isinstance(s, dict)]
    c("has_state_keys", bool(sks), "no state keys")
    for i, s in enumerate(sks):
        miss = [k for k in STATE_KEY_SHAPE if k not in s]
        c("state_{}_shape".format(i), not miss, "state key {} missing {}".format(i, miss))
    declared_keys = {s.get("key") for s in sks if s.get("key")}
    mission_keys = {s.get("key")
                    for s in (mission or {}).get("state_keys") or []
                    if isinstance(s, dict) and s.get("key")}

    # --- completion conditions ------------------------------------------------
    comps = enc.get("completion_conditions") or []
    c("has_completion", bool(comps), "no completion conditions")
    for i, comp in enumerate(comps):
        cm = [k for k in EC.CONDITION_REQUIRED if k not in comp]
        c("completion_{}_complete".format(i), not cm, "missing {}".format(cm))
        c("completion_{}_operator".format(i),
          comp.get("operator") in MC.COMPLETION_OPERATORS,
          "operator={}".format(comp.get("operator")))
        sk = comp.get("state_key")
        c("completion_{}_state_key_declared".format(i),
          sk in declared_keys or sk in mission_keys,
          "state_key={} not in encounter or linked-mission state keys".format(sk))

    # --- failure conditions -----------------------------------------------------
    fails = enc.get("failure_conditions") or []
    c("has_failure_conditions", bool(fails), "no failure conditions")
    for i, fc in enumerate(fails):
        fm = [k for k in EC.CONDITION_REQUIRED if k not in fc]
        c("failure_{}_complete".format(i), not fm, "missing {}".format(fm))

    # --- activation conditions ---------------------------------------------------
    acts = enc.get("activation_conditions") or []
    c("has_activation_conditions", bool(acts), "no activation conditions")
    for i, ac in enumerate(acts):
        am = [k for k in EC.CONDITION_REQUIRED if k not in ac]
        c("activation_{}_complete".format(i), not am, "missing {}".format(am))

    # --- reward hooks -----------------------------------------------------------
    rewards = enc.get("reward_hooks") or []
    c("has_reward_hooks", bool(rewards), "no reward hooks")
    for i, r in enumerate(rewards):
        rm = [k for k in EC.REWARD_HOOK_REQUIRED if k not in r]
        c("reward_{}_complete".format(i), not rm, "missing {}".format(rm))
        c("reward_{}_type".format(i), r.get("reward_type") in MC.REWARD_TYPES,
          "reward_type={}".format(r.get("reward_type")))

    # --- save/load contract -----------------------------------------------------
    sl = enc.get("save_load_contract") or {}
    slm = [k for k in EC.SAVE_LOAD_REQUIRED if k not in sl]
    c("save_load_complete", not slm, "missing {}".format(slm))
    c("save_load_roundtrip", sl.get("expect_roundtrip") is True,
      "expect_roundtrip={}".format(sl.get("expect_roundtrip")))
    persist = set(sl.get("persist_keys") or [])
    unpersisted = sorted(declared_keys - persist)
    c("save_load_persists_state", not unpersisted,
      "encounter state keys not in persist_keys: {}".format(unpersisted))

    # --- ownership --------------------------------------------------------------
    c("ownership_generated", enc.get("ownership_class") == "generated_owned",
      "ownership={}".format(enc.get("ownership_class")))

    # --- route sub-contracts ------------------------------------------------------
    for field in ("approach_routes", "escape_routes"):
        for i, route in enumerate(enc.get(field) or []):
            rm = [k for k in EC.ROUTE_REQUIRED if k not in route]
            c("{}_{}_complete".format(field, i), not rm, "missing {}".format(rm))
            wps = route.get("waypoints") or []
            c("{}_{}_waypoints".format(field, i), len(wps) >= 2,
              "waypoints={} (need >=2)".format(len(wps)))

    # --- implicit defaults fail ---------------------------------------------------
    c("has_spawn_groups", bool(enc.get("spawn_groups")), "no spawn groups")
    c("has_spawn_anchors", bool(enc.get("spawn_anchors")), "no spawn anchors")
    c("has_objective_links", bool(enc.get("objective_links")), "no objective links")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 encounter contract.")
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
            rep.check("loads::{}".format(eid), False, err,
                      code=FailureCode.ENCOUNTER_CONTRACT_FAILURE)
            continue
        check_encounter(rep, eid, enc, strict, pack=args.pack)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-contract", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_contract",
              "validate_encounter_contract_report.json")
    rep.print_summary("validate-encounter-contract")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
