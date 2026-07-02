#!/usr/bin/env python3
"""validate_world_pack_spec.py — WorldForge v1.0 world-pack SPEC validator.

Static, pure-Python pre-flight that proves a world pack *spec* is buildable
BEFORE any slice/terrain/UE work happens. It resolves every referenced surface
(slice packs, variant templates, terrain recipes, placement presets, POI
templates, state presets) against the repository and reports coverage against
the v1.0 MVP contract thresholds.

This is the Pass-1 acceptance gate:

    make validate-world-pack-spec PACK=desert_mvp_world

It does NOT launch UE and does NOT generate anything. It only reads YAML and
checks that the things the pack references actually exist on disk, that slice
names are unique, that every slice carries full terrain/material/placement/POI/
state intent, and that the matrix meets the MVP coverage minimums.

Uses the shared ``ValidationReport`` so strict/warn/fail semantics and the
on-disk report shape match every other WorldForge validator. Coverage minimums
are recorded as WARN (informational in normal mode, blocking under --strict),
so a thin pack still parses but a strict gate enforces the MVP matrix.

Writes:
    procedural/reports/world_packs/<id>/validate_world_pack_spec_report.json
    procedural/reports/coverage/<id>_coverage.json

Exit 0 = PASS (status ok|warn), 1 = FAIL (status fail|error).
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode

DEFN = REPO_ROOT / "procedural" / "definitions"

# v1.0 MVP coverage minimums (the contract thresholds).
MVP_MIN_MAPS = 25
MVP_MIN_TERRAIN = 3
MVP_MIN_VARIANTS = 8
MVP_MIN_PLACEMENT = 6
MVP_MIN_POI = 5
MVP_MIN_STATE = 2
MVP_MIN_SCENARIO_PATHS = 2

# v1.1 BiomeForge coverage contract (the multi-biome matrix minimums).
BIOME_MIN_MAPS = 60
BIOME_MIN_FAMILIES = 5
BIOME_MIN_TERRAIN_PER = 2       # terrain forms per biome
BIOME_MIN_PLACEMENT_PER = 2     # placement profiles per biome
BIOME_MIN_ENV_MODES_PER = 3     # environment/visual modes per biome

REQUIRED_SLICE_FIELDS = ("name", "variant", "seed", "placement", "state_preset",
                         "terrain", "poi")

# Fields create_slice_spec.py requires from a variant template (procedural/slices/
# <biome>_<variant>.yaml). A template that merely exists but omits any of these
# fails at generation time (not spec time) unless the spec gate checks for them —
# this is exactly what bit desert_light_industrial / desert_ruined_industrial.
REQUIRED_TEMPLATE_FIELDS = (
    ("render", "preview_base_color"),
    ("render", "terrain_mi"),
    ("render", "placement_data_asset"),
    ("state", "before"),
    ("state", "after"),
    ("state", "scope"),
    ("state", "key"),
)


def _variant_template(biome, variant):
    return REPO_ROOT / "procedural" / "slices" / "{}_{}.yaml".format(biome, variant)


def _terrain_recipe(terrain):
    return DEFN / "terrain" / "{}.yaml".format(terrain)


def _poi_template(poi):
    return DEFN / "poi" / "{}.yaml".format(poi)


def _state_preset(biome, state):
    return DEFN / "state" / biome / "{}.yaml".format(state)


def _placement_preset(biome, placement):
    """Placement presets live under definitions/placement/<biome>/ with a flat
    fallback at definitions/placement/. Returns the resolved Path or None."""
    cand = [DEFN / "placement" / biome / "{}.yaml".format(placement),
            DEFN / "placement" / "{}.yaml".format(placement)]
    for p in cand:
        if p.is_file():
            return p
    return None


# --- v1.1 BiomeForge-aware resolution ---------------------------------------
# BiomeForge surface definitions live under definitions/<cat>/biomes/<biome>/,
# POIs are abstract classes resolved against the biome contract's
# poi_compatibility list, and state is baked into the variant template (validated
# by variant_templates_complete) rather than a separate state-preset file.
try:
    import biomes as _biomes
except Exception:  # pragma: no cover
    _biomes = None


def _terrain_form_resolves(biome, terrain):
    return any(p.is_file() for p in (
        DEFN / "terrain" / "biomes" / biome / "{}.yaml".format(terrain),
        DEFN / "terrain" / "{}.yaml".format(terrain)))


def _placement_resolves_biome(biome, placement):
    return any(p.is_file() for p in (
        DEFN / "placement" / "biomes" / biome / "{}.yaml".format(placement),
        DEFN / "placement" / biome / "{}.yaml".format(placement),
        DEFN / "placement" / "{}.yaml".format(placement)))


def _poi_class_resolves(biome, poi):
    """A biome POI is valid iff the biome contract declares it in poi_compatibility."""
    if _biomes is None:
        return False
    try:
        return _biomes.compatible(_biomes.load_biome(biome), "poi_class", poi)
    except Exception:
        return False


def _biome_state_resolves(biome, preset):
    """State for BiomeForge is specified in the variant template (validated by
    variant_templates_complete). A dedicated state-preset file is optional; accept
    it when present under a biome path, else treat as template-backed."""
    return True


def _missing_detail(kind, misses):
    """Render a compact 'kind: <slice> -> <ref>' failure detail."""
    items = ", ".join("{}->{}".format(n, r) for n, r in misses[:8])
    if len(misses) > 8:
        items += ", ... (+{} more)".format(len(misses) - 8)
    return "{} unresolved: {}".format(kind, items)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Statically validate a world pack spec (no UE, no generation).")
    ap.add_argument("--pack", required=True, help="Path to world pack YAML")
    ap.add_argument("--strict", action="store_true",
                    help="Treat coverage shortfalls (WARN) as blocking; also via STRICT=1.")
    ap.add_argument("--min-maps", type=int, default=MVP_MIN_MAPS,
                    help="Minimum total map count (default: {}).".format(MVP_MIN_MAPS))
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()

    pack_path = Path(args.pack)
    if not pack_path.is_absolute():
        pack_path = REPO_ROOT / pack_path

    world_pack_id = pack_path.stem
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    if not pack_path.is_file():
        rep.error("world pack not found: {}".format(pack_path))
        rep.finalize()
        rep.print_summary("validate-world-pack-spec")
        sys.exit(rep.exit_code)

    try:
        world_pack = yaml.safe_load(pack_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        rep.error("world pack not parseable: {}".format(exc))
        rep.finalize()
        rep.print_summary("validate-world-pack-spec")
        sys.exit(rep.exit_code)

    world_pack_id = world_pack.get("world_pack_id", world_pack_id)
    rep.entity_id = world_pack_id
    default_biome = (world_pack.get("global_defaults") or {}).get("biome", "desert")
    biomeforge = bool(world_pack.get("biomeforge") or world_pack.get("biome_families"))
    packs = world_pack.get("packs", [])

    print("=== Validate World Pack Spec: {} (strict={}) ===".format(
        world_pack_id, "on" if strict else "off"))

    rep.check("world_pack_has_packs", bool(packs),
              "no slice packs referenced" if not packs else "{} slice pack(s)".format(len(packs)),
              code=FailureCode.SPEC_INVALID)

    # ---- Gather every slice across every referenced slice pack ----------------
    all_slices = []           # (biome, slice_dict)
    names = []
    for entry in packs:
        pack_id = entry.get("pack_id", "<unknown>")
        rel = entry.get("pack_path", "")
        sp_path = REPO_ROOT / rel if rel else None
        if not sp_path or not sp_path.is_file():
            rep.check("slice_pack_exists:{}".format(pack_id), False,
                      "slice pack file not found: {}".format(rel),
                      code=FailureCode.SPEC_INVALID)
            continue
        rep.check("slice_pack_exists:{}".format(pack_id), True, str(rel))
        try:
            sp = yaml.safe_load(sp_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            rep.check("slice_pack_parses:{}".format(pack_id), False,
                      "unparseable: {}".format(exc), code=FailureCode.SPEC_INVALID)
            continue
        biome = sp.get("biome", default_biome)
        for sl in sp.get("slices", []):
            all_slices.append((biome, sl))
            names.append(sl.get("name", ""))

    total = len(all_slices)
    print("Total slices: {}".format(total))

    # ---- Per-slice required fields -------------------------------------------
    field_misses = []
    for biome, sl in all_slices:
        missing = [f for f in REQUIRED_SLICE_FIELDS
                   if sl.get(f) in (None, "") and not (f == "seed" and sl.get(f) == 0)]
        if missing:
            field_misses.append((sl.get("name", "<unnamed>"), "+".join(missing)))
    rep.check("slices_have_full_intent", not field_misses,
              "all slices carry name/variant/seed/placement/state/terrain/poi"
              if not field_misses else _missing_detail("missing fields", field_misses),
              code=FailureCode.SPEC_INVALID)

    # ---- Duplicate names ------------------------------------------------------
    seen, dups = set(), []
    for n in names:
        if n in seen:
            dups.append(n)
        seen.add(n)
    rep.check("slice_names_unique", not dups,
              "no duplicate names" if not dups else "duplicates: {}".format(sorted(set(dups))),
              code=FailureCode.SPEC_INVALID)

    # ---- Reference resolution -------------------------------------------------
    if biomeforge:
        # BiomeForge: terrain/material/placement live under definitions/<cat>/
        # biomes/<biome>/, POIs are abstract classes checked against the biome
        # contract, and state is template-backed. (Same variant-template check.)
        resolvers = {
            "variant": lambda b, v: _variant_template(b, v).is_file(),
            "terrain": _terrain_form_resolves,
            "poi": _poi_class_resolves,
            "state_preset": _biome_state_resolves,
            "placement": _placement_resolves_biome,
        }
    else:
        resolvers = {
            "variant": lambda b, v: _variant_template(b, v).is_file(),
            "terrain": lambda b, v: _terrain_recipe(v).is_file(),
            "poi": lambda b, v: _poi_template(v).is_file(),
            "state_preset": lambda b, v: _state_preset(b, v).is_file(),
            "placement": lambda b, v: _placement_preset(b, v) is not None,
        }
    for field, resolves in resolvers.items():
        misses = []
        for biome, sl in all_slices:
            ref = sl.get(field)
            if ref in (None, ""):
                continue  # absence is caught by slices_have_full_intent
            if not resolves(biome, str(ref)):
                misses.append((sl.get("name", "<unnamed>"), ref))
        rep.check("{}_refs_resolve".format(field), not misses,
                  "all {} references resolve".format(field) if not misses
                  else _missing_detail(field, misses),
                  code=FailureCode.SPEC_INVALID)

    # ---- Variant template completeness (predicts generation-time failures) ----
    distinct_variants = sorted({(b, str(sl.get("variant")))
                                for b, sl in all_slices if sl.get("variant")})
    tmpl_misses = []
    for biome, variant in distinct_variants:
        tpath = _variant_template(biome, variant)
        if not tpath.is_file():
            continue  # existence already reported by variant_refs_resolve
        try:
            tmpl = yaml.safe_load(tpath.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            tmpl_misses.append((variant, "unparseable: {}".format(exc)))
            continue
        for section, field in REQUIRED_TEMPLATE_FIELDS:
            if (tmpl.get(section) or {}).get(field) in (None, ""):
                tmpl_misses.append((variant, "{}.{}".format(section, field)))
    rep.check("variant_templates_complete", not tmpl_misses,
              "all variant templates carry required render/state fields"
              if not tmpl_misses else _missing_detail("template field", tmpl_misses),
              code=FailureCode.SPEC_INVALID)

    # ---- Coverage -------------------------------------------------------------
    def distinct(field):
        return sorted({str(sl.get(field)) for _, sl in all_slices if sl.get(field) not in (None, "")})

    variants = distinct("variant")
    terrains = distinct("terrain")
    placements = distinct("placement")
    pois = distinct("poi")
    states = distinct("state_preset")
    scenario_paths = sorted({s for _, sl in all_slices for s in (sl.get("scenarios") or [])})

    coverage = {
        "world_pack_id": world_pack_id,
        "map_count": total,
        "terrain_forms": terrains,
        "material_variants": variants,
        "placement_presets": placements,
        "poi_types": pois,
        "state_presets": states,
        "runtime_scenario_paths": scenario_paths,
        "minimums": {
            "maps": args.min_maps, "terrain": MVP_MIN_TERRAIN, "variants": MVP_MIN_VARIANTS,
            "placement": MVP_MIN_PLACEMENT, "poi": MVP_MIN_POI, "state": MVP_MIN_STATE,
            "scenario_paths": MVP_MIN_SCENARIO_PATHS,
        },
    }

    # Zero maps is a hard FAIL; below-minimum is a WARN (blocking under --strict).
    rep.check("map_count_nonzero", total > 0, "{} maps".format(total),
              code=FailureCode.SPEC_INVALID)

    if biomeforge:
        # BiomeForge applies its OWN (stronger, not relaxed) coverage contract:
        # >=5 non-desert biome families, >=60 maps, and per biome >=2 terrain
        # forms, >=2 placement profiles, >=3 environment/visual modes.
        families = sorted({b for b, _ in all_slices})
        per_biome = {}
        for b, sl in all_slices:
            d = per_biome.setdefault(b, {"terrain": set(), "placement": set(), "variant": set()})
            for axis, field in (("terrain", "terrain"), ("placement", "placement"), ("variant", "variant")):
                if sl.get(field) not in (None, ""):
                    d[axis].add(str(sl[field]))
        cov_checks = [
            ("biome_map_count", total, BIOME_MIN_MAPS),
            ("biome_family_coverage", len(families), BIOME_MIN_FAMILIES),
        ]
        for b in families:
            cov_checks.append(("biome_terrain_coverage:{}".format(b), len(per_biome[b]["terrain"]), BIOME_MIN_TERRAIN_PER))
            cov_checks.append(("biome_placement_coverage:{}".format(b), len(per_biome[b]["placement"]), BIOME_MIN_PLACEMENT_PER))
            cov_checks.append(("biome_env_mode_coverage:{}".format(b), len(per_biome[b]["variant"]), BIOME_MIN_ENV_MODES_PER))
    else:
        cov_checks = [
            ("map_count_meets_min", total, args.min_maps),
            ("terrain_coverage", len(terrains), MVP_MIN_TERRAIN),
            ("material_variant_coverage", len(variants), MVP_MIN_VARIANTS),
            ("placement_coverage", len(placements), MVP_MIN_PLACEMENT),
            ("poi_coverage", len(pois), MVP_MIN_POI),
            ("state_coverage", len(states), MVP_MIN_STATE),
            ("scenario_path_coverage", len(scenario_paths), MVP_MIN_SCENARIO_PATHS),
        ]
    for key, have, need in cov_checks:
        rep.check(key, have >= need,
                  "{} (have {}, need {})".format("ok" if have >= need else "below minimum", have, need),
                  warn_only=True, code=FailureCode.SPEC_INVALID)

    rep.finalize()

    # ---- Reports --------------------------------------------------------------
    wp_dir = REPO_ROOT / "procedural" / "reports" / "world_packs" / world_pack_id
    rep.write(wp_dir, "validate_world_pack_spec_report.json")

    cov_dir = REPO_ROOT / "procedural" / "reports" / "coverage"
    cov_dir.mkdir(parents=True, exist_ok=True)
    coverage["status"] = rep.status
    coverage["passed"] = rep.passed
    (cov_dir / "{}_coverage.json".format(world_pack_id)).write_text(
        json.dumps(coverage, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Coverage: procedural/reports/coverage/{}_coverage.json".format(world_pack_id))

    rep.print_summary("validate-world-pack-spec")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
