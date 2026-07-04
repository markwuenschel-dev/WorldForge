#!/usr/bin/env python3
"""mesh_contract.py — WorldForge v1.2 MeshForge Intake contract (single source of truth).

This module is the KEYSTONE of the v1.2 MeshForge Intake layer. Every mesh
validator, generator, catalog tool, and negative fixture imports the taxonomy and
helpers defined here so the 8 v1.2 lanes agree on ONE schema, ONE set of allowed
final roots, and ONE family/source taxonomy. It is deliberately dependency-light
(PyYAML for definition loading only) and additive to the existing v0.8 generated-
asset intake sidecar — it does NOT replace generated_asset_registry.py; it is the
broader, source-agnostic, multi-family catalog the brief calls for.

Scope (brief §3): this is INTAKE, not full MeshForge. WorldForge does not care
whether a mesh came from Houdini, Blender, an internal Python recipe, an Unreal
script, or a future external generator. It cares whether the final asset is
owned, registered, provenanced, budgeted, validated, package-safe, repairable,
destroyable, and eligible for the intended consumers (PCG, biomes, POIs).

Layout owned by this contract:
    procedural/definitions/mesh_assets/<asset_id>.yaml     — human/recipe intent
    procedural/generated/mesh_assets/<asset_id>/descriptor.json — materialized record
    procedural/generated/worldforge_mesh_catalog.json      — catalog (source of truth)
    procedural/reports/mesh/<command>/...                  — command reports
    tests/fixtures/invalid_mesh_assets/*.yaml              — known-bad fixtures
"""

from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - import guard mirrored across pipeline
    yaml = None

REPO_ROOT = Path(__file__).resolve().parents[2]

# Bump when the mesh contract shape changes in a breaking way.
MESH_SCHEMA_VERSION = "1.2"

# ---------------------------------------------------------------------------
# Repo-relative locations owned by the MeshForge Intake layer
# ---------------------------------------------------------------------------
MESH_DEFINITIONS_REL = "procedural/definitions/mesh_assets"
MESH_GENERATED_REL = "procedural/generated/mesh_assets"
MESH_CATALOG_REL = "procedural/generated/worldforge_mesh_catalog.json"
MESH_REPORTS_REL = "procedural/reports/mesh"
MESH_ASSET_REPORTS_REL = "procedural/reports/mesh_assets"
MESH_INVALID_FIXTURES_REL = "tests/fixtures/invalid_mesh_assets"

# ---------------------------------------------------------------------------
# Mesh families (brief §4/§7) — exactly six, frozen.
# ---------------------------------------------------------------------------
MESH_FAMILIES = (
    "rock_outcrop",
    "industrial_debris",
    "traversal_marker",
    "biome_landmark",
    "resource_node",
    "encounter_cover",
)

# Required named variants per family (brief §7). At least 4 assets per family are
# required; these are the canonical variant names the create step draws from.
FAMILY_VARIANTS = {
    "rock_outcrop": (
        "desert_eroded_rock", "forest_mossy_boulder", "alpine_granite_outcrop",
        "volcanic_basalt_spire", "wetland_slick_stone", "alien_crystal_rock",
    ),
    "industrial_debris": (
        "broken_pipe_cluster", "rusted_panel_stack", "collapsed_support_beam",
        "scrap_barrier", "forge_debris_chunk", "industrial_cable_spool",
    ),
    "traversal_marker": (
        "trail_post", "hazard_marker", "route_stone",
        "snow_flag", "marsh_stake", "alien_waypoint_crystal",
    ),
    "biome_landmark": (
        "desert_arch", "forest_dead_tree_cluster", "alpine_ice_monolith",
        "volcanic_basaltshell", "wetland_root_tower", "alien_crystal_obelisk",
    ),
    "resource_node": (
        "ore_cluster", "scrap_cache", "herb_patch_proxy",
        "ice_crystal_node", "sulfur_deposit", "alien_resonance_cluster",
    ),
    "encounter_cover": (
        "low_rock_cover", "scrap_cover_wall", "snow_drift_cover",
        "fallen_tree_cover", "basalt_cover_ridge", "crystal_cover_cluster",
    ),
}

