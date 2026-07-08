"""runtime_headless_prepare.py (UE5 headless editor commandlet) — WorldForge v1.6x.

Prepares maps for the headless `-game` runtime batch. In ONE editor process it
walks a job list of map_ids (WF_PREP_MAPS -> path to a JSON list, or a single
WF_PREP_MAP) and, per map:

  1. loads the map,
  2. removes any prior WF_RT_* test actors (idempotent re-prepare),
  3. spawns the C++ runtime classes at the real PlayerStart:
       - AWFRuntimeTestPawn  (gravity-free flight, auto-possess Player0)
       - AWFRuntimeObjective (BeginPlay marker; on arrival: save + reload-verify
                              + mission.completed + graceful exit),
  4. saves the map.

The v1.6x runtime completion needs NO navmesh: the pawn reaches the objective by
continuous per-tick flight (not a teleport), which standalone `-game` can run
even though it never builds a navmesh. The `-game` runner boots each prepared map
in a fresh crash-isolated process; the orchestrator reads the WF_* markers the
C++ logs to WorldForge.log.

Run:
  UnrealEditor-Cmd <uproject> -ExecutePythonScript=<this> -unattended -nopause -stdout -nosplash
"""
import json
import os
import unreal

MAP_ROOT = "/Game/WorldForge/Maps/"
OFFSET_X = 900.0
TEST_LABELS = ("WF_RT_Pawn", "WF_RT_Obj", "WF_RT_Verifier")


def log(m):
    unreal.log("WF_PREP " + m)


def prepare_one(map_id):
    map_path = MAP_ROOT + map_id
    if not unreal.EditorLoadingAndSavingUtils.load_map(map_path):
        log("FAIL load %s" % map_id)
        return False
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = ues.get_editor_world()
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    starts = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.PlayerStart)
    if starts:
        ps = starts[0].get_actor_location()
        sx, sy, sz = ps.x, ps.y, ps.z
    else:
        sx, sy, sz = 0.0, 0.0, 300.0

    for a in eas.get_all_level_actors():
        try:
            lbl = a.get_actor_label()
        except Exception:
            lbl = ""
        if lbl in TEST_LABELS:
            eas.destroy_actor(a)

    pawn_cls = unreal.WFRuntimeTestPawn
    obj_cls = unreal.WFRuntimeObjective

    p = eas.spawn_actor_from_class(pawn_cls, unreal.Vector(sx, sy, sz), unreal.Rotator(0, 0, 0))
    o = eas.spawn_actor_from_class(obj_cls, unreal.Vector(sx + OFFSET_X, sy, sz), unreal.Rotator(0, 0, 0))
    if p:
        p.set_actor_label("WF_RT_Pawn")
    if o:
        o.set_actor_label("WF_RT_Obj")
        try:
            o.set_editor_property("scenario_id", map_id)
            o.set_editor_property("reach_radius", 250.0)
        except Exception as e:  # noqa: BLE001
            log("WARN could not set objective props: %r" % e)

    unreal.EditorLoadingAndSavingUtils.save_map(world, map_path)
    log("OK prepared %s start=%.0f,%.0f,%.0f obj=%.0f,%.0f pawn=%s obj=%s" % (
        map_id, sx, sy, sz, sx + OFFSET_X, sy, "ok" if p else "FAIL", "ok" if o else "FAIL"))
    return True


def main():
    single = os.environ.get("WF_PREP_MAP", "")
    jobs_path = os.environ.get("WF_PREP_MAPS", "")
    if single:
        map_ids = [single]
    elif jobs_path and os.path.isfile(jobs_path):
        map_ids = json.load(open(jobs_path, encoding="utf-8"))
    else:
        log("FATAL no WF_PREP_MAP or WF_PREP_MAPS file")
        return
    log("START %d maps" % len(map_ids))
    ok = 0
    for mid in map_ids:
        try:
            if prepare_one(mid):
                ok += 1
        except Exception as e:  # noqa: BLE001
            log("EXC %s: %r" % (mid, e))
    log("DONE %d/%d prepared" % (ok, len(map_ids)))


main()
