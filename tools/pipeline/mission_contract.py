#!/usr/bin/env python3
"""mission_contract.py — WorldForge v1.3 MissionForge contract (keystone).

The single source of truth for the v1.3 mission layer: the mission archetype
taxonomy, the objective-graph schema, biome-placement rules, and the completion /
reward / save-load / playtest sub-contracts. Every mission validator and the
PlaytestForge harness import from here so the 8 v1.3 lanes agree on ONE schema.

A mission loop is NOT a new world — it is a biome-aware *purpose* layered over an
existing generated map: it composes the map's level-design navigation graph
(player_start, primary/secondary POI, safe/danger zones — see
generate_level_design.py output) + entity anchors + a Runtime StateForge scenario
(state change + save/load) + v1.2 mesh/Megascans/Houdini dependencies into a
playable, provable objective graph.

Layout owned by this contract:
    procedural/definitions/missions/archetypes/<archetype>.yaml  — archetype intent
    procedural/generated/missions/<mission_id>/mission.json       — composed mission
    procedural/generated/worldforge_mission_catalog.json          — mission catalog
    procedural/reports/missions/<command>/...                     — command reports
    tests/fixtures/invalid_missions/*.json                        — known-bad fixtures
"""

from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[2]
MISSION_SCHEMA_VERSION = "1.3"

# ---------------------------------------------------------------------------
# Repo-relative locations
# ---------------------------------------------------------------------------
MISSION_ARCHETYPES_REL = "procedural/definitions/missions/archetypes"
MISSION_GENERATED_REL = "procedural/generated/missions"
MISSION_CATALOG_REL = "procedural/generated/worldforge_mission_catalog.json"
MISSION_REPORTS_REL = "procedural/reports/missions"
MISSION_INVALID_FIXTURES_REL = "tests/fixtures/invalid_missions"

# ---------------------------------------------------------------------------
# Mission archetypes (brief §1) — six, frozen. Data-driven definitions live in
# procedural/definitions/missions/archetypes/<id>.yaml; this tuple is the frozen
# name set the generator/validators check against.
# ---------------------------------------------------------------------------
MISSION_ARCHETYPES = (
    "disable_site",
    "recover_resource",
    "survey_landmark",
    "clear_hazard",
    "restore_power",
    "extract_cache",
)

# Biome families a mission may target (matches v1.1; desert is the separate
# regression pack, so mission_loop_world targets the 5 non-desert families).
BIOME_FAMILIES = (
    "temperate_forest", "alpine_snow", "volcanic_ashlands",
    "wetland_mire", "alien_crystal_badlands",
)
DESERT_BIOME = "desert"

# ---------------------------------------------------------------------------
# Objective-graph node roles (brief §2). The mission objective graph is layered
# on the level-design navigation graph (which supplies positions).
# ---------------------------------------------------------------------------
NODE_START = "start_anchor"
NODE_PRIMARY_POI = "primary_poi"
NODE_OBJECTIVE = "objective_anchor"
NODE_COMPLETION = "completion"
NODE_ROLES = (NODE_START, NODE_PRIMARY_POI, NODE_OBJECTIVE, NODE_COMPLETION)

# ---------------------------------------------------------------------------
# Mission contract fields (brief §2). Required in STRICT=1.
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = (
    "mission_id",
    "mission_archetype",
    "biome_family",
    "source_map",          # the biome map this mission is layered over
    "start_anchor",
    "primary_poi",
    "objective_anchors",
    "required_route",
    "hazard_zones",
    "safe_zones",
    "state_keys",
    "completion_conditions",
    "failure_conditions",
    "reward_outputs",
    "save_load_contract",
    "playtest_contract",
    "mesh_dependencies",
    "ownership_class",
)
OPTIONAL_FIELDS = (
    "schema_version", "display_name", "seed", "optional_route",
    "encounter_zones", "resource_nodes", "entity_anchors",
    "scenario_id", "provenance", "provenance_id", "registry_id",
    "source_hash", "notes", "budget_class",
)
# Fields the generator adds at write time (legitimate on a materialized mission).
GENERATED_ADDED_FIELDS = ("mission_path", "registry_owner")
KNOWN_FIELDS = tuple(REQUIRED_FIELDS) + OPTIONAL_FIELDS + GENERATED_ADDED_FIELDS

