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

RAW OBSERVATIONS ONLY — the non-circularity rule
------------------------------------------------
    far side   -> RAW observations ONLY. FORBIDDEN to emit a verdict boolean.
    assembler  -> derives values from raw, and must state its inputs.
    validator  -> RE-DERIVES from the same raw, independently, and compares.

Nothing in this file may emit ``actor_bounds_valid``, ``cleanup_verified``,
``player_clearance_valid``, ``temporary_placements_grounded``, ``overlap_count`` or
any other report-level verdict: those are DERIVATIONS, computed by the assembler
from the raw below and re-computed independently by the validator
(tools/pipeline/scene_survey_evidence.py:399-407). Emitting one here would collapse
that scheme into self-attestation. What this file emits is measurements: counts,
identities, transforms, sets, trace hits, and error strings.

``raw_evidence`` is the structured channel, shaped as the raw evidence BUNDLE the
evidence model addresses (``{kind: {ident: record}}``, refs of the form
``"<kind>#<ident>"`` — scene_survey_evidence.py:245-258). Kinds emitted here:

    world               one record: the identity of the world actually open
    actor               one record per enumerated actor (transform + bounds)
    component           one record per primitive component (collision + bounds)
    trace               one record per line trace actually performed
    marker              one record per temporary-marker CANDIDATE probed
    proxy               MeshForge proxy observation (honestly unobserved here)
    temporary_placement one record per object THIS operation spawned (see below)
    inventory           "pre" and "post" mutation snapshots

The per-marker keys ``grounded`` / ``footprint`` / ``overlap`` / ``capsule_clear``
are the field names the committed raw-bundle contract reads
(scene_survey_evidence.py:316,322,333,346). Here each is a nullable RESTATEMENT of
atomic trace observations that are ALSO emitted alongside it
(``ground_trace_ref``, ``footprint_trace_refs``, ``capsule_overlap_*_actor_paths``),
so the assembler can re-derive them from the atoms rather than take them on faith.
When the underlying atom was not collected the restatement is ``None`` — never
False, never zero. ``None`` means "not observed"; it never means "measured zero"
and it never means "fine".

Every Unreal API call below is individually guarded. The Python symbol surface of
UE 5.8 cannot be executed or introspected from the repo side, so an unexpected
shape must degrade to a recorded ``None`` plus a reason in ``collection_errors`` —
never to a fabricated success and never to a silently-plausible zero.

MUTATION / CLEANUP
------------------
``inventory.pre`` and ``inventory.post`` are raw snapshots of the dirty map-package
set, the dirty content-package set, the level's actor path set, and the objects
this operation owns. They are emitted RAW so cleanup can be VERIFIED by comparing
them, not asserted. Note the engine constraint: ``UPackage.is_dirty()`` is not
exposed to Python, so dirtiness is observable only as membership of
``EditorLoadingAndSavingUtils.get_dirty_map_packages()`` /
``get_dirty_content_packages()`` — there is no per-package predicate — and
``ScopedEditorTransaction.cancel()`` does NOT restore a package's dirty flag. That
is why the spawn policy is ``transient=True`` only, and why this pass spawns
nothing at all: marker clearance is trace-probed. Anything it did spawn would be
tracked in ``temporary_placement``, destroyed, and the destruction RE-OBSERVED
(``_SpawnLedger``).

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

# The raw bundle schema this file writes; the evidence model names the same string
# (tools/pipeline/scene_survey_evidence.py:64).
RAW_BUNDLE_SCHEMA = "wf.scene_survey.raw_evidence_bundle.v1"

# Stage vocabulary, mirroring scene_survey_evidence.STAGES (:96). A record's stage
# is load-bearing: an inventory taken at `observe` cannot witness `cleanup`.
ST_PREPARATION = "preparation"
ST_MAP_LOAD = "map_load"
ST_WORLD_IDENTITY = "world_identity"
ST_ANCHOR_BIND = "anchor_bind"
ST_OBSERVE = "observe"
ST_CLASSIFY = "classify"
ST_CLEANUP = "cleanup"

MARKER_CAPSULE_RADIUS = 34.0
MARKER_CAPSULE_HALF_HEIGHT = 88.0

OUT = os.environ.get("WF_SURVEY_OUT")
SUBJECT_JSON = os.environ.get("WF_SURVEY_SUBJECT", "")
REQUEST_PATH = os.environ.get("WF_SURVEY_REQUEST", "")
CAPTURES = [c.strip() for c in os.environ.get("WF_SURVEY_CAPTURES", "").split(",") if c.strip()]
OPERATION_ID = os.environ.get("WF_SURVEY_OPERATION_ID", "op_scene_survey")


def _env_number(name, default, cast):
    """Parse a numeric env var. Returns (value, error_or_None) and NEVER raises.

    This used to be a bare ``float(os.environ.get(...))`` at module scope, outside
    every try block: one malformed value and the module died before ``main`` was
    ever entered, so NO evidence file was written at all and the near side saw only
    a timeout. A bad knob is now a recorded input error with the documented default
    still in force — an honest degradation instead of a silent disappearance.
    """
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return cast(default), None
    try:
        value = cast(str(raw).strip())
    except (TypeError, ValueError) as exc:
        return cast(default), "{}={!r} is not a valid {}: {} — using default {!r}".format(
            name, raw, cast.__name__, exc, default)
    try:
        if not math.isfinite(float(value)):
            return cast(default), "{}={!r} is not finite — using default {!r}".format(
                name, raw, default)
    except (TypeError, ValueError, OverflowError):
        return cast(default), "{}={!r} is not a finite number — using default {!r}".format(
            name, raw, default)
    return value, None


