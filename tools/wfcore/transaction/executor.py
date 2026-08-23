#!/usr/bin/env python3
"""wfcore.transaction.executor -- apply a bounded delta, or leave nothing behind.

WHAT THIS MODULE IS RESPONSIBLE FOR
-----------------------------------
Turning a list of intended mutations into either (a) a commit whose postconditions
were measured, (b) a rollback whose restoration was measured, or (c) an honest
report that the world is in neither state. There is no fourth answer, and in
particular there is no answer that means "probably fine".

THE SEQUENCE, AND WHY EACH STEP IS WHERE IT IS
----------------------------------------------
    0. validate the bound records and the intended mutations       -> WF1246
       Shape first, because a malformed bound would otherwise be enforced, and an
       unenforceable bound authorises everything it fails to parse.

    1. preflight the DECLARED targets against their step's bound   -> WF1247/WF1213
       Cheap, and it means an obviously-illegal request is refused with the world
       untouched. This check can only ever catch honest mistakes -- see step 5.

    2. refuse mutations whose provider cannot undo them            -> WF1232
       Applying inside a transaction something whose provider declares
       rollback=none means the transaction has no rollback. Better to refuse than
       to discover it while unwinding.

    3. TAKE THE SINGLE-WRITER LOCK, BEFORE ANY MUTATION            -> WF1250
       ``acquire_operation_lock`` from tools/pipeline/scene_survey_operation.py --
       reused, never reimplemented. Released in a ``finally`` so a crash mid-apply
       does not leave the repository permanently unwritable. A lock we could not
       take is reported as a Core isolation failure, with the underlying refusal
       preserved verbatim in the detail.

    4. per mutation: OBSERVE the before-state, then apply
       The before-state is captured by observation, not taken from the request.
       The request's version is kept as ``before_state_declared`` and, when the two
       disagree, that is somebody else having changed the world underneath us
       -> WF1250. An unmeasurable before-state is refused -> WF1251: without a
       restore point, any undo is a claim.

    5. after each apply: check what the sink says was ACTUALLY touched -> WF1247
       This is the check the bound exists for. Step 1 compares a mutation's
       declared target to its own step's declared bound, which is circular and
       passes by construction. Only the sink knows what the provider really wrote,
       so only this check can catch a provider that quietly touches one more
       package. A sink that CANNOT report what it touched leaves the bound
       unenforceable -- that is reported as unverified (WF1251) and rolled back,
       never as an out-of-bounds violation nobody observed.

    6. post-observation -> commit, or unverified commit             -> WF1251
    7. on any abort: undo in REVERSE ORDER, then RE-OBSERVE each target
       and compare it to the captured before-state                  -> WF1248/WF1249

WHY THE UNDO'S RETURN VALUE IS RECORDED AND THEN IGNORED
---------------------------------------------------------
``undo()`` reporting success is the undo's opinion of itself, produced by the same
code whose correctness is in question. The status of every rolled-back mutation is
computed from ``states_equal(before_state, observed_after_rollback)`` and from
nothing else; ``undo_reported_ok`` is stored for diagnosis and is never read by
``delta.rollback_completeness``. The in-memory sink can be told to lie -- report
success and restore nothing -- and the suite proves that lie produces
PARTIAL_COMMIT rather than a rollback.

NO ENGINE IMPORT, EVER
----------------------
All world contact is behind ``MutationSink``. This module imports no engine
module and must not acquire one: a transaction rail that can only run with a live
editor open is a rail that stops being run, and then stops being true.
"""

import datetime
import re
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import tri
from ..failure import FailureCode as C  # ALSO puts tools/pipeline on sys.path
from ..providers import base as PB
from . import delta as D

# The single-writer lock and the atomic publish come from the operation module,
# which already solved both problems (steal-by-rename for stale locks, nonce-
# checked release, same-directory temp + fsync + os.replace). Importing it is the
# whole point: a second implementation of either would be a second, subtly
# different set of guarantees.
import scene_survey_operation as OPS  # noqa: E402  (import order is load-bearing)

RT_TRANSACTION_RESULT = D.RT_WORLD_DELTA

