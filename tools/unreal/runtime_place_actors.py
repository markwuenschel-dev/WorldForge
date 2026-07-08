"""runtime_place_actors.py (UE5 headless editor commandlet) — v1.6 P1 placement pass.

Reads a JSON job list (WF_PLACE_JOBS env var -> path) of {map_id} entries and, in
ONE headless editor process, for each map: loads it, spawns the WF_RuntimePawn
(Character, auto-possess) at the PlayerStart and the WF_Objective_V2 trigger a
fixed offset away, then saves the map. The -game runner then plays each map so the
objective's BeginPlay walks the pawn to it and completes.

Run:
  UnrealEditor-Cmd <uproject> -ExecutePythonScript=<this> -unattended -nopause -stdout
"""
import json
import os
import unreal

PAWN = "/Game/WorldForge/Runtime/BP_WF_RuntimePawn.BP_WF_RuntimePawn_C"
OBJ = "/Game/WorldForge/Runtime/BP_WF_Objective_V2.BP_WF_Objective_V2_C"
MAP_ROOT = "/Game/WorldForge/Maps/"
OFFSET_X = 900.0


def log(m):
    unreal.log("WF_PLACE " + m)


def load_class(path):
    return unreal.load_object(None, path.rsplit(".", 1)[0]).generated_class()


def place_one(map_id):
    map_path = MAP_ROOT + map_id
    if not unreal.EditorLoadingAndSavingUtils.load_map(map_path):
        log("FAIL load %s" % map_id)
        return False
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = ues.get_editor_world()
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    # find PlayerStart
    starts = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.PlayerStart)
    if starts:
        ps = starts[0].get_actor_location()
        sx, sy, sz = ps.x, ps.y, ps.z
    else:
        sx, sy, sz = 0.0, 0.0, 300.0
    # remove prior test actors
    for a in eas.get_all_level_actors():
        try:
            lbl = a.get_actor_label()
        except Exception:
            lbl = ""
        if lbl in ("WF_RT_Pawn", "WF_RT_Obj"):
            eas.destroy_actor(a)
    pawn_cls = load_class(PAWN)
    obj_cls = load_class(OBJ)
    p = eas.spawn_actor_from_class(pawn_cls, unreal.Vector(sx, sy, sz - 80.0), unreal.Rotator(0, 0, 0))
    o = eas.spawn_actor_from_class(obj_cls, unreal.Vector(sx + OFFSET_X, sy, sz - 160.0), unreal.Rotator(0, 0, 0))
    if p:
        p.set_actor_label("WF_RT_Pawn")
    if o:
        o.set_actor_label("WF_RT_Obj")
    unreal.EditorLoadingAndSavingUtils.save_map(world, map_path)
    log("OK placed %s start=%.0f,%.0f,%.0f obj=%.0f,%.0f" % (map_id, sx, sy, sz, sx + OFFSET_X, sy))
    return True


def main():
    jobs_path = os.environ.get("WF_PLACE_JOBS", "")
    if not jobs_path or not os.path.isfile(jobs_path):
        log("FATAL no WF_PLACE_JOBS file")
        return
    jobs = json.load(open(jobs_path, encoding="utf-8"))
    log("START %d jobs" % len(jobs))
    ok = 0
    for j in jobs:
        try:
            if place_one(j["map_id"]):
                ok += 1
        except Exception as e:  # noqa: BLE001
            log("EXC %s: %r" % (j.get("map_id"), e))
    log("DONE %d/%d placed" % (ok, len(jobs)))


main()
