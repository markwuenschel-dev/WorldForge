#!/usr/bin/env python3
"""wfcore.transaction.delta -- what a world change RECORDS about itself.

WHY A RECORD AND NOT A LOG LINE
-------------------------------
"We changed some things and it worked" is unfalsifiable. To be able to undo a
change, to prove it stayed inside what was authorised, and to say honestly
whether it is now committed, this layer has to hold four facts per mutation that
a log line never carries:

    WHAT was touched     target_kind + target_path, the same address space the
                         plan step used when it declared its bound
    WHO touched it       step_id + provider_id, so an out-of-bounds write is
                         attributable rather than merely detected
    WHAT IT WAS BEFORE   a before-state sufficient to restore it -- not a
                         description of it, the state itself
    WHAT WE SAW AFTER    observations taken after apply and after undo, kept
                         separate from what was EXPECTED, so the two can disagree

THE BOUND
---------
A plan step declares ``expected_changed_packages`` and ``expected_changed_actors``.
Together they ARE the mutation bound: the closed set of addresses that step is
permitted to alter. ``bound_from_step`` lifts them into a bound record and
``classify_target`` is the single place membership is decided, so the matching
rule cannot drift between the preflight check and the post-apply check.

Membership is EXACT, never prefix or glob. A bound that matches by prefix is a
bound the author cannot enumerate, and one that accepts ``*`` is not a bound at
all -- both are refused by the validator (WF1246). The cost of exactness is that
a step must list what it touches; that cost is the entire mechanism.

An empty bound is legal but must be SIGNED. ``allowed_packages: []`` plus
``allowed_actors: []`` is indistinguishable from an author who never filled the
field in, and the two have opposite correct readings: a step that genuinely
mutates nothing is a real and checkable claim, while an unfilled bound silently
refuses every mutation and reads, in a report, as a clean run. So "I mutate
nothing" must be declared with ``declares_no_mutation`` -- the same discipline
``wfcore.providers.base`` applies to an empty ``side_effects`` list.

STATE IS THREE-VALUED AT THE EDGE
---------------------------------
An observation can come back PRESENT, ABSENT, or UNMEASURED, and the third is not
a variant of the second. "The target is not there" and "we could not look" have
opposite consequences for rollback: the first says an undo of a create succeeded,
the second says we have no idea whether it did. So ``states_equal`` returns a
``wfcore.tri`` value and returns UNKNOWN whenever either side is unmeasured. Every
fold in this module goes through ``tri.conj``, so an unmeasured target propagates
as unknown instead of being quietly counted as a match.

THE FIVE OUTCOMES, AND WHY PARTIAL COMMIT IS ONE OF THEM
--------------------------------------------------------
    REFUSED               nothing was applied; the request never earned a mutation
    COMMITTED             applied AND the postconditions were MEASURED to hold
    COMMITTED_UNVERIFIED  applied, but no post-observation supports the claim
    ROLLED_BACK           applied then undone, and re-observation CONFIRMED it
    PARTIAL_COMMIT        applied, undo attempted, restoration not confirmed

The last one exists so it never has to be rounded into one of the others.
``is_committed`` and ``is_rolled_back`` both return False for it, by design: a
caller must not be able to write ``if not committed: retry`` and quietly retry on
top of a world that is half-changed.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from .. import tri
from ..failure import FailureCode as C
from ..providers import base as PB

# --------------------------------------------------------------------------- #
# schema identity (house convention: wf.<domain>.<thing>.v<N>)
# --------------------------------------------------------------------------- #
RT_MUTATION = "wf.core.mutation.v1"
RT_MUTATION_BOUND = "wf.core.mutation_bound.v1"
RT_WORLD_DELTA = "wf.core.world_delta.v1"

Check = Tuple[str, bool, str, Optional[str]]

# --------------------------------------------------------------------------- #
# the address space. TWO kinds, matching the two lists a plan step declares.
# --------------------------------------------------------------------------- #
TARGET_PACKAGE = "package"
TARGET_ACTOR = "actor"
TARGET_KINDS = (TARGET_PACKAGE, TARGET_ACTOR)

# --------------------------------------------------------------------------- #
# what can be done to a target
# --------------------------------------------------------------------------- #
OP_CREATE = "create"
OP_MODIFY = "modify"
OP_DELETE = "delete"
MUTATION_OPS = (OP_CREATE, OP_MODIFY, OP_DELETE)

# --------------------------------------------------------------------------- #
# observed state. UNMEASURED is a first-class kind, not a missing value.
# --------------------------------------------------------------------------- #
STATE_PRESENT = "present"
STATE_ABSENT = "absent"
STATE_UNMEASURED = "unmeasured"
STATE_KINDS = (STATE_PRESENT, STATE_ABSENT, STATE_UNMEASURED)

# --------------------------------------------------------------------------- #
# per-mutation lifecycle.
#
# ROLLBACK_UNVERIFIED is separate from ROLLBACK_FAILED on purpose. "we undid it
# and re-observation showed the old state is NOT back" is a measured failure that
# a repair path can act on. "we undid it and could not look" is an unknown, and
# recording it as a failure would send repair after a defect nobody observed --
# the exact coercion wfcore.tri exists to prevent.
# --------------------------------------------------------------------------- #
MUT_PLANNED = "planned"
MUT_REFUSED = "refused"
MUT_APPLIED = "applied"
MUT_APPLY_FAILED = "apply_failed"
MUT_ROLLED_BACK = "rolled_back"
MUT_ROLLBACK_FAILED = "rollback_failed"
MUT_ROLLBACK_UNVERIFIED = "rollback_unverified"
MUT_UNRECOVERABLE = "unrecoverable"
MUTATION_STATUSES = (
    MUT_PLANNED, MUT_REFUSED, MUT_APPLIED, MUT_APPLY_FAILED,
    MUT_ROLLED_BACK, MUT_ROLLBACK_FAILED, MUT_ROLLBACK_UNVERIFIED,
    MUT_UNRECOVERABLE,
)

# Statuses meaning "this mutation is, as far as anyone can tell, still in the
# world". Read by the coherence rails so the list is stated once.
STATUSES_STILL_IN_WORLD = (
    MUT_APPLIED, MUT_APPLY_FAILED, MUT_ROLLBACK_FAILED,
    MUT_ROLLBACK_UNVERIFIED, MUT_UNRECOVERABLE,
)

# --------------------------------------------------------------------------- #
# delta-level outcomes
# --------------------------------------------------------------------------- #
DELTA_REFUSED = "refused"
DELTA_COMMITTED = "committed"
DELTA_COMMITTED_UNVERIFIED = "committed_unverified"
DELTA_ROLLED_BACK = "rolled_back"
DELTA_PARTIAL_COMMIT = "partial_commit"
DELTA_OUTCOMES = (DELTA_REFUSED, DELTA_COMMITTED, DELTA_COMMITTED_UNVERIFIED,
                  DELTA_ROLLED_BACK, DELTA_PARTIAL_COMMIT)

# --------------------------------------------------------------------------- #
# bound membership verdicts
# --------------------------------------------------------------------------- #
TARGET_IN_BOUND = "in_bound"
TARGET_OUT_OF_BOUNDS = "out_of_bounds"
TARGET_PROTECTED = "protected"
TARGET_UNBOUNDED = "unbounded"          # the step declared no bound at all
TARGET_VERDICTS = (TARGET_IN_BOUND, TARGET_OUT_OF_BOUNDS,
                   TARGET_PROTECTED, TARGET_UNBOUNDED)

# --------------------------------------------------------------------------- #
# the PLAN STEP field names this layer reads. Named constants because the
# plan lane and this lane must agree on exactly these two lists and nothing else;
# a typo'd field name would silently produce an empty -- and therefore total --
# bound, which fails closed but for an invisible reason.
# --------------------------------------------------------------------------- #
STEP_FIELD_PACKAGES = "expected_changed_packages"
STEP_FIELD_ACTORS = "expected_changed_actors"
STEP_FIELD_ID = "step_id"
STEP_FIELD_PROVIDER = "selected_provider"
STEP_FIELD_ROLLBACK = "rollback"

# --------------------------------------------------------------------------- #
# record shapes
# --------------------------------------------------------------------------- #
BOUND_REQUIRED = ("step_id", "allowed_packages", "allowed_actors", "schema_version")
BOUND_ALLOWED = BOUND_REQUIRED + (
    "protected_paths",        # addresses that must not be touched even if in bound
    "declares_no_mutation",   # the SIGNED empty bound
    "notes",
)

MUTATION_REQUIRED = (
    "mutation_id", "step_id", "provider_id", "target_kind", "target_path",
    "operation", "before_state", "status", "rollback_mode", "schema_version",
)
MUTATION_ALLOWED = MUTATION_REQUIRED + (
    "before_state_declared",     # what the plan THOUGHT was there (advisory)
    "expected_after_state",      # the postcondition, as a state record
    "observed_after_apply",      # what we MEASURED after applying
    "observed_after_rollback",   # what we MEASURED after undoing
    "undo_reported_ok",          # the undo's opinion of itself; NEVER the verdict
    "undo_error",
    "restoration",               # tri: did re-observation confirm the undo?
    "verification",              # tri: did re-observation confirm the postcondition?
    "unrecoverable_reason",
    "evidence_refs", "detail", "notes",
)

WORLD_DELTA_REQUIRED = (
    "delta_id", "operation_id", "outcome", "bounds", "mutations",
    "evidence_refs", "schema_version",
)
WORLD_DELTA_ALLOWED = WORLD_DELTA_REQUIRED + (
    "report_type", "created_by", "created_at", "abort_reason",
    "failure_codes", "verification", "rollback_completeness",
    "bound_enforcement", "lock", "journal_path", "detail", "notes",
)


# --------------------------------------------------------------------------- #
# small local helpers (hand-rolled, mirroring wfcore.constraints/providers.base)
# --------------------------------------------------------------------------- #
def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _str_list(value: Any) -> bool:
    return (isinstance(value, (list, tuple))
            and all(_nonempty_str(v) for v in value))


def canonical(value: Any) -> str:
    """Stable serialization used for state comparison.

    Sorted keys so two equal payloads authored in different orders compare equal;
    ``default=str`` so an exotic value degrades into a comparable string rather
    than raising in the middle of a rollback verdict.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


