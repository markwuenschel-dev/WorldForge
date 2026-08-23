#!/usr/bin/env python3
"""wfcore.acceptance.evaluate -- the acceptance verdict, and the four refusals.

Run the suite from ``tools/``::

    PYTHONUTF8=1 python -m wfcore.acceptance.test_acceptance

THE RECORD, AND WHY IT CARRIES SO MUCH
--------------------------------------
An acceptance result is not ``{"accepted": true}``. A bare boolean is
unfalsifiable: nothing in it says what was judged, against which observation, or
whether that observation described the world under judgement at all. Two results
-- one earned, one fabricated -- would be the same document.

So the record states, per criterion:

    evaluation   the tri-value this criterion folded to
    evidence     one row per observation consulted, each naming the operation it
                 was taken under, when it was taken, whether it was
                 RELOAD-BACKED, and which tri-value it supports
    usable       re-derivable per row: stale rows and unreloaded rows are named
                 as such rather than silently dropped
    blocking_reason  VIOLATED vs never-measured, kept apart, because they route to
                 opposite repairs

and, per result, the operation under judgement -- so a reader can re-derive every
verdict from the document without re-running this module.

NON-CIRCULAR RE-DERIVATION
--------------------------
``validate_acceptance_result`` does NOT call ``evaluate_acceptance``. It reads
only what the record wrote down -- each evidence row's ``operation_id``,
``observed_at``, ``observation_kind``, ``reload_backed`` and ``supports``, checked
against the recorded ``judged_operation`` -- and recomputes usability and the fold
from those raw fields. It never trusts the producer's own ``usable`` flag; it
re-derives that too and objects when the two disagree. A producer that folded a
verdict its own evidence does not support is therefore caught, which is the only
failure this check can honestly claim to catch.

THE FOUR REFUSALS
-----------------
1. WF1257 CORE_ACCEPTANCE_ON_UNKNOWN. Acceptance is ``tri.accepts(fold)``. The
   code has TWO raise sites, and they are different failures wearing one name:

     * the PRODUCER raises it when the fold comes out UNKNOWN -- naming, in the
       result, the load-bearing constraints that were never measured, so an
       INDETERMINATE outcome says which measurement is missing instead of merely
       failing;
     * the VALIDATOR raises it when a record CLAIMS acceptance while its own
       evidence re-derives to UNKNOWN. That is the headline fake-green, and it is
       the reason ``accepted`` is written into the record as an explicit boolean:
       a claim that is not stated cannot be contradicted.

2. WF1258 CORE_ACCEPTANCE_STALE_EVIDENCE. Evidence is stale when its
   ``operation_id`` differs from the operation under judgement, when it was taken
   before the delta landed, or when nothing establishes the ordering at all. All
   three are refusals, and the third is separate on purpose: "we cannot tell
   whether this predates the change" must not be recorded as "we checked and it
   does not".

   A stale row does not merely fail to help -- it POISONS the criterion that
   cites it, exactly as an unbacked evidence row poisons a finding in
   ``analysis.reconcile``. Dropping the stale row and folding the survivors is
   the "filter out the ones we don't have data for" shrink that reads like
   housekeeping and returns SATISFIED. If a row should not count, the producer
   must not cite it.

3. WF1259 CORE_ACCEPTANCE_NOT_RELOADED. An in-memory world can satisfy criteria a
   saved-and-reloaded one does not: unsaved state, resolved-only-in-session
   references, and derived data that never round-tripped. So a judgement with no
   reload-backed observation is REFUSED -- not judged and rejected, which would
   send repair after a defect nobody established, and not judged and accepted,
   which is the fake-green.

4. WF1256 CORE_ACCEPTANCE_INVALID. Shape.

PARTIAL COMMIT IS REPORTED, NOT ROUNDED
---------------------------------------
``transaction.delta`` keeps PARTIAL_COMMIT as a fifth outcome precisely so it
never has to be rounded into "committed" or "rolled back". This module honours
that: a partial commit is refused with outcome ``partial_commit``, an EXPLICIT
``tri.UNKNOWN`` verdict, and WF1249 -- never REJECTED. Rejection reads as "the
world is wrong, repair it", and repairing on top of a half-changed world is how a
recoverable state becomes an unrecoverable one.

WHY A VERIFIED COMMIT IS RECORDED BUT IS NOT THE GATE
-----------------------------------------------------
``delta.commit_is_verified`` says the MUTATION's declared postcondition was
measured to hold. That is a claim about what the step intended, not about what
the consumer asked for; a step can land exactly what it promised and still leave
a hard invariant violated. So ``commit_verified`` is carried in the record for
diagnosis, and the gate is the reload-backed evidence rail, which is strictly
stronger.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import constraints as K
from .. import tri
from ..contracts import acceptance_criteria as AC
from ..failure import FailureCode as C
from ..transaction import delta as D

# --------------------------------------------------------------------------- #
# schema identity (house convention: wf.<domain>.<thing>.v<N>)
# --------------------------------------------------------------------------- #
RT_ACCEPTANCE_RESULT = "wf.core.acceptance_result.v1"
RT_ACCEPTANCE_FINDING = "wf.core.acceptance_finding.v1"
RT_ACCEPTANCE_EVIDENCE = "wf.core.acceptance_evidence.v1"
RT_JUDGED_OPERATION = "wf.core.judged_operation.v1"

# --------------------------------------------------------------------------- #
# how an observation was taken. RELOAD-BACKED is a separate KIND, not a flag on
# an ordinary observation, because it is the only kind acceptance may rest on.
# --------------------------------------------------------------------------- #
OBS_RELOADED = "reload_backed_observation"
OBS_IN_MEMORY = "in_memory_observation"
OBS_DECLARED = "declared_without_observation"
OBSERVATION_KINDS = (OBS_RELOADED, OBS_IN_MEMORY, OBS_DECLARED)

# The closed set of kinds acceptance may rest on. One visible tuple, for the same
# reason ``ACCEPTANCE_LOAD_BEARING`` is one: widening it is a semantic change to
# every judgement in existence and must be visible in a diff.
RELOAD_BACKED_KINDS = (OBS_RELOADED,)

# --------------------------------------------------------------------------- #
# why an evidence row does not describe the operation under judgement
# --------------------------------------------------------------------------- #
STALE_DIFFERENT_OPERATION = "taken_under_a_different_operation"
STALE_PREDATES_DELTA = "taken_before_the_delta_landed"
STALE_ORDER_UNESTABLISHED = "nothing_establishes_when_it_was_taken"
STALE_REASONS = (STALE_DIFFERENT_OPERATION, STALE_PREDATES_DELTA,
                 STALE_ORDER_UNESTABLISHED)

# --------------------------------------------------------------------------- #
# outcomes. FIVE, and the last two are not variants of "no".
# --------------------------------------------------------------------------- #
OUTCOME_ACCEPTED = "accepted"
OUTCOME_REJECTED = "rejected"            # measured, and something is wrong
OUTCOME_INDETERMINATE = "indeterminate"  # blocked by what nobody measured
OUTCOME_PARTIAL_COMMIT = "partial_commit"  # a world state no contract describes
OUTCOME_REFUSED = "refused"              # the judgement could not honestly run
ACCEPTANCE_OUTCOMES = (OUTCOME_ACCEPTED, OUTCOME_REJECTED, OUTCOME_INDETERMINATE,
                       OUTCOME_PARTIAL_COMMIT, OUTCOME_REFUSED)

# Outcomes in which no per-criterion judgement was made at all.
UNJUDGED_OUTCOMES = (OUTCOME_PARTIAL_COMMIT, OUTCOME_REFUSED)

# --------------------------------------------------------------------------- #
# record shapes
# --------------------------------------------------------------------------- #
JUDGED_OPERATION_REQUIRED = ("operation_id", "delta_id", "delta_outcome",
                             "applied_at", "commit_verified", "schema_version")

EVIDENCE_REQUIRED = ("evidence_id", "constraint_id", "operation_id",
                     "observed_at", "observation_kind", "reload_backed",
                     "supports", "evidence_refs", "detail")
EVIDENCE_ALLOWED = EVIDENCE_REQUIRED + ("observed_by", "notes", "schema_version")

# What the FINDING writes about each row it cites: the raw row plus the two
# re-derivable judgements. Both are written down so a reader can disagree with
# them; neither is trusted by the validator.
EVIDENCE_ROW_REQUIRED = EVIDENCE_REQUIRED + ("stale_reason", "usable",
                                             "schema_version")

FINDING_REQUIRED = ("constraint_id", "constraint_class", "acceptance_load_bearing",
                    "evaluation", "evidence", "blocking_reason", "failure_codes",
                    "detail", "schema_version")
FINDING_ALLOWED = FINDING_REQUIRED + ("notes",)

RESULT_REQUIRED = ("result_id", "criteria_id", "consumer_id", "request_id",
                   "judged_operation", "judged", "refusal_reason", "outcome",
                   "acceptance_verdict", "accepted", "findings", "blockers",
                   "stale_evidence", "unreloaded_criteria", "failure_codes",
                   "schema_version")
RESULT_ALLOWED = RESULT_REQUIRED + ("report_type", "created_by", "created_at",
                                    "meta", "notes")

Check = Tuple[str, bool, str, Optional[str]]

_P = "acr::"
_FP = "acf::"

CREATED_BY = "wfcore.acceptance.evaluate"


# --------------------------------------------------------------------------- #
# small readers
# --------------------------------------------------------------------------- #
def _is_number(x: Any) -> bool:
    """Numeric, and ``bool`` is NOT numeric here.

    ``isinstance(True, int)`` is True in Python, so a boolean ``observed_at``
    would order as 0/1 and compare "before" or "after" a real sequence number.
    """
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _dict_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [v for v in value if isinstance(v, dict)]


# --------------------------------------------------------------------------- #
# the operation under judgement
# --------------------------------------------------------------------------- #
def judged_operation(delta: Any, applied_at: Any) -> Dict[str, Any]:
    """Lift the delta under judgement into the record acceptance is judged against.

    Mirrors ``delta.bound_from_step``: it reads a few named fields off another
    lane's record and states them in a shape this lane owns, so a change on either
    side fails visibly here instead of being silently misread.

    ``applied_at`` is a monotonic ORDINAL, not a wall clock. A clock introduces a
    dependency on two machines agreeing, and an evidence row that predates a
    change by one second of clock skew is indistinguishable from one that follows
    it. The ordinal is supplied by whoever applied the delta, which is the only
    party that can honestly state it.
    """
    d = delta if isinstance(delta, dict) else {}
    outcome = d.get("outcome")
    return {
        "operation_id": d.get("operation_id"),
        "delta_id": d.get("delta_id"),
        "delta_outcome": outcome,
        "applied_at": applied_at,
        # Recorded for diagnosis, deliberately NOT the gate -- see the module
        # docstring. A mutation can land exactly what it promised and still leave
        # the consumer's invariant violated.
        "commit_verified": D.commit_is_verified(outcome),
        "schema_version": RT_JUDGED_OPERATION,
    }


# --------------------------------------------------------------------------- #
# evidence: staleness, reload-backing, usability
# --------------------------------------------------------------------------- #
def is_reload_backed(row: Any) -> bool:
    """True only for a row that names a reload-backed KIND *and* signs the flag.

    Two fields for one fact, on purpose: the kind is the vocabulary a producer
    selects from, and the flag is the claim it signs. ``validate_acceptance_*``
    objects when they disagree, so a row cannot acquire reload-backing by setting
    a boolean next to a kind that denies it.
    """
    if not isinstance(row, dict):
        return False
    return (row.get("observation_kind") in RELOAD_BACKED_KINDS
            and row.get("reload_backed") is True)


def evidence_staleness(row: Any, judged: Any) -> Optional[str]:
    """Why this row does not describe the operation under judgement, or ``None``.

    Ordering that cannot be established is its own reason. Reporting it as
    "predates the delta" would state a comparison nobody performed, and reporting
    it as fresh would accept the previous world whenever an ordinal was omitted --
    which is exactly when it is most likely to have been.
    """
    if not isinstance(row, dict) or not isinstance(judged, dict):
        return STALE_ORDER_UNESTABLISHED
    if row.get("operation_id") != judged.get("operation_id"):
        return STALE_DIFFERENT_OPERATION
    observed_at = row.get("observed_at")
    applied_at = judged.get("applied_at")
    if not (_is_number(observed_at) and _is_number(applied_at)):
        return STALE_ORDER_UNESTABLISHED
    if observed_at < applied_at:
        return STALE_PREDATES_DELTA
    return None


def evidence_usable(row: Any, judged: Any) -> Tuple[bool, Optional[str], Optional[str]]:
    """Can this row support a verdict? Returns ``(usable, detail, failure_code)``.

    The single usability rule in the module. The producer calls it to write the
    row, and the validator calls it to re-derive the row's own claim, so the two
    cannot disagree about what "usable" means -- while still disagreeing, loudly,
    about whether a particular row IS usable.
    """
    if not isinstance(row, dict):
        return (False, "evidence row is not an object", C.CORE_ACCEPTANCE_INVALID)

    stale = evidence_staleness(row, judged)
    if stale is not None:
        return (False,
                "evidence {!r} is stale ({}): it names operation {!r} taken at "
                "{!r}, while the operation under judgement is {!r} applied at "
                "{!r}. Stale evidence accepts the PREVIOUS world".format(
                    row.get("evidence_id"), stale, row.get("operation_id"),
                    row.get("observed_at"),
                    (judged or {}).get("operation_id") if isinstance(judged, dict)
                    else None,
                    (judged or {}).get("applied_at") if isinstance(judged, dict)
                    else None),
                C.CORE_ACCEPTANCE_STALE_EVIDENCE)

    if not is_reload_backed(row):
        return (False,
                "evidence {!r} is a {!r} observation (reload_backed={!r}); an "
                "in-memory world can satisfy criteria a saved-and-reloaded one "
                "does not, so it cannot support acceptance".format(
                    row.get("evidence_id"), row.get("observation_kind"),
                    row.get("reload_backed")),
                C.CORE_ACCEPTANCE_NOT_RELOADED)

    if row.get("supports") not in tri.TRI_VALUES:
        return (False,
                "evidence {!r} supports {!r}, which is not one of {}; a two-valued "
                "observation cannot distinguish 'measured and wrong' from 'never "
                "measured'".format(row.get("evidence_id"), row.get("supports"),
                                   tri.TRI_VALUES),
                C.CORE_ACCEPTANCE_INVALID)

    return (True, "reload-backed observation of the operation under judgement",
            None)


def _evidence_row(raw: Dict[str, Any], judged: Dict[str, Any]) -> Dict[str, Any]:
    """The row as written into a finding: the raw claim plus the two judgements."""
    stale = evidence_staleness(raw, judged)
    usable, detail, _code = evidence_usable(raw, judged)
    refs = raw.get("evidence_refs")
    return {
        "evidence_id": raw.get("evidence_id"),
        "constraint_id": raw.get("constraint_id"),
        "operation_id": raw.get("operation_id"),
        "observed_at": raw.get("observed_at"),
        "observation_kind": raw.get("observation_kind"),
        "reload_backed": raw.get("reload_backed"),
        "supports": raw.get("supports"),
        "evidence_refs": list(refs) if isinstance(refs, (list, tuple)) else [],
        "stale_reason": stale,
        "usable": bool(usable),
        "detail": raw.get("detail") or detail,
        "schema_version": RT_ACCEPTANCE_EVIDENCE,
    }


def _recompute_from_record(finding: Any, judged: Any) -> str:
    """Recompute a criterion's verdict from what the FINDING wrote down.

    Reads only the cited rows' raw fields and the recorded judged operation. It
    never calls the evaluator, and it never reads the producer's own ``usable``
    or ``stale_reason``, so agreement is evidence that the recorded verdict is
    supported by the recorded evidence -- not evidence that one function is
    deterministic.

    Any unusable cited row yields UNKNOWN for the whole criterion. See refusal 2
    in the module docstring: dropping it and folding the survivors is the shrink
    that returns SATISFIED.
    """
    if not isinstance(finding, dict):
        return tri.UNKNOWN
    rows = finding.get("evidence")
    rows = rows if isinstance(rows, list) else []
    if not rows:
        return tri.UNKNOWN
    values: List[str] = []
    for row in rows:
        ok, _detail, _code = evidence_usable(row, judged)
        if not ok:
            return tri.UNKNOWN
        values.append(row.get("supports"))
    return tri.conj(values)


# --------------------------------------------------------------------------- #
# the judgement
# --------------------------------------------------------------------------- #
def _blank_result(criteria: Any, judged: Dict[str, Any],
                  result_id: Optional[str]) -> Dict[str, Any]:
    c = criteria if isinstance(criteria, dict) else {}
    return {
        "result_id": result_id or "acceptance_{}".format(
            judged.get("delta_id") or judged.get("operation_id")),
        "criteria_id": c.get("criteria_id"),
        "consumer_id": c.get("consumer_id"),
        "request_id": c.get("request_id"),
        "judged_operation": judged,
        "judged": False,
        "refusal_reason": None,
        "outcome": OUTCOME_REFUSED,
        # EXPLICIT. Folding zero findings returns SATISFIED by tri.conj's
        # identity, so a refusal that does not write UNKNOWN out by hand reads,
        # downstream, as an acceptance nobody computed.
        "acceptance_verdict": tri.UNKNOWN,
        "accepted": False,
        "findings": [],
        "blockers": [],
        "stale_evidence": [],
        "unreloaded_criteria": [],
        "failure_codes": [],
        "created_by": CREATED_BY,
        "schema_version": RT_ACCEPTANCE_RESULT,
        "report_type": RT_ACCEPTANCE_RESULT,
    }


def _refuse(criteria: Any, judged: Dict[str, Any], result_id: Optional[str],
            outcome: str, reason: str, codes: Sequence[str]) -> Dict[str, Any]:
    out = _blank_result(criteria, judged, result_id)
    out["outcome"] = outcome
    out["refusal_reason"] = reason
    out["failure_codes"] = sorted(set(codes))
    return out


def _shape_problems(criteria: Any, judged: Dict[str, Any]) -> List[str]:
    """The shape failures that make a judgement impossible. WF1256 raise site."""
    problems: List[str] = []
    if not isinstance(criteria, dict):
        problems.append("acceptance criteria must be an object, got {}".format(
            type(criteria).__name__))
        return problems
    if not isinstance(criteria.get("constraints"), (list, tuple)):
        problems.append("criteria carry no constraint list; there is nothing to "
                        "judge against")
    elif not [c for c in _dict_list(criteria.get("constraints"))
              if K.is_acceptance_load_bearing(c)]:
        # Mirrors WF1203 upstream: a criteria set with no load-bearing member
        # folds to vacuous SATISFIED and would accept any world.
        problems.append("criteria declare no acceptance-load-bearing constraint; "
                        "the fold would be vacuously SATISFIED and would accept "
                        "any world at all")
    if not _nonempty_str(judged.get("operation_id")):
        problems.append("the delta under judgement names no operation_id, so no "
                        "evidence can be matched to the operation it describes")
    if judged.get("delta_outcome") not in D.DELTA_OUTCOMES:
        problems.append("delta outcome {!r} is not one of {}".format(
            judged.get("delta_outcome"), D.DELTA_OUTCOMES))
    if not _is_number(judged.get("applied_at")):
        problems.append("applied_at is {!r}, not an ordinal; without it nothing "
                        "establishes whether an observation predates the change "
                        "it claims to describe".format(judged.get("applied_at")))
    return problems


def evaluate_acceptance(criteria: Any, delta: Any, evidence: Any,
                        applied_at: Any = None,
                        result_id: Optional[str] = None) -> Dict[str, Any]:
    """Judge ONE result against the consumer's criteria. The entry point.

    ``criteria``   a ``contracts.acceptance_criteria`` record. Its constraints,
                   and their CLASSES, decide what can block.
    ``delta``      the ``transaction.delta`` world delta under judgement.
    ``evidence``   raw acceptance-evidence rows. Each names the constraint it
                   speaks to, the operation it was taken under, when it was taken,
                   how it was taken, and which tri-value it supports.
    ``applied_at`` the ordinal at which the delta's mutations landed.

    Refuses -- before judging anything -- on a malformed judgement, on a partial
    commit, on a delta that never committed, and on the absence of any
    reload-backed observation.
    """
    judged = judged_operation(delta, applied_at)
    rows = _dict_list(evidence)

    # --- refusal 0: shape ---------------------------------------------------- #
    problems = _shape_problems(criteria, judged)
    if problems:
        return _refuse(criteria, judged, result_id, OUTCOME_REFUSED,
                       "the judgement is malformed and cannot honestly run: "
                       "{}".format("; ".join(problems)),
                       [C.CORE_ACCEPTANCE_INVALID])

    # --- refusal 1: a partial commit is REPORTED, never rounded --------------- #
    if D.is_partial_commit(judged["delta_outcome"]):
        return _refuse(
            criteria, judged, result_id, OUTCOME_PARTIAL_COMMIT,
            "delta {!r} is a partial commit: applied, undo attempted, restoration "
            "not confirmed. No contract describes that world, so it can never be "
            "accepted -- and it is reported AS partial rather than as a rejection, "
            "because a rejection reads as 'the world is wrong, repair it' and "
            "repairing on top of a half-changed world is how a recoverable state "
            "becomes an unrecoverable one".format(judged.get("delta_id")),
            [C.CORE_DELTA_PARTIAL_COMMIT])

    # --- refusal 2: nothing landed, so there is no produced world to judge ---- #
    if not D.is_committed(judged["delta_outcome"]):
        return _refuse(
            criteria, judged, result_id, OUTCOME_REFUSED,
            "delta {!r} has outcome {!r}, so nothing it planned is in the world. "
            "Judging the consumer's criteria against it would be a verdict about "
            "a world that was never produced".format(
                judged.get("delta_id"), judged.get("delta_outcome")),
            [])

    # --- refusal 3: no reload-backed observation ------------------------------ #
    fresh_reloaded = [r for r in rows
                      if is_reload_backed(r)
                      and evidence_staleness(r, judged) is None]
    if not fresh_reloaded:
        return _refuse(
            criteria, judged, result_id, OUTCOME_REFUSED,
            "no reload-backed observation of operation {!r} was supplied ({} "
            "evidence row(s) offered). An in-memory world can satisfy criteria a "
            "saved-and-reloaded one does not, so acceptance is refused rather "
            "than taken on an observation of state that was never persisted"
            .format(judged.get("operation_id"), len(rows)),
            [C.CORE_ACCEPTANCE_NOT_RELOADED])

    # --- the per-criterion judgement ------------------------------------------ #
    constraints = _dict_list(criteria.get("constraints"))
    findings: List[Dict[str, Any]] = []
    pairs: List[Tuple[Dict[str, Any], str]] = []
    stale_evidence: List[Dict[str, Any]] = []
    unreloaded: List[Any] = []

    for constraint in constraints:
        cid = constraint.get("constraint_id")
        cited = [_evidence_row(r, judged) for r in rows
                 if r.get("constraint_id") == cid]
        evaluation = _recompute_from_record({"evidence": cited}, judged)

        codes: List[str] = []
        stale_rows = [r for r in cited if r["stale_reason"] is not None]
        for r in stale_rows:
            codes.append(C.CORE_ACCEPTANCE_STALE_EVIDENCE)
            stale_evidence.append({
                "evidence_id": r["evidence_id"],
                "constraint_id": cid,
                "stale_reason": r["stale_reason"],
                "operation_id": r["operation_id"],
                "observed_at": r["observed_at"],
            })
        if not any(is_reload_backed(r) for r in cited):
            unreloaded.append(cid)
            if K.is_acceptance_load_bearing(constraint):
                codes.append(C.CORE_ACCEPTANCE_NOT_RELOADED)

        findings.append({
            "constraint_id": cid,
            "constraint_class": constraint.get("constraint_class"),
            "acceptance_load_bearing": K.is_acceptance_load_bearing(constraint),
            "evaluation": evaluation,
            "evidence": cited,
            "blocking_reason": None,
            "failure_codes": sorted(set(codes)),
            "detail": "judged {} reload-backed and {} stale evidence row(s) "
                      "against the operation under judgement".format(
                          sum(1 for r in cited if r["usable"]), len(stale_rows)),
            "schema_version": RT_ACCEPTANCE_FINDING,
        })
        pairs.append((constraint, evaluation))

    # The fold and the blocker reasons come from ``constraints``; neither is
    # reimplemented here, so class authority holds by construction rather than by
    # this module remembering it.
    verdict = K.fold_acceptance(pairs)
    blockers = K.unresolved_blockers(pairs)
    reason_by_id = {b.get("constraint_id"): b.get("blocking_reason")
                    for b in blockers}
    for f in findings:
        f["blocking_reason"] = reason_by_id.get(f["constraint_id"])

    # THE line. ``tri.accepts``, never ``!= VIOLATED`` -- the two differ exactly
    # on the constraints nobody measured.
    accepted = tri.accepts(verdict)

    codes = {c for f in findings for c in f["failure_codes"]}
    if accepted:
        outcome = OUTCOME_ACCEPTED
    elif verdict == tri.VIOLATED:
        outcome = OUTCOME_REJECTED
    else:
        outcome = OUTCOME_INDETERMINATE
        # Producer raise site for WF1257: acceptance was sought and is blocked by
        # load-bearing constraints nothing measured. Naming the code here is what
        # makes an indeterminate result actionable -- it says WHICH measurement is
        # missing rather than merely failing.
        codes.add(C.CORE_ACCEPTANCE_ON_UNKNOWN)

    out = _blank_result(criteria, judged, result_id)
    out.update({
        "judged": True,
        "refusal_reason": None,
        "outcome": outcome,
        "acceptance_verdict": verdict,
        "accepted": accepted,
        "findings": findings,
        "blockers": blockers,
        "stale_evidence": stale_evidence,
        "unreloaded_criteria": sorted(map(str, unreloaded)),
        "failure_codes": sorted(codes),
    })
    return out


def explain_acceptance(result: Dict[str, Any]) -> List[str]:
    """Render an acceptance result as human-readable lines."""
    lines = ["acceptance {}: outcome={} verdict={} accepted={}".format(
        result.get("result_id"), result.get("outcome"),
        result.get("acceptance_verdict"), result.get("accepted"))]
    if result.get("refusal_reason"):
        lines.append("  refused: {}".format(result["refusal_reason"]))
    for b in result.get("blockers") or ():
        lines.append("  blocked by {} ({}): {}".format(
            b.get("constraint_id"), b.get("evaluation"),
            b.get("blocking_reason")))
    for s in result.get("stale_evidence") or ():
        lines.append("  stale evidence {} for {}: {}".format(
            s.get("evidence_id"), s.get("constraint_id"), s.get("stale_reason")))
    return lines


# --------------------------------------------------------------------------- #
# validators
# --------------------------------------------------------------------------- #
def validate_acceptance_evidence(row: Any, judged: Any = None,
                                 strict: bool = False) -> List[Check]:
    """Validate ONE evidence row. ``judged`` enables the staleness rails."""
    invalid = C.CORE_ACCEPTANCE_INVALID
    checks: List[Check] = []

    if not isinstance(row, dict):
        return [("evidence_is_object", False,
                 "evidence must be an object, got {}".format(type(row).__name__),
                 invalid)]

    p = "ace::{}::".format(row.get("evidence_id"))

    missing = [k for k in EVIDENCE_REQUIRED if k not in row]
    checks.append((p + "required", not missing,
                   "missing required key(s) {}".format(missing) if missing
                   else "all required keys present",
                   None if not missing else invalid))

    if strict:
        unknown = sorted(set(row) - set(EVIDENCE_ROW_REQUIRED) - set(EVIDENCE_ALLOWED))
        checks.append((p + "no_unknown_fields", not unknown,
                       "unknown key(s) {}".format(unknown) if unknown
                       else "no unknown keys", None if not unknown else invalid))

    kind = row.get("observation_kind")
    ok = kind in OBSERVATION_KINDS
    checks.append((p + "observation_kind_known", ok,
                   "observation_kind {!r} is not one of {}".format(
                       kind, OBSERVATION_KINDS),
                   None if ok else invalid))

    # THE consistency rail: the flag may not out-claim the kind.
    flag = row.get("reload_backed")
    ok = flag is not True or kind in RELOAD_BACKED_KINDS
    checks.append((
        p + "reload_flag_matches_kind", ok,
        "row claims reload_backed=True with observation_kind {!r}, which is not "
        "one of {}; a row that signs the claim while naming a kind that denies "
        "it is the fabrication this rail exists to prevent".format(
            kind, RELOAD_BACKED_KINDS),
        None if ok else C.CORE_ACCEPTANCE_NOT_RELOADED))

    supports = row.get("supports")
    ok = supports in tri.TRI_VALUES
    checks.append((p + "supports_is_tri", ok,
                   "supports {!r} is not one of {}".format(supports,
                                                           tri.TRI_VALUES),
                   None if ok else invalid))

    ok = _is_number(row.get("observed_at"))
    checks.append((p + "observed_at_is_ordinal", ok,
                   "observed_at {!r} is not an ordinal; without one nothing "
                   "establishes whether this observation predates the change it "
                   "claims to describe".format(row.get("observed_at")),
                   None if ok else C.CORE_ACCEPTANCE_STALE_EVIDENCE))

    if isinstance(judged, dict):
        stale = evidence_staleness(row, judged)
        checks.append((
            p + "describes_the_operation_under_judgement", stale is None,
            "row is stale ({}): operation {!r} at {!r} against judged operation "
            "{!r} applied at {!r}".format(
                stale, row.get("operation_id"), row.get("observed_at"),
                judged.get("operation_id"), judged.get("applied_at"))
            if stale is not None else "row describes the operation under judgement",
            None if stale is None else C.CORE_ACCEPTANCE_STALE_EVIDENCE))

        if "usable" in row or "stale_reason" in row:
            usable, _detail, _code = evidence_usable(row, judged)
            ok = row.get("usable") is usable and row.get("stale_reason") == stale
            checks.append((
                p + "row_judgements_are_re_derivable", ok,
                "row records usable={!r} stale_reason={!r}, but re-deriving from "
                "its own raw fields against the judged operation gives {!r} / "
                "{!r}; a row whose own summary disagrees with its content is the "
                "half every downstream reader actually reads".format(
                    row.get("usable"), row.get("stale_reason"), usable, stale),
                None if ok else C.CORE_ACCEPTANCE_STALE_EVIDENCE))

    return checks


def validate_acceptance_finding(finding: Any, judged: Any = None,
                                strict: bool = False) -> List[Check]:
    """Rails that hold for ONE criterion's finding."""
    invalid = C.CORE_ACCEPTANCE_INVALID
    checks: List[Check] = []

    if not isinstance(finding, dict):
        return [(_FP + "is_object", False,
                 "finding must be an object, got {}".format(type(finding).__name__),
                 invalid)]

    p = "{}{}::".format(_FP, finding.get("constraint_id"))

    missing = [k for k in FINDING_REQUIRED if k not in finding]
    checks.append((p + "required", not missing,
                   "missing required key(s) {}".format(missing) if missing
                   else "all required keys present",
                   None if not missing else invalid))

    if strict:
        unknown = sorted(set(finding) - set(FINDING_ALLOWED))
        checks.append((p + "no_unknown_fields", not unknown,
                       "unknown key(s) {}".format(unknown) if unknown
                       else "no unknown keys", None if not unknown else invalid))

    sv = finding.get("schema_version")
    ok = sv == RT_ACCEPTANCE_FINDING
    checks.append((p + "schema_version", ok,
                   "schema_version must be {!r} (got {!r})".format(
                       RT_ACCEPTANCE_FINDING, sv),
                   None if ok else invalid))

    klass = finding.get("constraint_class")
    ok = klass in K.CONSTRAINT_CLASSES
    checks.append((p + "class_known", ok,
                   "constraint_class {!r} is not one of {}".format(
                       klass, K.CONSTRAINT_CLASSES),
                   None if ok else C.CORE_CONSTRAINT_UNKNOWN_CLASS))

    evaluation = finding.get("evaluation")
    ok = evaluation in tri.TRI_VALUES
    checks.append((p + "evaluation_is_tri", ok,
                   "evaluation {!r} is not one of {}".format(evaluation,
                                                             tri.TRI_VALUES),
                   None if ok else invalid))

    lb = finding.get("acceptance_load_bearing")
    expected_lb = klass in K.ACCEPTANCE_LOAD_BEARING
    ok = lb is expected_lb
    checks.append((
        p + "load_bearing_matches_class", ok,
        "finding says acceptance_load_bearing={!r} for class {!r}, but "
        "ACCEPTANCE_LOAD_BEARING is {}; whether a criterion MAY block is a "
        "property of its class, never of this record".format(
            lb, klass, K.ACCEPTANCE_LOAD_BEARING),
        None if ok else C.CORE_CONSTRAINT_CLASS_AUTHORITY_VIOLATION))

    reason = finding.get("blocking_reason")
    if evaluation in tri.TRI_VALUES and expected_lb:
        ok = (reason is None) if tri.accepts(evaluation) else bool(reason)
        checks.append((
            p + "blocking_reason_matches_evaluation", ok,
            "evaluation {} with blocking_reason {!r}; a blocked load-bearing "
            "criterion must say whether it was measured-and-wrong or never "
            "measured, because those route to opposite repairs".format(
                evaluation, reason),
            None if ok else invalid))

    evidence = finding.get("evidence")
    ev_ok = isinstance(evidence, list) and all(isinstance(e, dict)
                                               for e in evidence)
    checks.append((p + "evidence_is_list", ev_ok,
                   "evidence must be a list of rows naming each observation "
                   "consulted", None if ev_ok else invalid))
    if ev_ok:
        for row in evidence:
            checks.extend(validate_acceptance_evidence(row, judged=judged,
                                                       strict=strict))

    # --- THE rail: a SATISFIED criterion rests on reload-backed evidence ------ #
    if evaluation == tri.SATISFIED:
        rows = evidence if ev_ok else []
        reloaded = [r for r in rows if is_reload_backed(r)]
        ok = bool(reloaded) and len(reloaded) == len(rows)
        checks.append((
            p + "satisfied_rests_on_reload_backed_evidence", ok,
            "evaluation is SATISFIED but the finding cites {} evidence row(s), of "
            "which {} are reload-backed; an in-memory world can satisfy criteria "
            "a saved-and-reloaded one does not, so this verdict would be about a "
            "world that was never persisted".format(len(rows), len(reloaded)),
            None if ok else C.CORE_ACCEPTANCE_NOT_RELOADED))

    # --- the verdict must follow from the record ------------------------------ #
    if isinstance(judged, dict):
        recomputed = _recompute_from_record(finding, judged)
        ok = recomputed == evaluation
        checks.append((
            p + "verdict_follows_from_evidence", ok,
            "recorded evaluation {!r} but the evidence written into this finding "
            "supports {!r}; a verdict its own record does not support cannot be "
            "audited by anyone who was not present when it was produced".format(
                evaluation, recomputed),
            None if ok else invalid))

    return checks


