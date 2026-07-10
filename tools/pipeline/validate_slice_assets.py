#!/usr/bin/env python3
"""validate_slice_assets.py — v2.0 Agent-2 asset ownership/provenance gate.

Proves the slice's per-map content carries explicit ownership + provenance and is
package-safe: every encounter behind a slice map declares an ownership_class and a
provenance block, and any third-party (megascans) dependency is DECLARED as a
tracked catalog reference (a list of string asset ids), never a raw redistributed
blob. This enforces the brief's "no new acquisition / no third-party
redistribution" policy without acquiring anything new.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_slice_assets.py \
        --pack encounter_loop_world --strict
Reports -> procedural/reports/slice/validate_slice_assets_report.json
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
ENCOUNTERS_DIR = REPO_ROOT / "procedural" / "generated" / "encounters"

# ownership classes that are legal to include in a generated package artifact.
PACKAGE_SAFE_OWNERSHIP = {
    "generated_owned", "catalog_backed", "houdini_generated", "third_party_external",
}


def _slice_maps():
    scen_dir = REPO_ROOT / SX.SLICE_SCENARIOS_REL
    return sorted({json.loads(f.read_text(encoding="utf-8"))["map_id"]
                   for f in scen_dir.glob("vs_*.json")})


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice asset ownership gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    if not (REPO_ROOT / SX.SLICE_CONTRACT_REL).is_file():
        rep.check("contract_present", False, "run generate_slice_scenarios.py first",
                  code=F.SLICE_ASSET_OWNERSHIP_INVALID)
        rep.error("slice not authored")
        rep.finalize()
        rep.write(REPORT_DIR, "validate_slice_assets_report.json")
        rep.print_summary("validate-slice-assets")
        sys.exit(rep.exit_code)

    maps = _slice_maps()
    rep.check("maps_present", len(maps) == SX.EXPECTED_MAPS,
              "expected {} unique slice maps, got {}".format(SX.EXPECTED_MAPS, len(maps)),
              code=F.SLICE_ASSET_OWNERSHIP_INVALID)

    for map_id in maps:
        p = "asset::{}::".format(map_id)
        epath = ENCOUNTERS_DIR / "enc_lp_{}".format(map_id) / "encounter.json"
        if not epath.is_file():
            rep.check(p + "encounter_present", False, "encounter.json missing",
                      code=F.SLICE_ASSET_OWNERSHIP_INVALID)
            continue
        e = json.loads(epath.read_text(encoding="utf-8"))
        oc = e.get("ownership_class")
        rep.check(p + "ownership_class_declared", isinstance(oc, str) and bool(oc),
                  "ownership_class missing", code=F.SLICE_ASSET_OWNERSHIP_INVALID)
        rep.check(p + "ownership_class_package_safe", oc in PACKAGE_SAFE_OWNERSHIP,
                  "ownership_class {!r} not package-safe".format(oc),
                  code=F.SLICE_ASSET_OWNERSHIP_INVALID)
        prov = e.get("provenance")
        rep.check(p + "provenance_present",
                  isinstance(prov, dict) and bool(prov.get("generator")),
                  "provenance block missing/empty", code=F.SLICE_ASSET_OWNERSHIP_INVALID)
        # third-party (megascans) deps must be DECLARED tracked ids, not raw blobs.
        meg = e.get("megascans_dependencies", [])
        rep.check(p + "megascans_declared_as_refs",
                  isinstance(meg, list) and all(isinstance(x, str) and x for x in meg),
                  "megascans_dependencies must be a list of tracked catalog ids",
                  code=F.SLICE_ASSET_OWNERSHIP_INVALID)
        mesh = e.get("mesh_dependencies", {})
        rep.check(p + "mesh_deps_structured", isinstance(mesh, dict),
                  "mesh_dependencies must be a structured object",
                  code=F.SLICE_ASSET_OWNERSHIP_INVALID)

    n = len(maps)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-slice-assets", pack=args.pack, strict=strict,
                            status=rep.status, record_count=n, records_total=n,
                            report_type="wf.slice.assets.v1"))
    rep.write(REPORT_DIR, "validate_slice_assets_report.json")
    rep.print_summary("validate-slice-assets")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
