#!/usr/bin/env python3
"""wfcore.planning.plan -- the typed plan, and the promise it makes to the executor.

WHY A TYPED PLAN AND NOT A LIST OF CALLS
----------------------------------------
A list of calls says what will be invoked. It says nothing that can be enforced
while it runs. The executor needs answers to questions a call list cannot carry:

    what is this step ALLOWED to change, exhaustively
    which provider was chosen, and why that one rather than the alternatives
    what must already be true before it starts, and what must be true after
    what proves it did what it said
    what happens if it fails, and can it be undone at all

Those are the fields below. Each one exists because its absence turns a
recoverable failure into an unrecoverable one.

THE MUTATION BOUND IS THE WHOLE POINT
-------------------------------------
``expected_changed_packages`` + ``expected_changed_actors`` together are the
bound the transaction executor enforces. A step whose bound is EMPTY while its
side effects are not evidence-only is invalid (WF1237), and the reason is not
tidiness: rollback works by undoing an enumerated set, so an unbounded step
cannot be rolled back COMPLETELY -- nothing enumerated what to undo. The failure
surfaces as a partially-reverted world, after the fact, with no record of what
was missed. Declaring the bound up front is what makes the undo total.

The one legitimate empty bound is a step that mutates nothing: an observation
step declares ``emits_evidence_only`` and touches no package and no actor. That
case is not an exception to the rule, it is the rule agreeing with itself.

WHY A STEP CARRIES ITS SELECTION RESULT
---------------------------------------
``selected_provider`` is a provider id, and a provider id in a plan is exactly
what ``providers.selection`` exists to prevent being hardcoded. So a step that
names a provider must also carry the ``selection`` record that produced it
(WF1237). Without it the plan is the hardcoded path wearing a plan's clothes: it
records a choice nobody made, cannot be re-checked, and hides that a second
provider was ever a candidate.

WHY THE ORDER IS DERIVED RATHER THAN AUTHORED
---------------------------------------------
``steps`` is a list, but the list order is NOT the execution order.
:func:`topological_order` derives the order from ``depends_on`` alone, breaking
ties lexicographically by ``step_id``. Two plans with identical steps assembled
in different orders therefore execute identically. The alternative -- honouring
authored order -- makes execution depend on how the synthesiser happened to
iterate, and a failure that reproduces only under the original iteration order
is a failure nobody can reproduce.

A cycle in ``depends_on`` has no order at all (WF1238). It is reported with the
members named, because "your plan has a cycle" is not actionable and an
unactionable failure gets worked around rather than fixed.

Domain neutrality: Core owns no consumer's vocabulary. Nothing here -- including
the examples -- may name a game, map, actor, faction, biome or asset (WF1211).
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import constraints as K
from .. import tri
from ..contracts.revision_policy import (MUTATION_KINDS, ROLLBACK_GRANULARITIES,
                                         mutation_verdict)
from ..failure import FailureCode as C
from ..providers.base import (CAPABILITIES, EFFECT_EVIDENCE_ONLY,
                              ROLLBACK_CAPABLE, SIDE_EFFECT_KINDS, Check,
                              declared_effect_kinds)

# --------------------------------------------------------------------------- #
# schema identity (house convention: wf.<domain>.<thing>.v<N>)
# --------------------------------------------------------------------------- #
RT_PLAN = "wf.core.plan.v1"

# --------------------------------------------------------------------------- #
# fallback vocabulary -- what happens to the PLAN when a step fails.
# Closed set: an unrecognised policy is a plan whose failure behaviour is
# undefined, and undefined failure behaviour is decided at the worst moment by
# whoever is reading the traceback.
# --------------------------------------------------------------------------- #
FALLBACK_ABORT = "abort"                        # stop; leave whatever committed
FALLBACK_ROLLBACK_AND_ABORT = "rollback_and_abort"   # undo this step, then stop
FALLBACK_RESELECT_PROVIDER = "reselect_provider"     # re-run selection, retry
FALLBACK_SKIP_STEP = "skip_step"                # continue without this step
FALLBACK_ESCALATE = "escalate_to_consumer"      # hand the decision back
FALLBACK_POLICIES = (FALLBACK_ABORT, FALLBACK_ROLLBACK_AND_ABORT,
                     FALLBACK_RESELECT_PROVIDER, FALLBACK_SKIP_STEP,
                     FALLBACK_ESCALATE)

# Policies that need a bounded number of attempts, or they are an unbounded loop
# wearing a recovery strategy's name.
FALLBACK_NEEDS_ATTEMPTS = (FALLBACK_RESELECT_PROVIDER,)

# --------------------------------------------------------------------------- #
# record shapes
# --------------------------------------------------------------------------- #
PREDICATE_REQUIRED = ("predicate_id", "subject", "expectation", "observation_key")
PREDICATE_ALLOWED = PREDICATE_REQUIRED + ("expected_value", "notes")

FALLBACK_POLICY_REQUIRED = ("on_failure",)
FALLBACK_POLICY_ALLOWED = FALLBACK_POLICY_REQUIRED + ("max_attempts", "detail", "notes")

# ``provider_rollback`` is the provider's DECLARED rollback mode, copied into the
# step at authoring time. Copied rather than looked up so the plan stays a
# self-contained promise -- and cross-checked against the live declaration by
# ``validate_plan(registry=...)``, so the copy cannot drift into a claim.
STEP_ROLLBACK_REQUIRED = ("rollback_required", "rollback_granularity",
                          "provider_rollback")
STEP_ROLLBACK_ALLOWED = STEP_ROLLBACK_REQUIRED + ("detail", "notes")

PLAN_ROLLBACK_REQUIRED = ("rollback_required", "rollback_granularity")
PLAN_ROLLBACK_ALLOWED = PLAN_ROLLBACK_REQUIRED + ("max_revision_attempts",
                                                  "detail", "notes")

# EXACTLY the twelve fields the plan->delta boundary is fixed on. The transaction
# executor reads these names; they are not free to drift.
PLAN_STEP_REQUIRED = (
    "step_id",
    "capability",                 # WHAT is done, from the Core capability vocabulary
    "selected_provider",          # provider_id -- produced by selection, never authored
    "depends_on",                 # step_ids; must form a DAG
    "preconditions",              # predicate records that must hold BEFORE
    "postconditions",             # predicate records that must hold AFTER
    "allowed_side_effects",       # subset of the provider's declared effect kinds
    "expected_changed_packages",  # THE bound, half one
    "expected_changed_actors",    # THE bound, half two
    "evidence_requirements",      # what must come back to prove what happened
    "fallback_policy",
    "rollback",
)
PLAN_STEP_ALLOWED = PLAN_STEP_REQUIRED + (
    "selection",        # the selection RESULT that chose selected_provider
    "mutation_kinds",   # revision_policy vocabulary; required when the step mutates
    "meta", "notes", "description", "created_by", "created_at",
)

PLAN_REQUIRED = (
    "plan_id",
    "request_id",
    "consumer_id",
    "schema_version",
    "steps",
    "fallback_policy",
    "rollback",
    "addresses",        # constraint_ids this plan intends to RESOLVE
)
PLAN_ALLOWED = PLAN_REQUIRED + (
    "analysis_id", "observes",   # constraint_ids this plan only intends to MEASURE
    "meta", "report_type", "created_by", "created_at", "description", "notes",
)


# --------------------------------------------------------------------------- #
# small local helpers (hand-rolled, mirroring wfcore.providers.base)
# --------------------------------------------------------------------------- #
def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _str_list(value: Any, min_len: int = 0) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) >= min_len
            and all(_nonempty_str(v) for v in value))


def _as_tuple(value: Any) -> Tuple[Any, ...]:
    return tuple(value) if isinstance(value, (list, tuple)) else ()


# --------------------------------------------------------------------------- #
# derived facts about a step -- one definition each, so no caller re-derives them
# --------------------------------------------------------------------------- #
def step_side_effect_kinds(step: Dict[str, Any]) -> Tuple[str, ...]:
    return tuple(e for e in _as_tuple(step.get("allowed_side_effects"))
                 if _nonempty_str(e))


def step_mutates(step: Dict[str, Any]) -> bool:
    """True unless every allowed side effect is ``emits_evidence_only``.

    Mirrors ``providers.base.mutates_anything`` deliberately: if the two ever
    disagreed, a step could be observation-shaped to the plan validator and
    mutation-shaped to the executor.
    """
    return any(k != EFFECT_EVIDENCE_ONLY for k in step_side_effect_kinds(step))


def step_mutation_bound(step: Dict[str, Any]) -> Tuple[str, ...]:
    """The exhaustive set this step may touch: packages and actors, sorted."""
    packages = [p for p in _as_tuple(step.get("expected_changed_packages"))
                if _nonempty_str(p)]
    actors = [a for a in _as_tuple(step.get("expected_changed_actors"))
              if _nonempty_str(a)]
    return tuple(sorted(set(packages) | set(actors)))


def plan_mutation_bound(plan: Dict[str, Any]) -> Tuple[str, ...]:
    """The union of every step's bound -- the whole plan's blast radius."""
    out: set = set()
    for step in _as_tuple(plan.get("steps")):
        if isinstance(step, dict):
            out |= set(step_mutation_bound(step))
    return tuple(sorted(out))


def plan_mutates(plan: Dict[str, Any]) -> bool:
    return any(step_mutates(s) for s in _as_tuple(plan.get("steps"))
               if isinstance(s, dict))


def _touches_protected(bound: Sequence[str],
                       protected: Sequence[str]) -> List[str]:
    """Which bound entries fall inside the protected set.

    Prefix containment counts: an actor inside a protected package IS protected
    content. Exact-match-only would let a step mutate everything inside a
    protected package while passing a check named for protecting it.
    """
    hits = []
    for entry in bound:
        for guard in protected:
            if not _nonempty_str(guard):
                continue
            if entry == guard or entry.startswith(guard + ".") or \
                    entry.startswith(guard + "/") or entry.startswith(guard + ":"):
                hits.append(entry)
                break
    return sorted(set(hits))


# --------------------------------------------------------------------------- #
# ordering -- derived, never authored
# --------------------------------------------------------------------------- #
def topological_order(plan: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Return ``(order, cycle_members)``. Deterministic by construction.

    Kahn's algorithm over ``depends_on``, emitting each ready wave in
    lexicographic ``step_id`` order. Two properties follow, and both are the
    reason this is a function rather than a sort at the call site:

      * the result does not depend on the order of ``plan["steps"]``, so a plan
        assembled by a different iteration produces the same execution
      * the result does not depend on set/dict iteration, so it does not change
        between processes with different hash seeds

    ``cycle_members`` is non-empty exactly when no order exists. It names the
    steps still waiting, because a cycle report that does not say WHICH steps is
    not something anyone can act on.
    """
    steps = [s for s in _as_tuple(plan.get("steps")) if isinstance(s, dict)]
    known = {s.get("step_id") for s in steps if _nonempty_str(s.get("step_id"))}

    remaining: Dict[str, List[str]] = {}
    for s in steps:
        sid = s.get("step_id")
        if not _nonempty_str(sid) or sid in remaining:
            continue
        remaining[sid] = sorted({d for d in _as_tuple(s.get("depends_on"))
                                 if _nonempty_str(d) and d in known and d != sid})

    order: List[str] = []
    while remaining:
        ready = sorted(sid for sid, deps in remaining.items()
                       if not any(d in remaining for d in deps))
        if not ready:
            break
        order.extend(ready)
        for sid in ready:
            del remaining[sid]
    return order, sorted(remaining)


