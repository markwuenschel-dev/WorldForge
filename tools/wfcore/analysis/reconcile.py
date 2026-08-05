#!/usr/bin/env python3
"""wfcore.analysis.reconcile -- reconcile the DESIRED world against the OBSERVED
world and emit a typed ``ConstraintAnalysis`` that plan synthesis consumes.

Run the suite from ``tools/``::

    PYTHONUTF8=1 python -m wfcore.analysis.test_reconcile

THE RECORD, AND WHY IT CARRIES SO MUCH
--------------------------------------
A finding is not ``{constraint_id: verdict}``. A bare verdict is unfalsifiable:
nothing in it says what was compared, so a wrong verdict and a right one are the
same document, and the only way to audit the analysis is to re-run the analyser
that produced it. So every finding states, in the record itself:

    comparison   the comparison KIND, the desired value, the observed value, the
                 tolerance applied and which constraint supplied it
    evidence     one record per observed field consulted -- its path, whether it
                 was backed, its provenance, its operation, its evidence refs
    evaluation   the tri-value
    remedy       MEASURE (go observe) or CHANGE_THE_WORLD (author a change)
    failure_codes the codes this finding raises

``validate_constraint_analysis`` then RE-DERIVES each verdict from the written
comparison and evidence alone -- see "non-circular re-derivation" below.

THE FOUR REFUSALS
-----------------
1. NOT THE SAME WORLD. ``models.observed_world.validate_model_pair`` /
   ``same_world`` decide; ``tri.accepts`` gates. A mismatch refuses with
   ``CORE_MODEL_IDENTITY_MISMATCH``, an unestablished observed identity with
   ``CORE_OBSERVED_WORLD_UNBACKED``. Differencing unrelated worlds yields a
   plausible, entirely meaningless plan.

   The refusal sets ``acceptance_verdict`` to ``tri.UNKNOWN`` EXPLICITLY. Folding
   the empty finding list would return SATISFIED by ``tri.conj``'s identity --
   a refusal that reads as an acceptance is the worst possible failure shape, and
   it arrives for free unless it is written out by hand.

2. AN UNEVALUABLE CONSTRAINT IS UNKNOWN. Never coerced to VIOLATED (that sends
   repair to fix something nobody measured) and never to SATISFIED (that
   fabricates evidence). It raises ``CORE_CONSTRAINT_NOT_EVALUATED`` (WF1202)
   when its class is acceptance-load-bearing, because only there does an
   unmeasured constraint stall the pipeline forever.

   ``DECLARED_UNKNOWN`` is exempt from WF1202 and always will be: it evaluates to
   UNKNOWN *by construction* via ``constraints.evaluate_declared_unknown``. It
   was evaluated; its evaluation is "undecided", and the consumer -- not Core --
   resolves it. Its remedy is DECIDE, not MEASURE, for exactly the reason
   ``contracts.acceptance_criteria`` exempts it from evaluation requirements:
   Core going to measure the consumer's own undecided intent is the authority
   inversion wearing a check.

3. AN UNBACKED OBSERVED FIELD IS UNKNOWN, NOT SATISFIED. An observed field is a
   record, not a scalar, so backing is consulted through
   ``observed_world.is_backed`` before the value is ever read. A supplied
   measurement that is not a world field (a budget's measured cost, say) gets the
   SAME rail: it must be a field record, its operation must be declared in the
   observed model, and its evidence refs must resolve in that model's index. A
   measurement exempt from backing is a request value wearing a measurement's
   record shape, which is precisely what ``observed_world`` exists to prevent.

4. A TOLERANCE IS NEVER EVALUATED STANDALONE. It has no truth value -- "0.5" is
   neither satisfied nor violated. It parameterises another constraint's
   comparison, and a tolerance naming no target raises
   ``CORE_TOLERANCE_WITHOUT_TARGET``. ``OPTIMIZATION_TARGET`` joins it in
   ``NON_PREDICATE_CLASSES`` for the neighbouring reason: a direction to optimise
   along has no pass/fail at all, so manufacturing one would invent a gate the
   consumer never declared. Neither class appears in
   ``constraints.ACCEPTANCE_LOAD_BEARING``, so excluding both from the fold
   cannot move the verdict -- asserted, not assumed, by
   ``test_non_predicate_classes_are_never_load_bearing``.

HOW THE DESIRED SIDE IS RESOLVED (AND WHY THERE ARE NO DEFAULTS)
-----------------------------------------------------------------
A constraint is bound to an observed field path -- explicitly via ``bindings``,
or implicitly when its ``subject`` already IS a path in the observed model. From
that path the desired counterpart is resolved through ``OBSERVED_ATTR_DESIRED``,
one visible table mapping an observed attribute to where its intent lives:

    ("declared", True)   the desired model DECLARING the entity/relation is the
                         intent -- a declared anchor must be present, a declared
                         relation must hold. If the desired model declares no
                         such entity, there is no intent to compare against and
                         the verdict is UNKNOWN. Not True-by-default.
    ("desired_field", n) read attribute ``n`` off the desired entry. Absent ->
                         UNKNOWN.
    Two classes supply their own desired side from the class definition rather
    than the model: ``PROHIBITED_OUTCOME`` expects False (that is what prohibited
    MEANS) and ``PROTECTED_SEMANTICS`` expects the set of changed protected
    identities to be empty. Both are stated by the taxonomy, not defaulted here.

NON-CIRCULAR RE-DERIVATION
--------------------------
``validate_constraint_analysis`` does NOT re-run ``reconcile`` and does not call
the evaluation helpers ``reconcile`` used. Re-deriving a verdict with the
producer's own function proves only that the function is deterministic.

Instead ``_recompute_from_record`` reads ONLY what the finding wrote down -- the
comparison kind, the desired value, the observed value, the tolerance, and
whether each cited evidence record was backed -- and recomputes the tri-value
from those raw fields with a comparator selected by the recorded kind. It never
touches the desired or observed model. A producer that folded a verdict its own
record does not support is therefore caught, which is the only failure this
check can honestly claim to catch.

The acceptance verdict is checked the same way: recomputed per finding, folded by
the validator's own reading of ``constraints.ACCEPTANCE_LOAD_BEARING``, and
compared against the recorded verdict.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import constraints as K
from .. import tri
from ..failure import FailureCode as C
from ..models import desired_world as DW
from ..models import observed_world as OW

# --------------------------------------------------------------------------- #
# schema identity
# --------------------------------------------------------------------------- #
RT_CONSTRAINT_ANALYSIS = "wf.core.constraint_analysis.v1"
RT_CONSTRAINT_FINDING = "wf.core.constraint_finding.v1"

# --------------------------------------------------------------------------- #
# What the analysis compared. The kind is written into the record so a reader --
# and the validator's independent re-derivation -- knows which comparator the
# desired/observed pair was judged with.
# --------------------------------------------------------------------------- #
COMPARE_EQUALITY = "equality"
COMPARE_NUMERIC_TOLERANCE = "numeric_within_tolerance"
COMPARE_BUDGET_LIMIT = "budget_within_limit"
COMPARE_PROTECTED_UNCHANGED = "protected_identity_unchanged"
COMPARE_DECLARED_UNKNOWN = "declared_unknown_by_construction"
COMPARE_NOT_A_PREDICATE = "not_a_predicate"
COMPARE_NOT_EVALUATED = "not_evaluated"

COMPARISON_KINDS = (COMPARE_EQUALITY, COMPARE_NUMERIC_TOLERANCE,
                    COMPARE_BUDGET_LIMIT, COMPARE_PROTECTED_UNCHANGED,
                    COMPARE_DECLARED_UNKNOWN, COMPARE_NOT_A_PREDICATE,
                    COMPARE_NOT_EVALUATED)

# --------------------------------------------------------------------------- #
# The remedy vocabulary -- the whole reason the analysis is typed. MEASURE and
# CHANGE_THE_WORLD route to different halves of the pipeline, and DECIDE routes
# out of it entirely, back to the consumer that declared the unknown.
# --------------------------------------------------------------------------- #
REMEDY_NONE = "none"
REMEDY_MEASURE = "measure"
REMEDY_CHANGE_THE_WORLD = "change_the_world"
REMEDY_DECIDE = "consumer_decides"

REMEDIES = (REMEDY_NONE, REMEDY_MEASURE, REMEDY_CHANGE_THE_WORLD, REMEDY_DECIDE)

# The remedy each tri-value demands. One table, read by the producer and by the
# validator, so "unknown means go measure" is stated once instead of retyped.
REMEDY_FOR_EVALUATION = {
    tri.SATISFIED: REMEDY_NONE,
    tri.VIOLATED: REMEDY_CHANGE_THE_WORLD,
    tri.UNKNOWN: REMEDY_MEASURE,
}

# Classes that carry no truth value of their own. See refusal 4 in the docstring.
NON_PREDICATE_CLASSES = (K.TOLERANCE, K.OPTIMIZATION_TARGET)

# --------------------------------------------------------------------------- #
# Where an observed attribute's INTENT lives on the desired side. The only
# correspondence table in this module; an attribute absent from it is one the
# analyser has no stated way to judge, which is UNKNOWN, not a guess.
# --------------------------------------------------------------------------- #
DECLARED = "declared"
DESIRED_FIELD = "desired_field"

OBSERVED_ATTR_DESIRED = {
    "present": (DECLARED, True),
    "holds": (DECLARED, True),
    "state_value": (DESIRED_FIELD, "state_value"),
    "count": (DESIRED_FIELD, "target_count"),
    "role": (DESIRED_FIELD, "role"),
}

# The observed attribute that answers "was this identity changed". A
# PROTECTED_SEMANTICS constraint is judged against it, per protected id.
PROTECTED_CHANGE_ATTR = "changed"

# --------------------------------------------------------------------------- #
# record shapes
# --------------------------------------------------------------------------- #
COMPARISON_REQUIRED = ("comparison_kind", "subject", "observed_paths",
                       "desired_value", "observed_value", "tolerance",
                       "tolerance_id", "unit", "detail")

EVIDENCE_RECORD_REQUIRED = ("path", "backed", "provenance", "operation_id",
                            "observed_by", "evidence_refs")

FINDING_REQUIRED = ("constraint_id", "constraint_class", "evaluation",
                    "acceptance_load_bearing", "comparison", "evidence",
                    "remedy", "failure_codes", "detail", "schema_version")
FINDING_ALLOWED = FINDING_REQUIRED + ("notes",)

ANALYSIS_REQUIRED = ("world_identity", "same_world", "reconciled",
                     "refusal_reason", "findings", "satisfied", "violated",
                     "unknown", "not_a_predicate", "acceptance_verdict",
                     "blockers", "failure_codes", "schema_version")
ANALYSIS_ALLOWED = ANALYSIS_REQUIRED + ("report_type", "created_by",
                                        "created_at", "meta", "notes")

Check = Tuple[str, bool, str, Optional[str]]

_P = "ca::"
_FP = "cf::"


# --------------------------------------------------------------------------- #
# small readers
# --------------------------------------------------------------------------- #
def _is_number(x: Any) -> bool:
    """Numeric, and ``bool`` is NOT numeric here.

    ``isinstance(True, int)`` is True in Python, so a boolean would slide into
    every numeric comparison as 0/1 and compare equal to a count of zero or one.
    """
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def constraints_of(request: Any) -> List[Dict[str, Any]]:
    """The constraint list, from a world request or from a bare list.

    Accepts both because the analysis is run against a request in production and
    against a constraint set in tests, and forcing the test to build a whole
    request would make the test suite depend on a contract it is not exercising.
    """
    if isinstance(request, dict):
        raw = request.get("constraints")
    else:
        raw = request
    if not isinstance(raw, (list, tuple)):
        return []
    return [c for c in raw if isinstance(c, dict)]


def tolerance_for(constraints: Sequence[Dict[str, Any]],
                  constraint_id: Any) -> Optional[Dict[str, Any]]:
    """The TOLERANCE constraint parameterising ``constraint_id``, if any."""
    for c in constraints:
        if (c.get("constraint_class") == K.TOLERANCE
                and c.get("applies_to") == constraint_id):
            return c
    return None


def _parse_path(path: Any) -> Optional[Tuple[str, str, str]]:
    """``<section>.entities.<entity_id>.<attr>`` -> ``(section, entity, attr)``."""
    if not isinstance(path, str):
        return None
    parts = path.split(".")
    if len(parts) < 4 or parts[1] != OW.ENTITIES_KEY:
        return None
    section, entity_id, attr = parts[0], parts[2], ".".join(parts[3:])
    if section not in OW.OBSERVED_SECTIONS:
        return None
    return section, entity_id, attr


def _desired_entry(desired: Any, section: str,
                   entity_id: str) -> Optional[Dict[str, Any]]:
    """The desired entry declaring ``entity_id`` in ``section``, or None.

    None is load-bearing: it means the consumer declared no intent about this
    entity, so there is nothing to compare the measurement against.
    """
    spec = DW.SECTION_SPEC.get(section)
    if spec is None or not isinstance(desired, dict):
        return None
    id_field = spec[1]
    entries = desired.get(section)
    if not isinstance(entries, (list, tuple)):
        return None
    for e in entries:
        if isinstance(e, dict) and e.get(id_field) == entity_id:
            return e
    return None


def _evidence_record(path: Any, field: Any, backed: bool) -> Dict[str, Any]:
    """One evidence row: WHICH observed field was consulted, and was it backed."""
    f = field if isinstance(field, dict) else {}
    refs = f.get("evidence_refs")
    return {
        "path": path,
        "backed": bool(backed),
        "provenance": f.get("provenance"),
        "operation_id": f.get("operation_id"),
        "observed_by": f.get("observed_by"),
        "evidence_refs": list(refs) if isinstance(refs, list) else [],
    }


def measurement_is_backed(observed: Any, field: Any) -> bool:
    """A supplied measurement gets the observed model's backing rail, in full.

    Three conditions, all cross-record on purpose (a forged measurement must
    therefore also forge an operation and an evidence entry in the model it
    claims to have been taken against):

      1. it is a backed observed field (``observed_world.is_backed``);
      2. the operation it cites is declared in THIS observed model, and for a
         MEASURED field that operation reports ``ok=True``;
      3. every evidence ref it cites resolves in THIS model's evidence index.
    """
    if not OW.is_backed(field):
        return False
    op = OW.operation_by_id(observed, field.get("operation_id"))
    if op is None:
        return False
    if field.get("provenance") == OW.MEASURED and op.get("ok") is not True:
        return False
    index = observed.get("evidence_index") if isinstance(observed, dict) else None
    if not isinstance(index, dict):
        return False
    refs = field.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        return False
    return all(r in index for r in refs)


# --------------------------------------------------------------------------- #
# comparison
# --------------------------------------------------------------------------- #
def _blank_comparison(kind: str, subject: Any, detail: str,
                      **over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "comparison_kind": kind,
        "subject": subject,
        "observed_paths": [],
        "desired_value": None,
        "observed_value": None,
        "tolerance": None,
        "tolerance_id": None,
        "unit": None,
        "detail": detail,
    }
    d.update(over)
    return d


def _compare(kind: str, desired_value: Any, observed_value: Any,
             tolerance: Any) -> str:
    """The comparators, in one place, keyed by comparison kind.

    Used by the producer AND by the validator's independent re-derivation. Both
    reading one table is what makes the re-derivation a check on the VERDICT
    rather than a second implementation that can drift into agreeing by accident
    -- the validator supplies its inputs from the written record, not from the
    models, so a producer that wrote a verdict its own record contradicts fails.
    """
    tol = tolerance if _is_number(tolerance) else 0
    if kind == COMPARE_BUDGET_LIMIT:
        if not (_is_number(observed_value) and _is_number(desired_value)):
            return tri.UNKNOWN
        return tri.from_bool(observed_value <= desired_value + tol)
    if kind == COMPARE_NUMERIC_TOLERANCE:
        if not (_is_number(observed_value) and _is_number(desired_value)):
            return tri.UNKNOWN
        return tri.from_bool(abs(observed_value - desired_value) <= tol)
    if kind in (COMPARE_EQUALITY, COMPARE_PROTECTED_UNCHANGED):
        return tri.from_bool(observed_value == desired_value)
    # COMPARE_DECLARED_UNKNOWN and COMPARE_NOT_EVALUATED both mean "no verdict
    # is supported", which is UNKNOWN and never anything else.
    return tri.UNKNOWN


# --------------------------------------------------------------------------- #
# per-class evaluation
# --------------------------------------------------------------------------- #
def _finding(constraint: Dict[str, Any], evaluation: Optional[str],
             comparison: Dict[str, Any], evidence: List[Dict[str, Any]],
             codes: List[str], detail: str) -> Dict[str, Any]:
    klass = constraint.get("constraint_class")
    if evaluation is None:
        remedy = REMEDY_NONE
    elif klass == K.DECLARED_UNKNOWN and evaluation == tri.UNKNOWN:
        remedy = REMEDY_DECIDE
    else:
        remedy = REMEDY_FOR_EVALUATION[evaluation]
    return {
        "constraint_id": constraint.get("constraint_id"),
        "constraint_class": klass,
        "evaluation": evaluation,
        "acceptance_load_bearing": K.is_acceptance_load_bearing(constraint),
        "comparison": comparison,
        "evidence": evidence,
        "remedy": remedy,
        "failure_codes": sorted(set(codes)),
        "detail": detail,
        "schema_version": RT_CONSTRAINT_FINDING,
    }


def _not_evaluated(constraint: Dict[str, Any], reason: str,
                   evidence: Optional[List[Dict[str, Any]]] = None,
                   extra_codes: Sequence[str] = ()) -> Dict[str, Any]:
    """The UNKNOWN finding. WF1202 only when the class can actually stall things.

    A non-load-bearing constraint nobody measured cannot hold up acceptance, and
    publishing WF1202 for it would train readers to ignore a code that elsewhere
    means "this pipeline can never finish". DECLARED_UNKNOWN never reaches here.
    """
    codes = list(extra_codes)
    if K.is_acceptance_load_bearing(constraint):
        codes.append(C.CORE_CONSTRAINT_NOT_EVALUATED)
    return _finding(
        constraint, tri.UNKNOWN,
        _blank_comparison(COMPARE_NOT_EVALUATED,
                          constraint.get("subject"), reason),
        evidence or [], codes, reason)


def _resolve_path(constraint: Dict[str, Any], observed: Any,
                  bindings: Dict[Any, str]) -> Optional[str]:
    """The observed field path this constraint is judged against, or None.

    Explicit ``bindings`` win; otherwise a ``subject`` that already IS a path in
    the observed model is used. Nothing is inferred from a subject that merely
    resembles one -- an almost-matching path resolved by fuzzy rules would judge
    a constraint against a field the consumer never named.
    """
    cid = constraint.get("constraint_id")
    fm = OW.field_map(observed)
    bound = bindings.get(cid)
    if isinstance(bound, str):
        return bound if bound in fm else None
    subject = constraint.get("subject")
    if isinstance(subject, str) and subject in fm:
        return subject
    return None


def _eval_path_constraint(constraint: Dict[str, Any], desired: Any,
                          observed: Any, path: str, tol_constraint: Any,
                          desired_side: Optional[Tuple[str, Any]] = None
                          ) -> Dict[str, Any]:
    """Judge one constraint bound to one observed field path.

    ``desired_side``, when given, is the class supplying its own intent (a
    PROHIBITED_OUTCOME expects False because that is what prohibited means).
    Otherwise the intent is resolved from the desired model via
    ``OBSERVED_ATTR_DESIRED``, and an unresolvable intent is UNKNOWN.
    """
    fm = OW.field_map(observed)
    field = fm.get(path)
    backed = OW.is_backed(field)
    evidence = [_evidence_record(path, field, backed)]

    parsed = _parse_path(path)
    if parsed is None:
        return _not_evaluated(
            constraint,
            "observed path {!r} is not an entity attribute path of the form "
            "<section>.entities.<entity_id>.<attribute>, so no desired "
            "counterpart can be resolved for it".format(path), evidence)
    section, entity_id, attr = parsed

    # --- the desired side ---------------------------------------------------- #
    if desired_side is not None:
        source, desired_value = desired_side
    else:
        spec = OBSERVED_ATTR_DESIRED.get(attr)
        if spec is None:
            return _not_evaluated(
                constraint,
                "observed attribute {!r} has no stated correspondence to any "
                "desired attribute; judging it would mean inventing what the "
                "consumer meant by it".format(attr), evidence)
        source, ref = spec
        entry = _desired_entry(desired, section, entity_id)
        if entry is None:
            return _not_evaluated(
                constraint,
                "the desired world declares no {} with id {!r}, so there is no "
                "stated intent to compare the measurement against".format(
                    section, entity_id), evidence)
        if source == DECLARED:
            desired_value = ref
        else:
            if ref not in entry:
                return _not_evaluated(
                    constraint,
                    "the desired {} {!r} states no {!r}, so the measurement has "
                    "nothing to be judged against".format(
                        section, entity_id, ref), evidence)
            desired_value = entry.get(ref)

    # --- the observed side --------------------------------------------------- #
    has, observed_value = OW.read(field)
    if not has:
        prov = field.get("provenance") if isinstance(field, dict) else None
        return _not_evaluated(
            constraint,
            "observed field {!r} carries no measurement (provenance={!r}); an "
            "unbacked field is UNKNOWN, and reading it as satisfied would "
            "fabricate the evidence the verdict rests on".format(path, prov),
            evidence, extra_codes=(C.CORE_OBSERVED_WORLD_UNBACKED,))

    # --- the comparison ------------------------------------------------------ #
    codes: List[str] = []
    tol_value = tol_constraint.get("limit") if isinstance(tol_constraint, dict) \
        else None
    numeric = _is_number(desired_value) and _is_number(observed_value)
    if numeric:
        kind = COMPARE_NUMERIC_TOLERANCE
    else:
        kind = COMPARE_EQUALITY
        if tol_value is not None:
            # A tolerance declared for a non-numeric comparison widens nothing;
            # it reads, in a report, as slack that was applied.
            codes.append(C.CORE_CONSTRAINT_INVALID)
            tol_value = None

    evaluation = _compare(kind, desired_value, observed_value, tol_value)
    comparison = _blank_comparison(
        kind, constraint.get("subject"),
        "compared observed {} against desired {}{}".format(
            path, desired_value,
            " with tolerance {}".format(tol_value)
            if tol_value is not None else ""),
        observed_paths=[path], desired_value=desired_value,
        observed_value=observed_value, tolerance=tol_value,
        tolerance_id=(tol_constraint or {}).get("constraint_id")
        if isinstance(tol_constraint, dict) else None,
        unit=(tol_constraint or {}).get("unit")
        if isinstance(tol_constraint, dict) else None)
    return _finding(constraint, evaluation, comparison, evidence, codes,
                    comparison["detail"])


def _eval_budget(constraint: Dict[str, Any], observed: Any, path: Optional[str],
                 measurement: Any, tol_constraint: Any) -> Dict[str, Any]:
    """A BUDGET is judged against its own declared ``limit``. WF1215 raise site.

    The limit comes from the constraint, never from the desired world: a budget
    IS the ceiling the consumer stated, and looking one up elsewhere would let
    the ceiling drift away from the statement that published it.
    """
    limit = constraint.get("limit")
    if not _is_number(limit):
        return _finding(
            constraint, tri.UNKNOWN,
            _blank_comparison(COMPARE_NOT_EVALUATED, constraint.get("subject"),
                              "BUDGET declares limit={!r}, which is not a "
                              "numeric ceiling; nothing can exceed it, so it "
                              "can never fail".format(limit)),
            [], [C.CORE_CONSTRAINT_INVALID, C.CORE_CONSTRAINT_NOT_EVALUATED],
            "budget has no numeric ceiling")

    field = None
    source = None
    if measurement is not None:
        field, source = measurement, "measurement"
    elif path is not None:
        field, source = OW.field_map(observed).get(path), path

    backed = (measurement_is_backed(observed, field) if source == "measurement"
              else OW.is_backed(field))
    evidence = [_evidence_record(source, field, backed)] if field is not None \
        else []

    if field is None:
        return _not_evaluated(
            constraint,
            "no measurement is bound to this budget; a ceiling nobody measured "
            "against cannot be exceeded or respected", evidence)
    if not backed:
        prov = field.get("provenance") if isinstance(field, dict) else None
        return _not_evaluated(
            constraint,
            "the measurement bound to this budget carries no backing "
            "(provenance={!r}); an unbacked cost is UNKNOWN, not within "
            "budget".format(prov),
            evidence, extra_codes=(C.CORE_OBSERVED_WORLD_UNBACKED,))

    measured_value = field.get("value")
    if not _is_number(measured_value):
        return _not_evaluated(
            constraint,
            "the measurement bound to this budget is {!r}, which is not a "
            "number and cannot be compared to a ceiling".format(measured_value),
            evidence, extra_codes=(C.CORE_CONSTRAINT_INVALID,))

    tol_value = tol_constraint.get("limit") if isinstance(tol_constraint, dict) \
        else None
    evaluation = _compare(COMPARE_BUDGET_LIMIT, limit, measured_value, tol_value)
    codes = [C.CORE_BUDGET_EXCEEDED] if evaluation == tri.VIOLATED else []
    comparison = _blank_comparison(
        COMPARE_BUDGET_LIMIT, constraint.get("subject"),
        "measured {} {} against ceiling {}{}".format(
            measured_value, constraint.get("unit") or "", limit,
            " with tolerance {}".format(tol_value)
            if tol_value is not None else ""),
        observed_paths=[source], desired_value=limit,
        observed_value=measured_value, tolerance=tol_value,
        tolerance_id=(tol_constraint or {}).get("constraint_id")
        if isinstance(tol_constraint, dict) else None,
        unit=constraint.get("unit"))
    return _finding(constraint, evaluation, comparison, evidence, codes,
                    comparison["detail"])


def _protected_paths(observed: Any, protected_id: Any) -> List[str]:
    """Every observed path stating whether ``protected_id`` was changed."""
    suffix = ".{}.{}.{}".format(OW.ENTITIES_KEY, protected_id,
                                PROTECTED_CHANGE_ATTR)
    return sorted(p for p in OW.field_map(observed) if p.endswith(suffix))


def _eval_protected(constraint: Dict[str, Any],
                    observed: Any) -> Dict[str, Any]:
    """PROTECTED_SEMANTICS: no named identity may be observed as changed.

    WF1213 raise site. The desired side is ``[]`` -- the empty set of changed
    identities -- which comes from the class definition, not from a default:
    protecting something means it must not change, and the record says so in a
    form the validator can re-derive by plain equality.

    An identity whose change-state was never observed is UNKNOWN for the WHOLE
    constraint. Reporting "the ones we looked at are fine" as SATISFIED would
    publish protection over content nobody checked.
    """
    protected = constraint.get("protected_ids")
    if not isinstance(protected, (list, tuple)) or not protected:
        return _finding(
            constraint, tri.UNKNOWN,
            _blank_comparison(COMPARE_NOT_EVALUATED, constraint.get("subject"),
                              "PROTECTED_SEMANTICS names protected_ids={!r}; an "
                              "empty protection set protects nothing while "
                              "still reading as protection".format(protected)),
            [], [C.CORE_CONSTRAINT_INVALID, C.CORE_CONSTRAINT_NOT_EVALUATED],
            "protection set is empty")

    fm = OW.field_map(observed)
    evidence: List[Dict[str, Any]] = []
    changed: List[Any] = []
    unobserved: List[Any] = []
    paths: List[str] = []
    unbacked_seen = False

    for pid in protected:
        found = _protected_paths(observed, pid)
        if not found:
            unobserved.append(pid)
            continue
        for path in found:
            paths.append(path)
            field = fm.get(path)
            backed = OW.is_backed(field)
            evidence.append(_evidence_record(path, field, backed))
            if not backed:
                unbacked_seen = True
                unobserved.append(pid)
                continue
            if field.get("value") is True:
                changed.append(pid)

    if unobserved:
        codes = [C.CORE_OBSERVED_WORLD_UNBACKED] if unbacked_seen else []
        return _not_evaluated(
            constraint,
            "protected identit(ies) {} have no backed observation of whether "
            "they changed; reporting the remainder as protected would publish "
            "protection over content nobody checked".format(sorted(
                map(str, set(unobserved)))),
            evidence, extra_codes=codes)

    changed = sorted(set(changed), key=str)
    evaluation = _compare(COMPARE_PROTECTED_UNCHANGED, [], changed, None)
    codes = [C.CORE_PROTECTED_CONTENT_TOUCHED] if changed else []
    comparison = _blank_comparison(
        COMPARE_PROTECTED_UNCHANGED, constraint.get("subject"),
        "protected identities {} observed; changed: {}".format(
            sorted(map(str, protected)), changed or "none"),
        observed_paths=paths, desired_value=[], observed_value=changed)
    return _finding(constraint, evaluation, comparison, evidence, codes,
                    comparison["detail"])


def _eval_tolerance(constraint: Dict[str, Any],
                    constraints: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """A TOLERANCE is never evaluated standalone. WF1205 when it targets nothing."""
    applies_to = constraint.get("applies_to")
    ids = {c.get("constraint_id") for c in constraints}
    resolves = bool(applies_to) and applies_to in ids
    codes = [] if resolves else [C.CORE_TOLERANCE_WITHOUT_TARGET]
    detail = ("parameterises {!r}; a tolerance has no truth value of its own and "
              "is never evaluated standalone".format(applies_to) if resolves
              else "applies_to={!r} names no constraint in this set, so this "
                   "tolerance widens no comparison at all".format(applies_to))
    return _finding(constraint, None,
                    _blank_comparison(COMPARE_NOT_A_PREDICATE,
                                      constraint.get("subject"), detail),
                    [], codes, detail)


def _eval_optimization(constraint: Dict[str, Any]) -> Dict[str, Any]:
    """An OPTIMIZATION_TARGET is a direction to rank along, with no pass/fail."""
    detail = ("direction {!r}; an optimisation target ranks candidates and has "
              "no pass/fail, so manufacturing a verdict for it would invent a "
              "gate the consumer never declared".format(
                  constraint.get("direction")))
    return _finding(constraint, None,
                    _blank_comparison(COMPARE_NOT_A_PREDICATE,
                                      constraint.get("subject"), detail),
                    [], [], detail)


def _eval_declared_unknown(constraint: Dict[str, Any]) -> Dict[str, Any]:
    """UNKNOWN by construction, via the constraints module's own authority."""
    evaluation = K.evaluate_declared_unknown(constraint)
    detail = ("declared undecided by the consumer; resolution is owned by {!r}, "
              "not by any measurement Core could take".format(
                  constraint.get("resolution_owner")))
    return _finding(constraint, evaluation,
                    _blank_comparison(COMPARE_DECLARED_UNKNOWN,
                                      constraint.get("subject"), detail),
                    [], [], detail)


