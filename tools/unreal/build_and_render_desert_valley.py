#!/usr/bin/env python3
r"""
build_and_render_desert_valley.py (UE5 Python)

Desert Industrialized Slice -- the RENDERED before/after proof (PlacementForge D13).
Builds the smallest renderable Desert_Valley_01 map and captures two screenshots:

    industrial_pressure = 0.0   -> clean desert   (state_0_00.png)
    industrial_pressure = 0.75  -> industrialized  (state_0_75.png)

What it proves visually:
  * TERRAIN reacts: the ground uses MI_Terrain_Rock_Desert_01, whose parent is the
    soot-wired M_Terrain_Master. Driving MPC_WorldState.IndustrialPressure (through the
    REAL path -- WorldForge.SetState console cmd -> WorldStateSubsystem -> MPC) lerps the
    ground toward soot.
  * FOLIAGE density reacts: placeholder foliage (engine basic shapes -- the real meshes
    live in the consuming game project) is scattered at counts derived from the
    PlacementRulesDataAsset response curve: count = effective_density * AREA_100M2,
    where effective_density = base * lerp(d0, d1, state). Clean = lush grass/trees +
    little scrub; industrial = sparse grass/trees + dead scrub takes over.

Rendering is headless via SceneCapture2D -> TextureRenderTarget2D -> export_render_target
(synchronous, no PIE). Run WITHOUT -NullRHI (needs a real RHI to render).

Outputs:
    procedural/reports/slices/desert_industrialized/screenshots/state_0_00.png
    procedural/reports/slices/desert_industrialized/screenshots/state_0_75.png
    procedural/reports/slices/desert_industrialized/render_report.json
"""

import json
import math
import os
import random
import traceback

import unreal

MAP_PATH = "/Game/Maps/Desert_Valley_01"
TERRAIN_MI = "/Game/Materials/Terrain/MI_Terrain_Rock_Desert_01"
DA_PATH = "/Game/Procedural/Placement/DA_ReclaimedDesert_Foliage"
GRAY_MAT = "/Engine/BasicShapes/BasicShapeMaterial"
PLANE = "/Engine/BasicShapes/Plane"

SCOPE = "Region"
CONTEXT_ID = "Desert_Valley_01"
DRIVING_KEY = "industrial_pressure"
STATES = [0.0, 0.75]

# Plane: engine Plane is 100uu; scale 40 -> 4000uu = 40 m square = 16 * (100 m^2).
PLANE_SCALE = 40.0
HALF = PLANE_SCALE * 100.0 / 2.0          # 2000 uu
SCATTER_HALF = HALF - 150.0
AREA_100M2 = (PLANE_SCALE * PLANE_SCALE * 100.0 * 100.0) / (100.0 * 1e4)  # = 16.0
RES_X, RES_Y = 1600, 900
SEED = 424242

# species id -> (engine shape, uniform xy scale, z scale, placeholder color RGB)
SHAPES = {
    "reclaimed_grass": ("/Engine/BasicShapes/Cylinder", 0.12, 0.45, (0.09, 0.42, 0.10)),  # live green
    "young_tree":      ("/Engine/BasicShapes/Cone",     0.55, 0.90, (0.05, 0.30, 0.07)),  # darker green
    "dead_scrub":      ("/Engine/BasicShapes/Cube",     0.22, 0.22, (0.34, 0.22, 0.09)),  # dead brown
}
VEG_DIR = "/Game/Maps/DesertValley"

# When driven by `make biome-slice`, the orchestrator writes a resolved JSON
# spec here (JSON only -- never YAML inside a UE script; see pre-ue-audit).
# Standalone runs find no file and fall back to the proven desert defaults
# above, preserving the original D13 behaviour.
ACTIVE_SLICE_REL = "procedural/reports/slices/_active_slice.json"
SLUG = "desert_industrialized"


def log(m):
    unreal.log("[desert_valley] {}".format(m))


