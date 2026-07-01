#!/usr/bin/env python3
"""validate_raytracing.py — WorldForge v1.0x ray-tracing compatibility gate (Agent 6).

Proves that ray-tracing on/off is EXPLICIT and COHERENT for every map, and that
the pack exercises both an RT-on and an RT-off path (so neither is silently
broken):

  * the rendering profile's ray_tracing field (off/optional/required) and the
    environment's ray_tracing.mode (off/selective/full) are both present and
    drawn from their vocabularies — RT posture is never implicit;
  * a rendering profile that REQUIRES ray tracing is only ever bound to an
    environment whose ray_tracing supports it (mode != off), and a rendering
    profile that declares ray_tracing=off is only bound to mode==off;
  * an RT-on environment is not paired with an excessive-cost rendering profile
    (RT + heavy volumetric fog is a frame-risk and is rejected here);
  * across the whole pack at least one RT-on and one RT-off map both validate.

Tagged FailureCode.RAYTRACING_FAILURE. Report validate_raytracing_report.json.
Core: validate_pack(pack, strict, profiles_root=None, bindings_path=None).
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

RTCODE = FailureCode.RAYTRACING_FAILURE

RT_MODE_VOCAB = ("off", "selective", "full")
RENDER_RT_VOCAB = ("off", "optional", "required")


def _resolve_env(rep, world_pack_id, m, bindings, profiles_root, bindings_path):
    slice_id = m.slice_id
    tag = "rt_binding::{}".format(slice_id or "<unknown>")
    if not slice_id or not m.spec_exists:
        rep.check(tag, False,
                  "coverage shortfall: {}".format(m.get("spec_error") or "no slice_id"),
                  code=RTCODE)
        return None, None
    env_name, source = P.environment_for(
        world_pack_id, slice_id, profiles_root, bindings_path, bindings=bindings)
    if env_name is None:
        rep.check(tag, False, "no explicit binding and no declared default",
                  code=FailureCode.PROFILE_MISSING_BINDING)
        return None, None
    if source == "default":
        rep.check(tag, False,
                  "slice not explicitly bound (fell back to default '{}')".format(env_name),
                  warn_only=True, code=FailureCode.PROFILE_MISSING_BINDING)
        return None, None
    try:
        resolved = P.resolve_environment(env_name, profiles_root)
    except P.ProfileError as exc:
        rep.check(tag, False, "binding '{}' does not resolve: {}".format(env_name, exc),
                  code=RTCODE)
        return None, None
    return env_name, resolved


def _check_raytracing(rep, slice_id, env_name, rendering, ray_tracing):
    """Return 'on' / 'off' / None (None == an error was recorded)."""
    base = "raytracing::{}".format(slice_id)
    rt_field = str(rendering.get("ray_tracing"))
    rt_mode = str(ray_tracing.get("mode"))

    # 1. RT posture explicit + valid on both sides.
    explicit = (rt_field in RENDER_RT_VOCAB) and (rt_mode in RT_MODE_VOCAB)
    rep.check(base + "::rt_explicit", explicit,
              "RT posture not explicit: rendering.ray_tracing={!r}, ray_tracing.mode={!r}".format(
                  rendering.get("ray_tracing"), ray_tracing.get("mode")), code=RTCODE)
    if not explicit:
        return None

    # 2. on/off compatibility.
    if rt_field == "required":
        rep.check(base + "::rt_required_supported", rt_mode != "off",
                  "rendering requires RT but env {} ray_tracing.mode=off".format(env_name),
                  code=RTCODE)
    elif rt_field == "off":
        rep.check(base + "::rt_off_consistent", rt_mode == "off",
                  "rendering declares ray_tracing=off but env {} ray_tracing.mode={}".format(
                      env_name, rt_mode), code=RTCODE)

    rt_on = rt_mode != "off"

    # 3. RT-on must not be paired with excessive volumetric fog (frame-risk).
    if rt_on:
        fog = rendering.get("volumetric_fog")
        rep.check(base + "::rt_not_excessive", fog != "heavy",
                  "RT-on env {} paired with rendering volumetric_fog={!r} (excessive)".format(
                      env_name, fog), code=RTCODE)
        # RT-on with GI/reflections declared but the rt_ fields all disabled is a
        # contradiction (env claims RT but the RT profile does nothing).
        does_something = any(bool(ray_tracing.get(k)) for k in
                             ("rt_reflections", "rt_gi", "rt_shadows", "rt_ao"))
        rep.check(base + "::rt_effective", does_something,
                  "env {} ray_tracing.mode={} but no rt_* feature enabled".format(
                      env_name, rt_mode), code=RTCODE)

    return "on" if rt_on else "off"


def validate_pack(pack, strict, profiles_root=None, bindings_path=None):
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    try:
        bindings = P.load_bindings(world_pack_id, profiles_root, bindings_path)
    except P.ProfileError as exc:
        rep.check("binding_overlay_loads", False, str(exc),
                  code=FailureCode.PROFILE_MISSING_BINDING)
        rep.set_meta(build_meta(command="validate-raytracing", pack=world_pack_id,
                                strict=strict, status=None, record_count=len(maps)))
        return rep
    rep.check("binding_overlay_loads", True,
              "{} explicit binding(s)".format(len(bindings.get("bindings", {}))))

    if not maps:
        rep.check("pack_has_maps", False, "world pack enumerated zero maps", code=RTCODE)

    postures = {"on": 0, "off": 0}
    for m in maps:
        env_name, resolved = _resolve_env(
            rep, world_pack_id, m, bindings, profiles_root, bindings_path)
        if resolved is None:
            continue
        rendering = resolved["children"]["rendering"]
        ray_tracing = resolved["children"]["ray_tracing"]
        posture = _check_raytracing(rep, m.slice_id, env_name, rendering, ray_tracing)
        if posture in postures:
            postures[posture] += 1

    # both RT-on and RT-off must be present AND valid across the pack.
    rep.check("raytracing::coverage_rt_on", postures["on"] >= 1,
              "no valid RT-on map in the pack (RT-on path unproven)", code=RTCODE)
    rep.check("raytracing::coverage_rt_off", postures["off"] >= 1,
              "no valid RT-off map in the pack (RT-off path unproven)", code=RTCODE)

    rep.set_meta(build_meta(
        command="validate-raytracing", pack=world_pack_id, strict=strict, status=None,
        record_count=len(maps),
        input_spec_hash=hash_obj(sorted(bindings.get("bindings", {}).items())),
        extra={"rt_on_maps": postures["on"], "rt_off_maps": postures["off"]},
    ))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate ray-tracing compatibility for a world pack.")
    ap.add_argument("--pack", default="desert_mvp_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--profiles-root", default=None)
    ap.add_argument("--bindings-path", default=None)
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.profiles_root, args.bindings_path)
    _, maps = enumerate_maps(args.pack)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_raytracing_report.json")
    rep.print_summary("validate-raytracing")
    print("[validate-raytracing] records={} (maps in pack)".format(len(maps)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