# Core's own lock address. NOT the operation module's default: two different
# operations sharing one lock file would serialise unrelated work, and worse,
# would let either one break the other's lock as "stale".
CORE_TRANSACTION_LOCK_REL = "procedural/reports/core/transaction/.core_transaction.lock"
CORE_TRANSACTION_JOURNAL_DIR = "procedural/reports/core/transaction"
DEFAULT_LOCK_TTL_SECONDS = 3600

Check = Tuple[str, bool, str, Optional[str]]


class MutationSinkError(RuntimeError):
    """Raised by a sink when an apply or an undo could not be performed.

    A raised error means "this did not complete". It does NOT mean "nothing
    happened" -- a half-applied mutation raises too, which is why the executor
    adds a failed apply to the rollback list rather than skipping it.
    """


# --------------------------------------------------------------------------- #
# the narrow interface everything world-facing goes through
# --------------------------------------------------------------------------- #
class MutationSink:
    """Four methods. Everything the executor knows about the world is here.

    ``observe(target_kind, target_path) -> state record``
        A ``delta`` state record: present / absent / UNMEASURED. Returning
        ``unmeasured_state(reason)`` is the correct answer when the sink cannot
        look; fabricating ``absent_state()`` instead would make an undone create
        indistinguishable from an unchecked one.

    ``apply(mutation) -> None``
        Perform the mutation. Raise ``MutationSinkError`` if it did not complete.

    ``undo(mutation) -> None``
        Attempt to restore ``mutation["before_state"]``. Its success or failure is
        recorded and then NOT used as the verdict -- the executor re-observes.

    ``drain_touched() -> Optional[List[Tuple[kind, path]]]``
        Every target this sink wrote since the last drain, INCLUDING ones the
        executor never asked for. This is the only channel through which an
        out-of-bound write can be detected, so returning ``None`` ("I cannot
        tell") is a real and distinct answer: it makes the bound unenforceable
        and the executor treats it as such rather than assuming compliance.
    """

    def observe(self, target_kind: str, target_path: str) -> Dict[str, Any]:
        raise NotImplementedError

    def apply(self, mutation: Dict[str, Any]) -> None:
        raise NotImplementedError

    def undo(self, mutation: Dict[str, Any]) -> None:
        raise NotImplementedError

    def drain_touched(self) -> Optional[List[Tuple[str, str]]]:
        raise NotImplementedError


