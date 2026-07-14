#!/usr/bin/env python3
"""transition_report_integrity.py — v2.5 transition report-integrity gate (--hostile).

Attacks the UE 5.8 evidence reports so a stale, unstamped, mislabeled, or 5.7-contaminated
report cannot pass as a 5.8 transition baseline. The single source-of-truth predicate is
``report_integrity_findings(obj, path)`` (empty list == clean); it is dogfooded on synthetic
clean/tampered records, then scanned across the REAL committed reports under the given dir.

COMMANDER META-IDENTITY CONVENTION (implemented exactly here):
  Report meta may carry: declared_target_engine (str, e.g. "5.8"), observed_runtime_engine
  (int|None), runtime_execution_required (bool), runtime_executed (bool). The meta
  engine_major/minor/patch describe the PYTHON HOST, NOT the UE runtime.
  * A runtime-FREE report (runtime_execution_required=False) that resolves engine_minor=7 via
    the uproject fallback is NOT contamination — it is not flagged. Pre-convention reports
    that carry NONE of the four keys are treated as runtime-free (target 5.8) and are clean.
  * CONTAMINATION iff: runtime_execution_required=True AND observed_runtime_engine != declared
    target minor; OR an evidence entry is tagged with a non-target engine minor; OR a
    report path/entry lives under procedural/reports/ue5_7.
  * MISLABEL iff: runtime_executed=True but observed_runtime_engine is None; OR the report
    claims observed 5.8 while carrying 5.7 (observed==7 under a 5.8 declared target).

Args: [reports_dir] (default procedural/reports/ue5_8) and --strict.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/transition_report_integrity.py \
        procedural/reports/ue5_8 --strict
Reports -> procedural/reports/ue5_8/hostile/transition_report_integrity_report.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "hostile"
DEFAULT_SCAN = "procedural/reports/ue5_8"

TARGET_MINOR = 8  # UE 5.8
CONVENTION_KEYS = ("declared_target_engine", "observed_runtime_engine",
                   "runtime_execution_required", "runtime_executed")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_UE5_7_FRAG = "procedural/reports/ue5_7"


def _minor_of_engine_str(s):
    """'5.8' -> 8, '5.7' -> 7; None on anything else."""
    if isinstance(s, str) and "." in s:
        try:
            return int(s.split(".")[1])
        except ValueError:
            return None
    return None


def resolve_convention(meta):
    """Resolve the four convention values, applying runtime-free defaults for the keys
    a pre-convention report omits. Returns (present_keys, decl_minor, obs, req, executed)."""
    present = [k for k in CONVENTION_KEYS if isinstance(meta, dict) and k in meta]
    decl_minor = _minor_of_engine_str(meta.get("declared_target_engine")) if isinstance(meta, dict) else None
    if decl_minor is None:
        decl_minor = TARGET_MINOR
    obs = meta.get("observed_runtime_engine") if isinstance(meta, dict) else None
    req = meta.get("runtime_execution_required") if isinstance(meta, dict) else None
    executed = meta.get("runtime_executed") if isinstance(meta, dict) else None
    return present, decl_minor, obs, (req if isinstance(req, bool) else False), \
        (executed if isinstance(executed, bool) else False)


def _entry_engine_minors(obj):
    """Engine-minor tags on evidence ENTRIES only (top-level list-of-dict fields).

    The meta block is deliberately excluded: its engine_minor is the python host, which
    legitimately resolves to 7 via the uproject fallback and is NOT an evidence tag."""
    out = []
    if not isinstance(obj, dict):
        return out
    for key, val in obj.items():
        if key == "meta":
            continue
        if isinstance(val, list):
            for it in val:
                if isinstance(it, dict) and "engine_minor" in it:
                    out.append(it.get("engine_minor"))
    return out


def _is_path_key(k):
    """A key that carries an evidence PATH (not free-text)."""
    return isinstance(k, str) and (
        k in ("evidence_entries", "report_path", "map_path")
        or k.endswith("_path") or k.endswith("_paths"))


def path_strings(obj):
    """Collect evidence-path strings from path-bearing fields only.

    Deliberately ignores free-text ``detail``/``notes`` and the ``meta`` block: a
    track-isolation check that *names* the ue5_7 tree in a detail string is describing an
    isolation guard, not laundering a 5.7 path. Only real path fields count."""
    out = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == "meta":
                    continue
                if _is_path_key(k):
                    if isinstance(v, str):
                        out.append(v)
                    elif isinstance(v, list):
                        out.extend([e for e in v if isinstance(e, str)])
                walk(v)
        elif isinstance(x, list):
            for e in x:
                walk(e)
    walk(obj)
    return out


def report_integrity_findings(obj, path_str=""):
    """Return a list of (label, failure_code) integrity findings; [] == clean."""
    if not isinstance(obj, dict):
        return [("not_an_object", C.TRANSITION_REPORT_INTEGRITY_FAILED)]
    meta = obj.get("meta")
    if not isinstance(meta, dict):
        return [("missing_meta", C.TRANSITION_REPORT_INTEGRITY_FAILED)]
    f = []
    # -- structural meta --
    sha = meta.get("git_sha")
    if not (isinstance(sha, str) and _SHA40.match(sha or "")):
        f.append(("bad_git_sha", C.TRANSITION_REPORT_INTEGRITY_FAILED))
    if not (isinstance(meta.get("timestamp"), str) and meta.get("timestamp")):
        f.append(("missing_timestamp", C.TRANSITION_REPORT_INTEGRITY_FAILED))
    rt = meta.get("report_type")
    if not (isinstance(rt, str) and rt.startswith("wf.")):
        f.append(("bad_report_type", C.TRANSITION_REPORT_INTEGRITY_FAILED))
    # A ValidationReport carries a top-level status; an evidence ARTIFACT does not.
    # Only the former is subject to status / manual-edit-status checks.
    is_validation_report = "status" in obj
    if is_validation_report and obj.get("status") not in ("ok", "fail", "warn", "error"):
        f.append(("bad_status", C.TRANSITION_REPORT_INTEGRITY_FAILED))
    # -- convention block consistency --
    present, decl_minor, obs, req, executed = resolve_convention(meta)
    if present and len(present) != len(CONVENTION_KEYS):
        f.append(("partial_convention_block:" + ",".join(present),
                  C.TRANSITION_REPORT_INTEGRITY_FAILED))
    if "runtime_execution_required" in meta and not isinstance(meta["runtime_execution_required"], bool):
        f.append(("runtime_execution_required_not_bool", C.TRANSITION_REPORT_INTEGRITY_FAILED))
    if "runtime_executed" in meta and not isinstance(meta["runtime_executed"], bool):
        f.append(("runtime_executed_not_bool", C.TRANSITION_REPORT_INTEGRITY_FAILED))
    obs_raw = meta.get("observed_runtime_engine")
    if "observed_runtime_engine" in meta and obs_raw is not None \
            and not (isinstance(obs_raw, int) and not isinstance(obs_raw, bool)):
        f.append(("observed_runtime_engine_not_int_or_null", C.TRANSITION_REPORT_INTEGRITY_FAILED))
    # -- CONTAMINATION --
    if req and isinstance(obs, int) and not isinstance(obs, bool) and obs != decl_minor:
        f.append(("contamination_runtime_engine_mismatch", C.EVIDENCE_ENGINE_MISMATCH))
    for em in _entry_engine_minors(obj):
        if em == 7:
            f.append(("contamination_5_7_evidence_entry", C.EVIDENCE_5_7_CONTAMINATION))
        elif em is not None and em != decl_minor:
            f.append(("contamination_foreign_evidence_entry", C.EVIDENCE_ENGINE_MISMATCH))
    ev_paths = path_strings(obj)
    if any(_UE5_7_FRAG in s.replace("\\", "/") for s in ev_paths) \
            or _UE5_7_FRAG in path_str.replace("\\", "/"):
        f.append(("contamination_ue5_7_path", C.EVIDENCE_COPIED_FROM_OLD_ENGINE))
    # -- MISLABEL --
    if executed and obs is None:
        f.append(("mislabel_executed_no_observed", C.EVIDENCE_ENGINE_MISMATCH))
    if executed and obs == 7 and decl_minor == 8:
        f.append(("mislabel_claims_5_8_carries_5_7", C.EVIDENCE_5_7_CONTAMINATION))
    # -- manual-edit smell (ValidationReports only) --
    fails = obj.get("failures")
    if is_validation_report and obj.get("status") == "ok" \
            and isinstance(fails, list) and len(fails) > 0:
        f.append(("manual_edit_ok_with_failures", C.TRANSITION_REPORT_INTEGRITY_FAILED))
    rp, rf = meta.get("records_passed"), meta.get("records_failed")
    rsk, rtot = meta.get("records_skipped"), meta.get("records_total")
    if all(isinstance(x, int) and not isinstance(x, bool) for x in (rp, rf, rsk, rtot)):
        if rp + rf + rsk != rtot:
            f.append(("manual_edit_tally_mismatch", C.TRANSITION_REPORT_INTEGRITY_FAILED))
    return f


# --------------------------------------------------------------------------- #
# Synthetic dogfood records.
# --------------------------------------------------------------------------- #
def _clean_report():
    return {"status": "ok", "failures": [],
            "checks": [{"name": "x", "verdict": "PASS"}],
            "meta": {"git_sha": "a" * 40, "timestamp": "2026-07-12T00:00:00+00:00",
                     "report_type": "wf.transition.x.v1",
                     "records_total": 3, "records_passed": 3, "records_failed": 0,
                     "records_skipped": 0,
                     "declared_target_engine": "5.8", "observed_runtime_engine": 8,
                     "runtime_execution_required": True, "runtime_executed": True}}


def _tamper_variants():
    v = []
    v.append(("no_meta", lambda r: r.pop("meta")))
    v.append(("unknown_sha", lambda r: r["meta"].__setitem__("git_sha", "unknown")))
    v.append(("short_sha", lambda r: r["meta"].__setitem__("git_sha", "abc123")))
    v.append(("no_timestamp", lambda r: r["meta"].pop("timestamp")))
    v.append(("bad_report_type", lambda r: r["meta"].__setitem__("report_type", "nope")))
    v.append(("bad_status", lambda r: r.__setitem__("status", "green")))
    v.append(("ok_with_failures",
              lambda r: (r.__setitem__("status", "ok"), r.__setitem__("failures", ["x: boom"]))))
    v.append(("tally_mismatch", lambda r: r["meta"].__setitem__("records_failed", 5)))
    v.append(("partial_convention",
              lambda r: r["meta"].pop("runtime_executed")))
    v.append(("contamination_runtime_engine",
              lambda r: r["meta"].__setitem__("observed_runtime_engine", 7)))
    v.append(("mislabel_executed_no_observed",
              lambda r: r["meta"].__setitem__("observed_runtime_engine", None)))
    v.append(("evidence_5_7_entry",
              lambda r: r.__setitem__("entries", [{"report_path": "procedural/reports/ue5_8/z.json",
                                                   "engine_minor": 7, "report_type": "wf.x"}])))
    v.append(("ue5_7_path_ref",
              lambda r: r.__setitem__("entries", [{"report_path": "procedural/reports/ue5_7/z.json",
                                                   "engine_minor": 8, "report_type": "wf.x"}])))
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 transition report-integrity gate.")
    ap.add_argument("reports_dir", nargs="?", default=DEFAULT_SCAN)
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "transition_report_integrity", strict=strict)

    # 1. Dogfood: clean passes, every tampered variant is flagged.
    rep.check("dogfood::clean_passes", report_integrity_findings(_clean_report()) == [],
              "clean synthetic report must pass: {}".format(
                  report_integrity_findings(_clean_report())),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    for label, mut in _tamper_variants():
        bad = _clean_report()
        mut(bad)
        rep.check("dogfood::flags_{}".format(label), report_integrity_findings(bad) != [],
                  "tampered report ({}) must be flagged".format(label),
                  code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    # 2. Scan the real committed reports under the target dir.
    scan_root = (REPO_ROOT / args.reports_dir).resolve()
    scanned = 0
    for p in sorted(scan_root.rglob("*_report.json")):
        rel = str(p.relative_to(REPO_ROOT)).replace("\\", "/")
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception as ex:  # noqa: BLE001
            rep.check("integrity::{}::parses".format(p.name), False,
                      "unparseable report: {}".format(ex), code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
            continue
        if "meta" not in obj:
            continue
        findings = report_integrity_findings(obj, rel)
        rep.check("integrity::{}".format(rel), findings == [],
                  "report-integrity problems: {}".format([(lbl, str(cd)) for lbl, cd in findings]),
                  code=(findings[0][1] if findings else C.TRANSITION_REPORT_INTEGRITY_FAILED))
        scanned += 1
    rep.check("integrity::non_vacuous", scanned >= 1,
              "must scan >= 1 real report under {} (got {})".format(args.reports_dir, scanned),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="transition-report-integrity", pack=None, strict=strict, status=rep.status,
        record_count=scanned, records_total=scanned,
        report_type="wf.transition.report_integrity.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "transition_report_integrity_report.json")
    rep.print_summary("transition-report-integrity")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
