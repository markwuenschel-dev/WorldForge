#!/usr/bin/env python3
"""wfcore.analysis.test_reconcile -- negative-first suite for constraint analysis.

Run from ``tools/``::

    PYTHONUTF8=1 python -m wfcore.analysis.test_reconcile

WHAT THIS SUITE IS FOR
----------------------
A reconciler that agrees with its own canonical example proves nothing -- the
example was built by the reconciler. What proves it is the set of KNOWN-BADS it
refuses, and refusing them FOR THE RIGHT CODE.

Every expected verdict here is RE-DERIVED FROM THE RAW OBSERVED RECORDS -- the
literal ``value``/``provenance``/``collection_ok`` keys of the observed fields --
never by calling the analyser's own evaluation helpers. A test that computes its
expectation with the function under test asserts only that the function is
deterministic.

Five tests are load-bearing beyond ordinary coverage and are named as such:

  * ``test_mismatched_world_identity_refuses_to_reconcile`` -- and the refusal's
    acceptance verdict is UNKNOWN, never the SATISFIED that folding zero findings
    would return for free.
  * ``test_unbacked_observed_field_is_unknown_not_satisfied`` -- an unbacked
    field carrying a value that WOULD satisfy the constraint must still be
    UNKNOWN.
  * ``test_soft_preference_never_changes_the_acceptance_verdict``
  * ``test_budget_over_its_limit_raises_wf1215``
  * ``test_changed_protected_identity_raises_wf1213``

``test_harness_negative_control`` feeds the failure-path assertions a CLEAN
record and proves they register a failure. Without it, a harness whose expect_*
functions silently pass everything would report a green suite over nothing.
"""

import copy
import sys

from .. import constraints as K
from .. import tri
from ..failure import FailureCode as C
from ..models import desired_world as DW
from ..models import observed_world as OW
from . import reconcile as R

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


def test(fn):
    _RAN.append(fn)
    return fn


# --------------------------------------------------------------------------- #
# fixtures -- raw, so expectations can be re-derived from them by hand
# --------------------------------------------------------------------------- #
def _desired():
    return DW._example_desired_world()


def _observed(**patch):
    d = R._example_observed_world()
    d.update(patch)
    return d


def _finding_of(analysis, constraint_id):
    for f in analysis["findings"]:
        if f["constraint_id"] == constraint_id:
            return f
    return None


def _raw_observed_field(observed, section, entity_id, attr):
    """The literal field record, read straight out of the document."""
    return observed[section][OW.ENTITIES_KEY][entity_id][attr]


def _run(**over):
    return R._example_constraint_analysis(**over)


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
        expect_code("negative control", clean, C.CORE_CONSTRAINT_INVALID)
        expect("negative control", False, "a false condition must be recorded")
        expect_eq("negative control", "got", "want")
        expect_pass("negative control",
                    [("a_check_that_failed", False, "detail",
                      C.CORE_CONSTRAINT_INVALID)])
        expect_code_absent("negative control",
                           [("a_check_that_failed", False, "detail",
                             C.CORE_CONSTRAINT_INVALID)],
                           C.CORE_CONSTRAINT_INVALID)
        registered = len(_FAILURES)
    finally:
        _FAILURES = saved
    expect_eq("harness registers every failure-path assertion", registered, 5)


# --------------------------------------------------------------------------- #
# canonical
# --------------------------------------------------------------------------- #
@test
def test_constraint_analysis_example_is_valid():
    expect_pass("analysis canonical",
                R.validate_constraint_analysis(_run(), strict=True))


@test
def test_constraint_finding_examples_are_valid():
    for f in _run()["findings"]:
        expect_pass("finding canonical {}".format(f["constraint_id"]),
                    R.validate_constraint_finding(f, strict=True))


@test
def test_canonical_analysis_covers_all_three_verdicts():
    """A canonical example in which everything happened to be measurable would
    teach the wrong lesson -- that a fully-decided analysis is the normal case."""
    a = _run()
    for key in ("satisfied", "violated", "unknown", "not_a_predicate"):
        expect("canonical analysis has a non-empty {!r} set".format(key),
               bool(a[key]), "{} was empty".format(key))


