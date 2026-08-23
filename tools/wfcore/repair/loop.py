#!/usr/bin/env python3
"""wfcore.repair.loop -- the bounded, converging, generically-planned repair loop.

Run the suite from ``tools/``::

    PYTHONUTF8=1 python -m wfcore.repair.test_repair

THE DRIVER SHAPE, AND WHY IT TAKES CALLABLES
--------------------------------------------
``repair_loop`` performs no I/O and knows no engine. It is handed four callables
and does nothing except sequence them, check what comes back, and decide whether
to go round again:

    reconcile_fn(acceptance, attempt_index)  -> analysis
        an analysis in the shape ``planning.synth`` reads. Validated at the
        boundary with ``synth.validate_analysis_expectation`` -- never assumed.

    synth_fn(analysis, attempt_index)        -> synthesis result
        MUST be a ``planning.synth`` synthesis result. The driver refuses
        anything else (WF1267): a plan that did not come from the generic
        synthesiser never went through provider selection, declares no mutation
        bound, and cannot be rolled back.

    apply_fn(plan, attempt_index)            -> (delta, applied_at)
        a ``transaction.delta`` world delta and the ordinal at which it landed.

    observe_fn(delta, attempt_index)         -> acceptance evidence rows

The seam is the point. An engine-bound loop can only be tested by running an
engine, and a loop that can only be tested by running an engine is a loop whose
refusals are never exercised -- which is to say, a loop with no refusals.

HOW CONVERGENCE IS MEASURED
---------------------------
Progress is::

    set(blockers_after) < set(blockers_before)      # STRICT subset

Three things this deliberately is not:

  * not a COUNT. ``{A} -> {B}`` leaves the count at one, and a loop that reports
    "still 1 blocker, working on it" churns forever while a human reads progress
    into it. Sets catch the swap; counts cannot.
  * not a non-strict subset. An identical blocker set means the attempt changed
    the world and moved nothing, which is the same non-progress wearing a
    committed delta.
  * not a comparison of failure CODES. Codes are a rendering of the blockers, and
    a reworded detail or a differently-ordered list moves them without moving the
    problem.

The attempt record writes ``removed`` and ``added`` alongside the two sets, so a
non-converging attempt names exactly what it traded for what.

THE BOUND
---------
``policy["rollback"]["max_revision_attempts"]`` -- the consumer's number, read
from the consumer's own revision policy. Core supplying a default here would be
Core deciding how many times it may rewrite somebody else's content.

WHAT THE DRIVER REFUSES BEFORE IT APPLIES ANYTHING
--------------------------------------------------
WF1268 CORE_REPAIR_WITHOUT_EVIDENCE, in three shapes, all checked BEFORE any
mutation:

  1. the acceptance result was never judged (no reload-backed observation). A
     repair on top of it fixes a failure nothing observed;
  2. the analysis wants a step for a constraint the judgement never recorded as
     blocking;
  3. the analysis calls a constraint VIOLATED that the judgement measured as
     UNKNOWN -- and the plan therefore authors a mutation for something nobody
     established was wrong.

WF1266 CORE_REPAIR_INVALID covers the mirror of (3): an analysis calling
something UNKNOWN that the judgement measured as VIOLATED stalls a repair that is
due, which is a different failure and gets a different code.
"""

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import tri
from ..acceptance import evaluate as EV
from ..failure import FailureCode as C
from ..planning import plan as P
from ..planning import synth as SY
from ..providers import selection as S

# --------------------------------------------------------------------------- #
# schema identity (house convention: wf.<domain>.<thing>.v<N>)
# --------------------------------------------------------------------------- #
RT_REPAIR_ATTEMPT = "wf.core.repair_attempt.v1"
RT_REPAIR_RESULT = "wf.core.repair_loop_result.v1"

# --------------------------------------------------------------------------- #
# outcomes -- a closed set, so "stopped" is never confused with "finished"
# --------------------------------------------------------------------------- #
REPAIR_ACCEPTED = "accepted"
REPAIR_NOTHING_TO_REPAIR = "nothing_to_repair"
REPAIR_EXHAUSTED = "attempts_exhausted"
REPAIR_NOT_CONVERGING = "not_converging"
REPAIR_UNPLANNABLE = "unplannable"
REPAIR_BYPASSED_PLANNING = "bypassed_planning"
REPAIR_WITHOUT_EVIDENCE = "without_evidence"
REPAIR_REFUSED = "refused"
REPAIR_OUTCOMES = (REPAIR_ACCEPTED, REPAIR_NOTHING_TO_REPAIR, REPAIR_EXHAUSTED,
                   REPAIR_NOT_CONVERGING, REPAIR_UNPLANNABLE,
                   REPAIR_BYPASSED_PLANNING, REPAIR_WITHOUT_EVIDENCE,
                   REPAIR_REFUSED)

# Outcomes that mean the loop stopped without reaching acceptance AND without
# having proved anything about why. Kept as a tuple so a reader can see that
# "accepted" is the only success, and that there are seven ways to not be it.
UNRESOLVED_OUTCOMES = tuple(o for o in REPAIR_OUTCOMES if o != REPAIR_ACCEPTED)

