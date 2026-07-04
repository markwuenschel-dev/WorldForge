#!/usr/bin/env python3
"""validate_surface_materialization.py — WorldForge v1.3.5 surface gate (Agent 2 lane).

Proves the ground + cliff surface layer is materialized for real, not named in
JSON only (brief §5 / Pillar 2). Per mission map: a dressing plan exists; both
ground_surface AND cliff_surface bind to a REAL existing asset — a Megascans
external id that exists in the external catalog, OR a declared generated fallback
that exists in the mesh catalog — the bound surface is biome-compatible with the
map's biome, and ownership is source-safe (a Megascans surface marked
generated_owned is a materialization failure).

Code: SURFACE_MATERIALIZATION_FAILURE.

Usage:
    python tools/pipeline/validate_surface_materialization.py --pack mission_loop_world [--strict]
Writes: procedural/reports/visual/validate_surface_materialization/validate_surface_materialization_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import visual_contract as VC
from mission_catalog import load_mission_catalog
import mission_contract as MC
from mesh_catalog import load_mesh_catalog
from external_asset_contract import load_external_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

SURF = FailureCode.SURFACE_MATERIALIZATION_FAILURE


def _load_plan(slice_id):
    p = REPO_ROOT / VC.DRESSING_REL / (slice_id + ".json")
    if not p.is_file():
        return None, "dressing plan not found: {}".format(p)
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, "dressing plan unparseable: {}".format(exc)


def _check_surface(rep, slice_id, label, surf, biome, ext_assets, mesh_assets):
    def c(name, ok, detail):
        return rep.check("{}::{}_{}".format(slice_id, label, name), ok, detail, code=SURF)

    if not isinstance(surf, dict) or not surf.get("asset_id"):
        c("bound", False, "no {} bound".format(label))
        return
    aid = surf.get("asset_id")
    ext_id = surf.get("external_asset_id")
    ownership = surf.get("ownership_class")

    in_external = aid in ext_assets or (ext_id in ext_assets if ext_id else False)
    in_mesh = aid in mesh_assets

    # A real asset must back the surface: external Megascans id OR generated mesh fallback.
    c("real_asset", in_external or in_mesh,
      "asset_id={} external={} mesh={}".format(aid, in_external, in_mesh))
    if not (in_external or in_mesh):
        return

    # Ownership safety: a Megascans (external) surface MUST be third_party_owned;
    # a generated fallback MUST be generated_owned.
    if in_external:
        ext_entry = ext_assets.get(ext_id or aid, {})
        c("ownership_third_party", ownership == VC.OWNERSHIP_THIRD_PARTY,
          "megascans surface ownership={} (must be {})".format(ownership, VC.OWNERSHIP_THIRD_PARTY))
        biomes = ext_entry.get("biome_compatibility") or []
        c("biome_compatible", biome in biomes, "biome={} not in {}".format(biome, biomes))
    else:
        mesh_entry = mesh_assets.get(aid, {})
        c("ownership_generated", ownership == VC.OWNERSHIP_GENERATED,
          "generated fallback ownership={} (must be {})".format(ownership, VC.OWNERSHIP_GENERATED))
        biomes = mesh_entry.get("biome_compatibility") or []
        c("biome_compatible", biome in biomes, "biome={} not in {}".format(biome, biomes))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3.5 surface materialization.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    mission_catalog = load_mission_catalog(REPO_ROOT)
    ext_assets = (load_external_catalog(REPO_ROOT).get("assets") or {})
    mesh_assets = (load_mesh_catalog(REPO_ROOT).get("assets") or {})

    mids = sorted((mission_catalog.get("missions") or {}).keys())
    if not mids:
        rep.error("no missions — run 'make create-mission-loops' first")

    n = 0
    for mid in mids:
        mission, err = MC.load_mission(mid)
        if mission is None:
            rep.check("{}::mission_loads".format(mid), False, err, code=SURF)
            continue
        slice_id = mission["source_map"]["slice_id"]
        biome = mission["biome_family"]

        plan, perr = _load_plan(slice_id)
        if plan is None:
            rep.check("{}::plan_exists".format(slice_id), False, perr, code=SURF)
            continue
        rep.check("{}::plan_exists".format(slice_id), True, "plan present")

        _check_surface(rep, slice_id, "ground_surface", plan.get("ground_surface"),
                       biome, ext_assets, mesh_assets)
        _check_surface(rep, slice_id, "cliff_surface", plan.get("cliff_surface"),
                       biome, ext_assets, mesh_assets)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-surface-materialization", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "validate_surface_materialization",
              "validate_surface_materialization_report.json")
    rep.print_summary("validate-surface-materialization")
    print("[validate-surface-materialization] {} maps checked".format(n))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
