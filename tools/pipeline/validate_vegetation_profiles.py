#!/usr/bin/env python3
"""validate_vegetation_profiles.py — WorldForge v1.1 BiomeForge vegetation gate.

Proves that EVERY vegetation profile named by EVERY non-desert biome in a
BiomeForge world pack has a real, in-budget definition: the file exists under
``procedural/definitions/vegetation/biomes/<biome>/<profile>.yaml``, its
profile_id and biome match, the profile is compatible with the biome, it declares
a density, and that density respects the biome's ``budget_caps.vegetation_density``
(and ``vegetation_density_performance_safe`` where the biome declares one). A
``none_*`` profile must declare exactly zero density; any other profile must place
real vegetation (density > 0) so a biome that requires vegetation never ships an
accidentally-empty profile.

Follows the v1.0x shared build contract: importable ``validate_pack``, one
ValidationReport per pack, one check per (biome, profile) pair, meta attached,
record_count == number of (biome, profile) pairs, canonical report path.

Core is importable:
    validate_pack(pack, strict, defs_root=None, biomes_root=None) -> ValidationReport
The negative harness injects a broken definition tree through ``defs_root``.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    raise

from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta, hash_obj
from world_pack_maps import resolve_world_pack_path, report_dir_for
import biomes as B

AXIS = "vegetation_profile"
CODE = FailureCode.VEGETATION_PROFILE_FAILURE

NONE_PREFIX = "none_"


def _default_defs_root():
    return REPO_ROOT / "procedural" / "definitions"


def _load_yaml(path):
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _rel(path):
    """Repo-relative string when possible; otherwise the raw path (fixtures)."""
    try:
        return str(Path(path).relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _pack_biomes(pack, biomes_root):
    wp_path = resolve_world_pack_path(pack)
    wp = _load_yaml(wp_path) or {}
    declared = wp.get("biome_families") or []
    present = set(B.list_biomes(biomes_root))
    return wp.get("world_pack_id", wp_path.stem), [b for b in declared if b in present]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _profile_reasons(biome_id, biome, profile, path):
    """Return a list of vegetation-profile violations (empty == valid & in budget)."""
    if not path.is_file():
        return ["definition file missing: {}".format(_rel(path))]
    try:
        data = _load_yaml(path)
    except Exception as exc:  # noqa: BLE001
        return ["definition unparseable: {}".format(exc)]
    if not isinstance(data, dict) or not data:
        return ["definition empty/not-a-mapping"]

    reasons = []
    if data.get("profile_id") != profile:
        reasons.append("profile_id {!r} != profile {!r}".format(data.get("profile_id"), profile))
    if data.get("biome") != biome_id:
        reasons.append("biome {!r} != {!r}".format(data.get("biome"), biome_id))
    if not B.compatible(biome, AXIS, profile):
        reasons.append("profile {!r} not in biome '{}' allow-list".format(profile, biome_id))

    caps = biome.get("budget_caps") or {}
    cap = _num(caps.get("vegetation_density"))
    perf_cap = _num(caps.get("vegetation_density_performance_safe"))
    is_none = profile.startswith(NONE_PREFIX)

    density = _num(data.get("density"))
    if density is None:
        reasons.append("missing required numeric 'density'")
    else:
        if not (0.0 <= density <= 1.0):
            reasons.append("density {} outside [0,1]".format(density))
        if is_none and density != 0.0:
            reasons.append("'{}' is a none_* profile but density={} (must be 0)".format(
                profile, density))
        if (not is_none) and density <= 0.0:
            reasons.append("'{}' places no vegetation (density={}) — biome requires real "
                           "vegetation for non-none profiles".format(profile, density))
        if cap is not None and density > cap + 1e-9:
            reasons.append("density {} exceeds biome vegetation_density cap {}".format(density, cap))

    # performance_safe budget: required for a real (non-none) profile whenever the
    # biome declares a performance-safe cap, and it must clamp under that cap.
    perf = data.get("density_performance_safe")
    if perf_cap is not None and not is_none:
        perf_val = _num(perf)
        if perf is None:
            reasons.append("biome declares a performance_safe veg cap but profile omits "
                           "'density_performance_safe'")
        elif perf_val is None or not (0.0 <= perf_val <= 1.0):
            reasons.append("density_performance_safe must be a float in [0,1], got {!r}".format(perf))
        else:
            if perf_val > perf_cap + 1e-9:
                reasons.append("density_performance_safe {} exceeds biome "
                               "vegetation_density_performance_safe cap {}".format(perf_val, perf_cap))
            if density is not None and perf_val > density + 1e-9:
                reasons.append("density_performance_safe {} > base density {} "
                               "(performance mode must not add vegetation)".format(perf_val, density))
    return reasons


def validate_pack(pack, strict, defs_root=None, biomes_root=None):
    """Importable core. Returns a ValidationReport (call .finalize()/.write())."""
    defs_root = Path(defs_root) if defs_root else _default_defs_root()
    world_pack_id, pack_biomes = _pack_biomes(pack, biomes_root)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    if not pack_biomes:
        rep.check("pack_declares_biomes", False,
                  "world pack declares no resolvable biome_families", code=CODE)

    record_count = 0
    manifest = []
    for biome_id in pack_biomes:
        try:
            biome = B.load_biome(biome_id, biomes_root)
        except B.BiomeError as exc:
            rep.check("biome::{}".format(biome_id), False, str(exc), code=CODE)
            continue
        for profile in B.allowed_values(biome, AXIS):
            record_count += 1
            path = defs_root / "vegetation" / "biomes" / biome_id / (profile + ".yaml")
            reasons = _profile_reasons(biome_id, biome, profile, path)
            tag = "vegetation_profile::{}::{}".format(biome_id, profile)
            rep.check(tag, not reasons,
                      "; ".join(reasons) if reasons else "vegetation profile valid & in budget",
                      code=CODE)
            manifest.append((biome_id, profile, not reasons))

    rep.set_meta(build_meta(
        command="validate-vegetation-profiles", pack=world_pack_id, strict=strict, status=None,
        record_count=record_count, input_spec_hash=hash_obj(sorted(manifest))))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate BiomeForge vegetation profiles for a world pack.")
    parser.add_argument("--pack", default="biome_expansion_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--defs-root", default=None)
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.defs_root)
    rep.finalize()
    rep.write(report_dir_for(rep.entity_id), "validate_vegetation_profiles_report.json")
    rep.print_summary("validate-vegetation-profiles")
    print("[validate-vegetation-profiles] records={} (biome x vegetation_profile pairs)".format(
        rep.to_dict()["meta"]["record_count"]))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