def evaluate_constraint(constraint: Dict[str, Any], desired: Any, observed: Any,
                        constraints: Sequence[Dict[str, Any]],
                        bindings: Dict[Any, str],
                        measurements: Dict[Any, Any]) -> Dict[str, Any]:
    """Judge ONE constraint and return its finding. Never raises on bad input."""
    klass = constraint.get("constraint_class")
    cid = constraint.get("constraint_id")

    if klass not in K.CONSTRAINT_CLASSES:
        return _finding(
            constraint, tri.UNKNOWN,
            _blank_comparison(COMPARE_NOT_EVALUATED, constraint.get("subject"),
                              "constraint_class {!r} is not one of {}".format(
                                  klass, K.CONSTRAINT_CLASSES)),
            [], [C.CORE_CONSTRAINT_UNKNOWN_CLASS,
                 C.CORE_CONSTRAINT_NOT_EVALUATED],
            "unknown constraint class")

    if klass == K.TOLERANCE:
        return _eval_tolerance(constraint, constraints)
    if klass == K.OPTIMIZATION_TARGET:
        return _eval_optimization(constraint)
    if klass == K.DECLARED_UNKNOWN:
        return _eval_declared_unknown(constraint)

    tol_constraint = tolerance_for(constraints, cid)
    path = _resolve_path(constraint, observed, bindings)

    if klass == K.PROTECTED_SEMANTICS:
        return _eval_protected(constraint, observed)
    if klass == K.BUDGET:
        return _eval_budget(constraint, observed, path,
                            measurements.get(cid), tol_constraint)

    if path is None:
        return _not_evaluated(
            constraint,
            "no observed field is bound to this constraint: neither an explicit "
            "binding nor a subject naming a field of the observed model. "
            "Nothing measured it, so it has no verdict")

    desired_side = ("class", False) if klass == K.PROHIBITED_OUTCOME else None
    return _eval_path_constraint(constraint, desired, observed, path,
                                 tol_constraint, desired_side)


