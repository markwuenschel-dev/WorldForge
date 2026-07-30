#!/usr/bin/env python3
r"""run_v2_6_fixture_smoke.py -- runtime proof for the v2.6 survey API surface.

WHY THIS EXISTS
---------------
tools/bridge/scene_survey_far_side.py is written defensively against a Python
symbol surface it has never been able to execute. Its own header says so:

    "Every Unreal API call below is individually guarded. The Python symbol
     surface of UE 5.8 cannot be executed or introspected from the repo side"

and its geometry helpers carry literal ``ASSUMED symbol:`` notes
(scene_survey_far_side.py:855-862 break_hit_result, :975-978
capsule_overlap_actors, :1010-1013 capsule_overlap_components). Those guards are
correct engineering, but they mean a *degraded* result and a *working* result are
indistinguishable from the repo side.

This harness converts assumption into observation. It boots THIS repo's own
project headless under ``-nullrhi``, calls each load-bearing symbol for real, and
classifies every one as exactly one of:

    runtime_verified    -- called it in a live editor; the result was well-formed
                           and usable.
    runtime_unavailable -- the symbol is not reflected here, or no editor exists
                           to ask. Nothing was observed.
    runtime_failed      -- the symbol exists but raised, or returned a shape the
                           caller cannot use.
    still_assumed       -- never reached; a prerequisite did not hold. This is
                           NEVER a pass.

GATE
----
GREEN only when EVERY required probe is ``runtime_verified`` AND the report
carries live-run proof AND every D18 criterion is answered. There is no optional
tier: an optional runtime probe is a probe whose failure nobody acts on.

WHAT IS PROBED (thirteen groups, all required)
----------------------------------------------
    plugin      plugin identity + load, and all three USceneSurveyStatics
                primitives -- merely importing ``unreal`` proves nothing about
                WorldForge being loaded.
    world       world / package identity
    actor       actor identity and world membership, transforms
    bounds      actor bounds and component bounds
    geometry    line_trace_single, break_hit_result (18-tuple decomposition),
                capsule_overlap_actors, capsule_overlap_components
    packages    dirty-package observation
    ownership   operation-owned transient spawn and destruction
    publication structured raw-evidence bundle + operation manifest
    measurement D18 grid cost measurement

D18 MEASUREMENT (docs/architecture/forge_design_decisions.md:121-149)
---------------------------------------------------------------------
For radius R and spacing s: k = floor(R/s), N = (2k+1)^2. The harness measures
several N with warm-up plus repetitions, and the NEAR side fits

    T(N) = alpha + beta*N + epsilon

by ordinary least squares in plain Python. alpha estimates fixed
operation/interop cost, beta the marginal cost per sample. No single timing
sample is ever reported as a measurement.

Every one of D18's six promotion criteria is answered with exactly one of
``measured_pass`` / ``measured_fail`` / ``unsupported`` / ``not_measured``.
``not_measured`` keeps the promotion decision OPEN and is never defaulted away:
the criteria table is pre-filled with it and a missing criterion turns the gate
RED.

SEPARATION OF POWERS
--------------------
The FAR side (inside the editor) emits raw observations and raw timings ONLY. It
computes no statistic, no fit, no criterion and no gate. The NEAR side derives
every verdict and independently RE-DERIVES the far side's claims from the
transported evidence: a probe that claims ``runtime_verified`` while carrying an
observation that does not support it is downgraded to ``runtime_failed``.

READ-ONLY AGAINST PROJECT CONTENT
---------------------------------
Never saves a package, never authors a permanent actor, never writes a ``.umap``.
The single mutation is one TRANSIENT actor, spawned, destroyed and then
RE-OBSERVED absent through a channel capable of saying "no".

PROJECT GUARD
-------------
The project path is DERIVED from this file's location and cannot be overridden by
any flag or environment variable. See ``_resolve_uproject``.

DUAL MODE
---------
One file, two roles. Run normally it is the NEAR side (launcher). The editor runs
the very same file as the FAR side via ``-ExecutePythonScript``, discriminated by
the ``WF_FIXTURE_SMOKE_FAR_SIDE`` environment variable the near side sets.

Acceptance (writes only under procedural/reports/, launches nothing):
    PYTHONUTF8=1 python tools/pipeline/run_v2_6_fixture_smoke.py --dry-run
Self-test (no editor, no writes at all):
    PYTHONUTF8=1 python tools/pipeline/test_v2_6_fixture_smoke.py
Live (boots the editor once, ~minutes):
    PYTHONUTF8=1 python tools/pipeline/run_v2_6_fixture_smoke.py
Report -> procedural/reports/scene_survey/fixture_smoke/v2_6_fixture_smoke_report.json
"""

import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------- #
# shared constants -- read by BOTH sides, so they cannot drift apart
# --------------------------------------------------------------------------- #
ENV_FAR_SIDE = "WF_FIXTURE_SMOKE_FAR_SIDE"
ENV_OUT = "WF_FIXTURE_SMOKE_OUT"
ENV_MAP = "WF_FIXTURE_SMOKE_MAP"
ENV_NONCE = "WF_FIXTURE_SMOKE_NONCE"
ENV_OPERATION_ID = "WF_FIXTURE_SMOKE_OPERATION_ID"
ENV_D18 = "WF_FIXTURE_SMOKE_D18"

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_UPROJECT = REPO_ROOT / "WorldForge.uproject"

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey" / "fixture_smoke"
REPORT_NAME = "v2_6_fixture_smoke_report.json"
DRYRUN_REPORT_NAME = "v2_6_fixture_smoke_report.dryrun.json"
NORUN_REPORT_NAME = "v2_6_fixture_smoke_report.norun.json"
SAMPLES_NAME = "v2_6_fixture_smoke_d18_samples.json"

SCHEMA_VERSION = "wf.scene_survey.fixture_smoke.v2"

# The raw-evidence schema strings are the SAME contract the real collector emits
# (scene_survey_far_side.py:255,:259). Duplicated as literals rather than
# imported, for the reason that file states at :260-266: this module also runs
# inside the UE Python interpreter, whose sys.path does not carry tools/pipeline,
# and an ImportError at module scope would kill the far side before any evidence
# could be written. The STRINGS are the contract.
RAW_BUNDLE_SCHEMA = "wf.scene_survey.raw_evidence_bundle.v1"
RAW_RECORD_SCHEMA = "wf.scene_survey.raw_evidence_record.v1"
MANIFEST_SCHEMA = "wf.scene_survey.fixture_smoke.operation_manifest.v1"
LIVENESS_DOMAIN = "wf.v2_6_fixture_smoke.liveness.v1"

# Mirrors scene_survey_far_side.py:528-534 exactly. A transported record that is
# missing any of these fields is not a publication of the contract shape.
RECORD_ENVELOPE_FIELDS = (
    "record_schema", "operation_id", "request_hash", "request_hash_algorithm",
    "record_id", "record_type", "record_ident", "stage", "collector",
    "collection_status", "evidence_class", "source_api", "world_identity",
    "actor_object_path", "component_object_path", "failure_code",
    "derived_fields", "measured_fields",
)

# The smallest, most boring map in the repo: one StaticMeshActor,
# non-World-Partition. A StaticMeshActor is also exactly what the
# component-bounds and geometry probes need -- it carries a
# UStaticMeshComponent, which IS a UPrimitiveComponent with collision.
DEFAULT_MAP = "/Game/WorldForge/Terrain/Terrain_AshFlats_01_Preview"

STATUS_VERIFIED = "runtime_verified"
STATUS_UNAVAILABLE = "runtime_unavailable"
STATUS_FAILED = "runtime_failed"
STATUS_ASSUMED = "still_assumed"
ALL_STATUSES = (STATUS_VERIFIED, STATUS_UNAVAILABLE, STATUS_FAILED, STATUS_ASSUMED)

# ---- report kinds. A report must say what KIND of thing produced it, so a
# ---- near-side-only artefact can never be mistaken for a live run.
KIND_LIVE = "live_editor_run"
KIND_DRY_RUN = "dry_run"
KIND_NO_EDITOR = "no_editor_resolved"
KIND_BOOT_FAILED = "editor_boot_produced_no_observations"
KIND_GUARD_REFUSED = "project_guard_refused"
ALL_REPORT_KINDS = (KIND_LIVE, KIND_DRY_RUN, KIND_NO_EDITOR, KIND_BOOT_FAILED,
                    KIND_GUARD_REFUSED)

# --------------------------------------------------------------------------- #
# THE PROBE REGISTRY
# --------------------------------------------------------------------------- #
# Every probe here is REQUIRED. Each names a symbol scene_survey_far_side.py
# depends on, with a citation of the line that depends on it. There is no
# "optional" tier on purpose: an optional runtime probe is a probe whose failure
# nobody acts on.
#
# NOTE ON THE CITATIONS: scene_survey_far_side.py is under active edit by a
# parallel lane and is 2638 lines as of this writing. The citations are pinned to
# the symbol TEXT, not just the number -- re-locate with grep before trusting a
# number.
#
# (name, group, symbol_note)
PROBES = (
    # ---- plugin identity and load ----------------------------------------- #
    ("plugin_runtime_identity", "plugin",
     "unreal.WorldForgeIdentityStatics.get_world_forge_runtime_identity() -- the "
     "native runtime identity surface. Importing `unreal` proves the ENGINE "
     "loaded, never that the WorldForge plugin did."),
    ("plugin_survey_statics_reflected", "plugin",
     "hasattr(unreal, 'SceneSurveyStatics') -- the independent plugin-load "
     "signal scene_survey_far_side.py:2365 already uses, and the precondition it "
     "refuses on at :2425"),
    ("survey_enumerate_actors", "plugin",
     "SceneSurveyStatics.enumerate_survey_actors(world, center, radius_cm) -> "
     "int32 -- Plugins/WorldForge/Source/WorldForgeCore/Public/SceneSurvey.h:37-39"
     "; call site scene_survey_far_side.py:2436"),
    ("survey_sample_support", "plugin",
     "SceneSurveyStatics.sample_survey_support(world, center, radius_cm, step_cm)"
     " -> int32 -- SceneSurvey.h:47-49; call site scene_survey_far_side.py:2437"),
    ("survey_probe_temp_marker", "plugin",
     "SceneSurveyStatics.probe_temp_marker(world, location, capsule_radius, "
     "capsule_half_height) -> bool -- SceneSurvey.h:55-58; call site "
     "scene_survey_far_side.py:2454"),

    # ---- world / package identity ------------------------------------------ #
    ("world_identity", "world",
     "world.get_package().get_name() -- scene_survey_far_side.py:_record_world"),

    # ---- actor identity, membership, transforms ---------------------------- #
    ("actor_path_name", "actor",
     "Actor.get_path_name() -- scene_survey_far_side.py:707 (_path_of)"),
    ("actor_world_membership", "actor",
     "Actor.get_world() identity vs the editor world, cross-checked against the "
     "level enumeration"),
    ("actor_transform", "actor",
     "get_actor_location / get_actor_rotation / get_actor_scale3d"),

    # ---- bounds ------------------------------------------------------------- #
    ("actor_bounds", "bounds",
     "Actor.get_actor_bounds(only_colliding[, include_from_child_actors]) -- "
     "marked ASSUMED in scene_survey_far_side.py"),
    ("component_bounds", "bounds",
     "SystemLibrary.get_component_bounds(comp) -> 3-tuple -- marked ASSUMED in "
     "scene_survey_far_side.py"),

    # ---- geometry: the surface that was previously UNEXERCISED -------------- #
    ("line_trace_single", "geometry",
     "SystemLibrary.line_trace_single(world, start, end, channel, trace_complex, "
     "actors_to_ignore, draw_debug, ignore_self) -- scene_survey_far_side.py:940"),
    ("hit_result_decomposition", "geometry",
     "GameplayStatics.break_hit_result(hit) -> ASSUMED 18-tuple. FHitResult "
     "members are bare UPROPERTY() with NO BlueprintReadOnly, so they are NOT "
     "Python attributes and this is the only route -- "
     "scene_survey_far_side.py:855-862,872"),
    ("capsule_overlap_actors", "geometry",
     "SystemLibrary.capsule_overlap_actors(world, center, radius, half_height, "
     "object_types, actor_class_filter, actors_to_ignore) -- ASSUMED at "
     "scene_survey_far_side.py:975-978, called at :985"),
    ("capsule_overlap_components", "geometry",
     "SystemLibrary.capsule_overlap_components(world, center, radius, "
     "half_height, object_types, component_class_filter, actors_to_ignore) -- "
     "ASSUMED at scene_survey_far_side.py:1010-1013, called at :1022"),

    # ---- dirty-package observation ------------------------------------------ #
    ("dirty_map_packages", "packages",
     "EditorLoadingAndSavingUtils.get_dirty_map_packages()"),
    ("dirty_content_packages", "packages",
     "EditorLoadingAndSavingUtils.get_dirty_content_packages()"),

    # ---- operation-owned mutation ------------------------------------------- #
    ("transient_spawn_destroy_reobserve", "ownership",
     "EditorActorSubsystem.spawn_actor_from_class(..., transient=True) then "
     "destroy_actor, with destruction RE-OBSERVED through a NON-VACUOUS channel"),

    # ---- publication surfaces ------------------------------------------------ #
    ("raw_evidence_publication", "publication",
     "the far side publishes a structured raw-evidence bundle shaped as "
     + RAW_BUNDLE_SCHEMA + " whose every record carries the full "
     + RAW_RECORD_SCHEMA + " envelope"),
    ("operation_manifest_publication", "publication",
     "the far side publishes an operation manifest (" + MANIFEST_SCHEMA + ") "
     "declaring operation identity, owned objects and their disposition, and a "
     "digest over the raw bundle that the near side RE-COMPUTES"),

    # ---- D18 measurement ------------------------------------------------------ #
    ("d18_grid_measurement", "measurement",
     "the far side collects timed support-grid runs at several N with warm-up "
     "and repetitions -- docs/architecture/forge_design_decisions.md:121-149"),
)
PROBE_NAMES = tuple(name for name, _group, _sym in PROBES)
PROBE_GROUP = {name: group for name, group, _sym in PROBES}
PROBE_SYMBOL = {name: sym for name, _group, sym in PROBES}
REQUIRED_PROBES = PROBE_NAMES  # all of them; see the note above

# Named subsets the gate asserts over EXPLICITLY, so "the geometry surface was
# never executed but the gate was green" is structurally impossible rather than
# merely unlikely. _gate_integrity re-checks these against the report.
GEOMETRY_PROBES = tuple(n for n, g, _ in PROBES if g == "geometry")
PLUGIN_PROBES = tuple(n for n, g, _ in PROBES if g == "plugin")
PUBLICATION_PROBES = tuple(n for n, g, _ in PROBES if g == "publication")
PROBE_GROUPS = tuple(dict.fromkeys(g for _n, g, _s in PROBES))

# --------------------------------------------------------------------------- #
# D18 -- vocabulary, criteria, declared thresholds
# --------------------------------------------------------------------------- #
D18_PASS = "measured_pass"
D18_FAIL = "measured_fail"
D18_UNSUPPORTED = "unsupported"
D18_NOT_MEASURED = "not_measured"
D18_VERDICTS = (D18_PASS, D18_FAIL, D18_UNSUPPORTED, D18_NOT_MEASURED)

# READ THIS BEFORE READING THE CRITERIA TABLE.
# D18 says: "move the collector to C++ when the fixture smoke demonstrates at
# least one of these". Each criterion is therefore a PROMOTION TRIGGER, so:
#   measured_pass  -- measured, and the trigger IS met  -> argues FOR C++
#   measured_fail  -- measured, and the trigger is NOT met -> Python stays
#   unsupported    -- the criterion cannot be expressed as a measurement by this
#                     harness at all; a different instrument is required
#   not_measured   -- not answered this run. The promotion decision stays OPEN.
D18_VERDICT_SEMANTICS = {
    D18_PASS: "measured; this promotion trigger IS met (argues for moving the "
              "collector to C++)",
    D18_FAIL: "measured; this promotion trigger is NOT met (the collector stays "
              "in Python on this criterion)",
    D18_UNSUPPORTED: "this criterion cannot be expressed as a measurement by "
                     "this harness; a different instrument is required",
    D18_NOT_MEASURED: "not answered by this run -- the promotion decision stays "
                      "OPEN on this criterion. NEVER a default; always carries a "
                      "reason.",
}

# docs/architecture/forge_design_decisions.md:139-147, one entry per criterion,
# quoted.
D18_CRITERIA = (
    ("c1_python_cannot_expose_data",
     "Unreal Python cannot expose the required trace, collision, package, or "
     "component data reliably."),
    ("c2_interop_dominates_trace",
     "Python-Unreal interop overhead materially dominates trace execution "
     "(T_interop >> T_trace)."),
    ("c3_max_grid_misses_budget",
     "The maximum supported (R, s) combination cannot meet a declared runtime "
     "budget."),
    ("c4_nondeterministic_or_incomplete",
     "Python collection produces nondeterministic ordering or incomplete raw "
     "records that cannot be corrected cleanly."),
    ("c5_cleanup_needs_native_ownership",
     "Cleanup or world-lifetime correctness requires native scoped ownership."),
    ("c6_native_batch_trace_cheaper",
     "A native batch trace materially reduces cost while preserving identical "
     "semantics."),
)
D18_CRITERION_IDS = tuple(cid for cid, _text in D18_CRITERIA)

