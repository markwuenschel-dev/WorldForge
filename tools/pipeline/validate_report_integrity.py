#!/usr/bin/env python3
"""validate_report_integrity.py — WorldForge v1.0x report-integrity gate (no fake green).

The other v1.0x gates each emit a JSON report. This gate validates the REPORTS
THEMSELVES so a run cannot silently skip, go stale, report zero records, drop
required metadata, or launder a partial failure as success. It is the meta-gate
that makes the whole shield trustworthy.

For every ``*_report.json`` under ``procedural/reports/world_packs/<pack>/`` it
checks (see failure_codes WF100–WF109):

    REPORT_EMPTY (WF102)               report is unparseable, ``{}`` or empty
    REPORT_INTEGRITY_FAILURE (WF100)  a v1.0x report is missing REQUIRED_META_KEYS
    REPORT_ZERO_RECORD (WF104)        record_count <= 0 (success over nothing = a lie)
    PARTIAL_SUCCESS_AS_SUCCESS (WF109) failures present but status/passed says ok
    RECORD_COUNT_MISMATCH (WF105)     meta.failure_count != len(failures), or
                                      record_count==0 while checks exist
    REPORT_STALE (WF103)              report mtime older than the generated spec /
                                      slice-pack / world-pack it derives from
                                      (WARN in normal mode, FAIL under strict), or
                                      older than --max-age-days when supplied
    UNKNOWN_SCHEMA_FIELD (WF107)      a check verdict outside the known vocabulary
    REPORT_MISSING (WF101)            with --final: a REQUIRED gate report is absent

The core is importable: ``validate_pack(pack, strict, reports_dir=None,
final=False, max_age_days=None) -> ValidationReport`` (unfinalized). The sibling
``test_negative_report_integrity`` fixtures (embedded in test_negative_validators)
prove each of these codes actually fires.

Run:
    PYTHONUTF8=1 python tools/pipeline/validate_report_integrity.py --pack desert_mvp_world --strict
    PYTHONUTF8=1 python tools/pipeline/validate_report_integrity.py --pack desert_mvp_world --strict --final
"""

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from validation_report import ValidationReport, strict_from_env, VERDICTS
from failure_codes import FailureCode
from report_meta import (build_meta, hash_obj, flag_from_env,
                         REQUIRED_META_KEYS, missing_meta_keys)
from world_pack_maps import enumerate_maps, report_dir_for
from mesh_contract import MESH_REPORTS_REL
import mission_contract as MC
import visual_contract as VC


# This gate's own report — excluded from the scan so it never grades itself.
OWN_REPORT = "validate_report_integrity_report.json"

# Aggregate rollup reports that are NOT per-check ValidationReports and are
# inherently one shield-run behind (the shield writes them AFTER this gate runs).
# Grading them here is both a shape mismatch (they carry "gates"/"blocking_gates",
# not "failures") and a red->green deadlock. Their integrity is the shield's own
# exit code. Excluded from the scan, like OWN_REPORT.
AGGREGATE_REPORTS = frozenset({"full_shield_report.json"})

# Grace window (seconds) so reports written microseconds apart from their inputs
# in the same generation batch are not falsely flagged stale.
STALE_GRACE_SECONDS = 2.0

# The full set of gate reports that MUST be present for a --final (release) scan.
# A required report that is entirely absent is REPORT_MISSING.
REQUIRED_REPORT_STEMS = (
    "validate_environment_contract",
    "validate_sky",
    "validate_lighting",
    "validate_fog",
    "validate_atmosphere",
    "validate_pois",
    "validate_level_design",
    "validate_reachability",
    "validate_poi_graph",
    "validate_entity_anchors",
    "validate_npc_spawns",
    "validate_encounter_readiness",
    "validate_rendering_profiles",
    "validate_scalability",
    "validate_raytracing",
    "validate_performance_budgets",
    "validate_inspection",
    "validate_world_pack",
)

