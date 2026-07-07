#!/usr/bin/env python3
r"""materialize_visual_kits_ue.py (UE5 Python) — WorldForge v1.5 Wave-3
(single-boot batch driver).

Applies each biome's VisualEnvironmentKit to every map in that biome AND finally
spawns the weather Niagara actor that materialize_environment_rig.py left
DEFERRED. Extends the environment-rig pattern:

  * kits: procedural/generated/visual/kits/*.json (VisualEnvironmentKit, keyed by
    biome) select which biomes to dress and carry the weather profile.
  * per-map rigs: procedural/generated/visual/environment_rigs/<slice_id>.json
    (resolved, one per map) drive the concrete component set + params. slice_ids
    are grouped to biomes via each rig's ``biome`` field.

For each map of a kit's biome this loads the level, clears stale WF_ environment
actors (NEVER touches WF_ENC_ encounter/cover actors), spawns the rig's
SkyAtmosphere / DirectionalLight sun / SkyLight / ExponentialHeightFog /
VolumetricCloud / unbound PostProcessVolume, then spawns WF_WeatherVFX:
  - if a real Niagara weather system asset resolves, it is bound to the
    NiagaraActor and weather_spawned = true;
  - otherwise an empty ANiagaraActor placeholder is spawned and recorded honestly
    with weather_spawned = false (placeholder_spawned = true).
save_current_level per map. Idempotent.

Report (honest, per-map weather_spawned):
    procedural/reports/visual/materialize_visual_kits/
        materialize_visual_kits_report.json

Run (single boot over all kit biomes):
    "<UE>/UnrealEditor-Cmd.exe" "D:/Unreal Projects/WorldForge/WorldForge.uproject" ^
        -ExecutePythonScript="tools/unreal/materialize_visual_kits_ue.py" ^
        -unattended -nopause -nosplash -stdout
"""

import json
import sys
import traceback
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KITS_DIR = REPO_ROOT / "procedural" / "generated" / "visual" / "kits"
RIG_DIR = REPO_ROOT / "procedural" / "generated" / "visual" / "environment_rigs"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "visual" / "materialize_visual_kits"
REPORT_NAME = "materialize_visual_kits_report.json"
MAP_ROOT = "/Game/WorldForge/Maps/"
WEATHER_DIR = "/Game/WorldForge/VFX/Weather/"
SCHEMA_VERSION = "wf.visual.materialize_visual_kits.v1"

# Environment/weather actor labels this driver OWNS (idempotency clears these,
# leaving WF_ENC_ encounter + cover actors untouched).
MANAGED_LABELS = {
    "WF_SkyAtmosphere", "WF_Sun", "WF_SkyLight", "WF_HeightFog",
    "WF_VolumetricCloud", "WF_PostProcess", "WF_WeatherVFX",
}


def _load_kits():
    """biome -> kit dict. Tolerate an empty/absent kits dir."""
    by_biome = {}
    if not KITS_DIR.is_dir():
        return by_biome
    for p in sorted(KITS_DIR.glob("*.json")):
        try:
            kit = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        b = kit.get("biome")
        if b:
            by_biome.setdefault(b, kit)
    return by_biome


def _rigs_by_biome():
    """biome -> [(slice_id, rig_dict)], from the resolved per-map rigs."""
    by_biome = defaultdict(list)
    if not RIG_DIR.is_dir():
        return by_biome
    for p in sorted(RIG_DIR.glob("*.json")):
        try:
            rig = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        b = rig.get("biome")
        sid = rig.get("slice_id") or p.stem
        if b:
            by_biome[b].append((sid, rig))
    return by_biome


def _params(rig, component):
    for c in rig.get("components", []):
        if c.get("component") == component:
            return c if c.get("enabled") else None
    return None


def _clear_managed(unreal, eas):
    removed = 0
    for a in list(eas.get_all_level_actors()):
        try:
            if a.get_actor_label() in MANAGED_LABELS:
                eas.destroy_actor(a)
                removed += 1
        except Exception:  # noqa: BLE001
            pass
    return removed


def _resolve_weather_system(unreal, kit, rig):
    """Return (system_obj_or_None, source_path_or_None, weather_kind)."""
    eal = unreal.EditorAssetLibrary
    wcomp = _params(rig, "WeatherVFX_Niagara")
    wparams = (wcomp or {}).get("params") or {}
    weather_kind = wparams.get("weather_kind") or (kit.get("environment_mode") if kit else None)
    candidates = []
    # explicit kit-provided niagara system
    kw = (kit or {}).get("weather") or {}
    if isinstance(kw, dict) and kw.get("niagara_system"):
        candidates.append(kw["niagara_system"])
    if wparams.get("niagara_system"):
        candidates.append(wparams["niagara_system"])
    if wparams.get("emitter"):
        candidates.append(WEATHER_DIR + str(wparams["emitter"]))
    if weather_kind:
        candidates.append(WEATHER_DIR + "NS_{}".format(weather_kind))
    for c in candidates:
        try:
            if eal.does_asset_exist(c):
                obj = eal.load_asset(c)
                if obj and isinstance(obj, unreal.NiagaraSystem):
                    return obj, c, weather_kind
        except Exception:  # noqa: BLE001
            pass
    return None, None, weather_kind


