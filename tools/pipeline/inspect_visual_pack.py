#!/usr/bin/env python3
"""inspect_visual_pack.py — WorldForge v1.3.5 VisualFidelity operator utility.

Read-only. Shows what the generated visual pack (or a single map) actually IS, and
— with --diagnose — classifies every problem into the brief's VISUAL_* failure
buckets so an operator sees which visual lane is red without opening 120 rig +
dressing JSON files. Mirrors the console/JSON-report habit of the existing
inspect_mission_pack.py / inspect_mesh_catalog.py operator tools; it is NOT a
generator and NOT part of the create/validate contract. It joins:

    procedural/generated/worldforge_visual_catalog.json          — the visual ledger
    procedural/generated/visual/environment_rigs/<slice_id>.json — resolved rigs
    procedural/generated/visual/dressing/<slice_id>.json         — dressing plans
    procedural/generated/worldforge_mission_catalog.json         — the mission this map carries
    procedural/reports/missions/playtest/<mission_id>.json       — playtest evidence

Three modes (operator):
    inspect-visual-pack    default: human summary + JSON report, exit 0
    inspect-visual-map     --map <slice_id>: full per-map dossier, exit 0 (2 if unknown)
    diagnose-visual-pack   --diagnose: classify problems into VISUAL_* buckets,
                           exit 0 if clean, 1 if any problem (usable as a gate)

    PYTHONUTF8=1 python tools/pipeline/inspect_visual_pack.py --pack mission_loop_world
    PYTHONUTF8=1 python tools/pipeline/inspect_visual_pack.py --pack mission_loop_world --map Alien_CrystalField_Debris_Perf_01
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/inspect_visual_pack.py --pack mission_loop_world --diagnose --strict
"""

import argparse
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import visual_contract as VC
from visual_catalog import load_visual_catalog, catalog_content_hash
from visual_rig_common import components_by_type, is_number
from mission_catalog import load_mission_catalog
import mission_contract as MC
from mesh_catalog import load_mesh_catalog
from external_asset_contract import load_external_catalog
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env, hash_obj

CLEARANCE_MIN_CM = 200.0
NEAR_POI_MAX_CM = 4000.0


