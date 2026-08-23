#!/usr/bin/env python3
"""run_consumer_flow.py -- drive the whole Core flow for one named consumer.

    cd tools
    PYTHONUTF8=1 python pipeline/run_consumer_flow.py --consumer demoarena
    PYTHONUTF8=1 python pipeline/run_consumer_flow.py --consumer demoexpanse --json
    PYTHONUTF8=1 python pipeline/run_consumer_flow.py --consumer demoarena --preview

WHAT THIS PROVES, AND WHAT IT DOES NOT
--------------------------------------
It proves that a consumer's own contracts -- profile, catalog, request, revision
policy, acceptance criteria -- pass through every Core stage without Core knowing
anything about that consumer. Run it for two consumers that disagree on almost
every axis, then run ``core_boundary_proof verify``: an unchanged Core digest is
the platform claim discharged mechanically rather than asserted.

It does NOT prove a real importing game asked for anything. Both shipped
consumers are WorldForge-authored DEMONSTRATIONS and say so in their own
provenance records. This runner REFUSES to label such a run caller-originated --
see ``_origination_gate``. WorldForge presenting its own request as a caller's
would be WF1288, and it is the one error that leaves every downstream artifact
looking perfect while answering a question nobody asked.

WHY THE STAGES ARE REPORTED INDIVIDUALLY
----------------------------------------
Each stage records its own status and failure codes rather than the run
collapsing to one boolean. A flow that reports only "ok/not ok" cannot tell a
consumer whose REQUEST is malformed from one whose world genuinely fails its
invariants, and those need opposite responses: fix the contract, or change the
world. The per-stage record is what makes the difference legible.

An UNKNOWN stage is reported as UNKNOWN. It is never rounded to failure -- an
unmeasured stage is something to go measure, not something to go fix.

--preview: THE PRE-MUTATION ARTIFACT BUNDLE
===========================================
``--preview`` answers the question an importing game must be able to ask BEFORE
it permits WorldForge to touch anything: *what would this do, and what could it
reach?* It runs analysis, planning, provider selection and mutation-bound
derivation, and it mutates nothing -- no editor is booted, no transaction is
opened, no file under the consumer's control is written.

WHY THE PREVIEW CANNOT SEE A WORLD, AND WHAT THAT COSTS
-------------------------------------------------------
Nothing has been observed when a preview runs, so the observed-world model this
mode builds is unbacked in every field: ``not_observed`` with ``value=None``,
per ``models.observed_world``. That is not a placeholder to be filled in later
by something more convenient -- it is the only honest shape, and the model has
no ``caller_supplied`` provenance precisely so a request value cannot be dressed
as a measurement.

Two consequences fall out of that, and both are reported rather than smoothed:

1. ``analysis.reconcile`` REFUSES. An observed model with no MEASURED world
   identity cannot be differenced against a desired one -- nothing establishes
   that the two describe the same world -- so reconcile returns
   ``reconciled=False`` with zero findings and ``acceptance_verdict=UNKNOWN``.
   The refusal is the artifact. A preview that reconciled cleanly against a
   world nobody looked at would be the failure this mode exists to make
   impossible.
2. NOTHING CAN BE VIOLATED. A violation is a measurement, and there are none.
   Every load-bearing constraint is UNKNOWN, so the plan the pipeline would
   actually run next contains only OBSERVATION steps, and its mutation bound is
   EMPTY. The empty bound is the proof of the "mutates nothing" claim, not an
   omission.

WHY THERE ARE TWO PLANS
-----------------------
An empty bound answers "what will happen next" but not "what am I authorising".
So the bundle carries two plans, and never conflates them:

  preview_plan      what the pipeline would do NEXT, synthesized from the
                    UNKNOWN findings above. Observation steps only. Bound EMPTY.
                    This is a statement about THIS run.

  mutation_envelope the UPPER BOUND of what this request could ever reach, if
                    every measurable load-bearing constraint came back violated.
                    Revision steps, non-empty bound, real rollback. This is a
                    statement about the REQUEST and the consumer's own revision
                    policy -- explicitly NOT a finding about any world. Every
                    record in it carries ``basis="authored_maximal_obligation"``
                    and ``not_an_observation=True``.

The envelope's target addresses are derived from ids the CONSUMER authored --
its request ``subject`` and its own landmark/affordance ids -- never invented
and never read off a project. Two classes are excluded from it on purpose:
PROTECTED_SEMANTICS (whose only "remedy" would be mutating the content the
consumer protected) and DECLARED_UNKNOWN (whose remedy is a decision the
consumer owes, not a change to the world). Both are reported in their own
sections instead of being quietly planned around.

THE ASSERTION THIS MODE EXISTS TO MAKE
--------------------------------------
Preview acceptance MUST NOT be ``satisfied``, and the runner exits non-zero if
it ever is. ``acceptance.evaluate_acceptance`` is called with no delta and no
evidence -- because there is no delta and no evidence -- and refuses. A
satisfied preview would mean the pipeline can accept a world it has never
looked at, which is the one outcome no amount of downstream rigour recovers
from.
"""

import argparse
import importlib
import json
import os
import sys

# tools/ is the package root for `consumers` and `wfcore` (the same convention
# `bridge` uses). Inserted rather than assumed so the script runs from anywhere.
_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from consumers import adapter as ADP                      # noqa: E402
from wfcore import constraints as K                       # noqa: E402
from wfcore import tri                                    # noqa: E402
from wfcore.acceptance import evaluate as EV              # noqa: E402
from wfcore.analysis import reconcile as RC               # noqa: E402
from wfcore.contracts import acceptance_criteria as ACR   # noqa: E402
from wfcore.contracts import asset_catalog as AC          # noqa: E402
from wfcore.contracts import consumer_profile as CP       # noqa: E402
from wfcore.contracts import revision_policy as RP        # noqa: E402
from wfcore.contracts import world_request as WR          # noqa: E402
from wfcore.models import desired_world as DW             # noqa: E402
from wfcore.models import observed_world as OW            # noqa: E402
from wfcore.planning import plan as PL                    # noqa: E402
from wfcore.planning import synth as SY                   # noqa: E402
from wfcore.providers import base as PB                   # noqa: E402
from wfcore.providers import registry as PR               # noqa: E402
from wfcore.providers import selection as PS              # noqa: E402
from wfcore.transaction import delta as TD                # noqa: E402

REPORT_TYPE = "wf.core.consumer_flow_report.v1"
PREVIEW_REPORT_TYPE = "wf.core.consumer_preview_report.v1"

