#!/usr/bin/env python3
"""validate_source_ownership_separation.py — WorldForge v1.2 addendum §14 lane.

The LOAD-BEARING ownership-separation validator. The v1.2 addendum keeps THREE
ownership models strictly apart and this gate proves they never merge:

  1. The generated mesh catalog (generated_owned) and the external asset catalog
     (third_party_owned) are separate ownership models — never merged.
  2. Houdini SOURCE HDAs and Houdini-generated BAKED outputs must NOT share the
     same ownership class: the baked output is generated_owned, but the source HDA
     is project_owned or third_party_owned.
  3. No cross-contamination: a generated mesh is never third_party/human owned;
     an external asset is never generated_owned.

Ambiguous or merged ownership fails in STRICT=1.

It is PACK-scoped and reads BOTH catalogs:
    procedural/generated/worldforge_mesh_catalog.json            (42 generated)
    procedural/generated/worldforge_external_asset_catalog.json  (51 Megascans)

Checks (addendum §14):
  (a) Every generated mesh asset resolves (MC.resolve_ownership_class) to a
      NON-None class and that class is generated_owned — ambiguous ownership is a
      SOURCE_OWNERSHIP_SEPARATION_FAILURE.
  (b) Every external asset resolves to third_party_owned.
  (c) The two catalogs are DISJOINT by id and by final path (no asset in both).
  (d) For each houdini_generated mesh: the baked OUTPUT is generated_owned but
      houdini_intake.hda_ownership_class is in HC.HDA_OWNERSHIP_CLASSES and is NOT
      generated_owned — HDA source ownership must differ from the baked-output
      ownership class (HOUDINI_HDA_OWNERSHIP_FAILURE otherwise).
  (e) No generated mesh is third_party_owned or human_owned; no external asset is
      generated_owned — cross-contamination is a SOURCE_OWNERSHIP_SEPARATION_FAILURE.

Usage:
    python tools/pipeline/validate_source_ownership_separation.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_source_ownership_separation.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_source_ownership_separation/
        validate_source_ownership_separation_report.json
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
import houdini_contract as HC
from mesh_catalog import load_mesh_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

_SEP_CODE = FailureCode.SOURCE_OWNERSHIP_SEPARATION_FAILURE
_HDA_CODE = FailureCode.HOUDINI_HDA_OWNERSHIP_FAILURE
_EXT_CODE = FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE

# Ownership classes a generated mesh output may NEVER carry (§14 (e)).
_FORBIDDEN_ON_GENERATED = (MC.OWNERSHIP_THIRD_PARTY, MC.OWNERSHIP_HUMAN)


def _load_mesh_record(asset_id, repo_root=REPO_ROOT):
    """Prefer the materialized descriptor (carries ownership + houdini_intake);
    fall back to the definition YAML. Returns (record, error_str)."""
    desc = MC.mesh_descriptor_path(asset_id, repo_root)
    if desc.is_file():
        try:
            return json.loads(desc.read_text(encoding="utf-8")), None
        except Exception as exc:
            return None, "descriptor unparseable: {}".format(exc)
    return MC.load_mesh_definition(MC.mesh_definition_path(asset_id, repo_root))


def check_generated_mesh(rep, aid, entry, record):
    """(a) + (e) + (d) for one generated mesh asset. Returns the resolved class."""
    def c(name, ok, detail="", code=_SEP_CODE):
        return rep.check("mesh::{}::{}".format(aid, name), ok, detail, code=code)

    resolved = MC.resolve_ownership_class(record)

    # (a) unambiguous, non-None ownership
    c("ownership_resolves", resolved is not None,
      "ownership is ambiguous (resolve_ownership_class returned None) — zero or "
      "conflicting ownership assertions", code=_SEP_CODE)

    # (a) generated mesh assets are generated_owned
    c("ownership_is_generated_owned",
      resolved == MC.OWNERSHIP_GENERATED,
      "generated mesh asset resolved to {!r}, expected {!r}".format(
          resolved, MC.OWNERSHIP_GENERATED),
      code=_SEP_CODE)

    # (e) never third_party / human owned
    c("not_third_party_or_human",
      resolved not in _FORBIDDEN_ON_GENERATED,
      "generated mesh asset marked {!r} — generated output must never carry a "
      "third_party/human ownership class".format(resolved), code=_SEP_CODE)

    # (d) houdini source HDA ownership must DIFFER from baked-output ownership
    if HC.is_houdini_asset(entry) or HC.is_houdini_asset(record):
        intake = HC.houdini_intake_block(record)
        hoc = intake.get("hda_ownership_class")
        c("houdini_hda_ownership_class_valid",
          hoc in HC.HDA_OWNERSHIP_CLASSES,
          "houdini_intake.hda_ownership_class must be one of {} (project/third-"
          "party — never generated), got {!r}".format(HC.HDA_OWNERSHIP_CLASSES, hoc),
          code=_HDA_CODE)
        c("houdini_hda_ownership_differs_from_output",
          hoc != MC.OWNERSHIP_GENERATED and hoc != resolved,
          "HDA source ownership {!r} must differ from the baked-output ownership "
          "class {!r}; source HDAs and baked outputs may not share an ownership "
          "class".format(hoc, resolved), code=_HDA_CODE)

    return resolved


def check_external_asset(rep, aid, entry):
    """(b) + (e) for one external asset. Returns the resolved class."""
    def c(name, ok, detail="", code=_EXT_CODE):
        return rep.check("external::{}::{}".format(aid, name), ok, detail, code=code)

    resolved = MC.resolve_ownership_class(entry)
    c("resolves_third_party_owned",
      resolved == MC.OWNERSHIP_THIRD_PARTY,
      "external asset resolved to {!r}, expected {!r}".format(
          resolved, MC.OWNERSHIP_THIRD_PARTY), code=_EXT_CODE)
    # (e) an external asset is never generated_owned
    c("not_generated_owned",
      resolved != MC.OWNERSHIP_GENERATED and not bool(entry.get("generated_owned")),
      "external asset marked generated_owned — the external (third_party) model "
      "must never be merged into the generated model", code=_SEP_CODE)
    return resolved


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    mesh = load_mesh_catalog(REPO_ROOT)
    ext = EAC.load_external_catalog(REPO_ROOT)
    mesh_assets = mesh.get("assets") or {}
    ext_assets = ext.get("assets") or {}

    if not mesh_assets:
        rep.error("no generated mesh assets found — run 'make create-mesh-assets' first")
        return rep, 0, 0, 0
    if not ext_assets:
        rep.error("no external assets found — run 'make scan-external-asset-library' first")
        return rep, 0, 0, 0

    # (a)(d)(e) generated mesh side
    n_houdini = 0
    for aid, entry in sorted(mesh_assets.items()):
        record, err = _load_mesh_record(aid)
        if record is None:
            rep.check("mesh::{}::record_loads".format(aid), False,
                      err or "no record", code=_SEP_CODE)
            continue
        if HC.is_houdini_asset(entry) or HC.is_houdini_asset(record):
            n_houdini += 1
        check_generated_mesh(rep, aid, entry, record)

    # (b)(e) external side
    for aid, entry in sorted(ext_assets.items()):
        check_external_asset(rep, aid, entry)

    # (c) the two catalogs are disjoint by id and by final path
    mesh_ids = set(mesh_assets.keys())
    ext_ids = set(ext_assets.keys())
    id_overlap = sorted(mesh_ids & ext_ids)
    rep.check("separation::asset_ids_disjoint", not id_overlap,
              "generated mesh and external catalogs must be disjoint by id "
              "(merged ownership models); shared ids: {}".format(id_overlap),
              code=_SEP_CODE)

    mesh_finals = {e.get("final_asset_path") for e in mesh_assets.values()
                   if e.get("final_asset_path")}
    ext_finals = {e.get("final_asset_path") for e in ext_assets.values()
                  if e.get("final_asset_path")}
    path_overlap = sorted(mesh_finals & ext_finals)
    rep.check("separation::final_paths_disjoint", not path_overlap,
              "generated mesh and external catalogs must be disjoint by final "
              "asset path; shared paths: {}".format(path_overlap), code=_SEP_CODE)

    return rep, len(mesh_assets), len(ext_assets), n_houdini


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.2 source ownership separation.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n_mesh, n_ext, n_houdini = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-source-ownership-separation", pack=args.pack,
        strict=strict, status=rep.status, record_count=n_mesh + n_ext,
        extra={"mesh_count": n_mesh, "external_count": n_ext,
               "houdini_count": n_houdini}))
    report_dir = (REPO_ROOT / MC.MESH_REPORTS_REL
                  / "validate_source_ownership_separation")
    rep.write(report_dir, "validate_source_ownership_separation_report.json")
    rep.print_summary("validate-source-ownership-separation")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
