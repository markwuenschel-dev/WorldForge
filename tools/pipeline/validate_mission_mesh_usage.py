#!/usr/bin/env python3
"""validate_mission_mesh_usage.py — WorldForge v1.3 meaningful mesh-usage validator (Agent 4).

Where validate_mission_dependencies proves the references RESOLVE, this validator
proves the references are USED MEANINGFULLY (brief §5 "use mesh families
meaningfully"). A mission is not allowed to bolt on a random mesh: every resolved
mesh asset must be biome-compatible with the mission's biome_family (the asset's
biome_compatibility must include the mission biome), its mesh_family must be one
of the six frozen MeshForge families, and the set of families the mission actually
consumes must intersect the archetype's declared required_families (i.e. a
disable_site that requires encounter_cover actually pulls in an encounter_cover /
required-family asset, not something unrelated).

Pack-wide aggregate (proves varied, non-degenerate consumption): every mesh family
that appears across the 60 missions must be a known family, and at least THREE
distinct mesh families must be consumed across the pack — a single-family pack
would betray that the mission layer is not really exercising the v1.2 mesh library.

Usage:
    python tools/pipeline/validate_mission_mesh_usage.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/validate_mission_mesh_usage/validate_mission_mesh_usage_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
from mission_catalog import load_mission_catalog
from mesh_catalog import load_mesh_catalog
from mesh_contract import MESH_FAMILIES
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

CODE = FailureCode.MISSION_MESH_DEPENDENCY_FAILURE
KNOWN_FAMILIES = set(MESH_FAMILIES)
# Minimum distinct mesh families the pack must consume to prove varied usage.
MIN_DISTINCT_FAMILIES_PACKWIDE = 3


def check_mission(rep, mid, m, mesh_assets, pack_families):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=CODE)

    biome = m.get("biome_family")
    md = m.get("mesh_dependencies") or {}
    resolved = md.get("resolved_mesh_assets") or []
    required = set(md.get("required_families") or [])

    c("has_resolved_asset", bool(resolved), "no resolved mesh assets to evaluate")

    used_families = set()
    for aid in resolved:
        entry = mesh_assets.get(aid)
        if entry is None:
            # Existence is the dependency lane's job; here we can't judge usage.
            c("asset_resolvable[{}]".format(aid), False,
              "resolved asset '{}' absent from mesh catalog".format(aid))
            continue
        fam = entry.get("mesh_family")
        used_families.add(fam)
        pack_families.add(fam)
        c("asset_family_known[{}]".format(aid), fam in KNOWN_FAMILIES,
          "mesh_family '{}' not a known family".format(fam))
        compat = entry.get("biome_compatibility") or []
        c("asset_biome_compatible[{}]".format(aid), biome in compat,
          "asset '{}' (family {}) biome_compatibility {} excludes mission biome '{}'".format(
              aid, fam, compat, biome))

    # The families actually consumed must be a sensible fit for the archetype:
    # they intersect the declared required_families (or, if the archetype declared
    # none, any known-family biome-compatible asset is a valid fallback).
    if required:
        c("families_match_archetype", bool(used_families & required),
          "consumed families {} do not intersect required_families {}".format(
              sorted(used_families), sorted(required)))
    else:
        c("families_match_archetype", used_families.issubset(KNOWN_FAMILIES),
          "no required_families declared; consumed {} must all be known".format(
              sorted(used_families)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 meaningful mission mesh usage.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    mesh_assets = (load_mesh_catalog(REPO_ROOT) or {}).get("assets") or {}
    catalog = load_mission_catalog(REPO_ROOT)
    mids = sorted((catalog.get("missions") or {}).keys())
    if not mids:
        rep.error("no missions — run 'make create-mission-loops' first")
    if not mesh_assets:
        rep.error("no generated mesh catalog — run the v1.2 MeshForge intake first")

    pack_families = set()
    n = 0
    for mid in mids:
        m, err = MC.load_mission(mid)
        if m is None:
            rep.check("{}::loads".format(mid), False, err, code=CODE)
            continue
        check_mission(rep, mid, m, mesh_assets, pack_families)
        n += 1

    # Pack-wide aggregate: known families only, and varied consumption.
    unknown = sorted(pack_families - KNOWN_FAMILIES)
    rep.check("pack::all_families_known", not unknown,
              "unknown mesh families consumed pack-wide: {}".format(unknown), code=CODE)
    rep.check("pack::varied_family_usage",
              len(pack_families & KNOWN_FAMILIES) >= MIN_DISTINCT_FAMILIES_PACKWIDE,
              "only {} distinct mesh families consumed pack-wide ({}); need >= {}".format(
                  len(pack_families & KNOWN_FAMILIES), sorted(pack_families),
                  MIN_DISTINCT_FAMILIES_PACKWIDE),
              code=CODE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-mission-mesh-usage", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n,
                            extra={"distinct_mesh_families_packwide": sorted(pack_families)}))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_mission_mesh_usage",
              "validate_mission_mesh_usage_report.json")
    rep.print_summary("validate-mission-mesh-usage")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
