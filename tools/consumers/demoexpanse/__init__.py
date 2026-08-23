#!/usr/bin/env python3
"""demoexpanse -- a WorldForge-authored DEMONSTRATION consumer: first-person expanse.

WHAT THIS IS, STATED PLAINLY
----------------------------
Not a real importing game. WorldForge wrote it. Its ``provenance.origination`` is
``worldforge_authored_demonstration`` and ``adapter.is_caller_originated()``
returns False, so no run driven by it may be labelled caller-originated (WF1288).

WHY IT EXISTS
-------------
It is the deliberate opposite of ``demoarena``, and its whole job is to be
different enough that passing BOTH means something. Two profiles that differ by a
rename would exercise identical code paths in Core and prove nothing at all; the
proof is only as strong as the distance between the consumers.

Where they disagree, and why each disagreement bites:

  * game type / camera -- ``narrative_exploration`` in ``first_person`` rather than
    an ``arena`` viewed ``top_down``. A first-person eye height makes SIGHTLINES a
    hard invariant; a top-down camera makes silhouette DENSITY one instead.
  * extent -- 4 km^2 of open ground against a 2500 m^2 bounded floor, three orders
    of magnitude apart, which is what stresses budgets and reachability rather
    than symmetry.
  * population -- ``sparse`` landmarks against ``dense`` cover. Opposite ends of
    the density vocabulary, so opposite scatter behaviour.
  * locomotion -- walk/sprint/climb/swim against walk/crouch. Climb and swim mean
    traversal reachability cannot be decided from ground geometry alone.
  * protected content -- the established skyline, not an arena boundary: a
    protected VISUAL relationship rather than a protected extent.
  * rollback -- ``whole_revision`` rather than ``per_mutation``, so the transaction
    layer is exercised at a different granularity.
  * unknown handling -- plain ``block``. This consumer is content to stop and wait
    for a human; ``demoarena`` demands measurement be requested.
"""

from typing import Any, Dict

from wfcore import constraints as K
from wfcore.contracts import acceptance_criteria as ACR
from wfcore.contracts import asset_catalog as AC
from wfcore.contracts import consumer_profile as CP
from wfcore.contracts import revision_policy as RP
from wfcore.contracts import world_request as WR

from .. import adapter as ADP

CONSUMER_ID = "demoexpanse"

DEMO_STATEMENT = (
    "demoexpanse is a WorldForge-authored DEMONSTRATION consumer, not a real "
    "importing game. WorldForge authored this profile, catalog, request, policy "
    "and criteria itself in order to exercise the Core flow and to prove that a "
    "substantially different consumer needs no change to WorldForge Core. No "
    "external caller asked for any of it, and no run driven by this adapter may "
    "be labelled caller-originated.")


def adapter() -> Dict[str, Any]:
    return ADP._example_adapter(
        adapter_id="adapter_demoexpanse",
        consumer_id=CONSUMER_ID,
        provenance={
            "origination": ADP.ORIGINATION_WORLDFORGE_DEMO,
            "authored_by": "WorldForge",
            "statement": DEMO_STATEMENT,
        },
        project_identity={
            "engine_version": "5.8",
            "project_identifier": "demoexpanse_project",
            "subject_root": "consumer://demoexpanse/expanse_region",
        },
        semantic_landmarks=[
            {"landmark_id": "lm_trailhead", "role": "entry",
             "must_be_reachable": True},
            {"landmark_id": "lm_far_ridge", "role": "vista",
             "must_be_reachable": True},
            {"landmark_id": "lm_waystation", "role": "shelter",
             "must_be_reachable": True},
            {"landmark_id": "lm_skyline_profile", "role": "boundary",
             "must_be_reachable": False},
        ],
        gameplay_anchors=[
            {"anchor_id": "anchor_walking_route", "anchor_kind": "traversal",
             "required": True},
            {"anchor_id": "anchor_overlook", "anchor_kind": "vantage",
             "required": True},
        ],
        # A full-height first-person body that can climb and swim. The eye height
        # is load-bearing here in a way it is not for a top-down game: every
        # sightline invariant is measured from it.
        player_metrics={
            "capsule_height_cm": 186.0,
            "capsule_radius_cm": 40.0,
            "eye_height_cm": 172.0,
            "max_step_height_cm": 50.0,
            "max_walk_slope_deg": 50.0,
            "max_jump_height_cm": 110.0,
        },
        camera_metrics={
            "camera_mode": "first_person",
            "horizontal_fov_deg": 103.0,
            "near_clip_cm": 5.0,
            "far_clip_cm": 800000.0,
        },
        approved_catalog_ids=["catalog_demoexpanse_natural"],
        protected_identities=["lm_skyline_profile"],
        runtime_state_access={
            "access_kind": "none",
            "detail": "the demonstration exposes no live runtime channel",
        },
        acceptance_hooks=[
            {"constraint_id": "c_vista_sightline",
             "evidence_kind": "runtime_observation",
             "hook_reference": "demoexpanse.probe_sightline"},
            {"constraint_id": "c_landmark_reachability",
             "evidence_kind": "runtime_observation",
             "hook_reference": "demoexpanse.probe_reachability"},
        ],
    )


