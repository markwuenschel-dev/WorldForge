#!/usr/bin/env python3
"""wfcore.transaction.test_transaction -- the negative suite for the transaction lane.

Run:  cd tools && PYTHONUTF8=1 python -m wfcore.transaction.test_transaction

WHAT IS ACTUALLY BEING PROVED
-----------------------------
A validator accepting its own example proves almost nothing. What proves this
lane exists is a set of scenarios in which the world is genuinely damaged, or
genuinely lied to the executor, and the reported outcome is still the true one:

  * a declared target outside the step's bound is refused with the world UNTOUCHED
  * a provider that quietly writes an EXTRA package is caught, even though its
    own declared target was perfectly legal -- the bound is enforced against what
    happened, not against what was intended
  * a mid-plan failure rolls back every prior mutation, and RE-OBSERVATION of the
    whole world confirms it is byte-for-byte what it was before
  * an undo that REPORTS SUCCESS and restores nothing produces PARTIAL_COMMIT, and
    is never reported as rolled back or committed
  * a commit taken without post-observation is UNVERIFIED, never a plain success
  * the single-writer lock is held for the entire apply (probed from INSIDE the
    sink, on every mutation) and released afterwards even when the apply explodes

NEGATIVE CONTROLS
-----------------
Two scenarios are run twice, once with the fault and once without, so a passing
assertion cannot be an artefact of the harness always producing the same verdict:
the lying-undo scenario must produce ROLLED_BACK when the lie is removed, and the
stray-write scenario must COMMIT when the stray write is removed. The harness
itself is also self-tested -- ``check()`` must be able to record a failure, or
every "pass" below is meaningless.

Exits non-zero on any failure.
"""

import os
import shutil
import sys
import tempfile

from .. import tri
from ..failure import FailureCode as C
from ..providers import base as PB
from . import delta as D
from . import executor as E

import scene_survey_operation as OPS  # noqa: E402  (path prepared by ..failure)

FAILURES = []
PASSED = [0]


# --------------------------------------------------------------------------- #
# harness
# --------------------------------------------------------------------------- #
def check(name, condition, detail=""):
    if condition:
        PASSED[0] += 1
    else:
        FAILURES.append("{}: {}".format(name, detail or "assertion failed"))


def all_ok(checks):
    return all(ok for (_n, ok, _d, _c) in checks)


def failing(checks):
    return [(n, d, c) for (n, ok, d, c) in checks if not ok]


def codes_of(checks):
    return {c for (_n, ok, _d, c) in checks if not ok and c}


def expect_valid(label, checks):
    check(label, all_ok(checks),
          "canonical example must pass; failures: {}".format(
              [(n, c) for (n, _d, c) in failing(checks)][:6]))


def expect_rejected_for(label, checks, code):
    got = codes_of(checks)
    check(label, code in got,
          "expected rejection code {} but got {}".format(code, sorted(got) or "NO FAILURE"))


def expect_code(label, result, code):
    got = result.get("failure_codes") or []
    check(label, code in got,
          "expected {} in failure_codes, got {} (outcome={})".format(
              code, got, result.get("outcome")))


# --------------------------------------------------------------------------- #
# fixtures -- domain-neutral addresses; Core owns no consumer's vocabulary
# --------------------------------------------------------------------------- #
PKG_A = "/generated/region_alpha/surface"
PKG_B = "/generated/region_alpha/detail"
PKG_OUTSIDE = "/generated/region_beta/surface"
ACTOR_A = "/generated/region_alpha/surface.anchor_0"

STEP_ID = "step_author_surface"


def bound(**over):
    return D._example_mutation_bound(
        step_id=STEP_ID,
        allowed_packages=[PKG_A, PKG_B],
        allowed_actors=[ACTOR_A],
        **over)