# --------------------------------------------------------------------------- #
# THE refusal: two models, two different worlds
# --------------------------------------------------------------------------- #
@test
def test_mismatched_world_identity_refuses_to_reconcile():
    """Differencing unrelated worlds yields a plausible, meaningless plan.

    The refusal's acceptance verdict is asserted explicitly: ``tri.conj`` of zero
    findings is SATISFIED, so a refusal that does not write UNKNOWN out by hand
    reads downstream as an acceptance nobody computed.
    """
    other = _observed(world_identity=OW.measured(
        {"world_id": "world_0002", "request_id": "request_0001", "revision": 1},
        "operation_bind", "world_binder", ("record#bind",),
        detail="identity read back out of a different bound world",
        stage=OW.STAGE_WORLD_BOUND))

    # re-derived by hand from the two documents, not from same_world()
    expect_eq("the two identities really do differ",
              _desired()["world_id"] == other["world_identity"]["value"]["world_id"],
              False)

    a = _run(observed=other)
    expect_eq("refuses to reconcile", a["reconciled"], False)
    expect_eq("emits no findings", a["findings"], [])
    expect_eq("acceptance verdict is UNKNOWN, not vacuous SATISFIED",
              a["acceptance_verdict"], tri.UNKNOWN)
    expect("refusal carries WF1222",
           C.CORE_MODEL_IDENTITY_MISMATCH in a["failure_codes"],
           "failure_codes were {}".format(a["failure_codes"]))
    expect_pass("refusal record is well formed",
                R.validate_constraint_analysis(a, strict=True))


@test
def test_unestablished_observed_identity_refuses_as_unbacked_not_mismatch():
    """An unmeasured identity is a different fact from a mismatched one."""
    other = _observed(world_identity=OW.not_observed(
        "the world was never bound, so no identity was read back out of it"))
    a = _run(observed=other)
    expect_eq("refuses to reconcile", a["reconciled"], False)
    expect_eq("same_world is UNKNOWN", a["same_world"], tri.UNKNOWN)
    expect("refusal carries WF1218",
           C.CORE_OBSERVED_WORLD_UNBACKED in a["failure_codes"],
           "failure_codes were {}".format(a["failure_codes"]))
    expect("an unmeasured identity is not reported as a mismatch",
           C.CORE_MODEL_IDENTITY_MISMATCH not in a["failure_codes"],
           "WF1222 was emitted for an identity nobody measured")


# --------------------------------------------------------------------------- #
# THE evidence rail
# --------------------------------------------------------------------------- #
@test
def test_unbacked_observed_field_is_unknown_not_satisfied():
    """An unbacked field carrying a SATISFYING value must still be UNKNOWN.

    The field below states ``value=True`` -- exactly what the constraint wants --
    with ``provenance=not_observed``. If backing is not consulted before the
    value is read, this is the shape that reads as green.
    """
    observed = _observed()
    forged = dict(OW.not_observed("nobody looked, but a value was written here"))
    forged["value"] = True
    observed["spatial_relations"][OW.ENTITIES_KEY]["relation_1"]["holds"] = forged

    # re-derived from the raw record: backed-ness is provenance + collection_ok.
    raw = _raw_observed_field(observed, "spatial_relations", "relation_1", "holds")
    expect("the fixture really is unbacked",
           raw["provenance"] in OW.UNBACKED_PROVENANCE
           and raw["collection_ok"] is not True,
           "fixture provenance={!r} collection_ok={!r}".format(
               raw["provenance"], raw["collection_ok"]))
    expect_eq("the fixture really does carry a satisfying value",
              raw["value"], True)

    a = _run(observed=observed)
    f = _finding_of(a, "c_relation_1_holds")
    expect_eq("unbacked field yields UNKNOWN", f["evaluation"], tri.UNKNOWN)
    expect("it is not reported as satisfied",
           "c_relation_1_holds" not in a["satisfied"],
           "satisfied set was {}".format(a["satisfied"]))
    expect("it is not coerced to violated either",
           "c_relation_1_holds" not in a["violated"],
           "violated set was {}".format(a["violated"]))
    expect("the finding names the unbacked field",
           C.CORE_OBSERVED_WORLD_UNBACKED in f["failure_codes"],
           "codes were {}".format(f["failure_codes"]))
    expect_eq("remedy is to go measure", f["remedy"], R.REMEDY_MEASURE)


