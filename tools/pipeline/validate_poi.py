#!/usr/bin/env python3
"""validate_poi.py — WorldForge v0.7 POIForge Lite artifact validator.

Validates generated POI artifacts for a given POI name.
Pure Python — no UE imports.

Usage:
    python tools/pipeline/validate_poi.py --name POI_IndustrialYard_01

Writes:
    procedural/reports/poi/<NAME>/validate_poi_report.json

Exit 0 = PASS, 1 = FAIL.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from poi_registry import load_poi_registry


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate POIForge Lite artifacts.")
    ap.add_argument("--name", required=True, help="POI name, e.g. POI_IndustrialYard_01")
    args = ap.parse_args(argv)

    poi_name = args.name
    artifact_dir = REPO_ROOT / "procedural" / "generated" / "poi" / poi_name
    report_dir = REPO_ROOT / "procedural" / "reports" / "poi" / poi_name
    report_dir.mkdir(parents=True, exist_ok=True)

    result = {"poi_name": poi_name, "checks": {}, "failures": []}

    def check(name, ok, detail="", warn_only=False):
        result["checks"][name] = {"ok": bool(ok), "detail": str(detail), "warn_only": warn_only}
        if not ok:
            if warn_only:
                result.setdefault("warnings", []).append("{}: {}".format(name, detail or "warn"))
            else:
                result["failures"].append("{}: {}".format(name, detail or "failed"))
        return bool(ok)

    desc_path = artifact_dir / "descriptor.json"
    descriptor = None

    if check("poi_descriptor_exists", desc_path.is_file(), str(desc_path.relative_to(REPO_ROOT))):
        try:
            with desc_path.open("r", encoding="utf-8") as fh:
                descriptor = json.load(fh)
            check("poi_descriptor_parses", True)
        except Exception as exc:
            check("poi_descriptor_parses", False, str(exc))

    if descriptor is None:
        result["passed"] = False
        result["status"] = "error"
        _write_report(report_dir, result)
        print("[validate-poi] FAIL — descriptor missing or unparseable")
        sys.exit(1)

    recipe_rel = descriptor.get("recipe_path", "")
    recipe_path = REPO_ROOT / recipe_rel.replace("/", "\\") if recipe_rel else None
    check("recipe_parses",
          recipe_path is not None and recipe_path.is_file(),
          "recipe file missing: {}".format(recipe_rel))

    registry = load_poi_registry(REPO_ROOT)
    check("registry_owns_poi", poi_name in registry,
          "not found in worldforge_poi_registry.json")

    prov = descriptor.get("provenance", {})
    check("provenance_exists", bool(prov), "provenance block absent from descriptor")

    prov_complete = bool(
        descriptor.get("poi_name") and
        descriptor.get("poi_type") and
        descriptor.get("recipe_id") and
        descriptor.get("seed") is not None and
        descriptor.get("footprint") and
        descriptor.get("bounds") and
        descriptor.get("anchors") is not None and
        descriptor.get("markers") is not None and
        descriptor.get("budgets") and
        descriptor.get("template_id") and
        prov.get("generator_name") and
        prov.get("generated_at_utc")
    )
    check("provenance_fields_complete", prov_complete,
          "descriptor must contain poi_name, poi_type, recipe_id, seed, footprint, bounds, "
          "anchors, markers, budgets, template_id, provenance.generator_name, provenance.generated_at_utc")

    bounds = descriptor.get("bounds", {})
    budgets = descriptor.get("budgets", {})
    max_area = int(budgets.get("max_bounds_area_cm2", 0))
    bounds_w = int(bounds.get("width_cm", 0))
    bounds_d = int(bounds.get("depth_cm", 0))
    bounds_area = int(bounds.get("area_cm2", 0))
    bounds_ok = (
        bool(bounds.get("id")) and
        bounds_w > 0 and
        bounds_d > 0 and
        bounds_area > 0 and
        (max_area <= 0 or bounds_area <= max_area)
    )
    check("bounds_valid", bounds_ok,
          "bounds must have id, width_cm>0, depth_cm>0, area_cm2>0, area_cm2<=max_bounds_area_cm2 "
          "(got width={} depth={} area={} max={})".format(bounds_w, bounds_d, bounds_area, max_area))

    anchors = descriptor.get("anchors", [])
    anchors_ok = (
        isinstance(anchors, list) and
        len(anchors) > 0 and
        all(isinstance(a, dict) and a.get("id") and a.get("role") for a in anchors)
    )
    check("anchors_valid", anchors_ok,
          "anchors must be non-empty list, each with id and role (got {} anchors)".format(len(anchors) if isinstance(anchors, list) else "non-list"))

    anchor_ids = {a["id"] for a in anchors if isinstance(a, dict) and "id" in a}
    markers = descriptor.get("markers", [])
    markers_ok = isinstance(markers, list) and len(markers) > 0
    if markers_ok:
        for m in markers:
            if not (isinstance(m, dict) and m.get("id") and m.get("role")):
                markers_ok = False
                break
            anchor_ref = m.get("anchor_ref")
            if anchor_ref and anchor_ref not in anchor_ids:
                markers_ok = False
                check("markers_valid", False,
                      "marker '{}' has anchor_ref '{}' not in anchors {}".format(
                          m.get("id"), anchor_ref, sorted(anchor_ids)))
                break
    check("markers_valid", markers_ok,
          "markers must be non-empty list, each with id and role, anchor_ref must resolve")

    primary_exists = any(
        isinstance(m, dict) and m.get("id") == "primary_poi_marker"
        for m in (markers if isinstance(markers, list) else [])
    )
    check("primary_marker_exists", primary_exists,
          "no marker with id='primary_poi_marker' found")

    budget_ok = (
        isinstance(budgets, dict) and
        int(budgets.get("max_static_mesh_actors", 0)) > 0 and
        int(budgets.get("max_marker_count", 0)) > 0 and
        int(budgets.get("max_bounds_area_cm2", 0)) > 0
    )
    check("budget_limits_valid", budget_ok,
          "budgets must have max_static_mesh_actors, max_marker_count, max_bounds_area_cm2 all > 0")

    result["passed"] = len(result["failures"]) == 0
    result["status"] = "ok" if result["passed"] else "fail"
    _write_report(report_dir, result)

    verdict = "PASS" if result["passed"] else "FAIL"
    n_warn = len(result.get("warnings", []))
    print("[validate-poi] {} — {} failure(s), {} warning(s)".format(
        verdict, len(result["failures"]), n_warn))
    for f in result["failures"]:
        print("[validate-poi]   FAIL: {}".format(f))
    for w in result.get("warnings", []):
        print("[validate-poi]   WARN: {}".format(w))
    sys.exit(0 if result["passed"] else 1)


def _write_report(report_dir: Path, result: dict):
    rpt_path = report_dir / "validate_poi_report.json"
    with rpt_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("[validate-poi] report → {}".format(rpt_path))


if __name__ == "__main__":
    main()
