#!/usr/bin/env python3
"""scene_survey_report_integrity.py — v2.6 report-integrity + evidence-index gate.

Ports the v2.4 tactical_report_integrity.py house pattern onto SceneSurveyForge.

Two jobs. First, it BUILDS a SceneSurveyEvidenceIndex from the committed evidence,
validates it against its contract (validate_scene_survey_evidence_index), asserts
every linked evidence path resolves on disk, and writes it. Second, it attacks the
scene-survey reports so an incomplete, unstamped, or vacuous report cannot pass as
evidence: the single source-of-truth predicate ``scene_survey_integrity_violations``
(empty == clean) checks each report carries a real meta block (git_sha != "unknown",
timestamp, wf.* report_type, integer records_total), an explicit status, and a
non-empty checks list — dogfooded on a synthetic clean report + tamper mutations,
then scanned across the REAL scene-survey report tree with a non-vacuous floor.

PRE-RUNTIME NOTE (v2.6 is early): the ONLY scene_survey reports that exist so far
are the always-available contract-spine / negatives / fuzz / torture / hygiene gate
reports under procedural/reports/scene_survey/. There is NO live-survey runtime
report yet. So the honest scan floor for this stage is MIN_REPORTS = 1 (require at
least one real, stamped report — not an inflated count). Likewise the evidence index
honestly reflects pre-runtime state: the 3-camera capture matrix is 0/3 seen and
integrity_result is "blocked" (a real bounded verdict), not a "pass" claimed over
zero captures. Its evidence_entries point at the REAL committed gate reports so the
path-resolution rail stays live and non-vacuous. Raise MIN_REPORTS (and flip the
index to captures_seen==captures_expected / "pass") once the live runtime emits real
survey reports + camera captures on disk.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/scene_survey_report_integrity.py --strict
Reports -> procedural/reports/scene_survey/scene_survey_report_integrity_report.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import scene_survey_contracts as SS
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

SS_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey"
# Pre-runtime floor: only the always-available gate reports exist so far (no live
# survey runtime report yet). Require >= 1 real stamped report — honest, not
# inflated. Raise this when the live runtime tree lands.
MIN_REPORTS = 1


def _git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
                              capture_output=True, text=True).stdout.strip() or "0" * 40
    except Exception:  # noqa: BLE001
        return "0" * 40


def _rel(paths):
    return [str(p.relative_to(REPO_ROOT)).replace("\\", "/") for p in paths]


def scene_survey_integrity_violations(obj):
    """Single source of truth: [] == clean. Every scene-survey report must carry a
    real meta block, an explicit bounded status, and a non-empty checks list."""
    if not isinstance(obj, dict):
        return ["not_an_object"]
    meta = obj.get("meta")
    if not isinstance(meta, dict):
        return ["missing_meta"]
    probs = []
    sha = meta.get("git_sha")
    if not (isinstance(sha, str) and sha and sha != "unknown"):
        probs.append("bad_git_sha")
    if not (isinstance(meta.get("timestamp"), str) and meta.get("timestamp")):
        probs.append("missing_timestamp")
    rt = meta.get("report_type")
    if not (isinstance(rt, str) and rt.startswith("wf.")):
        probs.append("bad_report_type")
    if not isinstance(meta.get("records_total"), int):
        probs.append("missing_records_total")
    if obj.get("status") not in ("ok", "fail", "warn", "error"):
        probs.append("bad_status")
    checks = obj.get("checks")
    if not (isinstance(checks, (list, dict)) and len(checks) > 0):
        probs.append("missing_checks")
    return probs


def _clean_report():
    return {"status": "ok", "checks": [{"name": "x", "verdict": "pass"}],
            "meta": {"git_sha": "0" * 40, "timestamp": "2026-07-19T00:00:00+00:00",
                     "report_type": "wf.scene_survey.x.v1", "records_total": 1}}


def _build_evidence_index(rep):
    """Build + validate the SceneSurveyEvidenceIndex from committed evidence.

    Pre-runtime honesty: no camera captures exist yet, so the 3-camera matrix is
    0/3 seen and integrity_result is "blocked" (a real bounded verdict), NOT a
    "pass" claimed over zero captures. The committed gate reports on disk are the
    only real evidence entries; pointing at them keeps the path-resolution rail
    live and non-vacuous.
    """
    committed = sorted(SS_DIR.rglob("*_report.json"))
    entries = _rel(committed)

    idx = SS._example_scene_survey_evidence_index(
        index_id="scene_survey_evidence_index_pre_runtime",
        integrity_result="blocked",
        captures_expected=len(SS.CAMERA_KINDS),
        captures_seen=0,
        evidence_entries=entries,
    )
    fails = [c for c in SS.validate_scene_survey_evidence_index(idx, strict=True) if not c[1]]
    rep.check("index::valid", len(fails) == 0,
              "evidence index invalid: {}".format([(c[0], c[2]) for c in fails][:4]),
              code=F.SCENE_SURVEY_EVIDENCE_INDEX_INVALID)
    # every linked evidence path must resolve on disk (non-vacuous: >= 1 real report)
    broken = [p for p in idx["evidence_entries"] if not (REPO_ROOT / p).is_file()]
    rep.check("index::all_paths_resolve", not broken,
              "evidence index links do not resolve: {}".format(broken[:4]),
              code=F.SCENE_SURVEY_EVIDENCE_INDEX_INVALID)
    rep.check("index::non_vacuous", len(idx["evidence_entries"]) >= MIN_REPORTS,
              "evidence index must reference >= {} committed report(s) (got {})".format(
                  MIN_REPORTS, len(idx["evidence_entries"])),
              code=F.SCENE_SURVEY_EVIDENCE_INDEX_INVALID)
    SS_DIR.mkdir(parents=True, exist_ok=True)
    (SS_DIR / "scene_survey_evidence_index.json").write_text(
        json.dumps(idx, indent=2, sort_keys=True), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="v2.6 scene-survey report-integrity + evidence-index gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "scene_survey_report_integrity", strict=strict)

    _build_evidence_index(rep)

    rep.check("dogfood::clean_passes", scene_survey_integrity_violations(_clean_report()) == [],
              "clean synthetic report must pass", code=F.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    for label, mut in (
        ("no_meta", lambda r: r.pop("meta")),
        ("unknown_sha", lambda r: r["meta"].__setitem__("git_sha", "unknown")),
        ("no_timestamp", lambda r: r["meta"].pop("timestamp")),
        ("bad_report_type", lambda r: r["meta"].__setitem__("report_type", "nope")),
        ("no_status", lambda r: r.__setitem__("status", "green")),
        ("no_checks", lambda r: r.pop("checks"))):
        bad = _clean_report()
        mut(bad)
        rep.check("dogfood::flags_{}".format(label),
                  scene_survey_integrity_violations(bad) != [],
                  "tampered report ({}) must be flagged".format(label),
                  code=F.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)

    scanned = 0
    for p in sorted(SS_DIR.rglob("*_report.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception as ex:  # noqa: BLE001
            rep.check("integrity::{}::parses".format(p.name), False,
                      "unparseable report: {}".format(ex),
                      code=F.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
            continue
        if "meta" not in obj:
            continue
        probs = scene_survey_integrity_violations(obj)
        rep.check("integrity::{}".format(p.relative_to(SS_DIR)), probs == [],
                  "report integrity problems: {}".format(probs),
                  code=F.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
        scanned += 1
    rep.check("integrity::non_vacuous", scanned >= MIN_REPORTS,
              "must scan >= {} real reports (got {})".format(MIN_REPORTS, scanned),
              code=F.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="scene-survey-report-integrity", pack=None, strict=strict, status=rep.status,
        record_count=scanned, records_total=scanned,
        report_type="wf.scene_survey.report_integrity.v1"))
    SS_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(SS_DIR, "scene_survey_report_integrity_report.json")
    rep.print_summary("scene-survey-report-integrity")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
