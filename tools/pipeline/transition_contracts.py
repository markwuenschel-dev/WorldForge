#!/usr/bin/env python3
"""transition_contracts.py — WorldForge v2.5 UE58TransitionForge contract spine.

v2.5 is the UE 5.7 -> 5.8 engine transition + adapter-portability + Gloamstead
bridge-contract milestone (re-scoped 2026-07-12 from SpatialIntelligenceForge). It is
NOT a new gameplay system. It is the bounded substrate that proves, with evidence, that
the existing v2.0/v2.2/v2.3/v2.4 WorldForge stack ports cleanly onto UE 5.8 without silent
loss — and that the Gloamstead bridge is a HONESTLY-REJECTING dry probe, not an authored
courtyard (real Gloamstead level proof is deferred to v2.7.x/2.8).

Core design principle (mirror of the tactical spine):
    A transition claim is valid only if the engine it ran on, the assets it converted,
    the plugin it built, the regressions it re-ran, the bridge it probed, and the evidence
    it emitted are recorded and validate against contracts. No "it opened in 5.8 and looked
    fine" claims. No 5.7 evidence laundered as a 5.8 baseline. Every transition claim needs
    evidence tagged with the engine that produced it.

This module holds the strict, schema-only contracts that define those transition artifacts
and prove — at authoring time, before any 5.8 conversion or plugin build exists — that
their *shape* is coherent and cannot launder: a report from the wrong engine, a required
engine capability marked unavailable, a conversion that silently drops actors, a build
report that claims success while the plugin failed to load or the binary is stale, a
regression report that flags a WorldForge regression yet marks itself regression-free, a
Gloamstead bridge probe that claims it could proceed with no plugin present or leaks an
absolute path, or a "5.8 baseline" evidence index contaminated with 5.7 reports.

Design mirrors tactical_contracts.py / streaming_contracts.py exactly:
    * frozen tuple enums (bounded taxonomy, one source of truth)
    * ``X_REQUIRED`` / ``X_ALLOWED`` field-name tuples
    * ``validate_X(obj, strict=False)`` returning (check, ok, detail, code) tuples built
      from shared runtime_schema (RS) helpers + domain honesty checks
    * ``_example_X(**over)`` canonical-valid factories (``d.update(over)`` spawns
      known-bad variants for the negatives/fuzz suites)
    * a ``CONTRACTS`` registry pairing each validator with a valid + known-bad example,
      ``CONTRACT_GROUPS`` partitioning it, and ``KNOWN_BAD_OWNING_CODE`` naming the code
      each known-bad must be rejected FOR

Schema-only: cross-artifact resolution (does the plugin binary actually exist on disk? did
the 5.8 editor really open the map? does the churn set match a real git diff?) is the job
of the Wave-2..7 gate validators, which have the filesystem + engine in hand. Stdlib only;
no jsonschema.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_schema as RS  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from engine_identity import IDENTITY_KEYS  # noqa: E402

# --------------------------------------------------------------------------- #
# schema_version / report_type dotted namespaces (wf.transition.<type>.v1)
# --------------------------------------------------------------------------- #
RT_ENGINE_IDENTITY = "wf.transition.engine_identity.v1"
RT_CAPABILITY_MANIFEST = "wf.transition.capability_manifest.v1"
RT_CONVERSION_MANIFEST = "wf.transition.conversion_manifest.v1"
RT_PLUGIN_BUILD = "wf.transition.plugin_build_report.v1"
RT_REGRESSION = "wf.transition.regression_report.v1"
RT_GLOAM_BRIDGE = "wf.transition.gloam_bridge_probe.v1"
RT_BASELINE = "wf.transition.baseline_index.v1"

# --------------------------------------------------------------------------- #
# Bounded taxonomy (one source of truth).
# --------------------------------------------------------------------------- #
# The engine transition edge: the frozen source engine and the active target engine.
SOURCE_ENGINE = "5.7"
TARGET_ENGINE = "5.8"
TRANSITION_ENGINES = (SOURCE_ENGINE, TARGET_ENGINE)
# The engine major all WorldForge runs share; a report on a different major is a mismatch.
EXPECTED_ENGINE_MAJOR = 5
# Capability kinds the transition depends on (bounded — an unknown kind is a smell).
CAPABILITY_KINDS = ("engine_module", "plugin_module", "editor_subsystem",
                    "asset_type", "build_tool")
# Conversion churn classes. expected = a churn the transition accounts for (asset upgrade,
# redirector); unexpected = an unaccounted change that must fail the manifest.
CHURN_CLASSES = ("none", "asset_version_upgrade", "redirector_fixup",
                 "expected_resave", "unexpected")
ACCOUNTED_CHURN = ("none", "asset_version_upgrade", "redirector_fixup", "expected_resave")
# Build results for the plugin build report.
BUILD_RESULTS = ("succeeded", "failed", "skipped")
# Regression classification of a per-map diff.
REGRESSION_CLASSES = ("clean", "expected_engine_diff", "unclassified", "worldforge_regression")
BENIGN_REGRESSION_CLASSES = ("clean", "expected_engine_diff")
# Gloamstead bridge probe results. The v2.5 bridge is a REJECTING dry probe by design;
# "ready" is reserved for the future real-level milestone and, if ever claimed, must be
# backed by a present plugin + present map + matching engine.
BRIDGE_RESULTS = ("rejected_dry_probe", "ready")
# The bridge targets Gloamstead, which runs on UE 5.8.
BRIDGE_ENGINE = "5.8"
# Honest evidence-engine tags (the minor of the engine that produced a report).
EVIDENCE_ENGINE_MINORS = (7, 8)

# The shared deterministic authoring timestamp (NOT wall-clock).
AUTHORING_TS = "2026-07-12T00:00:00+00:00"

# Report roots (repo-relative) — 5.7 and 5.8 evidence live in disjoint subtrees.
REPORTS_5_7_REL = "procedural/reports/ue5_7"
REPORTS_5_8_REL = "procedural/reports/ue5_8"

_WF_CODE_RE = re.compile(r"^WF\d{3,4}_[A-Z0-9_]+$")
# An absolute path leak: a Windows drive-letter path or a POSIX root path.
_ABS_PATH_RE = re.compile(r"^([A-Za-z]:[\\/]|[\\/])")


# --------------------------------------------------------------------------- #
# small local helpers (mirror tactical_contracts.py)
# --------------------------------------------------------------------------- #
def _str(obj, field, code, prefix):
    ch = RS.check_type(obj, field, str, code, prefix=prefix)
    v = obj.get(field) if isinstance(obj, dict) else None
    ch.append(("{}{}_nonempty".format(prefix, field),
               isinstance(v, str) and bool(v.strip()),
               "{} must be a non-empty string".format(field), code))
    return ch


def _bool(obj, field, code, prefix):
    v = obj.get(field) if isinstance(obj, dict) else None
    return [("{}{}_bool".format(prefix, field), isinstance(v, bool),
             "{} must be an explicit boolean (got {!r})".format(field, v), code)]


def _int(obj, field, code, prefix, allow_zero=True):
    ch = RS.check_positive_number(obj, field, code, prefix=prefix, allow_zero=allow_zero)
    v = obj.get(field) if isinstance(obj, dict) else None
    is_int = RS.is_number(v) and float(v).is_integer()
    ch.append(("{}{}_integer".format(prefix, field), is_int,
               "{} must be an integer (got {!r})".format(field, v), code))
    return ch


def _is_list(obj, field):
    return isinstance(obj.get(field), list) if isinstance(obj, dict) else False


def _is_dict(obj, field):
    return isinstance(obj.get(field), dict) if isinstance(obj, dict) else False


def _schema_version(obj, expected, code, prefix):
    sv = obj.get("schema_version") if isinstance(obj, dict) else None
    return [("{}schema_version".format(prefix), sv == expected,
             "schema_version must be {!r} (got {!r})".format(expected, sv), code)]


def _no_abs_path(value):
    """True iff value is a string with no absolute-path leak (drive-letter or root)."""
    return isinstance(value, str) and not _ABS_PATH_RE.match(value.strip())


# =========================================================================== #
# 1. EngineIdentity (WF1013) — the engine-identity block engine_identity.py emits,
#    as embedded in a report's meta. Proves a report names the engine it ran on.
# =========================================================================== #
IDENTITY_REQUIRED = tuple(IDENTITY_KEYS) + ("schema_version",)
IDENTITY_ALLOWED = IDENTITY_REQUIRED + ("engine_root", "_resolution", "report_type",
                                        "created_by", "created_at", "notes")


def validate_engine_identity(obj, strict=False):
    code = C.ENGINE_VERSION_MISMATCH
    ch = RS.check_required(obj, IDENTITY_REQUIRED, code,
                           nullable=("engine_build_id", "project_commit", "plugin_commit"))
    ch += RS.check_no_unknown(obj, IDENTITY_ALLOWED, code, strict)
    maj = obj.get("engine_major") if isinstance(obj, dict) else None
    ch.append(("id::engine_major_is_5", maj == EXPECTED_ENGINE_MAJOR,
               "engine_major must be {} (got {!r})".format(EXPECTED_ENGINE_MAJOR, maj), code))
    minor = obj.get("engine_minor") if isinstance(obj, dict) else None
    ch.append(("id::engine_minor_known",
               isinstance(minor, int) and not isinstance(minor, bool)
               and minor in EVIDENCE_ENGINE_MINORS,
               "engine_minor must be one of {} (got {!r})".format(EVIDENCE_ENGINE_MINORS, minor),
               code))
    patch = obj.get("engine_patch") if isinstance(obj, dict) else None
    ch.append(("id::engine_patch_int",
               isinstance(patch, int) and not isinstance(patch, bool) and patch >= 0,
               "engine_patch must be a non-negative integer (got {!r})".format(patch), code))
    # project_path_identity ties a report to its worktree: "<12-hex>:<basename>".
    ppi = obj.get("project_path_identity") if isinstance(obj, dict) else None
    ch.append(("id::path_identity_shape",
               isinstance(ppi, str) and bool(re.match(r"^[0-9a-f]{12}:.+$", ppi)),
               "project_path_identity must be '<12hex>:<basename>' (got {!r})".format(ppi), code))
    ch += _schema_version(obj, RT_ENGINE_IDENTITY, code, "id::")
    return ch


def _example_engine_identity(**over):
    d = {
        "engine_major": 5,
        "engine_minor": 8,
        "engine_patch": 0,
        "engine_build_id": "55116800@++UE5+Release-5.8",
        "project_commit": "4641ee8724d7eb901dde890afa9dc3e5b5c7ca41",
        "plugin_commit": "2940a5afd71828c336d918356fb71ff9aa6a1c81",
        "project_path_identity": "731a1b255046:WorldForge-UE58",
        "created_by": "worldforge.v2.5",
        "created_at": AUTHORING_TS,
        "schema_version": RT_ENGINE_IDENTITY,
        "report_type": RT_ENGINE_IDENTITY,
    }
    d.update(over)
    return d


# =========================================================================== #
# 2. CapabilityManifest (WF1011/WF1012) — the engine capabilities the transition
#    depends on, each with required/available/version so a missing or version-
#    mismatched capability cannot be laundered into a green transition.
# =========================================================================== #
CAPABILITY_MANIFEST_REQUIRED = (
    "manifest_id", "engine_minor", "capabilities", "schema_version",
)
CAPABILITY_MANIFEST_ALLOWED = CAPABILITY_MANIFEST_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes")
_CAPABILITY_ENTRY_REQUIRED = (
    "capability_id", "kind", "required", "available", "required_version", "actual_version",
)


def _capability_entry_checks(cap, idx):
    p = "cap::[{}]::".format(idx)
    ch = []
    if not isinstance(cap, dict):
        return [(p + "is_dict", False, "capability entry must be a dict", C.CAPABILITY_UNAVAILABLE)]
    for f in _CAPABILITY_ENTRY_REQUIRED:
        ch.append((p + f + "_present", f in cap,
                   "capability entry missing {}".format(f), C.CAPABILITY_UNAVAILABLE))
    ch.append((p + "kind_known", cap.get("kind") in CAPABILITY_KINDS,
               "capability kind must be in {} (got {!r})".format(CAPABILITY_KINDS, cap.get("kind")),
               C.CAPABILITY_UNAVAILABLE))
    req = cap.get("required")
    avail = cap.get("available")
    ch.append((p + "required_bool", isinstance(req, bool),
               "required must be a boolean", C.CAPABILITY_UNAVAILABLE))
    ch.append((p + "available_bool", isinstance(avail, bool),
               "available must be a boolean", C.CAPABILITY_UNAVAILABLE))
    # honesty: a REQUIRED capability that is not available fails the manifest (WF1011).
    ch.append((p + "required_implies_available", not (req is True and avail is not True),
               "capability {!r} is required but not available".format(cap.get("capability_id")),
               C.CAPABILITY_UNAVAILABLE))
    # honesty: an available capability whose actual_version != required_version is a
    # version mismatch (WF1012). Versions compared as strings (exact match contract).
    rv, av = cap.get("required_version"), cap.get("actual_version")
    version_ok = (avail is not True) or (rv is None) or (rv == av)
    ch.append((p + "version_match", version_ok,
               "available capability {!r} version {!r} != required {!r}".format(
                   cap.get("capability_id"), av, rv), C.CAPABILITY_VERSION_MISMATCH))
    return ch


def validate_capability_manifest(obj, strict=False):
    code = C.CAPABILITY_UNAVAILABLE
    ch = RS.check_required(obj, CAPABILITY_MANIFEST_REQUIRED, code)
    ch += RS.check_no_unknown(obj, CAPABILITY_MANIFEST_ALLOWED, code, strict)
    ch += _str(obj, "manifest_id", code, "cap::")
    minor = obj.get("engine_minor") if isinstance(obj, dict) else None
    ch.append(("cap::engine_minor_known",
               isinstance(minor, int) and not isinstance(minor, bool)
               and minor in EVIDENCE_ENGINE_MINORS,
               "engine_minor must be one of {} (got {!r})".format(EVIDENCE_ENGINE_MINORS, minor),
               code))
    caps = obj.get("capabilities") if _is_list(obj, "capabilities") else None
    ch.append(("cap::capabilities_nonempty", bool(caps),
               "capabilities must be a non-empty list", code))
    for i, cap in enumerate(caps or []):
        ch += _capability_entry_checks(cap, i)
    ch += _schema_version(obj, RT_CAPABILITY_MANIFEST, code, "cap::")
    return ch


def _example_capability_manifest(**over):
    d = {
        "manifest_id": "capman_ue58_transition",
        "engine_minor": 8,
        "capabilities": [
            {"capability_id": "WorldForgeRuntime", "kind": "plugin_module",
             "required": True, "available": True,
             "required_version": "2.5.0", "actual_version": "2.5.0"},
            {"capability_id": "PCGFramework", "kind": "engine_module",
             "required": True, "available": True,
             "required_version": None, "actual_version": "5.8.0"},
            {"capability_id": "WorldPartition", "kind": "editor_subsystem",
             "required": True, "available": True,
             "required_version": None, "actual_version": "5.8.0"},
        ],
        "created_by": "worldforge.v2.5",
        "created_at": AUTHORING_TS,
        "schema_version": RT_CAPABILITY_MANIFEST,
        "report_type": RT_CAPABILITY_MANIFEST,
    }
    d.update(over)
    return d


# =========================================================================== #
# 3. ConversionManifest (WF1014/WF1015/WF1016) — the 5.7 -> 5.8 asset/map
#    conversion record. Per-map actor accounting so a silent actor loss, an
#    incomplete manifest, or unaccounted churn cannot green a conversion.
# =========================================================================== #
CONVERSION_MANIFEST_REQUIRED = (
    "manifest_id", "source_engine", "target_engine", "maps", "expected_map_count",
    "schema_version",
)
CONVERSION_MANIFEST_ALLOWED = CONVERSION_MANIFEST_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
    # conversion_status is the authoritative-manifest completeness flag the --conversion
    # gate keys on ("complete"); it is a legitimate optional field, so the strict
    # no-unknown-fields check must permit it. Per-map churn notes ride "notes".
    "conversion_status")
_CONVERSION_MAP_REQUIRED = (
    "map_path", "actors_before", "actors_after", "accounted_deletions", "churn_class",
)


def _conversion_map_checks(m, idx):
    p = "cv::[{}]::".format(idx)
    ch = []
    if not isinstance(m, dict):
        return [(p + "is_dict", False, "map entry must be a dict", C.CONVERSION_MANIFEST_INCOMPLETE)]
    for f in _CONVERSION_MAP_REQUIRED:
        ch.append((p + f + "_present", f in m,
                   "map entry missing {}".format(f), C.CONVERSION_MANIFEST_INCOMPLETE))
    ch.append((p + "map_path_rel", _no_abs_path(m.get("map_path")),
               "map_path must be a relative repo path (no absolute leak): {!r}".format(
                   m.get("map_path")), C.CONVERSION_MANIFEST_INCOMPLETE))
    before, after = m.get("actors_before"), m.get("actors_after")
    deletions = m.get("accounted_deletions")
    for f, v in (("actors_before", before), ("actors_after", after),
                 ("accounted_deletions", deletions)):
        ok = isinstance(v, int) and not isinstance(v, bool) and v >= 0
        ch.append((p + f + "_nonneg_int", ok,
                   "{} must be a non-negative integer (got {!r})".format(f, v),
                   C.CONVERSION_MANIFEST_INCOMPLETE))
    ch.append((p + "churn_known", m.get("churn_class") in CHURN_CLASSES,
               "churn_class must be in {} (got {!r})".format(CHURN_CLASSES, m.get("churn_class")),
               C.CONVERSION_UNEXPECTED_CHURN))
    # honesty: unexpected churn is never an accepted conversion (WF1016).
    ch.append((p + "churn_accounted", m.get("churn_class") in ACCOUNTED_CHURN,
               "map {!r} has unexpected churn".format(m.get("map_path")),
               C.CONVERSION_UNEXPECTED_CHURN))
    # honesty: no actor loss — after must cover (before - accounted_deletions) (WF1014).
    if all(isinstance(v, int) and not isinstance(v, bool) for v in (before, after, deletions)):
        ch.append((p + "no_actor_loss", after >= before - deletions,
                   "map {!r} lost actors: after={} < before={} - deletions={}".format(
                       m.get("map_path"), after, before, deletions),
                   C.CONVERSION_ACTOR_LOSS))
    return ch


def validate_conversion_manifest(obj, strict=False):
    code = C.CONVERSION_MANIFEST_INCOMPLETE
    ch = RS.check_required(obj, CONVERSION_MANIFEST_REQUIRED, code)
    ch += RS.check_no_unknown(obj, CONVERSION_MANIFEST_ALLOWED, code, strict)
    ch += _str(obj, "manifest_id", code, "cv::")
    ch.append(("cv::source_engine", obj.get("source_engine") == SOURCE_ENGINE,
               "source_engine must be {!r}".format(SOURCE_ENGINE), C.ENGINE_VERSION_MISMATCH))
    ch.append(("cv::target_engine", obj.get("target_engine") == TARGET_ENGINE,
               "target_engine must be {!r}".format(TARGET_ENGINE), C.ENGINE_VERSION_MISMATCH))
    maps = obj.get("maps") if _is_list(obj, "maps") else None
    ch.append(("cv::maps_nonempty", bool(maps), "maps must be a non-empty list", code))
    for i, m in enumerate(maps or []):
        ch += _conversion_map_checks(m, i)
    # honesty: the manifest must cover exactly the expected number of maps (WF1015).
    exp = obj.get("expected_map_count")
    ch += _int(obj, "expected_map_count", code, "cv::", allow_zero=False)
    if isinstance(exp, int) and not isinstance(exp, bool) and maps is not None:
        ch.append(("cv::manifest_complete", len(maps) == exp,
                   "conversion manifest incomplete: {} maps but expected {}".format(
                       len(maps), exp), C.CONVERSION_MANIFEST_INCOMPLETE))
    ch += _schema_version(obj, RT_CONVERSION_MANIFEST, code, "cv::")
    return ch


def _example_conversion_manifest(**over):
    d = {
        "manifest_id": "conv_ue57_to_ue58_slice",
        "source_engine": "5.7",
        "target_engine": "5.8",
        "expected_map_count": 2,
        "maps": [
            {"map_path": "Content/Maps/encounter_loop_world.umap",
             "actors_before": 214, "actors_after": 214,
             "accounted_deletions": 0, "churn_class": "asset_version_upgrade"},
            {"map_path": "Content/Maps/alpine_snow.umap",
             "actors_before": 188, "actors_after": 187,
             "accounted_deletions": 1, "churn_class": "redirector_fixup"},
        ],
        "created_by": "worldforge.v2.5",
        "created_at": AUTHORING_TS,
        "schema_version": RT_CONVERSION_MANIFEST,
        "report_type": RT_CONVERSION_MANIFEST,
    }
    d.update(over)
    return d


# =========================================================================== #
# 4. PluginBuildReport (WF1017/WF1018/WF1019) — the WorldForge plugin build+load
#    result against 5.8. A report cannot claim overall_ok while the build failed,
#    the plugin did not load, or the binary is older than its newest source.
# =========================================================================== #
PLUGIN_BUILD_REQUIRED = (
    "report_id", "plugin_name", "target_engine", "build_result", "plugin_loaded",
    "overall_ok", "binary_mtime", "newest_source_mtime", "modules", "schema_version",
)
PLUGIN_BUILD_ALLOWED = PLUGIN_BUILD_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes", "warnings")


def validate_plugin_build_report(obj, strict=False):
    code = C.BUILD_FAILED
    ch = RS.check_required(obj, PLUGIN_BUILD_REQUIRED, code)
    ch += RS.check_no_unknown(obj, PLUGIN_BUILD_ALLOWED, code, strict)
    ch += _str(obj, "report_id", code, "pb::")
    ch += _str(obj, "plugin_name", code, "pb::")
    ch.append(("pb::target_engine", obj.get("target_engine") == TARGET_ENGINE,
               "target_engine must be {!r}".format(TARGET_ENGINE), C.ENGINE_VERSION_MISMATCH))
    ch += RS.check_enum(obj, "build_result", BUILD_RESULTS, code, prefix="pb::")
    ch += _bool(obj, "plugin_loaded", code, "pb::")
    ch += _bool(obj, "overall_ok", code, "pb::")
    ch += _list_of_str_modules(obj)
    bmt, smt = obj.get("binary_mtime"), obj.get("newest_source_mtime")
    for f, v in (("binary_mtime", bmt), ("newest_source_mtime", smt)):
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0
        ch.append(("pb::{}_epoch".format(f), ok,
                   "{} must be a non-negative epoch number (got {!r})".format(f, v),
                   C.STALE_PLUGIN_BINARY))
    ok = obj.get("overall_ok")
    # honesty: overall_ok requires a succeeded build (WF1017)...
    ch.append(("pb::ok_implies_built", not (ok is True and obj.get("build_result") != "succeeded"),
               "overall_ok=True but build_result={!r}".format(obj.get("build_result")),
               C.BUILD_FAILED))
    # ...a loaded plugin (WF1018)...
    ch.append(("pb::ok_implies_loaded", not (ok is True and obj.get("plugin_loaded") is not True),
               "overall_ok=True but plugin_loaded is not True", C.PLUGIN_LOAD_FAILED))
    # ...and a binary not older than its newest source (WF1019).
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (bmt, smt)):
        ch.append(("pb::binary_not_stale", not (ok is True and bmt < smt),
                   "overall_ok=True but binary_mtime {} < newest_source_mtime {} (stale)".format(
                       bmt, smt), C.STALE_PLUGIN_BINARY))
    ch += _schema_version(obj, RT_PLUGIN_BUILD, code, "pb::")
    return ch


def _list_of_str_modules(obj):
    v = obj.get("modules") if isinstance(obj, dict) else None
    ok = isinstance(v, list) and len(v) >= 1 and all(isinstance(x, str) and x.strip() for x in v)
    return [("pb::modules_nonempty_str_list", ok,
             "modules must be a non-empty list of module-name strings", C.BUILD_FAILED)]


def _example_plugin_build_report(**over):
    d = {
        "report_id": "pluginbuild_worldforge_ue58",
        "plugin_name": "WorldForge",
        "target_engine": "5.8",
        "build_result": "succeeded",
        "plugin_loaded": True,
        "overall_ok": True,
        "binary_mtime": 1752300000,
        "newest_source_mtime": 1752200000,
        "modules": ["WorldForgeRuntime", "WorldForgeCore", "WorldForgeEd"],
        "created_by": "worldforge.v2.5",
        "created_at": AUTHORING_TS,
        "schema_version": RT_PLUGIN_BUILD,
        "report_type": RT_PLUGIN_BUILD,
    }
    d.update(over)
    return d


# =========================================================================== #
# 5. TransitionRegressionReport (WF1020/WF1021/WF1022) — the v2.4/2.3/2.2 shield
#    re-run under 5.8. regression_free cannot be claimed while a map failed to
#    load, a diff is unclassified, or a WorldForge regression was detected.
# =========================================================================== #
REGRESSION_REPORT_REQUIRED = (
    "report_id", "engine_minor", "suites", "maps_checked", "maps_loaded",
    "diffs", "regression_free", "schema_version",
)
REGRESSION_REPORT_ALLOWED = REGRESSION_REPORT_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes")


def validate_transition_regression_report(obj, strict=False):
    code = C.TRANSITION_REGRESSION_FAILED
    ch = RS.check_required(obj, REGRESSION_REPORT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, REGRESSION_REPORT_ALLOWED, code, strict)
    ch += _str(obj, "report_id", code, "rg::")
    minor = obj.get("engine_minor")
    ch.append(("rg::engine_minor_target",
               isinstance(minor, int) and not isinstance(minor, bool) and minor == 8,
               "regression must run on the target engine (engine_minor=8, got {!r})".format(minor),
               C.EVIDENCE_ENGINE_MISMATCH))
    v = obj.get("suites")
    ch.append(("rg::suites_nonempty_str_list",
               isinstance(v, list) and len(v) >= 1 and all(isinstance(x, str) for x in v),
               "suites must be a non-empty list of shield names", code))
    checked, loaded = obj.get("maps_checked"), obj.get("maps_loaded")
    for f, val in (("maps_checked", checked), ("maps_loaded", loaded)):
        ch += _int(obj, f, code, "rg::", allow_zero=False)
    diffs = obj.get("diffs") if _is_list(obj, "diffs") else None
    ch.append(("rg::diffs_list", diffs is not None, "diffs must be a list (may be empty)", code))
    classes = []
    for i, d in enumerate(diffs or []):
        p = "rg::[{}]::".format(i)
        if not isinstance(d, dict):
            ch.append((p + "is_dict", False, "diff entry must be a dict", code))
            continue
        cls = d.get("classification")
        ch.append((p + "class_known", cls in REGRESSION_CLASSES,
                   "diff classification must be in {} (got {!r})".format(REGRESSION_CLASSES, cls),
                   C.REGRESSION_UNCLASSIFIED_DIFF))
        classes.append(cls)
    ch += _bool(obj, "regression_free", code, "rg::")
    free = obj.get("regression_free")
    # honesty: regression_free requires all maps loaded (WF1020)...
    if isinstance(checked, int) and isinstance(loaded, int) and not isinstance(checked, bool):
        ch.append(("rg::free_implies_all_loaded", not (free is True and loaded < checked),
                   "regression_free=True but only {}/{} maps loaded".format(loaded, checked),
                   C.MAP_LOAD_FAILED))
    # ...every diff classified (WF1021)...
    ch.append(("rg::free_implies_classified",
               not (free is True and any(c == "unclassified" for c in classes)),
               "regression_free=True but an unclassified diff remains", C.REGRESSION_UNCLASSIFIED_DIFF))
    # ...and no WorldForge regression (WF1022).
    ch.append(("rg::free_implies_no_regression",
               not (free is True and any(c == "worldforge_regression" for c in classes)),
               "regression_free=True but a worldforge_regression diff is present",
               C.REGRESSION_WORLDFORGE_REGRESSION))
    ch += _schema_version(obj, RT_REGRESSION, code, "rg::")
    return ch


def _example_transition_regression_report(**over):
    d = {
        "report_id": "regress_ue58_v24_v23_v22",
        "engine_minor": 8,
        "suites": ["v2_4_shield", "v2_3_shield", "v2_2_shield"],
        "maps_checked": 24,
        "maps_loaded": 24,
        "diffs": [
            {"map_path": "Content/Maps/encounter_loop_world.umap",
             "classification": "expected_engine_diff"},
            {"map_path": "Content/Maps/alpine_snow.umap", "classification": "clean"},
        ],
        "regression_free": True,
        "created_by": "worldforge.v2.5",
        "created_at": AUTHORING_TS,
        "schema_version": RT_REGRESSION,
        "report_type": RT_REGRESSION,
    }
    d.update(over)
    return d


# =========================================================================== #
# 6. GloamBridgeProbe (WF1023–WF1030) — the Gloamstead bridge DRY probe. v2.5
#    only lays the bridge contract: the probe must honestly report rejection and
#    must not leak absolute paths or claim readiness it cannot back.
# =========================================================================== #
BRIDGE_PROBE_REQUIRED = (
    "probe_id", "operation_id", "target_engine", "target_project", "probe_result",
    "plugin_present", "map_present", "evidence_entries", "schema_version",
)
BRIDGE_PROBE_ALLOWED = BRIDGE_PROBE_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes", "rejection_reason")


def validate_gloam_bridge_probe(obj, strict=False):
    code = C.BRIDGE_ABSENT_PLUGIN
    ch = RS.check_required(obj, BRIDGE_PROBE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, BRIDGE_PROBE_ALLOWED, code, strict)
    ch += _str(obj, "probe_id", code, "br::")
    ch += _str(obj, "operation_id", code, "br::")
    # honesty: the bridge targets Gloamstead on 5.8; a different engine is WF1023.
    ch.append(("br::target_engine", obj.get("target_engine") == BRIDGE_ENGINE,
               "bridge target_engine must be {!r} (got {!r})".format(
                   BRIDGE_ENGINE, obj.get("target_engine")), C.BRIDGE_WRONG_ENGINE))
    # a bridge pointed at WorldForge instead of Gloamstead is WF1024.
    ch.append(("br::target_project_gloam",
               isinstance(obj.get("target_project"), str)
               and "gloam" in obj.get("target_project", "").lower(),
               "bridge target_project must be a Gloamstead project (got {!r})".format(
                   obj.get("target_project")), C.BRIDGE_WRONG_PROJECT))
    ch += RS.check_enum(obj, "probe_result", BRIDGE_RESULTS, code, prefix="br::")
    ch += _bool(obj, "plugin_present", code, "br::")
    ch += _bool(obj, "map_present", code, "br::")
    entries = obj.get("evidence_entries") if _is_list(obj, "evidence_entries") else None
    ch.append(("br::evidence_list", entries is not None,
               "evidence_entries must be a list", code))
    # empty evidence in a probe that claims to have looked is WF1028.
    ch.append(("br::evidence_nonempty", bool(entries),
               "bridge probe must carry >= 1 evidence entry", C.BRIDGE_EMPTY_EVIDENCE))
    # no absolute-path leak anywhere in the evidence (WF1029).
    leaks = [e for e in (entries or []) if not _no_abs_path(e)]
    ch.append(("br::no_abs_path_leak", not leaks,
               "bridge evidence leaks absolute path(s): {}".format(leaks[:2]),
               C.BRIDGE_ABSOLUTE_PATH_LEAK))
    result = obj.get("probe_result")
    # honesty: a "ready" claim must be backed by a present plugin (WF1025)...
    ch.append(("br::ready_implies_plugin",
               not (result == "ready" and obj.get("plugin_present") is not True),
               "probe_result=ready but plugin_present is not True", C.BRIDGE_ABSENT_PLUGIN))
    # ...and a present map (WF1027).
    ch.append(("br::ready_implies_map",
               not (result == "ready" and obj.get("map_present") is not True),
               "probe_result=ready but map_present is not True", C.BRIDGE_MAP_MISSING))
    # a rejected dry probe must state a reason (keeps rejection auditable).
    ch.append(("br::rejected_has_reason",
               not (result == "rejected_dry_probe"
                    and not (isinstance(obj.get("rejection_reason"), str)
                             and obj.get("rejection_reason", "").strip())),
               "rejected_dry_probe must carry a non-empty rejection_reason", code))
    ch += _schema_version(obj, RT_GLOAM_BRIDGE, code, "br::")
    return ch


def _example_gloam_bridge_probe(**over):
    d = {
        "probe_id": "gloam_bridge_dry_probe",
        "operation_id": "op_v2_5_gloam_bridge_0001",
        "target_engine": "5.8",
        "target_project": "Gloamstead5_8",
        "probe_result": "rejected_dry_probe",
        "rejection_reason": "v2.5 lays the bridge contract only; no courtyard authored",
        "plugin_present": False,
        "map_present": False,
        "evidence_entries": ["procedural/reports/ue5_8/gloam/bridge_probe_report.json"],
        "created_by": "worldforge.v2.5",
        "created_at": AUTHORING_TS,
        "schema_version": RT_GLOAM_BRIDGE,
        "report_type": RT_GLOAM_BRIDGE,
    }
    d.update(over)
    return d


# =========================================================================== #
# 7. TransitionBaseline (WF1031/WF1032/WF1033) — the one-time 5.8 baseline
#    evidence index. Every indexed report must be tagged 5.8 and live under the
#    ue5_8 subtree; a 5.7 report or a ue5_7 path is contamination.
# =========================================================================== #
BASELINE_REQUIRED = (
    "index_id", "engine_minor", "entries", "entry_count", "schema_version",
)
BASELINE_ALLOWED = BASELINE_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes")
_BASELINE_ENTRY_REQUIRED = ("report_path", "engine_minor", "report_type")


def validate_transition_baseline(obj, strict=False):
    code = C.TRANSITION_REPORT_INTEGRITY_FAILED
    ch = RS.check_required(obj, BASELINE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, BASELINE_ALLOWED, code, strict)
    ch += _str(obj, "index_id", code, "bl::")
    minor = obj.get("engine_minor")
    ch.append(("bl::engine_minor_8",
               isinstance(minor, int) and not isinstance(minor, bool) and minor == 8,
               "baseline engine_minor must be 8 (got {!r})".format(minor),
               C.EVIDENCE_ENGINE_MISMATCH))
    entries = obj.get("entries") if _is_list(obj, "entries") else None
    ch.append(("bl::entries_nonempty", bool(entries),
               "entries must be a non-empty list", code))
    for i, e in enumerate(entries or []):
        p = "bl::[{}]::".format(i)
        if not isinstance(e, dict):
            ch.append((p + "is_dict", False, "entry must be a dict", code))
            continue
        for f in _BASELINE_ENTRY_REQUIRED:
            ch.append((p + f + "_present", f in e, "entry missing {}".format(f), code))
        em = e.get("engine_minor")
        # honesty: every entry must be tagged with the baseline's engine (WF1031).
        ch.append((p + "engine_matches_index", em == minor,
                   "entry engine_minor {!r} != baseline {!r}".format(em, minor),
                   C.EVIDENCE_ENGINE_MISMATCH))
        # honesty: a 5.7-tagged report in a 5.8 baseline is contamination (WF1032)...
        ch.append((p + "not_5_7_tagged", em != 7,
                   "5.8 baseline contaminated with a 5.7-tagged report", C.EVIDENCE_5_7_CONTAMINATION))
        rp = e.get("report_path")
        ch.append((p + "path_rel", _no_abs_path(rp),
                   "report_path must be relative (got {!r})".format(rp), code))
        # ...as is any path drawn from the frozen ue5_7 evidence subtree (WF1033).
        ch.append((p + "not_from_ue5_7_tree",
                   not (isinstance(rp, str) and REPORTS_5_7_REL in rp.replace("\\", "/")),
                   "baseline entry copied from the ue5_7 evidence tree: {!r}".format(rp),
                   C.EVIDENCE_COPIED_FROM_OLD_ENGINE))
    exp = obj.get("entry_count")
    ch += _int(obj, "entry_count", code, "bl::", allow_zero=False)
    if isinstance(exp, int) and not isinstance(exp, bool) and entries is not None:
        ch.append(("bl::count_matches", len(entries) == exp,
                   "entry_count {} != len(entries) {}".format(exp, len(entries)), code))
    ch += _schema_version(obj, RT_BASELINE, code, "bl::")
    return ch


def _example_transition_baseline(**over):
    d = {
        "index_id": "baseline_ue58_v2_5",
        "engine_minor": 8,
        "entry_count": 2,
        "entries": [
            {"report_path": "procedural/reports/ue5_8/validate_conversion_manifest_report.json",
             "engine_minor": 8, "report_type": RT_CONVERSION_MANIFEST},
            {"report_path": "procedural/reports/ue5_8/pluginbuild_report.json",
             "engine_minor": 8, "report_type": RT_PLUGIN_BUILD},
        ],
        "created_by": "worldforge.v2.5",
        "created_at": AUTHORING_TS,
        "schema_version": RT_BASELINE,
        "report_type": RT_BASELINE,
    }
    d.update(over)
    return d


# =========================================================================== #
# Registry — validator + valid example + known-bad example per contract.
# =========================================================================== #
CONTRACTS = {
    "EngineIdentity": (
        validate_engine_identity, _example_engine_identity,
        # engine_major 4 -> engine version mismatch (WF1013).
        lambda: _example_engine_identity(engine_major=4)),
    "CapabilityManifest": (
        validate_capability_manifest, _example_capability_manifest,
        # a required capability marked unavailable -> WF1011.
        lambda: _example_capability_manifest(capabilities=[
            {"capability_id": "WorldForgeRuntime", "kind": "plugin_module",
             "required": True, "available": False,
             "required_version": "2.5.0", "actual_version": None}])),
    "ConversionManifest": (
        validate_conversion_manifest, _example_conversion_manifest,
        # a map that loses an actor with no accounted deletion -> WF1014.
        lambda: _example_conversion_manifest(expected_map_count=1, maps=[
            {"map_path": "Content/Maps/encounter_loop_world.umap",
             "actors_before": 214, "actors_after": 210,
             "accounted_deletions": 0, "churn_class": "expected_resave"}])),
    "PluginBuildReport": (
        validate_plugin_build_report, _example_plugin_build_report,
        # overall_ok claimed while the build failed -> WF1017.
        lambda: _example_plugin_build_report(overall_ok=True, build_result="failed")),
    "TransitionRegressionReport": (
        validate_transition_regression_report, _example_transition_regression_report,
        # regression_free claimed with a worldforge_regression diff -> WF1022.
        lambda: _example_transition_regression_report(regression_free=True, diffs=[
            {"map_path": "Content/Maps/encounter_loop_world.umap",
             "classification": "worldforge_regression"}])),
    "GloamBridgeProbe": (
        validate_gloam_bridge_probe, _example_gloam_bridge_probe,
        # "ready" claim with no plugin present -> WF1025.
        lambda: _example_gloam_bridge_probe(probe_result="ready", plugin_present=False,
                                            map_present=True)),
    "TransitionBaseline": (
        validate_transition_baseline, _example_transition_baseline,
        # a 5.7-tagged entry laundered into the 5.8 baseline -> WF1032.
        lambda: _example_transition_baseline(entry_count=1, entries=[
            {"report_path": "procedural/reports/ue5_8/foo.json",
             "engine_minor": 7, "report_type": RT_PLUGIN_BUILD}])),
}

CONTRACT_GROUPS = {
    "identity_capability": ("EngineIdentity", "CapabilityManifest"),
    "conversion_build": ("ConversionManifest", "PluginBuildReport"),
    "regression_bridge": ("TransitionRegressionReport", "GloamBridgeProbe"),
    "baseline": ("TransitionBaseline",),
}

KNOWN_BAD_OWNING_CODE = {
    "EngineIdentity": C.ENGINE_VERSION_MISMATCH,
    "CapabilityManifest": C.CAPABILITY_UNAVAILABLE,
    "ConversionManifest": C.CONVERSION_ACTOR_LOSS,
    "PluginBuildReport": C.BUILD_FAILED,
    "TransitionRegressionReport": C.REGRESSION_WORLDFORGE_REGRESSION,
    "GloamBridgeProbe": C.BRIDGE_ABSENT_PLUGIN,
    "TransitionBaseline": C.EVIDENCE_5_7_CONTAMINATION,
}

# The set of transition failure codes this milestone owns (WF1011–1060).
TRANSITION_CODES = tuple(
    v for k, v in vars(C).items()
    if not k.startswith("_") and isinstance(v, str)
    and 1011 <= (int(v[2:6].rstrip("_")) if v[2:6].rstrip("_").isdigit() else -1) <= 1060
)
