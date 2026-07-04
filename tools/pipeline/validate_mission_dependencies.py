#!/usr/bin/env python3
"""validate_mission_dependencies.py — WorldForge v1.3 mission mesh/Megascans dependency validator (Agent 4).

Proves each generated mission LOADS the v1.2 substrate rather than merely naming
it (brief §5): every mission must consume at least one real generated mesh asset,
every resolved mesh asset id must exist in the v1.2 generated mesh catalog, every
non-null Megascans dressing reference must exist in the external (Megascans/Fab)
catalog, and every declared required mesh family must be one of the six frozen
MeshForge families. A mission that points at a mesh asset that was never generated,
or a Megascans asset that is not in the external ledger, is a broken dependency —
the mission would be un-materializable in-editor. This is the lane that shows v1.2
was not "just asset plumbing": the missions actually depend on the generated assets.

Usage:
    python tools/pipeline/validate_mission_dependencies.py --pack mission_loop_world [--strict]
Writes: procedural/reports/missions/validate_mission_dependencies/validate_mission_dependencies_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC
from mission_catalog import load_mission_catalog
from mesh_catalog import load_mesh_catalog
import external_asset_contract as EAC
from mesh_contract import MESH_FAMILIES
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

CODE = FailureCode.MISSION_MESH_DEPENDENCY_FAILURE
KNOWN_FAMILIES = set(MESH_FAMILIES)


def check_mission(rep, mid, m, mesh_assets, ext_assets):
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(mid, name), ok, detail, code=CODE)

    md = m.get("mesh_dependencies")
    if not isinstance(md, dict):
        c("mesh_dependencies_present", False, "mesh_dependencies missing or not an object")
        return
    c("mesh_dependencies_present", True, "")

    # Every mission must consume >= 1 real generated mesh asset.
    resolved = md.get("resolved_mesh_assets") or []
    c("resolved_mesh_assets_nonempty", bool(resolved),
      "resolved_mesh_assets is empty — mission consumes no generated mesh")

    # Every resolved mesh asset id must exist in the v1.2 generated mesh catalog.
    for aid in resolved:
        c("resolved_mesh_exists[{}]".format(aid), aid in mesh_assets,
          "resolved mesh asset '{}' not in generated mesh catalog".format(aid))

    # A non-null Megascans dressing reference must exist in the external catalog.
    dressing = md.get("megascans_dressing")
    if dressing is not None:
        c("megascans_dressing_exists[{}]".format(dressing), dressing in ext_assets,
          "megascans_dressing '{}' not in external asset catalog".format(dressing))

    # required_families non-empty and each a known MeshForge family.
    req = md.get("required_families") or []
    c("required_families_nonempty", bool(req), "required_families is empty")
    for fam in req:
        c("required_family_known[{}]".format(fam), fam in KNOWN_FAMILIES,
          "required family '{}' is not one of {}".format(fam, sorted(KNOWN_FAMILIES)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.3 mission mesh/Megascans dependencies.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    mesh_assets = (load_mesh_catalog(REPO_ROOT) or {}).get("assets") or {}
    ext_assets = (EAC.load_external_catalog(REPO_ROOT) or {}).get("assets") or {}
    catalog = load_mission_catalog(REPO_ROOT)
    mids = sorted((catalog.get("missions") or {}).keys())
    if not mids:
        rep.error("no missions — run 'make create-mission-loops' first")
    if not mesh_assets:
        rep.error("no generated mesh catalog — run the v1.2 MeshForge intake first")

    n = 0
    for mid in mids:
        m, err = MC.load_mission(mid)
        if m is None:
            rep.check("{}::loads".format(mid), False, err, code=CODE)
            continue
        check_mission(rep, mid, m, mesh_assets, ext_assets)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-mission-dependencies", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "validate_mission_dependencies",
              "validate_mission_dependencies_report.json")
    rep.print_summary("validate-mission-dependencies")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
