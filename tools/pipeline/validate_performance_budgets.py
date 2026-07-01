#!/usr/bin/env python3
"""validate_performance_budgets.py — WorldForge v1.0x static frame-risk gate (Agent 6).

Enforces per-map performance BUDGET CAPS and static FRAME-RISK rules for a world
pack. Each map's bound rendering profile declares a per-axis cost (dynamic
lights, fog volumes, high-cost materials, dense foliage clusters); the caps come
from the desert frame-budget metadata resolved for the platform the map's bound
scalability profile targets. A profile whose declared cost exceeds its platform
cap is a BUDGET_FAILURE. Composite frame-risk conditions (RT + heavy fog, a
cinematic profile on a performance tier, a tier that outruns its platform) are
FRAME_RISK_EXCEEDED.

The report doubles as the static frame-risk report: meta carries the observed
worst-case light/material/foliage load and per-map risk classification.

Tagged FailureCode.BUDGET_FAILURE / FailureCode.FRAME_RISK_EXCEEDED.
Report validate_performance_budgets_report.json.
Core: validate_pack(pack, strict, profiles_root=None, bindings_path=None,
                     budget_path=None).
"""

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    raise

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta, hash_obj
from world_pack_maps import enumerate_maps, report_dir_for

import profiles as P

BCODE = FailureCode.BUDGET_FAILURE
FRCODE = FailureCode.FRAME_RISK_EXCEEDED

DEFAULT_BUDGET = REPO_ROOT / "procedural" / "definitions" / "budgets" / "desert_frame_budget.yaml"

TIER_RANK = {"low": 1, "medium": 2, "high": 3, "ultra": 4, "cinematic": 5}
PLATFORM_MAX_TIER = {"console": "high", "pc": "ultra", "high_end_pc": "cinematic"}

# rendering profile axis -> (cap key in frame_caps[platform])
AXES = (
    ("light_count_budget", "max_dynamic_lights", "dynamic lights"),
    ("fog_volume_budget", "max_fog_volumes", "fog volumes"),
    ("high_cost_material_budget", "max_high_cost_materials", "high-cost materials"),
    ("foliage_cluster_budget", "max_dense_foliage_clusters", "dense foliage clusters"),
)


def _load_budget(budget_path):
    path = Path(budget_path) if budget_path else DEFAULT_BUDGET
    if not path.is_file():
        raise FileNotFoundError("frame budget not found: {}".format(path))
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or "frame_caps" not in data:
        raise ValueError("frame budget missing 'frame_caps': {}".format(path))
    return data, path


def _resolve_env(rep, world_pack_id, m, bindings, profiles_root, bindings_path):
    slice_id = m.slice_id
    tag = "budget_binding::{}".format(slice_id or "<unknown>")
    if not slice_id or not m.spec_exists:
        rep.check(tag, False,
                  "coverage shortfall: {}".format(m.get("spec_error") or "no slice_id"),
                  code=BCODE)
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
                  code=BCODE)
        return None, None
    return env_name, resolved