# --------------------------------------------------------------------------- #
# state records
# --------------------------------------------------------------------------- #
def present_state(payload: Any) -> Dict[str, Any]:
    """The target exists, and this is what it holds -- enough to restore it."""
    return {"state_kind": STATE_PRESENT, "payload": payload}


def absent_state() -> Dict[str, Any]:
    """The target was MEASURED and is not there. Distinct from unmeasured."""
    return {"state_kind": STATE_ABSENT}


def unmeasured_state(reason: str = "no observation was taken") -> Dict[str, Any]:
    """We did not, or could not, look. Carries the reason so it is actionable."""
    return {"state_kind": STATE_UNMEASURED, "reason": reason}


def is_state(value: Any) -> bool:
    return isinstance(value, dict) and value.get("state_kind") in STATE_KINDS


def is_measured(value: Any) -> bool:
    """True only for a state that came from a real observation."""
    return is_state(value) and value.get("state_kind") != STATE_UNMEASURED


def states_equal(a: Any, b: Any) -> str:
    """Compare two states. Returns a TRI value, not a bool.

    UNKNOWN whenever either side is unmeasured or malformed. This is the single
    most important boolean-avoidance in the package: a rollback verdict computed
    from an unmeasured observation would read as "restored" for exactly the
    targets nobody could check.
    """
    if not (is_state(a) and is_state(b)):
        return tri.UNKNOWN
    if not (is_measured(a) and is_measured(b)):
        return tri.UNKNOWN
    return tri.from_bool(canonical(a) == canonical(b), measured=True)