RADIUS, _RADIUS_ERR = _env_number("WF_SURVEY_RADIUS_CM", 3000.0, float)
STEP, _STEP_ERR = _env_number("WF_SURVEY_STEP_CM", 100.0, float)
MARKERS, _MARKERS_ERR = _env_number("WF_SURVEY_MARKERS", 3, int)
ENV_PARSE_ERRORS = [e for e in (_RADIUS_ERR, _STEP_ERR, _MARKERS_ERR) if e]


def _log(msg):
    try:
        unreal.log("[wf-survey] " + msg)
    except Exception:  # noqa: BLE001 — logging must never be the thing that fails a run
        pass


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


# --------------------------------------------------------------------------- #
# raw-collection primitives. Every one degrades to None + a reason, never to a
# plausible zero. `None` means NOT OBSERVED.
# --------------------------------------------------------------------------- #
def _xyz(v):
    """[x, y, z] from an unreal.Vector-like, or None if unreadable/non-finite."""
    try:
        out = [float(v.x), float(v.y), float(v.z)]
    except Exception:  # noqa: BLE001
        return None
    return out if _finite_vec3(out) else None


def _pyr(r):
    """[pitch, yaw, roll] from an unreal.Rotator-like, or None."""
    try:
        out = [float(r.pitch), float(r.yaw), float(r.roll)]
    except Exception:  # noqa: BLE001
        return None
    return out if _finite_vec3(out) else None


def _path_of(obj):
    try:
        return obj.get_path_name()
    except Exception:  # noqa: BLE001
        return None


def _class_of(obj):
    try:
        return obj.get_class().get_name()
    except Exception:  # noqa: BLE001
        return None


def _num(x):
    """A finite float, or None. Never returns 0.0 as a stand-in for unreadable."""
    try:
        f = float(x)
    except Exception:  # noqa: BLE001
        return None
    return f if math.isfinite(f) else None


def _enum_name(v):
    """A JSON-safe name for an enum-ish value, or None."""
    if v is None:
        return None
    for attr in ("name", "value"):
        try:
            got = getattr(v, attr)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(got, (str, int)) and not isinstance(got, bool):
            return got
    try:
        return str(v)
    except Exception:  # noqa: BLE001
        return None


def _actor_bounds(actor):
    """(origin, extent, api_used, error) via Actor.get_actor_bounds.

    ASSUMED symbol: ``get_actor_bounds(only_colliding, include_from_child_actors)``
    (UE 5.8 Actor.h:1610). The two-argument form is tried first and the one-argument
    form is the fallback, because a signature drift must degrade to a recorded
    reason rather than to a missing bounds record that reads like "no bounds here".
    """
    last = None
    for args, label in (((False, True), "Actor.get_actor_bounds(False, True)"),
                        ((False,), "Actor.get_actor_bounds(False)")):
        try:
            res = actor.get_actor_bounds(*args)
        except Exception as exc:  # noqa: BLE001
            last = "{}: {}: {}".format(label, type(exc).__name__, exc)
            continue
        try:
            origin, extent = res[0], res[1]
        except Exception as exc:  # noqa: BLE001
            last = "{} returned an unexpected shape {!r}: {}".format(label, type(res).__name__, exc)
            continue
        return _xyz(origin), _xyz(extent), label, None
    return None, None, None, last or "get_actor_bounds is unavailable"


def _component_bounds(comp):
    """(origin, extent, sphere_radius, error) via SystemLibrary.get_component_bounds.

    ASSUMED symbol: returns a 3-tuple (origin, extent, radius)
    (UE 5.8 KismetSystemLibrary.h:1756).
    """
    try:
        res = unreal.SystemLibrary.get_component_bounds(comp)
    except Exception as exc:  # noqa: BLE001
        return None, None, None, "get_component_bounds: {}: {}".format(type(exc).__name__, exc)
    try:
        origin, extent, radius = res[0], res[1], res[2]
    except Exception as exc:  # noqa: BLE001
        return None, None, None, "get_component_bounds returned an unexpected shape: {}".format(exc)
    return _xyz(origin), _xyz(extent), _num(radius), None


def _primitive_components(actor):
    """(components, error). Never returns [] to mean "could not enumerate"."""
    try:
        prim_cls = unreal.PrimitiveComponent
    except Exception as exc:  # noqa: BLE001
        return None, "unreal.PrimitiveComponent is not reflected: {}".format(exc)
    try:
        comps = actor.get_components_by_class(prim_cls)
    except Exception as exc:  # noqa: BLE001
        return None, "get_components_by_class: {}: {}".format(type(exc).__name__, exc)
    try:
        return list(comps), None
    except Exception as exc:  # noqa: BLE001
        return None, "component list is not iterable: {}".format(exc)


def _unpack_out(res):
    """UE Python returns (ReturnValue, OutParam) when a UFUNCTION has both.

    Returns (return_value_or_None, out_param_or_None). Both are None when the shape
    is not one this code recognises — an unrecognised shape must not be read as a
    miss, so the caller records it as unobserved.
    """
    if isinstance(res, bool):
        return res, None
    if isinstance(res, (tuple, list)) and len(res) >= 2:
        first = res[0]
        return (first if isinstance(first, bool) else None), res[1]
    return None, None


def _trace_channel():
    """The visibility TraceTypeQuery, or None. ASSUMED enum member name."""
    for name in ("TRACE_TYPE_QUERY1", "TraceTypeQuery1"):
        try:
            return getattr(unreal.TraceTypeQuery, name)
        except Exception:  # noqa: BLE001
            continue
    return None


