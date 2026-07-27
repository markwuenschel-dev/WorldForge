"""scene_survey_far_side.py — in-editor scene survey (run via -ExecutePythonScript).

The far side of run_scene_survey_probe.py. Opens the map named by the CALLER'S
already-resolved survey subject, VERIFIES the anchor that subject declares, and
drives the WorldForge survey primitives (USceneSurveyStatics, compiled into the
WorldForge plugin) around it — then writes a deterministic far-side JSON the near
side reads back and re-derives its report from. The C++ primitives also emit
WF_SURVEY_* marker lines to stdout, which the near side parses independently; the
two channels are corroborated against each other there (WF1109).

AUTHORITY BOUNDARY (v2.6): this script VERIFIES a subject, it never FINDS one.
Earlier it searched the loaded level for a class-name token and fell back to a
hard-coded actor class when the search missed — i.e. WorldForge chose the survey
subject, silently, and reported a spatial result about somewhere the caller had
not asked about. That inversion is gone:

  * ``explicit_transform`` — the caller's location is used verbatim. The level is
    never searched. There is nothing to find, so there is nothing to guess wrong.
  * ``actor_object_path`` — that EXACT object path is resolved. If it does not
    resolve, the operation FAILS (the near side maps this to
    WF1106_SCENE_SURVEY_SUBJECT_UNRESOLVED). It never degrades to a class-name
    search and never substitutes another actor: surveying a different actor than
    the one asked for is a wrong answer, not a partial one.

Whatever was actually anchored on is reported back as ``observed_anchor_location``
/ ``observed_anchor_object_path``, so the near side can BIND the result to the
request (``validate_subject_binding``) rather than assume they agree.

Read-only: this loads levels into the transient editor world and NEVER saves or
authors a permanent actor. It runs headless under -nullrhi, so it does the geometry
work (actor/component enumeration, downward-trace support classification, temporary-
marker CLEARANCE probing — no spawn) but does NOT capture screenshots (an RHI is
required; camera capture is a separate rendering pass) and does NOT drive MeshForge
runtime proxies (those spawn only at game BeginPlay, i.e. a -game pass, not an editor
load). Both are reported honestly as not-run-in-this-pass rather than faked. Capture
is OPT-IN: when the caller requested no captures, "no capture" is not a shortfall.

Everything reported here is OBSERVED from this running process. On any failure —
including an unhandled exception — evidence is still written, carrying the error and
a traceback. It never invents a success.

Inputs (environment) — the near side sets all of these:
    WF_SURVEY_OUT            absolute path for the far-side JSON (required)
    WF_SURVEY_SUBJECT        the caller-resolved SceneSurveySubject as INLINE JSON.
                             This is the PRIMARY subject channel (a subject is a few
                             hundred bytes; it needs no file and no shared mount).
    WF_SURVEY_REQUEST        absolute path to the BridgeRequest JSON; its "subject"
                             key is read ONLY when WF_SURVEY_SUBJECT is unset/empty.
                             Fallback channel, for a caller that already has the
                             request on disk.
                             Exactly one subject is used; WF_SURVEY_SUBJECT wins and
                             the source that answered is echoed as "subject_source".
    WF_SURVEY_CAPTURES       comma-separated capture kinds the caller requested;
                             "" (the default) means the caller requested none.
    WF_SURVEY_RADIUS_CM      support/enumeration radius (default 3000)
    WF_SURVEY_STEP_CM        support sample step        (default 100)
    WF_SURVEY_MARKERS        temporary-marker candidate count (default 3)
    WF_SURVEY_OPERATION_ID   operation id echoed into the JSON

There is deliberately NO map environment variable: the map is
``subject["map_asset_path"]``. A separate map knob would be a second channel that
could disagree with the subject about what was surveyed.
"""
import json
import math
import os
import traceback

import unreal  # provided by the UE Python runtime

