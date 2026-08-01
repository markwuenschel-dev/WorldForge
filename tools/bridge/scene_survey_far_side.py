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

    overlap_query       one record per capsule overlap query actually performed
    capture             the camera-capture question, answered honestly for a pass
                        that cannot render
    document            document-level collection facts (ref integrity, and a
                        serialization failure if one occurs)

The per-marker keys ``grounded`` / ``footprint`` / ``overlap`` / ``capsule_clear``
are the field names the committed raw-bundle contract reads
(scene_survey_evidence.py:316,322,333,346). Here each is a nullable RESTATEMENT of
atomic trace observations that are ALSO emitted alongside it
(``ground_trace_ref``, ``footprint_trace_refs``, ``overlap_query_ref``,
``capsule_overlap_actor_paths``, ``capsule_overlap_component_paths``), so the
assembler can re-derive them from the atoms rather than take them on faith.
When the underlying atom was not collected the restatement is ``None`` — never
False, never zero. ``None`` means "not observed"; it never means "measured zero"
and it never means "fine".

Every Unreal API call below is individually guarded. The Python symbol surface of
UE 5.8 cannot be executed or introspected from the repo side, so an unexpected
shape must degrade to a recorded ``None`` plus a reason in ``collection_errors`` —
never to a fabricated success and never to a silently-plausible zero.

THE RECORD ENVELOPE — stdout is never an evidence authority
-----------------------------------------------------------
The compiled primitives also print WF_SURVEY_* marker lines, and a near side that
had to scrape them would be treating an editor log as an evidence authority: a log
line carries no provenance, no identity, and no way to say "this was not measured".
So EVERY record in ``raw_evidence`` carries the same envelope, and the envelope,
not the log, is what a reader reasons over:

    record_schema         RAW_RECORD_SCHEMA
    operation_id          the run this record belongs to (WF_SURVEY_OPERATION_ID)
    request_hash          the caller's BridgeRequest digest
                          (WF_SURVEY_REQUEST_HASH), stamped verbatim; ``None`` when
                          the caller supplied none
    record_id             ``"<record_type>#<ident>"`` — IDENTICAL to the raw_ref
                          form the evidence model resolves
                          (scene_survey_evidence.py:245-246). UNIQUE within the
                          bundle by construction, because the bundle IS
                          ``{kind: {ident: record}}`` and the id is built from that
                          pair. STABLE across repeat runs of identical input,
                          because it is a pure function of kind and ident and reads
                          no clock, no counter and no run identity.
    record_type           the bundle kind; equals the key the record is filed under
    record_ident          the ident the record is filed under
    stage                 a member of the stage vocabulary below
    collector             the function that produced the record
    collection_status     collected / partial / not_attempted / failed — MECHANICS
    evidence_class        observed / derived_from_observed / caller_supplied /
                          not_requested / unsupported / failed — PROVENANCE. Closed
                          set, mirroring scene_survey_evidence.CLASSIFICATIONS
                          (scene_survey_evidence.py:73-81).
    source_api            the EXACT Unreal call the values came from, e.g.
                          ``"unreal.SystemLibrary.line_trace_single"``; ``None`` when
                          no API was reached. This is the field that lets a later
                          reader tell an OBSERVATION from an INFERENCE without
                          trusting anyone's narration.
    world_identity        package name of the world actually open when the record was
                          taken; ``None`` when it could not be read. Measured once
                          from the live editor, never copied from the request.
    actor_object_path     identity of the actor the record is about, where the record
                          type has one; ``None`` otherwise
    component_object_path likewise for a component
    failure_code          a registered WF failure code, set ONLY when evidence_class
                          is ``failed``; ``None`` otherwise, because ``not_requested``
                          and ``unsupported`` are not failures
    derived_fields        ``{field: {evidence_class, derivation, inputs, source_api}}``
                          for every value in the record that was COMPUTED rather than
                          read. A convenience value with no entry here is an
                          observation; one with an entry states its own formula and
                          its own inputs, so it can be recomputed instead of believed.
    measured_fields       the names of the fields in this record that are
                          measurements. When evidence_class is one of the
                          non-satisfying states the collector MECHANICALLY forces
                          every one of them to ``None`` — see ``_settle``.

TRI-STATE — the rule the rest of the file exists to protect
-----------------------------------------------------------
Every measured predicate is ``True`` / ``False`` / ``None``. ``None`` means the
collection did not occur or was insufficient. It is NEVER coerced to ``False``.
``False`` is a measurement and costs the caller a real answer; ``None`` costs them
a missing one, and those are different bills. A record whose collection did not
happen is ``not_requested`` / ``unsupported`` / ``failed`` with its measured values
``None`` — never a zero and never a ``False``.

DERIVATION ATOMS
----------------
A convenience field is permitted ONLY when the atoms it was computed from are
preserved in the same bundle. Each marker therefore carries ``ground_trace_ref``,
``footprint_trace_refs``, ``overlap_query_ref``, ``capsule_overlap_actor_paths`` and
``capsule_overlap_component_paths``, and every one of those ``*_ref`` values is a
``record_id`` that resolves inside this bundle. That is checked, not asserted:
``_record_ref_integrity`` walks every record after collection and files the list of
refs that did not resolve.

NON-FINITE NUMERICS
-------------------
NaN and Infinity are rejected at the source (``_num`` / ``_xyz`` / ``_finite_vec3``
all return ``None`` for them), and the document is serialized with
``allow_nan=False`` so anything that slipped through raises here instead of being
written as a bare ``NaN`` token that ``json.loads`` would silently accept on the
near side. A serialization failure is handled by SCRUBBING the offending values to
``None`` and filing a ``failed`` record naming them: a document that reports its own
failure is worth more than one that could not be written at all.

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

That re-observation is done with ``SystemLibrary.is_valid``, NOT with level
enumeration. A transient actor is never returned by ``get_all_level_actors`` at all,
so "not in the enumeration" is true before destruction as well as after and cannot
fail — see ``ENUMERATION_VACUITY_REASON`` and the ``_SpawnLedger`` docstring for the
live-boot measurement behind that. The enumeration observations are still emitted as
their own atoms with an explicit ``enumeration_absence_is_vacuous`` flag.

SYMBOL CONFIDENCE
-----------------
The Python symbol surface of UE 5.8 cannot be introspected from the repo side, so
every call below is guarded regardless. What differs is how much is known about the
shapes. RUNTIME-VERIFIED by a parallel lane's live UE 5.8 -nullrhi boot (engine
5.8.0-55116800) against a fixture map — NOT by this file's author, and NOT in this
process: ``World.get_package().get_name()``, ``Actor.get_path_name()``,
``Actor.get_actor_location/rotation/scale3d``, the TWO-ARGUMENT
``Actor.get_actor_bounds(False, True)``, the 3-tuple return of
``SystemLibrary.get_component_bounds``,
``EditorLoadingAndSavingUtils.get_dirty_map_packages/get_dirty_content_packages``,
and ``SystemLibrary.is_valid`` (True before ``destroy_actor``, False after). STILL
ASSUMED and labelled as such at each call site: ``SystemLibrary.line_trace_single``,
``SystemLibrary.capsule_overlap_actors``, ``SystemLibrary.capsule_overlap_components``,
``GameplayStatics.break_hit_result``, and every ``USceneSurveyStatics`` primitive.

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
    WF_SURVEY_REQUEST_HASH   the caller's BridgeRequest digest, verbatim, in the
                             ``"<algorithm>:<hex>"`` form ``hash_request`` emits
                             (tools/pipeline/scene_survey_operation.py:663). It is
                             CALLER_SUPPLIED and is stamped onto every record so a
                             later reader can bind a bundle to the question that
                             produced it. The far side never validates it and never
                             recomputes it: it does not see the BridgeRequest field
                             set (scene_survey_operation.py:579-597), so it has
                             nothing to recompute from. Unset => ``None`` on every
                             record plus a recorded input error. An absent digest
                             stays absent; inventing or defaulting one would turn a
                             replay check into a rubber stamp.