def _draw_debug_none():
    for name in ("NONE", "None_", "NO_DEBUG"):
        try:
            return getattr(unreal.DrawDebugTrace, name)
        except Exception:  # noqa: BLE001
            continue
    return None


def _object_type(index):
    """OBJECT_TYPE_QUERY<index> (1 = WorldStatic, 2 = WorldDynamic), or None."""
    for name in ("OBJECT_TYPE_QUERY{}".format(index), "ObjectTypeQuery{}".format(index)):
        try:
            return getattr(unreal.ObjectTypeQuery, name)
        except Exception:  # noqa: BLE001
            continue
    return None


def _break_hit(hit):
    """Best-effort raw fields out of an FHitResult.

    HitResult members are bare UPROPERTY() with no BlueprintReadOnly, so they are
    NOT Python attributes; ``GameplayStatics.break_hit_result`` is the only route
    (UE 5.8 GameplayStatics.h:1077). ASSUMED: an 18-tuple whose members are, in
    order, blocking_hit, initial_overlap, time, distance, location, impact_point,
    normal, impact_normal, phys_mat, hit_actor, hit_component, hit_bone_name,
    bone_name, hit_item, element_index, face_index, trace_start, trace_end.

    Every field is extracted defensively and independently: a tuple of a different
    length yields Nones plus a reason, never a wrong-field misread.
    """
    out = {"blocking_hit": None, "distance": None, "location": None,
           "impact_point": None, "impact_normal": None,
           "hit_actor_path": None, "hit_component_path": None}
    try:
        parts = unreal.GameplayStatics.break_hit_result(hit)
    except Exception as exc:  # noqa: BLE001
        return out, "break_hit_result: {}: {}".format(type(exc).__name__, exc)
    try:
        parts = list(parts)
    except Exception as exc:  # noqa: BLE001
        return out, "break_hit_result returned a non-sequence: {}".format(exc)
    if len(parts) < 18:
        return out, ("break_hit_result returned {} field(s), expected 18 — the "
                     "field order cannot be trusted, so nothing was read".format(len(parts)))

    def _at(i, fn):
        try:
            return fn(parts[i])
        except Exception:  # noqa: BLE001
            return None

    out["blocking_hit"] = _at(0, lambda v: bool(v) if isinstance(v, bool) else None)
    out["distance"] = _at(3, _num)
    out["location"] = _at(4, _xyz)
    out["impact_point"] = _at(5, _xyz)
    out["impact_normal"] = _at(7, _xyz)
    out["hit_actor_path"] = _at(9, lambda v: _path_of(v) if v is not None else None)
    out["hit_component_path"] = _at(10, lambda v: _path_of(v) if v is not None else None)
    return out, None


def _line_trace(raw, world, ident, start, end, purpose):
    """Run ONE line trace and file a raw ``trace`` record. Returns the record.

    ``hit`` is tri-state: True/False when the engine answered, None when the call or
    its return shape could not be read. A None here must never be counted as a miss.

    ASSUMED symbol: ``SystemLibrary.line_trace_single(world_context, start, end,
    trace_channel, trace_complex, actors_to_ignore, draw_debug_type, ignore_self)``
    returning ``(bool, FHitResult)``.
    """
    rec = {
        "purpose": purpose,
        "api": "unreal.SystemLibrary.line_trace_single",
        "channel": "TraceTypeQuery1(Visibility)",
        "trace_complex": True,
        "start": start,
        "end": end,
        "hit": None,
        "blocking_hit": None,
        "distance": None,
        "impact_point": None,
        "impact_normal": None,
        "hit_actor_path": None,
        "hit_component_path": None,
        "collection_ok": False,
        "errors": [],
    }
    raw["trace"][ident] = rec
    channel, debug = _trace_channel(), _draw_debug_none()
    if channel is None or debug is None:
        rec["errors"].append("TraceTypeQuery/DrawDebugTrace enum members are not reflected "
                             "under any name this script knows; no trace was attempted")
        return rec
    if not (_finite_vec3(start) and _finite_vec3(end)):
        rec["errors"].append("trace endpoints are not finite vec3s; no trace was attempted")
        return rec
    try:
        res = unreal.SystemLibrary.line_trace_single(
            world, unreal.Vector(start[0], start[1], start[2]),
            unreal.Vector(end[0], end[1], end[2]), channel, True, [], debug, True)
    except Exception as exc:  # noqa: BLE001
        rec["errors"].append("line_trace_single: {}: {}".format(type(exc).__name__, exc))
        return rec
    hit, out_hit = _unpack_out(res)
    if hit is None:
        rec["errors"].append("line_trace_single returned an unrecognised shape {!r}; the "
                             "hit/miss answer was NOT read".format(type(res).__name__))
        return rec
    rec["hit"] = bool(hit)
    rec["collection_ok"] = True
    if out_hit is not None:
        fields, err = _break_hit(out_hit)
        for k, v in fields.items():
            rec[k] = v
        if err:
            rec["errors"].append(err)
    else:
        rec["errors"].append("no FHitResult out-parameter was returned; only the hit "
                             "boolean was observed")
    return rec