# ---------------------------------------------------------------------------
# loading helpers
# ---------------------------------------------------------------------------
def _read_json(path):
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _dist2d(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _slice_to_mission(mission_catalog):
    out = {}
    for mid, e in (mission_catalog.get("missions") or {}).items():
        sid = e.get("source_map")
        if sid:
            out[sid] = mid
    return out


def _playtest_report_path(mission_id):
    return REPO_ROOT / MC.MISSION_REPORTS_REL / "playtest" / (mission_id + ".json")


# ---------------------------------------------------------------------------
# per-map evaluation (shared by inspect + diagnose)
# ---------------------------------------------------------------------------
def _rig_path(entry, sid):
    return REPO_ROOT / (entry.get("rig_path") or "{}/{}.json".format(VC.ENV_RIGS_REL, sid))


def _dress_path(entry, sid):
    return REPO_ROOT / (entry.get("dressing_path") or "{}/{}.json".format(VC.DRESSING_REL, sid))


def _count_actuals(rig, dressing):
    """Dynamic light / decal / vfx-emitter actuals for one map (mirrors
    validate_visual_budgets.count_actuals; kept local so this tool has no hard
    dependency on that module's private helpers)."""
    rig = rig or {}
    dressing = dressing or {}
    comps = rig.get("components") or []
    light_classes = ("ADirectionalLight", "ASkyLight", "APointLight", "ASpotLight", "ARectLight")

    def _is_light(c):
        if not isinstance(c, dict):
            return False
        if c.get("ue_class") in light_classes:
            return True
        ctype = c.get("component") or ""
        return ctype in (VC.COMP_DIRECTIONAL_SUN, VC.COMP_SKY_LIGHT) or "Light" in ctype

    dynamic_light_count = sum(1 for c in comps if isinstance(c, dict) and c.get("enabled") and _is_light(c))

    vfx = 0
    for c in comps:
        if isinstance(c, dict) and c.get("component") == VC.COMP_WEATHER_VFX and c.get("enabled"):
            try:
                vfx = int((c.get("params") or {}).get("emitter_count") or 0)
            except (TypeError, ValueError):
                vfx = 0
            break

    def _is_decal(rec):
        rec = rec or {}
        return rec.get("role") == "decal" or rec.get("asset_class") == "decal" or rec.get("asset_type") == "decal"

    decal = sum(1 for d in (dressing.get("dressing_assets") or []) if _is_decal(d))
    for k in ("ground_surface", "cliff_surface"):
        if _is_decal(dressing.get(k)):
            decal += 1
    return {"dynamic_light_count": dynamic_light_count, "decal_count": decal, "vfx_emitter_count": vfx}


def evaluate_map(sid, entry, sid2mid, mesh_assets, ext_assets):
    """Return a dossier dict of what this map IS + a list of (bucket, code, detail)
    problems. A fully-materialized, readable, in-budget map yields no problems."""
    problems = []
    d = {"slice_id": sid, "biome": entry.get("biome"),
         "profile_class": entry.get("profile_class"),
         "catalog_surface_status": entry.get("surface_status"),
         "catalog_dressing_status": entry.get("dressing_status")}

    rig = _read_json(_rig_path(entry, sid))
    dressing = _read_json(_dress_path(entry, sid))
    mission_id = sid2mid.get(sid)
    mission = MC.load_mission(mission_id, REPO_ROOT)[0] if mission_id else None

    # -- rig ---------------------------------------------------------------
    if rig is None:
        problems.append(("missing-rig", FailureCode.ENVIRONMENT_RIG_FAILURE, "rig missing/unparseable"))
        d["rig_present"] = False
        return d, problems
    d["rig_present"] = True
    comps = components_by_type(rig)
    d["components_enabled"] = sorted(c for c, cc in comps.items() if cc.get("enabled"))
    resolved, rdetail = VC.rig_is_fully_resolved(rig)
    d["rig_fully_resolved"] = resolved
    if not resolved:
        problems.append(("rig-not-resolved", FailureCode.ENVIRONMENT_RIG_FAILURE, rdetail))

    # sky
    sky = comps.get(VC.COMP_SKY_ATMOSPHERE) or {}
    lum = (sky.get("params") or {}).get("sky_luminance_cd_m2")
    d["sky_materialized"] = bool(sky.get("enabled")) and is_number(lum) and lum > 0
    if not d["sky_materialized"]:
        problems.append(("sky-not-materialized", FailureCode.SKY_MATERIALIZATION_FAILURE,
                         "sky_luminance_cd_m2={}".format(lum)))

    # exposure
    exposure = rig.get("exposure_ev")
    d["exposure_ev"] = exposure
    d["exposure_ok"] = is_number(exposure) and VC.EXPOSURE_EV_MIN <= exposure <= VC.EXPOSURE_EV_MAX
    if not d["exposure_ok"]:
        problems.append(("exposure-out-of-range", FailureCode.LIGHTING_EXPOSURE_FAILURE,
                         "exposure_ev={} not in [{},{}]".format(exposure, VC.EXPOSURE_EV_MIN, VC.EXPOSURE_EV_MAX)))

    # -- surfaces / dressing ----------------------------------------------
    if dressing is None:
        problems.append(("missing-dressing", FailureCode.WORLD_DRESSING_FAILURE, "dressing plan missing"))
        d["dressing_present"] = False
    else:
        d["dressing_present"] = True
        ground = (dressing.get("ground_surface") or {}).get("asset_id")
        cliff = (dressing.get("cliff_surface") or {}).get("asset_id")
        d["surfaces_bound"] = bool(ground) and bool(cliff)
        if not d["surfaces_bound"]:
            problems.append(("surface-not-real", FailureCode.SURFACE_MATERIALIZATION_FAILURE,
                             "ground={} cliff={}".format(ground, cliff)))
        d["dressing_asset_count"] = len(dressing.get("dressing_assets") or [])
        if d["dressing_asset_count"] == 0:
            problems.append(("missing-dressing", FailureCode.WORLD_DRESSING_FAILURE, "no dressing assets"))

        # package closure (light): every referenced asset exists + megascans not rewritten
        for label, ref in _iter_refs(dressing):
            aid = ref.get("asset_id")
            if _is_external_ref(ref):
                ext_id = ref.get("external_asset_id") or aid
                if ext_id not in ext_assets:
                    problems.append(("package-omits-asset", FailureCode.VISUAL_PACKAGE_FAILURE,
                                     "megascans '{}' absent from external catalog".format(ext_id)))
                elif ref.get("ownership_class") != VC.OWNERSHIP_THIRD_PARTY:
                    problems.append(("megascans-rewritten", FailureCode.VISUAL_PACKAGE_FAILURE,
                                     "megascans '{}' ownership={}".format(ext_id, ref.get("ownership_class"))))
            else:
                if aid not in mesh_assets:
                    problems.append(("package-omits-asset", FailureCode.VISUAL_PACKAGE_FAILURE,
                                     "generated mesh '{}' absent from mesh catalog".format(aid)))

    # -- budget ------------------------------------------------------------
    bucket = VC.profile_class_for_caps(entry.get("profile_class") or rig.get("profile_class"))
    caps = VC.PROFILE_BUDGET_CAPS.get(bucket, VC.PROFILE_BUDGET_CAPS["balanced"])
    actuals = _count_actuals(rig, dressing)
    d["budget_bucket"] = bucket
    d["budget_actuals"] = actuals
    over = [f for f in ("dynamic_light_count", "decal_count", "vfx_emitter_count") if actuals[f] > caps[f]]
    d["budget_within"] = not over
    for f in over:
        problems.append(("budget-exceeded", FailureCode.VISUAL_BUDGET_FAILURE,
                         "{} {}={} over cap {}".format(bucket, f, actuals[f], caps[f])))

    # -- readability: fog + dressing clearance + playtest ------------------
    if mission is not None:
        route = mission.get("required_route") or {}
        route_len = route.get("length_cm")
        start = (mission.get("start_anchor") or {}).get("world_position")
        poi = (mission.get("primary_poi") or {}).get("gameplay_anchor")
        waypoints = route.get("waypoints") or ([start, poi] if start and poi else [])
        fog = comps.get(VC.COMP_HEIGHT_FOG) or {}
        fp = fog.get("params") or {}
        vis = fp.get("visibility_min_cm")
        if fog.get("enabled") and is_number(vis) and is_number(route_len) and route_len > 0:
            sd = fp.get("start_distance_cm")
            readable = (sd if is_number(sd) else 0.0) + vis
            threshold = VC.MIN_FOG_VISIBILITY_FRACTION_OF_ROUTE * route_len
            d["fog_readable_cm"] = readable
            d["fog_threshold_cm"] = round(threshold, 1)
            if readable < threshold:
                problems.append(("fog-hides-route", FailureCode.VISUAL_READABILITY_FAILURE,
                                 "readable {:.0f}cm < {:.0f}cm".format(readable, threshold)))
        if dressing is not None and waypoints:
            pts = list(waypoints) + ([start] if start else [])
            blocking = []
            for a in (dressing.get("dressing_assets") or []):
                pos = a.get("world_position")
                if isinstance(pos, (list, tuple)) and len(pos) >= 2:
                    if min(_dist2d(pos, p) for p in pts) <= CLEARANCE_MIN_CM:
                        blocking.append(a.get("asset_id"))
            if blocking:
                problems.append(("dressing-blocks-route", FailureCode.VISUAL_READABILITY_FAILURE,
                                 "assets on route/start: {}".format(blocking)))
        pr = _read_json(_playtest_report_path(mission_id))
        d["playtest_completed"] = (pr or {}).get("completed") if pr else None
        if pr is None:
            problems.append(("playtest-missing", FailureCode.VISUAL_READABILITY_FAILURE,
                             "no playtest report for {}".format(mission_id)))
        elif pr.get("completed") is not True:
            problems.append(("playtest-not-complete", FailureCode.VISUAL_READABILITY_FAILURE,
                             "playtest completed={!r}".format(pr.get("completed"))))
    else:
        problems.append(("mission-unbound", FailureCode.VISUAL_READABILITY_FAILURE,
                         "no mission carries source_map={}".format(sid)))

    return d, problems


def _is_external_ref(ref):
    ref = ref or {}
    return bool(ref.get("external_asset_id")) or ref.get("source") in ("external", "external_catalog") \
        or ref.get("ownership_class") == VC.OWNERSHIP_THIRD_PARTY \
        or str(ref.get("asset_id") or "").startswith("megascans")


def _iter_refs(dressing):
    for key in ("ground_surface", "cliff_surface"):
        r = dressing.get(key)
        if isinstance(r, dict) and r.get("asset_id"):
            yield key, r
    for i, r in enumerate(dressing.get("dressing_assets") or []):
        if isinstance(r, dict) and r.get("asset_id"):
            yield "dressing_{}".format(i), r


# ---------------------------------------------------------------------------
# inspect-visual-pack
# ---------------------------------------------------------------------------
def _ordered(counter, taxonomy):
    out = OrderedDict()
    for key in taxonomy:
        out[key] = counter.get(key, 0)
    for key in sorted(counter):
        if key not in out:
            out[key] = counter[key]
    return out


def _summary(maps, dossiers):
    by_biome = Counter()
    by_profile = Counter()
    comp_cov = Counter()
    third_party_assets = set()
    generated_assets = set()
    surf_ok = dress_ok = read_ok = budget_ok = 0

    for sid, d in dossiers.items():
        by_biome[d.get("biome") or "(unset)"] += 1
        by_profile[d.get("profile_class") or "(unset)"] += 1
        for comp in d.get("components_enabled") or []:
            comp_cov[comp] += 1
        if d.get("surfaces_bound"):
            surf_ok += 1
        if d.get("dressing_present") and d.get("dressing_asset_count", 0) > 0:
            dress_ok += 1
        if d.get("fog_readable_cm") is None or d.get("fog_readable_cm", 0) >= d.get("fog_threshold_cm", 0):
            read_ok += 1
        if d.get("budget_within"):
            budget_ok += 1

    # third-party vs generated asset refs across all dressing plans
    for sid in maps:
        entry = maps[sid]
        dressing = _read_json(_dress_path(entry, sid))
        if not dressing:
            continue
        for _, ref in _iter_refs(dressing):
            if _is_external_ref(ref):
                third_party_assets.add(ref.get("external_asset_id") or ref.get("asset_id"))
            else:
                generated_assets.add(ref.get("asset_id"))

    return {
        "total_maps": len(dossiers),
        "by_biome": _ordered(by_biome, VC.BIOME_FAMILIES),
        "by_profile_class": OrderedDict(sorted(by_profile.items())),
        "rig_component_coverage": _ordered(comp_cov, VC.ALL_RIG_COMPONENTS),
        "surfaces_bound_maps": surf_ok,
        "dressing_materialized_maps": dress_ok,
        "readable_maps": read_ok,
        "within_budget_maps": budget_ok,
        "distinct_third_party_assets": len(third_party_assets),
        "distinct_generated_assets": len(generated_assets),
    }


def _print_counter(title, mapping, indent="    "):
    print("  %s" % title)
    if not mapping:
        print("%s(none)" % indent)
        return
    for key, n in mapping.items():
        print("%s%-28s %d" % (indent, key, n))


def cmd_inspect(pack, maps, dossiers, catalog, strict):
    data = _summary(maps, dossiers)
    print("=" * 72)
    print("INSPECT-VISUAL-PACK  pack=%s  (%d map(s))" % (pack, data["total_maps"]))
    print("=" * 72)
    _print_counter("Maps per biome:", data["by_biome"])
    _print_counter("Maps per profile_class:", data["by_profile_class"])
    _print_counter("Rig component coverage (maps with component enabled):",
                   data["rig_component_coverage"])
    print("  Materialization:")
    print("    surfaces bound                  %d" % data["surfaces_bound_maps"])
    print("    dressing materialized           %d" % data["dressing_materialized_maps"])
    print("    readable (fog/route ok)         %d" % data["readable_maps"])
    print("    within visual budget            %d" % data["within_budget_maps"])
    print("  Assets:")
    print("    distinct third-party (megascans)%d" % data["distinct_third_party_assets"])
    print("    distinct generated              %d" % data["distinct_generated_assets"])

    meta = build_meta(command="inspect-visual-pack", pack=pack, strict=strict,
                      status="ok", record_count=data["total_maps"],
                      input_spec_hash=catalog_content_hash(catalog),
                      output_manifest_hash=hash_obj(data), extra={"summary": data})
    _write_report("inspect_visual_pack", "inspect_visual_pack_report.json",
                  {"pack": pack, "summary": data, "meta": meta})
    return 0


def cmd_inspect_map(pack, maps, sid, sid2mid, mesh_assets, ext_assets, strict):
    entry = maps.get(sid)
    if entry is None:
        sys.stderr.write("map not found in visual catalog: %s\n" % sid)
        return 2
    dossier, problems = evaluate_map(sid, entry, sid2mid, mesh_assets, ext_assets)
    print("=" * 72)
    print("INSPECT-VISUAL-MAP  %s  (pack=%s)" % (sid, pack))
    print("=" * 72)
    for k in ("biome", "profile_class", "rig_present", "rig_fully_resolved",
              "components_enabled", "sky_materialized", "exposure_ev", "exposure_ok",
              "surfaces_bound", "dressing_asset_count", "budget_bucket", "budget_actuals",
              "budget_within", "fog_readable_cm", "fog_threshold_cm", "playtest_completed"):
        if k in dossier:
            print("  %-24s %s" % (k, dossier[k]))
    print("  %-24s %d" % ("problems", len(problems)))
    for bucket, code, detail in problems:
        print("      [%s] (%s) %s" % (bucket, code, detail))

    meta = build_meta(command="inspect-visual-map", pack=pack, strict=strict,
                      status="ok" if not problems else "warn", record_count=1,
                      failure_count=len(problems), input_spec_hash=hash_obj(dossier),
                      extra={"slice_id": sid})
    _write_report("inspect_visual_pack", "inspect_visual_%s_report.json" % sid,
                  {"pack": pack, "map": dossier,
                   "problems": [{"bucket": b, "code": c, "detail": det} for b, c, det in problems],
                   "meta": meta})
    return 0


# ---------------------------------------------------------------------------
# diagnose-visual-pack
# ---------------------------------------------------------------------------
DIAGNOSE_BUCKETS = (
    ("missing-rig", FailureCode.ENVIRONMENT_RIG_FAILURE),
    ("rig-not-resolved", FailureCode.ENVIRONMENT_RIG_FAILURE),
    ("sky-not-materialized", FailureCode.SKY_MATERIALIZATION_FAILURE),
    ("exposure-out-of-range", FailureCode.LIGHTING_EXPOSURE_FAILURE),
    ("surface-not-real", FailureCode.SURFACE_MATERIALIZATION_FAILURE),
    ("missing-dressing", FailureCode.WORLD_DRESSING_FAILURE),
    ("package-omits-asset", FailureCode.VISUAL_PACKAGE_FAILURE),
    ("megascans-rewritten", FailureCode.VISUAL_PACKAGE_FAILURE),
    ("budget-exceeded", FailureCode.VISUAL_BUDGET_FAILURE),
    ("fog-hides-route", FailureCode.VISUAL_READABILITY_FAILURE),
    ("dressing-blocks-route", FailureCode.VISUAL_READABILITY_FAILURE),
    ("playtest-missing", FailureCode.VISUAL_READABILITY_FAILURE),
    ("playtest-not-complete", FailureCode.VISUAL_READABILITY_FAILURE),
    ("mission-unbound", FailureCode.VISUAL_READABILITY_FAILURE),
)


def cmd_diagnose(pack, maps, sid2mid, mesh_assets, ext_assets, catalog, strict):
    found = {label: [] for label, _ in DIAGNOSE_BUCKETS}
    for sid in sorted(maps):
        _, problems = evaluate_map(sid, maps[sid], sid2mid, mesh_assets, ext_assets)
        for bucket, code, detail in problems:
            found.setdefault(bucket, []).append((sid, detail))

    total = sum(len(v) for v in found.values())
    print("=" * 72)
    print("DIAGNOSE-VISUAL-PACK  pack=%s  (%d map(s), %d problem(s))" % (pack, len(maps), total))
    print("=" * 72)
    for label, code in DIAGNOSE_BUCKETS:
        items = found.get(label) or []
        if not items:
            print("  [%-24s] (%s)  none" % (label, code))
            continue
        print("  [%-24s] (%s)  %d" % (label, code, len(items)))
        for sid, detail in items:
            print("      %-44s %s" % (sid, detail))
    if total == 0:
        print("\n  No problems found. GREEN.")

    buckets_report = {
        label: {"code": code, "count": len(found.get(label) or []),
                "maps": [sid for sid, _ in (found.get(label) or [])],
                "details": ["%s: %s" % (sid, det) for sid, det in (found.get(label) or [])]}
        for label, code in DIAGNOSE_BUCKETS
    }
    meta = build_meta(command="diagnose-visual-pack", pack=pack, strict=strict,
                      status="ok" if total == 0 else "fail", failure_count=total,
                      record_count=len(maps), input_spec_hash=catalog_content_hash(catalog),
                      extra={"total_problems": total, "buckets": buckets_report})
    _write_report("diagnose_visual_pack", "diagnose_visual_pack_report.json",
                  {"pack": pack, "total_problems": total, "buckets": buckets_report, "meta": meta})
    return 0 if total == 0 else 1


# ---------------------------------------------------------------------------
# report writer
# ---------------------------------------------------------------------------
def _write_report(command_dir, filename, report):
    out_dir = REPO_ROOT / VC.VISUAL_REPORTS_REL / command_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    with path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    try:
        shown = path.relative_to(Path.cwd())
    except ValueError:
        shown = path
    print("\n[report] -> %s" % shown)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Inspect / diagnose the WorldForge generated visual pack.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--map", default=None, help="Inspect a single map by slice_id")
    ap.add_argument("--diagnose", action="store_true",
                    help="Classify visual problems into VisualFidelity buckets")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    catalog = load_visual_catalog(REPO_ROOT)
    maps = catalog.get("maps") or {}
    sid2mid = _slice_to_mission(load_mission_catalog(REPO_ROOT))
    mesh_assets = (load_mesh_catalog(REPO_ROOT).get("assets") or {})
    ext_assets = (load_external_catalog(REPO_ROOT).get("assets") or {})

    if args.map:
        return cmd_inspect_map(args.pack, maps, args.map, sid2mid, mesh_assets, ext_assets, strict)
    if args.diagnose:
        return cmd_diagnose(args.pack, maps, sid2mid, mesh_assets, ext_assets, catalog, strict)

    dossiers = OrderedDict()
    for sid in sorted(maps):
        dossiers[sid], _ = evaluate_map(sid, maps[sid], sid2mid, mesh_assets, ext_assets)
    return cmd_inspect(args.pack, maps, dossiers, catalog, strict)


if __name__ == "__main__":
    sys.exit(main())