# The subset of gate reports that MUST carry a full v1.0x ``meta`` block. A report
# named here but lacking meta is a REPORT_INTEGRITY_FAILURE. (validate_inspection
# and validate_world_pack are legacy-shaped v0.9 reports that predate the meta
# block; they are required-present but not required-meta.)
META_REQUIRED_STEMS = frozenset(REQUIRED_REPORT_STEMS) - {
    "validate_inspection", "validate_world_pack",
}

# Where a required report may live if not in the pack report dir.
def _fallback_dirs():
    return [REPO_ROOT / "procedural" / "reports" / "inspection"]


def _stem_of(filename):
    """`validate_sky_report.json` -> `validate_sky`."""
    name = filename
    if name.endswith("_report.json"):
        return name[: -len("_report.json")]
    if name.endswith(".json"):
        return name[: -len(".json")]
    return name


def _input_anchor_mtime(maps):
    """Newest mtime among the generated specs + slice packs + world pack the
    reports derive from. Returns None if nothing resolvable (so a synthetic
    reports_dir with an unresolvable pack simply skips mtime-staleness)."""
    mtimes = []
    seen = set()
    for m in maps:
        sp = m.get("spec_path")
        if sp and sp not in seen:
            seen.add(sp)
            p = Path(sp)
            if p.is_file():
                mtimes.append(p.stat().st_mtime)
    return max(mtimes) if mtimes else None


def _locate_required(stem, rdir):
    """True if `<stem>_report.json` exists in the pack dir or a fallback dir."""
    fname = stem + "_report.json"
    if (Path(rdir) / fname).is_file():
        return True
    for d in _fallback_dirs():
        if (d / fname).is_file():
            return True
    return False


def _record_count_of(data, meta, checks):
    """Declared record count: meta.record_count when it's an int, else len(checks)."""
    if isinstance(meta, dict):
        rc = meta.get("record_count")
        if isinstance(rc, bool):  # bool is an int subclass; reject
            return None, len(checks)
        if isinstance(rc, int):
            return rc, len(checks)
    return None, len(checks)


def _check_one_report(rep, rf, strict, anchor_mtime, max_age_days):
    """Apply the integrity battery to a single report file, recording checks on rep."""
    stem = _stem_of(rf.name)
    tag = "report::" + rf.name

    # -- parse / non-empty --------------------------------------------------
    try:
        raw = rf.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        rep.check(tag + "::parses", False,
                  "report is unparseable: {}".format(exc),
                  code=FailureCode.REPORT_EMPTY)
        return
    if not isinstance(data, dict) or not data:
        rep.check(tag + "::non_empty", False,
                  "report is empty ({} / no content)".format(type(data).__name__),
                  code=FailureCode.REPORT_EMPTY)
        return

    checks = data.get("checks") or {}
    failures = data.get("failures") or []
    meta = data.get("meta")
    meta_tracked = isinstance(meta, dict) or (stem in META_REQUIRED_STEMS)

    # -- unknown verdict vocabulary (structural smell) ----------------------
    if isinstance(checks, dict):
        bad_verdicts = sorted({
            c.get("verdict") for c in checks.values()
            if isinstance(c, dict) and c.get("verdict") not in VERDICTS
        } - {None})
        if bad_verdicts:
            rep.check(tag + "::known_verdicts", False,
                      "check verdict(s) outside known vocabulary: {}".format(bad_verdicts),
                      code=FailureCode.UNKNOWN_SCHEMA_FIELD)

    # -- partial success laundered as success (applies to any report) -------
    eff_status = (meta.get("status") if isinstance(meta, dict) else None) or data.get("status")
    claims_ok = (eff_status in ("ok", "warn")) or (data.get("passed") is True)
    if failures and claims_ok:
        rep.check(tag + "::status_consistent", False,
                  "{} failure(s) present but status='{}' / passed={} (partial success "
                  "laundered as success)".format(len(failures), eff_status, data.get("passed")),
                  code=FailureCode.PARTIAL_SUCCESS_AS_SUCCESS)

    # -- v1.0x meta-tracked battery -----------------------------------------
    if meta_tracked:
        missing = missing_meta_keys(meta)
        if missing:
            rep.check(tag + "::meta_complete", False,
                      "missing required meta key(s): {}".format(missing),
                      code=FailureCode.REPORT_INTEGRITY_FAILURE)

        declared, n_checks = _record_count_of(data, meta, checks)
        effective_rc = declared if declared is not None else n_checks
        if effective_rc <= 0:
            rep.check(tag + "::nonzero_records", False,
                      "record_count={} (a zero-record report claiming success is a lie)".format(
                          effective_rc),
                      code=FailureCode.REPORT_ZERO_RECORD)

        if isinstance(meta, dict):
            fc = meta.get("failure_count")
            if isinstance(fc, int) and not isinstance(fc, bool) and fc != len(failures):
                rep.check(tag + "::failure_count_matches", False,
                          "meta.failure_count={} but report has {} failure(s)".format(
                              fc, len(failures)),
                          code=FailureCode.RECORD_COUNT_MISMATCH)
            if declared == 0 and n_checks > 0:
                rep.check(tag + "::record_count_matches", False,
                          "meta.record_count=0 but report carries {} check(s)".format(n_checks),
                          code=FailureCode.RECORD_COUNT_MISMATCH)

        # staleness by mtime vs the specs it derives from
        rmt = rf.stat().st_mtime
        if anchor_mtime is not None and (rmt + STALE_GRACE_SECONDS) < anchor_mtime:
            rep.check(tag + "::not_stale", False,
                      "report mtime {} older than newest input spec {} — regenerate/revalidate".format(
                          time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rmt)),
                          time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(anchor_mtime))),
                      warn_only=True, code=FailureCode.REPORT_STALE)
        if max_age_days is not None:
            age_days = (time.time() - rmt) / 86400.0
            if age_days > max_age_days:
                rep.check(tag + "::within_max_age", False,
                          "report is {:.1f} days old (> --max-age-days={})".format(
                              age_days, max_age_days),
                          warn_only=True, code=FailureCode.REPORT_STALE)


