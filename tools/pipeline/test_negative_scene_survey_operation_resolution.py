#!/usr/bin/env python3
"""test_negative_scene_survey_operation_resolution.py — the RED must say WHICH red.

WHAT THIS EXISTS FOR. ``v2_6_shield.py`` invoked the runtime gate without
``--operation-id``, so the gate went RED on a MISSING ARGUMENT while wearing the
same colour as the RED it is legitimately holding — no live runtime evidence has
been produced yet. A wiring defect that hides behind an expected RED is a wiring
defect nobody ever fixes, because the gate was "supposed to be red anyway".

So ``validate_scene_survey_runtime.resolve_operation_id`` now walks a CLOSED,
named set of sources and lands in exactly one terminal state, and each state has
its own check name and its own failure code:

    input::operation_id_resolved     WF1128  wiring defect (no source produced one)
    input::operation_id_unambiguous  WF1129  ambiguity (more than one candidate)
    input::caller_evidence_present   WF1097  ABSENT CALLER EVIDENCE — intentional

This harness asserts the three are genuinely TELLABLE APART (each fires alone,
over one synthetic tree), that a pack declaring exactly one bound operation
resolves it, and — the load-bearing negative — that "scan the operations
directory and take the newest" is not merely unimplemented but UNREACHABLE.

Every assertion drives the SHIPPED functions. Nothing here re-evaluates a literal
it just built.

``test_negative_validators.py`` auto-discovers every sibling ``test_negative_*.py``
and requires each to exit 0, so this harness rides that gate. Run directly:

    PYTHONUTF8=1 python tools/pipeline/test_negative_scene_survey_operation_resolution.py
"""

import json
import os
import pathlib
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import scene_survey_contracts as SS                      # noqa: E402
import scene_survey_operation as OP                      # noqa: E402
import validate_scene_survey_runtime as V                # noqa: E402
from failure_codes import FailureCode as C               # noqa: E402
from validation_report import ValidationReport           # noqa: E402

WIRING_RAIL = "input::operation_id_resolved"
AMBIGUITY_RAIL = "input::operation_id_unambiguous"
ABSENT_RAIL = "input::caller_evidence_present"
RESOLUTION_RAILS = (WIRING_RAIL, AMBIGUITY_RAIL, ABSENT_RAIL)

EXPECTED_CODE = {
    WIRING_RAIL: C.SCENE_SURVEY_OPERATION_ID_MISMATCH,
    AMBIGUITY_RAIL: C.SCENE_SURVEY_CONCURRENT_OPERATION,
    ABSENT_RAIL: C.SCENE_SURVEY_EVIDENCE_MISSING,
}


# --------------------------------------------------------------------------- #
# harness
# --------------------------------------------------------------------------- #
class _Suite(object):
    def __init__(self):
        self.failures = []
        self.count = 0

    def check(self, name, ok, detail=""):
        self.count += 1
        if not ok:
            self.failures.append("{}: {}".format(name, detail))
        return bool(ok)

    def report(self, tag):
        if self.failures:
            print("{} FAILED ({} of {} case(s)):".format(
                tag, len(self.failures), self.count))
            for line in self.failures:
                print("  - {}".format(line))
            return 1
        print("{}: PASS ({} case(s))".format(tag, self.count))
        return 0


def _select(args, repo_root):
    """Drive the SHIPPED ``_select_input`` and return (blocking, all_checks)."""
    rep = ValidationReport("suite", "operation_resolution", strict=True)
    V._select_input(rep, args, repo_root=repo_root)
    blocking = {n for n, c in rep.checks.items() if c.get("blocking")}
    return blocking, rep.checks


def _only(blocking, expected):
    """Exactly one resolution rail fired, and it is ``expected``."""
    fired = {r for r in RESOLUTION_RAILS if r in blocking}
    return fired == {expected}


