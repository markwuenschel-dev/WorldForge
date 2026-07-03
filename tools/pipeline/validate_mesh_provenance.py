#!/usr/bin/env python3
"""validate_mesh_provenance.py — WorldForge v1.2 mesh provenance + ownership validator.

Validates that every generated mesh asset is REGISTERED, PROVENANCED, and OWNED
(brief §27 "Required Checks", provenance side). This is the ledger-integrity gate:
it proves the catalog and the on-disk descriptors agree about who owns each mesh,
that a provenance record exists, that ownership flags are correct, that source
hashes match between descriptor and catalog, and that there are no orphans in
either direction (a descriptor with no catalog record, or a catalog record whose
descriptor is missing).

It reads the DESCRIPTORS produced by create_mesh_assets.py (the materialized
record — a superset of the definition that carries the ``provenance`` block,
``provenance_id`` and ``registry_id``) and cross-checks them against the
generated mesh catalog (the source of truth).

Usage:
    python tools/pipeline/validate_mesh_provenance.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_mesh_provenance.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_mesh_provenance/validate_mesh_provenance_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def _load_descriptor(asset_id, repo_root=REPO_ROOT):
    """Load the materialized descriptor for an asset. Returns (record, error)."""
    desc = MC.mesh_descriptor_path(asset_id, repo_root)
    if desc.is_file():
        try:
            return json.loads(desc.read_text(encoding="utf-8")), None
        except Exception as exc:
            return None, "descriptor unparseable: {}".format(exc)
    return None, "descriptor not found: {}".format(desc)


def check_asset(rep, asset_id, record, entry, strict):
    """Run all provenance/ownership checks for one asset, prefixing the id."""
    def c(name, ok, detail="", code=FailureCode.MESH_PROVENANCE_FAILURE):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=code)

    # -- registry record exists (catalog entry carries a registry_id) -------
    registry_id = (entry or {}).get("registry_id")
    c("registry_record_exists", bool(registry_id),
      "catalog entry registry_id missing/empty", code=FailureCode.MESH_CATALOG_FAILURE)

    # -- provenance record exists (descriptor provenance block + provenance_id)
    prov = record.get("provenance")
    c("provenance_block_present", isinstance(prov, dict) and bool(prov),
      "descriptor provenance block absent or empty")
    prov_id_desc = record.get("provenance_id")
    prov_id_cat = (entry or {}).get("provenance_id")
    c("provenance_id_present", bool(prov_id_desc) and bool(prov_id_cat),
      "provenance_id missing (descriptor={}, catalog={})".format(
          prov_id_desc, prov_id_cat))
    c("provenance_id_matches", prov_id_desc == prov_id_cat,
      "provenance_id mismatch: descriptor={} catalog={}".format(
          prov_id_desc, prov_id_cat))

    # -- ownership: generated-owned, not human-owned ------------------------
    c("ownership_generated_owned", record.get("generated_owned") is True,
      "generated_owned={}".format(record.get("generated_owned")),
      code=FailureCode.MESH_OWNERSHIP_FAILURE)
    c("ownership_human_owned_false", record.get("human_owned") is False,
      "human_owned={}".format(record.get("human_owned")),
      code=FailureCode.MESH_OWNERSHIP_FAILURE)

    # -- source_hash present and consistent descriptor <-> catalog ----------
    src_desc = record.get("source_hash")
    src_cat = (entry or {}).get("source_hash")
    c("source_hash_present", bool(src_desc),
      "descriptor source_hash missing")
    c("source_hash_matches_catalog", bool(src_desc) and src_desc == src_cat,
      "source_hash mismatch: descriptor={} catalog={}".format(src_desc, src_cat),
      code=FailureCode.MESH_CATALOG_FAILURE)

    # -- no orphan (catalog record -> descriptor exists on disk) ------------
    desc_path = MC.mesh_descriptor_path(asset_id)
    c("catalog_record_has_descriptor", desc_path.is_file(),
      "descriptor missing on disk for catalog record: {}".format(desc_path),
      code=FailureCode.MESH_CATALOG_FAILURE)


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = load_mesh_catalog(REPO_ROOT)
    assets = catalog.get("assets") or {}
    asset_ids = sorted(assets.keys())
    if not asset_ids:
        rep.error("no mesh assets in catalog — run 'make create-mesh-assets' first")
        return rep, 0

    n = 0
    for aid in asset_ids:
        record, err = _load_descriptor(aid)
        if record is None:
            rep.check("{}::descriptor_loads".format(aid), False, err or "no descriptor",
                      code=FailureCode.MESH_CATALOG_FAILURE)
            continue
        check_asset(rep, aid, record, assets.get(aid), strict)
        n += 1

    # -- no orphan (descriptor on disk -> catalog record exists) ------------
    gen_root = REPO_ROOT / MC.MESH_GENERATED_REL
    if gen_root.is_dir():
        for desc in sorted(gen_root.glob("*/descriptor.json")):
            disk_id = desc.parent.name
            rep.check(
                "{}::descriptor_has_catalog_record".format(disk_id),
                disk_id in assets,
                "orphan descriptor on disk with no catalog record: {}".format(desc),
                code=FailureCode.MESH_CATALOG_FAILURE)

    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.2 mesh provenance + ownership.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-mesh-provenance", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_mesh_provenance"
    rep.write(report_dir, "validate_mesh_provenance_report.json")
    rep.print_summary("validate-mesh-provenance")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