def validate_pack(pack, strict, reports_dir=None, final=False, max_age_days=None):
    """Core report-integrity validation. Returns an UNFINALIZED ValidationReport.

    reports_dir overrides the scan directory (used by the negative harness to
    point at a temp tree of known-bad reports). final requires the full gate set
    to be present.
    """
    world_pack_id, maps = enumerate_maps(pack)
    rdir = Path(reports_dir) if reports_dir else report_dir_for(world_pack_id)
    anchor_mtime = _input_anchor_mtime(maps)

    rep = ValidationReport("world_pack_id", world_pack_id or str(pack), strict=strict)

    report_files = sorted(
        p for p in rdir.glob("*_report.json")
        if p.name != OWN_REPORT and p.name not in AGGREGATE_REPORTS
    ) if rdir.is_dir() else []

    if not report_files:
        rep.check("reports_present", False,
                  "no *_report.json found under {}".format(rdir),
                  code=FailureCode.REPORT_MISSING)

    for rf in report_files:
        _check_one_report(rep, rf, strict, anchor_mtime, max_age_days)

    if final:
        for stem in REQUIRED_REPORT_STEMS:
            present = _locate_required(stem, rdir)
            rep.check("required::" + stem, present,
                      "required gate report present" if present
                      else "required gate report absent: {}_report.json".format(stem),
                      code=FailureCode.REPORT_MISSING)

    rep.set_meta(build_meta(
        command="validate-report-integrity",
        pack=world_pack_id,
        strict=strict,
        status=None,
        record_count=len(report_files),
        input_spec_hash=hash_obj(sorted(m.get("slice_id") for m in maps if m.get("slice_id"))),
        extra={"final": bool(final), "reports_scanned": len(report_files)},
    ))
    return rep


# ---------------------------------------------------------------------------
# v1.2 MeshForge Intake — mesh command report-integrity scan (--mesh)
# ---------------------------------------------------------------------------
# The v1.2 mesh gates (brief §17) each emit a ValidationReport under
# procedural/reports/mesh/<command>/<command>_report.json. --mesh validates
# THOSE reports the same way the world-pack scan validates gate reports: a mesh
# report cannot silently go missing, empty, zero-record, drop required metadata,
# carry an unknown status, or launder a child failure as success.

