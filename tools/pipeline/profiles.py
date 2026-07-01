#!/usr/bin/env python3
"""profiles.py — WorldForge v1.0x shared environment/visual-profile loader.

Single source of truth for reading the environment/visual profile data contract
under ``procedural/definitions/profiles/`` and the per-world-pack binding overlay
under ``procedural/definitions/profiles/bindings/``.

This is the substrate imported by the environment-contract validator (Agent 2)
and, later, by the sky/lighting/fog (Agent 3) and rendering/scalability/ray_tracing
(Agent 6) validators. The public API below is STABLE — Agents 3/6 import:

    from profiles import (
        PROFILE_KINDS, CHILD_KINDS, REQUIRED_FIELDS,
        load_profile, list_profiles, resolve_environment,
        load_bindings, environment_for,
        compat_matrix, incompatible, material_fields, material_diff_count,
        name_matches_class, style_class_compatible,
        ProfileError,
    )

Design notes
------------
* Every loader accepts an optional ``profiles_root`` (and bindings loaders an
  optional ``bindings_path``) so validators / negative fixtures can inject a
  broken tree without disturbing the real data.
* Missing / unparseable inputs raise ``ProfileError`` — callers decide whether
  that is a blocking failure (it always is, in strict mode).
* No implicit fallbacks: ``resolve_environment`` raises if a referenced child is
  missing; it never substitutes a default.
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    raise

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES_ROOT = REPO_ROOT / "procedural" / "definitions" / "profiles"

# The 11 child kinds an environment composes, in a stable order.
CHILD_KINDS = (
    "visual_style",
    "sky",
    "lighting",
    "fog",
    "atmosphere",
    "post_process",
    "time_of_day",
    "weather",
    "rendering",
    "scalability",
    "ray_tracing",
)

# All kinds, including the composite. (11 child kinds + "environment")
PROFILE_KINDS = CHILD_KINDS + ("environment",)

# ---------------------------------------------------------------------------
# Required content fields per kind. A profile missing any of these is a
# contract violation (ENVIRONMENT_PROFILE_FAILURE / <kind>_PROFILE_FAILURE).
# ``name``/``kind``/``description`` are metadata and NOT required content.
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = {
    "visual_style": ("style_class", "contrast_curve", "stylization", "palette"),
    "sky": ("model", "sky_luminance_cd_m2", "sun_disk_scale", "cloud_coverage"),
    "lighting": ("sun_intensity_lux", "sun_color_temp_k", "sky_light_intensity",
                 "shadow_sharpness"),
    "fog": ("density", "height_falloff", "start_distance_cm", "max_opacity"),
    "atmosphere": ("aerosol_density", "rayleigh_scale", "mie_scale", "heat_haze"),
    "post_process": ("exposure_ev", "contrast", "saturation", "color_grade"),
    "time_of_day": ("phase", "sun_angle_deg", "hour", "target_exposure_ev"),
    "weather": ("type", "wind_speed_kph", "particulate_density", "visibility_scale"),
    "rendering": ("rendering_mode", "gi_method", "ray_tracing", "shadow_quality"),
    "scalability": ("tier", "target_fps", "target_platform"),
    "ray_tracing": ("mode", "rt_reflections", "rt_gi"),
    "environment": ("class", "low_visibility") + CHILD_KINDS,
}

# Fields that are metadata, excluded from materiality comparison.
_META_FIELDS = ("name", "kind", "description")

# ---------------------------------------------------------------------------
# Compatibility-matrix tunables (real, checkable thresholds).
# ---------------------------------------------------------------------------
EXPOSURE_TOLERANCE_EV = 1.0     # night/dusk exposure must track its time-of-day
LOW_VISIBILITY_FOG_MIN = 0.5    # low_visibility environments need thick fog

# Behavior classes and the name tokens that must appear in a profile named for
# that class. Used by name_matches_class() to catch mislabeled environments.
CLASS_NAME_TOKENS = {
    "photoreal": ("photoreal",),
    "stylized": ("stylized",),
    "cinematic": ("cinematic",),
    "low_visibility": ("fog", "dust", "low_visibility", "horror"),
    "performance": ("performance",),
    "raytraced": ("raytraced", "ray_traced", "path_traced"),
    "alien": ("alien", "surreal"),
    "readable": ("readable", "clean", "gameplay"),
}

# Which visual_style.style_class values are acceptable for each environment class.
CLASS_STYLE_COMPAT = {
    "photoreal": {"photoreal"},
    "raytraced": {"photoreal", "cinematic"},
    "cinematic": {"cinematic", "photoreal"},
    "stylized": {"stylized"},
    "low_visibility": {"low_visibility", "photoreal", "stylized"},
    "performance": {"performance"},
    "readable": {"readable"},
    "alien": {"alien"},
}


class ProfileError(Exception):
    """Raised when a profile / binding is missing or unparseable."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _root(profiles_root=None):
    return Path(profiles_root) if profiles_root else DEFAULT_PROFILES_ROOT