class InMemoryMutationSink(MutationSink):
    """A world made of a dict, so the transaction rail is testable with no engine.

    Fault injection is part of the interface rather than bolted on by a test,
    because each knob corresponds to a real provider misbehaviour the executor
    exists to survive:

        fail_on_apply       the provider errors mid-plan
        fail_on_undo        the undo itself errors
        undo_restores_nothing
                            the undo REPORTS SUCCESS and changes nothing -- the
                            case that turns a rollback into a silent partial
                            commit, and the reason the executor re-observes
        stray_writes        the provider touches an address it never declared
        unobservable        a target that cannot be measured, in either direction
        cannot_report_touched
                            the sink does not know what it wrote at all
        on_apply            a hook run inside apply, used to prove the lock is
                            held for the whole duration rather than at the edges
    """

    def __init__(self, initial: Optional[Dict[Tuple[str, str], Any]] = None, *,
                 fail_on_apply: Sequence[str] = (),
                 fail_on_undo: Sequence[str] = (),
                 undo_restores_nothing: Sequence[str] = (),
                 stray_writes: Optional[Dict[str, Sequence[Tuple[str, str, Any]]]] = None,
                 unobservable: Sequence[Tuple[str, str]] = (),
                 cannot_report_touched: bool = False,
                 on_apply: Optional[Any] = None) -> None:
        self.world: Dict[Tuple[str, str], Any] = dict(initial or {})
        self.fail_on_apply = set(fail_on_apply)
        self.fail_on_undo = set(fail_on_undo)
        self.undo_restores_nothing = set(undo_restores_nothing)
        self.stray_writes = dict(stray_writes or {})
        self.unobservable = {(k, D.normalize_target_path(p)) for (k, p) in unobservable}
        self.cannot_report_touched = bool(cannot_report_touched)
        self.on_apply = on_apply
        self._touched: List[Tuple[str, str]] = []
        self.apply_calls: List[str] = []
        self.undo_calls: List[str] = []

    # -- world access -------------------------------------------------------- #
    def snapshot(self) -> Dict[str, Any]:
        """A comparable image of the whole world, for tests that assert restoration."""
        return {D.canonical([k[0], k[1]]): D.canonical(v) for k, v in self.world.items()}

    def observe(self, target_kind: str, target_path: str) -> Dict[str, Any]:
        key = (target_kind, D.normalize_target_path(target_path))
        if key in self.unobservable:
            return D.unmeasured_state("sink cannot observe {} {!r}".format(*key))
        if key in self.world:
            return D.present_state(self.world[key])
        return D.absent_state()

    def _write(self, target_kind: str, target_path: str, payload: Any,
               *, record: bool = True) -> None:
        key = (target_kind, D.normalize_target_path(target_path))
        if payload is None:
            self.world.pop(key, None)
        else:
            self.world[key] = payload
        if record:
            self._touched.append(key)

    # -- MutationSink -------------------------------------------------------- #
    def apply(self, mutation: Dict[str, Any]) -> None:
        mutation_id = mutation.get("mutation_id")
        self.apply_calls.append(mutation_id)
        if callable(self.on_apply):
            self.on_apply(mutation)
        for (kind, path, payload) in self.stray_writes.get(mutation_id, ()):
            self._write(kind, path, payload)
        if mutation_id in self.fail_on_apply:
            raise MutationSinkError(
                "sink refused to apply {!r}".format(mutation_id))
        kind = mutation.get("target_kind")
        path = mutation.get("target_path")
        op = mutation.get("operation")
        if op == D.OP_DELETE:
            self._write(kind, path, None)
        else:
            expected = mutation.get("expected_after_state") or {}
            self._write(kind, path, expected.get("payload"))

    def undo(self, mutation: Dict[str, Any]) -> None:
        mutation_id = mutation.get("mutation_id")
        self.undo_calls.append(mutation_id)
        if mutation_id in self.fail_on_undo:
            raise MutationSinkError("sink could not undo {!r}".format(mutation_id))
        if mutation_id in self.undo_restores_nothing:
            # Reports success, restores nothing. The whole point of re-observing.
            return
        before = mutation.get("before_state") or {}
        kind = mutation.get("target_kind")
        path = mutation.get("target_path")
        if before.get("state_kind") == D.STATE_PRESENT:
            self._write(kind, path, before.get("payload"), record=False)
        elif before.get("state_kind") == D.STATE_ABSENT:
            self._write(kind, path, None, record=False)

    def drain_touched(self) -> Optional[List[Tuple[str, str]]]:
        if self.cannot_report_touched:
            return None
        out = list(self._touched)
        self._touched = []
        return out


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("_")[:120]


def _failing(checks: List[Check]) -> List[Check]:
    return [(n, ok, d, c) for (n, ok, d, c) in checks if not ok]


def _operation_matches_before(operation: str, before: Dict[str, Any]) -> bool:
    """Is the world in the state this operation assumed when it was planned?"""
    kind = before.get("state_kind")
    if operation == D.OP_CREATE:
        return kind == D.STATE_ABSENT
    return kind == D.STATE_PRESENT


def _new_delta(operation_id: str, bounds: Any, mutations: List[Dict[str, Any]],
               evidence_refs: Sequence[str]) -> Dict[str, Any]:
    return {
        "delta_id": "delta_" + uuid.uuid4().hex[:16],
        "operation_id": operation_id,
        "outcome": D.DELTA_REFUSED,
        "bounds": list(bounds or []),
        "mutations": mutations,
        "evidence_refs": list(evidence_refs or []),
        "failure_codes": [],
        "verification": tri.UNKNOWN,
        "rollback_completeness": tri.UNKNOWN,
        "bound_enforcement": tri.UNKNOWN,
        "lock": {"held": False, "released": False, "path": None, "detail": ""},
        "abort_reason": "",
        "created_by": "worldforge.core",
        "created_at": _now_iso(),
        "schema_version": D.RT_WORLD_DELTA,
        "report_type": D.RT_WORLD_DELTA,
    }


def _add_code(record: Dict[str, Any], code: Optional[str]) -> None:
    if code and code not in record["failure_codes"]:
        record["failure_codes"].append(code)