# ---------------------------------------------------------------------------
# Source types (brief §8 + v1.2 addendum §4). Three are required for green; the
# rest are additional intake backends. houdini_generated is a generated backend;
# megascans_library is a THIRD-PARTY external library (different ownership — see
# OWNERSHIP_CLASSES below). Never collapse the two into one generic mesh source.
# ---------------------------------------------------------------------------
SOURCE_TYPES_REQUIRED = ("internal_recipe", "ue_generated", "imported_generated_stub")
SOURCE_TYPES_OPTIONAL = (
    "houdini_generated", "megascans_library",
    "blender_generated", "substance_material_generated", "custom_photogrammetry",
)
SOURCE_TYPES = SOURCE_TYPES_REQUIRED + SOURCE_TYPES_OPTIONAL

# ---------------------------------------------------------------------------
# Ownership classes (v1.2 addendum §3). FOUR explicit, non-collapsible classes.
# The load-bearing rule of the addendum: repair/destroy semantics differ per
# class. Ambiguous ownership fails in STRICT=1.
# ---------------------------------------------------------------------------
OWNERSHIP_GENERATED = "generated_owned"     # WorldForge/controlled-generator output
OWNERSHIP_PROJECT = "project_owned"         # committed/authored project asset
OWNERSHIP_THIRD_PARTY = "third_party_owned"  # external licensed (Megascans/Fab/marketplace)
OWNERSHIP_HUMAN = "human_owned"             # hand-authored local, outside gen lifecycle
OWNERSHIP_CLASSES = (
    OWNERSHIP_GENERATED, OWNERSHIP_PROJECT, OWNERSHIP_THIRD_PARTY, OWNERSHIP_HUMAN,
)

# Which ownership classes repair/destroy MAY touch (only when provenance is
# unambiguous). project_owned needs a special explicit command; third_party and
# human are never touched by ordinary lifecycle.
OWNERSHIP_LIFECYCLE_TOUCHABLE = (OWNERSHIP_GENERATED,)
OWNERSHIP_LIFECYCLE_PROTECTED = (OWNERSHIP_PROJECT, OWNERSHIP_THIRD_PARTY, OWNERSHIP_HUMAN)


def resolve_ownership_class(record):
    """Derive the ownership class of a mesh/asset record.

    Prefers an explicit ``ownership_class`` field; otherwise falls back to the
    v1.2 boolean flags (generated_owned / human_owned / third_party_owned /
    project_owned) so the existing 36-asset generated matrix resolves cleanly.
    Returns None when ownership is ambiguous (a STRICT failure at the call site).
    """
    r = record or {}
    oc = r.get("ownership_class")
    if oc in OWNERSHIP_CLASSES:
        return oc
    flags = {
        OWNERSHIP_THIRD_PARTY: bool(r.get("third_party_owned")),
        OWNERSHIP_HUMAN: bool(r.get("human_owned")),
        OWNERSHIP_PROJECT: bool(r.get("project_owned")),
        OWNERSHIP_GENERATED: bool(r.get("generated_owned")),
    }
    asserted = [k for k, v in flags.items() if v]
    if len(asserted) == 1:
        return asserted[0]
    # Ambiguous: zero or conflicting ownership assertions.
    return None

# ---------------------------------------------------------------------------
# Biome families this catalog can declare compatibility with (matches v1.1).
# ---------------------------------------------------------------------------
BIOME_FAMILIES = (
    "desert",
    "temperate_forest",
    "alpine_snow",
    "volcanic_ashlands",
    "wetland_mire",
    "alien_crystal_badlands",
)

