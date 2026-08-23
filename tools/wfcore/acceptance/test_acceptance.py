#!/usr/bin/env python3
"""wfcore.acceptance.test_acceptance -- negative-first suite for the verdict.

Run from ``tools/``::

    PYTHONUTF8=1 python -m wfcore.acceptance.test_acceptance

WHAT THIS SUITE IS FOR
----------------------
An evaluator that agrees with its own canonical example proves nothing -- the
example was built by the evaluator. What proves it is the set of KNOWN-BADS it
refuses, and refusing them FOR THE RIGHT CODE.

Every expected verdict here is RE-DERIVED FROM THE RAW EVIDENCE ROWS -- their
literal ``operation_id`` / ``observed_at`` / ``observation_kind`` / ``supports``
keys -- never by calling the evaluator's own helpers. A test that computes its
expectation with the function under test asserts only that the function is
deterministic.

Five tests are load-bearing beyond ordinary coverage and are named as such:

  * ``test_unknown_load_bearing_criterion_blocks_even_with_nothing_violated`` --
    the headline fake-green. The suite asserts, in the same test, that the
    two-valued spelling (``verdict != VIOLATED``) WOULD have accepted it.
  * ``test_acceptance_refused_without_a_reload_backed_observation`` -- and the
    in-memory rows carry SATISFYING values, which is the shape that reads green.
  * ``test_partial_commit_is_never_accepted_and_is_reported_as_partial``
  * ``test_stale_evidence_accepts_the_previous_world``
  * ``test_forged_acceptance_over_an_unknown_raises_wf1257``

``test_harness_negative_control`` feeds the failure-path assertions a CLEAN
record and proves they register a failure. Without it, a harness whose expect_*
functions silently pass everything would report a green suite over nothing.
"""

import copy
import sys

from .. import constraints as K
from .. import tri
from ..failure import FailureCode as C
from ..transaction import delta as D
from . import evaluate as EV

_FAILURES = []
_RAN = []


# --------------------------------------------------------------------------- #
# harness
# --------------------------------------------------------------------------- #
def _failing(checks):
    return [(n, d, code) for (n, ok, d, code) in checks if not ok]


def _codes(checks):
    return {code for (_n, ok, _d, code) in checks if not ok and code}


def expect_pass(label, checks):
    bad = _failing(checks)
    if bad:
        _FAILURES.append("{}: expected all checks to pass, {} failed:\n    {}"
                         .format(label, len(bad),
                                 "\n    ".join("{} [{}] {}".format(n, c, d)
                                               for (n, d, c) in bad[:6])))


def expect_code(label, checks, code):
    got = _codes(checks)
    if code not in got:
        _FAILURES.append(
            "{}: expected failure code {}, got {} (failing checks: {})"
            .format(label, code, sorted(got) or "none",
                    [n for (n, _d, _c) in _failing(checks)][:6]))


def expect_code_absent(label, checks, code):
    got = _codes(checks)
    if code in got:
        _FAILURES.append(
            "{}: failure code {} must NOT be emitted, but it was (checks: {})"
            .format(label, code,
                    [n for (n, _d, c) in _failing(checks) if c == code]))


def expect(label, condition, detail):
    if not condition:
        _FAILURES.append("{}: {}".format(label, detail))


def expect_eq(label, got, want):
    if got != want:
        _FAILURES.append("{}: expected {!r}, got {!r}".format(label, want, got))


def expect_record_code(label, record, code):
    got = record.get("failure_codes") or []
    if code not in got:
        _FAILURES.append("{}: expected record to carry {}, codes were {}".format(
            label, code, got))


def test(fn):
    _RAN.append(fn)
    return fn


# --------------------------------------------------------------------------- #
# fixtures -- raw, so expectations can be re-derived from them by hand
# --------------------------------------------------------------------------- #
def _criteria(**over):
    return EV._example_criteria(**over)


def _load_bearing_ids(criteria=None):
    criteria = _criteria() if criteria is None else criteria
    return [c["constraint_id"] for c in criteria["constraints"]
            if K.is_acceptance_load_bearing(c)]


def _non_load_bearing_ids(criteria=None):
    criteria = _criteria() if criteria is None else criteria
    return [c["constraint_id"] for c in criteria["constraints"]
            if not K.is_acceptance_load_bearing(c)]


