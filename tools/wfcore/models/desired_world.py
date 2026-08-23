#!/usr/bin/env python3
"""wfcore.models.desired_world -- the world the consumer WANTS, authored.

WHAT THIS MODEL IS
------------------
A desired world is the typed form of a consumer's request: the semantic
landmarks it wants legible, the gameplay anchors it wants to exist, the
population it wants present, the environmental state it wants the world to be
in, and the spatial relations that must hold between those things.

It is AUTHORED. Every value in it is intent, and intent needs no evidence -- a
consumer asking for two orientation references is not making a claim about the
world, it is stating what the world should become. That is the entire reason
this model is a plain record while ``observed_world`` is not.

THE ONE CONFUSION THIS FILE POLICES
-----------------------------------
The dangerous direction is not "desired lacks evidence" (it should) -- it is a
desired model that ARRIVES CARRYING evidence-provenance fields. That happens
when a caller round-trips an observed model, edits a few values, and submits it
as a request; or when a tool builds "desired" by copying "observed" and patching
the deltas. The result is a document that looks measured, differences against
itself, and produces an empty plan.

So ``validate_desired_world`` walks the whole record and rejects any nested
occurrence of an observation-provenance key (:data:`OBSERVATION_ONLY_FIELDS`).
A desired world may not even mention how something was observed, because it is
not a statement about what IS.

WHY IDS ARE ONE FLAT NAMESPACE
------------------------------
Spatial relations reference landmarks, anchors and population groups by bare id.
If two sections may reuse an id, a relation endpoint resolves to two different
entities and the relation means two different things depending on which the
reader picks. Uniqueness is therefore checked ACROSS sections, not within them,
and relation ids join the same namespace so a relation cannot shadow an entity.
"""

from typing import Any, Dict, List, Optional, Tuple

from ..failure import FailureCode as C

# --------------------------------------------------------------------------- #
# schema identity
# --------------------------------------------------------------------------- #
RT_DESIRED_WORLD = "wf.core.desired_world.v1"

# --------------------------------------------------------------------------- #
# The identity a desired and an observed model must agree on before they may be
# differenced. Declared HERE (the authored side declares identity; the observed
# side must read it back out of the world) and imported by observed_world so
# there is one tuple, not two that drift.
#
# ``revision`` is part of identity on purpose: differencing revision 3 of a
# request against a world observed under revision 2 is differencing against a
# stale world, and the resulting plan re-does or undoes work already applied.
# --------------------------------------------------------------------------- #
WORLD_IDENTITY_KEYS = ("world_id", "request_id", "revision")

# --------------------------------------------------------------------------- #
# Entity kinds and the section each lives in. One source of truth: the
# validator, the id-space walker and the differ all read this mapping.
# --------------------------------------------------------------------------- #
SEMANTIC_LANDMARK = "semantic_landmark"
GAMEPLAY_ANCHOR = "gameplay_anchor"
POPULATION_GROUP = "population_group"
ENVIRONMENT_STATE = "environment_state"
SPATIAL_RELATION = "spatial_relation"

DESIRED_ENTITY_KINDS = (
    SEMANTIC_LANDMARK,
    GAMEPLAY_ANCHOR,
    POPULATION_GROUP,
    ENVIRONMENT_STATE,
    SPATIAL_RELATION,
)

# section name -> (entity kind, id field, required fields)
SECTION_SPEC = {
    "semantic_landmarks": (SEMANTIC_LANDMARK, "landmark_id",
                           ("landmark_id", "role", "intent")),
    "gameplay_anchors": (GAMEPLAY_ANCHOR, "anchor_id",
                         ("anchor_id", "role", "required")),
    "population": (POPULATION_GROUP, "group_id",
                   ("group_id", "role", "target_count")),
    "environmental_state": (ENVIRONMENT_STATE, "state_id",
                            ("state_id", "state_dimension", "state_value")),
    "spatial_relations": (SPATIAL_RELATION, "relation_id",
                          ("relation_id", "relation", "subject_ref",
                           "object_ref")),
}

DESIRED_SECTIONS = tuple(sorted(SECTION_SPEC))

# Sections whose members may be named by a spatial relation. Relations may not
# reference other relations: a relation between relations has no spatial meaning
# and would let a cycle of references resolve without touching a single entity.
RELATABLE_SECTIONS = ("semantic_landmarks", "gameplay_anchors", "population",
                      "environmental_state")

