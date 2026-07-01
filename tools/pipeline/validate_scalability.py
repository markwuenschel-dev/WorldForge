#!/usr/bin/env python3
"""validate_scalability.py — WorldForge v1.0x scalability-tier gate (Agent 6).

Proves that EVERY map binds to a scalability profile whose declared tier, target
FPS and target platform are present and internally coherent with the rendering
profile it is paired with:

  * tier is drawn from the known tier vocabulary; target_fps is a positive
    number; target_platform is a known platform;
  * the tier is consistent with the paired rendering profile's cost_class — a
    performance/low tier must NOT bind a cinematic rendering profile (each tier
    declares max_rendering_cost_class, the highest rendering cost it may carry);
  * the tier does not exceed the capability ceiling of its target platform (a
    console profile may not ask for a cinematic/ultra tier).

Tagged FailureCode.SCALABILITY_FAILURE. Report validate_scalability_report.json.
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

SCODE = FailureCode.SCALABILITY_FAILURE

TIER_RANK = {"low": 1, "medium": 2, "high": 3, "ultra": 4, "cinematic": 5}
# Highest scalability tier each target platform may legitimately drive.
PLATFORM_MAX_TIER = {"console": "high", "pc": "ultra", "high_end_pc": "cinematic"}
REQUIRED_SCAL_FIELDS = P.REQUIRED_FIELDS["scalability"]  # tier, target_fps, target_platform


def _resolve_env(rep, world_pack_id, m, bindings, profiles_root, bindings_path):
    slice_id = m.slice_id
    tag = "scal_binding::{}".format(slice_id or "<unknown>")
    if not slice_id or not m.spec_exists:
        rep.check(tag, False,
                  "coverage shortfall: {}".format(m.get("spec_error") or "no slice_id"),
                  code=SCODE)
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
                  code=SCODE)
        return None, None
    return env_name, resolved


def _check_scalability(rep, slice_id, env_name, scalability, rendering):
    sname = scalability.get("name", "<scalability>")
    base = "scalability::{}".format(slice_id)

    # 1. required fields present.
    missing = [f for f in REQUIRED_SCAL_FIELDS if f not in scalability]
    missing += ["max_rendering_cost_class"] if "max_rendering_cost_class" not in scalability else []
    rep.check(base + "::fields_present", not missing,
              "profile '{}' missing scalability fields: {}".format(sname, missing)
              if missing else "all scalability fields present", code=SCODE)
    if missing:
        return

    tier = scalability.get("tier")
    fps = scalability.get("target_fps")
    platform = scalability.get("target_platform")

    # 2. tier / fps / platform validity.
    rep.check(base + "::tier_valid", tier in TIER_RANK,
              "unknown scalability tier {!r} (allowed {})".format(tier, sorted(TIER_RANK)),
              code=SCODE)
    rep.check(base + "::fps_valid",
              isinstance(fps, (int, float)) and not isinstance(fps, bool) and fps > 0,
              "target_fps must be a positive number (got {!r})".format(fps), code=SCODE)
    rep.check(base + "::platform_valid", platform in PLATFORM_MAX_TIER,
              "unknown target_platform {!r} (allowed {})".format(
                  platform, sorted(PLATFORM_MAX_TIER)), code=SCODE)
    if tier not in TIER_RANK or platform not in PLATFORM_MAX_TIER:
        return

    # 3. tier consistent with paired rendering cost_class.
    cost = rendering.get("cost_class")
    cap = scalability.get("max_rendering_cost_class")
    ok = (isinstance(cost, int) and isinstance(cap, int) and cost <= cap)
    rep.check(base + "::tier_rendering_consistent", ok,
              "tier '{}' allows rendering cost_class<={} but bound rendering '{}' is cost_class={}".format(
                  tier, cap, rendering.get("name"), cost), code=SCODE)

    # 4. tier does not exceed platform capability ceiling.
    platform_ceiling = PLATFORM_MAX_TIER[platform]
    ok2 = TIER_RANK[tier] <= TIER_RANK[platform_ceiling]
    rep.check(base + "::tier_within_platform", ok2,
              "tier '{}' (rank {}) exceeds platform '{}' ceiling '{}' (rank {})".format(
                  tier, TIER_RANK[tier], platform, platform_ceiling,
                  TIER_RANK[platform_ceiling]), code=SCODE)


def validate_pack(pack, strict, profiles_root=None, bindings_path=None):
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    try:
        bindings = P.load_bindings(world_pack_id, profiles_root, bindings_path)
    except P.ProfileError as exc:
        rep.check("binding_overlay_loads", False, str(exc),
                  code=FailureCode.PROFILE_MISSING_BINDING)
        rep.set_meta(build_meta(command="validate-scalability", pack=world_pack_id,
                                strict=strict, status=None, record_count=len(maps)))
        return rep
    rep.check("binding_overlay_loads", True,
              "{} explicit binding(s)".format(len(bindings.get("bindings", {}))))

    if not maps:
        rep.check("pack_has_maps", False, "world pack enumerated zero maps", code=SCODE)

    tiers_seen = set()
    for m in maps:
        env_name, resolved = _resolve_env(
            rep, world_pack_id, m, bindings, profiles_root, bindings_path)
        if resolved is None:
            continue
        scalability = resolved["children"]["scalability"]
        rendering = resolved["children"]["rendering"]
        tiers_seen.add(scalability.get("tier"))
        _check_scalability(rep, m.slice_id, env_name, scalability, rendering)

    # pack must exercise more than a single tier (a real scalability spread).
    rep.check("scalability::tier_spread", len(tiers_seen) >= 2,
              "pack uses only tiers {} (expected a spread across the pack)".format(
                  sorted(t for t in tiers_seen if t)), code=SCODE)

    rep.set_meta(build_meta(
        command="validate-scalability", pack=world_pack_id, strict=strict, status=None,
        record_count=len(maps),
        input_spec_hash=hash_obj(sorted(bindings.get("bindings", {}).items())),
    ))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate scalability profiles for a world pack.")
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
    rep.write(report_dir, "validate_scalability_report.json")
    rep.print_summary("validate-scalability")
    print("[validate-scalability] records={} (maps in pack)".format(len(maps)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