# --------------------------------------------------------------------------- #
# the reconciliation
# --------------------------------------------------------------------------- #
def _refusal(desired: Any, observed: Any, verdict: str,
             pair_checks: List[Check]) -> Dict[str, Any]:
    codes = sorted({code for (_n, ok, _d, code) in pair_checks
                    if not ok and code})
    reason = ("the desired and observed models describe DIFFERENT worlds; "
              "differencing them yields a plausible, entirely meaningless plan"
              if verdict == tri.VIOLATED else
              "the observed model carries no measured world identity, so "
              "nothing establishes that it is an observation of the world this "
              "request is about")
    return {
        "world_identity": DW.desired_identity(desired),
        "same_world": verdict,
        "reconciled": False,
        "refusal_reason": reason,
        "findings": [],
        "satisfied": [],
        "violated": [],
        "unknown": [],
        "not_a_predicate": [],
        # EXPLICIT. Folding zero findings returns SATISFIED by tri.conj's
        # identity, so a refusal would otherwise read as an acceptance.
        "acceptance_verdict": tri.UNKNOWN,
        "blockers": [],
        "failure_codes": codes,
        "created_by": "wfcore.analysis.reconcile",
        "schema_version": RT_CONSTRAINT_ANALYSIS,
        "report_type": RT_CONSTRAINT_ANALYSIS,
    }


