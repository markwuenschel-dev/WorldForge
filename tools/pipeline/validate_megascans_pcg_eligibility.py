#!/usr/bin/env python3
"""validate_megascans_pcg_eligibility.py — WorldForge v1.2 addendum Megascans PCG gate.

Validates that every THIRD-PARTY Megascans record declares an honest, complete
PCG eligibility contract (addendum §6). Megascans assets are external and licensed
and must NOT be PCG-consumed without explicit eligibility — implicit compatibility
fails in STRICT=1. A record that claims to be PCG-placeable
(pcg_allowed / pcg_conditionally_allowed) MUST carry a top-level ``pcg_rules``
block with the full placement rule set: allowed biomes / POI classes, slope and
height windows, density class, collision policy, and the safety guarantees
(avoid critical routes, avoid player start). External assets are inherently
CONDITIONAL — they require import into a project path before placement — so a
conditional record must additionally declare a non-empty ``conditions`` list.
A pcg_disallowed record must NOT smuggle in any placement rules at all: a
disallowed external asset that carries pcg_rules is an eligibility failure.

This is the eligibility gate — the sibling validate_megascans_biome_compatibility.py
enforces the biome taxonomy and validate_megascans_bindings.py enforces the
material/texture contract. All three read the EXTERNAL catalog, never the
generated mesh catalog (ownership models never merge — addendum §6/§7).

Usage:
    python tools/pipeline/validate_megascans_pcg_eligibility.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_megascans_pcg_eligibility.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_megascans_pcg_eligibility/validate_megascans_pcg_eligibility_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC
import external_asset_contract as EAC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

_CODE = FailureCode.MEGASCANS_PCG_ELIGIBILITY_FAILURE


def _pcg_rules(record):
    """Return the top-level pcg_rules dict for an external record (or None)."""
    rules = record.get("pcg_rules")
    return rules if isinstance(rules, dict) else None


def check_record(rep, asset_id, record):
    """Run all PCG-eligibility checks for one external asset, prefixed with its id."""
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=_CODE)

    eligibility = record.get("pcg_eligibility")
    c("pcg_eligibility_valid", eligibility in MC.PCG_ELIGIBILITY_VALUES,
      "pcg_eligibility must be one of {}: {}".format(
          MC.PCG_ELIGIBILITY_VALUES, eligibility))

    rules = _pcg_rules(record)

    if eligibility in (MC.PCG_ALLOWED, MC.PCG_CONDITIONAL):
        # -- pcg_rules must exist and be complete --------------------------
        c("pcg_rules_present", rules is not None,
          "top-level pcg_rules missing for {}".format(eligibility))
        if rules is None:
            return  # nothing further to validate without the rule block

        missing = [k for k in MC.PCG_METADATA_REQUIRED if k not in rules]
        c("pcg_rules_complete", not missing,
          "pcg_rules missing required keys: {}".format(missing))

        # -- allowed_biomes non-empty + subset of the record's biomes ------
        allowed_biomes = rules.get("allowed_biomes")
        biome_compat = record.get("biome_compatibility") or []
        c("allowed_biomes_non_empty",
          isinstance(allowed_biomes, list) and bool(allowed_biomes),
          "allowed_biomes must be a non-empty list: {}".format(allowed_biomes))
        if isinstance(allowed_biomes, list):
            outside = [b for b in allowed_biomes if b not in biome_compat]
            c("allowed_biomes_subset_of_compat", not outside,
              "allowed_biomes {} not in biome_compatibility {}".format(
                  outside, biome_compat))

        # -- slope limits --------------------------------------------------
        slope = rules.get("slope_limits")
        if isinstance(slope, dict) and "min_deg" in slope and "max_deg" in slope:
            c("slope_limits_sane", slope["min_deg"] <= slope["max_deg"],
              "slope_limits min>max: {}".format(slope))
        else:
            c("slope_limits_present", False,
              "slope_limits missing min_deg/max_deg: {}".format(slope))

        # -- height limits -------------------------------------------------
        height = rules.get("height_limits")
        if isinstance(height, dict) and "min_cm" in height and "max_cm" in height:
            c("height_limits_sane", height["min_cm"] <= height["max_cm"],
              "height_limits min>max: {}".format(height))
        else:
            c("height_limits_present", False,
              "height_limits missing min_cm/max_cm: {}".format(height))

        # -- safety + density guarantees -----------------------------------
        c("avoid_critical_routes_true", rules.get("avoid_critical_routes") is True,
          "avoid_critical_routes must be True: {}".format(
              rules.get("avoid_critical_routes")))
        c("avoid_player_start_present", "avoid_player_start" in rules,
          "avoid_player_start missing")
        c("density_class_non_empty", bool(rules.get("density_class")),
          "density_class must be non-empty: {}".format(rules.get("density_class")))

        # -- conditional external assets must declare their conditions -----
        if eligibility == MC.PCG_CONDITIONAL:
            conditions = rules.get("conditions")
            c("conditions_declared",
              isinstance(conditions, list) and bool(conditions),
              "pcg_conditionally_allowed requires a non-empty conditions list"
              " (external assets need import into a project path): {}".format(
                  conditions))

    elif eligibility == MC.PCG_DISALLOWED:
        # A disallowed external asset must not carry any placement rules.
        c("pcg_disallowed_has_no_rules", rules is None,
          "pcg_disallowed external asset must not declare top-level pcg_rules")


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = EAC.load_external_catalog(REPO_ROOT)
    assets = catalog.get("assets") or {}
    if not assets:
        rep.error("no external assets found — run "
                  "'python tools/pipeline/scan_external_asset_library.py --lib megascans' first")
        return rep, 0

    n = 0
    for aid, record in sorted(assets.items()):
        if not isinstance(record, dict):
            rep.check("{}::record_loads".format(aid), False,
                      "external catalog entry is not a mapping", code=_CODE)
            continue
        check_record(rep, aid, record)
        n += 1
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.2 Megascans PCG eligibility.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-megascans-pcg-eligibility", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_megascans_pcg_eligibility"
    rep.write(report_dir, "validate_megascans_pcg_eligibility_report.json")
    rep.print_summary("validate-megascans-pcg-eligibility")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
