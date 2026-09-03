#!/usr/bin/env python3
"""wfcore.providers.base -- what a provider must DECLARE before Core will use it.

WHY A DECLARATION AND NOT AN INTERFACE
--------------------------------------
An interface says a provider *can be called*. It says nothing about what happens
when you do. Core has to answer questions before execution -- can this run here,
what will it change, can it be undone, will it produce the same result twice,
what evidence comes back, and where does it stop being trustworthy. None of those
are answerable from a method signature, so they are DECLARED as data, validated
at authoring time, and carried into selection as the only facts selection is
allowed to reason about.

The declaration is therefore the contract. A provider is a record first and an
implementation second; this module owns the record and nothing else. No execution
lives here, and none is planned for this layer -- Core must be able to *describe*
and *rank* a capability it cannot currently run.

THE FOUR CLAIMS THAT ARE NOT FREE
---------------------------------
Every field below is a claim, and four of them are claims a provider could make
for free while being wrong. Each has a rail:

1. ``side_effects: []`` -- silence is not "none". An empty list is indistinguishable
   from "the author did not think about it", and those have opposite correct
   behaviours: a provider with genuinely no mutation must SAY so by declaring an
   ``emits_evidence_only`` effect. Empty -> WF1231.

2. ``determinism: deterministic_given_seed`` with no proof. Determinism is the
   property every reproducibility argument in this repository rests on, and it is
   the easiest one to assert and never test. Claiming it requires
   ``determinism_evidence`` -> WF1233.

3. ``rollback`` that contradicts the side effects it would have to undo. A
   ``transactional`` claim over an effect the provider itself marks
   ``reversible: false`` is not a rollback mechanism, it is a rollback-shaped
   sentence -> WF1232.

4. ``limitations: []`` -- a provider that declares no limitations is claiming
   universality, and universality is never true of a real tool. The rail does NOT
   force the author to invent a limitation: it forces them to SIGN the claim, by
   declaring a ``none_known`` limitation with ``attested_by``. This mirrors
   ``constraints.DECLARED_UNKNOWN``: the undecided case must be statable, so that
   it is distinguishable from the unconsidered case. Empty -> WF1226.

CAPABILITY IS WHAT IS DONE, NOT WHO DOES IT
-------------------------------------------
The capability vocabulary names *effects on the world*, never tool families.
Editor automation, a runtime-safe plugin path, procedural scattering, external
geometry synthesis, mesh synthesis, material tooling and scripted tool bridges
are all describable as combinations of the capabilities below -- which is the
point: selection matches on WHAT IS WANTED, so a second tool offering the same
capability is a candidate on day one without a new vocabulary entry or a code
change. A provider's identity lives in ``provider_id``; it is never a capability.

Domain neutrality: Core owns no consumer's vocabulary. Nothing here -- including
the examples -- may name a game, map, actor, faction, biome or asset (WF1211).
"""

from typing import Any, Dict, List, Optional, Tuple

from .. import tri
from ..failure import FailureCode as C

# --------------------------------------------------------------------------- #
# schema identity (house convention: wf.<domain>.<thing>.v<N>)
# --------------------------------------------------------------------------- #
RT_PROVIDER_DECLARATION = "wf.core.provider_declaration.v1"

Check = Tuple[str, bool, str, Optional[str]]

# --------------------------------------------------------------------------- #
# CAPABILITY vocabulary -- the closed set of things a provider can offer to DO.
# Deliberately about effect, not implementation. Adding an entry is a contract
# change visible to every consumer, so it is one visible tuple.
# --------------------------------------------------------------------------- #
CAP_EDITOR_AUTHORING = "editor_authoring"          # mutate authored content in-editor
CAP_RUNTIME_AUTHORING = "runtime_authoring"        # runtime-safe, shippable code path
CAP_TERRAIN_SHAPING = "terrain_shaping"            # bulk landform/height authoring
CAP_PROCEDURAL_SCATTER = "procedural_scatter"      # rule-driven instance placement
CAP_GEOMETRY_SYNTHESIS = "geometry_synthesis"      # generate geometry from parameters
CAP_MESH_SYNTHESIS = "mesh_synthesis"              # generate/derive mesh assets
CAP_MATERIAL_AUTHORING = "material_authoring"      # author/derive material assets
CAP_ASSET_INGEST = "asset_ingest"                  # import external artifacts
CAP_SCENE_OBSERVATION = "scene_observation"        # measure the world, mutate nothing
CAP_SCRIPTED_TOOL_BRIDGE = "scripted_tool_bridge"  # drive tooling via a script channel
# Lighting, fog, atmosphere and the rest of the environment envelope. Added as a
# visible contract change rather than smuggling rigs in under procedural_scatter:
# an environment rig is not a scatter, and mislabelling it would make provider
# selection choose the wrong thing for the right-sounding reason.
CAP_ENVIRONMENT_AUTHORING = "environment_authoring"