@test
def test_unevaluable_constraint_raises_wf1202_and_is_never_coerced():
    """No binding, no measurement -> UNKNOWN + WF1202. Never violated."""
    a = _run(bindings={})
    f = _finding_of(a, "c_relation_2_holds")
    expect_eq("an unbound constraint is UNKNOWN", f["evaluation"], tri.UNKNOWN)
    expect("it raises WF1202",
           C.CORE_CONSTRAINT_NOT_EVALUATED in f["failure_codes"],
           "codes were {}".format(f["failure_codes"]))
    expect_eq("remedy is MEASURE, not CHANGE_THE_WORLD", f["remedy"],
              R.REMEDY_MEASURE)
    expect_eq("nothing was coerced to violated", a["violated"], [])
    expect_eq("acceptance blocks on the unknown", a["acceptance_verdict"],
              tri.UNKNOWN)


@test
def test_declared_unknown_is_evaluated_not_unmeasured():
    """DECLARED_UNKNOWN evaluates to UNKNOWN by construction; WF1202 would lie."""
    f = _finding_of(_run(), "c_undecided_density")
    expect_eq("evaluates UNKNOWN", f["evaluation"], tri.UNKNOWN)
    expect_eq("remedy routes to the consumer, not to a measurement",
              f["remedy"], R.REMEDY_DECIDE)
    expect("no WF1202 for a constraint that WAS evaluated",
           C.CORE_CONSTRAINT_NOT_EVALUATED not in f["failure_codes"],
           "codes were {}".format(f["failure_codes"]))


# --------------------------------------------------------------------------- #
# THE budget raise site (WF1215)
# --------------------------------------------------------------------------- #
@test
def test_budget_over_its_limit_raises_wf1215():
    limit = [c for c in R._example_constraint_set()
             if c["constraint_id"] == "c_generation_budget"][0]["limit"]
    over = OW.measured(limit + 300, "operation_state_read", "state_reader",
                       ("record#state",),
                       detail="elapsed cost of the generation pass")
    # re-derived by hand from the raw measurement and the declared ceiling.
    expect("the fixture really does exceed the ceiling", over["value"] > limit,
           "measured {} against limit {}".format(over["value"], limit))

    a = _run(measurements={"c_generation_budget": over})
    f = _finding_of(a, "c_generation_budget")
    expect_eq("an exceeded budget is VIOLATED", f["evaluation"], tri.VIOLATED)
    expect("raises WF1215", C.CORE_BUDGET_EXCEEDED in f["failure_codes"],
           "codes were {}".format(f["failure_codes"]))
    expect_eq("remedy is to change the world", f["remedy"],
              R.REMEDY_CHANGE_THE_WORLD)
    expect_eq("comparison names the ceiling", f["comparison"]["desired_value"],
              limit)
    expect_pass("over-budget analysis is well formed",
                R.validate_constraint_analysis(a, strict=True))


@test
def test_budget_tolerance_widens_the_ceiling_but_only_numerically():
    """A tolerance parameterises the budget's comparison; it is never a verdict."""
    limit = 900
    constraints = [
        {"constraint_id": "c_budget", "constraint_class": K.BUDGET,
         "subject": "generation.elapsed", "detail": "within the ceiling",
         "limit": limit, "unit": "seconds"},
        {"constraint_id": "c_budget_slack", "constraint_class": K.TOLERANCE,
         "subject": "generation.elapsed", "detail": "slack on the ceiling",
         "applies_to": "c_budget", "limit": 100, "unit": "seconds"},
    ]
    measured = OW.measured(950, "operation_state_read", "state_reader",
                           ("record#state",), detail="elapsed cost")
    a = _run(constraints=constraints, bindings={},
             measurements={"c_budget": measured})
    expect_eq("950 is inside 900+100", _finding_of(a, "c_budget")["evaluation"],
              tri.SATISFIED)
    tol = _finding_of(a, "c_budget_slack")
    expect_eq("the tolerance itself carries no verdict", tol["evaluation"], None)
    expect_eq("the budget records the slack it applied",
              _finding_of(a, "c_budget")["comparison"]["tolerance"], 100)


