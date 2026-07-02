#!/usr/bin/env python3
"""validate_biome_environment_compatibility.py — WorldForge v1.1 BiomeForge gate.

Proves that every PROFILE-BACKED axis name a biome family allows actually resolves
to a real profile file. For each declared biome, ``biomes.referenced_profile_names``
returns {profiles.py-kind: [names]} for every profile-backed axis (environment,
visual_style, sky, lighting, fog, atmosphere, weather, rendering, scalability,
ray_tracing). Each referenced name must be present in ``profiles.list_profiles(kind)``
and load via ``profiles.load_profile(kind, name)``. Any name that does not resolve is
reported as a missing referenced profile.

This is the gate that stays HONEST-RED until Agent 3 materializes the new-biome
profiles: the biome allow-lists name real, intended profiles, but those profile files
do not exist yet. That red is CORRECT and must not be faked green — the gate turns
green only when the referenced profiles are authored.

One check per biome family. record_count == number of biome families.

Core is importable:
    validate_pack(pack, strict, biomes_root=None, profiles_root=None)
        -> ValidationReport
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta, hash_obj
from world_pack_maps import report_dir_for

import biomes as B
import profiles as P
from validate_biome_contract import load_world_pack

CODE = FailureCode.BIOME_ENVIRONMENT_COMPATIBILITY_FAILURE


def _missing_referenced_profiles(biome, profiles_root):
    """Return a sorted list of 'kind/name' referenced profiles that do not resolve."""
    missing = []
    referenced = B.referenced_profile_names(biome)
    for kind, names in referenced.items():
        try:
            present = set(P.list_profiles(kind, profiles_root))
        except P.ProfileError:
            present = set()
        for name in sorted(set(names)):
            if name not in present:
                missing.append("{}/{}".format(kind, name))
                continue
            try:
                P.load_profile(kind, name, profiles_root)
            except P.ProfileError as exc:
                missing.append("{}/{} (unloadable: {})".format(kind, name, exc))
    return sorted(missing)


def validate_pack(pack, strict, biomes_root=None, profiles_root=None):
    """Importable core. Returns a ValidationReport (call .finalize()/.write())."""
    world_pack_id, families = load_world_pack(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    if not families:
        rep.check("pack_declares_biome_families", False,
                  "world pack '{}' declares no biome_families".format(world_pack_id),
                  code=CODE)

    for bid in families:
        tag = "biome_env_compat::{}".format(bid)
        try:
            biome = B.load_biome(bid, biomes_root)
        except B.BiomeError as exc:
            rep.check(tag, False, str(exc), code=CODE)
            continue

        missing = _missing_referenced_profiles(biome, profiles_root)
        rep.check(
            tag, not missing,
            "biome '{}': all referenced profiles resolve".format(bid) if not missing else
            "biome '{}': {} referenced profile(s) do not resolve: {}".format(
                bid, len(missing), ", ".join(missing)),
            code=CODE,
        )

    rep.set_meta(build_meta(
        command="validate-biome-environment-compatibility", pack=world_pack_id,
        strict=strict, status=None, record_count=len(families),
        input_spec_hash=hash_obj(sorted(families)),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate that biome-referenced profiles resolve, for a world pack.")
    parser.add_argument("--pack", default="biome_expansion_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--biomes-root", default=None,
                        help="override biomes root (for fixtures/tests)")
    parser.add_argument("--profiles-root", default=None,
                        help="override profiles root (for fixtures/tests)")
    parser.add_argument("--bindings-path", default=None,
                        help="unused; accepted for CLI uniformity")
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.biomes_root, args.profiles_root)
    _, families = load_world_pack(args.pack)
    rep.finalize()
    rep.write(report_dir_for(rep.entity_id),
              "validate_biome_environment_compatibility_report.json")
    rep.print_summary("validate-biome-environment-compatibility")
    print("[validate-biome-environment-compatibility] records={} (biome families in pack)".format(
        len(families)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
