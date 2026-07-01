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


# This gate's own report — excluded from the scan so it never grades itself.
OWN_REPORT = "validate_report_integrity_report.json"

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
        p for p in rdir.glob("*_report.json") if p.name != OWN_REPORT
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.0x report-integrity gate (no fake green).")
    ap.add_argument("--pack", required=True, help="World pack id or path.")
    ap.add_argument("--strict", action="store_true", help="Strict mode; also via STRICT=1.")
    ap.add_argument("--final", action="store_true",
                    help="Also require the FULL set of gate reports to be present.")
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

    rep = validate_pack(args.pack, strict=strict, reports_dir=args.reports_dir,
                        final=final, max_age_days=args.max_age_days)
    rep.finalize()

    report_dir = report_dir_for(world_pack_id)
    rep.write(report_dir, OWN_REPORT)
    rep.print_summary("validate-report-integrity" + (" --final" if final else ""))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
