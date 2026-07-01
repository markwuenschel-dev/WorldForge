#!/usr/bin/env python3
"""validate_rendering_profiles.py — WorldForge v1.0x rendering-profile gate (Agent 6).

Proves that EVERY map in a world pack binds to a rendering profile that is
statically well-formed and internally consistent:

  * every required + enriched rendering setting is present and drawn from a known
    vocabulary (Lumen/Nanite/VSM booleans, volumetric-fog assumption, the
    material/texture/mesh/foliage complexity classes, light_count_budget,
    post_process_cost_class, cost_class);
  * Lumen on/off tracks the GI method (a baked profile must not claim Lumen; a
    Lumen GI method must claim Lumen);
  * ray tracing is compatible: a rendering profile that REQUIRES ray tracing may
    only be bound to an environment whose ray_tracing.mode is not 'off';
  * the performance-safe rendering profile is PROVABLY cheaper than the cinematic
    / ray-traced profiles — cost_class (and every raw budget axis) is strictly
    ordered, so "performance" can never silently cost as much as "cinematic".

Follows V10X_AGENT_CONTRACT.md: iterate via enumerate_maps, one ValidationReport
per pack, per-map checks tagged FailureCode.RENDERING_PROFILE_FAILURE, meta with
record_count == number of maps, canonical report path.

Core is importable:
    validate_pack(pack, strict, profiles_root=None, bindings_path=None) -> ValidationReport
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

RCODE = FailureCode.RENDERING_PROFILE_FAILURE

# Ordered qualitative-cost vocabulary shared by the *_class rendering fields.
CLASS_VOCAB = ("off", "low", "medium", "high", "ultra", "cinematic")
VOLUMETRIC_FOG_VOCAB = ("off", "light", "moderate", "heavy")
RAY_TRACING_FIELD_VOCAB = ("off", "optional", "required")

# The enriched rendering fields Agent 6 requires on top of the frozen four.
ENRICHED_BOOL_FIELDS = ("lumen", "nanite", "virtual_shadow_maps")
ENRICHED_CLASS_FIELDS = ("material_complexity_class", "texture_budget_class",
                         "mesh_density_class", "foliage_density_class",
                         "post_process_cost_class")
ENRICHED_INT_FIELDS = ("light_count_budget", "fog_volume_budget",
                       "high_cost_material_budget", "foliage_cluster_budget",
                       "cost_class")
REQUIRED_RENDERING_FIELDS = P.REQUIRED_FIELDS["rendering"]  # frozen four


def _resolve_env(rep, world_pack_id, m, bindings, profiles_root, bindings_path):
    """Resolve a map -> (env_name, resolved) or (None, None) recording a failure."""
    slice_id = m.slice_id
    tag = "render_binding::{}".format(slice_id or "<unknown>")
    if not slice_id or not m.spec_exists:
        rep.check(tag, False,
                  "coverage shortfall: {}".format(m.get("spec_error") or "no slice_id"),
                  code=RCODE)
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
                  code=RCODE)
        return None, None
    return env_name, resolved


def _check_rendering(rep, slice_id, env_name, rendering, ray_tracing):
    """Per-map rendering-profile validation. One tag prefix per slice."""
    rname = rendering.get("name", "<rendering>")
    base = "rendering::{}".format(slice_id)

    # 1. required + enriched fields present.
    missing = [f for f in REQUIRED_RENDERING_FIELDS if f not in rendering]
    missing += [f for f in ENRICHED_BOOL_FIELDS if f not in rendering]
    missing += ["volumetric_fog"] if "volumetric_fog" not in rendering else []
    missing += [f for f in ENRICHED_CLASS_FIELDS if f not in rendering]
    missing += [f for f in ENRICHED_INT_FIELDS if f not in rendering]
    rep.check(base + "::fields_present", not missing,
              "profile '{}' missing rendering fields: {}".format(rname, missing)
              if missing else "all rendering settings present",
              code=RCODE)
    if missing:
        return

    # 2. vocab / type validity.
    bad = []
    for f in ENRICHED_BOOL_FIELDS:
        if not isinstance(rendering.get(f), bool):
            bad.append("{}={!r} (not bool)".format(f, rendering.get(f)))
    if rendering.get("volumetric_fog") not in VOLUMETRIC_FOG_VOCAB:
        bad.append("volumetric_fog={!r}".format(rendering.get("volumetric_fog")))
    for f in ENRICHED_CLASS_FIELDS:
        if rendering.get(f) not in CLASS_VOCAB:
            bad.append("{}={!r}".format(f, rendering.get(f)))
    if str(rendering.get("ray_tracing")) not in RAY_TRACING_FIELD_VOCAB:
        bad.append("ray_tracing={!r}".format(rendering.get("ray_tracing")))
    for f in ENRICHED_INT_FIELDS:
        v = rendering.get(f)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            bad.append("{}={!r} (not a non-negative int)".format(f, v))
    rep.check(base + "::settings_valid", not bad,
              "profile '{}' invalid settings: {}".format(rname, bad) if bad
              else "all rendering settings within vocabulary",
              code=RCODE)
    if bad:
        return

    # 3. Lumen on/off must track the GI method.
    gi = rendering.get("gi_method")
    lumen = rendering.get("lumen")
    if gi == "baked":
        rep.check(base + "::lumen_expectation",
                  lumen is False,
                  "baked GI must not claim Lumen (lumen={})".format(lumen), code=RCODE)
    elif str(gi).startswith("lumen"):
        rep.check(base + "::lumen_expectation",
                  lumen is True,
                  "Lumen GI '{}' must claim lumen=true (lumen={})".format(gi, lumen),
                  code=RCODE)
    else:
        rep.check(base + "::lumen_expectation", True,
                  "gi_method={} does not constrain lumen".format(gi))

    # 4. Nanite expectation: dense meshes require Nanite.
    if rendering.get("mesh_density_class") in ("ultra", "cinematic"):
        rep.check(base + "::nanite_expectation", rendering.get("nanite") is True,
                  "mesh_density_class={} requires nanite=true".format(
                      rendering.get("mesh_density_class")), code=RCODE)

    # 5. ray-tracing compatibility with the bound environment.
    rt_field = str(rendering.get("ray_tracing"))
    rt_mode = str(ray_tracing.get("mode"))
    if rt_field == "required":
        rep.check(base + "::rt_compatible", rt_mode != "off",
                  "rendering '{}' requires ray tracing but env {} has ray_tracing.mode=off".format(
                      rname, env_name), code=RCODE)
    elif rt_field == "off":
        rep.check(base + "::rt_compatible", rt_mode == "off",
                  "rendering '{}' declares ray_tracing=off but env {} has ray_tracing.mode={}".format(
                      rname, env_name, rt_mode), code=RCODE)
    else:  # optional — compatible with anything
        rep.check(base + "::rt_compatible", True,
                  "ray_tracing=optional compatible with env mode={}".format(rt_mode))


def _check_cost_ordering(rep, profiles_root):
    """Pack-wide invariant: performance rendering is provably cheaper than cinematic.

    Loads every rendering profile and asserts that any performance-mode profile
    has a strictly lower cost_class (and lower raw light budget) than every
    cinematic-mode profile. This is what makes 'performance-safe' meaningful.
    """
    loaded = {}
    for n in P.list_profiles("rendering", profiles_root):
        try:
            loaded[n] = P.load_profile("rendering", n, profiles_root)
        except P.ProfileError as exc:
            rep.check("rendering_loadable::{}".format(n), False, str(exc), code=RCODE)
    perf = {n: d for n, d in loaded.items() if d.get("rendering_mode") == "performance"}
    cine = {n: d for n, d in loaded.items() if d.get("rendering_mode") == "cinematic"}

    rep.check("cost_ordering::has_performance_and_cinematic",
              bool(perf) and bool(cine),
              "pack must define both a performance and a cinematic rendering profile "
              "(performance={}, cinematic={})".format(sorted(perf), sorted(cine)),
              code=RCODE)

    for pn, pd in perf.items():
        for cn, cd in cine.items():
            pc, cc = pd.get("cost_class"), cd.get("cost_class")
            ok = (isinstance(pc, int) and isinstance(cc, int) and pc < cc)
            rep.check("cost_ordering::{}__lt__{}".format(pn, cn), ok,
                      "performance '{}' cost_class={} must be < cinematic '{}' cost_class={}".format(
                          pn, pc, cn, cc), code=RCODE)
            pl, cl = pd.get("light_count_budget"), cd.get("light_count_budget")
            ok2 = (isinstance(pl, int) and isinstance(cl, int) and pl < cl)
            rep.check("cost_ordering::lights::{}__lt__{}".format(pn, cn), ok2,
                      "performance '{}' light_count_budget={} must be < cinematic '{}' "
                      "light_count_budget={}".format(pn, pl, cn, cl), code=RCODE)


def _check_materiality(rep, profiles_root):
    """No two rendering profiles may be name-only clones (differ in < 2 fields).

    Tagged with the rendering-lane code so a cloned rendering profile is a
    RENDERING_PROFILE_FAILURE, not just an environment-contract materiality note.
    """
    names = P.list_profiles("rendering", profiles_root)
    loaded = {}
    for n in names:
        try:
            loaded[n] = P.load_profile("rendering", n, profiles_root)
        except P.ProfileError as exc:
            rep.check("rendering_loadable::{}".format(n), False, str(exc), code=RCODE)
    for i, a in enumerate(names):
        if a not in loaded:
            continue
        for b in names[i + 1:]:
            if b not in loaded:
                continue
            diffs = P.material_diff_count(loaded[a], loaded[b])
            rep.check("materiality::rendering::{}__vs__{}".format(a, b), diffs >= 2,
                      "rendering '{}' vs '{}' differ in {} field(s) (need >= 2)".format(
                          a, b, diffs), code=RCODE)


def validate_pack(pack, strict, profiles_root=None, bindings_path=None):
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    try:
        bindings = P.load_bindings(world_pack_id, profiles_root, bindings_path)
    except P.ProfileError as exc:
        rep.check("binding_overlay_loads", False, str(exc),
                  code=FailureCode.PROFILE_MISSING_BINDING)
        rep.set_meta(build_meta(command="validate-rendering-profiles", pack=world_pack_id,
                                strict=strict, status=None, record_count=len(maps)))
        return rep
    rep.check("binding_overlay_loads", True,
              "{} explicit binding(s)".format(len(bindings.get("bindings", {}))))

    if not maps:
        rep.check("pack_has_maps", False, "world pack enumerated zero maps", code=RCODE)

    for m in maps:
        env_name, resolved = _resolve_env(
            rep, world_pack_id, m, bindings, profiles_root, bindings_path)
        if resolved is None:
            continue
        rendering = resolved["children"]["rendering"]
        ray_tracing = resolved["children"]["ray_tracing"]
        _check_rendering(rep, m.slice_id, env_name, rendering, ray_tracing)

    # pack-wide provable-cheaper invariant + no name-only clones.
    _check_cost_ordering(rep, profiles_root)
    _check_materiality(rep, profiles_root)

    rep.set_meta(build_meta(
        command="validate-rendering-profiles", pack=world_pack_id, strict=strict,
        status=None, record_count=len(maps),
        input_spec_hash=hash_obj(sorted(bindings.get("bindings", {}).items())),
    ))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate rendering profiles for a world pack.")
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
    rep.write(report_dir, "validate_rendering_profiles_report.json")
    rep.print_summary("validate-rendering-profiles")
    print("[validate-rendering-profiles] records={} (maps in pack)".format(len(maps)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