def profile() -> Dict[str, Any]:
    return CP.build_consumer_profile(
        consumer_id=CONSUMER_ID,
        engine_identity={"engine_version": "5.8",
                         "project_identifier": "demoexpanse_project"},
        declared_capabilities=["terrain.heightfield", "population.scatter",
                               "navigation.bake", "lighting.timeofday"],
        game_type="narrative_exploration",
        visual_language="photoreal",
        locomotion_modes=["walk", "sprint", "climb", "swim"],
        player_metrics=adapter()["player_metrics"],
        camera_metrics=adapter()["camera_metrics"],
        standing_constraints=[
            K._example_constraint(
                constraint_id="sc_expanse_slope_limit",
                constraint_class=K.HARD_INVARIANT,
                subject="navigation.walk_slope",
                detail="walkable ground must not exceed 50 degrees; steeper "
                       "ground must be reachable by the climb affordance or not "
                       "at all"),
        ],
    )


def catalog() -> Dict[str, Any]:
    return AC.build_asset_catalog(
        catalog_id="catalog_demoexpanse_natural",
        consumer_id=CONSUMER_ID,
        entries=[
            AC._example_asset_entry(
                asset_id="asset_expanse_ground_layer",
                asset_role="terrain_layer",
                authorization="approved"),
            AC._example_asset_entry(
                asset_id="asset_expanse_rock_outcrop",
                asset_role="static_geometry",
                authorization="approved"),
            AC._example_asset_entry(
                asset_id="asset_expanse_canopy",
                asset_role="foliage",
                authorization="approved_with_conditions",
                conditions=["density must not occlude the protected skyline "
                            "profile from the trailhead"]),
            AC._example_asset_entry(
                asset_id="asset_expanse_waystation_kit",
                asset_role="modular_geometry",
                authorization="approved"),
        ],
    )


