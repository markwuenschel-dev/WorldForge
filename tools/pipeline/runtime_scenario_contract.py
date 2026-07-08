#!/usr/bin/env python3
"""runtime_scenario_contract.py — WorldForge v1.6 RuntimeScenario (hub contract).

A RuntimeScenario is the unit PlaytestForge Gamma executes: it binds one v1.5-
realized map + its mission + encounter + spawn anchor + objective sequence +
required interactions + expected state transitions + the pawn/route/visual-kit it
runs against. This is the hub the other runtime contracts hang off of; it imports
the interaction verb registry rather than restating it, and declares the
VALIDATION_REQUIREMENTS a live run must satisfy. A scenario that allows teleport
success (a non-empty allowed_recovery_modes containing a teleport mode) is a
fake-green vector and is rejected under the coverage/no-fake-green gates.
"""

from pathlib import Path

from failure_codes import FailureCode
import runtime_schema as RS
from runtime_interaction_contract import INTERACTION_VERBS, MISSION_ARCHETYPE_VERBS

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "wf.runtime.scenario.v1"

SCENARIO_GENERATED_REL = "procedural/generated/runtime/scenarios"
SCENARIO_CATALOG_REL = "procedural/generated/worldforge_runtime_scenario_catalog.json"
SCENARIO_MANIFEST_REL = "procedural/generated/worldforge_runtime_scenario_manifest.json"
SCENARIO_REPORTS_REL = "procedural/reports/runtime/scenarios"
SCENARIO_INVALID_FIXTURES_REL = "tests/fixtures/invalid_runtime_scenarios"

# The mission archetypes v1.6 covers (the same six MissionForge archetypes).
MISSION_ARCHETYPES = tuple(MISSION_ARCHETYPE_VERBS.keys())

# Encounter pressure profiles carried through from EncounterForge (v1.4).
ENCOUNTER_PROFILES = ("light_pressure", "standard_pressure")

# The validation requirements a scenario asserts its live run must satisfy.
VALIDATION_REQUIREMENTS = (
    "spawn",
    "possession",
    "navmesh",
    "collision",
    "interaction",
    "state",
    "completion",
    "save_load",
    "telemetry",
)

# Recovery modes that are permitted. Teleport is deliberately NOT here: a scenario
# may only list recovery modes used for *diagnostics reported as failure*, never
# for success. An empty list is the normal, strongest posture.
ALLOWED_RECOVERY_MODES = ("none",)
FORBIDDEN_RECOVERY_MODES = ("teleport", "teleport_to_objective", "phase_through",
                            "noclip", "ghost")

REQUIRED_FIELDS = (
    "runtime_scenario_id",
    "pack",
    "map_id",
    "biome",
    "mission_id",
    "mission_archetype",
    "encounter_id",
    "encounter_profile",
    "spawn_anchor_id",
    "start_transform",
    "objective_sequence",
    "required_interactions",
    "expected_state_transitions",
    "expected_completion_event",
    "save_load_required",
    "pawn_profile_id",
    "route_plan_id",
    "visual_kit_id",
    "cover_realization_report_id",
    "world_state_keys",
    "timeout_seconds",
    "allowed_recovery_modes",
    "validation_requirements",
    "created_by",
    "created_at",
)

ALLOWED_FIELDS = REQUIRED_FIELDS + ("schema_version", "scenario_tier")