OUT = os.environ.get("WF_SURVEY_OUT")
SUBJECT_JSON = os.environ.get("WF_SURVEY_SUBJECT", "")
REQUEST_PATH = os.environ.get("WF_SURVEY_REQUEST", "")
CAPTURES = [c.strip() for c in os.environ.get("WF_SURVEY_CAPTURES", "").split(",") if c.strip()]
RADIUS = float(os.environ.get("WF_SURVEY_RADIUS_CM", "3000"))
STEP = float(os.environ.get("WF_SURVEY_STEP_CM", "100"))
MARKERS = int(os.environ.get("WF_SURVEY_MARKERS", "3"))
OPERATION_ID = os.environ.get("WF_SURVEY_OPERATION_ID", "op_scene_survey")


def _log(msg):
    unreal.log("[wf-survey] " + msg)


def _editor_world():
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    return ues.get_editor_world()


def _world_package_name(world):
    """RAW observation: the package name of the world that is ACTUALLY open.

    This is the only channel in this file that is not a restatement of the
    caller's request. ``map``/``subject_id``/``subject_resolved_by`` are echoes of
    the subject, so a near side that compares them to the subject compares a value
    to a copy of itself. This one is measured from the live editor, which is what
    makes an identity check falsifiable.

    Returns the package name (e.g. ``/Game/Maps/Lvl_Foo``) or None if it cannot be
    read. None is honest: it means "not observed", never "matched".
    """
    try:
        return world.get_package().get_name()
    except Exception:  # noqa: BLE001 — an unreadable world identity is not a match
        return None


def _norm_package(p):
    """Normalise a package/object path for identity comparison.

    ``/Game/Maps/Foo.Foo`` and ``/Game/Maps/Foo`` name the same package. Compare on
    the package part only, case-insensitively, with trailing slashes removed.
    """
    if not isinstance(p, str):
        return None
    s = p.strip().rstrip("/")
    if not s:
        return None
    head, sep, tail = s.rpartition("/")
    if sep and "." in tail:
        s = head + "/" + tail.split(".", 1)[0]
    return s.lower()


def _finite_vec3(v):
    """True iff v is a 3-element list of FINITE real numbers (bools excluded).

    math.isfinite is load-bearing, not decoration: NaN and Infinity are float
    instances, so an isinstance-only check accepts them, they survive into
    unreal.Vector, and json.dump then emits bare NaN/Infinity tokens — invalid JSON
    that Python's own loads() accepts by default, so the poison propagates silently
    to the near side instead of failing here.
    """
    return (isinstance(v, list) and len(v) == 3
            and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                    and math.isfinite(x) for x in v))


