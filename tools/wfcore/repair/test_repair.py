#!/usr/bin/env python3
"""wfcore.repair.test_repair -- negative-first suite for the repair loop.

Run from ``tools/``::

    PYTHONUTF8=1 python -m wfcore.repair.test_repair

WHAT THIS SUITE IS FOR
----------------------
A loop that terminates on its own happy path proves nothing: any loop that stops
looks correct once. What proves it is the set of ways it REFUSES to go round
again, and refusing them FOR THE RIGHT CODE.

The engine is a scripted fixture, not a mock of the editor: each "stage" states
which criteria the next observation will support, so every expected blocker set
is RE-DERIVED FROM THE STAGE by hand, never by calling the loop's own helpers.
The real ``planning.synth`` synthesiser and a real provider registry drive the
happy path, so the generic-planning rail is checked against a plan that genuinely
came through provider selection rather than against a stub of one.

Five tests are load-bearing beyond ordinary coverage and are named as such:

  * ``test_swapping_one_blocker_for_another_is_not_convergence`` -- the count is
    unchanged, every attempt commits a delta, and a count-based loop runs forever.
  * ``test_attempts_are_bounded_by_the_consumers_policy``
  * ``test_a_plan_that_did_not_come_from_the_synthesiser_is_refused``
  * ``test_repairing_a_failure_nothing_observed_is_refused``
  * ``test_an_unknown_blocker_is_measured_and_a_violated_one_is_mutated``

``test_harness_negative_control`` feeds the failure-path assertions a CLEAN
record and proves they register a failure.
"""

import copy
import sys

from .. import constraints as K
from .. import tri
from ..acceptance import evaluate as EV
from ..contracts import revision_policy as RP
from ..failure import FailureCode as C
from ..planning import plan as P
from ..planning import synth as SY
from ..providers import base as B
from ..providers import registry as REG
from ..providers import selection as S
from ..transaction import delta as D
from . import loop as L

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
    got = (record or {}).get("failure_codes") or []
    if code not in got:
        _FAILURES.append("{}: expected record to carry {}, codes were {}".format(
            label, code, got))


def test(fn):
    _RAN.append(fn)
    return fn


# --------------------------------------------------------------------------- #
# provider fixtures -- domain-neutral: engine/tooling vocabulary only
# --------------------------------------------------------------------------- #
AUTHORING_PROVIDER = B._example_provider_declaration(
    provider_id="editor_authoring_bridge",
    capabilities=[B.CAP_EDITOR_AUTHORING],
    requirements=[],
    outputs=["authored_asset_set", "operation_manifest"],
    evidence=["operation_manifest", "raw_observation_log"],
    cost_profile={"wall_seconds": 30.0},
)

OBSERVATION_PROVIDER = B._example_provider_declaration(
    provider_id="scene_observation_bridge",
    capabilities=[B.CAP_SCENE_OBSERVATION],
    requirements=[],
    side_effects=[B._example_side_effect(
        effect_id="eff_observation_log",
        effect_kind=B.EFFECT_EVIDENCE_ONLY,
        scope="evidence.observation_log",
        reversible=True,
        detail="emits a measurement record and changes nothing in the world")],
    determinism=B.DET_ENV_DEPENDENT,
    rollback=B.ROLLBACK_NONE,
    outputs=["observation_set", "operation_manifest"],
    evidence=["raw_observation_log", "operation_manifest"],
    cost_profile={"wall_seconds": 5.0},
)
del OBSERVATION_PROVIDER["determinism_evidence"]


def _registry():
    reg = REG.CapabilityRegistry()
    for decl in (AUTHORING_PROVIDER, OBSERVATION_PROVIDER):
        checks = reg.register(decl)
        bad = _failing(checks)
        if bad:
            _FAILURES.append("fixture {} failed registration: {}".format(
                decl.get("provider_id"), [(n, c) for (n, _d, c) in bad][:4]))
    return reg


def _policy(max_attempts=3):
    return RP._example_revision_policy(
        consumer_id="consumer_placeholder",
        rollback={"rollback_required": True,
                  "rollback_granularity": "per_transaction",
                  "max_revision_attempts": max_attempts})


