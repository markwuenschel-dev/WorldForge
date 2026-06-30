#!/usr/bin/env python3
"""validate_poi.py — WorldForge v0.7 POIForge Lite artifact validator.

Validates generated POI artifacts for a given POI name.
Pure Python — no UE imports.

v0.9: migrated onto the shared ``ValidationReport`` helper (one report shape,
one strict-mode semantics) and stable ``FailureCode``s. All POI spec/budget
guarantees stay hard FAILs; there are no UE-gated or soft checks here, so a POI
either passes or has a real blocking failure in both normal and strict mode.

Usage:
    python tools/pipeline/validate_poi.py --name POI_IndustrialYard_01
    STRICT=1 python tools/pipeline/validate_poi.py --name POI_IndustrialYard_01 --strict

Writes:
    procedural/reports/poi/<NAME>/validate_poi_report.json

Exit 0 = PASS (status ok|warn), 1 = FAIL (status fail|error).
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from poi_registry import load_poi_registry
from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate POIForge Lite artifacts.")
    ap.add_argument("--name", required=True, help="POI name, e.g. POI_IndustrialYard_01")
    ap.add_argument("--strict", action="store_true",
                    help="Treat soft warnings as blocking (also via STRICT=1).")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    poi_name = args.name
    artifact_dir = REPO_ROOT / "procedural" / "generated" / "poi" / poi_name
    report_dir = REPO_ROOT / "procedural" / "reports" / "poi" / poi_name

    rep = ValidationReport("poi_name", poi_name, strict=strict)

    desc_path = artifact_dir / "descriptor.json"
    descriptor = None

    if rep.check("poi_descriptor_exists", desc_path.is_file(),
                 str(desc_path.relative_to(REPO_ROOT)),
                 code=FailureCode.DESCRIPTOR_MISSING):
        try:
            with desc_path.open("r", encoding="utf-8") as fh:
                descriptor = json.load(fh)
            rep.check("poi_descriptor_parses", True)
        except Exception as exc:
            rep.check("poi_descriptor_parses", False, str(exc),
                      code=FailureCode.DESCRIPTOR_UNPARSEABLE)

    if descriptor is None:
        rep.error("descriptor missing or unparseable")
        rep.write(report_dir, "validate_poi_report.json")
        rep.print_summary("validate-poi")
        print("[validate-poi] FAIL — descriptor missing or unparseable")
        sys.exit(rep.exit_code)

    recipe_rel = descriptor.get("recipe_path", "")
    recipe_path = REPO_ROOT / recipe_rel.replace("/", "\\") if recipe_rel else None
    rep.check("recipe_parses",
              recipe_path is not None and recipe_path.is_file(),
              "recipe file missing: {}".format(recipe_rel),
              code=FailureCode.RECIPE_MISSING)

    registry = load_poi_registry(REPO_ROOT)
    rep.check("registry_owns_poi", poi_name in registry,
              "not found in worldforge_poi_registry.json",
              code=FailureCode.REGISTRY_MISSING_ENTRY)

    prov = descriptor.get("provenance", {})
    rep.check("provenance_exists", bool(prov), "provenance block absent from descriptor",
              code=FailureCode.PROVENANCE_MISSING)

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
    rep.check("provenance_fields_complete", prov_complete,
              "descriptor must contain poi_name, poi_type, recipe_id, seed, footprint, bounds, "
              "anchors, markers, budgets, template_id, provenance.generator_name, provenance.generated_at_utc",
              code=FailureCode.PROVENANCE_INCOMPLETE)

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
    rep.check("bounds_valid", bounds_ok,
              "bounds must have id, width_cm>0, depth_cm>0, area_cm2>0, area_cm2<=max_bounds_area_cm2 "
              "(got width={} depth={} area={} max={})".format(bounds_w, bounds_d, bounds_area, max_area),
              code=FailureCode.SPEC_INVALID)

    anchors = descriptor.get("anchors", [])
    anchors_ok = (
        isinstance(anchors, list) and
        len(anchors) > 0 and
        all(isinstance(a, dict) and a.get("id") and a.get("role") for a in anchors)
    )
    rep.check("anchors_valid", anchors_ok,
              "anchors must be non-empty list, each with id and role (got {} anchors)".format(len(anchors) if isinstance(anchors, list) else "non-list"),
              code=FailureCode.SPEC_INVALID)

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
                rep.check("markers_valid", False,
                          "marker '{}' has anchor_ref '{}' not in anchors {}".format(
                              m.get("id"), anchor_ref, sorted(anchor_ids)),
                          code=FailureCode.SPEC_INVALID)
                break
    rep.check("markers_valid", markers_ok,
              "markers must be non-empty list, each with id and role, anchor_ref must resolve",
              code=FailureCode.SPEC_INVALID)

    primary_exists = any(
        isinstance(m, dict) and m.get("id") == "primary_poi_marker"
        for m in (markers if isinstance(markers, list) else [])
    )
    rep.check("primary_marker_exists", primary_exists,
              "no marker with id='primary_poi_marker' found",
              code=FailureCode.SPEC_INVALID)

    budget_ok = (
        isinstance(budgets, dict) and
        int(budgets.get("max_static_mesh_actors", 0)) > 0 and
        int(budgets.get("max_marker_count", 0)) > 0 and
        int(budgets.get("max_bounds_area_cm2", 0)) > 0
    )
    rep.check("budget_limits_valid", budget_ok,
              "budgets must have max_static_mesh_actors, max_marker_count, max_bounds_area_cm2 all > 0",
              code=FailureCode.SPEC_INVALID)

    rep.finalize()
    rep.write(report_dir, "validate_poi_report.json")
    rep.print_summary("validate-poi")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