CAPABILITIES = (
    CAP_EDITOR_AUTHORING,
    CAP_RUNTIME_AUTHORING,
    CAP_TERRAIN_SHAPING,
    CAP_PROCEDURAL_SCATTER,
    CAP_GEOMETRY_SYNTHESIS,
    CAP_MESH_SYNTHESIS,
    CAP_MATERIAL_AUTHORING,
    CAP_ASSET_INGEST,
    CAP_SCENE_OBSERVATION,
    CAP_SCRIPTED_TOOL_BRIDGE,
    CAP_ENVIRONMENT_AUTHORING,
)

# --------------------------------------------------------------------------- #
# determinism / rollback / side-effect / requirement / limitation vocabularies
# --------------------------------------------------------------------------- #
DET_SEEDED = "deterministic_given_seed"      # same seed + same inputs -> same output
DET_ENV_DEPENDENT = "stable_within_environment"  # stable per host/toolchain, not across
DET_NONDETERMINISTIC = "nondeterministic"
DET_UNKNOWN = "unknown"
DETERMINISM_CLASSES = (DET_SEEDED, DET_ENV_DEPENDENT, DET_NONDETERMINISTIC, DET_UNKNOWN)

ROLLBACK_TRANSACTIONAL = "transactional"   # a real undo boundary
ROLLBACK_COMPENSATING = "compensating"     # undo by inverse operation, best effort
ROLLBACK_NONE = "none"
ROLLBACK_UNKNOWN = "unknown"
ROLLBACK_MODES = (ROLLBACK_TRANSACTIONAL, ROLLBACK_COMPENSATING,
                  ROLLBACK_NONE, ROLLBACK_UNKNOWN)
# The modes that can actually undo something. Used by selection as a FILTER.
ROLLBACK_CAPABLE = (ROLLBACK_TRANSACTIONAL, ROLLBACK_COMPENSATING)

EFFECT_PERSISTENT_ASSET = "mutates_persistent_asset"
EFFECT_TRANSIENT_SCENE = "mutates_transient_scene"
EFFECT_EDITOR_STATE = "mutates_editor_state"
EFFECT_FILESYSTEM = "writes_filesystem"
EFFECT_EXTERNAL_PROCESS = "spawns_external_process"
EFFECT_NETWORK = "consumes_network"
EFFECT_EVIDENCE_ONLY = "emits_evidence_only"   # the explicit "I mutate nothing"
SIDE_EFFECT_KINDS = (
    EFFECT_PERSISTENT_ASSET, EFFECT_TRANSIENT_SCENE, EFFECT_EDITOR_STATE,
    EFFECT_FILESYSTEM, EFFECT_EXTERNAL_PROCESS, EFFECT_NETWORK,
    EFFECT_EVIDENCE_ONLY,
)

REQ_ENVIRONMENT = "environment"          # host/toolchain state
REQ_EXTERNAL_TOOL = "external_tool"      # a tool that must be installed/reachable
REQ_ENTITLEMENT = "entitlement"          # licence/seat/permission
REQ_INPUT_ARTIFACT = "input_artifact"    # an artifact that must already exist
REQ_ENGINE_STATE = "engine_state"        # editor/runtime must be in some state
REQ_CONSUMER_SUPPLIED = "consumer_supplied"   # the caller must provide something
REQUIREMENT_KINDS = (REQ_ENVIRONMENT, REQ_EXTERNAL_TOOL, REQ_ENTITLEMENT,
                     REQ_INPUT_ARTIFACT, REQ_ENGINE_STATE, REQ_CONSUMER_SUPPLIED)

