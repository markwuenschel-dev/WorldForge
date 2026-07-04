#!/usr/bin/env python3
"""validate_encounter_archetypes.py — WorldForge v1.4 archetype-conformance validator (Lane A).

Validates every generated encounter against its archetype spec yaml (brief §8):
role tags stay inside the spec's role list, spawn-group count and per-group
counts respect the spec's per-profile targets, spawn policy / bypass / cover /
escape-route requirements match, and the archetype-specific structural minimums
hold (patrol anchors, ambush anchors + readability cue, hazard zones, staged
waves, post-objective extraction trigger). Hazard zone types must be in the
frozen hazard taxonomy.

Usage:
    python tools/pipeline/validate_encounter_archetypes.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_archetypes/validate_encounter_archetypes_report.json
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


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_archetype(rep, eid, enc, archetypes):
    """Reusable per-encounter archetype core (imported by the negative/fuzz harness)."""

    def c(name, ok, detail="", code=FailureCode.ENCOUNTER_ARCHETYPE_FAILURE):
        return rep.check("{}::{}".format(name, eid), ok, detail, code=code)

    enc = enc or {}
    arch = enc.get("encounter_archetype")
    spec = (archetypes or {}).get(arch)
    if not c("archetype_spec_exists", isinstance(spec, dict),
             "no archetype spec for encounter_archetype={}".format(arch)):
        return

    profile = enc.get("encounter_profile")
    groups = [g for g in enc.get("spawn_groups") or [] if isinstance(g, dict)]

    # --- roles subset -----------------------------------------------------------
    spec_roles = set(spec.get("roles") or [])
    used_roles = set()
    for g in groups:
        used_roles.update(g.get("role_tags") or [])
    extra_roles = sorted(used_roles - spec_roles)
    c("roles_subset_of_spec", not extra_roles,
      "roles outside spec {}: {}".format(sorted(spec_roles), extra_roles))

    # --- spawn group count per profile ---------------------------------------------
    expected_groups = (spec.get("spawn_groups") or {}).get(profile)
    c("spawn_group_count", expected_groups is not None and len(groups) == expected_groups,
      "groups={} spec expects {} for profile={}".format(len(groups), expected_groups, profile))

    # --- per-group counts within spec range --------------------------------------
    rng = (spec.get("count_range") or {}).get(profile)
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        _, rng_max = rng
        for i, g in enumerate(groups):
            cmin, cmax = g.get("count_min"), g.get("count_max")
            ok = (_is_number(cmin) and _is_number(cmax)
                  and cmin >= 1 and cmin <= cmax and cmax <= rng_max)
            c("group_{}_count_range".format(i), ok,
              "count=[{},{}] spec range max {} (min>=1, min<=max)".format(cmin, cmax, rng_max))
    else:
        c("count_range_defined", False,
          "spec has no count_range for profile={}".format(profile))

    # --- spawn policy matches spec -------------------------------------------------
    spec_policy = spec.get("spawn_policy")
    for i, g in enumerate(groups):
        c("group_{}_spawn_policy".format(i), g.get("spawn_policy") == spec_policy,
          "spawn_policy={} spec {}".format(g.get("spawn_policy"), spec_policy))

    # --- cover / escape-route requirements ------------------------------------------
    if spec.get("cover_required"):
        c("cover_present", bool(enc.get("cover_anchors")),
          "spec requires cover but cover_anchors is empty")
    if spec.get("escape_route_required"):
        c("escape_route_present", bool(enc.get("escape_routes")),
          "spec requires an escape route but escape_routes is empty")

    # --- bypass flag matches spec ---------------------------------------------------
    c("bypass_matches_spec",
      bool(enc.get("bypass_allowed")) == bool(spec.get("bypass_allowed")),
      "bypass_allowed={} spec {}".format(enc.get("bypass_allowed"),
                                         spec.get("bypass_allowed")))

    # --- resource node requirement ---------------------------------------------------
    if spec.get("requires_resource_node"):
        c("resource_nodes_present", bool(enc.get("resource_nodes")),
          "spec requires a resource node but resource_nodes is empty")
        reward_types = [r.get("reward_type") for r in enc.get("reward_hooks") or []
                        if isinstance(r, dict)]
        c("resource_reward_present", "resource_grant" in reward_types,
          "no resource_grant reward hook (reward types: {})".format(reward_types))

    # --- hazard requirement --------------------------------------------------------
    hazard_zones = [h for h in enc.get("hazard_zones") or [] if isinstance(h, dict)]
    if spec.get("requires_hazard") or arch == "hazard_field":
        hz_min = spec.get("hazard_zone_min") or 1
        c("hazard_zones_present", len(hazard_zones) >= hz_min,
          "hazard_zones={} (spec min {})".format(len(hazard_zones), hz_min))

    # --- patrol archetypes -----------------------------------------------------------
    if arch in ("patrol_route", "roaming_threat"):
        p_min = spec.get("patrol_anchor_min") or 3
        patrols = enc.get("patrol_anchors") or []
        c("patrol_anchors_min", len(patrols) >= p_min,
          "patrol_anchors={} (spec min {})".format(len(patrols), p_min))

    # --- ambush choke -----------------------------------------------------------------
    if arch == "ambush_choke":
        a_min = spec.get("ambush_anchor_min") or 2
        ambushes = enc.get("ambush_anchors") or []
        c("ambush_anchors_min", len(ambushes) >= a_min,
          "ambush_anchors={} (spec min {})".format(len(ambushes), a_min))
        c("ambush_visual_marker", bool(enc.get("visual_marker_requirements")),
          "ambush needs a visual_marker_requirements readability cue")

    # --- defensive holdout ---------------------------------------------------------
    if arch == "defensive_holdout":
        wave_min = spec.get("wave_min") or 2
        c("holdout_staged_waves",
          bool(groups) and all(g.get("spawn_policy") == "staged_waves" for g in groups),
          "all holdout groups must use staged_waves: {}".format(
              [g.get("spawn_policy") for g in groups]))
        c("holdout_wave_count", len(groups) >= wave_min,
          "groups={} (spec wave_min {})".format(len(groups), wave_min))

    # --- extraction pressure ----------------------------------------------------------
    if arch == "extraction_pressure":
        mid = enc.get("mission_id")
        mission, _ = MC.load_mission(mid) if mid else (None, "mission_id missing")
        mission_keys = {s.get("key")
                        for s in (mission or {}).get("state_keys") or []
                        if isinstance(s, dict) and s.get("key")}
        post = any(isinstance(a, dict) and a.get("trigger") == "post_objective"
                   and a.get("state_key") in mission_keys
                   for a in enc.get("activation_conditions") or [])
        c("post_objective_trigger", post,
          "needs an activation condition with trigger=post_objective on a mission "
          "state key (mission keys: {})".format(sorted(mission_keys)))

    # --- hazard zone taxonomy ----------------------------------------------------------
    for i, hz in enumerate(hazard_zones):
        c("hazard_{}_type_known".format(i), hz.get("hazard_type") in EC.HAZARD_TYPES,
          "hazard_type={}".format(hz.get("hazard_type")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 encounter archetype conformance.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted((catalog.get("encounters") or {}).keys())
    if not eids:
        rep.error("no encounters — run 'make create-encounters' first")
    archetypes = EC.load_all_archetypes()
    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("loads::{}".format(eid), False, err,
                      code=FailureCode.ENCOUNTER_ARCHETYPE_FAILURE)
            continue
        check_archetype(rep, eid, enc, archetypes)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-archetypes", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_archetypes",
              "validate_encounter_archetypes_report.json")
    rep.print_summary("validate-encounter-archetypes")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
