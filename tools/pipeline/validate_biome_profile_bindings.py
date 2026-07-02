#!/usr/bin/env python3
"""validate_biome_profile_bindings.py — WorldForge v1.1 BiomeForge binding gate.

Proves that every map in a biome world pack is bound to an environment profile that
is (a) explicitly declared (no implicit fallback to the default in strict mode),
(b) permitted by the biome the map belongs to — i.e. the env name appears in that
biome's ``environment_profiles`` allow-list — and (c) materially real: it resolves
via ``profiles.resolve_environment`` with all of its child profiles present.

Maps are enumerated through the shared ``enumerate_maps`` so this gate agrees with
every other lane about "every map"; a map whose slice pack or slice_id is missing is
surfaced as a coverage shortfall rather than silently dropped.

This gate legitimately stays RED until the new-biome environment composites exist
(Agent 3): the bindings point at real, biome-declared env names, but those profiles
must be materialized before (c) can pass. That is honest — do not weaken (c).

Core is importable:
    validate_pack(pack, strict, biomes_root=None, profiles_root=None,
                  bindings_path=None) -> ValidationReport
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta, hash_obj
from world_pack_maps import enumerate_maps, report_dir_for

import biomes as B
import profiles as P

CODE = FailureCode.BIOME_PROFILE_BINDING_FAILURE


def validate_pack(pack, strict, biomes_root=None, profiles_root=None, bindings_path=None):
    """Importable core. Returns a ValidationReport (call .finalize()/.write())."""
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    # ---- load the binding overlay (hard fail if absent/unparseable) ----------
    try:
        bindings = P.load_bindings(world_pack_id, profiles_root, bindings_path)
    except P.ProfileError as exc:
        rep.check("binding_overlay_loads", False, str(exc), code=CODE)
        rep.set_meta(build_meta(command="validate-biome-profile-bindings",
                                pack=world_pack_id, strict=strict, status=None,
                                record_count=len(maps)))
        return rep
    rep.check("binding_overlay_loads", True,
              "{} explicit binding(s)".format(len(bindings.get("bindings", {}))))

    if not maps:
        rep.check("pack_has_maps", False, "world pack enumerated zero maps", code=CODE)

    _biome_cache = {}

    def _biome(bid):
        if bid not in _biome_cache:
            _biome_cache[bid] = B.load_biome(bid, biomes_root)
        return _biome_cache[bid]

    for m in maps:
        slice_id = m.slice_id
        tag = "biome_binding::{}".format(slice_id or "<unknown>")

        if not slice_id:
            rep.check(tag, False, "coverage shortfall: {}".format(
                m.get("spec_error") or "no slice_id"), code=CODE)
            continue

        biome_id = m.get("biome")
        if not biome_id:
            rep.check(tag, False, "map '{}' has no biome".format(slice_id), code=CODE)
            continue
        try:
            biome = _biome(biome_id)
        except B.BiomeError as exc:
            rep.check(tag, False, "biome '{}' does not load: {}".format(biome_id, exc),
                      code=CODE)
            continue

        env_name, source = P.environment_for(
            world_pack_id, slice_id, profiles_root, bindings_path, bindings=bindings)
        if env_name is None:
            rep.check(tag, False, "no explicit binding and no declared default", code=CODE)
            continue
        if source != "explicit":
            # No implicit fallback: every slice must be listed explicitly.
            rep.check(tag, False,
                      "slice not explicitly bound (fell back to '{}' via {})".format(
                          env_name, source),
                      code=CODE)
            continue

        # (b) the biome must permit this environment profile.
        if not B.compatible(biome, "environment_profile", env_name):
            rep.check(tag, False,
                      "env '{}' not in biome '{}' environment_profiles allow-list {}".format(
                          env_name, biome_id, B.allowed_values(biome, "environment_profile")),
                      code=CODE)
            continue

        # (c) the environment profile must materially resolve.
        try:
            resolved = P.resolve_environment(env_name, profiles_root)
        except P.ProfileError as exc:
            rep.check(tag, False,
                      "biome-declared env '{}' does not resolve yet: {}".format(env_name, exc),
                      code=CODE)
            continue

        rep.check(tag, True,
                  "bound -> {} (biome {}, {} children)".format(
                      env_name, biome_id, len(resolved["children"])))

    rep.set_meta(build_meta(
        command="validate-biome-profile-bindings", pack=world_pack_id, strict=strict,
        status=None, record_count=len(maps),
        input_spec_hash=hash_obj(sorted(bindings.get("bindings", {}).items())),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate biome/environment profile bindings for a world pack.")
    parser.add_argument("--pack", default="biome_expansion_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--biomes-root", default=None,
                        help="override biomes root (for fixtures/tests)")
    parser.add_argument("--profiles-root", default=None,
                        help="override profiles root (for fixtures/tests)")
    parser.add_argument("--bindings-path", default=None,
                        help="override binding overlay path (for fixtures/tests)")
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.biomes_root, args.profiles_root,
                        args.bindings_path)
    _, maps = enumerate_maps(args.pack)
    rep.finalize()
    rep.write(report_dir_for(rep.entity_id), "validate_biome_profile_bindings_report.json")
    rep.print_summary("validate-biome-profile-bindings")
    print("[validate-biome-profile-bindings] records={} (maps in pack)".format(len(maps)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
