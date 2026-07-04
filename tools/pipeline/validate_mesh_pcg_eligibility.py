#!/usr/bin/env python3
"""validate_mesh_pcg_eligibility.py — WorldForge v1.2 mesh PCG-eligibility validator.

Validates that every generated mesh asset declares an honest, complete PCG
eligibility contract (brief §10). PCG (Procedural Content Generation) is a
first-class consumer of the mesh catalog, so an asset that claims to be
PCG-placeable MUST carry the full placement rule set the PCG graph needs:
which biomes / POI classes / placement profiles it may appear in, its slope and
height windows, density class, collision policy, and the safety guarantees
(avoid critical routes, avoid player start). Conditional assets must additionally
declare the conditions under which placement is permitted, and disallowed assets
must not smuggle in PCG-driven placement rules.

This is the eligibility gate — the sibling validate_mesh_biome_compatibility.py
enforces the biome taxonomy, and validate_mesh_contract.py enforces the schema.

It reads the DESCRIPTORS produced by create_mesh_assets.py (the materialized
record), falling back to the definition YAML if a descriptor is absent.

Usage:
    python tools/pipeline/validate_mesh_pcg_eligibility.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_mesh_pcg_eligibility.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_mesh_pcg_eligibility/validate_mesh_pcg_eligibility_report.json
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

_CODE = FailureCode.MESH_PCG_ELIGIBILITY_FAILURE


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


def _pcg_rules(record):
    """Return the placement_compatibility.pcg_rules dict (or None)."""
    pc = record.get("placement_compatibility")
    if not isinstance(pc, dict):
        return None
    rules = pc.get("pcg_rules")
    return rules if isinstance(rules, dict) else None


def check_asset(rep, asset_id, record, strict):
    """Run all PCG-eligibility checks for one asset, prefixing names with the id."""
    def c(name, ok, detail="", warn_only=False):
        return rep.check("{}::{}".format(asset_id, name), ok, detail,
                         code=_CODE, warn_only=warn_only)

    eligibility = record.get("pcg_eligibility")
    c("pcg_eligibility_valid", eligibility in MC.PCG_ELIGIBILITY_VALUES,
      "pcg_eligibility={}".format(eligibility))

    rules = _pcg_rules(record)

    if eligibility in (MC.PCG_ALLOWED, MC.PCG_CONDITIONAL):
        # -- pcg_rules must exist and be complete ---------------------------
        c("pcg_rules_present", rules is not None,
          "placement_compatibility.pcg_rules missing for {}".format(eligibility))
        if rules is None:
            return  # nothing further to validate without the rule block

        missing = [k for k in MC.PCG_METADATA_REQUIRED if k not in rules]
        c("pcg_rules_complete", not missing,
          "pcg_rules missing required keys: {}".format(missing))

        # -- allowed_biomes non-empty and subset of the asset's biomes ------
        allowed_biomes = rules.get("allowed_biomes")
        biome_compat = record.get("biome_compatibility") or []
        c("allowed_biomes_non_empty",
          isinstance(allowed_biomes, list) and bool(allowed_biomes),
          "allowed_biomes={}".format(allowed_biomes))
        if isinstance(allowed_biomes, list):
            outside = [b for b in allowed_biomes if b not in biome_compat]
            c("allowed_biomes_subset_of_compat", not outside,
              "allowed_biomes {} not in biome_compatibility {}".format(
                  outside, biome_compat))

        # -- slope limits ---------------------------------------------------
        slope = rules.get("slope_limits")
        if isinstance(slope, dict) and "min_deg" in slope and "max_deg" in slope:
            c("slope_limits_sane", slope["min_deg"] <= slope["max_deg"],
              "slope_limits min>{} max".format(slope))
        else:
            c("slope_limits_present", False,
              "slope_limits missing min_deg/max_deg: {}".format(slope))

        # -- height limits --------------------------------------------------
        height = rules.get("height_limits")
        if isinstance(height, dict) and "min_cm" in height and "max_cm" in height:
            c("height_limits_sane", height["min_cm"] <= height["max_cm"],
              "height_limits min>{} max".format(height))
        else:
            c("height_limits_present", False,
              "height_limits missing min_cm/max_cm: {}".format(height))

        # -- safety + density guarantees ------------------------------------
        c("avoid_critical_routes_true", rules.get("avoid_critical_routes") is True,
          "avoid_critical_routes={}".format(rules.get("avoid_critical_routes")))
        c("avoid_player_start_present", "avoid_player_start" in rules,
          "avoid_player_start missing")
        c("density_class_non_empty", bool(rules.get("density_class")),
          "density_class={}".format(rules.get("density_class")))

        # -- conditional assets must declare their conditions ---------------
        if eligibility == MC.PCG_CONDITIONAL:
            conditions = rules.get("conditions")
            c("conditions_declared",
              isinstance(conditions, list) and bool(conditions),
              "pcg_conditionally_allowed requires non-empty conditions: {}".format(
                  conditions))

    elif eligibility == MC.PCG_DISALLOWED:
        # A disallowed asset must not claim any PCG-driven placement.
        c("pcg_disallowed_has_no_rules", rules is None,
          "pcg_disallowed asset must not declare placement_compatibility.pcg_rules")


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
                      code=_CODE)
            continue
        check_asset(rep, aid, record, strict)
        n += 1
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.2 mesh PCG eligibility.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--asset", default=None, help="Validate a single asset id")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict, asset=args.asset)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mesh-pcg-eligibility", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_mesh_pcg_eligibility"
    rep.write(report_dir, "validate_mesh_pcg_eligibility_report.json")
    rep.print_summary("validate-mesh-pcg-eligibility")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