# --------------------------------------------------------------------------- #
# the scripted engine
#
# A STAGE says what the next observation will support, per criterion. MISSING
# means "no row at all", which is how a criterion becomes UNKNOWN. Expected
# blocker sets are read off these dicts by hand in every test.
# --------------------------------------------------------------------------- #
MISSING = "__no_row_at_all__"

CRITERIA = EV._example_criteria()
CLASS_OF = {c["constraint_id"]: c["constraint_class"]
            for c in CRITERIA["constraints"]}
LOAD_BEARING = [c["constraint_id"] for c in CRITERIA["constraints"]
                if K.is_acceptance_load_bearing(c)]
LB_A, LB_B = LOAD_BEARING[0], LOAD_BEARING[1]


def _rows_from(stage, operation_id, observed_at):
    rows = []
    for idx, c in enumerate(CRITERIA["constraints"]):
        cid = c["constraint_id"]
        supports = stage.get(cid, tri.SATISFIED)
        if supports == MISSING:
            continue
        rows.append(EV._example_evidence(
            evidence_id="ev_{}_{:02d}".format(operation_id, idx),
            constraint_id=cid, operation_id=operation_id,
            observed_at=observed_at, supports=supports))
    return rows


def _acceptance_at(stage, index):
    op = "op_{:02d}".format(index)
    applied_at = 100 + index * 10
    delta = EV._example_delta(delta_id="delta_{:02d}".format(index),
                              operation_id=op)
    return EV.evaluate_acceptance(CRITERIA, delta,
                                  _rows_from(stage, op, applied_at + 1),
                                  applied_at)


class Engine(object):
    """apply_fn / observe_fn, scripted by stage. Records what it was handed."""

    def __init__(self, stages):
        self.stages = list(stages)
        self.plans = []
        self.observed = []

    def apply(self, plan, attempt_index):
        self.plans.append(plan)
        index = attempt_index + 1
        delta = EV._example_delta(delta_id="delta_{:02d}".format(index),
                                  operation_id="op_{:02d}".format(index))
        return delta, 100 + index * 10

    def observe(self, delta, attempt_index):
        index = min(attempt_index + 1, len(self.stages) - 1)
        self.observed.append(index)
        return _rows_from(self.stages[index], delta["operation_id"],
                          100 + (attempt_index + 1) * 10 + 1)


def _analysis_from(acceptance, attempt_index):
    """A synth-shaped analysis: one finding per OBSERVED blocker, no more.

    Deliberately derived from the acceptance record's own blockers, because that
    is what the driver's evidence rail demands -- an analysis that invents a
    finding is one of the known-bads below, not the normal case.
    """
    findings = []
    for i, b in enumerate(acceptance.get("blockers") or []):
        cid = b["constraint_id"]
        klass = CLASS_OF.get(cid)
        if b["evaluation"] == tri.VIOLATED:
            findings.append(SY._example_finding(
                constraint_id=cid,
                constraint_class=klass,
                subject="placeholder.measurable_{}".format(i),
                observation_key="placeholder.measurable_{}_holds".format(i),
                expected_changed_packages=[
                    "content_root/placeholder_package_{}".format(i)],
                expected_changed_actors=[
                    "content_root/placeholder_package_{}.placeholder_entity_0"
                    .format(i)]))
        else:
            findings.append(SY._example_unknown_finding(
                constraint_id=cid,
                constraint_class=klass,
                subject="placeholder.unmeasured_{}".format(i),
                measurement_key="placeholder.unmeasured_{}_measured".format(i)))
    return SY._example_analysis(
        analysis_id="analysis_{:02d}".format(attempt_index), findings=findings)


def _synth_fn(registry, policy):
    def run(analysis, attempt_index):
        return SY.synthesize_plan(analysis, registry, policy)
    return run


def _run(stages, max_attempts=3, reconcile_fn=None, synth_fn=None,
         initial=None, loop_id="repair_loop_test"):
    policy = _policy(max_attempts)
    engine = Engine(stages)
    acceptance = _acceptance_at(stages[0], 0) if initial is None else initial
    result = L.repair_loop(
        CRITERIA, policy, acceptance,
        reconcile_fn=reconcile_fn or _analysis_from,
        synth_fn=synth_fn or _synth_fn(_registry(), policy),
        apply_fn=engine.apply, observe_fn=engine.observe, loop_id=loop_id)
    return result, engine


