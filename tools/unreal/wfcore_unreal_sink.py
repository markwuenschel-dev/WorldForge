"""wfcore_unreal_sink.py -- the REAL MutationSink, run INSIDE the editor.

WHAT THIS IS
------------
Core's transaction executor (tools/wfcore/transaction/executor.py) is complete and
tested against ``InMemoryMutationSink``. This file is the other implementation of
that same four-method interface -- the one whose ``apply`` moves actual actors in an
actual Unreal world. Nothing about the transaction is reimplemented here: this
script adds ``tools/`` to ``sys.path``, imports ``wfcore.transaction.executor``,
constructs ``UnrealMutationSink``, and calls ``apply_delta`` with it. The bound
enforcement, the single-writer lock, the reverse-order undo, the re-observation and
the five outcomes are all Core's, unchanged, exercised for the first time against a
world that can actually be got wrong.

Run via ``UnrealEditor-Cmd <uproject> -ExecutePythonScript=<this> ...``; the near
side is tools/pipeline/run_wfcore_transaction.py.

WHY EVERY MUTATION KIND CARRIES AN EXPLICIT COMPENSATING ACTION
---------------------------------------------------------------
UE 5.8's Python surface exposes ``unreal.ScopedEditorTransaction`` (a context
manager, with ``.cancel()``) but exposes NO generic ``Undo()``. The engine will
therefore not rewind anything for us, and a sink that assumed it would is a sink
whose rollback is a claim. So each supported kind declares its own inverse:

    kind                compensating action
    ------------------  -----------------------------------------------------
    actor_spawn         destroy the actor this sink spawned (tracked by object
                        handle, not by re-lookup -- a spawn whose labelling
                        failed is still destroyable, and a re-lookup would miss
                        exactly that case)
    actor_transform     restore the location/rotation/scale CAPTURED by observe()
                        before the change

A mutation whose (target_kind, operation) pair maps to no kind in that table has no
inverse, and is REFUSED BEFORE apply_delta is ever called -- WF1279
(CORE_SINK_NO_COMPENSATION). Discovering unrollbackability while unwinding is the
failure this ordering exists to make impossible.

``ScopedEditorTransaction`` IS opened around each apply, because grouping the writes
is the editor-side convention and it costs one guarded call. It is decoration, not
mechanism: ``cancel()`` is never called and the rollback never consults it. (It also
does not restore a package's dirty flag, measured by the v2.6 survey lane -- see
tools/bridge/scene_survey_far_side.py, MUTATION / CLEANUP.)

THE ADDRESS SPACE
-----------------
``delta.py`` has exactly two target kinds, and membership of a bound is EXACT
string comparison, never a prefix or a glob. So an address must be predictable
BEFORE the mutation happens -- otherwise a create could never be declared in a
bound. An actor's UE object path is not predictable (the engine appends
``_0``/``_1`` at spawn), so this sink addresses an actor by the one identity the
caller chooses:

    actor    "<map_package>:<actor_label>"   e.g. "/Game/Maps/_wf_test_lvl:WF_TX_0"
    package  "<package_path>"                e.g. "/Game/Maps/_wf_test_lvl"

The map half of an actor address is checked against the package name of the world
that is ACTUALLY open, read from the live editor. A mutation addressed at a map that
is not loaded is UNMEASURABLE, not absent -- ``observe`` returns
``unmeasured_state`` and Core refuses it (WF1251) rather than spawning into whatever
world happened to be open.

Two actors sharing a label make the address ambiguous. That is also
``unmeasured_state``: a restore point that might belong to either of two actors is
not a restore point.

WHAT ``observe`` RETURNS, AND WHY IT IS THE SAME SHAPE AS ``expected_after_state``
---------------------------------------------------------------------------------
Core computes verification as ``states_equal(expected_after_state,
observed_after_apply)`` over a canonical JSON dump. So the observed payload must
contain exactly the fields a caller can predict, and nothing else. It is:

    {"actor_class": <short reflected class name>,
     "location": [x, y, z], "rotation": [pitch, yaw, roll], "scale": [x, y, z]}

with every number rounded to ``ROUND_DIGITS`` on BOTH the observe path and the
near-side request builder, so float formatting cannot turn a correct mutation into a
verification failure. The actor's object path is deliberately NOT in the payload:
the caller cannot predict it, and including it would make every postcondition
unsatisfiable. It is reported alongside, in the sink's diagnostics.

``actor_class`` is the short name ``UClass.get_name()`` returns ("StaticMeshActor",
"PointLight", "BP_Foo_C"). Class resolution for a spawn is a documented ladder:
``getattr(unreal, name)`` then ``unreal.load_class(None, "/Script/Engine." + name)``.
Blueprint-generated classes are OUT OF SCOPE and say so: a ``_C`` short name cannot
be located without its package, and guessing a package would spawn something the
caller did not ask for.

WHAT COUNTS AS "TOUCHED"
------------------------
``drain_touched`` reports the actor address for every actor this sink wrote. It
reports the MAP PACKAGE only when the sink actually saved the map -- an unsaved
editor-world mutation writes no package, and claiming otherwise would force every
caller to widen its bound for a write that never happened. Saving is opt-in
(``WF_TX_SAVE_MAP=1``); with it on, the map package must appear in the step's
``allowed_packages`` or Core will (correctly) abort on the out-of-bound write.

FAR-SIDE DISCIPLINE (matching tools/bridge/scene_survey_far_side.py)
--------------------------------------------------------------------
Inputs come from environment variables only, parsed defensively -- a bad value
degrades to a documented default plus a recorded parse error, never an exception at
module scope. There is ONE deterministic JSON output file and stdout is never an
evidence channel. Every ``unreal`` call is individually guarded and degrades to
``None`` plus a recorded reason; ``None`` means NOT OBSERVED and is never coerced to
``False``. A top-level catch-all writes a document carrying the traceback, because a
far side that dies silently is indistinguishable from one that never started. The
editor is asked to quit at the end, with a console-command fallback.

ENVIRONMENT CONTRACT
--------------------
    WF_TX_OUT           absolute path for the far-side JSON            (REQUIRED)
    WF_TX_REQUEST       absolute path to the request JSON
                        {operation_id, bounds, mutations, evidence_refs}
    WF_TX_REQUEST_JSON  the same object INLINE; used only when WF_TX_REQUEST is
                        unset/empty. Exactly one channel answers and the winner is
                        echoed as "request_source".
    WF_TX_MAP           /Game/... level to load before observing        (REQUIRED
                        for any actor mutation; a blank value loads nothing)
    WF_TX_REPO_ROOT     repo root for Core's single-writer lock + delta journal
                        (default: three levels above this file)
    WF_TX_OPERATION_ID  operation id; falls back to the request's, then to a
                        documented default
    WF_TX_SAVE_MAP      "1" to save the map after each mutation and after each
                        compensation (default "0" -- do not write to disk)
    WF_TX_OBSERVE_AFTER "0" to skip post-observation; Core then reports
                        committed_unverified, never a plain commit (default "1")
    WF_TX_TOOLS         override for the tools/ directory put on sys.path
"""

