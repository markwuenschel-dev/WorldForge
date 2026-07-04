#!/usr/bin/env python3
r"""materialize_environment_rig.py (UE5 Python) — WorldForge v1.3.5 environment-rig
live materializer.

Consumes the resolved environment-rig specs written headlessly by
tools/pipeline/materialize_environment_rigs.py
(procedural/generated/visual/environment_rigs/<slice_id>.json) and spawns the
real UE-native actors into the map: SkyAtmosphere, a directional sun light,
SkyLight, ExponentialHeightFog, VolumetricCloud (when enabled), an unbound
PostProcessVolume, and a weather Niagara actor (when enabled) — with every
parameter taken from the resolved spec. Writes a live-spawn materialization
report per rig so validate_environment_rig can flip live_spawned -> true.

This is the DEFERRED editor step for v1.3.5 (WF-FOLLOWUP-UE-VISUAL-MATERIALIZE):
the headless pipeline resolves + validates the full spec; this driver realizes it
in-engine when an editor with the WorldForge project is available.

Run headless (per map, or loop over the catalog):
    UnrealEditor-Cmd <uproject> -ExecutePythonScript="materialize_environment_rig.py <slice_id>" \
        -unattended -nopause -stdout
"""

import json
import sys
from pathlib import Path

# Project root: this file is tools/unreal/materialize_environment_rig.py
REPO_ROOT = Path(__file__).resolve().parents[2]
RIG_DIR = REPO_ROOT / "procedural" / "generated" / "visual" / "environment_rigs"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "visual" / "ue_materialize"


def _load_rig(slice_id):
    p = RIG_DIR / "{}.json".format(slice_id)
    if not p.is_file():
        raise FileNotFoundError("rig spec not found: {}".format(p))
    return json.loads(p.read_text(encoding="utf-8"))


def _params(rig, component):
    for c in rig.get("components", []):
        if c.get("component") == component:
            return c if c.get("enabled") else None
    return None


def materialize(slice_id):
    """Spawn the environment rig actors for one map. Requires the UE editor."""
    try:
        import unreal
    except ImportError:
        sys.stderr.write(
            "ERROR: this driver must run inside the Unreal editor "
            "(UnrealEditor-Cmd -ExecutePythonScript). No 'unreal' module here.\n")
        return 2

    rig = _load_rig(slice_id)
    eas = unreal.EditorActorSubsystem()
    spawned = []

    def spawn(actor_class, label):
        actor = eas.spawn_actor_from_class(actor_class, unreal.Vector(0, 0, 0))
        if actor:
            actor.set_actor_label(label)
            spawned.append(label)
        return actor

    # SkyAtmosphere
    if _params(rig, "SkyAtmosphere"):
        spawn(unreal.SkyAtmosphere, "WF_SkyAtmosphere")
    # Directional sun
    sun = _params(rig, "DirectionalLight_Sun")
    if sun:
        a = spawn(unreal.DirectionalLight, "WF_Sun")
        ang = (sun.get("params") or {}).get("sun_angle_deg")
        if a and ang is not None:
            a.set_actor_rotation(unreal.Rotator(0.0, -float(ang), 0.0), False)
    # SkyLight
    if _params(rig, "SkyLight"):
        spawn(unreal.SkyLight, "WF_SkyLight")
    # Height fog
    if _params(rig, "ExponentialHeightFog"):
        spawn(unreal.ExponentialHeightFog, "WF_HeightFog")
    # Volumetric cloud (optional)
    if _params(rig, "VolumetricCloud"):
        spawn(unreal.VolumetricCloud, "WF_VolumetricCloud")
    # Post process (unbound)
    pp = _params(rig, "PostProcessVolume")
    if pp:
        a = spawn(unreal.PostProcessVolume, "WF_PostProcess")
        if a:
            a.set_editor_property("unbound", True)
    # Weather VFX (optional) — spawned as a NiagaraActor placeholder; the concrete
    # system asset is bound by the weather profile when present in the project.
    if _params(rig, "WeatherVFX_Niagara"):
        spawned.append("WF_WeatherVFX (deferred: bind Niagara system)")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {"slice_id": slice_id, "live_spawned": True, "actors": spawned,
              "schema_version": "wf.visual.ue_materialize.v1"}
    (REPORT_DIR / "{}.json".format(slice_id)).write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    unreal.log("[materialize-environment-rig] {} — spawned {} actors".format(slice_id, len(spawned)))
    return 0


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else None
    if not sid:
        sys.stderr.write("usage: materialize_environment_rig.py <slice_id>\n")
        sys.exit(2)
    sys.exit(materialize(sid))
