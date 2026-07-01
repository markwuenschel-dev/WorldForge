#!/usr/bin/env python3
"""validate_lighting.py — WorldForge v1.0x lighting-profile gate.

Proves that EVERY map in a world pack binds to a materially-real, internally
consistent LIGHTING profile: the profile carries its required fields, defines a
sane exposure window (no guaranteed black frame, no guaranteed over-bright), the
environment's actual exposure sits inside that window, a directional (key) light
is declared, dynamic-light usage stays within an explicit budget, and the profile
never demands a renderer capability (ray tracing / Lumen) that the environment's
rendering + ray_tracing profiles have switched off.

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
EXPOSURE_ABS_MIN = -4.0    # below this, the frame is guaranteed black -> contract violation
EXPOSURE_ABS_MAX = 5.0     # above this, the frame is guaranteed blown out -> contract violation
RAY_TRACING_OFF = "off"


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _lighting_reasons(env_name, resolved, rep, tag):
    """Return (reasons, exposure_reasons). exposure_reasons are tagged separately."""
    reasons = []
    exposure_reasons = []
    ch = resolved["children"]
    lighting = ch["lighting"]
    post = ch["post_process"]
    rendering = ch["rendering"]
    ray_tracing = ch["ray_tracing"]

    missing = [f for f in P.REQUIRED_FIELDS["lighting"] if f not in lighting]
    if missing:
        reasons.append("lighting missing required fields: {}".format(missing))
        return reasons, exposure_reasons

    # directional (key) light must be declared and present.
    if lighting.get("directional_light") is not True:
        reasons.append("lighting has no directional_light (key light) declared")

    # exposure window must be well-formed and inside sane absolute bounds.
    emin = _num(lighting.get("exposure_ev_min"))
    emax = _num(lighting.get("exposure_ev_max"))
    if emin is None or emax is None:
        exposure_reasons.append("lighting exposure_ev_min/max missing or non-numeric")
    else:
        if emin >= emax:
            exposure_reasons.append(
                "exposure window inverted/empty: min={} >= max={}".format(emin, emax))
        if emin < EXPOSURE_ABS_MIN:
            exposure_reasons.append(
                "exposure_ev_min={} below black-frame floor {}".format(emin, EXPOSURE_ABS_MIN))
        if emax > EXPOSURE_ABS_MAX:
            exposure_reasons.append(
                "exposure_ev_max={} above over-bright ceiling {}".format(emax, EXPOSURE_ABS_MAX))
        # the environment's real exposure must fall inside the window.
        actual = _num(post.get("exposure_ev"))
        if actual is None:
            exposure_reasons.append("post_process.exposure_ev missing or non-numeric")
        elif not (emin <= actual <= emax):
            exposure_reasons.append(
                "post_process.exposure_ev={} outside lighting window [{}, {}]".format(
                    actual, emin, emax))

    # dynamic-light budget must be explicit and respected (no unbounded lights).
    count = _num(lighting.get("dynamic_light_count"))
    budget = _num(lighting.get("dynamic_light_count_budget"))
    if count is None or budget is None:
        reasons.append("lighting dynamic_light_count/budget missing or non-numeric")
    else:
        if budget <= 0:
            reasons.append("lighting dynamic_light_count_budget={} is not positive".format(budget))
        if count > budget:
            reasons.append(
                "dynamic_light_count={} exceeds budget={}".format(count, budget))

    # must not require ray tracing when the environment has it switched off.
    if lighting.get("requires_ray_tracing") is True:
        mode = ray_tracing.get("mode")
        if mode == RAY_TRACING_OFF or rendering.get("ray_tracing") == RAY_TRACING_OFF:
            reasons.append(
                "lighting requires_ray_tracing but ray_tracing.mode={!r} / "
                "rendering.ray_tracing={!r}".format(mode, rendering.get("ray_tracing")))

    # must not require Lumen when the environment's renderer disables it.
    if lighting.get("requires_lumen") is True and rendering.get("lumen") is not True:
        reasons.append(
            "lighting requires_lumen but rendering.lumen={!r}".format(rendering.get("lumen")))

    return reasons, exposure_reasons


def validate_pack(pack, strict, profiles_root=None, bindings_path=None):
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    try:
        bindings = P.load_bindings(world_pack_id, profiles_root, bindings_path)
    except P.ProfileError as exc:
        rep.check("binding_overlay_loads", False, str(exc),
                  code=FailureCode.LIGHTING_PROFILE_FAILURE)
        rep.set_meta(build_meta(command="validate-lighting", pack=world_pack_id,
                                strict=strict, status=None, record_count=len(maps)))
        return rep

    if not maps:
        rep.check("pack_has_maps", False, "world pack enumerated zero maps",
                  code=FailureCode.LIGHTING_PROFILE_FAILURE)

    for m in maps:
        slice_id = m.slice_id
        tag = "lighting::{}".format(slice_id or "<unknown>")

        if not slice_id or not m.spec_exists:
            rep.check(tag, False,
                      "coverage shortfall: {}".format(m.get("spec_error") or "no slice_id"),
                      code=FailureCode.LIGHTING_PROFILE_FAILURE)
            continue

        env_name, source = P.environment_for(
            world_pack_id, slice_id, profiles_root, bindings_path, bindings=bindings)
        if env_name is None:
            rep.check(tag, False, "no explicit binding and no declared default",
                      code=FailureCode.LIGHTING_PROFILE_FAILURE)
            continue

        try:
            resolved = P.resolve_environment(env_name, profiles_root)
        except P.ProfileError as exc:
            rep.check(tag, False, "env '{}' does not resolve: {}".format(env_name, exc),
                      code=FailureCode.LIGHTING_PROFILE_FAILURE)
            continue

        reasons, exposure_reasons = _lighting_reasons(env_name, resolved, rep, tag)
        light_name = resolved["environment"].get("lighting")

        # primary per-map lighting check.
        rep.check(
            tag, not reasons,
            "lighting '{}' via env '{}': {}".format(light_name, env_name, "; ".join(reasons))
            if reasons else "lighting '{}' consistent (env {})".format(light_name, env_name),
            code=FailureCode.LIGHTING_PROFILE_FAILURE,
        )
        # exposure gets its own coded check per map.
        rep.check(
            "exposure::{}".format(slice_id), not exposure_reasons,
            "lighting '{}' via env '{}': {}".format(
                light_name, env_name, "; ".join(exposure_reasons))
            if exposure_reasons else "exposure within range (env {})".format(env_name),
            code=FailureCode.EXPOSURE_OUT_OF_RANGE,
        )

    rep.set_meta(build_meta(
        command="validate-lighting", pack=world_pack_id, strict=strict, status=None,
        record_count=len(maps),
        input_spec_hash=hash_obj(sorted(bindings.get("bindings", {}).items())),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate lighting profiles for a world pack.")
    parser.add_argument("--pack", default="desert_mvp_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--profiles-root", default=None)
    parser.add_argument("--bindings-path", default=None)
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.profiles_root, args.bindings_path)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_lighting_report.json")
    rep.print_summary("validate-lighting")
    _, maps = enumerate_maps(args.pack)
    print("[validate-lighting] records={} (maps in pack)".format(len(maps)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
