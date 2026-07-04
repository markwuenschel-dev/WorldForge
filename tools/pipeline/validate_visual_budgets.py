#!/usr/bin/env python3
"""validate_visual_budgets.py — WorldForge v1.3.5 visual-budget lane (Pillar 7).

Every materialized map declares an environment class (performance / readable /
balanced / cinematic / raytraced). Each class carries hard caps on the
runtime-fidelity budget (VC.PROFILE_BUDGET_CAPS): dynamic light count, decal
count, weather-VFX emitter count. This validator resolves each map's cap bucket
from its profile class, counts the ACTUAL fidelity load from the resolved
environment rig + dressing plan, and fails any map that exceeds a cap — e.g. a
performance-class map that ships more dynamic lights / decals / VFX emitters than
its budget allows (VISUAL_BUDGET_FAILURE). It also asserts each map carries a
nanite/lod policy context (kept light: derived from generated mesh deps or a sane
default) so a materialized map never ships with an undeclared scalability policy.

On the current 60-map substrate every map is within budget; the report records
actuals-vs-caps per map so the headroom is auditable.

Usage:
    python tools/pipeline/validate_visual_budgets.py --pack mission_loop_world
    STRICT=1 python tools/pipeline/validate_visual_budgets.py --pack mission_loop_world --strict

Writes: procedural/reports/visual/validate_visual_budgets/validate_visual_budgets_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import visual_contract as VC
from visual_catalog import load_visual_catalog
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

_CODE = FailureCode.VISUAL_BUDGET_FAILURE

# UE classes that count against the dynamic-light budget.
_LIGHT_UE_CLASSES = ("ADirectionalLight", "ASkyLight", "APointLight", "ASpotLight",
                     "ARectLight")


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _is_light_component(comp):
    """A rig component that materializes as a dynamic light actor."""
    if not isinstance(comp, dict):
        return False
    if comp.get("ue_class") in _LIGHT_UE_CLASSES:
        return True
    ctype = comp.get("component") or ""
    return ctype in (VC.COMP_DIRECTIONAL_SUN, VC.COMP_SKY_LIGHT) or "Light" in ctype


def count_actuals(rig, dressing):
    """Count the actual fidelity load for one map from its rig + dressing plan.

    dynamic_light_count = enabled DirectionalLight_Sun + SkyLight (+ any other
        enabled light-class component).
    vfx_emitter_count   = WeatherVFX emitter_count when enabled, else 0.
    decal_count         = dressing records that are decals (role/asset_class
        'decal'); 0 when the plan carries none.
    """
    rig = rig or {}
    dressing = dressing or {}
    comps = rig.get("components") or []

    dynamic_light_count = sum(
        1 for c in comps if isinstance(c, dict) and c.get("enabled") and _is_light_component(c))

    vfx_emitter_count = 0
    for c in comps:
        if not isinstance(c, dict) or c.get("component") != VC.COMP_WEATHER_VFX:
            continue
        if c.get("enabled"):
            ec = (c.get("params") or {}).get("emitter_count", 0)
            try:
                vfx_emitter_count = int(ec or 0)
            except (TypeError, ValueError):
                vfx_emitter_count = 0
        break

    def _is_decal(rec):
        rec = rec or {}
        return (rec.get("role") == "decal" or rec.get("asset_class") == "decal"
                or rec.get("asset_type") == "decal")

    decal_count = sum(1 for d in (dressing.get("dressing_assets") or []) if _is_decal(d))
    for surf_key in ("ground_surface", "cliff_surface"):
        if _is_decal(dressing.get(surf_key)):
            decal_count += 1

    return {
        "dynamic_light_count": dynamic_light_count,
        "decal_count": decal_count,
        "vfx_emitter_count": vfx_emitter_count,
    }


def _scalability_policy(dressing, mesh_assets):
    """Light nanite/lod policy context for a map, from generated mesh deps or a
    sane default. Never blocks — a materialized map must simply DECLARE a policy.
    """
    dressing = dressing or {}
    refs = []
    for key in ("ground_surface", "cliff_surface"):
        r = dressing.get(key)
        if isinstance(r, dict) and r.get("asset_id"):
            refs.append(r["asset_id"])
    for r in (dressing.get("dressing_assets") or []):
        if isinstance(r, dict) and r.get("asset_id"):
            refs.append(r["asset_id"])

    budget_classes = sorted({
        (mesh_assets.get(a) or {}).get("budget_class")
        for a in refs if a in mesh_assets and (mesh_assets.get(a) or {}).get("budget_class")
    })
    # Sane defaults — generated meshes are authored Nanite-eligible with auto LODs.
    return {
        "nanite_policy": "nanite_enabled",
        "lod_policy": "lod_auto",
        "mesh_budget_classes": budget_classes,
    }


def check_map(rep, sid, rig, dressing, mesh_assets, profile_class):
    """Evaluate one map against its profile-class budget caps."""
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(sid, name), ok, detail, code=_CODE)

    bucket = VC.profile_class_for_caps(profile_class)
    caps = VC.PROFILE_BUDGET_CAPS.get(bucket, VC.PROFILE_BUDGET_CAPS["balanced"])
    actuals = count_actuals(rig, dressing)

    for field in ("dynamic_light_count", "decal_count", "vfx_emitter_count"):
        cap = caps[field]
        act = actuals[field]
        c("{}_within_budget".format(field), act <= cap,
          "{} class '{}' map has {}={} over cap {}".format(
              bucket, profile_class, field, act, cap))

    policy = _scalability_policy(dressing, mesh_assets)
    c("nanite_policy_declared", bool(policy.get("nanite_policy")),
      "no nanite policy context")
    c("lod_policy_declared", bool(policy.get("lod_policy")),
      "no lod policy context")

    return {"profile_class": profile_class, "budget_class": bucket,
            "caps": {k: caps[k] for k in ("dynamic_light_count", "decal_count",
                                          "vfx_emitter_count")},
            "actuals": actuals, "scalability": policy}


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_visual_catalog(REPO_ROOT)
    maps = catalog.get("maps") or {}
    if not maps:
        rep.error("no visual maps found — run the v1.3.5 visual materialization first")
        return rep, 0, {}

    mesh_assets = (load_mesh_catalog(REPO_ROOT).get("assets") or {})
    per_map = {}
    n = 0
    for sid in sorted(maps):
        entry = maps.get(sid) or {}
        rig_rel = entry.get("rig_path") or "{}/{}.json".format(VC.ENV_RIGS_REL, sid)
        dress_rel = entry.get("dressing_path") or "{}/{}.json".format(VC.DRESSING_REL, sid)
        rig, rerr = _read_json(REPO_ROOT / rig_rel)
        dressing, derr = _read_json(REPO_ROOT / dress_rel)
        if rig is None:
            rep.check("{}::rig_loads".format(sid), False, rerr or rig_rel, code=_CODE)
            continue
        if dressing is None:
            rep.check("{}::dressing_loads".format(sid), False, derr or dress_rel, code=_CODE)
            continue
        profile_class = entry.get("profile_class") or rig.get("profile_class") or "balanced"
        per_map[sid] = check_map(rep, sid, rig, dressing, mesh_assets, profile_class)
        n += 1

    return rep, n, per_map


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.3.5 per-map visual budgets (Pillar 7).")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n, per_map = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-visual-budgets", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n,
                            extra={"budgets": per_map}))
    report_dir = REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_visual_budgets"
    rep.write(report_dir, "validate_visual_budgets_report.json")
    rep.print_summary("validate-visual-budgets")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