def _capsule_overlap_actor_paths(world, center, radius, half_height, object_type_index):
    """(actor_path_list, error). None (not []) when the query could not be run.

    ASSUMED symbol: ``SystemLibrary.capsule_overlap_actors(world_context, center,
    radius, half_height, object_types, actor_class_filter, actors_to_ignore)``
    returning ``(bool, [Actor])``.
    """
    otype = _object_type(object_type_index)
    if otype is None:
        return None, "ObjectTypeQuery{} is not reflected".format(object_type_index)
    if not _finite_vec3(center):
        return None, "capsule centre is not a finite vec3"
    try:
        res = unreal.SystemLibrary.capsule_overlap_actors(
            world, unreal.Vector(center[0], center[1], center[2]),
            float(radius), float(half_height), [otype], None, [])
    except Exception as exc:  # noqa: BLE001
        return None, "capsule_overlap_actors: {}: {}".format(type(exc).__name__, exc)
    _ok, actors = _unpack_out(res)
    if actors is None:
        if isinstance(res, (tuple, list)) and len(res) == 1:
            actors = res[0]
        else:
            return None, ("capsule_overlap_actors returned an unrecognised shape {!r}; "
                          "the overlap set was NOT read".format(type(res).__name__))
    try:
        return sorted(p for p in (_path_of(a) for a in actors) if p), None
    except Exception as exc:  # noqa: BLE001
        return None, "capsule_overlap_actors result is not iterable: {}".format(exc)


def _all_level_actors():
    """(actors, error). None (not []) when enumeration itself failed."""
    last = None
    try:
        return list(unreal.EditorActorSubsystem().get_all_level_actors()), None
    except Exception as exc:  # noqa: BLE001
        last = "EditorActorSubsystem().get_all_level_actors: {}: {}".format(
            type(exc).__name__, exc)
    try:
        sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        return list(sub.get_all_level_actors()), None
    except Exception as exc:  # noqa: BLE001
        return None, "{}; get_editor_subsystem fallback: {}: {}".format(
            last, type(exc).__name__, exc)


def _dirty_packages(getter_name):
    """(sorted package names, error). None when the query could not be run.

    ``UPackage.is_dirty()`` is NOT exposed to Python, so dirtiness is observable
    ONLY as membership of these engine-owned sets — there is no per-package
    predicate to fall back on. An unreadable set is therefore recorded as None; an
    empty list here would be a claim that nothing is dirty, which is exactly the
    lie this file exists to avoid.
    """
    try:
        getter = getattr(unreal.EditorLoadingAndSavingUtils, getter_name)
    except Exception as exc:  # noqa: BLE001
        return None, "EditorLoadingAndSavingUtils.{} is not reflected: {}".format(
            getter_name, exc)
    try:
        pkgs = getter()
    except Exception as exc:  # noqa: BLE001
        return None, "{}: {}: {}".format(getter_name, type(exc).__name__, exc)
    try:
        return sorted(n for n in (_pkg_name(p) for p in pkgs) if n), None
    except Exception as exc:  # noqa: BLE001
        return None, "{} result is not iterable: {}".format(getter_name, exc)


def _pkg_name(pkg):
    try:
        return pkg.get_name()
    except Exception:  # noqa: BLE001
        return _path_of(pkg)


def _is_in_pie():
    """True/False/None. None means the PIE state could not be read.

    Spawn and destroy silently NO-OP during PIE, so a spawn attempted without this
    answer could report a placement that never existed. Unknown is treated as
    "do not spawn" by the ledger.
    """
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        return bool(les.is_in_play_in_editor())
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# spawn ledger — nothing may be created without being tracked and then observed
# to be gone.
# --------------------------------------------------------------------------- #
class _SpawnLedger:
    """Tracks every object THIS operation creates, and re-observes its removal.

    The survey as it stands spawns NOTHING (marker clearance is trace-probed, never
    placed), so ``owned_paths()`` is legitimately empty and that emptiness is a
    measurement, not a default. The ledger exists so that any future spawn is
    physically unable to escape the pre/post comparison: it spawns transiently only
    (``transient=True`` is the only safe spawn — a ScopedEditorTransaction cancel
    does NOT restore a package's dirty flag, and no Python API reads or clears one),
    it refuses to spawn when PIE state is unknown or active, and after destroying it
    RE-READS the level to confirm the object is gone rather than trusting
    ``destroy_actor``'s return.
    """

    def __init__(self, raw):
        self.raw = raw
        self.spawned = []          # [(ident, actor)]
        self.policy = ("transient-only; this pass spawns nothing (marker clearance is "
                       "trace-probed, never placed)")

    def owned_paths(self):
        """Paths of objects still owned by this operation. [] is a measurement."""
        out = []
        for ident, actor in self.spawned:
            p = _path_of(actor)
            out.append(p if p else "temporary_placement#{}".format(ident))
        return sorted(out)

    def spawn_transient(self, world, actor_class, location, ident):
        """Spawn ONE tracked transient actor, or file an honest refusal record."""
        rec = {
            "ident": ident,
            "requested_location": location,
            "spawn_attempted": False,
            "spawn_ok": False,
            "transient": True,
            "path_name": None,
            "destroy_attempted": False,
            "destroy_returned": None,
            "absent_after_cleanup": None,
            "collection_ok": False,
            "errors": [],
        }
        self.raw["temporary_placement"][ident] = rec
        pie = _is_in_pie()
        if pie is not False:
            rec["errors"].append(
                "refused to spawn: play-in-editor state is {!r} and spawn/destroy "
                "silently no-op during PIE".format(pie))
            return rec
        if not _finite_vec3(location):
            rec["errors"].append("refused to spawn: location is not a finite vec3")
            return rec
        rec["spawn_attempted"] = True
        try:
            sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            actor = sub.spawn_actor_from_class(
                actor_class, unreal.Vector(location[0], location[1], location[2]),
                unreal.Rotator(0.0, 0.0, 0.0), transient=True)
        except Exception as exc:  # noqa: BLE001
            rec["errors"].append("spawn_actor_from_class: {}: {}".format(
                type(exc).__name__, exc))
            return rec
        if actor is None:
            rec["errors"].append("spawn_actor_from_class returned None")
            return rec
        rec["spawn_ok"] = True
        rec["path_name"] = _path_of(actor)
        rec["collection_ok"] = True
        self.spawned.append((ident, actor))
        return rec

    def cleanup(self):
        """Destroy everything spawned, then RE-OBSERVE that it is gone.

        The removal is confirmed against a fresh level enumeration; ``destroy_actor``
        returning True is recorded as a separate raw field and is never taken as the
        proof on its own.
        """
        if not self.spawned:
            return
        for ident, actor in list(self.spawned):
            rec = self.raw["temporary_placement"].get(ident) or {}
            rec["destroy_attempted"] = True
            try:
                sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                rec["destroy_returned"] = bool(sub.destroy_actor(actor))
            except Exception as exc:  # noqa: BLE001
                rec.setdefault("errors", []).append(
                    "destroy_actor: {}: {}".format(type(exc).__name__, exc))
        after, err = _all_level_actors()
        if after is None:
            for ident, _actor in self.spawned:
                rec = self.raw["temporary_placement"].get(ident) or {}
                rec["absent_after_cleanup"] = None
                rec.setdefault("errors", []).append(
                    "could not re-enumerate the level to witness removal: {}".format(err))
            return
        present = set(p for p in (_path_of(a) for a in after) if p)
        for ident, _actor in self.spawned:
            rec = self.raw["temporary_placement"].get(ident) or {}
            path = rec.get("path_name")
            rec["absent_after_cleanup"] = (path not in present) if path else None
        self.spawned = []