STAGE_OK = "ok"
STAGE_FAILED = "failed"
STAGE_UNKNOWN = "unknown"


def _stage(name, checks):
    """Fold a validator's checks into one stage record, preserving the codes."""
    failing = [(n, d, c) for (n, ok, d, c) in checks if not ok]
    return {
        "stage": name,
        "status": STAGE_OK if not failing else STAGE_FAILED,
        "checks_run": len(checks),
        "failures": [{"check": n, "detail": d, "failure_code": c}
                     for (n, d, c) in failing][:12],
        "failure_codes": sorted({c for (_n, _d, c) in failing if c}),
    }


def _origination_gate(adapter_record):
    """Decide -- and record -- whether this run may be called caller-originated.

    Kept as its own stage rather than an inline flag because it is the single
    claim most worth being able to audit later. A reader must be able to see that
    the question was ASKED, and see the answer, without reading the runner.
    """
    origination = ADP.origination_of(adapter_record)
    caller_originated = ADP.is_caller_originated(adapter_record)
    verdict = ADP.caller_provenance_verdict(adapter_record)
    return {
        "stage": "origination",
        "status": STAGE_OK,
        "origination": origination,
        "caller_originated": caller_originated,
        "provenance_verdict": verdict,
        "detail": (
            "this run IS caller-originated; the request came from outside "
            "WorldForge" if caller_originated else
            "this run is NOT caller-originated: the consumer is a "
            "WorldForge-authored demonstration, so no artifact from this run "
            "may be presented as a caller's request (WF1288)"),
    }


def _read_source(mod):
    """Return the consumer module's source text, or None if it cannot be read.

    None is deliberate and honest: the scanner reports unsupplied source as NOT
    CHECKED rather than as clean, so a module we could not open must not silently
    become a passing scan.
    """
    path = getattr(mod, "__file__", None)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def import_consumer(consumer_id):
    """Import a consumer module by id, from INSIDE or OUTSIDE this repository.

    A real importing game's consumer module lives in THAT GAME'S repository, not
    in ``tools/consumers/``. Resolving every id as ``consumers.<id>`` would have
    forced each caller to vendor its own intent into the platform -- which is the
    authority inversion this whole architecture exists to prevent, arriving
    through the back door as a packaging decision.

    So a dotted id is taken as a full module path and imported as-is; a bare id
    keeps the original ``consumers.<id>`` behaviour for the shipped
    demonstrations. Callers outside this repo put their own root on ``sys.path``
    (see ``--consumer-path``) and name their module in full.

    Found by the first real caller: its consumer module could not be driven at
    all until this existed.
    """
    name = consumer_id if "." in consumer_id else "consumers." + consumer_id
    return importlib.import_module(name)


def run_consumer(consumer_id):
    mod = import_consumer(consumer_id)

    adapter_record = mod.adapter()
    profile = mod.profile()
    catalog = mod.catalog()
    request = mod.request()
    policy = mod.policy()
    criteria = mod.criteria()

    stages = [
        _origination_gate(adapter_record),
        _stage("adapter", ADP.validate_adapter(adapter_record, strict=True)),
        # The source TEXT is read and handed over, not the path: passing None
        # would be reported as NOT CHECKED, and a report quoting a never-read
        # scan is indistinguishable from one quoting a real result.
        _stage("adapter_no_generation_logic",
               ADP.validate_adapter_has_no_generation_logic(
                   adapter_record,
                   _read_source(mod),
                   module_name="consumers." + consumer_id)),
        _stage("consumer_profile", CP.validate_consumer_profile(profile, strict=True)),
        _stage("asset_catalog", AC.validate_asset_catalog(catalog, strict=True)),
        _stage("world_request", WR.validate_world_request(request, strict=True)),
        _stage("revision_policy", RP.validate_revision_policy(policy, strict=True)),
        _stage("acceptance_criteria",
               ACR.validate_acceptance_criteria(criteria, strict=True)),
        _stage("constraint_set", K.validate_constraint_set(
            request["constraints"], strict=True)),
    ]

    # The constraint taxonomy, as this consumer actually uses it. Reported
    # because it is the cheapest way to see that two consumers really do differ
    # in KIND and not only in wording.
    by_class = {}
    for c in request["constraints"]:
        by_class[c["constraint_class"]] = by_class.get(c["constraint_class"], 0) + 1
    load_bearing = [c for c in request["constraints"]
                    if c["constraint_class"] in K.ACCEPTANCE_LOAD_BEARING]

    # With nothing observed yet, every load-bearing constraint is UNKNOWN and the
    # fold must be UNKNOWN -- never SATISFIED. This is asserted rather than
    # assumed: a pre-observation fold that came back satisfied would mean the
    # pipeline could accept a world before looking at one.
    pre_fold = K.fold_acceptance([(c, tri.UNKNOWN) for c in load_bearing])
    stages.append({
        "stage": "pre_observation_fold",
        "status": STAGE_OK if pre_fold == tri.UNKNOWN else STAGE_FAILED,
        "fold": pre_fold,
        "detail": ("with nothing observed, acceptance folds to {} -- a fold of "
                   "SATISFIED here would mean the pipeline can accept a world "
                   "before observing one".format(pre_fold)),
    })

    failed = [s for s in stages if s["status"] == STAGE_FAILED]
    return {
        "report_type": REPORT_TYPE,
        "consumer_id": consumer_id,
        "adapter_id": adapter_record.get("adapter_id"),
        "request_id": request.get("request_id"),
        "caller_originated": ADP.is_caller_originated(adapter_record),
        "profile_shape": {
            "game_type": profile.get("game_type"),
            "visual_language": profile.get("visual_language"),
            "camera_mode": (profile.get("camera_metrics") or {}).get("camera_mode"),
            "locomotion_modes": profile.get("locomotion_modes"),
            "extent_m2": (request.get("environment") or {}).get("extent_m2"),
            "density_class": (request.get("population") or {}).get("density_class"),
            "rollback_granularity": (policy.get("rollback") or {}).get(
                "rollback_granularity"),
            "unknown_handling": criteria.get("unknown_handling"),
        },
        "constraint_classes": dict(sorted(by_class.items())),
        "load_bearing_count": len(load_bearing),
        "stages": stages,
        "stages_failed": len(failed),
        "green": not failed,
    }


# =========================================================================== #
# --preview: the pre-mutation artifact bundle
# =========================================================================== #

