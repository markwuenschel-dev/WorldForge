#!/usr/bin/env python3
"""wfcore.providers.selection -- choose a provider FROM THE REQUESTED RESULT.

WHAT IS BEING REPLACED
----------------------
Today a caller reaches a capability by naming the tool: the path from "I want
this result" to "this executable runs" is hardcoded at the call site. That has
two consequences that only show up later. A second tool offering the same
capability cannot become a candidate without editing every call site. And when
two builds differ, nothing in the output says WHY one path was taken, because no
decision was ever recorded -- there was no decision, only a literal.

So a selection request states the RESULT (a capability plus the outputs the
caller needs plus their constraints) and never a provider. ``provider_id`` and
friends are FORBIDDEN fields on a request (WF1226): accepting them would restore
the hardcoded path while looking like selection.

THE AUTHORITY SPLIT -- FILTERS vs SCORE
---------------------------------------
This is the single most important rule in this module.

    ACCEPTANCE-LOAD-BEARING constraints (hard invariants, prohibited outcomes,
    protected semantics, budgets, declared unknowns) act as FILTERS. They
    eliminate a provider. They contribute NOTHING to any score.

    SCORING constraints (soft preferences, optimisation targets) produce a
    score. They can NEVER eliminate a provider and can never rescue one.

The two sets are disjoint by construction -- they are read from
``constraints.ACCEPTANCE_LOAD_BEARING`` and ``constraints.SCORING_CLASSES``,
which do not overlap. If a hard invariant were allowed to contribute a large
negative score instead of filtering, a provider that violates it could still win
by scoring well elsewhere. That is an authority inversion: the consumer's
inviolable statement gets outvoted by its own preferences. The taxonomy exists to
make that impossible, and this module is where the impossibility is enforced.

UNKNOWN IS NOT ELIGIBLE, AND IT IS NOT A FAILURE EITHER
--------------------------------------------------------
A provider whose requirements cannot be evaluated is ``unknown``. It is NOT
selected -- selecting it would be a build resting on an unverified precondition.
It is also NOT reported as a requirement failure -- that would state a defect
nobody observed and send repair to fix something that may be perfectly fine. It
is reported as unknown, with the specific requirement that had no observation,
so the fix is obvious: go measure it.

AMBIGUITY IS AN OUTCOME, NOT A COIN FLIP
-----------------------------------------
When two eligible providers tie at the top and no declared tiebreak separates
them, selection FAILS with WF1229. It does not pick one.

Picking one would be defensible only if the pick were recorded and reproducible,
and it is neither: the tie means the request contains no statement that prefers
either, so any pick comes from something outside the request -- registration
order, dict ordering, a sort on a name. The build then differs between machines
for a reason that appears nowhere in the request, and the reason is unrecoverable
after the fact. A hard failure that says "your request does not distinguish these
two, add a preference or a tiebreak criterion" is strictly better: it is
actionable, and it keeps reproducibility a property of the request.

Tiebreaks ARE supported -- as ordered CRITERIA (``tiebreak_criteria``), never as
a provider name. A criterion is a statement about what the consumer values, so it
stays inside the "select from the requested result" rule.

PROVIDER-FACING SUBJECTS
------------------------
A constraint only participates in provider selection if its ``subject`` is in the
``provider.`` namespace. A constraint about the WORLD ("every anchor reachable")
says nothing about which tool should run; it is evaluated against the RESULT
during acceptance, not against a declaration here. Filtering on it would make
every provider unknown on every request.

Within the ``provider.`` namespace the rule inverts and is fail-closed: a
provider-facing subject this module does not recognise evaluates to UNKNOWN, so
an unrecognised demand blocks selection instead of being silently skipped.
"""

from typing import Any, Dict, List, Optional, Tuple

from .. import constraints as K
from .. import tri
from ..failure import FailureCode as C
from .base import (
    CAPABILITIES,
    DET_ENV_DEPENDENT,
    DET_SEEDED,
    DET_UNKNOWN,
    ROLLBACK_CAPABLE,
    ROLLBACK_TRANSACTIONAL,
    ROLLBACK_UNKNOWN,
    SIDE_EFFECT_KINDS,
    Check,
    declared_effect_kinds,
    declared_effect_scopes,
    evaluate_requirements,
    mutates_anything,
)

RT_SELECTION_REQUEST = "wf.core.provider_selection_request.v1"
RT_SELECTION_RESULT = "wf.core.provider_selection_result.v1"

# --------------------------------------------------------------------------- #
# vocabularies
# --------------------------------------------------------------------------- #
OUTCOME_SELECTED = "selected"
OUTCOME_AMBIGUOUS = "ambiguous"
OUTCOME_NO_CANDIDATE = "no_candidate"
OUTCOME_NO_ELIGIBLE_CANDIDATE = "no_eligible_candidate"
SELECTION_OUTCOMES = (OUTCOME_SELECTED, OUTCOME_AMBIGUOUS,
                      OUTCOME_NO_CANDIDATE, OUTCOME_NO_ELIGIBLE_CANDIDATE)

STATUS_SELECTED = "selected"
STATUS_ELIGIBLE = "eligible"
STATUS_REJECTED = "rejected"
STATUS_UNKNOWN = "unknown"
CANDIDATE_STATUSES = (STATUS_SELECTED, STATUS_ELIGIBLE, STATUS_REJECTED, STATUS_UNKNOWN)

STAGE_CAPABILITY = "capability_match"
STAGE_OUTPUTS = "required_outputs"
STAGE_REQUIREMENTS = "requirement_eligibility"
STAGE_FILTER = "hard_constraint_filter"
STAGE_SCORING = "scoring"
STAGE_TIEBREAK = "tiebreak"