# --------------------------------------------------------------------------- #
# a synthetic tree carrying TWO fully-published operations
# --------------------------------------------------------------------------- #
def _publish(root, operation_id):
    """Write a manifest + operation-scoped report for ``operation_id``."""
    rres = OP.report_path_for(root, operation_id)
    rres.value["absolute"].parent.mkdir(parents=True, exist_ok=True)
    rres.value["absolute"].write_text(
        json.dumps({"status": "ok", "survey": {"operation_id": operation_id}}),
        encoding="utf-8")
    subject = SS._example_scene_survey_subject()
    request = {
        "operation_id": operation_id, "output_location": "procedural/reports/x",
        "timeout_seconds": 900, "requested_operation": "scene_survey",
        "subject": subject, "target_map": subject["map_asset_path"],
        "target_project": "T.uproject",
        "target_repository": "t", "target_commit": "c", "target_engine": "5.8",
        "source_repository": "wf", "source_commit": "s",
        "required_plugin": "WorldForge", "required_plugin_version": "1",
        "required_plugin_source_hash": "sha256:deadbeef",
    }
    built = OP.build_operation_manifest(
        root, request, derived_report=rres.value["relative_posix"])
    if not built.ok:
        raise AssertionError("fixture manifest could not be built: {}".format(
            built.detail))
    published = OP.publish_operation_manifest(root, built.value)
    if not published.ok:
        raise AssertionError("fixture manifest could not be published: {}".format(
            published.detail))
    return rres.value["absolute"]


# --------------------------------------------------------------------------- #
# the no-directory-scan proof
# --------------------------------------------------------------------------- #
class _NoDirectoryEnumeration(object):
    """Make every directory-enumeration primitive raise, for the duration.

    This is the difference between "I grepped and found no glob call" and "the
    resolver demonstrably cannot have listed a directory": if ANY code path
    reached for one, resolution raises instead of returning, and the case fails.
    """

    PRIMITIVES = (
        (pathlib.Path, "iterdir"), (pathlib.Path, "glob"), (pathlib.Path, "rglob"),
        (os, "listdir"), (os, "scandir"), (os, "walk"),
    )

    def __init__(self):
        self._saved = []

    def __enter__(self):
        def _boom(*_a, **_kw):
            raise AssertionError(
                "resolve_operation_id enumerated a directory — 'take the newest "
                "operation on disk' must be unreachable")
        for owner, name in self.PRIMITIVES:
            self._saved.append((owner, name, getattr(owner, name)))
            setattr(owner, name, _boom)
        return self

    def __exit__(self, *_exc):
        for owner, name, original in self._saved:
            setattr(owner, name, original)
        return False


