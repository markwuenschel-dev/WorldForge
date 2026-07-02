#!/usr/bin/env python3
"""biomes.py — WorldForge v1.1 BiomeForge biome-family data contract loader.

Single source of truth for reading the ``biome_family`` contract under
``procedural/definitions/biomes/`` and the cross-axis compatibility matrix under
``procedural/definitions/biomes/compatibility_matrix.yaml``.

This is the substrate every v1.1 lane imports so "biome" cannot decay into a
loose label. The public API below is STABLE — Agents 2/3/4/5/6/7 import:

    from biomes import (
        BIOME_REQUIRED_FIELDS, BIOME_LIST_FIELDS, AXES,
        BiomeError,
        load_biome, list_biomes, biome_path,
        validate_biome_fields,
        load_compat_matrix, allowed_values, compatible,
        combination_allowed, forbidden_combinations,
        referenced_profile_names,
    )

Design notes (mirrors profiles.py conventions)
----------------------------------------------
* Every loader accepts an optional ``biomes_root`` so validators / negative
  fixtures can inject a broken tree without disturbing the real data.
* Missing / unparseable inputs raise ``BiomeError`` — callers decide whether
  that is blocking (it always is, in strict mode).
* NO implicit fallbacks and NO implicit defaults: a biome that omits a required
  field is a contract violation, not a field that silently defaults.
* The biome_family file is the AUTHORITATIVE allow-list for each axis (the names
  of terrain forms, material families, environment profiles, POI classes, etc.
  a biome permits). The compatibility_matrix.yaml adds only the cross-cutting
  rules that are NOT expressible as a single-axis allow-list (e.g. global
  forbidden pairs like performance_safe + raytraced_high).
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    raise

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BIOMES_ROOT = REPO_ROOT / "procedural" / "definitions" / "biomes"
COMPAT_MATRIX_FILENAME = "compatibility_matrix.yaml"

# ---------------------------------------------------------------------------
# The biome_family contract. Scalar metadata + the axis allow-lists + the rule
# blocks. A biome_family YAML missing ANY of these is BIOME_CONTRACT_FAILURE.
# ``name``/``kind`` are handled specially (id must equal file stem).
# ---------------------------------------------------------------------------

# Scalar / metadata fields every biome must carry.
BIOME_SCALAR_FIELDS = ("id", "display_name", "description")

# Axis allow-list fields — each MUST be a non-empty list of names. These are the
# ten compatibility axes the matrix validator ranges over (brief §"Biome
# Compatibility Matrix"): biome × {terrain_form, material_family,
# vegetation_profile, placement_profile, environment_profile,
# visual_style_profile, poi_class, entity_anchor_type, rendering_profile,
# scalability_profile, raytracing_profile}.
BIOME_LIST_FIELDS = (
    "terrain_forms",
    "material_families",
    "vegetation_profiles",
    "placement_profiles",
    "environment_profiles",
    "visual_style_profiles",
    "sky_profiles",
    "lighting_profiles",
    "fog_profiles",
    "atmosphere_profiles",
    "weather_profiles",
    "rendering_profiles",
    "scalability_profiles",
    "raytracing_profiles",
    "poi_compatibility",
    "ecology_tags",
    "entity_anchor_types",
)

# Rule / mapping blocks — each MUST be a non-empty mapping.
BIOME_RULE_FIELDS = (
    "level_design_rules",
    "traversal_rules",
    "entity_anchor_rules",
    "budget_caps",
    "package_rules",
    "ownership_rules",
    "negative_fixture_rules",
)

BIOME_REQUIRED_FIELDS = BIOME_SCALAR_FIELDS + BIOME_LIST_FIELDS + BIOME_RULE_FIELDS

# The compatibility axes and the biome_family field each derives its allow-list
# from. Keyed by the matrix axis name. Used by the matrix validator to range
# over "biome × axis" cleanly and by combination_allowed() to map a map binding
# key -> axis.
AXES = {
    "terrain_form": "terrain_forms",
    "material_family": "material_families",
    "vegetation_profile": "vegetation_profiles",
    "placement_profile": "placement_profiles",
    "environment_profile": "environment_profiles",
    "visual_style_profile": "visual_style_profiles",
    "sky_profile": "sky_profiles",
    "lighting_profile": "lighting_profiles",
    "fog_profile": "fog_profiles",
    "atmosphere_profile": "atmosphere_profiles",
    "weather_profile": "weather_profiles",
    "rendering_profile": "rendering_profiles",
    "scalability_profile": "scalability_profiles",
    "raytracing_profile": "raytracing_profiles",
    "poi_class": "poi_compatibility",
    "entity_anchor_type": "entity_anchor_types",
}

# The subset of AXES that name a profiles.py profile kind, so cross-validators
# (Agent 1/3) can confirm every name a biome allows actually resolves to a real
# profile file. Maps matrix axis -> profiles.py CHILD_KIND / kind dir.
PROFILE_AXES = {
    "environment_profile": "environment",
    "visual_style_profile": "visual_style",
    "sky_profile": "sky",
    "lighting_profile": "lighting",
    "fog_profile": "fog",
    "atmosphere_profile": "atmosphere",
    "weather_profile": "weather",
    "rendering_profile": "rendering",
    "scalability_profile": "scalability",
    "raytracing_profile": "ray_tracing",
}


class BiomeError(Exception):
    """Raised when a biome family / compatibility matrix is missing or invalid."""


def _root(biomes_root=None):
    return Path(biomes_root) if biomes_root else DEFAULT_BIOMES_ROOT


def biome_path(biome_id, biomes_root=None):
    """Path to a biome_family yaml (may or may not exist)."""
    return _root(biomes_root) / (str(biome_id) + ".yaml")


def load_biome(biome_id, biomes_root=None):
    """Load one biome_family dict. Raise BiomeError if missing/unparseable/empty."""
    if not biome_id:
        raise BiomeError("empty biome id")
    path = biome_path(biome_id, biomes_root)
    if not path.is_file():
        raise BiomeError("biome family not found: {} ({})".format(biome_id, path))
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001
        raise BiomeError("biome family unparseable: {} ({})".format(biome_id, exc))
    if not isinstance(data, dict) or not data:
        raise BiomeError("biome family empty/not-a-mapping: {}".format(biome_id))
    return data


def list_biomes(biomes_root=None):
    """Return sorted biome ids present (empty if the dir is absent).

    The compatibility matrix file lives in the same dir but is not a biome.
    """
    d = _root(biomes_root)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.yaml") if p.name != COMPAT_MATRIX_FILENAME)


# ---------------------------------------------------------------------------
# Contract validation (used by validate_biome_contract.py)
# ---------------------------------------------------------------------------
def validate_biome_fields(biome_id, biome, biomes_root=None):
    """Return a list of (code, detail) contract violations for one biome dict.

    Empty list == the biome satisfies the structural contract. This checks
    STRUCTURE only (required fields present, right shapes, id==stem, no unknown
    top-level fields). Cross-references (do the referenced profiles exist?) and
    materiality live in the dedicated validators so ownership stays clean.
    """
    from failure_codes import FailureCode
    problems = []
    C = FailureCode.BIOME_CONTRACT_FAILURE

    if not isinstance(biome, dict):
        return [(C, "biome {} is not a mapping".format(biome_id))]

    # id must equal the file stem (no drift between filename and declared id).
    declared = biome.get("id")
    if declared != biome_id:
        problems.append((C, "biome id {!r} != filename stem {!r}".format(declared, biome_id)))

    # Unknown top-level fields fail (strict: no silent extension).
    allowed = set(BIOME_REQUIRED_FIELDS) | {"kind"}
    for key in biome:
        if key not in allowed:
            problems.append((FailureCode.UNKNOWN_SCHEMA_FIELD,
                             "biome {} has unknown field {!r}".format(biome_id, key)))

    # Scalars present & non-empty strings.
    for f in BIOME_SCALAR_FIELDS:
        v = biome.get(f)
        if not isinstance(v, str) or not v.strip():
            problems.append((C, "biome {} field {!r} must be a non-empty string".format(biome_id, f)))

    # List axes present & non-empty lists of non-empty strings, no dupes.
    for f in BIOME_LIST_FIELDS:
        v = biome.get(f)
        if not isinstance(v, list) or not v:
            problems.append((C, "biome {} field {!r} must be a non-empty list".format(biome_id, f)))
            continue
        if any((not isinstance(x, str) or not x.strip()) for x in v):
            problems.append((C, "biome {} field {!r} has a non-string/empty entry".format(biome_id, f)))
        if len(set(v)) != len(v):
            problems.append((C, "biome {} field {!r} has duplicate entries".format(biome_id, f)))

    # Rule blocks present & non-empty mappings.
    for f in BIOME_RULE_FIELDS:
        v = biome.get(f)
        if not isinstance(v, dict) or not v:
            problems.append((C, "biome {} field {!r} must be a non-empty mapping".format(biome_id, f)))

    return problems


# ---------------------------------------------------------------------------
# Axis allow-lists / compatibility
# ---------------------------------------------------------------------------
def allowed_values(biome, axis):
    """Return the allow-list (list) a biome declares for a matrix axis.

    Raises BiomeError for an unknown axis. Returns [] if the biome omits the
    field (a contract violation caught upstream; here we surface "nothing is
    allowed" so compatible() correctly rejects).
    """
    if axis not in AXES:
        raise BiomeError("unknown compatibility axis: {!r}".format(axis))
    field = AXES[axis]
    v = biome.get(field)
    return list(v) if isinstance(v, list) else []


def compatible(biome, axis, value):
    """True iff ``value`` is in the biome's declared allow-list for ``axis``.

    Implicit compatibility is NOT allowed: a value the biome does not list is
    incompatible, full stop.
    """
    return value in allowed_values(biome, axis)


# ---------------------------------------------------------------------------
# Compatibility matrix (cross-cutting rules that a single allow-list can't hold)
# ---------------------------------------------------------------------------
def compat_matrix_path(biomes_root=None):
    return _root(biomes_root) / COMPAT_MATRIX_FILENAME


def load_compat_matrix(biomes_root=None):
    """Load the compatibility matrix. Raise BiomeError if missing/unparseable.

    Shape:
        version: <int>
        # Cross-cutting pairs that are forbidden regardless of biome. Each entry
        # names two axis:value bindings that must never co-occur on one map.
        forbidden_combinations:
          - { a: {axis: environment_profile, value: performance_safe},
              b: {axis: raytracing_profile,  value: full},
              reason: "performance_safe cannot pair with full ray tracing" }
        # Optional: axis pairs that REQUIRE a co-declared rule to be legal
        # (e.g. fog_heavy environment requires low_visibility declaration). These
        # are validated by the environment-compat lane; recorded here for rollup.
        requires_declaration:
          - { when: {axis: environment_profile, value: fog_heavy},
              requires: low_visibility, reason: "..." }
    """
    path = compat_matrix_path(biomes_root)
    if not path.is_file():
        raise BiomeError("compatibility matrix not found: {}".format(path))
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001
        raise BiomeError("compatibility matrix unparseable: {}".format(exc))
    if not isinstance(data, dict) or not data:
        raise BiomeError("compatibility matrix empty/not-a-mapping")
    data.setdefault("forbidden_combinations", [])
    data.setdefault("requires_declaration", [])
    if not isinstance(data["forbidden_combinations"], list):
        raise BiomeError("compatibility matrix 'forbidden_combinations' must be a list")
    return data


def forbidden_combinations(matrix=None, biomes_root=None):
    """Return the list of forbidden cross-axis pairs from the matrix."""
    if matrix is None:
        matrix = load_compat_matrix(biomes_root)
    return matrix.get("forbidden_combinations", [])


def combination_allowed(bindings, matrix=None, biomes_root=None):
    """Check a map's axis bindings against the global forbidden pairs.

    ``bindings`` is a mapping of axis-name -> value (e.g. from a generated map's
    binding record). Returns a list of human-readable violation reasons (empty
    == allowed). Biome-membership (is this value in the biome's allow-list?) is
    checked separately via compatible(); this catches only the cross-cutting
    pairs the matrix forbids.
    """
    if matrix is None:
        matrix = load_compat_matrix(biomes_root)
    reasons = []
    for entry in matrix.get("forbidden_combinations", []):
        a, b = entry.get("a", {}), entry.get("b", {})
        av, bv = a.get("axis"), b.get("axis")
        if av in bindings and bv in bindings and \
                bindings.get(av) == a.get("value") and bindings.get(bv) == b.get("value"):
            reasons.append(entry.get("reason") or
                           "forbidden: {}={} + {}={}".format(av, a.get("value"),
                                                             bv, b.get("value")))
    return reasons


def referenced_profile_names(biome):
    """Return {profiles.py-kind: [names]} for every profile-backed axis a biome
    declares, so a cross-validator can confirm each resolves to a real profile.
    """
    out = {}
    for axis, kind in PROFILE_AXES.items():
        out.setdefault(kind, [])
        out[kind].extend(allowed_values(biome, axis))
    return out


if __name__ == "__main__":
    # Self-check: load every biome and report structural contract status.
    ids = list_biomes()
    if not ids:
        print("no biome families found under", DEFAULT_BIOMES_ROOT)
    for bid in ids:
        try:
            b = load_biome(bid)
            probs = validate_biome_fields(bid, b)
            status = "OK" if not probs else "CONTRACT: {} problem(s)".format(len(probs))
            print("{:26s} {}".format(bid, status))
            for code, detail in probs[:6]:
                print("    - {} {}".format(code, detail))
        except BiomeError as exc:
            print("{:26s} ERROR: {}".format(bid, exc))
    try:
        m = load_compat_matrix()
        print("compat matrix: {} forbidden pair(s)".format(len(m.get("forbidden_combinations", []))))
    except BiomeError as exc:
        print("compat matrix ERROR:", exc)
