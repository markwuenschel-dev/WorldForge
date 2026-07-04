#!/usr/bin/env python3
"""test_negative_visual.py — WorldForge v1.3.5 VisualFidelity negative-fixture gate (Agent 7).

Every known-bad visual defect under tests/fixtures/invalid_visual/ must be
REJECTED by the validator that OWNS its defect, and after exercising every case the
harness must prove it left NOTHING behind: it regenerates the rigs + dressing and
re-runs the whole visual validator suite green (self-heal).

Mechanism (mirrors test_negative_mission.py safe-injection): for each case the
harness backs up ONE real artifact's bytes (an environment rig or a dressing plan),
applies exactly ONE defect in place, runs the SPECIFIC owning validator as a
subprocess, and asserts it exits non-zero. The original bytes are restored in a
finally, so a mid-run failure can never leave the generated visual tree or the
visual catalog dirty. The Megascans source cache is READ-ONLY and is never touched.

Cases (brief §10), each mapped to its owning validator:
    sky_not_materialized            -> validate_sky_materialization
    fog_hides_route                 -> validate_visual_readability
    exposure_blowout                -> validate_lighting_exposure
    post_process_missing            -> validate_post_process_profiles
    weather_vfx_overbudget          -> validate_visual_budgets
    decal_over_budget               -> validate_visual_budgets
    dressing_blocks_route           -> validate_world_dressing
    dressing_blocks_player_start    -> validate_world_dressing
    megascans_marked_generated_owned-> validate_visual_package
    package_omits_asset             -> validate_visual_package

A case that is wrongly ACCEPTED is a failure tagged with its owning code. Exit 0
iff every case was rejected AND the self-heal suite is clean. A global finally
restores the whole generated visual tree + visual catalog to its exact starting
bytes so the run is git-clean.

Report: procedural/reports/visual/test_negative_visual/test_negative_visual_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/test_negative_visual.py --pack mission_loop_world --strict
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "tools" / "pipeline"
sys.path.insert(0, str(PIPELINE))

import visual_contract as VC  # noqa: E402
from visual_catalog import load_visual_catalog  # noqa: E402
from mission_catalog import load_mission_catalog  # noqa: E402
import mission_contract as MC  # noqa: E402
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

PY = sys.executable
FIXTURES_DIR = REPO_ROOT / VC.VISUAL_INVALID_FIXTURES_REL

# The visual generated tree + catalog whose bytes must survive the run untouched.
MASTER_PATHS = (
    REPO_ROOT / VC.VISUAL_CATALOG_REL,
    REPO_ROOT / VC.VISUAL_ASSET_CATALOG_REL,
    REPO_ROOT / VC.ENV_RIGS_REL,
    REPO_ROOT / VC.DRESSING_REL,
)

# The full visual validator suite re-run to prove self-heal (excludes generators).
SELF_HEAL_VALIDATORS = (
    "validate_visual_asset_coverage.py",
    "validate_surface_materialization.py",
    "validate_world_dressing.py",
    "validate_environment_rig.py",
    "validate_sky_materialization.py",
    "validate_fog_materialization.py",
    "validate_cloud_materialization.py",
    "validate_lighting_exposure.py",
    "validate_post_process_profiles.py",
    "validate_weather_vfx.py",
    "validate_visual_readability.py",
    "validate_visual_budgets.py",
    "validate_visual_package.py",
)


# =============================================================================
# subprocess + snapshot helpers
# =============================================================================
def _run(script, extra, strict):
    path = PIPELINE / script
    if not path.is_file():
        return None, "script missing: {}".format(script)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if strict:
        env["STRICT"] = "1"
    proc = subprocess.run([PY, str(path)] + extra, cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True)
    tail = " | ".join((proc.stdout or "").strip().splitlines()[-1:])[:200]
    return proc.returncode, tail


def _snapshot_tree(paths, dest):
    dest = Path(dest)
    mapping = []
    for p in paths:
        p = Path(p)
        rel = p.relative_to(REPO_ROOT)
        target = dest / rel
        if p.is_dir():
            shutil.copytree(str(p), str(target), dirs_exist_ok=True)
        elif p.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(p), str(target))
        mapping.append((p, target, p.is_dir()))
    return mapping


def _restore_tree(mapping):
    for live, snap, is_dir in mapping:
        if is_dir:
            live_files = {q.relative_to(live) for q in live.rglob("*") if q.is_file()} if live.is_dir() else set()
            snap_files = {q.relative_to(snap) for q in snap.rglob("*") if q.is_file()} if snap.is_dir() else set()
            for extra in live_files - snap_files:
                try:
                    (live / extra).unlink()
                except OSError:
                    pass
            for rel in snap_files:
                dst = live / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(snap / rel), str(dst))
        else:
            if snap.is_file():
                live.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(snap), str(live))


# =============================================================================
# geometry
# =============================================================================
def _offset_pos(base, dx=8000.0, dy=8000.0):
    z = base[2] if isinstance(base, (list, tuple)) and len(base) > 2 else 0.0
    return [round(base[0] + dx, 2), round(base[1] + dy, 2), round(z, 2)]


# =============================================================================
# defect mutations — each: mutate(obj, ctx) -> mutated obj (in place ok)
# ctx = {"mission": <mission dict or None>}
# =============================================================================
def _rig_component(rig, ctype):
    for c in rig.get("components") or []:
        if isinstance(c, dict) and c.get("component") == ctype:
            return c
    return None


def _mut_strip_sky_params(rig, ctx):
    sky = _rig_component(rig, VC.COMP_SKY_ATMOSPHERE)
    sky["params"] = {}  # a name-only sky: no luminance / colors
    return rig


def _mut_fog_tiny_visibility(rig, ctx):
    fog = _rig_component(rig, VC.COMP_HEIGHT_FOG)
    fog["enabled"] = True
    fog["params"]["volumetric"] = True
    fog["params"]["start_distance_cm"] = 0
    fog["params"]["visibility_min_cm"] = 100  # pea-soup fog hides the whole route
    return rig


def _mut_exposure_blowout(rig, ctx):
    rig["exposure_ev"] = 9.0  # far outside the readable EV window -> blown out
    pp = _rig_component(rig, VC.COMP_POST_PROCESS)
    if pp:
        pp["params"]["exposure_ev"] = 9.0
    return rig


def _mut_remove_post_process(rig, ctx):
    rig["components"] = [c for c in rig.get("components") or []
                         if c.get("component") != VC.COMP_POST_PROCESS]
    return rig


def _mut_weather_overbudget(rig, ctx):
    wx = _rig_component(rig, VC.COMP_WEATHER_VFX)
    wx["enabled"] = True
    wx["params"]["weather_kind"] = "storm"
    wx["params"]["emitter_count"] = 99  # performance cap is 2
    return rig


def _mut_decal_overbudget(dressing, ctx):
    poi = ((ctx.get("mission") or {}).get("primary_poi") or {}).get("gameplay_anchor") or [0, 0, 0]
    decals = []
    for i in range(12):  # performance decal cap is 8
        decals.append({
            "asset_id": "mesh_debris_decal_{}".format(i),
            "ownership_class": VC.OWNERSHIP_GENERATED,
            "source": "mesh_catalog",
            "world_position": _offset_pos(poi, 9000.0 + i * 300.0, 9000.0 + i * 300.0),
            "role": "decal",
            "near_node": "primary_poi",
        })
    dressing.setdefault("dressing_assets", []).extend(decals)
    return dressing


def _mut_dressing_on_waypoint(dressing, ctx):
    mission = ctx.get("mission") or {}
    wps = (mission.get("required_route") or {}).get("waypoints") or []
    target = wps[-1] if wps else (mission.get("primary_poi") or {}).get("gameplay_anchor")
    assets = dressing.get("dressing_assets") or []
    if assets:
        assets[0]["world_position"] = [target[0], target[1], target[2] if len(target) > 2 else 0.0]
    return dressing


def _mut_dressing_on_start(dressing, ctx):
    start = ((ctx.get("mission") or {}).get("start_anchor") or {}).get("world_position")
    assets = dressing.get("dressing_assets") or []
    if assets:
        assets[0]["world_position"] = [start[0], start[1], start[2] if len(start) > 2 else 0.0]
    return dressing


def _mut_flip_megascans_generated(dressing, ctx):
    """Flip a Megascans (third-party) reference to generated_owned."""
    for key in ("ground_surface", "cliff_surface"):
        r = dressing.get(key)
        if isinstance(r, dict) and (r.get("external_asset_id") or r.get("source") == "external"):
            r["ownership_class"] = VC.OWNERSHIP_GENERATED
            return dressing
    for a in dressing.get("dressing_assets") or []:
        if a.get("ownership_class") == VC.OWNERSHIP_THIRD_PARTY or a.get("source") == "external_catalog":
            a["ownership_class"] = VC.OWNERSHIP_GENERATED
            return dressing
    return dressing


def _mut_dressing_fake_asset(dressing, ctx):
    poi = ((ctx.get("mission") or {}).get("primary_poi") or {}).get("gameplay_anchor") or [0, 0, 0]
    dressing.setdefault("dressing_assets", []).append({
        "asset_id": "mesh_nonexistent_fake_asset_zzz",
        "ownership_class": VC.OWNERSHIP_GENERATED,
        "source": "mesh_catalog",
        "world_position": _offset_pos(poi, 12000.0, 12000.0),
        "role": "landmark",
        "near_node": "primary_poi",
    })
    return dressing


# case -> spec. target: "rig" | "dressing". needs: None | "perf" | "external".
CASES = {
    "sky_not_materialized": {
        "target": "rig", "needs": None, "mut": _mut_strip_sky_params,
        "script": "validate_sky_materialization.py", "code": FailureCode.SKY_MATERIALIZATION_FAILURE,
        "desc": "SkyAtmosphere params stripped to a bare name (no luminance/colors)."},
    "fog_hides_route": {
        "target": "rig", "needs": None, "mut": _mut_fog_tiny_visibility,
        "script": "validate_visual_readability.py", "code": FailureCode.VISUAL_READABILITY_FAILURE,
        "desc": "Volumetric fog visibility set to 100cm; hides the entire mission route."},
    "exposure_blowout": {
        "target": "rig", "needs": None, "mut": _mut_exposure_blowout,
        "script": "validate_lighting_exposure.py", "code": FailureCode.LIGHTING_EXPOSURE_FAILURE,
        "desc": "exposure_ev=9 (outside the readable EV window; blown-out frame)."},
    "post_process_missing": {
        "target": "rig", "needs": None, "mut": _mut_remove_post_process,
        "script": "validate_post_process_profiles.py", "code": FailureCode.POST_PROCESS_PROFILE_FAILURE,
        "desc": "PostProcessVolume component removed from the rig."},
    "weather_vfx_overbudget": {
        "target": "rig", "needs": "perf", "mut": _mut_weather_overbudget,
        "script": "validate_visual_budgets.py", "code": FailureCode.VISUAL_BUDGET_FAILURE,
        "desc": "Performance map ships 99 weather-VFX emitters (cap is 2)."},
    "decal_over_budget": {
        "target": "dressing", "needs": "perf", "mut": _mut_decal_overbudget,
        "script": "validate_visual_budgets.py", "code": FailureCode.VISUAL_BUDGET_FAILURE,
        "desc": "Performance map ships 12 decals (cap is 8)."},
    "dressing_blocks_route": {
        "target": "dressing", "needs": None, "mut": _mut_dressing_on_waypoint,
        "script": "validate_world_dressing.py", "code": FailureCode.WORLD_DRESSING_FAILURE,
        "desc": "A dressing asset is placed on a required-route waypoint."},
    "dressing_blocks_player_start": {
        "target": "dressing", "needs": None, "mut": _mut_dressing_on_start,
        "script": "validate_world_dressing.py", "code": FailureCode.WORLD_DRESSING_FAILURE,
        "desc": "A dressing asset is placed on the player start."},
    "megascans_marked_generated_owned": {
        "target": "dressing", "needs": "external", "mut": _mut_flip_megascans_generated,
        "script": "validate_visual_package.py", "code": FailureCode.VISUAL_PACKAGE_FAILURE,
        "desc": "A Megascans reference is rewritten to generated_owned (ownership leak)."},
    "package_omits_asset": {
        "target": "dressing", "needs": None, "mut": _mut_dressing_fake_asset,
        "script": "validate_visual_package.py", "code": FailureCode.VISUAL_PACKAGE_FAILURE,
        "desc": "Dressing references a mesh asset absent from the mesh catalog."},
}


# =============================================================================
# fixtures (declarative defect descriptors)
# =============================================================================
def ensure_fixtures():
    """Materialize the declarative fixture descriptor for every case if absent.

    A fixture documents the case, the artifact it defects, the owning validator,
    and the expected failure code; the harness applies the actual mutation in
    code (robust to which slice is chosen at runtime)."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for case, spec in sorted(CASES.items()):
        fx = FIXTURES_DIR / (case + ".json")
        if fx.is_file():
            continue
        descriptor = {
            "case": case,
            "target_kind": spec["target"],
            "target_selector": spec["needs"] or "any",
            "mutation_op": spec["mut"].__name__,
            "owning_validator": spec["script"],
            "expected_code": spec["code"],
            "description": spec["desc"],
        }
        fx.write_text(json.dumps(descriptor, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# =============================================================================
# target resolution
# =============================================================================
def _resolve_targets():
    """Return (default_sid, perf_sid, external_sid, sid2mid)."""
    maps = load_visual_catalog(REPO_ROOT).get("maps") or {}
    sids = sorted(maps)
    default_sid = sids[0] if sids else None
    perf_sid = next((s for s in sids if (maps[s] or {}).get("profile_class") == "performance"), default_sid)

    external_sid = None
    for s in sids:
        dp = REPO_ROOT / VC.DRESSING_REL / (s + ".json")
        try:
            plan = json.loads(dp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        refs = [plan.get("ground_surface"), plan.get("cliff_surface")] + list(plan.get("dressing_assets") or [])
        if any(isinstance(r, dict) and (r.get("external_asset_id") or r.get("source") in ("external", "external_catalog")
               or r.get("ownership_class") == VC.OWNERSHIP_THIRD_PARTY) for r in refs):
            external_sid = s
            break

    mcat = load_mission_catalog(REPO_ROOT)
    sid2mid = {e.get("source_map"): mid for mid, e in (mcat.get("missions") or {}).items()}
    return default_sid, perf_sid, external_sid, sid2mid


def _target_slice(spec, default_sid, perf_sid, external_sid):
    if spec["needs"] == "perf":
        return perf_sid
    if spec["needs"] == "external":
        return external_sid
    return default_sid


def _artifact_path(kind, sid):
    if kind == "rig":
        return REPO_ROOT / VC.ENV_RIGS_REL / (sid + ".json")
    return REPO_ROOT / VC.DRESSING_REL / (sid + ".json")


# =============================================================================
# phases
# =============================================================================
def injection_phase(rep, pack, strict):
    default_sid, perf_sid, external_sid, sid2mid = _resolve_targets()
    if default_sid is None:
        rep.error("no visual maps — run materialize-environment-rigs + create-visual-dressing first")
        return

    for case in sorted(CASES):
        spec = CASES[case]
        code = spec["code"]

        fx = FIXTURES_DIR / (case + ".json")
        rep.check("fixture::{}".format(case), fx.is_file(),
                  "fixture descriptor present: {}".format(fx.name), code=code)

        sid = _target_slice(spec, default_sid, perf_sid, external_sid)
        if sid is None:
            rep.check("inject::{}".format(case), False,
                      "no eligible target slice (needs={})".format(spec["needs"]), code=code)
            continue

        path = _artifact_path(spec["target"], sid)
        if not path.is_file():
            rep.check("inject::{}".format(case), False,
                      "target artifact missing: {}".format(path), code=code)
            continue

        mid = sid2mid.get(sid)
        mission = MC.load_mission(mid, REPO_ROOT)[0] if mid else None
        ctx = {"mission": mission}

        backup = path.read_bytes()
        try:
            obj = spec["mut"](json.loads(backup.decode("utf-8")), ctx)
            path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            rc, tail = _run(spec["script"], ["--pack", pack] + (["--strict"] if strict else []), strict)
            rejected = rc is not None and rc != 0
            rep.check("inject::{}".format(case), rejected,
                      "{} on {} rc={} ({})".format(spec["script"], sid, rc, tail), code=code)
            print("{}  {} -> {} on {} (rc={})".format(
                "PASS" if rejected else "FAIL  ACCEPTED", case, spec["script"], sid, rc))
        finally:
            path.write_bytes(backup)


def selfheal_phase(rep, pack, strict):
    # regenerate the whole visual layer deterministically.
    rc, tail = _run("scan_megascans_visual_assets.py", ["--lib", "megascans"] + (["--strict"] if strict else []), strict)
    rep.check("selfheal::scan_megascans_visual_assets", rc == 0, "rc={} ({})".format(rc, tail),
              code=FailureCode.VISUAL_ASSET_COVERAGE_FAILURE)
    for gen in ("materialize_environment_rigs.py", "create_visual_dressing.py"):
        rc, tail = _run(gen, ["--pack", pack] + (["--strict"] if strict else []), strict)
        rep.check("selfheal::{}".format(gen.replace(".py", "")), rc == 0,
                  "{} rc={} ({})".format(gen, rc, tail), code=FailureCode.VISUAL_LIFECYCLE_FAILURE)

    for script in SELF_HEAL_VALIDATORS:
        rc, tail = _run(script, ["--pack", pack] + (["--strict"] if strict else []), strict)
        rep.check("selfheal::{}".format(script.replace(".py", "")), rc == 0,
                  "{} rc={} ({})".format(script, rc, tail), code=FailureCode.VISUAL_LIFECYCLE_FAILURE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.3.5 VisualFidelity negative-fixture gate.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    ensure_fixtures()

    master_dir = tempfile.mkdtemp(prefix="wf_visual_negative_master_")
    mapping = _snapshot_tree([p for p in MASTER_PATHS if p.exists()], master_dir)
    try:
        print("[visual-negative] INJECTION phase ({} cases)".format(len(CASES)))
        injection_phase(rep, args.pack, strict)
        print("[visual-negative] SELF-HEAL")
        selfheal_phase(rep, args.pack, strict)
    finally:
        _restore_tree(mapping)
        shutil.rmtree(master_dir, ignore_errors=True)

    rep.finalize()
    rep.set_meta(build_meta(command="visual-negative-validators", pack=args.pack,
                            strict=strict, status=rep.status, record_count=len(CASES),
                            extra={"cases": sorted(CASES),
                                   "owning_validators": {c: CASES[c]["script"] for c in sorted(CASES)}}))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "test_negative_visual",
              "test_negative_visual_report.json")
    rep.print_summary("visual-negative")
    print("[visual-negative] {} cases exercised".format(len(CASES)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