# ---------------------------------------------------------------------------
# PCG eligibility (brief §10)
# ---------------------------------------------------------------------------
PCG_ALLOWED = "pcg_allowed"
PCG_DISALLOWED = "pcg_disallowed"
PCG_CONDITIONAL = "pcg_conditionally_allowed"
PCG_ELIGIBILITY_VALUES = (PCG_ALLOWED, PCG_DISALLOWED, PCG_CONDITIONAL)

# ---------------------------------------------------------------------------
# Budget classes (brief §14). Ordered cheapest -> most expensive.
# ---------------------------------------------------------------------------
BUDGET_CLASSES = ("performance_safe", "balanced", "cinematic", "raytraced_high")
BUDGET_ORDER = {name: i for i, name in enumerate(BUDGET_CLASSES)}

# Rendering-profile caps: the maximum budget class a rendering profile may
# consume. performance_safe profiles cannot consume high-cost mesh sets unless
# explicitly capped (brief §14).
PROFILE_BUDGET_CAP = {
    "performance_safe": "balanced",
    "balanced": "cinematic",
    "high_fidelity": "raytraced_high",
    "cinematic": "raytraced_high",
    "raytraced_high": "raytraced_high",
}

# Budget classes that require an explicit raytracing policy declaration.
RAYTRACING_REQUIRED_BUDGETS = ("raytraced_high",)

# ---------------------------------------------------------------------------
# Final-path policy (brief §6). Ruthless about ownership.
# ---------------------------------------------------------------------------
ALLOWED_FINAL_ROOTS = (
    "/Game/WorldForge/Generated/Meshes/",
    "/Game/WorldForge/Generated/Materials/",
    "/Game/WorldForge/Generated/Metadata/",
)

# Forbidden as FINAL asset paths. Temp/Bake/Intermediate may appear only as
# intermediate/quarantine paths, never as a final asset path.
FORBIDDEN_FINAL_ROOTS = (
    "/Game/HoudiniEngine/Temp",
    "/Game/HoudiniEngine/Bake",
    "Temp/",
    "Bake/",
    "Intermediate/",
    "Saved/",
    "DerivedDataCache/",
    "/Game/ExternalUnowned",
    "/Game/HumanAuthored",
    "/Game/Content/ExternalUnowned",
    "/Game/Content/HumanAuthored",
    "/Plugins/",
    "Plugins/",
)

# Substrings that, if they appear anywhere in a final path, mark it as a
# quarantine/intermediate leak rather than an owned final path.
FORBIDDEN_PATH_SUBSTRINGS = (
    "/Temp/", "/Bake/", "/Intermediate/", "/Saved/", "/DerivedDataCache/",
)

# ---------------------------------------------------------------------------
# Family-specific geometry limits (brief §13). Largest-axis extent in cm.
# (min_extent_cm, max_extent_cm) — an asset outside this window fails unless it
# is a landmark class that explicitly declares a landmark budget.
# ---------------------------------------------------------------------------
FAMILY_BOUNDS_LIMITS_CM = {
    "rock_outcrop": (40.0, 2500.0),
    "industrial_debris": (30.0, 800.0),
    "traversal_marker": (20.0, 350.0),
    "biome_landmark": (400.0, 12000.0),
    "resource_node": (40.0, 700.0),
    "encounter_cover": (60.0, 600.0),
}

# Family-specific required geometry metadata (brief §13 / §28).
#   cover_height_class   — encounter_cover must declare it
#   landmark_budget      — biome_landmark must declare it
#   interaction_clearance_cm — resource_node must declare it
#   route_blocking       — traversal_marker must declare false; industrial_debris
#                          must explicitly declare if collision is player-blocking
FAMILY_REQUIRED_GEOMETRY = {
    "traversal_marker": ("route_blocking",),
    "encounter_cover": ("cover_height_class",),
    "biome_landmark": ("landmark_budget",),
    "resource_node": ("interaction_clearance_cm",),
    "industrial_debris": ("blocking_collision_declared",),
    "rock_outcrop": (),
}

COVER_HEIGHT_CLASSES = ("low", "half", "full")