def profile_path(kind, name, profiles_root=None):
    """Path to a profile yaml (may or may not exist)."""
    return _root(profiles_root) / kind / (str(name) + ".yaml")


def load_profile(kind, name, profiles_root=None):
    """Load one profile dict. Raise ProfileError if missing/unparseable/empty."""
    if kind not in PROFILE_KINDS:
        raise ProfileError("unknown profile kind: {!r}".format(kind))
    if not name:
        raise ProfileError("empty profile name for kind {!r}".format(kind))
    path = profile_path(kind, name, profiles_root)
    if not path.is_file():
        raise ProfileError("{} profile not found: {} ({})".format(kind, name, path))
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001
        raise ProfileError("{} profile unparseable: {} ({})".format(kind, name, exc))
    if not isinstance(data, dict) or not data:
        raise ProfileError("{} profile empty/not-a-mapping: {}".format(kind, name))
    return data


def list_profiles(kind, profiles_root=None):
    """Return sorted profile names present for a kind (empty if the dir is absent)."""
    if kind not in PROFILE_KINDS:
        raise ProfileError("unknown profile kind: {!r}".format(kind))
    d = _root(profiles_root) / kind
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


def resolve_environment(env_name, profiles_root=None):
    """Load an environment and every child profile it references.

    Returns ``{'environment': <dict>, 'children': {kind: <dict>}}``.
    Raises ProfileError if the environment or any referenced child is missing.
    """
    env = load_profile("environment", env_name, profiles_root)
    children = {}
    for kind in CHILD_KINDS:
        ref = env.get(kind)
        if ref is None:
            raise ProfileError(
                "environment {!r} missing child reference {!r}".format(env_name, kind))
        children[kind] = load_profile(kind, ref, profiles_root)
    return {"environment": env, "children": children}


# ---------------------------------------------------------------------------
# Bindings
# ---------------------------------------------------------------------------
def bindings_path_for(world_pack_id, profiles_root=None):
    return _root(profiles_root) / "bindings" / (str(world_pack_id) + ".yaml")


def load_bindings(world_pack_id, profiles_root=None, bindings_path=None):
    """Load the binding overlay for a world pack. Raise ProfileError if absent."""
    path = Path(bindings_path) if bindings_path else bindings_path_for(
        world_pack_id, profiles_root)
    if not path.is_file():
        raise ProfileError("binding overlay not found for {}: {}".format(
            world_pack_id, path))
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001
        raise ProfileError("binding overlay unparseable: {} ({})".format(path, exc))
    if not isinstance(data, dict) or not data:
        raise ProfileError("binding overlay empty/not-a-mapping: {}".format(path))
    data.setdefault("bindings", {})
    if not isinstance(data["bindings"], dict):
        raise ProfileError("binding overlay 'bindings' must be a mapping: {}".format(path))
    return data


def environment_for(world_pack_id, slice_id, profiles_root=None, bindings_path=None,
                    bindings=None):
    """Return ``(env_name, source)`` for a slice.

    ``source`` is 'explicit' if the slice is listed in ``bindings:``, else
    'default' (the declared default_environment_profile), else (None, 'missing')
    when neither an explicit binding nor a declared default exists.
    """
    if bindings is None:
        bindings = load_bindings(world_pack_id, profiles_root, bindings_path)
    explicit = bindings.get("bindings", {}).get(slice_id)
    if explicit:
        return explicit, "explicit"
    default = bindings.get("default_environment_profile")
    if default:
        return default, "default"
    return None, "missing"


# ---------------------------------------------------------------------------
# Materiality
# ---------------------------------------------------------------------------
def material_fields(profile):
    """Return the comparable (non-metadata) field mapping of a profile."""
    return {k: _hashable(v) for k, v in profile.items() if k not in _META_FIELDS}


def _hashable(v):
    if isinstance(v, list):
        return tuple(_hashable(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _hashable(x)) for k, x in v.items()))
    return v


def material_diff_count(a, b):
    """Count how many comparable fields differ between two profiles.

    Compared over the union of keys, so a field present in only one profile
    counts as a difference.
    """
    fa, fb = material_fields(a), material_fields(b)
    keys = set(fa) | set(fb)
    return sum(1 for k in keys if fa.get(k) != fb.get(k))


