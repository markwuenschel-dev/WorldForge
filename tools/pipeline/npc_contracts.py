#!/usr/bin/env python3
"""npc_contracts.py — WorldForge v1.7 NPCForge + EncounterBehaviorForge spine.

The full strict schema surface the v1.7 behavior substrate builds on. One module,
one section per contract, each with X_REQUIRED / X_ALLOWED field sets, a
``validate_X(obj, strict)`` returning ``(name, ok, detail, code)`` check tuples in
the exact shape ValidationReport.check consumes, and a canonical ``_example_X``
factory. A ``CONTRACTS`` registry pairs each validator with a valid example and a
known-bad example so the schema gate can dogfood that every contract actually
constrains (a contract that accepts its own known-bad is a fake-green vector).

This spine sits directly on the v1.6z grounded traversal substrate: behavior
scenarios reference a ``ground_scenario_id`` and NPC routes are bound to the
validated GroundRouteGraph / grounded_worldforge_route plans — never flight, never
teleport. Those honesty invariants are enforced here at the schema layer.

Contracts:
  NPCArchetype            validate_archetype
  NPCSpawnGroup           validate_spawn_group
  PerceptionModel         validate_perception_model
  PressureModel           validate_pressure_model
  BehaviorProfile         validate_behavior_profile
  NPCBehaviorState        validate_behavior_state
  BehaviorScenario        validate_behavior_scenario
  BehaviorTelemetry       validate_telemetry
  BehaviorCompletionReport validate_completion_report
"""

from pathlib import Path

from failure_codes import FailureCode
import runtime_schema as RS

REPO_ROOT = Path(__file__).resolve().parents[2]
C = FailureCode

# --------------------------------------------------------------------------- #
# Taxonomy — the behavior vocabulary. Kept here so every generator/validator/
# shield imports one source of truth.
# --------------------------------------------------------------------------- #
# Required v1.7 NPC archetypes (+ optional stretch) — Hard scope §"Required NPC
# archetypes". behavior_role is drawn from this set.
NPC_ARCHETYPES = (
    "grunt_patroller", "static_guard", "ranged_sentry", "hazard_warden", "ambush_trigger",
    # optional stretch
    "heavy_blocker", "scout_chaser",
)
REQUIRED_NPC_ARCHETYPES = NPC_ARCHETYPES[:5]

# Allowed movement models — Required data contracts §"Allowed movement models".
MOVEMENT_MODELS = (
    "stationary", "patrol_route", "guard_radius", "pursue_limited",
    "triggered_ambush", "hazard_anchor",
)
# Grounded-only movement: none of these may require flight or teleport. This is a
# taxonomy fact the route-binding layer and negatives lean on.
FORBIDDEN_MOVEMENT_MODELS = ("flight", "teleport", "continuous_flight", "teleport_pursuit")

# Allowed pressure models on an archetype — §"Allowed pressure models".
PRESSURE_MODELS = (
    "none", "proximity_pressure", "ranged_tick_pressure", "hazard_zone_pressure",
    "contact_pressure", "state_pressure",
)
# Allowed pressure OUTPUTS a PressureModel may emit — §PressureModel "Allowed
# pressure outputs". v1.7 alpha is telemetry/state pressure; simple_damage is
# declared but only counts as combat when actually implemented (kept honest).
PRESSURE_TYPES = (
    "telemetry_only", "state_pressure", "hazard_exposure", "simple_damage",
    "route_denial_warning",
)

# Route modes an archetype may traverse — grounded substrate only.
ROUTE_MODES = ("grounded_worldforge_route", "grounded_manual_waypoint", "stationary_anchor")

ROUTE_BLOCKING_POLICIES = ("never", "transient_only", "guard_zone_only")
SPAWN_ZONE_POLICIES = ("walkable_only", "walkable_off_route", "anchor_bound")
FORMATION_POLICIES = ("scatter", "line", "cluster", "perimeter", "single")
ROUTE_BINDING_POLICIES = ("patrol_segment", "guard_anchor", "ambush_volume", "hazard_zone", "roam_zone")
OCCLUSION_POLICIES = ("none", "line_trace", "capsule_trace")

# The 8 v1.4 encounter archetypes a BehaviorProfile maps to a behavior.
ENCOUNTER_ARCHETYPES = (
    "guarded_objective", "patrol_route", "ambush_choke", "hazard_field",
    "resource_contest", "defensive_holdout", "roaming_threat", "extraction_pressure",
)
# Required behavior-profile coverage — §"Required encounter behavior profiles".
BEHAVIOR_PROFILE_KINDS = (
    "patrol_pressure", "ambush_pressure", "hazard_pressure", "guard_pressure", "ranged_pressure",
)

# NPCBehaviorState allowed states — §NPCBehaviorState "Allowed states".
BEHAVIOR_STATES = (
    "unspawned", "spawned", "idle", "guarding", "patrolling", "alerted",
    "engaging", "pressuring", "resolved", "disabled", "expired", "failed",
)

MISSION_COMPLETION_POLICIES = ("must_remain_possible", "must_remain_possible_under_baseline")
RESULT_STATUS = ("pass", "fail", "skipped", "not_implemented")

# BehaviorCompletionReport completion classes — §BehaviorCompletionReport.
COMPLETION_CLASSES = (
    "behavior_completed_runtime",
    "failed_npc_spawn", "failed_route_binding", "failed_perception", "failed_pressure",
    "failed_encounter_state", "failed_mission_completion", "failed_save_load",
    "failed_balance", "failed_report_integrity",
)
SUCCESS_COMPLETION_CLASS = "behavior_completed_runtime"

# Balance classification bands.
BALANCE_CLASSES = ("balanced", "too_low", "too_high", "unwinnable", "no_pressure")

# Report type identifiers — §"Required reports / New report types".
RT_ARCHETYPE = "wf.npc.archetype_report.v1"
RT_SPAWN_GROUP = "wf.npc.spawn_group_report.v1"
RT_BEHAVIOR_PROFILE = "wf.npc.behavior_profile_report.v1"
RT_SCENARIO_MANIFEST = "wf.npc.behavior_scenario_manifest.v1"
RT_MATERIALIZATION = "wf.npc.materialization_report.v1"
RT_SPAWN_PLACEMENT = "wf.npc.spawn_placement_report.v1"
RT_ROUTE_BINDING = "wf.npc.route_binding_report.v1"
RT_TELEMETRY = "wf.npc.telemetry.v1"
RT_COMPLETION = "wf.npc.behavior_completion_report.v1"
RT_BALANCE = "wf.npc.behavior_balance_report.v1"
RT_FAILURE_SUMMARY = "wf.npc.failure_summary.v1"
RT_SHIELD_ROLLUP = "wf.v1_7.full_shield_rollup.v1"

