#!/usr/bin/env python3
"""validate_slice_environment.py — v2.0 Agent-2 environment/materialization gate.

Proves the 12 maps behind the slice are visually + physically materializable from
existing v1.5 content (no new asset acquisition): each map's .umap exists on disk,
its mission binds a real world_pack_map UE path, and its biome resolves to one of
the slice's two biomes. Modest by design — it confirms the slice's environments
are package-safe and present, not that they are final art.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_slice_environment.py \
        --pack encounter_loop_world --strict
Reports -> procedural/reports/slice/validate_slice_environment_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "slice"
MAPS_DIR = REPO_ROOT / "Content" / "WorldForge" / "Maps"
MISSIONS_DIR = REPO_ROOT / "procedural" / "generated" / "missions"


def _slice_maps():
    scen_dir = REPO_ROOT / SX.SLICE_SCENARIOS_REL
    maps = {}
    for f in sorted(scen_dir.glob("vs_*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        maps[s["map_id"]] = s["biome"]
    return maps


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice environment gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    contract_path = REPO_ROOT / SX.SLICE_CONTRACT_REL
    if not contract_path.is_file():
        rep.check("contract_present", False, "run generate_slice_scenarios.py first",
                  code=F.SLICE_ENVIRONMENT_INVALID)
        rep.error("slice not authored")
        rep.finalize()
        rep.write(REPORT_DIR, "validate_slice_environment_report.json")
        rep.print_summary("validate-slice-environment")
        sys.exit(rep.exit_code)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    biomes = set(contract.get("biomes", []))

    maps = _slice_maps()
    rep.check("maps_present", len(maps) == SX.EXPECTED_MAPS,
              "expected {} unique slice maps, got {}".format(SX.EXPECTED_MAPS, len(maps)),
              code=F.SLICE_ENVIRONMENT_INVALID)

    for map_id, biome in sorted(maps.items()):
        p = "env::{}::".format(map_id)
        rep.check(p + "umap_on_disk", (MAPS_DIR / (map_id + ".umap")).is_file(),
                  "missing .umap", code=F.SLICE_ENVIRONMENT_INVALID)
        mpath = MISSIONS_DIR / "mission_{}".format(map_id) / "mission.json"
        if not mpath.is_file():
            rep.check(p + "mission_present", False, "mission.json missing",
                      code=F.SLICE_ENVIRONMENT_INVALID)
            continue
        m = json.loads(mpath.read_text(encoding="utf-8"))
        sm = m.get("source_map") or {}
        expected = "/Game/WorldForge/Maps/{}".format(map_id)
        rep.check(p + "world_pack_map_binds", sm.get("world_pack_map") == expected,
                  "source_map.world_pack_map != {}".format(expected),
                  code=F.SLICE_ENVIRONMENT_INVALID)
        rep.check(p + "biome_resolves", m.get("biome_family") == biome and biome in biomes,
                  "biome_family {!r} != scenario biome {!r} or not in contract".format(
                      m.get("biome_family"), biome),
                  code=F.SLICE_ENVIRONMENT_INVALID)

    n = len(maps)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-slice-environment", pack=args.pack, strict=strict,
                            status=rep.status, record_count=n, records_total=n,
                            report_type="wf.slice.environment.v1"))
    rep.write(REPORT_DIR, "validate_slice_environment_report.json")
    rep.print_summary("validate-slice-environment")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