def _load_subject():
    """Return (subject_or_None, source_label, error_or_None).

    Two channels, one winner, and the winner is recorded. A subject that cannot be
    parsed is an ERROR, never an empty subject: an empty subject would be
    indistinguishable from "the caller asked for nothing", which is exactly the
    ambiguity that lets a survey silently pick its own target.
    """
    if SUBJECT_JSON.strip():
        try:
            return json.loads(SUBJECT_JSON), "env:WF_SURVEY_SUBJECT", None
        except ValueError as exc:
            return None, "env:WF_SURVEY_SUBJECT", "WF_SURVEY_SUBJECT is not valid JSON: {}".format(exc)
    if REQUEST_PATH.strip():
        try:
            with open(REQUEST_PATH, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (ValueError, OSError) as exc:
            return None, "file:WF_SURVEY_REQUEST", "cannot read WF_SURVEY_REQUEST {}: {}".format(
                REQUEST_PATH, exc)
        sub = doc.get("subject") if isinstance(doc, dict) else None
        if not isinstance(sub, dict):
            return None, "file:WF_SURVEY_REQUEST", (
                "request {} carries no 'subject' object".format(REQUEST_PATH))
        return sub, "file:WF_SURVEY_REQUEST", None
    return None, "absent", ("no survey subject was supplied (set WF_SURVEY_SUBJECT or "
                            "WF_SURVEY_REQUEST) — WorldForge must never choose one")


def _resolve_object_path(want, actors):
    """Resolve the EXACT object path ``want`` to a placed actor, or return None.

    Exact ``get_path_name()`` equality over the actors actually in the loaded level
    is the primary route: it can only ever return the object the caller named.
    ``unreal.load_object`` is a fallback for an actor the level-actor enumeration
    missed, and its result is accepted ONLY when its own path name equals ``want``
    — load_object is happy to resolve a *nearby* object, and accepting that would
    re-introduce, by the back door, exactly the substitution this function exists
    to prevent.

    There is no class-name search and no default actor. A miss is a miss.
    """
    for a in actors:
        try:
            if a.get_path_name() == want:
                return a
        except Exception:  # noqa: BLE001
            continue
    try:
        obj = unreal.load_object(None, want)
    except Exception:  # noqa: BLE001
        return None
    if obj is None:
        return None
    try:
        return obj if obj.get_path_name() == want else None
    except Exception:  # noqa: BLE001
        return None


def _verify_anchor(subject, actors):
    """VERIFY the caller's declared anchor. Returns (ok, location, object_path, detail).

    ``location`` is a plain [x, y, z] list (JSON-safe) or None. This never searches
    for a subject; each branch only confirms what the caller already resolved.
    """
    mode = subject.get("anchor_mode")
    if mode == "explicit_transform":
        loc = subject.get("anchor_location")
        if not _finite_vec3(loc):
            return (False, None, None,
                    "anchor_mode=explicit_transform but anchor_location is not a finite "
                    "vec3 (got {!r}) — the subject is unresolved".format(loc))
        return (True, [float(loc[0]), float(loc[1]), float(loc[2])], None,
                "used the caller's explicit transform verbatim; the level was not searched")
    if mode == "actor_object_path":
        want = subject.get("anchor_object_path")
        if not (isinstance(want, str) and want.strip()):
            return (False, None, None,
                    "anchor_mode=actor_object_path but anchor_object_path is empty "
                    "(got {!r}) — the subject is unresolved".format(want))
        actor = _resolve_object_path(want.strip(), actors)
        if actor is None:
            return (False, None, None,
                    "anchor_object_path {!r} did not resolve among the {} placed actors "
                    "of this level; refusing to substitute any other actor".format(
                        want, len(actors)))
        loc = actor.get_actor_location()
        return (True, [loc.x, loc.y, loc.z], actor.get_path_name(),
                "resolved the caller's exact object path")
    return (False, None, None,
            "unknown anchor_mode {!r} — WorldForge does not interpret anchor modes it "
            "was not given".format(mode))


def main():
    subject, subject_source, subject_error = _load_subject()
    subject = subject if isinstance(subject, dict) else {}
    map_path = subject.get("map_asset_path") or ""

    doc = {
        "operation_id": OPERATION_ID,
        "map": map_path,
        # The caller's subject, echoed so the near side can bind request<->result.
        "subject_id": subject.get("subject_id"),
        "subject_kind": subject.get("subject_kind"),
        "anchor_mode": subject.get("anchor_mode"),
        "subject_resolved_by": subject.get("resolved_by"),
        "subject_source": subject_source,
        # False until an anchor is actually VERIFIED. Never optimistic.
        "subject_resolved": False,
        "anchor_detail": None,
        "observed_anchor_location": None,
        "observed_anchor_object_path": None,
        "loaded": False,
        # RAW, measured from the live editor — NOT an echo of the request. The near
        # side re-derives the identity verdict from this; the far side states no
        # verdict of its own. None means "not observed", never "matched".
        "observed_world_package": None,
        "observed_engine_version": unreal.SystemLibrary.get_engine_version(),
        "resolved_uproject": unreal.Paths.get_project_file_path(),
        "actor_count": None,
        "support_total": None,
        "marker_total": 0,
        "marker_accepted": 0,
        # capture is OPT-IN and is not runnable in a -nullrhi pass either way.
        "captures_requested": list(CAPTURES),
        "camera_capture_ran": False,
        "camera_capture_reason": (
            "{} capture(s) requested but this pass cannot render: an RHI is required "
            "(-nullrhi)".format(len(CAPTURES)) if CAPTURES else
            "no captures were requested by the caller (capture is opt-in)"),
        "proxy_pass_ran": False,
        "proxy_pass_reason": "MeshForge proxies spawn at game BeginPlay; needs a -game pass",
        "survey_statics_available": hasattr(unreal, "SceneSurveyStatics"),
        "error": subject_error,
        "traceback": None,
    }
    if not OUT:
        _log("ERROR: WF_SURVEY_OUT not set")
        return
    if subject_error:
        # No subject => nothing legitimate to survey. Write the honest refusal.
        _write(doc)
        return
    if not map_path:
        doc["error"] = "subject carries no map_asset_path — nothing to open"
        _write(doc)
        return

    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        doc["loaded"] = bool(les.load_level(map_path))
        world = _editor_world()
        # Record the world identity BEFORE anything else reads the world, so the
        # observation stands even if a later step throws.
        doc["observed_world_package"] = _world_package_name(world)
        actors = unreal.EditorActorSubsystem().get_all_level_actors()
        ok, loc, opath, detail = _verify_anchor(subject, actors)
        doc["subject_resolved"] = bool(ok)
        doc["anchor_detail"] = detail
        doc["observed_anchor_location"] = loc
        doc["observed_anchor_object_path"] = opath
        # A failed load leaves the PREVIOUS world open. In explicit_transform mode
        # _verify_anchor never searches the level, so nothing downstream would ever
        # notice: the survey would measure the wrong world and report it under the
        # requested map path. Refuse before running any primitive, and say which of
        # the two things went wrong so the near side can raise the matching code.
        want_pkg = _norm_package(map_path)
        got_pkg = _norm_package(doc["observed_world_package"])
        if not doc["loaded"]:
            doc["error"] = (
                "load_level({!r}) returned False — the requested map was not opened; "
                "the editor is still on {!r}. Refusing to survey a world the caller "
                "did not ask for.".format(map_path, doc["observed_world_package"]))
        elif got_pkg is None:
            doc["error"] = (
                "the identity of the loaded world could not be read, so it cannot be "
                "confirmed to be {!r}. An unverifiable world is not a verified one."
                .format(map_path))
        elif want_pkg != got_pkg:
            doc["error"] = (
                "world identity mismatch: caller requested {!r} but the open world is "
                "{!r}. Refusing to report measurements of one world under the name of "
                "another.".format(map_path, doc["observed_world_package"]))
        elif not ok:
            doc["error"] = detail
        elif not doc["survey_statics_available"]:
            doc["error"] = "USceneSurveyStatics not reflected — WorldForge plugin not loaded"
        else:
            ctr = unreal.Vector(loc[0], loc[1], loc[2])
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
    except Exception as e:  # noqa: BLE001  — never fabricate a success
        doc["error"] = "{}: {}".format(type(e).__name__, e)
        doc["traceback"] = traceback.format_exc()

    _write(doc)


def _write(doc):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
    _log("wrote survey -> {} (subject={} resolved={} actors={} support={} markers={}/{} "
         "err={})".format(OUT, doc.get("subject_id"), doc.get("subject_resolved"),
                          doc["actor_count"], doc["support_total"],
                          doc["marker_accepted"], doc["marker_total"], doc["error"]))


try:
    main()
except Exception as _fatal:  # noqa: BLE001
    # Even a failure BEFORE/AROUND main's own handler must leave evidence: a far
    # side that dies silently is indistinguishable from one that never started,
    # and the near side would have nothing to report but a timeout.
    if OUT:
        try:
            _write({
                "operation_id": OPERATION_ID, "map": None, "subject_id": None,
                "subject_kind": None, "anchor_mode": None, "subject_resolved_by": None,
                "subject_source": None, "subject_resolved": False, "anchor_detail": None,
                "observed_anchor_location": None, "observed_anchor_object_path": None,
                "loaded": False, "observed_world_package": None,
                "observed_engine_version": None,
                "resolved_uproject": None, "actor_count": None, "support_total": None,
                "marker_total": 0, "marker_accepted": 0,
                "captures_requested": list(CAPTURES), "camera_capture_ran": False,
                "camera_capture_reason": "far side aborted before the capture question",
                "proxy_pass_ran": False, "proxy_pass_reason": "far side aborted",
                "survey_statics_available": False,
                "error": "{}: {}".format(type(_fatal).__name__, _fatal),
                "traceback": traceback.format_exc(),
            })
        except Exception:  # noqa: BLE001
            _log("FATAL: could not write far-side evidence")

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
