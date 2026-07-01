#!/usr/bin/env python3
"""validate_atmosphere.py — WorldForge v1.0x atmosphere-profile gate.

Proves that EVERY map in a world pack binds to a materially-real, internally
consistent ATMOSPHERE profile: the profile carries its required fields and is
compatible with the environment's sky, fog and lighting for its class — the
atmosphere's supported sky model matches the sky, the fog density stays within the
atmosphere's supported aerosol range, and a night atmosphere is only used at
night (with night-appropriate lighting).

Follows the v1.0x shared build contract (V10X_AGENT_CONTRACT.md).

Core is importable:
    validate_pack(pack, strict, profiles_root=None, bindings_path=None)
        -> ValidationReport
The negative harness injects a broken profiles tree through profiles_root.
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

import profiles as P

# -- checkable thresholds -----------------------------------------------------
NIGHT_SUN_LUX_MAX = 100     # a night atmosphere must be paired with night-level sun lighting


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _atmo_reasons(resolved):
    reasons = []
    ch = resolved["children"]
    atmo = ch["atmosphere"]
    sky = ch["sky"]
    fog = ch["fog"]
    tod = ch["time_of_day"]
    lighting = ch["lighting"]

    missing = [f for f in P.REQUIRED_FIELDS["atmosphere"] if f not in atmo]
    if missing:
        reasons.append("atmosphere missing required fields: {}".format(missing))
        return reasons

    # atmosphere <-> sky model compatibility.
    compat_models = atmo.get("compatible_sky_models")
    sky_model = sky.get("model")
    if not isinstance(compat_models, (list, tuple)) or not compat_models:
        reasons.append("atmosphere missing compatible_sky_models list")
    elif sky_model not in compat_models:
        reasons.append(
            "sky model {!r} not in atmosphere.compatible_sky_models={}".format(
                sky_model, list(compat_models)))

    # atmosphere <-> fog compatibility (aerosol range must cover the fog).
    fog_max = _num(atmo.get("compatible_fog_max_density"))
    density = _num(fog.get("density"))
    if fog_max is None:
        reasons.append("atmosphere missing/invalid compatible_fog_max_density")
    elif density is not None and density > fog_max:
        reasons.append(
            "fog.density={} exceeds atmosphere.compatible_fog_max_density={}".format(
                density, fog_max))

    # night atmosphere <-> time_of_day + lighting compatibility.
    is_night = bool(atmo.get("night"))
    phase = tod.get("phase")
    if is_night:
        if phase != "night":
            reasons.append(
                "night atmosphere used with time_of_day.phase={!r} (expected night)".format(phase))
        lux = _num(lighting.get("sun_intensity_lux"))
        if lux is not None and lux > NIGHT_SUN_LUX_MAX:
            reasons.append(
                "night atmosphere with daylight sun_intensity_lux={} (> {})".format(
                    lux, NIGHT_SUN_LUX_MAX))
    else:
        if phase == "night":
            reasons.append("non-night atmosphere used at time_of_day.phase=night")

    return reasons


def validate_pack(pack, strict, profiles_root=None, bindings_path=None):
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    try:
        bindings = P.load_bindings(world_pack_id, profiles_root, bindings_path)
    except P.ProfileError as exc:
        rep.check("binding_overlay_loads", False, str(exc),
                  code=FailureCode.ATMOSPHERE_PROFILE_FAILURE)
        rep.set_meta(build_meta(command="validate-atmosphere", pack=world_pack_id,
                                strict=strict, status=None, record_count=len(maps)))
        return rep

    if not maps:
        rep.check("pack_has_maps", False, "world pack enumerated zero maps",
                  code=FailureCode.ATMOSPHERE_PROFILE_FAILURE)

    for m in maps:
        slice_id = m.slice_id
        tag = "atmosphere::{}".format(slice_id or "<unknown>")

        if not slice_id or not m.spec_exists:
            rep.check(tag, False,
                      "coverage shortfall: {}".format(m.get("spec_error") or "no slice_id"),
                      code=FailureCode.ATMOSPHERE_PROFILE_FAILURE)
            continue

        env_name, source = P.environment_for(
            world_pack_id, slice_id, profiles_root, bindings_path, bindings=bindings)
        if env_name is None:
            rep.check(tag, False, "no explicit binding and no declared default",
                      code=FailureCode.ATMOSPHERE_PROFILE_FAILURE)
            continue

        try:
            resolved = P.resolve_environment(env_name, profiles_root)
        except P.ProfileError as exc:
            rep.check(tag, False, "env '{}' does not resolve: {}".format(env_name, exc),
                      code=FailureCode.ATMOSPHERE_PROFILE_FAILURE)
            continue

        reasons = _atmo_reasons(resolved)
        atmo_name = resolved["environment"].get("atmosphere")
        rep.check(
            tag, not reasons,
            "atmosphere '{}' via env '{}': {}".format(atmo_name, env_name, "; ".join(reasons))
            if reasons else "atmosphere '{}' consistent (env {})".format(atmo_name, env_name),
            code=FailureCode.ATMOSPHERE_PROFILE_FAILURE,
        )

    rep.set_meta(build_meta(
        command="validate-atmosphere", pack=world_pack_id, strict=strict, status=None,
        record_count=len(maps),
        input_spec_hash=hash_obj(sorted(bindings.get("bindings", {}).items())),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate atmosphere profiles for a world pack.")
    parser.add_argument("--pack", default="desert_mvp_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--profiles-root", default=None)
    parser.add_argument("--bindings-path", default=None)
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.profiles_root, args.bindings_path)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_atmosphere_report.json")
    rep.print_summary("validate-atmosphere")
    _, maps = enumerate_maps(args.pack)
    print("[validate-atmosphere] records={} (maps in pack)".format(len(maps)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