# Declared thresholds. Every one of these is a DECLARATION, not a discovery: a
# criterion answered against an undeclared threshold is an opinion.
D18_INTEROP_DOMINANCE_RATIO = 2.0   # criterion 2: T_interop / T_trace at or above
D18_BUDGET_SECONDS = 5.0            # criterion 3: budget for ONE grid collection
D18_BUDGET_RADIUS_CM = 4000.0       # ...at this declared maximum (R, s)
D18_BUDGET_STEP_CM = 100.0          # -> k=40, N=6561
D18_BATCH_MATERIAL_RATIO = 2.0      # criterion 6: native must be this much cheaper
D18_EQUIV_ABS_TOL = 1e-6            # record equivalence, absolute
D18_EQUIV_REL_TOL = 1e-9            # record equivalence, relative

# Default measurement plan. Every (R, s) here has R >= s ON PURPOSE.
# docs/contracts/v2_6_support_grid_contract.md:34-52 records an open discrepancy:
# the contract says k = floor(R/s) but the shipping C++ uses
# k = FMath::Max(1, (int32)(RadiusCm / StepCm)) (SceneSurvey.cpp:90), so the two
# disagree ONLY when R < s. Measuring exclusively at R >= s keeps every fit point
# on a sample count both formulas agree on; both are still computed and reported
# per config so the disagreement is visible if it ever moves.
D18_DEFAULT_CONFIGS = ((200.0, 200.0),    # k=1,  N=9
                       (400.0, 200.0),    # k=2,  N=25
                       (600.0, 200.0),    # k=3,  N=49
                       (800.0, 200.0),    # k=4,  N=81
                       (1200.0, 200.0),   # k=6,  N=169
                       (1600.0, 200.0))   # k=8,  N=289
D18_DEFAULT_WARMUP = 1
D18_DEFAULT_REPS = 5
D18_MIN_CONFIGS_FOR_FIT = 3
D18_MIN_REPS = 3
# Vertical extent of each support probe, in cm, above and below the grid plane.
D18_TRACE_UP_CM = 5000.0
D18_TRACE_DOWN_CM = 5000.0

