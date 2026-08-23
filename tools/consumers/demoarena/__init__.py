#!/usr/bin/env python3
"""demoarena -- a WorldForge-authored DEMONSTRATION consumer: top-down tactical arena.

WHAT THIS IS, STATED PLAINLY
----------------------------
This is NOT a real importing game. WorldForge wrote it. Its purpose is to exercise
the Core flow end to end and, paired with ``demoexpanse``, to demonstrate that a
substantially different consumer profile drives that same flow with no change to
``tools/wfcore/``.

Its ``provenance.origination`` is ``worldforge_authored_demonstration``, and
``adapter.is_caller_originated()`` returns False for it. A run driven by this
adapter must never be labelled caller-originated -- WorldForge presenting its own
request as a caller's is WF1288, and it is the one error that makes every
downstream result meaningless while looking perfect: the evidence is real, it just
answers a question nobody asked.

WHY THIS PROFILE, AND WHY IT IS THE OPPOSITE OF demoexpanse
-----------------------------------------------------------
A second consumer only proves something if it stresses different parts of Core.
Two profiles that differ by a rename would pass identically and prove nothing. So
these two disagree on every axis that changes what Core must do:

    axis                demoarena (here)        demoexpanse
    ------------------- ----------------------- ------------------------
    game type           arena                   narrative_exploration
    camera              top_down, ortho-ish     first_person
    visual language     graphic_flat            photoreal
    extent              small, bounded          large, open
    population          dense cover             sparse landmarks
    locomotion          walk + crouch only      walk/sprint/climb/swim
    hard invariants     cover density,          sightline reach,
                        firing-lane symmetry    traversal reachability
    protected content   the arena boundary      the established skyline
    rollback            per_mutation            whole_revision

The consequence that matters: a top-down arena cares about DENSITY and SYMMETRY
over a small bounded area, while first-person exploration cares about SIGHTLINES
and REACHABILITY over a large one. Those exercise different constraint classes and
different provider capabilities, which is the point.
"""

from typing import Any, Dict

from wfcore import constraints as K
from wfcore.contracts import acceptance_criteria as ACR
from wfcore.contracts import asset_catalog as AC
from wfcore.contracts import consumer_profile as CP
from wfcore.contracts import revision_policy as RP
from wfcore.contracts import world_request as WR

from .. import adapter as ADP

CONSUMER_ID = "demoarena"

DEMO_STATEMENT = (
    "demoarena is a WorldForge-authored DEMONSTRATION consumer, not a real "
    "importing game. WorldForge authored this profile, catalog, request, policy "
    "and criteria itself in order to exercise the Core flow and to prove that a "
    "substantially different consumer needs no change to WorldForge Core. No "
    "external caller asked for any of it, and no run driven by this adapter may "
    "be labelled caller-originated.")


def adapter() -> Dict[str, Any]:
    """The thin adapter. Exposes the project; contains no generation logic."""
    return ADP._example_adapter(
        adapter_id="adapter_demoarena",
        consumer_id=CONSUMER_ID,
        provenance={
            "origination": ADP.ORIGINATION_WORLDFORGE_DEMO,
            "authored_by": "WorldForge",
            "statement": DEMO_STATEMENT,
        },
        project_identity={
            "engine_version": "5.8",
            "project_identifier": "demoarena_project",
            "subject_root": "consumer://demoarena/arena_floor",
        },
        semantic_landmarks=[
            {"landmark_id": "lm_arena_entry", "role": "entry",
             "must_be_reachable": True},
            {"landmark_id": "lm_arena_centre", "role": "objective",
             "must_be_reachable": True},
            {"landmark_id": "lm_arena_boundary", "role": "boundary",
             "must_be_reachable": False},
        ],
        gameplay_anchors=[
            {"anchor_id": "anchor_cover_field", "anchor_kind": "cover",
             "required": True},
            {"anchor_id": "anchor_flank_left", "anchor_kind": "traversal",
             "required": True},
            {"anchor_id": "anchor_flank_right", "anchor_kind": "traversal",
             "required": True},
        ],
        # Low-mobility tactical movement: a short capsule, a shallow walkable
        # slope, and only a step-up hop. These are what make the arena's cover
        # geometry legible from above, so Core must respect them.
        #
        # max_jump_height_cm is a real positive measure, NOT 0. The contract
        # rejects a zero measure on purpose -- an unmeasured quantity arriving as
        # 0 reads downstream as a measurement -- and "this game has no jump" is
        # carried by locomotion_modes, which is where that fact belongs.
        player_metrics={
            "capsule_height_cm": 160.0,
            "capsule_radius_cm": 34.0,
            "eye_height_cm": 145.0,
            "max_step_height_cm": 25.0,
            "max_walk_slope_deg": 30.0,
            "max_jump_height_cm": 40.0,
        },
        camera_metrics={
            "camera_mode": "top_down",
            "horizontal_fov_deg": 40.0,
            "near_clip_cm": 50.0,
            "far_clip_cm": 40000.0,
        },
        approved_catalog_ids=["catalog_demoarena_blockout"],
        protected_identities=["lm_arena_boundary"],
        runtime_state_access={
            "access_kind": "none",
            "detail": "the demonstration exposes no live runtime channel",
        },
        acceptance_hooks=[
            {"constraint_id": "c_cover_density", "evidence_kind": "runtime_observation",
             "hook_reference": "demoarena.probe_cover_density"},
            {"constraint_id": "c_flank_symmetry", "evidence_kind": "runtime_observation",
             "hook_reference": "demoarena.probe_flank_symmetry"},
        ],
    )