def dangling_dependencies(plan: Dict[str, Any]) -> List[str]:
    """``depends_on`` entries naming a step this plan does not contain."""
    steps = [s for s in _as_tuple(plan.get("steps")) if isinstance(s, dict)]
    known = {s.get("step_id") for s in steps if _nonempty_str(s.get("step_id"))}
    out: set = set()
    for s in steps:
        for d in _as_tuple(s.get("depends_on")):
            if _nonempty_str(d) and d not in known:
                out.add(d)
    return sorted(out)


def dependents_of(plan: Dict[str, Any], step_id: str) -> List[str]:
    """Steps that declare a dependency on ``step_id``."""
    out = []
    for s in _as_tuple(plan.get("steps")):
        if isinstance(s, dict) and step_id in _as_tuple(s.get("depends_on")):
            out.append(s.get("step_id"))
    return sorted(x for x in out if _nonempty_str(x))


# --------------------------------------------------------------------------- #
# predicate evaluation -- the ONLY place a pre/postcondition becomes a tri-value
# --------------------------------------------------------------------------- #
def evaluate_predicate(predicate: Dict[str, Any],
                       observations: Dict[str, Any]) -> str:
    """Evaluate ONE predicate against observations. Absent observation -> UNKNOWN.

    Mirrors ``providers.base.evaluate_requirement``, and for the same reason: a
    precondition nobody measured is not "fine". Defaulting it to satisfied runs a
    mutation on an unverified premise; defaulting it to violated reports a defect
    nobody observed and sends repair after it.
    """
    if not isinstance(predicate, dict):
        return tri.UNKNOWN
    key = predicate.get("observation_key") or predicate.get("predicate_id")
    if not isinstance(observations, dict) or key not in observations:
        return tri.UNKNOWN
    value = observations[key]
    if "expected_value" in predicate:
        return tri.from_bool(value == predicate.get("expected_value"), measured=True)
    if isinstance(value, bool):
        return tri.from_bool(value, measured=True)
    if isinstance(value, str) and value in tri.TRI_VALUES:
        return value
    return tri.UNKNOWN


