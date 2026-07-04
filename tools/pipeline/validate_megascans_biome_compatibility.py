#!/usr/bin/env python3
"""validate_megascans_biome_compatibility.py — WorldForge v1.2 Megascans biome gate.

Validates that every THIRD-PARTY Megascans record declares an explicit, coherent
biome compatibility contract (addendum §6). A Megascans asset must say — out loud
— which biome families it belongs in; implicit / empty compatibility is a blocking
failure. It must NOT be used in a biome without explicit compatibility. Every
declared biome must be a known family, every material binding's biome_compatibility
must be known AND intersect the record's own biome_compatibility (a binding cannot
support a biome the asset does not claim), and any PCG placement rules may only
allow biomes the asset itself is compatible with (a record cannot be PCG-placed
into a biome it is not declared compatible with).

This is the biome-taxonomy gate — validate_megascans_pcg_eligibility.py enforces
PCG rule completeness and validate_megascans_bindings.py enforces the
material/texture contract. All three read the EXTERNAL catalog, never the
generated mesh catalog (ownership models never merge — addendum §6/§7).

Usage:
    python tools/pipeline/validate_megascans_biome_compatibility.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_megascans_biome_compatibility.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_megascans_biome_compatibility/validate_megascans_biome_compatibility_report.json
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

_CODE = FailureCode.MEGASCANS_BIOME_COMPATIBILITY_FAILURE


def _pcg_rules(record):
    """Return the top-level pcg_rules dict for an external record (or None)."""
    rules = record.get("pcg_rules")
    return rules if isinstance(rules, dict) else None


def check_record(rep, asset_id, record):
    """Run all biome-compatibility checks for one external asset, prefixed with id."""
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=_CODE)

    # -- record biome_compatibility: explicit, non-empty, all known --------
    # Implicit / empty compatibility is a blocking failure (addendum §6): a
    # Megascans asset must never be used in a biome without explicit declaration.
    biomes = record.get("biome_compatibility")
    c("biome_compatibility_non_empty",
      isinstance(biomes, list) and bool(biomes),
      "biome_compatibility must be a non-empty list (implicit not allowed): {}".format(
          biomes))

    biomes = biomes if isinstance(biomes, list) else []
    unknown = [b for b in biomes if b not in MC.BIOME_FAMILIES]
    c("biome_compatibility_known", not unknown,
      "unknown biome families in biome_compatibility: {}".format(unknown))

    # -- material bindings: known biomes + intersect the record's biomes ---
    bindings = record.get("material_bindings")
    if isinstance(bindings, list):
        biome_set = set(biomes)
        for i, b in enumerate(bindings):
            mbc = (b or {}).get("biome_compatibility")
            mbc = mbc if isinstance(mbc, list) else []
            bad = [x for x in mbc if x not in MC.BIOME_FAMILIES]
            c("binding_{}_biomes_known".format(i), not bad,
              "binding {} has unknown biome families: {}".format(i, bad))
            c("binding_{}_biomes_intersect_record".format(i),
              bool(set(mbc) & biome_set),
              "binding {} biomes {} do not intersect record biomes {}".format(
                  i, mbc, biomes))

    # -- pcg_rules.allowed_biomes must be a subset of the record's biomes --
    rules = _pcg_rules(record)
    if rules is not None:
        allowed = rules.get("allowed_biomes")
        allowed = allowed if isinstance(allowed, list) else []
        outside = [b for b in allowed if b not in biomes]
        c("pcg_allowed_biomes_subset", not outside,
          "pcg_rules.allowed_biomes {} not subset of biome_compatibility {}".format(
              outside, biomes))


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
        description="Validate WorldForge v1.2 Megascans biome compatibility.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-megascans-biome-compatibility", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_megascans_biome_compatibility"
    rep.write(report_dir, "validate_megascans_biome_compatibility_report.json")
    rep.print_summary("validate-megascans-biome-compatibility")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
