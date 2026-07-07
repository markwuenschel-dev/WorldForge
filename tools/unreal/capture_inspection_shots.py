#!/usr/bin/env python3
r"""capture_inspection_shots.py (UE5 Python) — WorldForge v1.5 Wave-3
(single-boot batch driver).

Captures one inspection screenshot per biome (>= 5) so the materialized worlds
can be eyeballed. For each biome it picks one representative already-saved map,
loads it (the map already carries its WF_ environment/weather/encounter/cover
actors), drops in a headless SceneCapture2D -> TextureRenderTarget2D rig with
locked exposure and skylight priming — the SAME capture path proven in
build_and_render_desert_valley.py — aims it at the encounter camera anchor, and
exports a PNG to Saved/WorldForge/InspectionShots/.

TICKET-001 (docs/tickets/): the headless SceneCapture path renders
MaterialInstanceConstant TEXTURE-parameter overrides near-white; scalar / vector
/ MPC params are fine. Terrain that relies on MIC texture overrides may therefore
read washed-out in these shots — recorded in the report; a real material capture
needs PIE / -game. Shots are captured non-destructively (the capture actor is
removed and the level is NOT saved).

Report:
    procedural/reports/visual/capture_inspection_shots/
        capture_inspection_shots_report.json
    per shot: {map_id, biome, mission, encounter, camera_anchor,
               screenshot_path, visual_kit_id, materialized_asset_counts,
               validation_status}

Run (inside the UE 5.7 editor, real RHI — do NOT pass -NullRHI):
    "<UE>/UnrealEditor-Cmd.exe" "D:/Unreal Projects/WorldForge/WorldForge.uproject" ^
        -ExecutePythonScript="tools/unreal/capture_inspection_shots.py" ^
        -unattended -nopause -nosplash -stdout
"""

import json
import os
import sys
import traceback
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RIG_DIR = REPO_ROOT / "procedural" / "generated" / "visual" / "environment_rigs"
KITS_DIR = REPO_ROOT / "procedural" / "generated" / "visual" / "kits"
ENCOUNTERS_DIR = REPO_ROOT / "procedural" / "generated" / "encounters"
ENCOUNTER_CATALOG = REPO_ROOT / "procedural" / "generated" / "worldforge_encounter_catalog.json"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "visual" / "capture_inspection_shots"
REPORT_NAME = "capture_inspection_shots_report.json"
MAP_ROOT = "/Game/WorldForge/Maps/"
SHOT_REL = os.path.join("Saved", "WorldForge", "InspectionShots")
RES_X, RES_Y = 1600, 900
TICKET_001 = ("TICKET-001: headless SceneCapture renders MIC texture-param "
              "overrides near-white (scalar/vector/MPC fine); use PIE/-game for "
              "true material capture.")
SCHEMA_VERSION = "wf.visual.capture_inspection_shots.v1"


def _pick_maps_by_biome():
    """biome -> representative slice_id (first, deterministic by name)."""
    by_biome = defaultdict(list)
    if RIG_DIR.is_dir():
        for p in sorted(RIG_DIR.glob("*.json")):
            try:
                rig = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            b = rig.get("biome")
            sid = rig.get("slice_id") or p.stem
            if b:
                by_biome[b].append(sid)
    return {b: sorted(sids)[0] for b, sids in by_biome.items() if sids}


def _kit_id_for_biome(biome):
    if not KITS_DIR.is_dir():
        return None
    for p in sorted(KITS_DIR.glob("*.json")):
        try:
            kit = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if kit.get("biome") == biome:
            return kit.get("visual_kit_id")
    return None


def _encounter_anchor_for_map(slice_id):
    """Return (mission_id, encounter_id, camera_anchor[x,y,z]) for a map, best
    effort from the encounter catalog + specs; defaults when absent."""
    mission_id = encounter_id = None
    anchor = None
    if ENCOUNTER_CATALOG.is_file():
        try:
            cat = json.loads(ENCOUNTER_CATALOG.read_text(encoding="utf-8"))
            for eid, entry in sorted((cat.get("encounters") or {}).items()):
                mid = entry.get("mission_id", "")
                if mid.endswith(slice_id) or mid[len("mission_"):] == slice_id:
                    mission_id, encounter_id = mid, eid
                    break
        except Exception:  # noqa: BLE001
            pass
    if encounter_id:
        p = ENCOUNTERS_DIR / encounter_id / "encounter.json"
        if p.is_file():
            try:
                enc = json.loads(p.read_text(encoding="utf-8"))
                for key in ("spawn_anchors", "patrol_anchors", "ambush_anchors"):
                    lst = enc.get(key) or []
                    if lst and lst[0].get("world_position"):
                        anchor = list(lst[0]["world_position"])
                        break
            except Exception:  # noqa: BLE001
                pass
    return mission_id, encounter_id, anchor


def _configure_exposure(unreal, comp):
    pp = comp.get_editor_property("post_process_settings")
    fields = {
        "auto_exposure_method": unreal.AutoExposureMethod.AEM_MANUAL,
        "auto_exposure_min_brightness": 1.0,
        "auto_exposure_max_brightness": 1.0,
        "auto_exposure_bias": 1.5,
        "override_auto_exposure_method": True,
        "override_auto_exposure_min_brightness": True,
        "override_auto_exposure_max_brightness": True,
        "override_auto_exposure_bias": True,
    }
    for k, v in fields.items():
        try:
            pp.set_editor_property(k, v)
        except Exception:  # noqa: BLE001
            pass
    comp.set_editor_property("post_process_settings", pp)