def reconcile(desired: Any, observed: Any, request: Any,
              bindings: Optional[Dict[Any, str]] = None,
              measurements: Optional[Dict[Any, Any]] = None
              ) -> Dict[str, Any]:
    """Reconcile DESIRED against OBSERVED for one request. The entry point.

    ``bindings``     constraint_id -> observed field path, for constraints whose
                     ``subject`` is stated in the consumer's own words rather
                     than as a path into the observed model.
    ``measurements`` constraint_id -> observed FIELD record, for quantities that
                     are not world fields (a budget's measured cost). Subject to
                     the same backing rail as any measurement --
                     :func:`measurement_is_backed`.

    Refuses, before evaluating anything, when the two models do not describe the
    same world.
    """
    bindings = dict(bindings or {})
    measurements = dict(measurements or {})
    constraints = constraints_of(request)

    pair_checks = OW.validate_model_pair(desired, observed)
    verdict = OW.same_world(desired, observed)
    if not tri.accepts(verdict):
        return _refusal(desired, observed, verdict, pair_checks)

    findings = [evaluate_constraint(c, desired, observed, constraints,
                                    bindings, measurements)
                for c in constraints]

    # Only PREDICATE findings enter the fold. Both non-predicate classes are
    # absent from ACCEPTANCE_LOAD_BEARING, so this cannot move the verdict --
    # proved by test_non_predicate_classes_are_never_load_bearing rather than
    # assumed here.
    pairs: List[Tuple[Dict[str, Any], str]] = []
    by_value: Dict[str, List[Any]] = {tri.SATISFIED: [], tri.VIOLATED: [],
                                      tri.UNKNOWN: []}
    not_predicate: List[Any] = []
    for c, f in zip(constraints, findings):
        if f["evaluation"] is None:
            not_predicate.append(f["constraint_id"])
            continue
        pairs.append((c, f["evaluation"]))
        by_value[f["evaluation"]].append(f["constraint_id"])

    codes = sorted({code for f in findings for code in f["failure_codes"]})

    return {
        "world_identity": OW.observed_identity(observed),
        "same_world": verdict,
        "reconciled": True,
        "refusal_reason": None,
        "findings": findings,
        "satisfied": by_value[tri.SATISFIED],
        "violated": by_value[tri.VIOLATED],
        "unknown": by_value[tri.UNKNOWN],
        "not_a_predicate": not_predicate,
        "acceptance_verdict": K.fold_acceptance(pairs),
        "blockers": K.unresolved_blockers(pairs),
        "failure_codes": codes,
        "created_by": "wfcore.analysis.reconcile",
        "schema_version": RT_CONSTRAINT_ANALYSIS,
        "report_type": RT_CONSTRAINT_ANALYSIS,
    }