def _rows(**over):
    return EV._example_evidence_set(**over)


def _row_for(rows, constraint_id):
    for r in rows:
        if r["constraint_id"] == constraint_id:
            return r
    return None


def _run(**over):
    return EV._example_acceptance_result(**over)


def _finding_of(result, constraint_id):
    for f in result["findings"]:
        if f["constraint_id"] == constraint_id:
            return f
    return None


# --------------------------------------------------------------------------- #
# harness negative control
# --------------------------------------------------------------------------- #
@test
def test_harness_negative_control():
    """Feed the failure-path assertions a CLEAN record; they must object.

    A suite whose expect_* helpers pass everything reports green over nothing,
    and it looks exactly like a suite that is working.
    """
    global _FAILURES
    saved = _FAILURES
    try:
        _FAILURES = []
        clean = [("a_check_that_passed", True, "nothing wrong here", None)]
        expect_code("negative control", clean, C.CORE_ACCEPTANCE_INVALID)
        expect("negative control", False, "a false condition must be recorded")
        expect_eq("negative control", "got", "want")
        expect_pass("negative control",
                    [("a_check_that_failed", False, "detail",
                      C.CORE_ACCEPTANCE_INVALID)])
        expect_code_absent("negative control",
                           [("a_check_that_failed", False, "detail",
                             C.CORE_ACCEPTANCE_INVALID)],
                           C.CORE_ACCEPTANCE_INVALID)
        expect_record_code("negative control", {"failure_codes": []},
                           C.CORE_ACCEPTANCE_INVALID)
        registered = len(_FAILURES)
    finally:
        _FAILURES = saved
    expect_eq("harness registers every failure-path assertion", registered, 6)


# --------------------------------------------------------------------------- #
# canonical
# --------------------------------------------------------------------------- #
@test
def test_acceptance_result_example_is_valid():
    expect_pass("acceptance result canonical",
                EV.validate_acceptance_result(_run(), strict=True))


@test
def test_acceptance_finding_examples_are_valid():
    result = _run()
    for f in result["findings"]:
        expect_pass("finding canonical {}".format(f["constraint_id"]),
                    EV.validate_acceptance_finding(
                        f, judged=result["judged_operation"], strict=True))


@test
def test_acceptance_evidence_example_is_valid():
    result = _run()
    for row in _rows():
        expect_pass("evidence canonical {}".format(row["evidence_id"]),
                    EV.validate_acceptance_evidence(
                        row, judged=result["judged_operation"], strict=True))


@test
def test_canonical_result_is_accepted_on_reload_backed_evidence():
    rows = _rows()
    # re-derived by hand from the raw rows, not from is_reload_backed()
    expect("every canonical row really is a reload-backed observation",
           all(r["observation_kind"] == EV.OBS_RELOADED
               and r["reload_backed"] is True
               and r["supports"] == tri.SATISFIED for r in rows),
           "rows were {}".format([(r["observation_kind"], r["reload_backed"],
                                   r["supports"]) for r in rows]))
    result = _run()
    expect_eq("the canonical result is judged", result["judged"], True)
    expect_eq("the canonical verdict is SATISFIED",
              result["acceptance_verdict"], tri.SATISFIED)
    expect_eq("and it is accepted", result["accepted"], True)
    expect_eq("outcome accepted", result["outcome"], EV.OUTCOME_ACCEPTED)
    expect_eq("nothing blocks", result["blockers"], [])
    expect_eq("no failure codes", result["failure_codes"], [])