# The runner owns the registry. Core must not ship a provider list -- a
# capability catalogue is a deployment fact, not a Core invariant -- and the
# consumer must not supply one, because a caller choosing its own provider is a
# caller choosing its own side effects.
#
# BOTH declarations describe WHAT A PROVIDER DOES WHEN IT RUNS. Neither is an
# attestation that it is installed or runnable here: availability is unobserved
# in preview exactly like everything else, and the report says so under
# `provider_availability`. Declaring `requirements=[]` is therefore not a claim
# that these providers need nothing -- it is the absence of a REQUIREMENT
# GATE, kept out because a gate the preview cannot honestly measure would
# resolve UNKNOWN and make every provider unselectable, turning "we have not
# looked" into "no provider exists".
PROVIDER_EDITOR_SINK = "unreal_editor_mutation_sink"
PROVIDER_SCENE_OBSERVER = "scene_observation_bridge"


def _editor_sink_declaration():
    """The provider `pipeline/run_wfcore_transaction.py` actually drives.

    Its id and rollback mode are that runner's constants (``PROVIDER_ID`` /
    ``ROLLBACK_MODE``); until now nothing registered it, so no plan could ever
    select the one sink WorldForge really has. Registering it here is what makes
    a planned step name a provider that exists on the other side of the boundary
    rather than a fixture.
    """
    d = PB._example_provider_declaration(
        provider_id=PROVIDER_EDITOR_SINK,
        capabilities=[PB.CAP_EDITOR_AUTHORING],
        requirements=[],
        side_effects=[PB._example_side_effect(
            effect_id="eff_editor_persistent_write",
            effect_kind=PB.EFFECT_PERSISTENT_ASSET,
            scope="content.authored_assets",
            reversible=True,
            detail="writes actors and packages inside the step's declared "
                   "mutation bound; undone by the compensating inverse the "
                   "sink records per mutation")],
        # An editor session is not seed-reproducible: the same request run twice
        # against two editor states does not produce byte-identical output.
        # Claiming DET_SEEDED here would be the cheapest lie in the file.
        determinism=PB.DET_ENV_DEPENDENT,
        rollback=PB.ROLLBACK_COMPENSATING,   # run_wfcore_transaction.ROLLBACK_MODE
        outputs=["authored_asset_set", "operation_manifest"],
        evidence=["operation_manifest", "raw_observation_log"],
        limitations=[PB._example_limitation(
            limitation_id="lim_requires_editor_session",
            limitation_kind="platform",
            detail="runs only inside an UnrealEditor-Cmd session; whether one "
                   "is available here is NOT observed by a preview")],
        description="the near/far side pair in tools/unreal/wfcore_unreal_sink.py",
    )
    # WF1233 guards the DET_SEEDED claim, not the downgrade -- but a
    # determinism_evidence key left behind after downgrading still ASSERTS a
    # proof for a claim no longer being made, so it goes.
    d.pop("determinism_evidence", None)
    return d


def _scene_observer_declaration():
    """A provider that measures and changes nothing. Mirrors the planning fixture."""
    d = PB._example_provider_declaration(
        provider_id=PROVIDER_SCENE_OBSERVER,
        capabilities=[PB.CAP_SCENE_OBSERVATION],
        requirements=[],
        side_effects=[PB._example_side_effect(
            effect_id="eff_observation_log",
            effect_kind=PB.EFFECT_EVIDENCE_ONLY,
            scope="evidence.observation_log",
            reversible=True,
            detail="emits a measurement record and changes nothing in the "
                   "world; this is what makes it selectable under the "
                   "provider.mutation_free filter an observation step asks for")],
        determinism=PB.DET_ENV_DEPENDENT,
        rollback=PB.ROLLBACK_NONE,   # nothing to roll back; nothing was changed
        outputs=["observation_set", "operation_manifest"],
        evidence=["raw_observation_log", "operation_manifest"],
        limitations=[PB._example_limitation(
            limitation_id="lim_observation_coverage",
            limitation_kind="coverage_unknown",
            detail="which of a consumer's constraints it can measure is not "
                   "established until it runs")],
        description="reads scene state into observed-world fields",
    )
    d.pop("determinism_evidence", None)
    return d


def _build_registry():
    """Build and populate the capability registry. Returns (registry, checks).

    ``register`` never raises -- an invalid declaration is simply not stored --
    so the checks are returned and folded into a stage. A registry that silently
    dropped a provider would surface later as WF1228 "no provider for
    capability", which reads as a missing capability rather than a rejected
    declaration.
    """
    reg = PR.CapabilityRegistry()
    checks = []
    for decl in (_editor_sink_declaration(), _scene_observer_declaration()):
        for (name, ok, detail, code) in reg.register(decl, strict=True):
            checks.append(("{}::{}".format(decl["provider_id"], name), ok,
                           detail, code))
    return reg, checks