def mutation(mutation_id, target_path, *, operation=D.OP_MODIFY,
             before_payload=None, after_payload=None, target_kind=D.TARGET_PACKAGE,
             **over):
    m = D._example_mutation(
        mutation_id=mutation_id,
        step_id=STEP_ID,
        target_kind=target_kind,
        target_path=target_path,
        operation=operation,
        before_state=(D.absent_state() if operation == D.OP_CREATE
                      else D.present_state(before_payload)),
        expected_after_state=(D.absent_state() if operation == D.OP_DELETE
                              else D.present_state(after_payload)),
        status=D.MUT_PLANNED,
        rollback_mode=PB.ROLLBACK_TRANSACTIONAL)
    m.update(over)
    return m


def initial_world():
    return {
        (D.TARGET_PACKAGE, PKG_A): {"revision": 1},
        (D.TARGET_PACKAGE, PKG_B): {"revision": 1},
        (D.TARGET_PACKAGE, PKG_OUTSIDE): {"revision": 7},
        (D.TARGET_ACTOR, ACTOR_A): {"transform": [0, 0, 0]},
    }


def two_step_mutations():
    return [
        mutation("mut_a", PKG_A, before_payload={"revision": 1}, after_payload={"revision": 2}),
        mutation("mut_b", PKG_B, before_payload={"revision": 1}, after_payload={"revision": 2}),
    ]


class Scratch(object):
    """A throwaway repo root, so the lock and the journal have somewhere real to live."""

    def __enter__(self):
        self.root = tempfile.mkdtemp(prefix="wfcore_txn_")
        return self.root

    def __exit__(self, *_exc):
        shutil.rmtree(self.root, ignore_errors=True)
        return False


def run(root, sink, mutations, bounds=None, **over):
    kwargs = dict(repo_root=root, operation_id="op_txn_test",
                  evidence_refs=["operation_manifest", "raw_observation_log"])
    kwargs.update(over)
    return E.apply_delta(sink, bounds if bounds is not None else [bound()],
                         mutations, **kwargs)


# --------------------------------------------------------------------------- #
# 0. the harness must be able to fail
# --------------------------------------------------------------------------- #
def test_harness_negative_control():
    saved_failures = list(FAILURES)
    saved_passed = PASSED[0]
    del FAILURES[:]
    PASSED[0] = 0

    check("deliberately_false", False, "this must be recorded")
    check("deliberately_true", True)
    recorded = list(FAILURES)
    observed_passed = PASSED[0]

    del FAILURES[:]
    FAILURES.extend(saved_failures)
    PASSED[0] = saved_passed

    check("harness.records_a_failure", len(recorded) == 1,
          "check() recorded {} failure(s); if it records none, every PASS below is "
          "meaningless".format(len(recorded)))
    check("harness.counts_a_pass", observed_passed == 1,
          "check() counted {} pass(es)".format(observed_passed))
    check("harness.expect_rejected_for_needs_a_code",
          C.CORE_DELTA_INVALID not in codes_of([("x", True, "", None)]),
          "codes_of must not report a code for a passing check")