def request() -> Dict[str, Any]:
    """Large, open, sparse. Sightlines and reachability instead of density."""
    return WR.build_world_request(
        request_id="request_demoexpanse_0001",
        consumer_id=CONSUMER_ID,
        catalog_id="catalog_demoexpanse_natural",
        subject="consumer://demoexpanse/expanse_region",
        request_kind="new_world",
        semantic_landmarks=[
            {"landmark_id": "lm_trailhead", "role": "entry",
             "must_be_reachable": True,
             "significance": "where the player enters the region on foot"},
            {"landmark_id": "lm_far_ridge", "role": "vista",
             "must_be_reachable": True},
            {"landmark_id": "lm_waystation", "role": "shelter",
             "must_be_reachable": True},
        ],
        gameplay_affordances=[
            {"affordance_id": "afford_walking_route",
             "affordance_kind": "traversal", "required": True,
             "detail": "a continuous walkable route from the trailhead to every "
                       "reachable landmark"},
            {"affordance_id": "afford_overlook",
             "affordance_kind": "vantage", "required": True,
             "detail": "at least one position from which the far ridge is "
                       "visible at eye height"},
        ],
        constraints=[
            K._example_constraint(
                constraint_id="c_landmark_reachability",
                constraint_class=K.HARD_INVARIANT,
                subject="afford_walking_route.reachability",
                detail="every landmark flagged must_be_reachable must be "
                       "reachable on foot from the trailhead"),
            K._example_constraint(
                constraint_id="c_vista_sightline",
                constraint_class=K.HARD_INVARIANT,
                subject="afford_overlook.sightline_from_eye_height",
                detail="the far ridge must be visible from the overlook at the "
                       "declared eye height, unoccluded"),
            K._example_constraint(
                constraint_id="c_no_invisible_walls",
                constraint_class=K.PROHIBITED_OUTCOME,
                subject="navigation.invisible_barrier",
                detail="the region must not be bounded by barriers that are "
                       "not visually explained"),
            K._example_constraint(
                constraint_id="c_skyline_untouched",
                constraint_class=K.PROTECTED_SEMANTICS,
                subject="visual.skyline_profile",
                detail="the established skyline silhouette is authored content "
                       "and must not be altered",
                protected_ids=["lm_skyline_profile"]),
            K._example_constraint(
                constraint_id="c_expanse_instance_budget",
                constraint_class=K.BUDGET,
                subject="population.instance_count",
                detail="placed instances across the region",
                limit=25000, unit="instances"),
            K._example_constraint(
                constraint_id="c_sightline_tolerance",
                constraint_class=K.TOLERANCE,
                subject="afford_overlook.sightline_from_eye_height",
                detail="permitted angular occlusion of the ridge silhouette",
                applies_to="c_vista_sightline",
                limit=2.0, unit="degrees"),
            # This consumer honestly does not know its foliage density yet, and
            # says so rather than omitting it -- an omitted constraint reads as
            # "does not matter", an undecided one must block.
            K._example_constraint(
                constraint_id="c_canopy_density_undecided",
                constraint_class=K.DECLARED_UNKNOWN,
                subject="population.canopy_density",
                detail="canopy density has not been decided by the art lead",
                resolution_owner="demoexpanse.art_direction"),
            K._example_constraint(
                constraint_id="c_prefer_natural_silhouettes",
                constraint_class=K.SOFT_PREFERENCE,
                subject="visual.silhouette_naturalism",
                detail="prefer irregular natural silhouettes over repeated forms",
                weight=3.0),
            K._example_constraint(
                constraint_id="c_maximise_traversable_area",
                constraint_class=K.OPTIMIZATION_TARGET,
                subject="navigation.traversable_fraction",
                detail="more of the region walkable is better",
                direction=K.MAXIMIZE, weight=2.0),
        ],
        population={"density_class": "sparse",
                    "population_roles": ["rock_outcrop", "canopy", "waystation"]},
        environment={"extent_m2": 4000000.0,        # 4 km^2, vs the arena's 2500
                     "relief_class": "vertical",
                     "lighting_condition": "bright"},
    )


def policy() -> Dict[str, Any]:
    """Loose policy: terrain and lighting permitted, coarse rollback."""
    return RP.build_revision_policy(
        policy_id="policy_demoexpanse",
        consumer_id=CONSUMER_ID,
        permitted_mutations=["add_geometry", "remove_geometry", "move_geometry",
                             "adjust_terrain_height", "adjust_lighting",
                             "add_population", "remove_population",
                             "adjust_navigation"],
        protected_content=["lm_skyline_profile"],
        prohibited_mutations=["replace_surface_material", "retag_metadata"],
        rollback={"rollback_required": True,
                  "rollback_granularity": "whole_revision",
                  "max_revision_attempts": 5},
    )


def criteria() -> Dict[str, Any]:
    return ACR.build_acceptance_criteria(
        criteria_id="criteria_demoexpanse",
        consumer_id=CONSUMER_ID,
        request_id="request_demoexpanse_0001",
        constraints=[c for c in request()["constraints"]
                     if c["constraint_class"] in K.ACCEPTANCE_LOAD_BEARING],
        evaluation_requirements=[
            {"constraint_id": "c_landmark_reachability",
             "evidence_kind": "runtime_observation",
             "evaluator": "demoexpanse.probe_reachability"},
            {"constraint_id": "c_vista_sightline",
             "evidence_kind": "runtime_observation",
             "evaluator": "demoexpanse.probe_sightline"},
            {"constraint_id": "c_no_invisible_walls",
             "evidence_kind": "human_review",
             "evaluator": "demoexpanse.review_boundaries"},
            {"constraint_id": "c_skyline_untouched",
             "evidence_kind": "authoring_time_check",
             "evaluator": "demoexpanse.compare_skyline_identity"},
            {"constraint_id": "c_expanse_instance_budget",
             "evidence_kind": "external_measurement",
             "evaluator": "demoexpanse.count_instances"},
            # The declared-unknown still needs a named evaluator: it blocks until
            # the consumer resolves it, and the record must say who will.
            {"constraint_id": "c_canopy_density_undecided",
             "evidence_kind": "human_review",
             "evaluator": "demoexpanse.art_direction"},
        ],
        unknown_handling="block",
    )