# This gate's own mesh report — written under its own command dir; never scanned.
OWN_MESH_REPORT = "validate_report_integrity_mesh_report.json"

# The canonical set of mesh command reports that MUST be present for a mesh
# integrity scan. An absent required report is REPORT_MISSING.
REQUIRED_MESH_COMMANDS = (
    "create_mesh_assets",
    "validate_mesh_contract",
    "validate_mesh_catalog",
    "validate_mesh_provenance",
    "validate_mesh_final_paths",
    "validate_mesh_material_bindings",
    "validate_mesh_collision_bounds",
    "validate_mesh_pcg_eligibility",
    "validate_mesh_biome_compatibility",
    "validate_mesh_rendering_budgets",
    "validate_mesh_package",
)

# TORTURE-gated / negative reports: scanned for integrity IF PRESENT, but never
# hard-required (mesh-lifecycle-torture only runs under the TORTURE gate, and
# mesh-negative writes its own report only when the negative lane has run).
OPTIONAL_MESH_COMMANDS = (
    "mesh_negative",
    "mesh_lifecycle_torture",
)

# Known overall-status vocabulary a mesh report may declare.
KNOWN_REPORT_STATUSES = ("ok", "warn", "fail", "error")


def _mesh_report_path(reports_root, command):
    """procedural/reports/mesh/<command>/<command>_report.json under reports_root."""
    return Path(reports_root) / command / (command + "_report.json")


def _check_one_mesh_report(rep, command, path, required=True):
    """Apply the mesh report-integrity battery to a single command report.

    Records checks on rep. Returns True if the report was present+parseable and
    the deeper battery ran, False if it was missing/empty/unparseable (which is
    itself a recorded failure for a required report).
    """
    tag = "mesh_report::" + command

    if not path.is_file():
        # A missing torture/negative report is simply not scanned (not required);
        # a missing required report is a blocking REPORT_MISSING.
        if required:
            rep.check(tag + "::present", False,
                      "required mesh report absent: {}".format(path),
                      code=FailureCode.REPORT_MISSING)
        return False

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        rep.check(tag + "::parses", False,
                  "mesh report is unparseable: {}".format(exc),
                  code=FailureCode.REPORT_EMPTY)
        return False
    if not isinstance(data, dict) or not data:
        rep.check(tag + "::non_empty", False,
                  "mesh report is empty ({} / no content)".format(type(data).__name__),
                  code=FailureCode.REPORT_EMPTY)
        return False

    rep.check(tag + "::present", True, "mesh report present: {}".format(path))

    meta = data.get("meta")
    failures = data.get("failures") or []

    # -- v1.0x meta block (command+pack+status+record_count at minimum) ------
    if not isinstance(meta, dict):
        rep.check(tag + "::meta_present", False,
                  "mesh report carries no meta block (missing mesh metadata)",
                  code=FailureCode.REPORT_INTEGRITY_FAILURE)
    else:
        missing = list(missing_meta_keys(meta))
        for k in ("command", "pack", "status", "record_count"):
            if k not in meta and k not in missing:
                missing.append(k)
        if missing:
            rep.check(tag + "::meta_complete", False,
                      "missing required meta key(s): {}".format(sorted(missing)),
                      code=FailureCode.REPORT_INTEGRITY_FAILURE)

    # -- status vocabulary + child-failure propagation ----------------------
    eff_status = (meta.get("status") if isinstance(meta, dict) else None) or data.get("status")
    if eff_status not in KNOWN_REPORT_STATUSES:
        rep.check(tag + "::known_status", False,
                  "mesh report status outside known vocabulary: {!r}".format(eff_status),
                  code=FailureCode.REPORT_INTEGRITY_FAILURE)
    elif eff_status in ("fail", "error"):
        rep.check(tag + "::child_passed", False,
                  "child mesh report status='{}' — child failure must propagate".format(eff_status),
                  code=FailureCode.CHILD_VALIDATION_FAILED)

    # -- partial success laundered as success -------------------------------
    claims_ok = (eff_status in ("ok", "warn")) or (data.get("passed") is True)
    if failures and claims_ok:
        rep.check(tag + "::status_consistent", False,
                  "{} failure(s) present but status='{}' / passed={} (partial success "
                  "laundered as success)".format(len(failures), eff_status, data.get("passed")),
                  code=FailureCode.PARTIAL_SUCCESS_AS_SUCCESS)

    # -- non-zero record count (success over nothing is a lie) --------------
    rc = meta.get("record_count") if isinstance(meta, dict) else None
    if isinstance(rc, bool) or not isinstance(rc, int) or rc <= 0:
        rep.check(tag + "::nonzero_records", False,
                  "record_count={!r} (a zero-record mesh report claiming success is a lie)".format(rc),
                  code=FailureCode.REPORT_ZERO_RECORD)

    return True