# --------------------------------------------------------------------------- #
# 1. validators
# --------------------------------------------------------------------------- #
def test_record_validators():
    expect_valid("validator.bound_example", D.validate_mutation_bound(
        D._example_mutation_bound(), strict=True))
    expect_valid("validator.mutation_example", D.validate_mutation(
        D._example_mutation(), strict=True))
    expect_valid("validator.delta_example", D.validate_world_delta(
        D._example_world_delta(), strict=True))

    expect_rejected_for(
        "validator.unsigned_empty_bound_rejected",
        D.validate_mutation_bound(D._example_mutation_bound(
            allowed_packages=[], allowed_actors=[])),
        C.CORE_DELTA_INVALID)
    check("validator.signed_empty_bound_accepted",
          all_ok(D.validate_mutation_bound(D._example_mutation_bound(
              allowed_packages=[], allowed_actors=[], declares_no_mutation=True))),
          "a SIGNED empty bound is a real claim and must validate")

    expect_rejected_for(
        "validator.wildcard_bound_rejected",
        D.validate_mutation_bound(D._example_mutation_bound(
            allowed_packages=["/generated/*"])),
        C.CORE_DELTA_INVALID)

    expect_rejected_for(
        "validator.mutation_without_before_state_rejected",
        D.validate_mutation(D._example_mutation(before_state=None)),
        C.CORE_DELTA_INVALID)
    expect_rejected_for(
        "validator.applied_mutation_with_unmeasured_before_state_rejected",
        D.validate_mutation(D._example_mutation(
            status=D.MUT_APPLIED, before_state=D.unmeasured_state("nobody looked"))),
        C.CORE_DELTA_UNVERIFIED)
    expect_rejected_for(
        "validator.create_over_existing_content_rejected",
        D.validate_mutation(D._example_mutation(
            status=D.MUT_APPLIED, operation=D.OP_CREATE,
            before_state=D.present_state({"revision": 1}))),
        C.CORE_DELTA_INVALID)

    # coherence: a delta whose mutation escapes its bound must not validate
    escaped = D._example_world_delta()
    escaped["mutations"][0]["target_path"] = PKG_OUTSIDE
    expect_rejected_for("validator.delta_mutation_outside_bound_rejected",
                        D.validate_world_delta(escaped), C.CORE_DELTA_OUT_OF_BOUNDS)

    # coherence: an unrestored mutation cannot be reported as rolled back
    lying = D._example_world_delta(outcome=D.DELTA_ROLLED_BACK)
    lying["mutations"][0]["status"] = D.MUT_ROLLBACK_FAILED
    expect_rejected_for("validator.rolled_back_with_unrestored_mutation_rejected",
                        D.validate_world_delta(lying), C.CORE_DELTA_PARTIAL_COMMIT)

    # coherence: a committed delta with nothing measured must be UNVERIFIED
    unmeasured = D._example_world_delta()
    unmeasured["mutations"][0].pop("observed_after_apply")
    expect_rejected_for("validator.committed_without_measurement_rejected",
                        D.validate_world_delta(unmeasured), C.CORE_DELTA_UNVERIFIED)


# --------------------------------------------------------------------------- #
# 2. tri-valued state comparison never coerces unknown
# --------------------------------------------------------------------------- #
def test_state_comparison_is_three_valued():
    present = D.present_state({"revision": 1})
    other = D.present_state({"revision": 2})
    check("state.equal_is_satisfied",
          D.states_equal(present, D.present_state({"revision": 1})) == tri.SATISFIED)
    check("state.different_is_violated",
          D.states_equal(present, other) == tri.VIOLATED)
    check("state.absent_is_not_unmeasured",
          D.states_equal(D.absent_state(), D.unmeasured_state("x")) == tri.UNKNOWN,
          "an unmeasured target must never compare equal to a measured absence")
    check("state.unmeasured_vs_unmeasured_is_unknown",
          D.states_equal(D.unmeasured_state("a"), D.unmeasured_state("a")) == tri.UNKNOWN,
          "two failures to look are not an agreement")
    check("state.key_order_does_not_matter",
          D.states_equal(D.present_state({"a": 1, "b": 2}),
                         D.present_state({"b": 2, "a": 1})) == tri.SATISFIED)


# --------------------------------------------------------------------------- #
# 3. an out-of-bounds DECLARED target is refused, world untouched
# --------------------------------------------------------------------------- #
def test_out_of_bounds_is_refused():
    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world())
        before = sink.snapshot()
        result = run(root, sink,
                     [mutation("mut_escape", PKG_OUTSIDE,
                               before_payload={"revision": 7},
                               after_payload={"revision": 8})])
        check("out_of_bounds.outcome_is_refused",
              result["outcome"] == D.DELTA_REFUSED,
              "outcome={}".format(result["outcome"]))
        expect_code("out_of_bounds.code", result, C.CORE_DELTA_OUT_OF_BOUNDS)
        check("out_of_bounds.world_untouched", sink.snapshot() == before,
              "a refusal must leave the world byte-for-byte unchanged")
        check("out_of_bounds.sink_never_called", sink.apply_calls == [],
              "apply was called {} time(s) on a refused delta".format(len(sink.apply_calls)))
        check("out_of_bounds.not_committed_not_rolled_back",
              not D.is_committed(result["outcome"]) and not D.is_rolled_back(result["outcome"]))

        # protected content is refused even when it IS in the allowed list
        sink2 = E.InMemoryMutationSink(initial_world())
        protected_bound = bound(protected_paths=[PKG_A])
        result2 = run(root, sink2,
                      [mutation("mut_protected", PKG_A,
                                before_payload={"revision": 1},
                                after_payload={"revision": 2})],
                      bounds=[protected_bound], operation_id="op_txn_protected")
        expect_code("protected.code", result2, C.CORE_PROTECTED_CONTENT_TOUCHED)
        check("protected.world_untouched", sink2.snapshot() == before,
              "a protected address listed as expected must still be refused")


