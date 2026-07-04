#!/usr/bin/env python3
"""validate_mesh_collision_bounds.py — WorldForge v1.2 mesh collision/bounds lane.

Validates the physical envelope of every generated mesh asset against the v1.2
mesh contract (brief §13/§28). The sibling schema gate
(validate_mesh_contract.py) only proves the bounds block is present with the
required keys and that pivot/scale/collision enums are individually valid; this
lane goes deeper and proves the envelope is FAMILY-CONSISTENT:

  * bounds present with all MC.BOUNDS_REQUIRED keys, every value > 0
  * the LARGEST of x/y/z_cm lands inside the family's extent window
    MC.FAMILY_BOUNDS_LIMITS_CM[family]  (MESH_BOUNDS_FAILURE)
  * collision_profile is declared, a known MC.COLLISION_PROFILES value, and
    allowed for the family per MC.FAMILY_ALLOWED_COLLISION  (MESH_COLLISION_FAILURE)
  * pivot_policy is a known MC.PIVOT_POLICIES value  (MESH_PIVOT_FAILURE)
  * scale_policy is a known MC.SCALE_POLICIES value  (MESH_SCALE_FAILURE)
  * family-specific geometry metadata (MC.FAMILY_REQUIRED_GEOMETRY):
      - traversal_marker  : route_blocking == False (visible, not route-blocking)
      - encounter_cover   : cover_height_class in MC.COVER_HEIGHT_CLASSES
      - biome_landmark    : landmark_budget declared (non-empty)
      - resource_node     : interaction_clearance_cm > 0
      - industrial_debris : blocking_collision_declared present (bool)
    A missing required geometry key fails with the family's dimension code.

It reads the DESCRIPTORS produced by create_mesh_assets.py (the materialized
record), falling back to the definition YAML if a descriptor is absent. A single
--asset scopes to one asset; default validates the whole catalog.

Usage:
    python tools/pipeline/validate_mesh_collision_bounds.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_mesh_collision_bounds.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_mesh_collision_bounds/validate_mesh_collision_bounds_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def _load_record(asset_id, repo_root=REPO_ROOT):
    """Prefer the descriptor; fall back to the raw definition YAML."""
    desc = MC.mesh_descriptor_path(asset_id, repo_root)
    if desc.is_file():
        try:
            return json.loads(desc.read_text(encoding="utf-8")), None
        except Exception as exc:
            return None, "descriptor unparseable: {}".format(exc)
    data, err = MC.load_mesh_definition(MC.mesh_definition_path(asset_id, repo_root))
    return data, err


def _num(value):
    """Return value as float if it is a real number, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _check_geometry(c, family, geometry):
    """Family-specific geometry metadata checks (brief §13/§28).

    Each check keys off the dimension code closest to the family's concern so a
    defect is bucketed to the owning lane. Missing required geometry keys fail
    with the family's dimension code.
    """
    required = MC.FAMILY_REQUIRED_GEOMETRY.get(family, ())
    for key in required:
        present = key in geometry
        if family == "biome_landmark":
            code = FailureCode.MESH_BOUNDS_FAILURE
        else:
            code = FailureCode.MESH_COLLISION_FAILURE
        c("geometry_{}_present".format(key), present,
          "geometry missing required key '{}' for family {}".format(key, family),
          code=code)
        if not present:
            continue

        if family == "traversal_marker" and key == "route_blocking":
            c("geometry_route_blocking_false", geometry.get(key) is False,
              "traversal_marker route_blocking must be False, got {}".format(
                  geometry.get(key)),
              code=FailureCode.MESH_COLLISION_FAILURE)
        elif family == "encounter_cover" and key == "cover_height_class":
            c("geometry_cover_height_class_valid",
              geometry.get(key) in MC.COVER_HEIGHT_CLASSES,
              "encounter_cover cover_height_class={} not in {}".format(
                  geometry.get(key), MC.COVER_HEIGHT_CLASSES),
              code=FailureCode.MESH_COLLISION_FAILURE)
        elif family == "biome_landmark" and key == "landmark_budget":
            c("geometry_landmark_budget_declared", bool(geometry.get(key)),
              "biome_landmark landmark_budget empty",
              code=FailureCode.MESH_BOUNDS_FAILURE)
        elif family == "resource_node" and key == "interaction_clearance_cm":
            clearance = _num(geometry.get(key))
            c("geometry_interaction_clearance_positive",
              clearance is not None and clearance > 0,
              "resource_node interaction_clearance_cm must be > 0, got {}".format(
                  geometry.get(key)),
              code=FailureCode.MESH_COLLISION_FAILURE)
        elif family == "industrial_debris" and key == "blocking_collision_declared":
            c("geometry_blocking_collision_declared_bool",
              isinstance(geometry.get(key), bool),
              "industrial_debris blocking_collision_declared must be a bool, got {}".format(
                  geometry.get(key)),
              code=FailureCode.MESH_COLLISION_FAILURE)


