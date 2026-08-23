#!/usr/bin/env python3
"""wfcore.planning.synth -- turn a constraint analysis into a typed plan.

WHAT THIS MODULE DECIDES, AND WHAT IT REFUSES TO DECIDE
-------------------------------------------------------
It decides: which findings deserve a step, what kind of step, in what dependency
relation, and -- through ``providers.selection`` -- which provider runs it.

It refuses to decide: whether a constraint matters (the class says), whether a
mutation is allowed (the revision policy says), and which provider is best
(selection says). Every one of those is somebody else's authority, and this
module's job is to carry them into the plan intact rather than re-litigate them.

THE RULE THAT THE WHOLE MODULE TURNS ON
---------------------------------------
    VIOLATED  ->  a change may be authored. Something was measured and it is wrong.
    UNKNOWN   ->  an OBSERVATION step. Nothing was measured, so nothing is known
                  to be wrong, and the only honest remedy is to go and measure.
    SATISFIED ->  no step at all.

Getting this backwards is the expensive mistake, and it is easy to make because
an UNKNOWN *feels* like a problem. Authoring a change for an UNKNOWN modifies the
consumer's world for a reason nobody established -- and the measurement that
would have said whether it was needed is exactly the thing that was skipped. So
an UNKNOWN finding produces a step whose side effects are ``emits_evidence_only``
and whose mutation bound is empty, and the synthesiser enforces that by asking
selection for a provider under a PROHIBITED_OUTCOME on ``provider.mutation_free``
-- a mutating provider is not merely unpreferred for an observation, it is
ineligible.

A PARTIAL PLAN IS NOT A PLAN
----------------------------
If any finding needs a step and no step can be built for it -- no provider, an
ambiguous selection, a missing remedy capability -- synthesis returns NO plan
(``unplannable``) rather than a plan with that finding quietly dropped. A plan
missing one violated load-bearing constraint still cannot reach acceptance, so
executing it changes the world and arrives somewhere already known to be
unacceptable. The dropped finding would be invisible; the refusal is not.

THE ANALYSIS INPUT -- A LOCAL STRUCTURAL EXPECTATION, NOT AN IMPORT
------------------------------------------------------------------
The analysis module is authored on a parallel lane. Importing it now would couple
two half-built surfaces, so this module states what it needs as a MINIMAL
structural expectation and VALIDATES it at the boundary
(:func:`validate_analysis_expectation`). Validating rather than assuming is the
point: when the real module lands, a mismatch fails loudly here instead of
producing a plausible plan from misread fields.

    analysis = {
      "analysis_id":  str,
      "request_id":   str,
      "consumer_id":  str,
      "observations": {observation_key: bool | tri-value | value},
      "findings": [
        {
          # required
          "constraint_id":    str,
          "constraint_class": one of constraints.CONSTRAINT_CLASSES,
          "evaluation":       one of tri.TRI_VALUES,
          "subject":          str,
          "detail":           str,
          # required when evaluation == VIOLATED and the class is load-bearing
          "remedy_capability":         one of providers.base.CAPABILITIES,
          "expected_changed_packages": [package path, ...],
          "expected_changed_actors":   [actor path, ...],
          "mutation_kinds":            [revision_policy.MUTATION_KINDS, ...],
          # optional
          "measure_capability":  capability used when evaluation == UNKNOWN
                                 (default: scene_observation),
          "observation_key":     key whose truth means the constraint now holds,
          "measurement_key":     key whose truth means the subject has been measured,
          "required_outputs":    [output kind, ...],
          "required_evidence":   [evidence kind, ...],
          "preconditions":       [plan.predicate record, ...],
          "depends_on_constraint_ids": [constraint_id, ...],
        }, ...
      ],
    }

Domain neutrality: Core owns no consumer's vocabulary. Nothing here -- including
the examples -- may name a game, map, actor, faction, biome or asset (WF1211).
"""

from typing import Any, Dict, List, Optional, Tuple

