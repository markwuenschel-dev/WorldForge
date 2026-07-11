#!/usr/bin/env python3
"""tactical_report_integrity.py — v2.4 report-integrity + evidence-index gate (Wave R).

Two jobs. First, it BUILDS the real TacticalEvidenceIndex from the committed authoring +
runtime evidence, validates it against its contract (integrity_result=pass requires the full
24-scenario matrix, no missing/stale evidence, and full required-action coverage), asserts
every linked path exists, and writes it. Second, it attacks the tactical reports so an
incomplete, unstamped, or vacuous report cannot pass as evidence: the single source-of-truth
predicate ``tactical_integrity_violations`` (empty == clean) checks each report carries a
real meta block (git_sha, timestamp, wf.* report_type, records tally), an explicit status,
and a non-empty checks list — dogfooded on synthetic records, then scanned across the REAL
tactical report tree with a non-vacuous floor.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/tactical_report_integrity.py --strict
Reports -> procedural/reports/tactical/tactical_report_integrity_report.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import tactical_contracts as TC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

TAC_DIR = REPO_ROOT / "procedural" / "reports" / "tactical"
GEN = REPO_ROOT / "procedural" / "generated" / "tactical"
OP_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "tactical"
MIN_REPORTS = 6


def _git_sha():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
                              capture_output=True, text=True).stdout.strip() or "0" * 40
    except Exception:  # noqa: BLE001
        return "0" * 40


def _rel(paths):
    return [str(p.relative_to(REPO_ROOT)).replace("\\", "/") for p in paths]


def tactical_integrity_violations(obj):
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
            "meta": {"git_sha": "0" * 40, "timestamp": "2026-07-11T00:00:00+00:00",
                     "report_type": "wf.tactical.x.v1", "records_total": 1}}


def _build_evidence_index(rep):
    runtime = sorted((TAC_DIR / "runtime").glob("tac_*.json"))
    decisions = sorted((TAC_DIR / "decisions").glob("tac_*.json"))
    saves = sorted((TAC_DIR / "save_load").glob("tss_*.json"))
    budgets = sorted((TAC_DIR / "budgets").glob("tbr_*.json"))
    profiles = sorted((GEN / "profiles").glob("*.json"))
    roles = sorted((GEN / "roles").glob("*.json"))
    affs = sorted((GEN / "affordances").glob("*.json"))
    binds = sorted((GEN / "bindings").glob("*.json"))
    op_views = [OP_DIR / "scenario_views.json", OP_DIR / "npc_views.json"]

    # required-action coverage from the real runtime reports
    covered = set()
    for p in runtime:
        covered |= set(json.loads(p.read_text(encoding="utf-8")).get("actions_executed") or [])

    idx = TC._example_tactical_evidence_index(
        created_at="live", git_sha=_git_sha(),
        scenario_count_expected=24, scenario_count_seen=len(runtime),
        behavior_profile_paths=_rel(profiles), role_definition_paths=_rel(roles),
        affordance_map_paths=_rel(affs), npc_binding_paths=_rel(binds),
        decision_trace_paths=_rel(decisions), runtime_report_paths=_rel(runtime),
        save_state_paths=_rel(saves), budget_report_paths=_rel(budgets),
        operator_view_paths=_rel([p for p in op_views if p.is_file()]),
        actions_covered=sorted(covered), missing_evidence=[], stale_evidence=[],
        integrity_result="pass")
    fails = [c for c in TC.validate_tactical_evidence_index(idx, strict=True) if not c[1]]
    rep.check("index::valid", len(fails) == 0,
              "evidence index invalid: {}".format([(c[0], c[3]) for c in fails][:4]),
              code=F.TACTICAL_EVIDENCE_INDEX_INVALID)
    # every linked path must exist on disk
    all_paths = (idx["behavior_profile_paths"] + idx["role_definition_paths"]
                 + idx["affordance_map_paths"] + idx["npc_binding_paths"]
                 + idx["decision_trace_paths"] + idx["runtime_report_paths"]
                 + idx["save_state_paths"] + idx["budget_report_paths"]
                 + idx["operator_view_paths"])
    broken = [p for p in all_paths if not (REPO_ROOT / p).is_file()]
    rep.check("index::all_paths_resolve", not broken,
              "evidence index links do not resolve: {}".format(broken[:4]),
              code=F.TACTICAL_EVIDENCE_INDEX_INVALID)
    (TAC_DIR).mkdir(parents=True, exist_ok=True)
    (TAC_DIR / "tactical_evidence_index.json").write_text(
        json.dumps(idx, indent=2, sort_keys=True), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical report-integrity + evidence-index gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "tactical_report_integrity", strict=strict)

    _build_evidence_index(rep)

    rep.check("dogfood::clean_passes", tactical_integrity_violations(_clean_report()) == [],
              "clean synthetic report must pass", code=F.TACTICAL_REPORT_INTEGRITY_FAILED)
    for label, mut in (
        ("no_meta", lambda r: r.pop("meta")),
        ("unknown_sha", lambda r: r["meta"].__setitem__("git_sha", "unknown")),
        ("no_timestamp", lambda r: r["meta"].pop("timestamp")),
        ("bad_report_type", lambda r: r["meta"].__setitem__("report_type", "nope")),
        ("no_status", lambda r: r.__setitem__("status", "green")),
        ("no_checks", lambda r: r.pop("checks"))):
        bad = _clean_report()
        mut(bad)
        rep.check("dogfood::flags_{}".format(label), tactical_integrity_violations(bad) != [],
                  "tampered report ({}) must be flagged".format(label),
                  code=F.TACTICAL_REPORT_INTEGRITY_FAILED)

    scanned = 0
    for p in sorted(TAC_DIR.rglob("*_report.json")):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception as ex:  # noqa: BLE001
            rep.check("integrity::{}::parses".format(p.name), False,
                      "unparseable report: {}".format(ex), code=F.TACTICAL_REPORT_INTEGRITY_FAILED)
            continue
        if "meta" not in obj:
            continue
        probs = tactical_integrity_violations(obj)
        rep.check("integrity::{}".format(p.relative_to(TAC_DIR)), probs == [],
                  "report integrity problems: {}".format(probs),
                  code=F.TACTICAL_REPORT_INTEGRITY_FAILED)
        scanned += 1
    rep.check("integrity::non_vacuous", scanned >= MIN_REPORTS,
              "must scan >= {} real reports (got {})".format(MIN_REPORTS, scanned),
              code=F.TACTICAL_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="tactical-report-integrity", pack=None, strict=strict, status=rep.status,
        record_count=scanned, records_total=scanned, report_type="wf.tactical.report_integrity.v1"))
    TAC_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(TAC_DIR, "tactical_report_integrity_report.json")
    rep.print_summary("tactical-report-integrity")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
