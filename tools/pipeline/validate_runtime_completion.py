#!/usr/bin/env python3
"""validate_runtime_completion.py — WorldForge v1.6 completion classification gate (Agent 5B).

Validates every per-scenario completion report against the frozen contract and
proves the batch is honest: exactly one report per scenario (no partial batch
laundered as success), each report's class is legal, and each carries its owning
failure_code. Whether the missions actually completed is a separate, blocking-
under-STRICT signal: any scenario not classified completed_runtime is flagged
(WARN -> blocking under STRICT), so an all-staged offline run is green without
STRICT and honestly not-green with it.

Usage:
    python tools/pipeline/validate_runtime_completion.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/runtime/completion/validate_runtime_completion_report.json
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_completion_contract as CC
import runtime_scenario_contract as SC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

SKIP_FILES = {"gamma_rollup.json", "run_playtest_forge_gamma_report.json",
              "validate_runtime_completion_report.json",
              "validate_playtest_gamma_no_fake_green_report.json",
              "validate_playtest_gamma_rollup_report.json",
              # P1 + v1.6x headless batch rollups / gate reports (not completion reports).
              "p1_rollup.json", "run_live_pie_batch_gate_report.json",
              "headless_rollup.json", "run_headless_runtime_batch_gate_report.json"}


def load_completion_reports():
    d = REPO_ROOT / CC.COMPLETION_REPORTS_REL
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            if p.name in SKIP_FILES:
                continue
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def n_scenarios():
    d = REPO_ROOT / SC.SCENARIO_GENERATED_REL
    return len(list(d.glob("*.json"))) if d.is_dir() else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 completion classification gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    reports = load_completion_reports()
    expected = n_scenarios()
    if not reports:
        rep.error("no completion reports — run 'make run-playtest-forge-gamma' first")

    classes = Counter()
    for sid in sorted(reports):
        rpt = reports[sid]
        for name, ok, detail, code in CC.validate_completion(rpt, strict=strict):
            rep.check("{}::{}".format(sid, name), ok, detail, code=code)
        classes[rpt.get("completion_class")] += 1

    # No partial batch: one report per scenario.
    rep.check("no_partial_batch", len(reports) == expected and expected > 0,
              "{}/{} completion reports (expected one per scenario)".format(len(reports), expected),
              code=C.PLAYTEST_GAMMA_PARTIAL_COMPLETION)

    completed = classes.get("completed_runtime", 0)
    # Honest completion signal: WARN (blocking under STRICT) when not all completed.
    rep.check("all_completed_runtime", completed == len(reports) and len(reports) > 0,
              "{}/{} completed_runtime; classes={}".format(completed, len(reports), dict(classes)),
              code=C.RUNTIME_LIVE_RUN_PENDING, warn_only=(completed < len(reports)))

    rep.finalize()
    rep.set_meta(build_meta(command="validate-runtime-completion", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(reports),
                            report_type="wf.runtime.completion_report.v1",
                            extra={"by_class": dict(classes), "completed_runtime": completed}))
    rep.write(REPO_ROOT / CC.COMPLETION_REPORTS_REL, "validate_runtime_completion_report.json")
    rep.print_summary("validate-runtime-completion")
    print("[validate-runtime-completion] {} reports, classes={}".format(len(reports), dict(classes)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