from .. import constraints as K
from .. import tri
from ..contracts.revision_policy import MUTATION_KINDS
from ..failure import FailureCode as C
from ..providers import selection as S
from ..providers.base import (CAP_SCENE_OBSERVATION, CAPABILITIES,
                              EFFECT_EVIDENCE_ONLY, Check,
                              declared_effect_kinds)
from . import plan as P

RT_PLAN_SYNTHESIS = "wf.core.plan_synthesis.v1"

# --------------------------------------------------------------------------- #
# outcomes -- a closed set, so "no plan" is never confused with "empty plan"
# --------------------------------------------------------------------------- #
OUTCOME_PLANNED = "planned"
OUTCOME_NOTHING_TO_PLAN = "nothing_to_plan"   # every load-bearing finding is satisfied
OUTCOME_UNPLANNABLE = "unplannable"           # something needed a step and none exists
SYNTHESIS_OUTCOMES = (OUTCOME_PLANNED, OUTCOME_NOTHING_TO_PLAN, OUTCOME_UNPLANNABLE)

STEP_KIND_REVISION = "revision"       # authored because something measured is wrong
STEP_KIND_OBSERVATION = "observation"  # authored because nothing was measured
STEP_KINDS = (STEP_KIND_REVISION, STEP_KIND_OBSERVATION)

ANALYSIS_REQUIRED = ("analysis_id", "request_id", "consumer_id", "findings",
                     "observations")
ANALYSIS_ALLOWED = ANALYSIS_REQUIRED + ("meta", "report_type", "created_by",
                                        "created_at", "notes", "schema_version")

FINDING_REQUIRED = ("constraint_id", "constraint_class", "evaluation", "subject",
                    "detail")
FINDING_ALLOWED = FINDING_REQUIRED + (
    "remedy_capability", "measure_capability", "expected_changed_packages",
    "expected_changed_actors", "mutation_kinds", "observation_key",
    "measurement_key", "required_outputs", "required_evidence", "preconditions",
    "depends_on_constraint_ids", "notes",
)

DEFAULT_REQUIRED_OUTPUTS = ("operation_manifest",)
DEFAULT_REVISION_EVIDENCE = ("operation_manifest",)
DEFAULT_OBSERVATION_EVIDENCE = ("raw_observation_log",)


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _as_tuple(value: Any) -> Tuple[Any, ...]:
    return tuple(value) if isinstance(value, (list, tuple)) else ()


def _str_list(value: Any, min_len: int = 0) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) >= min_len
            and all(_nonempty_str(v) for v in value))


# --------------------------------------------------------------------------- #
# classification -- one definition of "what does this finding deserve?"
# --------------------------------------------------------------------------- #
def finding_step_kind(finding: Dict[str, Any]) -> Optional[str]:
    """What kind of step this finding deserves, or ``None`` for no step at all.

    Only acceptance-load-bearing classes produce steps. A soft preference or an
    optimisation target cannot make a result unacceptable, so authoring a change
    to chase one spends the consumer's world on something that was never going to
    block -- and it would do so under the same rollback budget as a real repair.
    """
    if not isinstance(finding, dict):
        return None
    if finding.get("constraint_class") not in K.ACCEPTANCE_LOAD_BEARING:
        return None
    evaluation = finding.get("evaluation")
    if evaluation == tri.VIOLATED:
        return STEP_KIND_REVISION
    if evaluation == tri.UNKNOWN:
        return STEP_KIND_OBSERVATION
    return None


def step_id_for(finding: Dict[str, Any], kind: str) -> str:
    """Deterministic step identity, derived from the finding it came from.

    Derived rather than counted: a positional id (``step_3``) changes when an
    unrelated finding appears, which makes two plans for the same world look
    different and makes ``depends_on`` unreadable in a diff.
    """
    prefix = "step_observe_" if kind == STEP_KIND_OBSERVATION else "step_revise_"
    return prefix + str(finding.get("constraint_id"))