def validate_acceptance_result(obj: Any, strict: bool = False) -> List[Check]:
    """Validate ONE acceptance result, findings and evidence included.

    The verdict is re-derived from the per-finding evidence rows and from this
    module's own reading of ``constraints.ACCEPTANCE_LOAD_BEARING`` -- never by
    calling ``evaluate_acceptance`` or ``fold_acceptance`` on the producer's own
    evaluations, which would agree by construction and check nothing.

    WF1257's validator raise site lives here: a record that CLAIMS acceptance
    while its own evidence re-derives to UNKNOWN.
    """
    invalid = C.CORE_ACCEPTANCE_INVALID
    checks: List[Check] = []

    if not isinstance(obj, dict):
        return [(_P + "is_object", False,
                 "acceptance result must be an object, got {}".format(
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
    ok = sv == RT_ACCEPTANCE_RESULT
    checks.append((_P + "schema_version", ok,
                   "schema_version must be {!r} (got {!r})".format(
                       RT_ACCEPTANCE_RESULT, sv), None if ok else invalid))

    outcome = obj.get("outcome")
    ok = outcome in ACCEPTANCE_OUTCOMES
    checks.append((_P + "outcome_known", ok,
                   "outcome {!r} is not one of {}".format(outcome,
                                                          ACCEPTANCE_OUTCOMES),
                   None if ok else invalid))

    verdict = obj.get("acceptance_verdict")
    ok = verdict in tri.TRI_VALUES
    checks.append((_P + "verdict_is_tri", ok,
                   "acceptance_verdict {!r} is not one of {}".format(
                       verdict, tri.TRI_VALUES), None if ok else invalid))

    accepted = obj.get("accepted")
    ok = isinstance(accepted, bool)
    checks.append((_P + "accepted_is_bool", ok,
                   "accepted must be an explicit boolean (got {!r}); a claim that "
                   "is not stated cannot be contradicted".format(accepted),
                   None if ok else invalid))

    judged_flag = obj.get("judged")
    ok = isinstance(judged_flag, bool)
    checks.append((_P + "judged_is_bool", ok,
                   "judged must be an explicit boolean (got {!r})".format(
                       judged_flag), None if ok else invalid))

    judged = obj.get("judged_operation")
    j_ok = isinstance(judged, dict)
    checks.append((_P + "judged_operation_is_object", j_ok,
                   "judged_operation must be an object naming the operation this "
                   "verdict is about", None if j_ok else invalid))
    if j_ok:
        missing = [k for k in JUDGED_OPERATION_REQUIRED if k not in judged]
        checks.append((_P + "judged_operation_required", not missing,
                       "judged_operation missing key(s) {}".format(missing)
                       if missing else "judged_operation states every required key",
                       None if not missing else invalid))

    findings = obj.get("findings")
    f_ok = isinstance(findings, list)
    checks.append((_P + "findings_is_list", f_ok,
                   "findings must be a list", None if f_ok else invalid))
    findings = findings if f_ok else []

    # --- THE headline rail: accepted must be tri.accepts(verdict) ------------- #
    if isinstance(accepted, bool) and verdict in tri.TRI_VALUES:
        ok = accepted is tri.accepts(verdict)
        code = (C.CORE_ACCEPTANCE_ON_UNKNOWN
                if (accepted and verdict == tri.UNKNOWN) else invalid)
        checks.append((
            _P + "accepted_is_tri_accepts_not_not_violated", ok,
            "record claims accepted={!r} with acceptance_verdict {!r}. Acceptance "
            "is tri.accepts(fold) -- deliberately NOT 'fold != VIOLATED'. The two "
            "differ exactly on UNKNOWN, and accepting there means everything "
            "'passed' because nothing was measured".format(accepted, verdict),
            None if ok else code))

    if outcome == OUTCOME_ACCEPTED:
        ok = accepted is True and verdict == tri.SATISFIED
        checks.append((
            _P + "accepted_outcome_matches_verdict", ok,
            "outcome is {!r} with accepted={!r} and verdict {!r}".format(
                OUTCOME_ACCEPTED, accepted, verdict),
            None if ok else (C.CORE_ACCEPTANCE_ON_UNKNOWN
                             if verdict == tri.UNKNOWN else invalid)))

    # --- a partial commit can NEVER be accepted ------------------------------- #
    if j_ok and D.is_partial_commit(judged.get("delta_outcome")):
        ok = accepted is not True and outcome == OUTCOME_PARTIAL_COMMIT
        checks.append((
            _P + "partial_commit_is_never_accepted", ok,
            "the delta under judgement is a partial commit but the result records "
            "outcome={!r} accepted={!r}; that world is neither committed nor "
            "rolled back, no contract describes it, and it must be reported as "
            "{!r} rather than rounded to an acceptance or a rejection".format(
                outcome, accepted, OUTCOME_PARTIAL_COMMIT),
            None if ok else C.CORE_DELTA_PARTIAL_COMMIT))

    # --- refusal coherence ---------------------------------------------------- #
    if judged_flag is False:
        ok = verdict == tri.UNKNOWN
        checks.append((
            _P + "refusal_verdict_is_unknown", ok,
            "the result refused to judge but records acceptance_verdict {!r}; "
            "folding zero findings returns SATISFIED by tri.conj's identity, so a "
            "refusal that is not written out as UNKNOWN reads, downstream, as an "
            "acceptance nobody computed".format(verdict),
            None if ok else invalid))
        ok = not findings
        checks.append((
            _P + "refusal_emits_no_findings", ok,
            "the result refused to judge but carries {} finding(s); a verdict "
            "produced against a judgement that was never established is a "
            "confident statement about an unknown subject".format(len(findings)),
            None if ok else invalid))
        ok = bool(obj.get("refusal_reason"))
        checks.append((_P + "refusal_states_a_reason", ok,
                       "a refusal must say why; an unexplained refusal is "
                       "indistinguishable from a crash", None if ok else invalid))
        # A refusal judged NOTHING, so every load-bearing criterion is unmeasured
        # by definition. Claiming acceptance there is WF1257 in its purest form --
        # everything "passed" because the judgement never ran.
        ok = accepted is not True
        checks.append((_P + "refusal_is_not_an_acceptance", ok,
                       "the result refused to judge but records accepted={!r}; a "
                       "refusal measured nothing, so every load-bearing criterion "
                       "is unknown and acceptance cannot be claimed over it"
                       .format(accepted),
                       None if ok else C.CORE_ACCEPTANCE_ON_UNKNOWN))
        ok = outcome in UNJUDGED_OUTCOMES
        checks.append((_P + "refusal_outcome_is_unjudged", ok,
                       "a refusal must carry an outcome from {} (got {!r})".format(
                           UNJUDGED_OUTCOMES, outcome), None if ok else invalid))

    # --- every finding -------------------------------------------------------- #
    for f in findings:
        checks.extend(validate_acceptance_finding(
            f, judged=judged if j_ok else None, strict=strict))

    # --- the verdict, re-derived from the evidence ---------------------------- #
    if judged_flag is True and j_ok:
        recomputed: List[str] = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            if f.get("constraint_class") not in K.ACCEPTANCE_LOAD_BEARING:
                continue
            recomputed.append(_recompute_from_record(f, judged))
        want = tri.conj(recomputed)
        ok = verdict == want
        code = (C.CORE_ACCEPTANCE_ON_UNKNOWN
                if (want == tri.UNKNOWN and verdict == tri.SATISFIED) else invalid)
        checks.append((
            _P + "verdict_follows_from_findings", ok,
            "recorded acceptance_verdict {!r}, but folding the load-bearing "
            "findings re-derived from their OWN evidence rows gives {!r}. "
            "Re-derived here rather than by re-running the evaluator, which would "
            "agree by construction".format(verdict, want),
            None if ok else code))

        blocking = sorted(str(f.get("constraint_id")) for f in findings
                          if isinstance(f, dict)
                          and f.get("constraint_class") in K.ACCEPTANCE_LOAD_BEARING
                          and _recompute_from_record(f, judged) in (tri.VIOLATED,
                                                                    tri.UNKNOWN))
        blockers = obj.get("blockers")
        listed = sorted(str(b.get("constraint_id")) for b in blockers
                        if isinstance(b, dict)) if isinstance(blockers, list) \
            else None
        ok = listed is not None and listed == blocking
        checks.append((
            _P + "blockers_match_blocking_findings", ok,
            "blockers list {!r} but the load-bearing findings that block are {!r}; "
            "an unlisted blocker is a criterion nothing will ever go resolve"
            .format(listed, blocking), None if ok else invalid))

        # Every load-bearing criterion an ACCEPTED result rests on must cite a
        # reload-backed row. Checked separately from the fold because a producer
        # could fold SATISFIED from rows it also marked usable.
        if outcome == OUTCOME_ACCEPTED:
            unreloaded = sorted(
                str(f.get("constraint_id")) for f in findings
                if isinstance(f, dict)
                and f.get("constraint_class") in K.ACCEPTANCE_LOAD_BEARING
                and not any(is_reload_backed(r)
                            for r in (f.get("evidence") or [])
                            if isinstance(r, dict)))
            ok = not unreloaded
            checks.append((
                _P + "acceptance_rests_on_a_reload_backed_observation", ok,
                "the result was ACCEPTED but load-bearing criteri(a) {} cite no "
                "reload-backed observation; an in-memory world can satisfy "
                "criteria a saved-and-reloaded one does not".format(unreloaded),
                None if ok else C.CORE_ACCEPTANCE_NOT_RELOADED))

    return checks


# --------------------------------------------------------------------------- #
# canonical example factories (``**over`` spawns the known-bads)
#
# Domain-neutral by construction: the criteria come from the contracts lane's own
# canonical example, and every evidence row's constraint_id is DERIVED from it
# rather than retyped, so this module names no consumer's vocabulary at all.
# --------------------------------------------------------------------------- #
EXAMPLE_APPLIED_AT = 10


def _example_criteria(**over: Any) -> Dict[str, Any]:
    return AC._example_acceptance_criteria(**over)


def _example_delta(**over: Any) -> Dict[str, Any]:
    return D._example_world_delta(**over)


def _example_evidence(**over: Any) -> Dict[str, Any]:
    """ONE canonical reload-backed evidence row."""
    d: Dict[str, Any] = {
        "evidence_id": "ev_0001",
        "constraint_id": None,
        "operation_id": "op_0001",
        "observed_at": EXAMPLE_APPLIED_AT + 1,
        "observation_kind": OBS_RELOADED,
        "reload_backed": True,
        "supports": tri.SATISFIED,
        "evidence_refs": ["raw_observation_log"],
        "observed_by": "acceptance_observer",
        "detail": "measured after the world was saved and read back from disk",
        "schema_version": RT_ACCEPTANCE_EVIDENCE,
    }
    d.update(over)
    return d


def _example_evidence_set(criteria: Any = None,
                          **over: Any) -> List[Dict[str, Any]]:
    """One reload-backed row per declared criterion.

    Built by iterating the criteria rather than by listing ids: a hand-written set
    would embed the contracts lane's vocabulary here and would drift the moment
    that lane edits its example.
    """
    # A non-dict ``criteria`` is one of the known-bads this factory's callers
    # spawn; the evidence stays canonical so the malformed input is the only
    # thing under test.
    criteria = criteria if isinstance(criteria, dict) else _example_criteria()
    rows: List[Dict[str, Any]] = []
    for idx, c in enumerate(_dict_list(criteria.get("constraints"))):
        rows.append(_example_evidence(
            evidence_id="ev_{:04d}".format(idx + 1),
            constraint_id=c.get("constraint_id"), **over))
    return rows


def _example_acceptance_result(**over: Any) -> Dict[str, Any]:
    """Canonical-valid result, produced by running the real evaluator.

    Built rather than written: a hand-authored example proves the shape somebody
    typed, not the shape the evaluator emits, and the two drift on the first edit.

    ``pop`` with a ``None`` sentinel, never ``or``: an override of ``[]`` is a
    DELIBERATE empty input -- "no evidence at all" is one of the known-bads this
    factory exists to spawn -- and ``or`` would silently substitute the canonical
    value for it.
    """
    criteria = over.pop("criteria", None)
    delta = over.pop("delta", None)
    evidence = over.pop("evidence", None)
    applied_at = over.pop("applied_at", None)
    criteria = _example_criteria() if criteria is None else criteria
    delta = _example_delta() if delta is None else delta
    evidence = _example_evidence_set(criteria) if evidence is None else evidence
    applied_at = EXAMPLE_APPLIED_AT if applied_at is None else applied_at
    d = evaluate_acceptance(criteria, delta, evidence, applied_at)
    d.update(over)
    return d
