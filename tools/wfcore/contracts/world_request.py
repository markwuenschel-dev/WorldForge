#!/usr/bin/env python3
"""wfcore.contracts.world_request -- ONE concrete ask, stated so it can be judged.

A request is the only contract that names a specific thing to make. It carries
four kinds of content, and the split is what makes the ask machine-actionable:

    constraints           what must / must not / should hold -- the constraint
                          taxonomy, never a flat "requirements" list
    semantic_landmarks    the places that MEAN something to the consumer's game
    gameplay_affordances  what the space must let a player DO
    population +          how densely it is inhabited, and what kind of space it
    environment           physically is

WHY THE CONSTRAINT SET IS NOT RE-VALIDATED HERE
-----------------------------------------------
``constraints.validate_constraint_set`` is the one authority on constraint shape,
including the rail that a set with no acceptance-load-bearing member folds to
vacuous SATISFIED and would accept any world at all. This module folds those
checks in under a prefix (``wr::constraints.``) rather than re-deriving them. A
second implementation would drift the first time the taxonomy grows a class, and
it would drift silently -- both validators would still return checks, and the
weaker one would be the one that ran.

THE RAIL WORTH READING TWICE
----------------------------
``required_affordance_is_load_bearing``: an affordance flagged ``required`` that
no acceptance-load-bearing constraint mentions is decoration. Nothing can fail
because of it; the world can ship entirely without it; and the request will still
read, to a human, as though the affordance were guaranteed. That gap between what
a request LOOKS like it demands and what it can actually reject is the specific
way consumer contracts turn into wishlists, so it is a check and not a note.
"""

from typing import Any, Dict, List

from .. import constraints as K
from ..failure import FailureCode as C
from . import (Check, UNKNOWN, check_bool, check_enum, check_is_object,
               check_measure, check_no_unknown, check_required,
               check_schema_version, check_str, check_str_list, prefixed,
               require_caller_owned)

RT_WORLD_REQUEST = "wf.core.world_request.v1"

NEW_WORLD = "new_world"
REVISION = "revision"
REQUEST_KINDS = (NEW_WORLD, REVISION)

# What a place MEANS to the consumer's game, structurally. Never what it depicts.
LANDMARK_ROLES = (
    "entry",
    "objective",
    "vista",
    "shelter",
    "hazard",
    "junction",
    "boundary",
    "resource_point",
    "transition",
)

# What the space must let a player DO. Same discipline: verbs, not nouns.
AFFORDANCE_KINDS = (
    "traversal",
    "cover",
    "concealment",
    "vantage",
    "flanking_route",
    "chokepoint",
    "navigation_anchor",
    "interaction_surface",
    "spawn_area",
    "patrol_route",
)

# Population and environment vocabularies each carry ``unknown`` as a first-class
# member: a consumer that has not decided must be able to SAY so, because the
# alternative -- omitting the field -- is indistinguishable from "this does not
# matter to me", and those two have opposite correct behaviours.
DENSITY_CLASSES = ("none", "sparse", "moderate", "dense", UNKNOWN)
RELIEF_CLASSES = ("flat", "rolling", "broken", "vertical", UNKNOWN)
LIGHTING_CONDITIONS = ("bright", "overcast", "dim", "dark", UNKNOWN)

LANDMARK_REQUIRED = ("landmark_id", "role", "must_be_reachable")
LANDMARK_ALLOWED = LANDMARK_REQUIRED + ("significance", "anchor_hint", "notes")

AFFORDANCE_REQUIRED = ("affordance_id", "affordance_kind", "required")
AFFORDANCE_ALLOWED = AFFORDANCE_REQUIRED + ("detail", "notes")

POPULATION_REQUIRED = ("density_class", "population_roles")
ENVIRONMENT_REQUIRED = ("extent_m2", "relief_class", "lighting_condition")

WORLD_REQUEST_REQUIRED = (
    "request_id",
    "consumer_id",
    "catalog_id",
    "request_kind",
    "subject",
    "constraints",
    "semantic_landmarks",
    "gameplay_affordances",
    "population",
    "environment",
    "schema_version",
)
WORLD_REQUEST_ALLOWED = WORLD_REQUEST_REQUIRED + (
    "revision_target",
    "revision_policy_id",
    "seed",
    "created_by",
    "created_at",
    "report_type",
    "meta",
    "notes",
)

# ``subject`` is this contract's ``target_map``: it names the thing in the
# consumer's project that is about to be created or changed. There is no default,
# for the same reason ``bridge.schema.build_request`` has none -- a Core-chosen
# subject means Core did work on something nobody asked about, and the work looks
# exactly as successful as real work.
CALLER_OWNED_FIELDS = ("request_id", "consumer_id", "catalog_id", "subject",
                       "constraints")