def _load_active_slice(root):
    """Return the resolved slice spec dict, or {} when run standalone."""
    path = os.path.join(root, ACTIVE_SLICE_REL)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            spec = json.load(f)
        log("active slice: {} ({})".format(spec.get("slug"), path))
        return spec
    except Exception as e:  # noqa: BLE001
        log("active slice load failed ({}); using defaults: {}".format(path, e))
        return {}


def _apply_slice(spec):
    """Override module-level constants from a slice spec (no-op if empty)."""
    global MAP_PATH, TERRAIN_MI, DA_PATH, SCOPE, CONTEXT_ID, DRIVING_KEY
    global STATES, RES_X, RES_Y, SEED, SLUG
    if not spec:
        return
    MAP_PATH = spec.get("map", MAP_PATH)
    TERRAIN_MI = spec.get("terrain_mi", TERRAIN_MI)
    DA_PATH = spec.get("placement_data_asset", DA_PATH)
    st = spec.get("state", {})
    SCOPE = st.get("scope", SCOPE)
    CONTEXT_ID = st.get("context_id", CONTEXT_ID)
    DRIVING_KEY = st.get("key", DRIVING_KEY)
    STATES = spec.get("states", STATES)
    res = spec.get("resolution") or [RES_X, RES_Y]
    RES_X, RES_Y = int(res[0]), int(res[1])
    SEED = int(spec.get("seed", SEED))
    SLUG = spec.get("slug", SLUG)


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
    sun = _spawn(unreal.DirectionalLight, unreal.Vector(0, 0, 1000),
                 unreal.Rotator(-55, -40, 0))
    try:
        sun.set_actor_label("Sun")
        # Manual exposure ignores exposure bias here, so terrain tone is driven by
        # light intensity. This lands the desert at tan (not blown white); the unlit
        # foliage is independent of these lights.
        sun.light_component.set_intensity(11.0)
        sun.light_component.set_editor_property("atmosphere_sun_light", True)
    except Exception as e:
        log("sun cfg warn: {}".format(e))

    # Shadowless fill aligned with the camera view so the foliage faces we actually
    # see read as green/brown instead of black -- headless capture has ~no skylight
    # ambient to fill the sun-shadowed sides.
    fill_rot = unreal.MathLibrary.find_look_at_rotation(
        unreal.Vector(1700, -1700, 1150), unreal.Vector(0, 0, 0))
    fill = _spawn(unreal.DirectionalLight, unreal.Vector(0, 0, 1000), fill_rot)
    try:
        fill.set_actor_label("Fill")
        fill.light_component.set_intensity(4.0)
        fill.light_component.set_editor_property("atmosphere_sun_light", False)
        fill.light_component.set_editor_property("cast_shadows", False)
    except Exception as e:
        log("fill cfg warn: {}".format(e))

    _spawn(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))

    sky = _spawn(unreal.SkyLight, unreal.Vector(0, 0, 1200))
    try:
        sky.light_component.set_editor_property("real_time_capture", True)
        sky.light_component.set_editor_property("intensity", 6.0)
        # Lower hemisphere isn't solid black, so shadowed ground keeps some fill
        # even when the real-time capture is weak in a headless commandlet.
        try:
            sky.light_component.set_editor_property("lower_hemisphere_is_black", False)
        except Exception as e:
            log("skylight lower-hemi warn: {}".format(e))
    except Exception as e:
        log("skylight cfg warn: {}".format(e))

    fog = _spawn(unreal.ExponentialHeightFog, unreal.Vector(0, 0, 0))
    try:
        fog.get_component().set_editor_property("fog_density", 0.01)
    except Exception:
        pass
    return sky


def build_terrain():
    actor, _ = _spawn_mesh(PLANE, unreal.Vector(0, 0, 0))
    actor.set_actor_label("Ground")
    actor.set_actor_scale3d(unreal.Vector(PLANE_SCALE, PLANE_SCALE, 1.0))
    mi = unreal.EditorAssetLibrary.load_asset(TERRAIN_MI)
    smc = actor.static_mesh_component
    smc.set_material(0, mi)
    return actor