# Required keys inside sub-contracts.
ROUTE_REQUIRED = ("from_node", "to_node", "waypoints", "length_cm", "avoids_hazards")
COMPLETION_REQUIRED = ("condition_id", "state_key", "operator", "threshold", "at_node")
REWARD_REQUIRED = ("reward_id", "reward_type", "fires_on")
SAVE_LOAD_REQUIRED = ("persist_keys", "expect_roundtrip")
PLAYTEST_REQUIRED = ("modes", "expected_completion", "max_route_length_cm")

COMPLETION_OPERATORS = (">=", "<=", "==", ">", "<")
REWARD_TYPES = ("progression_marker", "resource_grant", "unlock", "state_flag")

# ---------------------------------------------------------------------------
# Biome-aware placement rules (brief §4). Each returns (ok, detail) given a
# composed mission + its source level-design; a rule failing is a placement fail.
# These are intentionally about ROUTE/READABILITY validity, not art.
# ---------------------------------------------------------------------------
# Minimum fraction of a route that must stay OUT of hazard bounds.
ROUTE_HAZARD_CLEARANCE = 0.5
# A mission's objective must sit within the terrain bounds by this margin (cm).
BOUNDS_MARGIN_CM = 100.0

# Per-biome placement constraints (brief §4 examples), machine-checkable.
BIOME_PLACEMENT_RULES = {
    "wetland_mire": {"requires_route_when_water": True, "max_slope_deg": 40},
    "alpine_snow": {"max_slope_deg": 35, "forbid_buried": True},
    "volcanic_ashlands": {"hazard_may_pressure_not_block": True},
    "temperate_forest": {"require_navigation_cue": True},
    "alien_crystal_badlands": {"require_readable_budget_safe": True},
}


# ---------------------------------------------------------------------------
# Archetype loading (data-driven, brief §1)
# ---------------------------------------------------------------------------
def archetype_path(archetype, repo_root=REPO_ROOT):
    return Path(repo_root) / MISSION_ARCHETYPES_REL / (archetype + ".yaml")


def load_archetype(archetype, repo_root=REPO_ROOT):
    """Load one archetype definition. Returns (data, error)."""
    if yaml is None:
        return None, "PyYAML required"
    p = archetype_path(archetype, repo_root)
    if not p.is_file():
        return None, "archetype not found: {}".format(p)
    try:
        with p.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}, None
    except Exception as exc:  # pragma: no cover
        return None, "archetype unparseable: {}".format(exc)


def load_all_archetypes(repo_root=REPO_ROOT):
    out = {}
    for a in MISSION_ARCHETYPES:
        data, err = load_archetype(a, repo_root)
        if data is not None:
            out[a] = data
    return out


# ---------------------------------------------------------------------------
# Mission loading
# ---------------------------------------------------------------------------
def mission_path(mission_id, repo_root=REPO_ROOT):
    return Path(repo_root) / MISSION_GENERATED_REL / mission_id / "mission.json"


def load_mission(mission_id, repo_root=REPO_ROOT):
    import json
    p = mission_path(mission_id, repo_root)
    if not p.is_file():
        return None, "mission not found: {}".format(p)
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as exc:  # pragma: no cover
        return None, "mission unparseable: {}".format(exc)


def unknown_fields(mission):
    return [k for k in (mission or {}) if k not in KNOWN_FIELDS]


def missing_required_fields(mission):
    m = mission or {}
    return [k for k in REQUIRED_FIELDS if k not in m or m.get(k) in (None, "")]


# ---------------------------------------------------------------------------
# Geometry helpers (abstract navigation — no UE)
# ---------------------------------------------------------------------------
def dist2d(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def point_in_bounds(pt, bounds):
    """bounds = {min:[x,y,..], max:[x,y,..]}."""
    mn, mx = bounds.get("min"), bounds.get("max")
    if not mn or not mx:
        return False
    return mn[0] <= pt[0] <= mx[0] and mn[1] <= pt[1] <= mx[1]


def segment_intersects_bounds(p0, p1, bounds, samples=16):
    """Approx: True if any sampled point on segment p0->p1 lies inside bounds."""
    mn, mx = bounds.get("min"), bounds.get("max")
    if not mn or not mx:
        return False
    for i in range(samples + 1):
        t = i / samples
        x = p0[0] + (p1[0] - p0[0]) * t
        y = p0[1] + (p1[1] - p0[1]) * t
        if mn[0] <= x <= mx[0] and mn[1] <= y <= mx[1]:
            return True
    return False
