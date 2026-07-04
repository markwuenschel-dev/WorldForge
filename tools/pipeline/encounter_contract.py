#!/usr/bin/env python3
"""encounter_contract.py — WorldForge v1.4 EncounterForge contract (Agent 1).

Single source of truth for the encounter data model: archetypes, spawn groups,
the deterministic abstract pressure model, difficulty bands, and pacing metrics.
Every encounter tool imports this as `import encounter_contract as EC`.

Structural sibling of mission_contract.py (v1.3). Encounters layer on top of
the 60 generated missions: every encounter links to exactly one mission and
consumes its routes/anchors/zones. No UE dependency — pure data + math.
"""

from pathlib import Path

import mission_contract as MC

REPO_ROOT = Path(__file__).resolve().parents[2]

ENCOUNTER_SCHEMA_VERSION = "1.4"
SPAWN_GROUP_SCHEMA_VERSION = "1.4"

# --- repo-relative locations ------------------------------------------------
ENCOUNTER_ARCHETYPES_REL = "procedural/definitions/encounters/archetypes"
ENCOUNTER_GENERATED_REL = "procedural/generated/encounters"
ENCOUNTER_CATALOG_REL = "procedural/generated/worldforge_encounter_catalog.json"
ENCOUNTER_REPORTS_REL = "procedural/reports/encounters"
ENCOUNTER_INVALID_FIXTURES_REL = "tests/fixtures/invalid_encounters"
PLAYTEST_BETA_REPORTS_REL = "procedural/reports/encounters/playtest_beta"
BALANCE_REPORTS_REL = "procedural/reports/encounters/balance"

# --- enumerations -------------------------------------------------------------
ENCOUNTER_ARCHETYPES = (
    "guarded_objective",
    "patrol_route",
    "ambush_choke",
    "hazard_field",
    "resource_contest",
    "defensive_holdout",
    "roaming_threat",
    "extraction_pressure",
)

ENCOUNTER_PROFILES = ("light_pressure", "standard_pressure")

DIFFICULTY_BANDS = ("trivial", "light", "standard", "hard", "extreme", "invalid")

# Bands each profile is allowed to classify into (v1.4 targets).
PROFILE_BAND_TARGETS = {
    "light_pressure": ("light", "standard"),
    "standard_pressure": ("standard", "hard"),
}

ROLE_TAGS = (
    "melee_pressure",
    "ranged_pressure",
    "area_denial",
    "patroller",
    "guard",
    "ambusher",
    "elite_placeholder",
    "ambient_threat",
    "hazard_proxy",
)

HAZARD_TYPES = (
    "heat",
    "lava_adjacent",
    "deep_water",
    "mud_slow",
    "whiteout_exposure",
    "fall_risk",
    "toxic_ash",
    "crystal_resonance",
    "ambush_visibility_loss",
)

SPAWN_POLICIES = ("on_activation", "pre_placed", "staged_waves")

# Biome → allowed hazard types (biome-specific encounter rules, brief §13).
BIOME_HAZARD_TYPES = {
    "temperate_forest": ("fall_risk", "ambush_visibility_loss", "mud_slow"),
    "alpine_snow": ("whiteout_exposure", "fall_risk", "ambush_visibility_loss"),
    "volcanic_ashlands": ("heat", "lava_adjacent", "toxic_ash"),
    "wetland_mire": ("deep_water", "mud_slow", "ambush_visibility_loss"),
    "alien_crystal_badlands": ("crystal_resonance", "fall_risk", "ambush_visibility_loss"),
}

# Biome → cover mesh families that are compatible (consumes v1.2 substrate).
BIOME_COVER_FAMILIES = {
    "temperate_forest": ("encounter_cover", "rock_outcrop"),
    "alpine_snow": ("encounter_cover", "rock_outcrop"),
    "volcanic_ashlands": ("encounter_cover", "rock_outcrop", "industrial_debris"),
    "wetland_mire": ("encounter_cover", "rock_outcrop"),
    "alien_crystal_badlands": ("encounter_cover", "rock_outcrop"),
}

