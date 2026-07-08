#!/usr/bin/env python3
"""runtime_route_contract.py — WorldForge v1.6 RuntimeRoutePlan.

A route plan is the traversal contract: where the pawn spawns, which goal anchors
it must reach, the waypoints between them, and the navmesh/collision requirements
the live run must satisfy. It may be *derived* from the existing mission graph,
but completion is only ever proven by real runtime movement — the plan itself is
necessary, not sufficient. Owns ROUTE_STATUS; the taxonomy imports it here.
"""

from pathlib import Path

from failure_codes import FailureCode
import runtime_schema as RS

REPO_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = "wf.runtime.route_plan.v1"

ROUTE_GENERATED_REL = "procedural/generated/runtime/routes"
ROUTE_CATALOG_REL = "procedural/generated/worldforge_runtime_route_catalog.json"
ROUTE_REPORTS_REL = "procedural/reports/runtime/routes"

# Runtime traversal outcome vocabulary.
ROUTE_STATUS = ("completed", "blocked", "timeout", "unreachable", "pending")

REQUIRED_FIELDS = (
    "route_plan_id",
    "map_id",
    "mission_id",
    "encounter_id",
    "start_anchor_id",
    "goal_anchor_ids",
    "route_waypoints",
    "navmesh_required",
    "collision_required",
    "line_trace_checks",
    "route_width_required",
    "max_allowed_detour_ratio",
    "objective_approach_radius",
    "hazard_avoidance_rules",
    "safe_zone_rules",
    "timeout_seconds",
)

OPTIONAL_FIELDS = ("schema_version", "biome", "mission_archetype",
                   "encounter_profile", "created_by", "created_at")
ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS


def validate_route_plan(obj, strict=False):
    """Return check tuples for one route plan."""
    C = FailureCode
    checks = []
    checks += RS.check_required(obj, REQUIRED_FIELDS, C.RUNTIME_ROUTE_PLAN_SCHEMA_FAILURE)
    checks += RS.check_no_unknown(obj, ALLOWED_FIELDS, C.RUNTIME_ROUTE_PLAN_SCHEMA_FAILURE, strict)
    checks += RS.check_type(obj, "goal_anchor_ids", list, C.RUNTIME_ROUTE_PLAN_FAILURE)
    checks += RS.check_type(obj, "route_waypoints", list, C.RUNTIME_ROUTE_PLAN_FAILURE)
    checks += RS.check_type(obj, "navmesh_required", bool, C.RUNTIME_NAVMESH_MISSING)
    checks += RS.check_type(obj, "collision_required", bool, C.RUNTIME_COLLISION_INVALID)
    checks += RS.check_positive_number(obj, "route_width_required", C.RUNTIME_ROUTE_PLAN_FAILURE)
    checks += RS.check_positive_number(obj, "objective_approach_radius", C.RUNTIME_OBJECTIVE_UNREACHABLE)
    checks += RS.check_positive_number(obj, "timeout_seconds", C.RUNTIME_ROUTE_TIMEOUT)
    checks += RS.check_positive_number(obj, "max_allowed_detour_ratio", C.RUNTIME_ROUTE_PLAN_FAILURE)

    # A plan with no goal and no waypoints cannot describe traversal.
    goals = obj.get("goal_anchor_ids") if isinstance(obj, dict) else None
    wps = obj.get("route_waypoints") if isinstance(obj, dict) else None
    checks.append(("route::has_goal", isinstance(goals, list) and len(goals) > 0,
                   "route plan must declare >=1 goal anchor",
                   C.RUNTIME_OBJECTIVE_UNREACHABLE))
    checks.append(("route::has_waypoints", isinstance(wps, list) and len(wps) >= 2,
                   "route plan must declare >=2 waypoints (start..goal)",
                   C.RUNTIME_WAYPOINT_UNREACHABLE))
    # Each waypoint must be a transform-like point.
    if isinstance(wps, list):
        bad = [i for i, w in enumerate(wps)
               if not (isinstance(w, dict) and all(RS.is_number(w.get(k)) for k in ("x", "y", "z")))]
        checks.append(("route::waypoints_well_formed", not bad,
                       "waypoints with non-numeric x/y/z at indices {}".format(bad[:6]) if bad
                       else "all waypoints have numeric x/y/z",
                       C.RUNTIME_WAYPOINT_UNREACHABLE))
    return checks


def _valid_fixture():
    return {
        "schema_version": SCHEMA_VERSION,
        "route_plan_id": "route_runtime_disable_site_wetland_seed02",
        "map_id": "wetland_mire_basin_reclaimed_seed02",
        "mission_id": "mission_disable_site_wetland_seed02",
        "encounter_id": "enc_wetland_seed02",
        "start_anchor_id": "spawn_player_primary",
        "goal_anchor_ids": ["disable_generator_core"],
        "route_waypoints": [
            {"x": 1024.0, "y": 512.0, "z": 120.0},
            {"x": 1300.0, "y": 580.0, "z": 110.0},
            {"x": 1500.0, "y": 640.0, "z": 96.0},
        ],
        "navmesh_required": True,
        "collision_required": True,
        "line_trace_checks": ["ground", "objective_los"],
        "route_width_required": 120.0,
        "max_allowed_detour_ratio": 1.6,
        "objective_approach_radius": 175.0,
        "hazard_avoidance_rules": [],
        "safe_zone_rules": [],
        "timeout_seconds": 180.0,
    }


if __name__ == "__main__":
    ok = [c for c in validate_route_plan(_valid_fixture(), strict=True) if not c[1]]
    assert not ok, "valid route failed: {}".format(ok)
    broken = _valid_fixture()
    broken["route_waypoints"] = []       # no traversal
    broken["objective_approach_radius"] = 0
    fails = [c for c in validate_route_plan(broken, strict=True) if not c[1]]
    assert any("waypoint" in c[0] for c in fails), "empty route not caught"
    print("OK runtime_route_contract self-check: valid passes, known-bad fails "
          "({} statuses)".format(len(ROUTE_STATUS)))