# --------------------------------------------------------------------------- #
# the executor
# --------------------------------------------------------------------------- #
def apply_delta(sink: MutationSink,
                bounds: Sequence[Dict[str, Any]],
                mutations: Sequence[Dict[str, Any]],
                *,
                repo_root: Any,
                operation_id: str,
                evidence_refs: Sequence[str] = (),
                observe_after: bool = True,
                require_rollback_capable: bool = True,
                journal: bool = True,
                lock_rel: str = CORE_TRANSACTION_LOCK_REL,
                lock_ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
                strict: bool = True) -> Dict[str, Any]:
    """Apply ``mutations`` transactionally under ``bounds``. Returns a WorldDelta.

    Never raises for a world-state problem -- every refusal, abort and partial
    commit comes back as a delta record carrying its own failure codes, because a
    caller that must catch an exception to learn the world is half-changed will
    eventually not catch it.

    ``observe_after=False`` is the "postcondition asserted rather than measured"
    path. It is permitted, and it is reported as ``committed_unverified`` with
    ``CORE_DELTA_UNVERIFIED``; it can never be reported as a plain commit.
    """
    working = [dict(m) for m in (mutations or [])]   # never mutate the caller's records
    record = _new_delta(operation_id, bounds, working, evidence_refs)
    by_step = D.index_bounds(bounds)

    # --- 0. shape ----------------------------------------------------------- #
    shape: List[Check] = []
    for idx, b in enumerate(bounds or []):
        for (n, ok, det, code) in D.validate_mutation_bound(b, strict=strict):
            shape.append(("bound[{}].{}".format(idx, n), ok, det, code))
    for idx, m in enumerate(working):
        for (n, ok, det, code) in D.validate_mutation(m, strict=False):
            shape.append(("mutation[{}].{}".format(idx, n), ok, det, code))
    bad = _failing(shape)
    if bad:
        for (_n, _ok, _d, code) in bad:
            _add_code(record, code or C.CORE_DELTA_INVALID)
        record["abort_reason"] = (
            "refused before taking the lock: {} shape check(s) failed, first is "
            "{}: {}".format(len(bad), bad[0][0], bad[0][2]))
        for m in working:
            m["status"] = D.MUT_REFUSED
        return _refuse(record, repo_root, journal)

    # --- 1. preflight the DECLARED targets ---------------------------------- #
    # Circular by nature (a step's declaration checked against the same step's
    # declaration) and kept anyway: it costs nothing and it refuses an obviously
    # illegal request without ever touching the world. The check that can actually
    # catch a lying provider is step 5.
    refused = False
    for m in working:
        verdict, code, detail = D.classify_target(
            by_step.get(m.get("step_id")), m.get("target_kind"), m.get("target_path"))
        if verdict != D.TARGET_IN_BOUND:
            m["status"] = D.MUT_REFUSED
            m["detail"] = detail
            _add_code(record, code)
            refused = True
    if refused:
        for m in working:
            m["status"] = D.MUT_REFUSED
        record["abort_reason"] = (
            "refused before taking the lock: a declared target lies outside its "
            "step's mutation bound, so no part of this delta is authorised")
        return _refuse(record, repo_root, journal)

    # --- 2. rollback capability --------------------------------------------- #
    if require_rollback_capable:
        incapable = [m.get("mutation_id") for m in working
                     if m.get("rollback_mode") not in PB.ROLLBACK_CAPABLE]
        if incapable:
            for m in working:
                m["status"] = D.MUT_REFUSED
            _add_code(record, C.CORE_PROVIDER_ROLLBACK_UNSUPPORTED)
            record["abort_reason"] = (
                "refused before taking the lock: mutation(s) {} are performed by a "
                "provider declaring rollback outside {}. Applying them inside a "
                "transaction would mean the transaction has no rollback, which is "
                "discovered at the worst possible moment -- while unwinding".format(
                    incapable, list(PB.ROLLBACK_CAPABLE)))
            return _refuse(record, repo_root, journal)

    # --- 3. the single-writer lock, BEFORE any mutation --------------------- #
    lock = OPS.acquire_operation_lock(repo_root, operation_id,
                                      lock_rel=lock_rel, ttl_seconds=lock_ttl_seconds)
    if not lock.ok:
        for m in working:
            m["status"] = D.MUT_REFUSED
        _add_code(record, C.CORE_TRANSACTION_NOT_ISOLATED)
        record["abort_reason"] = (
            "refused: the single-writer operation lock could not be taken, so this "
            "transaction cannot be isolated from another writer. Underlying refusal "
            "{}: {}".format(lock.code, lock.detail))
        return _refuse(record, repo_root, journal)

    record["lock"] = {"held": True, "released": False,
                      "path": str(lock.value.path), "operation_id": operation_id,
                      "detail": lock.detail}

    try:
        _apply_under_lock(record, sink, working, by_step, observe_after)
    finally:
        # ALWAYS, including on an unexpected exception: a lock that outlives the
        # process that took it makes the repository unwritable until a human or a
        # ttl clears it.
        released = OPS.release_operation_lock(lock.value)
        record["lock"]["released"] = bool(released.ok)
        if not released.ok:
            record["lock"]["release_detail"] = "{}: {}".format(released.code, released.detail)

    # Journalled AFTER the release so the published record states what really
    # happened to the lock rather than what was true halfway through.
    if journal:
        _write_journal(record, repo_root)
    return record