def read_species():
    da = unreal.EditorAssetLibrary.load_asset(DA_PATH)
    out = []
    for r in da.get_editor_property("species"):
        out.append({
            "id": str(r.get_editor_property("species_id")),
            "base": float(r.get_editor_property("base_density")),
            "d0": float(r.get_editor_property("density_at_state_zero")),
            "d1": float(r.get_editor_property("density_at_state_one")),
            "smin": float(r.get_editor_property("scale_min")),
            "smax": float(r.get_editor_property("scale_max")),
        })
    return out


def build_veg_materials():
    """Create one lit color material + a constant instance per species so the
    placeholder foliage reads as live-green vs dead-brown. Falls back to the engine
    gray material if creation fails."""
    at = unreal.AssetToolsHelpers.get_asset_tools()
    mats = {}
    try:
        base_path = VEG_DIR + "/M_WF_Veg"
        # Always rebuild from scratch: a committed/older asset may have unwired base
        # color (renders black), and the existence-guard would skip re-wiring it.
        # Delete the material AND its instances so parent links stay valid.
        for p in [base_path] + [VEG_DIR + "/MI_WF_Veg_" + s for s in SHAPES]:
            if unreal.EditorAssetLibrary.does_asset_exist(p):
                unreal.EditorAssetLibrary.delete_asset(p)

        base = at.create_asset("M_WF_Veg", VEG_DIR, unreal.Material, unreal.MaterialFactoryNew())
        # Unlit so the flat species color always reads (green vs brown), independent
        # of sun angle/shadowing -- these are placeholder proxies, not lit geometry.
        try:
            base.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
        except Exception as e:
            log("veg shading_model warn: {}".format(e))
        vp = unreal.MaterialEditingLibrary.create_material_expression(
            base, unreal.MaterialExpressionVectorParameter, -400, 0)
        vp.set_editor_property("parameter_name", "Color")
        vp.set_editor_property("default_value", unreal.LinearColor(0.2, 0.2, 0.2, 1.0))
        # Unlit reads emissive as the final color.
        unreal.MaterialEditingLibrary.connect_material_property(vp, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
        unreal.MaterialEditingLibrary.recompile_material(base)
        unreal.EditorAssetLibrary.save_loaded_asset(base)

        for sid, cfg in SHAPES.items():
            r, g, b = cfg[3]
            mic_name = "MI_WF_Veg_" + sid
            mic = at.create_asset(mic_name, VEG_DIR, unreal.MaterialInstanceConstant,
                                  unreal.MaterialInstanceConstantFactoryNew())
            mic.set_editor_property("parent", base)
            unreal.MaterialEditingLibrary.set_material_instance_vector_parameter_value(
                mic, "Color", unreal.LinearColor(r, g, b, 1.0))
            unreal.EditorAssetLibrary.save_loaded_asset(mic)
            mats[sid] = mic
    except Exception as e:
        log("veg material build failed ({}); using gray".format(e))
    return mats


def clear_foliage():
    for a in _eas().get_all_level_actors():
        try:
            if a.actor_has_tag("wf_foliage"):
                _eas().destroy_actor(a)
        except Exception:
            pass


def scatter(species, state, rng, veg_mats):
    """Spawn placeholder foliage actors for `state`; returns per-species counts."""
    clear_foliage()
    counts = {}
    gray = unreal.EditorAssetLibrary.load_asset(GRAY_MAT)
    for sp in species:
        eff = sp["base"] * (sp["d0"] + (sp["d1"] - sp["d0"]) * state)
        n = int(round(eff * AREA_100M2))
        counts[sp["id"]] = {"effective_density": round(eff, 4), "instances": n}
        cfg = SHAPES.get(sp["id"], ("/Engine/BasicShapes/Cube", 0.25, 0.25, (0.3, 0.3, 0.3)))
        shape, sxy, sz = cfg[0], cfg[1], cfg[2]
        mat = veg_mats.get(sp["id"], gray)
        for _ in range(n):
            x = rng.uniform(-SCATTER_HALF, SCATTER_HALF)
            y = rng.uniform(-SCATTER_HALF, SCATTER_HALF)
            s = rng.uniform(sp["smin"], sp["smax"])
            a, _m = _spawn_mesh(shape, unreal.Vector(x, y, 0))
            a.set_actor_scale3d(unreal.Vector(sxy * s, sxy * s, sz * s))
            # lift so the base sits on the ground (~50uu tall mesh half-height * z-scale)
            a.set_actor_location(unreal.Vector(x, y, 50.0 * sz * s), False, False)
            a.tags = ["wf_foliage"]
            a.static_mesh_component.set_material(0, mat)
    return counts


def _configure_exposure(comp):
    """Single-shot SceneCapture has no eye-adaptation history, so auto-exposure renders
    dark. Lock exposure to a fixed average (min==max) so the frame is deterministically
    exposed regardless of adaptation."""
    pp = comp.get_editor_property("post_process_settings")
    fields = {
        "auto_exposure_method": unreal.AutoExposureMethod.AEM_MANUAL,
        "auto_exposure_min_brightness": 1.0,
        "auto_exposure_max_brightness": 1.0,
        # Headless capture has no real-time skylight ambient, so the scene is lit
        # almost entirely by the (boosted) directional sun. A moderate boost lands the
        # terrain at desert-tan (not muddy, not blown white) so the soot lerp still
        # reads; the unlit emissive foliage stays saturated at this level. +1 EV ~= 2x.
        "auto_exposure_bias": 1.5,
        "override_auto_exposure_method": True,
        "override_auto_exposure_min_brightness": True,
        "override_auto_exposure_max_brightness": True,
        "override_auto_exposure_bias": True,
    }
    for k, v in fields.items():
        try:
            pp.set_editor_property(k, v)
        except Exception as e:
            log("pp set {} warn: {}".format(k, e))
    comp.set_editor_property("post_process_settings", pp)


def make_capture(rt):
    cap = _spawn(unreal.SceneCapture2D, unreal.Vector(0, 0, 0))
    cap.set_actor_label("WF_Capture")
    comp = cap.capture_component2d
    comp.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
    comp.set_editor_property("texture_target", rt)
    comp.set_editor_property("capture_every_frame", False)
    comp.set_editor_property("capture_on_movement", False)
    _configure_exposure(comp)
    return cap, comp


def position_view(cap_actor, fov=65.0):
    loc = unreal.Vector(1700, -1700, 1150)
    target = unreal.Vector(0, 0, 0)
    rot = unreal.MathLibrary.find_look_at_rotation(loc, target)
    cap_actor.set_actor_location_and_rotation(loc, rot, False, False)
    try:
        cap_actor.capture_component2d.set_editor_property("fov_angle", fov)
    except Exception:
        pass
    # A matching CineCamera so the saved map has a usable viewpoint too.
    cam = _spawn(unreal.CineCameraActor, loc, rot)
    cam.set_actor_label("Cam_BeforeAfter")
    return rot


def main():
    root = os.path.normpath(unreal.Paths.project_dir())
    _apply_slice(_load_active_slice(root))
    random.seed(SEED)
    rng = random.Random(SEED)
    rel_shot = "procedural/reports/slices/{}/screenshots".format(SLUG)
    shot_dir = os.path.join(root, rel_shot)
    os.makedirs(shot_dir, exist_ok=True)

    report = {"map": MAP_PATH, "states": STATES, "steps": [], "errors": []}
    try:
        # Fresh level every run for determinism. The proof map may already exist
        # (committed from a prior run); delete it first so new_level can recreate it
        # clean -- otherwise new_level silently refuses and we'd composite into the
        # editor's startup world (wrong lighting) and can't save.
        if unreal.EditorAssetLibrary.does_asset_exist(MAP_PATH):
            unreal.EditorAssetLibrary.delete_asset(MAP_PATH)
            log("removed existing map for fresh rebuild: {}".format(MAP_PATH))
        if not _les().new_level(MAP_PATH):
            raise RuntimeError("new_level failed for {} (asset still present?)".format(MAP_PATH))
        log("new level: {}".format(MAP_PATH))

        build_lighting()
        build_terrain()
        position_capture = None

        rt = unreal.TextureRenderTarget2D()
        rt.set_editor_property("size_x", RES_X)
        rt.set_editor_property("size_y", RES_Y)
        rt.set_editor_property("render_target_format", unreal.TextureRenderTargetFormat.RTF_RGBA8)
        try:
            rt.update_resource()
        except Exception as e:
            log("rt.update_resource warn: {}".format(e))
        cap_actor, cap_comp = make_capture(rt)
        position_view(cap_actor)

        species = read_species()
        report["species_rules"] = species
        veg_mats = build_veg_materials()
        report["veg_materials"] = sorted(veg_mats.keys())
        world = _world()
        report["editor_world"] = world.get_name() if world else None

        # Prime the renderer: in a non-ticking commandlet the real-time skylight
        # cubemap starts black, so a single cold capture renders dark. Trigger the
        # skylight recapture and run several throwaway captures so ambient lighting
        # (and material shaders) converge before any export.
        unreal.SystemLibrary.execute_console_command(world, "r.SkyLight.RealTimeReflectionCapture 1")
        for _ in range(6):
            cap_comp.capture_scene()

        for state in STATES:
            cmd = "WorldForge.SetState {} {} {} {}".format(SCOPE, CONTEXT_ID, DRIVING_KEY, state)
            unreal.SystemLibrary.execute_console_command(world, cmd)
            mpc = unreal.EditorAssetLibrary.load_asset("/CoreTerrainMaterials/State/MPC_WorldState")
            mpc_val = unreal.MaterialLibrary.get_scalar_parameter_value(world, mpc, "IndustrialPressure")

            counts = scatter(species, state, rng, veg_mats)

            # Recapture skylight for this state's ground, then settle with a few
            # captures so the real-time skylight + soot material fully converge
            # before exporting the frame.
            unreal.SystemLibrary.execute_console_command(world, "r.SkyLight.RealTimeReflectionCapture 1")
            for _ in range(3):
                cap_comp.capture_scene()

            fname = "state_{}.png".format("{:.2f}".format(state).replace(".", "_"))
            unreal.RenderingLibrary.export_render_target(world, rt, shot_dir, fname)

            step = {
                "set_value": state,
                "mpc_readback": round(mpc_val, 4),
                "mpc_matches_set": abs(mpc_val - state) < 1e-4,
                "foliage": counts,
                "screenshot": os.path.join(rel_shot, fname),
            }
            report["steps"].append(step)
            log("state {} -> MPC {} -> {}".format(state, step["mpc_readback"], fname))

        # Leave the map in the clean state and save it.
        unreal.SystemLibrary.execute_console_command(
            world, "WorldForge.SetState {} {} {} 0.0".format(SCOPE, CONTEXT_ID, DRIVING_KEY))
        scatter(species, 0.0, rng, veg_mats)
        _les().save_current_level()
        report["status"] = "ok"
    except Exception as exc:  # noqa: BLE001
        report["status"] = "error"
        report["errors"].append(str(exc))
        report["traceback"] = traceback.format_exc()
        log("ERROR: {}".format(exc))

    with open(os.path.join(os.path.dirname(shot_dir), "render_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    log("render_report written; status={}".format(report.get("status")))


if __name__ == "__main__":
    main()