# =========================================================================== #
# SHARED HELPERS -- defined once, used by BOTH sides. The digest helpers in
# particular MUST be one implementation: a far side and a near side that
# canonicalise differently would produce a digest mismatch that looks like
# tampering.
# =========================================================================== #
def canonical_json(obj):
    """The one canonical serialisation. Both sides digest exactly this."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(obj):
    return "sha256:" + hashlib.sha256(
        canonical_json(obj).encode("utf-8")).hexdigest()


def liveness_response(nonce, engine_version, uproject, pid, world_package):
    """The value a live far side can produce and a stale report cannot.

    Binds THIS run's nonce to values that only exist inside a booted editor. See
    LIVENESS THREAT MODEL in ``_verify_liveness`` for exactly what this does and
    does not defend against.
    """
    parts = [LIVENESS_DOMAIN, str(nonce), str(engine_version), str(uproject),
             str(pid), str(world_package)]
    return "sha256:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def grid_k_contract(radius_cm, step_cm):
    """k per docs/contracts/v2_6_support_grid_contract.md:20-31 -- floor(R/s)."""
    if step_cm <= 0:
        return None
    return int(math.floor(float(radius_cm) / float(step_cm)))


def grid_k_cpp(radius_cm, step_cm):
    """k as the SHIPPING C++ computes it -- SceneSurvey.cpp:90,
    ``FMath::Max(1, (int32)(RadiusCm / StepCm))``. Differs from the contract only
    when R < s; recorded so the known discrepancy stays visible."""
    if step_cm <= 0:
        return None
    return max(1, int(float(radius_cm) / float(step_cm)))


def grid_sample_count(k):
    """N = (2k + 1)^2 -- forge_design_decisions.md:133-137."""
    if k is None or k < 0:
        return None
    return (2 * k + 1) ** 2


def sample_id(row, col):
    """Canonical raw sample id.

    Row-major order is the contract: (i,j) < (i',j') iff i<i' or (i==i' and
    j<j'). Zero-padded non-negative row/col indices make LEXICOGRAPHIC order on
    the id string identical to row-major order on the coordinates, so ordering
    can be checked by sorting strings without re-deriving the geometry.
    """
    return "sample_{:04d}_{:04d}".format(row, col)


def _finite(x):
    """A finite float, or None. NEVER 0.0 as a stand-in for unreadable."""
    try:
        f = float(x)
    except Exception:  # noqa: BLE001
        return None
    return f if math.isfinite(f) else None


def _finite3(seq):
    """[x, y, z] of finite floats, or None."""
    try:
        out = [float(seq[0]), float(seq[1]), float(seq[2])]
    except Exception:  # noqa: BLE001
        return None
    return out if all(math.isfinite(v) for v in out) else None


def is_finite3(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(
        isinstance(v, (int, float)) and not isinstance(v, bool)
        and math.isfinite(v) for v in value)


# ---- statistics, plain Python. No third-party dependency: the repo installs
# ---- exactly one (pyyaml, .github/workflows/worldforge_contracts.yml:37) and
# ---- bans third-party imports outright in UE-side scripts (Makefile:198-199).
def median(values):
    vals = sorted(v for v in values if isinstance(v, (int, float))
                  and not isinstance(v, bool) and math.isfinite(v))
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def percentile(values, q):
    """Linear-interpolation percentile, q in [0, 100]. None when empty.

    The interpolation rule is declared rather than inherited: with 5 samples a
    nearest-rank p95 collapses onto the maximum and hides the tail's shape.
    """
    vals = sorted(v for v in values if isinstance(v, (int, float))
                  and not isinstance(v, bool) and math.isfinite(v))
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * (float(q) / 100.0)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def median_absolute_deviation(values):
    """MAD = median(|x - median(x)|). Raw, NOT scaled to a normal sigma."""
    med = median(values)
    if med is None:
        return None
    return median([abs(v - med) for v in values
                   if isinstance(v, (int, float)) and not isinstance(v, bool)
                   and math.isfinite(v)])


def fit_linear(xs, ys):
    """Ordinary least squares T(N) = alpha + beta*N + epsilon.

    Returns a dict, ALWAYS with a ``fitted`` boolean and a ``reason`` when it is
    False. A fit is refused rather than faked when there is no x-variance or
    fewer than three points -- a two-point "fit" has zero residual by
    construction and would report a perfect model of nothing.
    """
    pts = [(float(x), float(y)) for x, y in zip(xs, ys)
           if isinstance(x, (int, float)) and isinstance(y, (int, float))
           and math.isfinite(x) and math.isfinite(y)]
    out = {"fitted": False, "reason": None, "alpha": None, "beta": None,
           "r_squared": None, "residual_std": None, "points": len(pts),
           "distinct_x": 0}
    if len(pts) < 3:
        out["reason"] = ("only {} usable point(s); a fit needs at least 3"
                         .format(len(pts)))
        return out
    xs_ = [p[0] for p in pts]
    ys_ = [p[1] for p in pts]
    out["distinct_x"] = len(set(xs_))
    if out["distinct_x"] < 2:
        out["reason"] = "every point shares the same N; the slope is undefined"
        return out
    n = float(len(pts))
    mx = sum(xs_) / n
    my = sum(ys_) / n
    sxx = sum((x - mx) ** 2 for x in xs_)
    if sxx <= 0.0:
        out["reason"] = "zero variance in N"
        return out
    sxy = sum((x - mx) * (y - my) for x, y in pts)
    beta = sxy / sxx
    alpha = my - beta * mx
    resid = [y - (alpha + beta * x) for x, y in pts]
    sse = sum(r * r for r in resid)
    sst = sum((y - my) ** 2 for y in ys_)
    dof = len(pts) - 2
    out.update({
        "fitted": True,
        "alpha": alpha,
        "beta": beta,
        "r_squared": (1.0 - sse / sst) if sst > 0 else None,
        "residual_std": math.sqrt(sse / dof) if dof > 0 else None,
    })
    return out


def new_probe_table(status, detail):
    """A full probe table pinned to one status. Every probe key ALWAYS exists.

    A missing probe key would read as "not applicable" when it actually means
    "never ran", which is the exact confusion this file exists to remove.
    """
    return {name: {"status": status, "detail": detail, "group": group,
                   "symbol": symbol, "observed": None}
            for name, group, symbol in PROBES}


def new_d18_criteria_table(reason):
    """All six criteria pre-filled with not_measured. Never defaulted away."""
    return {cid: {"verdict": D18_NOT_MEASURED, "criterion": text,
                  "reason": reason, "evidence": None}
            for cid, text in D18_CRITERIA}

# =========================================================================== #
# EVIDENCE RE-DERIVATION
# --------------------------------------------------------------------------- #
# The far side declares a status. The near side does NOT take that declaration at
# face value: for every probe there is a validator that reads the transported
# OBSERVATION and asks whether it could have come from a working call. A probe
# that claims runtime_verified while carrying an observation that does not
# support it is downgraded to runtime_failed.
#
# This is the same shape the evidence model already uses elsewhere -- raw ->
# assembler derives -> validator re-derives independently -- applied to the smoke
# itself, and it is what makes a forged far-side status non-viable.
#
# Each validator returns None when the observation supports a pass, or a string
# saying what is missing.
# =========================================================================== #
def _need_keys(observed, keys):
    if not isinstance(observed, dict):
        return "the observation is {}, not an object".format(
            type(observed).__name__)
    missing = [k for k in keys if k not in observed]
    if missing:
        return "the observation is missing {}".format(", ".join(sorted(missing)))
    return None


def _need_nonempty_str(value, label):
    if not isinstance(value, str) or not value.strip():
        return "{} is not a non-empty string ({!r})".format(label, value)
    return None


def _v_plugin_runtime_identity(observed):
    fields = ("module_name", "plugin_name", "plugin_version", "contract_version",
              "build_identity", "loaded_module_path")
    err = _need_keys(observed, fields)
    if err:
        return err
    for f in fields:
        err = _need_nonempty_str(observed.get(f), f)
        if err:
            return err
    return None


def _v_survey_statics_reflected(observed):
    err = _need_keys(observed, ("hasattr", "class_repr"))
    if err:
        return err
    if observed.get("hasattr") is not True:
        return "hasattr(unreal, 'SceneSurveyStatics') was not True"
    return _need_nonempty_str(observed.get("class_repr"), "class_repr")


def _v_enumerate_actors(observed):
    err = _need_keys(observed, ("actor_count", "center", "radius_cm"))
    if err:
        return err
    count = observed.get("actor_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return "actor_count is not a non-negative int ({!r})".format(count)
    if not is_finite3(observed.get("center")):
        return "center is not a finite 3-vector"
    return None


def _v_sample_support(observed):
    err = _need_keys(observed, ("support_total", "center", "radius_cm", "step_cm"))
    if err:
        return err
    total = observed.get("support_total")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        return "support_total is not a non-negative int ({!r})".format(total)
    return None


def _v_probe_temp_marker(observed):
    err = _need_keys(observed, ("probe_returned", "candidate_location",
                                "capsule_radius", "capsule_half_height"))
    if err:
        return err
    if not isinstance(observed.get("probe_returned"), bool):
        return "probe_returned is not a bool ({!r})".format(
            observed.get("probe_returned"))
    if not is_finite3(observed.get("candidate_location")):
        return "candidate_location is not a finite 3-vector"
    return None


def _v_nonempty_string_observation(observed):
    return _need_nonempty_str(observed, "the observation")


def _v_world_membership(observed):
    err = _need_keys(observed, ("actor_world_package", "editor_world_package",
                                "present_in_level_enumeration"))
    if err:
        return err
    if observed.get("present_in_level_enumeration") is not True:
        return "the actor was not present in the level enumeration"
    a, e = observed.get("actor_world_package"), observed.get("editor_world_package")
    if not a or a != e:
        return "world packages do not agree ({!r} vs {!r})".format(a, e)
    return None


def _v_transform(observed):
    err = _need_keys(observed, ("location", "rotation", "scale3d"))
    if err:
        return err
    for key in ("location", "rotation", "scale3d"):
        if not is_finite3(observed.get(key)):
            return "{} is not a finite 3-vector".format(key)
    return None


def _v_actor_bounds(observed):
    err = _need_keys(observed, ("api_used", "origin", "extent"))
    if err:
        return err
    if not is_finite3(observed.get("origin")) or not is_finite3(observed.get("extent")):
        return "origin/extent are not finite 3-vectors"
    return _need_nonempty_str(observed.get("api_used"), "api_used")


def _v_component_bounds(observed):
    err = _need_keys(observed, ("origin", "extent", "sphere_radius",
                                "component_object_path"))
    if err:
        return err
    if not is_finite3(observed.get("origin")) or not is_finite3(observed.get("extent")):
        return "origin/extent are not finite 3-vectors"
    if _finite(observed.get("sphere_radius")) is None:
        return "sphere_radius is not a finite number"
    return None


def _v_line_trace(observed):
    err = _need_keys(observed, ("hit", "start", "end", "trace_channel",
                                "source_api", "out_hit_present"))
    if err:
        return err
    if not isinstance(observed.get("hit"), bool):
        return "hit is not a bool ({!r}) -- the hit/miss answer was not read".format(
            observed.get("hit"))
    if not is_finite3(observed.get("start")) or not is_finite3(observed.get("end")):
        return "trace endpoints are not finite 3-vectors"
    if observed.get("out_hit_present") is not True:
        return ("no FHitResult out-parameter was returned, so only the hit boolean "
                "was observed and the (bool, FHitResult) return shape is unproven")
    return _need_nonempty_str(observed.get("source_api"), "source_api")


def _v_hit_result(observed):
    err = _need_keys(observed, ("field_count", "fields", "read_errors",
                                "source_api"))
    if err:
        return err
    if observed.get("field_count") != 18:
        return ("break_hit_result returned {!r} field(s); the ASSUMED 18-tuple at "
                "scene_survey_far_side.py:855-862 is NOT confirmed and the field "
                "order cannot be trusted".format(observed.get("field_count")))
    if observed.get("read_errors"):
        return "field extraction reported errors: {}".format(
            observed.get("read_errors"))
    fields = observed.get("fields")
    if not isinstance(fields, dict):
        return "fields is not an object"
    if not isinstance(fields.get("blocking_hit"), bool):
        return "fields.blocking_hit is not a bool; index 0 did not decode"
    if _finite(fields.get("distance")) is None:
        return "fields.distance is not a finite number; index 3 did not decode"
    for key in ("location", "impact_point", "impact_normal"):
        if not is_finite3(fields.get(key)):
            return "fields.{} is not a finite 3-vector".format(key)
    return None


def _v_capsule_overlap(key):
    def _validate(observed):
        err = _need_keys(observed, ("query_ran", "paths", "center", "radius",
                                    "half_height", "object_type", "error"))
        if err:
            return err
        if observed.get("query_ran") is not True:
            return "the overlap query did not run"
        if observed.get("error"):
            return "the overlap query reported: {}".format(observed.get("error"))
        if not isinstance(observed.get("paths"), list):
            # An EMPTY list is a legitimate measurement -- nothing overlapped.
            # None is not: it means the set could not be read.
            return "{} were not read (paths is {!r})".format(
                key, observed.get("paths"))
        if not is_finite3(observed.get("center")):
            return "center is not a finite 3-vector"
        return None
    return _validate


def _v_dirty_packages(observed):
    if not isinstance(observed, list):
        # [] is a legitimate measurement: nothing is dirty. None is not.
        return "the dirty package set was not read (observed is {!r})".format(
            type(observed).__name__)
    return None


def _v_spawn_destroy(observed):
    err = _need_keys(observed, ("spawned_path", "validity_channel",
                                "valid_before_destroy", "valid_after_destroy",
                                "enumeration_absence_is_vacuous"))
    if err:
        return err
    if observed.get("valid_before_destroy") is not True:
        return "the spawned actor was not valid BEFORE destroy"
    if observed.get("valid_after_destroy") is not False:
        return ("the actor was not observed invalid after destroy "
                "(valid_after_destroy={!r})".format(
                    observed.get("valid_after_destroy")))
    err = _need_nonempty_str(observed.get("validity_channel"), "validity_channel")
    if err:
        return err
    return _need_nonempty_str(observed.get("spawned_path"), "spawned_path")


def _v_raw_evidence_publication(observed):
    err = _need_keys(observed, ("bundle_schema", "record_schema", "record_count",
                                "envelope_complete", "canonically_ordered",
                                "missing_envelope_fields"))
    if err:
        return err
    if observed.get("bundle_schema") != RAW_BUNDLE_SCHEMA:
        return "bundle_schema is {!r}, expected {!r}".format(
            observed.get("bundle_schema"), RAW_BUNDLE_SCHEMA)
    if observed.get("record_schema") != RAW_RECORD_SCHEMA:
        return "record_schema is {!r}, expected {!r}".format(
            observed.get("record_schema"), RAW_RECORD_SCHEMA)
    count = observed.get("record_count")
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return "record_count is {!r}; nothing was published".format(count)
    if observed.get("envelope_complete") is not True:
        return "records are missing envelope fields: {}".format(
            observed.get("missing_envelope_fields"))
    if observed.get("canonically_ordered") is not True:
        return "the published record ids are not in canonical order"
    return None


def _v_operation_manifest(observed):
    err = _need_keys(observed, ("manifest_schema", "operation_id",
                                "raw_evidence_digest", "digest_recomputed",
                                "digest_matches", "owned_objects",
                                "packages_saved", "permanent_actors_authored"))
    if err:
        return err
    if observed.get("manifest_schema") != MANIFEST_SCHEMA:
        return "manifest_schema is {!r}, expected {!r}".format(
            observed.get("manifest_schema"), MANIFEST_SCHEMA)
    err = _need_nonempty_str(observed.get("operation_id"), "operation_id")
    if err:
        return err
    if observed.get("digest_matches") is not True:
        return ("the near side re-computed the raw-bundle digest as {!r} but the "
                "manifest declares {!r}".format(observed.get("digest_recomputed"),
                                                observed.get("raw_evidence_digest")))
    if not isinstance(observed.get("owned_objects"), list):
        return "owned_objects is not a list"
    for obj in observed.get("owned_objects"):
        if not isinstance(obj, dict) or "object_path" not in obj \
                or "disposition" not in obj:
            return "an owned object entry is missing object_path/disposition"
        if obj.get("disposition") != "destroyed_and_reobserved_absent":
            return "owned object {!r} was left in disposition {!r}".format(
                obj.get("object_path"), obj.get("disposition"))
    if observed.get("packages_saved") != 0:
        return "the operation saved {!r} package(s); it must save none".format(
            observed.get("packages_saved"))
    if observed.get("permanent_actors_authored") != 0:
        return "the operation authored {!r} permanent actor(s)".format(
            observed.get("permanent_actors_authored"))
    return None


def _v_d18_measurement(observed):
    err = _need_keys(observed, ("configs_measured", "warmup_count",
                                "measurement_reps", "total_measured_reps",
                                "distinct_sample_counts", "collector_errors"))
    if err:
        return err
    configs = observed.get("configs_measured")
    if not isinstance(configs, int) or isinstance(configs, bool) \
            or configs < D18_MIN_CONFIGS_FOR_FIT:
        return ("only {!r} grid configuration(s) were measured; the fit "
                "T(N)=alpha+beta*N needs at least {}".format(
                    configs, D18_MIN_CONFIGS_FOR_FIT))
    if observed.get("distinct_sample_counts", 0) < D18_MIN_CONFIGS_FOR_FIT:
        return ("only {!r} distinct N value(s) were measured; alpha and beta "
                "cannot be separated".format(observed.get("distinct_sample_counts")))
    reps = observed.get("measurement_reps")
    if not isinstance(reps, int) or isinstance(reps, bool) or reps < D18_MIN_REPS:
        return ("only {!r} measurement repetition(s) per configuration; a single "
                "timing sample is not a measurement (minimum {})".format(
                    reps, D18_MIN_REPS))
    if observed.get("collector_errors"):
        return "the grid collector reported errors: {}".format(
            observed.get("collector_errors"))
    return None


# name -> validator. EVERY probe must appear: a probe with no validator is a
# probe whose runtime_verified claim nobody re-derives, and the structural
# self-check below refuses to let one exist.
EVIDENCE_VALIDATORS = {
    "plugin_runtime_identity": _v_plugin_runtime_identity,
    "plugin_survey_statics_reflected": _v_survey_statics_reflected,
    "survey_enumerate_actors": _v_enumerate_actors,
    "survey_sample_support": _v_sample_support,
    "survey_probe_temp_marker": _v_probe_temp_marker,
    "world_identity": _v_nonempty_string_observation,
    "actor_path_name": _v_nonempty_string_observation,
    "actor_world_membership": _v_world_membership,
    "actor_transform": _v_transform,
    "actor_bounds": _v_actor_bounds,
    "component_bounds": _v_component_bounds,
    "line_trace_single": _v_line_trace,
    "hit_result_decomposition": _v_hit_result,
    "capsule_overlap_actors": _v_capsule_overlap("overlapping actors"),
    "capsule_overlap_components": _v_capsule_overlap("overlapping components"),
    "dirty_map_packages": _v_dirty_packages,
    "dirty_content_packages": _v_dirty_packages,
    "transient_spawn_destroy_reobserve": _v_spawn_destroy,
    "raw_evidence_publication": _v_raw_evidence_publication,
    "operation_manifest_publication": _v_operation_manifest,
    "d18_grid_measurement": _v_d18_measurement,
}

_MISSING_VALIDATORS = tuple(n for n in PROBE_NAMES if n not in EVIDENCE_VALIDATORS)
if _MISSING_VALIDATORS:  # pragma: no cover -- structural, fires at import
    raise AssertionError(
        "every probe needs an evidence validator; missing: "
        + ", ".join(_MISSING_VALIDATORS))

# =========================================================================== #
# FAR SIDE -- runs INSIDE the editor, launched via -ExecutePythonScript.
#
# Emits observations and raw timings ONLY. It computes no statistic, no fit, no
# criterion, no gate. A far side that graded itself would be attesting to its own
# success.
# =========================================================================== #
def far_side_main():
    """Probe the live symbol surface and write raw observations to ENV_OUT."""
    import traceback

    import unreal  # provided by the UE Python runtime

    out_path = os.environ.get(ENV_OUT)
    map_path = os.environ.get(ENV_MAP) or DEFAULT_MAP
    nonce = os.environ.get(ENV_NONCE) or ""
    operation_id = os.environ.get(ENV_OPERATION_ID) or "op_v2_6_fixture_smoke"
    try:
        d18_plan = json.loads(os.environ.get(ENV_D18) or "{}")
    except Exception:  # noqa: BLE001
        d18_plan = {}

    doc = {
        "far_side_ran": True,
        "far_side_pid": os.getpid(),
        "map_requested": map_path,
        "map_loaded": None,
        "operation_id": operation_id,
        "nonce_seen": nonce,
        "observed_engine_version": None,
        "observed_uproject": None,
        "observed_world_package": None,
        "liveness_response": None,
        "probes": new_probe_table(
            STATUS_ASSUMED, "the far side aborted before this probe was reached"),
        "safety": {
            "dirty_map_packages_pre": None,
            "dirty_map_packages_post": None,
            "dirty_content_packages_pre": None,
            "dirty_content_packages_post": None,
            "target_map_dirty_after": None,
            "packages_saved": 0,
            "permanent_actors_authored": 0,
        },
        "raw_evidence": None,
        "operation_manifest": None,
        "d18_raw": None,
        "notes": [],
        "error": None,
        "traceback": None,
    }

    def log(msg):
        try:
            unreal.log("[v2.6-fixture-smoke] " + str(msg))
        except Exception:  # noqa: BLE001 -- logging must never fail the run
            pass

    def note(where, msg):
        doc["notes"].append("{}: {}".format(where, msg))

    def record(name, status, detail, observed=None):
        if status not in ALL_STATUSES:
            raise ValueError("illegal probe status " + repr(status))
        if name not in doc["probes"]:
            raise KeyError("unknown probe " + repr(name))
        rec = doc["probes"][name]
        rec["status"] = status
        rec["detail"] = str(detail)
        rec["observed"] = observed
        log("{}: {} ({})".format(name, status, detail))

    def write():
        if not out_path:
            log("FATAL: " + ENV_OUT + " is unset; nowhere to write observations")
            return
        try:
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2, sort_keys=True)
            log("wrote observations -> " + out_path)
        except Exception as exc:  # noqa: BLE001
            log("FATAL: could not write observations: {}: {}".format(
                type(exc).__name__, exc))

    def xyz(vec):
        try:
            return _finite3([vec.x, vec.y, vec.z])
        except Exception:  # noqa: BLE001
            return None

    def pyr(rot):
        try:
            return _finite3([rot.pitch, rot.yaw, rot.roll])
        except Exception:  # noqa: BLE001
            return None

    def why(exc):
        return "{}: {}".format(type(exc).__name__, exc)

    # ---- reflected-enum resolution, mirroring scene_survey_far_side.py:825-852
    def trace_channel():
        for name in ("TRACE_TYPE_QUERY1", "TraceTypeQuery1"):
            try:
                return getattr(unreal.TraceTypeQuery, name), name
            except Exception:  # noqa: BLE001
                continue
        return None, None

    def draw_debug_none():
        for name in ("NONE", "None_", "NO_DEBUG"):
            try:
                return getattr(unreal.DrawDebugTrace, name), name
            except Exception:  # noqa: BLE001
                continue
        return None, None

    def object_type(index):
        for name in ("OBJECT_TYPE_QUERY{}".format(index),
                     "ObjectTypeQuery{}".format(index)):
            try:
                return getattr(unreal.ObjectTypeQuery, name), name
            except Exception:  # noqa: BLE001
                continue
        return None, None

    def unpack_out(res):
        """UE Python returns (ReturnValue, OutParam) when a UFUNCTION has both.

        Mirrors scene_survey_far_side.py:810-823. An unrecognised shape must not
        be read as a miss, so both come back None.
        """
        if isinstance(res, bool):
            return res, None
        if isinstance(res, (tuple, list)) and len(res) >= 2:
            first = res[0]
            return (first if isinstance(first, bool) else None), res[1]
        return None, None

    # ---- the raw-evidence bundle this run publishes ------------------------ #
    raw_records = {}
    request_hash = digest({"map": map_path, "operation_id": operation_id,
                           "nonce": nonce})

    def envelope(record_type, ident, stage, collector, source_api=None,
                 actor_object_path=None, component_object_path=None,
                 measured_fields=()):
        """The envelope every raw record carries -- the same field list the real
        collector emits (scene_survey_far_side.py:528-534,:546-568). Constructed
        in the NOT-YET-COLLECTED state on purpose."""
        return {
            "record_schema": RAW_RECORD_SCHEMA,
            "operation_id": operation_id,
            "request_hash": request_hash,
            "request_hash_algorithm": "sha256",
            "record_id": "{}/{}".format(record_type, ident),
            "record_type": record_type,
            "record_ident": ident,
            "stage": stage,
            "collector": collector,
            "collection_status": "not_attempted",
            "evidence_class": "not_requested",
            "source_api": source_api,
            "world_identity": doc["observed_world_package"],
            "actor_object_path": actor_object_path,
            "component_object_path": component_object_path,
            "failure_code": None,
            "derived_fields": {},
            "measured_fields": list(measured_fields),
        }

    def publish(rec, collected, failure_code=None):
        rec["collection_status"] = "collected" if collected else "failed"
        rec["evidence_class"] = "observed" if collected else "not_requested"
        rec["failure_code"] = failure_code
        rec["world_identity"] = doc["observed_world_package"]
        raw_records[rec["record_id"]] = rec
        return rec

    try:
        # ---- identity of the process we are actually inside ---------------- #
        try:
            doc["observed_engine_version"] = unreal.SystemLibrary.get_engine_version()
        except Exception as exc:  # noqa: BLE001
            note("engine_version", "unreadable: " + why(exc))
        try:
            doc["observed_uproject"] = unreal.Paths.get_project_file_path()
        except Exception as exc:  # noqa: BLE001
            note("uproject", "unreadable: " + why(exc))

        # ---- plugin identity and load -------------------------------------- #
        # Lane-4 contract. If the symbol is absent the probe is
        # runtime_unavailable and the gate stays RED -- it is never skipped.
        ident_fields = ("module_name", "plugin_name", "plugin_version",
                        "contract_version", "build_identity", "loaded_module_path")
        statics = getattr(unreal, "WorldForgeIdentityStatics", None)
        if statics is None:
            record("plugin_runtime_identity", STATUS_UNAVAILABLE,
                   "unreal.WorldForgeIdentityStatics is not reflected. Either the "
                   "WorldForge plugin did not load, or the native runtime identity "
                   "surface has not been built yet. Nothing was observed.")
        else:
            getter = getattr(statics, "get_world_forge_runtime_identity", None)
            if getter is None:
                record("plugin_runtime_identity", STATUS_UNAVAILABLE,
                       "WorldForgeIdentityStatics exists but "
                       "get_world_forge_runtime_identity is not reflected on it")
            else:
                try:
                    ident = getter()
                except Exception as exc:  # noqa: BLE001
                    record("plugin_runtime_identity", STATUS_FAILED,
                           "get_world_forge_runtime_identity raised: " + why(exc))
                else:
                    got, missing = {}, []
                    for field in ident_fields:
                        value = None
                        for attr in (field, field.replace("_", "")):
                            try:
                                value = getattr(ident, attr)
                                break
                            except Exception:  # noqa: BLE001
                                continue
                        if value is None:
                            missing.append(field)
                        else:
                            got[field] = str(value)
                    if missing:
                        record("plugin_runtime_identity", STATUS_FAILED,
                               "the identity struct is missing field(s): "
                               + ", ".join(missing), got)
                    else:
                        record("plugin_runtime_identity", STATUS_VERIFIED,
                               "a WorldForge plugin-owned native function executed "
                               "and returned a complete runtime identity", got)

        # An INDEPENDENT load signal: the type the real collector refuses on
        # (scene_survey_far_side.py:2365,:2425).
        has_survey = hasattr(unreal, "SceneSurveyStatics")
        if not has_survey:
            record("plugin_survey_statics_reflected", STATUS_UNAVAILABLE,
                   "unreal.SceneSurveyStatics is not reflected -- the WorldForge "
                   "plugin is NOT loaded in this editor",
                   {"hasattr": False, "class_repr": None})
        else:
            record("plugin_survey_statics_reflected", STATUS_VERIFIED,
                   "unreal.SceneSurveyStatics is reflected",
                   {"hasattr": True, "class_repr": repr(unreal.SceneSurveyStatics)})

        # ---- load the target map (proven pattern: wf_map_actor_census.py:47-49)
        try:
            les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
            doc["map_loaded"] = bool(les.load_level(map_path))
        except Exception as exc:  # noqa: BLE001
            doc["map_loaded"] = False
            note("load_level", "raised: " + why(exc))

        if not doc["map_loaded"]:
            doc["error"] = ("map {} did not load; no world-dependent probe could "
                            "be reached".format(map_path))
            write()
            return

        # ---- probe: world identity ------------------------------------------ #
        world = None
        world_package = None
        try:
            ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
            world = ues.get_editor_world()
        except Exception as exc:  # noqa: BLE001
            record("world_identity", STATUS_UNAVAILABLE,
                   "UnrealEditorSubsystem.get_editor_world is unavailable: " + why(exc))
        if world is None and doc["probes"]["world_identity"]["status"] == STATUS_ASSUMED:
            record("world_identity", STATUS_FAILED,
                   "get_editor_world() returned None inside a loaded map")
        elif world is not None:
            try:
                pkg = world.get_package()
            except Exception as exc:  # noqa: BLE001
                pkg = None
                record("world_identity", STATUS_UNAVAILABLE,
                       "World.get_package is not reflected: " + why(exc))
            if pkg is not None:
                try:
                    world_package = pkg.get_name()
                except Exception as exc:  # noqa: BLE001
                    record("world_identity", STATUS_UNAVAILABLE,
                           "Package.get_name is not reflected: " + why(exc))
                else:
                    if isinstance(world_package, str) and world_package.strip():
                        doc["observed_world_package"] = world_package
                        record("world_identity", STATUS_VERIFIED,
                               "world.get_package().get_name() returned a usable "
                               "package name", world_package)
                    else:
                        record("world_identity", STATUS_FAILED,
                               "world.get_package().get_name() returned an unusable "
                               "value: {!r}".format(world_package))

        # The liveness response is bound to values only a live process holds.
        doc["liveness_response"] = liveness_response(
            nonce, doc["observed_engine_version"], doc["observed_uproject"],
            doc["far_side_pid"], doc["observed_world_package"])

        # ---- enumerate actors (proven: wf_map_actor_census.py:51) ------------ #
        actors = None
        eas = None
        try:
            eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
            actors = list(eas.get_all_level_actors())
        except Exception as exc:  # noqa: BLE001
            note("get_all_level_actors", "failed: " + why(exc))

        if not actors:
            doc["error"] = ("no actors enumerated in {}; the per-actor and geometry "
                            "probes could not be reached".format(map_path))
            write()
            return

        subject = actors[0]

        # ---- probe: actor path name ------------------------------------------ #
        try:
            path_name = subject.get_path_name()
        except Exception as exc:  # noqa: BLE001
            record("actor_path_name", STATUS_UNAVAILABLE,
                   "Actor.get_path_name is not reflected: " + why(exc))
            path_name = None
        else:
            if isinstance(path_name, str) and path_name.strip():
                record("actor_path_name", STATUS_VERIFIED,
                       "Actor.get_path_name() returned a usable object path",
                       path_name)
            else:
                record("actor_path_name", STATUS_FAILED,
                       "Actor.get_path_name() returned {!r}".format(path_name))

        # ---- probe: actor world membership ------------------------------------ #
        # Two independent channels must agree: the actor's own get_world()
        # package, and its presence in the level enumeration. Either alone could
        # be satisfied by an actor from some other world.
        try:
            actor_world = subject.get_world()
        except Exception as exc:  # noqa: BLE001
            record("actor_world_membership", STATUS_UNAVAILABLE,
                   "Actor.get_world is not reflected: " + why(exc))
        else:
            actor_world_pkg = None
            try:
                actor_world_pkg = actor_world.get_package().get_name()
            except Exception as exc:  # noqa: BLE001
                note("actor_world_package", "unreadable: " + why(exc))
            in_enumeration = path_name is not None and any(
                _safe_path(a) == path_name for a in actors)
            observed = {
                "actor_world_package": actor_world_pkg,
                "editor_world_package": world_package,
                "present_in_level_enumeration": in_enumeration,
            }
            if actor_world_pkg is None:
                record("actor_world_membership", STATUS_UNAVAILABLE,
                       "the actor's world package could not be read, so membership "
                       "could not be established", observed)
            elif world_package is not None and actor_world_pkg == world_package \
                    and in_enumeration:
                record("actor_world_membership", STATUS_VERIFIED,
                       "the actor's world matches the editor world AND the actor is "
                       "present in the level enumeration", observed)
            else:
                record("actor_world_membership", STATUS_FAILED,
                       "world membership channels disagree", observed)

        # ---- probe: actor transform -------------------------------------------- #
        transform = {}
        transform_errors = []
        for key, getter, conv in (("location", "get_actor_location", xyz),
                                  ("rotation", "get_actor_rotation", pyr),
                                  ("scale3d", "get_actor_scale3d", xyz)):
            try:
                fn = getattr(subject, getter)
            except Exception as exc:  # noqa: BLE001
                transform_errors.append("{} is not reflected: {}".format(getter, why(exc)))
                continue
            try:
                transform[key] = conv(fn())
            except Exception as exc:  # noqa: BLE001
                transform_errors.append("{} raised: {}".format(getter, why(exc)))
        if transform_errors and not transform:
            record("actor_transform", STATUS_UNAVAILABLE,
                   "; ".join(transform_errors), transform)
        elif transform_errors:
            record("actor_transform", STATUS_FAILED,
                   "; ".join(transform_errors), transform)
        elif all(transform.get(k) is not None
                 for k in ("location", "rotation", "scale3d")):
            record("actor_transform", STATUS_VERIFIED,
                   "location, rotation and scale3d all returned finite 3-vectors",
                   transform)
        else:
            record("actor_transform", STATUS_FAILED,
                   "a transform getter returned a non-finite or unreadable vector",
                   transform)

        # ---- probe: actor bounds ------------------------------------------------ #
        # 2-arg form first, 1-arg fallback. Which form actually answers is the
        # finding, and it is recorded rather than assumed.
        bounds_origin = bounds_extent = None
        bounds_errors = []
        for call_args, label in (((False, True), "get_actor_bounds(False, True)"),
                                 ((False,), "get_actor_bounds(False)")):
            try:
                res = subject.get_actor_bounds(*call_args)
            except Exception as exc:  # noqa: BLE001
                bounds_errors.append("{}: {}".format(label, why(exc)))
                continue
            try:
                origin, extent = xyz(res[0]), xyz(res[1])
            except Exception as exc:  # noqa: BLE001
                bounds_errors.append("{} returned an unusable shape: {}".format(
                    label, why(exc)))
                continue
            if origin is None or extent is None:
                bounds_errors.append(label + " returned non-finite components")
                continue
            bounds_origin, bounds_extent = origin, extent
            record("actor_bounds", STATUS_VERIFIED,
                   "the ASSUMED get_actor_bounds signature is real; answered by "
                   + label,
                   {"api_used": label, "origin": origin, "extent": extent,
                    "rejected_forms": bounds_errors,
                    "actor_object_path": path_name})
            break
        if bounds_origin is None:
            record("actor_bounds",
                   STATUS_UNAVAILABLE if not bounds_errors else STATUS_FAILED,
                   "; ".join(bounds_errors) or "get_actor_bounds is unavailable")

        # ---- probe: component bounds --------------------------------------------- #
        comps = None
        try:
            comps = list(subject.get_components_by_class(unreal.PrimitiveComponent))
        except Exception as exc:  # noqa: BLE001
            record("component_bounds", STATUS_UNAVAILABLE,
                   "could not enumerate PrimitiveComponents: " + why(exc))
        if comps is not None:
            if not comps:
                record("component_bounds", STATUS_ASSUMED,
                       "the subject actor carries no PrimitiveComponent, so "
                       "SystemLibrary.get_component_bounds was never called")
            else:
                try:
                    res = unreal.SystemLibrary.get_component_bounds(comps[0])
                except Exception as exc:  # noqa: BLE001
                    record("component_bounds", STATUS_UNAVAILABLE,
                           "SystemLibrary.get_component_bounds is not reflected or "
                           "raised: " + why(exc))
                else:
                    try:
                        origin, extent, radius = xyz(res[0]), xyz(res[1]), float(res[2])
                    except Exception as exc:  # noqa: BLE001
                        record("component_bounds", STATUS_FAILED,
                               "get_component_bounds returned an unusable shape "
                               "({!r}): {}".format(type(res).__name__, why(exc)))
                    else:
                        if origin is None or extent is None:
                            record("component_bounds", STATUS_FAILED,
                                   "get_component_bounds returned non-finite "
                                   "components")
                        else:
                            record("component_bounds", STATUS_VERIFIED,
                                   "the ASSUMED get_component_bounds 3-tuple is real",
                                   {"origin": origin, "extent": extent,
                                    "sphere_radius": radius,
                                    "component_object_path": _safe_path(comps[0])})
                            if bounds_origin is None:
                                bounds_origin, bounds_extent = origin, extent

        # ---- the probe anchor ---------------------------------------------- #
        # Everything geometric happens at the subject actor's bounds origin, so a
        # downward trace has something to hit and a capsule has something to
        # overlap. Falling back to the actor location, then to the world origin,
        # keeps the geometry surface exercised even on a degraded fixture -- but
        # WHICH anchor was used is recorded, because "the trace missed" means
        # something different at each one.
        if bounds_origin is not None:
            center = list(bounds_origin)
            anchor_source = "actor_bounds_origin"
        elif transform.get("location") is not None:
            center = list(transform["location"])
            anchor_source = "actor_location"
        else:
            center = [0.0, 0.0, 0.0]
            anchor_source = "world_origin_fallback"
        half_z = 100.0
        if bounds_extent is not None:
            half_z = max(100.0, float(bounds_extent[2]))
        note("anchor", "geometry anchored at {} ({})".format(center, anchor_source))

        # ---- probes: the three USceneSurveyStatics primitives ---------------- #
        # SceneSurvey.h:37-39, :47-49, :55-58. These are plugin-OWNED functions:
        # executing them is the load proof that observing an engine class is not.
        if not has_survey:
            for name in ("survey_enumerate_actors", "survey_sample_support",
                         "survey_probe_temp_marker"):
                record(name, STATUS_UNAVAILABLE,
                       "unreal.SceneSurveyStatics is not reflected, so this "
                       "plugin-owned primitive could not be called")
        else:
            stat = unreal.SceneSurveyStatics
            ctr = unreal.Vector(center[0], center[1], center[2])
            survey_radius, survey_step = 1000.0, 200.0

            try:
                actor_count = int(stat.enumerate_survey_actors(
                    world, ctr, survey_radius))
            except Exception as exc:  # noqa: BLE001
                record("survey_enumerate_actors", STATUS_FAILED,
                       "enumerate_survey_actors raised: " + why(exc))
            else:
                obs = {"actor_count": actor_count, "center": center,
                       "radius_cm": survey_radius}
                if actor_count < 0:
                    record("survey_enumerate_actors", STATUS_FAILED,
                           "enumerate_survey_actors returned a negative count", obs)
                else:
                    record("survey_enumerate_actors", STATUS_VERIFIED,
                           "a WorldForge plugin-owned native function executed and "
                           "returned an int32 actor count", obs)
                publish(dict(envelope(
                    "survey_primitive", "enumerate_survey_actors", "probe",
                    "USceneSurveyStatics::EnumerateSurveyActors",
                    source_api="SceneSurveyStatics.enumerate_survey_actors",
                    measured_fields=("actor_count",)), **{"observed": obs}), True)

            try:
                support_total = int(stat.sample_survey_support(
                    world, ctr, survey_radius, survey_step))
            except Exception as exc:  # noqa: BLE001
                record("survey_sample_support", STATUS_FAILED,
                       "sample_survey_support raised: " + why(exc))
            else:
                obs = {"support_total": support_total, "center": center,
                       "radius_cm": survey_radius, "step_cm": survey_step,
                       "n_contract": grid_sample_count(
                           grid_k_contract(survey_radius, survey_step)),
                       "n_cpp": grid_sample_count(
                           grid_k_cpp(survey_radius, survey_step))}
                if support_total < 0:
                    record("survey_sample_support", STATUS_FAILED,
                           "sample_survey_support returned a negative total", obs)
                else:
                    record("survey_sample_support", STATUS_VERIFIED,
                           "a WorldForge plugin-owned native function executed and "
                           "returned an int32 support total", obs)
                publish(dict(envelope(
                    "survey_primitive", "sample_survey_support", "probe",
                    "USceneSurveyStatics::SampleSurveySupport",
                    source_api="SceneSurveyStatics.sample_survey_support",
                    measured_fields=("support_total",)), **{"observed": obs}), True)

            marker_loc = [center[0] + survey_step, center[1], center[2]]
            try:
                probe_returned = bool(stat.probe_temp_marker(
                    world, unreal.Vector(*marker_loc), 34.0, 88.0))
            except Exception as exc:  # noqa: BLE001
                record("survey_probe_temp_marker", STATUS_FAILED,
                       "probe_temp_marker raised: " + why(exc))
            else:
                obs = {"probe_returned": probe_returned,
                       "candidate_location": marker_loc,
                       "capsule_radius": 34.0, "capsule_half_height": 88.0}
                # True and False are BOTH legitimate measurements here: the
                # primitive answers "is this spot placeable". Executing it is the
                # proof; its answer is data, not a verdict.
                record("survey_probe_temp_marker", STATUS_VERIFIED,
                       "a WorldForge plugin-owned native function executed and "
                       "returned a bool ({})".format(probe_returned), obs)
                publish(dict(envelope(
                    "survey_primitive", "probe_temp_marker", "probe",
                    "USceneSurveyStatics::ProbeTempMarker",
                    source_api="SceneSurveyStatics.probe_temp_marker",
                    measured_fields=("probe_returned",)), **{"observed": obs}), True)

        # ---- probes: line trace + hit-result decomposition -------------------- #
        channel, channel_name = trace_channel()
        debug, debug_name = draw_debug_none()
        trace_start = [center[0], center[1], center[2] + half_z + D18_TRACE_UP_CM]
        trace_end = [center[0], center[1], center[2] - half_z - D18_TRACE_DOWN_CM]
        out_hit = None
        if channel is None or debug is None:
            detail = ("TraceTypeQuery/DrawDebugTrace enum members are not reflected "
                      "under any name this harness knows (tried TRACE_TYPE_QUERY1/"
                      "TraceTypeQuery1 and NONE/None_/NO_DEBUG); no trace was "
                      "attempted")
            record("line_trace_single", STATUS_UNAVAILABLE, detail)
            record("hit_result_decomposition", STATUS_ASSUMED,
                   "no trace ran, so no FHitResult existed to decompose")
        else:
            trace_rec = publish(envelope(
                "trace", "probe_trace_000", "probe", "line_trace_single",
                source_api="SystemLibrary.line_trace_single",
                actor_object_path=path_name,
                measured_fields=("hit", "distance", "impact_point")), False,
                "support_sample")
            try:
                res = unreal.SystemLibrary.line_trace_single(
                    world, unreal.Vector(*trace_start), unreal.Vector(*trace_end),
                    channel, True, [], debug, True)
            except Exception as exc:  # noqa: BLE001
                record("line_trace_single", STATUS_UNAVAILABLE,
                       "SystemLibrary.line_trace_single is not reflected or raised: "
                       + why(exc),
                       {"start": trace_start, "end": trace_end,
                        "trace_channel": channel_name, "draw_debug": debug_name})
                record("hit_result_decomposition", STATUS_ASSUMED,
                       "the trace call did not return, so no FHitResult existed")
            else:
                hit, out_hit = unpack_out(res)
                obs = {"hit": hit, "start": trace_start, "end": trace_end,
                       "trace_channel": channel_name, "draw_debug": debug_name,
                       "out_hit_present": out_hit is not None,
                       "returned_shape": type(res).__name__,
                       "source_api": "SystemLibrary.line_trace_single",
                       "anchor_source": anchor_source}
                if hit is None:
                    record("line_trace_single", STATUS_FAILED,
                           "line_trace_single returned an unrecognised shape {!r}; "
                           "the hit/miss answer was NOT read".format(
                               type(res).__name__), obs)
                elif out_hit is None:
                    record("line_trace_single", STATUS_FAILED,
                           "the hit boolean was read but no FHitResult "
                           "out-parameter came back, so the (bool, FHitResult) "
                           "return shape scene_survey_far_side.py:947 depends on is "
                           "NOT confirmed", obs)
                else:
                    record("line_trace_single", STATUS_VERIFIED,
                           "line_trace_single executed and returned "
                           "(bool, FHitResult); hit={}".format(bool(hit)), obs)
                trace_rec["observed"] = obs
                publish(trace_rec, hit is not None,
                        None if hit is not None else "support_sample")

            if out_hit is None:
                if doc["probes"]["hit_result_decomposition"]["status"] == STATUS_ASSUMED:
                    record("hit_result_decomposition", STATUS_ASSUMED,
                           "no FHitResult out-parameter was produced, so "
                           "break_hit_result was never called")
            else:
                # FHitResult members are bare UPROPERTY() with NO
                # BlueprintReadOnly, so they are NOT Python attributes;
                # break_hit_result is the only route
                # (scene_survey_far_side.py:855-862).
                try:
                    parts = list(unreal.GameplayStatics.break_hit_result(out_hit))
                except Exception as exc:  # noqa: BLE001
                    record("hit_result_decomposition", STATUS_UNAVAILABLE,
                           "GameplayStatics.break_hit_result is not reflected or "
                           "raised: " + why(exc))
                else:
                    read_errors = []

                    def at(index, conv, label):
                        try:
                            return conv(parts[index])
                        except Exception as exc:  # noqa: BLE001
                            read_errors.append("{}[{}]: {}".format(
                                label, index, why(exc)))
                            return None

                    fields = {
                        "blocking_hit": at(0, lambda v: bool(v)
                                           if isinstance(v, bool) else None,
                                           "blocking_hit"),
                        "initial_overlap": at(1, lambda v: bool(v)
                                              if isinstance(v, bool) else None,
                                              "initial_overlap"),
                        "time": at(2, _finite, "time"),
                        "distance": at(3, _finite, "distance"),
                        "location": at(4, xyz, "location"),
                        "impact_point": at(5, xyz, "impact_point"),
                        "normal": at(6, xyz, "normal"),
                        "impact_normal": at(7, xyz, "impact_normal"),
                        "hit_actor_path": at(9, lambda v: _safe_path(v)
                                             if v is not None else None,
                                             "hit_actor"),
                        "hit_component_path": at(10, lambda v: _safe_path(v)
                                                 if v is not None else None,
                                                 "hit_component"),
                        "face_index": at(15, lambda v: int(v), "face_index"),
                        "trace_start": at(16, xyz, "trace_start"),
                        "trace_end": at(17, xyz, "trace_end"),
                    } if len(parts) >= 18 else {}
                    obs = {"field_count": len(parts), "fields": fields,
                           "read_errors": read_errors,
                           "source_api": "GameplayStatics.break_hit_result"}
                    if len(parts) != 18:
                        record("hit_result_decomposition", STATUS_FAILED,
                               "break_hit_result returned {} field(s), not the "
                               "ASSUMED 18; the field ORDER cannot be trusted, so "
                               "nothing was read from it".format(len(parts)), obs)
                    elif read_errors:
                        record("hit_result_decomposition", STATUS_FAILED,
                               "the 18-tuple arrived but field extraction failed: "
                               + "; ".join(read_errors), obs)
                    else:
                        record("hit_result_decomposition", STATUS_VERIFIED,
                               "the ASSUMED 18-tuple at "
                               "scene_survey_far_side.py:855-862 is real and every "
                               "load-bearing field decoded", obs)
                    publish(dict(envelope(
                        "hit_result", "probe_trace_000", "probe",
                        "break_hit_result",
                        source_api="GameplayStatics.break_hit_result",
                        actor_object_path=fields.get("hit_actor_path"),
                        component_object_path=fields.get("hit_component_path"),
                        measured_fields=tuple(sorted(fields))),
                        **{"observed": obs}), len(parts) == 18 and not read_errors,
                        None if len(parts) == 18 and not read_errors
                        else "support_sample")

        # ---- probes: capsule overlaps ------------------------------------------ #
        # Actor paths alone cannot say WHAT inside an actor blocks a capsule, which
        # is why the component set is collected as its own probe and degrades on
        # its own (scene_survey_far_side.py:1005-1013).
        otype, otype_name = object_type(1)  # 1 = WorldStatic
        for probe_name, fn_name, kind in (
                ("capsule_overlap_actors", "capsule_overlap_actors", "actors"),
                ("capsule_overlap_components", "capsule_overlap_components",
                 "components")):
            obs = {"query_ran": False, "paths": None, "center": center,
                   "radius": 200.0, "half_height": max(200.0, half_z),
                   "object_type": otype_name, "error": None,
                   "source_api": "SystemLibrary." + fn_name}
            if otype is None:
                obs["error"] = "ObjectTypeQuery1 is not reflected under any known name"
                record(probe_name, STATUS_UNAVAILABLE, obs["error"], obs)
                continue
            fn = getattr(unreal.SystemLibrary, fn_name, None)
            if fn is None:
                obs["error"] = "SystemLibrary.{} is not reflected".format(fn_name)
                record(probe_name, STATUS_UNAVAILABLE, obs["error"], obs)
                continue
            try:
                res = fn(world, unreal.Vector(*center), obs["radius"],
                         obs["half_height"], [otype], None, [])
            except Exception as exc:  # noqa: BLE001
                obs["error"] = "{} raised: {}".format(fn_name, why(exc))
                record(probe_name, STATUS_FAILED, obs["error"], obs)
                continue
            _ok, found = unpack_out(res)
            if found is None and isinstance(res, (tuple, list)) and len(res) == 1:
                found = res[0]
            if found is None:
                obs["error"] = ("{} returned an unrecognised shape {!r}; the overlap "
                                "set was NOT read".format(fn_name, type(res).__name__))
                record(probe_name, STATUS_FAILED, obs["error"], obs)
                continue
            try:
                paths = sorted(p for p in (_safe_path(o) for o in found) if p)
            except Exception as exc:  # noqa: BLE001
                obs["error"] = "{} result is not iterable: {}".format(fn_name, exc)
                record(probe_name, STATUS_FAILED, obs["error"], obs)
                continue
            obs["query_ran"] = True
            obs["paths"] = paths
            # An EMPTY overlap set is a legitimate MEASUREMENT -- the capsule
            # enclosed nothing. It is only a lie when it stands in for an
            # unreadable set, and every branch above has already routed that away.
            record(probe_name, STATUS_VERIFIED,
                   "the ASSUMED {} signature is real; {} {} returned".format(
                       fn_name, len(paths), kind), obs)
            publish(dict(envelope(
                "overlap", fn_name, "probe", fn_name,
                source_api="SystemLibrary." + fn_name,
                measured_fields=("paths",)), **{"observed": obs}), True)

        # ---- probes: dirty package sets ------------------------------------------ #
        def dirty(getter_name):
            """(names, status, detail). None names == not observed, never []."""
            try:
                getter = getattr(unreal.EditorLoadingAndSavingUtils, getter_name)
            except Exception as exc:  # noqa: BLE001
                return None, STATUS_UNAVAILABLE, \
                    "EditorLoadingAndSavingUtils.{} is not reflected: {}".format(
                        getter_name, why(exc))
            try:
                pkgs = getter()
            except Exception as exc:  # noqa: BLE001
                return None, STATUS_FAILED, "{} raised: {}".format(getter_name, why(exc))
            try:
                names = sorted(str(p.get_name()) for p in pkgs)
            except Exception as exc:  # noqa: BLE001
                return None, STATUS_FAILED, \
                    "{} result is not a usable package sequence: {}".format(
                        getter_name, why(exc))
            return names, STATUS_VERIFIED, \
                "{} returned a readable package set ({} entries)".format(
                    getter_name, len(names))

        maps_pre, map_status, map_detail = dirty("get_dirty_map_packages")
        record("dirty_map_packages", map_status, map_detail, maps_pre)
        doc["safety"]["dirty_map_packages_pre"] = maps_pre

        content_pre, content_status, content_detail = dirty("get_dirty_content_packages")
        record("dirty_content_packages", content_status, content_detail, content_pre)
        doc["safety"]["dirty_content_packages_pre"] = content_pre

        # ---- probe: operation-owned spawn -> destroy -> RE-OBSERVE absence ------- #
        # RUNTIME FINDING (this harness, 2026-07-27): an actor spawned with
        # transient=True is NOT returned by get_all_level_actors(). The consequence
        # is load-bearing: scene_survey_far_side.py derives
        #     absent_after_cleanup = (path not in present)
        # from that same enumeration. For a transient actor the path was NEVER in
        # `present`, so the expression is True whether or not destroy_actor did
        # anything -- the cleanup "verification" is VACUOUS. Absence from a set that
        # never contained the item is not evidence of removal.
        #
        # So this probe demands a channel that could actually have said "no":
        # object validity after destroy. Enumeration absence is still recorded, but
        # it is explicitly NOT allowed to be the proof.
        owned_objects = []
        spawn_obs = {
            "pie_state": None, "actors_before": len(actors),
            "actors_after_spawn": None, "actors_after_destroy": None,
            "spawned_path": None, "destroy_returned": None,
            "absent_after_cleanup": None,
            "visible_in_enumeration_after_spawn": None,
            "validity_channel": None, "valid_before_destroy": None,
            "valid_after_destroy": None, "enumeration_absence_is_vacuous": None,
        }

        def validity(obj):
            """(is_valid, channel), or (None, None) if no channel answered."""
            try:
                return bool(unreal.SystemLibrary.is_valid(obj)), "SystemLibrary.is_valid"
            except Exception:  # noqa: BLE001
                pass
            try:
                return bool(obj.is_valid()), "UObject.is_valid"
            except Exception:  # noqa: BLE001
                pass
            try:
                return (not bool(obj.is_actor_being_destroyed())), \
                    "not Actor.is_actor_being_destroyed"
            except Exception:  # noqa: BLE001
                pass
            return None, None

        pie = None
        try:
            pie = bool(unreal.get_editor_subsystem(
                unreal.LevelEditorSubsystem).is_in_play_in_editor())
        except Exception as exc:  # noqa: BLE001
            note("pie_state", "unreadable: " + why(exc))
        spawn_obs["pie_state"] = pie
        if pie is not False:
            record("transient_spawn_destroy_reobserve", STATUS_ASSUMED,
                   "refused to spawn: play-in-editor state is {!r} and "
                   "spawn/destroy silently no-op during PIE".format(pie), spawn_obs)
        elif eas is None:
            record("transient_spawn_destroy_reobserve", STATUS_UNAVAILABLE,
                   "EditorActorSubsystem is unavailable", spawn_obs)
        else:
            spawned = None
            try:
                spawned = eas.spawn_actor_from_class(
                    unreal.StaticMeshActor, unreal.Vector(0.0, 0.0, 0.0),
                    unreal.Rotator(0.0, 0.0, 0.0), transient=True)
            except Exception as exc:  # noqa: BLE001
                record("transient_spawn_destroy_reobserve", STATUS_UNAVAILABLE,
                       "spawn_actor_from_class(..., transient=True) is not reflected "
                       "or raised: " + why(exc), spawn_obs)
            if spawned is None and doc["probes"][
                    "transient_spawn_destroy_reobserve"]["status"] == STATUS_ASSUMED:
                record("transient_spawn_destroy_reobserve", STATUS_FAILED,
                       "spawn_actor_from_class returned None", spawn_obs)
            elif spawned is not None:
                spawn_obs["spawned_path"] = _safe_path(spawned)
                mid = None
                try:
                    mid = [_safe_path(a) for a in eas.get_all_level_actors()]
                except Exception as exc:  # noqa: BLE001
                    note("post_spawn_enumeration", "failed: " + why(exc))
                if mid is not None:
                    spawn_obs["actors_after_spawn"] = len(mid)
                    spawn_obs["visible_in_enumeration_after_spawn"] = \
                        spawn_obs["spawned_path"] in mid
                valid_before, vchannel = validity(spawned)
                spawn_obs["valid_before_destroy"] = valid_before
                spawn_obs["validity_channel"] = vchannel

                try:
                    spawn_obs["destroy_returned"] = bool(eas.destroy_actor(spawned))
                except Exception as exc:  # noqa: BLE001
                    note("destroy_actor", "raised: " + why(exc))

                after = None
                try:
                    after = [_safe_path(a) for a in eas.get_all_level_actors()]
                except Exception as exc:  # noqa: BLE001
                    note("post_destroy_enumeration", "failed: " + why(exc))
                if after is not None:
                    spawn_obs["actors_after_destroy"] = len(after)
                    spawn_obs["absent_after_cleanup"] = \
                        spawn_obs["spawned_path"] not in after
                valid_after, _ = validity(spawned)
                spawn_obs["valid_after_destroy"] = valid_after
                spawn_obs["enumeration_absence_is_vacuous"] = (
                    spawn_obs["visible_in_enumeration_after_spawn"] is not True)

                if valid_before is None or valid_after is None:
                    record("transient_spawn_destroy_reobserve", STATUS_UNAVAILABLE,
                           "no object-validity channel answered, and enumeration "
                           "absence is vacuous for a transient actor, so the "
                           "destruction could not be RE-OBSERVED by any channel "
                           "capable of reporting failure", spawn_obs)
                elif valid_before and not valid_after:
                    detail = ("transient spawn destroyed and the destruction "
                              "RE-OBSERVED via {} (valid True -> False)".format(
                                  vchannel))
                    if spawn_obs["enumeration_absence_is_vacuous"]:
                        detail += (". NOTE: the transient actor was never visible in "
                                   "get_all_level_actors(), so the "
                                   "enumeration-absence channel is VACUOUS here and "
                                   "proves nothing on its own")
                    record("transient_spawn_destroy_reobserve", STATUS_VERIFIED,
                           detail, spawn_obs)
                    owned_objects.append({
                        "object_path": spawn_obs["spawned_path"],
                        "object_class": "StaticMeshActor",
                        "transient": True,
                        "disposition": "destroyed_and_reobserved_absent",
                        "reobservation_channel": vchannel,
                    })
                elif not valid_before:
                    record("transient_spawn_destroy_reobserve", STATUS_FAILED,
                           "the spawned actor was already invalid BEFORE destroy, so "
                           "the spawn did not produce a live actor", spawn_obs)
                    owned_objects.append({
                        "object_path": spawn_obs["spawned_path"],
                        "object_class": "StaticMeshActor", "transient": True,
                        "disposition": "spawn_did_not_produce_a_live_actor",
                        "reobservation_channel": vchannel})
                else:
                    record("transient_spawn_destroy_reobserve", STATUS_FAILED,
                           "the actor is STILL VALID after destroy_actor returned "
                           "{} -- destruction did not happen".format(
                               spawn_obs["destroy_returned"]), spawn_obs)
                    owned_objects.append({
                        "object_path": spawn_obs["spawned_path"],
                        "object_class": "StaticMeshActor", "transient": True,
                        "disposition": "still_valid_after_destroy",
                        "reobservation_channel": vchannel})
                publish(dict(envelope(
                    "operation_owned_object", "transient_marker_000", "cleanup",
                    "spawn_destroy_reobserve",
                    source_api="EditorActorSubsystem.spawn_actor_from_class",
                    actor_object_path=spawn_obs["spawned_path"],
                    measured_fields=("valid_before_destroy",
                                     "valid_after_destroy")),
                    **{"observed": spawn_obs}),
                    spawn_obs["valid_after_destroy"] is False,
                    None if spawn_obs["valid_after_destroy"] is False
                    else "cleanup_unverified")

        # ---- D18 raw timing collection -------------------------------------- #
        # RAW ONLY. No median, no fit, no criterion is computed here -- the near
        # side derives all of it. forge_design_decisions.md:121-149.
        configs = d18_plan.get("configs") or [list(c) for c in D18_DEFAULT_CONFIGS]
        warmup = int(d18_plan.get("warmup", D18_DEFAULT_WARMUP))
        reps = int(d18_plan.get("reps", D18_DEFAULT_REPS))

        def collect_grid(radius, step):
            """ONE Python support-grid collection, timed end to end.

            This is the collector D18 is deciding about: per cell, one downward
            line trace plus one break_hit_result plus one raw record. Samples are
            emitted in canonical ROW-MAJOR order -- (i,j) < (i',j') iff i<i' or
            (i==i' and j<j').
            """
            k = grid_k_contract(radius, step)
            rows, errors = [], []
            t0 = time.perf_counter()
            for i in range(-k, k + 1):
                row = i + k
                for j in range(-k, k + 1):
                    col = j + k
                    sid = sample_id(row, col)
                    sx = center[0] + i * step
                    sy = center[1] + j * step
                    start = unreal.Vector(sx, sy, center[2] + D18_TRACE_UP_CM)
                    end = unreal.Vector(sx, sy, center[2] - D18_TRACE_DOWN_CM)
                    hit_flag, dist, impact_z = None, None, None
                    try:
                        res = unreal.SystemLibrary.line_trace_single(
                            world, start, end, channel, True, [], debug, True)
                    except Exception as exc:  # noqa: BLE001
                        if len(errors) < 5:
                            errors.append("{}: line_trace_single: {}".format(
                                sid, why(exc)))
                        rows.append([sid, None, None, None])
                        continue
                    hv, oh = unpack_out(res)
                    hit_flag = None if hv is None else (1 if hv else 0)
                    if oh is not None:
                        try:
                            parts = list(unreal.GameplayStatics.break_hit_result(oh))
                            if len(parts) >= 18:
                                dist = _finite(parts[3])
                                ip = xyz(parts[5])
                                impact_z = None if ip is None else ip[2]
                        except Exception as exc:  # noqa: BLE001
                            if len(errors) < 5:
                                errors.append("{}: break_hit_result: {}".format(
                                    sid, why(exc)))
                    rows.append([sid, hit_flag,
                                 None if dist is None else round(dist, 6),
                                 None if impact_z is None else round(impact_z, 6)])
            return time.perf_counter() - t0, rows, errors

        def time_interop_baseline(n):
            """N trivial REFLECTED calls -- the round-trip cost with no engine
            work behind it. This is the T_interop proxy, and it is a MODEL, not a
            decomposition; the near side is told so explicitly."""
            t0 = time.perf_counter()
            for _ in range(n):
                unreal.SystemLibrary.is_valid(world)
            return time.perf_counter() - t0

        def time_record_baseline(n, step):
            """N pure-Python coordinate computations + record constructions, with
            no engine call at all. This is the T_record term."""
            t0 = time.perf_counter()
            side = int(math.sqrt(n))
            for idx in range(n):
                row, col = divmod(idx, max(1, side))
                _row = [sample_id(row, col), center[0] + row * step,
                        center[1] + col * step, None]
            return time.perf_counter() - t0

        def time_native_grid(radius, step):
            """The C++ batch grid at the SAME (R, s). Cost side of criterion 6."""
            if not has_survey:
                return None
            try:
                ctr2 = unreal.Vector(center[0], center[1], center[2])
                t0 = time.perf_counter()
                unreal.SceneSurveyStatics.sample_survey_support(
                    world, ctr2, float(radius), float(step))
                return time.perf_counter() - t0
            except Exception as exc:  # noqa: BLE001
                note("native_grid_timing", "{} @R={} s={}".format(
                    why(exc), radius, step))
                return None

        d18_raw = {
            "collected": False,
            "reason": None,
            "warmup_count": warmup,
            "measurement_reps": reps,
            "trace_channel": channel_name,
            "anchor": center,
            "anchor_source": anchor_source,
            "grid_formula": "k = floor(R/s); N = (2k+1)^2",
            "sample_order": "row-major: (i,j) < (i',j') iff i<i' or (i==i' and j<j')",
            "clock": "time.perf_counter",
            "configs": [],
            "errors": [],
        }
        if channel is None or debug is None:
            d18_raw["reason"] = ("no trace channel / draw-debug enum is reflected, so "
                                 "the support grid could not be collected at all")
        elif world is None:
            d18_raw["reason"] = "no editor world; the grid has nowhere to trace"
        else:
            for cfg in configs:
                try:
                    radius, step = float(cfg[0]), float(cfg[1])
                except Exception as exc:  # noqa: BLE001
                    d18_raw["errors"].append("unusable config {!r}: {}".format(cfg, exc))
                    continue
                k_contract = grid_k_contract(radius, step)
                k_cpp = grid_k_cpp(radius, step)
                entry = {
                    "radius_cm": radius, "step_cm": step,
                    "k_contract": k_contract, "k_cpp": k_cpp,
                    "n_contract": grid_sample_count(k_contract),
                    "n_cpp": grid_sample_count(k_cpp),
                    "k_formulas_agree": k_contract == k_cpp,
                    "warmup_seconds": [], "reps": [],
                    "interop_baseline_seconds": None,
                    "record_baseline_seconds": None,
                    "native_grid_seconds": [],
                }
                n_expected = entry["n_contract"]
                for _ in range(max(0, warmup)):
                    elapsed, _rows, errs = collect_grid(radius, step)
                    entry["warmup_seconds"].append(elapsed)
                    d18_raw["errors"].extend(errs)
                for rep_index in range(max(1, reps)):
                    elapsed, rows, errs = collect_grid(radius, step)
                    d18_raw["errors"].extend(errs)
                    ids = [r[0] for r in rows]
                    entry["reps"].append({
                        "rep_index": rep_index,
                        "elapsed_seconds": elapsed,
                        "sample_count": len(rows),
                        "expected_sample_count": n_expected,
                        "missing_record_count": max(0, (n_expected or 0) - len(rows)),
                        "success_count": sum(1 for r in rows if r[1] is not None),
                        "id_sequence_sha256": "sha256:" + hashlib.sha256(
                            "\n".join(ids).encode("utf-8")).hexdigest(),
                        "ids_already_sorted": ids == sorted(ids),
                        "rows": rows,
                    })
                try:
                    entry["interop_baseline_seconds"] = time_interop_baseline(
                        n_expected or 0)
                    entry["record_baseline_seconds"] = time_record_baseline(
                        n_expected or 0, step)
                except Exception as exc:  # noqa: BLE001
                    d18_raw["errors"].append("baseline timing failed: " + why(exc))
                for _ in range(max(1, reps)):
                    native = time_native_grid(radius, step)
                    if native is not None:
                        entry["native_grid_seconds"].append(native)
                d18_raw["configs"].append(entry)
            d18_raw["collected"] = bool(d18_raw["configs"])
            if not d18_raw["collected"]:
                d18_raw["reason"] = "no grid configuration produced a measurement"
        doc["d18_raw"] = d18_raw

        distinct_n = sorted({c["n_contract"] for c in d18_raw["configs"]
                             if c.get("n_contract")})
        d18_obs = {
            "configs_measured": len(d18_raw["configs"]),
            "warmup_count": warmup,
            "measurement_reps": reps,
            "total_measured_reps": sum(len(c["reps"]) for c in d18_raw["configs"]),
            "distinct_sample_counts": len(distinct_n),
            "sample_counts": distinct_n,
            "collector_errors": d18_raw["errors"][:10],
        }
        if not d18_raw["collected"]:
            record("d18_grid_measurement", STATUS_UNAVAILABLE,
                   d18_raw["reason"] or "no grid measurement was collected", d18_obs)
        else:
            record("d18_grid_measurement", STATUS_VERIFIED,
                   "collected {} grid configuration(s) x {} warm-up + {} measured "
                   "repetition(s) over N in {}".format(
                       len(d18_raw["configs"]), warmup, reps, distinct_n), d18_obs)

        # ---- post-mutation safety snapshot ------------------------------------ #
        maps_post, _, _ = dirty("get_dirty_map_packages")
        content_post, _, _ = dirty("get_dirty_content_packages")
        doc["safety"]["dirty_map_packages_post"] = maps_post
        doc["safety"]["dirty_content_packages_post"] = content_post
        if maps_post is not None and world_package:
            doc["safety"]["target_map_dirty_after"] = world_package in maps_post

        # ---- publication: the structured raw-evidence bundle -------------------- #
        # Shaped as the real bundle is: {record_type: {record_ident: record}}.
        bundle_body = {}
        for rec in raw_records.values():
            bundle_body.setdefault(rec["record_type"], {})[rec["record_ident"]] = rec
        bundle = {
            "bundle_schema": RAW_BUNDLE_SCHEMA,
            "record_schema": RAW_RECORD_SCHEMA,
            "operation_id": operation_id,
            "request_hash": request_hash,
            "request_hash_algorithm": "sha256",
            "record_envelope_fields": list(RECORD_ENVELOPE_FIELDS),
            "records": {kind: {ident: bundle_body[kind][ident]
                               for ident in sorted(bundle_body[kind])}
                        for kind in sorted(bundle_body)},
        }
        doc["raw_evidence"] = bundle

        missing_envelope = []
        ordered = True
        for kind in bundle["records"]:
            idents = list(bundle["records"][kind])
            if idents != sorted(idents):
                ordered = False
            for ident, rec in bundle["records"][kind].items():
                gaps = [f for f in RECORD_ENVELOPE_FIELDS if f not in rec]
                if gaps:
                    missing_envelope.append("{}/{}: {}".format(
                        kind, ident, ",".join(gaps)))
        pub_obs = {
            "bundle_schema": bundle["bundle_schema"],
            "record_schema": bundle["record_schema"],
            "record_count": len(raw_records),
            "record_kinds": sorted(bundle["records"]),
            "envelope_complete": not missing_envelope,
            "missing_envelope_fields": missing_envelope[:10],
            "canonically_ordered": ordered,
        }
        if not raw_records:
            record("raw_evidence_publication", STATUS_FAILED,
                   "no raw record was published; the structured evidence channel "
                   "produced nothing", pub_obs)
        elif missing_envelope:
            record("raw_evidence_publication", STATUS_FAILED,
                   "published records are missing envelope fields: "
                   + "; ".join(missing_envelope[:5]), pub_obs)
        elif not ordered:
            record("raw_evidence_publication", STATUS_FAILED,
                   "published record ids are not in canonical order", pub_obs)
        else:
            record("raw_evidence_publication", STATUS_VERIFIED,
                   "published {} raw record(s) across {} kind(s), every one "
                   "carrying the full {}-field envelope".format(
                       len(raw_records), len(bundle["records"]),
                       len(RECORD_ENVELOPE_FIELDS)), pub_obs)

        # ---- publication: the operation manifest --------------------------------- #
        manifest = {
            "manifest_schema": MANIFEST_SCHEMA,
            "operation_id": operation_id,
            "request_hash": request_hash,
            "map_requested": map_path,
            "world_identity": doc["observed_world_package"],
            "engine_version": doc["observed_engine_version"],
            "far_side_pid": doc["far_side_pid"],
            "owned_objects": owned_objects,
            "packages_saved": doc["safety"]["packages_saved"],
            "permanent_actors_authored": doc["safety"]["permanent_actors_authored"],
            "raw_evidence_digest": None,
            "raw_record_count": len(raw_records),
        }
        try:
            manifest["raw_evidence_digest"] = digest(bundle)
        except Exception as exc:  # noqa: BLE001
            note("manifest_digest", "could not digest the raw bundle: " + why(exc))
        doc["operation_manifest"] = manifest

        man_obs = dict(manifest)
        # digest_matches is filled by the NEAR side, which re-computes the digest
        # from the transported bundle. The far side must not grade its own digest.
        man_obs["digest_recomputed"] = None
        man_obs["digest_matches"] = None
        if manifest["raw_evidence_digest"] is None:
            record("operation_manifest_publication", STATUS_FAILED,
                   "the manifest could not carry a raw-evidence digest", man_obs)
        else:
            record("operation_manifest_publication", STATUS_VERIFIED,
                   "published an operation manifest declaring {} owned object(s), "
                   "0 saved packages, and a digest over the raw bundle for the near "
                   "side to RE-COMPUTE".format(len(owned_objects)), man_obs)

    except Exception as exc:  # noqa: BLE001
        doc["error"] = why(exc)
        doc["traceback"] = traceback.format_exc()

    write()


def _safe_path(obj):
    try:
        return obj.get_path_name()
    except Exception:  # noqa: BLE001
        return None

# =========================================================================== #
# NEAR SIDE -- D18 ANALYSIS
# --------------------------------------------------------------------------- #
# Everything statistical happens HERE, on transported raw timings, so it can be
# unit-tested without an editor and so the far side never grades itself.
# =========================================================================== #
def _rows_equivalent(a_rows, b_rows):
    """(equivalent, reason). Identical ids in identical order, numerically equal
    within the declared tolerance."""
    if len(a_rows) != len(b_rows):
        return False, "sample counts differ: {} vs {}".format(
            len(a_rows), len(b_rows))
    for idx, (a, b) in enumerate(zip(a_rows, b_rows)):
        if a[0] != b[0]:
            return False, "sample {} id differs: {!r} vs {!r}".format(idx, a[0], b[0])
        if a[1] != b[1]:
            return False, "sample {} hit differs: {!r} vs {!r}".format(
                a[0], a[1], b[1])
        for field, pos in (("distance", 2), ("impact_z", 3)):
            av, bv = a[pos], b[pos]
            if av is None and bv is None:
                continue
            if av is None or bv is None:
                return False, "sample {} {} is None in one repeat only".format(
                    a[0], field)
            if abs(av - bv) > max(D18_EQUIV_ABS_TOL,
                                  D18_EQUIV_REL_TOL * max(abs(av), abs(bv))):
                return False, "sample {} {} differs: {!r} vs {!r}".format(
                    a[0], field, av, bv)
    return True, None


def analyze_d18(d18_raw, probes, safety):
    """Derive every D18 statistic, the fit, and all six criterion verdicts.

    Pure: takes transported raw observations, returns a document. Never reads the
    filesystem and never touches unreal.
    """
    out = {
        "collected": bool((d18_raw or {}).get("collected")),
        "reason": (d18_raw or {}).get("reason"),
        "clock": (d18_raw or {}).get("clock"),
        "grid_formula": (d18_raw or {}).get("grid_formula"),
        "sample_order": (d18_raw or {}).get("sample_order"),
        "warmup_count": (d18_raw or {}).get("warmup_count"),
        "measurement_reps": (d18_raw or {}).get("measurement_reps"),
        "declared_thresholds": {
            "interop_dominance_ratio": D18_INTEROP_DOMINANCE_RATIO,
            "budget_seconds": D18_BUDGET_SECONDS,
            "budget_radius_cm": D18_BUDGET_RADIUS_CM,
            "budget_step_cm": D18_BUDGET_STEP_CM,
            "batch_material_ratio": D18_BATCH_MATERIAL_RATIO,
            "equivalence_abs_tol": D18_EQUIV_ABS_TOL,
            "equivalence_rel_tol": D18_EQUIV_REL_TOL,
        },
        "per_config": [],
        "fit": None,
        "fit_basis": None,
        "ordering_stability": {"all_configs_stable": None, "unstable": []},
        "record_completeness": {"all_configs_complete": None, "incomplete": []},
        "interop_attribution": None,
        "verdict_semantics": dict(D18_VERDICT_SEMANTICS),
        "criteria": new_d18_criteria_table(
            "the D18 analysis did not reach this criterion"),
        "collector_errors": list((d18_raw or {}).get("errors") or [])[:10],
    }

    configs = list((d18_raw or {}).get("configs") or [])
    fit_points = []
    unstable, incomplete = [], []

    for cfg in configs:
        reps = list(cfg.get("reps") or [])
        times = [r.get("elapsed_seconds") for r in reps]
        rows_by_rep = [list(r.get("rows") or []) for r in reps]
        hashes = [r.get("id_sequence_sha256") for r in reps]

        stable = len(set(h for h in hashes if h)) <= 1 and all(
            r.get("ids_already_sorted") is True for r in reps)
        order_detail = None
        if len(set(h for h in hashes if h)) > 1:
            order_detail = "the id sequence hash changed across repetitions: {}".format(
                sorted(set(h for h in hashes if h)))
        elif not all(r.get("ids_already_sorted") is True for r in reps):
            order_detail = ("the emitted ids are not in canonical row-major order "
                            "within at least one repetition")

        equivalent, equiv_detail = True, None
        for idx in range(1, len(rows_by_rep)):
            equivalent, equiv_detail = _rows_equivalent(rows_by_rep[0], rows_by_rep[idx])
            if not equivalent:
                equiv_detail = "repeat {} vs repeat 0: {}".format(idx, equiv_detail)
                break
        if len(rows_by_rep) < 2:
            equivalent, equiv_detail = None, \
                "fewer than two repetitions; equivalence was not tested"

        missing = sum(int(r.get("missing_record_count") or 0) for r in reps)
        successes = [int(r.get("success_count") or 0) for r in reps]
        counts = [int(r.get("sample_count") or 0) for r in reps]

        n_contract = cfg.get("n_contract")
        interop_base = cfg.get("interop_baseline_seconds")
        record_base = cfg.get("record_baseline_seconds")
        med = median(times)
        native_med = median(cfg.get("native_grid_seconds") or [])

        # T_interop is MODELLED, not decomposed: the grid makes two reflected
        # calls per sample (line_trace_single + break_hit_result), so the
        # per-call baseline is scaled by two. Stated in the report so nobody
        # reads it as a measured split.
        interop_est = None if interop_base is None else interop_base * 2.0
        trace_est = None
        if med is not None and interop_est is not None and record_base is not None:
            trace_est = med - interop_est - record_base

        entry = {
            "radius_cm": cfg.get("radius_cm"),
            "step_cm": cfg.get("step_cm"),
            "k_contract": cfg.get("k_contract"),
            "k_cpp": cfg.get("k_cpp"),
            "k_formulas_agree": cfg.get("k_formulas_agree"),
            "n_contract": n_contract,
            "n_cpp": cfg.get("n_cpp"),
            "warmup_count": len(cfg.get("warmup_seconds") or []),
            "warmup_seconds": list(cfg.get("warmup_seconds") or []),
            "measurement_reps": len(reps),
            "median_seconds": med,
            "p95_seconds": percentile(times, 95),
            "median_absolute_deviation_seconds": median_absolute_deviation(times),
            "min_seconds": min(times) if times else None,
            "max_seconds": max(times) if times else None,
            "sample_count": counts[0] if counts else None,
            "sample_counts_per_rep": counts,
            "success_count": successes[0] if successes else None,
            "success_counts_per_rep": successes,
            "missing_record_count": missing,
            "ordering_stable": stable,
            "ordering_detail": order_detail,
            "id_sequence_sha256": hashes[0] if hashes else None,
            "records_equivalent": equivalent,
            "records_equivalence_detail": equiv_detail,
            "interop_baseline_seconds": interop_base,
            "record_baseline_seconds": record_base,
            "interop_estimate_seconds": interop_est,
            "trace_estimate_seconds": trace_est,
            "native_grid_median_seconds": native_med,
            "native_speedup_ratio": (med / native_med)
            if (med and native_med and native_med > 0) else None,
        }
        out["per_config"].append(entry)

        if not stable or equivalent is False:
            unstable.append({"n": n_contract, "ordering_detail": order_detail,
                             "equivalence_detail": equiv_detail})
        if missing or (n_contract and counts and any(c != n_contract for c in counts)):
            incomplete.append({"n_expected": n_contract, "counts": counts,
                               "missing": missing})
        for t in times:
            if n_contract and isinstance(t, (int, float)):
                fit_points.append((float(n_contract), float(t)))

    out["ordering_stability"] = {
        "all_configs_stable": (not unstable) if configs else None,
        "unstable": unstable,
    }
    out["record_completeness"] = {
        "all_configs_complete": (not incomplete) if configs else None,
        "incomplete": incomplete,
    }
    out["fit"] = fit_linear([p[0] for p in fit_points], [p[1] for p in fit_points])
    out["fit_basis"] = ("every measured repetition of every configuration is one "
                        "point; warm-up repetitions are EXCLUDED. alpha is the "
                        "fixed per-operation cost, beta the marginal cost per "
                        "sample.")
    out["fit"]["alpha_seconds"] = out["fit"].get("alpha")
    out["fit"]["beta_seconds_per_sample"] = out["fit"].get("beta")

    # ---- criterion 1: can Python expose the data at all? ------------------- #
    exposure_groups = ("plugin", "world", "actor", "bounds", "geometry", "packages")
    exposure = {n: (probes.get(n) or {}).get("status")
                for n in PROBE_NAMES if PROBE_GROUP[n] in exposure_groups}
    bad = sorted(n for n, s in exposure.items()
                 if s in (STATUS_UNAVAILABLE, STATUS_FAILED))
    unreached = sorted(n for n, s in exposure.items() if s == STATUS_ASSUMED)
    if bad:
        _set_criterion(out, "c1_python_cannot_expose_data", D18_PASS,
                       "{} data-exposure probe(s) did not return usable data: {}"
                       .format(len(bad), ", ".join(bad)), {"failing_probes": bad})
    elif unreached:
        _set_criterion(out, "c1_python_cannot_expose_data", D18_NOT_MEASURED,
                       "{} data-exposure probe(s) were never reached, so reliability "
                       "was not established either way: {}".format(
                           len(unreached), ", ".join(unreached)),
                       {"unreached_probes": unreached})
    elif exposure:
        _set_criterion(out, "c1_python_cannot_expose_data", D18_FAIL,
                       "all {} data-exposure probes returned usable trace, "
                       "collision, package and component data".format(len(exposure)),
                       {"verified_probes": sorted(exposure)})

    # ---- criterion 2: T_interop >> T_trace? -------------------------------- #
    usable = [c for c in out["per_config"]
              if c["trace_estimate_seconds"] is not None
              and c["interop_estimate_seconds"] is not None]
    largest = max(usable, key=lambda c: c["n_contract"] or 0) if usable else None
    attribution = {
        "model": "T_grid(N) = T_record(N) + T_interop(N) + T_trace(N); T_interop is "
                 "MODELLED as 2 x the measured per-call reflected-call baseline "
                 "(the grid makes two reflected calls per sample: "
                 "line_trace_single and break_hit_result). This is an "
                 "ATTRIBUTION MODEL, not a measured decomposition.",
        "basis_config_n": largest["n_contract"] if largest else None,
        "interop_estimate_seconds": largest["interop_estimate_seconds"] if largest else None,
        "trace_estimate_seconds": largest["trace_estimate_seconds"] if largest else None,
        "ratio": None,
    }
    if largest is None:
        _set_criterion(out, "c2_interop_dominates_trace", D18_NOT_MEASURED,
                       "no configuration produced both an interop baseline and a "
                       "grid median, so the two terms could not be separated", None)
    elif largest["trace_estimate_seconds"] <= 0:
        _set_criterion(out, "c2_interop_dominates_trace", D18_NOT_MEASURED,
                       "the attribution model left a non-positive trace estimate "
                       "({:.6g}s at N={}), which means the model does not separate "
                       "the terms at this scale -- reporting a ratio would be "
                       "arithmetic, not measurement".format(
                           largest["trace_estimate_seconds"], largest["n_contract"]),
                       attribution)
    else:
        ratio = largest["interop_estimate_seconds"] / largest["trace_estimate_seconds"]
        attribution["ratio"] = ratio
        verdict = D18_PASS if ratio >= D18_INTEROP_DOMINANCE_RATIO else D18_FAIL
        _set_criterion(out, "c2_interop_dominates_trace", verdict,
                       "at N={} the modelled T_interop/T_trace ratio is {:.3f} "
                       "against the declared dominance threshold of {}".format(
                           largest["n_contract"], ratio,
                           D18_INTEROP_DOMINANCE_RATIO), attribution)
    out["interop_attribution"] = attribution

    # ---- criterion 3: does the declared maximum (R, s) miss the budget? ----- #
    n_budget = grid_sample_count(grid_k_contract(D18_BUDGET_RADIUS_CM,
                                                 D18_BUDGET_STEP_CM))
    fit = out["fit"]
    if not fit.get("fitted"):
        _set_criterion(out, "c3_max_grid_misses_budget", D18_NOT_MEASURED,
                       "no fit was produced ({}), so T at the declared maximum "
                       "cannot be predicted".format(fit.get("reason")),
                       {"n_budget": n_budget})
    else:
        predicted = fit["alpha"] + fit["beta"] * n_budget
        verdict = D18_PASS if predicted > D18_BUDGET_SECONDS else D18_FAIL
        _set_criterion(out, "c3_max_grid_misses_budget", verdict,
                       "the fit predicts T({}) = {:.4f}s at the declared maximum "
                       "R={}cm s={}cm against a declared budget of {}s. This is an "
                       "EXTRAPOLATION beyond the measured range (max measured N={})."
                       .format(n_budget, predicted, D18_BUDGET_RADIUS_CM,
                               D18_BUDGET_STEP_CM, D18_BUDGET_SECONDS,
                               max((c["n_contract"] or 0)
                                   for c in out["per_config"]) if out["per_config"]
                               else None),
                       {"n_budget": n_budget, "predicted_seconds": predicted,
                        "budget_seconds": D18_BUDGET_SECONDS,
                        "extrapolated_beyond_measured_range": True})

    # ---- criterion 4: nondeterministic ordering or incomplete records? ------ #
    if not configs:
        _set_criterion(out, "c4_nondeterministic_or_incomplete", D18_NOT_MEASURED,
                       "no configuration was collected, so ordering and completeness "
                       "were never observed", None)
    elif unstable or incomplete:
        _set_criterion(out, "c4_nondeterministic_or_incomplete", D18_PASS,
                       "{} configuration(s) showed unstable ordering and {} showed "
                       "incomplete records".format(len(unstable), len(incomplete)),
                       {"unstable": unstable, "incomplete": incomplete})
    else:
        _set_criterion(out, "c4_nondeterministic_or_incomplete", D18_FAIL,
                       "across {} configuration(s), every repetition produced an "
                       "identical canonical id sequence and a complete record set, "
                       "with per-sample values equivalent within the declared "
                       "tolerance".format(len(configs)),
                       {"configs": len(configs),
                        "reps_each": out["measurement_reps"]})

    # ---- criterion 5: does cleanup require native scoped ownership? --------- #
    spawn_status = (probes.get("transient_spawn_destroy_reobserve") or {}).get("status")
    safety = safety or {}
    maps_pre = safety.get("dirty_map_packages_pre")
    maps_post = safety.get("dirty_map_packages_post")
    content_pre = safety.get("dirty_content_packages_pre")
    content_post = safety.get("dirty_content_packages_post")
    dirt_readable = None not in (maps_pre, maps_post, content_pre, content_post)
    dirt_unchanged = dirt_readable and maps_pre == maps_post \
        and content_pre == content_post
    cleanup_evidence = {
        "spawn_probe_status": spawn_status,
        "dirty_maps_pre": maps_pre, "dirty_maps_post": maps_post,
        "dirty_content_pre": content_pre, "dirty_content_post": content_post,
        "target_map_dirty_after": safety.get("target_map_dirty_after"),
    }
    if spawn_status == STATUS_ASSUMED:
        _set_criterion(out, "c5_cleanup_needs_native_ownership", D18_NOT_MEASURED,
                       "the operation-owned spawn/destroy probe was never reached, "
                       "so Python-side cleanup correctness was not observed",
                       cleanup_evidence)
    elif spawn_status != STATUS_VERIFIED:
        _set_criterion(out, "c5_cleanup_needs_native_ownership", D18_PASS,
                       "Python-side cleanup could not be re-observed as correct "
                       "(spawn/destroy probe is {})".format(spawn_status),
                       cleanup_evidence)
    elif not dirt_readable:
        _set_criterion(out, "c5_cleanup_needs_native_ownership", D18_NOT_MEASURED,
                       "the destruction was re-observed, but the dirty-package sets "
                       "could not be read on both sides of the mutation, so "
                       "world-lifetime cleanliness is unestablished", cleanup_evidence)
    elif not dirt_unchanged:
        _set_criterion(out, "c5_cleanup_needs_native_ownership", D18_PASS,
                       "the operation left the dirty-package sets changed, so "
                       "Python-side scoped cleanup did not fully hold",
                       cleanup_evidence)
    else:
        _set_criterion(out, "c5_cleanup_needs_native_ownership", D18_FAIL,
                       "the operation-owned object was destroyed and RE-OBSERVED "
                       "absent through a non-vacuous channel, and both dirty-package "
                       "sets are byte-identical across the mutation",
                       cleanup_evidence)

    # ---- criterion 6: is a native batch trace materially cheaper? ----------- #
    natives = [c for c in out["per_config"]
               if c.get("native_grid_median_seconds") is not None]
    if not natives:
        _set_criterion(out, "c6_native_batch_trace_cheaper", D18_NOT_MEASURED,
                       "no native batch grid was timed, so neither the cost side nor "
                       "the semantics side of this criterion was observed", None)
    else:
        ratios = [c["native_speedup_ratio"] for c in natives
                  if c.get("native_speedup_ratio")]
        _set_criterion(
            out, "c6_native_batch_trace_cheaper", D18_UNSUPPORTED,
            "the COST side is measured -- the native USceneSurveyStatics::"
            "SampleSurveySupport grid ran {:.3g}x faster than the Python collector "
            "at the largest common configuration -- but the criterion also requires "
            "'preserving identical semantics', and that CANNOT be established by "
            "this harness at any (R, s): SampleSurveySupport returns only an int32 "
            "total (SceneSurvey.h:47-49) and emits no per-sample raw records, so "
            "there is nothing to compare the Python per-sample records against. A "
            "C++ prototype that emits raw observations is the instrument this "
            "criterion needs.".format(max(ratios) if ratios else float("nan")),
            {"native_speedup_ratios": ratios,
             "blocked_on": "a native collector that emits per-sample raw records",
             "cost_side": "measured", "semantics_side": "unmeasurable_here"})

    return out


def _set_criterion(analysis, criterion_id, verdict, reason, evidence):
    if criterion_id not in analysis["criteria"]:
        raise KeyError("unknown D18 criterion " + repr(criterion_id))
    if verdict not in D18_VERDICTS:
        raise ValueError("illegal D18 verdict " + repr(verdict))
    analysis["criteria"][criterion_id]["verdict"] = verdict
    analysis["criteria"][criterion_id]["reason"] = reason
    analysis["criteria"][criterion_id]["evidence"] = evidence

# =========================================================================== #
# NEAR SIDE -- classification, liveness, gate
# =========================================================================== #
class GuardError(RuntimeError):
    """The project guard refused the run."""


def classify(far_doc, launch_detail):
    """Derive the probe table from far-side observations, or from their absence.

    Three things happen here that the far side cannot do for itself:
      1. a status outside the vocabulary becomes runtime_failed;
      2. a probe the far side never mentioned stays still_assumed;
      3. every runtime_verified claim is RE-DERIVED from the transported
         observation, and downgraded to runtime_failed when the observation does
         not support it. A forged status therefore buys nothing.
    """
    if far_doc is None:
        return new_probe_table(STATUS_UNAVAILABLE, launch_detail)
    probes = new_probe_table(
        STATUS_ASSUMED, "the far side produced no record for this probe")
    reported = (far_doc.get("probes") or {})
    if not isinstance(reported, dict):
        return new_probe_table(
            STATUS_FAILED, "the far side's probe table is not an object")
    for name, rec in reported.items():
        if name not in probes:
            continue  # an unknown probe name grants nothing
        if not isinstance(rec, dict):
            probes[name]["status"] = STATUS_FAILED
            probes[name]["detail"] = "the far side's record is not an object"
            continue
        status = rec.get("status")
        if status not in ALL_STATUSES:
            probes[name]["status"] = STATUS_FAILED
            probes[name]["detail"] = \
                "far side reported an illegal status {!r}".format(status)
            continue
        probes[name]["status"] = status
        probes[name]["detail"] = rec.get("detail")
        probes[name]["observed"] = rec.get("observed")

    for name in PROBE_NAMES:
        if probes[name]["status"] != STATUS_VERIFIED:
            continue
        try:
            complaint = EVIDENCE_VALIDATORS[name](probes[name]["observed"])
        except Exception as exc:  # noqa: BLE001
            complaint = "the observation could not be re-derived: {}: {}".format(
                type(exc).__name__, exc)
        if complaint:
            probes[name]["status"] = STATUS_FAILED
            probes[name]["rederivation"] = "rejected"
            probes[name]["detail"] = (
                "the far side claimed {} but the near side's independent "
                "re-derivation REJECTED it: {}. Original detail: {}".format(
                    STATUS_VERIFIED, complaint, probes[name].get("detail")))
        else:
            probes[name]["rederivation"] = "accepted"
    return probes


def verify_manifest_digest(far_doc, probes):
    """RE-COMPUTE the raw-bundle digest and fold the answer into the manifest probe.

    The far side declares a digest over the bundle it published. The near side
    recomputes it over the bundle it actually RECEIVED. A mismatch means the
    thing that was transported is not the thing that was measured, and no
    manifest claim survives it.
    """
    rec = probes.get("operation_manifest_publication")
    if rec is None:
        return
    observed = rec.get("observed")
    if not isinstance(observed, dict):
        return
    bundle = (far_doc or {}).get("raw_evidence")
    recomputed = None
    if bundle is not None:
        try:
            recomputed = digest(bundle)
        except Exception as exc:  # noqa: BLE001
            recomputed = "<undigestable: {}: {}>".format(type(exc).__name__, exc)
    observed["digest_recomputed"] = recomputed
    observed["digest_matches"] = (
        recomputed is not None and recomputed == observed.get("raw_evidence_digest"))
    if rec.get("status") == STATUS_VERIFIED:
        complaint = EVIDENCE_VALIDATORS["operation_manifest_publication"](observed)
        if complaint:
            rec["status"] = STATUS_FAILED
            rec["rederivation"] = "rejected"
            rec["detail"] = ("the far side claimed {} but the near side's "
                             "independent re-derivation REJECTED it: {}".format(
                                 STATUS_VERIFIED, complaint))


_ENGINE_VERSION_HINT = "a live editor returns something like '5.8.0-...+++UE5+Release-5.8'"


def verify_liveness(report, far_doc, expected_nonce):
    """Did a live Unreal process actually run, and is this report about THIS run?

    LIVENESS THREAT MODEL -- read before trusting the word "verified" here.
    What this DOES defend against:
      * a stale report being graded as current. The nonce is fresh per run, so a
        report from a previous run cannot satisfy the challenge for this one.
        This repo has been burned by exactly that -- a gate graded an eight-day-old
        artifact, and mtime is not a freshness signal here (an artifact was
        observed moving 07-19 -> 07-27 with identical bytes).
      * a near-side-only path (dry run, no editor, failed boot) producing an
        artifact shaped like a real result. Engine version, far-side pid and world
        identity simply do not exist on those paths.
      * a boot that produced no observations being graded as a run.
    What it does NOT defend against: a modified near side. The near side computes
    the gate, so it can always lie about it; this check is about distinguishing
    RUNS, not about defending against a hostile local checkout.
    """
    live = {
        "verified": False,
        "reason": None,
        "nonce": expected_nonce,
        "nonce_seen_by_far_side": (far_doc or {}).get("nonce_seen"),
        "near_side_pid": os.getpid(),
        "far_side_pid": (far_doc or {}).get("far_side_pid"),
        "distinct_process": None,
        "engine_version_plausible": None,
        "challenge_expected": None,
        "challenge_reported": (far_doc or {}).get("liveness_response"),
        "challenge_matches": None,
    }
    if far_doc is None:
        live["reason"] = ("no far-side observations exist, so no live Unreal process "
                          "was observed. This report is a NEAR-SIDE artefact.")
        return live
    if not far_doc.get("far_side_ran"):
        live["reason"] = "the far side did not report that it ran"
        return live

    engine = report.get("observed_engine_version")
    plausible = isinstance(engine, str) and any(ch.isdigit() for ch in engine) \
        and "." in engine
    live["engine_version_plausible"] = plausible

    far_pid = live["far_side_pid"]
    live["distinct_process"] = (
        isinstance(far_pid, int) and not isinstance(far_pid, bool)
        and far_pid != live["near_side_pid"])

    expected = liveness_response(
        expected_nonce, engine, report.get("observed_uproject"), far_pid,
        far_doc.get("observed_world_package"))
    live["challenge_expected"] = expected
    live["challenge_matches"] = (live["challenge_reported"] == expected)

    if live["nonce_seen_by_far_side"] != expected_nonce:
        live["reason"] = ("the far side saw nonce {!r} but this run issued {!r}; the "
                          "observations belong to a DIFFERENT run".format(
                              live["nonce_seen_by_far_side"], expected_nonce))
    elif not plausible:
        live["reason"] = ("no plausible engine version was observed in-process "
                          "({!r}); {}".format(engine, _ENGINE_VERSION_HINT))
    elif not live["distinct_process"]:
        live["reason"] = ("the far side reported pid {!r}, which is not a distinct "
                          "live process from this one ({})".format(
                              far_pid, live["near_side_pid"]))
    elif not live["challenge_matches"]:
        live["reason"] = ("the liveness challenge does not recompute: expected {} but "
                          "the far side reported {}".format(
                              expected, live["challenge_reported"]))
    else:
        live["verified"] = True
        live["reason"] = ("a distinct live process (pid {}) reported engine {!r} and "
                          "answered this run's fresh liveness challenge".format(
                              far_pid, engine))
    return live


def evaluate_gate(report):
    """Compute the gate from a report document. PURE -- returns, never mutates.

    Returns (green, reason, tally, unmet, integrity). Every condition is listed
    in `integrity` whether it held or not, so a reader never has to infer which
    checks ran.
    """
    probes = report.get("probes")
    if not isinstance(probes, dict):
        probes = {}

    missing_probe_keys = [n for n in PROBE_NAMES if n not in probes
                          or not isinstance(probes.get(n), dict)
                          or "status" not in probes[n]]

    tally = {status: 0 for status in ALL_STATUSES}
    tally["missing"] = len(missing_probe_keys)
    for name in PROBE_NAMES:
        if name in missing_probe_keys:
            continue
        status = probes[name].get("status")
        if status in tally:
            tally[status] += 1
        else:
            tally["missing"] += 1

    unmet = [n for n in REQUIRED_PROBES
             if n in missing_probe_keys
             or probes.get(n, {}).get("status") != STATUS_VERIFIED]

    def group_ok(names):
        return all(n not in missing_probe_keys
                   and probes.get(n, {}).get("status") == STATUS_VERIFIED
                   for n in names)

    criteria = ((report.get("d18") or {}).get("criteria") or {})
    missing_criteria = [c for c in D18_CRITERION_IDS if c not in criteria]
    bad_criteria = [c for c, rec in criteria.items()
                    if not isinstance(rec, dict)
                    or rec.get("verdict") not in D18_VERDICTS]

    integrity = {
        "probe_table_complete": not missing_probe_keys,
        "missing_probe_keys": missing_probe_keys,
        "all_required_probes_verified": not unmet,
        "group_coverage": {g: group_ok([n for n in PROBE_NAMES
                                        if PROBE_GROUP[n] == g])
                           for g in PROBE_GROUPS},
        "geometry_surface_executed": group_ok(GEOMETRY_PROBES),
        "plugin_surface_executed": group_ok(PLUGIN_PROBES),
        "publication_surface_executed": group_ok(PUBLICATION_PROBES),
        "report_kind_is_live": report.get("report_kind") == KIND_LIVE,
        "liveness_verified": bool((report.get("liveness") or {}).get("verified")),
        "d18_criteria_complete": not missing_criteria and not bad_criteria,
        "missing_d18_criteria": missing_criteria,
        "malformed_d18_criteria": sorted(bad_criteria),
        "generated_at_present": bool(report.get("generated_at")),
        "stayed_read_only": (report.get("safety") or {}).get(
            "target_map_dirty_after") is not True,
    }

    # ORDER MATTERS: the first failing condition is the one reported, and the
    # structural ones come first so "the geometry surface was never executed" can
    # never be masked by a later, softer complaint.
    checks = (
        ("probe_table_complete",
         "the probe table is missing {} required key(s): {}. A missing probe is "
         "NOT a pass.".format(len(missing_probe_keys), ", ".join(missing_probe_keys))),
        ("geometry_surface_executed",
         "the geometry surface was not executed: {} of {} geometry probes are not "
         "{}. This gate cannot go green with trace/overlap unexercised.".format(
             sum(1 for n in GEOMETRY_PROBES
                 if probes.get(n, {}).get("status") != STATUS_VERIFIED),
             len(GEOMETRY_PROBES), STATUS_VERIFIED)),
        ("plugin_surface_executed",
         "no WorldForge plugin-owned function was proven to execute; importing "
         "`unreal` does not prove the plugin loaded"),
        ("publication_surface_executed",
         "the structured raw-evidence bundle and/or the operation manifest was not "
         "published and re-derived"),
        ("all_required_probes_verified",
         "{} required symbol(s) are not {}: {}. still_assumed is NOT a pass.".format(
             len(unmet), STATUS_VERIFIED, ", ".join(unmet))),
        ("report_kind_is_live",
         "this report was produced by {!r}, not by a live editor run".format(
             report.get("report_kind"))),
        ("liveness_verified",
         "no live Unreal process was proven to have produced these observations: "
         "{}".format((report.get("liveness") or {}).get("reason"))),
        ("d18_criteria_complete",
         "the D18 criteria table is incomplete (missing {}; malformed {}). Every "
         "criterion must carry one of {}.".format(
             missing_criteria, sorted(bad_criteria), list(D18_VERDICTS))),
        ("generated_at_present",
         "the report carries no generated_at, so it cannot be distinguished from a "
         "stale artifact"),
        ("stayed_read_only",
         "the target map was left DIRTY, so the run was not read-only"),
    )
    for key, complaint in checks:
        if not integrity[key]:
            return False, "GATE RED -- " + complaint, tally, unmet, integrity

    return (True,
            "every required symbol was executed in a live editor, the geometry and "
            "plugin surfaces were exercised, the evidence was re-derived "
            "independently, and all {} D18 criteria are answered".format(
                len(D18_CRITERION_IDS)),
            tally, unmet, integrity)

def _resolve_uproject():
    """Return THIS repo's .uproject, or raise. Not overridable, by construction.

    There is deliberately no --project flag and no environment override: a knob
    that can point this harness at another project is a knob that can boot the
    caller's checkout, and booting the wrong project would produce runtime
    evidence attributed to the wrong tree.
    """
    resolved = EXPECTED_UPROJECT.resolve() if EXPECTED_UPROJECT.exists() \
        else EXPECTED_UPROJECT
    if resolved != EXPECTED_UPROJECT.resolve(strict=False):
        raise GuardError("resolved project {} is not this repo's {}".format(
            resolved, EXPECTED_UPROJECT))
    if not resolved.is_file():
        raise GuardError("this repo's project file does not exist: {}".format(resolved))
    if resolved.name != "WorldForge.uproject":
        raise GuardError("refusing to boot {}: only WorldForge.uproject is "
                         "permitted".format(resolved.name))
    if REPO_ROOT not in resolved.parents:
        raise GuardError("refusing to boot {}: it is outside this repository "
                         "({})".format(resolved, REPO_ROOT))
    lowered = str(resolved).lower()
    for forbidden in ("gloamstead",):
        if forbidden in lowered:
            raise GuardError("refusing to boot {}: path contains {!r}; this harness "
                             "boots only the WorldForge engine repo".format(
                                 resolved, forbidden))
    return resolved


def _resolve_ue_cmd(arg):
    """(path_or_None, source, detail). Never raises -- absence is reportable."""
    if arg:
        p = Path(arg)
        return (p, "arg", str(p)) if p.is_file() else \
            (None, "arg", "--ue-cmd {} does not exist".format(p))
    env = os.environ.get("WF_UE_CMD")
    if env:
        p = Path(env)
        return (p, "env", str(p)) if p.is_file() else \
            (None, "env", "WF_UE_CMD={} does not exist".format(p))
    sys.path.insert(0, str(REPO_ROOT / "tools" / "bridge"))
    try:
        import paths as P  # tools/bridge/paths.py
        resolved = P.resolve_ue_cmd()
        p = Path(str(resolved))
        return (p, resolved.source, str(p)) if p.is_file() else \
            (None, resolved.source, "{} does not exist".format(p))
    except Exception as exc:  # noqa: BLE001
        return None, "unresolved", "{}: {}".format(type(exc).__name__, exc)


def _utc_now():
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ"), now.timestamp()


def _new_report(report_kind, nonce, operation_id, map_path):
    generated_at, epoch = _utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        # A DECLARED timestamp, not an mtime. This repo has been burned by a gate
        # grading an eight-day-old artifact, and mtime is not a freshness signal
        # here -- an artifact was observed moving 07-19 -> 07-27 with identical
        # bytes. `run_nonce` additionally makes two runs byte-distinct even when
        # every observation is identical.
        "generated_at": generated_at,
        "generated_at_epoch": epoch,
        "run_nonce": nonce,
        "report_kind": report_kind,
        "report_kind_vocabulary": list(ALL_REPORT_KINDS),
        "operation_id": operation_id,
        "gate_green": False,
        "gate_reason": None,
        "gate_integrity": None,
        "project": None,
        "ue_cmd": None,
        "ue_cmd_source": None,
        "map": map_path,
        "map_loaded": None,
        "observed_engine_version": None,
        "observed_uproject": None,
        "observed_world_package": None,
        "runtime_executed": False,
        "editor_exit_code": None,
        "elapsed_seconds": None,
        "command": None,
        "liveness": {"verified": False,
                     "reason": "liveness was never evaluated"},
        "probes": new_probe_table(
            STATUS_UNAVAILABLE,
            "the harness did not get as far as launching an editor"),
        "tally": {},
        "unmet_required_probes": list(REQUIRED_PROBES),
        "safety": None,
        "raw_evidence_summary": None,
        "operation_manifest": None,
        "d18": analyze_d18(None, {}, None),
        "d18_samples_path": None,
        "far_side_notes": [],
        "far_side_error": None,
        "stdout_tail": None,
    }


def near_side_main(argv=None):
    import argparse
    import secrets
    import subprocess
    import tempfile

    parser = argparse.ArgumentParser(
        description="Boot this repo's project headless and prove the v2.6 survey "
                    "API surface. There is intentionally no --project flag.")
    parser.add_argument("--map", default=DEFAULT_MAP,
                        help="UE package path of the map to probe (default: %(default)s)")
    parser.add_argument("--ue-cmd", default=None,
                        help="UnrealEditor-Cmd.exe (default: WF_UE_CMD, then "
                             "tools/bridge/paths.resolve_ue_cmd)")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="editor wall-clock budget in seconds (default: %(default)s)")
    parser.add_argument("--d18-reps", type=int, default=D18_DEFAULT_REPS,
                        help="measured repetitions per grid configuration "
                             "(default: %(default)s; fewer than {} fails the D18 "
                             "probe -- a single timing sample is not a "
                             "measurement)".format(D18_MIN_REPS))
    parser.add_argument("--d18-warmup", type=int, default=D18_DEFAULT_WARMUP,
                        help="warm-up repetitions per configuration, excluded from "
                             "the fit (default: %(default)s)")
    parser.add_argument("--d18-configs", default=None,
                        help="semicolon-separated R:s pairs in cm, e.g. "
                             "'200:200;400:200;800:200'. At least {} distinct N are "
                             "needed to separate alpha from beta.".format(
                                 D18_MIN_CONFIGS_FOR_FIT))
    parser.add_argument("--dry-run", action="store_true",
                        help="resolve and guard everything, print the exact command "
                             "that WOULD run, and launch nothing. Writes only "
                             + DRYRUN_REPORT_NAME + ", never the canonical report.")
    args = parser.parse_args(argv)

    nonce = secrets.token_hex(16)
    operation_id = "op_v2_6_fixture_smoke_" + nonce[:12]

    configs = [list(c) for c in D18_DEFAULT_CONFIGS]
    if args.d18_configs:
        parsed = []
        for chunk in args.d18_configs.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                r_s, s_s = chunk.split(":")
                parsed.append([float(r_s), float(s_s)])
            except Exception:  # noqa: BLE001
                parser.error("unparseable --d18-configs entry {!r}".format(chunk))
        if parsed:
            configs = parsed
    d18_plan = {"configs": configs, "warmup": max(0, args.d18_warmup),
                "reps": max(1, args.d18_reps)}

    report = _new_report(KIND_NO_EDITOR, nonce, operation_id, args.map)

    # ---- guard first; nothing else happens until the project is proven ------
    try:
        uproject = _resolve_uproject()
    except GuardError as exc:
        report["report_kind"] = KIND_GUARD_REFUSED
        report["gate_reason"] = "project guard refused the run: {}".format(exc)
        return _finish(report, nonce, None)
    report["project"] = str(uproject).replace("\\", "/")

    ue_cmd, source, detail = _resolve_ue_cmd(args.ue_cmd)
    report["ue_cmd_source"] = source
    report["ue_cmd"] = str(ue_cmd).replace("\\", "/") if ue_cmd else None

    self_path = str(Path(__file__).resolve()).replace("\\", "/")
    # UE is a Windows process: absolute paths with forward slashes only.
    # Backslashes inside a quoted -ExecutePythonScript= value are re-parsed as C
    # escapes (gloam_bridge_live.py:72-75).
    command = ([str(ue_cmd)] if ue_cmd else ["<UnrealEditor-Cmd.exe unresolved>"]) + [
        report["project"],
        "-ExecutePythonScript={}".format(self_path),
        "-unattended", "-nopause", "-nosplash", "-nullrhi", "-stdout",
    ]
    report["command"] = command

    if ue_cmd is None:
        report["report_kind"] = KIND_NO_EDITOR
        report["gate_reason"] = (
            "no editor is available, so nothing was observed: {}. Every probe is "
            "{} -- none of them is a pass.".format(detail, STATUS_UNAVAILABLE))
        report["probes"] = new_probe_table(STATUS_UNAVAILABLE, detail)
        return _finish(report, nonce, None)

    if args.dry_run:
        report["report_kind"] = KIND_DRY_RUN
        report["gate_reason"] = (
            "--dry-run: no editor was launched, so nothing was observed. The probe "
            "table below is the repo's HONEST current state, not a result.")
        report["probes"] = new_probe_table(
            STATUS_ASSUMED, "--dry-run: this symbol has never been executed")
        report["liveness"]["reason"] = (
            "--dry-run never launches a process, so there is nothing live to prove")
        return _finish(report, nonce, None)

    # ---- launch --------------------------------------------------------------
    tmp_dir = tempfile.mkdtemp(prefix="wf_v26_fixture_smoke_")
    far_out = str(Path(tmp_dir) / "far_side_observations.json").replace("\\", "/")
    env = dict(os.environ)
    env[ENV_FAR_SIDE] = "1"
    env[ENV_OUT] = far_out
    env[ENV_MAP] = args.map
    env[ENV_NONCE] = nonce
    env[ENV_OPERATION_ID] = operation_id
    env[ENV_D18] = json.dumps(d18_plan)
    env["PYTHONUTF8"] = "1"

    started = time.time()
    stdout = ""
    try:
        proc = subprocess.run(command, env=env, timeout=args.timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        report["editor_exit_code"] = proc.returncode
        stdout = proc.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b"").decode("utf-8", "replace")
        report["editor_exit_code"] = None  # timed out: no exit code, no success
    except Exception as exc:  # noqa: BLE001
        stdout = "{}: {}".format(type(exc).__name__, exc)
    report["elapsed_seconds"] = round(time.time() - started, 2)
    report["stdout_tail"] = "\n".join(stdout.splitlines()[-40:]) or None

    far_doc = None
    if Path(far_out).is_file():
        try:
            with open(far_out, "r", encoding="utf-8") as fh:
                far_doc = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            report["far_side_error"] = "far-side JSON unreadable: {}: {}".format(
                type(exc).__name__, exc)
    if not isinstance(far_doc, dict):
        far_doc = None

    if far_doc is None:
        report["report_kind"] = KIND_BOOT_FAILED
        launch_detail = (
            "the editor produced no far-side observations (exit_code={}, {}s). "
            "Nothing was observed.".format(
                report["editor_exit_code"], report["elapsed_seconds"]))
        report["probes"] = classify(None, launch_detail)
        report["gate_reason"] = "GATE RED -- " + launch_detail
    else:
        report["report_kind"] = KIND_LIVE
        report["runtime_executed"] = bool(far_doc.get("far_side_ran"))
        report["map_loaded"] = far_doc.get("map_loaded")
        report["observed_engine_version"] = far_doc.get("observed_engine_version")
        report["observed_uproject"] = far_doc.get("observed_uproject")
        report["observed_world_package"] = far_doc.get("observed_world_package")
        report["safety"] = far_doc.get("safety")
        report["far_side_notes"] = far_doc.get("notes") or []
        report["far_side_error"] = far_doc.get("error") or report["far_side_error"]
        report["probes"] = classify(far_doc, "")
        verify_manifest_digest(far_doc, report["probes"])
        report["operation_manifest"] = far_doc.get("operation_manifest")
        bundle = far_doc.get("raw_evidence") or {}
        report["raw_evidence_summary"] = {
            "bundle_schema": bundle.get("bundle_schema"),
            "record_schema": bundle.get("record_schema"),
            "record_kinds": sorted((bundle.get("records") or {}).keys()),
            "record_count": sum(len(v) for v in (bundle.get("records") or {}).values()),
            "digest_recomputed_by_near_side": digest(bundle) if bundle else None,
        }
        report["d18"] = analyze_d18(far_doc.get("d18_raw"), report["probes"],
                                    far_doc.get("safety"))

    return _finish(report, nonce, far_doc)


def _strip_samples(far_doc):
    """Pull the per-sample rows out for the sidecar; the report keeps verdicts."""
    raw = (far_doc or {}).get("d18_raw") or {}
    out = []
    for cfg in raw.get("configs") or []:
        out.append({
            "radius_cm": cfg.get("radius_cm"), "step_cm": cfg.get("step_cm"),
            "n_contract": cfg.get("n_contract"),
            "reps": [{"rep_index": r.get("rep_index"),
                      "id_sequence_sha256": r.get("id_sequence_sha256"),
                      "rows": r.get("rows")}
                     for r in cfg.get("reps") or []],
        })
    return out


def _report_path_for(kind):
    """A non-live run can NEVER be written to the canonical report path.

    This is the structural half of "a failed boot must not leave behind a
    plausible report": the canonical filename is reachable only by a live run, so
    a boot failure cannot overwrite real evidence with a near-side artefact, and
    a consumer reading the canonical path is never reading a dry run.
    """
    if kind == KIND_LIVE:
        return REPORT_DIR / REPORT_NAME
    if kind == KIND_DRY_RUN:
        return REPORT_DIR / DRYRUN_REPORT_NAME
    return REPORT_DIR / NORUN_REPORT_NAME


def _finish(report, nonce, far_doc):
    """Verify liveness, compute the gate, persist, print, return an exit code."""
    report["liveness"] = verify_liveness(report, far_doc, nonce)

    green, reason, tally, unmet, integrity = evaluate_gate(report)
    report["gate_green"] = green
    report["tally"] = tally
    report["unmet_required_probes"] = unmet
    report["gate_integrity"] = integrity
    if green:
        report["gate_reason"] = reason
    else:
        # A pre-existing reason (guard refusal, no editor, dry run) explains WHY
        # the run never got far enough; the gate's own complaint is appended so a
        # reader gets both the cause and the structural verdict.
        prior = report.get("gate_reason")
        report["gate_reason"] = "{} | {}".format(prior, reason) if prior else reason

    out_path = _report_path_for(report["report_kind"])
    samples_path = REPORT_DIR / SAMPLES_NAME
    written = "<not written>"
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        samples = _strip_samples(far_doc)
        if samples:
            with open(samples_path, "w", encoding="utf-8") as fh:
                json.dump({"schema_version": SCHEMA_VERSION + ".d18_samples",
                           "generated_at": report["generated_at"],
                           "run_nonce": nonce,
                           "operation_id": report["operation_id"],
                           "sample_order": (report.get("d18") or {}).get("sample_order"),
                           "configs": samples}, fh, indent=2, sort_keys=True)
            report["d18_samples_path"] = str(samples_path)
        if report["report_kind"] != KIND_LIVE:
            canonical = REPORT_DIR / REPORT_NAME
            report["canonical_report_present"] = canonical.is_file()
            report["canonical_report_note"] = (
                "this run did NOT produce live evidence, so it was written to {} and "
                "the canonical report at {} was left untouched. If that canonical "
                "report exists it is OLDER than this attempt -- check its "
                "generated_at and run_nonce before trusting it.".format(
                    out_path.name, REPORT_NAME))
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        written = str(out_path)
    except Exception as exc:  # noqa: BLE001
        written = "<unwritable: {}: {}>".format(type(exc).__name__, exc)

    sys.stdout.write(_human_summary(report))
    sys.stdout.write("  report -> {}\n".format(written))
    if report.get("d18_samples_path"):
        sys.stdout.write("  d18 raw samples -> {}\n".format(
            report["d18_samples_path"]))
    sys.stdout.write("\n")
    return 0 if report["gate_green"] else 1


def _human_summary(report):
    width = max(len(n) for n in PROBE_NAMES)
    probes = report.get("probes") or {}
    lines = ["",
             "v2.6 fixture smoke -- {}".format("GREEN" if report["gate_green"]
                                               else "RED"),
             "kind    : {}".format(report.get("report_kind")),
             "at      : {}  nonce={}".format(report.get("generated_at"),
                                             report.get("run_nonce")),
             "project : {}".format(report["project"]),
             "engine  : {}".format(report["ue_cmd"] or "<none resolved>"),
             "map     : {}".format(report["map"]),
             "observed: engine={} loaded={} live={}".format(
                 report["observed_engine_version"], report["map_loaded"],
                 (report.get("liveness") or {}).get("verified")),
             ""]
    last_group = None
    for name in PROBE_NAMES:
        group = PROBE_GROUP[name]
        if group != last_group:
            lines.append("  [{}]".format(group))
            last_group = group
        rec = probes.get(name)
        status = "<MISSING FROM REPORT>" if not isinstance(rec, dict) \
            else rec.get("status")
        lines.append("    {}   {}".format(name.ljust(width), status))
    lines.append("")
    for name in PROBE_NAMES:
        rec = probes.get(name)
        if not isinstance(rec, dict):
            lines.append("  ! {}: MISSING FROM THE REPORT ENTIRELY".format(name))
        elif rec.get("status") != STATUS_VERIFIED:
            lines.append("  ! {}: {}".format(name, rec.get("detail")))
    tally = report.get("tally") or {}
    lines.append("")
    lines.append("  verified={} unavailable={} failed={} still_assumed={} missing={}"
                 .format(tally.get(STATUS_VERIFIED, 0),
                         tally.get(STATUS_UNAVAILABLE, 0),
                         tally.get(STATUS_FAILED, 0),
                         tally.get(STATUS_ASSUMED, 0), tally.get("missing", 0)))

    d18 = report.get("d18") or {}
    fit = d18.get("fit") or {}
    lines.append("")
    lines.append("  D18 -- T(N) = alpha + beta*N")
    if fit.get("fitted"):
        lines.append("    alpha={:.6g}s  beta={:.6g}s/sample  R2={}  resid_sd={:.3g}s"
                     "  points={}".format(
                         fit["alpha"], fit["beta"],
                         "n/a" if fit.get("r_squared") is None
                         else "{:.4f}".format(fit["r_squared"]),
                         fit.get("residual_std") or float("nan"), fit.get("points")))
    else:
        lines.append("    no fit: {}".format(fit.get("reason")))
    for cfg in d18.get("per_config") or []:
        lines.append("    N={:<6} median={:<10} p95={:<10} mad={:<10} ok={}/{}"
                     " order_stable={}".format(
                         cfg.get("n_contract"),
                         _fmt(cfg.get("median_seconds")), _fmt(cfg.get("p95_seconds")),
                         _fmt(cfg.get("median_absolute_deviation_seconds")),
                         cfg.get("success_count"), cfg.get("sample_count"),
                         cfg.get("ordering_stable")))
    lines.append("")
    for cid, _text in D18_CRITERIA:
        rec = (d18.get("criteria") or {}).get(cid) or {}
        lines.append("    {:<34} {}".format(cid, rec.get("verdict", "<MISSING>")))
    lines.append("")
    lines.append("  {}".format(report["gate_reason"]))
    lines.append("")
    return "\n".join(lines)


def _fmt(value):
    return "n/a" if value is None else "{:.6g}".format(value)


# =========================================================================== #
if os.environ.get(ENV_FAR_SIDE) == "1":
    # Inside the editor. Observe, write, then ask for a clean shutdown -- a plain
    # -ExecutePythonScript boot otherwise sits in the editor loop until the near
    # side's timeout.
    far_side_main()
    try:
        import unreal
        unreal.SystemLibrary.quit_editor()
    except Exception:  # noqa: BLE001
        pass
elif __name__ == "__main__":
    sys.exit(near_side_main())