# --------------------------------------------------------------------------- #
# 2. the normalized desired state
# --------------------------------------------------------------------------- #
def _desired_world_from_request(request):
    """Typed desired world from the consumer's request. Returns (model, gaps).

    A straight re-typing: landmarks become landmarks, required affordances
    become gameplay anchors, the stated environment becomes environmental state.
    Nothing is added that the consumer did not say.

    ``gaps`` records consumer intent that has NO expressible form in the typed
    model. The one that always fires is population: the consumer states a
    density CLASS and a set of roles, never a target_count, and ``desired_world``
    requires target_count to be a non-negative integer. Inventing one would put
    a fabricated number on the intent side of a subtraction -- and a budget
    ceiling is not a target, so the instance budget cannot stand in for it
    either. The groups are therefore omitted and the omission is reported, which
    is the honest-unknown-over-fabricated-zero rule applied to authored intent.
    """
    gaps = []
    landmarks = [
        {"landmark_id": lm["landmark_id"],
         "role": lm["role"],
         "intent": lm.get("significance")
         or "declared by the consumer's request; no further intent stated"}
        for lm in request.get("semantic_landmarks") or []]

    anchors = [
        {"anchor_id": a["affordance_id"],
         "role": a["affordance_kind"],
         "required": bool(a["required"])}
        for a in request.get("gameplay_affordances") or []]

    env = request.get("environment") or {}
    states = [
        {"state_id": "state_relief", "state_dimension": "relief_class",
         "state_value": env.get("relief_class")},
        {"state_id": "state_lighting", "state_dimension": "lighting_condition",
         "state_value": env.get("lighting_condition")},
        {"state_id": "state_extent", "state_dimension": "extent_m2",
         "state_value": env.get("extent_m2")},
    ]

    pop = request.get("population") or {}
    for role in pop.get("population_roles") or []:
        gaps.append({
            "consumer_intent": "population role {!r} at density_class {!r}".format(
                role, pop.get("density_class")),
            "not_expressible_as": "desired_world.population[].target_count",
            "reason": "the consumer states a density CLASS, never a count. "
                      "target_count must be a non-negative integer, and there "
                      "is no honest integer here: a fabricated one would cancel "
                      "a difference the planner needed to see, and the instance "
                      "BUDGET is a ceiling, not a target",
        })

    # Reachability the consumer actually declared, expressed as the relation the
    # typed model has for it. The entry landmark is the one the consumer gave
    # role "entry"; without one there is nothing to be reachable FROM, so the
    # relations are omitted rather than anchored to an arbitrary landmark.
    entry = next((lm["landmark_id"] for lm in request.get("semantic_landmarks") or []
                  if lm.get("role") == "entry"), None)
    relations = []
    if entry is not None:
        for lm in request.get("semantic_landmarks") or []:
            if lm.get("must_be_reachable") and lm["landmark_id"] != entry:
                relations.append({
                    "relation_id": "rel_reach_" + lm["landmark_id"],
                    "relation": DW.REACHABLE_FROM,
                    "subject_ref": lm["landmark_id"],
                    "object_ref": entry,
                })
    else:
        gaps.append({
            "consumer_intent": "must_be_reachable flags on the declared landmarks",
            "not_expressible_as": "desired_world.spatial_relations[]",
            "reason": "the request declares no landmark with role 'entry', so "
                      "there is no stated origin for reachability",
        })

    model = {
        # The world's identity is the address the CONSUMER named. Authored
        # intent, which is what a desired world is; never read back as a
        # measurement.
        #
        # ``revision_target`` and ``revision`` are DIFFERENT THINGS and were
        # conflated here until the first real caller exposed it. The target is
        # WHAT is being revised -- a package path. The revision is WHICH
        # revision of that world identity -- a non-negative integer used to
        # match a desired model against an observed one. Assigning the path to
        # the integer made the pair unmatchable, and no shipped demonstration
        # could surface it: both use request_kind="new_world", so
        # revision_target is absent and the `or 0` fallback always fired.
        #
        # A revision request therefore addresses its TARGET as the world id, and
        # the revision number stays 0 until something actually counts revisions.
        "world_id": request.get("revision_target") or request.get("subject"),
        "request_id": request.get("request_id"),
        "revision": 0,
        "semantic_landmarks": landmarks,
        "gameplay_anchors": anchors,
        "population": [],
        "environmental_state": states,
        "spatial_relations": relations,
        "created_by": "pipeline.run_consumer_flow",
        "schema_version": DW.RT_DESIRED_WORLD,
        "report_type": DW.RT_DESIRED_WORLD,
    }
    return model, gaps


# --------------------------------------------------------------------------- #
# 3. the observed world -- honestly empty
# --------------------------------------------------------------------------- #
PREVIEW_NOT_OBSERVED = (
    "a --preview run performs no observation pass: no world was bound and no "
    "collector ran, so this field has no measurement behind it")


def _unobserved_world():
    """An observed world in which NOTHING was observed. The honest shape.

    Every field is ``not_observed`` with ``value=None``; there are no operations
    and no evidence entries, because none ran and none exist. The model is built
    through the sanctioned constructors rather than as a literal so the
    provenance/value pairing cannot drift, and it is validated in the report --
    an honest document must still be a LEGAL one, or "we observed nothing" would
    be indistinguishable from "we emitted a malformed record".

    ``world_identity`` is not_observed too, and that is the load-bearing choice.
    A measured identity here would need an operation with ``ok=True`` and a
    resolving evidence ref, i.e. a fabricated operation and a fabricated
    artifact -- and it would let reconcile proceed against a world nobody bound.
    """
    model = {
        "world_identity": OW.not_observed(PREVIEW_NOT_OBSERVED),
        "observation_operations": [],
        "evidence_index": {},
        "created_by": "pipeline.run_consumer_flow",
        "schema_version": OW.RT_OBSERVED_WORLD,
        "report_type": OW.RT_OBSERVED_WORLD,
    }
    for section in OW.OBSERVED_SECTIONS:
        model[section] = {
            OW.ENUMERATION_KEY: OW.not_observed(PREVIEW_NOT_OBSERVED),
            OW.ENTITIES_KEY: {},
        }
    return model


def _observation_census(observed):
    """Prove field-by-field that nothing in the model is backed.

    Reported rather than asserted in a comment: "the preview observed nothing"
    is exactly the claim a reader should not have to take on trust, and
    ``field_evidence`` is Core's own answer to it.
    """
    rows = []
    for path, field in OW.iter_fields(observed):
        rows.append({
            "path": path,
            "provenance": field.get("provenance"),
            "value_is_null": field.get("value") is None,
            "backed": OW.is_backed(field),
            "field_evidence": OW.field_evidence(field),
        })
    return rows


# --------------------------------------------------------------------------- #
# 5. planning -- two analyses, never conflated
# --------------------------------------------------------------------------- #
# `planning.synth` states the analysis it needs as a LOCAL STRUCTURAL
# EXPECTATION and validates it at the boundary; it deliberately does NOT import
# `analysis.reconcile`, and the two records genuinely differ (reconcile emits no
# analysis_id/request_id/consumer_id/observations, and its findings carry the
# subject inside `comparison`, not at the top level). Bridging them is the
# RUNNER's job -- it is the seam between two Core lanes, and Core owning it
# would couple them. Every field below is copied from a record reconcile
# actually produced, or authored here and labelled as authored.

# Classes an observation step can honestly be planned for: measuring them is
# what would resolve them.
OBSERVABLE_CLASSES = (K.HARD_INVARIANT, K.PROHIBITED_OUTCOME,
                      K.PROTECTED_SEMANTICS, K.BUDGET)

# Classes a world mutation can honestly remedy. PROTECTED_SEMANTICS is absent on
# purpose: its "remedy" would be mutating the very content the consumer
# protected, which the revision policy forbids and should. DECLARED_UNKNOWN is
# absent because the remedy is a DECISION the consumer owes -- routing it to a
# provider would have Core decide something the consumer reserved.
REMEDIABLE_CLASSES = (K.HARD_INVARIANT, K.PROHIBITED_OUTCOME, K.BUDGET)

# Structural mutation verbs per class, intersected with the consumer's own
# permitted_mutations. The policy is an ALLOW-list, so the intersection is the
# authorisation; a class whose verbs the policy permits none of is not
# remediable under that policy and is reported instead of planned.
ENVELOPE_MUTATION_KINDS = {
    K.HARD_INVARIANT: ("add_geometry", "move_geometry"),
    K.PROHIBITED_OUTCOME: ("remove_geometry", "move_geometry"),
    K.BUDGET: ("remove_geometry", "remove_population"),
}