# --------------------------------------------------------------------------- #
# THE headline: acceptance on unknowns
# --------------------------------------------------------------------------- #
@test
def test_unknown_load_bearing_criterion_blocks_even_with_nothing_violated():
    """Everything 'passed' because nothing measured it. WF1257.

    One load-bearing criterion is left with no evidence at all. Nothing is
    violated, every row that IS present is reload-backed and satisfying, and the
    two-valued spelling of acceptance -- ``verdict != VIOLATED`` -- would accept
    it. That gap is the whole point, so it is asserted here rather than assumed.
    """
    unmeasured = _load_bearing_ids()[0]
    rows = [r for r in _rows() if r["constraint_id"] != unmeasured]

    # re-derived from the raw rows: nothing here supports a violation.
    expect("no remaining row supports a violation",
           all(r["supports"] == tri.SATISFIED for r in rows),
           "rows supported {}".format([r["supports"] for r in rows]))
    expect("the unmeasured criterion really is load-bearing",
           unmeasured in _load_bearing_ids(),
           "{} is not load-bearing".format(unmeasured))
    expect("and it really has no evidence",
           _row_for(rows, unmeasured) is None,
           "a row for {} survived the filter".format(unmeasured))

    result = _run(evidence=rows)
    expect_eq("the unmeasured criterion is UNKNOWN",
              _finding_of(result, unmeasured)["evaluation"], tri.UNKNOWN)
    expect_eq("nothing is violated", result["acceptance_verdict"], tri.UNKNOWN)
    expect_eq("so it is NOT accepted", result["accepted"], False)
    expect_eq("outcome is indeterminate, not rejected",
              result["outcome"], EV.OUTCOME_INDETERMINATE)
    expect_record_code("unknown blocks acceptance", result,
                       C.CORE_ACCEPTANCE_ON_UNKNOWN)
    expect("the blocker names the unmeasured criterion",
           unmeasured in [b["constraint_id"] for b in result["blockers"]],
           "blockers were {}".format(result["blockers"]))
    expect_eq("the blocking reason is 'never measured', not 'violated'",
              [b["blocking_reason"] for b in result["blockers"]
               if b["constraint_id"] == unmeasured][0],
              "not_evaluated_no_observation_supports_a_verdict")

    # THE gap, written out: the two-valued spelling would have accepted this.
    expect_eq("the two-valued spelling would have accepted it",
              result["acceptance_verdict"] != tri.VIOLATED, True)
    expect_eq("tri.accepts does not", tri.accepts(result["acceptance_verdict"]),
              False)
    expect_pass("the indeterminate result is well formed",
                EV.validate_acceptance_result(result, strict=True))


@test
def test_a_violated_criterion_is_rejected_not_indeterminate():
    """VIOLATED and UNKNOWN are kept apart: they route to opposite repairs."""
    target = _load_bearing_ids()[0]
    rows = copy.deepcopy(_rows())
    _row_for(rows, target)["supports"] = tri.VIOLATED

    result = _run(evidence=rows)
    expect_eq("the verdict is VIOLATED", result["acceptance_verdict"],
              tri.VIOLATED)
    expect_eq("outcome is rejected", result["outcome"], EV.OUTCOME_REJECTED)
    expect_eq("not accepted", result["accepted"], False)
    expect_eq("the blocking reason names a measured violation",
              [b["blocking_reason"] for b in result["blockers"]
               if b["constraint_id"] == target][0],
              "violated_by_observation")
    expect("a measured violation is not reported as an unknown",
           C.CORE_ACCEPTANCE_ON_UNKNOWN not in result["failure_codes"],
           "codes were {}".format(result["failure_codes"]))
    expect_pass("the rejection is well formed",
                EV.validate_acceptance_result(result, strict=True))


@test
def test_non_load_bearing_criterion_never_moves_the_verdict():
    """A soft preference is structurally incapable of blocking."""
    soft = _non_load_bearing_ids()
    expect("the canonical criteria really do carry a non-load-bearing member",
           bool(soft), "every criterion was load-bearing")

    baseline = _run()
    rows = copy.deepcopy(_rows())
    for cid in soft:
        _row_for(rows, cid)["supports"] = tri.VIOLATED
    flipped = _run(evidence=rows)

    expect_eq("the violated preference IS reported",
              _finding_of(flipped, soft[0])["evaluation"], tri.VIOLATED)
    expect_eq("but the verdict does not move", flipped["acceptance_verdict"],
              baseline["acceptance_verdict"])
    expect_eq("and it never becomes a blocker", flipped["blockers"], [])
    expect_eq("the result is still accepted", flipped["accepted"], True)

    # And with the preference dropped entirely.
    dropped = _run(evidence=[r for r in _rows() if r["constraint_id"] not in soft])
    expect_eq("dropping it does not move the verdict",
              dropped["acceptance_verdict"], baseline["acceptance_verdict"])