# --- encounter_definition contract -------------------------------------------
REQUIRED_FIELDS = (
    "encounter_id",
    "mission_id",
    "pack_id",
    "biome_family",
    "mission_archetype",
    "encounter_archetype",
    "encounter_profile",
    "difficulty_band",
    "pressure_budget",
    "pacing_target",
    "spawn_groups",
    "spawn_anchors",
    "cover_anchors",
    "safe_zones",
    "danger_zones",
    "approach_routes",
    "escape_routes",
    "objective_links",
    "state_keys",
    "activation_conditions",
    "completion_conditions",
    "failure_conditions",
    "reward_hooks",
    "save_load_contract",
    "playtest_contract",
    "mesh_dependencies",
    "budget_class",
    "ownership_class",
)

OPTIONAL_FIELDS = (
    "schema_version",
    "display_name",
    "seed",
    "patrol_anchors",
    "idle_anchors",
    "ambush_anchors",
    "hazard_zones",
    "resource_nodes",
    "megascans_dependencies",
    "visual_marker_requirements",
    "bypass_allowed",
    "provenance",
    "provenance_id",
    "registry_id",
    "source_hash",
    "notes",
)

GENERATED_ADDED_FIELDS = ("encounter_path", "registry_owner")

KNOWN_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS + GENERATED_ADDED_FIELDS

# --- spawn_group contract -----------------------------------------------------
SPAWN_GROUP_REQUIRED = (
    "spawn_group_id",
    "encounter_id",
    "archetype_tag",
    "faction_tag",
    "role_tags",
    "count_min",
    "count_max",
    "pressure_value",
    "difficulty_value",
    "spawn_policy",
    "spawn_anchor_ids",
    "allowed_spawn_zones",
    "forbidden_spawn_zones",
    "activation_condition",
    "state_keys",
    "budget_class",
)

SPAWN_GROUP_OPTIONAL = ("despawn_condition", "notes")
SPAWN_GROUP_KNOWN = SPAWN_GROUP_REQUIRED + SPAWN_GROUP_OPTIONAL

# Sub-contract key tuples (mirror MC.*_REQUIRED conventions).
ROUTE_REQUIRED = ("route_id", "kind", "waypoints", "length_cm")
CONDITION_REQUIRED = ("condition_id", "state_key", "operator", "threshold")
REWARD_HOOK_REQUIRED = ("reward_id", "reward_type", "fires_on")
SAVE_LOAD_REQUIRED = ("persist_keys", "expect_roundtrip")
PLAYTEST_REQUIRED = ("modes", "expected_completion", "max_pressure_band")
PACING_TARGET_REQUIRED = ("min_first_pressure_cm", "max_route_blockage_ratio",
                          "min_cover_per_pressure_point")

# --- pressure model (deterministic, abstract — brief §10) ---------------------
ROLE_PRESSURE_WEIGHTS = {
    "melee_pressure": 1.0,
    "ranged_pressure": 1.3,
    "area_denial": 1.6,
    "patroller": 0.9,
    "guard": 1.0,
    "ambusher": 1.4,
    "elite_placeholder": 2.5,
    "ambient_threat": 0.5,
    "hazard_proxy": 0.8,
}

HAZARD_PRESSURE_WEIGHTS = {
    "heat": 2.5,
    "lava_adjacent": 3.5,
    "deep_water": 3.0,
    "mud_slow": 1.5,
    "whiteout_exposure": 2.5,
    "fall_risk": 2.0,
    "toxic_ash": 3.0,
    "crystal_resonance": 2.5,
    "ambush_visibility_loss": 2.0,
}

# Biome baseline visibility pressure (fog/sightline proxy from env profiles).
BIOME_VISIBILITY_PRESSURE = {
    "temperate_forest": 2.0,
    "alpine_snow": 3.0,
    "volcanic_ashlands": 3.5,
    "wetland_mire": 3.0,
    "alien_crystal_badlands": 2.5,
}

# Pressure budgets per encounter profile.
PROFILE_PRESSURE_BUDGETS = {
    "light_pressure": 24.0,
    "standard_pressure": 40.0,
}

# Band thresholds over total pressure score. Order matters (ascending).
BAND_THRESHOLDS = (
    ("trivial", 0.0),
    ("light", 8.0),
    ("standard", 18.0),
    ("hard", 32.0),
    ("extreme", 48.0),
)
INVALID_PRESSURE_ABOVE = 64.0