# --------------------------------------------------------------------------- #
# harness negative control
# --------------------------------------------------------------------------- #
@test
def test_harness_negative_control():
    """Feed the failure-path assertions a CLEAN record; they must object."""
    global _FAILURES
    saved = _FAILURES
    try:
        _FAILURES = []
        clean = [("a_check_that_passed", True, "nothing wrong here", None)]
        expect_code("negative control", clean, C.CORE_REPAIR_INVALID)
        expect("negative control", False, "a false condition must be recorded")
        expect_eq("negative control", "got", "want")
        expect_pass("negative control",
                    [("a_check_that_failed", False, "detail",
                      C.CORE_REPAIR_INVALID)])
        expect_code_absent("negative control",
                           [("a_check_that_failed", False, "detail",
                             C.CORE_REPAIR_INVALID)], C.CORE_REPAIR_INVALID)
        expect_record_code("negative control", {"failure_codes": []},
                           C.CORE_REPAIR_INVALID)
        registered = len(_FAILURES)
    finally:
        _FAILURES = saved
    expect_eq("harness registers every failure-path assertion", registered, 6)


@test
def test_fixture_criteria_carry_two_load_bearing_criteria():
    """Every convergence test below depends on there being at least two."""
    expect("the fixture criteria carry >=2 load-bearing members",
           len(LOAD_BEARING) >= 2,
           "load-bearing members were {}".format(LOAD_BEARING))
    expect("and at least one non-load-bearing member",
           len(CRITERIA["constraints"]) > len(LOAD_BEARING),
           "every criterion was load-bearing")


# --------------------------------------------------------------------------- #
# the convergence definition, in isolation
# --------------------------------------------------------------------------- #
@test
def test_convergence_is_a_strict_subset_never_a_count():
    expect_eq("A -> {} converges", L.is_converging(["a"], []), True)
    expect_eq("{A,B} -> {A} converges", L.is_converging(["a", "b"], ["a"]), True)
    expect_eq("A -> B does NOT converge (the count is unchanged)",
              L.is_converging(["a"], ["b"]), False)
    expect_eq("A -> A does NOT converge", L.is_converging(["a"], ["a"]), False)
    expect_eq("A -> {A,B} does NOT converge",
              L.is_converging(["a"], ["a", "b"]), False)
    expect_eq("{} -> {} does NOT converge (nothing was reduced)",
              L.is_converging([], []), False)
    expect_eq("the swap is named", L.blocker_delta(["a"], ["b"]),
              (["a"], ["b"]))


# --------------------------------------------------------------------------- #
# the happy path, through the REAL synthesiser
# --------------------------------------------------------------------------- #
@test
def test_loop_reaches_acceptance_through_the_generic_planner():
    stages = [{LB_A: MISSING}, {}]
    # re-derived from the stages by hand: LB_A has no row at stage 0, so it is
    # the only blocker; stage 1 gives every criterion a satisfying row.
    expect_eq("stage 0 withholds exactly one load-bearing observation",
              [k for k, v in stages[0].items() if v == MISSING], [LB_A])

    result, engine = _run(stages)
    expect_eq("outcome accepted", result["outcome"], L.REPAIR_ACCEPTED)
    expect_eq("accepted", result["accepted"], True)
    expect_eq("one attempt was needed", result["attempts_used"], 1)
    expect_eq("it started from the observed blocker",
              result["initial_blockers"], [LB_A])
    expect_eq("and ended with none", result["final_blockers"], [])
    expect_eq("the attempt is recorded as converging",
              result["attempts"][0]["converging"], True)
    expect_eq("and names what it removed", result["attempts"][0]["removed"],
              [LB_A])
    expect_eq("no failure codes", result["failure_codes"], [])
    expect_pass("the accepted loop record is well formed",
                L.validate_repair_result(result, strict=True))

    # the plan really did come from the generic synthesiser
    plan = engine.plans[0]
    expect_eq("the plan carries the planning lane's schema identity",
              plan["schema_version"], P.RT_PLAN)
    expect("every step carries a provider selection result",
           all(s["selection"]["schema_version"] == S.RT_SELECTION_RESULT
               for s in plan["steps"]),
           "selections were {}".format([s.get("selection", {}).get(
               "schema_version") for s in plan["steps"]]))


