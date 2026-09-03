#!/usr/bin/env python3
"""test_evidence_ladder -- the rail that grades every other rail was itself ungraded.

WHY THIS SUITE EXISTS
---------------------
``evidence_ladder`` decides whether a capability is runtime_qualified. On
2026-09-03 it awarded rung 5 to ``landscape_provider`` on the strength of a
far-side document from a run that FAILED -- outcome ``rolled_back``,
verification ``violated``, ``WF1246_CORE_DELTA_INVALID``, the placeholder actor
destroyed by rollback.

The cause was a docstring that outran its code. ``_runtime_evidence`` promised
"an artifact that exists AND says it came from a live run" and implemented only
``isinstance(doc, dict)``. Any parseable JSON at the path counted, including a
record of the capability failing.

That is the exact inversion this ladder exists to prevent, in the ladder itself,
and nothing would have caught it because the module had no suite at all. These
assertions are the regression guard.

THE RULE BEING DEFENDED
-----------------------
Absence of a verdict is NOT failure -- artifact types differ, and a scene-survey
report carries none of these keys. But the PRESENCE of a failure signal is
decisive. Silence stays silence; a recorded failure can never again be read as
a success.
"""

import json
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from pipeline import evidence_ladder as EL    # noqa: E402

_FAILS = []
_N = [0]


def check(name, ok, detail=""):
    if ok:
        _N[0] += 1
    else:
        _FAILS.append("{}: {}".format(name, detail))
    return ok


class _artifact(object):
    """Write a doc under the repo root and yield its repo-relative path."""

    def __init__(self, doc):
        self.doc = doc
        self.dir = None
        self.rel = None

    def __enter__(self):
        self.dir = tempfile.mkdtemp(dir=EL._REPO, prefix="_ladder_probe_")
        path = os.path.join(self.dir, "far_side.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.doc, fh)
        self.rel = os.path.relpath(path, EL._REPO).replace(os.sep, "/")
        return self.rel

    def __exit__(self, *exc):
        try:
            os.remove(os.path.join(self.dir, "far_side.json"))
            os.rmdir(self.dir)
        except OSError:
            pass
        return False


# --------------------------------------------------------------------------- #
# the defect that prompted this suite
# --------------------------------------------------------------------------- #
def test_rolled_back_run_is_not_runtime_evidence():
    doc = {"operation_id": "op_probe", "outcome": "rolled_back",
           "verification": "violated",
           "failure_codes": ["WF1246_CORE_DELTA_INVALID"]}
    with _artifact(doc) as rel:
        ok, _which = EL._runtime_evidence([rel])
    check("rolled_back_refused", not ok,
          "a far-side document recording a ROLLED BACK, verification-violated "
          "run was accepted as proof the capability is runtime_qualified. This "
          "is the 2026-09-03 landscape defect")


def test_failure_codes_alone_are_decisive():
    with _artifact({"failure_codes": ["WF1246_CORE_DELTA_INVALID"]}) as rel:
        ok, _w = EL._runtime_evidence([rel])
    check("failure_codes_refused", not ok,
          "a document carrying failure codes was read as success")


def test_error_field_is_decisive():
    with _artifact({"error": "sink refused the request"}) as rel:
        ok, _w = EL._runtime_evidence([rel])
    check("error_refused", not ok, "a document carrying an error was read as success")


def test_violated_verification_is_decisive():
    with _artifact({"verification": "violated"}) as rel:
        ok, _w = EL._runtime_evidence([rel])
    check("violated_refused", not ok,
          "verification=violated was read as success")


def test_nested_delta_verdict_is_read():
    doc = {"operation_id": "op_probe",
           "delta": {"outcome": "rolled_back", "failure_codes": ["WF1246"]}}
    with _artifact(doc) as rel:
        ok, _w = EL._runtime_evidence([rel])
    check("nested_delta_refused", not ok,
          "a transaction document carries its verdict in the nested delta; "
          "reading only the top level would miss it")


def test_failed_status_is_decisive():
    """The procedural/ lane spells its verdict ``status``, not ``outcome``."""
    for bad in EL._FAILED_STATUSES:
        with _artifact({"recipe_id": "r", "status": bad}) as rel:
            ok, _w = EL._runtime_evidence([rel])
        check("status_{}_refused".format(bad), not ok,
              "status={!r} was accepted as runtime evidence; the two lanes name "
              "the same idea differently and a check that knows only one "
              "vocabulary reads the other's failures as silence".format(bad))
    with _artifact({"recipe_id": "r", "status": "ok"}) as rel:
        ok, _w = EL._runtime_evidence([rel])
    check("status_ok_accepted", ok, "status=ok must still count")


def test_every_failed_outcome_refused():
    for outcome in EL._FAILED_OUTCOMES:
        with _artifact({"outcome": outcome}) as rel:
            ok, _w = EL._runtime_evidence([rel])
        check("outcome_{}_refused".format(outcome), not ok,
              "outcome {!r} was accepted as runtime evidence".format(outcome))


# --------------------------------------------------------------------------- #
# and the other half: silence must stay silence
# --------------------------------------------------------------------------- #
def test_committed_run_is_accepted():
    doc = {"operation_id": "op_probe", "outcome": "committed",
           "verification": "satisfied", "failure_codes": []}
    with _artifact(doc) as rel:
        ok, which = EL._runtime_evidence([rel])
    check("committed_accepted", ok,
          "a committed, verification-satisfied run must still count, or the "
          "hardening has simply broken the ladder")
    check("committed_names_the_artifact", which is not None, "no path returned")


def test_document_without_verdict_fields_is_accepted():
    """A scene-survey report carries none of these keys. Absence is not failure."""
    with _artifact({"report_type": "wf.core.scene_survey_report.v1",
                    "subjects": []}) as rel:
        ok, _w = EL._runtime_evidence([rel])
    check("silent_document_accepted", ok,
          "a document that simply does not use outcome/verification/error was "
          "refused. Absence of a verdict is not a negative verdict, and other "
          "artifact types legitimately carry none of these fields")


def test_missing_and_unparseable_are_refused():
    ok, _w = EL._runtime_evidence(["procedural/reports/_does_not_exist_/x.json"])
    check("missing_refused", not ok, "a nonexistent path was accepted")
    d = tempfile.mkdtemp(dir=EL._REPO, prefix="_ladder_probe_")
    path = os.path.join(d, "bad.json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        rel = os.path.relpath(path, EL._REPO).replace(os.sep, "/")
        ok, _w = EL._runtime_evidence([rel])
        check("unparseable_refused", not ok, "unparseable JSON was accepted")
    finally:
        try:
            os.remove(path)
            os.rmdir(d)
        except OSError:
            pass


def test_ladder_is_ordered_and_never_self_awards_external():
    check("rungs_ordered",
          EL.RUNGS == ("implemented", "unit_tested", "hostile_qualified",
                       "shield_integrated", "runtime_qualified",
                       "externally_proven"),
          "the ladder's ordering is the whole point; got {!r}".format(EL.RUNGS))
    check("externally_proven_is_last",
          EL.RUNGS[-1] == "externally_proven",
          "externally_proven must remain the top rung and must never be "
          "self-awarded")


def main():
    for fn in sorted((v for k, v in globals().items()
                      if k.startswith("test_") and callable(v)),
                     key=lambda f: f.__name__):
        fn()
    if _FAILS:
        print("test_evidence_ladder: {} assertion(s) passed, {} FAILED"
              .format(_N[0], len(_FAILS)))
        for f in _FAILS:
            print("  FAIL {}".format(f))
        return 1
    print("test_evidence_ladder: {} assertion(s) passed, 0 failed".format(_N[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
