#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WorldForge v2.6 — on-disk hostile fixtures for the scene-survey surface.

`scene_survey_negatives.py` and `scene_survey_torture.py` prove the contract band
in-code. This complements them by materializing the mission's hostile scenario
list as ON-DISK JSON a dishonest submitter could actually hand us, then driving
each fixture through the REAL validator the shield itself calls.

Three honesty bars, in order of strength (the same ladder v2.5.1 established):

  1. the fixture is rejected at all;
  2. it is rejected for its OWNING failure code — a rejection for some unrelated
     reason proves nothing about the vector under test;
  3. where the catalogue names one, it is rejected BY its owning CHECK — the
     specific rail that is supposed to catch this lie, not a bystander.

Fixtures carry NO harness metadata. An embedded `_expected_code` key would itself
trip the strict unknown-key rail, producing a rejection that looks green and
proves nothing. The catalogue lives beside them in `index.json`.

Two anti-vacuity rails guard the suite itself:
  * positive controls — every driver must still ACCEPT the honest artifact, or
    "everything is rejected" would pass this file trivially;
  * a crash guard — a validator that raises on hostile input has not judged it,
    so an exception is a distinct failure from a rejection.

Coverage is declared, not implied: `NOT_YET_TESTABLE` names every vector from the
mission list that cannot be exercised at this commit and why. Silently dropping
them would read as "covered" when it is not.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/run_v2_6_known_bads.py --strict
Reports -> procedural/reports/scene_survey/hostile/v2_6_known_bads_report.json
"""

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import scene_survey_contracts as SS  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402

KB_DIR = REPO_ROOT / "procedural" / "known_bads" / "v2_6"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey" / "hostile"
CATALOGUE = KB_DIR / "index.json"

MIN_FIXTURES = 21


# --------------------------------------------------------------------------- #
# Vectors that this commit genuinely cannot test, and why. Declared so the
# coverage claim stays honest.
# --------------------------------------------------------------------------- #
NOT_YET_TESTABLE = {
    "request_hash_mismatch":
        "the runtime report does not yet emit request_hash; there is nothing to "
        "mismatch against",
    "subject_binding_hash_mismatch":
        "the runtime report does not yet emit subject_binding_hash",
    "runtime_report_copied_from_another_request":
        "replay detection needs request_hash in the report; without it the copy "
        "is indistinguishable from a legitimate re-run",
    "wrong_target_repository":
        "the scene-survey path does not yet compare resolved_target_repository "
        "against the request (the live bridge gate does, the survey gate does not)",
    "wrong_target_commit":
        "target_commit is never compared; only a 40-hex shape check exists, and "
        "only on the live bridge path",
    "temporary_markers_left_behind":
        "temporary_actor_count_* are not emitted; markers are trace-probed rather "
        "than spawned, so there is no count to leave dirty",
    "package_dirty_after_cleanup":
        "package_dirty_before / package_dirty_after are not observed or emitted",
    "nondeterministic_repeated_reports":
        "requires two real editor runs; determinism is enforced at runtime from "
        "per_run_hashes, which no static fixture can produce honestly",
    "screenshot_without_runtime_evidence":
        "no screenshot artifact is produced at all under the current -nullrhi "
        "pass, so the vector has no on-disk form yet",
}


# --------------------------------------------------------------------------- #
# Fixture construction. Deterministic; materialized then read back from disk so
# the thing under test is the bytes, not an in-memory object.
# --------------------------------------------------------------------------- #
def _subject(**over):
    return SS._example_scene_survey_subject(**over)


def _report(**over):
    return SS._example_scene_survey_report(**over)


def _fixtures():
    """slug -> (artifact, catalogue_entry)."""
    good_sub = _subject()
    out = {}

    def add(slug, artifact, driver, code, vector, check=None):
        entry = {"driver": driver, "expected_code": code, "vector": vector,
                 "fixture": slug + ".json"}
        if check:
            entry["expected_check"] = check
        out[slug] = (artifact, entry)

    # ---- subject contract ------------------------------------------------- #
    s = _subject()
    s.pop("map_asset_path")
    add("subject_missing_map", s, "subject_contract",
        C.SCENE_SURVEY_SUBJECT_UNRESOLVED,
        "a subject with no map — WorldForge would have to choose the level",
        "field::map_asset_path")

    s = _subject()
    s.pop("anchor_mode")
    add("subject_missing_anchor_mode", s, "subject_contract",
        C.SCENE_SURVEY_SUBJECT_UNRESOLVED,
        "a subject that never says how its anchor is expressed",
        "field::anchor_mode")

    add("subject_both_anchor_channels",
        _subject(anchor_mode="explicit_transform", anchor_location=[0.0, 0.0, 0.0],
                 anchor_object_path="/Game/M.M:PersistentLevel.A_0"),
        "subject_contract", C.SCENE_SURVEY_SUBJECT_UNRESOLVED,
        "both anchor channels populated — WorldForge would have to pick one",
        "ss::mode_exclusive")

    add("subject_neither_anchor_channel",
        _subject(anchor_location=None, anchor_object_path=None),
        "subject_contract", C.SCENE_SURVEY_SUBJECT_UNRESOLVED,
        "neither anchor channel populated — the caller never resolved the subject",
        "ss::mode_exclusive")

    add("subject_resolved_by_worldforge", _subject(resolved_by="worldforge"),
        "subject_contract", C.SCENE_SURVEY_SUBJECT_INFERRED,
        "a subject WorldForge claims to have resolved itself — the exact authority "
        "inversion v2.6 exists to refuse", "ss::resolved_by_caller")

    add("subject_empty_subject_id", _subject(subject_id=""),
        "subject_contract", C.SCENE_SURVEY_SUBJECT_UNRESOLVED,
        "a blank subject id — nothing to bind a report back to")

    s = _subject()
    s["surveyed_because"] = "the caller wanted it"
    add("subject_unknown_key", s, "subject_contract",
        C.SCENE_SURVEY_SUBJECT_UNRESOLVED,
        "an extra key smuggled onto the subject", "no_unknown_fields")

    add("subject_wrong_schema_version",
        _subject(schema_version="wf.scene_survey.survey_subject.v2"),
        "subject_contract", C.SCENE_SURVEY_SUBJECT_UNRESOLVED,
        "a subject claiming a schema version this build does not implement",
        "schema_version")

    # ---- subject <-> report binding ---------------------------------------- #
    add("binding_wrong_subject_id",
        {"subject": good_sub, "report": _report(subject_id="some_other_subject")},
        "subject_binding", C.SCENE_SURVEY_SUBJECT_MISMATCH,
        "a real survey of the wrong subject, returned against this request",
        "sb::subject_id_match")

    add("binding_substituted_map",
        {"subject": good_sub, "report": _report(map_asset_path="/Game/Maps/Other")},
        "subject_binding", C.SCENE_SURVEY_SUBJECT_MISMATCH,
        "right subject id, wrong level — still not the survey that was asked for",
        "sb::map_match")

    tsub = _subject(anchor_mode="explicit_transform",
                    anchor_location=[100.0, 200.0, 300.0], anchor_object_path=None)
    add("binding_transform_beyond_tolerance",
        {"subject": tsub,
         "report": _report(subject_id=tsub["subject_id"],
                           map_asset_path=tsub["map_asset_path"],
                           observed_anchor_location=[100.9, 200.9, 300.9],
                           observed_anchor_object_path=None)},
        "subject_binding", C.SCENE_SURVEY_SUBJECT_MISMATCH,
        "anchor drift of ~1.56cm Euclidean — under 1cm on every single axis, and "
        "still outside the L2 tolerance. The per-axis reading of this rail is the "
        "trap this fixture exists to catch",
        "sb::transform_within_tolerance")

    asub = _subject(anchor_mode="actor_object_path", anchor_location=None,
                    anchor_object_path="/Game/M.M:PersistentLevel.Wanted_0")
    add("binding_substituted_anchor_actor",
        {"subject": asub,
         "report": _report(subject_id=asub["subject_id"],
                           map_asset_path=asub["map_asset_path"],
                           observed_anchor_location=[0.0, 0.0, 0.0],
                           observed_anchor_object_path=
                           "/Game/M.M:PersistentLevel.Convenient_0")},
        "subject_binding", C.SCENE_SURVEY_SUBJECT_MISMATCH,
        "WorldForge surveyed a different actor than the one named and reported "
        "success", "sb::object_path_match")

    add("binding_resolver_inverted",
        {"subject": good_sub, "report": _report(subject_resolved_by="worldforge")},
        "subject_binding", C.SCENE_SURVEY_SUBJECT_INFERRED,
        "the report admits WorldForge resolved the subject",
        "sb::resolver_not_worldforge")

    # ---- report contract ---------------------------------------------------- #
    add("report_dry_probe_claims_runtime",
        _report(runtime_mode="live_survey_runtime", runtime_executed=False,
                evidence_paths=[]),
        "report_contract", C.SCENE_SURVEY_RUNTIME_SIMULATED_OVERCLAIM,
        "a report that never executed claiming live runtime truth",
        "sr::live_mode_executed")

    add("report_clean_without_evidence",
        _report(status="pass", failure_codes=[], evidence_paths=[]),
        "report_contract", C.SCENE_SURVEY_EVIDENCE_MISSING,
        "a clean pass with no evidence behind it", "sr::clean_requires_evidence")

    add("report_zero_support_samples_passed",
        _report(status="pass", failure_codes=[], support_samples_total=0,
                support_samples_valid=0),
        "report_contract", C.SCENE_SURVEY_EVIDENCE_MISSING,
        "a pass built on zero probed support samples",
        "sr::clean_requires_evidence")

    add("report_valid_exceeds_total",
        _report(support_samples_valid=99999),
        "report_contract", C.SCENE_SURVEY_REPORT_INVALID,
        "more valid samples than were ever taken", "sr::valid_le_total")

    add("report_unknown_failure_code",
        _report(failure_codes=["WF9999_NOT_A_REAL_CODE"], status="blocked"),
        "report_contract", C.SCENE_SURVEY_UNKNOWN_FAILURE_CODE,
        "a failure code invented to look rigorous", "sr::failure_codes_known")

    add("report_executed_without_observed_anchor",
        _report(runtime_executed=True, observed_anchor_location=None,
                observed_anchor_object_path=None),
        "report_contract", C.SCENE_SURVEY_SUBJECT_UNRESOLVED,
        "an executed run that cannot say where it actually looked",
        "sr::observed_anchor_present")

    add("report_resolver_inverted", _report(subject_resolved_by="worldforge"),
        "report_contract", C.SCENE_SURVEY_SUBJECT_INFERRED,
        "a report asserting WorldForge chose the subject",
        "sr::subject_resolved_by_caller")

    # The pre-Wave-1 scratch report shape, verbatim in structure: no subject_id,
    # no observed anchor, no resolver. This is the artifact sitting untracked in
    # the runtime report directory, and it must never be mistaken for acceptance.
    stale = _report()
    for k in ("subject_id", "observed_anchor_location",
              "observed_anchor_object_path", "subject_resolved_by"):
        stale.pop(k, None)
    add("report_pre_wave1_scratch_shape", stale, "report_contract",
        C.SCENE_SURVEY_REPORT_INVALID,
        "the pre-Wave-1 report shape, which predates subject binding entirely and "
        "would silently satisfy a gate that only asked whether a report exists")

    return out


# --------------------------------------------------------------------------- #
# Drivers — each one is the REAL validator the shield calls, not a stand-in.
# --------------------------------------------------------------------------- #
def _drive_subject(art):
    return SS.validate_scene_survey_subject(art, strict=True)


def _drive_report(art):
    return SS.validate_scene_survey_report(art, strict=True)


def _drive_binding(art):
    return SS.validate_subject_binding(art["subject"], art["report"], strict=True)


DRIVERS = {
    "subject_contract": _drive_subject,
    "report_contract": _drive_report,
    "subject_binding": _drive_binding,
}


def _positive_controls(rep):
    """Every driver must still ACCEPT the honest artifact."""
    good_sub = _subject()
    good_rep = _report()
    controls = [
        ("subject_contract", good_sub),
        ("report_contract", good_rep),
        ("subject_binding", {"subject": good_sub, "report": good_rep}),
    ]
    for driver, art in controls:
        fails = [c for c in DRIVERS[driver](art) if not c[1]]
        rep.check(
            "positive::{}".format(driver), not fails,
            "the honest artifact must still pass {} — without this rail, a driver "
            "that rejected everything would satisfy this whole suite (failed: {})"
            .format(driver, [c[0] for c in fails]),
            code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)


def _write_fixtures(fixtures):
    KB_DIR.mkdir(parents=True, exist_ok=True)
    catalogue = {}
    for slug, (artifact, entry) in sorted(fixtures.items()):
        path = KB_DIR / (slug + ".json")
        text = json.dumps(artifact, indent=2, sort_keys=True,
                          ensure_ascii=False) + "\n"
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        catalogue[slug] = entry
    doc = {
        "milestone": "v2.6",
        "contract_version": SS.CONTRACT_VERSION,
        "note": ("Fixtures carry no harness metadata on purpose: an embedded "
                 "_expected_code key would itself be rejected by the strict "
                 "unknown-key rail, which looks green and proves nothing."),
        "not_yet_testable": NOT_YET_TESTABLE,
        "fixtures": catalogue,
    }
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with CATALOGUE.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 scene-survey hostile fixtures")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    args, _unknown = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    fixtures = _fixtures()
    _write_fixtures(fixtures)

    rep = ValidationReport("pack", args.pack, strict=strict)

    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    entries = catalogue["fixtures"]

    rep.check("kb::catalogue_nonempty", len(entries) >= MIN_FIXTURES,
              "the hostile catalogue must carry at least {} fixtures (got {})"
              .format(MIN_FIXTURES, len(entries)),
              code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

    for slug in sorted(entries):
        entry = entries[slug]
        path = KB_DIR / entry["fixture"]
        # Read the BYTES back — the thing under test is the artifact on disk.
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            rep.check("kb::{}::loadable".format(slug), False,
                      "fixture did not load: {}".format(exc),
                      code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)
            continue

        driver = DRIVERS[entry["driver"]]
        # Crash guard: a validator that explodes on hostile input has not judged it.
        try:
            checks = driver(artifact)
            crashed = None
        except Exception as exc:
            checks, crashed = [], "{}: {}".format(type(exc).__name__, exc)

        rep.check("kb::{}::rejected_not_crashed".format(slug), crashed is None,
                  "the validator must JUDGE hostile input, not raise on it ({})"
                  .format(crashed),
                  code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)
        if crashed:
            continue

        fails = [c for c in checks if not c[1]]
        names = {c[0] for c in fails}
        codes = {c[3] for c in fails}

        rep.check("kb::{}::rejected".format(slug), len(fails) > 0,
                  "{} — must be rejected".format(entry["vector"]),
                  code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

        rep.check("kb::{}::owning_code".format(slug),
                  entry["expected_code"] in codes,
                  "must be rejected for {} — rejection for another reason proves "
                  "nothing about this vector (got {})".format(
                      entry["expected_code"], sorted(codes)),
                  code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

        if entry.get("expected_check"):
            want = entry["expected_check"]
            hit = any(want == n or n.endswith("::" + want) or want in n
                      for n in names)
            rep.check("kb::{}::owning_check".format(slug), hit,
                      "must be rejected BY {} — rejection by any other rail is "
                      "collateral, not proof of this vector (failed rails: {})"
                      .format(want, sorted(names)),
                      code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

    _positive_controls(rep)

    # Declared coverage gaps must stay declared, not quietly shrink to nothing.
    rep.check("kb::gaps_declared", len(NOT_YET_TESTABLE) > 0,
              "vectors that cannot be tested at this commit are named in "
              "NOT_YET_TESTABLE ({} declared) rather than silently omitted"
              .format(len(NOT_YET_TESTABLE)),
              code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="run-v2-6-known-bads", pack=args.pack, strict=strict,
        report_type="wf.scene_survey.hostile_fixtures.v1",
        status=rep.status, records_total=len(entries)))
    rep.write(REPORT_DIR, "v2_6_known_bads_report.json")
    rep.print_summary("v2-6-known-bads")
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
