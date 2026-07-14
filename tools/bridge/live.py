#!/usr/bin/env python3
"""tools/bridge/live.py — v2.5.1 LIVE cross-repository bridge contract.

The v2.5 bridge shipped a *rejecting dry probe* (probe.py): it proves the request/
response shape offline and honestly refuses to claim anything about a far side.
That is a NEGATIVE test and it stays one. It can never satisfy DoD #17, which
requires a REAL run against a SEPARATE UE 5.8 project.

This module is the LIVE counterpart. Where ``dry_probe`` asserts "nothing ran",
``LiveBridgeReport`` may only be built from evidence that a real editor process
actually produced, and ``validate_live_bridge_report`` is a POSITIVE gate: it
fails closed unless the far side genuinely executed.

Why a separate schema (``wf.transition.gloam_bridge_live.v1``) rather than reusing
GloamBridgeProbe:

  * GloamBridgeProbe requires ``target_project`` to contain "gloam" (WF1024). The
    fixture far side is honestly NOT Gloamstead — naming it "Gloam*" to slip past
    a substring check is exactly the laundering this lane exists to prevent.
  * GloamBridgeProbe has no vocabulary for the things a live run must prove:
    observed runtime engine, plugin *loaded* (not merely present), capability
    handshake, operation completion, independently re-verified evidence hashes.
  * transition_contracts.py is not this lane's to edit.

The live report therefore carries ``is_gloamstead_target`` and ``fixture_standin``
so the report states, in its own body, that the far side is a stand-in for the
Gloamstead repo and not Gloamstead itself. No Gloamstead compatibility is claimed.

Failure codes are drawn ONLY from the existing WF1011-WF1039 transition band; the
bridge band WF1023-WF1030 carries the bridge-specific semantics. No new codes.

Self-contained: stdlib + the shared report_meta/failure_codes infra. Never launches
a process (the runner does that), never writes a file.
"""

import re
import sys
from pathlib import Path

_PIPELINE = Path(__file__).resolve().parents[2] / "tools" / "pipeline"
if str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))

from failure_codes import FailureCode as C  # noqa: E402

from .schema import BRIDGE_ENGINE, EXIT_SUCCESS  # noqa: E402

# The live report schema. Deliberately distinct from RT_GLOAM_BRIDGE so a dry
# probe report can never be mistaken for — or relabelled as — a live one.
LIVE_SCHEMA_VERSION = "wf.transition.gloam_bridge_live.v1"

# execution_mode vocabulary. "live" is the ONLY value the positive gate accepts.
MODE_LIVE = "live"
MODE_DRY = "dry"
EXECUTION_MODES = (MODE_LIVE, MODE_DRY)

# Same absolute-path rule the dry probe uses, so both agree on "project-relative".
_ABS_PATH_RE = re.compile(r"^([A-Za-z]:[\\/]|[\\/])")

LIVE_REQUIRED = (
    "probe_id", "operation_id", "execution_mode",
    "target_repository", "resolved_target_repository",
    "target_commit", "resolved_target_commit",
    "target_project", "resolved_uproject",
    "declared_target_engine", "observed_runtime_engine",
    "plugin_present", "plugin_loaded", "capability_handshake_ok",
    "plugin_capability_manifest",
    "requested_operation", "operation_completed",
    "process_exit_status", "process_exit_code",
    "evidence_entries", "evidence_hashes", "evidence_count",
    "evidence_operation_id", "runtime_executed",
    "is_gloamstead_target", "fixture_standin",
    "schema_version",
)
LIVE_ALLOWED = LIVE_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
    "resolution_sources", "far_side_evidence", "operation_detail",
)


def _is_rel(value):
    """True iff value is a string carrying no absolute-path leak."""
    return isinstance(value, str) and not _ABS_PATH_RE.match(value.strip())


def engine_minor(version):
    """Parse a UE version string ("5.8.0-55116800+++UE5+Release-5.8") -> minor int.

    Returns None when the value is not a parseable UE version. Used to compare an
    OBSERVED runtime engine against the declared target without string-matching a
    whole build id.
    """
    if not isinstance(version, str):
        return None
    m = re.match(r"^\s*(\d+)\.(\d+)", version.strip())
    return int(m.group(2)) if m else None