# --------------------------------------------------------------------------- #
# mutation snapshots
# --------------------------------------------------------------------------- #
def _inventory(stage, ledger, world_package):
    """One RAW mutation snapshot. Emitted verbatim; nothing here is a verdict.

    ``collection_ok`` is True only when the actor set AND both dirty-package sets
    were actually read. A snapshot whose collection failed proves nothing, and the
    evidence model's cleanup sufficiency check rejects it for exactly that reason
    (scene_survey_evidence.py:369).
    """
    rec = {
        "stage": stage,
        "collector": "scene_survey_far_side._inventory",
        "collection_ok": False,
        "map_identity": world_package,
        "package_identity": world_package,
        "actor_paths": None,
        "actor_path_count": None,
        "dirty_map_packages": None,
        "dirty_content_packages": None,
        "dirty_packages": None,
        "operation_owned_actor_paths": ledger.owned_paths(),
        "spawn_policy": ledger.policy,
        "dirtiness_api_note": ("UPackage.is_dirty() is not exposed to Python; dirtiness "
                               "is observable only as membership of the engine's dirty "
                               "package sets"),
        "errors": [],
    }
    actors, actors_err = _all_level_actors()
    if actors is None:
        rec["errors"].append(actors_err)
    else:
        paths = sorted(p for p in (_path_of(a) for a in actors) if p)
        rec["actor_paths"] = paths
        rec["actor_path_count"] = len(paths)

    maps, map_err = _dirty_packages("get_dirty_map_packages")
    if maps is None:
        rec["errors"].append(map_err)
    else:
        rec["dirty_map_packages"] = maps

    content, content_err = _dirty_packages("get_dirty_content_packages")
    if content is None:
        rec["errors"].append(content_err)
    else:
        rec["dirty_content_packages"] = content

    if maps is not None and content is not None:
        rec["dirty_packages"] = sorted(set(maps) | set(content))

    rec["collection_ok"] = (rec["actor_paths"] is not None
                            and rec["dirty_packages"] is not None)
    return rec


# --------------------------------------------------------------------------- #
# structured spatial collectors
# --------------------------------------------------------------------------- #
def _collect_actor_records(raw, actors, center, radius):
    """Per-actor + per-component RAW records, replacing the stdout-regex channel.

    Mirrors the C++ enumerator's radius filter (SceneSurvey.cpp:49) so the two
    channels are describing the same population — but measures everything in Python
    from the live objects, so it is an INDEPENDENT observation rather than a reparse
    of the same log line.
    """
    if actors is None:
        return
    for index, actor in enumerate(actors):
        path = _path_of(actor)
        ident = path if path else "actor_{:05d}".format(index)
        loc = _xyz(_safe(lambda: actor.get_actor_location()))
        if loc is None:
            raw["actor"][ident] = {
                "path_name": path, "class_name": _class_of(actor),
                "location": None, "rotation": None, "scale": None,
                "bounds_origin": None, "bounds_extent": None, "bounds_api": None,
                "distance_to_anchor_cm": None, "component_refs": [],
                "collection_ok": False,
                "errors": ["actor location could not be read; the radius filter could "
                           "not be applied and no bounds were measured"],
            }
            continue
        dist = math.sqrt(sum((loc[i] - center[i]) ** 2 for i in range(3)))
        if dist > radius:
            continue
        origin, extent, api, berr = _actor_bounds(actor)
        rec = {
            "path_name": path,
            "class_name": _class_of(actor),
            "location": loc,
            "rotation": _pyr(_safe(lambda: actor.get_actor_rotation())),
            "scale": _xyz(_safe(lambda: actor.get_actor_scale3d())),
            "bounds_origin": origin,
            "bounds_extent": extent,
            "bounds_api": api,
            "distance_to_anchor_cm": dist,
            "component_refs": [],
            "collection_ok": bool(path and extent is not None),
            "errors": [],
        }
        if berr:
            rec["errors"].append(berr)
        raw["actor"][ident] = rec

        comps, cerr = _primitive_components(actor)
        if comps is None:
            rec["errors"].append(cerr)
            continue
        for ci, comp in enumerate(comps):
            cpath = _path_of(comp)
            cident = cpath if cpath else "{}::component_{:04d}".format(ident, ci)
            corigin, cextent, cradius, cberr = _component_bounds(comp)
            crec = {
                "actor_ref": "actor#{}".format(ident),
                "path_name": cpath,
                "class_name": _class_of(comp),
                "collision_enabled": _enum_name(
                    _safe(lambda: comp.get_editor_property("collision_enabled"))),
                "bounds_origin": corigin,
                "bounds_extent": cextent,
                "bounds_sphere_radius": cradius,
                "collection_ok": bool(cpath and cextent is not None),
                "errors": [],
            }
            if cberr:
                crec["errors"].append(cberr)
            raw["component"][cident] = crec
            rec["component_refs"].append("component#{}".format(cident))


