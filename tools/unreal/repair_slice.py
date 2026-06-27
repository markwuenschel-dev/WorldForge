#!/usr/bin/env python3
r"""
repair_slice.py (UE5 Python) -- WorldForge v0.5 slice repair.

Reads staged spec from procedural/reports/slices/_active_slice_spec.json,
opens the saved map, and repairs any missing required actors WITHOUT
rebuilding from scratch.

Repairs:
  terrain actor   (tag wf_terrain)
  PCG actor       (tag wf_pcg)
  region marker   (tag wf_region:<region_id>)
  PlayerStart
  NavMeshBoundsVolume

Writes: procedural/reports/slices/<biome>/<slice_id>/repair_slice_report.json
"""

import json
import os
import traceback

import unreal

TAG_REGION      = "wf_region"
TAG_STATE_KEY   = "wf_state_key"
TAG_STATE_BEFORE = "wf_state_before"
TAG_STATE_AFTER  = "wf_state_after"
TAG_SLICE       = "wf_slice"
TAG_PCG         = "wf_pcg"
TAG_PCG_GRAPH   = "wf_pcg_graph"
TAG_PLACEMENT_DA = "wf_placement_da"
TAG_TERRAIN     = "wf_terrain"

PLANE      = "/Engine/BasicShapes/Plane"
PLANE_SCALE = 40.0


def log(m):
    unreal.log("[repair-slice] {}".format(m))


def _les():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def _eas():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def _spawn(cls, loc, rot=None):
    rot = rot or unreal.Rotator(0, 0, 0)
    try:
        return _eas().spawn_actor_from_class(cls, loc, rot)
    except Exception:
        return unreal.EditorLevelLibrary.spawn_actor_from_class(cls, loc, rot)


def _spawn_mesh(mesh_path, loc, rot=None):
    mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
    rot = rot or unreal.Rotator(0, 0, 0)
    try:
        a = _eas().spawn_actor_from_object(mesh, loc, rot)
    except Exception:
        a = unreal.EditorLevelLibrary.spawn_actor_from_object(mesh, loc, rot)
    return a


def _tags(actor):
    out = []
    try:
        for t in actor.tags:
            out.append(str(t))
    except Exception:
        pass
    return out


def _has_tag(actor, name):
    return name in _tags(actor)


def _tag_value(actor, prefix):
    pfx = prefix + ":"
    for t in _tags(actor):
        if t.startswith(pfx):
            return t[len(pfx):]
    return None


def _find(actors, predicate):
    for a in actors:
        try:
            if predicate(a):
                return a
        except Exception:
            pass
    return None