import json
import math
import os
import sys
import traceback

FAR_SIDE_SCHEMA = "wf.core.unreal_sink_far_side.v1"

# Failure codes, LITERAL, under the same constraint the survey far side documents:
# this file runs inside the UE interpreter and an ImportError at module scope would
# kill it before any evidence could be written. Each is declared in
# tools/pipeline/failure_codes.py at the cited line.
FC_SINK_UNAVAILABLE = "WF1276_CORE_SINK_UNAVAILABLE"          # failure_codes.py:1377
FC_OBSERVATION_FAILED = "WF1277_CORE_SINK_OBSERVATION_FAILED"  # :1378
FC_APPLY_FAILED = "WF1278_CORE_SINK_APPLY_FAILED"              # :1379
FC_NO_COMPENSATION = "WF1279_CORE_SINK_NO_COMPENSATION"        # :1383
FC_SAVE_FAILED = "WF1280_CORE_SINK_SAVE_FAILED"                # :1384
FC_RELOAD_MISMATCH = "WF1281_CORE_SINK_RELOAD_MISMATCH"        # :1385

# Numbers are rounded to this many decimals on EVERY path that produces a payload,
# so a caller's declared postcondition and this sink's observation of it are
# comparable by exact canonical JSON. Core compares states with
# `delta.states_equal`, which is a string comparison of a canonical dump -- an
# unrounded 100.00000000000001 would read as a violated postcondition and roll back
# a mutation that was in fact correct.
ROUND_DIGITS = 3

# --------------------------------------------------------------------------- #
# mutation vocabulary. SMALL and fully correct, rather than broad and shaky.
# --------------------------------------------------------------------------- #
KIND_ACTOR_SPAWN = "actor_spawn"
KIND_ACTOR_TRANSFORM = "actor_transform"

# (target_kind, operation) -> kind. The ONE place the vocabulary is decided, so the
# preflight refusal and the apply dispatch cannot disagree about what is supported.
MUTATION_KINDS = {
    ("actor", "create"): KIND_ACTOR_SPAWN,
    ("actor", "modify"): KIND_ACTOR_TRANSFORM,
}

# kind -> the compensating action that undoes it. A kind absent from this table has
# no inverse and is refused before apply (WF1279). The two tables are separate on
# purpose: adding a kind to the first without the second is exactly the mistake the
# refusal exists to catch, and it fails closed.
COMPENSATIONS = {
    KIND_ACTOR_SPAWN: "destroy_spawned_actor",
    KIND_ACTOR_TRANSFORM: "restore_captured_transform",
}

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS_DEFAULT = os.path.normpath(os.path.join(_HERE, os.pardir))
_REPO_DEFAULT = os.path.normpath(os.path.join(_TOOLS_DEFAULT, os.pardir))


# --------------------------------------------------------------------------- #
# defensive env parsing -- NEVER raises, always degrades to a documented default
# --------------------------------------------------------------------------- #
def _env_text(name, default=None):
    """(value, error_or_None). A malformed value yields the default plus a reason."""
    raw = os.environ.get(name)
    if raw is None:
        return default, None
    try:
        value = str(raw).strip()
    except Exception:  # noqa: BLE001
        return default, "{} could not be read as text -- using default {!r}".format(
            name, default)
    if not value:
        return default, None
    return value, None


def _env_flag(name, default=False):
    """(bool, error_or_None). Only an explicit, recognised token moves the value."""
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return bool(default), None
    token = str(raw).strip().lower()
    if token in ("1", "true", "yes", "on"):
        return True, None
    if token in ("0", "false", "no", "off"):
        return False, None
    return bool(default), (
        "{}={!r} is not a recognised boolean -- using default {!r}".format(
            name, raw, bool(default)))


OUT, _OUT_ERR = _env_text("WF_TX_OUT", None)
REQUEST_PATH, _REQ_PATH_ERR = _env_text("WF_TX_REQUEST", "")
REQUEST_INLINE, _REQ_INLINE_ERR = _env_text("WF_TX_REQUEST_JSON", "")
MAP_PATH, _MAP_ERR = _env_text("WF_TX_MAP", "")
REPO_ROOT, _REPO_ERR = _env_text("WF_TX_REPO_ROOT", _REPO_DEFAULT)
OPERATION_ID_ENV, _OPID_ERR = _env_text("WF_TX_OPERATION_ID", "")
SAVE_MAP, _SAVE_ERR = _env_flag("WF_TX_SAVE_MAP", False)
OBSERVE_AFTER, _OBS_ERR = _env_flag("WF_TX_OBSERVE_AFTER", True)
TOOLS_DIR, _TOOLS_ERR = _env_text("WF_TX_TOOLS", _TOOLS_DEFAULT)

ENV_PARSE_ERRORS = [e for e in (_OUT_ERR, _REQ_PATH_ERR, _REQ_INLINE_ERR, _MAP_ERR,
                                _REPO_ERR, _OPID_ERR, _SAVE_ERR, _OBS_ERR,
                                _TOOLS_ERR) if e]

# tools/ must be importable BEFORE wfcore is imported. Inserted at 0 because this is
# a bare interpreter with no project packages on the path at all -- unlike
# wfcore.failure's append, there is nothing here to shadow.
if TOOLS_DIR and os.path.isdir(TOOLS_DIR) and TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import unreal  # noqa: E402  -- provided by the UE Python runtime