@test
def test_unbacked_budget_measurement_is_unknown_not_within_budget():
    """A measurement whose operation the observed model never declared is not one.

    The record below is shaped exactly like a measurement and would compare well
    inside the ceiling if its value were read.
    """
    forged = OW.measured(10, "operation_that_was_never_declared", "a_collector",
                         ("record#state",), detail="a cost nobody measured")
    a = _run(measurements={"c_generation_budget": forged})
    f = _finding_of(a, "c_generation_budget")
    expect_eq("a measurement from an undeclared operation is UNKNOWN",
              f["evaluation"], tri.UNKNOWN)
    expect("it raises the unbacked code",
           C.CORE_OBSERVED_WORLD_UNBACKED in f["failure_codes"],
           "codes were {}".format(f["failure_codes"]))
    expect("and it never claims to be within budget",
           C.CORE_BUDGET_EXCEEDED not in f["failure_codes"],
           "codes were {}".format(f["failure_codes"]))


# --------------------------------------------------------------------------- #
# THE protected-content raise site (WF1213)
# --------------------------------------------------------------------------- #
@test
def test_changed_protected_identity_raises_wf1213():
    observed = _observed()
    observed["semantic_landmarks"][OW.ENTITIES_KEY]["landmark_a"][
        R.PROTECTED_CHANGE_ATTR] = OW.measured(
            True, "operation_enumerate", "entity_enumerator",
            ("record#enumeration",),
            detail="the identity was observed to differ from its prior state")

    # re-derived from the raw record.
    raw = _raw_observed_field(observed, "semantic_landmarks", "landmark_a",
                              R.PROTECTED_CHANGE_ATTR)
    expect("the fixture is a backed observation of a change",
           raw["value"] is True and raw["provenance"] in OW.BACKED_PROVENANCE
           and raw["collection_ok"] is True,
           "fixture record was {!r}".format(raw))

    a = _run(observed=observed)
    f = _finding_of(a, "c_protect_landmark")
    expect_eq("a touched protected identity is VIOLATED", f["evaluation"],
              tri.VIOLATED)
    expect("raises WF1213",
           C.CORE_PROTECTED_CONTENT_TOUCHED in f["failure_codes"],
           "codes were {}".format(f["failure_codes"]))
    expect_eq("the record names which identity changed",
              f["comparison"]["observed_value"], ["landmark_a"])
    expect_eq("remedy is to change the world", f["remedy"],
              R.REMEDY_CHANGE_THE_WORLD)
    expect_pass("touched-protection analysis is well formed",
                R.validate_constraint_analysis(a, strict=True))


@test
def test_unobserved_protected_identity_is_unknown_not_protected():
    """Reporting the identities we looked at as protected would publish
    protection over content nobody checked."""
    observed = _observed()
    del observed["semantic_landmarks"][OW.ENTITIES_KEY]["landmark_a"][
        R.PROTECTED_CHANGE_ATTR]
    f = _finding_of(_run(observed=observed), "c_protect_landmark")
    expect_eq("an unobserved protected identity is UNKNOWN", f["evaluation"],
              tri.UNKNOWN)
    expect("it is not reported as touched",
           C.CORE_PROTECTED_CONTENT_TOUCHED not in f["failure_codes"],
           "codes were {}".format(f["failure_codes"]))
    expect("it raises WF1202 instead",
           C.CORE_CONSTRAINT_NOT_EVALUATED in f["failure_codes"],
           "codes were {}".format(f["failure_codes"]))


