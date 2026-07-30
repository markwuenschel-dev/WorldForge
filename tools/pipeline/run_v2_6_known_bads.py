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
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import scene_survey_contracts as SS  # noqa: E402
import scene_survey_evidence as EV  # noqa: E402
import scene_survey_operation as OP  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402

KB_DIR = REPO_ROOT / "procedural" / "known_bads" / "v2_6"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "scene_survey" / "hostile"
CATALOGUE = KB_DIR / "index.json"

MUTATIONS_SCRIPT = REPO_ROOT / "tools" / "pipeline" / "acceptance_recompute_mutations.py"
MUTATIONS_VERDICT = REPORT_DIR / "acceptance_mutations.json"
MUTATION_TERMS = ("M", "W", "P", "T", "B", "E")

MIN_FIXTURES = 27


# --------------------------------------------------------------------------- #
# Vectors that this commit genuinely cannot test, and why. Declared so the
# coverage claim stays honest.
# --------------------------------------------------------------------------- #
NOT_YET_TESTABLE = {
    "subject_binding_hash_mismatch":
        "subject_binding_hash does not exist anywhere in this build: no writer, no "
        "reader, no compute helper, and no slot in REPORT_ALLOWED "
        "(scene_survey_contracts.py:662-680), so strict check_no_unknown would "
        "reject it outright if a fixture invented one. The subject IS covered "
        "transitively — 'subject' is in REQUEST_HASH_INCLUDED "
        "(scene_survey_operation.py:586) — but that is the request hash, not a "
        "subject-binding hash, and a fixture that renamed one to the other would "
        "be testing a field this build has never had",
    "nondeterministic_repeated_reports":
        "requires two real editor runs; determinism is enforced at runtime from "
        "per_run_hashes, which no static fixture can produce honestly",
    "screenshot_without_runtime_evidence":
        "no screenshot artifact is produced at all under the current -nullrhi "
        "pass, so the vector has no on-disk form yet",
}

# --------------------------------------------------------------------------- #
# Vectors that ARE now covered, but only in part. Declaring the covered half
# without the uncovered one is how a suite drifts into overclaiming: the fixture
# below each of these is real and is killed by a real rail, and the string says
# exactly which half of the vector that rail does NOT reach. `kb::residual_gaps_
# declared` requires every catalogue entry carrying `residual_gap` to name one.
# --------------------------------------------------------------------------- #
RESIDUAL_GAPS = {
    "operation_wrong_target_repository":
        "target_repository is a caller ASSERTION that nothing resolves. The rail "
        "below refuses evidence sealed against a different asserted repository "
        "(it is in REQUEST_HASH_INCLUDED, scene_survey_operation.py:591), but no "
        "scene-survey code observes which tree was actually surveyed — "
        "scene_survey_far_side.py never resolves a repository at all. The live "
        "bridge's field comparison (tools/bridge/live.py:141-145, WF1024) has no "
        "scene-survey counterpart",
    "operation_wrong_target_commit":
        "same shape as the repository case: target_commit is hashed "
        "(scene_survey_operation.py:587) so evidence sealed against a different "
        "commit is refused, but nothing verifies the far side actually ran at "
        "that commit. Only the live-bridge path shape-checks 40-hex "
        "(tools/bridge/live.py:146-150)",
    "operation_replayed_from_another_request":
        "caught on the OPERATION-IDENTITY axis, not from the report body. The "
        "runtime report's operation block does carry request_hash "
        "(run_scene_survey_probe.py:1405-1408) but no validator reads it, so a "
        "copy presented WITHOUT its manifest is still undetectable from the "
        "report alone",
}


# --------------------------------------------------------------------------- #
# Fixture construction. Deterministic; materialized then read back from disk so
# the thing under test is the bytes, not an in-memory object.
# --------------------------------------------------------------------------- #
def _subject(**over):
    return SS._example_scene_survey_subject(**over)


def _report(**over):
    return SS._example_scene_survey_report(**over)


# --------------------------------------------------------------------------- #
# Operation-identity fixtures. These bind a sealed manifest to a request, which
# is the axis `verify_operation_evidence` judges — and the axis the runtime gate
# actually calls (validate_scene_survey_runtime.py:189-196).
# --------------------------------------------------------------------------- #
DERIVED_REPORT_STUB = REPORT_DIR / "operation_derived_report_stub.json"