# --------------------------------------------------------------------------- #
# path normalization + bound construction
# --------------------------------------------------------------------------- #
def normalize_target_path(path: Any) -> str:
    """Normalize an address for EXACT comparison.

    Deliberately minimal: separator form, surrounding whitespace, and a trailing
    separator. It does NOT resolve, lowercase, or shorten anything -- every such
    step is a place where two different addresses could be made to look like one,
    and this function's output is what decides whether a write was authorised.
    """
    if not isinstance(path, str):
        return ""
    return path.strip().replace("\\", "/").rstrip("/")


def bound_from_step(step: Any) -> Dict[str, Any]:
    """Lift a plan step's declared mutation bound into a bound record.

    Reads ONLY ``expected_changed_packages`` and ``expected_changed_actors``.
    Those two lists together are the bound; nothing else in the step widens it.
    """
    step = step if isinstance(step, dict) else {}
    packages = step.get(STEP_FIELD_PACKAGES) or []
    actors = step.get(STEP_FIELD_ACTORS) or []
    bound: Dict[str, Any] = {
        "step_id": step.get(STEP_FIELD_ID),
        "allowed_packages": [normalize_target_path(p) for p in packages
                             if _nonempty_str(p)],
        "allowed_actors": [normalize_target_path(a) for a in actors
                           if _nonempty_str(a)],
        "schema_version": RT_MUTATION_BOUND,
    }
    if not bound["allowed_packages"] and not bound["allowed_actors"]:
        # Carry the signature through only when the step really declared both
        # lists as empty; an absent field stays unsigned and fails validation.
        if (isinstance(step.get(STEP_FIELD_PACKAGES), (list, tuple))
                and isinstance(step.get(STEP_FIELD_ACTORS), (list, tuple))):
            bound["declares_no_mutation"] = True
    return bound


def index_bounds(bounds: Any) -> Dict[Any, Dict[str, Any]]:
    """step_id -> bound. A later duplicate does NOT overwrite an earlier one.

    Duplicates are caught by ``validate_world_delta``; keeping the first here
    means a duplicate can never be used to WIDEN a bound by shadowing it, even if
    a caller skips validation.
    """
    out: Dict[Any, Dict[str, Any]] = {}
    for b in bounds or []:
        if isinstance(b, dict) and b.get("step_id") not in out:
            out[b.get("step_id")] = b
    return out


