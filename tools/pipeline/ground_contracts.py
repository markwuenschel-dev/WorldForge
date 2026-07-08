#!/usr/bin/env python3
"""ground_contracts.py — WorldForge v1.6z GroundTraversalForge contract spine.

The full strict schema surface NPCForge builds on. One module, one section per
contract, each with REQUIRED_FIELDS, a validate_* function returning check tuples,
and a canonical _example. The completion report keeps its own module
(ground_completion_contract); everything else lives here so the spine is one
import. Taxonomy (traversal modes, statuses, failure owners) is defined here and
re-exported by ground_taxonomy.

Contracts:
  GroundTraversalScenario   validate_scenario
  GroundPawnProfile         validate_pawn_profile
  WalkabilityReport         validate_walkability
  NavmeshProbeReport        validate_navmesh_probe
  GroundRouteGraph          validate_route_graph
  GroundRoutePlan           validate_route_plan
  GroundTraversalTelemetry  validate_telemetry
"""

from pathlib import Path

from failure_codes import FailureCode
import runtime_schema as RS
import ground_completion_contract as GC  # re-use traversal modes + completion

REPO_ROOT = Path(__file__).resolve().parents[2]
C = FailureCode

# --------------------------------------------------------------------------- #
# Taxonomy
# --------------------------------------------------------------------------- #
TRAVERSAL_MODES = GC.TRAVERSAL_MODES
GROUNDED_SUCCESS_MODES = GC.GROUNDED_SUCCESS_MODES
FORBIDDEN_SUCCESS_MODES = GC.FORBIDDEN_SUCCESS_MODES
GROUND_COMPLETION_CLASSES = GC.COMPLETION_CLASSES

WALKABILITY_STATUS = ("pass", "degraded", "fail")
NAVMESH_STATUS = ("valid", "unavailable", "insufficient", "path_missing")
NAVMESH_RUNTIME_MODES = ("Static", "Dynamic", "DynamicModifiersOnly", "unknown")
ROUTE_GRAPH_STATUS = ("valid", "partial", "invalid")
ROUTE_PLAN_STATUS = ("valid", "blocked", "invalid")
GROUND_FAILURE_OWNERS = GC.FAILURE_OWNERS
RESULT_STATUS = ("pass", "fail", "skipped", "unavailable")

# Generated / report roots.
SCENARIO_GENERATED_REL = "procedural/generated/ground/scenarios"
PAWN_PROFILE_GENERATED_REL = "procedural/generated/ground/pawns"
WALKABILITY_REPORTS_REL = "procedural/reports/ground/walkability"
NAVMESH_PROBE_REPORTS_REL = "procedural/reports/ground/navmesh"
ROUTE_GRAPH_GENERATED_REL = "procedural/generated/ground/route_graphs"
ROUTE_PLAN_GENERATED_REL = "procedural/generated/ground/route_plans"


def _num(obj, field, code, prefix, allow_zero=True):
    return RS.check_positive_number(obj, field, code, prefix=prefix, allow_zero=allow_zero)


# --------------------------------------------------------------------------- #
# GroundTraversalScenario
# --------------------------------------------------------------------------- #
SCENARIO_SCHEMA_VERSION = "wf.ground.scenario.v1"
FALLBACK_POLICIES = ("navmesh_then_route_graph", "route_graph_only",
                     "navmesh_only", "manual_waypoint_only")
SCENARIO_REQUIRED = (
    "scenario_id", "runtime_scenario_id", "pack", "map_id", "mission_id", "encounter_id",
    "biome", "mission_archetype", "pressure_profile", "seed", "pawn_profile_id",
    "start_anchor_id", "objective_anchor_id", "expected_interaction_id", "expected_state_keys",
    "expected_save_load_keys", "allowed_traversal_modes", "preferred_traversal_mode",
    "fallback_policy", "capsule_radius", "capsule_half_height", "max_slope_degrees",
    "max_step_height", "min_route_width", "objective_approach_radius", "walkable_surface_policy",
    "navmesh_policy", "route_graph_policy", "cover_avoidance_policy", "hazard_avoidance_policy",
    "timeout_seconds", "save_load_required", "telemetry_required", "created_by", "created_at",
)
SCENARIO_ALLOWED = SCENARIO_REQUIRED + ("meta", "schema_version", "report_type")