# --------------------------------------------------------------------------- #
# the analysis boundary -- checked, never assumed
# --------------------------------------------------------------------------- #
def validate_analysis_expectation(analysis: Any, strict: bool = False) -> List[Check]:
    """Validate the MINIMAL structure this module needs from an analysis.

    Not a validator for the analysis lane's record -- that lane owns its own. This
    checks only what synthesis reads, so that a shape change is caught here rather
    than silently producing a plan built from fields that meant something else.
    """
    code = C.CORE_PLAN_INVALID
    if not isinstance(analysis, dict):
        return [("analysis_is_object", False,
                 "analysis must be an object, got {}".format(type(analysis).__name__),
                 code)]

    checks: List[Check] = []
    for fld in ANALYSIS_REQUIRED:
        present = analysis.get(fld) is not None
        checks.append(("analysis_has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else code))

    if strict:
        extra = sorted(set(analysis) - set(ANALYSIS_ALLOWED))
        checks.append(("analysis_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))

    ok = isinstance(analysis.get("observations"), dict)
    checks.append(("analysis_observations_is_object", ok,
                   "observations must be an object mapping observation keys to "
                   "measurements; absent, every requirement and precondition is "
                   "unknown and nothing can be selected or gated", None if ok else code))

    findings = analysis.get("findings")
    is_list = isinstance(findings, (list, tuple))
    checks.append(("analysis_findings_is_list", is_list,
                   "findings must be a list", None if is_list else code))
    if not is_list:
        return checks

    for idx, finding in enumerate(findings):
        for (n, ok, detail, sub_code) in _validate_finding(finding, strict=strict):
            checks.append(("finding[{}].{}".format(idx, n), ok, detail, sub_code))

    ids = [f.get("constraint_id") for f in findings if isinstance(f, dict)]
    dupes = sorted({i for i in ids if i and ids.count(i) > 1})
    checks.append(("analysis_constraint_ids_unique", not dupes,
                   "duplicate constraint_id(s) {}; a duplicate makes a finding's "
                   "verdict ambiguous and would produce two steps with one "
                   "id".format(dupes) if dupes else "constraint_ids unique",
                   None if not dupes else code))
    return checks


def _validate_finding(finding: Any, strict: bool = False) -> List[Check]:
    code = C.CORE_PLAN_INVALID
    if not isinstance(finding, dict):
        return [("finding_is_object", False,
                 "finding must be an object, got {}".format(type(finding).__name__),
                 code)]

    checks: List[Check] = []
    for fld in FINDING_REQUIRED:
        ok = _nonempty_str(finding.get(fld))
        checks.append(("finding_has_" + fld, ok,
                       "required field {!r} {}".format(
                           fld, "present" if ok else "missing/empty"),
                       None if ok else code))

    if strict:
        extra = sorted(set(finding) - set(FINDING_ALLOWED))
        checks.append(("finding_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))

    evaluation = finding.get("evaluation")
    ok = evaluation in tri.TRI_VALUES
    checks.append(("finding_evaluation_is_tri", ok,
                   "evaluation {!r} must be one of {}; a two-valued verdict cannot "
                   "distinguish 'measured and wrong' from 'never measured', and "
                   "those have opposite remedies".format(evaluation, tri.TRI_VALUES),
                   None if ok else code))

    klass = finding.get("constraint_class")
    ok = klass in K.CONSTRAINT_CLASSES
    checks.append(("finding_class_known", ok,
                   "constraint_class {!r} must be one of {}".format(
                       klass, K.CONSTRAINT_CLASSES),
                   None if ok else C.CORE_CONSTRAINT_UNKNOWN_CLASS))

    kind = finding_step_kind(finding)
    if kind == STEP_KIND_REVISION:
        cap = finding.get("remedy_capability")
        ok = cap in CAPABILITIES
        checks.append(("finding_violated_names_remedy_capability", ok,
                       "a VIOLATED load-bearing finding must name a "
                       "remedy_capability from {} (got {!r}); without one, nothing "
                       "states WHAT would change it and no provider can be "
                       "selected".format(CAPABILITIES, cap),
                       None if ok else C.CORE_PROVIDER_CAPABILITY_UNKNOWN))

        bound = (list(_as_tuple(finding.get("expected_changed_packages")))
                 + list(_as_tuple(finding.get("expected_changed_actors"))))
        ok = bool(bound) and all(_nonempty_str(b) for b in bound)
        checks.append(("finding_violated_names_a_mutation_bound", ok,
                       "a VIOLATED load-bearing finding must enumerate the packages "
                       "and/or actors a repair would touch (got {!r} / {!r}); an "
                       "unenumerated repair cannot be completely rolled back".format(
                           finding.get("expected_changed_packages"),
                           finding.get("expected_changed_actors")),
                       None if ok else C.CORE_PLAN_STEP_INVALID))

        kinds = _as_tuple(finding.get("mutation_kinds"))
        ok = bool(kinds) and all(k in MUTATION_KINDS for k in kinds)
        checks.append(("finding_violated_names_mutation_kinds", ok,
                       "a VIOLATED load-bearing finding must name >=1 mutation_kind "
                       "from {} (got {!r}); without one the revision policy cannot "
                       "be consulted and the repair is authorised by nobody".format(
                           MUTATION_KINDS, finding.get("mutation_kinds")),
                       None if ok else C.CORE_MUTATION_NOT_PERMITTED))

    if kind == STEP_KIND_OBSERVATION:
        cap = finding.get("measure_capability")
        ok = cap is None or cap in CAPABILITIES
        checks.append(("finding_unknown_measure_capability_known", ok,
                       "measure_capability {!r} must be one of {} (or absent, "
                       "defaulting to {!r})".format(cap, CAPABILITIES,
                                                    CAP_SCENE_OBSERVATION),
                       None if ok else C.CORE_PROVIDER_CAPABILITY_UNKNOWN))
    return checks


# --------------------------------------------------------------------------- #
# selection request construction -- the plan never names a provider itself
# --------------------------------------------------------------------------- #
def _selection_constraints(kind: str, policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The provider-facing constraints this KIND of step imposes.

    Every one is acceptance-load-bearing on purpose. These are not preferences: a
    mutating provider for an observation step, or an un-undoable provider under a
    policy that demands rollback, is not a worse choice -- it is a wrong one, and
    a score could trade either away.
    """
    constraints: List[Dict[str, Any]] = []

    if kind == STEP_KIND_OBSERVATION:
        constraints.append({
            "constraint_id": "c_observation_must_not_mutate",
            "constraint_class": K.PROHIBITED_OUTCOME,
            "subject": S.FACET_MUTATION_FREE,
            "detail": ("an UNKNOWN is unmeasured, not wrong; measuring it must not "
                       "change the world it is measuring"),
        })
        return constraints

    rollback = policy.get("rollback") if isinstance(policy, dict) else None
    if isinstance(rollback, dict) and rollback.get("rollback_required") is True:
        constraints.append({
            "constraint_id": "c_provider_rollback_capable",
            "constraint_class": K.HARD_INVARIANT,
            "subject": S.FACET_ROLLBACK_CAPABLE,
            "detail": ("the consumer's revision policy requires rollback, so a "
                       "provider with no undo mechanism cannot run a mutation"),
        })

    for constraint in _as_tuple(policy.get("protected_semantics")):
        if not isinstance(constraint, dict):
            continue
        subject = constraint.get("subject") or ""
        if str(subject).startswith(S.PROVIDER_SUBJECT_PREFIX):
            constraints.append(dict(constraint))
    return constraints


def build_selection_request(finding: Dict[str, Any], kind: str,
                            policy: Dict[str, Any],
                            observations: Dict[str, Any]) -> Dict[str, Any]:
    """Build the selection request for ONE step. States a RESULT, never a provider."""
    if kind == STEP_KIND_OBSERVATION:
        capability = finding.get("measure_capability") or CAP_SCENE_OBSERVATION
        evidence = list(_as_tuple(finding.get("required_evidence"))
                        or DEFAULT_OBSERVATION_EVIDENCE)
    else:
        capability = finding.get("remedy_capability")
        evidence = list(_as_tuple(finding.get("required_evidence"))
                        or DEFAULT_REVISION_EVIDENCE)

    return {
        "request_id": "req_{}_{}".format(kind, finding.get("constraint_id")),
        "capability": capability,
        "required_outputs": list(_as_tuple(finding.get("required_outputs"))
                                 or DEFAULT_REQUIRED_OUTPUTS),
        "required_evidence": evidence,
        "constraints": _selection_constraints(kind, policy),
        "observations": dict(observations or {}),
        "created_by": "worldforge.core",
        "schema_version": S.RT_SELECTION_REQUEST,
        "report_type": S.RT_SELECTION_REQUEST,
    }


# --------------------------------------------------------------------------- #
# step construction
# --------------------------------------------------------------------------- #
def _postcondition_for(finding: Dict[str, Any], kind: str) -> Dict[str, Any]:
    subject = finding.get("subject")
    cid = finding.get("constraint_id")
    if kind == STEP_KIND_OBSERVATION:
        return {
            "predicate_id": "post_{}_measured".format(cid),
            "subject": subject,
            "expectation": ("the subject has been measured, so the constraint can "
                            "receive a verdict instead of blocking as unknown"),
            "observation_key": (finding.get("measurement_key")
                                or "{}.measured".format(subject)),
        }
    return {
        "predicate_id": "post_{}_satisfied".format(cid),
        "subject": subject,
        "expectation": "the addressed constraint holds after this step",
        "observation_key": finding.get("observation_key") or str(subject),
    }


def _build_step(finding: Dict[str, Any], kind: str,
                declaration: Dict[str, Any], selection: Dict[str, Any],
                policy: Dict[str, Any], depends_on: List[str]) -> Dict[str, Any]:
    mutating = kind == STEP_KIND_REVISION
    policy_rollback = policy.get("rollback") if isinstance(policy, dict) else {}
    policy_rollback = policy_rollback if isinstance(policy_rollback, dict) else {}
    rollback_required = bool(policy_rollback.get("rollback_required")) and mutating

    if mutating:
        effects = sorted(set(declared_effect_kinds(declaration)))
        evidence = list(_as_tuple(finding.get("required_evidence"))
                        or DEFAULT_REVISION_EVIDENCE)
    else:
        # Selection already filtered to a mutation-free provider, so its declared
        # kinds are evidence-only; state that explicitly rather than inferring it.
        effects = [EFFECT_EVIDENCE_ONLY]
        evidence = list(_as_tuple(finding.get("required_evidence"))
                        or DEFAULT_OBSERVATION_EVIDENCE)

    step: Dict[str, Any] = {
        "step_id": step_id_for(finding, kind),
        "capability": selection.get("capability"),
        "selected_provider": selection.get("selected_provider"),
        "selection": selection,
        "depends_on": sorted(set(depends_on)),
        "preconditions": [dict(p) for p in _as_tuple(finding.get("preconditions"))
                          if isinstance(p, dict)],
        "postconditions": [_postcondition_for(finding, kind)],
        "allowed_side_effects": effects,
        "expected_changed_packages": (
            sorted(set(_as_tuple(finding.get("expected_changed_packages"))))
            if mutating else []),
        "expected_changed_actors": (
            sorted(set(_as_tuple(finding.get("expected_changed_actors"))))
            if mutating else []),
        "evidence_requirements": evidence,
        "fallback_policy": {
            "on_failure": (P.FALLBACK_ROLLBACK_AND_ABORT if mutating
                           else P.FALLBACK_ABORT),
            "detail": ("undo this step and stop rather than build on a failed change"
                       if mutating else
                       "stop: a measurement that failed leaves the subject unknown"),
        },
        "rollback": {
            "rollback_required": rollback_required,
            "rollback_granularity": (policy_rollback.get("rollback_granularity")
                                     if rollback_required else "none"),
            "provider_rollback": declaration.get("rollback"),
        },
        "description": finding.get("detail"),
        "created_by": "worldforge.core",
    }
    if mutating:
        step["mutation_kinds"] = sorted(set(_as_tuple(finding.get("mutation_kinds"))))
    return step


# --------------------------------------------------------------------------- #
# synthesis
# --------------------------------------------------------------------------- #
def synthesize_plan(analysis: Any, registry: Any, policy: Dict[str, Any],
                    plan_id: Optional[str] = None) -> Dict[str, Any]:
    """Turn an analysis into a plan, or explain why no plan exists.

    Returns a SYNTHESIS RESULT record. ``plan`` is ``None`` in both non-``planned``
    outcomes, and the two are kept distinct: "nothing needed doing" and "something
    needed doing and could not be planned" are opposite situations that a null
    plan alone would render identical.
    """
    result: Dict[str, Any] = {
        "synthesis_id": "synth_{}".format(
            analysis.get("analysis_id") if isinstance(analysis, dict) else "unknown"),
        "analysis_id": analysis.get("analysis_id") if isinstance(analysis, dict) else None,
        "outcome": OUTCOME_UNPLANNABLE,
        "plan": None,
        "addresses": [],
        "observes": [],
        "selections": [],
        "unresolved": [],
        "failure_codes": [],
        "schema_version": RT_PLAN_SYNTHESIS,
        "report_type": RT_PLAN_SYNTHESIS,
    }

    boundary = validate_analysis_expectation(analysis)
    broken = [(n, d, c) for (n, ok, d, c) in boundary if not ok]
    if broken:
        result["unresolved"] = [{
            "constraint_id": None,
            "reason": "analysis does not meet the structural expectation "
                      "synthesis reads: {}".format([n for (n, _d, _c) in broken[:6]]),
            "failure_codes": sorted({c for (_n, _d, c) in broken if c}),
        }]
        result["failure_codes"] = sorted({c for (_n, _d, c) in broken if c})
        return result

    observations = analysis.get("observations") or {}
    # Sorted by constraint_id: the plan must not depend on the order the analysis
    # happened to emit findings in, or two analyses of the same world produce two
    # different-looking plans.
    findings = sorted((f for f in analysis.get("findings") if isinstance(f, dict)),
                      key=lambda f: str(f.get("constraint_id")))

    wanted: List[Tuple[Dict[str, Any], str]] = []
    for finding in findings:
        kind = finding_step_kind(finding)
        if kind is not None:
            wanted.append((finding, kind))

    if not wanted:
        result["outcome"] = OUTCOME_NOTHING_TO_PLAN
        return result

    steps: List[Dict[str, Any]] = []
    by_constraint: Dict[str, str] = {}
    observation_by_subject: Dict[str, List[str]] = {}

    # Pass 1: observation steps. A revision that shares a subject with an
    # unmeasured constraint must wait for the measurement -- otherwise it authors
    # a change while the very thing that would judge it is still unknown.
    for finding, kind in wanted:
        if kind != STEP_KIND_OBSERVATION:
            continue
        step, failure = _plan_one(finding, kind, registry, policy, observations, [])
        if step is None:
            result["unresolved"].append(failure)
            continue
        steps.append(step)
        by_constraint[str(finding.get("constraint_id"))] = step["step_id"]
        observation_by_subject.setdefault(str(finding.get("subject")), []).append(
            step["step_id"])
        result["selections"].append(step["selection"])
        result["observes"].append(str(finding.get("constraint_id")))

    # Pass 2: revision steps, which may depend on pass 1.
    for finding, kind in wanted:
        if kind != STEP_KIND_REVISION:
            continue
        depends = list(observation_by_subject.get(str(finding.get("subject")), []))
        for cid in _as_tuple(finding.get("depends_on_constraint_ids")):
            if cid in by_constraint:
                depends.append(by_constraint[cid])
        step, failure = _plan_one(finding, kind, registry, policy, observations,
                                  depends)
        if step is None:
            result["unresolved"].append(failure)
            continue
        steps.append(step)
        by_constraint[str(finding.get("constraint_id"))] = step["step_id"]
        result["selections"].append(step["selection"])
        result["addresses"].append(str(finding.get("constraint_id")))

    # Late-bound revision->revision dependencies (both ends now have step ids).
    step_by_id = {s["step_id"]: s for s in steps}
    for finding, kind in wanted:
        sid = by_constraint.get(str(finding.get("constraint_id")))
        if sid is None or kind != STEP_KIND_REVISION:
            continue
        extra = [by_constraint[c] for c in _as_tuple(
            finding.get("depends_on_constraint_ids")) if c in by_constraint]
        step_by_id[sid]["depends_on"] = sorted(
            set(step_by_id[sid]["depends_on"]) | set(extra) - {sid})

    if result["unresolved"]:
        # Fail closed. See the module docstring: a plan with a violated
        # load-bearing constraint quietly dropped still cannot reach acceptance.
        codes: set = set()
        for entry in result["unresolved"]:
            codes |= set(entry.get("failure_codes") or ())
        result["outcome"] = OUTCOME_UNPLANNABLE
        result["failure_codes"] = sorted(codes)
        return result

    result["addresses"] = sorted(set(result["addresses"]))
    result["observes"] = sorted(set(result["observes"]))
    policy_rollback = policy.get("rollback") if isinstance(policy, dict) else {}
    policy_rollback = policy_rollback if isinstance(policy_rollback, dict) else {}

    result["plan"] = {
        "plan_id": plan_id or "plan_{}".format(analysis.get("analysis_id")),
        "request_id": analysis.get("request_id"),
        "consumer_id": analysis.get("consumer_id"),
        "analysis_id": analysis.get("analysis_id"),
        "steps": steps,
        "addresses": list(result["addresses"]),
        "observes": list(result["observes"]),
        "fallback_policy": {
            "on_failure": P.FALLBACK_ABORT,
            "detail": ("stop the plan: a step that failed leaves later steps resting "
                       "on a premise nobody re-established"),
        },
        "rollback": {
            "rollback_required": bool(policy_rollback.get("rollback_required")),
            "rollback_granularity": policy_rollback.get("rollback_granularity"),
            "max_revision_attempts": policy_rollback.get("max_revision_attempts"),
        },
        "created_by": "worldforge.core",
        "schema_version": P.RT_PLAN,
        "report_type": P.RT_PLAN,
    }
    result["outcome"] = OUTCOME_PLANNED
    return result


def _plan_one(finding: Dict[str, Any], kind: str, registry: Any,
              policy: Dict[str, Any], observations: Dict[str, Any],
              depends_on: List[str]) -> Tuple[Optional[Dict[str, Any]],
                                              Optional[Dict[str, Any]]]:
    """Build ONE step, or return why it could not be built. Never both."""
    cid = str(finding.get("constraint_id"))

    request = build_selection_request(finding, kind, policy, observations)
    request_checks = S.validate_selection_request(request)
    bad = [(n, c) for (n, ok, _d, c) in request_checks if not ok]
    if bad:
        return None, {
            "constraint_id": cid,
            "step_kind": kind,
            "reason": "the selection request built from this finding is malformed: "
                      "{}".format([n for (n, _c) in bad[:4]]),
            "failure_codes": sorted({c for (_n, c) in bad if c}),
        }

    selection = S.select_provider(registry, request)
    if selection.get("outcome") != S.OUTCOME_SELECTED:
        return None, {
            "constraint_id": cid,
            "step_kind": kind,
            "reason": "selection returned {!r} for capability {!r}; no step can "
                      "name a provider that selection did not produce".format(
                          selection.get("outcome"), request.get("capability")),
            "failure_codes": sorted(set(selection.get("failure_codes") or ())),
            "selection": selection,
        }

    declaration = registry.get(selection.get("selected_provider"))
    if not isinstance(declaration, dict):
        return None, {
            "constraint_id": cid,
            "step_kind": kind,
            "reason": "selection chose {!r} but the registry cannot resolve it".format(
                selection.get("selected_provider")),
            "failure_codes": [C.CORE_NO_PROVIDER_FOR_CAPABILITY],
        }

    step = _build_step(finding, kind, declaration, selection, policy, depends_on)
    checks = P.validate_plan_step(step, declaration=declaration, policy=policy)
    bad = [(n, c) for (n, ok, _d, c) in checks if not ok]
    if bad:
        return None, {
            "constraint_id": cid,
            "step_kind": kind,
            "reason": "the synthesised step does not validate: {}".format(
                [n for (n, _c) in bad[:4]]),
            "failure_codes": sorted({c for (_n, c) in bad if c}),
        }
    return step, None


def explain_synthesis(result: Dict[str, Any]) -> List[str]:
    """Render a synthesis result as human-readable lines."""
    lines = ["synthesis {}: outcome={} addresses={} observes={}".format(
        result.get("synthesis_id"), result.get("outcome"),
        result.get("addresses"), result.get("observes"))]
    for entry in _as_tuple(result.get("unresolved")):
        lines.append("  unresolved {}: {} {}".format(
            entry.get("constraint_id"), entry.get("reason"),
            entry.get("failure_codes")))
    if isinstance(result.get("plan"), dict):
        lines.extend("  " + line for line in P.explain_plan(result["plan"]))
    return lines


# --------------------------------------------------------------------------- #
# canonical example factories (``**over`` spawns the known-bads)
# --------------------------------------------------------------------------- #
def _example_finding(**over: Any) -> Dict[str, Any]:
    """Canonical VIOLATED load-bearing finding. Domain-neutral (WF1211)."""
    d: Dict[str, Any] = {
        "constraint_id": "c_placeholder_invariant",
        "constraint_class": K.HARD_INVARIANT,
        "evaluation": tri.VIOLATED,
        "subject": "placeholder.measurable",
        "detail": "the measured value does not satisfy the declared invariant",
        "remedy_capability": "editor_authoring",
        "expected_changed_packages": ["content_root/placeholder_package_a"],
        "expected_changed_actors": [
            "content_root/placeholder_package_a.placeholder_entity_0"],
        "mutation_kinds": ["add_geometry"],
        "observation_key": "placeholder.measurable_holds",
        "required_outputs": ["operation_manifest"],
        "required_evidence": ["operation_manifest"],
    }
    d.update(over)
    return d


def _example_unknown_finding(**over: Any) -> Dict[str, Any]:
    """Canonical UNKNOWN finding -- the one whose remedy is to MEASURE."""
    d: Dict[str, Any] = {
        "constraint_id": "c_placeholder_unknown",
        "constraint_class": K.HARD_INVARIANT,
        "evaluation": tri.UNKNOWN,
        "subject": "placeholder.unmeasured",
        "detail": "nothing has been measured, so no verdict is possible",
        "measure_capability": CAP_SCENE_OBSERVATION,
        "measurement_key": "placeholder.unmeasured_measured",
        "required_outputs": ["observation_set"],
        "required_evidence": ["raw_observation_log"],
    }
    d.update(over)
    return d


def _example_analysis(**over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "analysis_id": "analysis_placeholder",
        "request_id": "req_placeholder",
        "consumer_id": "consumer_placeholder",
        "observations": {},
        "findings": [_example_finding(), _example_unknown_finding()],
        "created_by": "worldforge.core",
    }
    d.update(over)
    return d