def validate_mesh(pack, strict, reports_dir=None):
    """Core mesh report-integrity scan. Returns an UNFINALIZED ValidationReport.

    Scans procedural/reports/mesh/<command>/<command>_report.json for every
    REQUIRED_MESH_COMMANDS entry (plus any present OPTIONAL_MESH_COMMANDS), so a
    missing/empty/zero-record/child-failed mesh report fails this gate.
    reports_dir overrides the mesh reports root (used by the negative harness).
    """
    try:
        world_pack_id, _ = enumerate_maps(pack)
    except Exception:
        world_pack_id = None
    reports_root = Path(reports_dir) if reports_dir else (REPO_ROOT / MESH_REPORTS_REL)

    rep = ValidationReport("mesh_pack_id", world_pack_id or str(pack), strict=strict)

    scanned = 0
    for command in REQUIRED_MESH_COMMANDS:
        _check_one_mesh_report(rep, command, _mesh_report_path(reports_root, command),
                               required=True)
        scanned += 1
    for command in OPTIONAL_MESH_COMMANDS:
        path = _mesh_report_path(reports_root, command)
        if path.is_file():
            _check_one_mesh_report(rep, command, path, required=False)
            scanned += 1

    rep.set_meta(build_meta(
        command="validate-report-integrity-mesh",
        pack=world_pack_id,
        strict=strict,
        status=None,
        record_count=scanned,
        extra={"mesh": True,
               "required_reports": len(REQUIRED_MESH_COMMANDS),
               "reports_scanned": scanned},
    ))
    return rep


# ---------------------------------------------------------------------------
# v1.2 addendum — SOURCE (Houdini + Megascans) command report-integrity (--sources)
# ---------------------------------------------------------------------------
# The v1.2 addendum source lanes (Houdini intake + Megascans external assets)
# each emit a ValidationReport under procedural/reports/mesh/<command>/
# <command>_report.json — the same layout as the mesh gates. --sources validates
# THOSE reports exactly the way --mesh validates the mesh command reports: a
# source report cannot silently go missing, empty, zero-record, drop required
# metadata, carry an unknown status, or launder a child failure as success. It
# does NOT alter the existing --mesh / world-pack behaviour.

# This gate's own source report — written under its own command dir; never scanned.
OWN_SOURCE_REPORT = "validate_report_integrity_sources_report.json"

# The canonical set of source command reports that MUST be present for a source
# integrity scan (addendum §5/§6/§8/§14). An absent required report is REPORT_MISSING.
REQUIRED_SOURCE_COMMANDS = (
    "validate_houdini_intake",
    "validate_houdini_cook_reports",
    "validate_houdini_bake_reports",
    "validate_houdini_generated_assets",
    "scan_external_asset_library",
    "validate_external_asset_catalog",
    "validate_megascans_catalog",
    "validate_external_asset_ownership",
    "validate_megascans_bindings",
    "validate_megascans_pcg_eligibility",
    "validate_megascans_biome_compatibility",
    "validate_third_party_package_policy",
    "validate_source_ownership_separation",
)

# TORTURE-gated / negative source reports: scanned for integrity IF PRESENT, but
# never hard-required (source-lifecycle-torture only runs under the TORTURE gate,
# and source-negative writes its report only when the negative lane has run).
OPTIONAL_SOURCE_COMMANDS = (
    "test_negative_sources",
    "source_lifecycle_torture",
)


