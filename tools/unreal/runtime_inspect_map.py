"""runtime_inspect_map.py — headless map inspection for v1.6x diagnosis.

Loads WF_INSPECT_MAP in the editor and reports the facts that decide the runtime
strategy: is it World Partition, is there a Landscape / ground, where is the real
PlayerStart, where are the nav bounds, and the full loaded-actor class tally.
"""
import os
import unreal

MAP_ROOT = "/Game/WorldForge/Maps/"


def log(m):
    unreal.log("WF_INSPECT " + m)


def main():
    mid = os.environ.get("WF_INSPECT_MAP", "")
    if not mid:
        log("FATAL no WF_INSPECT_MAP")
        return
    if not unreal.EditorLoadingAndSavingUtils.load_map(MAP_ROOT + mid):
        log("FAIL load %s" % mid)
        return
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = ues.get_editor_world()
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    # World Partition?
    try:
        wp = world.get_world_partition()
        log("world_partition=%s" % ("YES" if wp else "NO"))
    except Exception as e:  # noqa: BLE001
        log("world_partition query failed: %r" % e)

    actors = eas.get_all_level_actors()
    log("loaded_actor_count=%d" % len(actors))
    tally = {}
    for a in actors:
        cn = a.get_class().get_name()
        tally[cn] = tally.get(cn, 0) + 1
    for cn in sorted(tally):
        log("  class %-40s x%d" % (cn, tally[cn]))

    for cls_name, cls in (("PlayerStart", unreal.PlayerStart),
                          ("Landscape", getattr(unreal, "Landscape", None)),
                          ("NavMeshBoundsVolume", unreal.NavMeshBoundsVolume),
                          ("RecastNavMesh", unreal.RecastNavMesh)):
        if cls is None:
            continue
        try:
            found = unreal.GameplayStatics.get_all_actors_of_class(world, cls)
        except Exception as e:  # noqa: BLE001
            log("%s lookup failed: %r" % (cls_name, e))
            continue
        for f in found:
            loc = f.get_actor_location()
            b = ""
            if cls_name == "NavMeshBoundsVolume":
                try:
                    origin, ext = f.get_actor_bounds(False)
                    b = " bounds_origin=%.0f,%.0f,%.0f ext=%.0f,%.0f,%.0f" % (
                        origin.x, origin.y, origin.z, ext.x, ext.y, ext.z)
                except Exception:
                    pass
            log("%s @ %.0f,%.0f,%.0f%s" % (cls_name, loc.x, loc.y, loc.z, b))
        if not found:
            log("%s: NONE" % cls_name)


main()