def _stub_derived_report():
    """A real file for the manifest to bind, because a manifest must bind one.

    `build_operation_manifest` refuses a manifest with no derived report
    (scene_survey_operation.py:1155-1157) and digests whatever it is given. The
    fixtures below are regenerated on every run, so this file and the digests
    sealed over it are rewritten together and cannot drift apart.
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_report(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with DERIVED_REPORT_STUB.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    rel = OP.relative_posix(REPO_ROOT, DERIVED_REPORT_STUB)
    if not rel.ok:
        raise RuntimeError("stub report is not repo-relative: [{}] {}".format(
            rel.code, rel.detail))
    return rel.value


def _sealed_manifest(**request_over):
    """A manifest sealed by the REAL builder over a request, then serialized.

    Built, never hand-written: a hand-written manifest would carry a
    hand-written `manifest_digest`, and `verify_operation_evidence` recomputes
    that seal first (scene_survey_operation.py:1352-1354). Every fixture below
    would then be refused for a broken seal — a rejection that looks green and
    says nothing about the vector under test.
    """
    req = OP._fake_request(**request_over)
    res = OP.build_operation_manifest(REPO_ROOT, req,
                                      derived_report=_stub_derived_report(),
                                      created_at_utc="2026-07-30T00:00:00Z")
    if not res.ok:
        raise RuntimeError("could not seal fixture manifest: [{}] {}".format(
            res.code, res.detail))
    return res.value


# --------------------------------------------------------------------------- #
# Cleanup-ledger fixtures. `_SpawnLedger` (tools/bridge/scene_survey_far_side.py:
# 1355) now files a per-object ledger into the raw bundle, and
# `scene_survey_evidence.derive_cleanup_verified` (:1751) ANDs its conjunct onto
# the three snapshot terms. Both halves are reachable from a static bundle.
# --------------------------------------------------------------------------- #
CLEAN_OP = "op_v2_6_scene_survey_0001"
CLEAN_MAP = "/Game/Fixture/Lvl_Fixture"


def _snapshot(stage, **over):
    s = {"stage": stage, "collection_ok": True,
         "actor_paths": [CLEAN_MAP + ".Lvl_Fixture:PersistentLevel.Floor_0"],
         "dirty_packages": [], "operation_owned_actor_paths": [],
         "map_identity": CLEAN_MAP, "package_identity": CLEAN_MAP}
    s.update(over)
    return s


def _placement(oid, **over):
    """One temporary object handled cleanly: created, destroyed, witnessed gone."""
    p = {"record_id": "temporary_placement#" + oid,
         "record_type": "temporary_placement", "record_ident": oid,
         "operation_id": CLEAN_OP, "object_id": oid,
         "ownership_tag": "worldforge.scene_survey/" + CLEAN_OP,
         "creation_observed": True, "creation_stage": "observe",
         "destruction_attempted": True,
         "destruction_result": EV.DESTRUCTION_DESTROYED,
         "post_cleanup_presence": EV.PRESENCE_ABSENT,
         "absent_after_cleanup": True, "collection_ok": True}
    p.update(over)
    return p


def _cleanup_bundle(placements=None, pre=None, post=None, **ledger_over):
    """A raw bundle whose ledger SUMMARISES its own placements.

    The aggregates are computed from the placements given, exactly as
    `_SpawnLedger.write_manifest` computes them from the records it filed. A
    fixture that hand-wrote them would be a manifest no producer can emit, and
    `_ledger_contradictions` (scene_survey_evidence.py:747-818) rejects those on
    sight — which is a rejection for lying about the producer, not for the
    vector under test.
    """
    placements = placements or {}
    ids = sorted(placements)
    ledger = {"record_id": EV.LEDGER_REF, "record_type": EV.LEDGER_KIND,
              "record_ident": EV.LEDGER_IDENT, "operation_id": CLEAN_OP,
              "is_temporary_object_ledger": True, "collection_ok": True,
              "ownership_tag": "worldforge.scene_survey/" + CLEAN_OP,
              "cleanup_ran": True,
              "object_ids": ids, "object_count": len(ids),
              "created_object_ids": ids, "created_object_count": len(ids),
              "spawn_call_sites_in_module": 1, "spawn_call_sites_in_ledger": 1,
              "unledgered_spawn_call_sites": 0,
              "persistent_package_hash": None,
              "persistent_package_hash_supported": False}
    ledger.update(ledger_over)
    return {"inventory": {"pre": pre or _snapshot("anchor_bind"),
                          "post": post or _snapshot("cleanup")},
            "document": {EV.LEDGER_IDENT: ledger},
            "temporary_placement": placements}


def _fixtures():
    """slug -> (artifact, catalogue_entry)."""
    good_sub = _subject()
    out = {}

    def add(slug, artifact, driver, code, vector, check=None, residual=None):
        entry = {"driver": driver, "expected_code": code, "vector": vector,
                 "fixture": slug + ".json"}
        if check:
            entry["expected_check"] = check
        if residual:
            entry["residual_gap"] = residual
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

    # ---- operation identity: was this evidence made FOR this request? ------- #
    # Sealed manifest vs. the request it is presented against. `operation_id` is
    # deliberately EXCLUDED from request_hash (scene_survey_operation.py:593-597)
    # so "a prior artifact re-presented" and "a different question" are separable
    # failures — which is why the two fixtures below owe different rails despite
    # sharing a failure code.
    add("operation_request_hash_mismatch",
        {"manifest": _sealed_manifest(target_map="/Game/Fixture/Lvl_Fixture"),
         "request": OP._fake_request(target_map="/Game/Fixture/Lvl_Somewhere_Else")},
        "operation_identity", C.SCENE_SURVEY_OPERATION_ID_MISMATCH,
        "evidence sealed against one question, presented against another — same "
        "operation id, different map. The manifest's own seal is intact; only the "
        "binding to THIS request is false",
        "oi::request_hash_mismatch")

    add("operation_replayed_from_another_request",
        {"manifest": _sealed_manifest(operation_id="op_v2_6_scene_survey_PRIOR"),
         "request": OP._fake_request(operation_id="op_v2_6_scene_survey_0001")},
        "operation_identity", C.SCENE_SURVEY_OPERATION_ID_MISMATCH,
        "a prior operation's report and manifest re-presented for a NEW asking. "
        "The question is byte-identical, so request_hash matches perfectly — only "
        "the operation id betrays the replay, which is precisely why it is "
        "excluded from the hash",
        "oi::operation_id_mismatch",
        RESIDUAL_GAPS["operation_replayed_from_another_request"])

    add("operation_wrong_target_repository",
        {"manifest": _sealed_manifest(target_repository="FixtureCaller"),
         "request": OP._fake_request(target_repository="FixtureCaller_Fork")},
        "operation_identity", C.SCENE_SURVEY_OPERATION_ID_MISMATCH,
        "a survey of one repository handed back against a request naming another",
        "oi::request_hash_mismatch",
        RESIDUAL_GAPS["operation_wrong_target_repository"])

    add("operation_wrong_target_commit",
        {"manifest": _sealed_manifest(target_commit="0f" * 20),
         "request": OP._fake_request(target_commit="1a" * 20)},
        "operation_identity", C.SCENE_SURVEY_OPERATION_ID_MISMATCH,
        "a survey of one commit handed back against a request naming another",
        "oi::request_hash_mismatch",
        RESIDUAL_GAPS["operation_wrong_target_commit"])

    # ---- cleanup ledger: did the survey put the level back? ----------------- #
    # Both fixtures keep sufficiency SATISFIED. A bundle the evidence module
    # cannot read answers "unknown", and an unknown is not a caught leak — it
    # would reject for insufficiency and prove nothing. These are measured.
    add("cleanup_temporary_marker_left_behind",
        _cleanup_bundle({"wf_temp_marker_0": _placement(
            "wf_temp_marker_0", post_cleanup_presence=EV.PRESENCE_PRESENT,
            absent_after_cleanup=False)}),
        "cleanup_evidence", C.SCENE_SURVEY_CLEANUP_UNVERIFIED,
        "a temporary object the survey spawned, reported destroyed, and then "
        "OBSERVED still present after cleanup. Both inventory snapshots agree — "
        "the object was created and removed between them as far as any set "
        "comparison can tell — so only the per-object ledger can see it",
        "ce::no_objects_present_after_cleanup")

    add("cleanup_package_dirty_after_cleanup",
        _cleanup_bundle({"wf_temp_marker_0": _placement("wf_temp_marker_0")},
                        post=_snapshot("cleanup", dirty_packages=[CLEAN_MAP])),
        "cleanup_evidence", C.SCENE_SURVEY_CLEANUP_UNVERIFIED,
        "every temporary object was destroyed and witnessed gone, and the survey "
        "STILL left the map package dirty. The ledger conjunct is satisfied here, "
        "so a rejection proves the snapshot term is doing its own work",
        "ce::packages_not_dirtied")

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


def _drive_operation_identity(art):
    """The real `verify_operation_evidence` the runtime gate calls.

    `check_files=False`: the on-disk digests of raw evidence and the derived
    report are a DIFFERENT vector (WF1113 / WF1100, scene_survey_operation.py:
    1384-1399) and they short-circuit before some identity failures. Leaving them
    on would let a fixture be refused for a missing file and score as a caught
    replay. The runtime gate runs with check_files=True over real artifacts
    (validate_scene_survey_runtime.py:189-196); this suite isolates the identity
    axis on purpose.

    The result is a single OpResult, so its `reason` becomes the check name —
    that is what lets `expected_check` pin the specific rail rather than settling
    for "something refused it".
    """
    res = OP.verify_operation_evidence(REPO_ROOT, art["manifest"], art["request"],
                                       check_files=False)
    if res.ok:
        return [("oi::bound", True, res.detail, None)]
    return [("oi::{}".format(res.reason or "refused"), False, res.detail, res.code)]


def _drive_cleanup_evidence(raw):
    """The real cleanup derivation, decomposed into the rails it is built from.

    SUFFICIENCY FIRST, and reported separately. `derive_cleanup_verified` answers
    False both for "measured a leak" and for "could not tell", and a suite that
    conflated them would score an unreadable fixture as a caught leak. A bundle
    that is merely insufficient fails `ce::sufficient` and owns a different code,
    so it can never masquerade as a cleanup rejection.
    """
    enough, why = EV.sufficiency_cleanup(raw)
    if not enough:
        return [("ce::sufficient", False,
                 "the bundle cannot answer the cleanup question at all ({}) — an "
                 "unanswerable bundle is not a caught leak".format(why),
                 C.SCENE_SURVEY_EVIDENCE_INSUFFICIENT)]

    verdict, inp = EV.derive_cleanup_verified(raw)
    CU = C.SCENE_SURVEY_CLEANUP_UNVERIFIED
    return [
        ("ce::sufficient", True, why, None),
        ("ce::cleanup_verified", bool(verdict),
         "the survey must be able to show it put the level back", CU),
        ("ce::no_objects_present_after_cleanup",
         not inp.get("ledger_objects_present_after_cleanup"),
         "objects observed still present after cleanup: {}".format(
             inp.get("ledger_objects_present_after_cleanup")), CU),
        ("ce::no_objects_undestroyed", not inp.get("ledger_objects_not_destroyed"),
         "objects the ledger never saw destroyed: {}".format(
             inp.get("ledger_objects_not_destroyed")), CU),
        ("ce::no_unledgered_placements", not inp.get("ledger_unledgered_placements"),
         "placements filed with no ledger entry: {}".format(
             inp.get("ledger_unledgered_placements")), CU),
        ("ce::packages_not_dirtied", bool(inp.get("dirty_packages_equal")),
         "the dirty-package set must be identical before and after — newly dirty "
         "{}, no longer dirty {} (a package that STOPS being dirty was written to "
         "disk, which is a mutation too)".format(
             inp.get("newly_dirty_packages"), inp.get("no_longer_dirty_packages")),
         CU),
        ("ce::no_leaked_actors", not inp.get("leaked_actors"),
         "actors present after that were absent before: {}".format(
             inp.get("leaked_actors")), CU),
    ]


DRIVERS = {
    "subject_contract": _drive_subject,
    "report_contract": _drive_report,
    "subject_binding": _drive_binding,
    "operation_identity": _drive_operation_identity,
    "cleanup_evidence": _drive_cleanup_evidence,
}


def _positive_controls(rep):
    """Every driver must still ACCEPT the honest artifact."""
    good_sub = _subject()
    good_rep = _report()
    honest_req = OP._fake_request()
    controls = [
        ("subject_contract", good_sub),
        ("report_contract", good_rep),
        ("subject_binding", {"subject": good_sub, "report": good_rep}),
        # Evidence sealed for THIS request must still be accepted, or the four
        # identity fixtures above would be satisfied by a rail that refuses
        # everything.
        ("operation_identity", {"manifest": _sealed_manifest(), "request": honest_req}),
        # A survey that spawned one temporary object, destroyed it, witnessed it
        # gone and dirtied nothing must read CLEAN. Without this, "cleanup_verified
        # is never True" would satisfy both cleanup fixtures.
        ("cleanup_evidence",
         _cleanup_bundle({"wf_temp_marker_0": _placement("wf_temp_marker_0")})),
    ]
    for driver, art in controls:
        fails = [c for c in DRIVERS[driver](art) if not c[1]]
        rep.check(
            "positive::{}".format(driver), not fails,
            "the honest artifact must still pass {} — without this rail, a driver "
            "that rejected everything would satisfy this whole suite (failed: {})"
            .format(driver, [c[0] for c in fails]),
            code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)


# --------------------------------------------------------------------------- #
# Mutation evidence for the acceptance rails.
#
# Every fixture above proves a rail REJECTS something. None of them prove a rail
# would have ACCEPTED it had the implementation been wrong — a rail that is
# hard-wired to fail passes the whole suite above. `acceptance_recompute_mutations`
# closes that hole by re-introducing each defect in this repository's own code and
# requiring the corresponding RED to disappear. It ran as an orphan until this
# gate called it: nothing in the shield, the makefile, or any test referenced it.
#
# SUBPROCESS, deliberately. The harness monkeypatches `scene_survey_recompute`
# module attributes. In-process, a harness that died between patch and restore
# would leave a stubbed derivation installed under the fixture drivers above, and
# they would go green on it. A separate interpreter cannot leak that.
# --------------------------------------------------------------------------- #
def _mutation_evidence(rep, strict, pack):
    if not MUTATIONS_SCRIPT.is_file():
        rep.check("kb::mutations::present", False,
                  "the acceptance mutation harness is missing: {}"
                  .format(MUTATIONS_SCRIPT),
                  code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)
        return

    MUTATIONS_VERDICT.parent.mkdir(parents=True, exist_ok=True)
    if MUTATIONS_VERDICT.exists():
        # Never grade a stale verdict from a previous run as if it were this one.
        MUTATIONS_VERDICT.unlink()

    argv = [sys.executable, str(MUTATIONS_SCRIPT), "--pack", pack,
            "--json", str(MUTATIONS_VERDICT)]
    if strict:
        argv.append("--strict")
    proc = subprocess.run(argv, cwd=str(REPO_ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")

    # Exit 2 is "the harness never got to ask", which is NOT the same finding as
    # exit 1 "a rail did not carry its weight". Reporting them identically would
    # let a broken import read as a tested rail.
    rep.check("kb::mutations::harness_ran", proc.returncode != 2,
              "the mutation harness must complete, not abort ({})"
              .format((proc.stderr or "").strip()[-400:] or "no stderr"),
              code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

    rep.check("kb::mutations::exit_zero", proc.returncode == 0,
              "acceptance_recompute_mutations must exit 0 — every acceptance term's "
              "input mutation RED, and that RED killed by the implementation "
              "mutation (rc={})".format(proc.returncode),
              code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

    try:
        verdict = json.loads(MUTATIONS_VERDICT.read_text(encoding="utf-8"))
    except Exception as exc:
        rep.check("kb::mutations::verdict_readable", False,
                  "the structured verdict did not load: {}. An exit code alone "
                  "cannot distinguish six killed mutants from an emptied TERMS "
                  "tuple, so this gate refuses to grade on rc only".format(exc),
                  code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)
        return

    terms = verdict.get("terms") or {}
    missing = [t for t in MUTATION_TERMS if t not in terms]
    rep.check("kb::mutations::all_terms_exercised", not missing,
              "every acceptance term {} must be exercised — a term silently "
              "dropped from the harness reports PASS for a rail nobody questioned "
              "(missing: {})".format(list(MUTATION_TERMS), missing),
              code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

    for term in MUTATION_TERMS:
        rec = terms.get(term)
        if not isinstance(rec, dict):
            continue
        rep.check("kb::mutations::{}::input_red".format(term),
                  rec.get("input_mutation_red") is True,
                  "term {} ({}): the input mutation must RED {} — a rail that "
                  "stays green on a broken atom is not checking that atom"
                  .format(term, rec.get("derivation"), rec.get("expected_rails")),
                  code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)
        rep.check("kb::mutations::{}::mutant_killed".format(term),
                  rec.get("mutant_killed") is True,
                  "term {}: stubbing {} to always-True must STOP that RED — "
                  "otherwise the RED came from a bystander rail and proves nothing "
                  "about {} (survived: {})".format(
                      term, rec.get("derivation"), term, rec.get("survived_rails")),
                  code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)
        rep.check("kb::mutations::{}::restored".format(term),
                  rec.get("derivation_restored") is True,
                  "term {}: the implementation mutation on {} must be reverted"
                  .format(term, rec.get("derivation")),
                  code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

    for name, why in (
            ("clean_control_green",
             "the unmutated fixture must pass, or every RED above is unattributable"),
            ("restoration_green",
             "the fixture must still pass after all mutations — a leaked stub "
             "would silently weaken every later run in this process"),
            ("cross_check_double_catch",
             "an incoherent world record must be caught by BOTH the acceptance and "
             "the evidence rail"),
            ("symmetry_under_claim_red",
             "a report UNDER-claiming against its own evidence must also be refused"),
            ("anti_circularity_independent",
             "the recompute rail must reject a wrong-world survey that the shared "
             "predicate accepts — if they agree, the rail is reading its own claim"),
    ):
        rep.check("kb::mutations::control::{}".format(name),
                  (verdict.get("controls") or {}).get(name) is True, why,
                  code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

    if not verdict.get("ok"):
        for line in (verdict.get("failures") or [])[:20]:
            rep.check("kb::mutations::detail", False, line,
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
        "residual_gaps": RESIDUAL_GAPS,
        "fixtures": catalogue,
    }
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with CATALOGUE.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 scene-survey hostile fixtures")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    # Mutation evidence runs by default under strict — which is how the shield
    # already invokes this gate (v2_6_shield.py:81 passes `--pack X --strict`), so
    # the harness stops being an orphan without any shield edit. `--mutations`
    # forces it on outside strict; `--no-mutations` is an explicit, visible opt-out
    # rather than a silent default.
    ap.add_argument("--mutations", dest="mutations", action="store_true",
                    default=None)
    ap.add_argument("--no-mutations", dest="mutations", action="store_false")
    args, _unknown = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    do_mutations = strict if args.mutations is None else args.mutations

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

    # Every check above proves a rail REJECTS a bad artifact. None of them prove
    # the rail would have ACCEPTED it had the implementation been wrong.
    if do_mutations:
        _mutation_evidence(rep, strict, args.pack)

    # Declared coverage gaps must stay declared, not quietly shrink to nothing.
    rep.check("kb::gaps_declared", len(NOT_YET_TESTABLE) > 0,
              "vectors that cannot be tested at this commit are named in "
              "NOT_YET_TESTABLE ({} declared) rather than silently omitted"
              .format(len(NOT_YET_TESTABLE)),
              code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

    # A vector may not be BOTH declared untestable and covered by a fixture: that
    # combination is how a catalogue ends up contradicting itself, with the prose
    # disclaiming what the suite is quietly proving.
    contradictions = sorted(set(NOT_YET_TESTABLE) & set(entries))
    rep.check("kb::gaps_not_contradicted", not contradictions,
              "a vector cannot be listed in NOT_YET_TESTABLE and also carry a "
              "fixture — remove it from the gap list when it becomes testable "
              "(both: {})".format(contradictions),
              code=C.SCENE_SURVEY_NEGATIVE_ACCEPTED)

    # Partial coverage must SAY it is partial. Without this, a fixture proving the
    # narrow half of a vector reads in the catalogue exactly like one proving all
    # of it.
    undeclared = sorted(s for s in RESIDUAL_GAPS
                        if not (entries.get(s) or {}).get("residual_gap"))
    rep.check("kb::residual_gaps_declared", not undeclared,
              "every partially-covered vector must carry its residual_gap in the "
              "catalogue, naming the half its fixture does NOT reach (missing: {})"
              .format(undeclared),
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