LIM_SCALE = "scale"
LIM_FIDELITY = "fidelity"
LIM_PLATFORM = "platform"
LIM_INPUT_SHAPE = "input_shape"
LIM_CONCURRENCY = "concurrency"
LIM_COST = "cost"
LIM_COVERAGE_UNKNOWN = "coverage_unknown"
LIM_NONE_KNOWN = "none_known"            # the SIGNED universality claim
LIMITATION_KINDS = (LIM_SCALE, LIM_FIDELITY, LIM_PLATFORM, LIM_INPUT_SHAPE,
                    LIM_CONCURRENCY, LIM_COST, LIM_COVERAGE_UNKNOWN,
                    LIM_NONE_KNOWN)

# --------------------------------------------------------------------------- #
# record shapes
# --------------------------------------------------------------------------- #
PROVIDER_DECLARATION_REQUIRED = (
    "provider_id",        # stable identity; NEVER a capability, NEVER selectable directly
    "capabilities",       # >=1, all from CAPABILITIES
    "requirements",       # what must be true to run it (may be empty: nothing required)
    "side_effects",       # >=1; declare emits_evidence_only for a pure observer
    "determinism",        # one of DETERMINISM_CLASSES
    "rollback",           # one of ROLLBACK_MODES
    "outputs",            # >=1 output kind strings -- what the caller gets
    "evidence",           # >=1 evidence kind strings -- what proves what happened
    "limitations",        # >=1; a signed none_known counts, an empty list does not
    "schema_version",
)
PROVIDER_DECLARATION_ALLOWED = PROVIDER_DECLARATION_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "description", "notes",
    "determinism_evidence",   # required when determinism == DET_SEEDED
    "cost_profile",           # metric -> number; read by BUDGET filters + ranking
)

REQUIREMENT_REQUIRED = ("requirement_id", "requirement_kind", "subject", "detail")
REQUIREMENT_ALLOWED = REQUIREMENT_REQUIRED + ("observation_key", "notes")

SIDE_EFFECT_REQUIRED = ("effect_id", "effect_kind", "scope", "reversible")
SIDE_EFFECT_ALLOWED = SIDE_EFFECT_REQUIRED + ("detail", "notes")

LIMITATION_REQUIRED = ("limitation_id", "limitation_kind", "detail")
LIMITATION_ALLOWED = LIMITATION_REQUIRED + ("attested_by", "notes")


# --------------------------------------------------------------------------- #
# small local helpers (hand-rolled, mirroring wfcore.constraints -- Core does not
# import the flat pipeline RS helpers, only the failure-code authority)
# --------------------------------------------------------------------------- #
def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _str_list(value: Any, min_len: int = 0) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) >= min_len
            and all(_nonempty_str(v) for v in value))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# --------------------------------------------------------------------------- #
# requirement evaluation -- the ONLY place a requirement becomes a tri-value
# --------------------------------------------------------------------------- #
def evaluate_requirement(requirement: Dict[str, Any],
                         observations: Dict[str, Any]) -> str:
    """Evaluate ONE requirement against observations. Absent observation -> UNKNOWN.

    The default is UNKNOWN and it is load-bearing. A requirement nobody measured
    is not "fine" -- selection must be able to say "I could not tell", because
    the alternative (defaulting to satisfied) selects a provider that may not be
    runnable, and the alternative alternative (defaulting to violated) reports a
    failure of something that was never checked and sends repair after a
    non-existent defect.

    An observation whose value cannot be interpreted as a measurement is also
    UNKNOWN: a value we cannot read is not an observation we took.
    """
    key = requirement.get("observation_key") or requirement.get("requirement_id")
    if not isinstance(observations, dict) or key not in observations:
        return tri.UNKNOWN
    value = observations[key]
    if isinstance(value, bool):
        return tri.from_bool(value, measured=True)
    if isinstance(value, str) and value in tri.TRI_VALUES:
        return value
    return tri.UNKNOWN