def classify_target(bound: Any, target_kind: Any, target_path: Any) -> Tuple[str, Optional[str], str]:
    """Decide whether ONE address may be touched. Returns (verdict, code, detail).

    The single membership rule in the package -- the preflight check and the
    post-apply actual-touch check both call it, so they cannot disagree about
    what "inside the bound" means.

    Protection is tested FIRST and independently of membership: a protected
    address that also appears in the allowed list is still protected. A
    PROTECTED_SEMANTICS statement is a stronger claim than a step's own
    declaration of intent, and letting the step's list win would let a plan
    authorise itself past the consumer's protection.
    """
    path = normalize_target_path(target_path)
    if not isinstance(bound, dict):
        return (TARGET_UNBOUNDED, C.CORE_DELTA_OUT_OF_BOUNDS,
                "no bound was declared for this mutation's step; an unbounded "
                "mutation is refused rather than allowed, because the absence of "
                "a declaration is the absence of authorisation")

    protected = [normalize_target_path(p) for p in (bound.get("protected_paths") or [])]
    if path in protected:
        return (TARGET_PROTECTED, C.CORE_PROTECTED_CONTENT_TOUCHED,
                "{} {!r} is declared protected by step {!r}; protection is "
                "checked before membership, so a protected address cannot be "
                "unlocked by also listing it as expected".format(
                    target_kind, path, bound.get("step_id")))

    if target_kind == TARGET_PACKAGE:
        allowed = [normalize_target_path(p) for p in (bound.get("allowed_packages") or [])]
    elif target_kind == TARGET_ACTOR:
        allowed = [normalize_target_path(p) for p in (bound.get("allowed_actors") or [])]
    else:
        return (TARGET_OUT_OF_BOUNDS, C.CORE_DELTA_OUT_OF_BOUNDS,
                "target_kind {!r} is not one of {}; an address in an unknown "
                "space cannot be checked against any bound".format(
                    target_kind, TARGET_KINDS))

    if path in allowed:
        return (TARGET_IN_BOUND, None,
                "{} {!r} is inside the bound declared by step {!r}".format(
                    target_kind, path, bound.get("step_id")))
    return (TARGET_OUT_OF_BOUNDS, C.CORE_DELTA_OUT_OF_BOUNDS,
            "{} {!r} is NOT in step {!r}'s declared {} bound {}; the bound is the "
            "authorisation, so a write outside it is refused even though the "
            "provider evidently intended it".format(
                target_kind, path, bound.get("step_id"), target_kind, allowed))


# --------------------------------------------------------------------------- #
# folds over a delta -- all three-valued
# --------------------------------------------------------------------------- #
def _mutation_verification(mutation: Dict[str, Any]) -> str:
    """Did a post-observation CONFIRM this mutation's declared postcondition?

    UNKNOWN when the mutation declared no ``expected_after_state`` (there is
    nothing to confirm), and UNKNOWN when no observation was taken. Both cases
    must block a verified commit: a postcondition that was never stated and one
    that was never measured are equally unproven.
    """
    expected = mutation.get("expected_after_state")
    observed = mutation.get("observed_after_apply")
    if not is_state(expected):
        return tri.UNKNOWN
    return states_equal(expected, observed)


def verification_status(delta: Dict[str, Any]) -> str:
    """Fold every applied mutation's post-observation into ONE tri-value."""
    values = [_mutation_verification(m)
              for m in (delta.get("mutations") or [])
              if isinstance(m, dict)
              and m.get("status") in (MUT_APPLIED, MUT_ROLLED_BACK,
                                      MUT_ROLLBACK_FAILED, MUT_ROLLBACK_UNVERIFIED)]
    return tri.conj(values)


def _mutation_restoration(mutation: Dict[str, Any]) -> str:
    """Did RE-OBSERVATION confirm the undo put the old state back?

    Reads ``observed_after_rollback`` against ``before_state``. It does not read
    ``undo_reported_ok`` -- that field is recorded for diagnosis and is
    deliberately not an input to this verdict.
    """
    return states_equal(mutation.get("before_state"),
                        mutation.get("observed_after_rollback"))


def rollback_completeness(delta: Dict[str, Any]) -> str:
    """Fold restoration over every mutation a rollback was attempted for.

    A mutation recorded as UNRECOVERABLE folds in as VIOLATED: we know it is
    still in the world and we know we never captured a before-state for it, so
    this is a measured fact rather than an unknown.
    """
    values: List[str] = []
    for m in (delta.get("mutations") or []):
        if not isinstance(m, dict):
            continue
        if m.get("status") == MUT_UNRECOVERABLE:
            values.append(tri.VIOLATED)
        elif m.get("status") in (MUT_ROLLED_BACK, MUT_ROLLBACK_FAILED,
                                 MUT_ROLLBACK_UNVERIFIED):
            values.append(_mutation_restoration(m))
    return tri.conj(values)


def status_from_restoration(restoration: str) -> str:
    """Map a restoration tri-value onto the per-mutation status. One place only."""
    if restoration == tri.SATISFIED:
        return MUT_ROLLED_BACK
    if restoration == tri.VIOLATED:
        return MUT_ROLLBACK_FAILED
    return MUT_ROLLBACK_UNVERIFIED


# --------------------------------------------------------------------------- #
# outcome predicates -- the guard against rounding PARTIAL_COMMIT off
# --------------------------------------------------------------------------- #
def is_committed(outcome: str) -> bool:
    """True only when the mutations are, as a whole, in the world."""
    return outcome in (DELTA_COMMITTED, DELTA_COMMITTED_UNVERIFIED)


def is_rolled_back(outcome: str) -> bool:
    """True only when restoration was CONFIRMED for every mutation."""
    return outcome == DELTA_ROLLED_BACK