# --------------------------------------------------------------------------- #
# record shapes
# --------------------------------------------------------------------------- #
ATTEMPT_REQUIRED = ("attempt_index", "blockers_before", "blockers_after",
                    "removed", "added", "converging", "analysis_id",
                    "synthesis_id", "plan_id", "step_kinds", "delta_id",
                    "delta_outcome", "applied_at", "acceptance_outcome",
                    "acceptance_verdict", "failure_codes", "detail",
                    "schema_version")
ATTEMPT_ALLOWED = ATTEMPT_REQUIRED + ("notes",)

RESULT_REQUIRED = ("loop_id", "outcome", "accepted", "max_attempts",
                   "attempts_used", "attempts", "initial_blockers",
                   "final_blockers", "final_acceptance", "refusal_reason",
                   "failure_codes", "detail", "schema_version")
RESULT_ALLOWED = RESULT_REQUIRED + ("report_type", "created_by", "created_at",
                                    "meta", "notes")

Check = Tuple[str, bool, str, Optional[str]]

_P = "rl::"
_AP = "ra::"

CREATED_BY = "wfcore.repair.loop"


# --------------------------------------------------------------------------- #
# small readers
# --------------------------------------------------------------------------- #
def _as_tuple(value: Any) -> Tuple[Any, ...]:
    return tuple(value) if isinstance(value, (list, tuple)) else ()


def _dict_list(value: Any) -> List[Dict[str, Any]]:
    return [v for v in _as_tuple(value) if isinstance(v, dict)]


def _sorted_ids(values: Any) -> List[str]:
    return sorted({str(v) for v in values})


# --------------------------------------------------------------------------- #
# convergence -- the one definition, read by the driver AND the validator
# --------------------------------------------------------------------------- #
def blocker_ids(acceptance: Any) -> List[str]:
    """The SET of constraint ids blocking acceptance, as a sorted list.

    Read off ``acceptance.blockers``, which ``constraints.unresolved_blockers``
    produced -- so what counts as a blocker is decided by the constraint
    taxonomy, once, and not re-litigated per attempt.
    """
    if not isinstance(acceptance, dict):
        return []
    return _sorted_ids(b.get("constraint_id")
                       for b in _dict_list(acceptance.get("blockers"))
                       if b.get("constraint_id") is not None)


def is_converging(before: Any, after: Any) -> bool:
    """Did this attempt REDUCE the blocker set? A strict subset, never a count.

    ``{A} -> {B}`` is False: the count is unchanged and the sets are unrelated, so
    an attempt that swapped one blocker for another made no progress at all, and
    a loop that treats it as progress runs until something else stops it.

    ``{A} -> {A}`` is False too: the world changed and the problem did not.
    """
    return set(_as_tuple(after)) < set(_as_tuple(before))


def blocker_delta(before: Any, after: Any) -> Tuple[List[str], List[str]]:
    """``(removed, added)`` -- what an attempt traded for what."""
    b, a = set(_as_tuple(before)), set(_as_tuple(after))
    return (_sorted_ids(b - a), _sorted_ids(a - b))


# --------------------------------------------------------------------------- #
# the generic-planning rail (WF1267)
# --------------------------------------------------------------------------- #
def planning_provenance(synthesis: Any) -> Tuple[bool, str]:
    """Did this plan come from the generic synthesiser? ``(ok, detail)``.

    Checked structurally, against the identities the planning lane stamps on its
    own records: the synthesis result's schema version, the plan's schema
    version, and -- per step -- a provider SELECTION result. That last one is the
    load-bearing part: a bespoke fix names a provider directly, and a selection
    result is the artefact that only exists when ``providers.selection`` actually
    ran and left behind a registry snapshot and its reasons.
    """
    if not isinstance(synthesis, dict):
        return (False, "synthesis result must be an object, got {}".format(
            type(synthesis).__name__))

    if synthesis.get("schema_version") != SY.RT_PLAN_SYNTHESIS:
        return (False,
                "synthesis result carries schema_version {!r}, not {!r}; a repair "
                "whose plan did not come from the generic synthesiser is a "
                "bespoke fix path -- untested, unbounded and unrollbackable"
                .format(synthesis.get("schema_version"), SY.RT_PLAN_SYNTHESIS))

    outcome = synthesis.get("outcome")
    if outcome not in SY.SYNTHESIS_OUTCOMES:
        return (False, "synthesis outcome {!r} is not one of {}".format(
            outcome, SY.SYNTHESIS_OUTCOMES))

    if outcome != SY.OUTCOME_PLANNED:
        return (True, "synthesis produced no plan ({}); nothing claims to have "
                      "been planned generically".format(outcome))

    plan = synthesis.get("plan")
    if not isinstance(plan, dict) or plan.get("schema_version") != P.RT_PLAN:
        return (False,
                "synthesis reports {!r} but its plan carries schema_version {!r}, "
                "not {!r}".format(outcome,
                                  plan.get("schema_version")
                                  if isinstance(plan, dict) else None, P.RT_PLAN))

    steps = _dict_list(plan.get("steps"))
    if not steps:
        return (False, "a planned synthesis carries no steps; there is nothing "
                       "for the transaction path to run")

    unselected = [s.get("step_id") for s in steps
                  if not isinstance(s.get("selection"), dict)
                  or s["selection"].get("schema_version") != S.RT_SELECTION_RESULT]
    if unselected:
        return (False,
                "step(s) {} carry no provider selection result ({}); a step whose "
                "provider was named rather than SELECTED skipped every filter the "
                "selection layer applies, including the one that keeps a mutating "
                "provider out of an observation".format(unselected,
                                                        S.RT_SELECTION_RESULT))

    return (True, "plan {!r} came from the generic synthesiser with {} selected "
                  "step(s)".format(plan.get("plan_id"), len(steps)))


