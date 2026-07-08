#!/usr/bin/env python3
"""runtime_interaction_contract.py — WorldForge v1.6 RuntimeInteractionActor.

InteractionForge Alpha owns the generated runtime objective actors: the thing a
runtime pawn walks up to and *does something with* to advance a mission. This
module is the strict schema + the canonical verb registry, and the mapping from
the six mission archetypes to their objective verb (brief §"RuntimeInteraction-
Actor"). Owns INTERACTION_VERBS; the taxonomy imports it from here.

A materialized interaction actor is only real if it: has a positive interaction
radius, carries a supported verb, writes a mission state key, emits a runtime
event, and binds a save/load key so completion survives a reload.
"""

from pathlib import Path

from failure_codes import FailureCode
import runtime_schema as RS

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "wf.runtime.interaction_actor.v1"

INTERACTION_GENERATED_REL = "procedural/generated/runtime/interactions"
INTERACTION_CATALOG_REL = "procedural/generated/worldforge_runtime_interaction_catalog.json"
INTERACTION_REPORTS_REL = "procedural/reports/runtime/interactions"
INTERACTION_INVALID_FIXTURES_REL = "tests/fixtures/invalid_runtime_interactions"

# The seven supported v1.6 runtime verbs (brief §"Supported v1.6 verbs").
INTERACTION_VERBS = (
    "activate",
    "disable",
    "recover",
    "survey",
    "clear",
    "restore",
    "extract",
)

# Mission archetype -> objective verb (brief §"Map mission archetypes to verbs").
MISSION_ARCHETYPE_VERBS = {
    "disable_site": "disable",
    "recover_resource": "recover",
    "survey_landmark": "survey",
    "clear_hazard": "clear",
    "restore_power": "restore",
    "extract_cache": "extract",
}

# The runtime event each archetype's objective verb emits on success. Single
# source shared by the scenario generator and the interaction-actor generator so
# the "expected_event" a scenario asserts always matches what its actor emits.
ARCHETYPE_EVENTS = {
    "disable_site": "objective.disabled",
    "recover_resource": "objective.recovered",
    "survey_landmark": "objective.surveyed",
    "clear_hazard": "objective.cleared",
    "restore_power": "objective.restored",
    "extract_cache": "objective.extracted",
}

# The WF_* tag the runtime driver finds the objective actor by, per archetype.
ARCHETYPE_TAGS = {
    "disable_site": "WF_OBJ_DISABLE_TARGET",
    "recover_resource": "WF_OBJ_RECOVER_TARGET",
    "survey_landmark": "WF_OBJ_SURVEY_TARGET",
    "clear_hazard": "WF_OBJ_CLEAR_TARGET",
    "restore_power": "WF_OBJ_RESTORE_TARGET",
    "extract_cache": "WF_OBJ_EXTRACT_TARGET",
}


def event_for_archetype(archetype):
    """Return the success event an archetype's objective verb emits (or None)."""
    return ARCHETYPE_EVENTS.get(archetype)


def state_key_for_archetype(archetype):
    """Return the mission state key an archetype's objective completion writes."""
    return "mission.{}.completed".format(archetype)

REQUIRED_FIELDS = (
    "interaction_actor_id",
    "map_id",
    "mission_id",
    "objective_id",
    "actor_tag",
    "verb",
    "display_label",
    "world_transform",
    "interaction_radius",
    "interaction_duration_seconds",
    "requires_line_of_sight",
    "requires_facing",
    "state_key_written",
    "event_emitted",
    "completion_contribution",
    "save_load_key",
    "collision_profile",
    "visual_marker_id",
)

# Optional-but-known fields (kept out of REQUIRED but allowed under STRICT).
OPTIONAL_FIELDS = (
    "schema_version",
    "biome",
    "mission_archetype",
    "encounter_id",
    "created_by",
    "created_at",
)

ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def verb_for_archetype(archetype):
    """Return the canonical objective verb for a mission archetype (or None)."""
    return MISSION_ARCHETYPE_VERBS.get(archetype)