# Generated / report roots (repo-relative).
ARCHETYPE_GENERATED_REL = "procedural/generated/npc/archetypes"
SPAWN_GROUP_GENERATED_REL = "procedural/generated/npc/spawn_groups"
BEHAVIOR_PROFILE_GENERATED_REL = "procedural/generated/npc/behavior_profiles"
BEHAVIOR_SCENARIO_GENERATED_REL = "procedural/generated/npc/behavior_scenarios"
PERCEPTION_MODEL_GENERATED_REL = "procedural/generated/npc/perception_models"
PRESSURE_MODEL_GENERATED_REL = "procedural/generated/npc/pressure_models"
MATERIALIZATION_REPORTS_REL = "procedural/reports/npc/materialization"
SPAWN_PLACEMENT_REPORTS_REL = "procedural/reports/npc/spawn_placement"
ROUTE_BINDING_REPORTS_REL = "procedural/reports/npc/route_binding"
TELEMETRY_REPORTS_REL = "procedural/reports/npc/telemetry"
COMPLETION_REPORTS_REL = "procedural/reports/npc/completion"
BALANCE_REPORTS_REL = "procedural/reports/npc/balance"

# v1.7 materialization modes — how the runtime actor set is realized on a map.
#   runtime_spawn: UWFRuntimeAutoSpawnSubsystem spawns the actor set at BeginPlay in
#                  standalone -game (the CANONICAL v1.7 mode — reproduces the whole
#                  matrix from a clean checkout with no committed .umap edits).
#   baked_editor:  the actor set baked into the .umap by the editor prepare step
#                  (optional editor-preview / v1.7x; not required for the matrix).
RUNTIME_SPAWN_MODE = "runtime_spawn"
BAKED_EDITOR_MODE = "baked_editor"
MATERIALIZATION_MODES = (RUNTIME_SPAWN_MODE, BAKED_EDITOR_MODE)


def runtime_realized_maps(completion_dir):
    """The set of maps genuinely realized AT RUNTIME, derived only from committed
    behavior-completion evidence: a map counts iff it has >=1 completion report whose
    completion_class is SUCCESS_COMPLETION_CLASS with npc_count > 0 (the engine spawned
    real NPCs on that map). This is the single source of truth shared by the manifest
    writer (materialize) and the gate (validate) so the two can never drift, and it is
    grounded in evidence a separate validator (validate-npc-completion) already proves
    genuine — so runtime_spawn materialization cannot be greened without real runtime
    behavior. Returns a set of map_id strings."""
    import json as _json
    from pathlib import Path as _Path
    d = _Path(completion_dir)
    realized = set()
    if not d.is_dir():
        return realized
    for f in sorted(d.glob("bs_*.json")):
        try:
            r = _json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if (r.get("completion_class") == SUCCESS_COMPLETION_CLASS
                and isinstance(r.get("npc_count"), int) and r["npc_count"] > 0
                and r.get("map_id")):
            realized.add(r["map_id"])
    return realized


def _num(obj, field, code, prefix, allow_zero=True):
    return RS.check_positive_number(obj, field, code, prefix=prefix, allow_zero=allow_zero)


def _list(obj, field, code, prefix, min_len=0):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, list) and len(v) >= min_len
    return [("{}{}_list".format(prefix, field), ok,
             "{} must be a list (>= {} items)".format(field, min_len), code)]


def _bool(obj, field, code, prefix):
    v = obj.get(field) if isinstance(obj, dict) else None
    ok = isinstance(v, bool)
    return [("{}{}_bool".format(prefix, field), ok,
             "{} must be a boolean".format(field), code)]


# --------------------------------------------------------------------------- #
# NPCArchetype
# --------------------------------------------------------------------------- #
ARCHETYPE_SCHEMA_VERSION = "wf.npc.archetype.v1"
ARCHETYPE_REQUIRED = (
    "npc_archetype_id", "display_name", "behavior_role", "movement_model", "perception_model",
    "pressure_model", "allowed_spawn_zones", "allowed_route_modes", "collision_profile",
    "capsule_radius", "capsule_half_height", "movement_speed", "engagement_radius",
    "disengagement_radius", "line_of_sight_required", "can_block_route", "route_blocking_policy",
    "save_load_required", "telemetry_required", "balance_tags", "validation_requirements",
    "created_by", "created_at",
)
ARCHETYPE_ALLOWED = ARCHETYPE_REQUIRED + ("meta", "schema_version", "report_type")