@test
def test_an_unknown_blocker_is_measured_and_a_violated_one_is_mutated():
    """Backwards, the loop authors changes nobody established were needed."""
    stages = [{LB_A: MISSING, LB_B: tri.VIOLATED}, {}]
    result, engine = _run(stages)
    expect_eq("both blockers were addressed in one attempt",
              result["attempts_used"], 1)

    kinds = result["attempts"][0]["step_kinds"]
    expect_eq("the unmeasured criterion gets an OBSERVATION step",
              kinds[LB_A], SY.STEP_KIND_OBSERVATION)
    expect_eq("the measured violation gets a REVISION step",
              kinds[LB_B], SY.STEP_KIND_REVISION)

    steps = {s["step_id"]: s for s in engine.plans[0]["steps"]}
    observe_step = [s for s in steps.values()
                    if s["step_id"].startswith("step_observe_")][0]
    revise_step = [s for s in steps.values()
                   if s["step_id"].startswith("step_revise_")][0]
    expect_eq("the observation step declares an EMPTY mutation bound",
              (observe_step["expected_changed_packages"]
               + observe_step["expected_changed_actors"]), [])
    expect("the observation step declares it mutates nothing",
           observe_step["allowed_side_effects"] == [B.EFFECT_EVIDENCE_ONLY],
           "side effects were {}".format(observe_step["allowed_side_effects"]))
    expect("the revision step declares a non-empty bound",
           bool(revise_step["expected_changed_packages"]
                + revise_step["expected_changed_actors"]),
           "bound was empty")


@test
def test_an_observation_step_carrying_a_mutation_bound_is_refused():
    """The direction, forced backwards on a plan that is otherwise legitimate."""
    stages = [{LB_A: MISSING}, {}]
    registry = _registry()
    policy = _policy(3)
    honest = _synth_fn(registry, policy)

    def backwards(analysis, attempt_index):
        synthesis = copy.deepcopy(honest(analysis, attempt_index))
        for step in synthesis["plan"]["steps"]:
            if step["step_id"].startswith("step_observe_"):
                step["expected_changed_packages"] = [
                    "content_root/placeholder_package_x"]
        return synthesis

    result, engine = _run(stages, synth_fn=backwards)
    expect_eq("the loop refuses", result["outcome"], L.REPAIR_REFUSED)
    expect_record_code("unknown routed to a mutation", result,
                       C.CORE_REPAIR_WITHOUT_EVIDENCE)
    expect_eq("and nothing was applied", engine.plans, [])


# --------------------------------------------------------------------------- #
# THE convergence rail (WF1270)
# --------------------------------------------------------------------------- #
@test
def test_swapping_one_blocker_for_another_is_not_convergence():
    """A -> B. One blocker before, one after, a committed delta in between.

    A count-based loop reports "still 1 blocker, working on it" forever. The set
    comparison catches it on the first attempt.
    """
    stages = [{LB_A: tri.VIOLATED}, {LB_B: tri.VIOLATED}]
    # re-derived from the stages by hand.
    expect_eq("stage 0 blocks on exactly one criterion",
              sorted(k for k in stages[0]), [LB_A])
    expect_eq("stage 1 blocks on a DIFFERENT one",
              sorted(k for k in stages[1]), [LB_B])

    result, engine = _run(stages)
    attempt = result["attempts"][0]
    expect_eq("the blocker count did not move",
              len(attempt["blockers_before"]), len(attempt["blockers_after"]))
    expect_eq("but the sets are unrelated", attempt["blockers_before"], [LB_A])
    expect_eq("", attempt["blockers_after"], [LB_B])
    expect_eq("so the attempt is not converging", attempt["converging"], False)
    expect_eq("it names what it traded",
              (attempt["removed"], attempt["added"]), ([LB_A], [LB_B]))
    expect_eq("the loop stops", result["outcome"], L.REPAIR_NOT_CONVERGING)
    expect_record_code("swapped blockers", result, C.CORE_REPAIR_NOT_CONVERGING)
    expect_eq("it did not spend the whole attempt budget",
              result["attempts_used"], 1)
    expect_eq("and it did not report acceptance", result["accepted"], False)
    expect_pass("the non-converging loop record is well formed",
                L.validate_repair_result(result, strict=True))


