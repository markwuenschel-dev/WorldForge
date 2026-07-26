"""scene_survey_far_side.py — in-editor scene survey (run via -ExecutePythonScript).

The far side of run_scene_survey_probe.py. Opens a target map in the editor world
and drives the WorldForge survey primitives (USceneSurveyStatics, compiled into the
WorldForge plugin) over it, then writes a deterministic far-side JSON the near side
reads back and re-derives its report from. The C++ primitives also emit WF_SURVEY_*
marker lines to stdout, which the near side parses independently.

Read-only: this loads levels into the transient editor world and NEVER saves or
authors a permanent actor. It runs headless under -nullrhi, so it does the geometry
work (actor/component enumeration, downward-trace support classification, temporary-
marker CLEARANCE probing — no spawn) but does NOT capture screenshots (an RHI is
required; camera capture is a separate rendering pass) and does NOT drive MeshForge
runtime proxies (those spawn only at game BeginPlay, i.e. a -game pass, not an editor
load). Both are reported honestly as not-run-in-this-pass rather than faked.

Inputs (environment):
    WF_SURVEY_OUT            absolute path for the far-side JSON (required)
    WF_SURVEY_MAP            map asset path, e.g. /Game/ThirdPerson/Lvl_ThirdPerson
    WF_SURVEY_ANCHOR         player | heart          (default player)
    WF_SURVEY_RADIUS_CM      support/enumeration radius (default 3000)
    WF_SURVEY_STEP_CM        support sample step        (default 100)
    WF_SURVEY_MARKERS        temporary-marker candidate count (default 3)
    WF_SURVEY_OPERATION_ID   operation id echoed into the JSON
"""
import json
import os

import unreal  # provided by the UE Python runtime

OUT = os.environ.get("WF_SURVEY_OUT")
MAP = os.environ.get("WF_SURVEY_MAP", "")
ANCHOR = os.environ.get("WF_SURVEY_ANCHOR", "player")
RADIUS = float(os.environ.get("WF_SURVEY_RADIUS_CM", "3000"))
STEP = float(os.environ.get("WF_SURVEY_STEP_CM", "100"))
MARKERS = int(os.environ.get("WF_SURVEY_MARKERS", "3"))
OPERATION_ID = os.environ.get("WF_SURVEY_OPERATION_ID", "op_scene_survey")

# Anchor class-name tokens (matched case-insensitively against placed actors).
ANCHOR_TOKENS = {"player": "PlayerStart", "heart": "VeilHeart"}


def _log(msg):
    unreal.log("[wf-survey] " + msg)


def _editor_world():
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    return ues.get_editor_world()


def _resolve_anchor(actors):
    """Return (name, unreal.Vector) for the anchor placed-actor, or (None, None).

    Anchors on a PLACED actor's transform (PlayerStart / AVeilHeart) — never a
    spawned player pawn, which does not exist in an editor load. No guessed coords.
    """
    want = ANCHOR_TOKENS.get(ANCHOR, "PlayerStart").lower()
    for a in actors:
        try:
            if want in a.get_class().get_name().lower():
                return a.get_name(), a.get_actor_location()
        except Exception:  # noqa: BLE001
            continue
    return None, None


def main():
    doc = {
        "operation_id": OPERATION_ID,
        "map": MAP,
        "anchor": ANCHOR,
        "loaded": False,
        "observed_engine_version": unreal.SystemLibrary.get_engine_version(),
        "resolved_uproject": unreal.Paths.get_project_file_path(),
        "anchor_actor": None,
        "anchor_location": None,
        "actor_count": None,
        "support_total": None,
        "marker_total": 0,
        "marker_accepted": 0,
        # capabilities not runnable in a -nullrhi editor-load pass; honest, not faked.
        "camera_capture_ran": False,
        "camera_capture_reason": "requires an RHI + rendering pass (-nullrhi cannot render)",
        "proxy_pass_ran": False,
        "proxy_pass_reason": "MeshForge proxies spawn at game BeginPlay; needs a -game pass",
        "survey_statics_available": hasattr(unreal, "SceneSurveyStatics"),
        "error": None,
    }
    if not OUT:
        _log("ERROR: WF_SURVEY_OUT not set")
        return
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        doc["loaded"] = bool(les.load_level(MAP))
        world = _editor_world()
        actors = unreal.EditorActorSubsystem().get_all_level_actors()
        name, loc = _resolve_anchor(actors)
        doc["anchor_actor"] = name
        if loc is not None:
            doc["anchor_location"] = [loc.x, loc.y, loc.z]
            ctr = unreal.Vector(loc.x, loc.y, loc.z)
            if not doc["survey_statics_available"]:
                doc["error"] = "USceneSurveyStatics not reflected — WorldForge plugin not loaded"
            else:
                stat = unreal.SceneSurveyStatics
                doc["actor_count"] = int(stat.enumerate_survey_actors(world, ctr, RADIUS))
                doc["support_total"] = int(stat.sample_survey_support(world, ctr, RADIUS, STEP))
                accepted = 0
                for i in range(MARKERS):
                    cand = unreal.Vector(ctr.x + (i + 1) * STEP, ctr.y, ctr.z)
                    if stat.probe_temp_marker(world, cand, 34.0, 88.0):
                        accepted += 1
                doc["marker_total"] = MARKERS
                doc["marker_accepted"] = accepted
        else:
            doc["error"] = "anchor '{}' not resolvable among {} placed actors".format(
                ANCHOR, len(actors))
    except Exception as e:  # noqa: BLE001
        doc["error"] = str(e)

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
    _log("wrote survey -> {} (actors={} support={} markers={}/{} err={})".format(
        OUT, doc["actor_count"], doc["support_total"],
        doc["marker_accepted"], doc["marker_total"], doc["error"]))


main()

# Request a clean editor shutdown so the near-side process actually exits (a plain
# -ExecutePythonScript boot otherwise stays in the editor loop until timeout — the
# same hang observed on the -execcmds=quit smoke boot).
try:
    unreal.SystemLibrary.quit_editor()
except Exception as _e:  # noqa: BLE001
    try:
        unreal.SystemLibrary.execute_console_command(_editor_world(), "quit")
    except Exception:  # noqa: BLE001
        _log("WARNING: could not request editor shutdown; near side will rely on timeout")