# --------------------------------------------------------------------------- #
# independent re-derivation -- see the module docstring
# --------------------------------------------------------------------------- #
def _recompute_from_record(finding: Any) -> Optional[str]:
    """Recompute a finding's verdict from what the finding WROTE DOWN.

    Reads only ``comparison`` and ``evidence``. Never touches the desired or
    observed model, and never calls the evaluation functions that produced the
    finding, so agreement is evidence that the recorded verdict is supported by
    the recorded comparison -- not evidence that one function is deterministic.
    """
    if not isinstance(finding, dict):
        return None
    comparison = finding.get("comparison")
    if not isinstance(comparison, dict):
        return None
    kind = comparison.get("comparison_kind")
    if kind == COMPARE_NOT_A_PREDICATE:
        return None
    if kind in (COMPARE_DECLARED_UNKNOWN, COMPARE_NOT_EVALUATED):
        return tri.UNKNOWN

    evidence = finding.get("evidence")
    rows = evidence if isinstance(evidence, list) else []
    # No cited evidence, or any cited row that was not backed: the comparison
    # rests on something unmeasured, whatever the producer concluded.
    if not rows or any(not (isinstance(r, dict) and r.get("backed") is True)
                       for r in rows):
        return tri.UNKNOWN
    if kind not in COMPARISON_KINDS:
        return tri.UNKNOWN
    return _compare(kind, comparison.get("desired_value"),
                    comparison.get("observed_value"),
                    comparison.get("tolerance"))


