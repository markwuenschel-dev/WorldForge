#!/usr/bin/env python3
"""validate_mission_biome_compatibility.py — WorldForge v1.3 biome-compatibility validator (Agent 2).

Proves each mission's biome identity is coherent end to end (brief §4): the mission
declares a biome in the frozen BIOME_FAMILIES set, that biome matches the biome of
the source map it is layered over (from the level-design descriptor), every resolved
mesh dependency is biome-compatible (from the generated mesh catalog), and any
Megascans dressing pulled in is biome-compatible too (from the external-asset
catalog). A mission that dresses an alpine map with a desert-only mesh — or targets a
biome its source map is not — is a MISSION_BIOME_COMPATIBILITY_FAILURE.

Usage:
    python tools/pipeline/validate_mission_biome_compatibility.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/validate_mission_biome_compatibility/validate_mission_biome_compatibility_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
from mission_catalog import load_mission_catalog
from mesh_catalog import load_mesh_catalog
from external_asset_contract import load_external_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

LEVEL_DESIGN_REL = "procedural/generated/level_design"


def load_level_design(slice_id):
    p = REPO_ROOT / LEVEL_DESIGN_REL / (str(slice_id) + ".json")
    if not p.is_file():
        return None, "level_design not found: {}".format(p)
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as exc:  # pragma: no cover
        return None, "level_design unparseable: {}".format(exc)


def source_map_biome(ld):
    """The biome the source map was generated as (level_design carries 'biome')."""
    return (ld or {}).get("biome") or (ld or {}).get("biome_family")


def check_biome(rep, mid, m, mesh_assets, ext_assets):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(mid, name), ok, detail,
                         code=FailureCode.MISSION_BIOME_COMPATIBILITY_FAILURE)

    biome = m.get("biome_family")
    c("biome_in_families", biome in MC.BIOME_FAMILIES, "biome={}".format(biome))

    source_map = m.get("source_map") or {}
    slice_id = source_map.get("slice_id")
    ld, err = load_level_design(slice_id)
    if ld is None:
        c("source_map_level_design_loads", False, err)
        return
    map_biome = source_map_biome(ld)
    c("source_map_biome_matches", map_biome == biome,
      "mission biome={} source_map biome={}".format(biome, map_biome))

    # Every resolved mesh dependency must be biome-compatible.
    md = m.get("mesh_dependencies") or {}
    for aid in md.get("resolved_mesh_assets") or []:
        asset = mesh_assets.get(aid)
        if asset is None:
            c("mesh_{}_in_catalog".format(aid), False, "resolved mesh not in catalog: {}".format(aid))
            continue
        compat = asset.get("biome_compatibility") or []
        c("mesh_{}_biome_compatible".format(aid), biome in compat,
          "mesh {} biome_compatibility={} mission biome={}".format(aid, compat, biome))

    # Megascans dressing, when present, must also be biome-compatible.
    mega = md.get("megascans_dressing")
    if mega:
        ext = ext_assets.get(mega)
        if ext is None:
            c("megascans_in_catalog", False, "megascans dressing not in external catalog: {}".format(mega))
        else:
            compat = ext.get("biome_compatibility") or []
            c("megascans_biome_compatible", biome in compat,
              "megascans {} biome_compatibility={} mission biome={}".format(mega, compat, biome))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 mission biome compatibility.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_mission_catalog(REPO_ROOT)
    mesh_assets = (load_mesh_catalog(REPO_ROOT) or {}).get("assets") or {}
    ext_assets = (load_external_catalog(REPO_ROOT) or {}).get("assets") or {}
    mids = sorted((catalog.get("missions") or {}).keys())
    if not mids:
        rep.error("no missions — run 'make create-mission-loops' first")
    n = 0
    for mid in mids:
        m, err = MC.load_mission(mid)
        if m is None:
            rep.check("{}::loads".format(mid), False, err,
                      code=FailureCode.MISSION_BIOME_COMPATIBILITY_FAILURE)
            continue
        check_biome(rep, mid, m, mesh_assets, ext_assets)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mission-biome-compatibility", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_mission_biome_compatibility",
              "validate_mission_biome_compatibility_report.json")
    rep.print_summary("validate-mission-biome-compatibility")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