@test
def test_an_attempt_that_changes_nothing_is_not_convergence():
    stages = [{LB_A: tri.VIOLATED}, {LB_A: tri.VIOLATED}]
    result, _engine = _run(stages)
    expect_eq("the blocker set is identical",
              result["attempts"][0]["blockers_before"],
              result["attempts"][0]["blockers_after"])
    expect_eq("which is not progress", result["outcome"],
              L.REPAIR_NOT_CONVERGING)
    expect_record_code("no movement", result, C.CORE_REPAIR_NOT_CONVERGING)


@test
def test_an_attempt_that_adds_a_blocker_is_not_convergence():
    stages = [{LB_A: tri.VIOLATED}, {LB_A: tri.VIOLATED, LB_B: tri.VIOLATED}]
    result, _engine = _run(stages)
    expect_eq("the loop stops", result["outcome"], L.REPAIR_NOT_CONVERGING)
    expect_eq("and names the blocker it introduced",
              result["attempts"][0]["added"], [LB_B])


# --------------------------------------------------------------------------- #
# THE bound (WF1269)
# --------------------------------------------------------------------------- #
@test
def test_attempts_are_bounded_by_the_consumers_policy():
    """Converging every attempt, and still stopped by the consumer's number."""
    stages = [{LB_A: tri.VIOLATED, LB_B: tri.VIOLATED}, {LB_B: tri.VIOLATED}]
    result, engine = _run(stages, max_attempts=1)

    expect_eq("the bound is the consumer's number", result["max_attempts"], 1)
    expect_eq("exactly one attempt ran", result["attempts_used"], 1)
    expect_eq("and it DID converge", result["attempts"][0]["converging"], True)
    expect_eq("the loop still stops", result["outcome"], L.REPAIR_EXHAUSTED)
    expect_record_code("exhausted", result, C.CORE_REPAIR_ATTEMPTS_EXHAUSTED)
    expect_eq("a blocker survives", result["final_blockers"], [LB_B])
    expect_eq("and acceptance is not reported", result["accepted"], False)
    expect_eq("the engine was driven exactly once", len(engine.plans), 1)
    expect_pass("the exhausted loop record is well formed",
                L.validate_repair_result(result, strict=True))


@test
def test_a_policy_with_no_usable_bound_is_refused():
    policy = _policy(3)
    policy["rollback"]["max_revision_attempts"] = 0
    engine = Engine([{LB_A: tri.VIOLATED}, {}])
    result = L.repair_loop(
        CRITERIA, policy, _acceptance_at({LB_A: tri.VIOLATED}, 0),
        reconcile_fn=_analysis_from, synth_fn=_synth_fn(_registry(), policy),
        apply_fn=engine.apply, observe_fn=engine.observe)
    expect_eq("the loop refuses", result["outcome"], L.REPAIR_REFUSED)
    expect_record_code("no usable bound", result, C.CORE_REPAIR_INVALID)
    expect_eq("nothing was applied", engine.plans, [])
    expect_eq("max_attempts_of reports None", L.max_attempts_of(policy), None)


# --------------------------------------------------------------------------- #
# THE generic-planning rail (WF1267)
# --------------------------------------------------------------------------- #
@test
def test_a_plan_that_did_not_come_from_the_synthesiser_is_refused():
    """A bespoke fix path is untested, unbounded and unrollbackable."""
    stages = [{LB_A: tri.VIOLATED}, {}]

    def bespoke(analysis, attempt_index):
        # Shaped exactly like a synthesis result, minus the one thing only the
        # synthesiser can stamp.
        return {
            "synthesis_id": "synth_bespoke",
            "outcome": SY.OUTCOME_PLANNED,
            "plan": P._example_plan(),
            "failure_codes": [],
        }

    result, engine = _run(stages, synth_fn=bespoke)
    expect_eq("the loop refuses", result["outcome"], L.REPAIR_BYPASSED_PLANNING)
    expect_record_code("bespoke plan", result, C.CORE_REPAIR_BYPASSED_PLANNING)
    expect_eq("and nothing was applied", engine.plans, [])
    expect_pass("the refusal record is well formed",
                L.validate_repair_result(result, strict=True))