def _check_budget(rep, slice_id, env_name, rendering, scalability, ray_tracing, frame_caps, rules):
    base = "budget::{}".format(slice_id)
    platform = scalability.get("target_platform")
    tier = scalability.get("tier")

    caps = frame_caps.get(platform)
    if caps is None:
        rep.check(base + "::caps_resolved", False,
                  "no frame caps for platform {!r} (env {})".format(platform, env_name),
                  code=BCODE)
        return None
    rep.check(base + "::caps_resolved", True, "caps for platform {}".format(platform))

    observed = {}
    # --- per-axis budget caps -------------------------------------------------
    for field, cap_key, label in AXES:
        used = rendering.get(field)
        cap = caps.get(cap_key)
        observed[field] = used
        ok = (isinstance(used, int) and isinstance(cap, int) and used <= cap)
        rep.check(base + "::{}".format(field), ok,
                  "{}: rendering '{}' declares {} {} > cap {} for platform {}".format(
                      label, rendering.get("name"), used, label, cap, platform),
                  code=BCODE)

    # --- composite static frame-risk rules -----------------------------------
    rt_on = str(ray_tracing.get("mode")) != "off"
    if rules.get("rt_heavy_fog_forbidden", True) and rt_on:
        rep.check(base + "::rt_heavy_fog", rendering.get("volumetric_fog") != "heavy",
                  "frame-risk: RT-on env {} with rendering volumetric_fog=heavy".format(env_name),
                  code=FRCODE)
    if rules.get("cinematic_on_performance_tier_forbidden", True):
        risky = rendering.get("rendering_mode") == "cinematic" and tier == "low"
        rep.check(base + "::cinematic_on_perf_tier", not risky,
                  "frame-risk: cinematic rendering '{}' on performance tier '{}'".format(
                      rendering.get("name"), tier), code=FRCODE)
    if rules.get("tier_over_platform_forbidden", True) and tier in TIER_RANK \
            and platform in PLATFORM_MAX_TIER:
        ceiling = PLATFORM_MAX_TIER[platform]
        rep.check(base + "::tier_over_platform", TIER_RANK[tier] <= TIER_RANK[ceiling],
                  "frame-risk: tier '{}' exceeds platform '{}' ceiling '{}'".format(
                      tier, platform, ceiling), code=FRCODE)

    return observed


def validate_pack(pack, strict, profiles_root=None, bindings_path=None, budget_path=None):
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    try:
        budget, bpath = _load_budget(budget_path)
    except (FileNotFoundError, ValueError) as exc:
        rep.check("frame_budget_loads", False, str(exc), code=BCODE)
        rep.set_meta(build_meta(command="validate-performance-budgets", pack=world_pack_id,
                                strict=strict, status=None, record_count=len(maps)))
        return rep
    frame_caps = budget.get("frame_caps", {})
    rules = budget.get("frame_risk_rules", {})
    rep.check("frame_budget_loads", True,
              "loaded {} ({} platform cap set(s))".format(bpath.name, len(frame_caps)))

    try:
        bindings = P.load_bindings(world_pack_id, profiles_root, bindings_path)
    except P.ProfileError as exc:
        rep.check("binding_overlay_loads", False, str(exc),
                  code=FailureCode.PROFILE_MISSING_BINDING)
        rep.set_meta(build_meta(command="validate-performance-budgets", pack=world_pack_id,
                                strict=strict, status=None, record_count=len(maps)))
        return rep
    rep.check("binding_overlay_loads", True,
              "{} explicit binding(s)".format(len(bindings.get("bindings", {}))))

    if not maps:
        rep.check("pack_has_maps", False, "world pack enumerated zero maps", code=BCODE)

    peak = {field: 0 for field, _, _ in AXES}
    scored = 0
    for m in maps:
        env_name, resolved = _resolve_env(
            rep, world_pack_id, m, bindings, profiles_root, bindings_path)
        if resolved is None:
            continue
        rendering = resolved["children"]["rendering"]
        scalability = resolved["children"]["scalability"]
        ray_tracing = resolved["children"]["ray_tracing"]
        observed = _check_budget(rep, m.slice_id, env_name, rendering, scalability,
                                 ray_tracing, frame_caps, rules)
        if observed:
            scored += 1
            for field in peak:
                v = observed.get(field)
                if isinstance(v, int):
                    peak[field] = max(peak[field], v)

    rep.set_meta(build_meta(
        command="validate-performance-budgets", pack=world_pack_id, strict=strict,
        status=None, record_count=len(maps),
        input_spec_hash=hash_obj(sorted(bindings.get("bindings", {}).items())),
        extra={"frame_budget": bpath.name, "maps_scored": scored,
               "peak_load": peak},
    ))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate performance budgets / static frame-risk.")
    ap.add_argument("--pack", default="desert_mvp_world")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--profiles-root", default=None)
    ap.add_argument("--bindings-path", default=None)
    ap.add_argument("--budget-path", default=None)
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.profiles_root, args.bindings_path,
                        args.budget_path)
    _, maps = enumerate_maps(args.pack)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_performance_budgets_report.json")
    rep.print_summary("validate-performance-budgets")
    print("[validate-performance-budgets] records={} (maps in pack)".format(len(maps)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