_P = "wr::"


def validate_world_request(obj: Any, strict: bool = False) -> List[Check]:
    code = C.CORE_WORLD_REQUEST_INVALID
    ch = check_is_object(obj, code, _P, "world_request")
    if ch:
        return ch

    ch += check_required(obj, WORLD_REQUEST_REQUIRED, code, _P)
    ch += check_no_unknown(obj, WORLD_REQUEST_ALLOWED, code, _P, strict)
    for fld in ("request_id", "consumer_id", "catalog_id", "subject"):
        ch += check_str(obj, fld, code, _P)
    ch += check_enum(obj, "request_kind", REQUEST_KINDS, code, _P)
    ch += check_schema_version(obj, RT_WORLD_REQUEST, code, _P)

    # The constraint set goes through its own authority, prefixed so a reader can
    # see which validator produced which check.
    ch += prefixed(K.validate_constraint_set(obj.get("constraints"), strict=strict),
                   _P + "constraints.")

    ch += _rail_revision_shape(obj, code)
    ch += _rail_landmarks(obj, code)
    ch += _rail_affordances(obj, code)
    ch += _rail_population(obj, code)
    ch += _rail_environment(obj, code)
    return ch


def _rail_revision_shape(obj: Dict[str, Any], code: str) -> List[Check]:
    """A revision must name what it revises; a new world must NOT.

    Both directions are real failures. A revision with no ``revision_target`` has
    Core choosing which existing content to modify -- the authority inversion in
    its most destructive form, because the modification is applied to somebody's
    finished work. A ``new_world`` carrying a ``revision_target`` is a request
    whose two halves disagree, and every downstream reader picks a different half.
    """
    out: List[Check] = []
    kind = obj.get("request_kind")
    target = obj.get("revision_target")
    policy = obj.get("revision_policy_id")

    if kind == REVISION:
        ok = isinstance(target, str) and bool(target.strip())
        out.append((_P + "revision_names_target", ok,
                    "request_kind={!r} with revision_target={!r}; a revision that "
                    "does not name what it revises leaves Core to choose which of "
                    "the consumer's finished content to modify".format(kind, target),
                    None if ok else code))
        ok = isinstance(policy, str) and bool(policy.strip())
        out.append((_P + "revision_names_policy", ok,
                    "request_kind={!r} with revision_policy_id={!r}; a revision "
                    "without a policy has no statement of what may change, so "
                    "every mutation is unbounded".format(kind, policy),
                    None if ok else code))
    elif kind == NEW_WORLD:
        ok = target is None
        out.append((_P + "new_world_carries_no_revision_target", ok,
                    "request_kind={!r} but revision_target={!r}; the two halves "
                    "of this request disagree and each downstream reader will "
                    "believe a different one".format(kind, target),
                    None if ok else code))
    return out


def _rail_landmarks(obj: Dict[str, Any], code: str) -> List[Check]:
    """Landmarks are well-formed, uniquely identified, and include an entry.

    The entry rail: reachability is the single most common hard invariant a
    consumer declares, and reachability is measured FROM somewhere. A request with
    no landmark in the ``entry`` role makes every reachability constraint in the
    set permanently unevaluable -- it would fold to UNKNOWN forever, and the
    request would look complete right up until acceptance never came.
    """
    out: List[Check] = []
    landmarks = obj.get("semantic_landmarks")
    if not isinstance(landmarks, (list, tuple)):
        return [(_P + "semantic_landmarks_is_list", False,
                 "semantic_landmarks must be a list, got {}".format(
                     type(landmarks).__name__), code)]

    for idx, lm in enumerate(landmarks):
        p = "{}landmark[{}].".format(_P, idx)
        if not isinstance(lm, dict):
            out.append((p + "is_object", False,
                        "landmark must be an object, got {}".format(
                            type(lm).__name__), code))
            continue
        out += check_required(lm, LANDMARK_REQUIRED, code, p)
        out += check_str(lm, "landmark_id", code, p)
        out += check_enum(lm, "role", LANDMARK_ROLES, code, p)
        out += check_bool(lm, "must_be_reachable", code, p)

    ids = [lm.get("landmark_id") for lm in landmarks if isinstance(lm, dict)]
    dupes = sorted({i for i in ids if i is not None and ids.count(i) > 1})
    ok = not dupes
    out.append((_P + "landmark_ids_unique", ok,
                "duplicate landmark_id(s) {}".format(dupes) if dupes
                else "all landmark_ids unique", None if ok else code))

    entries = [lm for lm in landmarks
               if isinstance(lm, dict) and lm.get("role") == "entry"]
    ok = len(entries) > 0
    out.append((_P + "request_declares_an_entry_landmark", ok,
                "{} landmark(s) with role 'entry'; reachability is measured FROM "
                "somewhere, so a request with no entry makes every reachability "
                "constraint permanently unevaluable -- it folds to UNKNOWN "
                "forever and acceptance simply never arrives".format(len(entries)),
                None if ok else code))
    return out