@test
def test_planning_provenance_known_bads():
    registry = _registry()
    policy = _policy(3)
    honest = _synth_fn(registry, policy)(
        _analysis_from(_acceptance_at({LB_A: tri.VIOLATED}, 0), 0), 0)
    ok, detail = L.planning_provenance(honest)
    expect("the honest synthesis passes provenance", ok, detail)

    cases = [
        ("not an object", "a plan, honest"),
        ("no synthesis schema version",
         dict(honest, schema_version="wf.core.something_else.v1")),
        ("unknown synthesis outcome", dict(honest, outcome="fixed_it")),
        ("plan with the wrong schema version",
         dict(honest, plan=dict(honest["plan"],
                                schema_version="wf.core.something_else.v1"))),
        ("a planned synthesis with no steps",
         dict(honest, plan=dict(honest["plan"], steps=[]))),
        ("a step whose provider was named rather than selected",
         dict(honest, plan=dict(honest["plan"], steps=[
             {k: v for k, v in honest["plan"]["steps"][0].items()
              if k != "selection"}]))),
    ]
    for label, bad in cases:
        ok, _detail = L.planning_provenance(bad)
        expect_eq("provenance rejects: {}".format(label), ok, False)


# --------------------------------------------------------------------------- #
# THE evidence rail (WF1268)
# --------------------------------------------------------------------------- #
@test
def test_repairing_a_failure_nothing_observed_is_refused():
    """The analysis invents a finding for a criterion nothing recorded blocking."""
    stages = [{LB_A: tri.VIOLATED}, {}]

    def invents(acceptance, attempt_index):
        analysis = _analysis_from(acceptance, attempt_index)
        analysis["findings"].append(SY._example_finding(
            constraint_id="c_a_criterion_nobody_judged",
            subject="placeholder.measurable_invented",
            observation_key="placeholder.measurable_invented_holds"))
        return analysis

    result, engine = _run(stages, reconcile_fn=invents)
    expect_eq("the loop refuses", result["outcome"], L.REPAIR_WITHOUT_EVIDENCE)
    expect_record_code("invented finding", result,
                       C.CORE_REPAIR_WITHOUT_EVIDENCE)
    expect_eq("and nothing was applied", engine.plans, [])
    expect_pass("the refusal record is well formed",
                L.validate_repair_result(result, strict=True))


@test
def test_calling_an_unmeasured_criterion_violated_is_refused():
    """A mutation authored for something nobody established was wrong."""
    stages = [{LB_A: MISSING}, {}]
    acceptance = _acceptance_at(stages[0], 0)
    expect_eq("the judgement measured it as UNKNOWN, not violated",
              [b["evaluation"] for b in acceptance["blockers"]], [tri.UNKNOWN])

    def overclaims(acc, attempt_index):
        return SY._example_analysis(
            analysis_id="analysis_overclaim",
            findings=[SY._example_finding(
                constraint_id=LB_A, constraint_class=CLASS_OF[LB_A],
                subject="placeholder.measurable_0",
                observation_key="placeholder.measurable_0_holds")])

    result, engine = _run(stages, reconcile_fn=overclaims)
    expect_eq("the loop refuses", result["outcome"], L.REPAIR_WITHOUT_EVIDENCE)
    expect_record_code("violated over an unknown", result,
                       C.CORE_REPAIR_WITHOUT_EVIDENCE)
    expect_eq("and nothing was applied", engine.plans, [])


@test
def test_calling_a_measured_violation_unknown_stalls_a_due_repair():
    """The mirror of the above: a different failure, so a different code."""
    stages = [{LB_A: tri.VIOLATED}, {}]

    def understates(acc, attempt_index):
        return SY._example_analysis(
            analysis_id="analysis_understate",
            findings=[SY._example_unknown_finding(
                constraint_id=LB_A, constraint_class=CLASS_OF[LB_A],
                subject="placeholder.unmeasured_0",
                measurement_key="placeholder.unmeasured_0_measured")])

    result, _engine = _run(stages, reconcile_fn=understates)
    expect_eq("the loop refuses", result["outcome"], L.REPAIR_WITHOUT_EVIDENCE)
    expect_record_code("measured violation routed to a measurement", result,
                       C.CORE_REPAIR_INVALID)