def validate_sources(pack, strict, reports_dir=None):
    """Core source report-integrity scan. Returns an UNFINALIZED ValidationReport.

    Scans procedural/reports/mesh/<command>/<command>_report.json for every
    REQUIRED_SOURCE_COMMANDS entry (plus any present OPTIONAL_SOURCE_COMMANDS),
    reusing the same per-report battery as the --mesh scan, so a missing / empty /
    zero-record / child-failed source report fails this gate. reports_dir overrides
    the mesh reports root (used by a negative harness). Existing behaviour of the
    world-pack and --mesh scans is untouched.
    """
    try:
        world_pack_id, _ = enumerate_maps(pack)
    except Exception:
        world_pack_id = None
    reports_root = Path(reports_dir) if reports_dir else (REPO_ROOT / MESH_REPORTS_REL)

    rep = ValidationReport("source_pack_id", world_pack_id or str(pack), strict=strict)

    scanned = 0
    for command in REQUIRED_SOURCE_COMMANDS:
        _check_one_mesh_report(rep, command, _mesh_report_path(reports_root, command),
                               required=True)
        scanned += 1
    for command in OPTIONAL_SOURCE_COMMANDS:
        path = _mesh_report_path(reports_root, command)
        if path.is_file():
            _check_one_mesh_report(rep, command, path, required=False)
            scanned += 1

    rep.set_meta(build_meta(
        command="validate-report-integrity-sources",
        pack=world_pack_id,
        strict=strict,
        status=None,
        record_count=scanned,
        extra={"sources": True,
               "required_reports": len(REQUIRED_SOURCE_COMMANDS),
               "reports_scanned": scanned},
    ))
    return rep


# ---------------------------------------------------------------------------
# v1.3 MissionForge + PlaytestForge — mission command report-integrity (--missions)
# ---------------------------------------------------------------------------
# The v1.3 mission + playtest gates each emit a ValidationReport under
# procedural/reports/missions/<command>/<command>_report.json — the same
# per-command layout as the mesh/source gates. --missions validates THOSE reports
# exactly the way --mesh validates the mesh command reports: a mission report
# cannot silently go missing, empty, zero-record, drop required metadata, carry
# an unknown status, or launder a child failure as success. It does NOT alter the
# existing world-pack / --mesh / --sources behaviour.

# This gate's own missions report — written under its own command dir; never scanned.
OWN_MISSIONS_REPORT = "validate_report_integrity_missions_report.json"

# The canonical set of mission command reports that MUST be present for a mission
# integrity scan (brief §"v1.3 lanes"). An absent required report is REPORT_MISSING.
REQUIRED_MISSION_COMMANDS = (
    "create_mission_loops",
    "validate_mission_contract",
    "validate_mission_graph",
    "validate_mission_placement",
    "validate_mission_biome_compatibility",
    "validate_mission_routes",
    "validate_mission_objectives",
    "validate_mission_state",
    "validate_mission_save_load",
    "validate_mission_rewards",
    "validate_mission_dependencies",
    "validate_mission_mesh_usage",
    "validate_mission_entity_anchors",
    "validate_playtest_contract",
    "run_playtest_forge",
    "validate_playtest_reports",
)

# TORTURE-gated / negative mission reports: scanned for integrity IF PRESENT, but
# never hard-required (mission-lifecycle-torture only runs under the TORTURE gate,
# and mission-negative/fuzz write their report only when that lane has run).
OPTIONAL_MISSION_COMMANDS = (
    "test_negative_mission",
    "fuzz_mission_matrix",
    "mission_lifecycle_torture",
)