# --------------------------------------------------------------------------- #
# Closed relation vocabulary. Neutral, geometric/topological terms only -- Core
# owns no consumer's spatial idiom.
# --------------------------------------------------------------------------- #
NEAR = "near"
FAR_FROM = "far_from"
CONTAINS = "contains"
ADJACENT_TO = "adjacent_to"
VISIBLE_FROM = "visible_from"
REACHABLE_FROM = "reachable_from"
ABOVE = "above"
BELOW = "below"
SEPARATED_FROM = "separated_from"

SPATIAL_RELATIONS = (NEAR, FAR_FROM, CONTAINS, ADJACENT_TO, VISIBLE_FROM,
                     REACHABLE_FROM, ABOVE, BELOW, SEPARATED_FROM)

# --------------------------------------------------------------------------- #
# Keys that belong ONLY to a measurement. Their presence anywhere inside a
# desired world means an observed record was edited into a request.
# Kept in sync with observed_world.OBSERVED_FIELD_ALLOWED by
# test_models.test_provenance_key_lists_agree -- a new provenance key that this
# tuple does not know about would open a hole in the rail below.
# --------------------------------------------------------------------------- #
OBSERVATION_ONLY_FIELDS = (
    "provenance",
    "observed_by",
    "operation_id",
    "collection_ok",
    "evidence_refs",
    "derived_from",
    "observed_at_stage",
)

# --------------------------------------------------------------------------- #
# record shape
# --------------------------------------------------------------------------- #
DESIRED_WORLD_REQUIRED = (
    "world_id",
    "request_id",
    "revision",
    "semantic_landmarks",
    "gameplay_anchors",
    "population",
    "environmental_state",
    "spatial_relations",
    "schema_version",
)

DESIRED_WORLD_ALLOWED = DESIRED_WORLD_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
    "experience_graph_id",   # optional: the experience graph authored alongside
    "env_state_graph_id",    # optional: the environmental-state graph
)

Check = Tuple[str, bool, str, Optional[str]]

_P = "dw::"


# --------------------------------------------------------------------------- #
# readers
# --------------------------------------------------------------------------- #
def desired_identity(model: Any) -> Optional[Dict[str, Any]]:
    """The identity block, or None when it is not fully stated.

    None rather than a partially-filled dict: a half-identity would compare
    equal to another half-identity on the keys both happen to carry, which is
    exactly the silent match this identity exists to prevent.
    """
    if not isinstance(model, dict):
        return None
    if any(model.get(k) in (None, "") for k in WORLD_IDENTITY_KEYS):
        return None
    return {k: model[k] for k in WORLD_IDENTITY_KEYS}


def _entries(model: Any, section: str) -> List[Dict[str, Any]]:
    v = model.get(section) if isinstance(model, dict) else None
    return [e for e in v if isinstance(e, dict)] if isinstance(v, list) else []


def entity_ids(model: Any, sections: Tuple[str, ...] = RELATABLE_SECTIONS) -> List[str]:
    """Every declared entity id in ``sections``, in section order.

    Duplicates are preserved: the uniqueness rail needs to see them, and a
    silently de-duplicated list is how a duplicate id stops being detectable.
    """
    out: List[str] = []
    for section in sections:
        id_field = SECTION_SPEC[section][1]
        for e in _entries(model, section):
            ident = e.get(id_field)
            if isinstance(ident, str) and ident:
                out.append(ident)
    return out


def all_declared_ids(model: Any) -> List[str]:
    """Every id in the flat namespace -- entities AND relations."""
    return entity_ids(model, DESIRED_SECTIONS)


def declares_anything(model: Any) -> bool:
    """True when the model declares at least one entity.

    A desired world with no entities differences to "no change" against ANY
    observed world, so it accepts everything while reading as a real request.
    """
    return len(entity_ids(model)) > 0