# --------------------------------------------------------------------------- #
# THE reload rail (WF1259)
# --------------------------------------------------------------------------- #
@test
def test_acceptance_refused_without_a_reload_backed_observation():
    """Every row is an in-memory observation carrying a SATISFYING value.

    This is the shape that reads green: nothing is violated, nothing is missing,
    and every criterion has an observation. If reload-backing is not consulted
    before the value is folded, this accepts a world that was never persisted.
    """
    rows = _rows(observation_kind=EV.OBS_IN_MEMORY, reload_backed=False)

    # re-derived from the raw rows.
    expect("every row really is in-memory",
           all(r["observation_kind"] == EV.OBS_IN_MEMORY
               and r["reload_backed"] is False for r in rows),
           "rows were {}".format([(r["observation_kind"], r["reload_backed"])
                                  for r in rows]))
    expect("and every row really does carry a satisfying value",
           all(r["supports"] == tri.SATISFIED for r in rows),
           "rows supported {}".format([r["supports"] for r in rows]))

    result = _run(evidence=rows)
    expect_eq("the judgement refuses", result["judged"], False)
    expect_eq("outcome refused", result["outcome"], EV.OUTCOME_REFUSED)
    expect_eq("verdict is UNKNOWN, not vacuous SATISFIED",
              result["acceptance_verdict"], tri.UNKNOWN)
    expect_eq("not accepted", result["accepted"], False)
    expect_eq("no findings are produced against an unjudgeable result",
              result["findings"], [])
    expect_record_code("no reload-backed observation", result,
                       C.CORE_ACCEPTANCE_NOT_RELOADED)
    expect("the refusal says why", bool(result["refusal_reason"]),
           "refusal_reason was empty")
    expect_pass("the refusal record is well formed",
                EV.validate_acceptance_result(result, strict=True))


@test
def test_no_evidence_at_all_refuses_rather_than_folding_vacuously():
    result = _run(evidence=[])
    expect_eq("outcome refused", result["outcome"], EV.OUTCOME_REFUSED)
    expect_eq("verdict is UNKNOWN, never the vacuous SATISFIED tri.conj returns",
              result["acceptance_verdict"], tri.UNKNOWN)
    expect_record_code("empty evidence", result, C.CORE_ACCEPTANCE_NOT_RELOADED)


@test
def test_one_unreloaded_criterion_blocks_only_that_criterion():
    """Partial reload-backing is judged per criterion, not waved through."""
    target = _load_bearing_ids()[0]
    rows = copy.deepcopy(_rows())
    row = _row_for(rows, target)
    row["observation_kind"] = EV.OBS_IN_MEMORY
    row["reload_backed"] = False

    result = _run(evidence=rows)
    expect_eq("the judgement still runs (other rows are reload-backed)",
              result["judged"], True)
    expect_eq("the unreloaded criterion is UNKNOWN",
              _finding_of(result, target)["evaluation"], tri.UNKNOWN)
    expect_eq("not accepted", result["accepted"], False)
    expect("the finding names the reload failure",
           C.CORE_ACCEPTANCE_NOT_RELOADED
           in _finding_of(result, target)["failure_codes"],
           "codes were {}".format(_finding_of(result, target)["failure_codes"]))
    expect("and the result lists it as unreloaded",
           target in result["unreloaded_criteria"],
           "unreloaded_criteria was {}".format(result["unreloaded_criteria"]))
    expect_pass("the partially-reloaded result is well formed",
                EV.validate_acceptance_result(result, strict=True))