# --------------------------------------------------------------------------- #
# 4. THE BOUND IS ENFORCED AGAINST WHAT ACTUALLY HAPPENED
# --------------------------------------------------------------------------- #
def test_stray_write_is_caught_and_its_negative_control():
    # (a) the provider's declared target is legal, but it also writes elsewhere
    with Scratch() as root:
        sink = E.InMemoryMutationSink(
            initial_world(),
            stray_writes={"mut_a": [(D.TARGET_PACKAGE, PKG_OUTSIDE, {"revision": 99})]})
        result = run(root, sink, two_step_mutations())
        expect_code("stray.out_of_bounds_code", result, C.CORE_DELTA_OUT_OF_BOUNDS)
        check("stray.bound_enforcement_violated",
              result["bound_enforcement"] == tri.VIOLATED,
              "bound_enforcement={}".format(result["bound_enforcement"]))
        check("stray.declared_target_was_legal",
              all_ok(D.validate_mutation_bound(bound())) and PKG_A in bound()["allowed_packages"],
              "the fixture must be one a declared-target check would wave through")
        check("stray.outcome_is_partial_commit",
              result["outcome"] == D.DELTA_PARTIAL_COMMIT,
              "outcome={}; a write to an address with no captured restore point "
              "cannot be undone, so the transaction is neither committed nor "
              "rolled back".format(result["outcome"]))
        stray_records = [m for m in result["mutations"]
                         if m.get("status") == D.MUT_UNRECOVERABLE]
        check("stray.recorded_as_unrecoverable", len(stray_records) == 1,
              "expected exactly one unrecoverable stray record, got {}".format(
                  len(stray_records)))
        check("stray.no_fabricated_restore_point",
              stray_records and not D.is_measured(stray_records[0]["before_state"]),
              "a stray target's before-state must stay unmeasured, not be invented")
        check("stray.in_bound_mutation_was_restored",
              D.states_equal(sink.observe(D.TARGET_PACKAGE, PKG_A),
                             D.present_state({"revision": 1})) == tri.SATISFIED,
              "the legal mutation must still be rolled back")

    # (b) NEGATIVE CONTROL: same plan, no stray write -> a clean verified commit
    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world())
        result = run(root, sink, two_step_mutations())
        check("stray.control_commits",
              result["outcome"] == D.DELTA_COMMITTED,
              "without the stray write the same plan must commit; outcome={} codes={}"
              .format(result["outcome"], result["failure_codes"]))
        check("stray.control_bound_enforcement_satisfied",
              result["bound_enforcement"] == tri.SATISFIED)
        expect_valid("stray.control_delta_validates", D.validate_world_delta(result))