# --------------------------------------------------------------------------- #
def run(suite, root):
    op_a = "op_res_fixture_alpha_0001"
    op_b = "op_res_fixture_beta_0002"
    _publish(root, op_a)
    _publish(root, op_b)

    # ---- 1. WIRING DEFECT: no source names an operation ------------------- #
    blocking, checks = _select(V._Args(pack="worldforge_vertical_slice"), root)
    suite.check("wiring_defect_fires_alone", _only(blocking, WIRING_RAIL),
                "no --operation-id and no pack declaration must fire ONLY {} "
                "(blocking resolution rails: {})".format(
                    WIRING_RAIL, sorted(r for r in RESOLUTION_RAILS if r in blocking)))
    suite.check("wiring_defect_code",
                checks.get(WIRING_RAIL, {}).get("code") == EXPECTED_CODE[WIRING_RAIL],
                "expected {} on {}, got {!r}".format(
                    EXPECTED_CODE[WIRING_RAIL], WIRING_RAIL,
                    checks.get(WIRING_RAIL, {}).get("code")))
    suite.check("wiring_defect_says_wiring",
                "WIRING DEFECT" in checks.get(WIRING_RAIL, {}).get("detail", ""),
                "the wiring RED must name itself so it is not read as absent "
                "evidence: {!r}".format(checks.get(WIRING_RAIL, {}).get("detail")))
    suite.check("wiring_defect_does_not_claim_absent_evidence",
                checks.get(ABSENT_RAIL, {}).get("verdict") == "SKIP_NOT_APPLICABLE",
                "with no operation id there is no address to look for evidence at, "
                "so {} must be SKIPPED rather than blamed (verdict {!r})".format(
                    ABSENT_RAIL, checks.get(ABSENT_RAIL, {}).get("verdict")))

    # ---- 2. AMBIGUITY: two declared candidates ---------------------------- #
    args = V._Args(pack="two_op_pack",
                   pack_document={"scene_survey_operation_ids": [op_a, op_b]})
    blocking, checks = _select(args, root)
    suite.check("ambiguity_fires_alone", _only(blocking, AMBIGUITY_RAIL),
                "two declared bound operations must fire ONLY {} (blocking "
                "resolution rails: {})".format(
                    AMBIGUITY_RAIL,
                    sorted(r for r in RESOLUTION_RAILS if r in blocking)))
    suite.check("ambiguity_code",
                checks.get(AMBIGUITY_RAIL, {}).get("code")
                == EXPECTED_CODE[AMBIGUITY_RAIL],
                "expected {} on {}, got {!r}".format(
                    EXPECTED_CODE[AMBIGUITY_RAIL], AMBIGUITY_RAIL,
                    checks.get(AMBIGUITY_RAIL, {}).get("code")))
    res = V.resolve_operation_id(args, repo_root=root)
    suite.check("ambiguity_picks_nothing",
                res["operation_id"] is None
                and res["outcome"] == V.OUTCOME_AMBIGUOUS
                and res["candidates"] == sorted([op_a, op_b]),
                "an ambiguous declaration must resolve to NO operation, never to "
                "the first/newest candidate: {}".format(res))

    # ---- 3. ABSENT CALLER EVIDENCE: named, unambiguous, nothing on disk --- #
    blocking, checks = _select(V._Args(operation_id="op_res_never_ran_9999"), root)
    suite.check("absent_evidence_fires_alone", _only(blocking, ABSENT_RAIL),
                "a named operation with no artifacts must fire ONLY {} (blocking "
                "resolution rails: {})".format(
                    ABSENT_RAIL,
                    sorted(r for r in RESOLUTION_RAILS if r in blocking)))
    suite.check("absent_evidence_code",
                checks.get(ABSENT_RAIL, {}).get("code") == EXPECTED_CODE[ABSENT_RAIL],
                "expected {} on {}, got {!r}".format(
                    EXPECTED_CODE[ABSENT_RAIL], ABSENT_RAIL,
                    checks.get(ABSENT_RAIL, {}).get("code")))
    suite.check("absent_evidence_says_absent_evidence",
                "ABSENT CALLER EVIDENCE"
                in checks.get(ABSENT_RAIL, {}).get("detail", ""),
                "the intentional RED must name itself: {!r}".format(
                    checks.get(ABSENT_RAIL, {}).get("detail")))
    suite.check("absent_evidence_names_the_operation_scoped_address",
                "op_res_never_ran_9999"
                in checks.get(ABSENT_RAIL, {}).get("detail", ""),
                "the absent-evidence RED must name the operation it would have "
                "graded, or it is indistinguishable from the wiring RED")

    # ---- 4. the three codes are genuinely distinct ------------------------ #
    codes = [EXPECTED_CODE[r] for r in RESOLUTION_RAILS]
    suite.check("three_distinct_failure_codes", len(set(codes)) == 3,
                "the three outcomes must not collapse onto one code: {}".format(codes))

    # ---- 5. a pack declaring exactly ONE bound operation resolves it ------ #
    one = V.resolve_operation_id(
        V._Args(pack="one_op_pack",
                pack_document={"scene_survey_operation_id": op_a}),
        repo_root=root)
    suite.check("single_pack_declaration_resolves",
                one["operation_id"] == op_a and one["source"] == V.OP_SOURCE_PACK
                and one["outcome"] == V.OUTCOME_RESOLVED,
                "one declared bound operation must resolve from the pack source: "
                "{}".format(one))
    blocking, _checks = _select(
        V._Args(pack="one_op_pack",
                pack_document={"scene_survey_operation_id": op_a}), root)
    suite.check("pack_resolved_operation_has_evidence",
                not any(r in blocking for r in RESOLUTION_RAILS),
                "a pack-resolved operation whose manifest AND report are both on "
                "disk must clear all three resolution rails — a positive control, "
                "without which every negative above is unfalsifiable (got {})".format(
                    sorted(blocking)))

    # ---- 6. the explicit argument WINS over a pack declaration ------------ #
    won = V.resolve_operation_id(
        V._Args(operation_id=op_b, pack="one_op_pack",
                pack_document={"scene_survey_operation_id": op_a}),
        repo_root=root)
    suite.check("argument_beats_pack",
                won["operation_id"] == op_b
                and won["source"] == V.OP_SOURCE_ARGUMENT,
                "an explicitly passed --operation-id must win outright: {}".format(won))

    # ---- 7. NEWEST-ON-DISK IS IMPOSSIBLE ---------------------------------- #
    # Two operations are published under `root`, one strictly newer. A resolver
    # that scanned would hand one of them back for an invocation that named
    # neither. Asserted twice: behaviourally, and by making enumeration explode.
    newest = _publish(root, "op_res_fixture_newest_0003")
    os.utime(newest, (2 ** 31 - 1, 2 ** 31 - 1))  # unmistakably the newest file
    scanned = V.resolve_operation_id(V._Args(pack="worldforge_vertical_slice"),
                                     repo_root=root)
    suite.check("no_newest_on_disk_fallback",
                scanned["operation_id"] is None
                and scanned["outcome"] == V.OUTCOME_WIRING_DEFECT,
                "with three operations on disk and no source naming one, the "
                "resolver must resolve NOTHING — 'take the newest' is the "
                "eight-day-old-artifact defect in a new costume: {}".format(scanned))
    suite.check("sources_are_a_closed_set",
                tuple(scanned["sources_consulted"]) == V.OPERATION_ID_SOURCES
                and V.OPERATION_ID_SOURCES == (V.OP_SOURCE_ARGUMENT, V.OP_SOURCE_PACK),
                "the source list must stay closed and declared; a filesystem source "
                "added later has to change this literal: {}".format(
                    scanned["sources_consulted"]))
    # The guard itself must be falsifiable, or "resolution completed under it"
    # proves only that the guard does nothing.
    caught = []
    with _NoDirectoryEnumeration():
        for probe_fn in (lambda: list(root.iterdir()),
                         lambda: list(root.glob("*")),
                         lambda: os.listdir(str(root))):
            try:
                probe_fn()
                caught.append(None)
            except AssertionError:
                caught.append("raised")
    suite.check("no_enumeration_guard_is_armed",
                caught == ["raised", "raised", "raised"],
                "the guard must actually break directory enumeration, or the "
                "no-scan proof below is vacuous: {}".format(caught))

    try:
        with _NoDirectoryEnumeration():
            for probe in (V._Args(pack="worldforge_vertical_slice"),
                          V._Args(operation_id=op_a),
                          V._Args(pack="two_op_pack",
                                  pack_document={"scene_survey_operation_ids":
                                                 [op_a, op_b]})):
                V.resolve_operation_id(probe, repo_root=root)
        enumerated = None
    except AssertionError as exc:
        enumerated = str(exc)
    suite.check("resolution_never_enumerates_a_directory", enumerated is None,
                "resolution must complete with iterdir/glob/rglob/listdir/scandir/"
                "walk all disabled: {}".format(enumerated))

    # ---- 8. an unusable id is a WIRING defect, never silently normalised --- #
    for bad in ("../escape", "op with/slash", "   ", "..."):
        bad_res = V.resolve_operation_id(V._Args(operation_id=bad), repo_root=root)
        suite.check("unusable_id_rejected[{!r}]".format(bad),
                    bad_res["operation_id"] is None
                    and bad_res["outcome"] == V.OUTCOME_WIRING_DEFECT,
                    "an id that is not filesystem-safe as written must be REFUSED, "
                    "not slugged into some other operation's directory: {}".format(
                        bad_res))

    # ---- 9. a pack candidate that is unusable does not become a resolution - #
    poisoned = V.resolve_operation_id(
        V._Args(pack="bad_pack",
                pack_document={"scene_survey_operation_ids": ["../escape", op_a]}),
        repo_root=root)
    suite.check("unusable_pack_candidate_dropped_not_normalised",
                poisoned["operation_id"] == op_a
                and poisoned["candidates"] == [op_a],
                "an unusable declared candidate must be dropped, never normalised "
                "into a second candidate: {}".format(poisoned))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="wf_op_resolution_"))
    try:
        root = tmp / "repo"
        root.mkdir(parents=True, exist_ok=True)
        suite = _Suite()
        run(suite, root)
        rc = suite.report("NEGATIVE scene-survey operation-id resolution")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