def _load_bearing(request):
    return [c for c in request.get("constraints") or []
            if K.is_acceptance_load_bearing(c)]


def _observation_analysis(request, consumer_id):
    """The analysis of THIS run: every measurable constraint UNKNOWN.

    Authored by the runner because reconcile refused -- and it says UNKNOWN,
    which is the same verdict reconcile itself returns for every one of these
    constraints once a world identity exists but nothing else has been measured.
    Nothing here claims anything about a world.
    """
    findings = []
    for c in _load_bearing(request):
        if c["constraint_class"] not in OBSERVABLE_CLASSES:
            continue
        findings.append({
            "constraint_id": c["constraint_id"],
            "constraint_class": c["constraint_class"],
            "evaluation": tri.UNKNOWN,
            "subject": c["subject"],
            "detail": "nothing has been observed, so this constraint has no "
                      "verdict; the remedy is to measure it, never to change "
                      "the world on its behalf",
            "measure_capability": PB.CAP_SCENE_OBSERVATION,
        })
    return {
        "analysis_id": "analysis_preview_" + str(request.get("request_id")),
        "request_id": request.get("request_id"),
        "consumer_id": consumer_id,
        "observations": {},
        "findings": findings,
        "created_by": "pipeline.run_consumer_flow",
        "notes": "authored by the runner from the consumer's own constraint "
                 "set; every evaluation is UNKNOWN because nothing was observed",
    }


def _envelope_targets(constraint, request):
    """The addresses a remedy for this constraint could reach.

    Derived from ids the CONSUMER authored -- its request ``subject`` for the
    package, and the head of the constraint's own ``subject`` string when that
    head names a landmark or affordance the consumer declared. Nothing is
    invented and nothing is read off a project: these are the addresses the
    consumer NAMED, which is exactly the bound a caller can check against its
    own content.
    """
    package = TD.normalize_target_path(request.get("subject"))
    declared = {lm["landmark_id"] for lm in request.get("semantic_landmarks") or []}
    declared |= {a["affordance_id"] for a in request.get("gameplay_affordances") or []}
    head = str(constraint.get("subject") or "").split(".")[0]
    actors = []
    if head in declared:
        actors.append(TD.normalize_target_path(package + "/" + head))
    return [package], actors


def _envelope_analysis(request, consumer_id, policy):
    """The MAXIMAL-OBLIGATION analysis. Authored, hypothetical, and labelled.

    Every remediable load-bearing constraint is marked VIOLATED -- not because
    anything was measured, but because "all of them are wrong" is the worst case
    and the worst case is what bounds the damage a caller is being asked to
    authorise. Returns (analysis, excluded) so the constraints left out are
    reported rather than disappearing.
    """
    permitted = set(policy.get("permitted_mutations") or [])
    findings, excluded = [], []
    for c in _load_bearing(request):
        klass = c["constraint_class"]
        if klass not in REMEDIABLE_CLASSES:
            excluded.append({
                "constraint_id": c["constraint_id"],
                "constraint_class": klass,
                "reason": ("a protected-semantics violation could only be "
                           "remedied by mutating the content the consumer "
                           "protected, which its own revision policy forbids"
                           if klass == K.PROTECTED_SEMANTICS else
                           "a declared unknown is resolved by a consumer "
                           "DECISION, never by a change to the world"),
                "remedy_owner": c.get("resolution_owner") or "the consumer",
            })
            continue
        kinds = [k for k in ENVELOPE_MUTATION_KINDS[klass] if k in permitted]
        if not kinds:
            excluded.append({
                "constraint_id": c["constraint_id"],
                "constraint_class": klass,
                "reason": "the consumer's revision policy permits none of the "
                          "mutation kinds {} that could remedy this class"
                          .format(list(ENVELOPE_MUTATION_KINDS[klass])),
                "remedy_owner": "the consumer",
            })
            continue
        packages, actors = _envelope_targets(c, request)
        findings.append({
            "constraint_id": c["constraint_id"],
            "constraint_class": klass,
            "evaluation": tri.VIOLATED,
            "subject": c["subject"],
            "detail": "HYPOTHETICAL: bounds what a remedy could reach if this "
                      "constraint were found violated. Nothing has measured it.",
            "remedy_capability": PB.CAP_EDITOR_AUTHORING,
            "expected_changed_packages": packages,
            "expected_changed_actors": actors,
            "mutation_kinds": kinds,
        })
    analysis = {
        "analysis_id": "envelope_" + str(request.get("request_id")),
        "request_id": request.get("request_id"),
        "consumer_id": consumer_id,
        "observations": {},
        "findings": findings,
        "created_by": "pipeline.run_consumer_flow",
        "notes": "AUTHORED MAXIMAL OBLIGATION -- not an observation, and no "
                 "finding in it may be cited as a fact about any world",
    }
    return analysis, excluded


def _synthesis_stage(name, analysis, registry, policy, basis, observational):
    """Run synthesis and fold the result into a reportable record.

    ``unplannable`` is reported as a FAILED stage: synthesis refuses whole
    rather than dropping a finding, so an unplannable result means something the
    caller asked for cannot be done at all -- which is precisely what a
    pre-mutation bundle exists to surface.
    """
    boundary = SY.validate_analysis_expectation(analysis, strict=True)
    result = SY.synthesize_plan(analysis, registry, policy)
    plan = result.get("plan")
    ok = result["outcome"] in (SY.OUTCOME_PLANNED, SY.OUTCOME_NOTHING_TO_PLAN)
    plan_checks = PL.validate_plan(plan, policy=policy, strict=True) if plan else []
    failing = [(n, d, c) for (n, k, d, c) in list(boundary) + list(plan_checks)
               if not k]
    return {
        "stage": name,
        "status": STAGE_OK if ok and not failing else STAGE_FAILED,
        "basis": basis,
        "not_an_observation": not observational,
        "synthesis_id": result.get("synthesis_id"),
        "outcome": result["outcome"],
        "plan_id": (plan or {}).get("plan_id"),
        "step_count": len(((plan or {}).get("steps")) or []),
        "addresses": result.get("addresses"),
        "observes": result.get("observes"),
        "unresolved": result.get("unresolved"),
        "failure_codes": sorted(set(result.get("failure_codes") or [])
                                | {c for (_n, _d, c) in failing if c}),
        "failures": [{"check": n, "detail": d, "failure_code": c}
                     for (n, d, c) in failing][:12],
        "plan_mutates": bool(plan) and PL.plan_mutates(plan),
        "execution_order": PL.topological_order(plan)[0] if plan else [],
        "plan": plan,
    }, plan