def _gate(step: Dict[str, Any], observations: Dict[str, Any], field: str,
          code: str, stage: str) -> Dict[str, Any]:
    reasons: List[Dict[str, Any]] = []
    values: List[str] = []
    for predicate in _as_tuple(step.get(field)):
        value = evaluate_predicate(predicate, observations)
        values.append(value)
        reasons.append({
            "stage": stage,
            "predicate_id": (predicate.get("predicate_id")
                             if isinstance(predicate, dict) else None),
            "subject": (predicate.get("subject")
                        if isinstance(predicate, dict) else None),
            "evaluation": value,
            "detail": ("predicate holds against observation" if value == tri.SATISFIED
                       else "predicate is contradicted by observation"
                       if value == tri.VIOLATED
                       else "no observation supports a verdict for this predicate"),
            # UNKNOWN carries NO code on purpose: an unmeasured predicate reported
            # as unmet states a defect nobody observed. It still blocks -- the
            # fold below is UNKNOWN, and UNKNOWN is not acceptance.
            "failure_code": code if value == tri.VIOLATED else None,
        })
    evaluation = tri.conj(values)
    return {
        "step_id": step.get("step_id") if isinstance(step, dict) else None,
        "stage": stage,
        "evaluation": evaluation,
        "reasons": reasons,
        "failure_codes": [code] if evaluation == tri.VIOLATED else [],
    }