# --------------------------------------------------------------------------- #
# THE staleness rail (WF1258)
# --------------------------------------------------------------------------- #
@test
def test_stale_evidence_accepts_the_previous_world():
    """Evidence taken before the delta landed describes the world it replaced."""
    target = _load_bearing_ids()[0]
    rows = copy.deepcopy(_rows())
    _row_for(rows, target)["observed_at"] = EV.EXAMPLE_APPLIED_AT - 1

    # re-derived by hand: the row predates the ordinal at which the delta landed.
    expect("the fixture really does predate the delta",
           _row_for(rows, target)["observed_at"] < EV.EXAMPLE_APPLIED_AT,
           "observed_at={} applied_at={}".format(
               _row_for(rows, target)["observed_at"], EV.EXAMPLE_APPLIED_AT))

    result = _run(evidence=rows)
    expect_eq("a criterion resting on stale evidence is UNKNOWN",
              _finding_of(result, target)["evaluation"], tri.UNKNOWN)
    expect_eq("not accepted", result["accepted"], False)
    expect_record_code("stale evidence", result, C.CORE_ACCEPTANCE_STALE_EVIDENCE)
    expect_eq("the stale row is named, not silently dropped",
              [s["stale_reason"] for s in result["stale_evidence"]],
              [EV.STALE_PREDATES_DELTA])
    # The record is internally COHERENT -- it recorded the staleness honestly --
    # so it raises WF1258 and nothing else. A validator that stayed silent here
    # would let a judgement rest on the previous world without objecting.
    checks = EV.validate_acceptance_result(result, strict=True)
    expect_code("the validator objects to the stale row", checks,
                C.CORE_ACCEPTANCE_STALE_EVIDENCE)
    expect_code_absent("but the record itself is coherent", checks,
                       C.CORE_ACCEPTANCE_INVALID)


@test
def test_evidence_from_another_operation_is_stale():
    target = _load_bearing_ids()[0]
    rows = copy.deepcopy(_rows())
    _row_for(rows, target)["operation_id"] = "op_some_earlier_operation"

    result = _run(evidence=rows)
    expect_eq("evidence naming another operation is UNKNOWN",
              _finding_of(result, target)["evaluation"], tri.UNKNOWN)
    expect_record_code("different operation", result,
                       C.CORE_ACCEPTANCE_STALE_EVIDENCE)
    expect_eq("the reason distinguishes it from an ordering problem",
              [s["stale_reason"] for s in result["stale_evidence"]],
              [EV.STALE_DIFFERENT_OPERATION])


@test
def test_unorderable_evidence_is_not_reported_as_predating():
    """'We cannot tell when this was taken' is its own reason, and it blocks."""
    target = _load_bearing_ids()[0]
    rows = copy.deepcopy(_rows())
    _row_for(rows, target)["observed_at"] = None

    result = _run(evidence=rows)
    expect_eq("an unorderable row is UNKNOWN",
              _finding_of(result, target)["evaluation"], tri.UNKNOWN)
    expect_eq("the reason is unestablished ordering, not a comparison nobody made",
              [s["stale_reason"] for s in result["stale_evidence"]],
              [EV.STALE_ORDER_UNESTABLISHED])


@test
def test_a_stale_row_poisons_its_criterion_rather_than_being_filtered_out():
    """Dropping the stale row and folding the survivors is the shrink that
    returns SATISFIED. The criterion must go UNKNOWN instead."""
    target = _load_bearing_ids()[0]
    rows = copy.deepcopy(_rows())
    stale = copy.deepcopy(_row_for(rows, target))
    stale["evidence_id"] = "ev_stale"
    stale["observed_at"] = EV.EXAMPLE_APPLIED_AT - 5
    rows.append(stale)

    # The criterion now has ONE fresh reload-backed satisfying row and one stale
    # one. Filtering the stale one out would fold SATISFIED.
    cited = [r for r in rows if r["constraint_id"] == target]
    expect_eq("the criterion cites two rows", len(cited), 2)
    expect("one of them is fresh and satisfying",
           any(r["observed_at"] >= EV.EXAMPLE_APPLIED_AT
               and r["supports"] == tri.SATISFIED for r in cited),
           "cited rows were {}".format(cited))

    result = _run(evidence=rows)
    expect_eq("the criterion is UNKNOWN, not SATISFIED",
              _finding_of(result, target)["evaluation"], tri.UNKNOWN)
    expect_eq("not accepted", result["accepted"], False)


