#!/usr/bin/env python3
"""v2.6 assembler probes — hostile tests for the REPORT ASSEMBLER, not for artifacts.

Why this file exists, and why the known-bads harness cannot replace it
=====================================================================
``run_v2_6_known_bads.py`` drives three STATIC validators
(``validate_scene_survey_subject`` / ``_report`` / ``validate_subject_binding``)
over artifacts read off disk. Every one of them takes a finished document. None of
them ever executes ``run_scene_survey_probe._build_report``.

That gap is exactly where the vacuous-binding defect lived. Before this change the
assembler copied ``map_asset_path``/``subject_id``/``subject_resolved_by`` out of the
caller's subject into the report and the pair validator then compared the subject to
a copy of itself, so ``sb::subject_id_match``, ``sb::map_match`` and
``sb::resolver_not_worldforge`` could not fail for any input whatsoever. A static
fixture can hand-author a disagreeing pair and watch the rails reject it — proving
the rails work, while proving nothing about an assembler that will never emit a
disagreeing pair. A green known-bads gate was therefore compatible with a completely
unfalsifiable runtime path.

These probes close that hole by calling ``_build_report`` directly with a fabricated
``runs`` list. No editor, no ``-nullrhi`` boot, no plugin: ``_one_run`` returns a
plain dict (``exit_code``/``stdout``/``secs``/``far``/``parsed``), so the assembler's
entire input surface is constructible in-process. What is under test here is the
WIRING — which channel each report field is actually sourced from — which is the one
thing no artifact-level test can see.

Anti-vacuity: every hostile probe is paired with a positive control asserting the
same rail passes on an honest input. A probe suite that only ever asserts "rejected"
would stay green if the assembler started rejecting everything.

Run:  PYTHONUTF8=1 STRICT=1 python tools/pipeline/run_v2_6_assembler_probes.py --strict
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import run_scene_survey_probe as RP           # noqa: E402
import scene_survey_contracts as SS           # noqa: E402
from failure_codes import FailureCode as C    # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport      # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey" / "hostile"

MAP = "/Game/Fixture/Lvl_Fixture"
OTHER_MAP = "/Game/Fixture/Lvl_SomewhereElse"


class _Args(object):
    """Minimal stand-in for the argparse namespace ``_build_report`` reads."""

    def __init__(self):
        self.operation_id = "op_v2_6_assembler_probe"
        self.engine_root = None
        self.project = "D:/fixture/Fixture.uproject"
        self.repeat = 1


def _parsed(actors=12, support_total=158, markers=3, accepted=3):
    """A stdout marker-channel parse result consistent with the far doc below."""
    return {
        "support": {"total": support_total, "valid": 120, "unsupported": 20,
                    "edge": 10, "blocked": 8, "trace_error": 0, "unknown": 0},
        "enum": {"actors": actors, "components": 44},
        "markers": [{"accepted": i < accepted, "overlap": False, "clearance": True,
                     "grounded": True} for i in range(markers)],
    }


def _far(observed_world_package=MAP, loaded=True, actors=12, support_total=158,
         markers=3, accepted=3, error=None, **over):
    """A far-side document. Defaults describe an HONEST run of the requested map."""
    d = {
        "operation_id": "op_v2_6_assembler_probe",
        # Echoes of the request — present because the real far side emits them.
        # Nothing in the assembler may treat these as observations.
        "map": MAP,
        "subject_id": "subject_fixture_alpha",
        "subject_kind": "point",
        "anchor_mode": "explicit_transform",
        "subject_resolved_by": "caller",
        "subject_source": "env:WF_SURVEY_SUBJECT",
        "subject_resolved": True,
        "anchor_detail": "used the caller's explicit transform verbatim",
        "observed_anchor_location": [1200.0, -450.0, 92.5],
        "observed_anchor_object_path": None,
        "loaded": loaded,
        "observed_world_package": observed_world_package,
        "observed_engine_version": "5.8.0-fixture",
        "resolved_uproject": "D:/fixture/Fixture.uproject",
        "actor_count": actors,
        "support_total": support_total,
        "marker_total": markers,
        "marker_accepted": accepted,
        "captures_requested": [],
        "camera_capture_ran": False,
        "camera_capture_reason": "no captures were requested by the caller (capture is opt-in)",
        "proxy_pass_ran": False,
        "proxy_pass_reason": "fixture",
        "survey_statics_available": True,
        "error": error,
        "traceback": None,
    }
    d.update(over)
    return d


def _runs(far, parsed=None, exit_code=0):
    return [{"exit_code": exit_code, "stdout": "", "secs": 1.0,
             "far": far, "parsed": parsed if parsed is not None else _parsed()}]


def _build(far, subject=None, parsed=None, exit_code=0, determinism_ok=True):
    """Drive the real assembler. Returns (report, binding_fails)."""
    subj = subject if subject is not None else SS._example_scene_survey_subject()
    report, _dis, _corr, binding_fails = RP._build_report(
        _Args(), subj, [], _runs(far, parsed, exit_code), determinism_ok)
    return report, binding_fails


def _codes(report):
    return {str(c) for c in report.get("failure_codes") or []}


def _rails(binding_fails):
    return {c[0] for c in binding_fails}


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 report-assembler hostile probes.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # ---------------------------------------------------------------- controls --
    # POSITIVE CONTROL. An honest run of the requested map must bind clean and raise
    # neither world code. Without this, every "rejected" probe below would stay green
    # if the assembler simply failed everything.
    honest, honest_fails = _build(_far())
    rep.check("asm::control::honest_binds_clean", not honest_fails,
              "an honest far-side document must bind clean — a suite where nothing "
              "passes proves nothing (failed rails: {})".format(sorted(_rails(honest_fails))),
              code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)
    rep.check("asm::control::honest_raises_no_world_code",
              not ({str(C.SCENE_SURVEY_MAP_LOAD_FAILED),
                    str(C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED)} & _codes(honest)),
              "an honest run must raise neither WF1121 nor WF1122 (got {})".format(
                  sorted(_codes(honest))),
              code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)
    rep.check("asm::control::honest_status_not_fail", honest.get("status") != "fail",
              "an honest run must not be a hard failure (status={}, codes={})".format(
                  honest.get("status"), sorted(_codes(honest))),
              code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

    # ------------------------------------------------------- the wiring itself --
    # THE REGRESSION GUARD. This is the probe that would have caught the original
    # defect and that fails the instant anyone re-sources map_asset_path from the
    # subject. The far doc below echoes the REQUESTED map in far["map"] (exactly as
    # the real far side does) while the world actually open is a different one.
    wrong = _far(observed_world_package=OTHER_MAP)
    wrong_report, wrong_fails = _build(wrong)
    rep.check("asm::map_is_observed_not_requested",
              wrong_report.get("map_asset_path") != MAP,
              "report map_asset_path must come from the OBSERVED world, never from "
              "the subject or from far['map'] (both of which are the request echoed "
              "back). Got {!r} for a run whose open world was {!r}".format(
                  wrong_report.get("map_asset_path"), OTHER_MAP),
              code=C.SCENE_SURVEY_SUBJECT_MISMATCH)
    rep.check("asm::wrong_world_breaks_binding",
              "sb::map_match" in _rails(wrong_fails),
              "surveying a different world than the caller asked for must fail "
              "sb::map_match — this rail was vacuous while the assembler copied the "
              "subject's map into the report (failed rails: {})".format(
                  sorted(_rails(wrong_fails))),
              code=C.SCENE_SURVEY_SUBJECT_MISMATCH)
    rep.check("asm::wrong_world_raises_wf1122",
              str(C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED) in _codes(wrong_report),
              "a world-identity mismatch must raise WF1122 (got {})".format(
                  sorted(_codes(wrong_report))),
              code=C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED)
    rep.check("asm::wrong_world_is_hard_fail", wrong_report.get("status") == "fail",
              "a survey of the wrong world is a wrong answer, not a partial one "
              "(status={})".format(wrong_report.get("status")),
              code=C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED)

    # ------------------------------------------------------------ load failure --
    # The defect this closes: load_level's return was stored in doc["loaded"] and
    # consumed by nothing, so in explicit_transform mode (which never searches the
    # level) a failed load surveyed whatever world was already open.
    unloaded = _far(loaded=False, observed_world_package="/Game/Startup/DefaultMap")
    unloaded_report, _ = _build(unloaded)
    rep.check("asm::load_failure_raises_wf1121",
              str(C.SCENE_SURVEY_MAP_LOAD_FAILED) in _codes(unloaded_report),
              "load_level returning False must raise WF1121 (got {})".format(
                  sorted(_codes(unloaded_report))),
              code=C.SCENE_SURVEY_MAP_LOAD_FAILED)
    rep.check("asm::load_failure_is_hard_fail",
              unloaded_report.get("status") == "fail",
              "a failed map load must be a hard failure (status={})".format(
                  unloaded_report.get("status")),
              code=C.SCENE_SURVEY_MAP_LOAD_FAILED)
    # A far side that failed to load but ALSO failed to set its own error string must
    # still be caught: the near side re-derives the verdict from the raw observation
    # rather than trusting the far side's self-report.
    silent = _far(loaded=False, observed_world_package="/Game/Startup/DefaultMap",
                  error=None)
    silent_report, _ = _build(silent)
    rep.check("asm::silent_load_failure_still_caught",
              silent_report.get("status") == "fail",
              "a far side that failed to load and reported no error of its own must "
              "still fail here — the verdict is re-derived from raw, not inherited "
              "(status={}, codes={})".format(silent_report.get("status"),
                                             sorted(_codes(silent_report))),
              code=C.SCENE_SURVEY_MAP_LOAD_FAILED)

    # --------------------------------------------------- unreadable identity ----
    unknown = _far(observed_world_package=None)
    unknown_report, _ = _build(unknown)
    rep.check("asm::unreadable_identity_raises_wf1122",
              str(C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED) in _codes(unknown_report),
              "a world whose identity could not be read is NOT a verified world and "
              "must raise WF1122 (got {})".format(sorted(_codes(unknown_report))),
              code=C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED)
    rep.check("asm::unreadable_identity_not_reported_as_map",
              unknown_report.get("map_asset_path") != MAP,
              "an unobserved map must never be reported as the observed one "
              "(got {!r})".format(unknown_report.get("map_asset_path")),
              code=C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED)

    # ------------------------------------------------------------ normalisation --
    # /Game/Maps/Foo.Foo and /Game/Maps/Foo name one package. Treating them as
    # different would produce a false WF1122 on every honest run whose engine returns
    # the object-path form, which is the failure mode that makes people delete rails.
    dotted = _far(observed_world_package=MAP + ".Lvl_Fixture")
    dotted_report, dotted_fails = _build(dotted)
    rep.check("asm::package_form_normalised",
              str(C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED) not in _codes(dotted_report)
              and "sb::map_match" not in _rails(dotted_fails),
              "'{}.Lvl_Fixture' and '{}' name the same package and must compare equal "
              "(codes={}, rails={})".format(MAP, MAP, sorted(_codes(dotted_report)),
                                            sorted(_rails(dotted_fails))),
              code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)
    # ...but normalisation must not be so loose that a different map slips through.
    near_miss = _far(observed_world_package=MAP + "_Backup")
    near_miss_report, _ = _build(near_miss)
    rep.check("asm::normalisation_not_a_prefix_match",
              str(C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED) in _codes(near_miss_report),
              "'{}_Backup' is a DIFFERENT map and must not be normalised into a match "
              "(got {})".format(MAP, sorted(_codes(near_miss_report))),
              code=C.SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED)

    # A case-different package satisfies the (case-folded) identity verdict but not
    # the (exact-equality) sb::map_match rail. Assert it FAILS CLOSED rather than
    # slipping through — the documented behaviour must be the tested behaviour.
    cased = _far(observed_world_package=MAP.upper())
    cased_report, cased_fails = _build(cased)
    rep.check("asm::case_difference_fails_closed",
              cased_report.get("status") == "fail" or bool(cased_fails),
              "a world package differing only in case must not be silently accepted "
              "(status={}, rails={}, codes={})".format(
                  cased_report.get("status"), sorted(_rails(cased_fails)),
                  sorted(_codes(cased_report))),
              code=C.SCENE_SURVEY_SUBJECT_MISMATCH)

    # ------------------------------------------------- honest classification ----
    # These two rails are NOT observations and this suite must not pretend otherwise.
    # WorldForge has no channel that could ever observe a different subject_id or a
    # different resolver, so they are caller_supplied continuity checks. Asserting
    # that fact here keeps a future reader from mistaking them for evidence.
    rep.check("asm::subject_id_is_caller_supplied",
              honest.get("subject_id") == SS._example_scene_survey_subject()["subject_id"],
              "subject_id is caller vocabulary echoed for continuity; there is no "
              "observation channel for it and this suite does not claim one",
              code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="v2-6-assembler-probes", pack=args.pack, strict=strict,
        status=rep.status, report_type="wf.scene_survey.assembler_probes.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "v2_6_assembler_probes_report.json")
    rep.print_summary("v2-6-assembler-probes")
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