def gate_step_preconditions(step: Dict[str, Any],
                            observations: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a step's preconditions. VIOLATED -> WF1239; UNKNOWN blocks, uncoded."""
    return _gate(step, observations, "preconditions",
                 C.CORE_PLAN_PRECONDITION_UNMET, "precondition")


def gate_step_postconditions(step: Dict[str, Any],
                             observations: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a step's postconditions. VIOLATED -> WF1240; UNKNOWN blocks, uncoded."""
    return _gate(step, observations, "postconditions",
                 C.CORE_PLAN_POSTCONDITION_UNMET, "postcondition")


# --------------------------------------------------------------------------- #
# validators
# --------------------------------------------------------------------------- #
def validate_predicate(predicate: Any, strict: bool = False) -> List[Check]:
    """Validate ONE pre/postcondition record."""
    code = C.CORE_PLAN_STEP_INVALID
    if not isinstance(predicate, dict):
        return [("predicate_is_object", False,
                 "predicate must be an object, got {}".format(type(predicate).__name__),
                 code)]
    checks: List[Check] = []
    for fld in PREDICATE_REQUIRED:
        ok = _nonempty_str(predicate.get(fld))
        checks.append(("predicate_has_" + fld, ok,
                       "required field {!r} {}; a predicate with no {} cannot be "
                       "evaluated, and an unevaluable predicate reads as a check "
                       "while checking nothing".format(
                           fld, "present" if ok else "missing/empty", fld),
                       None if ok else code))
    if strict:
        extra = sorted(set(predicate) - set(PREDICATE_ALLOWED))
        checks.append(("predicate_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))
    return checks


def validate_fallback_policy(policy: Any, strict: bool = False) -> List[Check]:
    """Validate ONE fallback policy record."""
    code = C.CORE_PLAN_FALLBACK_INVALID
    if not isinstance(policy, dict):
        return [("fallback_is_object", False,
                 "fallback_policy must be an object, got {}".format(
                     type(policy).__name__), code)]
    checks: List[Check] = []
    on_failure = policy.get("on_failure")
    ok = on_failure in FALLBACK_POLICIES
    checks.append(("fallback_on_failure_known", ok,
                   "on_failure {!r} must be one of {}; an unrecognised policy "
                   "leaves failure behaviour undefined, and undefined failure "
                   "behaviour gets decided at the worst possible moment".format(
                       on_failure, FALLBACK_POLICIES), None if ok else code))
    if on_failure in FALLBACK_NEEDS_ATTEMPTS:
        attempts = policy.get("max_attempts")
        ok = (isinstance(attempts, int) and not isinstance(attempts, bool)
              and attempts >= 1)
        checks.append(("fallback_bounded_attempts", ok,
                       "on_failure={!r} requires max_attempts >= 1 (got {!r}); a "
                       "retry with no ceiling is an unbounded loop wearing a "
                       "recovery strategy's name".format(on_failure, attempts),
                       None if ok else code))
    if strict:
        extra = sorted(set(policy) - set(FALLBACK_POLICY_ALLOWED))
        checks.append(("fallback_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))
    return checks


def validate_plan_step(step: Any, strict: bool = False,
                       declaration: Optional[Dict[str, Any]] = None,
                       policy: Optional[Dict[str, Any]] = None) -> List[Check]:
    """Validate ONE plan step.

    ``declaration`` enables the rails that need the provider's own claims (side
    effect subset, evidence subset, rollback support). ``policy`` enables the
    rails that need the consumer's authorisation (permitted mutations, protected
    content). Both are optional and both are load-bearing when supplied: a step
    validated without them is structurally sound and NOT yet known to be allowed.
    """
    code = C.CORE_PLAN_STEP_INVALID
    if not isinstance(step, dict):
        return [("step_is_object", False,
                 "step must be an object, got {}".format(type(step).__name__), code)]

    checks: List[Check] = []
    for fld in PLAN_STEP_REQUIRED:
        present = step.get(fld) is not None
        checks.append(("step_has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else code))

    if strict:
        extra = sorted(set(step) - set(PLAN_STEP_ALLOWED))
        checks.append(("step_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))

    checks.append(("step_id_nonempty_string", _nonempty_str(step.get("step_id")),
                   "step_id must be a non-empty string (got {!r})".format(
                       step.get("step_id")), code))

    capability = step.get("capability")
    ok = capability in CAPABILITIES
    checks.append(("step_capability_known", ok,
                   "capability {!r} must be one of {}".format(capability, CAPABILITIES),
                   None if ok else C.CORE_PROVIDER_CAPABILITY_UNKNOWN))

    # --- the provider was SELECTED, not named ------------------------------- #
    provider_id = step.get("selected_provider")
    ok = _nonempty_str(provider_id)
    checks.append(("step_names_a_provider", ok,
                   "selected_provider must be a non-empty provider id (got {!r})"
                   .format(provider_id), None if ok else code))

    selection = step.get("selection")
    has_selection = isinstance(selection, dict)
    checks.append(("step_provider_choice_is_auditable", has_selection,
                   "step names provider {!r} with no ``selection`` record; a plan "
                   "that names a provider without the selection that produced it "
                   "is the hardcoded path wearing a plan's clothes -- the choice "
                   "cannot be re-checked, and that a second provider was ever a "
                   "candidate is invisible".format(provider_id),
                   None if has_selection else code))
    if has_selection:
        ok = selection.get("selected_provider") == provider_id
        checks.append(("step_selection_names_the_same_provider", ok,
                       "selection selected {!r} but the step runs {!r}; a step that "
                       "diverges from its own selection record records a decision "
                       "nobody made".format(selection.get("selected_provider"),
                                            provider_id),
                       None if ok else code))
        ok = not (selection.get("failure_codes") or ())
        checks.append(("step_selection_succeeded", ok,
                       "selection carries failure code(s) {} yet the step runs its "
                       "provider anyway".format(list(selection.get("failure_codes") or ())),
                       None if ok else C.CORE_NO_PROVIDER_FOR_CAPABILITY))

    ok = _str_list(step.get("depends_on"), min_len=0)
    checks.append(("step_depends_on_str_list", ok,
                   "depends_on must be a list of step_ids (an empty list is a real "
                   "statement: this step depends on nothing); got {!r}".format(
                       step.get("depends_on")), None if ok else code))
    if isinstance(step.get("depends_on"), (list, tuple)):
        ok = step.get("step_id") not in step.get("depends_on")
        checks.append(("step_does_not_depend_on_itself", ok,
                       "step {!r} depends on itself, which is a cycle of length one"
                       .format(step.get("step_id")),
                       None if ok else C.CORE_PLAN_DEPENDENCY_CYCLE))

    for field in ("preconditions", "postconditions"):
        value = step.get(field)
        is_list = isinstance(value, (list, tuple))
        checks.append(("step_{}_is_list".format(field), is_list,
                       "{} must be a list of predicate records (use [] to state "
                       "there are none)".format(field), None if is_list else code))
        if is_list:
            for idx, predicate in enumerate(value):
                for (n, sub_ok, detail, sub_code) in validate_predicate(
                        predicate, strict=strict):
                    checks.append(("{}[{}].{}".format(field, idx, n), sub_ok,
                                   detail, sub_code))

    # A step that promises nothing about its own result cannot be verified, so
    # its success is unfalsifiable -- the same rail providers carry for evidence.
    ok = isinstance(step.get("postconditions"), (list, tuple)) and \
        len(step.get("postconditions")) >= 1
    checks.append(("step_declares_a_postcondition", ok,
                   "postconditions is {!r}; a step that states nothing that must be "
                   "true afterwards cannot be shown to have worked, so its success "
                   "is unfalsifiable".format(step.get("postconditions")),
                   None if ok else code))

    ok = _str_list(step.get("evidence_requirements"), min_len=1)
    checks.append(("step_requires_evidence", ok,
                   "evidence_requirements must name >=1 evidence kind (got {!r}); a "
                   "step that requires no proof is a step whose outcome is taken on "
                   "trust".format(step.get("evidence_requirements")),
                   None if ok else code))

    # --- side effects ------------------------------------------------------- #
    effects = step.get("allowed_side_effects")
    is_list = isinstance(effects, (list, tuple))
    ok = is_list and len(effects) >= 1
    checks.append(("step_side_effects_declared", ok,
                   "allowed_side_effects is {!r}; an empty list is indistinguishable "
                   "from an author who never considered it. A step that mutates "
                   "nothing must SAY so with {!r}".format(effects, EFFECT_EVIDENCE_ONLY),
                   None if ok else C.CORE_PROVIDER_SIDE_EFFECT_UNDECLARED))
    if is_list:
        unknown = sorted({e for e in effects if e not in SIDE_EFFECT_KINDS})
        checks.append(("step_side_effect_kinds_known", not unknown,
                       "allowed_side_effects names {} which is not in {}".format(
                           unknown, SIDE_EFFECT_KINDS) if unknown
                       else "all side-effect kinds are in the Core vocabulary",
                       None if not unknown else C.CORE_PROVIDER_SIDE_EFFECT_UNDECLARED))

    # --- THE mutation bound ------------------------------------------------- #
    for field in ("expected_changed_packages", "expected_changed_actors"):
        ok = _str_list(step.get(field), min_len=0)
        checks.append(("step_{}_str_list".format(field), ok,
                       "{} must be a list of path strings (got {!r})".format(
                           field, step.get(field)), None if ok else code))

    bound = step_mutation_bound(step)
    mutates = step_mutates(step)
    ok = (not mutates) or bool(bound)
    checks.append(("step_mutation_is_bounded", ok,
                   "step declares side effect(s) {} but expected_changed_packages "
                   "and expected_changed_actors are both empty. That is an "
                   "UNBOUNDED mutation: rollback undoes an enumerated set, so "
                   "nothing enumerated means nothing can be completely undone, and "
                   "the gap shows up as a half-reverted world with no record of "
                   "what was missed".format(list(step_side_effect_kinds(step))),
                   None if ok else code))

    ok = mutates or not bound
    checks.append(("step_evidence_only_touches_nothing", ok,
                   "step declares only {!r} yet claims it will change {}; an "
                   "observation step that touches content is not an observation"
                   .format(EFFECT_EVIDENCE_ONLY, list(bound)),
                   None if ok else C.CORE_PROVIDER_SIDE_EFFECT_UNDECLARED))

    # --- mutation kinds (the consumer's authorisation vocabulary) ----------- #
    kinds = _as_tuple(step.get("mutation_kinds"))
    if mutates:
        ok = len(kinds) >= 1 and all(_nonempty_str(k) for k in kinds)
        checks.append(("step_declares_mutation_kinds", ok,
                       "a mutating step must declare >=1 mutation_kind (got {!r}); "
                       "without one, no revision policy can be consulted and the "
                       "step is authorised by nobody".format(step.get("mutation_kinds")),
                       None if ok else C.CORE_MUTATION_NOT_PERMITTED))
        unknown = sorted({k for k in kinds if k not in MUTATION_KINDS})
        checks.append(("step_mutation_kinds_known", not unknown,
                       "mutation_kind(s) {} are not in {}".format(unknown, MUTATION_KINDS)
                       if unknown else "all mutation kinds are in the Core vocabulary",
                       None if not unknown else C.CORE_MUTATION_NOT_PERMITTED))
    else:
        ok = not kinds
        checks.append(("step_observation_declares_no_mutation_kind", ok,
                       "an evidence-only step declares mutation_kind(s) {}; a step "
                       "that changes nothing cannot perform a mutation".format(list(kinds)),
                       None if ok else C.CORE_MUTATION_NOT_PERMITTED))

    checks += validate_fallback_policy(step.get("fallback_policy"), strict=strict)
    checks += _validate_step_rollback(step, strict=strict)

    if isinstance(declaration, dict):
        checks += _rail_step_within_declaration(step, declaration)
    if isinstance(policy, dict):
        checks += _rail_step_within_policy(step, policy)
    return checks


def _validate_step_rollback(step: Dict[str, Any], strict: bool = False) -> List[Check]:
    code = C.CORE_PLAN_STEP_INVALID
    rb = step.get("rollback")
    if not isinstance(rb, dict):
        return [("step_rollback_is_object", False,
                 "rollback must be an object, got {}".format(type(rb).__name__), code)]
    checks: List[Check] = []
    required = rb.get("rollback_required")
    ok = isinstance(required, bool)
    checks.append(("step_rollback_required_explicit", ok,
                   "rollback_required must be an explicit boolean (got {!r}); an "
                   "omitted value is read by an executor as 'safe to try', which is "
                   "exactly the assumption that must be stated".format(required),
                   None if ok else code))
    gran = rb.get("rollback_granularity")
    ok = gran in ROLLBACK_GRANULARITIES
    checks.append(("step_rollback_granularity_known", ok,
                   "rollback_granularity {!r} must be one of {}".format(
                       gran, ROLLBACK_GRANULARITIES), None if ok else code))
    provider_rollback = rb.get("provider_rollback")
    ok = _nonempty_str(provider_rollback)
    checks.append(("step_rollback_names_provider_mode", ok,
                   "provider_rollback must state the provider's declared rollback "
                   "mode (got {!r}); without it, 'this step can be undone' rests on "
                   "nothing".format(provider_rollback), None if ok else code))

    if required is True:
        ok = provider_rollback in ROLLBACK_CAPABLE
        checks.append(("step_required_rollback_is_supported", ok,
                       "rollback_required=True but the provider declares "
                       "rollback={!r}, which is not one of {}. A demanded rollback "
                       "that no mechanism can perform is discovered as unmeetable "
                       "only after something has already changed".format(
                           provider_rollback, ROLLBACK_CAPABLE),
                       None if ok else C.CORE_PLAN_NO_ROLLBACK))
        ok = gran != "none"
        checks.append(("step_required_rollback_has_a_unit", ok,
                       "rollback_required=True with rollback_granularity='none'; a "
                       "rollback demanded with no unit to roll back to cannot be "
                       "performed", None if ok else C.CORE_PLAN_NO_ROLLBACK))

    if strict:
        extra = sorted(set(rb) - set(STEP_ROLLBACK_ALLOWED))
        checks.append(("step_rollback_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))
    return checks


def _rail_step_within_declaration(step: Dict[str, Any],
                                  declaration: Dict[str, Any]) -> List[Check]:
    """The step may not promise more than its provider declared it can do."""
    checks: List[Check] = []

    declared_effects = set(declared_effect_kinds(declaration))
    undeclared = sorted(set(step_side_effect_kinds(step)) - declared_effects)
    ok = not undeclared
    checks.append(("step_side_effects_within_declaration", ok,
                   "step allows side effect(s) {} that provider {!r} never declared "
                   "(declares {}); an undeclared effect is outside every bound the "
                   "executor can enforce, so it cannot be undone".format(
                       undeclared, declaration.get("provider_id"),
                       sorted(declared_effects)) if undeclared
                   else "allowed_side_effects are a subset of the provider's declaration",
                   None if ok else C.CORE_PROVIDER_SIDE_EFFECT_UNDECLARED))

    declared_evidence = set(_as_tuple(declaration.get("evidence")))
    missing = sorted(set(_as_tuple(step.get("evidence_requirements"))) - declared_evidence)
    ok = not missing
    checks.append(("step_evidence_within_declaration", ok,
                   "step requires evidence {} that provider {!r} does not emit "
                   "(emits {}); the step can never be shown to have worked".format(
                       missing, declaration.get("provider_id"), sorted(declared_evidence))
                   if missing else "evidence_requirements are emitted by the provider",
                   None if ok else C.CORE_PLAN_STEP_INVALID))

    ok = step.get("capability") in _as_tuple(declaration.get("capabilities"))
    checks.append(("step_capability_offered_by_provider", ok,
                   "step wants capability {!r} but provider {!r} offers {}".format(
                       step.get("capability"), declaration.get("provider_id"),
                       list(_as_tuple(declaration.get("capabilities")))),
                   None if ok else C.CORE_NO_PROVIDER_FOR_CAPABILITY))

    rb = step.get("rollback")
    if isinstance(rb, dict) and _nonempty_str(rb.get("provider_rollback")):
        ok = rb.get("provider_rollback") == declaration.get("rollback")
        checks.append(("step_rollback_claim_matches_declaration", ok,
                       "step copies provider_rollback={!r} but provider {!r} "
                       "declares rollback={!r}; a stale copy is a rollback promise "
                       "resting on a claim nobody makes".format(
                           rb.get("provider_rollback"), declaration.get("provider_id"),
                           declaration.get("rollback")),
                       None if ok else C.CORE_PLAN_NO_ROLLBACK))
    return checks


def _rail_step_within_policy(step: Dict[str, Any],
                             policy: Dict[str, Any]) -> List[Check]:
    """The step may not do more than the consumer authorised."""
    checks: List[Check] = []

    for kind in _as_tuple(step.get("mutation_kinds")):
        verdict = mutation_verdict(policy, kind)
        ok = tri.accepts(verdict)
        checks.append(("step_mutation_permitted::{}".format(kind), ok,
                       "mutation kind {!r} evaluates {} against consumer {!r}'s "
                       "policy (permitted={}); permitted_mutations is an ALLOW-list, "
                       "so absence is a refusal".format(
                           kind, verdict, policy.get("consumer_id"),
                           list(_as_tuple(policy.get("permitted_mutations")))),
                       None if ok else C.CORE_MUTATION_NOT_PERMITTED))

    protected = [p for p in _as_tuple(policy.get("protected_content"))
                 if _nonempty_str(p)]
    touched = _touches_protected(step_mutation_bound(step), protected)
    ok = not touched
    checks.append(("step_bound_avoids_protected_content", ok,
                   "step {!r} would change {} which is inside the consumer's "
                   "protected_content; protection is not a preference and cannot be "
                   "traded against anything".format(step.get("step_id"), touched)
                   if touched else "step bound does not intersect protected content",
                   None if ok else C.CORE_PROTECTED_CONTENT_TOUCHED))
    return checks


def validate_plan(plan: Any, strict: bool = False,
                  registry: Any = None,
                  policy: Optional[Dict[str, Any]] = None,
                  analysis: Optional[Dict[str, Any]] = None) -> List[Check]:
    """Validate a WHOLE plan.

    ``registry`` / ``policy`` / ``analysis`` are optional and each unlocks rails
    that cannot be checked from the plan alone. A plan validated without them is
    STRUCTURALLY sound and nothing more -- in particular it is not yet known to be
    permitted, nor known to address anything real.
    """
    code = C.CORE_PLAN_INVALID
    if not isinstance(plan, dict):
        return [("plan_is_object", False,
                 "plan must be an object, got {}".format(type(plan).__name__), code)]

    checks: List[Check] = []
    for fld in PLAN_REQUIRED:
        present = plan.get(fld) is not None
        checks.append(("plan_has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else code))

    if strict:
        extra = sorted(set(plan) - set(PLAN_ALLOWED))
        checks.append(("plan_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))

    for fld in ("plan_id", "request_id", "consumer_id"):
        checks.append(("plan_{}_nonempty_string".format(fld),
                       _nonempty_str(plan.get(fld)),
                       "{} must be a non-empty string (got {!r})".format(
                           fld, plan.get(fld)), code))

    sv = plan.get("schema_version")
    ok = sv == RT_PLAN
    checks.append(("plan_schema_version", ok,
                   "schema_version must be {!r} (got {!r})".format(RT_PLAN, sv),
                   None if ok else code))

    steps = plan.get("steps")
    is_list = isinstance(steps, (list, tuple))
    ok = is_list and len(steps) >= 1
    checks.append(("plan_has_steps", ok,
                   "steps is {!r}; a plan with no step changes nothing and measures "
                   "nothing, so executing it can only consume an attempt".format(
                       steps if not is_list else len(steps)),
                   None if ok else code))

    if is_list:
        declarations: Dict[str, Any] = {}
        for idx, step in enumerate(steps):
            declaration = None
            if registry is not None and isinstance(step, dict):
                pid = step.get("selected_provider")
                declaration = registry.get(pid) if _nonempty_str(pid) else None
                declarations[pid] = declaration
                found = declaration is not None
                checks.append(("step[{}].step_provider_is_registered".format(idx),
                               found,
                               "step names provider {!r}, which is not registered; "
                               "the plan promises a capability nothing here can "
                               "run".format(pid),
                               None if found else C.CORE_NO_PROVIDER_FOR_CAPABILITY))
            for (n, sub_ok, detail, sub_code) in validate_plan_step(
                    step, strict=strict, declaration=declaration, policy=policy):
                checks.append(("step[{}].{}".format(idx, n), sub_ok, detail, sub_code))

        ids = [s.get("step_id") for s in steps if isinstance(s, dict)]
        dupes = sorted({i for i in ids if i and ids.count(i) > 1})
        checks.append(("plan_step_ids_unique", not dupes,
                       "duplicate step_id(s) {}; a duplicate id makes depends_on "
                       "ambiguous and lets one step silently shadow another".format(dupes)
                       if dupes else "step_ids unique", None if not dupes else code))

        dangling = dangling_dependencies(plan)
        checks.append(("plan_dependencies_resolve", not dangling,
                       "depends_on names {} which this plan does not contain; the "
                       "step would wait on something that will never run".format(dangling)
                       if dangling else "every depends_on resolves inside the plan",
                       None if not dangling else code))

        order, cycle = topological_order(plan)
        checks.append(("plan_dependencies_are_acyclic", not cycle,
                       "steps {} form a dependency cycle, so no execution order "
                       "exists; each is waiting for another to finish first".format(cycle)
                       if cycle else "depends_on forms a DAG with a total order of "
                                     "{} step(s)".format(len(order)),
                       None if not cycle else C.CORE_PLAN_DEPENDENCY_CYCLE))

        checks += _rail_fallback_coherence(plan)

    checks += _validate_plan_rollback(plan, strict=strict)
    checks += validate_fallback_policy(plan.get("fallback_policy"), strict=strict)
    checks += _rail_plan_addresses_something(plan, analysis)
    return checks


def _validate_plan_rollback(plan: Dict[str, Any], strict: bool = False) -> List[Check]:
    code = C.CORE_PLAN_INVALID
    rb = plan.get("rollback")
    if not isinstance(rb, dict):
        return [("plan_rollback_is_object", False,
                 "plan rollback must be an object, got {}".format(type(rb).__name__),
                 code)]
    checks: List[Check] = []
    required = rb.get("rollback_required")
    ok = isinstance(required, bool)
    checks.append(("plan_rollback_required_explicit", ok,
                   "rollback_required must be an explicit boolean (got {!r})".format(
                       required), None if ok else code))
    gran = rb.get("rollback_granularity")
    ok = gran in ROLLBACK_GRANULARITIES
    checks.append(("plan_rollback_granularity_known", ok,
                   "rollback_granularity {!r} must be one of {}".format(
                       gran, ROLLBACK_GRANULARITIES), None if ok else code))
    if strict:
        extra = sorted(set(rb) - set(PLAN_ROLLBACK_ALLOWED))
        checks.append(("plan_rollback_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))

    if required is True:
        unbacked = sorted({
            s.get("step_id") for s in _as_tuple(plan.get("steps"))
            if isinstance(s, dict) and step_mutates(s)
            and not (isinstance(s.get("rollback"), dict)
                     and s["rollback"].get("provider_rollback") in ROLLBACK_CAPABLE)})
        ok = not unbacked
        checks.append(("plan_required_rollback_is_supported_by_every_step", ok,
                       "the plan requires rollback but mutating step(s) {} run "
                       "providers that declare no rollback mechanism; the plan "
                       "promises an undo it cannot perform, and the shortfall is "
                       "found only after the world has changed".format(unbacked)
                       if unbacked else "every mutating step can be rolled back",
                       None if not unbacked else C.CORE_PLAN_NO_ROLLBACK))
    return checks


def _rail_fallback_coherence(plan: Dict[str, Any]) -> List[Check]:
    """Fallbacks that would leave the plan proceeding on a broken premise."""
    checks: List[Check] = []
    for step in _as_tuple(plan.get("steps")):
        if not isinstance(step, dict):
            continue
        policy = step.get("fallback_policy")
        if not isinstance(policy, dict):
            continue
        sid = step.get("step_id")
        if policy.get("on_failure") == FALLBACK_SKIP_STEP:
            dependents = dependents_of(plan, sid)
            ok = not dependents
            checks.append(("plan_skip_step_has_no_dependents::{}".format(sid), ok,
                           "step {!r} is set to {!r} on failure, but step(s) {} "
                           "depend on it; skipping it lets them run with their "
                           "preconditions resting on a step that never "
                           "happened".format(sid, FALLBACK_SKIP_STEP, dependents)
                           if dependents else "skippable step has no dependents",
                           None if ok else C.CORE_PLAN_FALLBACK_INVALID))
            ok = not step_mutates(step)
            checks.append(("plan_skip_step_is_not_a_mutation::{}".format(sid), ok,
                           "mutating step {!r} is set to {!r} on failure; continuing "
                           "past a failed mutation leaves the world half-changed "
                           "while the plan proceeds as though it were "
                           "whole".format(sid, FALLBACK_SKIP_STEP),
                           None if ok else C.CORE_PLAN_FALLBACK_INVALID))
    return checks


def _rail_plan_addresses_something(plan: Dict[str, Any],
                                   analysis: Optional[Dict[str, Any]]) -> List[Check]:
    """A plan that changes things must be changing them FOR something.

    The rail is scoped to plans that mutate, and deliberately so: its rationale is
    that executing the plan burns a revision attempt to arrive somewhere already
    known to be unacceptable. An observation-only plan mutates nothing and burns
    nothing -- it is the correct response to an UNKNOWN, and forbidding it here
    would forbid measuring.
    """
    code = C.CORE_PLAN_ADDRESSES_NOTHING
    checks: List[Check] = []
    addresses = plan.get("addresses")
    is_list = isinstance(addresses, (list, tuple))
    checks.append(("plan_addresses_is_list", is_list,
                   "addresses must be a list of constraint_ids (got {!r})".format(
                       type(addresses).__name__), None if is_list else C.CORE_PLAN_INVALID))
    if not is_list:
        return checks

    mutating = plan_mutates(plan)
    ok = bool(addresses) or not mutating
    checks.append(("plan_addresses_something", ok,
                   "the plan contains mutating step(s) but addresses no constraint. "
                   "Executing it changes the consumer's world and burns a revision "
                   "attempt to arrive somewhere already known to be unacceptable"
                   if not ok else
                   "plan addresses {} constraint(s)".format(len(addresses))
                   if mutating else
                   "observation-only plan: it mutates nothing, so it has nothing to "
                   "address and burns no revision attempt",
                   None if ok else code))

    if not isinstance(analysis, dict):
        return checks

    findings = {f.get("constraint_id"): f
                for f in _as_tuple(analysis.get("findings")) if isinstance(f, dict)}
    unknown_ids = sorted({a for a in addresses if a not in findings})
    checks.append(("plan_addressed_constraints_exist", not unknown_ids,
                   "addresses names {} which the analysis does not contain; a plan "
                   "cannot resolve a constraint nobody evaluated".format(unknown_ids)
                   if unknown_ids else "every addressed constraint exists in the analysis",
                   None if not unknown_ids else code))

    not_violated = sorted({
        a for a in addresses
        if a in findings and findings[a].get("evaluation") != tri.VIOLATED})
    checks.append(("plan_addresses_only_violated_constraints", not not_violated,
                   "addresses names {} which the analysis reports as NOT violated. "
                   "An UNKNOWN constraint's remedy is to MEASURE it, and a SATISFIED "
                   "one needs nothing; authoring a change for either one changes the "
                   "consumer's world for a reason nobody established".format(not_violated)
                   if not_violated else "every addressed constraint is violated",
                   None if not not_violated else code))

    non_load_bearing = sorted({
        a for a in addresses
        if a in findings
        and findings[a].get("constraint_class") not in K.ACCEPTANCE_LOAD_BEARING})
    checks.append(("plan_addresses_only_load_bearing_constraints", not non_load_bearing,
                   "addresses names {} whose class cannot block acceptance; resolving "
                   "one cannot move the result from unacceptable to acceptable".format(
                       non_load_bearing) if non_load_bearing
                   else "every addressed constraint is acceptance-load-bearing",
                   None if not non_load_bearing else code))
    return checks


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def explain_plan(plan: Dict[str, Any]) -> List[str]:
    """Render a plan as human-readable lines, in EXECUTION order.

    A machine-checkable plan nobody can read is only half of a promise.
    """
    order, cycle = topological_order(plan)
    by_id = {s.get("step_id"): s for s in _as_tuple(plan.get("steps"))
             if isinstance(s, dict)}
    lines = ["plan {} (request {}, consumer {}) addresses {}".format(
        plan.get("plan_id"), plan.get("request_id"), plan.get("consumer_id"),
        list(_as_tuple(plan.get("addresses"))) or "nothing (observation only)")]
    for position, sid in enumerate(order):
        step = by_id.get(sid) or {}
        lines.append("  {}. {} [{}] via {} -- {}".format(
            position + 1, sid, step.get("capability"), step.get("selected_provider"),
            "mutates {}".format(list(step_mutation_bound(step))) if step_mutates(step)
            else "observes; touches nothing"))
    if cycle:
        lines.append("  !! dependency cycle among {} -- no execution order exists".format(cycle))
    return lines


# --------------------------------------------------------------------------- #
# canonical example factories (``**over`` spawns the known-bads)
# --------------------------------------------------------------------------- #
def _example_predicate(**over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "predicate_id": "pred_authoring_session_open",
        "subject": "engine.authoring_session",
        "expectation": "an interactive authoring session is open and idle",
        "observation_key": "engine.authoring_session_open",
    }
    d.update(over)
    return d


def _example_fallback_policy(**over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "on_failure": FALLBACK_ROLLBACK_AND_ABORT,
        "detail": "undo this step, then stop rather than build on a failed change",
    }
    d.update(over)
    return d


def _example_step_rollback(**over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "rollback_required": True,
        "rollback_granularity": "per_transaction",
        "provider_rollback": "transactional",
    }
    d.update(over)
    return d


def _example_selection(**over: Any) -> Dict[str, Any]:
    """A minimal, valid-shaped selection result, as a step would carry it."""
    d: Dict[str, Any] = {
        "selection_id": "sel_req_placeholder",
        "request_id": "req_placeholder",
        "capability": "editor_authoring",
        "outcome": "selected",
        "selected_provider": "editor_authoring_bridge",
        "considered": [],
        "ranking": [{"provider_id": "editor_authoring_bridge", "score": 1.0}],
        "ambiguous_between": [],
        "failure_codes": [],
    }
    d.update(over)
    return d


def _example_plan_step(**over: Any) -> Dict[str, Any]:
    """Canonical-valid MUTATING step. Domain-neutral by construction (WF1211)."""
    d: Dict[str, Any] = {
        "step_id": "step_revise_c_placeholder_invariant",
        "capability": "editor_authoring",
        "selected_provider": "editor_authoring_bridge",
        "selection": _example_selection(),
        "depends_on": [],
        "preconditions": [_example_predicate()],
        "postconditions": [_example_predicate(
            predicate_id="pred_placeholder_invariant_holds",
            subject="placeholder.measurable",
            expectation="the addressed invariant holds after this step",
            observation_key="placeholder.measurable_holds")],
        "allowed_side_effects": ["mutates_persistent_asset"],
        "expected_changed_packages": ["content_root/placeholder_package_a"],
        "expected_changed_actors": [
            "content_root/placeholder_package_a.placeholder_entity_0"],
        "mutation_kinds": ["add_geometry"],
        "evidence_requirements": ["operation_manifest"],
        "fallback_policy": _example_fallback_policy(),
        "rollback": _example_step_rollback(),
    }
    d.update(over)
    return d


def _example_observation_step(**over: Any) -> Dict[str, Any]:
    """Canonical-valid OBSERVATION step: the correct response to an UNKNOWN."""
    d: Dict[str, Any] = {
        "step_id": "step_observe_c_placeholder_unknown",
        "capability": "scene_observation",
        "selected_provider": "scene_observation_bridge",
        "selection": _example_selection(capability="scene_observation",
                                        selected_provider="scene_observation_bridge"),
        "depends_on": [],
        "preconditions": [],
        "postconditions": [_example_predicate(
            predicate_id="pred_placeholder_unknown_measured",
            subject="placeholder.unmeasured",
            expectation="the subject has been measured, so a verdict is possible",
            observation_key="placeholder.unmeasured_measured")],
        "allowed_side_effects": [EFFECT_EVIDENCE_ONLY],
        "expected_changed_packages": [],
        "expected_changed_actors": [],
        "evidence_requirements": ["raw_observation_log"],
        "fallback_policy": _example_fallback_policy(on_failure=FALLBACK_ABORT),
        "rollback": _example_step_rollback(rollback_required=False,
                                           rollback_granularity="none",
                                           provider_rollback="none"),
    }
    d.update(over)
    return d


def _example_plan(**over: Any) -> Dict[str, Any]:
    """Canonical-valid plan: one observation step, one mutation step depending on it."""
    observe = _example_observation_step()
    revise = _example_plan_step(depends_on=[observe["step_id"]])
    d: Dict[str, Any] = {
        "plan_id": "plan_placeholder",
        "request_id": "req_placeholder",
        "consumer_id": "consumer_placeholder",
        "analysis_id": "analysis_placeholder",
        "steps": [observe, revise],
        "addresses": ["c_placeholder_invariant"],
        "observes": ["c_placeholder_unknown"],
        "fallback_policy": _example_fallback_policy(on_failure=FALLBACK_ABORT),
        "rollback": {"rollback_required": True,
                     "rollback_granularity": "per_transaction",
                     "max_revision_attempts": 3},
        "created_by": "worldforge.core",
        "schema_version": RT_PLAN,
        "report_type": RT_PLAN,
    }
    d.update(over)
    return d