# --------------------------------------------------------------------------- #
# 6-9. selection, bounds, changes, rollback -- all read off produced records
# --------------------------------------------------------------------------- #
def _selection_records(plan):
    """Per step, the selection record the planner attached, plus its rendering.

    ``explain`` takes the whole selection RESULT, so the readable lines and the
    machine-readable record come from the same object -- a rendering that could
    disagree with the record it renders would be worse than none.
    """
    out = []
    for step in (plan or {}).get("steps") or []:
        sel = step.get("selection") or {}
        out.append({
            "step_id": step.get("step_id"),
            "capability": step.get("capability"),
            "selected_provider": step.get("selected_provider"),
            "outcome": sel.get("outcome"),
            "considered": [{"provider_id": e.get("provider_id"),
                            "status": e.get("status"),
                            "eligibility": e.get("eligibility"),
                            "score": e.get("score")}
                           for e in sel.get("considered") or []],
            "ranking": sel.get("ranking"),
            "ambiguous_between": sel.get("ambiguous_between"),
            "explanation": PS.explain(sel),
        })
    return out


def _mutation_bounds(plan):
    """Per step, the bound, lifted through Core's own ``bound_from_step``.

    Routed through delta rather than re-read off the step, because the bound the
    executor will ENFORCE is the one delta derives -- and a preview that showed
    a bound computed some other way would be previewing a different rule than
    the one that runs.
    """
    rows = []
    for step in (plan or {}).get("steps") or []:
        bound = TD.bound_from_step(step)
        checks = TD.validate_mutation_bound(bound, strict=True)
        rows.append({
            "step_id": step.get("step_id"),
            "bound": bound,
            "declares_no_mutation": bound.get("declares_no_mutation", False),
            "bound_is_valid": all(ok for (_n, ok, _d, _c) in checks),
            "bound_failures": [{"check": n, "detail": d, "failure_code": c}
                               for (n, ok, d, c) in checks if not ok][:6],
        })
    return rows


def _expected_changes(bounds):
    """The union of every step's bound, deduplicated and sorted.

    EMPTY IS A RESULT, NOT A GAP. For the preview plan this set is empty because
    every step is an observation step, and that emptiness is the machine-checkable
    form of "this run mutates nothing".
    """
    packages, actors = set(), set()
    for row in bounds:
        packages |= set(row["bound"].get("allowed_packages") or [])
        actors |= set(row["bound"].get("allowed_actors") or [])
    return {
        "expected_changed_packages": sorted(packages),
        "expected_changed_actors": sorted(actors),
        "total": len(packages) + len(actors),
        "mutates_nothing": not packages and not actors,
    }


def _rollback_actions(plan, registry):
    """The compensating actions each selected provider declares it can take.

    Read off the PROVIDER DECLARATION, not off the step: what can be undone is a
    property of the provider, and a step cannot grant itself a reversibility its
    provider never claimed. An irreversible effect is listed separately and
    never netted against the reversible ones -- a caller deciding whether to
    permit a run needs the irreversible column on its own.
    """
    rows = []
    for step in (plan or {}).get("steps") or []:
        pid = step.get("selected_provider")
        decl = registry.get(pid) or {}
        effects = decl.get("side_effects") or []
        rows.append({
            "step_id": step.get("step_id"),
            "provider_id": pid,
            "provider_rollback_mode": decl.get("rollback"),
            "step_rollback": step.get("rollback"),
            "rollback_capable": decl.get("rollback") in PB.ROLLBACK_CAPABLE,
            "compensating_actions": [
                {"effect_id": e.get("effect_id"),
                 "effect_kind": e.get("effect_kind"),
                 "scope": e.get("scope"),
                 "compensation": "undo {} within {}".format(
                     e.get("effect_kind"), e.get("scope")),
                 "detail": e.get("detail")}
                for e in effects if e.get("reversible") is True],
            "irreversible_effects": [
                {"effect_id": e.get("effect_id"),
                 "effect_kind": e.get("effect_kind"),
                 "scope": e.get("scope"),
                 "detail": e.get("detail")}
                for e in effects if e.get("reversible") is not True],
        })
    return rows


# --------------------------------------------------------------------------- #
# 10. what acceptance will require, and the assertion that it is not met
# --------------------------------------------------------------------------- #
def _acceptance_preview(criteria, request):
    """The evidence acceptance will demand, and the verdict with none supplied.

    ``evaluate_acceptance`` is called with no delta and no evidence because
    there IS no delta and no evidence. It refuses, and the refusal is the point:
    the verdict is UNKNOWN, never satisfied.
    """
    reqs = criteria.get("evaluation_requirements") or []
    by_id = {c["constraint_id"]: c for c in request.get("constraints") or []}
    required = [{
        "constraint_id": r.get("constraint_id"),
        "constraint_class": (by_id.get(r.get("constraint_id")) or {}).get(
            "constraint_class"),
        "evidence_kind": r.get("evidence_kind"),
        "evaluator": r.get("evaluator"),
        "supplied_by_this_preview": False,
    } for r in reqs]

    result = EV.evaluate_acceptance(criteria, None, [], None)
    load_bearing = _load_bearing(request)
    fold = K.fold_acceptance([(c, tri.UNKNOWN) for c in load_bearing])
    return {
        "stage": "preview_acceptance",
        "status": (STAGE_OK
                   if result["acceptance_verdict"] != tri.SATISFIED
                   and result["outcome"] != EV.OUTCOME_ACCEPTED
                   and fold != tri.SATISFIED
                   else STAGE_FAILED),
        "unknown_handling": criteria.get("unknown_handling"),
        "required_evidence": required,
        "required_evidence_count": len(required),
        "evidence_supplied_count": 0,
        "outcome": result["outcome"],
        "acceptance_verdict": result["acceptance_verdict"],
        "accepted": result["accepted"],
        "refusal_reason": result["refusal_reason"],
        "failure_codes": result["failure_codes"],
        "pre_observation_fold": fold,
        "detail": "acceptance was asked to judge a run with no delta and no "
                  "evidence, and refused. A preview that came back {} would "
                  "mean the pipeline can accept a world it has never looked at"
                  .format(tri.SATISFIED),
    }


