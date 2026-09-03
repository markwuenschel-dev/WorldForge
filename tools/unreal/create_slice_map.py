#!/usr/bin/env python3
r"""
create_slice_map.py (UE5 Python) -- WorldForge slice factory, map builder.

Reads a generated slice spec JSON (from tools/pipeline/create_slice_spec.py) and
builds a real, saved, state-aware UE map for it -- no manual editor clicking:

    <map>                 created/recreated under /Game/WorldForge/Maps/<NAME>
    terrain plane         assigned the slice's terrain MI (textures show in editor)
    PCG actor             a PCGVolume running the slice's PCG graph (foliage scatter)
    region marker         a tagged actor carrying region_id + state key/before/after
    state bridge          WorldForge.SetState(before) -> MPC readback (proves the bridge)
    saved level + report

JSON only (never YAML inside a UE script; see `make pre-ue-audit`). Run headless via
biome-slice-style launch, or `make create-slice-map SPEC=...`.

Report: <output_dir>/create_map_report.json
"""

import argparse
import json
import os
import traceback

import unreal

# Region marker + linkage tags (validate_slice.py reads these back).
TAG_REGION = "wf_region"          # wf_region:<region_id>
TAG_STATE_KEY = "wf_state_key"    # wf_state_key:<key>
TAG_STATE_BEFORE = "wf_state_before"
TAG_STATE_AFTER = "wf_state_after"
TAG_SLICE = "wf_slice"            # wf_slice:<slice_id>
TAG_PCG = "wf_pcg"               # marks the PCG actor
TAG_PLACEMENT_DA = "wf_placement_da"  # wf_placement_da:<data_asset path>
TAG_TERRAIN = "wf_terrain"        # marks the ground actor

PLANE = "/Engine/BasicShapes/Plane"
PLANE_SCALE = 40.0
MPC_PATH = "/CoreTerrainMaterials/State/MPC_WorldState"
MPC_PRESSURE_PARAM = "IndustrialPressure"


def log(m):
    unreal.log("[create-slice-map] {}".format(m))


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
    return a, mesh