# --------------------------------------------------------------------------- #
# 5. a mid-plan failure rolls back everything, CONFIRMED by re-observation
# --------------------------------------------------------------------------- #
def test_midplan_failure_rolls_back_and_reobservation_confirms():
    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world(), fail_on_apply={"mut_c"})
        before = sink.snapshot()
        mutations = two_step_mutations() + [
            mutation("mut_c", ACTOR_A, target_kind=D.TARGET_ACTOR,
                     before_payload={"transform": [0, 0, 0]},
                     after_payload={"transform": [1, 0, 0]}),
        ]
        result = run(root, sink, mutations)

        check("rollback.outcome_is_rolled_back",
              result["outcome"] == D.DELTA_ROLLED_BACK,
              "outcome={} codes={} reason={}".format(
                  result["outcome"], result["failure_codes"], result["abort_reason"]))
        check("rollback.completeness_is_satisfied",
              result["rollback_completeness"] == tri.SATISFIED,
              "rollback_completeness={}".format(result["rollback_completeness"]))
        check("rollback.every_prior_mutation_was_undone",
              sorted(sink.undo_calls) == ["mut_a", "mut_b", "mut_c"],
              "undo_calls={}".format(sink.undo_calls))
        check("rollback.reverse_order",
              sink.undo_calls == ["mut_c", "mut_b", "mut_a"],
              "undo must run in reverse order, got {}".format(sink.undo_calls))
        check("rollback.world_is_byte_for_byte_restored", sink.snapshot() == before,
              "re-observation of the whole world must match the pre-transaction image")
        for m in result["mutations"]:
            if m.get("status") in (D.MUT_ROLLED_BACK,):
                check("rollback.{}.restoration_measured".format(m["mutation_id"]),
                      m.get("restoration") == tri.SATISFIED,
                      "restoration={}".format(m.get("restoration")))
        check("rollback.not_committed",
              not D.is_committed(result["outcome"]))
        expect_valid("rollback.delta_validates", D.validate_world_delta(result))


# --------------------------------------------------------------------------- #
# 6. AN UNDO THAT LIES -> PARTIAL_COMMIT, never "rolled back"
# --------------------------------------------------------------------------- #
def test_lying_undo_is_partial_commit_and_its_negative_control():
    # (a) undo reports success and restores nothing
    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world(),
                                      fail_on_apply={"mut_c"},
                                      undo_restores_nothing={"mut_a"})
        mutations = two_step_mutations() + [
            mutation("mut_c", ACTOR_A, target_kind=D.TARGET_ACTOR,
                     before_payload={"transform": [0, 0, 0]},
                     after_payload={"transform": [1, 0, 0]}),
        ]
        result = run(root, sink, mutations)

        check("lying_undo.outcome_is_partial_commit",
              result["outcome"] == D.DELTA_PARTIAL_COMMIT,
              "outcome={} codes={}".format(result["outcome"], result["failure_codes"]))
        expect_code("lying_undo.rollback_failed_code", result, C.CORE_DELTA_ROLLBACK_FAILED)
        expect_code("lying_undo.partial_commit_code", result, C.CORE_DELTA_PARTIAL_COMMIT)
        check("lying_undo.not_reported_as_rolled_back",
              not D.is_rolled_back(result["outcome"]),
              "a partial commit must never satisfy is_rolled_back")
        check("lying_undo.not_reported_as_committed",
              not D.is_committed(result["outcome"]),
              "a partial commit must never satisfy is_committed")
        check("lying_undo.not_reported_as_verified",
              not D.commit_is_verified(result["outcome"]))

        liar = [m for m in result["mutations"] if m["mutation_id"] == "mut_a"][0]
        check("lying_undo.undo_reported_success",
              liar.get("undo_reported_ok") is True,
              "the fixture must actually lie: undo_reported_ok={}".format(
                  liar.get("undo_reported_ok")))
        check("lying_undo.verdict_came_from_reobservation",
              liar.get("status") == D.MUT_ROLLBACK_FAILED
              and liar.get("restoration") == tri.VIOLATED,
              "status={} restoration={}; the verdict must come from re-observing the "
              "target, not from the undo's own report".format(
                  liar.get("status"), liar.get("restoration")))
        check("lying_undo.world_really_is_still_changed",
              D.states_equal(sink.observe(D.TARGET_PACKAGE, PKG_A),
                             D.present_state({"revision": 2})) == tri.SATISFIED,
              "the fixture must leave the world genuinely unrestored")

    # (b) NEGATIVE CONTROL: identical scenario, undo tells the truth -> ROLLED_BACK
    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world(), fail_on_apply={"mut_c"})
        before = sink.snapshot()
        mutations = two_step_mutations() + [
            mutation("mut_c", ACTOR_A, target_kind=D.TARGET_ACTOR,
                     before_payload={"transform": [0, 0, 0]},
                     after_payload={"transform": [1, 0, 0]}),
        ]
        result = run(root, sink, mutations)
        check("lying_undo.control_is_rolled_back",
              result["outcome"] == D.DELTA_ROLLED_BACK,
              "with the lie removed the SAME scenario must roll back cleanly; "
              "outcome={}".format(result["outcome"]))
        check("lying_undo.control_world_restored", sink.snapshot() == before)

    # (c) an UNOBSERVABLE target after undo is UNKNOWN, not a rollback failure
    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world(), fail_on_apply={"mut_b"})
        result = run(root, sink, two_step_mutations())
        # make PKG_A unobservable only for the post-undo re-observation
        check("lying_undo.setup_control_ran",
              result["outcome"] in D.DELTA_OUTCOMES,
              "outcome={}".format(result["outcome"]))

    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world(), fail_on_apply={"mut_b"})
        original_undo = sink.undo

        def undo_then_blind(m):
            original_undo(m)
            sink.unobservable.add((m.get("target_kind"),
                                   D.normalize_target_path(m.get("target_path"))))

        sink.undo = undo_then_blind
        result = run(root, sink, two_step_mutations())
        check("unobservable_rollback.outcome_is_partial_commit",
              result["outcome"] == D.DELTA_PARTIAL_COMMIT,
              "outcome={}".format(result["outcome"]))
        expect_code("unobservable_rollback.unverified_code", result, C.CORE_DELTA_UNVERIFIED)
        check("unobservable_rollback.not_reported_as_rollback_failure",
              C.CORE_DELTA_ROLLBACK_FAILED not in result["failure_codes"],
              "an unknown must not be reported as a measured rollback failure; "
              "codes={}".format(result["failure_codes"]))
        statuses = {m["mutation_id"]: m.get("status") for m in result["mutations"]}
        check("unobservable_rollback.status_is_unverified_not_failed",
              statuses.get("mut_a") == D.MUT_ROLLBACK_UNVERIFIED,
              "statuses={}".format(statuses))


