#!/usr/bin/env python3
"""validate_mesh_catalog.py — WorldForge v1.2 mesh-catalog integrity (Agent 1 lane).

Enforces the catalog invariants (brief §9). The generated mesh catalog is the
source of truth; this validator proves it is consistent with what is on disk:

  * every generated mesh has exactly one catalog record
  * every catalog record points to an existing final asset (descriptor on disk)
  * every final asset has provenance + ownership recorded
  * every PCG-eligible asset has placement rules
  * every biome-compatible asset declares biome compatibility
  * no orphan generated mesh exists outside the catalog
  * no catalog record points to a missing descriptor

Usage:
    python tools/pipeline/validate_mesh_catalog.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_mesh_catalog.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_mesh_catalog/validate_mesh_catalog_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC
from mesh_catalog import catalog_content_hash, load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def _descriptor_ids_on_disk(repo_root=REPO_ROOT):
    root = Path(repo_root) / MC.MESH_GENERATED_REL
    if not root.is_dir():
        return set()
    return {p.name for p in root.iterdir() if p.is_dir() and (p / "descriptor.json").is_file()}


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    assets = catalog.get("assets") or {}

    rep.check("catalog_nonempty", bool(assets),
              "catalog has {} record(s)".format(len(assets)),
              code=FailureCode.MESH_CATALOG_FAILURE)
    if not assets:
        return rep, 0

    disk_ids = _descriptor_ids_on_disk()

    # Orphans: a descriptor on disk with no catalog record (brief §9).
    orphans = sorted(disk_ids - set(assets.keys()))
    rep.check("no_orphan_generated_meshes", not orphans,
              "generated meshes missing catalog records: {}".format(orphans),
              code=FailureCode.MESH_CATALOG_FAILURE)

    for aid, entry in sorted(assets.items()):
        def c(name, ok, detail="", code=FailureCode.MESH_CATALOG_FAILURE, warn_only=False):
            return rep.check("{}::{}".format(aid, name), ok, detail, code=code, warn_only=warn_only)

        # exactly one record — dict keys are unique, so verify id consistency.
        c("record_id_matches", entry.get("asset_id") == aid,
          "entry.asset_id={}".format(entry.get("asset_id")))

        # points to an existing descriptor / final asset record
        desc_rel = entry.get("descriptor_path", "")
        desc_path = REPO_ROOT / desc_rel if desc_rel else None
        exists = bool(desc_path and desc_path.is_file())
        c("descriptor_exists", exists,
          "descriptor missing: {}".format(desc_rel),
          code=FailureCode.MESH_CATALOG_FAILURE)

        descriptor = None
        if exists:
            try:
                descriptor = json.loads(desc_path.read_text(encoding="utf-8"))
            except Exception as exc:
                c("descriptor_parses", False, str(exc))

        # provenance + ownership recorded (brief §9)
        c("provenance_id_present", bool(entry.get("provenance_id")),
          "provenance_id missing", code=FailureCode.MESH_PROVENANCE_FAILURE)
        c("registry_id_present", bool(entry.get("registry_id")),
          "registry_id missing", code=FailureCode.MESH_CATALOG_FAILURE)
        if descriptor is not None:
            c("descriptor_generated_owned", descriptor.get("generated_owned") is True,
              "generated_owned={}".format(descriptor.get("generated_owned")),
              code=FailureCode.MESH_OWNERSHIP_FAILURE)
            c("descriptor_has_provenance", bool(descriptor.get("provenance")),
              "provenance block absent", code=FailureCode.MESH_PROVENANCE_FAILURE)

        # PCG-eligible assets must carry placement rules (brief §9)
        pcg = entry.get("pcg_eligibility")
        if pcg in (MC.PCG_ALLOWED, MC.PCG_CONDITIONAL) and descriptor is not None:
            rules = ((descriptor.get("placement_compatibility") or {}).get("pcg_rules"))
            c("pcg_eligible_has_placement_rules", bool(rules),
              "pcg_eligibility={} but no placement pcg_rules".format(pcg),
              code=FailureCode.MESH_PCG_ELIGIBILITY_FAILURE)

        # biome compatibility declared (brief §9)
        c("biome_compatibility_declared",
          isinstance(entry.get("biome_compatibility"), list) and bool(entry.get("biome_compatibility")),
          "biome_compatibility={}".format(entry.get("biome_compatibility")),
          code=FailureCode.MESH_BIOME_COMPATIBILITY_FAILURE)

    return rep, len(assets)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate WorldForge v1.2 mesh catalog integrity.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict)
    rep.finalize()
    catalog = load_mesh_catalog(REPO_ROOT)
    rep.set_meta(build_meta(command="validate-mesh-catalog", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n,
                            output_manifest_hash=catalog_content_hash(catalog)))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_mesh_catalog"
    rep.write(report_dir, "validate_mesh_catalog_report.json")
    rep.print_summary("validate-mesh-catalog")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