# The namespace a constraint subject must live in to say anything about a
# provider. See the module docstring.
PROVIDER_SUBJECT_PREFIX = "provider."

# Recognised provider-facing facets. Anything else under ``provider.`` is
# deliberately UNKNOWN rather than ignored.
FACET_DETERMINISM_SEEDED = "provider.determinism.seeded"
FACET_DETERMINISM_ENV_STABLE = "provider.determinism.at_least_environment_stable"
FACET_ROLLBACK_TRANSACTIONAL = "provider.rollback.transactional"
FACET_ROLLBACK_CAPABLE = "provider.rollback.capable"
FACET_MUTATION_FREE = "provider.mutation_free"
FACET_SIDE_EFFECT_SCOPE = "provider.side_effect_scope"
FACET_PREFIX_CAPABILITY = "provider.capability."
FACET_PREFIX_OUTPUT = "provider.output."
FACET_PREFIX_EVIDENCE = "provider.evidence."
FACET_PREFIX_SIDE_EFFECT = "provider.side_effect."
FACET_PREFIX_COST = "provider.cost."

# float comparison slack for tie detection. Deliberately tiny: two scores that
# differ only below this are not meaningfully different, and treating them as
# different is how an arbitrary pick sneaks back in wearing a decimal.
SCORE_EPSILON = 1e-9

# --------------------------------------------------------------------------- #
# record shapes
# --------------------------------------------------------------------------- #
SELECTION_REQUEST_REQUIRED = (
    "request_id",
    "capability",         # the RESULT wanted, in capability vocabulary
    "required_outputs",   # what the caller must receive back, >=1
    "constraints",        # wfcore.constraints records; class decides filter vs score
    "observations",       # what has actually been measured about the environment
    "schema_version",
)
SELECTION_REQUEST_ALLOWED = SELECTION_REQUEST_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
    "required_evidence",  # evidence kinds the caller must get back
    "tiebreak_criteria",  # ordered provider-facing facets, never provider names
)
# Fields that would reintroduce the hardcoded path. Present -> WF1226.
SELECTION_REQUEST_FORBIDDEN = (
    "provider_id", "provider", "providers", "preferred_provider", "provider_hint",
)

SELECTION_RESULT_REQUIRED = (
    "selection_id", "request_id", "capability", "outcome", "selected_provider",
    "considered", "ranking", "ambiguous_between", "failure_codes", "schema_version",
)
SELECTION_RESULT_ALLOWED = SELECTION_RESULT_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
    "tiebreak_applied", "registry_snapshot",
)


# --------------------------------------------------------------------------- #
# facet evaluation
# --------------------------------------------------------------------------- #
def _membership_tri(needle: str, haystack: Any) -> str:
    values = tuple(haystack or ())
    return tri.from_bool(needle in values, measured=True)