def build_lighting():
    """Minimal, sane editor lighting so the saved map is openable and lit."""
    sun = _spawn(unreal.DirectionalLight, unreal.Vector(0, 0, 1000), unreal.Rotator(-50, -40, 0))
    try:
        sun.set_actor_label("Sun")
        sun.light_component.set_intensity(6.0)
        sun.light_component.set_editor_property("atmosphere_sun_light", True)
    except Exception as e:
        log("sun cfg warn: {}".format(e))
    _spawn(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
    sky = _spawn(unreal.SkyLight, unreal.Vector(0, 0, 1200))
    try:
        sky.light_component.set_editor_property("real_time_capture", True)
        sky.light_component.set_editor_property("intensity", 3.0)
    except Exception as e:
        log("skylight cfg warn: {}".format(e))
    fog = _spawn(unreal.ExponentialHeightFog, unreal.Vector(0, 0, 0))
    try:
        fog.get_component().set_editor_property("fog_density", 0.01)
    except Exception:
        pass


def build_terrain(mi_path, report, terrain_forge=None):
    """Ground plane assigned the slice terrain MI. Returns (actor, assigned_path)."""
    actor, _ = _spawn_mesh(PLANE, unreal.Vector(0, 0, 0))
    actor.set_actor_label("Ground")
    actor.set_actor_scale3d(unreal.Vector(PLANE_SCALE, PLANE_SCALE, 1.0))
    tags = [TAG_TERRAIN]
    # When the slice is terrain-backed, stamp TerrainForge metadata onto the actor.
    if terrain_forge:
        tags.append("wf_terrain_forge")
        tags.append("wf_terrain_name:{}".format(terrain_forge.get("terrain_name", "")))
        tags.append("wf_terrain_recipe:{}".format(terrain_forge.get("recipe_id", "")))
        tags.append("wf_terrain_placement_mask:{}".format(terrain_forge.get("placement_mask", "")))
        tags.append("wf_terrain_nav_mask:{}".format(terrain_forge.get("nav_safe_mask", "")))
    actor.tags = tags
    mi = unreal.EditorAssetLibrary.load_asset(mi_path)
    if mi is None:
        report["errors"].append("terrain MI not found: {}".format(mi_path))
        return actor, None
    actor.static_mesh_component.set_material(0, mi)
    log("terrain MI assigned: {}".format(mi_path))
    return actor, mi_path


def measure_pcg_execution(actor, comp, report):
    """Invoke generation and MEASURE what exists afterwards. Writes report["pcg_execution"].

    Binding a graph is a wiring fact; this is the separate question of whether
    anything came out. Two deliberate choices:

    * The count is read from the WORLD, not from PCG's own bookkeeping. We sum
      instance counts over the InstancedStaticMeshComponents that exist on the
      actor after generation. A number PCG reports about itself is the same
      class of evidence as a report a pipeline writes about its own cook.
    * The UE 5.8 PCG Python surface is not assumed. Every call is tried
      defensively, exactly as the graph binding above does, and ``method``
      records which API actually worked -- so the report says HOW it knows. If
      nothing works we record generated=false and say so; we never write a
      count we did not obtain.
    """
    import datetime
    method_parts = []
    generated = False
    for call in ("generate", "generate_local"):
        try:
            getattr(comp, call)(True)
            generated = True
            method_parts.append("invoke={}".format(call))
            break
        except Exception as e:  # noqa: BLE001
            method_parts.append("invoke_failed={}({})".format(call, type(e).__name__))

    point_count = None
    instance_count = None
    if generated:
        try:
            ism_cls = getattr(unreal, "InstancedStaticMeshComponent", None)
            total = 0
            found = 0
            if ism_cls is not None:
                for c in actor.get_components_by_class(ism_cls):
                    found += 1
                    try:
                        total += int(c.get_instance_count())
                    except Exception:
                        try:
                            total += int(c.get_editor_property("instance_count"))
                        except Exception:
                            pass
            instance_count = total
            point_count = total
            method_parts.append("readback=ISM_instance_count(components={})".format(found))
        except Exception as e:  # noqa: BLE001
            method_parts.append("readback_failed={}".format(type(e).__name__))

    report["pcg_execution"] = {
        "generated": generated,
        # None, never 0, when we could not measure. A fabricated zero would read
        # as "we looked and saw none", which is a different fact.
        "point_count": point_count,
        "instance_count": instance_count,
        "method": "; ".join(method_parts) or "no generation API available",
        "measured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    log("PCG execution measured: {}".format(report["pcg_execution"]))


def build_pcg(pcg_path, da_path, report):
    """Spawn a PCG actor running the slice's PCG graph. Prefer a real PCGVolume with
    a PCGComponent bound to the graph; if PCG isn't available, fall back to a tagged
    marker so the slice still records its PCG/placement linkage. Returns kind str."""
    graph = unreal.EditorAssetLibrary.load_asset(pcg_path) if pcg_path else None
    if graph is None:
        report["warnings"].append("PCG graph not found: {}".format(pcg_path))
    pcg_actor = None
    kind = None
    # Try the real PCGVolume path.
    try:
        vol_cls = getattr(unreal, "PCGVolume", None)
        comp_cls = getattr(unreal, "PCGComponent", None)
        if vol_cls is not None:
            pcg_actor = _spawn(vol_cls, unreal.Vector(0, 0, 200))
            pcg_actor.set_actor_scale3d(unreal.Vector(PLANE_SCALE, PLANE_SCALE, 4.0))
            comp = None
            try:
                comp = pcg_actor.get_component_by_class(comp_cls) if comp_cls else None
            except Exception:
                comp = None
            if comp is None:
                try:
                    comp = pcg_actor.get_editor_property("pcg_component")
                except Exception:
                    comp = None
            if comp is not None and graph is not None:
                set_ok = False
                for setter in ("set_graph", "set_graph_interface"):
                    try:
                        getattr(comp, setter)(graph)
                        set_ok = True
                        break
                    except Exception:
                        pass
                if not set_ok:
                    for prop in ("graph", "graph_instance"):
                        try:
                            comp.set_editor_property(prop, graph)
                            set_ok = True
                            break
                        except Exception:
                            pass
                report["pcg_graph_bound"] = bool(set_ok)
                if set_ok:
                    try:
                        measure_pcg_execution(pcg_actor, comp, report)
                    except Exception as e:  # noqa: BLE001
                        report["warnings"].append(
                            "PCG execution measurement failed ({}); slice will "
                            "report WF204".format(e))
            kind = "PCGVolume"
    except Exception as e:  # noqa: BLE001
        report["warnings"].append("PCGVolume path failed ({}); using marker".format(e))
        pcg_actor = None
    if pcg_actor is None:
        # Fallback: a lightweight tagged marker representing the PCG hookup.
        pcg_actor = _spawn(unreal.TargetPoint, unreal.Vector(0, 0, 200))
        kind = "marker"
    pcg_actor.set_actor_label("WF_PCG")
    tags = [TAG_PCG]
    if pcg_path:
        tags.append("{}:{}".format("wf_pcg_graph", pcg_path))
    if da_path:
        tags.append("{}:{}".format(TAG_PLACEMENT_DA, da_path))
    pcg_actor.tags = tags
    log("PCG actor spawned ({}); graph={} da={}".format(kind, pcg_path, da_path))
    return kind


def build_region_marker(slice_id, region_id, state, report):
    """A tagged TargetPoint carrying region_id + state key/before/after so the saved
    map persistently records its state address (the runtime store is in-memory only)."""
    marker = _spawn(unreal.TargetPoint, unreal.Vector(0, 0, 50))
    marker.set_actor_label("WF_Region_{}".format(region_id))
    marker.tags = [
        "{}:{}".format(TAG_REGION, region_id),
        "{}:{}".format(TAG_SLICE, slice_id),
        "{}:{}".format(TAG_STATE_KEY, state.get("key")),
        "{}:{}".format(TAG_STATE_BEFORE, state.get("before")),
        "{}:{}".format(TAG_STATE_AFTER, state.get("after")),
    ]
    log("region marker: region={} key={}".format(region_id, state.get("key")))
    return marker


def build_player_start(report):
    """Spawn a PlayerStart so the map is immediately playable."""
    try:
        actor = _spawn(unreal.PlayerStart, unreal.Vector(0, 0, 300))
        actor.set_actor_label("PlayerStart")
        report["player_start"] = True
        log("PlayerStart spawned")
    except Exception as e:
        report["warnings"].append("PlayerStart spawn failed: {}".format(e))
        report["player_start"] = False


def build_nav_bounds(report):
    """Spawn a NavMeshBoundsVolume covering the terrain plane."""
    try:
        vol = _spawn(unreal.NavMeshBoundsVolume, unreal.Vector(0, 0, 500))
        vol.set_actor_label("NavMesh")
        vol.set_actor_scale3d(unreal.Vector(20.0, 20.0, 10.0))
        report["nav_bounds"] = True
        log("NavMeshBoundsVolume spawned")
    except Exception as e:
        report["warnings"].append("NavMeshBoundsVolume spawn failed: {}".format(e))
        report["nav_bounds"] = False


def build_poi_marker(poi_forge, report):
    poi_type = poi_forge.get("poi_type", "")
    poi_name = poi_forge.get("poi_name", "")
    descriptor_path = poi_forge.get("descriptor_path", "")
    bounds_id = poi_forge.get("bounds_id", "primary_bounds")
    primary_marker_id = poi_forge.get("primary_marker_id", "primary_poi_marker")

    actor = _spawn(unreal.TargetPoint, unreal.Vector(500, 0, 100))
    actor.set_actor_label("WF_POI_{}".format(poi_name))
    actor.tags = [
        "wf_poi_forge",
        "wf_poi_type:{}".format(poi_type),
        "wf_poi_name:{}".format(poi_name),
        "wf_poi_descriptor:{}".format(descriptor_path),
        "wf_poi_bounds:{}".format(bounds_id),
        "wf_poi_primary_marker:{}".format(primary_marker_id),
    ]
    anchors = poi_forge.get("anchors", [])
    for i, anchor in enumerate(anchors):
        anchor_id = anchor.get("id", "anchor_{}".format(i))
        offset = anchor.get("offset_cm", [0, 0, 0])
        a_actor = _spawn(unreal.TargetPoint, unreal.Vector(
            500 + offset[0] * 0.01,
            offset[1] * 0.01,
            100 + offset[2] * 0.01,
        ))
        a_actor.set_actor_label("WF_POI_Anchor_{}".format(anchor_id))
        a_actor.tags = [
            "wf_poi_anchor",
            "wf_poi_anchor_id:{}".format(anchor_id),
            "wf_poi_anchor_role:{}".format(anchor.get("role", "")),
            "wf_poi_name:{}".format(poi_name),
        ]
    report["poi_forge"] = {"poi_type": poi_type, "poi_name": poi_name, "anchors_spawned": len(anchors)}
    log("POI marker spawned: type={} name={} anchors={}".format(poi_type, poi_name, len(anchors)))


def prime_state(state, report):
    """Drive the runtime state to `before` and read the MPC back -- proves the
    SetState -> WorldStateSubsystem -> MPC bridge is alive for this slice."""
    world = _world()
    scope = state.get("scope", "Region")
    ctx = state.get("context_id")
    key = state.get("key")
    before = state.get("before", 0.0)
    try:
        unreal.SystemLibrary.execute_console_command(
            world, "WorldForge.SetState {} {} {} {}".format(scope, ctx, key, before))
        mpc = unreal.EditorAssetLibrary.load_asset(MPC_PATH)
        val = unreal.MaterialLibrary.get_scalar_parameter_value(world, mpc, MPC_PRESSURE_PARAM)
        report["mpc_readback"] = round(float(val), 4)
        report["mpc_bridge_ok"] = abs(float(val) - float(before)) < 1e-4
    except Exception as e:  # noqa: BLE001
        report["warnings"].append("state prime failed: {}".format(e))
        report["mpc_bridge_ok"] = False


def build_map_for_spec(spec, root):
    """Build + save one slice map from its spec dict. Returns the report dict.

    Factored out of main() so a single-session batch driver can materialize many
    slices without re-booting the editor per slice.
    """
    map_path = spec["map"]
    slice_id = spec["slice_id"]
    region_id = spec["region_id"]
    state = spec["state"]
    mi_path = spec["terrain"]["material_mi"]
    placement = spec.get("placement", {})
    da_path = placement.get("data_asset")
    pcg_path = placement.get("pcg_graph")
    terrain_forge = spec.get("terrain_forge")  # present only for terrain-backed slices
    out_dir = os.path.join(root, spec.get("output_dir", "procedural/reports/slices/_unsorted/" + slice_id))
    os.makedirs(out_dir, exist_ok=True)

    report = {"slice_id": slice_id, "map": map_path, "region_id": region_id,
              "errors": [], "warnings": []}
    if terrain_forge:
        report["terrain_forge"] = terrain_forge.get("terrain_name")
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(map_path):
            unreal.EditorAssetLibrary.delete_asset(map_path)
            log("removed existing map for clean rebuild: {}".format(map_path))
        if not _les().new_level(map_path):
            raise RuntimeError("new_level failed for {}".format(map_path))
        log("new level: {}".format(map_path))

        build_lighting()
        _, assigned_mi = build_terrain(mi_path, report, terrain_forge=terrain_forge)
        report["terrain_mi"] = assigned_mi
        report["pcg_kind"] = build_pcg(pcg_path, da_path, report)
        build_region_marker(slice_id, region_id, state, report)
        build_player_start(report)
        build_nav_bounds(report)
        poi_forge = spec.get("poi_forge")
        if poi_forge:
            build_poi_marker(poi_forge, report)
        prime_state(state, report)

        world = _world()
        report["editor_world"] = world.get_name() if world else None
        _les().save_current_level()
        report["saved"] = True
        report["status"] = "ok" if not report["errors"] else "error"
    except Exception as exc:  # noqa: BLE001
        report["status"] = "error"
        report["errors"].append(str(exc))
        report["traceback"] = traceback.format_exc()
        log("ERROR: {}".format(exc))

    with open(os.path.join(out_dir, "create_map_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    log("create_map_report written; status={}".format(report.get("status")))
    return report


def main():
    ap = argparse.ArgumentParser(description="Build a saved, state-aware UE map from a slice spec.")
    ap.add_argument("--spec", default=None)
    ap.add_argument("--project-root", default=".")
    args = ap.parse_args()

    # Spec resolution (UE -ExecutePythonScript can't reliably pass a path with spaces):
    #   --spec arg  ->  $WF_SLICE_SPEC  ->  fixed pointer file written by the launcher.
    root = os.path.normpath(unreal.Paths.project_dir())
    DEFAULT_SPEC_REL = "procedural/reports/slices/_active_slice_spec.json"
    chosen = args.spec or os.environ.get("WF_SLICE_SPEC") or os.path.join(root, DEFAULT_SPEC_REL)
    spec_path = chosen if os.path.isabs(chosen) else os.path.join(root, chosen)
    log("reading slice spec: {}".format(spec_path))
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    build_map_for_spec(spec, root)


if __name__ == "__main__":
    main()