def check_asset(rep, asset_id, record, strict):
    """Run all collision/bounds checks for one asset, prefixing check names."""
    def c(name, ok, detail="", code=FailureCode.MESH_BOUNDS_FAILURE):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=code)

    family = record.get("mesh_family")

    # -- bounds block: present, complete, all positive ----------------------
    bounds = record.get("bounds")
    if not isinstance(bounds, dict):
        c("bounds_present", False, "bounds absent",
          code=FailureCode.MESH_BOUNDS_FAILURE)
        return
    c("bounds_present", True, "bounds present")

    miss = [k for k in MC.BOUNDS_REQUIRED if k not in bounds]
    c("bounds_complete", not miss, "bounds missing keys: {}".format(miss),
      code=FailureCode.MESH_BOUNDS_FAILURE)

    dims = {k: _num(bounds.get(k)) for k in MC.BOUNDS_REQUIRED}
    all_positive = all(v is not None and v > 0 for v in dims.values())
    c("bounds_positive", all_positive,
      "every bound must be > 0, got {}".format(
          {k: bounds.get(k) for k in MC.BOUNDS_REQUIRED}),
      code=FailureCode.MESH_BOUNDS_FAILURE)

    # -- largest axis within the family's extent window ---------------------
    limits = MC.FAMILY_BOUNDS_LIMITS_CM.get(family)
    if all_positive and limits is not None:
        largest = max(dims.values())
        lo, hi = limits
        c("bounds_largest_axis_in_window", lo <= largest <= hi,
          "largest extent {}cm outside {} window {} for family {}".format(
              largest, family, limits, family),
          code=FailureCode.MESH_BOUNDS_FAILURE)
    elif limits is None:
        c("bounds_family_window_known", False,
          "no bounds window defined for family {}".format(family),
          code=FailureCode.MESH_BOUNDS_FAILURE)

    # -- collision profile: known and allowed for the family ----------------
    profile = record.get("collision_profile")
    c("collision_profile_known", profile in MC.COLLISION_PROFILES,
      "collision_profile={} not in {}".format(profile, MC.COLLISION_PROFILES),
      code=FailureCode.MESH_COLLISION_FAILURE)
    allowed = MC.FAMILY_ALLOWED_COLLISION.get(family, ())
    c("collision_profile_allowed_for_family", profile in allowed,
      "collision_profile={} not allowed for family {} (allowed: {})".format(
          profile, family, allowed),
      code=FailureCode.MESH_COLLISION_FAILURE)

    # -- pivot / scale policy -----------------------------------------------
    c("pivot_policy_valid", record.get("pivot_policy") in MC.PIVOT_POLICIES,
      "pivot_policy={}".format(record.get("pivot_policy")),
      code=FailureCode.MESH_PIVOT_FAILURE)
    c("scale_policy_valid", record.get("scale_policy") in MC.SCALE_POLICIES,
      "scale_policy={}".format(record.get("scale_policy")),
      code=FailureCode.MESH_SCALE_FAILURE)

    # -- family-specific geometry metadata ----------------------------------
    def cg(name, ok, detail="", code=FailureCode.MESH_COLLISION_FAILURE):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=code)

    geometry = record.get("geometry")
    geometry = geometry if isinstance(geometry, dict) else {}
    _check_geometry(cg, family, geometry)


def validate(pack, strict, asset=None):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    asset_ids = [asset] if asset else [aid for aid, _ in
                                       sorted((catalog.get("assets") or {}).items())]
    if not asset_ids:
        rep.error("no mesh assets found — run 'make create-mesh-assets' first")
        return rep, 0

    n = 0
    for aid in asset_ids:
        record, err = _load_record(aid)
        if record is None:
            rep.check("{}::record_loads".format(aid), False, err or "no record",
                      code=FailureCode.MESH_BOUNDS_FAILURE)
            continue
        check_asset(rep, aid, record, strict)
        n += 1
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.2 mesh collision + bounds.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--asset", default=None, help="Validate a single asset id")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict, asset=args.asset)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mesh-collision-bounds", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_mesh_collision_bounds"
    rep.write(report_dir, "validate_mesh_collision_bounds_report.json")
    rep.print_summary("validate-mesh-collision-bounds")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