def _facet_filter_tri(constraint: Dict[str, Any],
                      declaration: Dict[str, Any]) -> Tuple[str, str]:
    """Evaluate ONE acceptance-load-bearing constraint against ONE declaration.

    Returns ``(tri_value, detail)``. Never returns SATISFIED for a facet it does
    not understand: an unrecognised provider-facing demand is UNKNOWN, which
    blocks, because "we did not know how to check your rule" must not read as
    "your rule holds".
    """
    subject = constraint.get("subject") or ""
    klass = constraint.get("constraint_class")

    if klass == K.DECLARED_UNKNOWN:
        return (tri.UNKNOWN,
                "constraint is a DECLARED_UNKNOWN; the consumer has not decided it, "
                "so no provider can be shown to satisfy it")

    # --- determinism ------------------------------------------------------- #
    if subject in (FACET_DETERMINISM_SEEDED, FACET_DETERMINISM_ENV_STABLE):
        det = declaration.get("determinism")
        if det == DET_UNKNOWN or det is None:
            return (tri.UNKNOWN,
                    "provider declares determinism={!r}; nothing supports a verdict".format(det))
        allowed = ((DET_SEEDED,) if subject == FACET_DETERMINISM_SEEDED
                   else (DET_SEEDED, DET_ENV_DEPENDENT))
        return (tri.from_bool(det in allowed, measured=True),
                "provider determinism={!r}, required one of {}".format(det, allowed))

    # --- rollback ---------------------------------------------------------- #
    if subject in (FACET_ROLLBACK_TRANSACTIONAL, FACET_ROLLBACK_CAPABLE):
        rb = declaration.get("rollback")
        if rb == ROLLBACK_UNKNOWN or rb is None:
            return (tri.UNKNOWN,
                    "provider declares rollback={!r}; nothing supports a verdict".format(rb))
        allowed = ((ROLLBACK_TRANSACTIONAL,) if subject == FACET_ROLLBACK_TRANSACTIONAL
                   else tuple(ROLLBACK_CAPABLE))
        return (tri.from_bool(rb in allowed, measured=True),
                "provider rollback={!r}, required one of {}".format(rb, allowed))

    # --- capability / output / evidence membership ------------------------- #
    if subject.startswith(FACET_PREFIX_CAPABILITY):
        cap = subject[len(FACET_PREFIX_CAPABILITY):]
        if cap not in CAPABILITIES:
            return (tri.UNKNOWN,
                    "constraint names capability {!r}, which is not in the Core "
                    "vocabulary; it cannot be checked against any declaration".format(cap))
        return (_membership_tri(cap, declaration.get("capabilities")),
                "provider capabilities={}".format(tuple(declaration.get("capabilities") or ())))
    if subject.startswith(FACET_PREFIX_OUTPUT):
        kind = subject[len(FACET_PREFIX_OUTPUT):]
        return (_membership_tri(kind, declaration.get("outputs")),
                "provider outputs={}".format(tuple(declaration.get("outputs") or ())))
    if subject.startswith(FACET_PREFIX_EVIDENCE):
        kind = subject[len(FACET_PREFIX_EVIDENCE):]
        return (_membership_tri(kind, declaration.get("evidence")),
                "provider evidence={}".format(tuple(declaration.get("evidence") or ())))

    # --- prohibited side effects ------------------------------------------- #
    if subject.startswith(FACET_PREFIX_SIDE_EFFECT):
        kind = subject[len(FACET_PREFIX_SIDE_EFFECT):]
        if klass != K.PROHIBITED_OUTCOME:
            return (tri.UNKNOWN,
                    "a side-effect subject is only interpretable as a PROHIBITED_"
                    "OUTCOME; under class {!r} its intended sense is undefined".format(klass))
        if kind not in SIDE_EFFECT_KINDS:
            return (tri.UNKNOWN,
                    "constraint prohibits effect kind {!r}, which is not in the Core "
                    "vocabulary {}".format(kind, SIDE_EFFECT_KINDS))
        declared = declared_effect_kinds(declaration)
        return (tri.from_bool(kind not in declared, measured=True),
                "provider declares effect kinds {}".format(declared))

    if subject == FACET_MUTATION_FREE:
        if klass != K.PROHIBITED_OUTCOME:
            return (tri.UNKNOWN,
                    "mutation_free is only interpretable as a PROHIBITED_OUTCOME; "
                    "under class {!r} its sense is undefined".format(klass))
        return (tri.from_bool(not mutates_anything(declaration), measured=True),
                "provider declares effect kinds {}".format(declared_effect_kinds(declaration)))

    # --- protected semantics ----------------------------------------------- #
    if subject == FACET_SIDE_EFFECT_SCOPE:
        if klass != K.PROTECTED_SEMANTICS:
            return (tri.UNKNOWN,
                    "side_effect_scope is only interpretable as PROTECTED_SEMANTICS; "
                    "under class {!r} its sense is undefined".format(klass))
        protected = constraint.get("protected_ids")
        if not isinstance(protected, (list, tuple)) or not protected:
            return (tri.UNKNOWN,
                    "PROTECTED_SEMANTICS names no protected_ids; there is nothing to "
                    "compare the provider's declared scopes against")
        scopes = declared_effect_scopes(declaration)
        touched = sorted(set(scopes) & set(protected))
        return (tri.from_bool(not touched, measured=True),
                "provider would touch protected scope(s) {}".format(touched) if touched
                else "provider scopes {} do not intersect the protected set".format(scopes))

    # --- budgets ------------------------------------------------------------ #
    if subject.startswith(FACET_PREFIX_COST):
        metric = subject[len(FACET_PREFIX_COST):]
        limit = constraint.get("limit")
        if not isinstance(limit, (int, float)) or isinstance(limit, bool):
            return (tri.UNKNOWN,
                    "constraint declares limit={!r}; a non-numeric ceiling cannot be "
                    "compared".format(limit))
        profile = declaration.get("cost_profile")
        value = profile.get(metric) if isinstance(profile, dict) else None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return (tri.UNKNOWN,
                    "provider declares no numeric cost for metric {!r}; the budget "
                    "was never evaluated, which is not the same as being met".format(metric))
        return (tri.from_bool(value <= limit, measured=True),
                "provider cost {}={} against limit {}".format(metric, value, limit))

    return (tri.UNKNOWN,
            "subject {!r} is in the provider namespace but is not a facet this "
            "version understands; fail-closed to unknown rather than skipping it".format(subject))


def _facet_preference_value(subject: str, declaration: Dict[str, Any]) -> Optional[float]:
    """Map a provider-facing facet to a 0..1 preference value, or None if unknown.

    Avoidance facets (side effects, mutation) score 1.0 for ABSENCE, matching
    the sense they carry as prohibitions -- so a preference and a prohibition on
    the same subject never point in opposite directions.
    """
    det = declaration.get("determinism")
    if subject == FACET_DETERMINISM_SEEDED:
        return None if det in (DET_UNKNOWN, None) else (1.0 if det == DET_SEEDED else 0.0)
    if subject == FACET_DETERMINISM_ENV_STABLE:
        return (None if det in (DET_UNKNOWN, None)
                else (1.0 if det in (DET_SEEDED, DET_ENV_DEPENDENT) else 0.0))
    rb = declaration.get("rollback")
    if subject == FACET_ROLLBACK_TRANSACTIONAL:
        return (None if rb in (ROLLBACK_UNKNOWN, None)
                else (1.0 if rb == ROLLBACK_TRANSACTIONAL else 0.0))
    if subject == FACET_ROLLBACK_CAPABLE:
        return (None if rb in (ROLLBACK_UNKNOWN, None)
                else (1.0 if rb in ROLLBACK_CAPABLE else 0.0))
    if subject == FACET_MUTATION_FREE:
        return 0.0 if mutates_anything(declaration) else 1.0
    if subject.startswith(FACET_PREFIX_CAPABILITY):
        return 1.0 if subject[len(FACET_PREFIX_CAPABILITY):] in (
            declaration.get("capabilities") or ()) else 0.0
    if subject.startswith(FACET_PREFIX_OUTPUT):
        return 1.0 if subject[len(FACET_PREFIX_OUTPUT):] in (
            declaration.get("outputs") or ()) else 0.0
    if subject.startswith(FACET_PREFIX_EVIDENCE):
        return 1.0 if subject[len(FACET_PREFIX_EVIDENCE):] in (
            declaration.get("evidence") or ()) else 0.0
    if subject.startswith(FACET_PREFIX_SIDE_EFFECT):
        kind = subject[len(FACET_PREFIX_SIDE_EFFECT):]
        return 0.0 if kind in declared_effect_kinds(declaration) else 1.0
    return None