def validate_scenario(obj, strict=False):
    ch = RS.check_required(obj, SCENARIO_REQUIRED, C.GROUND_TRAVERSAL_SCHEMA_FAILURE)
    ch += RS.check_no_unknown(obj, SCENARIO_ALLOWED, C.GROUND_TRAVERSAL_SCHEMA_FAILURE, strict)
    ch += RS.check_enum(obj, "preferred_traversal_mode", TRAVERSAL_MODES, C.GROUND_MODE_SELECTION_FAILURE)
    ch += RS.check_enum(obj, "fallback_policy", FALLBACK_POLICIES, C.GROUND_MODE_SELECTION_FAILURE)
    if not isinstance(obj, dict):
        return ch
    modes = obj.get("allowed_traversal_modes")
    ch.append(("scenario::allowed_modes_list", isinstance(modes, list) and len(modes) > 0,
               "allowed_traversal_modes must be a non-empty list", C.GROUND_MODE_SELECTION_FAILURE))
    if isinstance(modes, list):
        bad = [m for m in modes if m not in TRAVERSAL_MODES]
        ch.append(("scenario::allowed_modes_valid", not bad,
                   "unknown traversal modes: {}".format(bad), C.GROUND_MODE_SELECTION_FAILURE))
        # A v1.6y success scenario may NOT allow flight/teleport as a success mode.
        forbidden = [m for m in modes if GC.is_forbidden_mode(m)]
        ch.append(("scenario::no_flight_teleport_as_success", not forbidden,
                   "allowed_traversal_modes contains forbidden success mode(s): {}".format(forbidden),
                   C.GROUND_TRAVERSAL_MODE_FORBIDDEN))
    ch.append(("scenario::preferred_is_grounded",
               GC.is_grounded_mode(obj.get("preferred_traversal_mode")),
               "preferred_traversal_mode must be a grounded mode", C.GROUND_TRAVERSAL_MODE_FORBIDDEN))
    for f in ("capsule_radius", "capsule_half_height", "max_slope_degrees", "max_step_height",
              "min_route_width", "objective_approach_radius", "timeout_seconds"):
        ch += _num(obj, f, C.GROUND_TRAVERSAL_SCHEMA_FAILURE, "scenario::", allow_zero=False)
    for f in ("expected_state_keys", "expected_save_load_keys"):
        ch.append(("scenario::{}_list".format(f), isinstance(obj.get(f), list),
                   "{} must be a list".format(f), C.GROUND_TRAVERSAL_SCHEMA_FAILURE))
    return ch