def _safe(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


def _collect_marker_record(raw, world, index, location, probe_returned):
    """RAW observations for ONE temporary-marker candidate.

    The C++ ``ProbeTempMarker`` returns a single bool and logs the rest; the
    per-candidate detail exists nowhere the near side can reach except by scraping
    that log line. So the individual trace and overlap queries are re-run here in
    Python and filed as raw records the assembler can derive from.

    ``grounded`` / ``footprint`` / ``overlap`` / ``capsule_clear`` are NULLABLE
    restatements of those atoms, carried under the names the raw-bundle contract
    reads (scene_survey_evidence.py:316,322,333,346). Each is None whenever its
    underlying observation was not collected. ``accepted`` is not recomputed here at
    all — it is the value the compiled primitive RETURNED.
    """
    ident = "marker_{:03d}".format(index)
    rec = {
        "index": index,
        "location": location,
        "capsule_radius": MARKER_CAPSULE_RADIUS,
        "capsule_half_height": MARKER_CAPSULE_HALF_HEIGHT,
        "probe_temp_marker_returned": probe_returned,
        "accepted": probe_returned,
        "ground_trace_ref": None,
        "ground_impact_z": None,
        "footprint_trace_refs": [],
        "footprint_trace_hits": [],
        "capsule_center": None,
        "capsule_overlap_static_actor_paths": None,
        "capsule_overlap_dynamic_actor_paths": None,
        "grounded": None,
        "footprint": None,
        "overlap": None,
        "capsule_clear": None,
        "collection_ok": False,
        "errors": [],
    }
    raw["marker"][ident] = rec
    if world is None or not _finite_vec3(location):
        rec["errors"].append("no world or non-finite candidate location; no trace was run")
        return rec

    # Ground contact. Reach matches the C++ probe (SceneSurvey.cpp:204-207) so the
    # two channels are asking the same question of the same geometry.
    gid = "{}::ground".format(ident)
    ground = _line_trace(raw, world, gid,
                         [location[0], location[1], location[2] + 100.0],
                         [location[0], location[1], location[2] - 3000.0],
                         "marker ground contact")
    rec["ground_trace_ref"] = "trace#{}".format(gid)
    if ground["hit"] is not None:
        rec["grounded"] = bool(ground["hit"])
    ip = ground.get("impact_point")
    ground_z = ip[2] if _finite_vec3(ip) else None
    rec["ground_impact_z"] = ground_z
    if ground_z is None:
        ground_z = location[2]

    # Four-corner footprint traces at the capsule radius (SceneSurvey.cpp:212-221).
    offsets = ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0))
    hits = []
    for ci, (ox, oy) in enumerate(offsets):
        fid = "{}::footprint_{}".format(ident, ci)
        ft = _line_trace(raw, world, fid,
                         [location[0] + ox * MARKER_CAPSULE_RADIUS,
                          location[1] + oy * MARKER_CAPSULE_RADIUS, ground_z + 100.0],
                         [location[0] + ox * MARKER_CAPSULE_RADIUS,
                          location[1] + oy * MARKER_CAPSULE_RADIUS, ground_z - 200.0],
                         "marker footprint corner")
        rec["footprint_trace_refs"].append("trace#{}".format(fid))
        hits.append(ft["hit"])
    rec["footprint_trace_hits"] = hits
    if all(h is not None for h in hits):
        rec["footprint"] = all(bool(h) for h in hits) and (rec["grounded"] is True)

    # Capsule clearance against static and dynamic geometry (SceneSurvey.cpp:224-229).
    cap_ctr = [location[0], location[1], ground_z + MARKER_CAPSULE_HALF_HEIGHT + 2.0]
    rec["capsule_center"] = cap_ctr if _finite_vec3(cap_ctr) else None
    static_paths, serr = _capsule_overlap_actor_paths(
        world, cap_ctr, MARKER_CAPSULE_RADIUS, MARKER_CAPSULE_HALF_HEIGHT, 1)
    dynamic_paths, derr = _capsule_overlap_actor_paths(
        world, cap_ctr, MARKER_CAPSULE_RADIUS, MARKER_CAPSULE_HALF_HEIGHT, 2)
    rec["capsule_overlap_static_actor_paths"] = static_paths
    rec["capsule_overlap_dynamic_actor_paths"] = dynamic_paths
    for e in (serr, derr):
        if e:
            rec["errors"].append(e)
    if static_paths is not None and dynamic_paths is not None:
        rec["overlap"] = bool(static_paths) or bool(dynamic_paths)
        rec["capsule_clear"] = not rec["overlap"]

    rec["collection_ok"] = (rec["grounded"] is not None
                            and rec["footprint"] is not None
                            and rec["capsule_clear"] is not None)
    return rec