# ---------------------------------------------------------------------------
# Class / name consistency
# ---------------------------------------------------------------------------
def name_matches_class(env_name, env_class):
    """True if the environment name carries a token consistent with its class."""
    tokens = CLASS_NAME_TOKENS.get(env_class)
    if not tokens:
        return False  # unknown class is itself a violation
    low = str(env_name).lower()
    return any(tok in low for tok in tokens)


def style_class_compatible(env_class, style_class):
    """True if a visual_style.style_class is acceptable for an environment class."""
    allowed = CLASS_STYLE_COMPAT.get(env_class)
    if allowed is None:
        return False
    return style_class in allowed


# ---------------------------------------------------------------------------
# Compatibility matrix
# ---------------------------------------------------------------------------
def compat_matrix():
    """Return the machine-readable compatibility matrix (thresholds + rules).

    Exposed so downstream validators (Agents 3/6) and docs can reference the
    exact numbers rather than re-deriving them.
    """
    return {
        "exposure_tolerance_ev": EXPOSURE_TOLERANCE_EV,
        "low_visibility_fog_min": LOW_VISIBILITY_FOG_MIN,
        "rules": [
            "rendering.ray_tracing=='required' requires ray_tracing.mode!='off'",
            "time_of_day.phase in {night,dusk} requires "
            "abs(post_process.exposure_ev - time_of_day.target_exposure_ev) "
            "<= exposure_tolerance_ev",
            "environment.low_visibility True requires fog.density "
            ">= low_visibility_fog_min",
            "environment.class=='performance' forbids rendering.rendering_mode=='cinematic'",
            "visual_style.style_class must be in CLASS_STYLE_COMPAT[environment.class]",
        ],
        "class_name_tokens": {k: list(v) for k, v in CLASS_NAME_TOKENS.items()},
        "class_style_compat": {k: sorted(v) for k, v in CLASS_STYLE_COMPAT.items()},
    }


def incompatible(env_resolved):
    """Return a list of human-readable incompatibility reasons (empty == OK).

    ``env_resolved`` is the dict returned by ``resolve_environment``.
    """
    env = env_resolved["environment"]
    ch = env_resolved["children"]
    reasons = []

    rendering = ch["rendering"]
    ray_tracing = ch["ray_tracing"]
    post = ch["post_process"]
    tod = ch["time_of_day"]
    fog = ch["fog"]
    style = ch["visual_style"]

    # 1. ray tracing required but disabled.
    if rendering.get("ray_tracing") == "required" and ray_tracing.get("mode") == "off":
        reasons.append(
            "rendering.ray_tracing=required but ray_tracing.mode=off")

    # 2. night/dusk time-of-day with daytime exposure.
    phase = tod.get("phase")
    if phase in ("night", "dusk"):
        try:
            drift = abs(float(post.get("exposure_ev")) - float(tod.get("target_exposure_ev")))
        except (TypeError, ValueError):
            drift = None
        if drift is None:
            reasons.append(
                "post_process.exposure_ev / time_of_day.target_exposure_ev non-numeric")
        elif drift > EXPOSURE_TOLERANCE_EV:
            reasons.append(
                "time_of_day.phase={} but post_process.exposure_ev={} drifts {:.2f}EV "
                "from target_exposure_ev={} (> {}EV)".format(
                    phase, post.get("exposure_ev"), drift,
                    tod.get("target_exposure_ev"), EXPOSURE_TOLERANCE_EV))

    # 3. low_visibility environment must actually be low-visibility (thick fog).
    if env.get("low_visibility") is True:
        try:
            density = float(fog.get("density"))
        except (TypeError, ValueError):
            density = None
        if density is None:
            reasons.append("low_visibility environment but fog.density non-numeric")
        elif density < LOW_VISIBILITY_FOG_MIN:
            reasons.append(
                "low_visibility environment but fog.density={} < {}".format(
                    density, LOW_VISIBILITY_FOG_MIN))

    # 4. performance environment must not use cinematic rendering.
    if env.get("class") == "performance" and rendering.get("rendering_mode") == "cinematic":
        reasons.append("performance environment uses cinematic rendering_mode")

    # 5. visual style class must be compatible with environment class.
    if not style_class_compatible(env.get("class"), style.get("style_class")):
        reasons.append(
            "visual_style.style_class={} incompatible with environment.class={}".format(
                style.get("style_class"), env.get("class")))

    return reasons


if __name__ == "__main__":
    # Self-check: resolve every environment and report compat status.
    for env_name in list_profiles("environment"):
        try:
            res = resolve_environment(env_name)
            bad = incompatible(res)
            status = "OK" if not bad else "INCOMPAT: " + "; ".join(bad)
            print("{:34s} {}".format(env_name, status))
        except ProfileError as exc:
            print("{:34s} ERROR: {}".format(env_name, exc))