def _example_scenario(**over):
    d = {
        "scenario_id": "gs_x", "runtime_scenario_id": "rt_enc_lp_M__light_pressure", "pack": "encounter_loop_world",
        "map_id": "M", "mission_id": "m", "encounter_id": "n/a", "biome": "b",
        "mission_archetype": "disable_site", "pressure_profile": "light_pressure", "seed": 0,
        "pawn_profile_id": "wf_grounded_default", "start_anchor_id": "spawn_player_primary",
        "objective_anchor_id": "disable_target", "expected_interaction_id": "int_x",
        "expected_state_keys": ["mission_complete"], "expected_save_load_keys": ["mission_complete"],
        "allowed_traversal_modes": ["grounded_worldforge_route", "grounded_manual_waypoint"],
        "preferred_traversal_mode": "grounded_worldforge_route", "fallback_policy": "route_graph_only",
        "capsule_radius": 34.0, "capsule_half_height": 88.0, "max_slope_degrees": 44.0,
        "max_step_height": 45.0, "min_route_width": 120.0, "objective_approach_radius": 200.0,
        "walkable_surface_policy": "trace_down", "navmesh_policy": "probe_only",
        "route_graph_policy": "required", "cover_avoidance_policy": "avoid",
        "hazard_avoidance_policy": "avoid", "timeout_seconds": 180.0, "save_load_required": True,
        "telemetry_required": True, "created_by": "worldforge.v1.6z", "created_at": "2026-07-08T00:00:00+00:00",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# GroundPawnProfile
# --------------------------------------------------------------------------- #
PAWN_SCHEMA_VERSION = "wf.ground.pawn_profile.v1"
PAWN_REQUIRED = (
    "pawn_profile_id", "pawn_class", "controller_class", "movement_component",
    "capsule_radius", "capsule_half_height", "max_walk_speed", "acceleration",
    "braking_deceleration", "max_slope_degrees", "max_step_height", "gravity_enabled",
    "ground_constraint_enabled", "flight_enabled", "teleport_enabled", "collision_channel",
    "nav_agent_radius", "nav_agent_height", "interaction_component", "telemetry_component",
)
PAWN_ALLOWED = PAWN_REQUIRED + ("meta", "schema_version")


def validate_pawn_profile(obj, strict=False):
    ch = RS.check_required(obj, PAWN_REQUIRED, C.GROUND_PAWN_PROFILE_FAILURE)
    ch += RS.check_no_unknown(obj, PAWN_ALLOWED, C.GROUND_PAWN_PROFILE_FAILURE, strict)
    if not isinstance(obj, dict):
        return ch
    # Grounded-success invariants.
    ch.append(("pawn::gravity_on", obj.get("gravity_enabled") is True,
               "grounded pawn must have gravity_enabled=true", C.GROUND_PAWN_PROFILE_FAILURE))
    ch.append(("pawn::ground_constraint_on", obj.get("ground_constraint_enabled") is True,
               "grounded pawn must have ground_constraint_enabled=true", C.GROUND_PAWN_PROFILE_FAILURE))
    ch.append(("pawn::flight_off", obj.get("flight_enabled") is False,
               "grounded pawn must have flight_enabled=false", C.GROUND_FLIGHT_COUNTED_AS_SUCCESS))
    ch.append(("pawn::teleport_off", obj.get("teleport_enabled") is False,
               "grounded pawn must have teleport_enabled=false", C.GROUND_TELEPORT_COUNTED_AS_SUCCESS))
    for f in ("capsule_radius", "capsule_half_height", "max_walk_speed", "max_slope_degrees",
              "max_step_height", "nav_agent_radius", "nav_agent_height"):
        ch += _num(obj, f, C.GROUND_PAWN_PROFILE_FAILURE, "pawn::", allow_zero=False)
    return ch


def _example_pawn(**over):
    d = {
        "pawn_profile_id": "wf_grounded_default", "pawn_class": "AWFGroundedRuntimePawn",
        "controller_class": "PlayerController", "movement_component": "CharacterMovementComponent",
        "capsule_radius": 34.0, "capsule_half_height": 88.0, "max_walk_speed": 600.0,
        "acceleration": 2048.0, "braking_deceleration": 2048.0, "max_slope_degrees": 44.0,
        "max_step_height": 45.0, "gravity_enabled": True, "ground_constraint_enabled": True,
        "flight_enabled": False, "teleport_enabled": False, "collision_channel": "Pawn",
        "nav_agent_radius": 34.0, "nav_agent_height": 176.0,
        "interaction_component": "UWFGroundInteractionComponent",
        "telemetry_component": "UWFGroundTelemetryComponent",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# WalkabilityReport
# --------------------------------------------------------------------------- #
WALKABILITY_SCHEMA_VERSION = "wf.ground.walkability_report.v1"
WALKABILITY_REQUIRED = (
    "report_id", "map_id", "biome", "terrain_surfaces_checked", "walkable_surfaces",
    "blocked_surfaces", "unknown_surfaces", "slope_failures", "step_failures",
    "capsule_clearance_failures", "cover_intrusions", "hazard_intrusions",
    "objective_access_failures", "safe_zone_access_failures", "danger_zone_access_failures",
    "navmesh_presence", "navmesh_coverage_ratio", "worldforge_route_coverage_ratio",
    "status", "failure_codes", "created_at",
)
WALKABILITY_ALLOWED = WALKABILITY_REQUIRED + ("meta", "schema_version", "report_type",
                                              "spawn_walkable", "objective_walkable",
                                              "spawn_to_objective_walkable", "samples")


def validate_walkability(obj, strict=False):
    ch = RS.check_required(obj, WALKABILITY_REQUIRED, C.GROUND_WALKABILITY_ANALYSIS_FAILURE)
    ch += RS.check_no_unknown(obj, WALKABILITY_ALLOWED, C.GROUND_WALKABILITY_ANALYSIS_FAILURE, strict)
    ch += RS.check_enum(obj, "status", WALKABILITY_STATUS, C.GROUND_WALKABILITY_ANALYSIS_FAILURE)
    if not isinstance(obj, dict):
        return ch
    ch.append(("walk::codes_list", isinstance(obj.get("failure_codes"), list),
               "failure_codes must be a list", C.GROUND_WALKABILITY_ANALYSIS_FAILURE))
    # A pass must have >0 walkable surfaces and no zero-record success.
    checked = obj.get("terrain_surfaces_checked")
    walkable = obj.get("walkable_surfaces")
    ch.append(("walk::checked_positive", isinstance(checked, int) and checked > 0,
               "terrain_surfaces_checked must be >0 (no zero-record analysis)",
               C.GROUND_WALKABILITY_ANALYSIS_FAILURE))
    if obj.get("status") == "pass":
        ch.append(("walk::pass_has_walkable", isinstance(walkable, int) and walkable > 0,
                   "walkability status=pass with zero walkable_surfaces", C.GROUND_SURFACE_NOT_WALKABLE))
        ch.append(("walk::pass_no_codes", len(obj.get("failure_codes") or []) == 0,
                   "walkability status=pass must carry no failure_codes",
                   C.GROUND_WALKABILITY_ANALYSIS_FAILURE))
    elif obj.get("status") == "fail":
        ch.append(("walk::fail_has_code", len(obj.get("failure_codes") or []) > 0,
                   "walkability status=fail must carry a failure_code",
                   C.GROUND_WALKABILITY_ANALYSIS_FAILURE))
    for f in ("navmesh_coverage_ratio", "worldforge_route_coverage_ratio"):
        v = obj.get(f)
        ch.append(("walk::{}_ratio".format(f), isinstance(v, (int, float)) and 0.0 <= v <= 1.0,
                   "{} must be in [0,1]".format(f), C.GROUND_WALKABILITY_ANALYSIS_FAILURE))
    return ch


def _example_walkability(**over):
    d = {
        "report_id": "walk:M", "map_id": "M", "biome": "b", "terrain_surfaces_checked": 400,
        "walkable_surfaces": 372, "blocked_surfaces": 21, "unknown_surfaces": 7,
        "slope_failures": 3, "step_failures": 1, "capsule_clearance_failures": 2,
        "cover_intrusions": 0, "hazard_intrusions": 0, "objective_access_failures": 0,
        "safe_zone_access_failures": 0, "danger_zone_access_failures": 0, "navmesh_presence": True,
        "navmesh_coverage_ratio": 0.0, "worldforge_route_coverage_ratio": 0.93, "status": "pass",
        "failure_codes": [], "created_at": "live", "spawn_walkable": True,
        "objective_walkable": True, "spawn_to_objective_walkable": True,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# NavmeshProbeReport
# --------------------------------------------------------------------------- #
NAVMESH_SCHEMA_VERSION = "wf.ground.navmesh_probe_report.v1"
NAVMESH_REQUIRED = (
    "report_id", "map_id", "navmesh_present", "navmesh_bounds_present",
    "navmesh_runtime_generation_mode", "navmesh_tiles_count", "navmesh_coverage_ratio",
    "spawn_on_navmesh", "objective_on_navmesh", "path_exists", "path_length", "path_status",
    "navmesh_errors", "recommended_action", "status", "failure_codes",
)
NAVMESH_ALLOWED = NAVMESH_REQUIRED + ("meta", "schema_version", "report_type", "created_at")


def validate_navmesh_probe(obj, strict=False):
    ch = RS.check_required(obj, NAVMESH_REQUIRED, C.GROUND_NAVMESH_PROBE_FAILURE)
    ch += RS.check_no_unknown(obj, NAVMESH_ALLOWED, C.GROUND_NAVMESH_PROBE_FAILURE, strict)
    ch += RS.check_enum(obj, "status", NAVMESH_STATUS, C.GROUND_NAVMESH_PROBE_FAILURE)
    ch += RS.check_enum(obj, "path_status", NAVMESH_STATUS, C.GROUND_NAVMESH_PROBE_FAILURE)
    ch += RS.check_enum(obj, "navmesh_runtime_generation_mode", NAVMESH_RUNTIME_MODES,
                        C.GROUND_NAVMESH_PROBE_FAILURE)
    if not isinstance(obj, dict):
        return ch
    ch.append(("nav::errors_list", isinstance(obj.get("navmesh_errors"), list),
               "navmesh_errors must be a list", C.GROUND_NAVMESH_PROBE_FAILURE))
    ch.append(("nav::codes_list", isinstance(obj.get("failure_codes"), list),
               "failure_codes must be a list", C.GROUND_NAVMESH_PROBE_FAILURE))
    # Honesty: a report that says path_exists must have a status of valid.
    if obj.get("path_exists") is True:
        ch.append(("nav::path_status_valid", obj.get("path_status") == "valid",
                   "path_exists=true but path_status != valid", C.GROUND_NAVMESH_PROBE_FAILURE))
    else:
        ch.append(("nav::no_path_owns_code", len(obj.get("failure_codes") or []) > 0,
                   "path_exists=false must own a failure_code (e.g. NAVMESH_PATH_MISSING)",
                   C.GROUND_NAVMESH_PATH_MISSING))
    return ch


def _example_navmesh(**over):
    # The empirically true state for these headless maps.
    d = {
        "report_id": "nav:M", "map_id": "M", "navmesh_present": True, "navmesh_bounds_present": True,
        "navmesh_runtime_generation_mode": "Dynamic", "navmesh_tiles_count": 0,
        "navmesh_coverage_ratio": 0.0, "spawn_on_navmesh": False, "objective_on_navmesh": False,
        "path_exists": False, "path_length": 0.0, "path_status": "path_missing",
        "navmesh_errors": ["no runtime tiles generated in -game"],
        "recommended_action": "use grounded route substrate (navmesh unavailable headless)",
        "status": "path_missing", "failure_codes": [C.GROUND_NAVMESH_PATH_MISSING], "created_at": "live",
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# GroundRouteGraph
# --------------------------------------------------------------------------- #
ROUTE_GRAPH_SCHEMA_VERSION = "wf.ground.route_graph.v1"
ROUTE_GRAPH_REQUIRED = (
    "route_graph_id", "map_id", "nodes", "edges", "walkable_surface_refs", "anchor_refs",
    "spawn_node", "objective_node", "cover_avoidance_zones", "hazard_avoidance_zones",
    "safe_zone_refs", "danger_zone_refs", "route_widths", "slope_samples", "step_samples",
    "capsule_clearance_samples", "validation_status", "failure_codes",
)
ROUTE_GRAPH_ALLOWED = ROUTE_GRAPH_REQUIRED + ("meta", "schema_version", "created_at", "created_by")
EDGE_REQUIRED = ("edge_id", "from_node", "to_node", "distance", "min_clearance", "max_slope",
                 "max_step", "cover_intrusion", "hazard_intrusion", "walkability_status")


def validate_route_graph(obj, strict=False):
    ch = RS.check_required(obj, ROUTE_GRAPH_REQUIRED, C.GROUND_ROUTE_GRAPH_FAILURE)
    ch += RS.check_no_unknown(obj, ROUTE_GRAPH_ALLOWED, C.GROUND_ROUTE_GRAPH_FAILURE, strict)
    ch += RS.check_enum(obj, "validation_status", ROUTE_GRAPH_STATUS, C.GROUND_ROUTE_GRAPH_FAILURE)
    if not isinstance(obj, dict):
        return ch
    nodes = obj.get("nodes")
    edges = obj.get("edges")
    ch.append(("graph::nodes_list", isinstance(nodes, list) and len(nodes) >= 2,
               "route graph must have >=2 nodes", C.GROUND_ROUTE_NODE_INVALID))
    ch.append(("graph::edges_list", isinstance(edges, list) and len(edges) >= 1,
               "route graph must have >=1 edge", C.GROUND_ROUTE_EDGE_INVALID))
    node_ids = {n.get("node_id") for n in nodes} if isinstance(nodes, list) else set()
    if isinstance(nodes, list):
        ch.append(("graph::spawn_node_present", obj.get("spawn_node") in node_ids,
                   "spawn_node not among nodes", C.GROUND_ROUTE_NODE_INVALID))
        ch.append(("graph::objective_node_present", obj.get("objective_node") in node_ids,
                   "objective_node not among nodes", C.GROUND_ROUTE_NODE_INVALID))
    if isinstance(edges, list):
        for i, e in enumerate(edges):
            miss = [f for f in EDGE_REQUIRED if not isinstance(e, dict) or f not in e]
            ch.append(("graph::edge{}_fields".format(i), not miss,
                       "edge {} missing {}".format(i, miss), C.GROUND_ROUTE_EDGE_INVALID))
            if isinstance(e, dict):
                ends_ok = e.get("from_node") in node_ids and e.get("to_node") in node_ids
                ch.append(("graph::edge{}_endpoints".format(i), ends_ok,
                           "edge {} endpoints not in nodes".format(i), C.GROUND_ROUTE_EDGE_INVALID))
    return ch


def _node(nid, x, y, z, kind="walkable"):
    return {"node_id": nid, "x": x, "y": y, "z": z, "kind": kind, "walkable": True}


def _edge(eid, a, b, dist):
    return {"edge_id": eid, "from_node": a, "to_node": b, "distance": dist, "min_clearance": 120.0,
            "max_slope": 12.0, "max_step": 20.0, "cover_intrusion": False, "hazard_intrusion": False,
            "walkability_status": "pass"}


def _example_route_graph(**over):
    d = {
        "route_graph_id": "rg:M", "map_id": "M",
        "nodes": [_node("spawn", 0, 0, 90, "spawn"), _node("mid", 450, 0, 92),
                  _node("obj", 900, 0, 94, "objective")],
        "edges": [_edge("e0", "spawn", "mid", 450.0), _edge("e1", "mid", "obj", 450.0)],
        "walkable_surface_refs": ["surf_0"], "anchor_refs": ["spawn_player_primary", "disable_target"],
        "spawn_node": "spawn", "objective_node": "obj", "cover_avoidance_zones": [],
        "hazard_avoidance_zones": [], "safe_zone_refs": [], "danger_zone_refs": [],
        "route_widths": [120.0, 120.0], "slope_samples": [10.0, 12.0], "step_samples": [15.0, 20.0],
        "capsule_clearance_samples": [130.0, 128.0], "validation_status": "valid", "failure_codes": [],
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# GroundRoutePlan
# --------------------------------------------------------------------------- #
ROUTE_PLAN_SCHEMA_VERSION = "wf.ground.route_plan.v1"
ROUTE_PLAN_REQUIRED = (
    "route_plan_id", "scenario_id", "map_id", "mission_id", "encounter_id", "traversal_mode",
    "route_nodes", "runtime_waypoints", "expected_distance", "max_allowed_detour_ratio",
    "objective_approach_radius", "line_trace_checks", "capsule_sweep_checks", "slope_checks",
    "step_checks", "cover_avoidance_checks", "hazard_avoidance_checks", "status", "failure_codes",
)
ROUTE_PLAN_ALLOWED = ROUTE_PLAN_REQUIRED + ("meta", "schema_version", "created_at", "created_by")


def validate_route_plan(obj, strict=False):
    ch = RS.check_required(obj, ROUTE_PLAN_REQUIRED, C.GROUND_ROUTE_GRAPH_FAILURE)
    ch += RS.check_no_unknown(obj, ROUTE_PLAN_ALLOWED, C.GROUND_ROUTE_GRAPH_FAILURE, strict)
    ch += RS.check_enum(obj, "traversal_mode", TRAVERSAL_MODES, C.GROUND_MODE_SELECTION_FAILURE)
    ch += RS.check_enum(obj, "status", ROUTE_PLAN_STATUS, C.GROUND_ROUTE_GRAPH_FAILURE)
    if not isinstance(obj, dict):
        return ch
    wp = obj.get("runtime_waypoints")
    rn = obj.get("route_nodes")
    ch.append(("plan::waypoints_list", isinstance(wp, list) and len(wp) >= 2,
               "route plan needs >=2 runtime_waypoints (multi-node)", C.GROUND_ROUTE_UNREACHABLE))
    ch.append(("plan::nodes_list", isinstance(rn, list) and len(rn) >= 2,
               "route plan needs >=2 route_nodes", C.GROUND_ROUTE_NODE_INVALID))
    ch.append(("plan::mode_grounded_for_valid",
               obj.get("status") != "valid" or GC.is_grounded_mode(obj.get("traversal_mode")),
               "a valid route plan must use a grounded traversal mode", C.GROUND_TRAVERSAL_MODE_FORBIDDEN))
    if obj.get("status") == "blocked":
        ch.append(("plan::blocked_has_code", len(obj.get("failure_codes") or []) > 0,
                   "blocked route plan must own a failure_code", C.GROUND_ROUTE_UNREACHABLE))
    return ch


def _example_route_plan(**over):
    d = {
        "route_plan_id": "rp:x", "scenario_id": "gs_x", "map_id": "M", "mission_id": "m",
        "encounter_id": "n/a", "traversal_mode": "grounded_worldforge_route",
        "route_nodes": ["spawn", "mid", "obj"],
        "runtime_waypoints": [{"x": 0, "y": 0, "z": 90}, {"x": 450, "y": 0, "z": 92},
                              {"x": 900, "y": 0, "z": 94}],
        "expected_distance": 900.0, "max_allowed_detour_ratio": 1.6, "objective_approach_radius": 200.0,
        "line_trace_checks": ["ground", "objective_los"], "capsule_sweep_checks": ["corridor"],
        "slope_checks": ["<=44"], "step_checks": ["<=45"], "cover_avoidance_checks": ["clear"],
        "hazard_avoidance_checks": ["clear"], "status": "valid", "failure_codes": [],
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# GroundTraversalTelemetry
# --------------------------------------------------------------------------- #
TELEMETRY_SCHEMA_VERSION = "wf.ground.telemetry.v1"
GROUND_EVENT_TYPES = (
    "ground.scenario.started", "ground.map.loaded", "ground.pawn.spawned", "ground.pawn.possessed",
    "ground.mode.selected", "ground.navmesh.probed", "ground.navmesh.used",
    "ground.route_graph.generated", "ground.worldforge_route.used", "ground.route.started",
    "ground.waypoint.reached", "ground.slope.checked", "ground.step.checked",
    "ground.capsule_clearance.checked", "ground.cover.avoided", "ground.hazard.avoided",
    "ground.route.blocked", "ground.objective.approached", "ground.objective.reached",
    "ground.interaction.started", "ground.interaction.succeeded", "ground.state.changed",
    "ground.save.completed", "ground.reload.verified", "ground.scenario.completed",
    "ground.scenario.failed",
)
COMPLETION_REQUIRED_EVENTS = (
    "ground.mode.selected", "ground.route.started", "ground.objective.reached",
    "ground.interaction.succeeded", "ground.state.changed", "ground.save.completed",
    "ground.reload.verified", "ground.scenario.completed",
)


def validate_telemetry(obj, strict=False, require_completion=False):
    ch = []
    ok_top = isinstance(obj, dict) and isinstance(obj.get("events"), list)
    ch.append(("tel::has_events", ok_top, "telemetry must carry an events list",
               C.GROUND_REPORT_MISSING_TELEMETRY))
    if not ok_top:
        return ch
    evs = obj["events"]
    seen = set()
    for i, e in enumerate(evs):
        et = e.get("event_type") if isinstance(e, dict) else None
        ok = et in GROUND_EVENT_TYPES
        ch.append(("tel::event{}_type".format(i), ok,
                   "event {} type {!r} not in registry".format(i, et), C.GROUND_TRAVERSAL_SCHEMA_FAILURE))
        if ok:
            seen.add(et)
    if require_completion:
        missing = [e for e in COMPLETION_REQUIRED_EVENTS if e not in seen]
        ch.append(("tel::completion_events_present", not missing,
                   "grounded completion telemetry missing events: {}".format(missing),
                   C.GROUND_REPORT_MISSING_TELEMETRY))
    return ch


def _example_telemetry(**over):
    d = {"report_type": TELEMETRY_SCHEMA_VERSION, "runtime_scenario_id": "x",
         "traversal_mode": "grounded_manual_waypoint",
         "events": [{"event_type": t, "frame": i} for i, t in enumerate(COMPLETION_REQUIRED_EVENTS)]}
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# Registry of all contracts, for the schema validator + fuzz harness.
# --------------------------------------------------------------------------- #
CONTRACTS = {
    "GroundTraversalScenario": (validate_scenario, _example_scenario,
                                lambda: _example_scenario(preferred_traversal_mode="continuous_flight",
                                                          allowed_traversal_modes=["continuous_flight"])),
    "GroundPawnProfile": (validate_pawn_profile, _example_pawn,
                          lambda: _example_pawn(flight_enabled=True, gravity_enabled=False)),
    "WalkabilityReport": (validate_walkability, _example_walkability,
                          lambda: _example_walkability(status="pass", walkable_surfaces=0)),
    "NavmeshProbeReport": (validate_navmesh_probe, _example_navmesh,
                           lambda: _example_navmesh(path_exists=True, path_status="path_missing")),
    "GroundRouteGraph": (validate_route_graph, _example_route_graph,
                         lambda: _example_route_graph(edges=[])),
    "GroundRoutePlan": (validate_route_plan, _example_route_plan,
                        lambda: _example_route_plan(traversal_mode="continuous_flight", status="valid")),
    "GroundTraversalTelemetry": (validate_telemetry, _example_telemetry,
                                 lambda: {"events": [{"event_type": "bogus.event"}]}),
}