There is deliberately NO map environment variable: the map is
``subject["map_asset_path"]``. A separate map knob would be a second channel that
could disagree with the subject about what was surveyed.
"""
import inspect
import json
import math
import os
import traceback

import unreal  # provided by the UE Python runtime

# The raw bundle schema this file writes; the evidence model names the same string
# (tools/pipeline/scene_survey_evidence.py:64).
RAW_BUNDLE_SCHEMA = "wf.scene_survey.raw_evidence_bundle.v1"
# The per-RECORD envelope schema. Additive to the bundle schema above: the bundle
# SHAPE ({kind: {ident: record}}) is unchanged and every legacy key still emits
# exactly as it did — each record simply carries more.
RAW_RECORD_SCHEMA = "wf.scene_survey.raw_evidence_record.v1"

# ---- evidence classes ----------------------------------------------------- #
# CLOSED SET, mirroring scene_survey_evidence.CLASSIFICATIONS
# (tools/pipeline/scene_survey_evidence.py:73-81). Duplicated as literals rather
# than imported ON PURPOSE: this file runs inside the UE Python interpreter, whose
# sys.path does not carry tools/pipeline, and an ImportError at module scope would
# kill the far side before any evidence could be written at all — the exact failure
# mode _env_number was already rewritten to avoid. The STRINGS are the contract.
EC_OBSERVED = "observed"
EC_DERIVED = "derived_from_observed"
EC_CALLER_SUPPLIED = "caller_supplied"
EC_NOT_REQUESTED = "not_requested"
EC_UNSUPPORTED = "unsupported"
EC_FAILED = "failed"
EVIDENCE_CLASSES = (EC_OBSERVED, EC_DERIVED, EC_CALLER_SUPPLIED, EC_NOT_REQUESTED,
                    EC_UNSUPPORTED, EC_FAILED)
# The honest terminal states (scene_survey_evidence.py:92). A record in one of these
# carries NO measurement: every field named in its `measured_fields` is forced to
# None by `_settle`.
EC_NON_SATISFYING = (EC_NOT_REQUESTED, EC_UNSUPPORTED, EC_FAILED)

# ---- collection status ---------------------------------------------------- #
# A SEPARATE axis from evidence_class, deliberately. Status is about the MECHANICS
# (did the collection run to completion?); class is about PROVENANCE (where does
# this value come from?). A record can be `observed` and `partial` at once — some
# of its fields answered and some did not — and folding the two axes into one would
# force a choice between calling that an observation and calling it a failure.
CS_COLLECTED = "collected"
CS_PARTIAL = "partial"
CS_NOT_ATTEMPTED = "not_attempted"
CS_FAILED = "failed"
COLLECTION_STATUSES = (CS_COLLECTED, CS_PARTIAL, CS_NOT_ATTEMPTED, CS_FAILED)

# ---- failure codes -------------------------------------------------------- #
# LITERAL strings from the registered WF vocabulary, under the same import
# constraint as the evidence classes above. Each line cites the declaration it
# copies so the duplication is auditable rather than invisible.
FC_ACTOR_ENUMERATION = "WF1072_SCENE_SURVEY_ACTOR_ENUMERATION_INVALID"   # :1162
FC_ACTOR_BOUNDS = "WF1073_SCENE_SURVEY_ACTOR_BOUNDS_MISSING"            # :1163
FC_COMPONENT_STATE = "WF1074_SCENE_SURVEY_COMPONENT_STATE_INVALID"      # :1164
FC_SUPPORT_SAMPLE = "WF1075_SCENE_SURVEY_SUPPORT_SAMPLE_INVALID"        # :1166
FC_PLACEMENT_INVALID = "WF1082_SCENE_SURVEY_PLACEMENT_INVALID"          # :1174
FC_CLEARANCE_MISSING = "WF1085_SCENE_SURVEY_PLACEMENT_CLEARANCE_MISSING"  # :1177
FC_CLEANUP_UNVERIFIED = "WF1092_SCENE_SURVEY_CLEANUP_UNVERIFIED"        # :1185
FC_REPORT_INVALID = "WF1062_SCENE_SURVEY_REPORT_INVALID"                # :1149
FC_WORLD_IDENTITY = "WF1122_SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED"     # :1224
FC_OBSERVATION_FAILED = "WF1123_SCENE_SURVEY_OBSERVATION_FAILED"        # :1225
# All ten are declared in tools/pipeline/failure_codes.py at the cited lines.
FAILURE_CODES = (FC_ACTOR_ENUMERATION, FC_ACTOR_BOUNDS, FC_COMPONENT_STATE,
                 FC_SUPPORT_SAMPLE, FC_PLACEMENT_INVALID, FC_CLEARANCE_MISSING,
                 FC_CLEANUP_UNVERIFIED, FC_REPORT_INVALID, FC_WORLD_IDENTITY,
                 FC_OBSERVATION_FAILED)

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

# ---- source_api names ----------------------------------------------------- #
# The EXACT Unreal call each raw value came from, named once so a record and its
# collector can never disagree about which API answered. This is the field that
# lets a later reader separate an OBSERVATION from an INFERENCE: a value whose
# source_api names a call was read from the engine; one whose provenance lives in
# `derived_fields` was computed from values that were.
TRACE_API = "unreal.SystemLibrary.line_trace_single"
BREAK_HIT_API = "unreal.GameplayStatics.break_hit_result"
CAPSULE_ACTORS_API = "unreal.SystemLibrary.capsule_overlap_actors"
CAPSULE_COMPONENTS_API = "unreal.SystemLibrary.capsule_overlap_components"
COMPONENT_BOUNDS_API = "unreal.SystemLibrary.get_component_bounds"
LEVEL_ACTORS_API = "unreal.EditorActorSubsystem.get_all_level_actors"
COMPONENTS_BY_CLASS_API = "unreal.Actor.get_components_by_class"
WORLD_PACKAGE_API = "unreal.World.get_package().get_name()"
DIRTY_PACKAGES_API = "unreal.EditorLoadingAndSavingUtils.{}"
SPAWN_API = "unreal.EditorActorSubsystem.spawn_actor_from_class"
DESTROY_API = "unreal.EditorActorSubsystem.destroy_actor"
IS_VALID_API = "unreal.SystemLibrary.is_valid"

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


def _env_text(name, default=None):
    """Parse a TEXT env var. Returns (value, error_or_None) and NEVER raises.

    The text sibling of ``_env_number``, with the identical contract — no exception
    can escape and a malformed value degrades to the documented default plus a
    recorded reason. ``_env_number`` cannot simply be reused for text: its finiteness
    rail runs ``float()`` over the parsed value, which every non-numeric string
    fails, so a perfectly good digest would be discarded as "not finite".
    """
    raw = os.environ.get(name)
    if raw is None:
        return default, None
    try:
        value = str(raw).strip()
    except Exception:  # noqa: BLE001
        return default, "{} could not be read as text — using default {!r}".format(
            name, default)
    if not value:
        return default, None
    if len(value.split()) != 1:
        return default, ("{}={!r} contains whitespace; an opaque token cannot — "
                         "using default {!r}".format(name, raw, default))
    return value, None


RADIUS, _RADIUS_ERR = _env_number("WF_SURVEY_RADIUS_CM", 3000.0, float)
STEP, _STEP_ERR = _env_number("WF_SURVEY_STEP_CM", 100.0, float)
MARKERS, _MARKERS_ERR = _env_number("WF_SURVEY_MARKERS", 3, int)

# The caller's request digest. CALLER_SUPPLIED and never checked here: the far side
# does not see the BridgeRequest field set that produced it
# (tools/pipeline/scene_survey_operation.py:579-597), so it has nothing to recompute
# from and any "validation" it performed would be theatre. It is carried verbatim.
REQUEST_HASH, _REQUEST_HASH_ERR = _env_text("WF_SURVEY_REQUEST_HASH", None)
if REQUEST_HASH is None and not _REQUEST_HASH_ERR:
    _REQUEST_HASH_ERR = (
        "WF_SURVEY_REQUEST_HASH was not set — every record carries "
        "request_hash=None. The far side cannot recompute the digest, so an absent "
        "hash stays absent; inventing or defaulting one would turn a replay check "
        "into a rubber stamp.")
# The algorithm is READ OFF the supplied value's documented "<algorithm>:<hex>"
# shape (scene_survey_operation.py:663). It is not a second knob that could disagree
# with the digest it describes, and it is None when the shape says nothing.
REQUEST_HASH_ALGORITHM = (REQUEST_HASH.split(":", 1)[0]
                          if isinstance(REQUEST_HASH, str) and ":" in REQUEST_HASH
                          else None)

ENV_PARSE_ERRORS = [e for e in (_RADIUS_ERR, _STEP_ERR, _MARKERS_ERR,
                                _REQUEST_HASH_ERR) if e]


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

    RUNTIME-VERIFIED symbol (parallel lane's live UE 5.8 -nullrhi boot, engine
    5.8.0-55116800; not verified in this process): returned a usable package name.
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
# the record envelope — see THE RECORD ENVELOPE in the module docstring.
# --------------------------------------------------------------------------- #
# The observed world identity, cached. Every record's envelope needs it and none of
# them should pay another reflected call (or add another failure point) to re-read
# it: it is read ONCE, by `_record_world`, from the live editor. It stays None until
# then, and stays None forever if it could not be read — it is NEVER back-filled
# from the requested map path, which would make the envelope an echo of the request
# instead of a measurement, and would make an identity mismatch invisible.
_OBSERVED_WORLD = {"package_name": None}


def _world_identity():
    return _OBSERVED_WORLD["package_name"]


def _raw_ref(kind, ident):
    """``"<kind>#<ident>"`` — the raw_ref form the evidence model resolves
    (tools/pipeline/scene_survey_evidence.py:245-246).

    A record's ``record_id`` IS this string, built from the very pair the record is
    filed under, so a ref and the id it points at cannot drift apart and the id
    cannot collide with another record's: two records with the same id would have to
    be the same dict entry.
    """
    return "{}#{}".format(kind, ident)


# The envelope's own field list, declared once and emitted with the document, so a
# reader can check that a record carries the full envelope without knowing this
# file. Kept beside `_envelope` because the two must agree — and drift between them
# is MEASURED, not trusted: `_record_ref_integrity` walks every record against this
# tuple and files the ones that are missing a field (INV-ENV).
RECORD_ENVELOPE_FIELDS = (
    "record_schema", "operation_id", "request_hash", "request_hash_algorithm",
    "record_id", "record_type", "record_ident", "stage", "collector",
    "collection_status", "evidence_class", "source_api", "world_identity",
    "actor_object_path", "component_object_path", "failure_code", "derived_fields",
    "measured_fields",
)


def _envelope(record_type, ident, stage, collector, source_api=None,
              actor_object_path=None, component_object_path=None,
              measured_fields=()):
    """The envelope every raw record carries.

    Constructed in the NOT-YET-COLLECTED state on purpose: ``collection_status``
    starts at ``not_attempted`` and ``evidence_class`` at ``not_requested``, so a
    record that is filed and then abandoned mid-collection — because a call threw,
    or because a `return` was taken on an error path — reads as "this did not
    happen" rather than inheriting an optimistic default nobody set. `_settle` is
    the only thing that moves it off that state.
    """
    return {
        "record_schema": RAW_RECORD_SCHEMA,
        "operation_id": OPERATION_ID,
        "request_hash": REQUEST_HASH,
        "request_hash_algorithm": REQUEST_HASH_ALGORITHM,
        "record_id": _raw_ref(record_type, ident),
        "record_type": record_type,
        "record_ident": ident,
        "stage": stage,
        "collector": collector,
        "collection_status": CS_NOT_ATTEMPTED,
        "evidence_class": EC_NOT_REQUESTED,
        "source_api": source_api,
        "world_identity": _world_identity(),
        "actor_object_path": actor_object_path,
        "component_object_path": component_object_path,
        "failure_code": None,
        "derived_fields": {},
        "measured_fields": list(measured_fields),
    }


def _settle(rec, collected, failure_code=None, evidence_class=None, detail=None):
    """Close a record: fix collection_status, evidence_class and failure_code.

    ``collected`` is TRI-STATE and answers the MECHANICAL question only:

        True  — the collection ran and produced its measurements
        False — the collection ran, or was refused, and produced none
        None  — the collection was never attempted

    The status is then refined by the record's OWN error list: a record that
    collected something AND recorded an error is ``partial``, a fact that neither
    "collected" nor "failed" can express and that a single boolean would have to
    round to one of them. ``evidence_class`` may be overridden for the cases the
    mechanics cannot see — a capability this pass genuinely cannot provide is
    ``unsupported``, not ``failed``, however cleanly it did not run.

    Returns the record so callers can ``return _settle(rec, ...)``.
    """
    errors = rec.get("errors") or []
    if collected is True:
        rec["collection_status"] = CS_PARTIAL if errors else CS_COLLECTED
        cls = evidence_class or EC_OBSERVED
    elif collected is False:
        rec["collection_status"] = CS_FAILED
        cls = evidence_class or EC_FAILED
    else:
        rec["collection_status"] = CS_NOT_ATTEMPTED
        cls = evidence_class or EC_NOT_REQUESTED
    # An unrecognised class is not permitted to pass through as itself: "unknown
    # provenance" must never read as "fine" (scene_survey_evidence.py:70-72).
    rec["evidence_class"] = cls if cls in EVIDENCE_CLASSES else EC_FAILED
    # The two axes are separate but not independent, and this is where they are
    # reconciled. `not_requested` and `unsupported` both mean the collection DID NOT
    # HAPPEN, so their mechanical status is `not_attempted` whatever the caller
    # passed — a refusal reported as `failed` claims an attempt that was never made,
    # and `failed` is the one status that reads as an incident.
    if rec["evidence_class"] in (EC_NOT_REQUESTED, EC_UNSUPPORTED):
        rec["collection_status"] = CS_NOT_ATTEMPTED
    elif rec["evidence_class"] == EC_FAILED:
        rec["collection_status"] = CS_FAILED
    # A failure code belongs to a FAILURE. not_requested and unsupported are not
    # failures — nothing broke; the question was never asked, or cannot be asked in
    # this pass — so attaching a code there would manufacture an incident.
    if rec["evidence_class"] == EC_FAILED:
        rec["failure_code"] = (failure_code if failure_code in FAILURE_CODES
                               else FC_OBSERVATION_FAILED)
    else:
        rec["failure_code"] = None
    if detail:
        rec["detail"] = str(detail)
    # The rule with teeth. A record that carries no evidence must carry no values,
    # and that is enforced HERE, mechanically, rather than trusted to each collector
    # remembering to leave its fields None. "We always leave those None" is exactly
    # the kind of claim that rots the first time someone adds a field.
    if rec["evidence_class"] in EC_NON_SATISFYING:
        for name in rec.get("measured_fields") or ():
            if name in rec:
                rec[name] = None
    return rec


def _derived(rec, field, value, derivation, inputs, source_api=None):
    """Set a COMPUTED field on ``rec`` and register HOW it was computed.

    A convenience value with no entry in ``derived_fields`` is an observation. One
    with an entry states its own formula and its own inputs, so a later reader can
    RECOMPUTE it from the atoms preserved in the same bundle instead of believing
    it. That is the whole difference between a derivation and an assertion
    (scene_survey_evidence.py:200-210).
    """
    rec[field] = value
    rec["derived_fields"][field] = {
        "evidence_class": EC_DERIVED,
        "derivation": derivation,
        "inputs": list(inputs),
        "source_api": source_api,
    }
    return value


def _vec_sub(a, b):
    """Component-wise a - b, or None if either side is not a finite vec3."""
    if not (_finite_vec3(a) and _finite_vec3(b)):
        return None
    out = [float(a[i]) - float(b[i]) for i in range(3)]
    return out if _finite_vec3(out) else None


def _vec_add(a, b):
    if not (_finite_vec3(a) and _finite_vec3(b)):
        return None
    out = [float(a[i]) + float(b[i]) for i in range(3)]
    return out if _finite_vec3(out) else None


def _unit_and_dot_up(v):
    """(unit_vector, n_hat . z_hat) for a surface normal, or (None, None).

    The engine's impact normal is nominally unit length, but "nominally" is not a
    measurement: a degenerate or unnormalised normal would make the dot product
    silently wrong rather than absent, so the magnitude is computed and a zero or
    non-finite one yields None on both outputs.
    """
    if not _finite_vec3(v):
        return None, None
    mag = math.sqrt(sum(float(x) ** 2 for x in v))
    if not math.isfinite(mag) or mag <= 0.0:
        return None, None
    unit = [float(x) / mag for x in v]
    if not _finite_vec3(unit):
        return None, None
    dot = unit[2]  # n_hat . z_hat with z_hat = (0, 0, 1)
    return unit, (dot if math.isfinite(dot) else None)


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

    RUNTIME-VERIFIED symbol (parallel lane's live UE 5.8 -nullrhi boot, engine
    5.8.0-55116800; not verified in this process): the TWO-argument form
    ``get_actor_bounds(only_colliding, include_from_child_actors)`` answered. The
    one-argument fallback and the guard are KEPT anyway — a verified shape on one
    engine build is not a guaranteed shape on every one, and a signature drift must
    still degrade to a recorded reason rather than to a missing bounds record that
    reads like "no bounds here".
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

    RUNTIME-VERIFIED symbol (parallel lane's live UE 5.8 -nullrhi boot, engine
    5.8.0-55116800; not verified in this process): the 3-tuple return
    (origin, extent, radius) was confirmed (UE 5.8 KismetSystemLibrary.h:1756). The
    shape guard is kept regardless.
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
    rec = _envelope("trace", ident, ST_OBSERVE, "scene_survey_far_side._line_trace",
                    source_api=TRACE_API,
                    measured_fields=("hit", "blocking_hit", "distance", "location",
                                     "impact_point", "impact_normal",
                                     "hit_actor_path", "hit_component_path"))
    rec.update({
        "purpose": purpose,
        "api": TRACE_API,
        "channel": "TraceTypeQuery1(Visibility)",
        "trace_complex": True,
        "start": start,
        "end": end,
        "hit": None,
        "blocking_hit": None,
        "distance": None,
        "location": None,
        "impact_point": None,
        "impact_normal": None,
        "hit_actor_path": None,
        "hit_component_path": None,
        "collection_ok": False,
        "errors": [],
    })
    raw["trace"][ident] = rec
    channel, debug = _trace_channel(), _draw_debug_none()
    if channel is None or debug is None:
        rec["errors"].append("TraceTypeQuery/DrawDebugTrace enum members are not reflected "
                             "under any name this script knows; no trace was attempted")
        return _settle(rec, False, FC_SUPPORT_SAMPLE)
    if not (_finite_vec3(start) and _finite_vec3(end)):
        rec["errors"].append("trace endpoints are not finite vec3s; no trace was attempted")
        return _settle(rec, False, FC_SUPPORT_SAMPLE)
    try:
        res = unreal.SystemLibrary.line_trace_single(
            world, unreal.Vector(start[0], start[1], start[2]),
            unreal.Vector(end[0], end[1], end[2]), channel, True, [], debug, True)
    except Exception as exc:  # noqa: BLE001
        rec["errors"].append("line_trace_single: {}: {}".format(type(exc).__name__, exc))
        return _settle(rec, False, FC_SUPPORT_SAMPLE)
    hit, out_hit = _unpack_out(res)
    if hit is None:
        rec["errors"].append("line_trace_single returned an unrecognised shape {!r}; the "
                             "hit/miss answer was NOT read".format(type(res).__name__))
        return _settle(rec, False, FC_SUPPORT_SAMPLE)
    rec["hit"] = bool(hit)
    rec["collection_ok"] = True
    if out_hit is not None:
        fields, err = _break_hit(out_hit)
        for k, v in fields.items():
            rec[k] = v
        rec["hit_actor_object_path"] = rec.get("hit_actor_path")
        rec["actor_object_path"] = rec.get("hit_actor_path")
        rec["component_object_path"] = rec.get("hit_component_path")
        if err:
            rec["errors"].append(err)
            rec["source_api"] = TRACE_API + " (+ " + BREAK_HIT_API + " unread)"
        else:
            rec["source_api"] = TRACE_API + " + " + BREAK_HIT_API
    else:
        rec["errors"].append("no FHitResult out-parameter was returned; only the hit "
                             "boolean was observed")
    return _settle(rec, True)


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


def _capsule_overlap_component_paths(world, center, radius, half_height,
                                     object_type_index):
    """(component_path_list, error). None (not []) when the query could not be run.

    ASSUMED symbol: ``SystemLibrary.capsule_overlap_components(world_context, center,
    radius, half_height, object_types, component_class_filter, actors_to_ignore)``
    returning ``(bool, [PrimitiveComponent])``.

    Actor paths alone cannot say WHAT inside an actor blocks a capsule: a large
    actor with one small collider and a large actor that is solid produce the same
    actor path. The component set is the atom that makes an overlap claim
    recomputable, so it is collected separately and degrades to None on its own.
    """
    otype = _object_type(object_type_index)
    if otype is None:
        return None, "ObjectTypeQuery{} is not reflected".format(object_type_index)
    if not _finite_vec3(center):
        return None, "capsule centre is not a finite vec3"
    try:
        res = unreal.SystemLibrary.capsule_overlap_components(
            world, unreal.Vector(center[0], center[1], center[2]),
            float(radius), float(half_height), [otype], None, [])
    except Exception as exc:  # noqa: BLE001
        return None, "capsule_overlap_components: {}: {}".format(type(exc).__name__, exc)
    _ok, comps = _unpack_out(res)
    if comps is None:
        if isinstance(res, (tuple, list)) and len(res) == 1:
            comps = res[0]
        else:
            return None, ("capsule_overlap_components returned an unrecognised shape "
                          "{!r}; the overlap set was NOT read".format(type(res).__name__))
    try:
        return sorted(p for p in (_path_of(c) for c in comps) if p), None
    except Exception as exc:  # noqa: BLE001
        return None, "capsule_overlap_components result is not iterable: {}".format(exc)


def _union_or_none(*sets):
    """Sorted union of path lists, or None if ANY input is None.

    None propagates on purpose. A union that quietly skipped an unread input would
    report a SMALLER overlap set than was actually queried, and a smaller overlap
    set reads as "clearer" — the single most dangerous direction for this value to
    be wrong in.
    """
    out = set()
    for s in sets:
        if s is None:
            return None
        out |= set(s)
    return sorted(out)


def _collect_overlap_query(raw, world, ident, center, radius, half_height):
    """Run the capsule overlap queries for ONE candidate and file a raw record.

    One record per candidate, covering BOTH object-type queries, so a marker can
    carry a single ``overlap_query_ref`` that resolves. Static and dynamic remain
    separately readable inside it: collapsing them would lose which population
    blocked the capsule.
    """
    rec = _envelope("overlap_query", ident, ST_CLASSIFY,
                    "scene_survey_far_side._collect_overlap_query",
                    source_api=CAPSULE_ACTORS_API + " + " + CAPSULE_COMPONENTS_API,
                    measured_fields=("static_actor_paths", "dynamic_actor_paths",
                                     "static_component_paths",
                                     "dynamic_component_paths",
                                     "actor_paths", "component_paths"))
    rec.update({
        "center": center if _finite_vec3(center) else None,
        "radius": _num(radius),
        "half_height": _num(half_height),
        "object_type_queries": [1, 2],
        "object_type_meaning": {"1": "WorldStatic", "2": "WorldDynamic"},
        "static_actor_paths": None,
        "dynamic_actor_paths": None,
        "static_component_paths": None,
        "dynamic_component_paths": None,
        "actor_paths": None,
        "component_paths": None,
        "collection_ok": False,
        "errors": [],
    })
    raw["overlap_query"][ident] = rec
    if world is None or not _finite_vec3(center):
        rec["errors"].append("no world or non-finite capsule centre; no overlap query "
                             "was attempted")
        return _settle(rec, False, FC_CLEARANCE_MISSING)

    static_a, sa_err = _capsule_overlap_actor_paths(world, center, radius,
                                                    half_height, 1)
    dynamic_a, da_err = _capsule_overlap_actor_paths(world, center, radius,
                                                     half_height, 2)
    static_c, sc_err = _capsule_overlap_component_paths(world, center, radius,
                                                        half_height, 1)
    dynamic_c, dc_err = _capsule_overlap_component_paths(world, center, radius,
                                                         half_height, 2)
    rec["static_actor_paths"] = static_a
    rec["dynamic_actor_paths"] = dynamic_a
    rec["static_component_paths"] = static_c
    rec["dynamic_component_paths"] = dynamic_c
    for e in (sa_err, da_err, sc_err, dc_err):
        if e:
            rec["errors"].append(e)
    _derived(rec, "actor_paths", _union_or_none(static_a, dynamic_a),
             "sorted(set(static_actor_paths) | set(dynamic_actor_paths)); None if "
             "either sub-query was unread",
             ["static_actor_paths", "dynamic_actor_paths"],
             source_api=CAPSULE_ACTORS_API)
    _derived(rec, "component_paths", _union_or_none(static_c, dynamic_c),
             "sorted(set(static_component_paths) | set(dynamic_component_paths)); "
             "None if either sub-query was unread",
             ["static_component_paths", "dynamic_component_paths"],
             source_api=CAPSULE_COMPONENTS_API)
    # `collection_ok` answers the CLEARANCE question specifically: it is True only
    # when the actor union was read, because that is the channel the clearance claim
    # is derived from. The RECORD, though, is `failed` only when NOTHING answered —
    # a record that measured three of four sub-queries is `observed`/`partial`, and
    # settling it as failed would make `_settle` void the three real measurements it
    # did take.
    rec["collection_ok"] = rec["actor_paths"] is not None
    answered = [x for x in (static_a, dynamic_a, static_c, dynamic_c) if x is not None]
    if answered:
        return _settle(rec, True)
    return _settle(rec, False, FC_CLEARANCE_MISSING)


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

    RUNTIME-VERIFIED symbols (parallel lane's live UE 5.8 -nullrhi boot, engine
    5.8.0-55116800; not verified in this process): both getters returned readable
    sets. The guard is kept regardless.
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


def _is_valid(obj):
    """True/False/None — does this UObject still exist? None means UNREAD.

    RUNTIME-VERIFIED by a parallel lane's live UE 5.8 -nullrhi boot (engine
    5.8.0-55116800) against a fixture map: ``SystemLibrary.is_valid`` returned True
    before ``destroy_actor`` and False after. That is the ONLY channel in this file
    that can say "no" about a transient actor's destruction — see `_SpawnLedger`.
    ``UObject.is_valid`` is kept as a fallback shape, and a reading that is not a
    bool degrades to None rather than to a plausible answer.
    """
    if obj is None:
        return None
    try:
        return bool(unreal.SystemLibrary.is_valid(obj))
    except Exception:  # noqa: BLE001
        pass
    try:
        got = obj.is_valid()
    except Exception:  # noqa: BLE001
        return None
    return bool(got) if isinstance(got, bool) else None


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
# Why level enumeration cannot witness a transient actor's destruction. Stated once,
# emitted into every temporary_placement record, so the vacuity travels with the
# evidence instead of living only in a comment nobody downstream reads.
ENUMERATION_VACUITY_REASON = (
    "an actor spawned with transient=True is never returned by "
    "EditorActorSubsystem.get_all_level_actors() at all (measured 1 -> 1 across a "
    "transient spawn on a live UE 5.8 -nullrhi boot, engine 5.8.0-55116800; a "
    "NON-transient spawn measured 234 -> 235 in this repo's committed evidence at "
    "procedural/evidence/ue5_8/runtime_smoke.json). Its absence from the enumeration "
    "is therefore true before destruction as well as after, so it cannot distinguish "
    "a destroyed object from a live one. absent_after_cleanup is derived from "
    "is_valid instead, which the same boot verified answers True before destroy and "
    "False after.")

# --------------------------------------------------------------------------- #
# ledger vocabulary — CLOSED sets, so no reader has to interpret free text
# --------------------------------------------------------------------------- #
# The tag stamped on every object this operation creates. Ownership is what makes
# O_created a SET at all: without it "an object that appeared" and "an object WE
# made" are the same sentence, and only the second one is this operation's to clean
# up. It is per-operation, so two concurrent surveys cannot claim each other's
# objects.
OWNERSHIP_TAG_PREFIX = "worldforge.scene_survey"


def _ownership_tag():
    return "{}/{}".format(OWNERSHIP_TAG_PREFIX, OPERATION_ID)


# `post_cleanup_presence` — the WITNESSED final state of one owned object. CLOSED.
# `unknown` is a member on purpose: "we could not look" is a state of the
# observation, and it must not be spellable as "absent". `never_created` is the
# other one that matters — an object that was refused or failed to spawn was never
# there to leak, and that is a measurement of this operation, not a hole in it.
PRESENCE_NEVER_CREATED = "never_created"
PRESENCE_ABSENT = "absent"
PRESENCE_PRESENT = "present"
PRESENCE_UNKNOWN = "unknown"
PRESENCE_STATES = (PRESENCE_NEVER_CREATED, PRESENCE_ABSENT, PRESENCE_PRESENT,
                   PRESENCE_UNKNOWN)

# `destruction_result` — the DESTROY CALL's own outcome and nothing more, i.e. the
# runtime's claim about itself. CLOSED. Removal is witnessed separately, by
# `post_cleanup_presence`, which is measured afterwards through a DIFFERENT api
# (`SystemLibrary.is_valid`). The two are kept apart because the whole hazard this
# ledger exists for is a destroy that returns True over an object that is still
# there — a single "cleaned_up" boolean could not express that at all.
DESTRUCTION_NOT_ATTEMPTED = "not_attempted"
DESTRUCTION_DESTROYED = "destroyed"
DESTRUCTION_RETURNED_FALSE = "destroy_returned_false"
DESTRUCTION_ERROR = "error"
DESTRUCTION_UNKNOWN = "unknown"
DESTRUCTION_RESULTS = (DESTRUCTION_NOT_ATTEMPTED, DESTRUCTION_DESTROYED,
                       DESTRUCTION_RETURNED_FALSE, DESTRUCTION_ERROR,
                       DESTRUCTION_UNKNOWN)

# P, the persistent-package term of CleanupVerified, has two halves and only ONE of
# them is observable from UE Python.
#
#   P as IDENTITY  — which package is open. Observable: it is the world package
#                    name every inventory already carries as `package_identity`,
#                    and the assembler ANDs it into the verdict.
#   P as CONTENT   — a hash/digest of the persistent package's bytes, which is what
#                    would prove the on-disk asset did not change. NOT observable:
#                    see the reason below.
#
# The content half is emitted as `unsupported` with a null value rather than being
# quietly dropped or defaulted to "equal", because an unavailable comparison that
# reads as agreement is precisely a fabricated pass.
PACKAGE_HASH_UNSUPPORTED_REASON = (
    "no UE Python api exposes a content hash or save-state digest of a persistent "
    "package: UPackage.is_dirty(), UPackage.get_file_size() and the package GUID "
    "are not reflected to Python, and the only package-level state Python can read "
    "is MEMBERSHIP of the editor's dirty-package sets "
    "(unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages / "
    "get_dirty_content_packages), which is a boolean per package and not a digest. "
    "Hashing the .umap on disk would answer a different question — whether the file "
    "changed — and would still be blind to an in-memory mutation that was never "
    "saved, which is the mutation a survey is most likely to cause. P_1 == P_0 is "
    "therefore reported as UNSUPPORTED with value None; the observable identity half "
    "is reported separately as persistent_package_identity_equal.")

# The ledger's own record. Filed under `document` rather than `temporary_placement`
# so it is not mistaken for a placement and does not join that predicate's
# population. Its ABSENCE is the signal the consumer keys on: a cleanup verdict
# derived from two inventory snapshots alone cannot see an object that was created
# AND destroyed between them, so no ledger means `unknown`, never success.
LEDGER_KIND = "document"
LEDGER_IDENT = "temporary_object_ledger"


def _spawn_call_sites():
    """(total, ledgered) occurrences of the spawn call in THIS module's source.

    "every temporary object is created through the ledger" is a claim about the
    CODE, and a claim about the code that nobody measures is a comment. This counts
    the literal spawn call in the module and in `spawn_transient` alone; the
    consumer refuses the cleanup verdict when the two disagree, because a second
    spawn path means the ledger's object set can be incomplete and an incomplete
    O_created makes the per-object conjunct vacuous.

    (None, None) when the source cannot be read — that is a hole in this
    introspection, not an observation about the world, and it is reported as such.
    """
    token = "spawn_actor_from_class" + "("  # split so this line is not itself a hit
    try:
        path = inspect.getsourcefile(_SpawnLedger)
        with open(path, "r", encoding="utf-8") as fh:
            module_src = fh.read()
        fn_src = "".join(inspect.getsourcelines(_SpawnLedger.spawn_transient)[0])
    except Exception:  # noqa: BLE001
        return None, None
    return module_src.count(token), fn_src.count(token)


# The MEASUREMENT fields of a temporary_placement record. `ident`,
# `requested_location`, `transient`, `spawn_attempted` and `spawn_ok` are the
# ACTION's own record — what this operation did — and stay readable on a refused or
# failed record, because a refusal nobody can attribute is not an honest refusal.
# `creation_observed`, `destruction_attempted`, `destruction_result` and
# `post_cleanup_presence` are in that same category and are deliberately NOT listed
# here: on a refused spawn they carry `False` / `not_attempted` / `never_created`,
# which are the true statements about an object that never existed. Blanking them
# to None would turn "nothing was created, so nothing can have leaked" into "we do
# not know", and the consumer would have to guess which one it was.
PLACEMENT_MEASURED = ("path_name", "destroy_returned", "absent_after_cleanup",
                      "is_valid_before_destroy", "is_valid_after_destroy",
                      "enumeration_present_before_cleanup",
                      "enumeration_present_after_cleanup",
                      "enumeration_absent_after_cleanup")


class _SpawnLedger:
    """Tracks every object THIS operation creates, and re-observes its removal.

    The survey as it stands spawns NOTHING (marker clearance is trace-probed, never
    placed), so ``owned_paths()`` is legitimately empty and that emptiness is a
    measurement, not a default. The ledger exists so that any future spawn is
    physically unable to escape the pre/post comparison: it spawns transiently only
    (``transient=True`` is the only safe spawn — a ScopedEditorTransaction cancel
    does NOT restore a package's dirty flag, and no Python API reads or clears one),
    it refuses to spawn when PIE state is unknown or active, and after destroying it
    RE-OBSERVES the object rather than trusting ``destroy_actor``'s return.

    HAZARD FIXED — the unfalsifiable cleanup rail
    ---------------------------------------------
    That re-observation used to be ``path not in get_all_level_actors()``. A
    parallel lane's LIVE UE 5.8 -nullrhi boot (engine 5.8.0-55116800, fixture map)
    measured that an actor spawned with ``transient=True`` is NEVER returned by
    ``EditorActorSubsystem.get_all_level_actors()`` at all — 1 -> 1 across a
    transient spawn, against 234 -> 235 for a NON-transient spawn in this repo's
    committed evidence (procedural/evidence/ue5_8/runtime_smoke.json, produced by
    tools/pipeline/wf_runtime_smoke.py:56, which passes no transient kwarg).

    Since this ledger MANDATES ``transient=True``, the spawned actor was never in
    the enumeration to begin with, so ``path not in present`` was True whether or
    not ``destroy_actor`` did anything. The rail could not fail. It was read as
    proof of cleanup by the evidence model's PRED_TEMPORARY_CLEANUP predicate
    (tools/pipeline/scene_survey_evidence.py:828-836), which makes it precisely the
    fake-green this whole scheme exists to eliminate.

    ``absent_after_cleanup`` is therefore now derived from ``is_valid``, which the
    same boot verified CAN say no (True before destroy, False after). The
    enumeration observations are still emitted — as their own atoms, alongside an
    explicit ``enumeration_absence_is_vacuous`` flag — so nothing is lost and no
    future reader can mistake enumeration-absence for evidence again.
    """

    def __init__(self, raw):
        self.raw = raw
        self.spawned = []          # [(ident, actor)]
        self.created = []          # every object_id creation was OBSERVED for
        self.cleanup_ran = False
        self.ownership_tag = _ownership_tag()
        self.policy = ("transient-only; this pass spawns nothing (marker clearance is "
                       "trace-probed, never placed)")
        # Filed at CONSTRUCTION, not at cleanup. The manifest's absence is what tells
        # the consumer that no ledger was installed at all, so it must exist from the
        # moment the ledger does — including on every early-error path, where a
        # manifest written only at the end would be missing for the opposite reason.
        self.write_manifest()

    def write_manifest(self):
        """File/refresh the ledger's own record: what it owns, and whether it ran.

        This is the artifact the cleanup rail is gated on. It states, in one place
        and as RAW, the three things two inventory snapshots cannot say:

          * the COMPLETE set of object ids this operation created (O_created), so a
            consumer can iterate them rather than infer them from a diff that never
            saw the short-lived ones;
          * that cleanup actually RAN, as opposed to having been skipped by an early
            return that left the post snapshot looking identical to the pre one;
          * that `spawn_transient` is the only spawn path in this module, measured
            from the source rather than asserted.

        No verdict is computed here. The far side emits raw; the assembler derives.
        """
        total_sites, ledgered_sites = _spawn_call_sites()
        rec = _envelope(LEDGER_KIND, LEDGER_IDENT, ST_CLEANUP if self.cleanup_ran
                        else ST_PREPARATION,
                        "scene_survey_far_side._SpawnLedger.write_manifest",
                        source_api=" + ".join((SPAWN_API, DESTROY_API, IS_VALID_API)),
                        measured_fields=())
        object_ids = sorted(str(k) for k in (self.raw.get(
            "temporary_placement") or {}))
        rec.update({
            "is_temporary_object_ledger": True,
            "ownership_tag": self.ownership_tag,
            "spawn_policy": self.policy,
            "spawn_entry_point": ("scene_survey_far_side._SpawnLedger."
                                  "spawn_transient"),
            "spawn_call_sites_in_module": total_sites,
            "spawn_call_sites_in_ledger": ledgered_sites,
            # None when the source could not be read: an unmeasured introspection,
            # NOT an observation that there are no stray spawn paths.
            "unledgered_spawn_call_sites": (
                None if (total_sites is None or ledgered_sites is None)
                else total_sites - ledgered_sites),
            "object_ids": object_ids,
            "object_count": len(object_ids),
            "created_object_ids": sorted(str(i) for i in self.created),
            "created_object_count": len(self.created),
            "still_owned_object_ids": sorted(str(i) for i, _a in self.spawned),
            "temporary_object_refs": [_raw_ref("temporary_placement", i)
                                      for i in object_ids],
            "cleanup_ran": bool(self.cleanup_ran),
            "package_identity": _world_identity(),
            # P, the persistent-package term, split into its observable and its
            # unobservable half. See PACKAGE_HASH_UNSUPPORTED_REASON.
            "persistent_package_hash": None,
            "persistent_package_hash_supported": False,
            "persistent_package_hash_evidence_class": EC_UNSUPPORTED,
            "persistent_package_hash_unsupported_reason":
                PACKAGE_HASH_UNSUPPORTED_REASON,
            "presence_states": list(PRESENCE_STATES),
            "destruction_results": list(DESTRUCTION_RESULTS),
            "collection_ok": True,
            "errors": [],
        })
        self.raw.setdefault(LEDGER_KIND, {})[LEDGER_IDENT] = _settle(rec, True)
        return rec

    def owned_paths(self):
        """Paths of objects still owned by this operation. [] is a measurement."""
        out = []
        for ident, actor in self.spawned:
            p = _path_of(actor)
            out.append(p if p else "temporary_placement#{}".format(ident))
        return sorted(out)

    def spawn_transient(self, world, actor_class, location, ident):
        """Spawn ONE tracked transient actor, or file an honest refusal record.

        THE spawn path. Every operation-owned temporary object is created here or
        it is not created at all — `_spawn_call_sites` measures that from the
        module source and the assembler refuses the cleanup verdict when a second
        spawn call appears, because an incomplete O_created makes the per-object
        cleanup conjunct vacuous rather than false.

        The record filed here is the object's whole life story: it is created in
        the not-yet-created state, amended by `cleanup`, and never deleted. A
        refused spawn keeps its record too — `creation_observed=False` and
        `post_cleanup_presence="never_created"` are the true statements about an
        object that never existed, and they are different facts from silence.
        """
        rec = _envelope("temporary_placement", ident, ST_OBSERVE,
                        "scene_survey_far_side._SpawnLedger.spawn_transient",
                        source_api=SPAWN_API,
                        measured_fields=PLACEMENT_MEASURED)
        rec.update({
            "ident": ident,
            # ---- identity + ownership -------------------------------------------
            # object_id is the ledger's stable handle for this object and is what the
            # manifest lists; path_name is the engine's, and is None until the object
            # exists. Two names because the ledger must be able to talk about an
            # object whose spawn was refused, which has no path.
            "object_id": ident,
            "ownership_tag": self.ownership_tag,
            "package_identity": _world_identity(),
            "requested_location": location,
            "spawn_attempted": False,
            "spawn_ok": False,
            # ---- the ledger's life-cycle vocabulary ------------------------------
            "creation_observed": False,
            "creation_stage": ST_OBSERVE,
            "destruction_attempted": False,
            "destruction_result": DESTRUCTION_NOT_ATTEMPTED,
            "post_cleanup_presence": PRESENCE_NEVER_CREATED,
            "transient": True,
            "path_name": None,
            "destroy_attempted": False,
            "destroy_returned": None,
            "absent_after_cleanup": None,
            # ---- the two cleanup channels, kept apart on purpose ----------------
            # VALIDITY: falsifiable. Runtime-verified to answer True before destroy
            # and False after, for a transient actor.
            "is_valid_before_destroy": None,
            "is_valid_after_destroy": None,
            "validity_api": IS_VALID_API,
            # ENUMERATION: VACUOUS for a transient spawn — a transient actor is
            # never enumerated, so its absence proves nothing. Emitted anyway,
            # under names that cannot be confused with a cleanup verdict, so a
            # validator can see the vacuity for itself instead of taking it on
            # faith, and so a future NON-transient spawn mode still has its atoms.
            "enumeration_present_before_cleanup": None,
            "enumeration_present_after_cleanup": None,
            "enumeration_absent_after_cleanup": None,
            "enumeration_absence_is_vacuous": True,
            "enumeration_vacuity_reason": ENUMERATION_VACUITY_REASON,
            "cleanup_channel": "is_valid",
            "collection_ok": False,
            "errors": [],
        })
        self.raw["temporary_placement"][ident] = rec
        pie = _is_in_pie()
        if pie is not False:
            rec["errors"].append(
                "refused to spawn: play-in-editor state is {!r} and spawn/destroy "
                "silently no-op during PIE".format(pie))
            # UNSUPPORTED, not failed: nothing broke. The editor is in a state where
            # this operation cannot be performed at all, and saying "failed" would
            # report an incident that did not occur.
            self.write_manifest()
            return _settle(rec, False, evidence_class=EC_UNSUPPORTED)
        if not _finite_vec3(location):
            rec["errors"].append("refused to spawn: location is not a finite vec3")
            self.write_manifest()
            return _settle(rec, False, FC_PLACEMENT_INVALID)
        rec["spawn_attempted"] = True
        try:
            sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            actor = sub.spawn_actor_from_class(
                actor_class, unreal.Vector(location[0], location[1], location[2]),
                unreal.Rotator(0.0, 0.0, 0.0), transient=True)
        except Exception as exc:  # noqa: BLE001
            rec["errors"].append("spawn_actor_from_class: {}: {}".format(
                type(exc).__name__, exc))
            self.write_manifest()
            return _settle(rec, False, FC_PLACEMENT_INVALID)
        if actor is None:
            rec["errors"].append("spawn_actor_from_class returned None")
            self.write_manifest()
            return _settle(rec, False, FC_PLACEMENT_INVALID)
        rec["spawn_ok"] = True
        rec["path_name"] = _path_of(actor)
        rec["actor_object_path"] = rec["path_name"]
        rec["collection_ok"] = True
        # CREATION OBSERVED — the spawn call returned a live object handle. From
        # here the object is in O_created and can only leave that set by being
        # witnessed gone; there is no path that un-creates it.
        rec["creation_observed"] = True
        rec["post_cleanup_presence"] = PRESENCE_UNKNOWN
        self.spawned.append((ident, actor))
        self.created.append(ident)
        self.write_manifest()
        return _settle(rec, True)

    def cleanup(self):
        """Destroy everything spawned, then RE-OBSERVE that it is gone.

        Removal is confirmed by ``is_valid``, NOT by level enumeration — see the
        class docstring for the live-boot measurement that showed why enumeration
        cannot answer this question for a transient actor. ``destroy_actor``
        returning True is recorded as a separate raw field and is never taken as the
        proof on its own: it is the runtime's claim about itself.

        Every channel is emitted with its own value and its own unknown. A channel
        that could not be read is ``None``, never ``False`` and never "absent".
        """
        # `cleanup_ran` is set FIRST and unconditionally. It answers "did the
        # operation reach its cleanup stage", which is a different question from
        # "was there anything to destroy" — and the consumer needs the first one,
        # because an early return that skipped cleanup entirely leaves a post
        # inventory that looks exactly like a clean one.
        self.cleanup_ran = True
        if not self.spawned:
            self.write_manifest()
            return
        # ---- BEFORE: both channels, while the object should still exist ---------
        before, before_err = _all_level_actors()
        present_before = (None if before is None
                          else set(p for p in (_path_of(a) for a in before) if p))
        for ident, actor in list(self.spawned):
            rec = self.raw["temporary_placement"].get(ident) or {}
            path = rec.get("path_name")
            rec["stage"] = ST_CLEANUP
            rec["source_api"] = " + ".join((SPAWN_API, DESTROY_API, IS_VALID_API))
            rec["is_valid_before_destroy"] = _is_valid(actor)
            rec["enumeration_present_before_cleanup"] = (
                None if (present_before is None or not path) else (path in present_before))
            if before_err:
                rec.setdefault("errors", []).append(
                    "pre-cleanup enumeration unavailable: {}".format(before_err))

        # ---- DESTROY -------------------------------------------------------- #
        for ident, actor in list(self.spawned):
            rec = self.raw["temporary_placement"].get(ident) or {}
            rec["destroy_attempted"] = True
            rec["destruction_attempted"] = True
            try:
                sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
                rec["destroy_returned"] = bool(sub.destroy_actor(actor))
                # The CALL's outcome, named as such. It is never the proof — the
                # proof is post_cleanup_presence, measured below through is_valid.
                rec["destruction_result"] = (
                    DESTRUCTION_DESTROYED if rec["destroy_returned"]
                    else DESTRUCTION_RETURNED_FALSE)
            except Exception as exc:  # noqa: BLE001
                rec["destruction_result"] = DESTRUCTION_ERROR
                rec.setdefault("errors", []).append(
                    "destroy_actor: {}: {}".format(type(exc).__name__, exc))

        # ---- AFTER: both channels again ------------------------------------- #
        after, after_err = _all_level_actors()
        present_after = (None if after is None
                         else set(p for p in (_path_of(a) for a in after) if p))
        if after is None:
            self._note_all("could not re-enumerate the level after cleanup: {}".format(
                after_err))
        for ident, actor in list(self.spawned):
            rec = self.raw["temporary_placement"].get(ident) or {}
            path = rec.get("path_name")
            rec["is_valid_after_destroy"] = _is_valid(actor)
            rec["enumeration_present_after_cleanup"] = (
                None if (present_after is None or not path) else (path in present_after))
            rec["enumeration_absent_after_cleanup"] = (
                None if rec["enumeration_present_after_cleanup"] is None
                else (not rec["enumeration_present_after_cleanup"]))
            # `enumeration_absence_is_vacuous` is True exactly when the object was
            # spawned transient — which this ledger mandates — because a transient
            # actor is never enumerated whether it exists or not. It is written from
            # the record's own `transient` flag rather than hard-coded, so a future
            # non-transient spawn mode reports its own honest vacuity.
            rec["enumeration_absence_is_vacuous"] = bool(rec.get("transient"))
            # THE cleanup claim, from the only channel that can say no.
            iv = rec["is_valid_after_destroy"]
            if iv is None:
                rec["absent_after_cleanup"] = None
                rec["post_cleanup_presence"] = PRESENCE_UNKNOWN
                rec["cleanup_channel"] = "is_valid(unread)"
                rec.setdefault("errors", []).append(
                    "is_valid could not be read after destroy, so the object's "
                    "removal was NOT witnessed. Enumeration-absence is not used as "
                    "a fallback: for a transient spawn it is vacuously true and "
                    "would manufacture a pass.")
                _settle(rec, True)
                continue
            _derived(rec, "absent_after_cleanup", (not iv),
                     "absent_after_cleanup = NOT is_valid_after_destroy. NOT derived "
                     "from enumeration: for a transient spawn "
                     "enumeration_absent_after_cleanup is vacuously true and cannot "
                     "fail (see enumeration_vacuity_reason)",
                     ["is_valid_after_destroy"], source_api=IS_VALID_API)
            # The same measurement, in the ledger's closed vocabulary. Registered as
            # DERIVED from the same single atom, so the two names cannot drift into
            # two opinions — and the consumer cross-checks them anyway
            # (scene_survey_evidence.contradictory_atoms).
            _derived(rec, "post_cleanup_presence",
                     PRESENCE_ABSENT if not iv else PRESENCE_PRESENT,
                     "post_cleanup_presence = 'absent' when is_valid_after_destroy "
                     "is False, 'present' when it is True, 'unknown' when it could "
                     "not be read. Never 'absent' by default.",
                     ["is_valid_after_destroy"], source_api=IS_VALID_API)
            rec["cleanup_channel"] = "is_valid"
            _settle(rec, True)
        self.spawned = []
        self.write_manifest()

    def _note_all(self, detail):
        for ident, _actor in self.spawned:
            rec = self.raw["temporary_placement"].get(ident) or {}
            rec.setdefault("errors", []).append(detail)


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
    ident = "pre" if stage == ST_ANCHOR_BIND else ("post" if stage == ST_CLEANUP
                                                   else stage)
    owned = ledger.owned_paths()
    rec = _envelope("inventory", ident, stage, "scene_survey_far_side._inventory",
                    source_api=(LEVEL_ACTORS_API + " + "
                                + DIRTY_PACKAGES_API.format(
                                    "get_dirty_map_packages/get_dirty_content_packages")),
                    measured_fields=("actor_paths", "actor_path_count",
                                     "dirty_map_packages", "dirty_content_packages",
                                     "dirty_packages"))
    rec.update({
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
        "operation_owned_actor_paths": owned,
        # The cleanup formula wants the operation-owned TEMPORARY-OBJECT set beside
        # the dirty-package sets and the map/package identity, all in one snapshot.
        # These are restatements of the ledger under the names that formula reads;
        # each resolves to a temporary_placement record in this same bundle.
        "temporary_object_paths": owned,
        "temporary_object_count": len(owned),
        "temporary_object_refs": sorted(
            _raw_ref("temporary_placement", k)
            for k in (ledger.raw.get("temporary_placement") or {})),
        "spawn_policy": ledger.policy,
        "ownership_tag": ledger.ownership_tag,
        "dirtiness_api_note": ("UPackage.is_dirty() is not exposed to Python; dirtiness "
                               "is observable only as membership of the engine's dirty "
                               "package sets"),
        # ---- P, the persistent-package term, per snapshot ---------------------- #
        # The observable half is `package_identity` above. The content half is not
        # observable at all from UE Python and is emitted as an explicit
        # `unsupported` with a NULL value — never a zero, never a placeholder hash,
        # and never omitted, because an absent field and an unavailable measurement
        # read identically to a consumer that has to guess.
        "persistent_package_identity": world_package,
        "persistent_package_hash": None,
        "persistent_package_hash_supported": False,
        "persistent_package_hash_evidence_class": EC_UNSUPPORTED,
        "persistent_package_hash_unsupported_reason": PACKAGE_HASH_UNSUPPORTED_REASON,
        "errors": [],
    })
    rec["world_identity"] = world_package
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
        _derived(rec, "dirty_packages", sorted(set(maps) | set(content)),
                 "sorted(set(dirty_map_packages) | set(dirty_content_packages)); None "
                 "if either engine set was unread",
                 ["dirty_map_packages", "dirty_content_packages"],
                 source_api=DIRTY_PACKAGES_API.format(
                     "get_dirty_map_packages/get_dirty_content_packages"))

    rec["collection_ok"] = (rec["actor_paths"] is not None
                            and rec["dirty_packages"] is not None)
    # A snapshot that read NEITHER of its two halves witnesses nothing and is
    # `failed`; one that read either half is an observation with a hole in it, and
    # `collection_ok=False` is what tells the cleanup rail not to use it
    # (scene_survey_evidence.py:369).
    if rec["actor_paths"] is None and rec["dirty_packages"] is None:
        return _settle(rec, False, FC_CLEANUP_UNVERIFIED)
    return _settle(rec, True)


# --------------------------------------------------------------------------- #
# structured spatial collectors
# --------------------------------------------------------------------------- #
# Axis order for every bounds vector in this file. Emitted alongside the vectors
# because "[x, y, z]" is a convention, and a convention that is only in a comment
# is one a reader has to guess at.
BOUNDS_AXIS_ORDER = ["x", "y", "z"]

# The MEASUREMENT fields of an actor/component record — the ones `_settle` forces
# to None on a non-satisfying record. `path_name` and `class_name` are deliberately
# NOT in these lists: identity is what makes a failure attributable, and a failed
# record with its identity blanked is a failure nobody can act on.
ACTOR_MEASURED = ("location", "rotation", "scale", "bounds_origin", "bounds_extent",
                  "bounds_min", "bounds_max", "distance_to_anchor_cm")
COMPONENT_MEASURED = ("collision_enabled", "bounds_origin", "bounds_extent",
                      "bounds_sphere_radius", "bounds_min", "bounds_max")


def _bounds_min_max(rec, origin, extent, source_api):
    """Register bounds_min / bounds_max as DERIVED from the observed origin/extent.

    The bounds predicate the assembler evaluates is stated over min and max:

        B_i = finite(min) AND finite(max) AND for every axis a: min_a <= max_a

    The engine call returns an origin and a half-extent, so min/max are computed
    here — and registered as computed, with their formula and inputs, so the
    assembler can recompute them from the same two atoms rather than trust this
    file's arithmetic. `bounds_primary` names origin/extent as the READ pair.

    An extent with a negative component would make min > max on that axis. That is
    NOT corrected here: the far side reports what the engine said, and a bounds pair
    that violates the predicate is exactly the finding B_i exists to surface.
    """
    if origin is None or extent is None:
        return
    lo = _vec_sub(origin, extent)
    hi = _vec_add(origin, extent)
    _derived(rec, "bounds_min", lo,
             "bounds_min[a] = bounds_origin[a] - bounds_extent[a] for a in "
             "bounds_axis_order; None if either input is not a finite vec3",
             ["bounds_origin", "bounds_extent"], source_api=source_api)
    _derived(rec, "bounds_max", hi,
             "bounds_max[a] = bounds_origin[a] + bounds_extent[a] for a in "
             "bounds_axis_order; None if either input is not a finite vec3",
             ["bounds_origin", "bounds_extent"], source_api=source_api)


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
            arec = _envelope("actor", ident, ST_OBSERVE,
                             "scene_survey_far_side._collect_actor_records",
                             source_api=LEVEL_ACTORS_API, actor_object_path=path,
                             measured_fields=ACTOR_MEASURED)
            arec.update({
                "path_name": path, "class_name": _class_of(actor),
                "location": None, "rotation": None, "scale": None,
                "bounds_origin": None, "bounds_extent": None, "bounds_api": None,
                "bounds_min": None, "bounds_max": None, "bounds_primary": None,
                "bounds_axis_order": BOUNDS_AXIS_ORDER,
                "distance_to_anchor_cm": None, "component_refs": [],
                "collection_ok": False,
                "errors": ["actor location could not be read; the radius filter could "
                           "not be applied and no bounds were measured"],
            })
            raw["actor"][ident] = _settle(arec, False, FC_ACTOR_ENUMERATION)
            continue
        dist = math.sqrt(sum((loc[i] - center[i]) ** 2 for i in range(3)))
        if dist > radius:
            continue
        origin, extent, api, berr = _actor_bounds(actor)
        rec = _envelope("actor", ident, ST_OBSERVE,
                        "scene_survey_far_side._collect_actor_records",
                        source_api=api or LEVEL_ACTORS_API, actor_object_path=path,
                        measured_fields=ACTOR_MEASURED)
        rec.update({
            "path_name": path,
            "class_name": _class_of(actor),
            "location": loc,
            "rotation": _pyr(_safe(lambda: actor.get_actor_rotation())),
            "scale": _xyz(_safe(lambda: actor.get_actor_scale3d())),
            "bounds_origin": origin,
            "bounds_extent": extent,
            "bounds_api": api,
            # The bounds predicate B_i is stated over MIN and MAX, so both are
            # emitted explicitly rather than left for a reader to reconstruct from
            # origin/extent and get the sign convention wrong. `bounds_primary`
            # names which pair was READ and which was COMPUTED: the engine call
            # returns origin/extent, so that pair is the observation and min/max are
            # registered in `derived_fields` with their formula.
            "bounds_min": None,
            "bounds_max": None,
            "bounds_primary": "origin_extent" if extent is not None else None,
            "bounds_axis_order": BOUNDS_AXIS_ORDER,
            "distance_to_anchor_cm": dist,
            "component_refs": [],
            "collection_ok": bool(path and extent is not None),
            "errors": [],
        })
        _bounds_min_max(rec, origin, extent, api)
        if berr:
            rec["errors"].append(berr)
        raw["actor"][ident] = rec
        _settle(rec, True, FC_ACTOR_BOUNDS)

        comps, cerr = _primitive_components(actor)
        if comps is None:
            rec["errors"].append(cerr)
            _settle(rec, True, FC_ACTOR_BOUNDS)
            continue
        for ci, comp in enumerate(comps):
            cpath = _path_of(comp)
            cident = cpath if cpath else "{}::component_{:04d}".format(ident, ci)
            corigin, cextent, cradius, cberr = _component_bounds(comp)
            crec = _envelope("component", cident, ST_OBSERVE,
                             "scene_survey_far_side._collect_actor_records",
                             source_api=(COMPONENTS_BY_CLASS_API + " + "
                                         + COMPONENT_BOUNDS_API),
                             actor_object_path=path, component_object_path=cpath,
                             measured_fields=COMPONENT_MEASURED)
            crec.update({
                "actor_ref": _raw_ref("actor", ident),
                "path_name": cpath,
                "class_name": _class_of(comp),
                "collision_enabled": _enum_name(
                    _safe(lambda: comp.get_editor_property("collision_enabled"))),
                "bounds_origin": corigin,
                "bounds_extent": cextent,
                "bounds_sphere_radius": cradius,
                "bounds_min": None,
                "bounds_max": None,
                "bounds_primary": "origin_extent" if cextent is not None else None,
                "bounds_axis_order": BOUNDS_AXIS_ORDER,
                "collection_ok": bool(cpath and cextent is not None),
                "errors": [],
            })
            _bounds_min_max(crec, corigin, cextent, COMPONENT_BOUNDS_API)
            if cberr:
                crec["errors"].append(cberr)
            raw["component"][cident] = crec
            # `failed` only when NOTHING answered. A component whose bounds are
            # unreadable but whose identity and collision state ARE readable is a
            # partial observation, and settling it `failed` would make `_settle`
            # throw away the two fields that did answer.
            _settle(crec, (cextent is not None
                           or crec["collision_enabled"] is not None
                           or cpath is not None),
                    FC_COMPONENT_STATE)
            rec["component_refs"].append(_raw_ref("component", cident))


def _safe(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


# The MEASUREMENT fields of a marker record. `index`, `location`, `capsule_radius`
# and `capsule_half_height` are the QUESTION, not the answer, and stay readable on a
# failed record so the failure can be attributed to a candidate.
MARKER_MEASURED = ("probe_temp_marker_returned", "accepted", "contact", "grounded",
                   "footprint", "overlap", "capsule_clear", "ground_impact_z",
                   "ground_impact_point", "ground_delta_z_cm",
                   "ground_surface_normal", "ground_surface_normal_unit",
                   "ground_surface_normal_dot_up", "footprint_supported_sample_count",
                   "supported_footprint_area_cm2",
                   "capsule_overlap_static_actor_paths",
                   "capsule_overlap_dynamic_actor_paths",
                   "capsule_overlap_actor_paths", "capsule_overlap_component_paths")

# The grounding predicate's thresholds are POLICY and the far side was handed none
# of them. They are emitted as an explicit None triple rather than omitted, so a
# reader can see that the question of "how much support is enough" was left open
# here on purpose — an absent key reads as an oversight, and a defaulted number
# would silently decide the very thing this file must not decide.
GROUNDING_THRESHOLDS = {
    "tau_supported_area_ratio": None,
    "tau_delta_z_cm": None,
    "cos_theta_max": None,
    "note": ("grounding thresholds are policy, not observations; the far side was "
             "supplied none and invents none. The deriving side supplies them."),
}


def _collect_marker_record(raw, world, index, location, probe_returned):
    """RAW observations for ONE temporary-marker candidate.

    The C++ ``ProbeTempMarker`` returns a single bool and logs the rest; the
    per-candidate detail exists nowhere the near side can reach except by scraping
    that log line. So the individual trace and overlap queries are re-run here in
    Python and filed as raw records the assembler can derive from.

    ``grounded`` / ``footprint`` / ``overlap`` / ``capsule_clear`` are NULLABLE
    restatements of those atoms, carried under the names the raw-bundle contract
    reads (scene_survey_evidence.py:316,322,333,346). Each is None whenever its
    underlying observation was not collected, and each is registered in
    ``derived_fields`` with the formula that produced it. ``accepted`` is not
    recomputed here at all — it is the value the compiled primitive RETURNED.

    GROUNDING ATOMS. The grounding predicate the assembler evaluates is

        G_m = contact
              AND supported_footprint_area / required_footprint_area >= tau_s
              AND abs(delta_z) <= tau_z
              AND n_hat . z_hat >= cos(theta_max)

    so every term is emitted as its own atom: ``contact``, the two areas plus the
    sample counts they were computed from, ``ground_delta_z_cm``, and
    ``ground_surface_normal`` with its unit form and its dot with up. The three
    thresholds are NOT emitted with values: tau_s, tau_z and theta_max are POLICY,
    the far side was handed none of them, and inventing defaults would silently
    decide the question this file exists to leave open.
    """
    ident = "marker_{:03d}".format(index)
    rec = _envelope("marker", ident, ST_CLASSIFY,
                    "scene_survey_far_side._collect_marker_record",
                    source_api=TRACE_API + " + " + CAPSULE_ACTORS_API,
                    measured_fields=MARKER_MEASURED)
    rec.update({
        "index": index,
        "location": location,
        "capsule_radius": MARKER_CAPSULE_RADIUS,
        "capsule_half_height": MARKER_CAPSULE_HALF_HEIGHT,
        "probe_temp_marker_returned": probe_returned,
        "accepted": probe_returned,
        "ground_trace_ref": None,
        "ground_impact_z": None,
        "ground_impact_point": None,
        "ground_delta_z_cm": None,
        "ground_surface_normal": None,
        "ground_surface_normal_unit": None,
        "ground_surface_normal_dot_up": None,
        "contact": None,
        "footprint_trace_refs": [],
        "footprint_trace_hits": [],
        "footprint_sample_count": None,
        "footprint_supported_sample_count": None,
        "footprint_sample_offsets_cm": None,
        "footprint_sample_radius_cm": MARKER_CAPSULE_RADIUS,
        "required_footprint_area_cm2": None,
        "supported_footprint_area_cm2": None,
        "grounding_thresholds": GROUNDING_THRESHOLDS,
        "capsule_center": None,
        "overlap_query_ref": None,
        "capsule_overlap_static_actor_paths": None,
        "capsule_overlap_dynamic_actor_paths": None,
        "capsule_overlap_actor_paths": None,
        "capsule_overlap_component_paths": None,
        "grounded": None,
        "footprint": None,
        "overlap": None,
        "capsule_clear": None,
        "collection_ok": False,
        "errors": [],
    })
    raw["marker"][ident] = rec
    if world is None or not _finite_vec3(location):
        rec["errors"].append("no world or non-finite candidate location; no trace was run")
        return _settle(rec, False, FC_PLACEMENT_INVALID)

    # Ground contact. Reach matches the C++ probe (SceneSurvey.cpp:204-207) so the
    # two channels are asking the same question of the same geometry.
    gid = "{}::ground".format(ident)
    ground = _line_trace(raw, world, gid,
                         [location[0], location[1], location[2] + 100.0],
                         [location[0], location[1], location[2] - 3000.0],
                         "marker ground contact")
    rec["ground_trace_ref"] = _raw_ref("trace", gid)
    # `contact` is the ground trace's own tri-state answer, carried under the name
    # the grounding formula uses. `grounded` is the same value under the name the
    # committed bundle contract reads; both are None when the trace did not answer.
    rec["contact"] = ground["hit"] if ground["hit"] is None else bool(ground["hit"])
    if ground["hit"] is not None:
        _derived(rec, "grounded", bool(ground["hit"]),
                 "grounded = trace(ground_trace_ref).hit; None when that trace did "
                 "not answer — never coerced to False",
                 [rec["ground_trace_ref"]], source_api=TRACE_API)
    ip = ground.get("impact_point")
    rec["ground_impact_point"] = ip if _finite_vec3(ip) else None
    ground_z = ip[2] if _finite_vec3(ip) else None
    rec["ground_impact_z"] = ground_z
    normal = ground.get("impact_normal")
    rec["ground_surface_normal"] = normal if _finite_vec3(normal) else None
    unit, dot_up = _unit_and_dot_up(rec["ground_surface_normal"])
    if unit is not None:
        _derived(rec, "ground_surface_normal_unit", unit,
                 "n_hat = ground_surface_normal / ||ground_surface_normal||; None "
                 "when the normal is absent, non-finite or zero-length",
                 ["ground_surface_normal"], source_api=TRACE_API)
        _derived(rec, "ground_surface_normal_dot_up", dot_up,
                 "n_hat . z_hat with z_hat = (0, 0, 1), i.e. n_hat[2]. Compare "
                 "against cos(theta_max); the far side supplies no theta_max",
                 ["ground_surface_normal_unit"], source_api=TRACE_API)
    if ground_z is not None:
        _derived(rec, "ground_delta_z_cm", _num(location[2] - ground_z),
                 "ground_delta_z_cm = location[2] - ground_impact_z (SIGNED; the "
                 "grounding predicate takes its absolute value). None when the "
                 "ground trace reported no impact point",
                 ["location", "ground_impact_z"], source_api=TRACE_API)
    # The footprint traces are cast relative to the OBSERVED ground plane when there
    # is one. When there is not, they fall back to the candidate's own z — recorded
    # here rather than left implicit, because a footprint measured against a guessed
    # plane is a different measurement from one measured against an observed plane.
    footprint_datum_z = ground_z
    rec["footprint_datum_z"] = ground_z
    rec["footprint_datum_source"] = ("ground_impact_z" if ground_z is not None
                                     else "candidate_location_z")
    if footprint_datum_z is None:
        footprint_datum_z = location[2]

    # Four-corner footprint traces at the capsule radius (SceneSurvey.cpp:212-221).
    offsets = ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0))
    hits = []
    for ci, (ox, oy) in enumerate(offsets):
        fid = "{}::footprint_{}".format(ident, ci)
        ft = _line_trace(raw, world, fid,
                         [location[0] + ox * MARKER_CAPSULE_RADIUS,
                          location[1] + oy * MARKER_CAPSULE_RADIUS,
                          footprint_datum_z + 100.0],
                         [location[0] + ox * MARKER_CAPSULE_RADIUS,
                          location[1] + oy * MARKER_CAPSULE_RADIUS,
                          footprint_datum_z - 200.0],
                         "marker footprint corner")
        rec["footprint_trace_refs"].append(_raw_ref("trace", fid))
        hits.append(ft["hit"])
    rec["footprint_trace_hits"] = hits
    rec["footprint_sample_count"] = len(hits)
    rec["footprint_sample_offsets_cm"] = [
        [ox * MARKER_CAPSULE_RADIUS, oy * MARKER_CAPSULE_RADIUS] for ox, oy in offsets]
    _derived(rec, "required_footprint_area_cm2",
             _num(math.pi * MARKER_CAPSULE_RADIUS ** 2),
             "required_footprint_area_cm2 = pi * capsule_radius^2 — the capsule's "
             "full cross-section, i.e. the area the predicate's denominator refers to",
             ["capsule_radius"], source_api=None)
    if all(h is not None for h in hits):
        supported = sum(1 for h in hits if h)
        rec["footprint_supported_sample_count"] = supported
        _derived(rec, "supported_footprint_area_cm2",
                 _num(math.pi * MARKER_CAPSULE_RADIUS ** 2
                      * (float(supported) / float(len(hits)))),
                 "supported_footprint_area_cm2 = required_footprint_area_cm2 * "
                 "(footprint_supported_sample_count / footprint_sample_count) — a "
                 "4-sample estimate on the offsets in footprint_sample_offsets_cm, "
                 "not an integrated area",
                 ["required_footprint_area_cm2", "footprint_supported_sample_count",
                  "footprint_sample_count"], source_api=None)
        # HAZARD FIXED: this read `all(...) and (rec["grounded"] is True)`, so a
        # marker whose ground trace did not answer got footprint=False — an UNKNOWN
        # coerced to a measured False, in the one direction that reads as a real
        # negative finding. Unknown ground contact now yields unknown footprint.
        if rec["grounded"] is None:
            rec["errors"].append(
                "footprint is unknown: all four corner traces answered, but ground "
                "contact did not, and the restatement is conjunctive")
        else:
            _derived(rec, "footprint",
                     all(bool(h) for h in hits) and (rec["grounded"] is True),
                     "footprint = all(trace(r).hit for r in footprint_trace_refs) "
                     "AND grounded; None when any corner trace or the ground trace "
                     "did not answer",
                     list(rec["footprint_trace_refs"]) + [rec["ground_trace_ref"]],
                     source_api=TRACE_API)

    # Capsule clearance against static and dynamic geometry (SceneSurvey.cpp:224-229).
    cap_ctr = [location[0], location[1],
               footprint_datum_z + MARKER_CAPSULE_HALF_HEIGHT + 2.0]
    rec["capsule_center"] = cap_ctr if _finite_vec3(cap_ctr) else None
    oq = _collect_overlap_query(raw, world, "{}::capsule".format(ident), cap_ctr,
                                MARKER_CAPSULE_RADIUS, MARKER_CAPSULE_HALF_HEIGHT)
    rec["overlap_query_ref"] = oq["record_id"]
    static_paths = oq["static_actor_paths"]
    dynamic_paths = oq["dynamic_actor_paths"]
    rec["capsule_overlap_static_actor_paths"] = static_paths
    rec["capsule_overlap_dynamic_actor_paths"] = dynamic_paths
    rec["capsule_overlap_actor_paths"] = oq["actor_paths"]
    rec["capsule_overlap_component_paths"] = oq["component_paths"]
    for e in (oq.get("errors") or []):
        rec["errors"].append(e)
    if static_paths is not None and dynamic_paths is not None:
        _derived(rec, "overlap", bool(static_paths) or bool(dynamic_paths),
                 "overlap = len(capsule_overlap_actor_paths) > 0, over the union of "
                 "the WorldStatic and WorldDynamic queries; None when either "
                 "sub-query was unread",
                 [rec["overlap_query_ref"]], source_api=CAPSULE_ACTORS_API)
        _derived(rec, "capsule_clear", not rec["overlap"],
                 "capsule_clear = NOT overlap; None when overlap is None — an "
                 "unmeasured capsule is not a clear one",
                 [rec["overlap_query_ref"]], source_api=CAPSULE_ACTORS_API)

    rec["collection_ok"] = (rec["grounded"] is not None
                            and rec["footprint"] is not None
                            and rec["capsule_clear"] is not None)
    # The record OBSERVED something as soon as any one of its atoms answered. It is
    # `failed` only when the whole candidate produced nothing.
    answered = [v for v in (rec["grounded"], rec["footprint"], rec["capsule_clear"],
                            rec["ground_impact_z"], rec["capsule_overlap_actor_paths"])
                if v is not None]
    return _settle(rec, bool(answered), FC_PLACEMENT_INVALID)


def _record_world(raw, world, package_name):
    """RAW identity of the world that is actually open.

    This is also where the envelope's ``world_identity`` is sourced: the package
    name is cached here, ONCE, from the live editor. Records filed before this point
    carry ``world_identity=None`` and that is correct — at that moment no world
    identity had been observed, and back-filling one afterwards would be asserting
    that earlier measurements were taken in a world nobody had yet confirmed.
    """
    _OBSERVED_WORLD["package_name"] = package_name
    rec = _envelope("world", "observed", ST_WORLD_IDENTITY,
                    "scene_survey_far_side._record_world",
                    source_api=WORLD_PACKAGE_API,
                    measured_fields=("package_name", "world_object_path",
                                     "world_class_name", "is_package_external",
                                     "is_in_play_in_editor"))
    rec.update({
        "package_name": package_name,
        "world_object_path": _path_of(world),
        "world_class_name": _class_of(world),
        "is_package_external": _safe(lambda: bool(world.is_package_external())),
        "is_in_play_in_editor": _is_in_pie(),
        "collection_ok": package_name is not None,
        "collector": "scene_survey_far_side._record_world",
        "errors": [],
    })
    rec["world_identity"] = package_name
    if package_name is None:
        rec["errors"].append("the open world's package name could not be read")
    raw["world"]["observed"] = _settle(rec, package_name is not None, FC_WORLD_IDENTITY)
    return rec


def _record_proxy_unobserved(raw):
    """MeshForge runtime proxies are NOT observable in an editor pass.

    They spawn at game BeginPlay, so a -nullrhi editor load has nothing to look at.
    This is filed as an explicitly unobserved record with a reason — value None, not
    a zero. A ``proxy_owners: 0`` here would be indistinguishable from a real
    measurement of an empty set.

    ``unsupported``, not ``failed``: nothing broke. This pass is structurally unable
    to answer the question, which is a different fact from having tried and lost.
    """
    rec = _envelope("proxy", "runtime_proxies", ST_OBSERVE,
                    "scene_survey_far_side._record_proxy_unobserved",
                    source_api=None, measured_fields=("value", "proxy_owner_paths"))
    rec.update({
        "value": None,
        "proxy_owner_paths": None,
        "collection_ok": False,
        "collector": "scene_survey_far_side._record_proxy_unobserved",
        "stage": ST_OBSERVE,
        "detail": ("MeshForge runtime proxies spawn at game BeginPlay; an editor "
                   "-nullrhi load never reaches BeginPlay, so neither their presence "
                   "nor their absence was observed in this pass"),
        "errors": [],
    })
    raw["proxy"]["runtime_proxies"] = _settle(
        rec, False, evidence_class=EC_UNSUPPORTED,
        detail=rec["detail"])
    return rec


def _record_capture_question(raw):
    """The camera-capture question, answered honestly for a pass that cannot render.

    Two DIFFERENT terminal states, and the difference is the whole point: when the
    caller requested no captures the answer is ``not_requested`` (there is no
    shortfall — capture is opt-in); when the caller DID request captures the answer
    is ``unsupported``, because an RHI is required and this pass runs under -nullrhi.
    A single ``camera_capture_ran: False`` cannot tell those apart, and one of them
    is a missing deliverable while the other is a satisfied request.
    """
    requested = list(CAPTURES)
    rec = _envelope("capture", "camera", ST_OBSERVE,
                    "scene_survey_far_side._record_capture_question",
                    source_api=None,
                    measured_fields=("value", "capture_paths"))
    rec.update({
        "value": None,
        "capture_paths": None,
        "captures_requested": requested,
        "collection_ok": False,
        "errors": [],
    })
    raw["capture"]["camera"] = _settle(
        rec, None if not requested else False,
        evidence_class=(EC_NOT_REQUESTED if not requested else EC_UNSUPPORTED),
        detail=_capture_reason())
    return rec


def _record_ref_integrity(raw):
    """Walk every record and MEASURE the bundle's own structural invariants.

    Three of them, each stated as the list of records that violate it rather than as
    a boolean. A boolean would be a verdict ABOUT THE DOCUMENT, and this file states
    no verdicts; a list is a measurement, and a reader can see for themselves that
    it is empty:

      INV-REF   every ``*_ref`` names a ``record_id`` present in this bundle.
      INV-ID    every record's ``record_id`` equals ``"<kind>#<ident>"`` for the
                pair it is filed under — which is what makes ids unique within the
                bundle and stable across repeat runs of identical input.
      INV-ENV   every record carries every field in ``RECORD_ENVELOPE_FIELDS``. This
                is why the constant and ``_envelope`` cannot silently drift apart:
                the drift would show up here as a populated list.
    """
    ids = set()
    records = []          # [(kind, ident, record)]
    for kind, idents in raw.items():
        if not isinstance(idents, dict):
            continue
        for ident, r in idents.items():
            if isinstance(r, dict) and isinstance(r.get("record_id"), str):
                ids.add(r["record_id"])
                records.append((kind, ident, r))
    unresolved = []
    checked = 0
    mismatched_ids = []
    incomplete = []
    for kind, ident, r in records:
        want_id = _raw_ref(kind, ident)
        if r.get("record_id") != want_id or r.get("record_type") != kind:
            mismatched_ids.append({"filed_as": want_id,
                                   "record_id": r.get("record_id"),
                                   "record_type": r.get("record_type")})
        missing = [f for f in RECORD_ENVELOPE_FIELDS if f not in r]
        if missing:
            incomplete.append({"record_id": r.get("record_id"), "missing": missing})
        for key, val in list(r.items()):
            vals = ()
            if key.endswith("_refs") and isinstance(val, list):
                vals = [v for v in val if isinstance(v, str)]
            elif key.endswith("_ref") and isinstance(val, str):
                vals = [val]
            for v in vals:
                checked += 1
                if v not in ids:
                    unresolved.append({"from_record_id": r.get("record_id"),
                                       "field": key, "ref": v})
    rec = _envelope("document", "ref_integrity", ST_CLASSIFY,
                    "scene_survey_far_side._record_ref_integrity",
                    source_api=None,
                    measured_fields=("record_ids_total", "refs_checked",
                                     "unresolved_refs", "unresolved_ref_count",
                                     "record_id_mismatches",
                                     "record_id_mismatch_count",
                                     "envelope_incomplete_records",
                                     "envelope_incomplete_count"))
    rec.update({
        "record_ids_total": len(ids),
        "records_total": len(records),
        "refs_checked": checked,
        "unresolved_refs": sorted(unresolved, key=lambda d: (d["from_record_id"] or "",
                                                             d["field"], d["ref"])),
        "unresolved_ref_count": len(unresolved),
        "record_id_mismatches": sorted(mismatched_ids, key=lambda d: d["filed_as"]),
        "record_id_mismatch_count": len(mismatched_ids),
        "envelope_incomplete_records": sorted(
            incomplete, key=lambda d: d["record_id"] or ""),
        "envelope_incomplete_count": len(incomplete),
        "envelope_fields": list(RECORD_ENVELOPE_FIELDS),
        "collection_ok": True,
        "errors": [],
    })
    raw["document"]["ref_integrity"] = _settle(rec, True)
    return rec


def _new_raw_bundle():
    """The empty raw bundle. Kinds are pre-created so refs address a real container."""
    return {
        "schema_version": RAW_BUNDLE_SCHEMA,
        "record_schema_version": RAW_RECORD_SCHEMA,
        "world": {},
        "actor": {},
        "component": {},
        "trace": {},
        "overlap_query": {},
        "marker": {},
        "proxy": {},
        "capture": {},
        "temporary_placement": {},
        "inventory": {},
        "document": {},
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
        # CALLER_SUPPLIED and never validated here (see WF_SURVEY_REQUEST_HASH in the
        # module docstring). Present at document level AND stamped on every record, so
        # a bundle cannot be separated from the question that produced it.
        "request_hash": REQUEST_HASH,
        "request_hash_algorithm": REQUEST_HASH_ALGORITHM,
        "request_hash_source": "env:WF_SURVEY_REQUEST_HASH",
        "request_hash_evidence_class": EC_CALLER_SUPPLIED,
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
        "raw_evidence_record_schema": RAW_RECORD_SCHEMA,
        # The closed vocabularies, emitted WITH the document rather than left to a
        # reader to look up in a file they may not have. A bundle that travels
        # without its vocabulary is a bundle whose classifications can be
        # reinterpreted later; carrying them makes drift visible instead of silent.
        "evidence_class_vocabulary": list(EVIDENCE_CLASSES),
        "collection_status_vocabulary": list(COLLECTION_STATUSES),
        "record_envelope_fields": list(RECORD_ENVELOPE_FIELDS),
        "raw_evidence": _new_raw_bundle(),
        # Collection problems that are NOT survey failures. Kept OUT of "error" on
        # purpose: "error" means the survey must not be believed, while these mean
        # one measurement is missing and the near side decides what that costs.
        "collection_errors": [],
        "environment_inputs": {
            "radius_cm": RADIUS,
            "step_cm": STEP,
            "markers_requested": MARKERS,
            "request_hash": REQUEST_HASH,
            "request_hash_algorithm": REQUEST_HASH_ALGORITHM,
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
    _record_capture_question(raw)

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

    # LAST, so it sees every record every path filed. Its own record is filed after
    # the walk, so it never has to describe itself.
    try:
        _record_ref_integrity(raw)
        for u in raw["document"]["ref_integrity"]["unresolved_refs"]:
            _note(doc, "ref_integrity",
                  "{}.{} -> {} does not resolve in this bundle".format(
                      u["from_record_id"], u["field"], u["ref"]))
    except Exception as exc:  # noqa: BLE001
        _note(doc, "_record_ref_integrity", "{}: {}".format(type(exc).__name__, exc))

    _write(doc)


def _scrub_non_finite(obj, path, casualties):
    """Return a copy of ``obj`` with every non-finite float replaced by None.

    Reached only when ``allow_nan=False`` has already refused the document, i.e.
    when a NaN or Infinity got past `_num`/`_xyz`/`_finite_vec3` at the source. The
    poisoned VALUE becomes None — "not observed", the honest reading of a number
    that cannot be represented — and its dotted path is recorded, so the loss is
    itemised rather than merely survived. Keys are never removed: the document's key
    set must not change shape depending on whether an engine returned a NaN.
    """
    if isinstance(obj, float):
        if math.isfinite(obj):
            return obj
        casualties.append(path)
        return None
    if isinstance(obj, dict):
        return {k: _scrub_non_finite(v, "{}.{}".format(path, k), casualties)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_non_finite(v, "{}[{}]".format(path, i), casualties)
                for i, v in enumerate(obj)]
    return obj


def _serialize(doc):
    """(json_text, casualties, error). NEVER emits NaN/Infinity and never raises.

    ``allow_nan=False`` is the whole point. Python's default writes bare ``NaN`` and
    ``Infinity`` tokens, which are NOT valid JSON but which Python's own ``loads``
    accepts — so a poisoned number crosses to the near side silently and reappears
    there as a real measurement. Refusing at the boundary turns that into a visible,
    itemised failure instead.
    """
    try:
        return json.dumps(doc, indent=2, sort_keys=True, allow_nan=False), [], None
    except (ValueError, TypeError) as exc:
        first = "{}: {}".format(type(exc).__name__, exc)
    casualties = []
    scrubbed = _scrub_non_finite(doc, "$", casualties)
    # File the failure as a raw record, so a reader of the bundle finds it where
    # they find everything else rather than only in a log line.
    try:
        # measured_fields is deliberately EMPTY. `non_finite_paths` and
        # `non_finite_count` describe the FAILURE, they are not measurements of the
        # scene — and `_settle` voids the measured fields of a `failed` record, so
        # listing them here would blank the only diagnostic this record exists to
        # carry. Same reasoning as `ident` on a refused temporary_placement.
        rec = _envelope("document", "serialization", ST_CLASSIFY,
                        "scene_survey_far_side._serialize", source_api=None,
                        measured_fields=())
        rec.update({
            "non_finite_paths": sorted(casualties),
            "non_finite_count": len(casualties),
            "collection_ok": False,
            "errors": [first],
        })
        _settle(rec, False, FC_REPORT_INVALID,
                detail=("the document could not be serialized with allow_nan=False; "
                        "{} non-finite value(s) were replaced with None so the "
                        "document could still be written".format(len(casualties))))
        scrubbed.setdefault("raw_evidence", {}).setdefault("document", {})
        scrubbed["raw_evidence"]["document"]["serialization"] = rec
        scrubbed.setdefault("collection_errors", []).append(
            {"collector": "_serialize", "detail": first})
    except Exception:  # noqa: BLE001 — the report of the failure must not fail
        pass
    try:
        return json.dumps(scrubbed, indent=2, sort_keys=True, allow_nan=False), \
            casualties, first
    except (ValueError, TypeError) as exc:
        return None, casualties, "{}; and after scrubbing: {}: {}".format(
            first, type(exc).__name__, exc)


def _write(doc):
    text, casualties, serr = _serialize(doc)
    if text is None:
        # Last resort: a document that reports ONLY its own failure still beats no
        # document at all, because the near side's alternative reading of an absent
        # file is a timeout — indistinguishable from a far side that never started.
        skeleton = _new_doc()
        skeleton["error"] = "far-side document could not be serialized: {}".format(serr)
        try:
            text = json.dumps(skeleton, indent=2, sort_keys=True, allow_nan=False)
        except Exception:  # noqa: BLE001
            _log("FATAL: even the far-side skeleton could not be serialized")
            return
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    if serr:
        _log("WARNING: {} non-finite value(s) were scrubbed to None: {}".format(
            len(casualties), serr))
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
