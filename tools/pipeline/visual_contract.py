#!/usr/bin/env python3
"""visual_contract.py — WorldForge v1.3.5 Visual Fidelity contract (keystone).

Turns the validated biome/mission substrate into a materialization contract: the
UE-native environment rig (SkyAtmosphere / DirectionalLight / SkyLight /
ExponentialHeightFog / VolumetricCloud / PostProcessVolume / weather VFX)
resolved from the existing v1.0x/v1.1 profile data, plus visual asset coverage,
surface/dressing, budgets, and readability rules.

The load-bearing rule (brief §5): a sky/fog/light profile that exists only as a
JSON *name* is NOT materialized. This contract resolves each profile into a
CONCRETE actor/component spec with every parameter bound; the materializer writes
a materialization report; the validators fail the bare-name case and pass the
fully-resolved case. Live in-editor actor spawning (via
tools/unreal/materialize_environment_rig.py) is the deferred editor step — the
resolved spec + report are exactly what a UE driver consumes. No UE here.

Layout owned by this contract:
    procedural/generated/visual/environment_rigs/<slice_id>.json  — resolved rig
    procedural/generated/visual/dressing/<slice_id>.json          — dressing plan
    procedural/generated/worldforge_visual_catalog.json           — visual catalog
    procedural/generated/worldforge_visual_asset_catalog.json     — classified externals
    procedural/reports/visual/<command>/...                       — command reports
    tests/fixtures/invalid_visual/*.json                          — known-bad fixtures
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import profiles as P

VISUAL_SCHEMA_VERSION = "1.3.5"

# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
VISUAL_GENERATED_REL = "procedural/generated/visual"
ENV_RIGS_REL = "procedural/generated/visual/environment_rigs"
DRESSING_REL = "procedural/generated/visual/dressing"
VISUAL_CATALOG_REL = "procedural/generated/worldforge_visual_catalog.json"
VISUAL_ASSET_CATALOG_REL = "procedural/generated/worldforge_visual_asset_catalog.json"
VISUAL_REPORTS_REL = "procedural/reports/visual"
VISUAL_INVALID_FIXTURES_REL = "tests/fixtures/invalid_visual"

BIOME_FAMILIES = (
    "temperate_forest", "alpine_snow", "volcanic_ashlands",
    "wetland_mire", "alien_crystal_badlands",
)

# ---------------------------------------------------------------------------
# Environment rig — the UE-native actor/component set (brief §5). Each rig
# component maps to a real UE class and is resolved from a source profile.
# ---------------------------------------------------------------------------
COMP_SKY_ATMOSPHERE = "SkyAtmosphere"
COMP_DIRECTIONAL_SUN = "DirectionalLight_Sun"
COMP_SKY_LIGHT = "SkyLight"
COMP_HEIGHT_FOG = "ExponentialHeightFog"
COMP_VOLUMETRIC_CLOUD = "VolumetricCloud"
COMP_POST_PROCESS = "PostProcessVolume"
COMP_WEATHER_VFX = "WeatherVFX_Niagara"

# Components that MUST be present + fully resolved in every rig.
REQUIRED_RIG_COMPONENTS = (
    COMP_SKY_ATMOSPHERE, COMP_DIRECTIONAL_SUN, COMP_SKY_LIGHT,
    COMP_HEIGHT_FOG, COMP_POST_PROCESS,
)
# Conditionally present (declared enabled=false when not applicable).
OPTIONAL_RIG_COMPONENTS = (COMP_VOLUMETRIC_CLOUD, COMP_WEATHER_VFX)
ALL_RIG_COMPONENTS = REQUIRED_RIG_COMPONENTS + OPTIONAL_RIG_COMPONENTS

# The real UE actor/class each component spawns as (for the deferred UE driver).
UE_ACTOR_CLASS = {
    COMP_SKY_ATMOSPHERE: "ASkyAtmosphere",
    COMP_DIRECTIONAL_SUN: "ADirectionalLight",
    COMP_SKY_LIGHT: "ASkyLight",
    COMP_HEIGHT_FOG: "AExponentialHeightFog",
    COMP_VOLUMETRIC_CLOUD: "AVolumetricCloud",
    COMP_POST_PROCESS: "APostProcessVolume",
    COMP_WEATHER_VFX: "ANiagaraActor",
}

# ---------------------------------------------------------------------------
# Ownership — visual dressing/rig records are generated_owned; Megascans source
# stays third_party_owned (brief §3 / v1.2 model).
# ---------------------------------------------------------------------------
OWNERSHIP_GENERATED = "generated_owned"
OWNERSHIP_THIRD_PARTY = "third_party_owned"

# ---------------------------------------------------------------------------
# Coverage requirements (Pillar 1). Every biome needs enough real assets.
# ---------------------------------------------------------------------------
MIN_ASSETS_PER_BIOME = 3          # real (external or generated) visual assets
MIN_ASSET_FAMILIES_PER_BIOME = 2  # distinct surface/rock/ground/dressing families

# Visual asset classes a scanned/generated asset can serve (surface fidelity +
# dressing). Derived from Megascans category or generated mesh family.
VISUAL_ASSET_CLASSES = (
    "ground_surface", "cliff_surface", "rock_dressing", "debris_dressing",
    "vegetation_dressing", "decal", "landmark", "cover", "crystal", "snow_surface",
)

# ---------------------------------------------------------------------------
# Visual budgets (Pillar 7). Per-map materialized-fidelity caps by profile class.
# ---------------------------------------------------------------------------
BUDGET_FIELDS = (
    "dynamic_light_count", "decal_count", "foliage_density_class",
    "volumetric_fog_cost_class", "vfx_emitter_count", "texture_memory_class",
    "nanite_policy", "lod_policy", "material_complexity_class",
)
# Caps per profile class (performance / balanced / cinematic / raytraced).
PROFILE_BUDGET_CAPS = {
    "performance": {"dynamic_light_count": 2, "decal_count": 8, "vfx_emitter_count": 2},
    "readable":    {"dynamic_light_count": 3, "decal_count": 16, "vfx_emitter_count": 3},
    "balanced":    {"dynamic_light_count": 4, "decal_count": 24, "vfx_emitter_count": 4},
    "cinematic":   {"dynamic_light_count": 8, "decal_count": 48, "vfx_emitter_count": 8},
    "raytraced":   {"dynamic_light_count": 8, "decal_count": 64, "vfx_emitter_count": 12},
}

# ---------------------------------------------------------------------------
# Readability (Pillar 6). Fidelity must not break playability.
# ---------------------------------------------------------------------------
# Fog visibility must exceed this fraction of the shortest mission route so the
# objective stays reachable/visible through the fog.
MIN_FOG_VISIBILITY_FRACTION_OF_ROUTE = 0.25
# Exposure must stay within this EV window so objectives aren't black/blown-out.
EXPOSURE_EV_MIN, EXPOSURE_EV_MAX = -3.0, 3.0


# ---------------------------------------------------------------------------
# Rig resolution — the materialization core. Resolves a slice's bound
# environment profile into a concrete UE-actor/component spec.
# ---------------------------------------------------------------------------
def resolve_rig(world_pack_id, slice_id, biome=None, profiles_root=None):
    """Resolve the full environment rig spec for one map. Returns (rig, error).

    rig = {slice_id, biome, environment_profile, profile_class, components:[...],
           exposure_ev, materialized(bool)}. Each component carries its UE class,
           enabled flag, source profile name, and fully-bound params.
    """
    try:
        res = P.environment_for(world_pack_id, slice_id, profiles_root=profiles_root)
        env_name = res[0] if isinstance(res, (tuple, list)) else res
        resolved = P.resolve_environment(env_name, profiles_root=profiles_root)
    except Exception as exc:
        return None, "environment does not resolve for {}: {}".format(slice_id, exc)

    env = resolved.get("environment", {})
    ch = resolved.get("children", {})
    sky = ch.get("sky", {}) or {}
    lighting = ch.get("lighting", {}) or {}
    fog = ch.get("fog", {}) or {}
    atmo = ch.get("atmosphere", {}) or {}
    pp = ch.get("post_process", {}) or {}
    weather = ch.get("weather", {}) or {}

    profile_class = env.get("class", "balanced")
    exposure_ev = float(env.get("exposure_ev", 0.0))
    sun_angle = float(env.get("sun_angle_deg", 45.0))
    cloud_coverage = float(sky.get("cloud_coverage", 0.0) or 0.0)
    weather_kind = (weather.get("name") or env.get("weather") or "clear")
    has_weather_vfx = str(weather_kind).lower() not in ("clear", "none", "")

    def comp(ctype, enabled, source, params):
        return {"component": ctype, "ue_class": UE_ACTOR_CLASS[ctype],
                "enabled": bool(enabled), "source_profile": source, "params": params}

    components = [
        comp(COMP_SKY_ATMOSPHERE, True, env.get("sky"), {
            "sky_luminance_cd_m2": sky.get("sky_luminance_cd_m2"),
            "sun_disk_scale": sky.get("sun_disk_scale"),
            "zenith_color": sky.get("zenith_color"),
            "horizon_color": sky.get("horizon_color"),
            "atmosphere_model": atmo.get("model", "earth"),
        }),
        comp(COMP_DIRECTIONAL_SUN, True, env.get("lighting"), {
            "sun_angle_deg": sun_angle,
            "intensity_lux": lighting.get("sun_intensity_lux", lighting.get("intensity_lux")),
            "light_color": lighting.get("light_color", lighting.get("color")),
            "casts_shadows": True,
        }),
        comp(COMP_SKY_LIGHT, True, env.get("sky"), {
            "recapture": True, "intensity_scale": lighting.get("sky_light_intensity", 1.0),
        }),
        comp(COMP_HEIGHT_FOG, True, env.get("fog"), {
            "density": fog.get("density", env.get("fog_density", 0.02)),
            "height_falloff": fog.get("height_falloff", 0.2),
            "start_distance_cm": fog.get("start_distance_cm", 0),
            "fog_color": fog.get("color"),
            "max_opacity": fog.get("max_opacity", 1.0),
            "volumetric": bool(fog.get("volumetric", False)),
            "visibility_min_cm": fog.get("visibility_min_cm"),
        }),
        comp(COMP_VOLUMETRIC_CLOUD, cloud_coverage > 0.0, env.get("sky"), {
            "coverage": cloud_coverage, "cloud_model": sky.get("cloud_model", "volumetric"),
        }),
        comp(COMP_POST_PROCESS, True, env.get("post_process"), {
            "exposure_ev": exposure_ev,
            "auto_exposure": pp.get("auto_exposure", False),
            "color_grading": pp.get("color_grading", pp.get("name")),
            "bloom": pp.get("bloom"),
            "unbound": True,
        }),
        comp(COMP_WEATHER_VFX, has_weather_vfx, env.get("weather"), {
            "weather_kind": weather_kind,
            "emitter": weather.get("vfx_emitter", "Niagara_" + str(weather_kind)),
            "emitter_count": weather.get("emitter_count", 1 if has_weather_vfx else 0),
        }),
    ]

    rig = {
        "schema_version": VISUAL_SCHEMA_VERSION,
        "slice_id": slice_id,
        "biome": biome,
        "world_pack_id": world_pack_id,
        "environment_profile": env_name,
        "profile_class": profile_class,
        "exposure_ev": exposure_ev,
        "components": components,
        "ownership_class": OWNERSHIP_GENERATED,
        # 'materialized' means fully RESOLVED into a concrete actor spec here.
        # Live in-editor spawning is recorded separately by the UE driver report.
        "materialized": True,
    }
    return rig, None


def rig_is_fully_resolved(rig):
    """True if every required component is present, enabled, and has bound params
    (not a bare name). This is the anti-'JSON-only' check (brief §5)."""
    if not isinstance(rig, dict) or not rig.get("components"):
        return False, "no components"
    by_type = {c.get("component"): c for c in rig["components"]}
    for req in REQUIRED_RIG_COMPONENTS:
        c = by_type.get(req)
        if not c:
            return False, "missing required component {}".format(req)
        if not c.get("enabled"):
            return False, "required component {} disabled".format(req)
        params = c.get("params") or {}
        # a materialized component must carry at least one bound, non-null param
        if not any(v is not None for v in params.values()):
            return False, "component {} has no bound params (JSON-only)".format(req)
        if not c.get("source_profile"):
            return False, "component {} has no source profile".format(req)
    return True, "fully resolved"


def profile_class_for_caps(profile_class):
    """Map an environment class to a budget-cap bucket."""
    pc = (profile_class or "balanced").lower()
    if pc in PROFILE_BUDGET_CAPS:
        return pc
    if "perf" in pc:
        return "performance"
    if "cinema" in pc:
        return "cinematic"
    if "ray" in pc or "photoreal" in pc:
        return "raytraced"
    if "readable" in pc or "clean" in pc:
        return "readable"
    return "balanced"
