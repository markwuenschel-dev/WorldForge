#!/usr/bin/env python3
"""generate_streaming_regions.py — v2.3 Wave 2 region/tile authoring (Agent 2).

Generates the 2 bounded regions (hub_spoke + linear_chain), their 3 tiles each, and
the shared streaming budget profile, from streaming_spec + the real v2.0 slice maps.
Deterministic; every record is validated against streaming_contracts before it is
written — generation never emits a record its own contract would reject.

Deliverables (handoff §12 Agent 2):
    procedural/generated/regions/*.json
    procedural/generated/tiles/*.json
    procedural/generated/streaming/budget_profiles/*.json
    procedural/reports/streaming/authoring/region_authoring_report.json

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/generate_streaming_regions.py --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_contracts as SC
import streaming_spec as SPEC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REGIONS_DIR = REPO_ROOT / "procedural" / "generated" / "regions"
TILES_DIR = REPO_ROOT / "procedural" / "generated" / "tiles"
BUDGET_DIR = REPO_ROOT / "procedural" / "generated" / "streaming" / "budget_profiles"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "authoring"
OWNERSHIP_MANIFEST = "procedural/reports/operator/index/asset_ownership_views.json"


def generate(rep):
    for d in (REGIONS_DIR, TILES_DIR, BUDGET_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # shared budget profile
    budget = SC._example_streaming_budget_profile(budget_profile_id=SPEC.BUDGET_PROFILE_ID)
    bfails = [c for c in SC.validate_streaming_budget_profile(budget, strict=True) if not c[1]]
    rep.check("budget::valid", len(bfails) == 0,
              "budget profile invalid: {}".format([c[0] for c in bfails][:4]),
              code=F.STREAMING_BUDGET_PROFILE_INVALID)
    (BUDGET_DIR / (SPEC.BUDGET_PROFILE_ID + ".json")).write_text(
        json.dumps(budget, indent=2, sort_keys=True), encoding="utf-8")

    region_count = tile_count = 0
    for region in SPEC.REGIONS:
        rid = region["region_id"]
        specs = SPEC.tile_specs(region)
        nb = SPEC.neighbors(region)
        anchors_by_tile = {}
        for ap in SPEC.anchor_plan(region):
            anchors_by_tile.setdefault(ap["tile_id"], []).append(ap["anchor_id"])

        tile_ids = [t[0] for t in region["tiles"]]
        entry = next(t[0] for t in region["tiles"] if t[5])
        exits = [t[0] for t in region["tiles"] if t[6]]

        # tiles
        for tid in tile_ids:
            sp = specs[tid]
            tile = SC._example_tile_definition(
                tile_id=tid, region_id=rid, map_id=sp["map_id"],
                source_scenario_ids=list(sp["source_scenarios"]), biome=region["biome"],
                tile_role=sp["role"],
                tile_bounds={"origin": SPEC.tile_origin(sp["grid"]), "size": list(SPEC.TILE_SIZE)},
                neighbor_tile_ids=list(nb[tid]),
                load_policy="preload" if sp["role"] in ("hub", "entry") else "adjacent_prefetch",
                unload_policy="keep_resident" if sp["role"] in ("hub", "entry") else "unload_on_exit",
                anchor_ids=sorted(anchors_by_tile.get(tid, [])),
                budget_profile_id=SPEC.BUDGET_PROFILE_ID,
                ownership_manifest_path=OWNERSHIP_MANIFEST)
            tfails = [c for c in SC.validate_tile_definition(tile, strict=True) if not c[1]]
            rep.check("tile::{}::valid".format(tid), len(tfails) == 0,
                      "tile invalid: {}".format([c[0] for c in tfails][:4]),
                      code=F.STREAMING_TILE_CONTRACT_INVALID)
            (TILES_DIR / (tid + ".json")).write_text(
                json.dumps(tile, indent=2, sort_keys=True), encoding="utf-8")
            tile_count += 1

        # region
        rdef = SC._example_region_definition(
            region_id=rid, region_name=region["region_name"],
            source_pack_id="worldforge_vertical_slice",
            region_layout_type=region["layout"], tile_ids=tile_ids,
            entry_tile_id=entry, exit_tile_ids=exits, region_seed=region["seed"],
            biome_set=[region["biome"]], mission_archetypes=list(SPEC.MISSION_ARCHETYPES),
            streaming_profile=region["streaming_profile"],
            budget_profile_id=SPEC.BUDGET_PROFILE_ID)
        rfails = [c for c in SC.validate_region_definition(rdef, strict=True) if not c[1]]
        rep.check("region::{}::valid".format(rid), len(rfails) == 0,
                  "region invalid: {}".format([c[0] for c in rfails][:4]),
                  code=F.STREAMING_REGION_CONTRACT_INVALID)
        # graph connectivity (BFS from entry over reciprocal neighbors)
        seen, frontier = {entry}, [entry]
        while frontier:
            cur = frontier.pop()
            for n in nb[cur]:
                if n not in seen:
                    seen.add(n)
                    frontier.append(n)
        rep.check("region::{}::graph_connected".format(rid), seen == set(tile_ids),
                  "region graph must be connected (unreached: {})".format(
                      sorted(set(tile_ids) - seen)),
                  code=F.STREAMING_TILE_GRAPH_DISCONNECTED)
        (REGIONS_DIR / (rid + ".json")).write_text(
            json.dumps(rdef, indent=2, sort_keys=True), encoding="utf-8")
        region_count += 1

    rep.check("regions::count_2", region_count == SC.EXPECTED_REGION_COUNT,
              "expected {} regions (got {})".format(SC.EXPECTED_REGION_COUNT, region_count),
              code=F.STREAMING_REGION_CONTRACT_INVALID)
    rep.check("tiles::3_to_5_per_region",
              all(SC.MIN_TILES_PER_REGION <= len(r["tiles"]) <= SC.MAX_TILES_PER_REGION
                  for r in SPEC.REGIONS),
              "each region must have 3-5 tiles", code=F.STREAMING_TILE_CONTRACT_INVALID)
    return region_count + tile_count


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 region/tile authoring generator.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = generate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="generate-streaming-regions", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.streaming.region_authoring.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "region_authoring_report.json")
    rep.print_summary("generate-streaming-regions")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