# --------------------------------------------------------------------------- #
# the evidence rails (WF1268 / WF1266)
# --------------------------------------------------------------------------- #
def _observed_evaluations(acceptance: Any) -> Dict[str, str]:
    """constraint_id -> the tri-value the JUDGEMENT measured for it."""
    out: Dict[str, str] = {}
    for f in _dict_list((acceptance or {}).get("findings")
                        if isinstance(acceptance, dict) else None):
        if f.get("constraint_id") is not None:
            out[str(f.get("constraint_id"))] = f.get("evaluation")
    return out


def repair_evidence_problems(analysis: Any,
                             acceptance: Any) -> List[Dict[str, Any]]:
    """Every way this analysis would repair something nothing observed.

    Runs BEFORE synthesis, so a repair that rests on nothing never becomes a plan
    -- let alone a mutation.
    """
    problems: List[Dict[str, Any]] = []
    observed_blockers = set(blocker_ids(acceptance))
    observed = _observed_evaluations(acceptance)

    for finding in _dict_list((analysis or {}).get("findings")
                              if isinstance(analysis, dict) else None):
        kind = SY.finding_step_kind(finding)
        if kind is None:
            continue
        cid = str(finding.get("constraint_id"))

        if cid not in observed_blockers:
            problems.append({
                "constraint_id": cid,
                "reason": "the analysis wants a {} step for {!r}, but the "
                          "acceptance judgement never recorded it as blocking "
                          "(blockers were {}). Repairing a failure nothing "
                          "observed spends the consumer's world on a problem "
                          "nobody established".format(
                              kind, cid, sorted(observed_blockers)),
                "failure_code": C.CORE_REPAIR_WITHOUT_EVIDENCE,
            })
            continue

        measured = observed.get(cid)
        stated = finding.get("evaluation")
        if stated == tri.VIOLATED and measured == tri.UNKNOWN:
            problems.append({
                "constraint_id": cid,
                "reason": "the analysis states {!r} is VIOLATED, but the "
                          "judgement measured it as UNKNOWN. A revision step "
                          "would author a change to the consumer's world for "
                          "something nobody established was wrong -- and the "
                          "measurement that would have said so is exactly the "
                          "step being skipped".format(cid),
                "failure_code": C.CORE_REPAIR_WITHOUT_EVIDENCE,
            })
        elif stated == tri.UNKNOWN and measured == tri.VIOLATED:
            problems.append({
                "constraint_id": cid,
                "reason": "the analysis states {!r} is UNKNOWN, but the judgement "
                          "MEASURED it as violated. Routing a measured violation "
                          "to an observation step stalls a repair that is due, "
                          "and the loop will spend an attempt re-measuring "
                          "something it already knows".format(cid),
                "failure_code": C.CORE_REPAIR_INVALID,
            })
    return problems


def remedy_kind_problems(analysis: Any, plan: Any) -> List[Dict[str, Any]]:
    """Check the synthesised plan against the analysis's own remedy direction.

    UNKNOWN -> an OBSERVATION step, whose mutation bound must be EMPTY.
    VIOLATED -> a REVISION step, whose mutation bound must NOT be.

    The bound is read straight off the step, in the same two fields
    ``transaction.delta`` reads to decide what a mutation was authorised to touch,
    so "this step mutates nothing" means here exactly what it means there.
    """
    problems: List[Dict[str, Any]] = []
    steps = {s.get("step_id"): s for s in _dict_list((plan or {}).get("steps")
                                                     if isinstance(plan, dict)
                                                     else None)}

    for finding in _dict_list((analysis or {}).get("findings")
                              if isinstance(analysis, dict) else None):
        kind = SY.finding_step_kind(finding)
        if kind is None:
            continue
        cid = str(finding.get("constraint_id"))
        step = steps.get(SY.step_id_for(finding, kind))
        if step is None:
            problems.append({
                "constraint_id": cid,
                "reason": "no step in the synthesised plan addresses {!r}; a plan "
                          "with a blocker quietly dropped still cannot reach "
                          "acceptance, so executing it arrives somewhere already "
                          "known to be unacceptable".format(cid),
                "failure_code": C.CORE_REPAIR_INVALID,
            })
            continue

        bound = (list(_as_tuple(step.get("expected_changed_packages")))
                 + list(_as_tuple(step.get("expected_changed_actors"))))

        if kind == SY.STEP_KIND_OBSERVATION and bound:
            problems.append({
                "constraint_id": cid,
                "reason": "{!r} is UNKNOWN, so its repair is an OBSERVATION -- go "
                          "measure it. The synthesised step instead declares a "
                          "mutation bound {}; authoring a change for an unmeasured "
                          "constraint modifies the consumer's world for a reason "
                          "nobody established".format(cid, bound),
                "failure_code": C.CORE_REPAIR_WITHOUT_EVIDENCE,
            })
        elif kind == SY.STEP_KIND_REVISION and not bound:
            problems.append({
                "constraint_id": cid,
                "reason": "{!r} is VIOLATED, so its repair is a MUTATION. The "
                          "synthesised step declares no mutation bound at all, so "
                          "it can change nothing and the violation will survive "
                          "the attempt while the attempt reports work done"
                          .format(cid),
                "failure_code": C.CORE_REPAIR_INVALID,
            })
    return problems