# --------------------------------------------------------------------------- #
# 7. a commit with no post-observation is UNVERIFIED, not a success
# --------------------------------------------------------------------------- #
def test_commit_without_post_observation_is_unverified():
    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world())
        result = run(root, sink, two_step_mutations(), observe_after=False)

        check("unverified.outcome",
              result["outcome"] == D.DELTA_COMMITTED_UNVERIFIED,
              "outcome={}".format(result["outcome"]))
        expect_code("unverified.code", result, C.CORE_DELTA_UNVERIFIED)
        check("unverified.verification_is_unknown",
              result["verification"] == tri.UNKNOWN,
              "verification={}".format(result["verification"]))
        check("unverified.is_committed_true", D.is_committed(result["outcome"]),
              "the mutations ARE in the world; that part is true")
        check("unverified.commit_is_verified_false",
              not D.commit_is_verified(result["outcome"]),
              "an unverified commit must never satisfy commit_is_verified")
        check("unverified.mutations_really_applied",
              D.states_equal(sink.observe(D.TARGET_PACKAGE, PKG_A),
                             D.present_state({"revision": 2})) == tri.SATISFIED)

        # a mutation that declares NO postcondition can never be a verified commit
        sink2 = E.InMemoryMutationSink(initial_world())
        no_post = two_step_mutations()
        no_post[0].pop("expected_after_state")
        result2 = run(root, sink2, no_post, operation_id="op_txn_no_post")
        check("unverified.absent_postcondition_is_unknown",
              result2["outcome"] == D.DELTA_COMMITTED_UNVERIFIED,
              "outcome={}".format(result2["outcome"]))
        expect_code("unverified.absent_postcondition_code", result2, C.CORE_DELTA_UNVERIFIED)


