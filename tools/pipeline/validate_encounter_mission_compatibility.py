#!/usr/bin/env python3
"""validate_encounter_mission_compatibility.py — WorldForge v1.4 mission-compat validator (Lane B).

Proves every encounter is honestly wired to its linked v1.3 mission (brief
§7/§25): the mission exists and agrees on biome and mission archetype; every
objective link resolves to a real mission objective anchor, mission resource
node, or encounter resource node; state wiring is closed — activation
conditions reference mission or encounter state keys and completion conditions
reference encounter state keys; extraction_pressure encounters are armed by the
mission's own completion contract (post_objective trigger on the mission's
completion state key at the mission's completion threshold — the mission cannot
complete before the extraction contract is armed); resource_contest encounters
only bind to missions that actually carry resource nodes; the determinism
lineage holds (encounter seed == mission seed); the difficulty band is coherent
with the encounter profile; and the encounter only uses Megascans dressing
already proven for the mission map.

Usage:
    python tools/pipeline/validate_encounter_mission_compatibility.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_mission_compatibility/validate_encounter_mission_compatibility_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from encounter_catalog import load_encounter_catalog
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport


def _fmt(items, n=4):
    items = list(items)
    shown = ", ".join(str(x) for x in items[:n])
    return shown + (" …(+{})".format(len(items) - n) if len(items) > n else "")


def check_mission_compat(rep, eid, enc, mission):
    """Core mission-compatibility checks for one encounter (importable).

    ``mission`` may be None (unresolvable mission_id) — that is itself the
    first failure and short-circuits the mission-dependent checks.
    """
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(name, eid), ok, detail,
                         code=FailureCode.ENCOUNTER_MISSION_COMPATIBILITY_FAILURE)

    # 1. The linked mission must exist and be loadable.
    if not c("mission_exists", mission is not None,
             "mission_id={} could not be loaded".format(enc.get("mission_id"))):
        return

    # 2/3. Biome and mission archetype must agree with the mission.
    c("biome_matches_mission", enc.get("biome_family") == mission.get("biome_family"),
      "encounter={} mission={}".format(enc.get("biome_family"),
                                       mission.get("biome_family")))
    c("archetype_matches_mission",
      enc.get("mission_archetype") == mission.get("mission_archetype"),
      "encounter={} mission={}".format(enc.get("mission_archetype"),
                                       mission.get("mission_archetype")))

    # 4. Every objective link resolves to a real target.
    targets = {o.get("id") for o in mission.get("objective_anchors") or []}
    targets |= {r.get("id") for r in mission.get("resource_nodes") or []}
    targets |= {r.get("id") for r in enc.get("resource_nodes") or []}
    targets.discard(None)
    dangling = [ol for ol in enc.get("objective_links") or [] if ol not in targets]
    c("objective_links_resolve", not dangling,
      "objective_links resolving to no mission objective anchor / mission "
      "resource node / encounter resource node: {}".format(_fmt(dangling)))

    # 5/6. State wiring is closed over mission + encounter state keys.
    m_keys = {k.get("key") for k in mission.get("state_keys") or []}
    e_keys = {k.get("key") for k in enc.get("state_keys") or []}
    m_keys.discard(None)
    e_keys.discard(None)
    unwired = [a.get("state_key") for a in enc.get("activation_conditions") or []
               if a.get("state_key") not in m_keys | e_keys]
    c("activation_state_keys_wired", not unwired,
      "activation state_keys unknown to mission and encounter: {}".format(
          _fmt(unwired)))
    orphaned = [x.get("state_key") for x in enc.get("completion_conditions") or []
                if x.get("state_key") not in e_keys]
    c("completion_state_keys_wired", not orphaned,
      "completion state_keys not declared by the encounter: {}".format(
          _fmt(orphaned)))

    # 7. extraction_pressure is armed by the mission's completion contract.
    extraction = enc.get("encounter_archetype") == "extraction_pressure"
    if extraction:
        post = [a for a in enc.get("activation_conditions") or []
                if a.get("trigger") == "post_objective"]
        mccs = mission.get("completion_conditions") or []
        armed = bool(post) and all(
            any(cc.get("state_key") == a.get("state_key")
                and cc.get("threshold") == a.get("threshold") for cc in mccs)
            for a in post)
        c("extraction_pressure_armed_post_objective", armed,
          "post_objective activations {} do not match mission completion "
          "conditions {}".format(
              _fmt([(a.get("state_key"), a.get("threshold")) for a in post]),
              _fmt([(cc.get("state_key"), cc.get("threshold")) for cc in mccs]))
          if post else "extraction_pressure has no post_objective activation")
    else:
        c("extraction_pressure_armed_post_objective", True,
          "n/a (encounter_archetype={})".format(enc.get("encounter_archetype")))

    # 8. resource_contest requires the mission to carry resource nodes.
    contest = enc.get("encounter_archetype") == "resource_contest"
    c("resource_contest_has_mission_nodes",
      (not contest) or bool(mission.get("resource_nodes")),
      "resource_contest over a mission with no resource_nodes"
      if contest else "n/a (encounter_archetype={})".format(
          enc.get("encounter_archetype")))

    # 9. Determinism lineage: encounter seed == mission seed.
    c("seed_matches_mission", enc.get("seed") == mission.get("seed"),
      "encounter seed={} mission seed={}".format(enc.get("seed"),
                                                 mission.get("seed")))

    # 10. Profile/band coherence.
    profile = enc.get("encounter_profile")
    band = enc.get("difficulty_band")
    allowed = EC.PROFILE_BAND_TARGETS.get(profile, ())
    c("band_coherent_with_profile", band in allowed,
      "difficulty_band={} not in {} targets {}".format(band, profile, allowed))

    # 11. Megascans dressing must already be proven for the mission map.
    mega = enc.get("megascans_dependencies") or []
    # v1.3 missions carry megascans_dressing as a scalar id (or null); a bare
    # string counts as ONE proven id, never as a set of characters.
    _dressing = (mission.get("mesh_dependencies") or {}).get("megascans_dressing")
    proven = {_dressing} if isinstance(_dressing, str) else set(_dressing or [])
    unproven = sorted(set(mega) - proven)
    c("megascans_proven_for_mission", not unproven,
      "megascans_dependencies not in the mission's megascans_dressing: {}".format(
          _fmt(unproven)))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate v1.4 encounter <-> mission compatibility.")
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
                      code=FailureCode.ENCOUNTER_MISSION_COMPATIBILITY_FAILURE)
            continue
        mission, _merr = MC.load_mission(enc.get("mission_id") or "")
        check_mission_compat(rep, eid, enc, mission)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-mission-compatibility",
                            pack=args.pack, strict=strict, status=rep.status,
                            record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL
              / "validate_encounter_mission_compatibility",
              "validate_encounter_mission_compatibility_report.json")
    rep.print_summary("validate-encounter-mission-compatibility")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