def _count_wf_actors(unreal, eas):
    counts = {"encounter": 0, "environment": 0, "weather": 0, "total_wf": 0}
    for a in list(eas.get_all_level_actors()):
        try:
            lbl = a.get_actor_label()
        except Exception:  # noqa: BLE001
            continue
        if not lbl.startswith("WF_"):
            continue
        counts["total_wf"] += 1
        if lbl.startswith("WF_ENC_"):
            counts["encounter"] += 1
        elif lbl == "WF_WeatherVFX":
            counts["weather"] += 1
        else:
            counts["environment"] += 1
    return counts


def capture_map(unreal, eas, world, slice_id, anchor, shot_dir):
    """Spawn a capture rig, render one PNG for the loaded map. Returns path."""
    rt = unreal.TextureRenderTarget2D()
    rt.set_editor_property("size_x", RES_X)
    rt.set_editor_property("size_y", RES_Y)
    rt.set_editor_property("render_target_format", unreal.TextureRenderTargetFormat.RTF_RGBA8)
    try:
        rt.update_resource()
    except Exception:  # noqa: BLE001
        pass

    target = unreal.Vector(anchor[0], anchor[1], anchor[2]) if anchor else unreal.Vector(0, 0, 0)
    loc = unreal.Vector(target.x + 1700.0, target.y - 1700.0, target.z + 1150.0)
    rot = unreal.MathLibrary.find_look_at_rotation(loc, target)

    cap = eas.spawn_actor_from_class(unreal.SceneCapture2D, loc, rot)
    cap.set_actor_label("WF_InspectCapture")
    comp = cap.capture_component2d
    comp.set_editor_property("capture_source", unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR)
    comp.set_editor_property("texture_target", rt)
    comp.set_editor_property("capture_every_frame", False)
    comp.set_editor_property("capture_on_movement", False)
    try:
        comp.set_editor_property("fov_angle", 65.0)
    except Exception:  # noqa: BLE001
        pass
    _configure_exposure(unreal, comp)

    # Prime the renderer: real-time skylight cubemap starts black in a non-ticking
    # commandlet, so cold captures render dark. Recapture + throwaway captures.
    try:
        unreal.SystemLibrary.execute_console_command(world, "r.SkyLight.RealTimeReflectionCapture 1")
    except Exception:  # noqa: BLE001
        pass
    for _ in range(6):
        comp.capture_scene()

    fname = "{}.png".format(slice_id)
    try:
        unreal.RenderingLibrary.export_render_target(world, rt, shot_dir, fname)
        out = os.path.join(shot_dir, fname)
    except Exception as exc:  # noqa: BLE001
        try:
            eas.destroy_actor(cap)
        except Exception:  # noqa: BLE001
            pass
        raise exc
    # Non-destructive: remove the capture actor; do NOT save the level.
    try:
        eas.destroy_actor(cap)
    except Exception:  # noqa: BLE001
        pass
    return out


def main():
    try:
        import unreal
    except ImportError:
        sys.stderr.write("ERROR: run inside the Unreal editor "
                         "(UnrealEditor-Cmd -ExecutePythonScript).\n")
        return 2

    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)

    root = os.path.normpath(unreal.Paths.project_dir())
    shot_dir = os.path.join(root, SHOT_REL)
    os.makedirs(shot_dir, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    picks = _pick_maps_by_biome()
    if not picks:
        unreal.log_warning("[inspect-shots] no environment rigs at {}; empty report".format(RIG_DIR))

    shots, failed = [], []
    for biome in sorted(picks):
        slice_id = picks[biome]
        map_path = MAP_ROOT + slice_id
        mission_id, encounter_id, anchor = _encounter_anchor_for_map(slice_id)
        shot = {"map_id": slice_id, "biome": biome, "mission": mission_id,
                "encounter": encounter_id, "camera_anchor": anchor,
                "screenshot_path": None,
                "visual_kit_id": _kit_id_for_biome(biome),
                "materialized_asset_counts": None,
                "validation_status": "pending"}
        try:
            if not les.load_level(map_path):
                raise RuntimeError("load_level returned False")
            world = ues.get_editor_world()
            shot["materialized_asset_counts"] = _count_wf_actors(unreal, eas)
            out = capture_map(unreal, eas, world, slice_id, anchor, shot_dir)
            rel = os.path.relpath(out, root).replace("\\", "/")
            shot["screenshot_path"] = rel
            shot["validation_status"] = "captured"
            shots.append(shot)
            unreal.log("[inspect-shots] {} ({}) -> {}".format(slice_id, biome, rel))
        except Exception as exc:  # noqa: BLE001
            shot["validation_status"] = "failed"
            shot["error"] = str(exc)
            failed.append(shot)
            shots.append(shot)
            unreal.log_error("[inspect-shots] FAIL {}: {}\n{}".format(
                slice_id, exc, traceback.format_exc()))

    report = {
        "command": "capture_inspection_shots",
        "schema_version": SCHEMA_VERSION,
        "live_captured": True,
        "capture_source": "scene_capture",
        "ticket_001_limitation": TICKET_001,
        "biomes_captured": sum(1 for s in shots if s["validation_status"] == "captured"),
        "total_biomes": len(picks),
        "failed": len(failed),
        "status": "ok" if not failed else "error",
        "shots": shots,
    }
    (REPORT_DIR / REPORT_NAME).write_text(json.dumps(report, indent=2), encoding="utf-8")
    unreal.log("[inspect-shots] DONE — {}/{} biomes captured, {} failed".format(
        report["biomes_captured"], len(picks), len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