# --------------------------------------------------------------------------- #
# THE partial-commit rail (WF1249)
# --------------------------------------------------------------------------- #
@test
def test_partial_commit_is_never_accepted_and_is_reported_as_partial():
    """A world state no contract describes. Reported AS partial, not rejected."""
    delta = EV._example_delta(outcome=D.DELTA_PARTIAL_COMMIT)
    expect_eq("the fixture really is a partial commit",
              D.is_partial_commit(delta["outcome"]), True)
    expect("and it is neither committed nor rolled back",
           not D.is_committed(delta["outcome"])
           and not D.is_rolled_back(delta["outcome"]),
           "is_committed={} is_rolled_back={}".format(
               D.is_committed(delta["outcome"]),
               D.is_rolled_back(delta["outcome"])))

    result = _run(delta=delta)
    expect_eq("outcome is partial_commit", result["outcome"],
              EV.OUTCOME_PARTIAL_COMMIT)
    expect("it is NOT rounded into a rejection",
           result["outcome"] != EV.OUTCOME_REJECTED,
           "outcome was {}".format(result["outcome"]))
    expect_eq("it can never be accepted", result["accepted"], False)
    expect_eq("the verdict is written out as UNKNOWN",
              result["acceptance_verdict"], tri.UNKNOWN)
    expect_record_code("partial commit", result, C.CORE_DELTA_PARTIAL_COMMIT)
    expect_pass("the partial-commit refusal is well formed",
                EV.validate_acceptance_result(result, strict=True))

    # And even with a full set of fresh reload-backed satisfying evidence.
    with_evidence = _run(delta=delta, evidence=_rows())
    expect_eq("perfect evidence does not rescue a partial commit",
              with_evidence["accepted"], False)
    expect_eq("still reported as partial", with_evidence["outcome"],
              EV.OUTCOME_PARTIAL_COMMIT)


@test
def test_a_delta_that_never_committed_is_refused_not_judged():
    for outcome in (D.DELTA_REFUSED, D.DELTA_ROLLED_BACK):
        result = _run(delta=EV._example_delta(outcome=outcome))
        expect_eq("outcome {} refuses judgement".format(outcome),
                  result["outcome"], EV.OUTCOME_REFUSED)
        expect_eq("verdict is UNKNOWN for {}".format(outcome),
                  result["acceptance_verdict"], tri.UNKNOWN)
        expect_eq("not accepted for {}".format(outcome), result["accepted"],
                  False)


@test
def test_an_unverified_commit_can_still_be_accepted_on_reloaded_evidence():
    """``commit_is_verified`` is recorded, not the gate -- see the module docstring."""
    delta = EV._example_delta(outcome=D.DELTA_COMMITTED_UNVERIFIED)
    expect_eq("the fixture is committed", D.is_committed(delta["outcome"]), True)
    expect_eq("but its commit is not verified",
              D.commit_is_verified(delta["outcome"]), False)

    result = _run(delta=delta)
    expect_eq("the judgement runs", result["judged"], True)
    expect_eq("and reload-backed evidence carries it", result["accepted"], True)
    expect_eq("the record still states the commit was unverified",
              result["judged_operation"]["commit_verified"], False)


# --------------------------------------------------------------------------- #
# shape refusals (WF1256)
# --------------------------------------------------------------------------- #
@test
def test_shape_refusals_raise_wf1256():
    cases = [
        ("criteria are not an object", dict(criteria="not an object")),
        ("criteria carry no constraints",
         dict(criteria=_criteria(constraints=[]))),
        ("criteria carry only non-load-bearing constraints",
         dict(criteria=_criteria(constraints=[
             c for c in _criteria()["constraints"]
             if not K.is_acceptance_load_bearing(c)],
             evaluation_requirements=[], must_block_ids=[]))),
        ("the delta names no operation",
         dict(delta=EV._example_delta(operation_id=None))),
        ("no applied_at ordinal", dict(applied_at="recently")),
    ]
    for label, over in cases:
        result = _run(**over)
        expect_eq("{}: refuses".format(label), result["outcome"],
                  EV.OUTCOME_REFUSED)
        expect_record_code(label, result, C.CORE_ACCEPTANCE_INVALID)
        expect_eq("{}: verdict stays UNKNOWN".format(label),
                  result["acceptance_verdict"], tri.UNKNOWN)