def validate_archetype(obj, strict=False):
    ch = RS.check_required(obj, ARCHETYPE_REQUIRED, C.NPC_ARCHETYPE_SCHEMA_FAILURE)
    ch += RS.check_no_unknown(obj, ARCHETYPE_ALLOWED, C.NPC_ARCHETYPE_SCHEMA_FAILURE, strict)
    ch += RS.check_enum(obj, "behavior_role", NPC_ARCHETYPES, C.NPC_ARCHETYPE_SCHEMA_FAILURE)
    ch += RS.check_enum(obj, "movement_model", MOVEMENT_MODELS, C.NPC_ARCHETYPE_SCHEMA_FAILURE)
    ch += RS.check_enum(obj, "pressure_model", PRESSURE_MODELS, C.NPC_ARCHETYPE_SCHEMA_FAILURE)
    ch += RS.check_enum(obj, "route_blocking_policy", ROUTE_BLOCKING_POLICIES, C.NPC_ARCHETYPE_SCHEMA_FAILURE)
    if not isinstance(obj, dict):
        return ch
    # perception_model is a reference to a PerceptionModel (id string, non-empty).
    pm = obj.get("perception_model")
    ch.append(("arch::perception_model_ref", isinstance(pm, str) and len(pm) > 0,
               "perception_model must be a non-empty perception_model_id", C.NPC_ARCHETYPE_SCHEMA_FAILURE))
    for f in ("capsule_radius", "capsule_half_height", "engagement_radius", "disengagement_radius"):
        ch += _num(obj, f, C.NPC_ARCHETYPE_SCHEMA_FAILURE, "arch::", allow_zero=False)
    ch += _num(obj, "movement_speed", C.NPC_ARCHETYPE_SCHEMA_FAILURE, "arch::", allow_zero=True)
    for f in ("line_of_sight_required", "can_block_route", "save_load_required", "telemetry_required"):
        ch += _bool(obj, f, C.NPC_ARCHETYPE_SCHEMA_FAILURE, "arch::")
    for f in ("allowed_spawn_zones", "allowed_route_modes", "balance_tags", "validation_requirements"):
        ch += _list(obj, f, C.NPC_ARCHETYPE_SCHEMA_FAILURE, "arch::", min_len=1)
    # Route modes must be grounded substrate only — never flight/teleport.
    modes = obj.get("allowed_route_modes")
    if isinstance(modes, list):
        bad = [m for m in modes if m not in ROUTE_MODES]
        ch.append(("arch::route_modes_grounded", not bad,
                   "allowed_route_modes has non-grounded mode(s): {}".format(bad),
                   C.NPC_ROUTE_FLIGHT_REQUIRED))
    # A stationary movement model may not require route traversal.
    if obj.get("movement_model") == "stationary":
        ch.append(("arch::stationary_no_route",
                   "stationary_anchor" in (modes or []) or not obj.get("can_block_route"),
                   "stationary archetype should use stationary_anchor route mode",
                   C.NPC_ARCHETYPE_SCHEMA_FAILURE))
    # can_block_route=false implies route_blocking_policy == never.
    if obj.get("can_block_route") is False:
        ch.append(("arch::no_block_policy_never", obj.get("route_blocking_policy") == "never",
                   "can_block_route=false requires route_blocking_policy=never",
                   C.NPC_ROUTE_BLOCKS_MISSION_PATH))
    # engagement < disengagement (hysteresis) — else detection thrashes.
    er, dr = obj.get("engagement_radius"), obj.get("disengagement_radius")
    if RS.is_number(er) and RS.is_number(dr):
        ch.append(("arch::disengage_ge_engage", dr >= er,
                   "disengagement_radius must be >= engagement_radius", C.NPC_ARCHETYPE_SCHEMA_FAILURE))
    return ch


