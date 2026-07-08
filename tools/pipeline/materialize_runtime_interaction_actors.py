#!/usr/bin/env python3
"""materialize_runtime_interaction_actors.py — WorldForge v1.6 InteractionForge Alpha (Agent 3A).

Materializes one RuntimeInteractionActor per mission objective across the pack:
each mission's archetype maps to a verb, a WF_* actor tag, a success event, and a
mission state key + save/load key. This is the *authoring-side* materialization
(the JSON spec the UE driver spawns as an actor); the live editor spawn is done
by tools/unreal/runtime_generate_interactions.py against these specs. Every actor
is validated against the frozen runtime_interaction_contract before write, and no
two actors may claim the same (map_id, objective_id) — a duplicate objective
actor is a real bug caught here.

Usage:
    python tools/pipeline/materialize_runtime_interaction_actors.py --pack encounter_loop_world [--strict]
Writes: procedural/generated/runtime/interactions/<interaction_actor_id>.json (one per actor)
        procedural/generated/worldforge_runtime_interaction_catalog.json
        procedural/reports/runtime/interactions/materialize_runtime_interaction_actors_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_interaction_contract as IC
from report_meta import build_meta, hash_obj, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

MISSION_CATALOG_REL = "procedural/generated/worldforge_mission_catalog.json"
CREATED_AT = "2026-07-06T00:00:00+00:00"


def _stable_transform(map_id, objective_id):
    h = int(hash_obj({"m": map_id, "o": objective_id})[:8], 16)
    return {
        "x": float(768 + (h % 4096)),
        "y": float(768 + ((h >> 12) % 4096)),
        "z": 96.0,
        "yaw": float(h % 360),
    }


def build_actor(mission):
    archetype = mission.get("mission_archetype")
    map_id = mission.get("source_map")
    verb = IC.MISSION_ARCHETYPE_VERBS.get(archetype, "activate")
    obj_id = "{}_target".format(verb)
    state_key = IC.state_key_for_archetype(archetype)
    return {
        "schema_version": IC.SCHEMA_VERSION,
        "interaction_actor_id": "int_{}__{}".format(map_id, archetype),
        "map_id": map_id,
        "mission_id": mission.get("mission_id"),
        "objective_id": obj_id,
        "actor_tag": IC.ARCHETYPE_TAGS.get(archetype, "WF_OBJ_TARGET"),
        "verb": verb,
        "display_label": "{} target".format(verb.capitalize()),
        "world_transform": _stable_transform(map_id, obj_id),
        "interaction_radius": 175.0,
        "interaction_duration_seconds": 3.0,
        "requires_line_of_sight": True,
        "requires_facing": True,
        "state_key_written": state_key,
        "event_emitted": IC.event_for_archetype(archetype) or "objective.activated",
        "completion_contribution": 1.0,
        "save_load_key": state_key,
        "collision_profile": "BlockAllDynamic",
        "visual_marker_id": "WF_MARKER_OBJECTIVE",
        "biome": mission.get("biome_family"),
        "mission_archetype": archetype,
        "created_by": "worldforge.v1.6.interaction_forge_alpha",
        "created_at": CREATED_AT,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 interaction actor materialization.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    missions = (json.loads((REPO_ROOT / MISSION_CATALOG_REL).read_text(encoding="utf-8"))
                .get("missions") or {})
    if not missions:
        rep.error("no missions in catalog")

    out_dir = REPO_ROOT / IC.INTERACTION_GENERATED_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog = {"schema_version": IC.SCHEMA_VERSION, "pack": args.pack, "interactions": {}}
    seen_objectives = {}       # (map_id, objective_id) -> actor_id  (dup guard)
    archetypes_covered = set()
    n_ok = 0

    for mid in sorted(missions):
        mission = missions[mid]
        actor = build_actor(mission)
        aid = actor["interaction_actor_id"]
        key = (actor["map_id"], actor["objective_id"])
        # Duplicate objective actor for the same objective is a hard failure.
        if key in seen_objectives:
            rep.check("{}::no_duplicate".format(aid), False,
                      "duplicate objective actor for {} (also {})".format(key, seen_objectives[key]),
                      code=C.INTERACTION_ACTOR_DUPLICATE)
            continue
        for name, ok, detail, code in IC.validate_interaction_actor(actor, strict=strict):
            rep.check("{}::{}".format(aid, name), ok, detail, code=code)
        bad = any(not ok for _, ok, _, _ in IC.validate_interaction_actor(actor, strict=strict))
        if bad:
            continue
        seen_objectives[key] = aid
        archetypes_covered.add(actor["mission_archetype"])
        (out_dir / "{}.json".format(aid)).write_text(
            json.dumps(actor, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        catalog["interactions"][aid] = {
            "map_id": actor["map_id"], "mission_id": actor["mission_id"],
            "objective_id": actor["objective_id"], "verb": actor["verb"],
            "mission_archetype": actor["mission_archetype"], "biome": actor["biome"],
        }
        n_ok += 1

    catalog["interaction_count"] = n_ok
    (REPO_ROOT / IC.INTERACTION_CATALOG_REL).write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Every one of the six archetypes must be covered by >=1 actor.
    all_verbs = set(IC.MISSION_ARCHETYPE_VERBS.keys())
    rep.check("all_six_archetypes_covered", all_verbs <= archetypes_covered,
              "missing archetypes: {}".format(sorted(all_verbs - archetypes_covered)),
              code=C.INTERACTION_ACTOR_MATERIALIZATION_FAILURE)
    rep.check("actors_materialized", n_ok == len(missions) and n_ok > 0,
              "{}/{} interaction actors materialized".format(n_ok, len(missions)),
              code=C.INTERACTION_ACTOR_MATERIALIZATION_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="runtime-interaction-actors", pack=args.pack, strict=strict,
                            status=rep.status, record_count=n_ok,
                            report_type="wf.runtime.interaction_actor_materialization.v1",
                            output_manifest_hash=hash_obj(catalog),
                            extra={"actors": n_ok, "archetypes_covered": sorted(archetypes_covered)}))
    rep.write(REPO_ROOT / IC.INTERACTION_REPORTS_REL,
              "materialize_runtime_interaction_actors_report.json")
    rep.print_summary("runtime-interaction-actors")
    print("[runtime-interaction-actors] {}/{} actors, archetypes covered: {}".format(
        n_ok, len(missions), sorted(archetypes_covered)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