@test
def test_repair_on_an_unjudged_acceptance_is_refused():
    """A partial commit was never judged, so nothing observed a failure."""
    partial = EV._example_acceptance_result(
        delta=EV._example_delta(outcome=D.DELTA_PARTIAL_COMMIT))
    expect_eq("the judgement refused", partial["judged"], False)
    expect_eq("and it names no blockers", partial["blockers"], [])

    result, engine = _run([{}], initial=partial)
    expect_eq("the loop refuses", result["outcome"], L.REPAIR_WITHOUT_EVIDENCE)
    expect_record_code("unjudged acceptance", result,
                       C.CORE_REPAIR_WITHOUT_EVIDENCE)
    expect_eq("nothing was applied", engine.plans, [])

    # And the other shape: a record that names blockers while admitting it never
    # judged anything.
    forged = copy.deepcopy(_acceptance_at({LB_A: tri.VIOLATED}, 0))
    forged["judged"] = False
    forged["refusal_reason"] = "a judgement that did not happen"
    result, engine = _run([{}], initial=forged)
    expect_eq("the loop refuses that too", result["outcome"],
              L.REPAIR_WITHOUT_EVIDENCE)
    expect_record_code("blockers over an unjudged result", result,
                       C.CORE_REPAIR_WITHOUT_EVIDENCE)
    expect_eq("nothing was applied", engine.plans, [])


@test
def test_an_unplannable_repair_stops_rather_than_going_round_again():
    stages = [{LB_A: tri.VIOLATED}, {}]
    policy = _policy(3)
    # No provider can author anything, so the violated finding cannot be planned.
    reg = REG.CapabilityRegistry()
    reg.register(OBSERVATION_PROVIDER)
    engine = Engine(stages)
    result = L.repair_loop(
        CRITERIA, policy, _acceptance_at(stages[0], 0),
        reconcile_fn=_analysis_from, synth_fn=_synth_fn(reg, policy),
        apply_fn=engine.apply, observe_fn=engine.observe)
    expect_eq("the loop stops", result["outcome"], L.REPAIR_UNPLANNABLE)
    expect_eq("nothing was applied", engine.plans, [])
    expect("the refusal says why", bool(result["refusal_reason"]),
           "refusal_reason was empty")


# --------------------------------------------------------------------------- #
# validate_repair_attempt / validate_repair_result: known-bads
# --------------------------------------------------------------------------- #
@test
def test_attempt_known_bads():
    invalid = C.CORE_REPAIR_INVALID
    result, _engine = _run([{LB_A: MISSING}, {}])
    good = result["attempts"][0]
    expect_pass("attempt canonical", L.validate_repair_attempt(good, strict=True))

    # 1. not an object.
    expect_code("attempt is not an object",
                L.validate_repair_attempt(["nope"]), invalid)

    # 2. an attempt calling a swap 'converging'.
    bad = copy.deepcopy(good)
    bad["blockers_before"] = ["a"]
    bad["blockers_after"] = ["b"]
    bad["removed"] = ["a"]
    bad["added"] = ["b"]
    bad["converging"] = True
    expect_code("a swap recorded as convergence",
                L.validate_repair_attempt(bad), C.CORE_REPAIR_NOT_CONVERGING)

    # 3. a non-converging attempt that raises no WF1270.
    bad = copy.deepcopy(good)
    bad["blockers_before"] = ["a"]
    bad["blockers_after"] = ["a"]
    bad["removed"] = []
    bad["added"] = []
    bad["converging"] = False
    bad["failure_codes"] = []
    expect_code("silent non-converging attempt",
                L.validate_repair_attempt(bad), C.CORE_REPAIR_NOT_CONVERGING)

    # 4. removed/added that disagree with the sets.
    bad = copy.deepcopy(good)
    bad["removed"] = []
    expect_code("removed disagrees with the sets",
                L.validate_repair_attempt(bad), invalid)

    # 5. a step kind outside the vocabulary.
    bad = copy.deepcopy(good)
    bad["step_kinds"] = {"c_x": "just_fix_it"}
    expect_code("unknown step kind", L.validate_repair_attempt(bad), invalid)


