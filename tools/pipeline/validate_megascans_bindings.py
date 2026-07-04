#!/usr/bin/env python3
"""validate_megascans_bindings.py — WorldForge v1.2 addendum Megascans binding validator.

Validates that every THIRD-PARTY Megascans record in the external asset catalog
carries an honest, complete material / texture binding contract (addendum §6).
A Megascans asset is externally owned and licensed, so its bindings describe
EXTERNAL source materials: the material_asset_path may legitimately be None, but
ONLY when the binding explicitly declares ``external_source: true``. A None
material path WITHOUT that declaration is a missing reference — a binding failure,
not an external convenience. Every binding must still name its slot, material
family, texture set, and the biome families it supports (all known families), and
the record must carry a non-empty top-level texture_set.

This is the binding gate — the sibling validate_megascans_pcg_eligibility.py
enforces PCG rule completeness and validate_megascans_biome_compatibility.py
enforces the biome taxonomy. All three read the EXTERNAL catalog, never the
generated mesh catalog (ownership models never merge — addendum §6/§7).

Usage:
    python tools/pipeline/validate_megascans_bindings.py --pack biome_expansion_world
    STRICT=1 python tools/pipeline/validate_megascans_bindings.py --pack biome_expansion_world --strict

Writes: procedural/reports/mesh/validate_megascans_bindings/validate_megascans_bindings_report.json
Exit 0 = pass, 1 = fail.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mesh_contract as MC
import external_asset_contract as EAC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

_CODE = FailureCode.MEGASCANS_BINDING_FAILURE


def check_record(rep, asset_id, record):
    """Run all binding checks for one external asset, prefixing names with the id."""
    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(asset_id, name), ok, detail, code=_CODE)

    # -- top-level texture_set must be present + non-empty ------------------
    texture_set = record.get("texture_set")
    c("texture_set_non_empty",
      isinstance(texture_set, list) and bool(texture_set),
      "top-level texture_set must be a non-empty list: {}".format(texture_set))

    # -- material_bindings present + non-empty -----------------------------
    bindings = record.get("material_bindings")
    c("material_bindings_non_empty",
      isinstance(bindings, list) and bool(bindings),
      "material_bindings must be a non-empty list: {}".format(bindings))
    if not (isinstance(bindings, list) and bindings):
        return  # nothing further to validate without bindings

    for i, b in enumerate(bindings):
        b = b if isinstance(b, dict) else {}

        c("binding_{}_slot_name".format(i), bool(b.get("slot_name")),
          "binding {} missing slot_name".format(i))
        c("binding_{}_material_family".format(i), bool(b.get("material_family")),
          "binding {} missing material_family".format(i))

        tex = b.get("texture_set")
        c("binding_{}_texture_set_non_empty".format(i),
          isinstance(tex, list) and bool(tex),
          "binding {} texture_set must be a non-empty list: {}".format(i, tex))

        # -- material_asset_path: None only when external_source is True ----
        path = b.get("material_asset_path")
        external_source = b.get("external_source") is True
        if path is None:
            c("binding_{}_material_path_external_ok".format(i), external_source,
              "binding {} has a None material_asset_path without external_source=True"
              " (missing material/texture reference)".format(i))
        else:
            c("binding_{}_material_path_non_empty".format(i),
              isinstance(path, str) and bool(path.strip()),
              "binding {} material_asset_path must be a non-empty string when set:"
              " {!r}".format(i, path))

        # -- binding biome_compatibility non-empty + all known families ----
        mbc = b.get("biome_compatibility")
        c("binding_{}_biome_compat_non_empty".format(i),
          isinstance(mbc, list) and bool(mbc),
          "binding {} biome_compatibility must be a non-empty list: {}".format(i, mbc))
        mbc = mbc if isinstance(mbc, list) else []
        unknown = [x for x in mbc if x not in MC.BIOME_FAMILIES]
        c("binding_{}_biome_compat_known".format(i), not unknown,
          "binding {} has unknown biome families: {}".format(i, unknown))


def validate(pack, strict):
    rep = ValidationReport("pack", pack, strict=strict)
    catalog = EAC.load_external_catalog(REPO_ROOT)
    assets = catalog.get("assets") or {}
    if not assets:
        rep.error("no external assets found — run "
                  "'python tools/pipeline/scan_external_asset_library.py --lib megascans' first")
        return rep, 0

    n = 0
    for aid, record in sorted(assets.items()):
        if not isinstance(record, dict):
            rep.check("{}::record_loads".format(aid), False,
                      "external catalog entry is not a mapping", code=_CODE)
            continue
        check_record(rep, aid, record)
        n += 1
    return rep, n


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate WorldForge v1.2 Megascans material/texture bindings.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, n = validate(args.pack, strict)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-megascans-bindings", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "validate_megascans_bindings"
    rep.write(report_dir, "validate_megascans_bindings_report.json")
    rep.print_summary("validate-megascans-bindings")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