# ---------------------------------------------------------------------------
# Collision profiles allowed per family (brief §13). A profile outside the
# family's allowed set fails.
# ---------------------------------------------------------------------------
COLLISION_PROFILES = (
    "BlockAll", "BlockAllDynamic", "OverlapAll", "NoCollision",
    "Custom", "SimpleAndComplex",
)
FAMILY_ALLOWED_COLLISION = {
    "rock_outcrop": ("BlockAll", "BlockAllDynamic", "SimpleAndComplex", "Custom"),
    "industrial_debris": ("BlockAll", "BlockAllDynamic", "OverlapAll", "Custom", "SimpleAndComplex"),
    "traversal_marker": ("OverlapAll", "NoCollision", "Custom", "BlockAllDynamic"),
    "biome_landmark": ("BlockAll", "BlockAllDynamic", "SimpleAndComplex", "Custom"),
    "resource_node": ("OverlapAll", "BlockAllDynamic", "Custom"),
    "encounter_cover": ("BlockAll", "BlockAllDynamic", "SimpleAndComplex", "Custom"),
}

# Nanite / LOD / raytracing policy vocabularies (brief §14).
NANITE_POLICIES = ("nanite_enabled", "nanite_disabled", "nanite_not_applicable")
LOD_POLICIES = ("lod_auto", "lod_manual", "lod_not_applicable")
SHADOW_POLICIES = ("shadow_default", "shadow_disabled", "shadow_forced")
RAYTRACING_POLICIES = ("raytracing_default", "raytracing_disabled", "raytracing_forced")
PIVOT_POLICIES = ("base_center", "true_center", "custom")
SCALE_POLICIES = ("uniform", "non_uniform_declared", "locked")

# ---------------------------------------------------------------------------
# Contract field taxonomy (brief §5). These are the fields the mesh-asset
# DEFINITION yaml may declare; unknown top-level fields fail in STRICT=1.
# ---------------------------------------------------------------------------
# Required in STRICT=1 (brief §5 "Strict-mode rules").
REQUIRED_FIELDS = (
    "asset_id",
    "display_name",
    "mesh_family",
    "source_type",
    "source_recipe",
    "source_hash",
    "final_asset_path",
    "generated_owned",
    "human_owned",
    "material_bindings",
    "collision_profile",
    "bounds",
    "pivot_policy",
    "scale_policy",
    "budget_class",
    "pcg_eligibility",
    "biome_compatibility",
)

# All recognised top-level fields (required + optional). Anything outside this in
# STRICT mode is an UNKNOWN_SCHEMA_FIELD failure (brief §5 "unknown fields fail").
OPTIONAL_FIELDS = (
    "schema_version",
    "source_tool_version",
    "intermediate_paths",
    "quarantine_paths",
    "placement_compatibility",
    "poi_compatibility",
    "lod_policy",
    "nanite_policy",
    "shadow_policy",
    "raytracing_policy",
    "package_rules",
    "repair_policy",
    "destroy_policy",
    "inspection_metadata",
    "rendering_budget",
    "source_metadata",   # per-source-type provenance block (brief §8)
    "geometry",          # family-specific geometry metadata (cover height, etc.)
    "notes",
    # v1.2 addendum — ownership-class model + Houdini intake.
    "ownership_class",   # explicit 4-class ownership (addendum §3)
    "third_party_owned", # ownership boolean flags (addendum §3)
    "project_owned",
    "external_licensed",
    "houdini_intake",    # houdini_generated intake block (addendum §5)
)
# Fields the registrar/generator ADDS to the descriptor at materialization time.
# They are legitimate on a descriptor (not on a human-authored definition), so
# unknown-field checks accept them when validating a materialized descriptor.
DESCRIPTOR_ADDED_FIELDS = (
    "definition_path", "descriptor_path", "generated_at_utc", "provenance",
    "provenance_id", "registry_id", "registry_owner", "outputs",
)
KNOWN_FIELDS = tuple(REQUIRED_FIELDS) + OPTIONAL_FIELDS + DESCRIPTOR_ADDED_FIELDS