# --------------------------------------------------------------------------- #
# validate_acceptance_result: known-bads
# --------------------------------------------------------------------------- #
@test
def test_forged_acceptance_over_an_unknown_raises_wf1257():
    """The headline fake-green, written out as a forged record."""
    unmeasured = _load_bearing_ids()[0]
    bad = copy.deepcopy(_run(
        evidence=[r for r in _rows() if r["constraint_id"] != unmeasured]))
    expect_eq("the honest evaluator did not accept it", bad["accepted"], False)

    # forge it: claim acceptance while the evidence still measures nothing.
    bad["accepted"] = True
    bad["acceptance_verdict"] = tri.SATISFIED
    bad["outcome"] = EV.OUTCOME_ACCEPTED
    bad["blockers"] = []
    bad["failure_codes"] = []

    checks = EV.validate_acceptance_result(bad)
    expect_code("forged acceptance over an unknown", checks,
                C.CORE_ACCEPTANCE_ON_UNKNOWN)


@test
def test_result_known_bads():
    invalid = C.CORE_ACCEPTANCE_INVALID

    # 1. not an object at all.
    expect_code("result is not an object",
                EV.validate_acceptance_result(["not", "an", "object"]), invalid)

    # 2. accepted claimed over a MEASURED violation.
    target = _load_bearing_ids()[0]
    rows = copy.deepcopy(_rows())
    _row_for(rows, target)["supports"] = tri.VIOLATED
    bad = copy.deepcopy(_run(evidence=rows))
    bad["accepted"] = True
    bad["outcome"] = EV.OUTCOME_ACCEPTED
    expect_code("accepted over a measured violation",
                EV.validate_acceptance_result(bad), invalid)

    # 3. a refusal recording an acceptance -- the vacuous-fold trap.
    bad = copy.deepcopy(_run(evidence=[]))
    bad["acceptance_verdict"] = tri.SATISFIED
    bad["accepted"] = True
    bad["outcome"] = EV.OUTCOME_ACCEPTED
    expect_code("refusal recording an acceptance",
                EV.validate_acceptance_result(bad),
                C.CORE_ACCEPTANCE_ON_UNKNOWN)

    # 4. a blocker dropped from the blockers list.
    bad = copy.deepcopy(_run(
        evidence=[r for r in _rows() if r["constraint_id"] != target]))
    bad["blockers"] = []
    expect_code("dropped blocker", EV.validate_acceptance_result(bad), invalid)

    # 5. an evidence row claiming reload-backing while naming an in-memory kind.
    bad = copy.deepcopy(_run())
    bad["findings"][0]["evidence"][0]["observation_kind"] = EV.OBS_IN_MEMORY
    expect_code("row signs reload_backed over an in-memory kind",
                EV.validate_acceptance_result(bad),
                C.CORE_ACCEPTANCE_NOT_RELOADED)

    # 6. a row whose own usable/stale summary contradicts its content.
    bad = copy.deepcopy(_run())
    bad["findings"][0]["evidence"][0]["operation_id"] = "op_a_different_one"
    expect_code("row summary contradicts its content",
                EV.validate_acceptance_result(bad),
                C.CORE_ACCEPTANCE_STALE_EVIDENCE)

    # 7. a partial commit recorded as accepted.
    bad = copy.deepcopy(_run())
    bad["judged_operation"]["delta_outcome"] = D.DELTA_PARTIAL_COMMIT
    expect_code("partial commit recorded as accepted",
                EV.validate_acceptance_result(bad), C.CORE_DELTA_PARTIAL_COMMIT)

    # 8. a soft preference claiming it can block acceptance.
    soft = _non_load_bearing_ids()[0]
    bad = copy.deepcopy(_run())
    _finding_of(bad, soft)["acceptance_load_bearing"] = True
    expect_code("soft preference claiming load-bearing status",
                EV.validate_acceptance_result(bad),
                C.CORE_CONSTRAINT_CLASS_AUTHORITY_VIOLATION)

    # 9. a finding whose verdict its own evidence contradicts.
    bad = copy.deepcopy(_run())
    _finding_of(bad, target)["evaluation"] = tri.VIOLATED
    expect_code("verdict contradicts the cited evidence",
                EV.validate_acceptance_result(bad), invalid)

    # 10. a judged result with the schema version of something else.
    bad = copy.deepcopy(_run())
    bad["schema_version"] = "wf.core.something_else.v1"
    expect_code("wrong schema version",
                EV.validate_acceptance_result(bad), invalid)