# --------------------------------------------------------------------------- #
# class authority
# --------------------------------------------------------------------------- #
@test
def test_soft_preference_never_changes_the_acceptance_verdict():
    """Three ways of moving a soft preference; the verdict must not move."""
    baseline = _run()
    base_verdict = baseline["acceptance_verdict"]
    base_blockers = sorted(b["constraint_id"] for b in baseline["blockers"])

    # 1. flip the observation the preference reads, so it evaluates VIOLATED.
    observed = _observed()
    observed["environmental_state"][OW.ENTITIES_KEY]["state_visibility"][
        "state_value"] = OW.measured("obstructed", "operation_state_read",
                                     "state_reader", ("record#state",))
    flipped = _run(observed=observed)
    expect_eq("a violated soft preference IS reported",
              _finding_of(flipped, "c_visibility_preference")["evaluation"],
              tri.VIOLATED)
    expect_eq("but the verdict does not move",
              flipped["acceptance_verdict"], base_verdict)
    expect_eq("and it never becomes a blocker",
              sorted(b["constraint_id"] for b in flipped["blockers"]),
              base_blockers)

    # 2. remove it entirely.
    without = [c for c in R._example_constraint_set()
               if c["constraint_id"] != "c_visibility_preference"]
    expect_eq("removing it does not move the verdict",
              _run(constraints=without)["acceptance_verdict"], base_verdict)

    # 3. add ten more, all violated.
    many = list(R._example_constraint_set())
    bindings = dict(R._example_bindings())
    for i in range(10):
        cid = "c_extra_preference_{}".format(i)
        many.append({"constraint_id": cid,
                     "constraint_class": K.SOFT_PREFERENCE,
                     "subject": "environmental_state.state_visibility",
                     "detail": "another preference on the same observation",
                     "weight": 0.9})
        bindings[cid] = ("environmental_state.entities.state_visibility"
                         ".state_value")
    piled = _run(observed=observed, constraints=many, bindings=bindings)
    expect_eq("ten violated preferences do not move the verdict",
              piled["acceptance_verdict"], base_verdict)
    expect_eq("ten violated preferences add no blockers",
              sorted(b["constraint_id"] for b in piled["blockers"]),
              base_blockers)


@test
def test_non_predicate_classes_are_never_load_bearing():
    """Excluding them from the fold is only safe because of this.

    Asserted against ``constraints.ACCEPTANCE_LOAD_BEARING`` rather than assumed
    in ``reconcile``: if the taxonomy ever admits one of these classes to the
    acceptance set, the exclusion becomes a silent way to drop a real blocker.
    """
    overlap = sorted(set(R.NON_PREDICATE_CLASSES)
                     & set(K.ACCEPTANCE_LOAD_BEARING))
    expect_eq("no non-predicate class may block acceptance", overlap, [])


@test
def test_tolerance_is_never_evaluated_standalone():
    a = _run()
    f = _finding_of(a, "c_population_slack")
    expect_eq("a tolerance carries no verdict", f["evaluation"], None)
    expect_eq("a tolerance is not acceptance-load-bearing",
              f["acceptance_load_bearing"], False)
    expect("a tolerance is listed as a non-predicate",
           "c_population_slack" in a["not_a_predicate"],
           "not_a_predicate was {}".format(a["not_a_predicate"]))


@test
def test_dangling_tolerance_raises_wf1205():
    constraints = [
        {"constraint_id": "c_invariant", "constraint_class": K.HARD_INVARIANT,
         "subject": "spatial_relations.entities.relation_1.holds",
         "detail": "the first declared relation must hold"},
        {"constraint_id": "c_orphan_slack", "constraint_class": K.TOLERANCE,
         "subject": "spatial_relations.relation_1", "detail": "slack",
         "applies_to": "c_a_constraint_that_is_not_in_this_set", "limit": 1},
    ]
    f = _finding_of(_run(constraints=constraints, bindings={}),
                    "c_orphan_slack")
    expect("a tolerance targeting nothing raises WF1205",
           C.CORE_TOLERANCE_WITHOUT_TARGET in f["failure_codes"],
           "codes were {}".format(f["failure_codes"]))


@test
def test_prohibited_outcome_takes_its_desired_side_from_its_class():
    """PROHIBITED_OUTCOME expects False because that is what prohibited MEANS."""
    a = _run()
    f = _finding_of(a, "c_no_second_relation")
    expect_eq("the desired side is False", f["comparison"]["desired_value"],
              False)
    raw = _raw_observed_field(_observed(), "spatial_relations", "relation_2",
                              "holds")
    expect_eq("the observation really is False", raw["value"], False)
    expect_eq("so the prohibition holds", f["evaluation"], tri.SATISFIED)


@test
def test_subject_that_is_already_an_observed_path_needs_no_binding():
    constraints = [
        {"constraint_id": "c_direct", "constraint_class": K.HARD_INVARIANT,
         "subject": "spatial_relations.entities.relation_1.holds",
         "detail": "the first declared relation must hold"},
    ]
    f = _finding_of(_run(constraints=constraints, bindings={}), "c_direct")
    expect_eq("resolved without an explicit binding", f["evaluation"],
              tri.SATISFIED)


