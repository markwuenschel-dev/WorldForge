#!/usr/bin/env python3
"""validate_placement_profiles.py — WorldForge v1.1 BiomeForge placement gate.

Proves that EVERY placement profile named by EVERY non-desert biome in a
BiomeForge world pack has a real, well-formed definition: the file exists under
``procedural/definitions/placement/biomes/<biome>/<profile>.yaml``, its
placement_id and biome match, the profile is compatible with the biome, and it
declares at least one scatter category whose ``density_at_0`` / ``density_at_1``
endpoints are numeric and in [0,1] (a state-reactive density curve, mirroring the
desert placement profiles). This guarantees each biome's object scatter is
materially specified, not a bare name.

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

AXIS = "placement_profile"
CODE = FailureCode.PLACEMENT_PROFILE_FAILURE


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
    """Return a list of placement-profile violations (empty == well-formed)."""
    if not path.is_file():
        return ["definition file missing: {}".format(_rel(path))]
    try:
        data = _load_yaml(path)
    except Exception as exc:  # noqa: BLE001
        return ["definition unparseable: {}".format(exc)]
    if not isinstance(data, dict) or not data:
        return ["definition empty/not-a-mapping"]

    reasons = []
    if data.get("placement_id") != profile:
        reasons.append("placement_id {!r} != profile {!r}".format(data.get("placement_id"), profile))
    if data.get("biome") != biome_id:
        reasons.append("biome {!r} != {!r}".format(data.get("biome"), biome_id))
    if not B.compatible(biome, AXIS, profile):
        reasons.append("profile {!r} not in biome '{}' allow-list".format(profile, biome_id))
    if not data.get("description"):
        reasons.append("missing 'description'")

    cats = data.get("categories")
    if not isinstance(cats, dict) or not cats:
        reasons.append("missing/empty 'categories' mapping")
        return reasons
    for cat_name, cat in cats.items():
        if not isinstance(cat, dict):
            reasons.append("category '{}' is not a mapping".format(cat_name))
            continue
        for endpoint in ("density_at_0", "density_at_1"):
            val = _num(cat.get(endpoint))
            if val is None:
                reasons.append("category '{}' {} non-numeric".format(cat_name, endpoint))
            elif not (0.0 <= val <= 1.0):
                reasons.append("category '{}' {}={} outside [0,1]".format(cat_name, endpoint, val))
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
            path = defs_root / "placement" / "biomes" / biome_id / (profile + ".yaml")
            reasons = _profile_reasons(biome_id, biome, profile, path)
            tag = "placement_profile::{}::{}".format(biome_id, profile)
            rep.check(tag, not reasons,
                      "; ".join(reasons) if reasons else "placement profile well-formed",
                      code=CODE)
            manifest.append((biome_id, profile, not reasons))

    rep.set_meta(build_meta(
        command="validate-placement-profiles", pack=world_pack_id, strict=strict, status=None,
        record_count=record_count, input_spec_hash=hash_obj(sorted(manifest))))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate BiomeForge placement profiles for a world pack.")
    parser.add_argument("--pack", default="biome_expansion_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--defs-root", default=None)
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.defs_root)
    rep.finalize()
    rep.write(report_dir_for(rep.entity_id), "validate_placement_profiles_report.json")
    rep.print_summary("validate-placement-profiles")
    print("[validate-placement-profiles] records={} (biome x placement_profile pairs)".format(
        rep.to_dict()["meta"]["record_count"]))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