def _record_world(raw, world, package_name):
    """RAW identity of the world that is actually open."""
    raw["world"]["observed"] = {
        "package_name": package_name,
        "world_object_path": _path_of(world),
        "world_class_name": _class_of(world),
        "is_package_external": _safe(lambda: bool(world.is_package_external())),
        "is_in_play_in_editor": _is_in_pie(),
        "collection_ok": package_name is not None,
        "collector": "scene_survey_far_side._record_world",
    }


def _record_proxy_unobserved(raw):
    """MeshForge runtime proxies are NOT observable in an editor pass.

    They spawn at game BeginPlay, so a -nullrhi editor load has nothing to look at.
    This is filed as an explicitly unobserved record with a reason — value None, not
    a zero. A ``proxy_owners: 0`` here would be indistinguishable from a real
    measurement of an empty set.
    """
    raw["proxy"]["runtime_proxies"] = {
        "value": None,
        "collection_ok": False,
        "collector": "scene_survey_far_side._record_proxy_unobserved",
        "stage": ST_OBSERVE,
        "detail": ("MeshForge runtime proxies spawn at game BeginPlay; an editor "
                   "-nullrhi load never reaches BeginPlay, so neither their presence "
                   "nor their absence was observed in this pass"),
    }


def _new_raw_bundle():
    """The empty raw bundle. Kinds are pre-created so refs address a real container."""
    return {
        "schema_version": RAW_BUNDLE_SCHEMA,
        "world": {},
        "actor": {},
        "component": {},
        "trace": {},
        "marker": {},
        "proxy": {},
        "temporary_placement": {},
        "inventory": {},
    }


# --------------------------------------------------------------------------- #
# subject handling
# --------------------------------------------------------------------------- #
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
    for a in actors or ():
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
                        want, len(actors) if actors is not None else 0))
        loc = _xyz(_safe(lambda: actor.get_actor_location()))
        if loc is None:
            return (False, None, None,
                    "anchor_object_path {!r} resolved but its location could not be read "
                    "as a finite vec3 — an unreadable anchor is not a verified one".format(
                        want))
        return (True, loc, actor.get_path_name(),
                "resolved the caller's exact object path")
    return (False, None, None,
            "unknown anchor_mode {!r} — WorldForge does not interpret anchor modes it "
            "was not given".format(mode))


# --------------------------------------------------------------------------- #
# the document
# --------------------------------------------------------------------------- #
def _new_doc():
    """The far-side document skeleton.

    BOTH the main path and the module-level fatal handler build their document from
    THIS function, so key-set parity between them is structural rather than a pair
    of literals that have to be kept in step by hand. A near side that reads a key
    present in one document and absent in the other would see a KeyError on exactly
    the runs where evidence matters most.

    Nothing here touches the Unreal API: the skeleton must be constructible even in
    the fatal path, where the reason we are here may be that the API is unusable.
    """
    return {
        "operation_id": OPERATION_ID,
        "map": None,
        # The caller's subject, echoed so the near side can bind request<->result.
        "subject_id": None,
        "subject_kind": None,
        "anchor_mode": None,
        "subject_resolved_by": None,
        "subject_source": None,
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
        "observed_engine_version": None,
        "resolved_uproject": None,
        "actor_count": None,
        "support_total": None,
        "marker_total": 0,
        "marker_accepted": 0,
        # capture is OPT-IN and is not runnable in a -nullrhi pass either way.
        "captures_requested": list(CAPTURES),
        "camera_capture_ran": False,
        "camera_capture_reason": None,
        "proxy_pass_ran": False,
        "proxy_pass_reason": "MeshForge proxies spawn at game BeginPlay; needs a -game pass",
        "survey_statics_available": False,
        # ---- structured RAW channel (see the module docstring) -------------------
        "raw_evidence_schema": RAW_BUNDLE_SCHEMA,
        "raw_evidence": _new_raw_bundle(),
        # Collection problems that are NOT survey failures. Kept OUT of "error" on
        # purpose: "error" means the survey must not be believed, while these mean
        # one measurement is missing and the near side decides what that costs.
        "collection_errors": [],
        "environment_inputs": {
            "radius_cm": RADIUS,
            "step_cm": STEP,
            "markers_requested": MARKERS,
            "parse_errors": list(ENV_PARSE_ERRORS),
        },
        "error": None,
        "traceback": None,
    }


def _capture_reason():
    return ("{} capture(s) requested but this pass cannot render: an RHI is required "
            "(-nullrhi)".format(len(CAPTURES)) if CAPTURES else
            "no captures were requested by the caller (capture is opt-in)")


def _note(doc, collector, detail):
    """File a collection problem without pretending the whole survey failed."""
    if detail:
        doc["collection_errors"].append({"collector": collector, "detail": str(detail)})