def validate_live_bridge_report(obj, strict=False):
    """Return (name, ok, detail, code) checks for a LIVE bridge report.

    This is a POSITIVE gate: it is GREEN only when the far side genuinely ran. Every
    rule below is a way for a dishonest or degraded run to be caught, mapped to its
    owning code in the existing WF1011-WF1039 band.
    """
    ch = []
    gen = C.BRIDGE_ABSENT_PLUGIN  # generic shape code, mirroring the dry contract

    # ---- shape -------------------------------------------------------------
    missing = [k for k in LIVE_REQUIRED if k not in obj]
    ch.append(("live::required_fields", not missing,
               "missing required field(s): {}".format(missing[:6]), gen))
    if strict:
        unknown = [k for k in obj if k not in LIVE_ALLOWED]
        ch.append(("live::no_unknown_fields", not unknown,
                   "unknown field(s): {}".format(unknown[:6]), gen))
    ch.append(("live::schema_version",
               obj.get("schema_version") == LIVE_SCHEMA_VERSION,
               "schema_version must be {!r} (got {!r})".format(
                   LIVE_SCHEMA_VERSION, obj.get("schema_version")),
               C.TRANSITION_REPORT_INTEGRITY_FAILED))

    # ---- the live claim itself ---------------------------------------------
    # A dry/rejecting probe submitted to this gate dies here (WF1034): it is not
    # live and it never executed a runtime.
    ch.append(("live::execution_mode_live",
               obj.get("execution_mode") == MODE_LIVE,
               "execution_mode must be {!r} (got {!r}) — a dry probe cannot satisfy "
               "a live gate".format(MODE_LIVE, obj.get("execution_mode")),
               C.TRANSITION_REPORT_INTEGRITY_FAILED))
    ch.append(("live::runtime_executed",
               obj.get("runtime_executed") is True,
               "runtime_executed must be True — no live editor run, no live gate",
               C.TRANSITION_REPORT_INTEGRITY_FAILED))

    # ---- target repository / commit resolved across the boundary -----------
    ch.append(("live::target_repository_resolved",
               isinstance(obj.get("resolved_target_repository"), str)
               and bool(obj.get("resolved_target_repository", "").strip()),
               "far side must resolve the target repository", gen))
    ch.append(("live::target_repository_matches",
               obj.get("resolved_target_repository") == obj.get("target_repository"),
               "resolved_target_repository {!r} != requested {!r}".format(
                   obj.get("resolved_target_repository"), obj.get("target_repository")),
               C.BRIDGE_WRONG_PROJECT))
    commit = obj.get("resolved_target_commit")
    ch.append(("live::target_commit_resolved",
               isinstance(commit, str) and bool(re.fullmatch(r"[0-9a-f]{40}", commit or "")),
               "far side must resolve target_commit to a real 40-hex SHA (got {!r})".format(
                   commit), gen))

    # ---- correct .uproject selected ----------------------------------------
    ch.append(("live::uproject_selected",
               isinstance(obj.get("resolved_uproject"), str)
               and obj.get("resolved_uproject", "").endswith(".uproject"),
               "resolved_uproject must name the .uproject the editor actually opened "
               "(got {!r})".format(obj.get("resolved_uproject")),
               C.BRIDGE_WRONG_PROJECT))
    ch.append(("live::uproject_is_target_project",
               isinstance(obj.get("resolved_uproject"), str)
               and isinstance(obj.get("target_project"), str)
               and obj.get("resolved_uproject", "").rsplit("/", 1)[-1]
               == "{}.uproject".format(obj.get("target_project")),
               "editor opened {!r}, which is not target_project {!r}".format(
                   obj.get("resolved_uproject"), obj.get("target_project")),
               C.BRIDGE_WRONG_PROJECT))
    ch.append(("live::uproject_relative",
               _is_rel(obj.get("resolved_uproject")),
               "resolved_uproject must be target-project-relative (no machine path)",
               C.BRIDGE_ABSOLUTE_PATH_LEAK))

    # ---- observed engine: from the RUNNING editor, not a config file -------
    observed = obj.get("observed_runtime_engine")
    ch.append(("live::observed_engine_present",
               isinstance(observed, str) and bool(observed.strip()),
               "observed_runtime_engine must be reported by the running editor",
               C.BRIDGE_WRONG_ENGINE))
    ch.append(("live::observed_engine_is_5_8",
               engine_minor(observed) == engine_minor(BRIDGE_ENGINE),
               "observed_runtime_engine must be UE {} (got {!r})".format(
                   BRIDGE_ENGINE, observed),
               C.BRIDGE_WRONG_ENGINE))
    ch.append(("live::declared_engine_is_5_8",
               obj.get("declared_target_engine") == BRIDGE_ENGINE,
               "declared_target_engine must be {!r} (got {!r})".format(
                   BRIDGE_ENGINE, obj.get("declared_target_engine")),
               C.BRIDGE_WRONG_ENGINE))
    # The observed engine must corroborate the declared one — this is the rule that
    # turns "I targeted 5.8" into "5.8 actually ran".
    ch.append(("live::observed_matches_declared",
               engine_minor(observed) == engine_minor(obj.get("declared_target_engine")),
               "observed runtime engine {!r} contradicts declared target {!r}".format(
                   observed, obj.get("declared_target_engine")),
               C.EVIDENCE_ENGINE_MISMATCH))

    # ---- plugin present AND loaded -----------------------------------------
    ch.append(("live::plugin_present", obj.get("plugin_present") is True,
               "required plugin must be present in the target project",
               C.BRIDGE_ABSENT_PLUGIN))
    # Present-but-not-loaded is the classic false green: the .uplugin is on disk but
    # the module never initialised. That is WF1018, not WF1025.
    ch.append(("live::plugin_loaded", obj.get("plugin_loaded") is True,
               "required plugin must be LOADED in the running editor (present on disk "
               "is not loaded)", C.PLUGIN_LOAD_FAILED))

    # ---- capability handshake ----------------------------------------------
    manifest = obj.get("plugin_capability_manifest")
    ch.append(("live::capability_manifest_list", isinstance(manifest, list),
               "plugin_capability_manifest must be a list", gen))
    ch.append(("live::capability_manifest_nonempty", bool(manifest),
               "capability handshake must return >= 1 capability",
               C.CAPABILITY_UNAVAILABLE))
    unavailable = [c.get("capability_id") for c in (manifest or [])
                   if isinstance(c, dict) and c.get("available") is not True]
    ch.append(("live::capabilities_available", not unavailable,
               "capability handshake reported unavailable capabilities: {}".format(
                   unavailable[:4]), C.CAPABILITY_UNAVAILABLE))
    ch.append(("live::capability_handshake_ok",
               obj.get("capability_handshake_ok") is True,
               "plugin capability handshake must succeed", C.CAPABILITY_UNAVAILABLE))

    # ---- a real operation executed -----------------------------------------
    ch.append(("live::operation_completed",
               obj.get("operation_completed") is True,
               "the requested operation must actually complete on the far side",
               C.TRANSITION_REPORT_INTEGRITY_FAILED))
    ch.append(("live::process_exit_success",
               obj.get("process_exit_status") == EXIT_SUCCESS,
               "process_exit_status must be {!r} (got {!r})".format(
                   EXIT_SUCCESS, obj.get("process_exit_status")), gen))
    ch.append(("live::process_exit_code_zero",
               obj.get("process_exit_code") == 0,
               "process_exit_code must be 0 (got {!r})".format(obj.get("process_exit_code")),
               gen))

    # ---- evidence returned across the boundary -----------------------------
    entries = obj.get("evidence_entries")
    hashes = obj.get("evidence_hashes")
    ch.append(("live::evidence_list", isinstance(entries, list) and isinstance(hashes, list),
               "evidence_entries and evidence_hashes must be lists", gen))
    # THE rule that kills "process exited 0 but produced nothing" (WF1028).
    ch.append(("live::evidence_nonempty", bool(entries),
               "a completed live operation must return >= 1 evidence entry",
               C.BRIDGE_EMPTY_EVIDENCE))
    ch.append(("live::evidence_count_matches",
               obj.get("evidence_count") == len(entries or []),
               "evidence_count {!r} != len(evidence_entries) {}".format(
                   obj.get("evidence_count"), len(entries or [])),
               C.BRIDGE_EMPTY_EVIDENCE))
    ch.append(("live::evidence_count_positive",
               isinstance(obj.get("evidence_count"), int)
               and obj.get("evidence_count", 0) > 0,
               "evidence_count must be > 0", C.BRIDGE_EMPTY_EVIDENCE))
    ch.append(("live::evidence_hashes_paired",
               len(entries or []) == len(hashes or []),
               "every evidence entry must carry a hash ({} entries vs {} hashes)".format(
                   len(entries or []), len(hashes or [])),
               C.TRANSITION_REPORT_INTEGRITY_FAILED))
    ch.append(("live::evidence_hashes_wellformed",
               all(isinstance(h, str) and re.fullmatch(r"(sha256:)?[0-9a-f]{64}", h or "")
                   for h in (hashes or [])) and bool(hashes),
               "evidence hashes must be sha256 digests",
               C.TRANSITION_REPORT_INTEGRITY_FAILED))
    leaks = [e for e in (entries or []) if not _is_rel(e)]
    ch.append(("live::evidence_project_relative", not leaks,
               "evidence must be target-project-relative; leaks: {}".format(leaks[:2]),
               C.BRIDGE_ABSOLUTE_PATH_LEAK))
    # Evidence produced under a DIFFERENT operation is stale reuse (WF1026) — this is
    # what stops a passing run from being replayed forever.
    ch.append(("live::evidence_fresh",
               obj.get("evidence_operation_id") == obj.get("operation_id"),
               "evidence_operation_id {!r} != operation_id {!r} (stale/reused evidence)".format(
                   obj.get("evidence_operation_id"), obj.get("operation_id")),
               C.BRIDGE_STALE_PLUGIN))

    # ---- operation_id preserved end to end ---------------------------------
    far = obj.get("far_side_evidence") or {}
    if isinstance(far, dict) and far:
        # The id the FAR SIDE echoed back must be the id we sent. This is the
        # end-to-end continuity check (WF1030) — it crosses the boundary.
        ch.append(("live::operation_id_echoed",
                   far.get("operation_id") == obj.get("operation_id"),
                   "far side echoed operation_id {!r} != requested {!r}".format(
                       far.get("operation_id"), obj.get("operation_id")),
                   C.BRIDGE_OPERATION_ID_MISMATCH))
    ch.append(("live::operation_id_wellformed",
               isinstance(obj.get("operation_id"), str)
               and bool(obj.get("operation_id", "").strip()),
               "operation_id must be a non-empty string",
               C.BRIDGE_OPERATION_ID_MISMATCH))

    # ---- honesty breadcrumbs -----------------------------------------------
    # The fixture is NOT Gloamstead and the report must say so in its own body.
    ch.append(("live::fixture_standin_declared",
               obj.get("fixture_standin") is True
               and obj.get("is_gloamstead_target") is False,
               "the live report must declare the far side a fixture stand-in and NOT "
               "claim a Gloamstead target",
               C.TRANSITION_HYGIENE_FAILED))
    return ch


