#!/usr/bin/env python3
"""validate_generated_asset.py — WorldForge generated-asset intake validator.

Validates that ONE generated asset has been correctly taken into WorldForge
ownership: registry + descriptor + catalog membership, with the forbidden
Houdini Temp/Bake paths rejected. Pure Python — no UE imports.

v0.9: migrated onto the shared ``ValidationReport`` helper (one report shape,
one strict-mode semantics) and stable ``FailureCode``s. The hard intake
guarantees stay hard FAILs; the UE StaticMesh-at-path check reads a UE report
when present (verified PASS/FAIL) and is skipped otherwise — run
``make relocate-houdini-asset`` to drive the editor materialization.

Usage:
    python tools/pipeline/validate_generated_asset.py --asset rock_generator_desert_01
    STRICT=1 python tools/pipeline/validate_generated_asset.py --asset rock_generator_desert_01 --strict

Writes:
    procedural/reports/generated_assets/<asset_id>/validate_generated_asset_report.json

Exit 0 = PASS (status ok|warn), 1 = FAIL (status fail|error).

Requires: PyYAML (pip install pyyaml)
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_ROOT = "/Game/WorldForge/Generated/Houdini/Rocks"

sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from generated_asset_registry import is_forbidden_path, load_generated_asset_registry
from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode


def _catalog_has(catalog_id, category, unreal_path):
    cat_path = REPO_ROOT / "procedural" / "definitions" / "assets" / (catalog_id + ".yaml")
    if not cat_path.is_file():
        return False
    try:
        with cat_path.open("r", encoding="utf-8") as fh:
            catalog = yaml.safe_load(fh) or {}
    except Exception:
        return False
    assets = (catalog.get("categories", {}).get(category, {}) or {}).get("assets", [])
    return unreal_path in assets


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate WorldForge generated-asset intake.")
    ap.add_argument("--asset", required=True, help="Asset id")
    ap.add_argument("--strict", action="store_true",
                    help="Treat soft warnings as blocking (also via STRICT=1).")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    asset_id = args.asset
    report_dir = REPO_ROOT / "procedural" / "reports" / "generated_assets" / asset_id

    rep = ValidationReport("asset_id", asset_id, strict=strict)

    # -- Descriptor ---------------------------------------------------------
    desc_path = REPO_ROOT / "procedural" / "generated" / "generated_assets" / asset_id / "descriptor.json"
    descriptor = None
    if rep.check("descriptor_exists", desc_path.is_file(),
                 str(desc_path.relative_to(REPO_ROOT)),
                 code=FailureCode.DESCRIPTOR_MISSING):
        try:
            with desc_path.open("r", encoding="utf-8") as fh:
                descriptor = json.load(fh)
            rep.check("descriptor_parses", True)
        except Exception as exc:
            rep.check("descriptor_parses", False, str(exc),
                      code=FailureCode.DESCRIPTOR_UNPARSEABLE)

    if descriptor is None:
        rep.error("descriptor missing or unparseable")
        rep.write(report_dir, "validate_generated_asset_report.json")
        rep.print_summary("validate-generated-asset")
        print("[validate-generated-asset] FAIL — descriptor missing or unparseable")
        sys.exit(rep.exit_code)

    unreal_path = descriptor.get("unreal_path", "")

    # -- Registry -----------------------------------------------------------
    registry = load_generated_asset_registry(REPO_ROOT)
    rep.check("registry_owns_asset", asset_id in registry,
              "not found in worldforge_generated_asset_registry.json",
              code=FailureCode.REGISTRY_MISSING_ENTRY)

    # -- Identity / type ----------------------------------------------------
    rep.check("asset_type_is_static_mesh", descriptor.get("asset_type") == "static_mesh",
              "asset_type={}".format(descriptor.get("asset_type")),
              code=FailureCode.SPEC_INVALID)
    rep.check("source_is_houdini", descriptor.get("source") == "houdini",
              "source={}".format(descriptor.get("source")),
              code=FailureCode.SPEC_INVALID)
    rep.check("hda_name_present", bool(descriptor.get("hda_name")), "hda_name missing",
              code=FailureCode.PROVENANCE_INCOMPLETE)

    # -- Path ownership (the load-bearing intake guarantees) ----------------
    rep.check("path_under_worldforge_owned", unreal_path.startswith(ALLOWED_ROOT),
              "must be under {} — got {}".format(ALLOWED_ROOT, unreal_path),
              code=FailureCode.PATH_NOT_OWNED)
    rep.check("path_not_houdini_temp_or_bake", not is_forbidden_path(unreal_path),
              "registered path is a forbidden Houdini Temp/Bake path: {}".format(unreal_path),
              code=FailureCode.FORBIDDEN_PATH)

    # -- Flags --------------------------------------------------------------
    rep.check("generated_owned_true", descriptor.get("generated_owned") is True,
              "generated_owned={}".format(descriptor.get("generated_owned")),
              code=FailureCode.GENERATED_FLAG_MISSING)
    rep.check("not_temporary", descriptor.get("temporary") is False,
              "temporary={}".format(descriptor.get("temporary")),
              code=FailureCode.TEMP_PATH_AS_FINAL)

    # -- PCG eligibility + desert compatibility (machine-readable) ----------
    rep.check("pcg_allowed_true", descriptor.get("pcg_allowed") is True,
              "pcg_allowed={}".format(descriptor.get("pcg_allowed")),
              code=FailureCode.SPEC_INVALID)
    rep.check("desert_compatible", "desert" in (descriptor.get("biome") or []),
              "biome={}".format(descriptor.get("biome")),
              code=FailureCode.SPEC_INVALID)
    in_catalog = _catalog_has(descriptor.get("asset_catalog", ""),
                              descriptor.get("placement_category", ""), unreal_path)
    rep.check("catalog_membership", in_catalog,
              "PCG eligibility requires {} listed in {}.{}".format(
                  unreal_path, descriptor.get("asset_catalog"), descriptor.get("placement_category")),
              code=FailureCode.CATALOG_MEMBERSHIP_MISSING)

    # -- Provenance ---------------------------------------------------------
    rep.check("provenance_exists", bool(descriptor.get("provenance")),
              "provenance block absent from descriptor",
              code=FailureCode.PROVENANCE_MISSING)

    # -- UE presence: verified when the editor relocate has produced its report;
    #    otherwise skipped (run 'make relocate-houdini-asset' to drive the editor).
    ue_report = report_dir / "ue_generated_asset_report.json"
    if ue_report.is_file():
        ue_ok = False
        ue_code = FailureCode.UE_ARTIFACT_MISSING
        try:
            ue_rpt = json.loads(ue_report.read_text(encoding="utf-8"))
            is_sm = ue_rpt.get("is_static_mesh") is True
            ue_ok = bool(ue_rpt.get("passed")) and is_sm
            ue_detail = "ue path={} static_mesh={}".format(
                ue_rpt.get("unreal_path"), ue_rpt.get("is_static_mesh"))
            if not ue_ok and not is_sm:
                # UE report exists but the materialized asset is not a StaticMesh.
                ue_code = FailureCode.UE_ASSET_NOT_STATIC_MESH
        except Exception as exc:
            ue_detail = "ue report unreadable: {}".format(exc)
        rep.ue_check("asset_exists_in_ue_as_static_mesh", ue_ok, ue_detail, code=ue_code)
    else:
        rep.skip("asset_exists_in_ue_as_static_mesh",
                 "no ue_generated_asset_report yet; run 'make relocate-houdini-asset' to materialize + verify the StaticMesh")

    # -- Result -------------------------------------------------------------
    rep.finalize()
    rep.write(report_dir, "validate_generated_asset_report.json")
    rep.print_summary("validate-generated-asset")
    print("[validate-generated-asset]   path={} pcg_allowed={} biome={}".format(
        unreal_path, descriptor.get("pcg_allowed"), descriptor.get("biome")))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