def main():
    subject, subject_source, subject_error = _load_subject()
    subject = subject if isinstance(subject, dict) else {}
    map_path = subject.get("map_asset_path") or ""

    doc = _new_doc()
    doc["map"] = map_path
    doc["subject_id"] = subject.get("subject_id")
    doc["subject_kind"] = subject.get("subject_kind")
    doc["anchor_mode"] = subject.get("anchor_mode")
    doc["subject_resolved_by"] = subject.get("resolved_by")
    doc["subject_source"] = subject_source
    doc["camera_capture_reason"] = _capture_reason()
    doc["error"] = subject_error
    for e in ENV_PARSE_ERRORS:
        _note(doc, "env", e)
    # These three used to sit inside the document literal, outside every try: a
    # single reflection failure there aborted main() before any document existed.
    doc["observed_engine_version"] = _safe(lambda: unreal.SystemLibrary.get_engine_version())
    doc["resolved_uproject"] = _safe(lambda: unreal.Paths.get_project_file_path())
    doc["survey_statics_available"] = bool(_safe(
        lambda: hasattr(unreal, "SceneSurveyStatics")))

    raw = doc["raw_evidence"]
    ledger = _SpawnLedger(raw)
    _record_proxy_unobserved(raw)

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
        _record_world(raw, world, doc["observed_world_package"])
        actors, actors_err = _all_level_actors()
        if actors is None:
            _note(doc, "_all_level_actors", actors_err)
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
            # ---- PRE snapshot: taken after the anchor binds and BEFORE any
            # primitive runs, so it is a true "as we found it" state. -----------
            raw["inventory"]["pre"] = _inventory(ST_ANCHOR_BIND, ledger,
                                                 doc["observed_world_package"])
            for e in raw["inventory"]["pre"]["errors"]:
                _note(doc, "inventory.pre", e)

            ctr = unreal.Vector(loc[0], loc[1], loc[2])
            stat = unreal.SceneSurveyStatics
            doc["actor_count"] = int(stat.enumerate_survey_actors(world, ctr, RADIUS))
            doc["support_total"] = int(stat.sample_survey_support(world, ctr, RADIUS, STEP))

            # ---- structured per-actor / per-component records ------------------
            # An INDEPENDENT Python-side measurement of the same population the C++
            # enumerator walked; the near side no longer has to scrape WF_SURVEY_ACTOR
            # / WF_SURVEY_COMPONENT out of editor log text to see any of this.
            try:
                _collect_actor_records(raw, actors, loc, RADIUS)
            except Exception as exc:  # noqa: BLE001
                _note(doc, "_collect_actor_records", "{}: {}".format(type(exc).__name__, exc))

            accepted = 0
            for i in range(max(0, MARKERS)):
                cand = unreal.Vector(ctr.x + (i + 1) * STEP, ctr.y, ctr.z)
                cand_loc = [float(cand.x), float(cand.y), float(cand.z)]
                probe_returned = None
                try:
                    probe_returned = bool(stat.probe_temp_marker(
                        world, cand, MARKER_CAPSULE_RADIUS, MARKER_CAPSULE_HALF_HEIGHT))
                except Exception as exc:  # noqa: BLE001
                    _note(doc, "probe_temp_marker",
                          "candidate {}: {}: {}".format(i, type(exc).__name__, exc))
                if probe_returned:
                    accepted += 1
                try:
                    mrec = _collect_marker_record(raw, world, i, cand_loc, probe_returned)
                    for e in mrec["errors"]:
                        _note(doc, "marker_{:03d}".format(i), e)
                except Exception as exc:  # noqa: BLE001
                    _note(doc, "_collect_marker_record",
                          "candidate {}: {}: {}".format(i, type(exc).__name__, exc))
            doc["marker_total"] = max(0, MARKERS)
            doc["marker_accepted"] = accepted

            # ---- cleanup, then the POST snapshot -------------------------------
            # Nothing was spawned (marker clearance is trace-probed), so the ledger
            # has nothing to remove — and that emptiness is measured, not assumed.
            try:
                ledger.cleanup()
            except Exception as exc:  # noqa: BLE001
                _note(doc, "spawn_ledger.cleanup", "{}: {}".format(type(exc).__name__, exc))
            raw["inventory"]["post"] = _inventory(ST_CLEANUP, ledger,
                                                  doc["observed_world_package"])
            for e in raw["inventory"]["post"]["errors"]:
                _note(doc, "inventory.post", e)
    except Exception as e:  # noqa: BLE001  — never fabricate a success
        doc["error"] = "{}: {}".format(type(e).__name__, e)
        doc["traceback"] = traceback.format_exc()

    _write(doc)


def _write(doc):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
    # HAZARD FIXED: this line used subscript access for five keys, so a document
    # missing any of them raised a KeyError AFTER the JSON had already been flushed
    # — the file on disk was fine, the process died anyway, and the near side saw a
    # crash instead of the evidence sitting right there. Logging must never be able
    # to fail a run that already produced its evidence.
    raw = doc.get("raw_evidence") or {}
    _log("wrote survey -> {} (subject={} resolved={} actors={} support={} markers={}/{} "
         "raw: actors={} components={} traces={} markers={} inventories={} "
         "collection_errors={} err={})".format(
             OUT, doc.get("subject_id"), doc.get("subject_resolved"),
             doc.get("actor_count"), doc.get("support_total"),
             doc.get("marker_accepted"), doc.get("marker_total"),
             len(raw.get("actor") or {}), len(raw.get("component") or {}),
             len(raw.get("trace") or {}), len(raw.get("marker") or {}),
             sorted((raw.get("inventory") or {}).keys()),
             len(doc.get("collection_errors") or []), doc.get("error")))


try:
    main()
except Exception as _fatal:  # noqa: BLE001
    # Even a failure BEFORE/AROUND main's own handler must leave evidence: a far
    # side that dies silently is indistinguishable from one that never started,
    # and the near side would have nothing to report but a timeout. The skeleton is
    # built by _new_doc(), so it CANNOT drift out of key-set parity with the main
    # document.
    if OUT:
        try:
            _fatal_doc = _new_doc()
            _fatal_doc["camera_capture_reason"] = "far side aborted before the capture question"
            _fatal_doc["proxy_pass_reason"] = "far side aborted"
            _fatal_doc["error"] = "{}: {}".format(type(_fatal).__name__, _fatal)
            _fatal_doc["traceback"] = traceback.format_exc()
            _write(_fatal_doc)
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
