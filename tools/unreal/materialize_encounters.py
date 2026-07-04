#!/usr/bin/env python3
r"""materialize_encounters.py (UE5 Python) — WorldForge v1.4 encounter live
materializer (single-boot batch driver).

Consumes the validated encounter specs written headlessly by
tools/pipeline/create_encounters.py (procedural/generated/encounters/<eid>/
encounter.json) and spawns real UE actors into each mission map — both
encounter profiles per map:

  - TargetPoint per spawn / patrol / ambush anchor, safe zone, danger-zone
    center, and resource node (label = the spec id, so anchors are greppable)
  - StaticMeshActor cube proxy per cover anchor (honest proxy: the v1.2 mesh
    catalog is metadata-only until UE .uasset materialization lands; the cube
    is a real spatial blocker at the validated position, not a fake asset)
  - TextRenderActor per hazard zone showing its visual_marker class (the
    readability cue the visual-marker requirement demands)

Every encounter's actors live under folder WF_Encounters/<encounter_id> and
carry the WF_ENC_ label prefix; a rerun removes stale WF_ENC_ actors first, so
the driver is idempotent. Writes a live-spawn report per encounter to
procedural/reports/encounters/ue_materialize/<eid>.json so downstream tooling
can flip live_spawned -> true.

Run (single boot over all 60 maps):
    UnrealEditor-Cmd <uproject> \
        -ExecutePythonScript="tools/unreal/materialize_encounters.py" \
        -unattended -nopause -nosplash -stdout
"""

import json
import sys
import traceback
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENCOUNTERS_DIR = REPO_ROOT / "procedural" / "generated" / "encounters"
CATALOG = REPO_ROOT / "procedural" / "generated" / "worldforge_encounter_catalog.json"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "encounters" / "ue_materialize"
MAP_ROOT = "/Game/WorldForge/Maps/"
LABEL_PREFIX = "WF_ENC_"
COVER_SCALE = {"low": 0.6, "half_height": 1.1, "full_height": 2.0}


def _load_encounters():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_map = defaultdict(list)
    for eid, entry in sorted((catalog.get("encounters") or {}).items()):
        p = ENCOUNTERS_DIR / eid / "encounter.json"
        enc = json.loads(p.read_text(encoding="utf-8"))
        slice_id = entry["mission_id"][len("mission_"):]
        by_map[slice_id].append(enc)
    return by_map


def _zone_center(bounds):
    lo, hi = bounds["min"], bounds["max"]
    return [(lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, 60.0]


def materialize_map(unreal, eas, slice_id, encounters):
    """Spawn both encounters' actors into one loaded map. Returns report rows."""
    # idempotency: clear stale encounter actors from any previous run.
    removed = 0
    for actor in list(eas.get_all_level_actors()):
        try:
            if actor.get_actor_label().startswith(LABEL_PREFIX):
                eas.destroy_actor(actor)
                removed += 1
        except Exception:  # noqa: BLE001 — dead weak refs during iteration
            pass

    cube = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube")
    rows = []
    for enc in encounters:
        eid = enc["encounter_id"]
        folder = "WF_Encounters/{}".format(eid)
        spawned = []

        def spawn(cls, label, pos, scale=None):
            actor = eas.spawn_actor_from_class(
                cls, unreal.Vector(pos[0], pos[1], pos[2] if len(pos) > 2 else 0.0))
            if not actor:
                return None
            actor.set_actor_label(LABEL_PREFIX + label)
            actor.set_folder_path(folder)
            if scale:
                actor.set_actor_scale3d(unreal.Vector(*scale))
            spawned.append(LABEL_PREFIX + label)
            return actor

        for key in ("spawn_anchors", "patrol_anchors", "ambush_anchors"):
            for a in enc.get(key) or []:
                spawn(unreal.TargetPoint, a["id"], a["world_position"])
        for z in enc.get("safe_zones") or []:
            spawn(unreal.TargetPoint, z["id"], z["world_position"])
        for z in enc.get("danger_zones") or []:
            spawn(unreal.TargetPoint, z["id"], _zone_center(z["bounds"]))
        for n in enc.get("resource_nodes") or []:
            if n.get("world_position"):
                spawn(unreal.TargetPoint, "{}_{}".format(eid, n["id"]),
                      n["world_position"])
        for c in enc.get("cover_anchors") or []:
            h = COVER_SCALE.get(c.get("height_class"), 1.1)
            actor = spawn(unreal.StaticMeshActor, c["id"],
                          c["world_position"], scale=(1.6, 1.6, h))
            if actor and cube:
                actor.static_mesh_component.set_static_mesh(cube)
        for hz in enc.get("hazard_zones") or []:
            actor = spawn(unreal.TextRenderActor, hz["id"],
                          _zone_center(hz["bounds"]), scale=(6.0, 6.0, 6.0))
            if actor:
                actor.text_render.set_text(unreal.Text.cast(
                    hz.get("visual_marker") or hz["hazard_type"]))

        rows.append({"encounter_id": eid, "mission_id": enc["mission_id"],
                     "map": MAP_ROOT + slice_id, "live_spawned": True,
                     "actors": spawned, "removed_stale": removed,
                     "schema_version": "wf.encounter.ue_materialize.v1"})
    return rows


def main():
    try:
        import unreal
    except ImportError:
        sys.stderr.write("ERROR: run inside the Unreal editor "
                         "(UnrealEditor-Cmd -ExecutePythonScript).\n")
        return 2

    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    by_map = _load_encounters()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    ok_maps, failed = 0, []
    for slice_id in sorted(by_map):
        map_path = MAP_ROOT + slice_id
        try:
            if not les.load_level(map_path):
                raise RuntimeError("load_level returned False")
            rows = materialize_map(unreal, eas, slice_id, by_map[slice_id])
            if not les.save_current_level():
                raise RuntimeError("save_current_level returned False")
            for row in rows:
                (REPORT_DIR / "{}.json".format(row["encounter_id"])).write_text(
                    json.dumps(row, indent=2), encoding="utf-8")
            ok_maps += 1
            unreal.log("[materialize-encounters] {} — {} encounters, {} actors".format(
                slice_id, len(rows), sum(len(r["actors"]) for r in rows)))
        except Exception as exc:  # noqa: BLE001
            failed.append((slice_id, str(exc)))
            unreal.log_error("[materialize-encounters] FAIL {}: {}\n{}".format(
                slice_id, exc, traceback.format_exc()))

    unreal.log("[materialize-encounters] DONE — {}/{} maps ok, {} failed".format(
        ok_maps, len(by_map), len(failed)))
    for slice_id, err in failed:
        unreal.log_error("  FAILED {}: {}".format(slice_id, err))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
