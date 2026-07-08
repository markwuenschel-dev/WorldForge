#!/usr/bin/env python3
"""generate_runtime_scenarios.py — WorldForge v1.6 RuntimeScenario generator (Agent 4A).

Derives one RuntimeScenario per encounter in the encounter catalog (120 = 60
missions x 2 pressure profiles), binding each to its v1.5-realized map, mission,
spawn anchor, objective verb, route plan, pawn profile, and visual kit. Every
generated scenario is validated against the frozen runtime_scenario_contract
before it is written — a generator that emits an unplayable scenario fails here,
not in the live run. Generation is deterministic: no timestamps or randomness
leak into the scenario bodies (created_at is a fixed provenance constant), so the
determinism gate is satisfied.

Usage:
    python tools/pipeline/generate_runtime_scenarios.py --pack encounter_loop_world [--strict]
Writes: procedural/generated/runtime/scenarios/<scenario_id>.json  (one per scenario)
        procedural/generated/worldforge_runtime_scenario_manifest.json
        procedural/reports/runtime/scenarios/generate_runtime_scenarios_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_scenario_contract as SC
from report_meta import build_meta, hash_obj, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

MISSION_CATALOG_REL = "procedural/generated/worldforge_mission_catalog.json"
ENCOUNTER_CATALOG_REL = "procedural/generated/worldforge_encounter_catalog.json"

# Fixed provenance stamp — generation must be deterministic (no now()).
CREATED_BY = "worldforge.v1.6.runtime_scenario_generator"
CREATED_AT = "2026-07-06T00:00:00+00:00"

# Per-archetype generation policy: objective verb event + objective sequence.
ARCHETYPE_EVENTS = {
    "disable_site": "objective.disabled",
    "recover_resource": "objective.recovered",
    "survey_landmark": "objective.surveyed",
    "clear_hazard": "objective.cleared",
    "restore_power": "objective.restored",
    "extract_cache": "objective.extracted",
}
ARCHETYPE_TAGS = {
    "disable_site": "WF_OBJ_DISABLE_TARGET",
    "recover_resource": "WF_OBJ_RECOVER_TARGET",
    "survey_landmark": "WF_OBJ_SURVEY_TARGET",
    "clear_hazard": "WF_OBJ_CLEAR_TARGET",
    "restore_power": "WF_OBJ_RESTORE_TARGET",
    "extract_cache": "WF_OBJ_EXTRACT_TARGET",
}


def state_key_for(archetype):
    return "mission.{}.completed".format(archetype)


def objective_sequence_for(archetype):
    verb = SC.MISSION_ARCHETYPE_VERBS.get(archetype, "activate")
    return ["reach_primary_poi", "{}_target".format(verb),
            "confirm_state", "extract_or_complete"]


def _stable_transform(map_id, salt=0):
    """Deterministic synthetic start transform (the live driver resolves the real
    spawn anchor; this is the authoring-side placeholder, numeric + stable)."""
    h = int(hash_obj({"m": map_id, "s": salt})[:8], 16)
    return {
        "x": float(512 + (h % 4096)),
        "y": float(512 + ((h >> 12) % 4096)),
        "z": 120.0,
        "yaw": float(h % 360),
    }


def build_scenario(enc, mission):
    archetype = enc.get("mission_archetype")
    map_id = mission.get("source_map")
    biome = enc.get("biome_family")
    profile = enc.get("encounter_profile")
    verb = SC.MISSION_ARCHETYPE_VERBS.get(archetype, "activate")
    event = ARCHETYPE_EVENTS.get(archetype, "objective.activated")
    obj_id = "{}_target".format(verb)
    runtime_id = "rt_{}__{}".format(enc.get("encounter_id"), profile)
    mission_state = [state_key_for(archetype)]
    # namespace the mission's own state keys under the objective
    for k in (mission.get("state_keys") or []):
        mission_state.append("objective.{}.{}".format(obj_id, k))
    return {
        "schema_version": SC.SCHEMA_VERSION,
        "runtime_scenario_id": runtime_id,
        "pack": enc.get("pack_id") or "encounter_loop_world",
        "map_id": map_id,
        "biome": biome,
        "mission_id": enc.get("mission_id"),
        "mission_archetype": archetype,
        "encounter_id": enc.get("encounter_id"),
        "encounter_profile": profile,
        "spawn_anchor_id": "spawn_player_primary",
        "start_transform": _stable_transform(map_id),
        "objective_sequence": objective_sequence_for(archetype),
        "required_interactions": [{
            "interaction_id": obj_id,
            "verb": verb,
            "actor_tag": ARCHETYPE_TAGS.get(archetype, "WF_OBJ_TARGET"),
            "required_radius": 175.0,
            "expected_event": event,
        }],
        "expected_state_transitions": [{
            "key": state_key_for(archetype), "from": False, "to": True}],
        "expected_completion_event": "mission.completed",
        "save_load_required": True,
        "pawn_profile_id": "wf_runtime_test_pawn_default",
        "route_plan_id": "route_{}__{}".format(map_id, archetype),
        "visual_kit_id": "visual_kit_{}_default".format(biome),
        "cover_realization_report_id": "wf.visual.cover_replacement_report.v1.latest",
        "world_state_keys": mission_state,
        "timeout_seconds": 180,
        "allowed_recovery_modes": [],
        "validation_requirements": list(SC.VALIDATION_REQUIREMENTS),
        "created_by": CREATED_BY,
        "created_at": CREATED_AT,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 runtime scenario generator.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    missions = (json.loads((REPO_ROOT / MISSION_CATALOG_REL).read_text(encoding="utf-8"))
                .get("missions") or {})
    encounters = (json.loads((REPO_ROOT / ENCOUNTER_CATALOG_REL).read_text(encoding="utf-8"))
                  .get("encounters") or {})
    if not encounters:
        rep.error("no encounters in catalog — run v1.4 create-encounters first")

    out_dir = REPO_ROOT / SC.SCENARIO_GENERATED_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": SC.SCHEMA_VERSION, "pack": args.pack, "scenarios": {}}

    n_ok = 0
    for eid in sorted(encounters.keys()):
        enc = encounters[eid]
        mission = missions.get(enc.get("mission_id") or "")
        if mission is None:
            rep.check("{}::mission_present".format(eid), False,
                      "encounter references missing mission {!r}".format(enc.get("mission_id")),
                      code=FailureCode.RUNTIME_SCENARIO_GENERATION_FAILURE)
            continue
        scen = build_scenario(enc, mission)
        # Self-validate every generated scenario against the frozen contract.
        checks = SC.validate_scenario(scen, strict=strict)
        bad = [c for c in checks if not c[1]]
        sid = scen["runtime_scenario_id"]
        rep.check("{}::valid".format(sid), not bad,
                  "generated scenario invalid: {}".format([c[0] for c in bad][:5]) if bad
                  else "scenario valid",
                  code=FailureCode.RUNTIME_SCENARIO_GENERATION_FAILURE)
        if bad:
            continue
        (out_dir / "{}.json".format(sid)).write_text(
            json.dumps(scen, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        manifest["scenarios"][sid] = {
            "map_id": scen["map_id"], "biome": scen["biome"],
            "mission_archetype": scen["mission_archetype"],
            "encounter_profile": scen["encounter_profile"],
            "mission_id": scen["mission_id"], "encounter_id": scen["encounter_id"],
        }
        n_ok += 1

    manifest["scenario_count"] = n_ok
    manifest["input_hash"] = hash_obj({"m": sorted(missions), "e": sorted(encounters)})
    (REPO_ROOT / SC.SCENARIO_MANIFEST_REL).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rep.check("scenarios_generated", n_ok == len(encounters) and n_ok > 0,
              "{}/{} scenarios generated".format(n_ok, len(encounters)),
              code=FailureCode.RUNTIME_SCENARIO_GENERATION_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="runtime-generate-scenarios", pack=args.pack, strict=strict,
                            status=rep.status, record_count=n_ok,
                            report_type="wf.runtime.scenario_manifest.v1",
                            output_manifest_hash=hash_obj(manifest),
                            extra={"scenarios_generated": n_ok,
                                   "encounters_total": len(encounters)}))
    rep.write(REPO_ROOT / SC.SCENARIO_REPORTS_REL, "generate_runtime_scenarios_report.json")
    rep.print_summary("runtime-generate-scenarios")
    print("[runtime-generate-scenarios] {}/{} scenarios generated -> {}".format(
        n_ok, len(encounters), SC.SCENARIO_GENERATED_REL))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