def example_live_report(**over):
    """A minimal VALID LiveBridgeReport, for dogfooding the gate and its negatives.

    This is a fixture for testing the CONTRACT, never evidence of a run: it is only
    ever passed to validate_live_bridge_report() by the gate's own dogfood, and is
    never written to a report path. Overrides let a caller model each dishonest
    report the gate must reject.
    """
    d = {
        "probe_id": "gloam_bridge_live_run",
        "operation_id": "op_example_0001",
        "execution_mode": MODE_LIVE,
        "target_repository": "WF-BridgeFixture58",
        "resolved_target_repository": "WF-BridgeFixture58",
        "target_commit": "0" * 40,
        "resolved_target_commit": "0" * 40,
        "target_project": "WFBridgeFixture58",
        "resolved_uproject": "WFBridgeFixture58.uproject",
        "declared_target_engine": BRIDGE_ENGINE,
        "observed_runtime_engine": "5.8.0-55116800+++UE5+Release-5.8",
        "plugin_present": True,
        "plugin_loaded": True,
        "capability_handshake_ok": True,
        "plugin_capability_manifest": [
            {"capability_id": "WorldForgeCore.MaterialRecipeDataAsset",
             "available": True, "evidence": "present in reflection registry"},
        ],
        "requested_operation": "materialize_recipe_asset",
        "operation_completed": True,
        "process_exit_status": EXIT_SUCCESS,
        "process_exit_code": 0,
        "evidence_entries": ["Content/WFBridge/WFBridgeRecipe_op_example_0001.uasset"],
        "evidence_hashes": ["a" * 64],
        "evidence_count": 1,
        "evidence_operation_id": "op_example_0001",
        "runtime_executed": True,
        "is_gloamstead_target": False,
        "fixture_standin": True,
        "far_side_evidence": {"operation_id": "op_example_0001"},
        "schema_version": LIVE_SCHEMA_VERSION,
        "report_type": LIVE_SCHEMA_VERSION,
        "created_by": "worldforge.v2.5.1",
        "created_at": "2026-07-14T00:00:00+00:00",
    }
    d.update(over)
    return d


def evidence_belongs_to(entries, project_root_names):
    """Return evidence entries that do NOT belong to the target project.

    ``project_root_names`` is the set of top-level directories the target project
    legitimately owns (e.g. {"Content", "Saved", "Config", "Plugins"}). An entry
    rooted anywhere else came from another project and must not be counted as this
    operation's evidence (WF1024).
    """
    foreign = []
    for e in entries or []:
        if not isinstance(e, str):
            foreign.append(e)
            continue
        head = e.replace("\\", "/").strip("/").split("/", 1)[0]
        if head not in project_root_names:
            foreign.append(e)
    return foreign
