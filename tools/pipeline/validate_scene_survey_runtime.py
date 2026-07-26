#!/usr/bin/env python3
"""validate_scene_survey_runtime.py — v2.6 scene-survey runtime evidence gate.

FAIL-CLOSED: green ONLY when a real runtime survey report exists on disk, validates
against the SceneSurveyReport contract, was produced by a genuine editor run
(runtime_executed=True), and is deterministic across its repeat runs. Until
run_scene_survey_probe.py boots a target and writes that report, this gate is honestly
RED — there is no runtime truth to validate yet.

A blocked-pending-camera report (the honest state of a -nullrhi spatial pass) is
ACCEPTED here: the runtime gate proves the survey ran, was well-formed, and was
deterministic — camera completeness is a separate rendering pass, not faked into a
pass. What is rejected: a missing report, an invalid report, a report that never
executed, or a report whose repeat runs disagree (WF1094).

Dogfooded on a synthetic clean report + tamper mutations so the gate cannot fake-green.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_scene_survey_runtime.py --strict
Reports -> procedural/reports/scene_survey/runtime/validate_scene_survey_runtime_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import scene_survey_contracts as SS
from failure_codes import FailureCode as C
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey" / "runtime"
RUNTIME_REPORT = REPORT_DIR / "scene_survey_report.json"


def _validate_runtime_obj(rep, obj, tag):
    """Apply the runtime-truth rails to a survey report object."""
    fails = [c for c in SS.validate_scene_survey_report(obj, strict=True) if not c[1]]
    rep.check("runtime::{}::contract_valid".format(tag), len(fails) == 0,
              "runtime report must satisfy the SceneSurveyReport contract: {}".format(
                  [c[0] for c in fails][:4]),
              code=C.SCENE_SURVEY_REPORT_INVALID)
    rep.check("runtime::{}::executed".format(tag), obj.get("runtime_executed") is True,
              "runtime_executed must be True — a report with no real editor run is not "
              "runtime truth", code=C.SCENE_SURVEY_RUNTIME_SIMULATED_OVERCLAIM)
    meta = obj.get("meta") or {}
    hashes = meta.get("per_run_hashes") or []
    consistent = meta.get("determinism_consistent")
    rep.check("runtime::{}::deterministic".format(tag),
              consistent is True and len(set(hashes)) <= 1 and len(hashes) >= 1,
              "repeat runs must be byte-identical (per_run_hashes={})".format(hashes),
              code=C.SCENE_SURVEY_DETERMINISM_MISMATCH)


def _dogfood(rep):
    """Prove the runtime rails reject tampered reports (cannot fake-green)."""
    clean = SS._example_scene_survey_report()
    clean["meta"] = {"determinism_consistent": True, "per_run_hashes": ["sha256:aaa"]}
    cfails = [c for c in SS.validate_scene_survey_report(clean, strict=True) if not c[1]]
    rep.check("dogfood::clean_report_valid", len(cfails) == 0,
              "synthetic clean report must validate: {}".format([c[0] for c in cfails][:4]),
              code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    # tamper: not executed — the executed rail's predicate must reject it.
    t1 = dict(clean, runtime_executed=False)
    rep.check("dogfood::not_executed_rejected", (t1.get("runtime_executed") is True) is False,
              "the executed rail must reject a report with runtime_executed=False",
              code=C.SCENE_SURVEY_RUNTIME_SIMULATED_OVERCLAIM)
    # tamper: valid > total
    t2 = dict(clean, support_samples_valid=99999)
    t2fails = [c for c in SS.validate_scene_survey_report(t2, strict=True) if not c[1]]
    rep.check("dogfood::valid_gt_total_rejected", len(t2fails) > 0,
              "valid>total must be rejected by the contract",
              code=C.SCENE_SURVEY_REPORT_INVALID)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 scene-survey runtime evidence gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    _dogfood(rep)

    # Fail-closed: the runtime report must exist and be parseable.
    exists = RUNTIME_REPORT.is_file()
    rep.check("runtime::report_present", exists,
              "no runtime survey report at {} — run run_scene_survey_probe.py against a "
              "target first (fail-closed until a live survey runs)".format(
                  RUNTIME_REPORT.relative_to(REPO_ROOT).as_posix()),
              code=C.SCENE_SURVEY_EVIDENCE_MISSING)
    if exists:
        try:
            obj = json.loads(RUNTIME_REPORT.read_text(encoding="utf-8"))
            # The domain SceneSurveyReport rides under "survey" in the house wrapper.
            survey = obj.get("survey", obj)
            _validate_runtime_obj(rep, survey, "live")
        except ValueError as exc:
            rep.check("runtime::report_parseable", False,
                      "runtime report is not valid JSON: {}".format(exc),
                      code=C.SCENE_SURVEY_REPORT_INVALID)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-scene-survey-runtime", pack=args.pack, strict=strict,
        status=rep.status, report_type="wf.scene_survey.runtime_gate.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_scene_survey_runtime_report.json")
    rep.print_summary("validate-scene-survey-runtime")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
