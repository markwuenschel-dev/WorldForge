#!/usr/bin/env python3
"""operator_contracts.py — WorldForge v2.1 OperatorForge strict-schema spine.

v2.1 turns WorldForge's evidence sprawl (v1.6z traversal, v1.7 NPC, v1.8 combat,
v1.9 reward, v2.0 vertical slice + package proof) into an operator-readable
control surface: pack/scenario/evidence/failure/asset/route views, a safe command
launcher, and run diffs. This module holds the strict contracts that define those
operator artifacts and prove — at authoring time, before any dashboard or index
exists — that their *shape* is coherent and cannot launder stale/missing/unknown
evidence into a green view.

Design mirrors slice_contracts.py exactly (the v2.0 spine):
    * frozen tuple enums (bounded taxonomy, one source of truth)
    * ``X_REQUIRED`` / ``X_ALLOWED`` field-name tuples
    * ``validate_X(obj, strict=False)`` returning a list of
      ``(check_name, ok, detail, failure_code)`` tuples — the exact shape
      ValidationReport.check consumes — built from the shared runtime_schema (RS)
      helpers plus domain-specific cross-field checks
    * ``_example_X(**over)`` canonical-valid factories (``d.update(over)`` spawns
      known-bad variants for the negatives/fuzz suites)
    * a ``CONTRACTS`` registry pairing each validator with a valid + known-bad
      example, and ``KNOWN_BAD_OWNING_CODE`` naming the code each known-bad must
      be rejected FOR (rejection for the wrong reason is not real coverage)

The honesty invariants (anti-fake-green) live INSIDE the validators. OperatorForge
INDEXES evidence; it does not make stale evidence true, so these invariants guard
the *index*, not the underlying runtime:
    * an OperatorReportIndex may only report integrity_result=pass with an EMPTY
      missing_evidence AND stale_evidence -> WF717/WF716
    * an OperatorPackCard for a v2.0 slice pack that is passing (empty
      failure_codes) MUST carry real package proof -> WF725
    * an OperatorScenarioCard cannot claim runtime_status=pass with no
      report_paths -> WF714
    * an EvidenceTrace verdict=pass requires >= 1 supporting report, and any
      stale_inputs force verdict=blocked -> WF721/WF716
    * a FailureCodeIndex row of blocking/fatal severity MUST carry a suggested
      next action -> WF722
    * an AssetOwnershipView must keep the four ownership classes distinct and may
      never mark third_party/human-owned assets destroyable -> WF723
    * a RouteWalkabilityView may NOT claim a proved grounded_navmesh traversal
      (headless UE navmesh remains an honest path_missing limit), and flight/
      teleport are never valid objective access -> WF724
    * an OperatorCommandRequest may only be allowed for an allowlisted command;
      destructive commands are blocked; full-matrix reruns require an explicit
      reason; a write command run without dry_run needs a reason -> WF726/729/728/727
    * an OperatorCommandResult with a nonzero exit_code cannot be status=pass, and
      pass requires created outputs + zero blocking failure codes -> WF730
    * an OperatorDiffReport must compare two DISTINCT runs -> WF731
    * a KnownRegressionRegistry active row needs a reproduction command; a
      resolved row needs resolution notes -> WF732

This module is schema-only: it validates the *structure and internal coherence*
of a record. Cross-record resolution (does a report_path exist on disk? does a
failure_code resolve to the real registry?) is the job of the Wave-2 index
validators, which have the filesystem in hand. Stdlib only; no jsonschema (the
house style is hand-rolled field checks via RS).
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_schema as RS  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402

# --------------------------------------------------------------------------- #
# schema_version / report_type dotted namespaces (wf.operator.<type>.v1)
# --------------------------------------------------------------------------- #
RT_REPORT_INDEX = "wf.operator.report_index.v1"
RT_PACK_CARD = "wf.operator.pack_card.v1"
RT_SCENARIO_CARD = "wf.operator.scenario_card.v1"
RT_EVIDENCE_TRACE = "wf.operator.evidence_trace.v1"
RT_FAILURE_CODE_INDEX = "wf.operator.failure_code_index.v1"
RT_ASSET_OWNERSHIP_VIEW = "wf.operator.asset_ownership_view.v1"
RT_ROUTE_WALKABILITY_VIEW = "wf.operator.route_walkability_view.v1"
RT_COMMAND_REQUEST = "wf.operator.command_request.v1"
RT_COMMAND_RESULT = "wf.operator.command_result.v1"
RT_DIFF_REPORT = "wf.operator.diff_report.v1"
RT_KNOWN_REGRESSION = "wf.operator.known_regression.v1"

# --------------------------------------------------------------------------- #
# Bounded taxonomy (one source of truth).
# --------------------------------------------------------------------------- #
# Index/trace integrity verdicts. "blocked" is the honest verdict when evidence
# is stale or missing — never "pass".
INTEGRITY_RESULTS = ("pass", "fail", "blocked")

# Per-facet status vocabulary for scenario cards. "absent" = no evidence exists
# for this facet (honest gap, not a failure); "not_run" = the facet was not
# exercised; never conflate either with "pass".
FACET_STATUS = ("pass", "fail", "blocked", "absent", "not_run")

# Evidence-trace verdict + claim-status share the integrity vocabulary.
TRACE_VERDICTS = INTEGRITY_RESULTS

# FailureCodeIndex severity + status vocabularies (handoff §7.5).
FC_SEVERITIES = ("info", "warning", "blocking", "fatal", "unknown")
FC_STATUSES = ("active", "resolved", "expected_negative", "regression", "unknown")
FC_BLOCKING_SEVERITIES = ("blocking", "fatal")

# The four ownership classes — MUST remain distinct (handoff §7.6). Houdini
# generated outputs, Houdini source HDAs, Megascans raw source, and WorldForge
# generated metadata never collapse into one class.
OWNERSHIP_CLASSES = ("generated_owned", "project_owned", "third_party_owned", "human_owned")
# Classes whose assets WorldForge must never destroy/regenerate (repair safety).
PROTECTED_OWNERSHIP_CLASSES = ("third_party_owned", "human_owned")
# Legal repair/destroy policies. "protected" = never auto-destroyed;
# "regenerate" = safe to destroy+rebuild (only for generated_owned).
REPAIR_DESTROY_POLICIES = ("protected", "regenerate", "manual_only")

# RouteWalkabilityView traversal modes. Only the two grounded WorldForge modes are
# valid PROVED objective access; grounded_navmesh remains an honest headless limit
# (path_missing) and flight/teleport are never grounded traversal.
TRAVERSAL_MODES = (
    "grounded_manual_waypoint", "grounded_worldforge_route",
    "grounded_navmesh", "flight", "teleport",
)
PROVED_TRAVERSAL_MODES = ("grounded_manual_waypoint", "grounded_worldforge_route")
# Per-facet route status vocabulary.
ROUTE_STATUS = ("pass", "fail", "blocked", "absent", "not_run")

# CommandResult status vocabulary.
COMMAND_RESULT_STATUS = ("pass", "failed", "blocked")

# --------------------------------------------------------------------------- #
# Command allowlist policy (handoff §9). ONE source of truth — the Wave-4 command
# launcher (operator_command.py) imports these; the contract enforces the shape.
# --------------------------------------------------------------------------- #
# Read-only / index commands: safe to run without dry-run or authorization. They
# only ever write under procedural/reports/operator/**.
OPERATOR_READ_ONLY_COMMANDS = (
    "operator-index-reports", "validate-operator-index", "operator-dashboard",
    "operator-smoke", "operator-evidence-view", "operator-failure-index",
    "operator-asset-ownership", "operator-route-view", "operator-diff-runs",
    "operator-negative-validators", "operator-report-integrity", "operator-hygiene",
    "operator-command-dry-run", "v2-1-shield",
)
# Targeted validation/rerun commands: real work, but bounded. A non-read-only
# command run for real (dry_run=false) requires an explicit reason.
OPERATOR_TARGETED_COMMANDS = (
    "vertical-slice-contracts", "validate-slice-scenarios", "validate-slice-traversal",
    "validate-slice-npc-combat", "validate-slice-rewards", "validate-slice-save-load",
    "validate-slice-evidence-index", "validate-slice-package",
    "v2-0-shield", "run-vertical-slice-smoke",
)
# Commands that require an explicit authorization reason (handoff §9): full matrix,
# package build, large UE runtime batch, cleanup, migration.
OPERATOR_AUTHORIZATION_COMMANDS = (
    "vertical-slice-runtime-matrix", "package-slice", "ue-runtime-batch",
    "artifact-cleanup", "report-migration",
)
# The subset that is a FULL scenario-matrix rerun (§9 full-matrix rule).
OPERATOR_FULL_MATRIX_COMMANDS = ("vertical-slice-runtime-matrix", "ue-runtime-batch")
# The complete allowlist an OperatorCommandRequest.command_id may name.
OPERATOR_COMMAND_ALLOWLIST = (
    OPERATOR_READ_ONLY_COMMANDS + OPERATOR_TARGETED_COMMANDS
    + OPERATOR_AUTHORIZATION_COMMANDS
)
# Forbidden-in-v2.1 destructive commands (§9). These are NOT allowlisted; a
# request naming one must have allowed=false and is rejected for WF729.
OPERATOR_DESTRUCTIVE_COMMANDS = (
    "git-push", "git-reset-hard", "git-clean", "delete-asset", "modify-umap",
    "modify-uasset", "change-engine-plugins", "download-marketplace-asset",
    "destructive-repair",
)
# A request's target_scenarios must be bounded unless it is a full-matrix command.
MAX_TARGET_SCENARIOS = 24

# The shared deterministic authoring timestamp (NOT wall-clock) for example/
# authoring records. Real operator artifacts stamp created_at="live" + a real sha.
AUTHORING_TS = "2026-07-10T00:00:00+00:00"

# Generated / report roots (repo-relative).
OPERATOR_REPORTS_REL = "procedural/reports/operator"
OPERATOR_INDEX_REL = "procedural/reports/operator/index"
OPERATOR_DASHBOARD_REL = "procedural/reports/operator/dashboard"
OPERATOR_DIFF_REL = "procedural/reports/operator/diff"
OPERATOR_COMMANDS_REL = "procedural/reports/operator/commands"

_WF_CODE_RE = re.compile(r"^WF\d{3}_[A-Z0-9_]+$")


# --------------------------------------------------------------------------- #
# small local helpers (mirror slice_contracts.py)
# --------------------------------------------------------------------------- #
def _str(obj, field, code, prefix):
    """A required id/path/version string: present, a str, and non-empty."""
    ch = RS.check_type(obj, field, str, code, prefix=prefix)
    v = obj.get(field) if isinstance(obj, dict) else None
    ch.append(("{}{}_nonempty".format(prefix, field),
               isinstance(v, str) and bool(v.strip()),
               "{} must be a non-empty string".format(field), code))
    return ch


def _bool(obj, field, code, prefix):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, bool)
    return [("{}{}_bool".format(prefix, field), ok,
             "{} must be an explicit boolean (got {!r})".format(field, v), code)]


def _int(obj, field, code, prefix, allow_zero=True):
    """A required integer field: a real number, integer-valued, and >=0 (or >0)."""
    ch = RS.check_positive_number(obj, field, code, prefix=prefix, allow_zero=allow_zero)
    v = obj.get(field) if isinstance(obj, dict) else None
    is_int = RS.is_number(v) and float(v).is_integer()
    ch.append(("{}{}_integer".format(prefix, field), is_int,
               "{} must be an integer (got {!r})".format(field, v), code))
    return ch


def _list_of_str(obj, field, code, prefix, min_len=0):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, list) and len(v) >= min_len and all(isinstance(x, str) for x in v)
    return [("{}{}_str_list".format(prefix, field), ok,
             "{} must be a list of >= {} strings".format(field, min_len), code)]


def _is_list(obj, field):
    return isinstance(obj.get(field), list) if isinstance(obj, dict) else False


def _schema_version(obj, expected, code, prefix):
    sv = obj.get("schema_version") if isinstance(obj, dict) else None
    return [("{}schema_version".format(prefix), sv == expected,
             "schema_version must be {!r} (got {!r})".format(expected, sv), code)]


# --------------------------------------------------------------------------- #
# 1. OperatorReportIndex (WF711)  — the canonical index over all evidence
# --------------------------------------------------------------------------- #
REPORT_INDEX_REQUIRED = (
    "index_id", "created_at", "git_sha", "repo_status", "source_roots",
    "report_count", "scenario_count", "pack_count", "map_count",
    "failure_code_count", "evidence_categories", "missing_evidence",
    "stale_evidence", "integrity_result", "schema_version",
)
REPORT_INDEX_ALLOWED = REPORT_INDEX_REQUIRED + (
    "meta", "report_type", "created_by", "notes", "source_milestones",
)
_INDEX_COUNTS = ("report_count", "scenario_count", "pack_count", "map_count",
                 "failure_code_count")


def validate_report_index(obj, strict=False):
    code = C.OPERATOR_INDEX_SCHEMA_INVALID
    ch = RS.check_required(obj, REPORT_INDEX_REQUIRED, code)
    ch += RS.check_no_unknown(obj, REPORT_INDEX_ALLOWED, code, strict)
    ch += _str(obj, "index_id", code, "ori::")
    ch += _str(obj, "created_at", code, "ori::")
    ch += _str(obj, "git_sha", code, "ori::")
    ch += _str(obj, "repo_status", code, "ori::")
    ch += _list_of_str(obj, "source_roots", C.OPERATOR_SOURCE_ROOT_MISSING, "ori::", min_len=1)
    for f in _INDEX_COUNTS:
        ch += _int(obj, f, code, "ori::", allow_zero=True)
    for f in ("evidence_categories", "missing_evidence", "stale_evidence"):
        ch.append(("ori::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    ch += RS.check_enum(obj, "integrity_result", INTEGRITY_RESULTS, code, prefix="ori::")

    # --- honesty: a live index requires a real sha; git_sha 'unknown' is stale ---
    if obj.get("created_at") == "live":
        sha = obj.get("git_sha")
        ch.append(("ori::live_requires_real_sha",
                   isinstance(sha, str) and sha and sha != "unknown",
                   "created_at='live' requires a real git_sha (got {!r})".format(sha),
                   C.OPERATOR_STALE_EVIDENCE))
    # --- honesty: integrity_result=pass requires zero missing + zero stale -------
    passing = obj.get("integrity_result") == "pass"
    if passing:
        ch.append(("ori::pass_requires_no_missing",
                   _is_list(obj, "missing_evidence") and len(obj["missing_evidence"]) == 0,
                   "integrity_result=pass requires an empty missing_evidence list",
                   C.OPERATOR_MISSING_EVIDENCE))
        ch.append(("ori::pass_requires_no_stale",
                   _is_list(obj, "stale_evidence") and len(obj["stale_evidence"]) == 0,
                   "integrity_result=pass requires an empty stale_evidence list",
                   C.OPERATOR_STALE_EVIDENCE))
    ch += _schema_version(obj, RT_REPORT_INDEX, code, "ori::")
    return ch


def _example_report_index(**over):
    d = {
        "index_id": "operator_report_index",
        "created_at": "live",
        "git_sha": "0000000000000000000000000000000000000000",
        "repo_status": "clean",
        "source_roots": ["procedural/reports/slice", "procedural/reports/rewards"],
        "report_count": 42,
        "scenario_count": 24,
        "pack_count": 1,
        "map_count": 12,
        "failure_code_count": 0,
        "evidence_categories": ["runtime", "traversal", "npc", "combat", "reward",
                                "save_load", "package"],
        "missing_evidence": [],
        "stale_evidence": [],
        "integrity_result": "pass",
        "source_milestones": ["v2.0", "v1.9", "v1.8", "v1.7", "v1.6z"],
        "created_by": "worldforge.v2.1",
        "schema_version": RT_REPORT_INDEX,
        "report_type": RT_REPORT_INDEX,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 2. OperatorPackCard (WF719)  — one pack's overview + package proof
# --------------------------------------------------------------------------- #
PACK_CARD_REQUIRED = (
    "pack_id", "pack_name", "version", "source_milestone", "scenario_count",
    "map_count", "biomes", "mission_archetypes", "pressure_profiles",
    "package_report_path", "package_exists", "package_size_bytes",
    "runtime_result_summary", "shield_result_summary", "evidence_index_path",
    "failure_codes", "schema_version",
)
PACK_CARD_ALLOWED = PACK_CARD_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)
# Packs whose source_milestone requires real package proof (a passing card MUST
# carry package_exists + size). v2.0 slice packs are the canonical case.
PACKAGE_REQUIRED_MILESTONES = ("v2.0",)


def validate_pack_card(obj, strict=False):
    code = C.OPERATOR_PACK_INDEX_INVALID
    ch = RS.check_required(obj, PACK_CARD_REQUIRED, code)
    ch += RS.check_no_unknown(obj, PACK_CARD_ALLOWED, code, strict)
    for f in ("pack_id", "pack_name", "version", "source_milestone",
              "package_report_path", "runtime_result_summary",
              "shield_result_summary", "evidence_index_path"):
        ch += _str(obj, f, code, "opc::")
    ch += _int(obj, "scenario_count", code, "opc::", allow_zero=False)
    ch += _int(obj, "map_count", code, "opc::", allow_zero=False)
    ch += _int(obj, "package_size_bytes", code, "opc::", allow_zero=True)
    ch += _bool(obj, "package_exists", C.OPERATOR_PACKAGE_PROOF_MISSING, "opc::")
    for f in ("biomes", "mission_archetypes", "pressure_profiles"):
        ch += _list_of_str(obj, f, code, "opc::", min_len=1)
    fc_is_list = _is_list(obj, "failure_codes")
    ch.append(("opc::failure_codes_list", fc_is_list, "failure_codes must be a list", code))

    # --- honesty: a passing v2.0 slice pack MUST carry real package proof --------
    passing = fc_is_list and len(obj.get("failure_codes") or []) == 0
    if passing and obj.get("source_milestone") in PACKAGE_REQUIRED_MILESTONES:
        exists = obj.get("package_exists") is True
        size = obj.get("package_size_bytes")
        path = obj.get("package_report_path")
        ch.append(("opc::pass_requires_package_proof",
                   exists and RS.is_number(size) and size > 0
                   and isinstance(path, str) and bool(path.strip()),
                   "a passing {} pack requires package_exists=true, "
                   "package_size_bytes>0 and a package_report_path".format(
                       obj.get("source_milestone")),
                   C.OPERATOR_PACKAGE_PROOF_MISSING))
    ch += _schema_version(obj, RT_PACK_CARD, code, "opc::")
    return ch


def _example_pack_card(**over):
    d = {
        "pack_id": "worldforge_vertical_slice",
        "pack_name": "WorldForge Vertical Slice",
        "version": "2.0",
        "source_milestone": "v2.0",
        "scenario_count": 24,
        "map_count": 12,
        "biomes": ["desert", "forest"],
        "mission_archetypes": ["reach_objective", "recover_item", "clear_encounter"],
        "pressure_profiles": ["baseline", "high"],
        "package_report_path": "procedural/reports/slice/package/slice_package_report.json",
        "package_exists": True,
        "package_size_bytes": 524288000,
        "runtime_result_summary": "24/24 slice_completed_runtime",
        "shield_result_summary": "v2-0-shield GREEN",
        "evidence_index_path": "procedural/reports/slice/integrity/slice_evidence_index.json",
        "failure_codes": [],
        "created_at": "live",
        "schema_version": RT_PACK_CARD,
        "report_type": RT_PACK_CARD,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 3. OperatorScenarioCard (WF720)  — one scenario's per-system status roll-up
# --------------------------------------------------------------------------- #
SCENARIO_CARD_REQUIRED = (
    "scenario_id", "pack_id", "map_id", "biome", "mission_archetype",
    "pressure_profile", "seed", "runtime_status", "traversal_status",
    "npc_status", "combat_status", "reward_status", "save_load_status",
    "package_status", "telemetry_paths", "report_paths", "failure_codes",
    "schema_version",
)
SCENARIO_CARD_ALLOWED = SCENARIO_CARD_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)
_CARD_FACETS = ("runtime_status", "traversal_status", "npc_status",
                "combat_status", "reward_status", "save_load_status",
                "package_status")


def validate_scenario_card(obj, strict=False):
    code = C.OPERATOR_SCENARIO_CARD_INVALID
    ch = RS.check_required(obj, SCENARIO_CARD_REQUIRED, code)
    ch += RS.check_no_unknown(obj, SCENARIO_CARD_ALLOWED, code, strict)
    for f in ("scenario_id", "pack_id", "map_id", "biome", "mission_archetype",
              "pressure_profile"):
        ch += _str(obj, f, code, "osc::")
    ch += _int(obj, "seed", code, "osc::", allow_zero=True)
    for f in _CARD_FACETS:
        ch += RS.check_enum(obj, f, FACET_STATUS, code, prefix="osc::")
    for f in ("telemetry_paths", "report_paths"):
        ch.append(("osc::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    fc_is_list = _is_list(obj, "failure_codes")
    ch.append(("osc::failure_codes_list", fc_is_list, "failure_codes must be a list", code))

    # --- honesty: runtime_status=pass requires >= 1 report path ------------------
    if obj.get("runtime_status") == "pass":
        ch.append(("osc::runtime_pass_requires_reports",
                   _is_list(obj, "report_paths") and len(obj["report_paths"]) > 0,
                   "runtime_status=pass requires >= 1 report_path",
                   C.OPERATOR_REPORT_PATH_MISSING))
        ch.append(("osc::runtime_pass_requires_telemetry",
                   _is_list(obj, "telemetry_paths") and len(obj["telemetry_paths"]) > 0,
                   "runtime_status=pass requires >= 1 telemetry_path",
                   C.OPERATOR_REPORT_PATH_MISSING))
    ch += _schema_version(obj, RT_SCENARIO_CARD, code, "osc::")
    return ch


def _example_scenario_card(**over):
    d = {
        "scenario_id": "vs_desert_reach_objective_baseline_s1",
        "pack_id": "worldforge_vertical_slice",
        "map_id": "L_desert_reach_objective_s1",
        "biome": "desert",
        "mission_archetype": "reach_objective",
        "pressure_profile": "baseline",
        "seed": 1,
        "runtime_status": "pass",
        "traversal_status": "pass",
        "npc_status": "pass",
        "combat_status": "pass",
        "reward_status": "pass",
        "save_load_status": "pass",
        "package_status": "pass",
        "telemetry_paths": [
            "procedural/reports/slice/runtime/slice_traversal_vs_desert_reach_objective_baseline_s1.json"],
        "report_paths": [
            "procedural/reports/slice/runtime/slice_runtime_vs_desert_reach_objective_baseline_s1.json"],
        "failure_codes": [],
        "created_at": "live",
        "schema_version": RT_SCENARIO_CARD,
        "report_type": RT_SCENARIO_CARD,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 4. EvidenceTrace (WF721)  — resolves one claim to its supporting evidence
# --------------------------------------------------------------------------- #
EVIDENCE_TRACE_REQUIRED = (
    "trace_id", "scenario_id", "claim", "claim_status", "supporting_reports",
    "supporting_telemetry", "supporting_save_load_proofs",
    "supporting_package_proofs", "source_milestones", "stale_inputs",
    "missing_inputs", "verdict", "failure_codes", "schema_version",
)
EVIDENCE_TRACE_ALLOWED = EVIDENCE_TRACE_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)
_TRACE_SUPPORT_LISTS = ("supporting_reports", "supporting_telemetry",
                        "supporting_save_load_proofs", "supporting_package_proofs")


def validate_evidence_trace(obj, strict=False):
    code = C.OPERATOR_EVIDENCE_TRACE_INVALID
    ch = RS.check_required(obj, EVIDENCE_TRACE_REQUIRED, code)
    ch += RS.check_no_unknown(obj, EVIDENCE_TRACE_ALLOWED, code, strict)
    ch += _str(obj, "trace_id", code, "oet::")
    ch += _str(obj, "scenario_id", code, "oet::")
    ch += _str(obj, "claim", code, "oet::")
    ch += RS.check_enum(obj, "claim_status", TRACE_VERDICTS, code, prefix="oet::")
    ch += RS.check_enum(obj, "verdict", TRACE_VERDICTS, code, prefix="oet::")
    for f in _TRACE_SUPPORT_LISTS + ("source_milestones", "stale_inputs", "missing_inputs"):
        ch.append(("oet::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    fc_is_list = _is_list(obj, "failure_codes")
    ch.append(("oet::failure_codes_list", fc_is_list, "failure_codes must be a list", code))

    # --- honesty: verdict=pass requires >= 1 supporting report -------------------
    if obj.get("verdict") == "pass":
        ch.append(("oet::pass_requires_supporting_report",
                   _is_list(obj, "supporting_reports") and len(obj["supporting_reports"]) > 0,
                   "verdict=pass requires >= 1 supporting_report",
                   C.OPERATOR_EVIDENCE_TRACE_INVALID))
        ch.append(("oet::pass_forbids_missing_inputs",
                   _is_list(obj, "missing_inputs") and len(obj["missing_inputs"]) == 0,
                   "verdict=pass requires an empty missing_inputs list",
                   C.OPERATOR_MISSING_EVIDENCE))
    # --- honesty: any stale input forces verdict=blocked, never pass -------------
    if _is_list(obj, "stale_inputs") and len(obj["stale_inputs"]) > 0:
        ch.append(("oet::stale_forces_blocked",
                   obj.get("verdict") == "blocked",
                   "stale_inputs present -> verdict must be 'blocked' (got {!r})".format(
                       obj.get("verdict")),
                   C.OPERATOR_STALE_EVIDENCE))
    ch += _schema_version(obj, RT_EVIDENCE_TRACE, code, "oet::")
    return ch


def _example_evidence_trace(**over):
    d = {
        "trace_id": "trace_vs_desert_reach_objective_baseline_s1_completed",
        "scenario_id": "vs_desert_reach_objective_baseline_s1",
        "claim": "scenario completed",
        "claim_status": "pass",
        "supporting_reports": [
            "procedural/reports/slice/runtime/slice_runtime_vs_desert_reach_objective_baseline_s1.json"],
        "supporting_telemetry": [
            "procedural/reports/slice/runtime/slice_traversal_vs_desert_reach_objective_baseline_s1.json"],
        "supporting_save_load_proofs": [
            "procedural/reports/slice/save_load/slice_save_load_vs_desert_reach_objective_baseline_s1.json"],
        "supporting_package_proofs": [
            "procedural/reports/slice/package/slice_package_report.json"],
        "source_milestones": ["v2.0", "v1.9"],
        "stale_inputs": [],
        "missing_inputs": [],
        "verdict": "pass",
        "failure_codes": [],
        "created_at": "live",
        "schema_version": RT_EVIDENCE_TRACE,
        "report_type": RT_EVIDENCE_TRACE,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 5. FailureCodeIndex (WF722)  — one row per failure code seen in reports
# --------------------------------------------------------------------------- #
FAILURE_CODE_INDEX_REQUIRED = (
    "failure_code", "namespace", "milestone", "severity", "meaning",
    "owning_validator", "known_causes", "suggested_next_actions",
    "related_reports", "first_seen", "last_seen", "status", "schema_version",
)
FAILURE_CODE_INDEX_ALLOWED = FAILURE_CODE_INDEX_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)


def validate_failure_code_index(obj, strict=False):
    code = C.OPERATOR_FAILURE_INDEX_INVALID
    ch = RS.check_required(obj, FAILURE_CODE_INDEX_REQUIRED, code)
    ch += RS.check_no_unknown(obj, FAILURE_CODE_INDEX_ALLOWED, code, strict)
    for f in ("failure_code", "namespace", "milestone", "meaning",
              "owning_validator", "first_seen", "last_seen"):
        ch += _str(obj, f, code, "ofi::")
    ch += RS.check_enum(obj, "severity", FC_SEVERITIES, code, prefix="ofi::")
    ch += RS.check_enum(obj, "status", FC_STATUSES, code, prefix="ofi::")
    for f in ("known_causes", "suggested_next_actions", "related_reports"):
        ch.append(("ofi::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))

    # --- honesty: failure_code must be a well-formed WFnnn_* code ----------------
    fc = obj.get("failure_code")
    ch.append(("ofi::failure_code_well_formed",
               isinstance(fc, str) and bool(_WF_CODE_RE.match(fc)),
               "failure_code must match WFnnn_SHORT_NAME (got {!r})".format(fc),
               C.OPERATOR_UNKNOWN_FAILURE_CODE))
    # --- honesty: blocking/fatal severities MUST carry a suggested next action ---
    if obj.get("severity") in FC_BLOCKING_SEVERITIES:
        ch.append(("ofi::blocking_requires_next_action",
                   _is_list(obj, "suggested_next_actions")
                   and len(obj["suggested_next_actions"]) > 0,
                   "severity={} requires >= 1 suggested_next_action".format(obj.get("severity")),
                   C.OPERATOR_FAILURE_INDEX_INVALID))
    ch += _schema_version(obj, RT_FAILURE_CODE_INDEX, code, "ofi::")
    return ch


def _example_failure_code_index(**over):
    d = {
        "failure_code": "WF704_SLICE_REWARD_WITHOUT_MUTATION",
        "namespace": "SLICE",
        "milestone": "v2.0",
        "severity": "blocking",
        "meaning": "A reward was granted but no inventory/progression state mutated.",
        "owning_validator": "slice_contracts.validate_slice_runtime_report",
        "known_causes": ["reward bridge disabled", "save slot not written"],
        "suggested_next_actions": [
            "re-run validate-slice-rewards --strict",
            "inspect the scenario's runtime report reward_granted vs *_mutated flags"],
        "related_reports": ["procedural/reports/slice/runtime"],
        "first_seen": "2026-07-09",
        "last_seen": "2026-07-10",
        "status": "expected_negative",
        "created_at": "live",
        "schema_version": RT_FAILURE_CODE_INDEX,
        "report_type": RT_FAILURE_CODE_INDEX,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 6. AssetOwnershipView (WF723)  — one asset's ownership/provenance/policy
# --------------------------------------------------------------------------- #
ASSET_OWNERSHIP_REQUIRED = (
    "asset_id", "asset_path", "ownership_class", "source", "license_class",
    "used_by_maps", "used_by_scenarios", "repair_destroy_policy",
    "package_policy", "provenance_report_path", "status", "failure_codes",
    "schema_version",
)
ASSET_OWNERSHIP_ALLOWED = ASSET_OWNERSHIP_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)


def validate_asset_ownership_view(obj, strict=False):
    code = C.OPERATOR_ASSET_OWNERSHIP_INVALID
    ch = RS.check_required(obj, ASSET_OWNERSHIP_REQUIRED, code)
    ch += RS.check_no_unknown(obj, ASSET_OWNERSHIP_ALLOWED, code, strict)
    for f in ("asset_id", "asset_path", "source", "license_class",
              "package_policy", "provenance_report_path", "status"):
        ch += _str(obj, f, code, "aov::")
    ch += RS.check_enum(obj, "ownership_class", OWNERSHIP_CLASSES, code, prefix="aov::")
    ch += RS.check_enum(obj, "repair_destroy_policy", REPAIR_DESTROY_POLICIES, code, prefix="aov::")
    for f in ("used_by_maps", "used_by_scenarios"):
        ch.append(("aov::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    ch.append(("aov::failure_codes_list", _is_list(obj, "failure_codes"),
               "failure_codes must be a list", code))

    # --- honesty: protected ownership classes may NEVER be regenerate/destroyable -
    if obj.get("ownership_class") in PROTECTED_OWNERSHIP_CLASSES:
        ch.append(("aov::protected_class_not_regenerate",
                   obj.get("repair_destroy_policy") != "regenerate",
                   "{} assets must not have repair_destroy_policy=regenerate".format(
                       obj.get("ownership_class")),
                   C.OPERATOR_ASSET_OWNERSHIP_INVALID))
    ch += _schema_version(obj, RT_ASSET_OWNERSHIP_VIEW, code, "aov::")
    return ch


def _example_asset_ownership_view(**over):
    d = {
        "asset_id": "MI_Terrain_Desert_01",
        "asset_path": "Content/Materials/Terrain/MI_Terrain_Desert_01.uasset",
        "ownership_class": "generated_owned",
        "source": "worldforge.terrain_forge",
        "license_class": "worldforge_generated",
        "used_by_maps": ["L_desert_reach_objective_s1"],
        "used_by_scenarios": ["vs_desert_reach_objective_baseline_s1"],
        "repair_destroy_policy": "regenerate",
        "package_policy": "include",
        "provenance_report_path": "procedural/reports/assets/mi_terrain_desert_01.json",
        "status": "ok",
        "failure_codes": [],
        "created_at": "live",
        "schema_version": RT_ASSET_OWNERSHIP_VIEW,
        "report_type": RT_ASSET_OWNERSHIP_VIEW,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 7. RouteWalkabilityView (WF724)  — one scenario's traversal/walkability proof
# --------------------------------------------------------------------------- #
ROUTE_VIEW_REQUIRED = (
    "map_id", "scenario_id", "traversal_mode", "walkability_report_path",
    "route_plan_path", "navmesh_probe_path", "objective_access_status",
    "cover_intrusion_status", "capsule_clearance_status", "slope_status",
    "step_status", "failure_codes", "schema_version",
)
ROUTE_VIEW_ALLOWED = ROUTE_VIEW_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)
_ROUTE_FACETS = ("objective_access_status", "cover_intrusion_status",
                 "capsule_clearance_status", "slope_status", "step_status")


def validate_route_walkability_view(obj, strict=False):
    code = C.OPERATOR_ROUTE_VIEW_INVALID
    ch = RS.check_required(obj, ROUTE_VIEW_REQUIRED, code)
    ch += RS.check_no_unknown(obj, ROUTE_VIEW_ALLOWED, code, strict)
    for f in ("map_id", "scenario_id", "walkability_report_path",
              "route_plan_path", "navmesh_probe_path"):
        ch += _str(obj, f, code, "orv::")
    ch += RS.check_enum(obj, "traversal_mode", TRAVERSAL_MODES, code, prefix="orv::")
    for f in _ROUTE_FACETS:
        ch += RS.check_enum(obj, f, ROUTE_STATUS, code, prefix="orv::")
    ch.append(("orv::failure_codes_list", _is_list(obj, "failure_codes"),
               "failure_codes must be a list", code))

    # --- truth boundary: a proved objective access requires a grounded WorldForge
    # mode. grounded_navmesh is an honest headless path_missing limit and
    # flight/teleport are never valid grounded traversal. -------------------------
    if obj.get("objective_access_status") == "pass":
        ch.append(("orv::proved_access_is_grounded_worldforge",
                   obj.get("traversal_mode") in PROVED_TRAVERSAL_MODES,
                   "objective_access_status=pass requires a proved grounded WorldForge "
                   "mode {} (got {!r}); grounded_navmesh/flight/teleport are not proved"
                   .format(PROVED_TRAVERSAL_MODES, obj.get("traversal_mode")),
                   C.OPERATOR_ROUTE_VIEW_INVALID))
    ch += _schema_version(obj, RT_ROUTE_WALKABILITY_VIEW, code, "orv::")
    return ch


def _example_route_walkability_view(**over):
    d = {
        "map_id": "L_desert_reach_objective_s1",
        "scenario_id": "vs_desert_reach_objective_baseline_s1",
        "traversal_mode": "grounded_worldforge_route",
        "walkability_report_path": "procedural/reports/ground/walkability_L_desert_reach_objective_s1.json",
        "route_plan_path": "procedural/reports/ground/route_plan_vs_desert_reach_objective_baseline_s1.json",
        "navmesh_probe_path": "procedural/reports/ground/navmesh_probe_L_desert_reach_objective_s1.json",
        "objective_access_status": "pass",
        "cover_intrusion_status": "pass",
        "capsule_clearance_status": "pass",
        "slope_status": "pass",
        "step_status": "pass",
        "failure_codes": [],
        "created_at": "live",
        "schema_version": RT_ROUTE_WALKABILITY_VIEW,
        "report_type": RT_ROUTE_WALKABILITY_VIEW,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 8. OperatorCommandRequest (WF726)  — a safe, bounded rerun/validation request
# --------------------------------------------------------------------------- #
COMMAND_REQUEST_REQUIRED = (
    "request_id", "created_at", "requested_by", "command_id", "command_args",
    "target_pack", "target_scenarios", "dry_run", "allowed", "reason",
    "expected_outputs", "schema_version",
)
COMMAND_REQUEST_ALLOWED = COMMAND_REQUEST_REQUIRED + (
    "meta", "report_type", "created_by", "notes",
)


def validate_command_request(obj, strict=False):
    code = C.OPERATOR_COMMAND_NOT_ALLOWLISTED
    ch = RS.check_required(obj, COMMAND_REQUEST_REQUIRED, code)
    ch += RS.check_no_unknown(obj, COMMAND_REQUEST_ALLOWED, code, strict)
    for f in ("request_id", "created_at", "requested_by", "command_id", "target_pack"):
        ch += _str(obj, f, code, "ocr::")
    for f in ("command_args", "target_scenarios", "expected_outputs"):
        ch.append(("ocr::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    ch += _bool(obj, "dry_run", C.OPERATOR_COMMAND_DRY_RUN_REQUIRED, "ocr::")
    ch += _bool(obj, "allowed", code, "ocr::")
    ch.append(("ocr::reason_is_str", isinstance(obj.get("reason"), str),
               "reason must be a string (may be empty for read-only)", code))

    cid = obj.get("command_id")
    allowed = obj.get("allowed") is True
    dry_run = obj.get("dry_run") is True
    reason = obj.get("reason") if isinstance(obj.get("reason"), str) else ""

    # --- honesty: a destructive command is forbidden — allowed MUST be false -----
    if cid in OPERATOR_DESTRUCTIVE_COMMANDS:
        ch.append(("ocr::destructive_blocked", not allowed,
                   "destructive command {!r} is forbidden in v2.1 — allowed must be false"
                   .format(cid), C.OPERATOR_DESTRUCTIVE_COMMAND_BLOCKED))
    else:
        # --- honesty: an allowed command MUST be on the allowlist ----------------
        ch.append(("ocr::allowed_requires_allowlisted",
                   (not allowed) or (cid in OPERATOR_COMMAND_ALLOWLIST),
                   "allowed=true requires command_id on the allowlist (got {!r})".format(cid),
                   C.OPERATOR_COMMAND_NOT_ALLOWLISTED))
        # --- honesty: a full-matrix command requires an explicit reason ----------
        if cid in OPERATOR_FULL_MATRIX_COMMANDS and allowed:
            ch.append(("ocr::full_matrix_requires_reason", bool(reason.strip()),
                       "a full-matrix command requires an explicit authorization reason",
                       C.OPERATOR_FULL_MATRIX_UNAUTHORIZED))
        # --- honesty: a non-read-only command run for real needs dry_run OR reason
        if cid not in OPERATOR_READ_ONLY_COMMANDS and allowed and not dry_run:
            ch.append(("ocr::real_run_requires_reason", bool(reason.strip()),
                       "a non-read-only command with dry_run=false requires an explicit "
                       "reason (dry-run first, or authorize)",
                       C.OPERATOR_COMMAND_DRY_RUN_REQUIRED))

    # --- honesty: target_scenarios bounded unless a full-matrix command ----------
    if _is_list(obj, "target_scenarios") and cid not in OPERATOR_FULL_MATRIX_COMMANDS:
        ch.append(("ocr::target_scenarios_bounded",
                   len(obj["target_scenarios"]) <= MAX_TARGET_SCENARIOS,
                   "target_scenarios must be bounded (<= {}) unless a full-matrix command"
                   .format(MAX_TARGET_SCENARIOS), C.OPERATOR_FULL_MATRIX_UNAUTHORIZED))
    ch += _schema_version(obj, RT_COMMAND_REQUEST, code, "ocr::")
    return ch


def _example_command_request(**over):
    d = {
        "request_id": "req_index_reports_0001",
        "created_at": "live",
        "requested_by": "operator",
        "command_id": "operator-index-reports",
        "command_args": ["--strict"],
        "target_pack": "worldforge_vertical_slice",
        "target_scenarios": [],
        "dry_run": True,
        "allowed": True,
        "reason": "",
        "expected_outputs": ["procedural/reports/operator/index/operator_report_index.json"],
        "schema_version": RT_COMMAND_REQUEST,
        "report_type": RT_COMMAND_REQUEST,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 9. OperatorCommandResult (WF730)  — the captured outcome of a request
# --------------------------------------------------------------------------- #
COMMAND_RESULT_REQUIRED = (
    "result_id", "request_id", "started_at", "ended_at", "exit_code",
    "stdout_path", "stderr_path", "created_outputs", "updated_indexes",
    "status", "failure_codes", "schema_version",
)
COMMAND_RESULT_ALLOWED = COMMAND_RESULT_REQUIRED + (
    "meta", "report_type", "created_by", "notes",
)


def validate_command_result(obj, strict=False):
    code = C.OPERATOR_COMMAND_RESULT_INVALID
    ch = RS.check_required(obj, COMMAND_RESULT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, COMMAND_RESULT_ALLOWED, code, strict)
    for f in ("result_id", "request_id", "started_at", "ended_at",
              "stdout_path", "stderr_path"):
        ch += _str(obj, f, code, "ocx::")
    # exit_code is an integer (0 = success); allow_zero because 0 is the good case.
    ch += _int(obj, "exit_code", code, "ocx::", allow_zero=True)
    for f in ("created_outputs", "updated_indexes"):
        ch.append(("ocx::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    ch += RS.check_enum(obj, "status", COMMAND_RESULT_STATUS, code, prefix="ocx::")
    fc_is_list = _is_list(obj, "failure_codes")
    ch.append(("ocx::failure_codes_list", fc_is_list, "failure_codes must be a list", code))

    exit_code = obj.get("exit_code")
    nonzero = RS.is_number(exit_code) and int(exit_code) != 0
    # --- honesty: a nonzero exit code forces status != pass ----------------------
    ch.append(("ocx::nonzero_exit_not_pass",
               (not nonzero) or obj.get("status") != "pass",
               "a nonzero exit_code cannot be status=pass",
               C.OPERATOR_COMMAND_RESULT_INVALID))
    # --- honesty: status=pass requires created outputs + zero blocking codes -----
    if obj.get("status") == "pass":
        ch.append(("ocx::pass_requires_outputs",
                   _is_list(obj, "created_outputs") and len(obj["created_outputs"]) > 0,
                   "status=pass requires >= 1 created_output",
                   C.OPERATOR_COMMAND_RESULT_INVALID))
        ch.append(("ocx::pass_requires_clean_codes",
                   fc_is_list and len(obj.get("failure_codes") or []) == 0,
                   "status=pass requires an empty failure_codes list",
                   C.OPERATOR_COMMAND_RESULT_INVALID))
    ch += _schema_version(obj, RT_COMMAND_RESULT, code, "ocx::")
    return ch


def _example_command_result(**over):
    d = {
        "result_id": "res_index_reports_0001",
        "request_id": "req_index_reports_0001",
        "started_at": "live",
        "ended_at": "live",
        "exit_code": 0,
        "stdout_path": "procedural/reports/operator/commands/res_index_reports_0001.stdout.txt",
        "stderr_path": "procedural/reports/operator/commands/res_index_reports_0001.stderr.txt",
        "created_outputs": ["procedural/reports/operator/index/operator_report_index.json"],
        "updated_indexes": ["operator_report_index"],
        "status": "pass",
        "failure_codes": [],
        "schema_version": RT_COMMAND_RESULT,
        "report_type": RT_COMMAND_RESULT,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 10. OperatorDiffReport (WF731)  — a diff between two operator runs
# --------------------------------------------------------------------------- #
DIFF_REPORT_REQUIRED = (
    "diff_id", "left_run_id", "right_run_id", "left_git_sha", "right_git_sha",
    "changed_reports", "changed_scenarios", "changed_failures",
    "resolved_failures", "new_failures", "changed_package_status",
    "changed_runtime_status", "summary", "failure_codes", "schema_version",
)
DIFF_REPORT_ALLOWED = DIFF_REPORT_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)
_DIFF_LISTS = ("changed_reports", "changed_scenarios", "changed_failures",
               "resolved_failures", "new_failures")


def validate_diff_report(obj, strict=False):
    code = C.OPERATOR_DIFF_INVALID
    ch = RS.check_required(obj, DIFF_REPORT_REQUIRED, code)
    ch += RS.check_no_unknown(obj, DIFF_REPORT_ALLOWED, code, strict)
    for f in ("diff_id", "left_run_id", "right_run_id", "left_git_sha",
              "right_git_sha", "summary"):
        ch += _str(obj, f, code, "odr::")
    for f in _DIFF_LISTS:
        ch.append(("odr::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    for f in ("changed_package_status", "changed_runtime_status"):
        ch += _bool(obj, f, code, "odr::")

    # --- honesty: a diff must compare two DISTINCT runs --------------------------
    lr, rr = obj.get("left_run_id"), obj.get("right_run_id")
    ch.append(("odr::distinct_runs",
               isinstance(lr, str) and isinstance(rr, str) and lr != rr,
               "a diff must compare two distinct runs (left_run_id != right_run_id)",
               C.OPERATOR_DIFF_INVALID))
    # --- honesty: every new/resolved failure entry must be a well-formed code ----
    for f in ("new_failures", "resolved_failures"):
        if _is_list(obj, f):
            bad = [x for x in obj[f] if not (isinstance(x, str) and _WF_CODE_RE.match(x))]
            ch.append(("odr::{}_well_formed".format(f), not bad,
                       "{} entries must be well-formed WFnnn_* codes (bad: {})".format(
                           f, bad[:3]), C.OPERATOR_UNKNOWN_FAILURE_CODE))
    ch += _schema_version(obj, RT_DIFF_REPORT, code, "odr::")
    return ch


def _example_diff_report(**over):
    d = {
        "diff_id": "diff_run0001_run0002",
        "left_run_id": "run0001",
        "right_run_id": "run0002",
        "left_git_sha": "1111111111111111111111111111111111111111",
        "right_git_sha": "2222222222222222222222222222222222222222",
        "changed_reports": ["procedural/reports/slice/runtime"],
        "changed_scenarios": ["vs_desert_reach_objective_baseline_s1"],
        "changed_failures": [],
        "resolved_failures": ["WF704_SLICE_REWARD_WITHOUT_MUTATION"],
        "new_failures": [],
        "changed_package_status": False,
        "changed_runtime_status": True,
        "summary": "1 scenario changed; 1 failure resolved; 0 new failures.",
        "failure_codes": [],
        "created_at": "live",
        "schema_version": RT_DIFF_REPORT,
        "report_type": RT_DIFF_REPORT,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# 11. KnownRegressionRegistry (WF732)  — tracked cross-run regressions
# --------------------------------------------------------------------------- #
KNOWN_REGRESSION_REQUIRED = (
    "regression_id", "title", "milestone", "first_seen_git_sha",
    "last_seen_git_sha", "affected_packs", "affected_scenarios",
    "failure_codes", "status", "owner_hint", "reproduction_command",
    "resolution_notes", "schema_version",
)
KNOWN_REGRESSION_ALLOWED = KNOWN_REGRESSION_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)


def validate_known_regression(obj, strict=False):
    code = C.OPERATOR_REGRESSION_REGISTRY_INVALID
    ch = RS.check_required(obj, KNOWN_REGRESSION_REQUIRED, code)
    ch += RS.check_no_unknown(obj, KNOWN_REGRESSION_ALLOWED, code, strict)
    for f in ("regression_id", "title", "milestone", "first_seen_git_sha",
              "last_seen_git_sha", "owner_hint"):
        ch += _str(obj, f, code, "okr::")
    ch += RS.check_enum(obj, "status", FC_STATUSES, code, prefix="okr::")
    for f in ("affected_packs", "affected_scenarios", "failure_codes"):
        ch.append(("okr::{}_is_list".format(f), _is_list(obj, f),
                   "{} must be a list".format(f), code))
    # reproduction_command / resolution_notes are conditionally-required strings.
    for f in ("reproduction_command", "resolution_notes"):
        ch.append(("okr::{}_is_str".format(f), isinstance(obj.get(f), str),
                   "{} must be a string".format(f), code))

    status = obj.get("status")
    repro = obj.get("reproduction_command") if isinstance(obj.get("reproduction_command"), str) else ""
    notes = obj.get("resolution_notes") if isinstance(obj.get("resolution_notes"), str) else ""
    # --- honesty: an active regression needs a reproduction command --------------
    if status in ("active", "regression"):
        ch.append(("okr::active_requires_repro", bool(repro.strip()),
                   "an active/regression row requires a reproduction_command",
                   C.OPERATOR_REGRESSION_REGISTRY_INVALID))
    # --- honesty: a resolved regression needs resolution notes -------------------
    if status == "resolved":
        ch.append(("okr::resolved_requires_notes", bool(notes.strip()),
                   "a resolved row requires resolution_notes",
                   C.OPERATOR_REGRESSION_REGISTRY_INVALID))
    ch += _schema_version(obj, RT_KNOWN_REGRESSION, code, "okr::")
    return ch


def _example_known_regression(**over):
    d = {
        "regression_id": "reg_mission_mesh_playtest",
        "title": "Mission full-shield mesh/playtest gates pre-existing red",
        "milestone": "v1.7",
        "first_seen_git_sha": "9734faa00000000000000000000000000000000",
        "last_seen_git_sha": "0000000000000000000000000000000000000000",
        "affected_packs": ["encounter_loop_world"],
        "affected_scenarios": [],
        "failure_codes": ["WF680_SLICE_NPC_EVIDENCE_MISSING"],
        "status": "active",
        "owner_hint": "meshforge / playtest lane",
        "reproduction_command": "python tools/pipeline/v1_7_shield.py --pack encounter_loop_world --strict",
        "resolution_notes": "",
        "created_at": "live",
        "schema_version": RT_KNOWN_REGRESSION,
        "report_type": RT_KNOWN_REGRESSION,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# Registry of all contracts, for the schema validators + fuzz/negatives harness.
# Each entry: name -> (validate_fn, valid_example_fn, known_bad_example_fn).
# The known-bad MUST fail the validator for its OWNING code — a contract that
# accepts it is fake green.
# --------------------------------------------------------------------------- #
CONTRACTS = {
    "OperatorReportIndex": (
        validate_report_index, _example_report_index,
        # integrity_result=pass but missing_evidence non-empty -> WF717.
        lambda: _example_report_index(missing_evidence=["procedural/reports/slice/runtime/x.json"])),
    "OperatorPackCard": (
        validate_pack_card, _example_pack_card,
        # passing v2.0 pack but no package on disk -> WF725.
        lambda: _example_pack_card(package_exists=False, package_size_bytes=0)),
    "OperatorScenarioCard": (
        validate_scenario_card, _example_scenario_card,
        # runtime_status=pass but no report paths -> WF714.
        lambda: _example_scenario_card(report_paths=[])),
    "EvidenceTrace": (
        validate_evidence_trace, _example_evidence_trace,
        # verdict=pass but no supporting report -> WF721.
        lambda: _example_evidence_trace(supporting_reports=[])),
    "FailureCodeIndex": (
        validate_failure_code_index, _example_failure_code_index,
        # blocking severity but no suggested next action -> WF722.
        lambda: _example_failure_code_index(suggested_next_actions=[])),
    "AssetOwnershipView": (
        validate_asset_ownership_view, _example_asset_ownership_view,
        # third-party asset marked regenerate/destroyable -> WF723.
        lambda: _example_asset_ownership_view(ownership_class="third_party_owned",
                                              repair_destroy_policy="regenerate")),
    "RouteWalkabilityView": (
        validate_route_walkability_view, _example_route_walkability_view,
        # claims proved objective access via grounded_navmesh (honest limit) -> WF724.
        lambda: _example_route_walkability_view(traversal_mode="grounded_navmesh")),
    "OperatorCommandRequest": (
        validate_command_request, _example_command_request,
        # allowed=true for a non-allowlisted command -> WF726.
        lambda: _example_command_request(command_id="rm-the-repo", allowed=True)),
    "OperatorCommandResult": (
        validate_command_result, _example_command_result,
        # nonzero exit but status=pass -> WF730.
        lambda: _example_command_result(exit_code=1, status="pass")),
    "OperatorDiffReport": (
        validate_diff_report, _example_diff_report,
        # left_run_id == right_run_id (diffing a run against itself) -> WF731.
        lambda: _example_diff_report(right_run_id="run0001")),
    "KnownRegressionRegistry": (
        validate_known_regression, _example_known_regression,
        # active regression with no reproduction command -> WF732.
        lambda: _example_known_regression(reproduction_command="")),
}

CONTRACT_GROUPS = {
    "index": ("OperatorReportIndex", "EvidenceTrace"),
    "browser": ("OperatorPackCard", "OperatorScenarioCard"),
    "diagnostics": ("FailureCodeIndex", "OperatorDiffReport", "KnownRegressionRegistry"),
    "assets_routes": ("AssetOwnershipView", "RouteWalkabilityView"),
    "commands": ("OperatorCommandRequest", "OperatorCommandResult"),
}

# The owning failure code each known-bad must be rejected FOR (used by the
# negatives suite: rejection for the wrong reason is not real coverage).
KNOWN_BAD_OWNING_CODE = {
    "OperatorReportIndex": C.OPERATOR_MISSING_EVIDENCE,
    "OperatorPackCard": C.OPERATOR_PACKAGE_PROOF_MISSING,
    "OperatorScenarioCard": C.OPERATOR_REPORT_PATH_MISSING,
    "EvidenceTrace": C.OPERATOR_EVIDENCE_TRACE_INVALID,
    "FailureCodeIndex": C.OPERATOR_FAILURE_INDEX_INVALID,
    "AssetOwnershipView": C.OPERATOR_ASSET_OWNERSHIP_INVALID,
    "RouteWalkabilityView": C.OPERATOR_ROUTE_VIEW_INVALID,
    "OperatorCommandRequest": C.OPERATOR_COMMAND_NOT_ALLOWLISTED,
    "OperatorCommandResult": C.OPERATOR_COMMAND_RESULT_INVALID,
    "OperatorDiffReport": C.OPERATOR_DIFF_INVALID,
    "KnownRegressionRegistry": C.OPERATOR_REGRESSION_REGISTRY_INVALID,
}