def _apply_under_lock(record: Dict[str, Any], sink: MutationSink,
                      working: List[Dict[str, Any]],
                      by_step: Dict[Any, Dict[str, Any]],
                      observe_after: bool) -> None:
    """The mutating half. Runs with the single-writer lock held, and only then."""
    applied: List[Dict[str, Any]] = []
    abort_reason = ""
    for m in list(working):
        kind = m.get("target_kind")
        path = m.get("target_path")

        # -- 4a. capture the restore point BY OBSERVATION -------------------- #
        declared = m.get("before_state")
        observed_before = sink.observe(kind, path)
        m["before_state_declared"] = declared
        m["before_state"] = observed_before

        if not D.is_measured(observed_before):
            _add_code(record, C.CORE_DELTA_UNVERIFIED)
            abort_reason = (
                "mutation {!r}: the before-state of {} {!r} could not be measured "
                "({}). Without a restore point any undo would be a claim, so the "
                "mutation is not applied".format(
                    m.get("mutation_id"), kind, path, observed_before.get("reason")))
            break

        if D.is_state(declared) and D.states_equal(declared, observed_before) == tri.VIOLATED:
            _add_code(record, C.CORE_TRANSACTION_NOT_ISOLATED)
            abort_reason = (
                "mutation {!r}: {} {!r} is not in the state the plan observed when "
                "it was authored; another writer changed it between planning and "
                "now, so this transaction is not isolated".format(
                    m.get("mutation_id"), kind, path))
            break

        if not _operation_matches_before(m.get("operation"), observed_before):
            _add_code(record, C.CORE_TRANSACTION_NOT_ISOLATED)
            abort_reason = (
                "mutation {!r}: operation {!r} assumes a {} target, but {} {!r} was "
                "observed {!r}".format(
                    m.get("mutation_id"), m.get("operation"),
                    "non-existent" if m.get("operation") == D.OP_CREATE else "existing",
                    kind, path, observed_before.get("state_kind")))
            break

        # -- 4b. apply ------------------------------------------------------- #
        try:
            sink.apply(m)
            m["status"] = D.MUT_APPLIED
            applied.append(m)
        except MutationSinkError as exc:
            # A raised apply may still have changed something. It goes on the
            # rollback list precisely BECAUSE it did not complete.
            m["status"] = D.MUT_APPLY_FAILED
            m["detail"] = str(exc)
            applied.append(m)
            abort_reason = "mutation {!r} failed to apply: {}".format(
                m.get("mutation_id"), exc)
            break

        # -- 5. what was ACTUALLY touched ------------------------------------ #
        touched = sink.drain_touched()
        if touched is None:
            record["bound_enforcement"] = tri.UNKNOWN
            _add_code(record, C.CORE_DELTA_UNVERIFIED)
            abort_reason = (
                "mutation {!r}: the sink cannot report which targets it wrote, so "
                "the declared mutation bound cannot be enforced against what "
                "actually happened. Unenforceable is reported as unverified, never "
                "as compliance and never as a violation nobody observed".format(
                    m.get("mutation_id")))
            break

        stray = _check_actual_touches(record, m, touched, by_step)
        if stray:
            abort_reason = (
                "mutation {!r} (provider {!r}) wrote {} target(s) outside step {!r}'s "
                "declared bound: {}. The bound is enforced against what happened, "
                "not what was intended -- this is the case the declaration exists "
                "to catch".format(
                    m.get("mutation_id"), m.get("provider_id"), len(stray),
                    m.get("step_id"), [s["target_path"] for s in stray]))
            working.extend(stray)
            break

    if not abort_reason:
        record["bound_enforcement"] = tri.SATISFIED
        _commit_or_unverified(record, sink, applied, observe_after)
        if D.is_committed(record["outcome"]):
            return
        abort_reason = record["abort_reason"]

    record["abort_reason"] = abort_reason
    _rollback(record, sink, applied)