# --------------------------------------------------------------------------- #
# validators
# --------------------------------------------------------------------------- #
def validate_constraint_finding(finding: Any, strict: bool = False
                                ) -> List[Check]:
    """Rails that hold for ONE finding in isolation."""
    invalid = C.CORE_CONSTRAINT_INVALID
    p = "{}{}::".format(_FP, (finding or {}).get("constraint_id")
                        if isinstance(finding, dict) else "?")
    checks: List[Check] = []

    if not isinstance(finding, dict):
        return [(_FP + "is_object", False,
                 "finding must be an object, got {}".format(
                     type(finding).__name__), invalid)]

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
    checks.append((p + "schema_version", sv == RT_CONSTRAINT_FINDING,
                   "schema_version must be {!r} (got {!r})".format(
                       RT_CONSTRAINT_FINDING, sv),
                   None if sv == RT_CONSTRAINT_FINDING else invalid))

    klass = finding.get("constraint_class")
    known = klass in K.CONSTRAINT_CLASSES
    checks.append((p + "class_known", known,
                   "constraint_class {!r} is not one of {}".format(
                       klass, K.CONSTRAINT_CLASSES),
                   None if known else C.CORE_CONSTRAINT_UNKNOWN_CLASS))

    evaluation = finding.get("evaluation")
    non_predicate = klass in NON_PREDICATE_CLASSES
    if non_predicate:
        ok = evaluation is None
        checks.append((
            p + "non_predicate_has_no_verdict", ok,
            "class {} carries evaluation={!r}; a tolerance parameterises another "
            "constraint's comparison and an optimisation target ranks "
            "candidates -- neither has a truth value, and manufacturing one "
            "gives it authority the taxonomy denies it".format(klass, evaluation),
            None if ok else C.CORE_CONSTRAINT_CLASS_AUTHORITY_VIOLATION))
    else:
        ok = evaluation in tri.TRI_VALUES
        checks.append((p + "evaluation_is_tri", ok,
                       "evaluation {!r} is not one of {}".format(
                           evaluation, tri.TRI_VALUES),
                       None if ok else invalid))

    remedy = finding.get("remedy")
    ok = remedy in REMEDIES
    checks.append((p + "remedy_known", ok,
                   "remedy {!r} is not one of {}".format(remedy, REMEDIES),
                   None if ok else invalid))

    if evaluation in tri.TRI_VALUES and remedy in REMEDIES:
        if klass == K.DECLARED_UNKNOWN and evaluation == tri.UNKNOWN:
            want = REMEDY_DECIDE
        else:
            want = REMEDY_FOR_EVALUATION[evaluation]
        ok = remedy == want
        checks.append((
            p + "remedy_matches_evaluation", ok,
            "evaluation {} demands remedy {} but the finding says {}; a "
            "violation routed to MEASURE stalls a repair that is due, and an "
            "unknown routed to CHANGE_THE_WORLD authors a change nobody "
            "established was needed".format(evaluation, want, remedy),
            None if ok else invalid))

    lb = finding.get("acceptance_load_bearing")
    expected_lb = klass in K.ACCEPTANCE_LOAD_BEARING
    ok = lb is expected_lb
    checks.append((
        p + "load_bearing_matches_class", ok,
        "finding says acceptance_load_bearing={!r} for class {!r}, but "
        "ACCEPTANCE_LOAD_BEARING is {}; whether a constraint MAY block is a "
        "property of its class, never of this record".format(
            lb, klass, K.ACCEPTANCE_LOAD_BEARING),
        None if ok else C.CORE_CONSTRAINT_CLASS_AUTHORITY_VIOLATION))

    comparison = finding.get("comparison")
    comp_ok = isinstance(comparison, dict)
    checks.append((p + "comparison_is_object", comp_ok,
                   "comparison must be an object stating what was compared",
                   None if comp_ok else invalid))
    if comp_ok:
        missing = [k for k in COMPARISON_REQUIRED if k not in comparison]
        checks.append((p + "comparison_required", not missing,
                       "comparison missing key(s) {}".format(missing) if missing
                       else "comparison states every required key",
                       None if not missing else invalid))
        kind = comparison.get("comparison_kind")
        ok = kind in COMPARISON_KINDS
        checks.append((p + "comparison_kind_known", ok,
                       "comparison_kind {!r} is not one of {}".format(
                           kind, COMPARISON_KINDS),
                       None if ok else invalid))

    evidence = finding.get("evidence")
    ev_ok = isinstance(evidence, list) and all(isinstance(e, dict)
                                               for e in evidence)
    checks.append((p + "evidence_is_list", ev_ok,
                   "evidence must be a list of records naming each observed "
                   "field consulted", None if ev_ok else invalid))
    if ev_ok:
        for i, row in enumerate(evidence):
            missing = [k for k in EVIDENCE_RECORD_REQUIRED if k not in row]
            checks.append((
                "{}evidence[{}].required".format(p, i), not missing,
                "evidence row missing key(s) {}".format(missing) if missing
                else "evidence row states every required key",
                None if not missing else invalid))
            backed = row.get("backed")
            prov = row.get("provenance")
            consistent = backed is not True or prov in OW.BACKED_PROVENANCE
            checks.append((
                "{}evidence[{}].backed_matches_provenance".format(p, i),
                consistent,
                "evidence row claims backed=True with provenance {!r}, which is "
                "not one of {}; a row that calls itself backed while naming an "
                "unbacked provenance is the fabrication the observed model "
                "exists to prevent".format(prov, OW.BACKED_PROVENANCE),
                None if consistent else C.CORE_OBSERVED_WORLD_UNBACKED))

    # --- THE rail: a verdict may not outrun its evidence --------------------- #
    if evaluation == tri.SATISFIED:
        rows = evidence if ev_ok else []
        ok = bool(rows) and all(r.get("backed") is True for r in rows)
        checks.append((
            p + "satisfied_rests_on_backed_evidence", ok,
            "evaluation is SATISFIED but the finding cites {} evidence row(s), "
            "of which {} are backed; a constraint compared against an unbacked "
            "observed field is UNKNOWN, and calling it satisfied fabricates the "
            "measurement the verdict rests on".format(
                len(rows), sum(1 for r in rows if r.get("backed") is True)),
            None if ok else C.CORE_OBSERVED_WORLD_UNBACKED))

    # --- an unmeasured load-bearing constraint must say so ------------------- #
    codes = finding.get("failure_codes")
    codes = codes if isinstance(codes, list) else []
    if (evaluation == tri.UNKNOWN and expected_lb
            and klass != K.DECLARED_UNKNOWN):
        ok = C.CORE_CONSTRAINT_NOT_EVALUATED in codes
        checks.append((
            p + "unevaluated_load_bearing_raises_wf1202", ok,
            "an acceptance-load-bearing constraint evaluated UNKNOWN must raise "
            "{}; without it the pipeline folds UNKNOWN forever and nothing names "
            "the constraint that will never resolve (codes: {})".format(
                C.CORE_CONSTRAINT_NOT_EVALUATED, codes),
            None if ok else C.CORE_CONSTRAINT_NOT_EVALUATED))
    if klass == K.DECLARED_UNKNOWN:
        ok = C.CORE_CONSTRAINT_NOT_EVALUATED not in codes
        checks.append((
            p + "declared_unknown_is_not_wf1202", ok,
            "a DECLARED_UNKNOWN raised {}; it was evaluated -- to UNKNOWN, by "
            "construction -- and reporting it as never-evaluated sends Core to "
            "measure the consumer's own undecided intent".format(
                C.CORE_CONSTRAINT_NOT_EVALUATED),
            None if ok else C.CORE_CONSTRAINT_CLASS_AUTHORITY_VIOLATION))

    # --- the verdict must follow from the record ----------------------------- #
    recomputed = _recompute_from_record(finding)
    ok = recomputed == evaluation
    checks.append((
        p + "verdict_follows_from_record", ok,
        "recorded evaluation {!r} but the comparison and evidence written into "
        "this finding support {!r}; a verdict its own record does not support "
        "cannot be audited by anyone who was not present when it was "
        "produced".format(evaluation, recomputed),
        None if ok else invalid))

    return checks