def _observation_keys_present(node: Any, path: str = "$") -> List[str]:
    """Every path at which an observation-provenance key appears. Recursive."""
    found: List[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            here = "{}.{}".format(path, k)
            if k in OBSERVATION_ONLY_FIELDS:
                found.append(here)
            found.extend(_observation_keys_present(v, here))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found.extend(_observation_keys_present(v, "{}[{}]".format(path, i)))
    return found


# --------------------------------------------------------------------------- #
# validator
# --------------------------------------------------------------------------- #
def validate_desired_world(obj: Any, strict: bool = False) -> List[Check]:
    """Validate ONE desired-world record. House ``(name, ok, detail, code)``.

    Everything here is a structural or coherence rail. Whether the consumer's
    intent is ACHIEVABLE is not this function's question -- that is constraint
    analysis against an observed world, and answering it here would be Core
    deciding what the consumer is allowed to want.
    """
    code = C.CORE_DESIRED_WORLD_INVALID
    checks: List[Check] = []

    if not isinstance(obj, dict):
        return [(_P + "is_object", False,
                 "desired world must be an object, got {}".format(
                     type(obj).__name__), code)]

    for fld in DESIRED_WORLD_REQUIRED:
        present = obj.get(fld) is not None
        checks.append((_P + "has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else code))

    if strict:
        unknown = sorted(set(obj) - set(DESIRED_WORLD_ALLOWED))
        checks.append((_P + "no_unknown_fields", not unknown,
                       "unexpected field(s) {}".format(unknown) if unknown
                       else "no unexpected fields",
                       None if not unknown else code))

    sv = obj.get("schema_version")
    checks.append((_P + "schema_version", sv == RT_DESIRED_WORLD,
                   "schema_version must be {!r} (got {!r})".format(
                       RT_DESIRED_WORLD, sv),
                   None if sv == RT_DESIRED_WORLD else code))

    # --- identity ---------------------------------------------------------- #
    for fld in ("world_id", "request_id"):
        v = obj.get(fld)
        ok = isinstance(v, str) and bool(v.strip())
        checks.append((_P + fld + "_nonempty", ok,
                       "{} must be a non-empty string (got {!r})".format(fld, v),
                       None if ok else code))
    rev = obj.get("revision")
    rev_ok = isinstance(rev, int) and not isinstance(rev, bool) and rev >= 0
    checks.append((_P + "revision_integer", rev_ok,
                   "revision must be a non-negative integer (got {!r}); it is "
                   "part of world identity, so a missing or float revision "
                   "makes the desired/observed pair unmatchable".format(rev),
                   None if rev_ok else code))

    # --- sections are lists of objects -------------------------------------- #
    for section in DESIRED_SECTIONS:
        v = obj.get(section)
        ok = isinstance(v, list) and all(isinstance(e, dict) for e in v)
        checks.append((_P + section + "_list_of_objects", ok,
                       "{} must be a list of objects (got {!r})".format(
                           section, type(v).__name__),
                       None if ok else code))

    # --- per-entry required fields ------------------------------------------ #
    for section in DESIRED_SECTIONS:
        _kind, id_field, required = SECTION_SPEC[section]
        for idx, entry in enumerate(_entries(obj, section)):
            for fld in required:
                present = entry.get(fld) is not None and entry.get(fld) != ""
                checks.append((
                    "{}{}[{}].has_{}".format(_P, section, idx, fld), present,
                    "{}[{}] required field {!r} {}".format(
                        section, idx, fld,
                        "present" if present else "missing/empty"),
                    None if present else code))
            ident = entry.get(id_field)
            ok = isinstance(ident, str) and bool(ident.strip())
            checks.append((
                "{}{}[{}].id_nonempty".format(_P, section, idx), ok,
                "{}[{}] {} must be a non-empty string (got {!r})".format(
                    section, idx, id_field, ident),
                None if ok else code))

    # --- anchors: required must be an EXPLICIT bool -------------------------- #
    # An anchor whose requiredness is absent is neither required nor optional,
    # and every downstream reader picks a different default for it.
    for idx, anchor in enumerate(_entries(obj, "gameplay_anchors")):
        v = anchor.get("required")
        ok = isinstance(v, bool)
        checks.append((
            "{}gameplay_anchors[{}].required_is_bool".format(_P, idx), ok,
            "gameplay_anchors[{}].required must be an explicit boolean (got "
            "{!r}); an implicit default decides for the consumer whether an "
            "anchor may be skipped".format(idx, v),
            None if ok else code))

    # --- population: target_count must be a real non-negative integer -------- #
    for idx, group in enumerate(_entries(obj, "population")):
        v = group.get("target_count")
        ok = isinstance(v, int) and not isinstance(v, bool) and v >= 0
        checks.append((
            "{}population[{}].target_count_integer".format(_P, idx), ok,
            "population[{}].target_count must be a non-negative integer "
            "(got {!r})".format(idx, v),
            None if ok else code))

    # --- id namespace is flat and unique ------------------------------------ #
    ids = all_declared_ids(obj)
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    checks.append((_P + "ids_unique", not dupes,
                   "duplicate id(s) {} across sections; ids form ONE namespace "
                   "because spatial relations name them bare, and a reused id "
                   "makes a relation endpoint resolve to two entities"
                   .format(dupes) if dupes else "all declared ids unique",
                   None if not dupes else code))

    # --- the model must declare something ----------------------------------- #
    any_entity = declares_anything(obj)
    checks.append((_P + "declares_at_least_one_entity", any_entity,
                   "a desired world with no landmarks, anchors, population or "
                   "environmental state differences to 'no change' against any "
                   "observed world, so it accepts everything",
                   None if any_entity else code))

    # --- relations: known kind, resolving endpoints, no self-relation -------- #
    resolvable = set(entity_ids(obj))
    for idx, rel in enumerate(_entries(obj, "spatial_relations")):
        kind = rel.get("relation")
        ok = kind in SPATIAL_RELATIONS
        checks.append((
            "{}spatial_relations[{}].relation_known".format(_P, idx), ok,
            "relation {!r} is not one of {}".format(kind, SPATIAL_RELATIONS),
            None if ok else code))
        for endpoint in ("subject_ref", "object_ref"):
            ref = rel.get(endpoint)
            ok = ref in resolvable
            checks.append((
                "{}spatial_relations[{}].{}_resolves".format(_P, idx, endpoint),
                ok,
                "{} {!r} names no declared entity; a dangling endpoint makes "
                "the relation unevaluable while still reading as a stated "
                "requirement".format(endpoint, ref),
                None if ok else code))
        subj, objt = rel.get("subject_ref"), rel.get("object_ref")
        ok = not (subj is not None and subj == objt)
        checks.append((
            "{}spatial_relations[{}].endpoints_distinct".format(_P, idx), ok,
            "subject_ref and object_ref are both {!r}; a relation from an "
            "entity to itself constrains nothing".format(subj),
            None if ok else code))

    # --- THE category rail: no observation provenance in an authored model --- #
    leaked = _observation_keys_present(obj)
    checks.append((_P + "carries_no_observation_provenance", not leaked,
                   "observation-provenance key(s) at {}; a desired world is "
                   "AUTHORED intent and must not describe how anything was "
                   "measured. Provenance here means an observed record was "
                   "edited into a request, which differences against itself "
                   "and yields an empty plan".format(leaked) if leaked
                   else "no observation-provenance keys present",
                   None if not leaked else code))

    return checks


# --------------------------------------------------------------------------- #
# canonical example
# --------------------------------------------------------------------------- #
def _example_desired_world(**over: Any) -> Dict[str, Any]:
    """Canonical-valid desired world. ``**over`` spawns the known-bads.

    Domain-neutral throughout: placeholder ids and generic level-design roles.
    Core naming a consumer's content -- even in an example -- is Core choosing a
    subject nobody asked for.
    """
    d: Dict[str, Any] = {
        "world_id": "world_0001",
        "request_id": "request_0001",
        "revision": 1,
        "semantic_landmarks": [
            {"landmark_id": "landmark_a",
             "role": "orientation_reference",
             "intent": "a reference legible from the entry anchor"},
            {"landmark_id": "landmark_b",
             "role": "orientation_reference",
             "intent": "a second reference at distance from the first"},
        ],
        "gameplay_anchors": [
            {"anchor_id": "anchor_entry", "role": "entry_point",
             "required": True},
            {"anchor_id": "anchor_objective", "role": "objective_point",
             "required": True},
        ],
        "population": [
            {"group_id": "population_group_a", "role": "ambient_agent",
             "target_count": 4},
        ],
        "environmental_state": [
            {"state_id": "state_illumination", "state_dimension": "illumination",
             "state_value": "high"},
            {"state_id": "state_visibility", "state_dimension": "visibility",
             "state_value": "unobstructed"},
        ],
        "spatial_relations": [
            {"relation_id": "relation_1", "relation": REACHABLE_FROM,
             "subject_ref": "anchor_objective", "object_ref": "anchor_entry"},
            {"relation_id": "relation_2", "relation": VISIBLE_FROM,
             "subject_ref": "landmark_a", "object_ref": "anchor_entry"},
        ],
        "experience_graph_id": "experience_graph_0001",
        "env_state_graph_id": "env_state_graph_0001",
        "created_by": "wfcore.models",
        "schema_version": RT_DESIRED_WORLD,
        "report_type": RT_DESIRED_WORLD,
    }
    d.update(over)
    return d