# --------------------------------------------------------------------------- #
# the bound
# --------------------------------------------------------------------------- #
def max_attempts_of(policy: Any) -> Optional[int]:
    """The consumer's ``max_revision_attempts``, or ``None`` if it stated none.

    ``None`` is load-bearing: Core defaulting a bound here would be Core deciding
    how many times it may rewrite somebody else's content.
    """
    rollback = (policy or {}).get("rollback") if isinstance(policy, dict) else None
    if not isinstance(rollback, dict):
        return None
    value = rollback.get("max_revision_attempts")
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None
    return value


# --------------------------------------------------------------------------- #
# the driver
# --------------------------------------------------------------------------- #
def _blank_result(loop_id: Optional[str], max_attempts: Any,
                  initial: Sequence[str]) -> Dict[str, Any]:
    return {
        "loop_id": loop_id or "repair_loop",
        "outcome": REPAIR_REFUSED,
        "accepted": False,
        "max_attempts": max_attempts,
        "attempts_used": 0,
        "attempts": [],
        "initial_blockers": list(initial),
        "final_blockers": list(initial),
        "final_acceptance": None,
        "refusal_reason": None,
        "failure_codes": [],
        "detail": "",
        "created_by": CREATED_BY,
        "schema_version": RT_REPAIR_RESULT,
        "report_type": RT_REPAIR_RESULT,
    }


def _attempt_record(index: int, before: Sequence[str], after: Sequence[str],
                    analysis: Any, synthesis: Any, plan: Any, delta: Any,
                    applied_at: Any, acceptance: Any, step_kinds: Dict[str, str],
                    codes: Sequence[str], detail: str) -> Dict[str, Any]:
    removed, added = blocker_delta(before, after)
    return {
        "attempt_index": index,
        "blockers_before": list(before),
        "blockers_after": list(after),
        "removed": removed,
        "added": added,
        "converging": is_converging(before, after),
        "analysis_id": (analysis or {}).get("analysis_id")
        if isinstance(analysis, dict) else None,
        "synthesis_id": (synthesis or {}).get("synthesis_id")
        if isinstance(synthesis, dict) else None,
        "plan_id": (plan or {}).get("plan_id") if isinstance(plan, dict) else None,
        "step_kinds": dict(step_kinds),
        "delta_id": (delta or {}).get("delta_id") if isinstance(delta, dict)
        else None,
        "delta_outcome": (delta or {}).get("outcome") if isinstance(delta, dict)
        else None,
        "applied_at": applied_at,
        "acceptance_outcome": (acceptance or {}).get("outcome")
        if isinstance(acceptance, dict) else None,
        "acceptance_verdict": (acceptance or {}).get("acceptance_verdict")
        if isinstance(acceptance, dict) else None,
        "failure_codes": sorted(set(codes)),
        "detail": detail,
        "schema_version": RT_REPAIR_ATTEMPT,
    }