@test
def test_undeclared_desired_entity_is_unknown_not_a_default():
    """No stated intent means no verdict -- never a True that happens to pass."""
    desired = _desired()
    desired["spatial_relations"] = [
        r for r in desired["spatial_relations"]
        if r["relation_id"] != "relation_1"]
    f = _finding_of(_run(desired=desired), "c_relation_1_holds")
    expect_eq("an undeclared desired counterpart is UNKNOWN", f["evaluation"],
              tri.UNKNOWN)


# --------------------------------------------------------------------------- #
# validate_constraint_analysis: known-bads
# --------------------------------------------------------------------------- #
@test
def test_analysis_known_bads():
    invalid = C.CORE_CONSTRAINT_INVALID

    # 1. a SATISFIED finding whose cited evidence is not backed.
    bad = copy.deepcopy(_run())
    f = _finding_of(bad, "c_relation_1_holds")
    f["evidence"][0]["backed"] = False
    expect_code("satisfied on unbacked evidence",
                R.validate_constraint_analysis(bad),
                C.CORE_OBSERVED_WORLD_UNBACKED)

    # 2. an acceptance verdict the findings do not support.
    bad = copy.deepcopy(_run())
    bad["acceptance_verdict"] = tri.SATISFIED
    expect_code("forged acceptance verdict",
                R.validate_constraint_analysis(bad), invalid)

    # 3. a refusal recording an acceptance -- the vacuous-fold trap, written out.
    bad = copy.deepcopy(_run())
    bad["reconciled"] = False
    bad["findings"] = []
    bad["satisfied"] = bad["violated"] = bad["unknown"] = []
    bad["not_a_predicate"] = []
    bad["blockers"] = []
    bad["same_world"] = tri.VIOLATED
    bad["refusal_reason"] = "the two models describe different worlds"
    bad["acceptance_verdict"] = tri.SATISFIED
    expect_code("refusal recording an acceptance",
                R.validate_constraint_analysis(bad), invalid)

    # 4. reconciled anyway, across two different worlds.
    bad = copy.deepcopy(_run())
    bad["same_world"] = tri.VIOLATED
    expect_code("reconciled across different worlds",
                R.validate_constraint_analysis(bad),
                C.CORE_MODEL_IDENTITY_MISMATCH)

    # 5. a summary set that disagrees with the findings it summarises.
    bad = copy.deepcopy(_run())
    bad["satisfied"] = bad["satisfied"] + bad["violated"]
    bad["violated"] = []
    expect_code("summary disagrees with findings",
                R.validate_constraint_analysis(bad), invalid)

    # 6. a load-bearing blocker dropped from the blockers list.
    bad = copy.deepcopy(_run())
    bad["blockers"] = []
    expect_code("dropped blocker", R.validate_constraint_analysis(bad), invalid)


