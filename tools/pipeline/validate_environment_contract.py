#!/usr/bin/env python3
"""validate_environment_contract.py — WorldForge v1.0x environment/visual contract gate.

Proves that EVERY map in a world pack binds to a materially-real environment
profile: the binding exists and resolves, all referenced child profiles exist and
carry their required fields, every profile is materially distinct from its
siblings (no name-only clones), no incompatible profile combinations are used,
the default is explicitly declared and itself valid, and each environment's name
matches its declared behavior class.

Follows the v1.0x shared build contract (V10X_AGENT_CONTRACT.md): iterate via
enumerate_maps, one ValidationReport per pack, one check per map plus profile-
level checks, meta attached, record_count == number of maps, canonical report
path.

Core is importable:  validate_pack(pack, strict, profiles_root=None,
bindings_path=None) -> ValidationReport   (the negative harness injects broken
roots through the optional overrides).
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta, hash_obj, flag_from_env
from world_pack_maps import enumerate_maps, report_dir_for

import profiles as P


def _check_profile_fields(rep, kind, name, data, code):
    """Add a required-fields check for one loaded profile. Return True if OK."""
    required = P.REQUIRED_FIELDS.get(kind, ())
    missing = [f for f in required if f not in data]
    ok = not missing
    rep.check(
        "profile_fields::{}::{}".format(kind, name),
        ok,
        "missing required fields: {}".format(missing) if missing
        else "all required fields present ({})".format(len(required)),
        code=code,
    )
    return ok


def _materiality_for_kind(rep, kind, profiles_root):
    """Flag any pair of sibling profiles that are name-only / near clones.

    Two siblings differing in fewer than 2 comparable fields are a materiality
    violation (0 diffs == name-only clone; 1 diff == near-clone that violates the
    'differ in MULTIPLE concrete fields' rule).
    """
    names = P.list_profiles(kind, profiles_root)
    loaded = {}
    for n in names:
        try:
            loaded[n] = P.load_profile(kind, n, profiles_root)
        except P.ProfileError as exc:
            rep.check("profile_loadable::{}::{}".format(kind, n), False, str(exc),
                      code=FailureCode.ENVIRONMENT_PROFILE_FAILURE)
    for i, a in enumerate(names):
        if a not in loaded:
            continue
        for b in names[i + 1:]:
            if b not in loaded:
                continue
            diffs = P.material_diff_count(loaded[a], loaded[b])
            rep.check(
                "materiality::{}::{}__vs__{}".format(kind, a, b),
                diffs >= 2,
                "{} vs {} differ in {} field(s) (need >= 2)".format(a, b, diffs),
                code=FailureCode.PROFILE_NOT_MATERIAL,
            )


def _validate_referenced_environments(rep, env_names, profiles_root):
    """Field + class-name + compat checks for the set of environments actually used."""
    for env_name in sorted(env_names):
        try:
            resolved = P.resolve_environment(env_name, profiles_root)
        except P.ProfileError as exc:
            rep.check("environment_resolves::{}".format(env_name), False, str(exc),
                      code=FailureCode.ENVIRONMENT_PROFILE_FAILURE)
            continue
        rep.check("environment_resolves::{}".format(env_name), True,
                  "resolved with {} children".format(len(resolved["children"])))

        env = resolved["environment"]
        _check_profile_fields(rep, "environment", env_name, env,
                              FailureCode.ENVIRONMENT_PROFILE_FAILURE)
        for kind, child in resolved["children"].items():
            code = {
                "sky": FailureCode.SKY_PROFILE_FAILURE,
                "lighting": FailureCode.LIGHTING_PROFILE_FAILURE,
                "fog": FailureCode.FOG_PROFILE_FAILURE,
                "atmosphere": FailureCode.ATMOSPHERE_PROFILE_FAILURE,
                "visual_style": FailureCode.VISUAL_STYLE_FAILURE,
                "rendering": FailureCode.RENDERING_PROFILE_FAILURE,
                "scalability": FailureCode.SCALABILITY_FAILURE,
                "ray_tracing": FailureCode.RAYTRACING_FAILURE,
            }.get(kind, FailureCode.ENVIRONMENT_PROFILE_FAILURE)
            _check_profile_fields(rep, kind, env.get(kind), child, code)

        # name <-> behavior class consistency.
        env_class = env.get("class")
        rep.check(
            "class_name_match::{}".format(env_name),
            P.name_matches_class(env_name, env_class),
            "name does not carry a token for class={!r}".format(env_class),
            code=FailureCode.ENVIRONMENT_PROFILE_FAILURE,
        )

        # compatibility matrix.
        reasons = P.incompatible(resolved)
        rep.check(
            "compatible::{}".format(env_name),
            not reasons,
            "; ".join(reasons) if reasons else "no incompatible combinations",
            code=FailureCode.PROFILE_INCOMPATIBLE,
        )


def validate_pack(pack, strict, profiles_root=None, bindings_path=None):
    """Importable core. Returns a finalized-on-write ValidationReport."""
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    # ---- load the binding overlay (hard fail if absent/unparseable) ----------
    try:
        bindings = P.load_bindings(world_pack_id, profiles_root, bindings_path)
    except P.ProfileError as exc:
        rep.check("binding_overlay_loads", False, str(exc),
                  code=FailureCode.PROFILE_MISSING_BINDING)
        rep.set_meta(build_meta(command="validate-environment-contract",
                                pack=world_pack_id, strict=strict, status=None,
                                record_count=len(maps)))
        return rep
    rep.check("binding_overlay_loads", True,
              "{} explicit binding(s)".format(len(bindings.get("bindings", {}))))

    # ---- default must be explicitly declared AND itself valid ----------------
    default_env = bindings.get("default_environment_profile")
    rep.check("default_environment_declared", bool(default_env),
              "default_environment_profile is not declared",
              code=FailureCode.PROFILE_MISSING_BINDING)
    referenced_envs = set()
    if default_env:
        try:
            P.resolve_environment(default_env, profiles_root)
            rep.check("default_environment_valid", True,
                      "default '{}' resolves".format(default_env))
            referenced_envs.add(default_env)
        except P.ProfileError as exc:
            rep.check("default_environment_valid", False, str(exc),
                      code=FailureCode.ENVIRONMENT_PROFILE_FAILURE)

    # ---- per-map binding checks (one check per map, record_count == len) -----
    if not maps:
        rep.check("pack_has_maps", False, "world pack enumerated zero maps",
                  code=FailureCode.PROFILE_MISSING_BINDING)

    for m in maps:
        slice_id = m.slice_id
        tag = "env_binding::{}".format(slice_id or "<unknown>")

        if not slice_id or not m.spec_exists:
            rep.check(tag, False,
                      "coverage shortfall: {}".format(m.get("spec_error") or "no slice_id"),
                      code=FailureCode.ENVIRONMENT_PROFILE_FAILURE)
            continue

        env_name, source = P.environment_for(
            world_pack_id, slice_id, profiles_root, bindings_path, bindings=bindings)

        if env_name is None:
            rep.check(tag, False, "no explicit binding and no declared default",
                      code=FailureCode.PROFILE_MISSING_BINDING)
            continue

        if source == "default":
            # No implicit fallback in strict: every slice must be listed explicitly.
            rep.check(
                tag, False,
                "slice not explicitly bound (fell back to default '{}')".format(env_name),
                warn_only=True,
                code=FailureCode.PROFILE_MISSING_BINDING,
            )
            continue

        referenced_envs.add(env_name)
        try:
            resolved = P.resolve_environment(env_name, profiles_root)
        except P.ProfileError as exc:
            rep.check(tag, False,
                      "binding '{}' does not resolve: {}".format(env_name, exc),
                      code=FailureCode.ENVIRONMENT_PROFILE_FAILURE)
            continue

        reasons = P.incompatible(resolved)
        if reasons:
            rep.check(tag, False,
                      "binding '{}' incompatible: {}".format(env_name, "; ".join(reasons)),
                      code=FailureCode.PROFILE_INCOMPATIBLE)
            continue

        rep.check(tag, True, "bound -> {} ({})".format(env_name, source))

    # ---- profile-level checks (once) -----------------------------------------
    _validate_referenced_environments(rep, referenced_envs, profiles_root)
    for kind in P.PROFILE_KINDS:
        _materiality_for_kind(rep, kind, profiles_root)

    rep.set_meta(build_meta(
        command="validate-environment-contract", pack=world_pack_id, strict=strict,
        status=None, record_count=len(maps),
        input_spec_hash=hash_obj(sorted(bindings.get("bindings", {}).items())),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate the environment/visual-profile contract for a world pack.")
    parser.add_argument("--pack", default="desert_mvp_world",
                        help="world pack id (default: desert_mvp_world)")
    parser.add_argument("--strict", action="store_true", help="hostile / strict mode")
    parser.add_argument("--profiles-root", default=None,
                        help="override profiles root (for fixtures/tests)")
    parser.add_argument("--bindings-path", default=None,
                        help="override binding overlay path (for fixtures/tests)")
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.profiles_root, args.bindings_path)

    _, maps = enumerate_maps(args.pack)
    world_pack_id = rep.entity_id
    report_dir = report_dir_for(world_pack_id)
    rep.finalize()
    rep.write(report_dir, "validate_environment_contract_report.json")
    rep.print_summary("validate-environment-contract")
    print("[validate-environment-contract] records={} (maps in pack)".format(len(maps)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