def _step_kinds(analysis: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for f in _dict_list((analysis or {}).get("findings")
                        if isinstance(analysis, dict) else None):
        kind = SY.finding_step_kind(f)
        if kind is not None:
            out[str(f.get("constraint_id"))] = kind
    return out


def repair_loop(criteria: Any, policy: Any, acceptance: Any,
                reconcile_fn: Callable[..., Any],
                synth_fn: Callable[..., Any],
                apply_fn: Callable[..., Any],
                observe_fn: Callable[..., Any],
                loop_id: Optional[str] = None) -> Dict[str, Any]:
    """Repair until accepted, or stop for a reason that is written down.

    Never applies anything on the first pass: the loop begins by reading the
    acceptance result it was handed, and every refusal that can be decided
    without touching the world is decided before ``apply_fn`` is called at all.
    """
    max_attempts = max_attempts_of(policy)
    initial = blocker_ids(acceptance)
    result = _blank_result(loop_id, max_attempts, initial)
    result["final_acceptance"] = acceptance

    if max_attempts is None:
        result["outcome"] = REPAIR_REFUSED
        result["refusal_reason"] = (
            "the consumer's revision policy states no usable "
            "max_revision_attempts; Core supplying a bound would be Core "
            "deciding how many times it may rewrite somebody else's content")
        result["failure_codes"] = [C.CORE_REPAIR_INVALID]
        result["detail"] = result["refusal_reason"]
        return result

    codes: set = set()
    attempts: List[Dict[str, Any]] = []
    current = acceptance

    while True:
        if isinstance(current, dict) and current.get("accepted") is True:
            result["outcome"] = REPAIR_ACCEPTED
            break

        before = blocker_ids(current)

        if not before:
            # Not accepted, and nothing named as blocking. Either the judgement
            # refused (partial commit, no reload-backed observation) or the record
            # is incoherent. Repairing here would fix a failure nothing observed.
            result["outcome"] = REPAIR_WITHOUT_EVIDENCE
            result["refusal_reason"] = (
                "the acceptance result is not accepted (outcome {!r}) yet names "
                "no blocking constraint, so there is nothing a repair could be "
                "said to address".format(
                    current.get("outcome") if isinstance(current, dict) else None))
            codes.add(C.CORE_REPAIR_WITHOUT_EVIDENCE)
            break

        if current.get("judged") is not True:
            result["outcome"] = REPAIR_WITHOUT_EVIDENCE
            result["refusal_reason"] = (
                "the acceptance result refused to judge (outcome {!r}: {}); a "
                "repair planned on top of it would fix a failure nothing "
                "observed".format(current.get("outcome"),
                                  current.get("refusal_reason")))
            codes.add(C.CORE_REPAIR_WITHOUT_EVIDENCE)
            break

        if len(attempts) >= max_attempts:
            result["outcome"] = REPAIR_EXHAUSTED
            result["refusal_reason"] = (
                "the consumer's revision policy allows {} revision attempt(s) and "
                "all are spent; {} constraint(s) still block. An unbounded loop "
                "rewrites the consumer's content indefinitely on the strength of "
                "an acceptance it is not reaching".format(max_attempts,
                                                          len(before)))
            codes.add(C.CORE_REPAIR_ATTEMPTS_EXHAUSTED)
            break

        index = len(attempts)

        # --- 1. the analysis, checked at the boundary ------------------------ #
        analysis = reconcile_fn(current, index)
        boundary = SY.validate_analysis_expectation(analysis)
        broken = [(n, c) for (n, ok, _d, c) in boundary if not ok]
        if broken:
            result["outcome"] = REPAIR_REFUSED
            result["refusal_reason"] = (
                "the analysis does not meet the structural expectation planning "
                "reads: {}".format([n for (n, _c) in broken[:6]]))
            codes.add(C.CORE_REPAIR_INVALID)
            codes |= {c for (_n, c) in broken if c}
            break

        # --- 2. is this repair supported by anything that was observed? ------ #
        evidence_problems = repair_evidence_problems(analysis, current)
        if evidence_problems:
            result["outcome"] = REPAIR_WITHOUT_EVIDENCE
            result["refusal_reason"] = "; ".join(
                p["reason"] for p in evidence_problems[:3])
            codes |= {p["failure_code"] for p in evidence_problems}
            break

        # --- 3. the plan, and ONLY from the generic synthesiser --------------- #
        synthesis = synth_fn(analysis, index)
        ok, detail = planning_provenance(synthesis)
        if not ok:
            result["outcome"] = REPAIR_BYPASSED_PLANNING
            result["refusal_reason"] = detail
            codes.add(C.CORE_REPAIR_BYPASSED_PLANNING)
            break

        s_outcome = synthesis.get("outcome")
        if s_outcome != SY.OUTCOME_PLANNED:
            result["outcome"] = REPAIR_UNPLANNABLE
            result["refusal_reason"] = (
                "synthesis returned {!r} while {} constraint(s) block; a loop that "
                "applies nothing and goes round again churns forever while "
                "reporting progress it is not making".format(s_outcome,
                                                             len(before)))
            codes.add(C.CORE_REPAIR_INVALID)
            codes |= set(_as_tuple(synthesis.get("failure_codes")))
            break

        plan = synthesis.get("plan")

        # --- 4. UNKNOWN measures, VIOLATED mutates. Never backwards. --------- #
        kind_problems = remedy_kind_problems(analysis, plan)
        if kind_problems:
            result["outcome"] = REPAIR_REFUSED
            result["refusal_reason"] = "; ".join(
                p["reason"] for p in kind_problems[:3])
            codes |= {p["failure_code"] for p in kind_problems}
            break

        # --- 5. apply, observe, re-judge -------------------------------------- #
        delta, applied_at = apply_fn(plan, index)
        evidence = observe_fn(delta, index)
        current = EV.evaluate_acceptance(criteria, delta, evidence, applied_at)
        after = blocker_ids(current)

        attempt_codes = set(_as_tuple(current.get("failure_codes")))
        converging = is_converging(before, after)
        if not converging:
            attempt_codes.add(C.CORE_REPAIR_NOT_CONVERGING)

        attempts.append(_attempt_record(
            index, before, after, analysis, synthesis, plan, delta, applied_at,
            current, _step_kinds(analysis), attempt_codes,
            "blockers {} -> {}".format(before, after)))

        if not converging:
            removed, added = blocker_delta(before, after)
            result["outcome"] = REPAIR_NOT_CONVERGING
            result["refusal_reason"] = (
                "attempt {} did not reduce the blocker set: {} -> {} (removed {}, "
                "added {}). Progress is a STRICT SUBSET, not a smaller count -- "
                "swapping one blocker for another leaves the count unchanged and "
                "the loop would run forever reporting work done".format(
                    index, before, after, removed, added))
            codes.add(C.CORE_REPAIR_NOT_CONVERGING)
            break

    result["attempts"] = attempts
    result["attempts_used"] = len(attempts)
    result["final_acceptance"] = current
    result["final_blockers"] = blocker_ids(current)
    result["accepted"] = bool(isinstance(current, dict)
                              and current.get("accepted") is True)
    result["failure_codes"] = sorted(codes)
    if not result["detail"]:
        result["detail"] = result["refusal_reason"] or (
            "reached acceptance after {} attempt(s)".format(len(attempts)))
    return result


def explain_repair(result: Dict[str, Any]) -> List[str]:
    """Render a repair loop result as human-readable lines."""
    lines = ["repair {}: outcome={} accepted={} attempts={}/{}".format(
        result.get("loop_id"), result.get("outcome"), result.get("accepted"),
        result.get("attempts_used"), result.get("max_attempts"))]
    for a in _as_tuple(result.get("attempts")):
        lines.append("  attempt {}: {} -> {} (removed {}, added {}) converging={}"
                     .format(a.get("attempt_index"), a.get("blockers_before"),
                             a.get("blockers_after"), a.get("removed"),
                             a.get("added"), a.get("converging")))
    if result.get("refusal_reason"):
        lines.append("  stopped: {}".format(result["refusal_reason"]))
    return lines


# --------------------------------------------------------------------------- #
# validators
# --------------------------------------------------------------------------- #
def validate_repair_attempt(attempt: Any, strict: bool = False) -> List[Check]:
    """Rails that hold for ONE attempt.

    The rail that matters is ``converging``: it is re-derived from the two
    recorded blocker sets, never trusted. An attempt that calls itself converging
    while it swapped one blocker for another is the record a human reads as
    progress.
    """
    invalid = C.CORE_REPAIR_INVALID
    checks: List[Check] = []

    if not isinstance(attempt, dict):
        return [(_AP + "is_object", False,
                 "attempt must be an object, got {}".format(
                     type(attempt).__name__), invalid)]

    p = "{}{}::".format(_AP, attempt.get("attempt_index"))

    missing = [k for k in ATTEMPT_REQUIRED if k not in attempt]
    checks.append((p + "required", not missing,
                   "missing required key(s) {}".format(missing) if missing
                   else "all required keys present",
                   None if not missing else invalid))

    if strict:
        unknown = sorted(set(attempt) - set(ATTEMPT_ALLOWED))
        checks.append((p + "no_unknown_fields", not unknown,
                       "unknown key(s) {}".format(unknown) if unknown
                       else "no unknown keys", None if not unknown else invalid))

    sv = attempt.get("schema_version")
    ok = sv == RT_REPAIR_ATTEMPT
    checks.append((p + "schema_version", ok,
                   "schema_version must be {!r} (got {!r})".format(
                       RT_REPAIR_ATTEMPT, sv), None if ok else invalid))

    before = attempt.get("blockers_before")
    after = attempt.get("blockers_after")
    lists_ok = isinstance(before, list) and isinstance(after, list)
    checks.append((p + "blocker_sets_are_lists", lists_ok,
                   "blockers_before/blockers_after must both be lists (got {} / "
                   "{})".format(type(before).__name__, type(after).__name__),
                   None if lists_ok else invalid))

    if lists_ok:
        # --- THE rail ---------------------------------------------------------
        want = is_converging(before, after)
        got = attempt.get("converging")
        ok = got is want
        checks.append((
            p + "converging_is_re_derived_from_the_sets", ok,
            "attempt records converging={!r}, but {} -> {} is a strict subset "
            "reduction: {}. Convergence is a SET relation, not a count -- "
            "swapping one blocker for another leaves the count unchanged and the "
            "loop churns forever while reporting progress it is not making"
            .format(got, before, after, want),
            None if ok else C.CORE_REPAIR_NOT_CONVERGING))

        removed, added = blocker_delta(before, after)
        ok = _sorted_ids(_as_tuple(attempt.get("removed"))) == removed
        checks.append((p + "removed_matches_the_sets", ok,
                       "attempt records removed={!r} but the sets give {!r}"
                       .format(attempt.get("removed"), removed),
                       None if ok else invalid))
        ok = _sorted_ids(_as_tuple(attempt.get("added"))) == added
        checks.append((p + "added_matches_the_sets", ok,
                       "attempt records added={!r} but the sets give {!r}".format(
                           attempt.get("added"), added), None if ok else invalid))

        # A non-converging attempt must SAY so in its codes; otherwise the loop
        # result rolls up clean over an attempt that made no progress.
        if not want:
            ok = C.CORE_REPAIR_NOT_CONVERGING in _as_tuple(
                attempt.get("failure_codes"))
            checks.append((
                p + "non_converging_attempt_raises_wf1270", ok,
                "the attempt reduced nothing ({} -> {}) but raises no {}; without "
                "it the loop rolls up clean over an attempt that changed the "
                "world and moved no blocker".format(
                    before, after, C.CORE_REPAIR_NOT_CONVERGING),
                None if ok else C.CORE_REPAIR_NOT_CONVERGING))

    verdict = attempt.get("acceptance_verdict")
    ok = verdict is None or verdict in tri.TRI_VALUES
    checks.append((p + "acceptance_verdict_is_tri", ok,
                   "acceptance_verdict {!r} is not one of {}".format(
                       verdict, tri.TRI_VALUES), None if ok else invalid))

    kinds = attempt.get("step_kinds")
    if isinstance(kinds, dict):
        bad = sorted(k for k, v in kinds.items() if v not in SY.STEP_KINDS)
        checks.append((p + "step_kinds_known", not bad,
                       "step_kinds names {} outside {}".format(bad, SY.STEP_KINDS)
                       if bad else "every step kind is one of {}".format(
                           SY.STEP_KINDS),
                       None if not bad else invalid))

    return checks


def validate_repair_result(obj: Any, strict: bool = False) -> List[Check]:
    """Validate a WHOLE repair loop result: every attempt, then the chain rails.

    The chain rails are the reason this validator exists. Each closes a way the
    record can be internally contradictory while every attempt in it validates --
    and a contradictory loop record is worse than an invalid one, because it
    reads as a clean report of a repair that did not happen.
    """
    invalid = C.CORE_REPAIR_INVALID
    checks: List[Check] = []

    if not isinstance(obj, dict):
        return [(_P + "is_object", False,
                 "repair result must be an object, got {}".format(
                     type(obj).__name__), invalid)]

    for fld in RESULT_REQUIRED:
        present = fld in obj
        checks.append((_P + "has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else invalid))

    if strict:
        unknown = sorted(set(obj) - set(RESULT_ALLOWED))
        checks.append((_P + "no_unknown_fields", not unknown,
                       "unexpected field(s) {}".format(unknown) if unknown
                       else "no unexpected fields", None if not unknown else invalid))

    sv = obj.get("schema_version")
    ok = sv == RT_REPAIR_RESULT
    checks.append((_P + "schema_version", ok,
                   "schema_version must be {!r} (got {!r})".format(
                       RT_REPAIR_RESULT, sv), None if ok else invalid))

    outcome = obj.get("outcome")
    ok = outcome in REPAIR_OUTCOMES
    checks.append((_P + "outcome_known", ok,
                   "outcome {!r} is not one of {}".format(outcome, REPAIR_OUTCOMES),
                   None if ok else invalid))

    accepted = obj.get("accepted")
    ok = isinstance(accepted, bool)
    checks.append((_P + "accepted_is_bool", ok,
                   "accepted must be an explicit boolean (got {!r})".format(
                       accepted), None if ok else invalid))

    attempts = obj.get("attempts")
    a_ok = isinstance(attempts, list)
    checks.append((_P + "attempts_is_list", a_ok, "attempts must be a list",
                   None if a_ok else invalid))
    attempts = attempts if a_ok else []

    for attempt in attempts:
        checks.extend(validate_repair_attempt(attempt, strict=strict))

    ok = obj.get("attempts_used") == len(attempts)
    checks.append((_P + "attempts_used_matches_attempts", ok,
                   "attempts_used is {!r} but {} attempt(s) are recorded; the "
                   "count is what a reader trusts and the list is what happened"
                   .format(obj.get("attempts_used"), len(attempts)),
                   None if ok else invalid))

    # --- THE bound rail ------------------------------------------------------- #
    max_attempts = obj.get("max_attempts")
    if isinstance(max_attempts, int) and not isinstance(max_attempts, bool):
        ok = len(attempts) <= max_attempts
        checks.append((
            _P + "attempts_within_the_consumers_bound", ok,
            "{} attempt(s) were run against a policy bound of {}; the bound is the "
            "consumer's statement of how many times Core may rewrite its content, "
            "and exceeding it is not a rounding error".format(len(attempts),
                                                              max_attempts),
            None if ok else C.CORE_REPAIR_ATTEMPTS_EXHAUSTED))
        if outcome == REPAIR_EXHAUSTED:
            ok = len(attempts) >= max_attempts
            checks.append((
                _P + "exhausted_really_did_exhaust_the_bound", ok,
                "outcome is {!r} after {} of {} allowed attempt(s); reporting a "
                "budget as spent while it is not hides a loop that gave up"
                .format(REPAIR_EXHAUSTED, len(attempts), max_attempts),
                None if ok else invalid))

    # --- the chain must be continuous ----------------------------------------- #
    initial = obj.get("initial_blockers")
    if attempts and isinstance(initial, list):
        first = attempts[0].get("blockers_before") if isinstance(attempts[0], dict) \
            else None
        ok = _sorted_ids(_as_tuple(first)) == _sorted_ids(initial)
        checks.append((
            _P + "first_attempt_starts_from_the_initial_blockers", ok,
            "the loop records initial_blockers {!r} but its first attempt started "
            "from {!r}".format(initial, first), None if ok else invalid))

    for i in range(1, len(attempts)):
        prev = attempts[i - 1] if isinstance(attempts[i - 1], dict) else {}
        cur = attempts[i] if isinstance(attempts[i], dict) else {}
        ok = (_sorted_ids(_as_tuple(cur.get("blockers_before")))
              == _sorted_ids(_as_tuple(prev.get("blockers_after"))))
        checks.append((
            "{}attempt[{}].continues_from_the_previous".format(_P, i), ok,
            "attempt {} starts from {!r} but attempt {} ended at {!r}; a gap in "
            "the chain means the loop is comparing against a state no attempt "
            "produced, and convergence measured across it proves nothing".format(
                i, cur.get("blockers_before"), i - 1, prev.get("blockers_after")),
            None if ok else invalid))

        ok = prev.get("attempt_index") != cur.get("attempt_index")
        checks.append((
            "{}attempt[{}].index_is_distinct".format(_P, i), ok,
            "attempt indices {!r} repeat; a duplicate index makes the order "
            "ambiguous".format(cur.get("attempt_index")),
            None if ok else invalid))

    final = obj.get("final_blockers")
    if attempts and isinstance(final, list):
        last = attempts[-1].get("blockers_after") if isinstance(attempts[-1], dict) \
            else None
        ok = _sorted_ids(_as_tuple(last)) == _sorted_ids(final)
        checks.append((
            _P + "final_blockers_match_the_last_attempt", ok,
            "the loop records final_blockers {!r} but its last attempt ended at "
            "{!r}".format(final, last), None if ok else invalid))

    # --- outcome coherence ----------------------------------------------------- #
    if outcome == REPAIR_ACCEPTED:
        ok = accepted is True
        checks.append((_P + "accepted_outcome_is_accepted", ok,
                       "outcome is {!r} with accepted={!r}".format(
                           REPAIR_ACCEPTED, accepted), None if ok else invalid))
        ok = not (obj.get("final_blockers") or [])
        checks.append((
            _P + "accepted_leaves_no_blockers", ok,
            "outcome is {!r} but {} constraint(s) still block; acceptance is the "
            "absence of blockers, not a decision taken over them".format(
                REPAIR_ACCEPTED, len(obj.get("final_blockers") or [])),
            None if ok else C.CORE_ACCEPTANCE_ON_UNKNOWN))
    elif outcome in UNRESOLVED_OUTCOMES:
        ok = accepted is not True
        checks.append((
            _P + "unresolved_outcome_is_not_an_acceptance", ok,
            "outcome is {!r} but the loop records accepted=True; a loop that "
            "stopped without reaching acceptance must not report one".format(
                outcome), None if ok else C.CORE_ACCEPTANCE_ON_UNKNOWN))
        ok = bool(obj.get("refusal_reason"))
        checks.append((
            _P + "unresolved_outcome_states_a_reason", ok,
            "outcome {!r} carries no refusal_reason; an unexplained stop is "
            "indistinguishable from a crash".format(outcome),
            None if ok else invalid))

    codes = _as_tuple(obj.get("failure_codes"))
    if outcome == REPAIR_NOT_CONVERGING:
        ok = C.CORE_REPAIR_NOT_CONVERGING in codes
        checks.append((_P + "not_converging_raises_wf1270", ok,
                       "outcome is {!r} but codes are {}".format(outcome,
                                                                 list(codes)),
                       None if ok else C.CORE_REPAIR_NOT_CONVERGING))
    if outcome == REPAIR_EXHAUSTED:
        ok = C.CORE_REPAIR_ATTEMPTS_EXHAUSTED in codes
        checks.append((_P + "exhausted_raises_wf1269", ok,
                       "outcome is {!r} but codes are {}".format(outcome,
                                                                 list(codes)),
                       None if ok else C.CORE_REPAIR_ATTEMPTS_EXHAUSTED))
    if outcome == REPAIR_BYPASSED_PLANNING:
        ok = C.CORE_REPAIR_BYPASSED_PLANNING in codes
        checks.append((_P + "bypassed_planning_raises_wf1267", ok,
                       "outcome is {!r} but codes are {}".format(outcome,
                                                                 list(codes)),
                       None if ok else C.CORE_REPAIR_BYPASSED_PLANNING))
    if outcome == REPAIR_WITHOUT_EVIDENCE:
        ok = C.CORE_REPAIR_WITHOUT_EVIDENCE in codes
        checks.append((_P + "without_evidence_raises_wf1268", ok,
                       "outcome is {!r} but codes are {}".format(outcome,
                                                                 list(codes)),
                       None if ok else C.CORE_REPAIR_WITHOUT_EVIDENCE))

    return checks