def evaluate_requirements(declaration: Dict[str, Any],
                          observations: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """Fold every requirement into ONE tri-value, plus a per-requirement trace.

    Kleene conjunction: a single VIOLATED is decisive; otherwise any UNKNOWN
    keeps the whole thing UNKNOWN. Zero requirements folds to SATISFIED by
    ``tri.conj``'s identity -- correct here, because "this provider requires
    nothing" is a real and checkable state, unlike an empty constraint set.

    The trace is returned rather than logged: selection has to be able to say
    WHICH requirement was unknown, and a fold alone cannot.
    """
    trace: List[Dict[str, Any]] = []
    reqs = declaration.get("requirements") or []
    for req in reqs:
        if not isinstance(req, dict):
            trace.append({"requirement_id": None, "evaluation": tri.UNKNOWN,
                          "detail": "malformed requirement record"})
            continue
        value = evaluate_requirement(req, observations)
        trace.append({
            "requirement_id": req.get("requirement_id"),
            "requirement_kind": req.get("requirement_kind"),
            "subject": req.get("subject"),
            "evaluation": value,
            "detail": ("requirement satisfied by observation" if value == tri.SATISFIED
                       else "requirement violated by observation" if value == tri.VIOLATED
                       else "no observation supports a verdict for this requirement"),
        })
    return tri.conj(t["evaluation"] for t in trace), trace


def declared_effect_kinds(declaration: Dict[str, Any]) -> Tuple[str, ...]:
    """The side-effect kinds this provider admits to. Used by PROHIBITED filters."""
    out = []
    for eff in declaration.get("side_effects") or []:
        if isinstance(eff, dict) and _nonempty_str(eff.get("effect_kind")):
            out.append(eff["effect_kind"])
    return tuple(out)


def declared_effect_scopes(declaration: Dict[str, Any]) -> Tuple[str, ...]:
    """The scopes this provider admits it will touch. Used by PROTECTED filters."""
    out = []
    for eff in declaration.get("side_effects") or []:
        if isinstance(eff, dict) and _nonempty_str(eff.get("scope")):
            out.append(eff["scope"])
    return tuple(out)


def mutates_anything(declaration: Dict[str, Any]) -> bool:
    """True unless every declared effect is ``emits_evidence_only``."""
    kinds = declared_effect_kinds(declaration)
    return any(k != EFFECT_EVIDENCE_ONLY for k in kinds)


# --------------------------------------------------------------------------- #
# validators
# --------------------------------------------------------------------------- #
def validate_requirement(requirement: Any, strict: bool = False) -> List[Check]:
    """Validate ONE requirement record."""
    checks: List[Check] = []
    code = C.CORE_PROVIDER_DECLARATION_INVALID
    if not isinstance(requirement, dict):
        return [("requirement_is_object", False,
                 "requirement must be an object, got {}".format(type(requirement).__name__),
                 code)]
    for fld in REQUIREMENT_REQUIRED:
        ok = _nonempty_str(requirement.get(fld))
        checks.append(("requirement_has_" + fld, ok,
                       "required field {!r} {}".format(
                           fld, "present" if ok else "missing/empty"),
                       None if ok else code))
    kind = requirement.get("requirement_kind")
    ok = kind in REQUIREMENT_KINDS
    checks.append(("requirement_kind_known", ok,
                   "requirement_kind {!r} must be one of {}".format(kind, REQUIREMENT_KINDS),
                   None if ok else code))
    if strict:
        extra = sorted(set(requirement) - set(REQUIREMENT_ALLOWED))
        checks.append(("requirement_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields",
                       None if not extra else code))
    return checks


def validate_side_effect(effect: Any, strict: bool = False) -> List[Check]:
    """Validate ONE side-effect record."""
    checks: List[Check] = []
    code = C.CORE_PROVIDER_SIDE_EFFECT_UNDECLARED
    if not isinstance(effect, dict):
        return [("side_effect_is_object", False,
                 "side effect must be an object, got {}".format(type(effect).__name__),
                 code)]
    for fld in ("effect_id", "scope"):
        ok = _nonempty_str(effect.get(fld))
        checks.append(("side_effect_has_" + fld, ok,
                       "required field {!r} {}".format(
                           fld, "present" if ok else "missing/empty"),
                       None if ok else code))
    kind = effect.get("effect_kind")
    ok = kind in SIDE_EFFECT_KINDS
    checks.append(("side_effect_kind_known", ok,
                   "effect_kind {!r} must be one of {}".format(kind, SIDE_EFFECT_KINDS),
                   None if ok else code))
    rev = effect.get("reversible")
    ok = isinstance(rev, bool)
    checks.append(("side_effect_reversible_explicit", ok,
                   "reversible must be an explicit boolean (got {!r}); an omitted "
                   "reversibility is read by a planner as 'safe to try', which is "
                   "the assumption that most needs to be stated".format(rev),
                   None if ok else C.CORE_PROVIDER_ROLLBACK_UNSUPPORTED))
    if strict:
        extra = sorted(set(effect) - set(SIDE_EFFECT_ALLOWED))
        checks.append(("side_effect_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields",
                       None if not extra else code))
    return checks


def validate_limitation(limitation: Any, strict: bool = False) -> List[Check]:
    """Validate ONE limitation record, including the signed-universality rail."""
    checks: List[Check] = []
    code = C.CORE_PROVIDER_DECLARATION_INVALID
    if not isinstance(limitation, dict):
        return [("limitation_is_object", False,
                 "limitation must be an object, got {}".format(type(limitation).__name__),
                 code)]
    for fld in LIMITATION_REQUIRED:
        ok = _nonempty_str(limitation.get(fld))
        checks.append(("limitation_has_" + fld, ok,
                       "required field {!r} {}".format(
                           fld, "present" if ok else "missing/empty"),
                       None if ok else code))
    kind = limitation.get("limitation_kind")
    ok = kind in LIMITATION_KINDS
    checks.append(("limitation_kind_known", ok,
                   "limitation_kind {!r} must be one of {}".format(kind, LIMITATION_KINDS),
                   None if ok else code))
    if kind == LIM_NONE_KNOWN:
        ok = _nonempty_str(limitation.get("attested_by"))
        checks.append(("limitation_none_known_is_attested", ok,
                       "a {!r} limitation is a claim of universality and must name "
                       "attested_by; unsigned, it is indistinguishable from nobody "
                       "having looked".format(LIM_NONE_KNOWN),
                       None if ok else code))
    if strict:
        extra = sorted(set(limitation) - set(LIMITATION_ALLOWED))
        checks.append(("limitation_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields",
                       None if not extra else code))
    return checks


def validate_provider_declaration(declaration: Any, strict: bool = False) -> List[Check]:
    """Validate a WHOLE provider declaration, including the four honesty rails.

    Field-level checks first, then the cross-field rails that are the reason this
    validator exists at all -- each one closes a way a provider can look
    trustworthy in a report while telling Core nothing it can rely on.
    """
    checks: List[Check] = []
    code = C.CORE_PROVIDER_DECLARATION_INVALID

    if not isinstance(declaration, dict):
        return [("provider_declaration_is_object", False,
                 "declaration must be an object, got {}".format(
                     type(declaration).__name__), code)]

    for fld in PROVIDER_DECLARATION_REQUIRED:
        present = declaration.get(fld) not in (None, "")
        checks.append(("provider_has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing/empty"),
                       None if present else code))

    checks.append(("provider_id_nonempty_string", _nonempty_str(declaration.get("provider_id")),
                   "provider_id must be a non-empty string", code))

    if strict:
        extra = sorted(set(declaration) - set(PROVIDER_DECLARATION_ALLOWED))
        checks.append(("provider_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields",
                       None if not extra else code))

    # --- capabilities: >=1, every one from the closed vocabulary --------------
    caps = declaration.get("capabilities")
    ok = _str_list(caps, min_len=1)
    checks.append(("provider_capabilities_nonempty", ok,
                   "capabilities must be a list of >=1 capability strings (got {!r}); "
                   "a provider offering nothing can never be selected and only "
                   "inflates the registry".format(caps), None if ok else code))
    if isinstance(caps, (list, tuple)):
        unknown = sorted({c for c in caps if c not in CAPABILITIES})
        ok = not unknown
        checks.append(("provider_capabilities_known", ok,
                       "capability {} is not in the Core vocabulary {}".format(
                           unknown, CAPABILITIES) if unknown
                       else "all capabilities are in the Core vocabulary",
                       None if ok else C.CORE_PROVIDER_CAPABILITY_UNKNOWN))
        dupes = sorted({c for c in caps if caps.count(c) > 1})
        checks.append(("provider_capabilities_unique", not dupes,
                       "duplicate capability {}".format(dupes) if dupes
                       else "no duplicate capabilities", None if not dupes else code))

    # --- outputs / evidence: a provider that produces and proves nothing -------
    for fld, why in (("outputs", "a provider that produces no output cannot satisfy "
                                 "any requested result"),
                     ("evidence", "a provider that emits no evidence cannot be "
                                  "verified, so its success is unfalsifiable")):
        ok = _str_list(declaration.get(fld), min_len=1)
        checks.append(("provider_{}_nonempty".format(fld), ok,
                       "{} must be a list of >=1 strings; {}".format(fld, why),
                       None if ok else code))

    # --- requirements: list (may be empty), each valid -------------------------
    reqs = declaration.get("requirements")
    ok = isinstance(reqs, (list, tuple))
    checks.append(("provider_requirements_is_list", ok,
                   "requirements must be a list (an empty list is a real, checkable "
                   "claim: this provider requires nothing)", None if ok else code))
    if isinstance(reqs, (list, tuple)):
        for idx, req in enumerate(reqs):
            for (name, sub_ok, detail, sub_code) in validate_requirement(req, strict=strict):
                checks.append(("requirement[{}].{}".format(idx, name), sub_ok, detail, sub_code))
        ids = [r.get("requirement_id") for r in reqs if isinstance(r, dict)]
        dupes = sorted({i for i in ids if i and ids.count(i) > 1})
        checks.append(("provider_requirement_ids_unique", not dupes,
                       "duplicate requirement_id {}".format(dupes) if dupes
                       else "requirement ids unique", None if not dupes else code))

    # --- RAIL 1: silence is not "no side effects" (WF1231) --------------------
    effects = declaration.get("side_effects")
    is_list = isinstance(effects, (list, tuple))
    ok = is_list and len(effects) > 0
    checks.append(("provider_side_effects_declared", ok,
                   "side_effects is {!r}; an empty/absent list is indistinguishable "
                   "from an author who never considered it. A provider that mutates "
                   "nothing must SAY so with an {!r} effect, so that 'none' is a "
                   "declaration rather than a silence".format(effects, EFFECT_EVIDENCE_ONLY),
                   None if ok else C.CORE_PROVIDER_SIDE_EFFECT_UNDECLARED))
    if is_list:
        for idx, eff in enumerate(effects):
            for (name, sub_ok, detail, sub_code) in validate_side_effect(eff, strict=strict):
                checks.append(("side_effect[{}].{}".format(idx, name), sub_ok, detail, sub_code))

    # --- RAIL 4: limitations must be declared or universality signed (WF1226) --
    lims = declaration.get("limitations")
    is_list = isinstance(lims, (list, tuple))
    ok = is_list and len(lims) > 0
    checks.append(("provider_limitations_declared", ok,
                   "limitations is {!r}; a provider that declares no limitation is "
                   "claiming universality by omission. Declare the real limits, or "
                   "declare a {!r} limitation with attested_by and own the claim"
                   .format(lims, LIM_NONE_KNOWN), None if ok else code))
    if is_list:
        for idx, lim in enumerate(lims):
            for (name, sub_ok, detail, sub_code) in validate_limitation(lim, strict=strict):
                checks.append(("limitation[{}].{}".format(idx, name), sub_ok, detail, sub_code))

    # --- determinism vocabulary + RAIL 2: an unproven claim (WF1233) ----------
    det = declaration.get("determinism")
    ok = det in DETERMINISM_CLASSES
    checks.append(("provider_determinism_known", ok,
                   "determinism {!r} must be one of {}".format(det, DETERMINISM_CLASSES),
                   None if ok else code))
    if det == DET_SEEDED:
        ev = declaration.get("determinism_evidence")
        ok = _nonempty_str(ev) or _str_list(ev, min_len=1)
        checks.append(("provider_determinism_claim_is_proven", ok,
                       "determinism={!r} is the claim every reproducibility argument "
                       "rests on and the cheapest one to assert; it requires "
                       "determinism_evidence naming what proves it (got {!r})"
                       .format(det, ev),
                       None if ok else C.CORE_PROVIDER_DETERMINISM_UNPROVEN))

    # --- rollback vocabulary + RAIL 3: a rollback that cannot cover its effects -
    rb = declaration.get("rollback")
    ok = rb in ROLLBACK_MODES
    checks.append(("provider_rollback_known", ok,
                   "rollback {!r} must be one of {}".format(rb, ROLLBACK_MODES),
                   None if ok else code))
    if isinstance(effects, (list, tuple)):
        irreversible = sorted({e.get("effect_id") for e in effects
                               if isinstance(e, dict) and e.get("reversible") is False})
        if rb == ROLLBACK_TRANSACTIONAL:
            ok = not irreversible
            checks.append(("provider_rollback_covers_effects", ok,
                           "rollback={!r} but effect(s) {} are declared reversible=false; "
                           "a transactional boundary that cannot undo its own effects is "
                           "a rollback-shaped sentence, and a planner reading it will "
                           "authorise a mutation on the strength of an undo that does "
                           "not exist".format(rb, irreversible),
                           None if ok else C.CORE_PROVIDER_ROLLBACK_UNSUPPORTED))
        if rb in (ROLLBACK_NONE, ROLLBACK_UNKNOWN):
            reversible_claims = sorted({e.get("effect_id") for e in effects
                                        if isinstance(e, dict) and e.get("reversible") is True
                                        and e.get("effect_kind") != EFFECT_EVIDENCE_ONLY})
            ok = not reversible_claims
            checks.append(("provider_reversible_effects_have_a_mechanism", ok,
                           "effect(s) {} claim reversible=true while rollback={!r}; "
                           "reversibility with no declared mechanism cannot be invoked"
                           .format(reversible_claims, rb),
                           None if ok else C.CORE_PROVIDER_ROLLBACK_UNSUPPORTED))

    # --- cost_profile, when present, must be numeric (BUDGET filters read it) --
    cost = declaration.get("cost_profile")
    if cost is not None:
        ok = isinstance(cost, dict) and all(
            _nonempty_str(k) and _is_number(v) for k, v in cost.items())
        checks.append(("provider_cost_profile_numeric", ok,
                       "cost_profile must map metric names to numbers (got {!r}); "
                       "a non-numeric cost cannot be compared to a BUDGET limit and "
                       "would silently evaluate as unknown".format(cost),
                       None if ok else code))

    sv = declaration.get("schema_version")
    ok = sv == RT_PROVIDER_DECLARATION
    checks.append(("provider_schema_version", ok,
                   "schema_version must be {!r} (got {!r})".format(
                       RT_PROVIDER_DECLARATION, sv), None if ok else code))
    return checks