def _weight_of(constraint: Dict[str, Any]) -> float:
    w = constraint.get("weight")
    if isinstance(w, (int, float)) and not isinstance(w, bool):
        return float(w)
    return 1.0


def _cost_value(declaration: Dict[str, Any], metric: str) -> Optional[float]:
    profile = declaration.get("cost_profile")
    if not isinstance(profile, dict):
        return None
    v = profile.get(metric)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def _score(candidates: List[Dict[str, Any]],
           scoring: List[Dict[str, Any]]) -> Dict[str, Tuple[float, List[Dict[str, Any]]]]:
    """Score every candidate. Scores NEVER eliminate -- see the module docstring.

    Cost metrics are normalised across the candidate set being ranked, so a
    minimise target means "cheapest of these", not "cheap in the abstract". A
    candidate missing the metric contributes nothing for that target and is
    recorded as unscored, never assumed best.
    """
    out: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
    contributions: Dict[str, List[Dict[str, Any]]] = {
        d["provider_id"]: [] for d in candidates}
    totals: Dict[str, float] = {d["provider_id"]: 0.0 for d in candidates}

    for constraint in scoring:
        subject = constraint.get("subject") or ""
        weight = _weight_of(constraint)
        direction = constraint.get("direction")

        if subject.startswith(FACET_PREFIX_COST):
            metric = subject[len(FACET_PREFIX_COST):]
            raw = {d["provider_id"]: _cost_value(d, metric) for d in candidates}
            present = [v for v in raw.values() if v is not None]
            lo, hi = (min(present), max(present)) if present else (None, None)
            for pid, value in raw.items():
                if value is None:
                    contributions[pid].append({
                        "constraint_id": constraint.get("constraint_id"),
                        "subject": subject, "value": None, "contribution": 0.0,
                        "detail": "provider declares no cost for metric {!r}; unscored, "
                                  "not assumed favourable".format(metric)})
                    continue
                if hi == lo:
                    norm = 1.0   # no discriminating power; identical for everyone
                elif direction == K.MAXIMIZE:
                    norm = (value - lo) / (hi - lo)
                else:            # MINIMIZE is the default sense for a cost
                    norm = (hi - value) / (hi - lo)
                totals[pid] += weight * norm
                contributions[pid].append({
                    "constraint_id": constraint.get("constraint_id"),
                    "subject": subject, "value": value, "contribution": weight * norm,
                    "detail": "cost {}={} normalised to {:.6f} over [{}, {}]".format(
                        metric, value, norm, lo, hi)})
            continue

        for d in candidates:
            pid = d["provider_id"]
            value = _facet_preference_value(subject, d)
            if value is None:
                contributions[pid].append({
                    "constraint_id": constraint.get("constraint_id"),
                    "subject": subject, "value": None, "contribution": 0.0,
                    "detail": "facet {!r} cannot be evaluated against this declaration; "
                              "unscored (a preference never blocks)".format(subject)})
                continue
            if constraint.get("constraint_class") == K.OPTIMIZATION_TARGET and \
                    direction == K.MINIMIZE:
                value = 1.0 - value
            totals[pid] += weight * value
            contributions[pid].append({
                "constraint_id": constraint.get("constraint_id"),
                "subject": subject, "value": value, "contribution": weight * value,
                "detail": "facet {!r} scored {}".format(subject, value)})

    for pid in totals:
        out[pid] = (totals[pid], contributions[pid])
    return out