PRESSURE_RADIUS_CM = 2500.0   # a spawn anchor pressures route points within this
COVER_NEAR_CM = 1500.0        # cover counts as "near" a pressure point within this
SAFE_START_CLEARANCE_CM = 2000.0   # spawn anchors must keep this from player start
OBJECTIVE_CLEARANCE_CM = 800.0     # spawn anchors must keep this from objective
                                   # interaction anchors unless explicitly allowed


def densify_route(waypoints, step_cm=1000.0):
    """Interpolate a route polyline to <=step_cm segments.

    v1.3 routes carry only their endpoints; pressure/pacing metrics need the
    full corridor, so every route consumer goes through this densifier.
    """
    pts = [w for w in (waypoints or []) if w]
    if len(pts) < 2:
        return pts
    out = [pts[0]]
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        seg = MC.dist2d(a, b)
        n = max(int(seg // step_cm), 1)
        for k in range(1, n + 1):
            t = k / n
            out.append([a[0] + (b[0] - a[0]) * t,
                        a[1] + (b[1] - a[1]) * t,
                        (a[2] if len(a) > 2 else 0.0)])
    return out


def spawn_pressure(spawn_groups):
    """Pressure from spawn groups: avg count x max role weight x difficulty."""
    total = 0.0
    for g in spawn_groups or []:
        roles = g.get("role_tags") or []
        weight = max((ROLE_PRESSURE_WEIGHTS.get(r, 0.0) for r in roles), default=0.0)
        avg = ((g.get("count_min") or 0) + (g.get("count_max") or 0)) / 2.0
        total += avg * weight * float(g.get("difficulty_value") or 0.0)
    return round(total, 3)


def hazard_pressure(hazard_zones):
    total = 0.0
    for hz in hazard_zones or []:
        total += HAZARD_PRESSURE_WEIGHTS.get(hz.get("hazard_type"), 0.0)
    return round(total, 3)


def route_pressure(encounter, mission):
    """Fraction of the mission's required route inside pressure radius x 10."""
    waypoints = densify_route(
        ((mission or {}).get("required_route") or {}).get("waypoints"))
    anchors = [a.get("world_position") for a in encounter.get("spawn_anchors") or []]
    anchors = [a for a in anchors if a]
    if not waypoints or not anchors:
        return 0.0
    contested = 0
    for wp in waypoints:
        if any(MC.dist2d(wp, a) <= PRESSURE_RADIUS_CM for a in anchors):
            contested += 1
    return round(10.0 * contested / len(waypoints), 3)


def visibility_pressure(encounter):
    biome = encounter.get("biome_family")
    base = BIOME_VISIBILITY_PRESSURE.get(biome, 0.0)
    cover = len(encounter.get("cover_anchors") or [])
    # cover mitigates visibility exposure, floor at 25% of base
    mitigated = max(base - 0.35 * cover, base * 0.25)
    return round(mitigated, 3)


def density_pressure(encounter):
    zones = max(len(encounter.get("danger_zones") or []), 1)
    count = 0
    for g in encounter.get("spawn_groups") or []:
        count += g.get("count_max") or 0
    return round(1.5 * count / zones / 2.0, 3)


def pressure_components(encounter, mission):
    return {
        "spawn_pressure": spawn_pressure(encounter.get("spawn_groups")),
        "hazard_pressure": hazard_pressure(encounter.get("hazard_zones")),
        "route_pressure": route_pressure(encounter, mission),
        "visibility_pressure": visibility_pressure(encounter),
        "density_pressure": density_pressure(encounter),
    }


def total_pressure(components):
    return round(sum(components.values()), 3)


def classify_band(score):
    """Map a total pressure score to a difficulty band ('invalid' when out of range)."""
    if score is None or score < 0 or score > INVALID_PRESSURE_ABOVE:
        return "invalid"
    band = "trivial"
    for name, floor in BAND_THRESHOLDS:
        if score >= floor:
            band = name
    return band


def band_allowed_for_profile(band, profile):
    return band in PROFILE_BAND_TARGETS.get(profile, ())


# --- pacing metrics (brief §11) -----------------------------------------------
def _positions(encounter, key):
    return [a.get("world_position") for a in encounter.get(key) or []
            if a.get("world_position")]


def pacing_metrics(encounter, mission):
    """Deterministic pacing metrics computed from encounter + mission geometry."""
    start = ((mission or {}).get("start_anchor") or {}).get("world_position")
    objective = None
    for oa in (mission or {}).get("objective_anchors") or []:
        objective = oa.get("world_position")
        break
    spawns = _positions(encounter, "spawn_anchors")
    covers = _positions(encounter, "cover_anchors")
    safes = [s.get("world_position") for s in encounter.get("safe_zones") or []
             if s.get("world_position")]
    waypoints = densify_route(
        ((mission or {}).get("required_route") or {}).get("waypoints"))

    first_pressure = min((MC.dist2d(start, s) for s in spawns), default=None) \
        if start else None
    between = []
    ordered = sorted(spawns, key=lambda s: MC.dist2d(start, s)) if start else spawns
    for i in range(1, len(ordered)):
        between.append(MC.dist2d(ordered[i - 1], ordered[i]))
    objective_pressure = min((MC.dist2d(objective, s) for s in spawns), default=None) \
        if objective else None
    safe_after = min((MC.dist2d(s, z) for s in spawns for z in safes), default=None)

    contested = 0
    for wp in waypoints:
        if any(MC.dist2d(wp, s) <= PRESSURE_RADIUS_CM for s in spawns):
            contested += 1
    blockage = round(contested / len(waypoints), 3) if waypoints else 0.0

    near_cover = 0
    for s in spawns:
        if any(MC.dist2d(s, c) <= COVER_NEAR_CM for c in covers):
            near_cover += 1
    cover_density = round(near_cover / len(spawns), 3) if spawns else 0.0

    hazard_overlap = 0
    hz_bounds = [h.get("bounds") for h in encounter.get("hazard_zones") or []
                 if h.get("bounds")]
    for wp in waypoints:
        if any(MC.point_in_bounds(wp, b) for b in hz_bounds):
            hazard_overlap += 1
    hazard_ratio = round(hazard_overlap / len(waypoints), 3) if waypoints else 0.0

    return {
        "distance_from_spawn_to_first_pressure": first_pressure,
        "distance_between_pressure_points": [round(d, 1) for d in between],
        "objective_pressure_distance": objective_pressure,
        "safe_zone_distance_after_pressure": safe_after,
        "encounter_count_per_mission": 1,
        "pressure_peak_count": len(spawns),
        "route_blockage_ratio": blockage,
        "optional_route_ratio": 1.0 if (mission or {}).get("optional_route") else 0.0,
        "cover_density_near_pressure": cover_density,
        "hazard_overlap_ratio": hazard_ratio,
    }


# --- io helpers (mirror mission_contract) --------------------------------------
def archetype_path(archetype, repo_root=REPO_ROOT):
    return repo_root / ENCOUNTER_ARCHETYPES_REL / "{}.yaml".format(archetype)


def load_archetype(archetype, repo_root=REPO_ROOT):
    import yaml
    p = archetype_path(archetype, repo_root)
    if not p.is_file():
        return None, "archetype spec missing: {}".format(p)
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001
        return None, "archetype unparseable: {}".format(exc)


def load_all_archetypes(repo_root=REPO_ROOT):
    out = {}
    for a in ENCOUNTER_ARCHETYPES:
        data, err = load_archetype(a, repo_root)
        if data is not None:
            out[a] = data
    return out


def encounter_path(encounter_id, repo_root=REPO_ROOT):
    return repo_root / ENCOUNTER_GENERATED_REL / encounter_id / "encounter.json"


def load_encounter(encounter_id, repo_root=REPO_ROOT):
    import json
    p = encounter_path(encounter_id, repo_root)
    if not p.is_file():
        return None, "encounter.json missing: {}".format(p)
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001
        return None, "encounter.json unparseable: {}".format(exc)


def unknown_fields(encounter):
    return sorted(k for k in (encounter or {}) if k not in KNOWN_FIELDS)


def missing_required_fields(encounter):
    return sorted(k for k in REQUIRED_FIELDS if k not in (encounter or {}))


def spawn_group_unknown_fields(group):
    return sorted(k for k in (group or {}) if k not in SPAWN_GROUP_KNOWN)


def spawn_group_missing_fields(group):
    return sorted(k for k in SPAWN_GROUP_REQUIRED if k not in (group or {}))