def _check_actual_touches(record: Dict[str, Any], mutation: Dict[str, Any],
                          touched: Sequence[Tuple[str, str]],
                          by_step: Dict[Any, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Check every ACTUALLY-written target against the step's bound.

    Returns synthetic mutation records for the strays. They are marked
    UNRECOVERABLE, not "applied": no before-state was ever captured for an address
    the executor did not know would be written, so there is nothing to restore it
    to. That is an unpleasant answer and it is the true one -- inventing a
    before-state here would fabricate a restore point.
    """
    bound = by_step.get(mutation.get("step_id"))
    stray: List[Dict[str, Any]] = []
    seen = set()
    for entry in touched:
        try:
            kind, path = entry[0], entry[1]
        except (TypeError, IndexError):
            continue
        key = (kind, D.normalize_target_path(path))
        if key in seen:
            continue
        seen.add(key)
        verdict, code, detail = D.classify_target(bound, kind, path)
        if verdict == D.TARGET_IN_BOUND:
            continue
        record["bound_enforcement"] = tri.VIOLATED
        _add_code(record, code)
        stray.append({
            "mutation_id": "{}_stray_{}".format(mutation.get("mutation_id"), len(stray)),
            "step_id": mutation.get("step_id"),
            "provider_id": mutation.get("provider_id"),
            "target_kind": kind,
            "target_path": D.normalize_target_path(path),
            "operation": D.OP_MODIFY,
            "before_state": D.unmeasured_state(
                "this address was never declared, so no restore point was captured "
                "before the provider wrote it"),
            "status": D.MUT_UNRECOVERABLE,
            "unrecoverable_reason": detail,
            "rollback_mode": mutation.get("rollback_mode"),
            "schema_version": D.RT_MUTATION,
        })
    return stray


def _commit_or_unverified(record: Dict[str, Any], sink: MutationSink,
                          applied: List[Dict[str, Any]], observe_after: bool) -> None:
    """Decide between committed, committed-unverified, and abort-and-roll-back."""
    if not observe_after:
        record["verification"] = tri.UNKNOWN
        record["outcome"] = D.DELTA_COMMITTED_UNVERIFIED
        _add_code(record, C.CORE_DELTA_UNVERIFIED)
        record["abort_reason"] = ""
        record["detail"] = (
            "committed with NO post-observation: every postcondition here was "
            "asserted, not measured. This is a claim about the world, not a "
            "result from it")
        return

    for m in applied:
        m["observed_after_apply"] = sink.observe(m.get("target_kind"), m.get("target_path"))
        m["verification"] = D._mutation_verification(m)
    sink.drain_touched()  # observation is not mutation; keep the touch log clean

    verdict = D.verification_status(record)
    record["verification"] = verdict
    if verdict == tri.SATISFIED:
        record["outcome"] = D.DELTA_COMMITTED
        return
    if verdict == tri.UNKNOWN:
        record["outcome"] = D.DELTA_COMMITTED_UNVERIFIED
        _add_code(record, C.CORE_DELTA_UNVERIFIED)
        record["detail"] = (
            "committed, but the post-observation fold is unknown: at least one "
            "applied mutation declared no postcondition or could not be measured")
        return
    # VIOLATED -- the postcondition was measured and it does not hold.
    record["abort_reason"] = (
        "post-observation CONTRADICTS the declared postcondition for at least one "
        "applied mutation; the world does not contain what this delta claims to "
        "have put there, so it is rolled back rather than reported")
    _add_code(record, C.CORE_DELTA_INVALID)
    record["outcome"] = D.DELTA_PARTIAL_COMMIT  # provisional; _rollback decides


def _rollback(record: Dict[str, Any], sink: MutationSink,
              applied: List[Dict[str, Any]]) -> None:
    """Undo in REVERSE order, then RE-OBSERVE to decide whether it worked.

    Reverse order because a later mutation may depend on an earlier one; undoing
    forwards would try to restore a base that a still-applied later mutation is
    sitting on top of.

    The verdict for each mutation comes from comparing the RE-OBSERVED state to
    the captured before-state. ``undo_reported_ok`` is written down and then never
    read again in this function -- an undo that reports success and restores
    nothing must land as ROLLBACK_FAILED, and it only can if the return value is
    not what decides.
    """
    for m in reversed(applied):
        if m.get("status") == D.MUT_UNRECOVERABLE:
            continue
        try:
            sink.undo(m)
            m["undo_reported_ok"] = True
        except MutationSinkError as exc:
            m["undo_reported_ok"] = False
            m["undo_error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - a sink defect is still a failed undo
            m["undo_reported_ok"] = False
            m["undo_error"] = "{}: {}".format(type(exc).__name__, exc)

        m["observed_after_rollback"] = sink.observe(m.get("target_kind"), m.get("target_path"))
        m["restoration"] = D._mutation_restoration(m)
        m["status"] = D.status_from_restoration(m["restoration"])
    sink.drain_touched()  # undo writes are not provider mutations; do not re-check them

    completeness = D.rollback_completeness(record)
    record["rollback_completeness"] = completeness

    if completeness == tri.SATISFIED:
        record["outcome"] = D.DELTA_ROLLED_BACK
        record["detail"] = (
            "rolled back and CONFIRMED: every undone target was re-observed and "
            "matches its captured before-state")
        return

    # Neither committed nor rolled back. Reported as exactly that.
    record["outcome"] = D.DELTA_PARTIAL_COMMIT
    _add_code(record, C.CORE_DELTA_PARTIAL_COMMIT)
    if completeness == tri.VIOLATED:
        _add_code(record, C.CORE_DELTA_ROLLBACK_FAILED)
        record["detail"] = (
            "PARTIAL COMMIT: the rollback ran and re-observation shows at least one "
            "target was not restored. The world is neither committed nor rolled "
            "back, and reporting it as either would be a lie a caller acts on")
    else:
        _add_code(record, C.CORE_DELTA_UNVERIFIED)
        record["detail"] = (
            "PARTIAL COMMIT: the rollback ran but at least one target could not be "
            "re-observed, so restoration is unknown. Unknown is not restored, and "
            "it is not a confirmed failure either")


def _write_journal(record: Dict[str, Any], repo_root: Any) -> None:
    """Publish the delta journal atomically, so a crash leaves whole or nothing."""
    rel = "{}/{}/world_delta.json".format(
        CORE_TRANSACTION_JOURNAL_DIR, _slug(record.get("operation_id")))
    result = OPS.atomic_write_json(rel, record, repo_root=repo_root)
    if result.ok:
        record["journal_path"] = str(result.value["path"])
    else:
        record["journal_path"] = None
        record["notes"] = "journal not published: {}: {}".format(result.code, result.detail)


def _refuse(record: Dict[str, Any], repo_root: Any, journal: bool) -> Dict[str, Any]:
    """Terminate before any mutation. The world was never touched on this path."""
    record["outcome"] = D.DELTA_REFUSED
    if journal:
        _write_journal(record, repo_root)
    return record


# --------------------------------------------------------------------------- #
# canonical example factory
# --------------------------------------------------------------------------- #
def _example_transaction(**over: Any) -> Dict[str, Any]:
    """A one-step, one-mutation transaction request. Domain-neutral addresses."""
    d: Dict[str, Any] = {
        "operation_id": "op_core_transaction_example",
        "bounds": [D._example_mutation_bound()],
        "mutations": [D._example_mutation()],
        "evidence_refs": ["operation_manifest"],
    }
    d.update(over)
    return d