def validate_missions(pack, strict, reports_dir=None):
    """Core mission report-integrity scan. Returns an UNFINALIZED ValidationReport.

    Scans procedural/reports/missions/<command>/<command>_report.json for every
    REQUIRED_MISSION_COMMANDS entry (plus any present OPTIONAL_MISSION_COMMANDS),
    reusing the same per-report battery as the --mesh scan, so a missing / empty /
    zero-record / child-failed mission report fails this gate. reports_dir overrides
    the missions reports root (used by a negative harness). Existing behaviour of the
    world-pack / --mesh / --sources scans is untouched.
    """
    try:
        world_pack_id, _ = enumerate_maps(pack)
    except Exception:
        world_pack_id = None
    reports_root = Path(reports_dir) if reports_dir else (REPO_ROOT / MC.MISSION_REPORTS_REL)

    rep = ValidationReport("mission_pack_id", world_pack_id or str(pack), strict=strict)

    scanned = 0
    for command in REQUIRED_MISSION_COMMANDS:
        _check_one_mesh_report(rep, command, _mesh_report_path(reports_root, command),
                               required=True)
        scanned += 1
    for command in OPTIONAL_MISSION_COMMANDS:
        path = _mesh_report_path(reports_root, command)
        if path.is_file():
            _check_one_mesh_report(rep, command, path, required=False)
            scanned += 1

    rep.set_meta(build_meta(
        command="validate-report-integrity-missions",
        pack=world_pack_id,
        strict=strict,
        status=None,
        record_count=scanned,
        extra={"missions": True,
               "required_reports": len(REQUIRED_MISSION_COMMANDS),
               "reports_scanned": scanned},
    ))
    return rep


# ---------------------------------------------------------------------------
# v1.3.5 VisualFidelityForge — visual command report-integrity (--visuals)
# ---------------------------------------------------------------------------
# The v1.3.5 visual gates each emit a ValidationReport under
# procedural/reports/visual/<command>/<command>_report.json — the same
# per-command layout as the mesh/source/mission gates. --visuals validates THOSE
# reports exactly the way --mesh validates the mesh command reports: a visual
# report cannot silently go missing, empty, zero-record, drop required metadata,
# carry an unknown status, or launder a child failure as success. It does NOT
# alter the existing world-pack / --mesh / --sources / --missions behaviour.

# This gate's own visuals report — written under its own command dir; never scanned.
OWN_VISUALS_REPORT = "validate_report_integrity_visuals_report.json"

# The canonical set of visual command reports that MUST be present for a visual
# integrity scan (brief §"visual lanes"). An absent required report is REPORT_MISSING.
REQUIRED_VISUAL_COMMANDS = (
    "materialize_environment_rigs",
    "scan_megascans_visual_assets",
    "create_visual_dressing",
    "validate_visual_asset_coverage",
    "validate_surface_materialization",
    "validate_world_dressing",
    "validate_environment_rig",
    "validate_sky_materialization",
    "validate_fog_materialization",
    "validate_cloud_materialization",
    "validate_lighting_exposure",
    "validate_post_process_profiles",
    "validate_weather_vfx",
    "validate_visual_readability",
    "validate_visual_budgets",
    "validate_visual_package",
)

# TORTURE-gated / negative visual reports: scanned for integrity IF PRESENT, but
# never hard-required (visual-lifecycle-torture only runs under the TORTURE gate,
# and visual-negative writes its report only when that lane has run).
OPTIONAL_VISUAL_COMMANDS = (
    "test_negative_visual",
    "visual_lifecycle_torture",
)