# --------------------------------------------------------------------------- #
# 8. the lock is held for the WHOLE apply, and released afterwards
# --------------------------------------------------------------------------- #
def test_lock_is_held_across_the_whole_apply():
    with Scratch() as root:
        probes = []

        def probe(_m):
            # A SECOND writer tries to take the same lock from inside the apply.
            attempt = OPS.acquire_operation_lock(
                root, "op_txn_second_writer",
                lock_rel=E.CORE_TRANSACTION_LOCK_REL, attempts=1)
            probes.append((attempt.ok, attempt.code))
            if attempt.ok:  # must not happen; release so the test can continue
                OPS.release_operation_lock(attempt.value)

        sink = E.InMemoryMutationSink(initial_world(), on_apply=probe)
        result = run(root, sink, two_step_mutations())

        check("lock.probe_ran_for_every_mutation", len(probes) == 2,
              "probe ran {} time(s); it must run inside every apply".format(len(probes)))
        check("lock.second_writer_always_refused",
              probes and all(not ok for (ok, _c) in probes),
              "a second writer acquired the lock mid-apply: {}".format(probes))
        check("lock.refusal_is_the_concurrency_code",
              all(code == C.SCENE_SURVEY_CONCURRENT_OPERATION for (_ok, code) in probes),
              "probe codes={}".format(probes))
        check("lock.recorded_as_held", result["lock"]["held"] is True)
        check("lock.released_after", result["lock"]["released"] is True,
              "lock record={}".format(result["lock"]))

        after = OPS.acquire_operation_lock(root, "op_txn_after",
                                           lock_rel=E.CORE_TRANSACTION_LOCK_REL, attempts=1)
        check("lock.free_after_apply", after.ok,
              "the lock must be free once apply returns: {}: {}".format(
                  after.code, after.detail))
        if after.ok:
            OPS.release_operation_lock(after.value)

        # released even when the sink explodes with something the executor
        # does not model
        def detonate(_m):
            raise ZeroDivisionError("a sink defect the executor never anticipated")

        boom = E.InMemoryMutationSink(initial_world(), on_apply=detonate)
        raised = None
        try:
            run(root, boom, two_step_mutations(), operation_id="op_txn_boom")
        except ZeroDivisionError as exc:
            raised = exc
        check("lock.unexpected_exception_propagates", raised is not None,
              "an unmodelled sink defect must not be swallowed")
        recovered = OPS.acquire_operation_lock(root, "op_txn_recover",
                                               lock_rel=E.CORE_TRANSACTION_LOCK_REL,
                                               attempts=1)
        check("lock.released_even_on_unexpected_exception", recovered.ok,
              "the finally must release the lock: {}: {}".format(
                  recovered.code, recovered.detail))
        if recovered.ok:
            OPS.release_operation_lock(recovered.value)

        # and a delta that cannot take the lock is refused, not applied
        held = OPS.acquire_operation_lock(root, "op_txn_holder",
                                          lock_rel=E.CORE_TRANSACTION_LOCK_REL, attempts=1)
        check("lock.holder_acquired", held.ok, "{}".format(held.detail))
        if held.ok:
            blocked_sink = E.InMemoryMutationSink(initial_world())
            snapshot = blocked_sink.snapshot()
            blocked = run(root, blocked_sink, two_step_mutations(),
                          operation_id="op_txn_blocked")
            check("lock.contended_delta_is_refused",
                  blocked["outcome"] == D.DELTA_REFUSED,
                  "outcome={}".format(blocked["outcome"]))
            expect_code("lock.contended_code", blocked, C.CORE_TRANSACTION_NOT_ISOLATED)
            check("lock.contended_world_untouched",
                  blocked_sink.snapshot() == snapshot)
            OPS.release_operation_lock(held.value)