def main():
    root = os.path.normpath(unreal.Paths.project_dir())
    staging = os.path.join(root, "procedural", "reports", "slices", "_active_slice_spec.json")
    log("reading spec: {}".format(staging))

    with open(staging, "r", encoding="utf-8") as f:
        spec = json.load(f)

    slice_id   = spec["slice_id"]
    biome      = spec.get("biome", "unknown")
    map_path   = spec["map"]
    region_id  = spec["region_id"]
    state      = spec["state"]
    mi_path    = spec["terrain"]["material_mi"]
    placement  = spec.get("placement", {})
    da_path    = placement.get("data_asset")
    pcg_path   = placement.get("pcg_graph")
    out_dir    = os.path.join(root, spec.get("output_dir",
                    os.path.join("procedural", "reports", "slices", biome, slice_id)))
    os.makedirs(out_dir, exist_ok=True)

    report = {
        "slice_id": slice_id,
        "map": map_path,
        "repairs": [],
        "no_change_needed": [],
        "errors": [],
        "warnings": [],
    }

    if not unreal.EditorAssetLibrary.does_asset_exist(map_path):
        report["passed"] = False
        report["status"] = "error"
        report["errors"].append("map not found: {}".format(map_path))
        with open(os.path.join(out_dir, "repair_slice_report.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        log("FAIL: map not found")
        return

    _les().load_level(map_path)
    log("map loaded: {}".format(map_path))

    actors = _eas().get_all_level_actors()
    repaired = False

    # ---- terrain actor ----
    ground = _find(actors, lambda a: _has_tag(a, TAG_TERRAIN))
    if ground is not None:
        report["no_change_needed"].append("terrain_actor")
        log("terrain_actor: OK")
    else:
        log("terrain_actor: MISSING — repairing")
        try:
            actor = _spawn_mesh(PLANE, unreal.Vector(0, 0, 0))
            actor.set_actor_label("Ground")
            actor.set_actor_scale3d(unreal.Vector(PLANE_SCALE, PLANE_SCALE, 1.0))
            actor.tags = [TAG_TERRAIN]
            mi = unreal.EditorAssetLibrary.load_asset(mi_path)
            if mi:
                actor.static_mesh_component.set_material(0, mi)
            report["repairs"].append("created_missing_terrain_actor")
            repaired = True
        except Exception as e:
            report["errors"].append("terrain repair failed: {}".format(e))

    # ---- PCG actor ----
    actors = _eas().get_all_level_actors()
    pcg = _find(actors, lambda a: _has_tag(a, TAG_PCG))
    if pcg is not None:
        report["no_change_needed"].append("pcg_actor")
        log("pcg_actor: OK")
    else:
        log("pcg_actor: MISSING — repairing")
        try:
            graph = unreal.EditorAssetLibrary.load_asset(pcg_path) if pcg_path else None
            pcg_actor = None
            vol_cls = getattr(unreal, "PCGVolume", None)
            if vol_cls:
                try:
                    pcg_actor = _spawn(vol_cls, unreal.Vector(0, 0, 200))
                    pcg_actor.set_actor_scale3d(unreal.Vector(PLANE_SCALE, PLANE_SCALE, 4.0))
                    comp_cls = getattr(unreal, "PCGComponent", None)
                    if comp_cls and graph:
                        comp = None
                        try:
                            comp = pcg_actor.get_component_by_class(comp_cls)
                        except Exception:
                            pass
                        if comp:
                            for setter in ("set_graph", "set_graph_interface"):
                                try:
                                    getattr(comp, setter)(graph)
                                    break
                                except Exception:
                                    pass
                except Exception as e:
                    report["warnings"].append("PCGVolume spawn failed: {}".format(e))
                    pcg_actor = None
            if pcg_actor is None:
                pcg_actor = _spawn(unreal.TargetPoint, unreal.Vector(0, 0, 200))
            pcg_actor.set_actor_label("WF_PCG")
            tags = [TAG_PCG]
            if pcg_path:
                tags.append("{}:{}".format(TAG_PCG_GRAPH, pcg_path))
            if da_path:
                tags.append("{}:{}".format(TAG_PLACEMENT_DA, da_path))
            pcg_actor.tags = tags
            report["repairs"].append("created_missing_pcg_actor")
            repaired = True
        except Exception as e:
            report["errors"].append("PCG repair failed: {}".format(e))

    # ---- region marker ----
    actors = _eas().get_all_level_actors()
    marker = _find(actors, lambda a: _tag_value(a, TAG_REGION) == region_id)
    if marker is not None:
        report["no_change_needed"].append("region_marker")
        log("region_marker: OK")
    else:
        log("region_marker: MISSING — repairing")
        try:
            m = _spawn(unreal.TargetPoint, unreal.Vector(0, 0, 50))
            m.set_actor_label("WF_Region_{}".format(region_id))
            m.tags = [
                "{}:{}".format(TAG_REGION, region_id),
                "{}:{}".format(TAG_SLICE, slice_id),
                "{}:{}".format(TAG_STATE_KEY, state.get("key")),
                "{}:{}".format(TAG_STATE_BEFORE, state.get("before")),
                "{}:{}".format(TAG_STATE_AFTER, state.get("after")),
            ]
            report["repairs"].append("created_missing_region_marker")
            repaired = True
        except Exception as e:
            report["errors"].append("region marker repair failed: {}".format(e))

    # ---- PlayerStart ----
    actors = _eas().get_all_level_actors()
    ps = _find(actors, lambda a: isinstance(a, unreal.PlayerStart))
    if ps is not None:
        report["no_change_needed"].append("player_start")
        log("player_start: OK")
    else:
        log("player_start: MISSING — repairing")
        try:
            actor = _spawn(unreal.PlayerStart, unreal.Vector(0, 0, 300))
            actor.set_actor_label("PlayerStart")
            report["repairs"].append("created_missing_player_start")
            repaired = True
        except Exception as e:
            report["warnings"].append("PlayerStart repair failed: {}".format(e))

    # ---- NavMeshBoundsVolume ----
    actors = _eas().get_all_level_actors()
    nav = _find(actors, lambda a: isinstance(a, unreal.NavMeshBoundsVolume))
    if nav is not None:
        report["no_change_needed"].append("nav_bounds")
        log("nav_bounds: OK")
    else:
        log("nav_bounds: MISSING — repairing")
        try:
            vol = _spawn(unreal.NavMeshBoundsVolume, unreal.Vector(0, 0, 500))
            vol.set_actor_label("NavMesh")
            vol.set_actor_scale3d(unreal.Vector(20.0, 20.0, 10.0))
            report["repairs"].append("created_missing_nav_bounds")
            repaired = True
        except Exception as e:
            report["warnings"].append("NavMeshBoundsVolume repair failed: {}".format(e))

    if repaired:
        _les().save_current_level()
        log("level saved after repairs")

    report["passed"] = len(report["errors"]) == 0
    report["status"] = "ok" if report["passed"] else "error"

    report_path = os.path.join(out_dir, "repair_slice_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    verdict = "PASS" if report["passed"] else "FAIL"
    log("repair_slice: {} — {} repairs, {} errors".format(
        verdict, len(report["repairs"]), len(report["errors"])))
    for r in report["repairs"]:
        log("  repaired: {}".format(r))


if __name__ == "__main__":
    main()