# --------------------------------------------------------------------------- #
# the selection itself
# --------------------------------------------------------------------------- #
def select_provider(registry: Any, request: Dict[str, Any],
                    selection_id: Optional[str] = None) -> Dict[str, Any]:
    """Select a provider for a requested RESULT, and explain the whole decision.

    Every provider that was looked at appears in ``considered`` with a status and
    the reasons that produced it -- including the ones that were never close.
    "Why not X?" must be answerable from the result alone, months later, without
    re-running anything.
    """
    capability = request.get("capability")
    required_outputs = list(request.get("required_outputs") or ())
    required_evidence = list(request.get("required_evidence") or ())
    observations = request.get("observations") or {}
    all_constraints = [c for c in (request.get("constraints") or ())
                       if isinstance(c, dict)]

    provider_facing = [c for c in all_constraints
                       if str(c.get("subject") or "").startswith(PROVIDER_SUBJECT_PREFIX)]
    filters = [c for c in provider_facing
               if c.get("constraint_class") in K.ACCEPTANCE_LOAD_BEARING]
    scoring = [c for c in provider_facing
               if c.get("constraint_class") in K.SCORING_CLASSES]

    result: Dict[str, Any] = {
        "selection_id": selection_id or "sel_{}".format(request.get("request_id")),
        "request_id": request.get("request_id"),
        "capability": capability,
        "outcome": OUTCOME_NO_CANDIDATE,
        "selected_provider": None,
        "considered": [],
        "ranking": [],
        "ambiguous_between": [],
        "tiebreak_applied": [],
        "failure_codes": [],
        "registry_snapshot": registry.snapshot() if hasattr(registry, "snapshot") else None,
        "schema_version": RT_SELECTION_RESULT,
        "report_type": RT_SELECTION_RESULT,
    }

    entries: Dict[str, Dict[str, Any]] = {}

    def _entry(pid: str) -> Dict[str, Any]:
        if pid not in entries:
            entries[pid] = {"provider_id": pid, "status": STATUS_ELIGIBLE,
                            "eligibility": tri.SATISFIED, "reasons": [], "score": None}
        return entries[pid]

    def _reason(pid, stage, subject, evaluation, detail, code=None):
        _entry(pid)["reasons"].append({
            "stage": stage, "subject": subject, "evaluation": evaluation,
            "detail": detail, "failure_code": code})

    # -- stage 1: capability + required outputs/evidence -------------------- #
    pool = registry.providers_for(capability) if capability in CAPABILITIES else ()
    pool_ids = {d.get("provider_id") for d in pool}
    candidates: List[Dict[str, Any]] = []
    for decl in registry.registered():
        pid = decl.get("provider_id")
        _entry(pid)
        if pid not in pool_ids:
            _entry(pid)["status"] = STATUS_REJECTED
            _entry(pid)["eligibility"] = tri.VIOLATED
            _reason(pid, STAGE_CAPABILITY, capability, tri.VIOLATED,
                    "provider does not offer capability {!r} (offers {})".format(
                        capability, tuple(decl.get("capabilities") or ())),
                    C.CORE_NO_PROVIDER_FOR_CAPABILITY)
            continue
        missing_out = [o for o in required_outputs if o not in (decl.get("outputs") or ())]
        missing_ev = [e for e in required_evidence if e not in (decl.get("evidence") or ())]
        if missing_out or missing_ev:
            _entry(pid)["status"] = STATUS_REJECTED
            _entry(pid)["eligibility"] = tri.VIOLATED
            _reason(pid, STAGE_OUTPUTS, capability, tri.VIOLATED,
                    "requested result needs output(s) {} and evidence {}; provider "
                    "produces {} / emits {}".format(
                        missing_out, missing_ev,
                        tuple(decl.get("outputs") or ()), tuple(decl.get("evidence") or ())),
                    C.CORE_NO_PROVIDER_FOR_CAPABILITY)
            continue
        candidates.append(decl)

    if not candidates:
        result["considered"] = _ordered_entries(entries)
        result["outcome"] = OUTCOME_NO_CANDIDATE
        result["failure_codes"] = [C.CORE_NO_PROVIDER_FOR_CAPABILITY]
        return result

    # -- stage 2: requirement eligibility (tri) ----------------------------- #
    # -- stage 3: hard-constraint FILTERS (never scores) -------------------- #
    eligible: List[Dict[str, Any]] = []
    saw_requirement_violation = False
    for decl in candidates:
        pid = decl["provider_id"]
        req_tri, trace = evaluate_requirements(decl, observations)
        for t in trace:
            if t["evaluation"] != tri.SATISFIED:
                _reason(pid, STAGE_REQUIREMENTS, t.get("subject"), t["evaluation"],
                        "requirement {!r}: {}".format(t.get("requirement_id"), t["detail"]),
                        C.CORE_PROVIDER_REQUIREMENT_UNMET
                        if t["evaluation"] == tri.VIOLATED else None)
        if req_tri == tri.VIOLATED:
            saw_requirement_violation = True

        filter_values = []
        for c in filters:
            value, detail = _facet_filter_tri(c, decl)
            filter_values.append(value)
            if value != tri.SATISFIED:
                _reason(pid, STAGE_FILTER, c.get("subject"), value,
                        "{} constraint {!r} filtered this provider: {}".format(
                            c.get("constraint_class"), c.get("constraint_id"), detail),
                        C.CORE_PROVIDER_REQUIREMENT_UNMET if value == tri.VIOLATED else None)

        overall = tri.conj([req_tri] + filter_values)
        _entry(pid)["eligibility"] = overall
        if overall == tri.VIOLATED:
            _entry(pid)["status"] = STATUS_REJECTED
        elif overall == tri.UNKNOWN:
            # NOT eligible, and NOT a failure. Reported as unknown so the fix is
            # "go measure", not "go repair something nobody observed".
            _entry(pid)["status"] = STATUS_UNKNOWN
        else:
            _entry(pid)["status"] = STATUS_ELIGIBLE
            eligible.append(decl)

    if not eligible:
        result["considered"] = _ordered_entries(entries)
        result["outcome"] = OUTCOME_NO_ELIGIBLE_CANDIDATE
        codes = [C.CORE_NO_PROVIDER_FOR_CAPABILITY]
        if saw_requirement_violation:
            codes.append(C.CORE_PROVIDER_REQUIREMENT_UNMET)
        result["failure_codes"] = codes
        return result

    # -- stage 4: score the survivors --------------------------------------- #
    scores = _score(eligible, scoring)
    for pid, (total, contribs) in scores.items():
        _entry(pid)["score"] = total
        for contrib in contribs:
            _reason(pid, STAGE_SCORING, contrib["subject"], tri.SATISFIED,
                    "{} (contribution {:+.6f})".format(contrib["detail"],
                                                       contrib["contribution"]))

    ranking = sorted(((pid, scores[pid][0]) for pid in scores),
                     key=lambda kv: (-kv[1], kv[0]))
    result["ranking"] = [{"provider_id": pid, "score": score} for pid, score in ranking]

    top_score = ranking[0][1]
    tied = [pid for pid, score in ranking if abs(score - top_score) <= SCORE_EPSILON]

    # -- stage 5: declared tiebreak criteria, then ambiguity ---------------- #
    applied: List[str] = []
    if len(tied) > 1:
        by_id = {d["provider_id"]: d for d in eligible}
        for criterion in list(request.get("tiebreak_criteria") or ()):
            values = {pid: _facet_preference_value(criterion, by_id[pid]) for pid in tied}
            comparable = {pid: (-1.0 if v is None else v) for pid, v in values.items()}
            best = max(comparable.values())
            survivors = sorted([pid for pid, v in comparable.items() if v >= best])
            applied.append(criterion)
            for pid in tied:
                _reason(pid, STAGE_TIEBREAK, criterion,
                        tri.SATISFIED if pid in survivors else tri.VIOLATED,
                        "tiebreak criterion {!r} value={!r}; {}".format(
                            criterion, values[pid],
                            "survives" if pid in survivors else "eliminated"))
            tied = survivors
            if len(tied) == 1:
                break

    result["tiebreak_applied"] = applied

    if len(tied) > 1:
        # NOT a coin flip. See the module docstring.
        result["outcome"] = OUTCOME_AMBIGUOUS
        result["ambiguous_between"] = sorted(tied)
        result["failure_codes"] = [C.CORE_PROVIDER_SELECTION_AMBIGUOUS]
        for pid in tied:
            _reason(pid, STAGE_TIEBREAK, None, tri.UNKNOWN,
                    "tied at score {} with {} and nothing in the request "
                    "distinguishes them; picking one would come from outside the "
                    "request and would not be reproducible".format(
                        top_score, sorted(p for p in tied if p != pid)),
                    C.CORE_PROVIDER_SELECTION_AMBIGUOUS)
        result["considered"] = _ordered_entries(entries)
        return result

    winner = tied[0]
    _entry(winner)["status"] = STATUS_SELECTED
    result["selected_provider"] = winner
    result["outcome"] = OUTCOME_SELECTED
    result["considered"] = _ordered_entries(entries)
    return result