def _rail_affordances(obj: Dict[str, Any], code: str) -> List[Check]:
    """Affordances are well-formed, and every REQUIRED one can actually fail."""
    out: List[Check] = []
    affordances = obj.get("gameplay_affordances")
    if not isinstance(affordances, (list, tuple)):
        return [(_P + "gameplay_affordances_is_list", False,
                 "gameplay_affordances must be a list, got {}".format(
                     type(affordances).__name__), code)]

    for idx, af in enumerate(affordances):
        p = "{}affordance[{}].".format(_P, idx)
        if not isinstance(af, dict):
            out.append((p + "is_object", False,
                        "affordance must be an object, got {}".format(
                            type(af).__name__), code))
            continue
        out += check_required(af, AFFORDANCE_REQUIRED, code, p)
        out += check_str(af, "affordance_id", code, p)
        out += check_enum(af, "affordance_kind", AFFORDANCE_KINDS, code, p)
        out += check_bool(af, "required", code, p)

    ids = [af.get("affordance_id") for af in affordances if isinstance(af, dict)]
    dupes = sorted({i for i in ids if i is not None and ids.count(i) > 1})
    ok = not dupes
    out.append((_P + "affordance_ids_unique", ok,
                "duplicate affordance_id(s) {}".format(dupes) if dupes
                else "all affordance_ids unique", None if ok else code))

    # --- the decoration rail --------------------------------------------------
    load_bearing_subjects = [
        str(c.get("subject", "")) for c in (obj.get("constraints") or [])
        if isinstance(c, dict) and K.is_acceptance_load_bearing(c)]
    unbacked = []
    for af in affordances:
        if not isinstance(af, dict) or af.get("required") is not True:
            continue
        aid = af.get("affordance_id")
        if not isinstance(aid, str) or not aid:
            continue
        if not any(aid == s or aid in s for s in load_bearing_subjects):
            unbacked.append(aid)

    ok = not unbacked
    out.append((_P + "required_affordance_is_load_bearing", ok,
                "affordance(s) {} are flagged required but no acceptance-load-"
                "bearing constraint names them as its subject; nothing can fail "
                "because they are absent, so 'required' is decoration and the "
                "world may ship entirely without them".format(unbacked)
                if unbacked
                else "every required affordance is named by a load-bearing "
                     "constraint", None if ok else code))
    return out


def _rail_population(obj: Dict[str, Any], code: str) -> List[Check]:
    """Population is stated, and an unknown density names who resolves it."""
    out: List[Check] = []
    pop = obj.get("population")
    if not isinstance(pop, dict):
        return [(_P + "population_is_object", False,
                 "population must be an object, got {}".format(type(pop).__name__),
                 code)]

    out += check_required(pop, POPULATION_REQUIRED, code, _P + "population.")
    out += check_enum(pop, "density_class", DENSITY_CLASSES, code,
                      _P + "population.")
    out += check_str_list(pop, "population_roles", code, _P + "population.",
                          min_len=0)

    density = pop.get("density_class")
    roles = pop.get("population_roles")

    if density == UNKNOWN:
        owner = pop.get("resolution_owner")
        ok = isinstance(owner, str) and bool(owner.strip())
        out.append((_P + "population.unknown_names_resolution_owner", ok,
                    "density_class is {!r} but resolution_owner={!r}; an unknown "
                    "blocks acceptance until decided, and an ownerless permanent "
                    "blocker is indistinguishable from a defect in Core".format(
                        UNKNOWN, owner), None if ok else code))

    if density == "none" and isinstance(roles, (list, tuple)) and roles:
        out.append((_P + "population.density_matches_roles", False,
                    "density_class='none' while population_roles={} names {} "
                    "role(s); the two halves contradict, and Core would either "
                    "populate a world declared empty or drop roles the consumer "
                    "asked for".format(list(roles), len(roles)), code))
    else:
        out.append((_P + "population.density_matches_roles", True,
                    "density_class and population_roles agree", None))
    return out