def validate_scenario(obj, strict=False):
    """Return check tuples for one runtime scenario."""
    C = FailureCode
    checks = []
    checks += RS.check_required(obj, REQUIRED_FIELDS, C.RUNTIME_SCENARIO_SCHEMA_FAILURE)
    checks += RS.check_no_unknown(obj, ALLOWED_FIELDS, C.RUNTIME_SCENARIO_SCHEMA_FAILURE, strict)
    checks += RS.check_enum(obj, "mission_archetype", MISSION_ARCHETYPES,
                            C.RUNTIME_SCENARIO_SCHEMA_FAILURE)
    checks += RS.check_enum(obj, "encounter_profile", ENCOUNTER_PROFILES,
                            C.RUNTIME_SCENARIO_SCHEMA_FAILURE)
    checks += RS.check_transform(obj, "start_transform", C.RUNTIME_SCENARIO_SCHEMA_FAILURE,
                                 require_yaw=True)
    checks += RS.check_positive_number(obj, "timeout_seconds", C.RUNTIME_ROUTE_TIMEOUT)
    checks += RS.check_type(obj, "objective_sequence", list, C.RUNTIME_SCENARIO_SCHEMA_FAILURE)
    checks += RS.check_type(obj, "required_interactions", list, C.INTERACTION_ACTOR_MISSING)
    checks += RS.check_type(obj, "expected_state_transitions", list, C.RUNTIME_SCENARIO_SCHEMA_FAILURE)
    checks += RS.check_type(obj, "save_load_required", bool, C.RUNTIME_SCENARIO_SCHEMA_FAILURE)
    checks += RS.check_type(obj, "world_state_keys", list, C.RUNTIME_SCENARIO_SCHEMA_FAILURE)

    # timeout must be strictly positive (brief negative: timeout_seconds <= 0).
    ts = obj.get("timeout_seconds") if isinstance(obj, dict) else None
    checks.append(("scenario::timeout_positive", RS.is_number(ts) and ts > 0,
                   "timeout_seconds must be > 0 (got {!r})".format(ts),
                   C.RUNTIME_ROUTE_TIMEOUT))

    # No teleport success: allowed_recovery_modes may not contain a forbidden mode.
    arm = obj.get("allowed_recovery_modes") if isinstance(obj, dict) else None
    if isinstance(arm, list):
        bad = sorted(set(m for m in arm if m in FORBIDDEN_RECOVERY_MODES))
        checks.append(("scenario::no_teleport_recovery", not bad,
                       "allowed_recovery_modes contains forbidden teleport mode(s): {}".format(bad) if bad
                       else "no forbidden recovery modes",
                       C.PLAYTEST_GAMMA_TELEPORT_SUCCESS_FORBIDDEN))
    else:
        checks.append(("scenario::recovery_modes_list", False,
                       "allowed_recovery_modes must be a list", C.RUNTIME_SCENARIO_SCHEMA_FAILURE))

    # required_interactions must each carry a supported verb + expected event.
    ris = obj.get("required_interactions") if isinstance(obj, dict) else None
    if isinstance(ris, list):
        for i, ri in enumerate(ris):
            verb = ri.get("verb") if isinstance(ri, dict) else None
            checks.append(("scenario::interaction[{}]_verb".format(i), verb in INTERACTION_VERBS,
                           "required interaction verb {!r} unsupported".format(verb),
                           C.INTERACTION_VERB_UNSUPPORTED))
            checks.append(("scenario::interaction[{}]_event".format(i),
                           bool(isinstance(ri, dict) and ri.get("expected_event")),
                           "required interaction must declare expected_event",
                           C.INTERACTION_EVENT_MISSING))

    # validation_requirements must be a subset of the known set and cover the
    # runtime-truth minimum (spawn/possession/navmesh/interaction/state/completion).
    vr = obj.get("validation_requirements") if isinstance(obj, dict) else None
    if isinstance(vr, list):
        unknown = sorted(set(vr) - set(VALIDATION_REQUIREMENTS))
        checks.append(("scenario::validation_requirements_known", not unknown,
                       "unknown validation requirements: {}".format(unknown) if unknown
                       else "validation requirements known",
                       C.RUNTIME_SCENARIO_SCHEMA_FAILURE))
    return checks


def scenario_id(map_id, mission_archetype, encounter_profile):
    """Deterministic scenario id (no timestamp)."""
    return "rt_{}__{}__{}".format(map_id, mission_archetype, encounter_profile)


def _valid_fixture():
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_scenario_id": "rt_wetland_disable_site_seed02_standard",
        "pack": "encounter_loop_world",
        "map_id": "wetland_mire_basin_reclaimed_seed02",
        "biome": "wetland_mire",
        "mission_id": "mission_disable_site_wetland_seed02",
        "mission_archetype": "disable_site",
        "encounter_id": "enc_standard_pressure_wetland_seed02",
        "encounter_profile": "standard_pressure",
        "spawn_anchor_id": "spawn_player_primary",
        "start_transform": {"x": 1024.0, "y": 512.0, "z": 120.0, "yaw": 90.0},
        "objective_sequence": ["reach_primary_poi", "disable_target",
                               "confirm_state", "extract_or_complete"],
        "required_interactions": [{
            "interaction_id": "disable_generator_core", "verb": "disable",
            "actor_tag": "WF_OBJ_DISABLE_TARGET", "required_radius": 175.0,
            "expected_event": "objective.disabled"}],
        "expected_state_transitions": [{
            "key": "mission.disable_site.completed", "from": False, "to": True}],
        "expected_completion_event": "mission.completed",
        "save_load_required": True,
        "pawn_profile_id": "wf_runtime_test_pawn_default",
        "route_plan_id": "route_runtime_disable_site_wetland_seed02",
        "visual_kit_id": "visual_kit_wetland_mire_default",
        "cover_realization_report_id": "wf.visual.cover_replacement_report.v1.latest",
        "world_state_keys": ["mission.disable_site.completed",
                             "objective.disable_generator_core.state"],
        "timeout_seconds": 180,
        "allowed_recovery_modes": [],
        "validation_requirements": list(VALIDATION_REQUIREMENTS),
        "created_by": "worldforge.v1.6.runtime_scenario_generator",
        "created_at": "2026-07-06T00:00:00+00:00",
    }


if __name__ == "__main__":
    ok = [c for c in validate_scenario(_valid_fixture(), strict=True) if not c[1]]
    assert not ok, "valid scenario failed: {}".format(ok)
    # Teleport recovery + non-positive timeout must be caught.
    broken = _valid_fixture()
    broken["allowed_recovery_modes"] = ["teleport_to_objective"]
    broken["timeout_seconds"] = 0
    fails = [c for c in validate_scenario(broken, strict=True) if not c[1]]
    assert any("no_teleport_recovery" in c[0] for c in fails), "teleport recovery not caught"
    assert any("timeout_positive" in c[0] for c in fails), "non-positive timeout not caught"
    print("OK runtime_scenario_contract self-check: valid passes, known-bad fails "
          "({} archetypes x {} profiles)".format(len(MISSION_ARCHETYPES), len(ENCOUNTER_PROFILES)))