# Required keys inside a single material_bindings entry (brief §12).
MATERIAL_BINDING_REQUIRED = (
    "slot_name", "material_asset_path", "material_family",
    "biome_compatibility", "rendering_budget_class",
)

# Required keys inside the bounds block (brief §13).
BOUNDS_REQUIRED = ("x_cm", "y_cm", "z_cm")

# Required rendering-budget keys (brief §14).
RENDERING_BUDGET_REQUIRED = (
    "triangle_class", "material_complexity_class", "texture_class",
    "collision_complexity_class", "nanite_policy", "lod_policy",
    "shadow_policy", "raytracing_policy", "pcg_density_class",
    "package_size_class",
)

# Required PCG metadata for pcg_allowed / pcg_conditionally_allowed assets (§10).
PCG_METADATA_REQUIRED = (
    "allowed_biomes", "allowed_poi_classes", "allowed_placement_profiles",
    "slope_limits", "height_limits", "density_class", "collision_policy",
    "avoid_critical_routes",
)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def is_forbidden_final_path(path):
    """True if a path can NEVER be a final asset path (Temp/Bake/plugins/etc.)."""
    p = (path or "").strip()
    if not p:
        return True
    for pre in FORBIDDEN_FINAL_ROOTS:
        if p == pre.rstrip("/") or p.startswith(pre):
            return True
    for sub in FORBIDDEN_PATH_SUBSTRINGS:
        if sub in p:
            return True
    return False


def is_allowed_final_path(path):
    """True if a path is under a WorldForge-owned generated final root."""
    p = (path or "").strip()
    if not p or is_forbidden_final_path(p):
        return False
    return any(p.startswith(root) for root in ALLOWED_FINAL_ROOTS)


def family_of_variant(variant):
    """Return the mesh family a canonical variant name belongs to, or None."""
    for fam, variants in FAMILY_VARIANTS.items():
        if variant in variants:
            return fam
    return None


def budget_within_cap(asset_budget, profile):
    """True if asset_budget is <= the cap a rendering profile may consume."""
    cap = PROFILE_BUDGET_CAP.get(profile)
    if cap is None or asset_budget not in BUDGET_ORDER or cap not in BUDGET_ORDER:
        return False
    return BUDGET_ORDER[asset_budget] <= BUDGET_ORDER[cap]


# ---------------------------------------------------------------------------
# Definition / descriptor loading
# ---------------------------------------------------------------------------
def mesh_definition_path(asset_id, repo_root=REPO_ROOT):
    return Path(repo_root) / MESH_DEFINITIONS_REL / (asset_id + ".yaml")


def mesh_descriptor_path(asset_id, repo_root=REPO_ROOT):
    return Path(repo_root) / MESH_GENERATED_REL / asset_id / "descriptor.json"


def load_mesh_definition(path):
    """Load a mesh-asset definition YAML. Returns (data, error_str)."""
    if yaml is None:
        return None, "PyYAML required (pip install pyyaml)"
    p = Path(path)
    if not p.is_file():
        return None, "definition not found: {}".format(p)
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            return None, "definition is not a mapping: {}".format(p)
        return data, None
    except Exception as exc:  # pragma: no cover
        return None, "definition unparseable: {}".format(exc)


def iter_mesh_definitions(repo_root=REPO_ROOT):
    """Yield (asset_id, path) for every mesh-asset definition on disk."""
    root = Path(repo_root) / MESH_DEFINITIONS_REL
    if not root.is_dir():
        return
    for p in sorted(root.glob("*.yaml")):
        yield p.stem, p


def unknown_fields(definition):
    """Return the top-level definition keys that are not in the known schema."""
    return [k for k in (definition or {}) if k not in KNOWN_FIELDS]


def missing_required_fields(definition):
    """Return required contract fields absent from a definition/descriptor."""
    d = definition or {}
    return [k for k in REQUIRED_FIELDS if k not in d or d.get(k) in (None, "")]
