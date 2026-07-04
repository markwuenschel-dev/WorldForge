#!/usr/bin/env python3
"""validate_third_party_package_policy.py — WorldForge v1.2 addendum §8 lane.

The THIRD-PARTY package-policy gate. Megascans raw source assets may ONLY ship as
*incorporated project content* — never as a standalone, redistributable raw-asset
pack (addendum §8/§14). This validator asserts that every external (Megascans)
record in the external asset catalog carries a package_policy that pins it to the
incorporated model, and that the external (third_party) catalog has NOT leaked
into the generated mesh catalog (a third_party asset emitted into the generated
catalog without external provenance is a derived-output / package-policy breach).

It is PACK-scoped and reads BOTH catalogs:
    procedural/generated/worldforge_external_asset_catalog.json  (51 Megascans)
    procedural/generated/worldforge_mesh_catalog.json            (42 generated)

Per external record (addendum §8):
  * package_policy present with ALL EAC.PACKAGE_POLICY_REQUIRED keys
  * package_usage == EAC.PACKAGE_USAGE_INCORPORATED  (never standalone)
  * standalone_redistribution_allowed is False
  * raw_asset_export_allowed is False
  * requires_project_context is True
  * license_family preserved (present)
  * ownership resolves to third_party_owned (this IS the third-party lane)

Cross-catalog (the load-bearing separation check for THIS lane):
  * external_asset_id set and mesh catalog asset_id set are DISJOINT
  * external final asset paths and mesh final asset paths are DISJOINT
  * NO generated mesh catalog entry resolves to third_party_owned — a third_party
    asset in the generated catalog without external provenance is a
    DERIVED_OUTPUT_PROVENANCE_FAILURE

Usage:
    python tools/pipeline/validate_third_party_package_policy.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_third_party_package_policy.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_third_party_package_policy/
        validate_third_party_package_policy_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC
import external_asset_contract as EAC
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

_POLICY_CODE = FailureCode.THIRD_PARTY_ASSET_PACKAGE_POLICY_FAILURE
_PROV_CODE = FailureCode.DERIVED_OUTPUT_PROVENANCE_FAILURE


def _load_mesh_record(asset_id, repo_root=REPO_ROOT):
    """Prefer the materialized descriptor (carries ownership fields); fall back to
    the definition YAML. Returns (record, error_str)."""
    desc = MC.mesh_descriptor_path(asset_id, repo_root)
    if desc.is_file():
        try:
            return json.loads(desc.read_text(encoding="utf-8")), None
        except Exception as exc:
            return None, "descriptor unparseable: {}".format(exc)
    return MC.load_mesh_definition(MC.mesh_definition_path(asset_id, repo_root))


def check_external_record(rep, aid, entry):
    """Assert one Megascans record is pinned to the incorporated package model."""
    def c(name, ok, detail="", code=_POLICY_CODE):
        return rep.check("external::{}::{}".format(aid, name), ok, detail, code=code)

    # -- this lane only speaks about third_party assets ----------------------
    resolved = MC.resolve_ownership_class(entry)
    c("resolves_third_party_owned",
      resolved == MC.OWNERSHIP_THIRD_PARTY,
      "external asset ownership resolved to {!r}, expected {!r}".format(
          resolved, MC.OWNERSHIP_THIRD_PARTY))

    # -- package_policy present with all required keys -----------------------
    pp = entry.get("package_policy")
    if not isinstance(pp, dict):
        c("package_policy_present", False,
          "package_policy absent or not a mapping: {!r}".format(pp))
        return
    c("package_policy_present", True, "")
    missing = [k for k in EAC.PACKAGE_POLICY_REQUIRED if k not in pp]
    c("package_policy_complete", not missing,
      "package_policy missing required keys: {}".format(missing))

    # -- incorporated project content ONLY, never standalone -----------------
    usage = pp.get("package_usage")
    c("package_usage_incorporated",
      usage == EAC.PACKAGE_USAGE_INCORPORATED,
      "package_usage must be {!r} (incorporated project content only, never "
      "standalone), got {!r}".format(EAC.PACKAGE_USAGE_INCORPORATED, usage))
    c("standalone_redistribution_forbidden",
      pp.get("standalone_redistribution_allowed") is False,
      "standalone_redistribution_allowed must be False (raw Megascans source may "
      "never be a standalone redistributable pack), got {!r}".format(
          pp.get("standalone_redistribution_allowed")))
    c("raw_asset_export_forbidden",
      pp.get("raw_asset_export_allowed") is False,
      "raw_asset_export_allowed must be False (raw source assets may not be "
      "exported), got {!r}".format(pp.get("raw_asset_export_allowed")))
    c("requires_project_context_true",
      pp.get("requires_project_context") is True,
      "requires_project_context must be True (usable only inside the project), "
      "got {!r}".format(pp.get("requires_project_context")))

    # -- license family preserved --------------------------------------------
    lf = entry.get("license_family")
    c("license_family_preserved", bool(lf),
      "license_family missing/empty on a third_party asset: {!r}".format(lf),
      code=FailureCode.EXTERNAL_LICENSE_METADATA_FAILURE)


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    ext = EAC.load_external_catalog(REPO_ROOT)
    mesh = load_mesh_catalog(REPO_ROOT)
    ext_assets = ext.get("assets") or {}
    mesh_assets = mesh.get("assets") or {}

    if not ext_assets:
        rep.error("no external assets found — run 'make scan-external-asset-library' first")
        return rep, 0, 0

    # -- per-record package policy -------------------------------------------
    for aid, entry in sorted(ext_assets.items()):
        check_external_record(rep, aid, entry)
    n_ext = len(ext_assets)

    # -- cross-catalog: external (third_party) must NOT leak into generated ---
    ext_ids = set(ext_assets.keys())
    mesh_ids = set(mesh_assets.keys())
    id_overlap = sorted(ext_ids & mesh_ids)
    rep.check("cross_catalog::asset_ids_disjoint", not id_overlap,
              "external_asset_id set and generated mesh asset_id set must be "
              "disjoint; shared ids: {}".format(id_overlap), code=_POLICY_CODE)

    ext_finals = {e.get("final_asset_path") for e in ext_assets.values()
                  if e.get("final_asset_path")}
    mesh_finals = {e.get("final_asset_path") for e in mesh_assets.values()
                   if e.get("final_asset_path")}
    path_overlap = sorted(ext_finals & mesh_finals)
    rep.check("cross_catalog::final_paths_disjoint", not path_overlap,
              "external and generated mesh final asset paths must be disjoint; "
              "shared paths: {}".format(path_overlap), code=_POLICY_CODE)

    # -- no generated mesh entry may resolve to third_party_owned ------------
    third_party_in_mesh = []
    for aid in sorted(mesh_assets.keys()):
        record, err = _load_mesh_record(aid)
        if record is None:
            rep.check("mesh::{}::record_loads".format(aid), False,
                      err or "no record", code=_PROV_CODE)
            continue
        if MC.resolve_ownership_class(record) == MC.OWNERSHIP_THIRD_PARTY:
            third_party_in_mesh.append(aid)
    rep.check("cross_catalog::no_third_party_in_generated_catalog",
              not third_party_in_mesh,
              "generated mesh catalog entries resolve to third_party_owned "
              "(third_party asset emitted into the generated catalog without "
              "external provenance): {}".format(third_party_in_mesh),
              code=_PROV_CODE)

    return rep, n_ext, len(mesh_assets)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.2 third-party (Megascans) package policy.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n_ext, n_mesh = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-third-party-package-policy", pack=args.pack,
        strict=strict, status=rep.status, record_count=n_ext,
        extra={"external_count": n_ext, "mesh_count": n_mesh}))
    report_dir = (REPO_ROOT / MC.MESH_REPORTS_REL
                  / "validate_third_party_package_policy")
    rep.write(report_dir, "validate_third_party_package_policy_report.json")
    rep.print_summary("validate-third-party-package-policy")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