# --------------------------------------------------------------------------- #
# canonical example factories (``**over`` spawns the known-bads)
# --------------------------------------------------------------------------- #
def _example_requirement(**over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "requirement_id": "req_authoring_session_open",
        "requirement_kind": REQ_ENGINE_STATE,
        "subject": "engine.authoring_session",
        "detail": "an interactive authoring session must be open and idle",
        "observation_key": "engine.authoring_session_open",
    }
    d.update(over)
    return d


def _example_side_effect(**over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "effect_id": "eff_persistent_content_write",
        "effect_kind": EFFECT_PERSISTENT_ASSET,
        "scope": "content.authored_assets",
        "reversible": True,
        "detail": "writes authored assets inside the operation's mutation bound",
    }
    d.update(over)
    return d


def _example_limitation(**over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "limitation_id": "lim_instance_count_ceiling",
        "limitation_kind": LIM_SCALE,
        "detail": "degrades beyond roughly 1e5 authored instances per operation",
    }
    d.update(over)
    return d


def _example_provider_declaration(**over: Any) -> Dict[str, Any]:
    """Canonical-valid declaration. Domain-neutral by construction (WF1211)."""
    d: Dict[str, Any] = {
        "provider_id": "editor_authoring_bridge",
        "capabilities": [CAP_EDITOR_AUTHORING, CAP_MATERIAL_AUTHORING],
        "requirements": [_example_requirement()],
        "side_effects": [_example_side_effect()],
        "determinism": DET_SEEDED,
        "determinism_evidence": ["repeat_run_hash_equality_suite"],
        "rollback": ROLLBACK_TRANSACTIONAL,
        "outputs": ["authored_asset_set", "operation_manifest"],
        "evidence": ["operation_manifest", "raw_observation_log"],
        "limitations": [_example_limitation()],
        "cost_profile": {"wall_seconds": 30.0, "operator_attention": 0.0},
        "description": "authors content through an interactive engine session",
        "created_by": "worldforge.core",
        "schema_version": RT_PROVIDER_DECLARATION,
        "report_type": RT_PROVIDER_DECLARATION,
    }
    d.update(over)
    return d