def validate_visuals(pack, strict, reports_dir=None):
    """Core visual report-integrity scan. Returns an UNFINALIZED ValidationReport.

    Scans procedural/reports/visual/<command>/<command>_report.json for every
    REQUIRED_VISUAL_COMMANDS entry (plus any present OPTIONAL_VISUAL_COMMANDS),
    reusing the same per-report battery as the --mesh scan, so a missing / empty /
    zero-record / child-failed visual report fails this gate. reports_dir overrides
    the visual reports root (used by a negative harness). Existing behaviour of the
    world-pack / --mesh / --sources / --missions scans is untouched.
    """
    try:
        world_pack_id, _ = enumerate_maps(pack)
    except Exception:
        world_pack_id = None
    reports_root = Path(reports_dir) if reports_dir else (REPO_ROOT / VC.VISUAL_REPORTS_REL)

    rep = ValidationReport("visual_pack_id", world_pack_id or str(pack), strict=strict)

    scanned = 0
    for command in REQUIRED_VISUAL_COMMANDS:
        _check_one_mesh_report(rep, command, _mesh_report_path(reports_root, command),
                               required=True)
        scanned += 1
    for command in OPTIONAL_VISUAL_COMMANDS:
        path = _mesh_report_path(reports_root, command)
        if path.is_file():
            _check_one_mesh_report(rep, command, path, required=False)
            scanned += 1

    rep.set_meta(build_meta(
        command="validate-report-integrity-visuals",
        pack=world_pack_id,
        strict=strict,
        status=None,
        record_count=scanned,
        extra={"visuals": True,
               "required_reports": len(REQUIRED_VISUAL_COMMANDS),
               "reports_scanned": scanned},
    ))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.0x report-integrity gate (no fake green).")
    ap.add_argument("--pack", required=True, help="World pack id or path.")
    ap.add_argument("--strict", action="store_true", help="Strict mode; also via STRICT=1.")
    ap.add_argument("--final", action="store_true",
                    help="Also require the FULL set of gate reports to be present.")
    ap.add_argument("--mesh", action="store_true",
                    help="Scan the v1.2 MeshForge command reports (procedural/reports/mesh/*) "
                         "instead of the world-pack gate reports.")
    ap.add_argument("--sources", action="store_true",
                    help="Scan the v1.2 addendum SOURCE command reports (Houdini + Megascans, "
                         "procedural/reports/mesh/*) instead of the world-pack gate reports.")
    ap.add_argument("--missions", action="store_true",
                    help="Scan the v1.3 MissionForge + PlaytestForge command reports "
                         "(procedural/reports/missions/*) instead of the world-pack gate reports.")
    ap.add_argument("--visuals", action="store_true",
                    help="Scan the v1.3.5 VisualFidelityForge command reports "
                         "(procedural/reports/visual/*) instead of the world-pack gate reports.")
    ap.add_argument("--max-age-days", type=float, default=None,
                    help="Flag reports older than this many days as stale (default: off).")
    ap.add_argument("--reports-dir", default=None,
                    help="Override the scanned report directory (default: canonical pack dir).")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    final = args.final or flag_from_env("FINAL")

    try:
        world_pack_id, _ = enumerate_maps(args.pack)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot enumerate pack {}: {}\n".format(args.pack, exc))
        return 2

    if args.mesh:
        rep = validate_mesh(args.pack, strict=strict, reports_dir=args.reports_dir)
        rep.finalize()
        mesh_report_dir = REPO_ROOT / MESH_REPORTS_REL / "validate_report_integrity"
        rep.write(mesh_report_dir, OWN_MESH_REPORT)
        rep.print_summary("validate-report-integrity --mesh")
        return rep.exit_code

    if args.sources:
        rep = validate_sources(args.pack, strict=strict, reports_dir=args.reports_dir)
        rep.finalize()
        sources_report_dir = REPO_ROOT / MESH_REPORTS_REL / "validate_report_integrity"
        rep.write(sources_report_dir, OWN_SOURCE_REPORT)
        rep.print_summary("validate-report-integrity --sources")
        return rep.exit_code

    if args.missions:
        rep = validate_missions(args.pack, strict=strict, reports_dir=args.reports_dir)
        rep.finalize()
        missions_report_dir = REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_report_integrity"
        rep.write(missions_report_dir, OWN_MISSIONS_REPORT)
        rep.print_summary("validate-report-integrity --missions")
        return rep.exit_code

    if args.visuals:
        rep = validate_visuals(args.pack, strict=strict, reports_dir=args.reports_dir)
        rep.finalize()
        visuals_report_dir = REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_report_integrity"
        rep.write(visuals_report_dir, OWN_VISUALS_REPORT)
        rep.print_summary("validate-report-integrity --visuals")
        return rep.exit_code

    rep = validate_pack(args.pack, strict=strict, reports_dir=args.reports_dir,
                        final=final, max_age_days=args.max_age_days)
    rep.finalize()

    report_dir = report_dir_for(world_pack_id)
    rep.write(report_dir, OWN_REPORT)
    rep.print_summary("validate-report-integrity" + (" --final" if final else ""))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