# --------------------------------------------------------------------------- #
# 9. unenforceable bound, unmeasurable restore point, isolation drift
# --------------------------------------------------------------------------- #
def test_unknown_is_never_spent_as_compliance():
    # (a) the sink cannot say what it touched -> UNVERIFIED, never "compliant"
    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world(), cannot_report_touched=True)
        before = sink.snapshot()
        result = run(root, sink, two_step_mutations())
        expect_code("unknown.unreportable_touches_code", result, C.CORE_DELTA_UNVERIFIED)
        check("unknown.unreportable_touches_not_out_of_bounds",
              C.CORE_DELTA_OUT_OF_BOUNDS not in result["failure_codes"],
              "an unenforceable bound must not be reported as a violation nobody "
              "observed; codes={}".format(result["failure_codes"]))
        check("unknown.unreportable_touches_not_committed",
              not D.is_committed(result["outcome"]),
              "outcome={}".format(result["outcome"]))
        check("unknown.unreportable_touches_rolled_back",
              sink.snapshot() == before,
              "the aborted mutation must be undone")

    # (b) an unmeasurable before-state means no restore point -> refuse to apply
    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world(),
                                      unobservable=[(D.TARGET_PACKAGE, PKG_A)])
        before = sink.snapshot()
        result = run(root, sink, two_step_mutations())
        expect_code("unknown.unmeasurable_before_state_code", result, C.CORE_DELTA_UNVERIFIED)
        check("unknown.unmeasurable_before_state_applied_nothing",
              sink.apply_calls == [],
              "apply_calls={}; a mutation with no restore point must not run".format(
                  sink.apply_calls))
        check("unknown.unmeasurable_before_state_world_untouched",
              sink.snapshot() == before)

    # (c) the world moved between planning and applying -> not isolated
    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world())
        before = sink.snapshot()
        drifted = two_step_mutations()
        drifted[0]["before_state"] = D.present_state({"revision": 41})
        result = run(root, sink, drifted)
        expect_code("isolation.drift_code", result, C.CORE_TRANSACTION_NOT_ISOLATED)
        check("isolation.drift_applied_nothing", sink.apply_calls == [],
              "apply_calls={}".format(sink.apply_calls))
        check("isolation.drift_world_untouched", sink.snapshot() == before)

    # (d) a provider that cannot roll back is refused before the lock is taken
    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world())
        before = sink.snapshot()
        no_undo = two_step_mutations()
        no_undo[1]["rollback_mode"] = PB.ROLLBACK_NONE
        result = run(root, sink, no_undo)
        expect_code("rollback_capability.code", result, C.CORE_PROVIDER_ROLLBACK_UNSUPPORTED)
        check("rollback_capability.outcome_is_refused",
              result["outcome"] == D.DELTA_REFUSED,
              "outcome={}".format(result["outcome"]))
        check("rollback_capability.world_untouched", sink.snapshot() == before)


# --------------------------------------------------------------------------- #
# 10. the delta is journalled atomically and re-validates from disk
# --------------------------------------------------------------------------- #
def test_delta_is_journalled():
    import json
    with Scratch() as root:
        sink = E.InMemoryMutationSink(initial_world())
        result = run(root, sink, two_step_mutations())
        path = result.get("journal_path")
        check("journal.path_recorded", bool(path), "journal_path={}".format(path))
        check("journal.file_exists", bool(path) and os.path.isfile(path))
        if path and os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                reloaded = json.load(fh)
            check("journal.outcome_round_trips",
                  reloaded.get("outcome") == result["outcome"])
            check("journal.records_lock_release",
                  reloaded.get("lock", {}).get("released") is True,
                  "the published record must state what really happened to the lock")
            expect_valid("journal.reloaded_delta_validates",
                         D.validate_world_delta(reloaded))


# --------------------------------------------------------------------------- #
def main():
    tests = [
        test_harness_negative_control,
        test_record_validators,
        test_state_comparison_is_three_valued,
        test_out_of_bounds_is_refused,
        test_stray_write_is_caught_and_its_negative_control,
        test_midplan_failure_rolls_back_and_reobservation_confirms,
        test_lying_undo_is_partial_commit_and_its_negative_control,
        test_commit_without_post_observation_is_unverified,
        test_lock_is_held_across_the_whole_apply,
        test_unknown_is_never_spent_as_compliance,
        test_delta_is_journalled,
    ]
    for fn in tests:
        try:
            fn()
        except Exception as exc:  # a crash is a failure, never a skip
            FAILURES.append("{} raised {}: {}".format(fn.__name__, type(exc).__name__, exc))
        print("  ran {}".format(fn.__name__))

    print("")
    print("wfcore.transaction: {} assertion(s) passed, {} failed".format(
        PASSED[0], len(FAILURES)))
    for f in FAILURES:
        print("  FAIL {}".format(f))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
