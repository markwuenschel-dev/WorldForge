#!/usr/bin/env python3
"""validate_sky.py — WorldForge v1.0x sky-profile gate.

Proves that EVERY map in a world pack binds to a materially-real, internally
consistent SKY profile: the sky profile exists and carries its required fields,
its sky model is a real model, cloud modelling is present when the coverage
demands it, the sky's time-of-day affinity matches the environment's declared
time_of_day, the sun-disk visibility agrees with the sun angle, a night sky is
only used at night (and never with daytime exposure assumptions), and a
storm/dust sky is only used where the fog + lighting agree it is a storm.

Follows the v1.0x shared build contract (V10X_AGENT_CONTRACT.md): iterate via
enumerate_maps, one ValidationReport per pack, one check per map, meta attached,
record_count == number of maps, canonical report path.

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
SKY_MODELS = ("physical", "gradient")
CLOUD_MODELS = ("procedural", "volumetric", "painted", "none")
CLOUD_VOLUMETRIC_COVERAGE = 0.5    # >= this coverage requires a volumetric cloud model
CLOUD_PRESENT_COVERAGE = 0.25      # >= this coverage requires a non-'none' cloud model
NIGHT_EXPOSURE_MIN = 1.5           # a night sky must run with lifted (night) exposure
STORM_FOG_MIN = 0.5                # a storm/dust sky needs genuinely thick fog
STORM_SUN_MAX_LUX = 60000          # a storm/dust sky needs filtered (not full) sun


def _sky_reasons(env_name, resolved):
    """Return a list of human-readable sky incompatibility reasons (empty == OK)."""
    reasons = []
    ch = resolved["children"]
    sky = ch["sky"]
    tod = ch["time_of_day"]
    fog = ch["fog"]
    lighting = ch["lighting"]
    post = ch["post_process"]

    # required fields present (defence in depth; env-contract also checks).
    missing = [f for f in P.REQUIRED_FIELDS["sky"] if f not in sky]
    if missing:
        reasons.append("sky missing required fields: {}".format(missing))
        return reasons  # cannot reason further without the basics

    # sky model must be a real, supported model.
    model = sky.get("model")
    if model not in SKY_MODELS:
        reasons.append("sky model {!r} not in {}".format(model, list(SKY_MODELS)))

    # cloud modelling present when coverage demands it.
    try:
        coverage = float(sky.get("cloud_coverage"))
    except (TypeError, ValueError):
        coverage = None
        reasons.append("sky cloud_coverage non-numeric")
    cloud_model = sky.get("cloud_model")
    if cloud_model is not None and cloud_model not in CLOUD_MODELS:
        reasons.append("sky cloud_model {!r} not in {}".format(cloud_model, list(CLOUD_MODELS)))
    if coverage is not None:
        if coverage >= CLOUD_VOLUMETRIC_COVERAGE and cloud_model != "volumetric":
            reasons.append(
                "cloud_coverage={} >= {} requires cloud_model=volumetric (got {!r})".format(
                    coverage, CLOUD_VOLUMETRIC_COVERAGE, cloud_model))
        elif coverage >= CLOUD_PRESENT_COVERAGE and cloud_model in (None, "none"):
            reasons.append(
                "cloud_coverage={} >= {} requires a cloud model (got {!r})".format(
                    coverage, CLOUD_PRESENT_COVERAGE, cloud_model))

    # sun direction / time-of-day coupling.
    phase = tod.get("phase")
    affinity = sky.get("time_of_day_affinity")
    if not isinstance(affinity, (list, tuple)) or not affinity:
        reasons.append("sky missing time_of_day_affinity list")
    elif phase not in affinity:
        reasons.append(
            "environment time_of_day.phase={!r} not in sky time_of_day_affinity={}".format(
                phase, list(affinity)))

    # sun-disk visibility must agree with the sun angle.
    sun_visible = sky.get("sun_visible")
    try:
        sun_angle = float(tod.get("sun_angle_deg"))
    except (TypeError, ValueError):
        sun_angle = None
        reasons.append("time_of_day.sun_angle_deg non-numeric")
    if sun_visible is None:
        reasons.append("sky missing sun_visible flag")
    elif sun_angle is not None:
        if sun_angle < 0 and sun_visible:
            reasons.append(
                "sun_angle_deg={} is below horizon but sky.sun_visible=true".format(sun_angle))
        if sun_angle >= 0 and not sun_visible:
            reasons.append(
                "sun_angle_deg={} is above horizon but sky.sun_visible=false".format(sun_angle))

    # night sky must be used at night AND must not assume daytime exposure.
    is_night = bool(sky.get("night"))
    if is_night:
        if phase != "night":
            reasons.append(
                "night sky used with time_of_day.phase={!r} (expected night)".format(phase))
        try:
            exposure = float(post.get("exposure_ev"))
        except (TypeError, ValueError):
            exposure = None
            reasons.append("night sky but post_process.exposure_ev non-numeric")
        if exposure is not None and exposure < NIGHT_EXPOSURE_MIN:
            reasons.append(
                "night sky uses daytime exposure post_process.exposure_ev={} "
                "(< night minimum {})".format(exposure, NIGHT_EXPOSURE_MIN))
    else:
        if phase == "night":
            reasons.append("non-night sky used at time_of_day.phase=night")

    # storm/dust sky must agree with the fog + lighting (it is genuinely a storm).
    if bool(sky.get("storm")):
        try:
            density = float(fog.get("density"))
        except (TypeError, ValueError):
            density = None
            reasons.append("storm sky but fog.density non-numeric")
        if density is not None and density < STORM_FOG_MIN:
            reasons.append(
                "storm sky but fog.density={} < {} (storm needs thick fog)".format(
                    density, STORM_FOG_MIN))
        try:
            lux = float(lighting.get("sun_intensity_lux"))
        except (TypeError, ValueError):
            lux = None
            reasons.append("storm sky but lighting.sun_intensity_lux non-numeric")
        if lux is not None and lux > STORM_SUN_MAX_LUX:
            reasons.append(
                "storm sky but lighting.sun_intensity_lux={} > {} (sun not filtered)".format(
                    lux, STORM_SUN_MAX_LUX))

    return reasons


def validate_pack(pack, strict, profiles_root=None, bindings_path=None):
    """Importable core. Returns a ValidationReport (call .finalize()/.write())."""
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    try:
        bindings = P.load_bindings(world_pack_id, profiles_root, bindings_path)
    except P.ProfileError as exc:
        rep.check("binding_overlay_loads", False, str(exc),
                  code=FailureCode.SKY_PROFILE_FAILURE)
        rep.set_meta(build_meta(command="validate-sky", pack=world_pack_id,
                                strict=strict, status=None, record_count=len(maps)))
        return rep

    if not maps:
        rep.check("pack_has_maps", False, "world pack enumerated zero maps",
                  code=FailureCode.SKY_PROFILE_FAILURE)

    for m in maps:
        slice_id = m.slice_id
        tag = "sky::{}".format(slice_id or "<unknown>")

        if not slice_id or not m.spec_exists:
            rep.check(tag, False,
                      "coverage shortfall: {}".format(m.get("spec_error") or "no slice_id"),
                      code=FailureCode.SKY_PROFILE_FAILURE)
            continue

        env_name, source = P.environment_for(
            world_pack_id, slice_id, profiles_root, bindings_path, bindings=bindings)
        if env_name is None:
            rep.check(tag, False, "no explicit binding and no declared default",
                      code=FailureCode.SKY_PROFILE_FAILURE)
            continue

        try:
            resolved = P.resolve_environment(env_name, profiles_root)
        except P.ProfileError as exc:
            rep.check(tag, False, "env '{}' does not resolve: {}".format(env_name, exc),
                      code=FailureCode.SKY_PROFILE_FAILURE)
            continue

        reasons = _sky_reasons(env_name, resolved)
        rep.check(
            tag, not reasons,
            "sky '{}' via env '{}': {}".format(
                resolved["environment"].get("sky"), env_name, "; ".join(reasons))
            if reasons else "sky '{}' consistent (env {})".format(
                resolved["environment"].get("sky"), env_name),
            code=FailureCode.SKY_PROFILE_FAILURE,
        )

    rep.set_meta(build_meta(
        command="validate-sky", pack=world_pack_id, strict=strict, status=None,
        record_count=len(maps),
        input_spec_hash=hash_obj(sorted(bindings.get("bindings", {}).items())),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate sky profiles for a world pack.")
    parser.add_argument("--pack", default="desert_mvp_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--profiles-root", default=None)
    parser.add_argument("--bindings-path", default=None)
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.profiles_root, args.bindings_path)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_sky_report.json")
    rep.print_summary("validate-sky")
    _, maps = enumerate_maps(args.pack)
    print("[validate-sky] records={} (maps in pack)".format(len(maps)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