# --------------------------------------------------------------------------- #
# the bundle
# --------------------------------------------------------------------------- #
def run_preview(consumer_id):
    """Produce the pre-mutation artifact bundle. Mutates NOTHING."""
    mod = import_consumer(consumer_id)
    adapter_record = mod.adapter()
    request = mod.request()
    policy = mod.policy()
    criteria = mod.criteria()

    stages = []

    # --- 1. caller provenance ------------------------------------------------ #
    # The run claims exactly what the adapter declares. Claiming more is WF1288,
    # and the claim is checked rather than assumed so the label on this bundle
    # is the adapter's admission and not the runner's preference.
    declared = ADP.origination_of(adapter_record)
    prov_checks = ADP.validate_run_provenance(adapter_record, declared)
    prov = _stage("caller_provenance", prov_checks)
    prov.update({
        "claimed_origination": declared,
        "provenance_verdict": ADP.caller_provenance_verdict(adapter_record),
        "caller_originated": ADP.is_caller_originated(adapter_record),
        "detail": "this bundle may not be presented as a caller's request "
                  "unless the adapter itself declares a caller origination",
    })
    stages.append(prov)

    # --- 2. desired state ---------------------------------------------------- #
    desired, gaps = _desired_world_from_request(request)
    stages.append(_stage("desired_world", DW.validate_desired_world(
        desired, strict=True)))

    # --- 3. observed evidence: nothing ---------------------------------------- #
    observed = _unobserved_world()
    obs_stage = _stage("observed_world", OW.validate_observed_world(
        observed, strict=True))
    census = _observation_census(observed)
    obs_stage.update({
        "fields": len(census),
        "backed_fields": sum(1 for r in census if r["backed"]),
        "detail": "every field is unbacked; the model is VALID and observes "
                  "nothing, which are two separate claims and both are checked",
    })
    if obs_stage["backed_fields"]:
        obs_stage["status"] = STAGE_FAILED
    stages.append(obs_stage)

    # --- 4. reconcile: the refusal is the artifact ---------------------------- #
    analysis = RC.reconcile(desired, observed, request,
                            bindings={}, measurements={})
    an_checks = RC.validate_constraint_analysis(analysis, strict=True)
    an_stage = _stage("constraint_analysis", an_checks)
    an_stage.update({
        "reconciled": analysis["reconciled"],
        "same_world": analysis["same_world"],
        "acceptance_verdict": analysis["acceptance_verdict"],
        "refusal_reason": analysis["refusal_reason"],
        "finding_count": len(analysis["findings"]),
        "satisfied": analysis["satisfied"],
        "violated": analysis["violated"],
        "unknown": analysis["unknown"],
        "analysis_failure_codes": analysis["failure_codes"],
        "detail": "reconcile REFUSED: with no measured world identity nothing "
                  "establishes that the observation is of the world this "
                  "request is about. Zero findings and an UNKNOWN verdict are "
                  "the correct output, not a degraded one",
    })
    # A preview that reconciled, or that produced a violation, would mean
    # something was measured. Neither may happen here.
    if analysis["reconciled"] or analysis["violated"] \
            or analysis["acceptance_verdict"] == tri.SATISFIED:
        an_stage["status"] = STAGE_FAILED
    stages.append(an_stage)

    # --- registry ------------------------------------------------------------- #
    registry, reg_checks = _build_registry()
    reg_stage = _stage("provider_registry", reg_checks)
    reg_stage.update({
        "provider_ids": list(registry.provider_ids()),
        "capability_index": {k: list(v) for k, v in
                             sorted(registry.capability_index().items())},
        "collisions": {k: list(v) for k, v in registry.collisions().items()},
        "provider_availability": tri.UNKNOWN,
        "detail": "these are capability DECLARATIONS, not attestations that "
                  "either provider is installed or runnable; availability is "
                  "unobserved in a preview like everything else",
    })
    stages.append(reg_stage)

    # --- 5-9. the two plans --------------------------------------------------- #
    obs_an = _observation_analysis(request, consumer_id)
    next_stage, next_plan = _synthesis_stage(
        "preview_plan", obs_an, registry, policy,
        basis="unknown_findings_from_this_run", observational=True)
    stages.append(next_stage)

    env_an, excluded = _envelope_analysis(request, consumer_id, policy)
    env_stage, env_plan = _synthesis_stage(
        "mutation_envelope", env_an, registry, policy,
        basis="authored_maximal_obligation", observational=False)
    env_stage["excluded_constraints"] = excluded
    stages.append(env_stage)

    next_bounds = _mutation_bounds(next_plan)
    env_bounds = _mutation_bounds(env_plan)
    next_changes = _expected_changes(next_bounds)
    env_changes = _expected_changes(env_bounds)

    # The claim the whole mode rests on, restated as a check: the plan this run
    # would actually execute must reach nothing.
    stages.append({
        "stage": "preview_mutates_nothing",
        "status": (STAGE_OK if next_changes["mutates_nothing"]
                   and not next_stage["plan_mutates"] else STAGE_FAILED),
        "expected_changes": next_changes,
        "plan_mutates": next_stage["plan_mutates"],
        "detail": "the plan this run would execute next declares an EMPTY "
                  "mutation bound, because nothing has been measured and "
                  "therefore nothing has been shown to need changing",
    })

    # --- 10. acceptance ------------------------------------------------------- #
    acc = _acceptance_preview(criteria, request)
    stages.append(acc)

    failed = [s for s in stages if s["status"] == STAGE_FAILED]
    return {
        "report_type": PREVIEW_REPORT_TYPE,
        "mode": "preview",
        "mutated_anything": False,
        "consumer_id": consumer_id,
        "adapter_id": adapter_record.get("adapter_id"),
        "request_id": request.get("request_id"),
        "caller_originated": ADP.is_caller_originated(adapter_record),
        "artifacts": {
            "caller_provenance": prov,
            "desired_world": {"model": desired,
                              "unexpressible_intent": gaps},
            "observed_evidence": {"model": observed,
                                  "field_census": census},
            "constraint_analysis": analysis,
            "preview_plan": next_stage["plan"],
            "mutation_envelope": {
                "basis": "authored_maximal_obligation",
                "not_an_observation": True,
                "plan": env_stage["plan"],
                "excluded_constraints": excluded,
            },
            "provider_selection": {
                "preview_plan": _selection_records(next_plan),
                "mutation_envelope": _selection_records(env_plan),
            },
            "mutation_bounds": {
                "preview_plan": next_bounds,
                "mutation_envelope": env_bounds,
            },
            "expected_changes": {
                "preview_plan": next_changes,
                "mutation_envelope": env_changes,
            },
            "rollback_actions": {
                "preview_plan": _rollback_actions(next_plan, registry),
                "mutation_envelope": _rollback_actions(env_plan, registry),
            },
            "acceptance_requirements": acc,
        },
        "preview_acceptance_verdict": acc["acceptance_verdict"],
        "preview_acceptance_outcome": acc["outcome"],
        "stages": stages,
        "stages_failed": len(failed),
        "green": not failed,
    }


