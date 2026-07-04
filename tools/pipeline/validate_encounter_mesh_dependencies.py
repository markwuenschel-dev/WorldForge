#!/usr/bin/env python3
"""validate_encounter_mesh_dependencies.py — WorldForge v1.4 encounter mesh-dependency validator (Lane D).

Proves every encounter's mesh consumption is REAL and OWNERSHIP-CLEAN (brief
§12/§27): mesh_dependencies carries required_families + resolved_mesh_assets
lists; every required family is biome-compatible (EC.BIOME_COVER_FAMILIES);
every resolved asset exists in the v1.2 generated mesh catalog, resolves to
generated_owned, lists the encounter's biome in biome_compatibility, and
belongs to one of the declared required families; cover-requiring encounters
(cover_anchors non-empty) must actually resolve cover assets — cover without
assets is a fail; every megascans_dependencies id exists in the THIRD-PARTY
external catalog and is third_party_owned (a megascans id claiming
generated_owned is a hard ownership-separation fail); and no duplicate ids
appear across resolved_mesh_assets.

Usage:
    python tools/pipeline/validate_encounter_mesh_dependencies.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_mesh_dependencies/validate_encounter_mesh_dependencies_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mesh_contract as MESHC
from encounter_catalog import load_encounter_catalog
from external_asset_contract import load_external_catalog
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

CODE = FailureCode.ENCOUNTER_MESH_DEPENDENCY_FAILURE
BIOME_CODE = FailureCode.ENCOUNTER_BIOME_COMPATIBILITY_FAILURE

# asset_id -> resolved ownership class (descriptor-backed, cached per run).
_OWNERSHIP_CACHE = {}


def _resolved_ownership(aid, entry):
    """Resolve an asset's ownership class, preferring the materialized descriptor
    (catalog entries do not carry ownership flags; descriptors do)."""
    if aid in _OWNERSHIP_CACHE:
        return _OWNERSHIP_CACHE[aid]
    record = entry or {}
    desc = MESHC.mesh_descriptor_path(aid, REPO_ROOT)
    if desc.is_file():
        try:
            record = json.loads(desc.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — unreadable descriptor: fall back to entry
            record = entry or {}
    resolved = MESHC.resolve_ownership_class(record)
    _OWNERSHIP_CACHE[aid] = resolved
    return resolved


def check_mesh_deps(rep, eid, enc, mesh_assets, ext_assets):
    """Core mesh-dependency checks for one encounter (namespace '<check>::<eid>')."""
    def c(name, ok, detail="", code=CODE):
        return rep.check("{}::{}".format(name, eid), ok, detail, code=code)

    biome = enc.get("biome_family")
    md = enc.get("mesh_dependencies")

    # mesh_dependencies present with required_families + resolved_mesh_assets lists.
    c("mesh_dependencies_present", isinstance(md, dict),
      "mesh_dependencies missing or not a dict: {!r}".format(md))
    md = md if isinstance(md, dict) else {}
    req = md.get("required_families")
    res = md.get("resolved_mesh_assets")
    c("required_families_is_list", isinstance(req, list),
      "required_families must be a list, got {!r}".format(req))
    c("resolved_mesh_assets_is_list", isinstance(res, list),
      "resolved_mesh_assets must be a list, got {!r}".format(res))
    req = req if isinstance(req, list) else []
    res = res if isinstance(res, list) else []

    # Every required family must be biome-compatible for this encounter's biome.
    allowed = EC.BIOME_COVER_FAMILIES.get(biome, ())
    for fam in req:
        c("required_family_biome_compatible[{}]".format(fam), fam in allowed,
          "family '{}' not in EC.BIOME_COVER_FAMILIES['{}'] = {}".format(
              fam, biome, list(allowed)), code=BIOME_CODE)

    # Every resolved asset: exists, generated_owned, biome-compatible, family declared.
    seen = set()
    for aid in res:
        c("resolved_asset_unique[{}]".format(aid), aid not in seen,
          "duplicate resolved mesh asset id '{}'".format(aid))
        seen.add(aid)
        entry = mesh_assets.get(aid)
        exists = entry is not None
        c("resolved_asset_in_catalog[{}]".format(aid), exists,
          "resolved asset '{}' absent from generated mesh catalog".format(aid))
        if not exists:
            continue
        ownership = _resolved_ownership(aid, entry)
        c("resolved_asset_generated_owned[{}]".format(aid),
          ownership == MESHC.OWNERSHIP_GENERATED,
          "asset '{}' ownership resolved to {!r}, expected {!r}".format(
              aid, ownership, MESHC.OWNERSHIP_GENERATED))
        compat = entry.get("biome_compatibility") or []
        c("resolved_asset_biome_compatible[{}]".format(aid), biome in compat,
          "asset '{}' biome_compatibility {} excludes encounter biome '{}'".format(
              aid, compat, biome), code=BIOME_CODE)
        fam = entry.get("mesh_family")
        c("resolved_asset_family_required[{}]".format(aid), fam in req,
          "asset '{}' mesh_family '{}' not among required_families {}".format(
              aid, fam, sorted(req)))

    # Cover-requiring encounters must actually resolve mesh assets.
    covers = enc.get("cover_anchors") or []
    if covers:
        c("cover_requires_families", bool(req),
          "{} cover anchors but required_families is empty — cover without "
          "mesh families".format(len(covers)))
        c("cover_requires_resolved_assets", bool(res),
          "{} cover anchors but resolved_mesh_assets is empty — cover without "
          "assets".format(len(covers)))

    # Megascans dependencies: third-party catalog membership + ownership separation.
    for gid in enc.get("megascans_dependencies") or []:
        ext = ext_assets.get(gid)
        exists = ext is not None
        c("megascans_in_external_catalog[{}]".format(gid), exists,
          "megascans dependency '{}' absent from external (third-party) "
          "catalog".format(gid))
        if not exists:
            continue
        ownership = MESHC.resolve_ownership_class(ext)
        c("megascans_third_party_owned[{}]".format(gid),
          ownership == MESHC.OWNERSHIP_THIRD_PARTY,
          "megascans dependency '{}' ownership resolved to {!r}, expected "
          "{!r}".format(gid, ownership, MESHC.OWNERSHIP_THIRD_PARTY))
        c("megascans_never_generated_owned[{}]".format(gid),
          ownership != MESHC.OWNERSHIP_GENERATED and not bool(ext.get("generated_owned")),
          "megascans dependency '{}' claims generated_owned — ownership models "
          "must never merge".format(gid))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate v1.4 encounter mesh/megascans dependencies.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    mesh_assets = (load_mesh_catalog(REPO_ROOT) or {}).get("assets") or {}
    ext_assets = (load_external_catalog(REPO_ROOT) or {}).get("assets") or {}
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted(eid for eid, e in (catalog.get("encounters") or {}).items()
                  if (e or {}).get("pack_id") == args.pack)
    if not eids:
        rep.error("no encounters in pack '{}' — run 'make create-encounters' first".format(args.pack))
    if not mesh_assets:
        rep.error("no generated mesh catalog — run the v1.2 MeshForge intake first")
    if not ext_assets:
        rep.error("no external (Megascans) asset catalog — run the v1.2 Megascans intake first")

    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("loads::{}".format(eid), False, err, code=CODE)
            continue
        check_mesh_deps(rep, eid, enc, mesh_assets, ext_assets)
        n += 1

    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-mesh-dependencies",
                            pack=args.pack, strict=strict, status=rep.status,
                            record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_mesh_dependencies",
              "validate_encounter_mesh_dependencies_report.json")
    rep.print_summary("validate-encounter-mesh-dependencies")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