@test
def test_result_known_bads():
    invalid = C.CORE_REPAIR_INVALID
    accepted, _e = _run([{LB_A: MISSING}, {}])

    # 1. not an object.
    expect_code("result is not an object",
                L.validate_repair_result("nope"), invalid)

    # 2. more attempts than the consumer's bound.
    bad = copy.deepcopy(accepted)
    bad["max_attempts"] = 0
    expect_code("attempts beyond the bound", L.validate_repair_result(bad),
                C.CORE_REPAIR_ATTEMPTS_EXHAUSTED)

    # 3. an unresolved outcome claiming acceptance.
    bad = copy.deepcopy(accepted)
    bad["outcome"] = L.REPAIR_NOT_CONVERGING
    bad["accepted"] = True
    expect_code("unresolved outcome reporting acceptance",
                L.validate_repair_result(bad), C.CORE_ACCEPTANCE_ON_UNKNOWN)

    # 4. an accepted outcome with blockers still standing.
    bad = copy.deepcopy(accepted)
    bad["final_blockers"] = [LB_A]
    expect_code("accepted over surviving blockers",
                L.validate_repair_result(bad), C.CORE_ACCEPTANCE_ON_UNKNOWN)

    # 5. attempts_used that disagrees with the attempt list.
    bad = copy.deepcopy(accepted)
    bad["attempts_used"] = 7
    expect_code("attempts_used disagrees with attempts",
                L.validate_repair_result(bad), invalid)

    # 6. a not-converging outcome that raises no WF1270.
    bad = copy.deepcopy(accepted)
    bad["outcome"] = L.REPAIR_NOT_CONVERGING
    bad["accepted"] = False
    bad["refusal_reason"] = "it stopped"
    bad["failure_codes"] = []
    expect_code("silent not-converging loop", L.validate_repair_result(bad),
                C.CORE_REPAIR_NOT_CONVERGING)

    # 7. a chain gap: the first attempt does not start from initial_blockers.
    bad = copy.deepcopy(accepted)
    bad["initial_blockers"] = ["c_something_else"]
    expect_code("chain gap at the start", L.validate_repair_result(bad), invalid)

    # 8. an unresolved outcome with no reason.
    bad = copy.deepcopy(accepted)
    bad["outcome"] = L.REPAIR_EXHAUSTED
    bad["accepted"] = False
    bad["refusal_reason"] = None
    bad["failure_codes"] = [C.CORE_REPAIR_ATTEMPTS_EXHAUSTED]
    expect_code("unexplained stop", L.validate_repair_result(bad), invalid)


@test
def test_chain_continuity_is_checked_between_attempts():
    """Two attempts, then a forged gap between them."""
    stages = [{LB_A: tri.VIOLATED, LB_B: tri.VIOLATED},
              {LB_B: tri.VIOLATED}, {}]
    result, _engine = _run(stages, max_attempts=3)
    expect_eq("two attempts ran", result["attempts_used"], 2)
    expect_eq("and it ended accepted", result["outcome"], L.REPAIR_ACCEPTED)
    expect_pass("the two-attempt record is well formed",
                L.validate_repair_result(result, strict=True))

    bad = copy.deepcopy(result)
    bad["attempts"][1]["blockers_before"] = ["c_a_state_no_attempt_produced"]
    bad["attempts"][1]["removed"], bad["attempts"][1]["added"] = L.blocker_delta(
        bad["attempts"][1]["blockers_before"], bad["attempts"][1]["blockers_after"])
    bad["attempts"][1]["converging"] = L.is_converging(
        bad["attempts"][1]["blockers_before"], bad["attempts"][1]["blockers_after"])
    expect_code("a gap in the chain", L.validate_repair_result(bad),
                C.CORE_REPAIR_INVALID)


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
    print("wfcore.repair.test_repair: ran {} tests".format(len(_RAN)))
    if _FAILURES:
        print("FAILED ({} problem(s)):".format(len(_FAILURES)))
        for f in _FAILURES:
            print("  - {}".format(f))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