@test
def test_finding_known_bads():
    invalid = C.CORE_ACCEPTANCE_INVALID
    result = _run()
    judged = result["judged_operation"]
    target = _load_bearing_ids()[0]

    # 1. not an object.
    expect_code("finding is not an object",
                EV.validate_acceptance_finding("nope", judged=judged), invalid)

    # 2. a SATISFIED finding resting on an in-memory row.
    bad = copy.deepcopy(_finding_of(result, target))
    bad["evidence"][0]["observation_kind"] = EV.OBS_IN_MEMORY
    bad["evidence"][0]["reload_backed"] = False
    bad["evidence"][0]["usable"] = False
    expect_code("satisfied on an in-memory observation",
                EV.validate_acceptance_finding(bad, judged=judged),
                C.CORE_ACCEPTANCE_NOT_RELOADED)

    # 3. a blocked load-bearing finding that states no blocking reason.
    bad = copy.deepcopy(_finding_of(result, target))
    bad["evaluation"] = tri.UNKNOWN
    bad["evidence"] = []
    bad["blocking_reason"] = None
    expect_code("blocked finding with no reason",
                EV.validate_acceptance_finding(bad, judged=judged), invalid)

    # 4. an unknown constraint class.
    bad = copy.deepcopy(_finding_of(result, target))
    bad["constraint_class"] = "a_class_nobody_declared"
    expect_code("unknown constraint class",
                EV.validate_acceptance_finding(bad, judged=judged),
                C.CORE_CONSTRAINT_UNKNOWN_CLASS)


@test
def test_evidence_known_bads():
    invalid = C.CORE_ACCEPTANCE_INVALID
    judged = _run()["judged_operation"]

    # 1. not an object.
    expect_code("evidence is not an object",
                EV.validate_acceptance_evidence(42, judged=judged), invalid)

    # 2. an unknown observation kind.
    expect_code("unknown observation kind",
                EV.validate_acceptance_evidence(
                    EV._example_evidence(observation_kind="looked_at_it"),
                    judged=judged), invalid)

    # 3. a two-valued 'supports'.
    expect_code("boolean supports",
                EV.validate_acceptance_evidence(
                    EV._example_evidence(supports=True), judged=judged), invalid)

    # 4. no ordinal at all.
    expect_code("no observed_at ordinal",
                EV.validate_acceptance_evidence(
                    EV._example_evidence(observed_at=None), judged=judged),
                C.CORE_ACCEPTANCE_STALE_EVIDENCE)

    # 5. reload_backed signed over a kind that denies it.
    expect_code("reload flag over an in-memory kind",
                EV.validate_acceptance_evidence(
                    EV._example_evidence(observation_kind=EV.OBS_DECLARED,
                                         reload_backed=True), judged=judged),
                C.CORE_ACCEPTANCE_NOT_RELOADED)


# --------------------------------------------------------------------------- #
# class authority
# --------------------------------------------------------------------------- #
@test
def test_reload_backed_kinds_are_a_strict_subset_of_observation_kinds():
    """Widening the reload-backed set is a semantic change to every judgement."""
    extra = sorted(set(EV.RELOAD_BACKED_KINDS) - set(EV.OBSERVATION_KINDS))
    expect_eq("every reload-backed kind is a declared observation kind", extra, [])
    expect("the in-memory kind is never reload-backed",
           EV.OBS_IN_MEMORY not in EV.RELOAD_BACKED_KINDS,
           "OBS_IN_MEMORY is in RELOAD_BACKED_KINDS")
    expect("a declared-without-observation kind is never reload-backed",
           EV.OBS_DECLARED not in EV.RELOAD_BACKED_KINDS,
           "OBS_DECLARED is in RELOAD_BACKED_KINDS")


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #
def main():
    for fn in _RAN:
        try:
            fn()
        except Exception as exc:  # a crashing test is a failing test
            _FAILURES.append("{}: raised {}: {}".format(
                fn.__name__, type(exc).__name__, exc))
    print("wfcore.acceptance.test_acceptance: ran {} tests".format(len(_RAN)))
    if _FAILURES:
        print("FAILED ({} problem(s)):".format(len(_FAILURES)))
        for f in _FAILURES:
            print("  - {}".format(f))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
