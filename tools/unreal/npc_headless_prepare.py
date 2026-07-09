"""npc_headless_prepare.py (UE5 headless editor commandlet) — WorldForge v1.7 Wave R.

Prepares maps for the headless NPC behavior batch. In ONE editor process it walks a
job list of map_ids (WF_PREP_MAPS -> path to a JSON list, or a single WF_PREP_MAP)
and, per map:

  1. loads the map,
  2. removes any prior WF_RT_* / WF_NPC_* test actors (idempotent re-prepare),
  3. spawns the runtime classes the NPC behavior scenario needs:
       - AWFGroundedRuntimePawn  (the grounded player pawn — walks to the objective;
                                  mission completion preserved, from v1.6y),
       - AWFRuntimeObjective     (mission objective — save + reload-verify + exit),
       - AWFEncounterManager     (spawns grounded AWFNPCPawn sentries, runs real
                                  perception/pressure, persists NPC state),
  4. saves the map.

The per-scenario NPC spec (count / pressure profile / radii) is supplied at RUN time
via environment variables the manager reads in BeginPlay — so a map is prepared once
and drives BOTH pressure profiles without re-preparation. Maps are restored clean in
git afterwards; prepare is a required idempotent pipeline step (same policy as v1.6x).

Run:
  UnrealEditor-Cmd <uproject> -ExecutePythonScript=<this> -unattended -nopause -stdout -nosplash
"""
import json
import os
import unreal

MAP_ROOT = "/Game/WorldForge/Maps/"
OFFSET_X = 900.0
TEST_LABELS = ("WF_RT_Pawn", "WF_RT_Obj", "WF_RT_Verifier", "WF_NPC_Mgr")


def log(m):
    unreal.log("WF_NPCPREP " + m)


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

    # Grounded player pawn (walks to objective) + objective + NPC encounter manager.
    p = eas.spawn_actor_from_class(unreal.WFGroundedRuntimePawn,
                                   unreal.Vector(sx, sy, sz), unreal.Rotator(0, 0, 0))
    o = eas.spawn_actor_from_class(unreal.WFRuntimeObjective,
                                   unreal.Vector(sx + OFFSET_X, sy, sz), unreal.Rotator(0, 0, 0))
    mgr = eas.spawn_actor_from_class(unreal.WFEncounterManager,
                                     unreal.Vector(sx, sy, sz), unreal.Rotator(0, 0, 0))
    if p:
        p.set_actor_label("WF_RT_Pawn")
    if o:
        o.set_actor_label("WF_RT_Obj")
        try:
            o.set_editor_property("scenario_id", map_id)
            o.set_editor_property("reach_radius", 250.0)
        except Exception as e:  # noqa: BLE001
            log("WARN could not set objective props: %r" % e)
    if mgr:
        mgr.set_actor_label("WF_NPC_Mgr")
        try:
            mgr.set_editor_property("scenario_id", map_id)
            mgr.set_editor_property("default_npc_count", 3)
        except Exception as e:  # noqa: BLE001
            log("WARN could not set manager props: %r" % e)

    unreal.EditorLoadingAndSavingUtils.save_map(world, map_path)
    log("OK prepared %s start=%.0f,%.0f,%.0f pawn=%s obj=%s mgr=%s" % (
        map_id, sx, sy, sz, "ok" if p else "FAIL", "ok" if o else "FAIL", "ok" if mgr else "FAIL"))
    return bool(p and o and mgr)


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