def validate_constraint_analysis(obj: Any, strict: bool = False) -> List[Check]:
    """Validate ONE constraint analysis, findings included.

    The acceptance verdict is re-derived from the per-finding records (see
    ``_recompute_from_record``) and from this module's own reading of
    ``constraints.ACCEPTANCE_LOAD_BEARING`` -- never by calling
    ``fold_acceptance`` on the producer's own evaluations, which would agree by
    construction and check nothing.
    """
    invalid = C.CORE_CONSTRAINT_INVALID
    checks: List[Check] = []

    if not isinstance(obj, dict):
        return [(_P + "is_object", False,
                 "constraint analysis must be an object, got {}".format(
                     type(obj).__name__), invalid)]

    for fld in ANALYSIS_REQUIRED:
        present = fld in obj
        checks.append((_P + "has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else invalid))

    if strict:
        unknown = sorted(set(obj) - set(ANALYSIS_ALLOWED))
        checks.append((_P + "no_unknown_fields", not unknown,
                       "unexpected field(s) {}".format(unknown) if unknown
                       else "no unexpected fields",
                       None if not unknown else invalid))

    sv = obj.get("schema_version")
    checks.append((_P + "schema_version", sv == RT_CONSTRAINT_ANALYSIS,
                   "schema_version must be {!r} (got {!r})".format(
                       RT_CONSTRAINT_ANALYSIS, sv),
                   None if sv == RT_CONSTRAINT_ANALYSIS else invalid))

    same = obj.get("same_world")
    ok = same in tri.TRI_VALUES
    checks.append((_P + "same_world_is_tri", ok,
                   "same_world {!r} is not one of {}".format(same,
                                                             tri.TRI_VALUES),
                   None if ok else invalid))

    verdict = obj.get("acceptance_verdict")
    ok = verdict in tri.TRI_VALUES
    checks.append((_P + "acceptance_verdict_is_tri", ok,
                   "acceptance_verdict {!r} is not one of {}".format(
                       verdict, tri.TRI_VALUES),
                   None if ok else invalid))

    reconciled = obj.get("reconciled")
    ok = isinstance(reconciled, bool)
    checks.append((_P + "reconciled_is_bool", ok,
                   "reconciled must be an explicit boolean (got {!r})".format(
                       reconciled), None if ok else invalid))

    findings = obj.get("findings")
    f_ok = isinstance(findings, list)
    checks.append((_P + "findings_is_list", f_ok,
                   "findings must be a list", None if f_ok else invalid))
    findings = findings if f_ok else []

    # --- refusal coherence --------------------------------------------------- #
    if reconciled is False:
        ok = verdict == tri.UNKNOWN
        checks.append((
            _P + "refusal_verdict_is_unknown", ok,
            "the analysis refused to reconcile but records acceptance_verdict "
            "{!r}; folding zero findings returns SATISFIED by tri.conj's "
            "identity, so a refusal that is not written out as UNKNOWN reads, "
            "downstream, as an acceptance nobody computed".format(verdict),
            None if ok else invalid))
        ok = not findings
        checks.append((
            _P + "refusal_emits_no_findings", ok,
            "the analysis refused to reconcile but carries {} finding(s); a "
            "verdict produced against a world that was never established is a "
            "confident statement about an unknown subject".format(len(findings)),
            None if ok else invalid))
        ok = bool(obj.get("refusal_reason"))
        checks.append((_P + "refusal_states_a_reason", ok,
                       "a refusal must say why; an unexplained refusal is "
                       "indistinguishable from a crash",
                       None if ok else invalid))
        ok = tri.accepts(same) is False
        checks.append((
            _P + "refusal_matches_same_world", ok,
            "the analysis refused while same_world is {!r}; refusing a pair "
            "whose identities agree hides a real reconciliation".format(same),
            None if ok else C.CORE_MODEL_IDENTITY_MISMATCH))
    elif reconciled is True:
        ok = tri.accepts(same)
        checks.append((
            _P + "reconciled_only_on_same_world", ok,
            "the analysis reconciled with same_world={!r}; differencing models "
            "that do not describe the same world yields a plausible, entirely "
            "meaningless plan".format(same),
            None if ok else (C.CORE_MODEL_IDENTITY_MISMATCH
                             if same == tri.VIOLATED
                             else C.CORE_OBSERVED_WORLD_UNBACKED)))

    # --- every finding ------------------------------------------------------- #
    for f in findings:
        checks.extend(validate_constraint_finding(f, strict=strict))

    # --- the sets must partition the findings -------------------------------- #
    by_value: Dict[str, List[Any]] = {tri.SATISFIED: [], tri.VIOLATED: [],
                                      tri.UNKNOWN: []}
    non_predicate: List[Any] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        ev = f.get("evaluation")
        if ev in by_value:
            by_value[ev].append(f.get("constraint_id"))
        else:
            non_predicate.append(f.get("constraint_id"))

    for key, want in (("satisfied", by_value[tri.SATISFIED]),
                      ("violated", by_value[tri.VIOLATED]),
                      ("unknown", by_value[tri.UNKNOWN]),
                      ("not_a_predicate", non_predicate)):
        got = obj.get(key)
        got = got if isinstance(got, list) else None
        ok = got is not None and sorted(map(str, got)) == sorted(map(str, want))
        checks.append((
            "{}{}_set_matches_findings".format(_P, key), ok,
            "the {!r} set is {!r} but the findings group as {!r}; a summary that "
            "disagrees with the findings is the half every downstream reader "
            "actually reads".format(key, got, want),
            None if ok else invalid))

    # --- the verdict, re-derived from the records ---------------------------- #
    if reconciled is True:
        recomputed: List[str] = []
        for f in findings:
            if not isinstance(f, dict):
                continue
            if f.get("constraint_class") not in K.ACCEPTANCE_LOAD_BEARING:
                continue
            value = _recompute_from_record(f)
            if value in tri.TRI_VALUES:
                recomputed.append(value)
        want = tri.conj(recomputed)
        ok = verdict == want
        checks.append((
            _P + "verdict_follows_from_findings", ok,
            "recorded acceptance_verdict {!r}, but folding the load-bearing "
            "findings re-derived from their own comparison and evidence records "
            "gives {!r}. Re-derived here rather than by re-running the producer, "
            "which would agree by construction".format(verdict, want),
            None if ok else invalid))

        blocking = [f.get("constraint_id") for f in findings
                    if isinstance(f, dict)
                    and f.get("constraint_class") in K.ACCEPTANCE_LOAD_BEARING
                    and _recompute_from_record(f) in (tri.VIOLATED, tri.UNKNOWN)]
        blockers = obj.get("blockers")
        listed = sorted(str(b.get("constraint_id")) for b in blockers
                        if isinstance(b, dict)) if isinstance(blockers, list) \
            else None
        ok = listed is not None and listed == sorted(map(str, blocking))
        checks.append((
            _P + "blockers_match_blocking_findings", ok,
            "blockers list {!r} but the load-bearing findings that block are "
            "{!r}; an unlisted blocker is a constraint nothing will ever go "
            "resolve".format(listed, sorted(map(str, blocking))),
            None if ok else invalid))

    return checks


# --------------------------------------------------------------------------- #
# canonical examples
# --------------------------------------------------------------------------- #
def _example_observed_world(**over: Any) -> Dict[str, Any]:
    """The models' canonical observation, plus a stated change-observation.

    ``semantic_landmarks.entities.landmark_a.changed`` is added because
    PROTECTED_SEMANTICS is judged against exactly that attribute, and an example
    in which no protected identity was ever observed would only ever demonstrate
    the UNKNOWN path.
    """
    import copy
    d = copy.deepcopy(OW._example_observed_world())
    d["semantic_landmarks"][OW.ENTITIES_KEY]["landmark_a"][
        PROTECTED_CHANGE_ATTR] = OW.measured(
            False, "operation_enumerate", "entity_enumerator",
            ("record#enumeration",),
            detail="the identity was compared against its prior state and was "
                   "not altered by this pass")
    d.update(over)
    return d


def _example_constraint_set(**_over: Any) -> List[Dict[str, Any]]:
    """A constraint set exercising every branch the analyser has.

    Domain-neutral throughout: the ids name generic measurables, never any
    caller's content.
    """
    return [
        {"constraint_id": "c_relation_1_holds",
         "constraint_class": K.HARD_INVARIANT,
         "subject": "spatial_relations.relation_1",
         "detail": "the first declared spatial relation must hold"},
        {"constraint_id": "c_relation_2_holds",
         "constraint_class": K.HARD_INVARIANT,
         "subject": "spatial_relations.relation_2",
         "detail": "the second declared spatial relation must hold"},
        {"constraint_id": "c_population_count",
         "constraint_class": K.HARD_INVARIANT,
         "subject": "population.population_group_a.count",
         "detail": "the declared group must reach its target count"},
        {"constraint_id": "c_population_slack",
         "constraint_class": K.TOLERANCE,
         "subject": "population.population_group_a.count",
         "detail": "the count may fall short by one",
         "applies_to": "c_population_count",
         "limit": 1,
         "unit": "members"},
        {"constraint_id": "c_generation_budget",
         "constraint_class": K.BUDGET,
         "subject": "generation.elapsed",
         "detail": "generation must complete within the stated ceiling",
         "limit": 900,
         "unit": "seconds"},
        {"constraint_id": "c_protect_landmark",
         "constraint_class": K.PROTECTED_SEMANTICS,
         "subject": "semantic_landmarks.landmark_a",
         "detail": "the declared landmark identity must not be altered",
         "protected_ids": ["landmark_a"]},
        {"constraint_id": "c_no_second_relation",
         "constraint_class": K.PROHIBITED_OUTCOME,
         "subject": "spatial_relations.relation_2",
         "detail": "the second relation must not hold"},
        {"constraint_id": "c_visibility_preference",
         "constraint_class": K.SOFT_PREFERENCE,
         "subject": "environmental_state.state_visibility",
         "detail": "prefer the declared visibility state",
         "weight": 0.4},
        {"constraint_id": "c_minimize_elapsed",
         "constraint_class": K.OPTIMIZATION_TARGET,
         "subject": "generation.elapsed",
         "detail": "shorter generation is better",
         "direction": K.MINIMIZE,
         "weight": 0.2},
        {"constraint_id": "c_undecided_density",
         "constraint_class": K.DECLARED_UNKNOWN,
         "subject": "population.density",
         "detail": "the consumer has not decided the density it wants",
         "resolution_owner": "consumer_design_owner"},
    ]


def _example_bindings() -> Dict[str, str]:
    """Constraint id -> observed field path.

    Explicit rather than inferred: a consumer states its subject in its own
    words, and the integrator says which measurement answers it. Guessing that
    correspondence would judge a constraint against a field nobody named.
    """
    return {
        "c_relation_1_holds": "spatial_relations.entities.relation_1.holds",
        "c_relation_2_holds": "spatial_relations.entities.relation_2.holds",
        "c_population_count": "population.entities.population_group_a.count",
        "c_no_second_relation": "spatial_relations.entities.relation_2.holds",
        "c_visibility_preference":
            "environmental_state.entities.state_visibility.state_value",
    }


def _example_measurements() -> Dict[str, Dict[str, Any]]:
    """A budget's measured cost -- a measurement that is not a world field.

    It cites an operation the observed model declares and an evidence entry that
    model's index resolves, because ``measurement_is_backed`` requires both. A
    measurement exempt from that rail would be a plain number wearing a
    measurement's record shape.
    """
    return {
        "c_generation_budget": OW.measured(
            720, "operation_state_read", "state_reader", ("record#state",),
            detail="elapsed cost of the generation pass"),
    }


def _example_constraint_analysis(**over: Any) -> Dict[str, Any]:
    """Canonical-valid analysis, produced by running the real reconciler.

    Built rather than written: a hand-authored example proves the shape somebody
    typed, not the shape the analyser emits, and the two drift on the first edit.
    """
    # ``pop`` with a default sentinel, never ``or``: an override of ``{}`` or
    # ``[]`` is a DELIBERATE empty input -- "no bindings at all" is one of the
    # known-bads this factory exists to spawn -- and ``or`` would silently
    # substitute the canonical value for it.
    desired = over.pop("desired", None)
    observed = over.pop("observed", None)
    constraints = over.pop("constraints", None)
    bindings = over.pop("bindings", None)
    measurements = over.pop("measurements", None)
    desired = DW._example_desired_world() if desired is None else desired
    observed = _example_observed_world() if observed is None else observed
    constraints = _example_constraint_set() if constraints is None else constraints
    bindings = _example_bindings() if bindings is None else bindings
    measurements = _example_measurements() if measurements is None \
        else measurements
    d = reconcile(desired, observed, constraints, bindings=bindings,
                  measurements=measurements)
    d.update(over)
    return d