def profile() -> Dict[str, Any]:
    return CP.build_consumer_profile(
        consumer_id=CONSUMER_ID,
        engine_identity={"engine_version": "5.8",
                         "project_identifier": "demoarena_project"},
        declared_capabilities=["population.scatter", "navigation.bake"],
        game_type="arena",
        visual_language="graphic_flat",
        locomotion_modes=["walk", "crouch"],
        player_metrics=adapter()["player_metrics"],
        camera_metrics=adapter()["camera_metrics"],
        standing_constraints=[
            K._example_constraint(
                constraint_id="sc_arena_step_clearance",
                constraint_class=K.HARD_INVARIANT,
                subject="navigation.step_height",
                detail="no walkable surface may require a step above 25cm"),
        ],
    )


def catalog() -> Dict[str, Any]:
    return AC.build_asset_catalog(
        catalog_id="catalog_demoarena_blockout",
        consumer_id=CONSUMER_ID,
        entries=[
            AC._example_asset_entry(
                asset_id="asset_arena_cover_block",
                asset_role="modular_geometry",
                authorization="approved"),
            AC._example_asset_entry(
                asset_id="asset_arena_floor_flat",
                asset_role="surface_material",
                authorization="approved"),
            AC._example_asset_entry(
                asset_id="asset_arena_boundary_wall",
                asset_role="static_geometry",
                authorization="approved"),
        ],
    )