def _print_preview(report):
    a = report["artifacts"]
    print("consumer preview -- {}".format(report["consumer_id"]))
    print("  request           : {}".format(report["request_id"]))
    print("  caller-originated : {}".format(report["caller_originated"]))
    print("  mutated anything  : {}".format(report["mutated_anything"]))
    print("")
    print("  ARTIFACT BUNDLE")
    print("   1 caller provenance   : verdict={} claimed={}".format(
        a["caller_provenance"]["provenance_verdict"],
        a["caller_provenance"]["claimed_origination"]))
    print("   2 desired state       : {} landmarks, {} anchors, {} states, "
          "{} relations ({} intent gap(s))".format(
              len(a["desired_world"]["model"]["semantic_landmarks"]),
              len(a["desired_world"]["model"]["gameplay_anchors"]),
              len(a["desired_world"]["model"]["environmental_state"]),
              len(a["desired_world"]["model"]["spatial_relations"]),
              len(a["desired_world"]["unexpressible_intent"])))
    census = a["observed_evidence"]["field_census"]
    print("   3 observed evidence   : {} field(s), {} backed, all {}".format(
        len(census), sum(1 for r in census if r["backed"]),
        sorted({r["provenance"] for r in census})))
    an = a["constraint_analysis"]
    print("   4 constraint analysis : reconciled={} same_world={} verdict={} "
          "findings={}".format(an["reconciled"], an["same_world"],
                               an["acceptance_verdict"], len(an["findings"])))
    for name in ("preview_plan", "mutation_envelope"):
        st = next(s for s in report["stages"] if s["stage"] == name)
        print("   5 plan [{:17}]: outcome={} steps={} mutates={}".format(
            name, st["outcome"], st["step_count"], st["plan_mutates"]))
    for name in ("preview_plan", "mutation_envelope"):
        for row in a["provider_selection"][name]:
            print("   6 selection [{:17}]: {} -> {}".format(
                name, row["step_id"], row["selected_provider"]))
    for name in ("preview_plan", "mutation_envelope"):
        ch = a["expected_changes"][name]
        print("   7/8 bounds [{:17}]: {} package(s) {} actor(s) "
              "mutates_nothing={}".format(
                  name, len(ch["expected_changed_packages"]),
                  len(ch["expected_changed_actors"]), ch["mutates_nothing"]))
        for pkg in ch["expected_changed_packages"]:
            print("          package  {}".format(pkg))
        for act in ch["expected_changed_actors"]:
            print("          actor    {}".format(act))
    rb = a["rollback_actions"]["mutation_envelope"]
    print("   9 rollback            : {} step(s), modes {}".format(
        len(rb), sorted({r["provider_rollback_mode"] for r in rb}) or ["-"]))
    acc = a["acceptance_requirements"]
    print("  10 acceptance evidence : {} required, {} supplied -> outcome={} "
          "verdict={}".format(acc["required_evidence_count"],
                              acc["evidence_supplied_count"],
                              acc["outcome"], acc["acceptance_verdict"]))
    print("")
    for s in report["stages"]:
        print("  [{:6}] {:32} {}".format(
            s["status"].upper(), s["stage"],
            ("codes " + ",".join(s["failure_codes"]))
            if s.get("failure_codes") else ""))
        for f in s.get("failures", [])[:3]:
            print("           - {}: {}".format(f["check"], f["detail"][:110]))
    print("")
    print("  PREVIEW {}".format("GREEN" if report["green"] else "RED"))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--consumer-path", action="append", default=[],
                   metavar="DIR",
                   help="directory to prepend to sys.path before importing the "
                        "consumer; repeatable. A caller in its OWN repository "
                        "passes its root here and names its module in full via "
                        "--consumer.")
    p.add_argument("--consumer", required=True,
                   help="consumer id -- a package under tools/consumers/")
    p.add_argument("--json", action="store_true")
    p.add_argument("--preview", action="store_true",
                   help="produce the pre-mutation artifact bundle; mutate nothing")
    p.add_argument("--out", default=None, help="write the JSON report here")
    args = p.parse_args(argv)

    # Put the caller's own root on the path BEFORE importing its module. Order is
    # preserved as given so a caller can shadow deliberately; nothing is silently
    # deduplicated away, because a path that appears twice is the caller's
    # business and not this runner's to tidy.
    for d in args.consumer_path:
        d = os.path.abspath(d)
        if not os.path.isdir(d):
            print("consumer-path does not exist: {}".format(d))
            return 2
        if d not in sys.path:
            sys.path.insert(0, d)

    report = run_preview(args.consumer) if args.preview \
        else run_consumer(args.consumer)

    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.preview:
        _print_preview(report)
    else:
        print("consumer flow -- {}".format(report["consumer_id"]))
        print("  request           : {}".format(report["request_id"]))
        print("  caller-originated : {}".format(report["caller_originated"]))
        sh = report["profile_shape"]
        print("  profile           : {} / {} / {} / {}".format(
            sh["game_type"], sh["visual_language"], sh["camera_mode"],
            sh["rollback_granularity"]))
        print("  extent m2         : {}   density: {}".format(
            sh["extent_m2"], sh["density_class"]))
        print("  constraints       : {}".format(report["constraint_classes"]))
        print("")
        for s in report["stages"]:
            print("  [{:6}] {:32} {}".format(
                s["status"].upper(), s["stage"],
                ("codes " + ",".join(s["failure_codes"]))
                if s.get("failure_codes") else ""))
            for f in s.get("failures", [])[:3]:
                print("           - {}: {}".format(f["check"], f["detail"][:110]))
        print("")
        print("  FLOW {}".format("GREEN" if report["green"] else "RED"))

    # A satisfied preview acceptance is a hard non-zero exit even if every stage
    # somehow passed: it is the one result that must never be able to leave this
    # process looking like a success.
    if args.preview and report.get("preview_acceptance_verdict") == tri.SATISFIED:
        print("REFUSED: preview acceptance came back {!r}; the pipeline cannot "
              "accept a world it has never observed".format(tri.SATISFIED))
        return 2

    return 0 if report["green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