def _rail_environment(obj: Dict[str, Any], code: str) -> List[Check]:
    """Environment is stated in measures, and unknowns name their owner."""
    out: List[Check] = []
    env = obj.get("environment")
    if not isinstance(env, dict):
        return [(_P + "environment_is_object", False,
                 "environment must be an object, got {}".format(type(env).__name__),
                 code)]

    out += check_required(env, ENVIRONMENT_REQUIRED, code, _P + "environment.")
    out += check_measure(env, "extent_m2", code, _P + "environment.")
    out += check_enum(env, "relief_class", RELIEF_CLASSES, code,
                      _P + "environment.")
    out += check_enum(env, "lighting_condition", LIGHTING_CONDITIONS, code,
                      _P + "environment.")

    unknown_fields = sorted(f for f in ENVIRONMENT_REQUIRED
                            if env.get(f) == UNKNOWN)
    if unknown_fields:
        owner = env.get("resolution_owner")
        ok = isinstance(owner, str) and bool(owner.strip())
        out.append((_P + "environment.unknown_names_resolution_owner", ok,
                    "environment field(s) {} are {!r} but resolution_owner={!r}; "
                    "the unknown is honest and welcome, the missing owner is "
                    "not".format(unknown_fields, UNKNOWN, owner),
                    None if ok else code))
    else:
        out.append((_P + "environment.unknown_names_resolution_owner", True,
                    "no environment field is declared unknown", None))
    return out


def build_world_request(**over: Any) -> Dict[str, Any]:
    """Build a request. ``CALLER_OWNED_FIELDS`` are REQUIRED -- no defaults.

    Core defaults only its own schema identity and the empty-but-stated shape of
    the semantic sections. It never defaults ``subject``, ``constraints``, or the
    consumer/catalog binding: those ARE the ask, and a Core-supplied ask produces
    work that is indistinguishable from real work right up to the point somebody
    asks who wanted it.
    """
    require_caller_owned(over, CALLER_OWNED_FIELDS, "world_request")
    d: Dict[str, Any] = dict(
        request_kind=NEW_WORLD,
        semantic_landmarks=[],
        gameplay_affordances=[],
        schema_version=RT_WORLD_REQUEST,
        report_type=RT_WORLD_REQUEST,
    )
    d.update(over)
    return d


def _example_world_request(**over: Any) -> Dict[str, Any]:
    """Canonical-valid request. ``**over`` spawns the known-bads.

    The constraint set carries a HARD_INVARIANT whose subject is the required
    affordance's id -- that is what makes the affordance able to fail, and it is
    the shape a real consumer must copy.
    """
    d: Dict[str, Any] = dict(
        request_id="request_placeholder_0001",
        consumer_id="consumer_placeholder",
        catalog_id="catalog_placeholder",
        subject="subject_placeholder",
        request_kind=NEW_WORLD,
        constraints=[
            {
                "constraint_id": "afford_traversal_spine",
                "constraint_class": K.HARD_INVARIANT,
                "subject": "afford_traversal_spine",
                "detail": ("a continuous traversable route must connect the entry "
                           "landmark to every landmark in the objective role"),
            },
            {
                "constraint_id": "c_generation_budget",
                "constraint_class": K.BUDGET,
                "subject": "generation.wall_clock",
                "detail": "generation must complete within the stated budget",
                "limit": 900,
                "unit": "seconds",
            },
            {
                "constraint_id": "c_silhouette_variety",
                "constraint_class": K.SOFT_PREFERENCE,
                "subject": "composition.silhouette_variety",
                "detail": "prefer varied skyline silhouettes over uniform ones",
                "weight": 0.4,
            },
        ],
        semantic_landmarks=[
            {
                "landmark_id": "landmark_entry_01",
                "role": "entry",
                "must_be_reachable": True,
                "significance": "where the consumer's player begins",
            },
            {
                "landmark_id": "landmark_objective_01",
                "role": "objective",
                "must_be_reachable": True,
            },
        ],
        gameplay_affordances=[
            {
                "affordance_id": "afford_traversal_spine",
                "affordance_kind": "traversal",
                "required": True,
                "detail": "one continuous route across the playable extent",
            },
            {
                "affordance_id": "afford_vantage_points",
                "affordance_kind": "vantage",
                "required": False,
            },
        ],
        population={
            "density_class": "sparse",
            "population_roles": ["population_role_a", "population_role_b"],
        },
        environment={
            "extent_m2": 250000.0,
            "relief_class": "rolling",
            "lighting_condition": "overcast",
        },
        seed=1,
    )
    d.update(over)
    return build_world_request(**d)