def request() -> Dict[str, Any]:
    """The world this consumer wants. Small, bounded, dense, symmetric."""
    return WR.build_world_request(
        request_id="request_demoarena_0001",
        consumer_id=CONSUMER_ID,
        catalog_id="catalog_demoarena_blockout",
        subject="consumer://demoarena/arena_floor",
        request_kind="new_world",
        semantic_landmarks=[
            {"landmark_id": "lm_arena_entry", "role": "entry",
             "must_be_reachable": True,
             "significance": "where both sides enter the arena"},
            {"landmark_id": "lm_arena_centre", "role": "objective",
             "must_be_reachable": True},
        ],
        gameplay_affordances=[
            {"affordance_id": "afford_cover_field", "affordance_kind": "cover",
             "required": True,
             "detail": "cover must be dense enough to cross the arena without "
                       "an unbroken firing lane"},
            {"affordance_id": "afford_flank_routes",
             "affordance_kind": "flanking_route", "required": True},
        ],
        constraints=[
            # HARD: the two invariants that define a tactical arena.
            K._example_constraint(
                constraint_id="c_cover_density",
                constraint_class=K.HARD_INVARIANT,
                subject="afford_cover_field.density_per_100m2",
                detail="cover objects per 100 m^2 must be at least the declared "
                       "minimum, or the arena has no tactical shape"),
            K._example_constraint(
                constraint_id="c_flank_symmetry",
                constraint_class=K.HARD_INVARIANT,
                subject="afford_flank_routes.length_symmetry",
                detail="left and right flanking routes must be within tolerance "
                       "of equal length; asymmetry decides the match before it "
                       "is played"),
            # PROHIBITED: what must not appear.
            K._example_constraint(
                constraint_id="c_no_unbroken_firing_lane",
                constraint_class=K.PROHIBITED_OUTCOME,
                subject="layout.firing_lane",
                detail="no straight unobstructed line may span the arena's full "
                       "diagonal"),
            # PROTECTED: the boundary is the consumer's, not WorldForge's.
            K._example_constraint(
                constraint_id="c_boundary_untouched",
                constraint_class=K.PROTECTED_SEMANTICS,
                subject="layout.arena_boundary",
                detail="the arena boundary defines the competitive space and "
                       "must not be moved or resized",
                protected_ids=["lm_arena_boundary"]),
            # BUDGET + its TOLERANCE.
            K._example_constraint(
                constraint_id="c_arena_instance_budget",
                constraint_class=K.BUDGET,
                subject="population.instance_count",
                detail="total placed instances must stay within the arena budget",
                limit=400, unit="instances"),
            K._example_constraint(
                constraint_id="c_symmetry_tolerance",
                constraint_class=K.TOLERANCE,
                subject="afford_flank_routes.length_symmetry",
                detail="flank lengths may differ by up to this much",
                applies_to="c_flank_symmetry",
                limit=150.0, unit="cm"),
            # SOFT / OPTIMIZATION: must never be able to fail the build.
            K._example_constraint(
                constraint_id="c_prefer_low_silhouette",
                constraint_class=K.SOFT_PREFERENCE,
                subject="visual.silhouette_height",
                detail="prefer cover that reads clearly from a top-down camera",
                weight=2.0),
            K._example_constraint(
                constraint_id="c_minimise_instance_count",
                constraint_class=K.OPTIMIZATION_TARGET,
                subject="population.instance_count",
                detail="fewer instances at equal tactical quality",
                direction=K.MINIMIZE, weight=1.0),
        ],
        population={"density_class": "dense",
                    "population_roles": ["cover_block", "boundary_marker"]},
        environment={"extent_m2": 2500.0,          # small and bounded
                     "relief_class": "flat",
                     "lighting_condition": "overcast"},
    )


def policy() -> Dict[str, Any]:
    """Tight policy: fine-grained rollback, geometry only, boundary protected."""
    return RP.build_revision_policy(
        policy_id="policy_demoarena",
        consumer_id=CONSUMER_ID,
        permitted_mutations=["add_geometry", "remove_geometry", "move_geometry",
                             "add_population", "remove_population",
                             "move_population"],
        protected_content=["lm_arena_boundary"],
        prohibited_mutations=["adjust_terrain_height", "adjust_lighting",
                              "replace_surface_material"],
        rollback={"rollback_required": True,
                  "rollback_granularity": "per_mutation",
                  "max_revision_attempts": 3},
    )


def criteria() -> Dict[str, Any]:
    return ACR.build_acceptance_criteria(
        criteria_id="criteria_demoarena",
        consumer_id=CONSUMER_ID,
        request_id="request_demoarena_0001",
        constraints=[c for c in request()["constraints"]
                     if c["constraint_class"] in K.ACCEPTANCE_LOAD_BEARING],
        # Every load-bearing constraint MUST name what will evaluate it.
        # Without this they fold UNKNOWN forever: the criteria read complete
        # while the pipeline simply never finishes.
        evaluation_requirements=[
            {"constraint_id": "c_cover_density",
             "evidence_kind": "runtime_observation",
             "evaluator": "demoarena.probe_cover_density"},
            {"constraint_id": "c_flank_symmetry",
             "evidence_kind": "runtime_observation",
             "evaluator": "demoarena.probe_flank_symmetry"},
            {"constraint_id": "c_no_unbroken_firing_lane",
             "evidence_kind": "runtime_observation",
             "evaluator": "demoarena.probe_firing_lanes"},
            {"constraint_id": "c_boundary_untouched",
             "evidence_kind": "authoring_time_check",
             "evaluator": "demoarena.compare_boundary_identity"},
            {"constraint_id": "c_arena_instance_budget",
             "evidence_kind": "external_measurement",
             "evaluator": "demoarena.count_instances"},
        ],
        unknown_handling="block_and_request_measurement",
    )