def _example_archetype(**over):
    d = {
        "npc_archetype_id": "npc_grunt_patroller", "display_name": "Grunt Patroller",
        "behavior_role": "grunt_patroller", "movement_model": "patrol_route",
        "perception_model": "perc_standard_radius", "pressure_model": "proximity_pressure",
        "allowed_spawn_zones": ["walkable_off_route"], "allowed_route_modes": ["grounded_worldforge_route"],
        "collision_profile": "Pawn", "capsule_radius": 34.0, "capsule_half_height": 88.0,
        "movement_speed": 300.0, "engagement_radius": 800.0, "disengagement_radius": 1200.0,
        "line_of_sight_required": False, "can_block_route": False, "route_blocking_policy": "never",
        "save_load_required": True, "telemetry_required": True, "balance_tags": ["low_pressure"],
        "validation_requirements": ["spawn_walkable", "route_bound", "telemetry"],
        "created_by": "worldforge.v1.7", "created_at": "2026-07-08T00:00:00+00:00",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# NPCSpawnGroup
# --------------------------------------------------------------------------- #
SPAWN_GROUP_SCHEMA_VERSION = "wf.npc.spawn_group.v1"
SPAWN_GROUP_REQUIRED = (
    "spawn_group_id", "encounter_id", "mission_id", "map_id", "biome", "pressure_profile",
    "npc_archetype_ids", "spawn_anchor_ids", "count", "formation_policy", "route_binding_policy",
    "spawn_zone_policy", "max_density", "min_distance_from_objective", "min_distance_from_player_spawn",
    "route_clearance_required", "walkability_required", "save_load_required", "validation_requirements",
)
SPAWN_GROUP_ALLOWED = SPAWN_GROUP_REQUIRED + ("meta", "schema_version", "report_type", "created_by",
                                              "created_at", "behavior_profile_id")


def validate_spawn_group(obj, strict=False):
    ch = RS.check_required(obj, SPAWN_GROUP_REQUIRED, C.NPC_SPAWN_GROUP_SCHEMA_FAILURE)
    ch += RS.check_no_unknown(obj, SPAWN_GROUP_ALLOWED, C.NPC_SPAWN_GROUP_SCHEMA_FAILURE, strict)
    ch += RS.check_enum(obj, "formation_policy", FORMATION_POLICIES, C.NPC_SPAWN_GROUP_SCHEMA_FAILURE)
    ch += RS.check_enum(obj, "route_binding_policy", ROUTE_BINDING_POLICIES, C.NPC_SPAWN_GROUP_SCHEMA_FAILURE)
    ch += RS.check_enum(obj, "spawn_zone_policy", SPAWN_ZONE_POLICIES, C.NPC_SPAWN_GROUP_SCHEMA_FAILURE)
    if not isinstance(obj, dict):
        return ch
    ch += _list(obj, "npc_archetype_ids", C.NPC_SPAWN_GROUP_SCHEMA_FAILURE, "grp::", min_len=1)
    ch += _list(obj, "spawn_anchor_ids", C.NPC_SPAWN_POINT_MISSING, "grp::", min_len=1)
    ch += _list(obj, "validation_requirements", C.NPC_SPAWN_GROUP_SCHEMA_FAILURE, "grp::", min_len=1)
    cnt = obj.get("count")
    ch.append(("grp::count_positive", isinstance(cnt, int) and cnt > 0,
               "count must be a positive integer (no zero-NPC spawn group)", C.NPC_SPAWN_GROUP_SCHEMA_FAILURE))
    for f in ("max_density", "min_distance_from_objective", "min_distance_from_player_spawn"):
        ch += _num(obj, f, C.NPC_SPAWN_GROUP_SCHEMA_FAILURE, "grp::", allow_zero=False)
    for f in ("route_clearance_required", "walkability_required", "save_load_required"):
        ch += _bool(obj, f, C.NPC_SPAWN_GROUP_SCHEMA_FAILURE, "grp::")
    # count must not exceed anchors * max_density budget (structural density guard).
    anchors = obj.get("spawn_anchor_ids")
    dens = obj.get("max_density")
    if isinstance(anchors, list) and isinstance(cnt, int) and RS.is_number(dens):
        ch.append(("grp::density_within_budget", cnt <= len(anchors) * dens + 1e-9,
                   "count {} exceeds anchors*max_density budget".format(cnt),
                   C.NPC_DENSITY_BUDGET_FAILURE))
    # Walkability must be required — spawns are walkability-driven (merge gate).
    ch.append(("grp::walkability_required_true", obj.get("walkability_required") is True,
               "spawn placement must be walkability-driven (walkability_required=true)",
               C.NPC_SPAWN_OFF_WALKABLE_SURFACE))
    return ch


def _example_spawn_group(**over):
    d = {
        "spawn_group_id": "sg_M_guarded_objective", "encounter_id": "enc_M_guarded_objective",
        "mission_id": "m_M", "map_id": "M", "biome": "volcanic_ashlands",
        "pressure_profile": "standard_pressure", "npc_archetype_ids": ["npc_static_guard"],
        "spawn_anchor_ids": ["guard_anchor_0", "guard_anchor_1"], "count": 2,
        "formation_policy": "perimeter", "route_binding_policy": "guard_anchor",
        "spawn_zone_policy": "walkable_off_route", "max_density": 1.0,
        "min_distance_from_objective": 400.0, "min_distance_from_player_spawn": 1500.0,
        "route_clearance_required": True, "walkability_required": True,
        "save_load_required": True, "validation_requirements": ["spawn_walkable", "not_on_route"],
        "behavior_profile_id": "bp_guard_pressure",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# PerceptionModel
# --------------------------------------------------------------------------- #
PERCEPTION_SCHEMA_VERSION = "wf.npc.perception_model.v1"
PERCEPTION_REQUIRED = (
    "perception_model_id", "radius", "field_of_view_degrees", "line_of_sight_required",
    "hearing_radius", "memory_seconds", "update_interval_seconds", "occlusion_policy",
    "detection_threshold", "loss_threshold",
)
PERCEPTION_ALLOWED = PERCEPTION_REQUIRED + ("meta", "schema_version", "report_type",
                                            "created_by", "created_at")


def validate_perception_model(obj, strict=False):
    ch = RS.check_required(obj, PERCEPTION_REQUIRED, C.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE)
    ch += RS.check_no_unknown(obj, PERCEPTION_ALLOWED, C.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE, strict)
    ch += RS.check_enum(obj, "occlusion_policy", OCCLUSION_POLICIES, C.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE)
    if not isinstance(obj, dict):
        return ch
    ch += _bool(obj, "line_of_sight_required", C.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE, "perc::")
    for f in ("radius", "update_interval_seconds"):
        ch += _num(obj, f, C.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE, "perc::", allow_zero=False)
    for f in ("hearing_radius", "memory_seconds"):
        ch += _num(obj, f, C.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE, "perc::", allow_zero=True)
    fov = obj.get("field_of_view_degrees")
    ch.append(("perc::fov_range", RS.is_number(fov) and 0 < fov <= 360,
               "field_of_view_degrees must be in (0, 360]", C.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE))
    for f in ("detection_threshold", "loss_threshold"):
        v = obj.get(f)
        ch.append(("perc::{}_unit".format(f), RS.is_number(v) and 0.0 <= v <= 1.0,
                   "{} must be in [0,1]".format(f), C.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE))
    dt, lt = obj.get("detection_threshold"), obj.get("loss_threshold")
    if RS.is_number(dt) and RS.is_number(lt):
        ch.append(("perc::loss_le_detect", lt <= dt,
                   "loss_threshold must be <= detection_threshold (hysteresis)",
                   C.NPC_PERCEPTION_MODEL_SCHEMA_FAILURE))
    # LOS-required perception must trace occlusion, else it can "see" through walls.
    if obj.get("line_of_sight_required") is True:
        ch.append(("perc::los_needs_occlusion", obj.get("occlusion_policy") in ("line_trace", "capsule_trace"),
                   "line_of_sight_required=true needs an occlusion trace policy",
                   C.NPC_PERCEPTION_FAILURE))
    return ch


def _example_perception(**over):
    d = {
        "perception_model_id": "perc_standard_radius", "radius": 800.0,
        "field_of_view_degrees": 200.0, "line_of_sight_required": False, "hearing_radius": 600.0,
        "memory_seconds": 4.0, "update_interval_seconds": 0.25, "occlusion_policy": "none",
        "detection_threshold": 0.6, "loss_threshold": 0.3,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# PressureModel
# --------------------------------------------------------------------------- #
PRESSURE_SCHEMA_VERSION = "wf.npc.pressure_model.v1"
PRESSURE_REQUIRED = (
    "pressure_model_id", "pressure_type", "radius", "tick_interval_seconds", "pressure_value",
    "max_pressure_duration", "cooldown_seconds", "requires_line_of_sight", "state_effects",
    "telemetry_events",
)
PRESSURE_ALLOWED = PRESSURE_REQUIRED + ("meta", "schema_version", "report_type",
                                        "created_by", "created_at")


def validate_pressure_model(obj, strict=False):
    ch = RS.check_required(obj, PRESSURE_REQUIRED, C.NPC_PRESSURE_MODEL_SCHEMA_FAILURE)
    ch += RS.check_no_unknown(obj, PRESSURE_ALLOWED, C.NPC_PRESSURE_MODEL_SCHEMA_FAILURE, strict)
    ch += RS.check_enum(obj, "pressure_type", PRESSURE_TYPES, C.NPC_PRESSURE_MODEL_SCHEMA_FAILURE)
    if not isinstance(obj, dict):
        return ch
    ch += _bool(obj, "requires_line_of_sight", C.NPC_PRESSURE_MODEL_SCHEMA_FAILURE, "prs::")
    for f in ("radius", "tick_interval_seconds", "max_pressure_duration"):
        ch += _num(obj, f, C.NPC_PRESSURE_MODEL_SCHEMA_FAILURE, "prs::", allow_zero=False)
    ch += _num(obj, "cooldown_seconds", C.NPC_PRESSURE_MODEL_SCHEMA_FAILURE, "prs::", allow_zero=True)
    ch += _list(obj, "state_effects", C.NPC_PRESSURE_MODEL_SCHEMA_FAILURE, "prs::", min_len=0)
    ch += _list(obj, "telemetry_events", C.NPC_PRESSURE_MODEL_SCHEMA_FAILURE, "prs::", min_len=1)
    pv = obj.get("pressure_value")
    ptype = obj.get("pressure_type")
    # A pressure model that is not telemetry_only MUST apply positive pressure —
    # zero pressure is not "active behavior" (balance: NPC_PRESSURE_TOO_LOW).
    if ptype and ptype != "telemetry_only":
        ch.append(("prs::value_positive", RS.is_number(pv) and pv > 0,
                   "non-telemetry pressure_type requires pressure_value > 0", C.NPC_PRESSURE_TOO_LOW))
    else:
        ch.append(("prs::value_number", RS.is_number(pv) and pv >= 0,
                   "pressure_value must be a number >= 0", C.NPC_PRESSURE_MODEL_SCHEMA_FAILURE))
    # Pressure must expire — a model with no max_pressure_duration never resolves.
    md = obj.get("max_pressure_duration")
    ch.append(("prs::expires", RS.is_number(md) and md > 0,
               "pressure must expire (max_pressure_duration > 0)", C.NPC_PRESSURE_FAILURE))
    return ch


def _example_pressure(**over):
    d = {
        "pressure_model_id": "prs_proximity_low", "pressure_type": "state_pressure",
        "radius": 600.0, "tick_interval_seconds": 0.5,
        "pressure_value": 4.0, "max_pressure_duration": 20.0, "cooldown_seconds": 3.0,
        "requires_line_of_sight": False, "state_effects": ["alert_raised"],
        "telemetry_events": ["behavior.pressure.applied", "behavior.pressure.expired"],
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# BehaviorProfile — maps a v1.4 encounter archetype to runtime behavior.
# --------------------------------------------------------------------------- #
BEHAVIOR_PROFILE_SCHEMA_VERSION = "wf.npc.behavior_profile.v1"
BEHAVIOR_PROFILE_REQUIRED = (
    "behavior_profile_id", "encounter_archetype", "pressure_profile", "npc_archetypes",
    "spawn_group_rules", "route_rules", "perception_rules", "engagement_rules", "pressure_rules",
    "resolution_rules", "mission_completion_policy", "save_load_policy", "telemetry_requirements",
    "balance_requirements",
)
BEHAVIOR_PROFILE_ALLOWED = BEHAVIOR_PROFILE_REQUIRED + ("meta", "schema_version", "report_type",
                                                        "created_by", "created_at", "profile_kind")


def validate_behavior_profile(obj, strict=False):
    ch = RS.check_required(obj, BEHAVIOR_PROFILE_REQUIRED, C.NPC_BEHAVIOR_PROFILE_SCHEMA_FAILURE)
    ch += RS.check_no_unknown(obj, BEHAVIOR_PROFILE_ALLOWED, C.NPC_BEHAVIOR_PROFILE_SCHEMA_FAILURE, strict)
    ch += RS.check_enum(obj, "encounter_archetype", ENCOUNTER_ARCHETYPES, C.NPC_BEHAVIOR_PROFILE_SCHEMA_FAILURE)
    ch += RS.check_enum(obj, "mission_completion_policy", MISSION_COMPLETION_POLICIES,
                        C.NPC_MISSION_COMPLETION_BLOCKED)
    if not isinstance(obj, dict):
        return ch
    ch += _list(obj, "npc_archetypes", C.NPC_BEHAVIOR_PROFILE_SCHEMA_FAILURE, "bp::", min_len=1)
    for f in ("telemetry_requirements", "balance_requirements"):
        ch += _list(obj, f, C.NPC_BEHAVIOR_PROFILE_SCHEMA_FAILURE, "bp::", min_len=1)
    for f in ("spawn_group_rules", "route_rules", "perception_rules", "engagement_rules",
              "pressure_rules", "resolution_rules", "save_load_policy"):
        ok = isinstance(obj.get(f), dict) and len(obj.get(f)) > 0
        ch.append(("bp::{}_object".format(f), ok, "{} must be a non-empty object".format(f),
                   C.NPC_BEHAVIOR_PROFILE_SCHEMA_FAILURE))
    # Behavior must preserve mission completion — a profile can't opt out.
    ch.append(("bp::mission_completion_preserved",
               obj.get("mission_completion_policy") in MISSION_COMPLETION_POLICIES,
               "profile must preserve mission completion", C.NPC_MISSION_COMPLETION_BLOCKED))
    # profile_kind, if present, must be a known behavior profile kind.
    if obj.get("profile_kind") is not None:
        ch.append(("bp::profile_kind_known", obj.get("profile_kind") in BEHAVIOR_PROFILE_KINDS,
                   "profile_kind not in {}".format(BEHAVIOR_PROFILE_KINDS),
                   C.NPC_BEHAVIOR_PROFILE_SCHEMA_FAILURE))
    return ch


def _example_behavior_profile(**over):
    d = {
        "behavior_profile_id": "bp_guard_pressure", "encounter_archetype": "guarded_objective",
        "pressure_profile": "standard_pressure", "npc_archetypes": ["static_guard"],
        "profile_kind": "guard_pressure",
        "spawn_group_rules": {"formation": "perimeter", "min_dist_objective": 400.0},
        "route_rules": {"binding": "guard_anchor", "no_block_mission_path": True},
        "perception_rules": {"model": "perc_standard_radius"},
        "engagement_rules": {"enter": "engagement_radius", "exit": "disengagement_radius"},
        "pressure_rules": {"model": "prs_proximity_low"},
        "resolution_rules": {"on_pawn_leaves": "return_to_guard", "expire_after": 60.0},
        "mission_completion_policy": "must_remain_possible_under_baseline",
        "save_load_policy": {"persist": ["state", "route_node"]},
        "telemetry_requirements": ["behavior.npc.spawned", "behavior.pressure.applied"],
        "balance_requirements": ["baseline_winnable", "pressure_events_seen"],
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# NPCBehaviorState — runtime state record (save/load unit).
# --------------------------------------------------------------------------- #
BEHAVIOR_STATE_SCHEMA_VERSION = "wf.npc.behavior_state.v1"
BEHAVIOR_STATE_REQUIRED = (
    "npc_instance_id", "spawn_group_id", "archetype_id", "map_id", "mission_id", "encounter_id",
    "current_state", "current_route_node", "current_target", "perception_state", "engagement_state",
    "pressure_state", "health_state", "spawned_at", "last_state_change", "save_load_key",
)
BEHAVIOR_STATE_ALLOWED = BEHAVIOR_STATE_REQUIRED + ("meta", "schema_version", "report_type")


_STATE_STR_FIELDS = ("npc_instance_id", "spawn_group_id", "archetype_id", "map_id", "mission_id",
                     "encounter_id", "perception_state", "engagement_state", "pressure_state",
                     "health_state", "save_load_key")
_STATE_NUM_FIELDS = ("spawned_at", "last_state_change")


def validate_behavior_state(obj, strict=False):
    ch = RS.check_required(obj, BEHAVIOR_STATE_REQUIRED, C.NPC_BEHAVIOR_INIT_FAILURE,
                           nullable=("current_route_node", "current_target"))
    ch += RS.check_no_unknown(obj, BEHAVIOR_STATE_ALLOWED, C.NPC_BEHAVIOR_INIT_FAILURE, strict)
    ch += RS.check_enum(obj, "current_state", BEHAVIOR_STATES, C.NPC_ENCOUNTER_STATE_FAILURE)
    if not isinstance(obj, dict):
        return ch
    # Genuine strictness: every scalar field must hold its declared type — a
    # runtime state record with a numeric id or a stringly timestamp is malformed.
    for f in _STATE_STR_FIELDS:
        ch += RS.check_type(obj, f, str, C.NPC_BEHAVIOR_INIT_FAILURE, prefix="state::")
    for f in _STATE_NUM_FIELDS:
        ch += RS.check_positive_number(obj, f, C.NPC_BEHAVIOR_INIT_FAILURE, prefix="state::", allow_zero=True)
    sk = obj.get("save_load_key")
    ch.append(("state::save_load_key", isinstance(sk, str) and len(sk) > 0,
               "save_load_key must be a non-empty string (save/load unit)", C.NPC_SAVE_LOAD_FAILURE))
    return ch


def _example_behavior_state(**over):
    d = {
        "npc_instance_id": "npc_M_guard_0", "spawn_group_id": "sg_M_guarded_objective",
        "archetype_id": "npc_static_guard", "map_id": "M", "mission_id": "m_M",
        "encounter_id": "enc_M_guarded_objective", "current_state": "guarding",
        "current_route_node": "guard_anchor_0", "current_target": None,
        "perception_state": "unaware", "engagement_state": "idle", "pressure_state": "inactive",
        "health_state": "alive", "spawned_at": 0.0, "last_state_change": 0.0,
        "save_load_key": "npc_M_guard_0",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# BehaviorScenario
# --------------------------------------------------------------------------- #
BEHAVIOR_SCENARIO_SCHEMA_VERSION = "wf.npc.behavior_scenario.v1"
BEHAVIOR_SCENARIO_REQUIRED = (
    "behavior_scenario_id", "runtime_scenario_id", "ground_scenario_id", "pack", "map_id",
    "mission_id", "encounter_id", "biome", "mission_archetype", "pressure_profile", "seed",
    "spawn_groups", "behavior_profiles", "expected_npc_states", "expected_perception_events",
    "expected_pressure_events", "expected_encounter_state_transitions", "expected_mission_completion",
    "save_load_required", "timeout_seconds", "validation_requirements",
)
BEHAVIOR_SCENARIO_ALLOWED = BEHAVIOR_SCENARIO_REQUIRED + ("meta", "schema_version", "report_type",
                                                          "created_by", "created_at")


def validate_behavior_scenario(obj, strict=False):
    ch = RS.check_required(obj, BEHAVIOR_SCENARIO_REQUIRED, C.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE)
    ch += RS.check_no_unknown(obj, BEHAVIOR_SCENARIO_ALLOWED, C.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE, strict)
    if not isinstance(obj, dict):
        return ch
    # The scenario is grounded on a v1.6z ground scenario — that link is mandatory.
    gs = obj.get("ground_scenario_id")
    ch.append(("scn::ground_scenario_ref", isinstance(gs, str) and len(gs) > 0,
               "behavior scenario must reference a v1.6z ground_scenario_id", C.NPC_ROUTE_GRAPH_MISSING))
    ch += _list(obj, "spawn_groups", C.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE, "scn::", min_len=1)
    ch += _list(obj, "behavior_profiles", C.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE, "scn::", min_len=1)
    for f in ("expected_npc_states", "expected_perception_events", "expected_pressure_events",
              "expected_encounter_state_transitions", "validation_requirements"):
        ch += _list(obj, f, C.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE, "scn::", min_len=0)
    ch += _num(obj, "timeout_seconds", C.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE, "scn::", allow_zero=False)
    ch += _bool(obj, "save_load_required", C.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE, "scn::")
    ch += _bool(obj, "expected_mission_completion", C.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE, "scn::")
    # A scenario must expect at least one pressure event — else it's not behavior.
    ep = obj.get("expected_pressure_events")
    ch.append(("scn::expects_pressure", isinstance(ep, list) and len(ep) >= 1,
               "scenario must expect >=1 pressure event (active behavior)", C.NPC_NO_PRESSURE_EVENTS))
    # Baseline scenario must keep mission completion possible.
    ch.append(("scn::mission_completable", obj.get("expected_mission_completion") is True,
               "baseline behavior scenario must expect mission completion", C.NPC_MISSION_COMPLETION_BLOCKED))
    return ch


def _example_behavior_scenario(**over):
    d = {
        "behavior_scenario_id": "bs_M_guarded_objective_s0", "runtime_scenario_id": "rt_enc_lp_M_s0",
        "ground_scenario_id": "gs_M_s0", "pack": "encounter_loop_world", "map_id": "M",
        "mission_id": "m_M", "encounter_id": "enc_M_guarded_objective", "biome": "volcanic_ashlands",
        "mission_archetype": "disable_site", "pressure_profile": "standard_pressure", "seed": 0,
        "spawn_groups": ["sg_M_guarded_objective"], "behavior_profiles": ["bp_guard_pressure"],
        "expected_npc_states": ["spawned", "guarding", "alerted", "pressuring", "resolved"],
        "expected_perception_events": ["behavior.perception.detected"],
        "expected_pressure_events": ["behavior.pressure.applied"],
        "expected_encounter_state_transitions": ["idle->alerted", "alerted->pressuring"],
        "expected_mission_completion": True, "save_load_required": True, "timeout_seconds": 180.0,
        "validation_requirements": ["telemetry", "mission_completion", "save_load"],
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# BehaviorTelemetry
# --------------------------------------------------------------------------- #
TELEMETRY_SCHEMA_VERSION = "wf.npc.telemetry.v1"
BEHAVIOR_EVENT_TYPES = (
    "behavior.scenario.started", "behavior.map.loaded", "behavior.npc.spawned",
    "behavior.npc.possessed_or_initialized", "behavior.npc.route.bound",
    "behavior.npc.patrol.started", "behavior.npc.waypoint.reached", "behavior.npc.guard.started",
    "behavior.perception.checked", "behavior.perception.detected", "behavior.perception.lost",
    "behavior.engagement.started", "behavior.pressure.applied", "behavior.pressure.expired",
    "behavior.encounter.state_changed", "behavior.mission.route_preserved",
    "behavior.mission.completed", "behavior.save.completed", "behavior.reload.verified",
    "behavior.scenario.completed", "behavior.scenario.failed",
)
# The event set a genuine behavior_completed_runtime run must contain — proof that
# behavior actually occurred (spawn + init + route bind + a pressure event +
# mission completion + save/load), not just a map that loaded.
COMPLETION_REQUIRED_EVENTS = (
    "behavior.scenario.started", "behavior.npc.spawned", "behavior.npc.possessed_or_initialized",
    "behavior.npc.route.bound", "behavior.pressure.applied", "behavior.encounter.state_changed",
    "behavior.mission.completed", "behavior.save.completed", "behavior.reload.verified",
    "behavior.scenario.completed",
)


def validate_telemetry(obj, strict=False, require_completion=False):
    ch = []
    ok_top = isinstance(obj, dict) and isinstance(obj.get("events"), list)
    ch.append(("tel::has_events", ok_top, "telemetry must carry an events list", C.NPC_TELEMETRY_MISSING))
    if not ok_top:
        return ch
    evs = obj["events"]
    ch.append(("tel::events_nonempty", len(evs) > 0, "telemetry events must be non-empty",
               C.NPC_TELEMETRY_MISSING))
    seen = set()
    for i, e in enumerate(evs):
        et = e.get("event_type") if isinstance(e, dict) else None
        ok = et in BEHAVIOR_EVENT_TYPES
        ch.append(("tel::event{}_type".format(i), ok,
                   "event {} type {!r} not in registry".format(i, et), C.NPC_BEHAVIOR_SCENARIO_SCHEMA_FAILURE))
        if ok:
            seen.add(et)
    if require_completion:
        missing = [e for e in COMPLETION_REQUIRED_EVENTS if e not in seen]
        ch.append(("tel::completion_events_present", not missing,
                   "behavior completion telemetry missing events: {}".format(missing),
                   C.NPC_TELEMETRY_MISSING))
        # No pressure event means no active behavior — hard fail for completion.
        ch.append(("tel::has_pressure_event", "behavior.pressure.applied" in seen,
                   "completion telemetry has no pressure event (no active behavior)",
                   C.NPC_NO_PRESSURE_EVENTS))
    return ch


def _example_telemetry(**over):
    d = {"report_type": TELEMETRY_SCHEMA_VERSION, "behavior_scenario_id": "bs_x",
         "events": [{"event_type": t, "frame": i} for i, t in enumerate(COMPLETION_REQUIRED_EVENTS)]}
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# BehaviorCompletionReport
# --------------------------------------------------------------------------- #
COMPLETION_SCHEMA_VERSION = "wf.npc.behavior_completion_report.v1"
COMPLETION_REQUIRED = (
    "report_id", "behavior_scenario_id", "runtime_scenario_id", "ground_scenario_id", "map_id",
    "mission_id", "encounter_id", "biome", "mission_archetype", "pressure_profile", "seed",
    "status", "completion_class", "spawn_result", "route_binding_result", "perception_result",
    "pressure_result", "encounter_state_result", "mission_completion_result", "save_load_result",
    "balance_result", "telemetry_path", "evidence_paths", "failure_owner", "failure_codes",
    "runtime_duration_seconds", "npc_count", "pressure_events_seen", "mission_completed",
    "created_at", "git_commit",
)
COMPLETION_ALLOWED = COMPLETION_REQUIRED + ("meta", "schema_version", "report_type")
_RESULT_FIELDS = ("spawn_result", "route_binding_result", "perception_result", "pressure_result",
                  "encounter_state_result", "mission_completion_result", "save_load_result",
                  "balance_result")


def validate_completion_report(obj, strict=False):
    ch = RS.check_required(obj, COMPLETION_REQUIRED, C.NPC_REPORT_INTEGRITY_FAILURE,
                           nullable=("failure_owner",))
    ch += RS.check_no_unknown(obj, COMPLETION_ALLOWED, C.NPC_REPORT_INTEGRITY_FAILURE, strict)
    ch += RS.check_enum(obj, "status", RESULT_STATUS, C.NPC_REPORT_INTEGRITY_FAILURE)
    ch += RS.check_enum(obj, "completion_class", COMPLETION_CLASSES, C.NPC_REPORT_INTEGRITY_FAILURE)
    if not isinstance(obj, dict):
        return ch
    for f in _RESULT_FIELDS:
        ch += RS.check_enum(obj, f, RESULT_STATUS, C.NPC_REPORT_INTEGRITY_FAILURE)
    ch.append(("cmp::codes_list", isinstance(obj.get("failure_codes"), list),
               "failure_codes must be a list", C.NPC_REPORT_INTEGRITY_FAILURE))
    ch.append(("cmp::evidence_list", isinstance(obj.get("evidence_paths"), list),
               "evidence_paths must be a list", C.NPC_REPORT_INTEGRITY_FAILURE))
    ch += _num(obj, "runtime_duration_seconds", C.NPC_REPORT_INTEGRITY_FAILURE, "cmp::", allow_zero=False)
    cls = obj.get("completion_class")
    status = obj.get("status")
    npc_count = obj.get("npc_count")
    pev = obj.get("pressure_events_seen")
    # ---- anti-fake-green honesty invariants ----
    if cls == SUCCESS_COMPLETION_CLASS:
        ch.append(("cmp::success_is_pass", status == "pass",
                   "behavior_completed_runtime must have status=pass", C.NPC_REPORT_INTEGRITY_FAILURE))
        ch.append(("cmp::success_has_npcs", isinstance(npc_count, int) and npc_count > 0,
                   "success with zero NPCs is fake green", C.NPC_ACTOR_MISSING))
        ch.append(("cmp::success_has_pressure", isinstance(pev, int) and pev > 0,
                   "success with zero pressure events is not active behavior", C.NPC_NO_PRESSURE_EVENTS))
        ch.append(("cmp::success_mission_done", obj.get("mission_completed") is True,
                   "success must have mission_completed=true", C.NPC_MISSION_COMPLETION_BLOCKED))
        ch.append(("cmp::success_save_load", obj.get("save_load_result") == "pass",
                   "success must have save_load_result=pass", C.NPC_SAVE_LOAD_FAILURE))
        ch.append(("cmp::success_has_telemetry",
                   isinstance(obj.get("telemetry_path"), str) and len(obj.get("telemetry_path")) > 0,
                   "success must reference a telemetry_path", C.NPC_TELEMETRY_MISSING))
        ch.append(("cmp::success_no_codes", len(obj.get("failure_codes") or []) == 0,
                   "success must carry no failure_codes", C.NPC_REPORT_INTEGRITY_FAILURE))
        ch.append(("cmp::success_results_pass",
                   all(obj.get(f) == "pass" for f in ("spawn_result", "route_binding_result",
                                                      "pressure_result", "encounter_state_result",
                                                      "mission_completion_result")),
                   "success requires spawn/route/pressure/state/mission results = pass",
                   C.NPC_REPORT_INTEGRITY_FAILURE))
    else:
        # A failure class must own a failure code and a failure owner.
        ch.append(("cmp::failure_has_code", len(obj.get("failure_codes") or []) > 0,
                   "a failed completion_class must own a failure_code", C.NPC_REPORT_INTEGRITY_FAILURE))
        ch.append(("cmp::failure_not_pass", status != "pass",
                   "a failed completion_class must not have status=pass", C.NPC_REPORT_INTEGRITY_FAILURE))
        ch.append(("cmp::failure_has_owner", bool(obj.get("failure_owner")),
                   "a failed completion_class must name a failure_owner", C.NPC_REPORT_INTEGRITY_FAILURE))
    return ch


def _example_completion(**over):
    d = {
        "report_id": "npc_cmp:bs_M_guarded_objective_s0", "behavior_scenario_id": "bs_M_guarded_objective_s0",
        "runtime_scenario_id": "rt_enc_lp_M_s0", "ground_scenario_id": "gs_M_s0", "map_id": "M",
        "mission_id": "m_M", "encounter_id": "enc_M_guarded_objective", "biome": "volcanic_ashlands",
        "mission_archetype": "disable_site", "pressure_profile": "standard_pressure", "seed": 0,
        "status": "pass", "completion_class": "behavior_completed_runtime", "spawn_result": "pass",
        "route_binding_result": "pass", "perception_result": "pass", "pressure_result": "pass",
        "encounter_state_result": "pass", "mission_completion_result": "pass", "save_load_result": "pass",
        "balance_result": "pass", "telemetry_path": "procedural/reports/npc/telemetry/bs_M.json",
        "evidence_paths": ["procedural/reports/npc/telemetry/bs_M.json"], "failure_owner": None,
        "failure_codes": [], "runtime_duration_seconds": 12.4, "npc_count": 2, "pressure_events_seen": 7,
        "mission_completed": True, "created_at": "live", "git_commit": "unknown",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# Registry of all contracts, for the schema validator + fuzz harness.
# Each entry: name -> (validate_fn, valid_example_fn, known_bad_example_fn).
# The known-bad MUST fail the validator — a contract that accepts it is fake green.
# --------------------------------------------------------------------------- #
CONTRACTS = {
    "NPCArchetype": (
        validate_archetype, _example_archetype,
        # non-grounded route mode must be rejected (flight-required).
        lambda: _example_archetype(allowed_route_modes=["continuous_flight"])),
    "NPCSpawnGroup": (
        validate_spawn_group, _example_spawn_group,
        # walkability not required is rejected (spawns must be walkability-driven).
        lambda: _example_spawn_group(walkability_required=False)),
    "PerceptionModel": (
        validate_perception_model, _example_perception,
        # LOS required but no occlusion trace = sees through walls.
        lambda: _example_perception(line_of_sight_required=True, occlusion_policy="none")),
    "PressureModel": (
        validate_pressure_model, _example_pressure,
        # non-telemetry pressure with zero value = no active pressure.
        lambda: _example_pressure(pressure_type="contact_pressure", pressure_value=0.0)),
    "BehaviorProfile": (
        validate_behavior_profile, _example_behavior_profile,
        # unknown encounter archetype rejected.
        lambda: _example_behavior_profile(encounter_archetype="not_an_archetype")),
    "NPCBehaviorState": (
        validate_behavior_state, _example_behavior_state,
        # unknown current_state rejected.
        lambda: _example_behavior_state(current_state="teleporting")),
    "BehaviorScenario": (
        validate_behavior_scenario, _example_behavior_scenario,
        # a scenario with no expected pressure events is not behavior.
        lambda: _example_behavior_scenario(expected_pressure_events=[])),
    "BehaviorTelemetry": (
        lambda o, strict=False: validate_telemetry(o, strict=strict, require_completion=True),
        _example_telemetry,
        # completion telemetry missing the pressure event.
        lambda: {"events": [{"event_type": "behavior.scenario.started"},
                            {"event_type": "behavior.scenario.completed"}]}),
    "BehaviorCompletionReport": (
        validate_completion_report, _example_completion,
        # success class with zero NPCs / zero pressure = fake green.
        lambda: _example_completion(npc_count=0, pressure_events_seen=0)),
}