def _ordered_entries(entries: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic order for the explanation. Never insertion order."""
    return [entries[pid] for pid in sorted(entries)]


def explain(result: Dict[str, Any]) -> List[str]:
    """Render a selection result as human-readable lines (one per provider).

    A machine-readable explanation nobody reads is only half of explainability.
    """
    lines = ["selection {}: outcome={} selected={}".format(
        result.get("selection_id"), result.get("outcome"), result.get("selected_provider"))]
    for entry in result.get("considered") or ():
        lines.append("  {} [{}] eligibility={} score={}".format(
            entry.get("provider_id"), entry.get("status"),
            entry.get("eligibility"), entry.get("score")))
        for reason in entry.get("reasons") or ():
            lines.append("      - {}: {}".format(reason.get("stage"), reason.get("detail")))
    return lines


# --------------------------------------------------------------------------- #
# validators
# --------------------------------------------------------------------------- #
def validate_selection_request(request: Any, strict: bool = False) -> List[Check]:
    """Validate a selection request, including the no-hardcoded-path rail.

    Structural defects in the selection surface carry WF1226: the request is part
    of the provider contract surface, and Core's provider band has one code for
    "this record cannot be trusted as written".
    """
    checks: List[Check] = []
    code = C.CORE_PROVIDER_DECLARATION_INVALID

    if not isinstance(request, dict):
        return [("selection_request_is_object", False,
                 "request must be an object, got {}".format(type(request).__name__), code)]

    for fld in SELECTION_REQUEST_REQUIRED:
        present = fld in request and request.get(fld) is not None
        checks.append(("request_has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else code))

    # --- the rail this module exists for ----------------------------------- #
    named = sorted(f for f in SELECTION_REQUEST_FORBIDDEN if f in request)
    checks.append(("request_names_no_provider", not named,
                   "request carries {}; selection is made FROM THE REQUESTED RESULT, "
                   "never from a named provider. A request that names its provider is "
                   "the hardcoded path wearing selection's clothes: it cannot be "
                   "outranked, it hides that a second provider exists, and the "
                   "resulting build records a choice nobody made".format(named)
                   if named else "request names no provider (selection is from the result)",
                   None if not named else code))

    if strict:
        extra = sorted(set(request) - set(SELECTION_REQUEST_ALLOWED))
        checks.append(("request_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))

    cap = request.get("capability")
    ok = cap in CAPABILITIES
    checks.append(("request_capability_known", ok,
                   "capability {!r} must be one of {}".format(cap, CAPABILITIES),
                   None if ok else C.CORE_PROVIDER_CAPABILITY_UNKNOWN))

    outs = request.get("required_outputs")
    ok = isinstance(outs, (list, tuple)) and len(outs) > 0 and all(
        isinstance(o, str) and o for o in outs)
    checks.append(("request_required_outputs_nonempty", ok,
                   "required_outputs must list >=1 output kind; a request that names "
                   "no result cannot select from the result (got {!r})".format(outs),
                   None if ok else code))

    cons = request.get("constraints")
    ok = isinstance(cons, (list, tuple))
    checks.append(("request_constraints_is_list", ok,
                   "constraints must be a list", None if ok else code))
    if isinstance(cons, (list, tuple)):
        for idx, c in enumerate(cons):
            for (name, sub_ok, detail, sub_code) in K.validate_constraint(c, strict=strict):
                checks.append(("constraint[{}].{}".format(idx, name), sub_ok, detail, sub_code))

    obs = request.get("observations")
    ok = isinstance(obs, dict)
    checks.append(("request_observations_is_object", ok,
                   "observations must be an object mapping observation keys to "
                   "measurements; absent, every requirement is unknown and nothing "
                   "can be selected (got {!r})".format(type(obs).__name__),
                   None if ok else code))

    tb = request.get("tiebreak_criteria")
    if tb is not None:
        ok = isinstance(tb, (list, tuple)) and all(
            isinstance(t, str) and t.startswith(PROVIDER_SUBJECT_PREFIX) for t in tb)
        checks.append(("request_tiebreak_criteria_are_facets", ok,
                       "tiebreak_criteria must be provider-facing facet subjects "
                       "(prefix {!r}), never provider names -- a tiebreak by name is "
                       "a hardcoded path with extra steps (got {!r})".format(
                           PROVIDER_SUBJECT_PREFIX, tb), None if ok else code))

    sv = request.get("schema_version")
    ok = sv == RT_SELECTION_REQUEST
    checks.append(("request_schema_version", ok,
                   "schema_version must be {!r} (got {!r})".format(RT_SELECTION_REQUEST, sv),
                   None if ok else code))
    return checks


def validate_selection_result(result: Any, strict: bool = False) -> List[Check]:
    """Validate a selection result, including the explainability rails.

    The rails encode what a selection result must never be able to say:
      * a selection with no basis (nothing eligible, yet something selected)
      * a rejection with no recoverable reason
      * an UNKNOWN eligibility reported as a requirement FAILURE
      * a winner that merely tied, with no tiebreak recorded
    """
    checks: List[Check] = []
    code = C.CORE_PROVIDER_DECLARATION_INVALID

    if not isinstance(result, dict):
        return [("selection_result_is_object", False,
                 "result must be an object, got {}".format(type(result).__name__), code)]

    for fld in SELECTION_RESULT_REQUIRED:
        present = fld in result
        checks.append(("result_has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else code))

    if strict:
        extra = sorted(set(result) - set(SELECTION_RESULT_ALLOWED))
        checks.append(("result_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))

    outcome = result.get("outcome")
    ok = outcome in SELECTION_OUTCOMES
    checks.append(("result_outcome_known", ok,
                   "outcome {!r} must be one of {}".format(outcome, SELECTION_OUTCOMES),
                   None if ok else code))

    considered = result.get("considered")
    ok = isinstance(considered, (list, tuple))
    checks.append(("result_considered_is_list", ok,
                   "considered must be a list of per-provider explanations",
                   None if ok else code))
    codes = list(result.get("failure_codes") or ())

    if isinstance(considered, (list, tuple)):
        for idx, entry in enumerate(considered):
            prefix = "considered[{}]".format(idx)
            if not isinstance(entry, dict):
                checks.append((prefix + ".is_object", False,
                               "each considered entry must be an object", code))
                continue
            st = entry.get("status")
            checks.append((prefix + ".status_known", st in CANDIDATE_STATUSES,
                           "status {!r} must be one of {}".format(st, CANDIDATE_STATUSES),
                           None if st in CANDIDATE_STATUSES else code))
            el = entry.get("eligibility")
            checks.append((prefix + ".eligibility_is_tri", el in tri.TRI_VALUES,
                           "eligibility {!r} must be one of {}".format(el, tri.TRI_VALUES),
                           None if el in tri.TRI_VALUES else code))
            reasons = entry.get("reasons")
            reasons = reasons if isinstance(reasons, (list, tuple)) else []

            if st == STATUS_REJECTED:
                coded = [r for r in reasons
                         if isinstance(r, dict) and r.get("failure_code")]
                checks.append((prefix + ".rejection_is_explained", bool(coded),
                               "provider {!r} is rejected with no reason carrying a "
                               "failure code; an unexplained rejection makes 'why not "
                               "this one?' unanswerable after the run".format(
                                   entry.get("provider_id")),
                               None if coded else code))

            if st == STATUS_UNKNOWN or el == tri.UNKNOWN:
                mislabelled = [r for r in reasons
                               if isinstance(r, dict)
                               and r.get("evaluation") == tri.UNKNOWN
                               and r.get("failure_code") == C.CORE_PROVIDER_REQUIREMENT_UNMET]
                checks.append((prefix + ".unknown_not_reported_as_unmet", not mislabelled,
                               "provider {!r} has UNKNOWN eligibility but a reason "
                               "carries {}; an unmeasured requirement must never be "
                               "reported as a failed one -- that states a defect nobody "
                               "observed and sends repair after it".format(
                                   entry.get("provider_id"),
                                   C.CORE_PROVIDER_REQUIREMENT_UNMET),
                               None if not mislabelled else C.CORE_PROVIDER_REQUIREMENT_UNMET))

            checks.append((prefix + ".not_selected_while_unknown",
                           not (st == STATUS_SELECTED and el != tri.SATISFIED),
                           "provider {!r} is SELECTED with eligibility {!r}; selection "
                           "requires satisfied eligibility, never merely 'not violated'"
                           .format(entry.get("provider_id"), el),
                           None if not (st == STATUS_SELECTED and el != tri.SATISFIED)
                           else C.CORE_NO_PROVIDER_FOR_CAPABILITY))

    selected = result.get("selected_provider")
    ranking = result.get("ranking") if isinstance(result.get("ranking"), (list, tuple)) else []
    ambiguous = result.get("ambiguous_between")
    ambiguous = list(ambiguous) if isinstance(ambiguous, (list, tuple)) else []
    tiebreak = result.get("tiebreak_applied")
    tiebreak = list(tiebreak) if isinstance(tiebreak, (list, tuple)) else []

    if outcome == OUTCOME_SELECTED:
        ok = isinstance(selected, str) and bool(selected)
        checks.append(("result_selected_names_provider", ok,
                       "outcome=selected requires selected_provider (got {!r})".format(selected),
                       None if ok else code))
        ok = not codes
        checks.append(("result_selected_has_no_failure_codes", ok,
                       "outcome=selected must carry an empty failure_codes list "
                       "(got {})".format(codes), None if ok else code))
        ok = bool(result.get("registry_snapshot"))
        checks.append(("result_selected_records_the_pool", ok,
                       "outcome=selected must carry the registry_snapshot it chose "
                       "from; without the candidate set, the choice cannot be "
                       "re-checked later and 'X was chosen' is unfalsifiable",
                       None if ok else code))
        # --- the anti-arbitrary-pick rail --------------------------------- #
        scores = [r.get("score") for r in ranking
                  if isinstance(r, dict) and isinstance(r.get("score"), (int, float))]
        if len(scores) >= 2:
            ordered = sorted(scores, reverse=True)
            strict_win = (ordered[0] - ordered[1]) > SCORE_EPSILON
            ok = strict_win or bool(tiebreak)
            checks.append(("result_winner_is_not_an_arbitrary_pick", ok,
                           "top two scores are {} and {} (tied within {}) and "
                           "tiebreak_applied is empty; a winner that merely tied was "
                           "picked by something outside the request, which makes the "
                           "build non-reproducible and the reason unrecoverable"
                           .format(ordered[0], ordered[1], SCORE_EPSILON),
                           None if ok else C.CORE_PROVIDER_SELECTION_AMBIGUOUS))
    else:
        ok = selected is None
        checks.append(("result_unselected_has_no_provider", ok,
                       "outcome={!r} must leave selected_provider null (got {!r})".format(
                           outcome, selected), None if ok else code))
        ok = bool(codes)
        checks.append(("result_unselected_carries_a_code", ok,
                       "outcome={!r} must carry >=1 failure_code explaining why nothing "
                       "was selected".format(outcome), None if ok else code))

    if outcome == OUTCOME_AMBIGUOUS:
        ok = len(ambiguous) >= 2
        checks.append(("result_ambiguous_names_the_tie", ok,
                       "outcome=ambiguous must list >=2 providers in ambiguous_between "
                       "(got {})".format(ambiguous), None if ok else code))
        ok = C.CORE_PROVIDER_SELECTION_AMBIGUOUS in codes
        checks.append(("result_ambiguous_carries_its_code", ok,
                       "outcome=ambiguous must carry {} (got {})".format(
                           C.CORE_PROVIDER_SELECTION_AMBIGUOUS, codes),
                       None if ok else C.CORE_PROVIDER_SELECTION_AMBIGUOUS))
    else:
        ok = not ambiguous
        checks.append(("result_non_ambiguous_has_no_tie_set", ok,
                       "ambiguous_between must be empty unless outcome=ambiguous "
                       "(got {})".format(ambiguous), None if ok else code))

    if outcome == OUTCOME_NO_CANDIDATE:
        ok = C.CORE_NO_PROVIDER_FOR_CAPABILITY in codes
        checks.append(("result_no_candidate_carries_its_code", ok,
                       "outcome=no_candidate must carry {} (got {})".format(
                           C.CORE_NO_PROVIDER_FOR_CAPABILITY, codes),
                       None if ok else C.CORE_NO_PROVIDER_FOR_CAPABILITY))

    sv = result.get("schema_version")
    ok = sv == RT_SELECTION_RESULT
    checks.append(("result_schema_version", ok,
                   "schema_version must be {!r} (got {!r})".format(RT_SELECTION_RESULT, sv),
                   None if ok else code))
    return checks


# --------------------------------------------------------------------------- #
# canonical example factories
# --------------------------------------------------------------------------- #
def _example_selection_request(**over: Any) -> Dict[str, Any]:
    """Canonical-valid request. Domain-neutral; states a RESULT, not a provider."""
    d: Dict[str, Any] = {
        "request_id": "req_author_surface_materials",
        "capability": "material_authoring",
        "required_outputs": ["authored_asset_set"],
        "required_evidence": ["operation_manifest"],
        "constraints": [
            K._example_constraint(
                constraint_id="c_provider_must_be_seeded",
                constraint_class=K.HARD_INVARIANT,
                subject=FACET_DETERMINISM_SEEDED,
                detail="the provider must be reproducible from a seed"),
            K._example_constraint(
                constraint_id="c_prefer_transactional_rollback",
                constraint_class=K.SOFT_PREFERENCE,
                subject=FACET_ROLLBACK_TRANSACTIONAL,
                detail="prefer a provider with a real undo boundary",
                weight=1.0),
        ],
        "observations": {"engine.authoring_session_open": True},
        "tiebreak_criteria": [FACET_ROLLBACK_TRANSACTIONAL],
        "created_by": "worldforge.core",
        "schema_version": RT_SELECTION_REQUEST,
        "report_type": RT_SELECTION_REQUEST,
    }
    d.update(over)
    return d


def _example_selection_result(**over: Any) -> Dict[str, Any]:
    """Canonical-valid result: one winner, one explained rejection."""
    d: Dict[str, Any] = {
        "selection_id": "sel_req_author_surface_materials",
        "request_id": "req_author_surface_materials",
        "capability": "material_authoring",
        "outcome": OUTCOME_SELECTED,
        "selected_provider": "editor_authoring_bridge",
        "considered": [
            {"provider_id": "editor_authoring_bridge", "status": STATUS_SELECTED,
             "eligibility": tri.SATISFIED, "score": 1.0,
             "reasons": [{"stage": STAGE_SCORING,
                          "subject": FACET_ROLLBACK_TRANSACTIONAL,
                          "evaluation": tri.SATISFIED,
                          "detail": "facet scored 1.0 (contribution +1.000000)",
                          "failure_code": None}]},
            {"provider_id": "runtime_authoring_bridge", "status": STATUS_REJECTED,
             "eligibility": tri.VIOLATED, "score": None,
             "reasons": [{"stage": STAGE_FILTER,
                          "subject": FACET_DETERMINISM_SEEDED,
                          "evaluation": tri.VIOLATED,
                          "detail": "hard_invariant filtered this provider: "
                                    "provider determinism='nondeterministic'",
                          "failure_code": C.CORE_PROVIDER_REQUIREMENT_UNMET}]},
        ],
        "ranking": [{"provider_id": "editor_authoring_bridge", "score": 1.0}],
        "ambiguous_between": [],
        "tiebreak_applied": [],
        "failure_codes": [],
        "registry_snapshot": {"registry_id": "wfcore_capability_registry",
                              "providers": ["editor_authoring_bridge",
                                            "runtime_authoring_bridge"]},
        "created_by": "worldforge.core",
        "schema_version": RT_SELECTION_RESULT,
        "report_type": RT_SELECTION_RESULT,
    }
    d.update(over)
    return d