def materialize_map(unreal, eas, slice_id, kit, rig):
    removed = _clear_managed(unreal, eas)
    spawned = []

    def spawn(cls, label):
        actor = eas.spawn_actor_from_class(cls, unreal.Vector(0, 0, 0))
        if actor:
            actor.set_actor_label(label)
            spawned.append(label)
        return actor

    if _params(rig, "SkyAtmosphere"):
        spawn(unreal.SkyAtmosphere, "WF_SkyAtmosphere")
    sun = _params(rig, "DirectionalLight_Sun")
    if sun:
        a = spawn(unreal.DirectionalLight, "WF_Sun")
        ang = (sun.get("params") or {}).get("sun_angle_deg")
        if a and ang is not None:
            a.set_actor_rotation(unreal.Rotator(0.0, -float(ang), 0.0), False)
    if _params(rig, "SkyLight"):
        spawn(unreal.SkyLight, "WF_SkyLight")
    if _params(rig, "ExponentialHeightFog"):
        spawn(unreal.ExponentialHeightFog, "WF_HeightFog")
    if _params(rig, "VolumetricCloud"):
        spawn(unreal.VolumetricCloud, "WF_VolumetricCloud")
    pp = _params(rig, "PostProcessVolume")
    if pp:
        a = spawn(unreal.PostProcessVolume, "WF_PostProcess")
        if a:
            a.set_editor_property("unbound", True)

    # Weather Niagara — the previously-deferred step, now actually spawned.
    weather_spawned, placeholder_spawned, weather_src = False, False, None
    system, weather_src, weather_kind = _resolve_weather_system(unreal, kit, rig)
    wactor = spawn(unreal.NiagaraActor, "WF_WeatherVFX")
    if wactor:
        if system is not None:
            try:
                wactor.get_niagara_component().set_asset(system)
                weather_spawned = True
            except Exception:  # noqa: BLE001 — fall back to placeholder record
                placeholder_spawned = True
        else:
            placeholder_spawned = True

    return {"slice_id": slice_id, "map": MAP_ROOT + slice_id,
            "biome": rig.get("biome"),
            "visual_kit_id": (kit or {}).get("visual_kit_id"),
            "removed_stale": removed, "actors": spawned,
            "weather_spawned": weather_spawned,
            "weather_placeholder": placeholder_spawned,
            "weather_kind": weather_kind, "weather_system": weather_src,
            "live_spawned": True}


def main():
    try:
        import unreal
    except ImportError:
        sys.stderr.write("ERROR: run inside the Unreal editor "
                         "(UnrealEditor-Cmd -ExecutePythonScript).\n")
        return 2

    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    kits = _load_kits()
    rigs = _rigs_by_biome()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    if not kits:
        unreal.log_warning("[visual-kits] no VisualEnvironmentKits at {} "
                           "(resolver not run?); empty report".format(KITS_DIR))

    map_rows, failed = [], []
    for biome in sorted(kits):
        kit = kits[biome]
        targets = rigs.get(biome, [])
        if not targets:
            unreal.log_warning("[visual-kits] kit {} biome {} has no maps".format(
                kit.get("visual_kit_id"), biome))
        for slice_id, rig in targets:
            map_path = MAP_ROOT + slice_id
            try:
                if not les.load_level(map_path):
                    raise RuntimeError("load_level returned False")
                row = materialize_map(unreal, eas, slice_id, kit, rig)
                if not les.save_current_level():
                    raise RuntimeError("save_current_level returned False")
                map_rows.append(row)
                unreal.log("[visual-kits] {} — {} actors, weather_spawned={}".format(
                    slice_id, len(row["actors"]), row["weather_spawned"]))
            except Exception as exc:  # noqa: BLE001
                failed.append({"slice_id": slice_id, "error": str(exc)})
                unreal.log_error("[visual-kits] FAIL {}: {}\n{}".format(
                    slice_id, exc, traceback.format_exc()))

    report = {
        "command": "materialize_visual_kits",
        "schema_version": SCHEMA_VERSION,
        "live_spawned": True,
        "kit_biomes": sorted(kits.keys()),
        "total_maps": len(map_rows),
        "weather_spawned_count": sum(1 for r in map_rows if r["weather_spawned"]),
        "weather_placeholder_count": sum(1 for r in map_rows if r["weather_placeholder"]),
        "failed_maps": len(failed),
        "status": "ok" if not failed else "error",
        "maps": map_rows,
        "failures": failed,
    }
    (REPORT_DIR / REPORT_NAME).write_text(json.dumps(report, indent=2), encoding="utf-8")
    unreal.log("[visual-kits] DONE — {} maps, {} weather real, {} placeholder, {} failed".format(
        len(map_rows), report["weather_spawned_count"],
        report["weather_placeholder_count"], len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