# Core, guarded. An ImportError here is a real and reportable state
# (WF1276_CORE_SINK_UNAVAILABLE), not a reason to die before writing anything.
CORE_IMPORT_ERROR = None
try:
    from wfcore.transaction import delta as D          # noqa: E402
    from wfcore.transaction import executor as EX      # noqa: E402
except Exception as _core_exc:  # noqa: BLE001
    D = None
    EX = None
    CORE_IMPORT_ERROR = "{}: {}".format(type(_core_exc).__name__, _core_exc)


def _log(msg):
    try:
        unreal.log("[wf-tx] " + str(msg))
    except Exception:  # noqa: BLE001 -- logging must never fail a run
        pass


# --------------------------------------------------------------------------- #
# PURE helpers. No engine contact; every one of these is exercised headlessly by
# tools/pipeline/test_wfcore_unreal_sink.py.
# --------------------------------------------------------------------------- #
def normalize_class_ref(value):
    """Reduce a class reference to the SHORT name ``UClass.get_name()`` returns.

    ``/Script/Engine.StaticMeshActor`` -> ``StaticMeshActor``
    ``/Game/BP/BP_Foo.BP_Foo_C``       -> ``BP_Foo_C``
    ``StaticMeshActor``                -> ``StaticMeshActor``

    Used by the near-side request builder so the caller's declared payload and this
    sink's observation of it are written in the same alphabet. It is NOT applied to
    an observation and then compared against an unnormalised declaration -- that
    would compare two different spellings and call the difference a defect.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text or None


def parse_actor_address(path):
    """``"<map_package>:<label>"`` -> (map_package, label, error).

    Returns ``(None, None, reason)`` for anything that is not exactly one colon
    separating two non-empty halves. A half-parsed address is refused rather than
    guessed at: the address is what decides which actor gets written.
    """
    if not isinstance(path, str) or not path.strip():
        return None, None, "actor address must be a non-empty string, got {!r}".format(path)
    text = path.strip()
    if text.count(":") != 1:
        return None, None, (
            "actor address {!r} must be exactly '<map_package>:<actor_label>' with "
            "one colon (found {})".format(path, text.count(":")))
    map_pkg, label = text.split(":", 1)
    map_pkg, label = map_pkg.strip().rstrip("/"), label.strip()
    if not map_pkg or not label:
        return None, None, (
            "actor address {!r} has an empty map package or label; an address that "
            "names no actor cannot be observed and must not be applied".format(path))
    return map_pkg, label, None


def normalize_package(value):
    """Compare-ready package name: ``/Game/Maps/Foo.Foo`` and ``/Game/Maps/Foo`` are
    the same package. Lower-cased, trailing slash removed, object suffix dropped."""
    if not isinstance(value, str):
        return None
    text = value.strip().rstrip("/")
    if not text:
        return None
    head, sep, tail = text.rpartition("/")
    if sep and "." in tail:
        text = head + "/" + tail.split(".", 1)[0]
    return text.lower()


def mutation_kind(target_kind, operation):
    """The supported kind for this (target_kind, operation) pair, or None."""
    return MUTATION_KINDS.get((target_kind, operation))


def compensation_for(kind):
    """The declared compensating action for a kind, or None when it has none."""
    return COMPENSATIONS.get(kind)


def refusals_for(mutations):
    """Every mutation this sink cannot UNDO, refused BEFORE anything is applied.

    Returns a list of ``{mutation_id, target_kind, operation, kind, failure_code,
    detail}``. A non-empty list means ``apply_delta`` is never called at all, so the
    world is provably untouched -- which is a stronger statement than any refusal
    made after the lock is taken.
    """
    out = []
    for m in (mutations or []):
        if not isinstance(m, dict):
            out.append({
                "mutation_id": None, "target_kind": None, "operation": None,
                "kind": None, "failure_code": FC_NO_COMPENSATION,
                "detail": "mutation record is {}, not an object; nothing about it "
                          "can be compensated".format(type(m).__name__)})
            continue
        kind = mutation_kind(m.get("target_kind"), m.get("operation"))
        comp = compensation_for(kind) if kind else None
        if comp:
            continue
        out.append({
            "mutation_id": m.get("mutation_id"),
            "target_kind": m.get("target_kind"),
            "operation": m.get("operation"),
            "kind": kind,
            "failure_code": FC_NO_COMPENSATION,
            "detail": (
                "({!r}, {!r}) maps to {}, which has no declared compensating action "
                "in this sink. UE 5.8 exposes no generic Undo to Python, so a "
                "mutation with no inverse cannot be rolled back -- it is refused "
                "before it is applied, never discovered while unwinding. Supported "
                "pairs: {}".format(
                    m.get("target_kind"), m.get("operation"),
                    kind if kind else "no supported kind",
                    sorted(MUTATION_KINDS.keys()))),
        })
    return out


def _round(value):
    """A finite float rounded to ROUND_DIGITS, or None. Never 0.0 for unreadable."""
    try:
        f = float(value)
    except Exception:  # noqa: BLE001
        return None
    if not math.isfinite(f):
        return None
    # +0.0 rather than -0.0: the two are equal as floats but serialize differently,
    # and a canonical-JSON comparison would call that a violated postcondition.
    return round(f, ROUND_DIGITS) + 0.0


def _round_triple(values):
    """[a, b, c] rounded, or None if any element is missing or non-finite."""
    try:
        items = list(values)
    except Exception:  # noqa: BLE001
        return None
    if len(items) != 3:
        return None
    out = [_round(v) for v in items]
    return None if any(v is None for v in out) else out


def actor_payload(actor_class, location, rotation, scale):
    """The canonical actor payload -- the ONE shape both sides of the comparison use.

    Returns None when any component is unreadable, because a payload with a hole in
    it is not a restore point and must not be passed off as one.
    """
    cls = normalize_class_ref(actor_class)
    loc, rot, scl = _round_triple(location), _round_triple(rotation), _round_triple(scale)
    if not cls or loc is None or rot is None or scl is None:
        return None
    return {"actor_class": cls, "location": loc, "rotation": rot, "scale": scl}


# --------------------------------------------------------------------------- #
# guarded engine access. Each returns a value or None + a reason; never raises.
# --------------------------------------------------------------------------- #
def _editor_world():
    try:
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        return ues.get_editor_world(), None
    except Exception as exc:  # noqa: BLE001
        return None, "UnrealEditorSubsystem.get_editor_world: {}: {}".format(
            type(exc).__name__, exc)


def _world_package_name(world):
    if world is None:
        return None, "no editor world is open"
    try:
        return world.get_package().get_name(), None
    except Exception as exc:  # noqa: BLE001
        return None, "World.get_package().get_name(): {}: {}".format(
            type(exc).__name__, exc)


def _actor_subsystem():
    try:
        return unreal.get_editor_subsystem(unreal.EditorActorSubsystem), None
    except Exception as exc:  # noqa: BLE001
        return None, "get_editor_subsystem(EditorActorSubsystem): {}: {}".format(
            type(exc).__name__, exc)


def _actor_label(actor):
    try:
        return actor.get_actor_label()
    except Exception:  # noqa: BLE001
        return None


def _actor_path(actor):
    try:
        return actor.get_path_name()
    except Exception:  # noqa: BLE001
        return None


def _actor_class_name(actor):
    try:
        return actor.get_class().get_name()
    except Exception:  # noqa: BLE001
        return None


def _xyz(vec):
    try:
        return [vec.x, vec.y, vec.z]
    except Exception:  # noqa: BLE001
        return None


def _pyr(rot):
    try:
        return [rot.pitch, rot.yaw, rot.roll]
    except Exception:  # noqa: BLE001
        return None


def load_level(map_path):
    """Load ``map_path``. Returns (ok_or_None, api_used, error).

    ``None`` for ok means the call could not be made at all -- distinct from a
    measured False, which means the engine tried and refused.
    """
    if not map_path:
        return None, None, "no map was requested; nothing was loaded"
    last = None
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        ok = les.load_level(map_path)
        return bool(ok), "unreal.LevelEditorSubsystem.load_level", None
    except Exception as exc:  # noqa: BLE001
        last = "LevelEditorSubsystem.load_level: {}: {}".format(type(exc).__name__, exc)
    try:
        ok = unreal.EditorLoadingAndSavingUtils.load_map(map_path)
        return bool(ok), "unreal.EditorLoadingAndSavingUtils.load_map", last
    except Exception as exc:  # noqa: BLE001
        return None, None, "{}; and {}: {}: {}".format(
            last, "EditorLoadingAndSavingUtils.load_map", type(exc).__name__, exc)


def resolve_actor_class(short_name):
    """Resolve a SHORT reflected class name to a UClass. Returns (cls, api, error).

    The ladder is documented and short on purpose:
        1. ``getattr(unreal, name)``                    -- every engine C++ class
        2. ``unreal.load_class(None, '/Script/Engine.' + name)``

    Blueprint-generated classes (``BP_Foo_C``) are OUT OF SCOPE: the short name does
    not carry the package they live in, and inventing one would spawn something the
    caller never asked for. Such a name reaches the end of the ladder and is
    reported as unresolvable, which is the honest answer.
    """
    name = normalize_class_ref(short_name)
    if not name:
        return None, None, "actor_class {!r} is not a usable class name".format(short_name)
    try:
        candidate = getattr(unreal, name)
    except Exception:  # noqa: BLE001
        candidate = None
    if candidate is not None:
        return candidate, "getattr(unreal, {!r})".format(name), None
    try:
        loaded = unreal.load_class(None, "/Script/Engine." + name)
    except Exception as exc:  # noqa: BLE001
        return None, None, (
            "actor_class {!r} is not an attribute of the unreal module and "
            "load_class('/Script/Engine.{}') raised {}: {}. Blueprint-generated "
            "classes are out of scope for this sink -- a '_C' short name does not "
            "name the package it lives in".format(name, name, type(exc).__name__, exc))
    if loaded is None:
        return None, None, (
            "actor_class {!r} resolved to nothing on either rung of the ladder "
            "(getattr(unreal, ...), load_class('/Script/Engine....'))".format(name))
    return loaded, "unreal.load_class(None, '/Script/Engine.{}')".format(name), None


class _NullTransaction(object):
    """Stand-in for ScopedEditorTransaction when the type is not reflected.

    Doing nothing is correct here: the transaction is editor-side grouping, and the
    rollback never consults it. A missing type must not stop the mutation.
    """

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _transaction(description):
    try:
        return unreal.ScopedEditorTransaction(description)
    except Exception:  # noqa: BLE001
        return _NullTransaction()


# --------------------------------------------------------------------------- #
# the sink
# --------------------------------------------------------------------------- #
class UnrealMutationSink(object):
    """Core's ``MutationSink`` contract, implemented against a live editor world.

    Duck-typed rather than subclassed: ``apply_delta`` calls the four methods and
    never isinstance-checks, and inheriting would make this class undefinable in the
    one situation it most needs to report -- Core failing to import.

    ``observe`` NEVER raises and never fabricates. Anything it could not measure
    comes back as ``unmeasured_state(reason)``; Core then refuses the mutation
    (WF1251) rather than applying something it has no restore point for.

    ``apply`` raises ``MutationSinkError`` for anything that did not complete. It
    registers a spawned actor in ``_spawned`` BEFORE attempting to label it, so an
    actor whose labelling failed -- and which therefore cannot be found by address
    -- is still destroyable by the compensation.
    """

    def __init__(self, save_map=False, expected_map=None):
        self.save_map = bool(save_map)
        self.expected_map = expected_map
        self._touched = []
        self._spawned = {}        # mutation_id -> actor handle
        self.notes = []           # per-call diagnostics, reported alongside the delta
        self.apply_calls = []
        self.undo_calls = []
        self.observe_calls = []
        self.saves = []

    # -- helpers ----------------------------------------------------------- #
    def _note(self, where, detail, failure_code=None):
        self.notes.append({"where": where, "detail": str(detail),
                           "failure_code": failure_code})

    def _fail(self, message, failure_code=FC_APPLY_FAILED):
        self._note("apply", message, failure_code)
        return EX.MutationSinkError("{}: {}".format(failure_code, message))

    def _resolve_actor(self, label):
        """(actor, reason). ``reason`` is set whenever ``actor`` is None OR the
        lookup itself was unreliable; an ambiguous label yields (None, reason)."""
        eas, err = _actor_subsystem()
        if eas is None:
            return None, err
        try:
            actors = eas.get_all_level_actors()
        except Exception as exc:  # noqa: BLE001
            return None, "EditorActorSubsystem.get_all_level_actors: {}: {}".format(
                type(exc).__name__, exc)
        try:
            matches = [a for a in actors if _actor_label(a) == label]
        except Exception as exc:  # noqa: BLE001
            return None, "level actor list is not iterable: {}: {}".format(
                type(exc).__name__, exc)
        if len(matches) > 1:
            return None, (
                "{} actors in this level carry the label {!r}; the address is "
                "ambiguous, and a restore point that might belong to either of two "
                "actors is not a restore point".format(len(matches), label))
        return (matches[0] if matches else None), None

    def _world_matches(self, map_pkg):
        """(True/False/None, reason). None means the open world could not be read."""
        world, err = _editor_world()
        if world is None:
            return None, err
        name, err = _world_package_name(world)
        if name is None:
            return None, err
        want, got = normalize_package(map_pkg), normalize_package(name)
        if want is None or got is None:
            return None, "package name {!r} or {!r} could not be normalised".format(
                map_pkg, name)
        return (want == got), (
            None if want == got else
            "the address names map {!r} but the world actually open is {!r}; "
            "mutating whichever world happened to be loaded would be a correct "
            "operation performed in the wrong place".format(map_pkg, name))

    def _save_current_map(self, map_pkg):
        """Save the open map. Returns None on success, a reason on failure."""
        world, err = _editor_world()
        if world is None:
            return err or "no editor world to save"
        try:
            ok = unreal.EditorLoadingAndSavingUtils.save_map(world, map_pkg)
        except Exception as exc:  # noqa: BLE001
            return "EditorLoadingAndSavingUtils.save_map: {}: {}".format(
                type(exc).__name__, exc)
        self.saves.append({"map": map_pkg, "reported_ok": bool(ok)})
        if not ok:
            return "EditorLoadingAndSavingUtils.save_map({!r}) reported failure".format(
                map_pkg)
        return None

    def _record_touch(self, kind, path):
        self._touched.append((kind, D.normalize_target_path(path)))

    # -- MutationSink: observe --------------------------------------------- #
    def observe(self, target_kind, target_path):
        """A delta state record. NEVER raises, never fabricates a measurement."""
        self.observe_calls.append((target_kind, target_path))
        try:
            return self._observe(target_kind, target_path)
        except Exception as exc:  # noqa: BLE001 -- an unreadable world is not "absent"
            self._note("observe", "{}: {}".format(type(exc).__name__, exc),
                       FC_OBSERVATION_FAILED)
            return D.unmeasured_state(
                "observing {} {!r} raised {}: {}".format(
                    target_kind, target_path, type(exc).__name__, exc))

    def _observe(self, target_kind, target_path):
        if target_kind == "package":
            try:
                exists = unreal.EditorAssetLibrary.does_asset_exist(target_path)
            except Exception as exc:  # noqa: BLE001
                return D.unmeasured_state(
                    "EditorAssetLibrary.does_asset_exist({!r}): {}: {}".format(
                        target_path, type(exc).__name__, exc))
            # A package's payload is its existence only. This sink declares no
            # package mutation kind (see MUTATION_KINDS), so it never needs to
            # restore package CONTENT -- and claiming a content restore point it
            # does not have would be the worse error.
            return D.present_state({"asset_exists": True}) if exists else D.absent_state()

        if target_kind != "actor":
            return D.unmeasured_state(
                "target_kind {!r} is not one of ('actor', 'package'); this sink has "
                "no address space for it".format(target_kind))

        map_pkg, label, err = parse_actor_address(target_path)
        if err:
            return D.unmeasured_state(err)

        matches, why = self._world_matches(map_pkg)
        if matches is None:
            return D.unmeasured_state(
                "the world actually open could not be read, so {!r} cannot be "
                "located: {}".format(target_path, why))
        if matches is False:
            return D.unmeasured_state(why)

        actor, why = self._resolve_actor(label)
        if why:
            return D.unmeasured_state(why)
        if actor is None:
            # MEASURED absent: the level was enumerated and no actor carries this
            # label. Distinct from every unmeasured branch above.
            return D.absent_state()

        cls = _actor_class_name(actor)
        loc = rot = scl = None
        try:
            loc = _xyz(actor.get_actor_location())
        except Exception:  # noqa: BLE001
            loc = None
        try:
            rot = _pyr(actor.get_actor_rotation())
        except Exception:  # noqa: BLE001
            rot = None
        try:
            scl = _xyz(actor.get_actor_scale3d())
        except Exception:  # noqa: BLE001
            scl = None
        payload = actor_payload(cls, loc, rot, scl)
        if payload is None:
            return D.unmeasured_state(
                "actor {!r} is present but its transform could not be fully read "
                "(class={!r} location={!r} rotation={!r} scale={!r}); a partial "
                "payload is not a restore point".format(
                    target_path, cls, loc, rot, scl))
        self._note("observe", "{} -> {} at {}".format(
            target_path, cls, _actor_path(actor)))
        return D.present_state(payload)

    # -- MutationSink: apply ------------------------------------------------ #
    def apply(self, mutation):
        mutation_id = mutation.get("mutation_id")
        self.apply_calls.append(mutation_id)
        kind = mutation_kind(mutation.get("target_kind"), mutation.get("operation"))
        if not compensation_for(kind):
            # Defence in depth. `refusals_for` already stopped this before the lock
            # was taken; reaching here means someone bypassed the preflight, and the
            # refusal must still happen BEFORE anything is written.
            raise self._fail(
                "({!r}, {!r}) has no declared compensating action; refusing to apply "
                "something this sink cannot undo".format(
                    mutation.get("target_kind"), mutation.get("operation")),
                FC_NO_COMPENSATION)
        if kind == KIND_ACTOR_SPAWN:
            return self._apply_spawn(mutation)
        return self._apply_transform(mutation)

    def _spec_of(self, mutation):
        """The declared postcondition payload -- which IS the instruction.

        The spawn/transform spec and the postcondition are the same object by
        design: a sink that took its instructions from one field and was verified
        against another could satisfy the check while doing something else.
        """
        expected = mutation.get("expected_after_state") or {}
        payload = expected.get("payload") if isinstance(expected, dict) else None
        if not isinstance(payload, dict):
            raise self._fail(
                "mutation {!r} carries no expected_after_state payload; this sink "
                "takes its instruction FROM the postcondition, so there is nothing "
                "to apply".format(mutation.get("mutation_id")))
        spec = actor_payload(payload.get("actor_class"), payload.get("location"),
                             payload.get("rotation"), payload.get("scale"))
        if spec is None:
            raise self._fail(
                "mutation {!r}'s payload {!r} is not a complete actor payload "
                "(actor_class + finite location/rotation/scale)".format(
                    mutation.get("mutation_id"), payload))
        return spec

    def _apply_spawn(self, mutation):
        spec = self._spec_of(mutation)
        map_pkg, label, err = parse_actor_address(mutation.get("target_path"))
        if err:
            raise self._fail(err)
        cls, api, err = resolve_actor_class(spec["actor_class"])
        if cls is None:
            raise self._fail(err)
        eas, err = _actor_subsystem()
        if eas is None:
            raise self._fail(err or "EditorActorSubsystem is unavailable",
                             FC_SINK_UNAVAILABLE)
        loc, rot = spec["location"], spec["rotation"]
        with _transaction("WorldForge transaction: spawn {}".format(label)):
            try:
                actor = eas.spawn_actor_from_class(
                    cls, unreal.Vector(loc[0], loc[1], loc[2]),
                    unreal.Rotator(rot[0], rot[1], rot[2]))
            except Exception as exc:  # noqa: BLE001
                raise self._fail("spawn_actor_from_class({}): {}: {}".format(
                    api, type(exc).__name__, exc))
            if actor is None:
                raise self._fail(
                    "spawn_actor_from_class({}) returned None; nothing was spawned "
                    "and nothing is claimed".format(api))
            # Registered FIRST. Everything below can fail, and once the actor
            # exists the compensation must be able to reach it by handle -- a
            # re-lookup by label would miss precisely the actor whose labelling
            # is what failed.
            self._spawned[mutation.get("mutation_id")] = actor
            self._record_touch("actor", mutation.get("target_path"))
            try:
                actor.set_actor_label(label)
            except Exception as exc:  # noqa: BLE001
                raise self._fail("set_actor_label({!r}): {}: {}".format(
                    label, type(exc).__name__, exc))
            scl = spec["scale"]
            try:
                actor.set_actor_scale3d(unreal.Vector(scl[0], scl[1], scl[2]))
            except Exception as exc:  # noqa: BLE001
                raise self._fail("set_actor_scale3d: {}: {}".format(
                    type(exc).__name__, exc))
        self._note("apply", "spawned {} as {} via {}".format(
            spec["actor_class"], _actor_path(actor), api))
        self._maybe_save(map_pkg)

    def _apply_transform(self, mutation):
        spec = self._spec_of(mutation)
        map_pkg, label, err = parse_actor_address(mutation.get("target_path"))
        if err:
            raise self._fail(err)
        actor, why = self._resolve_actor(label)
        if actor is None:
            raise self._fail(
                why or "no actor carries the label {!r}; a modify has nothing to "
                       "modify".format(label))
        with _transaction("WorldForge transaction: transform {}".format(label)):
            self._record_touch("actor", mutation.get("target_path"))
            self._set_transform(actor, spec)
        self._note("apply", "moved {} to {}".format(
            _actor_path(actor), spec["location"]))
        self._maybe_save(map_pkg)

    def _set_transform(self, actor, spec):
        """Three individually-guarded setters, not one Transform ctor.

        ``unreal.Transform``'s Python constructor takes a QUATERNION rotation in
        some builds and a rotator in others; a wrong guess there would rotate the
        actor to somewhere plausible rather than fail. Three named setters cannot be
        misread that way, and each degrades with its own reason.
        """
        loc, rot, scl = spec["location"], spec["rotation"], spec["scale"]
        try:
            actor.set_actor_location(unreal.Vector(loc[0], loc[1], loc[2]), False, True)
        except Exception as exc:  # noqa: BLE001
            raise self._fail("set_actor_location: {}: {}".format(type(exc).__name__, exc))
        try:
            actor.set_actor_rotation(unreal.Rotator(rot[0], rot[1], rot[2]), True)
        except Exception as exc:  # noqa: BLE001
            raise self._fail("set_actor_rotation: {}: {}".format(type(exc).__name__, exc))
        try:
            actor.set_actor_scale3d(unreal.Vector(scl[0], scl[1], scl[2]))
        except Exception as exc:  # noqa: BLE001
            raise self._fail("set_actor_scale3d: {}: {}".format(type(exc).__name__, exc))

    def _maybe_save(self, map_pkg):
        """Save only when asked, and report the package as touched only when saved.

        An unsaved editor-world mutation writes no package. Reporting one anyway
        would force every caller to widen its bound to authorise a write that never
        happened -- and a bound widened for a phantom write authorises a real one.
        """
        if not self.save_map:
            return
        err = self._save_current_map(map_pkg)
        self._record_touch("package", map_pkg)
        if err:
            raise self._fail(err, FC_SAVE_FAILED)

    # -- MutationSink: undo ------------------------------------------------- #
    def undo(self, mutation):
        """Run the declared compensating action. Its success is Core's to re-observe.

        This method's return value is NOT the verdict -- ``executor._rollback``
        records ``undo_reported_ok`` and then decides from a fresh observation. What
        this method owes is an honest raise when the compensation did not complete.
        """
        mutation_id = mutation.get("mutation_id")
        self.undo_calls.append(mutation_id)
        kind = mutation_kind(mutation.get("target_kind"), mutation.get("operation"))
        comp = compensation_for(kind)
        if not comp:
            raise EX.MutationSinkError(
                "{}: mutation {!r} has no compensating action; it should have been "
                "refused before it was applied".format(FC_NO_COMPENSATION, mutation_id))
        map_pkg, label, err = parse_actor_address(mutation.get("target_path"))
        if err:
            raise EX.MutationSinkError("{}: {}".format(FC_APPLY_FAILED, err))
        if comp == "destroy_spawned_actor":
            self._compensate_spawn(mutation, label)
        else:
            self._compensate_transform(mutation, label)
        if self.save_map:
            save_err = self._save_current_map(map_pkg)
            if save_err:
                raise EX.MutationSinkError("{}: {}".format(FC_SAVE_FAILED, save_err))

    def _compensate_spawn(self, mutation, label):
        mutation_id = mutation.get("mutation_id")
        actor = self._spawned.get(mutation_id)
        if actor is None:
            # Nothing was ever spawned for this mutation: the apply raised before
            # reaching the spawn call. There is nothing to destroy, and destroying
            # a same-labelled actor that this sink did not create would be a
            # deletion nobody authorised.
            self._note("undo", "mutation {!r} spawned nothing; nothing to destroy".format(
                mutation_id))
            return
        eas, err = _actor_subsystem()
        if eas is None:
            raise EX.MutationSinkError("{}: {}".format(
                FC_SINK_UNAVAILABLE, err or "EditorActorSubsystem is unavailable"))
        try:
            eas.destroy_actor(actor)
        except Exception as exc:  # noqa: BLE001
            raise EX.MutationSinkError("{}: destroy_actor({!r}): {}: {}".format(
                FC_APPLY_FAILED, label, type(exc).__name__, exc))
        # Corroborating check only. The VERDICT is Core's re-observation; this is
        # recorded because is_valid answers a question level enumeration cannot
        # (see the survey lane's ENUMERATION_VACUITY_REASON).
        try:
            still_valid = unreal.SystemLibrary.is_valid(actor)
        except Exception:  # noqa: BLE001
            still_valid = None
        self._note("undo", "destroyed {!r}; SystemLibrary.is_valid -> {!r}".format(
            label, still_valid))
        self._spawned.pop(mutation_id, None)

    def _compensate_transform(self, mutation, label):
        before = mutation.get("before_state") or {}
        payload = before.get("payload") if isinstance(before, dict) else None
        if before.get("state_kind") != "present" or not isinstance(payload, dict):
            raise EX.MutationSinkError(
                "{}: mutation {!r} has no measured present before_state to restore; "
                "its undo would be a claim".format(
                    FC_APPLY_FAILED, mutation.get("mutation_id")))
        spec = actor_payload(payload.get("actor_class"), payload.get("location"),
                             payload.get("rotation"), payload.get("scale"))
        if spec is None:
            raise EX.MutationSinkError(
                "{}: the captured before_state payload {!r} is not a complete actor "
                "payload, so there is no transform to put back".format(
                    FC_APPLY_FAILED, payload))
        actor, why = self._resolve_actor(label)
        if actor is None:
            raise EX.MutationSinkError(
                "{}: {}".format(FC_APPLY_FAILED,
                                why or "actor {!r} is gone; its transform cannot be "
                                       "restored".format(label)))
        with _transaction("WorldForge transaction: restore {}".format(label)):
            # Undo writes are NOT provider mutations: `executor._rollback` drains and
            # discards the touch log afterwards, and re-checking them against the
            # bound would re-flag the same addresses the apply already cleared.
            self._set_transform(actor, spec)
        self._note("undo", "restored {!r} to {}".format(label, spec["location"]))

    # -- MutationSink: drain_touched --------------------------------------- #
    def drain_touched(self):
        """Every target written since the last drain.

        Returns a list, never None: this sink knows exactly what it wrote because it
        wrote it. ``None`` is reserved for a sink that genuinely cannot tell, and
        returning it here would make the bound unenforceable for no reason.
        """
        out = list(self._touched)
        self._touched = []
        return out


# --------------------------------------------------------------------------- #
# request loading
# --------------------------------------------------------------------------- #
def load_request(request_path, inline_json):
    """(request_dict, source, error). Exactly one channel answers; the file wins."""
    if request_path:
        try:
            with open(request_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception as exc:  # noqa: BLE001
            return None, "file", "could not read WF_TX_REQUEST {!r}: {}: {}".format(
                request_path, type(exc).__name__, exc)
        if not isinstance(data, dict):
            return None, "file", "WF_TX_REQUEST {!r} is a {}, not an object".format(
                request_path, type(data).__name__)
        return data, "file", None
    if inline_json:
        try:
            data = json.loads(inline_json)
        except Exception as exc:  # noqa: BLE001
            return None, "inline", "WF_TX_REQUEST_JSON is not valid JSON: {}: {}".format(
                type(exc).__name__, exc)
        if not isinstance(data, dict):
            return None, "inline", "WF_TX_REQUEST_JSON is a {}, not an object".format(
                type(data).__name__)
        return data, "inline", None
    return None, None, (
        "neither WF_TX_REQUEST nor WF_TX_REQUEST_JSON was supplied; there is no "
        "transaction to run")


def _new_doc():
    """The far-side document skeleton. Built by ONE function so the fatal-path
    document cannot drift out of key-set parity with the main one."""
    return {
        "far_side_schema": FAR_SIDE_SCHEMA,
        "operation_id": OPERATION_ID_ENV or None,
        "request_source": None,
        "map_requested": MAP_PATH or None,
        "map_loaded": None,
        "map_load_api": None,
        "world_package_observed": None,
        "save_map": SAVE_MAP,
        "observe_after": OBSERVE_AFTER,
        "repo_root": REPO_ROOT,
        "core_import_error": CORE_IMPORT_ERROR,
        "env_parse_errors": list(ENV_PARSE_ERRORS),
        "sink_refusals": [],
        "sink_notes": [],
        "sink_saves": [],
        "supported_kinds": {"{}|{}".format(k[0], k[1]): v
                            for k, v in sorted(MUTATION_KINDS.items())},
        "compensations": dict(COMPENSATIONS),
        "delta": None,
        "failure_codes": [],
        "error": None,
        "traceback": None,
    }


def _add_code(doc, code):
    if code and code not in doc["failure_codes"]:
        doc["failure_codes"].append(code)


def main():
    doc = _new_doc()
    if CORE_IMPORT_ERROR:
        doc["error"] = (
            "wfcore could not be imported from {!r}, so there is no transaction "
            "executor to run: {}".format(TOOLS_DIR, CORE_IMPORT_ERROR))
        _add_code(doc, FC_SINK_UNAVAILABLE)
        _write(doc)
        return

    request, source, err = load_request(REQUEST_PATH, REQUEST_INLINE)
    doc["request_source"] = source
    if request is None:
        doc["error"] = err
        _add_code(doc, FC_SINK_UNAVAILABLE)
        _write(doc)
        return

    operation_id = (OPERATION_ID_ENV or request.get("operation_id")
                    or "op_wfcore_unreal_transaction")
    doc["operation_id"] = operation_id
    bounds = request.get("bounds") or []
    mutations = request.get("mutations") or []
    evidence_refs = request.get("evidence_refs") or []

    # --- refuse the uncompensatable BEFORE the world is touched ------------- #
    refusals = refusals_for(mutations)
    doc["sink_refusals"] = refusals
    if refusals:
        _add_code(doc, FC_NO_COMPENSATION)
        doc["error"] = (
            "{} of {} mutation(s) name a kind this sink cannot undo. apply_delta was "
            "NOT called, so the world was never touched -- a stronger statement than "
            "any refusal made after the lock is taken".format(
                len(refusals), len(mutations)))
        _write(doc)
        return

    # --- load the map ------------------------------------------------------- #
    if MAP_PATH:
        loaded, api, load_err = load_level(MAP_PATH)
        doc["map_loaded"] = loaded
        doc["map_load_api"] = api
        if load_err:
            doc["sink_notes"].append({"where": "load_level", "detail": load_err,
                                      "failure_code": None})
        if loaded is not True:
            # Not fatal by itself: every mutation's observe() re-checks the world
            # that is actually open, and an unloaded map makes those unmeasurable,
            # which Core refuses. Recorded here so the reason is visible.
            _add_code(doc, FC_RELOAD_MISMATCH)

    world, werr = _editor_world()
    world_pkg, perr = _world_package_name(world)
    doc["world_package_observed"] = world_pkg
    if world_pkg is None:
        doc["sink_notes"].append({"where": "world_identity",
                                  "detail": werr or perr,
                                  "failure_code": FC_OBSERVATION_FAILED})

    # --- run the REAL executor against the REAL sink ------------------------ #
    sink = UnrealMutationSink(save_map=SAVE_MAP, expected_map=MAP_PATH or world_pkg)
    try:
        record = EX.apply_delta(
            sink, bounds, mutations,
            repo_root=REPO_ROOT,
            operation_id=operation_id,
            evidence_refs=evidence_refs,
            observe_after=OBSERVE_AFTER,
            journal=True)
    except Exception as exc:  # noqa: BLE001
        doc["error"] = "apply_delta raised {}: {}".format(type(exc).__name__, exc)
        doc["traceback"] = traceback.format_exc()
        _add_code(doc, FC_APPLY_FAILED)
        doc["sink_notes"] = list(sink.notes)
        doc["sink_saves"] = list(sink.saves)
        _write(doc)
        return

    doc["delta"] = record
    doc["sink_notes"] = list(sink.notes)
    doc["sink_saves"] = list(sink.saves)
    for code in (record.get("failure_codes") or []):
        _add_code(doc, code)
    _write(doc)


def _write(doc):
    """ONE deterministic JSON file. Never stdout, never NaN, never silent."""
    if not OUT:
        _log("FATAL: WF_TX_OUT is unset; the far side has nowhere to write its "
             "evidence and the near side will see only a timeout")
        return
    try:
        text = json.dumps(doc, indent=2, sort_keys=True, allow_nan=False, default=str)
    except (ValueError, TypeError) as exc:
        # A document that reports only its own failure still beats no document: the
        # near side's alternative reading of an absent file is a timeout, which is
        # indistinguishable from a far side that never started.
        skeleton = _new_doc()
        skeleton["error"] = "far-side document could not be serialized: {}: {}".format(
            type(exc).__name__, exc)
        try:
            text = json.dumps(skeleton, indent=2, sort_keys=True, allow_nan=False,
                              default=str)
        except Exception:  # noqa: BLE001
            _log("FATAL: even the far-side skeleton could not be serialized")
            return
    try:
        with open(OUT, "w", encoding="utf-8") as handle:
            handle.write(text)
    except Exception as exc:  # noqa: BLE001
        _log("FATAL: could not write {!r}: {}: {}".format(OUT, type(exc).__name__, exc))
        return
    delta = doc.get("delta") or {}
    _log("wrote transaction -> {} (outcome={} verification={} rollback={} "
         "bound={} codes={} refusals={} err={})".format(
             OUT, delta.get("outcome"), delta.get("verification"),
             delta.get("rollback_completeness"), delta.get("bound_enforcement"),
             doc.get("failure_codes"), len(doc.get("sink_refusals") or []),
             doc.get("error")))


try:
    main()
except Exception as _fatal:  # noqa: BLE001
    # A far side that dies silently is indistinguishable from one that never
    # started. The skeleton comes from _new_doc() so it cannot drift out of key-set
    # parity with the document the happy path writes.
    try:
        _fatal_doc = _new_doc()
        _fatal_doc["error"] = "{}: {}".format(type(_fatal).__name__, _fatal)
        _fatal_doc["traceback"] = traceback.format_exc()
        _write(_fatal_doc)
    except Exception:  # noqa: BLE001
        _log("FATAL: could not write far-side evidence")

# Ask for a clean shutdown, or the -ExecutePythonScript boot sits in the editor loop
# until the near side's timeout and reports a hang instead of a result.
try:
    unreal.SystemLibrary.quit_editor()
except Exception:  # noqa: BLE001
    try:
        _w, _ = _editor_world()
        unreal.SystemLibrary.execute_console_command(_w, "quit")
    except Exception:  # noqa: BLE001
        _log("WARNING: could not request editor shutdown; the near side will rely "
             "on its timeout")
