#!/usr/bin/env python3
"""validate_fog.py — WorldForge v1.0x fog-profile gate.

Proves that EVERY map in a world pack binds to a materially-real, internally
consistent FOG profile: the profile carries its required fields, its density is in
range, playable (non-low-visibility) maps preserve a minimum visibility so the
player start is never fully occluded, fog is compatible with the lighting (thick
fog implies soft shadows), volumetric fog respects a performance budget, local fog
volumes stay within a cap, and any genuinely fog-heavy profile is explicitly
flagged low_visibility (and only used inside a low_visibility environment).

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
DENSITY_MIN = 0.0
DENSITY_MAX = 1.0
MAX_OPACITY_CEIL = 1.0          # fog must never be fully opaque (player must see *something*)
VISIBILITY_FLOOR_CM = 3000      # playable maps must keep at least this far visible
HEAVY_DENSITY = 0.7             # at/above this a fog profile is 'fog-heavy'
LOW_VIS_SHADOW_MAX = 0.6        # thick fog needs soft (not razor-crisp) shadows
LOCAL_FOG_VOLUME_CAP = 8        # global hard cap on local fog volumes per map


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _fog_reasons(resolved):
    """Return (fog_reasons, visibility_reasons)."""
    reasons = []
    vis_reasons = []
    env = resolved["environment"]
    ch = resolved["children"]
    fog = ch["fog"]
    lighting = ch["lighting"]

    missing = [f for f in P.REQUIRED_FIELDS["fog"] if f not in fog]
    if missing:
        reasons.append("fog missing required fields: {}".format(missing))
        return reasons, vis_reasons

    density = _num(fog.get("density"))
    if density is None:
        reasons.append("fog.density non-numeric")
    elif not (DENSITY_MIN <= density <= DENSITY_MAX):
        reasons.append("fog.density={} outside [{}, {}]".format(
            density, DENSITY_MIN, DENSITY_MAX))

    # fog must never fully occlude the view (player start stays readable).
    max_opacity = _num(fog.get("max_opacity"))
    if max_opacity is None:
        reasons.append("fog.max_opacity non-numeric")
    elif max_opacity >= MAX_OPACITY_CEIL:
        reasons.append("fog.max_opacity={} fully occludes (>= {})".format(
            max_opacity, MAX_OPACITY_CEIL))

    low_vis = bool(fog.get("low_visibility"))

    # fog-heavy profiles must be explicitly flagged low_visibility.
    if density is not None and density >= HEAVY_DENSITY and not low_vis:
        reasons.append(
            "fog-heavy (density={} >= {}) but not marked low_visibility".format(
                density, HEAVY_DENSITY))

    # low_visibility fog may only appear inside a low_visibility environment, and a
    # low_visibility environment must use low_visibility fog (two-way consistency).
    env_low_vis = env.get("low_visibility") is True
    if low_vis and not env_low_vis:
        reasons.append(
            "low_visibility fog used in non-low_visibility environment '{}'".format(
                env.get("name")))
    if env_low_vis and not low_vis:
        reasons.append(
            "low_visibility environment '{}' uses non-low_visibility fog".format(
                env.get("name")))

    # thick fog implies soft shadows (fog + lighting compatibility).
    if low_vis:
        sharp = _num(lighting.get("shadow_sharpness"))
        if sharp is not None and sharp > LOW_VIS_SHADOW_MAX:
            reasons.append(
                "low_visibility fog with harsh shadow_sharpness={} (> {})".format(
                    sharp, LOW_VIS_SHADOW_MAX))

    # volumetric fog performance budget.
    if bool(fog.get("volumetric")) and env.get("class") == "performance":
        reasons.append("volumetric fog used on a performance-class environment")

    # local fog volume cap.
    lfv = _num(fog.get("local_fog_volume_count"))
    budget = _num(fog.get("local_fog_volume_budget"))
    if lfv is None or budget is None:
        reasons.append("fog local_fog_volume_count/budget missing or non-numeric")
    else:
        if lfv > budget:
            reasons.append("local_fog_volume_count={} exceeds budget={}".format(lfv, budget))
        if lfv > LOCAL_FOG_VOLUME_CAP:
            reasons.append("local_fog_volume_count={} exceeds hard cap {}".format(
                lfv, LOCAL_FOG_VOLUME_CAP))

    # visibility minimum for PLAYABLE (non-low-visibility) maps.
    if not low_vis:
        vis = _num(fog.get("visibility_min_cm"))
        if vis is None:
            vis_reasons.append("fog.visibility_min_cm missing or non-numeric")
        elif vis < VISIBILITY_FLOOR_CM:
            vis_reasons.append(
                "playable fog visibility_min_cm={} below floor {}".format(
                    vis, VISIBILITY_FLOOR_CM))

    return reasons, vis_reasons


def validate_pack(pack, strict, profiles_root=None, bindings_path=None):
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    try:
        bindings = P.load_bindings(world_pack_id, profiles_root, bindings_path)
    except P.ProfileError as exc:
        rep.check("binding_overlay_loads", False, str(exc),
                  code=FailureCode.FOG_PROFILE_FAILURE)
        rep.set_meta(build_meta(command="validate-fog", pack=world_pack_id,
                                strict=strict, status=None, record_count=len(maps)))
        return rep

    if not maps:
        rep.check("pack_has_maps", False, "world pack enumerated zero maps",
                  code=FailureCode.FOG_PROFILE_FAILURE)

    for m in maps:
        slice_id = m.slice_id
        tag = "fog::{}".format(slice_id or "<unknown>")

        if not slice_id or not m.spec_exists:
            rep.check(tag, False,
                      "coverage shortfall: {}".format(m.get("spec_error") or "no slice_id"),
                      code=FailureCode.FOG_PROFILE_FAILURE)
            continue

        env_name, source = P.environment_for(
            world_pack_id, slice_id, profiles_root, bindings_path, bindings=bindings)
        if env_name is None:
            rep.check(tag, False, "no explicit binding and no declared default",
                      code=FailureCode.FOG_PROFILE_FAILURE)
            continue

        try:
            resolved = P.resolve_environment(env_name, profiles_root)
        except P.ProfileError as exc:
            rep.check(tag, False, "env '{}' does not resolve: {}".format(env_name, exc),
                      code=FailureCode.FOG_PROFILE_FAILURE)
            continue

        reasons, vis_reasons = _fog_reasons(resolved)
        fog_name = resolved["environment"].get("fog")

        rep.check(
            tag, not reasons,
            "fog '{}' via env '{}': {}".format(fog_name, env_name, "; ".join(reasons))
            if reasons else "fog '{}' consistent (env {})".format(fog_name, env_name),
            code=FailureCode.FOG_PROFILE_FAILURE,
        )
        rep.check(
            "visibility::{}".format(slice_id), not vis_reasons,
            "fog '{}' via env '{}': {}".format(fog_name, env_name, "; ".join(vis_reasons))
            if vis_reasons else "visibility minimum preserved (env {})".format(env_name),
            code=FailureCode.VISIBILITY_MINIMUM_VIOLATED,
        )

    rep.set_meta(build_meta(
        command="validate-fog", pack=world_pack_id, strict=strict, status=None,
        record_count=len(maps),
        input_spec_hash=hash_obj(sorted(bindings.get("bindings", {}).items())),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate fog profiles for a world pack.")
    parser.add_argument("--pack", default="desert_mvp_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--profiles-root", default=None)
    parser.add_argument("--bindings-path", default=None)
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.profiles_root, args.bindings_path)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_fog_report.json")
    rep.print_summary("validate-fog")
    _, maps = enumerate_maps(args.pack)
    print("[validate-fog] records={} (maps in pack)".format(len(maps)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