# --------------------------------------------------------------------------- #
# validate_constraint_finding: known-bads
# --------------------------------------------------------------------------- #
@test
def test_finding_known_bads():
    invalid = C.CORE_CONSTRAINT_INVALID
    authority = C.CORE_CONSTRAINT_CLASS_AUTHORITY_VIOLATION

    # 1. not an object at all.
    expect_code("finding is not an object",
                R.validate_constraint_finding(["not", "an", "object"]), invalid)

    # 2. a TOLERANCE handed a verdict -- authority it does not have.
    bad = copy.deepcopy(_finding_of(_run(), "c_population_slack"))
    bad["evaluation"] = tri.SATISFIED
    expect_code("tolerance evaluated standalone",
                R.validate_constraint_finding(bad), authority)

    # 3. a violation routed to MEASURE.
    bad = copy.deepcopy(_finding_of(_run(), "c_relation_2_holds"))
    bad["remedy"] = R.REMEDY_MEASURE
    expect_code("violation routed to measure",
                R.validate_constraint_finding(bad), invalid)

    # 4. an evidence row calling itself backed while naming an unbacked
    #    provenance.
    bad = copy.deepcopy(_finding_of(_run(), "c_population_count"))
    bad["evidence"][0]["backed"] = True
    expect_code("evidence row backed with unbacked provenance",
                R.validate_constraint_finding(bad),
                C.CORE_OBSERVED_WORLD_UNBACKED)

    # 5. a soft preference claiming it can block acceptance.
    bad = copy.deepcopy(_finding_of(_run(), "c_visibility_preference"))
    bad["acceptance_load_bearing"] = True
    expect_code("soft preference claiming load-bearing status",
                R.validate_constraint_finding(bad), authority)

    # 6. a DECLARED_UNKNOWN reported as never evaluated.
    bad = copy.deepcopy(_finding_of(_run(), "c_undecided_density"))
    bad["failure_codes"] = [C.CORE_CONSTRAINT_NOT_EVALUATED]
    expect_code("declared unknown reported as unmeasured",
                R.validate_constraint_finding(bad), authority)

    # 7. a verdict the finding's own comparison contradicts.
    bad = copy.deepcopy(_finding_of(_run(), "c_relation_2_holds"))
    bad["evaluation"] = tri.SATISFIED
    bad["remedy"] = R.REMEDY_NONE
    expect_code("verdict contradicts the recorded comparison",
                R.validate_constraint_finding(bad), invalid)

    # 8. an unmeasured load-bearing constraint that raises no WF1202.
    bad = copy.deepcopy(_finding_of(_run(), "c_population_count"))
    bad["failure_codes"] = []
    expect_code("silent unevaluated load-bearing constraint",
                R.validate_constraint_finding(bad),
                C.CORE_CONSTRAINT_NOT_EVALUATED)


@test
def test_unknown_class_is_unknown_not_violated():
    constraints = [
        {"constraint_id": "c_hard", "constraint_class": K.HARD_INVARIANT,
         "subject": "spatial_relations.entities.relation_1.holds",
         "detail": "the first declared relation must hold"},
        {"constraint_id": "c_strange", "constraint_class": "a_class_nobody_declared",
         "subject": "spatial_relations.entities.relation_1.holds",
         "detail": "a constraint whose class is outside the taxonomy"},
    ]
    a = _run(constraints=constraints, bindings={})
    f = _finding_of(a, "c_strange")
    expect_eq("an unknown class is UNKNOWN", f["evaluation"], tri.UNKNOWN)
    expect("it raises the unknown-class code",
           C.CORE_CONSTRAINT_UNKNOWN_CLASS in f["failure_codes"],
           "codes were {}".format(f["failure_codes"]))
    expect_eq("it is never coerced to violated", a["violated"], [])


# --------------------------------------------------------------------------- #
# hygiene: Core owns no consumer's vocabulary
# --------------------------------------------------------------------------- #
@test
def test_example_ids_are_domain_neutral():
    """Checked as an ALLOW-list over the id vocabulary, not a deny-list of known
    game words: a deny-list only catches the games somebody thought of."""
    import re
    allowed_token = re.compile(
        r"^(c|world|request|landmark|anchor|population|group|state|relation|"
        r"beat|connection|transition|experience|graph|env|operation|record|"
        r"observation|entry|objective|orientation|reference|ambient|agent|"
        r"point|illumination|visibility|generation|elapsed|budget|slack|count|"
        r"density|undecided|protect|holds|no|second|minimize|preference|"
        r"consumer|design|owner|members|seconds|high|low|unobstructed|"
        r"obstructed|derivation|enumeration|bind|read|relations|extra|"
        r"a|b|[0-9]+)$")

    found = []
    for c in R._example_constraint_set():
        found.append(c["constraint_id"])
        found.extend(str(p) for p in c.get("protected_ids") or [])
    for c in R._example_constraint_set():
        if c.get("resolution_owner"):
            found.append(c["resolution_owner"])

    offenders = sorted({
        ident for ident in found
        if any(not allowed_token.match(tok) for tok in ident.split("_"))})
    expect("example ids are domain-neutral", not offenders,
           "id(s) {} contain tokens outside the neutral vocabulary; a Core "
           "example naming a consumer's content has already chosen a subject "
           "nobody asked for".format(offenders))


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
    print("wfcore.analysis.test_reconcile: ran {} tests".format(len(_RAN)))
    if _FAILURES:
        print("FAILED ({} problem(s)):".format(len(_FAILURES)))
        for f in _FAILURES:
            print("  - {}".format(f))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