def validate_interaction_actor(obj, strict=False):
    """Return check tuples (name, ok, detail, code) for one interaction actor."""
    C = FailureCode
    checks = []
    checks += RS.check_required(obj, REQUIRED_FIELDS, C.INTERACTION_ACTOR_SCHEMA_FAILURE)
    checks += RS.check_no_unknown(obj, ALLOWED_FIELDS, C.INTERACTION_ACTOR_SCHEMA_FAILURE, strict)
    checks += RS.check_enum(obj, "verb", INTERACTION_VERBS, C.INTERACTION_VERB_UNSUPPORTED)
    checks += RS.check_transform(obj, "world_transform", C.INTERACTION_ACTOR_SCHEMA_FAILURE)
    # A zero/negative radius means the pawn could never register the interaction.
    checks += RS.check_positive_number(obj, "interaction_radius", C.INTERACTION_RADIUS_INVALID)
    checks += RS.check_positive_number(obj, "interaction_duration_seconds",
                                       C.INTERACTION_ACTOR_SCHEMA_FAILURE, allow_zero=True)
    checks += RS.check_type(obj, "requires_line_of_sight", bool,
                            C.INTERACTION_LINE_OF_SIGHT_FAILURE)
    checks += RS.check_type(obj, "requires_facing", bool, C.INTERACTION_ACTOR_SCHEMA_FAILURE)
    # State + event bindings are what make a completion real, not cosmetic.
    checks += RS.check_type(obj, "state_key_written", str, C.INTERACTION_STATE_KEY_MISSING)
    checks += RS.check_type(obj, "event_emitted", str, C.INTERACTION_EVENT_MISSING)
    checks += RS.check_type(obj, "save_load_key", str, C.INTERACTION_SAVE_LOAD_BINDING_FAILURE)
    checks += RS.check_positive_number(obj, "completion_contribution",
                                       C.INTERACTION_COMPLETION_CONTRIBUTION_FAILURE, allow_zero=True)
    return checks


def _valid_fixture():
    return {
        "schema_version": SCHEMA_VERSION,
        "interaction_actor_id": "int_disable_generator_core_wetland_seed02",
        "map_id": "wetland_mire_basin_reclaimed_seed02",
        "mission_id": "mission_disable_site_wetland_seed02",
        "objective_id": "disable_generator_core",
        "actor_tag": "WF_OBJ_DISABLE_TARGET",
        "verb": "disable",
        "display_label": "Disable Generator Core",
        "world_transform": {"x": 1500.0, "y": 640.0, "z": 96.0, "yaw": 0.0},
        "interaction_radius": 175.0,
        "interaction_duration_seconds": 3.0,
        "requires_line_of_sight": True,
        "requires_facing": True,
        "state_key_written": "mission.disable_site.completed",
        "event_emitted": "objective.disabled",
        "completion_contribution": 1.0,
        "save_load_key": "mission.disable_site.completed",
        "collision_profile": "BlockAllDynamic",
        "visual_marker_id": "WF_MARKER_OBJECTIVE",
    }


if __name__ == "__main__":
    good = validate_interaction_actor(_valid_fixture(), strict=True)
    bad_fixtures = [f for f in good if not f[1]]
    assert not bad_fixtures, "valid fixture failed: {}".format(bad_fixtures)
    broken = _valid_fixture()
    broken["verb"] = "teleport"          # unsupported verb
    broken["interaction_radius"] = 0     # invalid radius
    fails = [f for f in validate_interaction_actor(broken, strict=True) if not f[1]]
    assert any("verb" in f[0] for f in fails), "unsupported verb not caught"
    assert any("interaction_radius" in f[0] for f in fails), "zero radius not caught"
    assert set(MISSION_ARCHETYPE_VERBS.values()) <= set(INTERACTION_VERBS)
    print("OK runtime_interaction_contract self-check: valid passes, "
          "known-bad fails ({} verbs)".format(len(INTERACTION_VERBS)))
