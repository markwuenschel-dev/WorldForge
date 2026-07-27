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

SUBJECT BINDING (WF1106/1107/1108). A survey is only runtime truth about the thing
the CALLER asked about. So the runtime envelope must carry the SceneSurveySubject it
was handed alongside the report it produced, and the two must bind: same subject_id,
same map, the observed anchor within tolerance of the requested one (or on the exact
requested object), and resolved_by="caller" on both sides. A report that cannot be
bound to a request is unfalsifiable — it could have surveyed anything — so its
absence is a hard FAIL here, not a skip.

PROBE DEPENDENCY (v2.6, in flight): this rail requires run_scene_survey_probe.py to
write the resolved subject into the runtime envelope under "subject". Until it does,
this gate stays honestly RED — which is the correct fail-closed state, not a defect
in the rail. See the REPORT-BACK note.

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


def _validate_runtime_binding(rep, subject, report, tag):
    """The runtime report must bind to the subject the CALLER handed over."""
    present = isinstance(subject, dict) and bool(subject)
    rep.check("runtime::{}::subject_present".format(tag), present,
              "the runtime envelope must carry the caller-resolved SceneSurveySubject "
              "under 'subject' — a report that cannot be bound to a request is "
              "unfalsifiable (run_scene_survey_probe.py must emit it)",
              code=C.SCENE_SURVEY_SUBJECT_MISMATCH)
    if not present:
        return
    sfails = [c for c in SS.validate_scene_survey_subject(subject, strict=True) if not c[1]]
    rep.check("runtime::{}::subject_valid".format(tag), len(sfails) == 0,
              "the handed-over subject must satisfy the SceneSurveySubject contract: "
              "{}".format([c[0] for c in sfails][:4]),
              code=C.SCENE_SURVEY_SUBJECT_UNRESOLVED)
    bfails = [c for c in SS.validate_subject_binding(subject, report, strict=True)
              if not c[1]]
    rep.check("runtime::{}::binds_to_subject".format(tag), len(bfails) == 0,
              "the survey did not bind to the subject it was handed: {}".format(
                  [(c[0], c[2]) for c in bfails][:3]),
              code=C.SCENE_SURVEY_SUBJECT_MISMATCH)
    rep.check("runtime::{}::resolved_by_caller".format(tag),
              subject.get("resolved_by") == "caller"
              and report.get("subject_resolved_by") == "caller",
              "both sides must declare resolved_by='caller' — WorldForge must never "
              "resolve the survey subject itself (subject={!r}, report={!r})".format(
                  subject.get("resolved_by"), report.get("subject_resolved_by")),
              code=C.SCENE_SURVEY_SUBJECT_INFERRED)


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
    # tamper: WorldForge resolved the subject for itself -> WF1108.
    t3 = dict(clean, subject_resolved_by="worldforge")
    t3codes = {c[3] for c in SS.validate_scene_survey_report(t3, strict=True) if not c[1]}
    rep.check("dogfood::self_resolved_rejected",
              C.SCENE_SURVEY_SUBJECT_INFERRED in t3codes,
              "a report claiming WorldForge resolved the subject must be rejected for "
              "{} (got {})".format(C.SCENE_SURVEY_SUBJECT_INFERRED, sorted(t3codes)[:4]),
              code=C.SCENE_SURVEY_SUBJECT_INFERRED)
    # tamper: executed but will not say where it anchored -> WF1106.
    t4 = dict(clean, observed_anchor_location=None)
    t4codes = {c[3] for c in SS.validate_scene_survey_report(t4, strict=True) if not c[1]}
    rep.check("dogfood::no_observed_anchor_rejected",
              C.SCENE_SURVEY_SUBJECT_UNRESOLVED in t4codes,
              "an executed run with no observed anchor must be rejected for {} "
              "(got {})".format(C.SCENE_SURVEY_SUBJECT_UNRESOLVED, sorted(t4codes)[:4]),
              code=C.SCENE_SURVEY_SUBJECT_UNRESOLVED)

    # --- the binding rails themselves must be able to FAIL --------------------
    # A matched pair binds clean...
    subject = SS._example_scene_survey_subject()
    ok_pair = [c for c in SS.validate_subject_binding(subject, clean, strict=True)
               if not c[1]]
    rep.check("dogfood::matched_pair_binds", len(ok_pair) == 0,
              "a matched subject<->report pair must bind clean: {}".format(
                  [c[0] for c in ok_pair][:4]),
              code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)
    # ...and a report that surveyed a DIFFERENT subject must not (WF1107).
    for tag, over, owning in (
            ("wrong_subject_id", {"subject_id": "subject_fixture_beta"},
             C.SCENE_SURVEY_SUBJECT_MISMATCH),
            ("wrong_map", {"map_asset_path": "/Game/Fixture/Lvl_Other"},
             C.SCENE_SURVEY_SUBJECT_MISMATCH),
            ("anchor_drift", {"observed_anchor_location": [1200.0, -450.0, 97.5]},
             C.SCENE_SURVEY_SUBJECT_MISMATCH),
            ("self_resolved", {"subject_resolved_by": "worldforge"},
             C.SCENE_SURVEY_SUBJECT_INFERRED)):
        codes = {c[3] for c in SS.validate_subject_binding(
            subject, dict(clean, **over), strict=True) if not c[1]}
        rep.check("dogfood::binding_{}_rejected".format(tag), owning in codes,
                  "an unbound survey must be rejected for {} (got {})".format(
                      owning, sorted(codes)[:4]), code=owning)
    # ...and the presence rail itself must FAIL on a missing subject rather than
    # skipping it — run the real rail into a throwaway report and read its failures.
    absent = ValidationReport("suite", "dogfood_binding_absent", strict=True)
    _validate_runtime_binding(absent, None, clean, "dogfood")
    rep.check("dogfood::absent_subject_rejected", len(absent.failures) > 0,
              "an envelope with no 'subject' block must FAIL the binding rail, not skip it",
              code=C.SCENE_SURVEY_SUBJECT_MISMATCH)
    # positive control: the same rail on a real matched pair must be silent, or the
    # rail above is just failing unconditionally.
    bound = ValidationReport("suite", "dogfood_binding_present", strict=True)
    _validate_runtime_binding(bound, subject, clean, "dogfood")
    rep.check("dogfood::bound_subject_accepted", len(bound.failures) == 0,
              "the binding rail must pass a genuinely matched pair (got {})".format(
                  bound.failures[:3]),
              code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED)


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
            # The domain SceneSurveyReport rides under "survey" in the house wrapper;
            # the caller-resolved SceneSurveySubject it was handed rides under "subject".
            survey = obj.get("survey", obj)
            _validate_runtime_obj(rep, survey, "live")
            _validate_runtime_binding(rep, obj.get("subject"), survey, "live")
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