def is_partial_commit(outcome: str) -> bool:
    return outcome == DELTA_PARTIAL_COMMIT


def commit_is_verified(outcome: str) -> bool:
    """True only for a commit whose postconditions were MEASURED to hold.

    ``DELTA_COMMITTED_UNVERIFIED`` returns False here while returning True from
    ``is_committed``: the change is in the world, and the claim that it is the
    RIGHT change is unsupported. Those are different questions and the two
    predicates keep them apart.
    """
    return outcome == DELTA_COMMITTED


# --------------------------------------------------------------------------- #
# validators
# --------------------------------------------------------------------------- #
def validate_mutation_bound(bound: Any, strict: bool = False) -> List[Check]:
    """Validate ONE bound record, including the signed-empty-bound rail."""
    checks: List[Check] = []
    code = C.CORE_DELTA_INVALID

    if not isinstance(bound, dict):
        return [("bound_is_object", False,
                 "bound must be an object, got {}".format(type(bound).__name__), code)]

    for fld in BOUND_REQUIRED:
        present = bound.get(fld) is not None
        checks.append(("bound_has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else code))

    checks.append(("bound_step_id_nonempty", _nonempty_str(bound.get("step_id")),
                   "step_id must be a non-empty string (got {!r}); an unattributed "
                   "bound cannot be matched to the mutations it governs".format(
                       bound.get("step_id")),
                   None if _nonempty_str(bound.get("step_id")) else code))

    for fld in ("allowed_packages", "allowed_actors"):
        value = bound.get(fld)
        ok = _str_list(value)
        checks.append(("bound_{}_is_string_list".format(fld), ok,
                       "{} must be a list of non-empty strings (got {!r})".format(fld, value),
                       None if ok else code))
        if isinstance(value, (list, tuple)):
            bad = sorted({v for v in value if isinstance(v, str)
                          and ("*" in v or "?" in v or normalize_target_path(v) == "")})
            ok = not bad
            checks.append(("bound_{}_no_wildcards".format(fld), ok,
                           "entries {} contain a wildcard or normalize to empty; a "
                           "bound that matches by pattern is not a bound its author "
                           "can enumerate, and an empty entry would authorise a "
                           "path nobody named".format(bad) if bad
                           else "every entry is an exact, non-empty address",
                           None if ok else code))
            dupes = sorted({v for v in value if list(value).count(v) > 1})
            checks.append(("bound_{}_unique".format(fld), not dupes,
                           "duplicate entries {}".format(dupes) if dupes
                           else "no duplicate entries", None if not dupes else code))

    # RAIL: an empty bound must be SIGNED, exactly as an empty side-effect list is.
    empty = (not (bound.get("allowed_packages") or [])
             and not (bound.get("allowed_actors") or []))
    if empty:
        signed = bound.get("declares_no_mutation") is True
        checks.append(("bound_empty_is_signed", signed,
                       "step {!r} declares an empty bound; an unsigned empty bound "
                       "is indistinguishable from a field nobody filled in, and it "
                       "refuses every mutation while reading in a report as a clean "
                       "run. Set declares_no_mutation=true to own the claim".format(
                           bound.get("step_id")),
                       None if signed else code))

    protected = bound.get("protected_paths")
    if protected is not None:
        ok = _str_list(protected)
        checks.append(("bound_protected_paths_is_string_list", ok,
                       "protected_paths must be a list of non-empty strings (got "
                       "{!r})".format(protected), None if ok else code))

    sv = bound.get("schema_version")
    ok = sv == RT_MUTATION_BOUND
    checks.append(("bound_schema_version", ok,
                   "schema_version must be {!r} (got {!r})".format(RT_MUTATION_BOUND, sv),
                   None if ok else code))

    if strict:
        extra = sorted(set(bound) - set(BOUND_ALLOWED))
        checks.append(("bound_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))
    return checks


def validate_mutation(mutation: Any, strict: bool = False) -> List[Check]:
    """Validate ONE mutation record.

    The rail that matters is ``before_state``: a mutation whose before-state is
    absent, malformed, or unmeasured cannot be undone, and recording it anyway
    produces a delta that CLAIMS to be reversible. The claim, not the mutation, is
    the danger -- a planner reading it will authorise the next step on the
    strength of an undo that cannot run.
    """
    checks: List[Check] = []
    code = C.CORE_DELTA_INVALID

    if not isinstance(mutation, dict):
        return [("mutation_is_object", False,
                 "mutation must be an object, got {}".format(type(mutation).__name__),
                 code)]

    for fld in MUTATION_REQUIRED:
        present = mutation.get(fld) is not None
        checks.append(("mutation_has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else code))

    for fld in ("mutation_id", "step_id", "provider_id", "target_path"):
        ok = _nonempty_str(mutation.get(fld))
        checks.append(("mutation_{}_nonempty".format(fld), ok,
                       "{} must be a non-empty string (got {!r})".format(
                           fld, mutation.get(fld)),
                       None if ok else code))

    kind = mutation.get("target_kind")
    ok = kind in TARGET_KINDS
    checks.append(("mutation_target_kind_known", ok,
                   "target_kind {!r} must be one of {}".format(kind, TARGET_KINDS),
                   None if ok else code))

    op = mutation.get("operation")
    ok = op in MUTATION_OPS
    checks.append(("mutation_operation_known", ok,
                   "operation {!r} must be one of {}".format(op, MUTATION_OPS),
                   None if ok else code))

    status = mutation.get("status")
    ok = status in MUTATION_STATUSES
    checks.append(("mutation_status_known", ok,
                   "status {!r} must be one of {}".format(status, MUTATION_STATUSES),
                   None if ok else code))

    rb = mutation.get("rollback_mode")
    ok = rb in PB.ROLLBACK_MODES
    checks.append(("mutation_rollback_mode_known", ok,
                   "rollback_mode {!r} must be one of {}; it is copied from the "
                   "declaration of the provider that performed the mutation, so a "
                   "value outside the vocabulary means the mutation is not "
                   "attributable to a declared capability".format(rb, PB.ROLLBACK_MODES),
                   None if ok else code))

    # --- the before-state rail ------------------------------------------------
    before = mutation.get("before_state")
    ok = is_state(before)
    checks.append(("mutation_before_state_is_state_record", ok,
                   "before_state must be a state record with state_kind in {} (got "
                   "{!r}); a mutation without one cannot be undone, and a delta "
                   "that carries it still reads as reversible".format(STATE_KINDS, before),
                   None if ok else code))

    if is_state(before) and status not in (MUT_PLANNED, MUT_REFUSED, MUT_UNRECOVERABLE):
        ok = is_measured(before)
        checks.append(("mutation_before_state_was_measured", ok,
                       "before_state is {!r} for an applied mutation; an unmeasured "
                       "before-state is not a restore point, so any undo built on it "
                       "would be a claim rather than a restoration".format(
                           before.get("state_kind")),
                       None if ok else C.CORE_DELTA_UNVERIFIED))

        # operation/before-state coherence: each op implies what must have been there
        if op == OP_CREATE:
            ok = before.get("state_kind") == STATE_ABSENT
            checks.append(("mutation_create_before_state_absent", ok,
                           "operation is {!r} but before_state is {!r}; a create over "
                           "something that already existed is a modify, and undoing it "
                           "by deletion would destroy content the delta never "
                           "captured".format(OP_CREATE, before.get("state_kind")),
                           None if ok else code))
        elif op in (OP_MODIFY, OP_DELETE):
            ok = before.get("state_kind") == STATE_PRESENT
            checks.append(("mutation_{}_before_state_present".format(op), ok,
                           "operation is {!r} but before_state is {!r}; there is no "
                           "prior content to restore, so the recorded undo cannot "
                           "put anything back".format(op, before.get("state_kind")),
                           None if ok else code))

    if mutation.get("expected_after_state") is not None:
        ok = is_state(mutation.get("expected_after_state"))
        checks.append(("mutation_expected_after_state_is_state_record", ok,
                       "expected_after_state must be a state record (got {!r})".format(
                           mutation.get("expected_after_state")),
                       None if ok else code))

    sv = mutation.get("schema_version")
    ok = sv == RT_MUTATION
    checks.append(("mutation_schema_version", ok,
                   "schema_version must be {!r} (got {!r})".format(RT_MUTATION, sv),
                   None if ok else code))

    if strict:
        extra = sorted(set(mutation) - set(MUTATION_ALLOWED))
        checks.append(("mutation_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))
    return checks


def validate_world_delta(delta: Any, strict: bool = False) -> List[Check]:
    """Validate a WHOLE delta: every member, then the coherence rails.

    The coherence rails are the reason this validator exists. Each one closes a
    way a delta can be internally contradictory while every individual record in
    it validates -- and a contradictory delta is worse than an invalid one,
    because it reads as a clean report of something that did not happen.
    """
    checks: List[Check] = []
    code = C.CORE_DELTA_INVALID

    if not isinstance(delta, dict):
        return [("world_delta_is_object", False,
                 "delta must be an object, got {}".format(type(delta).__name__), code)]

    for fld in WORLD_DELTA_REQUIRED:
        present = delta.get(fld) is not None
        checks.append(("delta_has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else code))

    for fld in ("delta_id", "operation_id"):
        ok = _nonempty_str(delta.get(fld))
        checks.append(("delta_{}_nonempty".format(fld), ok,
                       "{} must be a non-empty string (got {!r})".format(fld, delta.get(fld)),
                       None if ok else code))

    outcome = delta.get("outcome")
    ok = outcome in DELTA_OUTCOMES
    checks.append(("delta_outcome_known", ok,
                   "outcome {!r} must be one of {}".format(outcome, DELTA_OUTCOMES),
                   None if ok else code))

    bounds = delta.get("bounds")
    ok = isinstance(bounds, (list, tuple))
    checks.append(("delta_bounds_is_list", ok,
                   "bounds must be a list (got {!r})".format(type(bounds).__name__),
                   None if ok else code))
    if isinstance(bounds, (list, tuple)):
        for idx, b in enumerate(bounds):
            for (n, sub_ok, d, sub_code) in validate_mutation_bound(b, strict=strict):
                checks.append(("bound[{}].{}".format(idx, n), sub_ok, d, sub_code))
        step_ids = [b.get("step_id") for b in bounds if isinstance(b, dict)]
        dupes = sorted({s for s in step_ids if s is not None and step_ids.count(s) > 1})
        checks.append(("delta_bound_step_ids_unique", not dupes,
                       "duplicate bound step_id(s) {}; two bounds for one step means "
                       "the effective bound depends on lookup order, and the wider "
                       "of the two would eventually win".format(dupes) if dupes
                       else "one bound per step", None if not dupes else code))

    mutations = delta.get("mutations")
    ok = isinstance(mutations, (list, tuple))
    checks.append(("delta_mutations_is_list", ok,
                   "mutations must be a list (got {!r})".format(type(mutations).__name__),
                   None if ok else code))
    if not isinstance(mutations, (list, tuple)):
        return checks

    for idx, m in enumerate(mutations):
        for (n, sub_ok, d, sub_code) in validate_mutation(m, strict=strict):
            checks.append(("mutation[{}].{}".format(idx, n), sub_ok, d, sub_code))

    ids = [m.get("mutation_id") for m in mutations if isinstance(m, dict)]
    dupes = sorted({i for i in ids if i is not None and ids.count(i) > 1})
    checks.append(("delta_mutation_ids_unique", not dupes,
                   "duplicate mutation_id(s) {}; a duplicate makes the rollback "
                   "order ambiguous and lets one record shadow another".format(dupes)
                   if dupes else "all mutation_ids unique",
                   None if not dupes else code))

    # --- RAIL: every mutation is governed by a bound, and stays inside it ------
    by_step = index_bounds(bounds if isinstance(bounds, (list, tuple)) else [])
    out_of_bounds: List[str] = []
    protected_hits: List[str] = []
    unbounded: List[str] = []
    for m in mutations:
        if not isinstance(m, dict) or m.get("status") == MUT_REFUSED:
            continue
        bound = by_step.get(m.get("step_id"))
        verdict, _vcode, _detail = classify_target(
            bound, m.get("target_kind"), m.get("target_path"))
        if verdict == TARGET_UNBOUNDED:
            unbounded.append(str(m.get("mutation_id")))
        elif verdict == TARGET_PROTECTED:
            protected_hits.append(str(m.get("mutation_id")))
        elif verdict == TARGET_OUT_OF_BOUNDS:
            out_of_bounds.append(str(m.get("mutation_id")))

    checks.append(("delta_every_mutation_is_bounded", not unbounded,
                   "mutation(s) {} name a step with no bound in this delta; an "
                   "unbounded mutation is not authorised by anything".format(unbounded)
                   if unbounded else "every mutation's step declares a bound",
                   None if not unbounded else C.CORE_DELTA_OUT_OF_BOUNDS))

    checks.append(("delta_mutations_inside_bound", not out_of_bounds,
                   "mutation(s) {} touch an address outside their step's declared "
                   "bound".format(out_of_bounds) if out_of_bounds
                   else "every recorded mutation is inside its step's bound",
                   None if not out_of_bounds else C.CORE_DELTA_OUT_OF_BOUNDS))

    checks.append(("delta_no_protected_content_touched", not protected_hits,
                   "mutation(s) {} touch an address declared protected".format(
                       protected_hits) if protected_hits
                   else "no protected address was touched",
                   None if not protected_hits else C.CORE_PROTECTED_CONTENT_TOUCHED))

    # --- RAIL: the outcome must agree with the per-mutation statuses -----------
    still_in_world = [m.get("mutation_id") for m in mutations
                      if isinstance(m, dict) and m.get("status") in STATUSES_STILL_IN_WORLD]
    unrestored = [m.get("mutation_id") for m in mutations
                  if isinstance(m, dict)
                  and m.get("status") in (MUT_ROLLBACK_FAILED, MUT_ROLLBACK_UNVERIFIED,
                                          MUT_UNRECOVERABLE)]

    if outcome == DELTA_ROLLED_BACK:
        ok = not still_in_world
        checks.append(("delta_rolled_back_leaves_nothing_applied", ok,
                       "outcome is {!r} but mutation(s) {} are still recorded as in "
                       "the world; reporting a partial state as a rollback tells the "
                       "caller it may safely retry from the original base".format(
                           DELTA_ROLLED_BACK, still_in_world) if not ok
                       else "no mutation remains in the world",
                       None if ok else C.CORE_DELTA_PARTIAL_COMMIT))

    if outcome == DELTA_REFUSED:
        applied_anyway = [m.get("mutation_id") for m in mutations
                          if isinstance(m, dict) and m.get("status") != MUT_REFUSED
                          and m.get("status") != MUT_PLANNED]
        ok = not applied_anyway
        checks.append(("delta_refused_applied_nothing", ok,
                       "outcome is {!r} but mutation(s) {} were not refused; a "
                       "refusal must mean the world was never touched".format(
                           DELTA_REFUSED, applied_anyway) if not ok
                       else "a refused delta applied nothing", None if ok else code))

    if unrestored and outcome != DELTA_PARTIAL_COMMIT:
        checks.append(("delta_unrestored_forces_partial_commit", False,
                       "mutation(s) {} were neither restored nor confirmed restored, "
                       "yet outcome is {!r}. That state is neither committed nor "
                       "rolled back and must be reported as {!r} rather than rounded "
                       "to either".format(unrestored, outcome, DELTA_PARTIAL_COMMIT),
                       C.CORE_DELTA_PARTIAL_COMMIT))
    else:
        checks.append(("delta_unrestored_forces_partial_commit", True,
                       "outcome {!r} agrees with the per-mutation restoration "
                       "statuses".format(outcome), None))

    if outcome == DELTA_PARTIAL_COMMIT:
        ok = bool(unrestored)
        checks.append(("delta_partial_commit_has_an_unrestored_mutation", ok,
                       "outcome is {!r} but every mutation is accounted for; a "
                       "partial commit must name what is stuck".format(
                           DELTA_PARTIAL_COMMIT) if not ok
                       else "partial commit names {} unrestored mutation(s)".format(
                           len(unrestored)),
                       None if ok else code))

    # --- RAIL: a commit is verified only if it was measured -------------------
    if outcome == DELTA_COMMITTED:
        v = verification_status(delta)
        ok = v == tri.SATISFIED
        checks.append(("delta_committed_is_measured", ok,
                       "outcome is {!r} but the post-observation fold is {!r}; a "
                       "commit with nothing measured is a postcondition ASSERTED, "
                       "and it must be reported as {!r} instead".format(
                           DELTA_COMMITTED, v, DELTA_COMMITTED_UNVERIFIED) if not ok
                       else "every applied mutation's postcondition was measured to hold",
                       None if ok else C.CORE_DELTA_UNVERIFIED))

    # --- RAIL: anything that touched the world must carry evidence ------------
    evidence = delta.get("evidence_refs")
    if outcome != DELTA_REFUSED:
        ok = _str_list(evidence) and len(evidence) > 0
        checks.append(("delta_evidence_refs_nonempty", ok,
                       "evidence_refs is {!r}; a delta that changed the world and "
                       "points at no evidence cannot be audited afterwards, so its "
                       "outcome is unfalsifiable".format(evidence),
                       None if ok else code))
    else:
        ok = evidence is None or _str_list(evidence)
        checks.append(("delta_evidence_refs_nonempty", ok,
                       "evidence_refs must be a list of strings when present",
                       None if ok else code))

    sv = delta.get("schema_version")
    ok = sv == RT_WORLD_DELTA
    checks.append(("delta_schema_version", ok,
                   "schema_version must be {!r} (got {!r})".format(RT_WORLD_DELTA, sv),
                   None if ok else code))

    if strict:
        extra = sorted(set(delta) - set(WORLD_DELTA_ALLOWED))
        checks.append(("delta_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))

    return checks


# --------------------------------------------------------------------------- #
# canonical example factories (``**over`` spawns the known-bads)
#
# Domain-neutral by construction: Core owns no consumer's vocabulary, so the
# addresses below name a generic content root, never any game's content.
# --------------------------------------------------------------------------- #
def _example_mutation_bound(**over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "step_id": "step_author_surface",
        "allowed_packages": ["/generated/region_alpha/surface"],
        "allowed_actors": ["/generated/region_alpha/surface.anchor_0"],
        "protected_paths": [],
        "schema_version": RT_MUTATION_BOUND,
    }
    d.update(over)
    return d


def _example_mutation(**over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "mutation_id": "mut_0001",
        "step_id": "step_author_surface",
        "provider_id": "editor_authoring_bridge",
        "target_kind": TARGET_PACKAGE,
        "target_path": "/generated/region_alpha/surface",
        "operation": OP_MODIFY,
        "before_state": present_state({"revision": 1}),
        "expected_after_state": present_state({"revision": 2}),
        "status": MUT_PLANNED,
        "rollback_mode": PB.ROLLBACK_TRANSACTIONAL,
        "schema_version": RT_MUTATION,
    }
    d.update(over)
    return d


def _example_world_delta(**over: Any) -> Dict[str, Any]:
    mutation = _example_mutation(
        status=MUT_APPLIED,
        observed_after_apply=present_state({"revision": 2}))
    d: Dict[str, Any] = {
        "delta_id": "delta_0001",
        "operation_id": "op_0001",
        "outcome": DELTA_COMMITTED,
        "bounds": [_example_mutation_bound()],
        "mutations": [mutation],
        "evidence_refs": ["operation_manifest", "raw_observation_log"],
        "failure_codes": [],
        "created_by": "worldforge.core",
        "schema_version": RT_WORLD_DELTA,
        "report_type": RT_WORLD_DELTA,
    }
    d.update(over)
    return d
