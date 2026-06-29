#!/usr/bin/env python3
"""validate_generated_asset.py — WorldForge generated-asset intake validator.

Validates that ONE generated asset has been correctly taken into WorldForge
ownership: registry + descriptor + catalog membership, with the forbidden
Houdini Temp/Bake paths rejected. Pure Python — no UE imports.

The actual UE StaticMesh-at-path check is loaded from a UE report when present
and treated as warn_only until relocate_houdini_asset.py has been run.

Usage:
    python tools/pipeline/validate_generated_asset.py --asset rock_generator_desert_01

Writes:
    procedural/reports/generated_assets/<asset_id>/validate_generated_asset_report.json

Exit 0 = PASS, 1 = FAIL.

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
    args = ap.parse_args(argv)

    asset_id = args.asset
    report_dir = REPO_ROOT / "procedural" / "reports" / "generated_assets" / asset_id
    report_dir.mkdir(parents=True, exist_ok=True)
    result = {"asset_id": asset_id, "checks": {}, "failures": []}

    def check(name, ok, detail="", warn_only=False):
        result["checks"][name] = {"ok": bool(ok), "detail": str(detail), "warn_only": warn_only}
        if not ok:
            if warn_only:
                result.setdefault("warnings", []).append("{}: {}".format(name, detail or "warn"))
            else:
                result["failures"].append("{}: {}".format(name, detail or "failed"))
        return bool(ok)

    # -- Descriptor ---------------------------------------------------------
    desc_path = REPO_ROOT / "procedural" / "generated" / "generated_assets" / asset_id / "descriptor.json"
    descriptor = None
    if check("descriptor_exists", desc_path.is_file(), str(desc_path.relative_to(REPO_ROOT))):
        try:
            with desc_path.open("r", encoding="utf-8") as fh:
                descriptor = json.load(fh)
            check("descriptor_parses", True)
        except Exception as exc:
            check("descriptor_parses", False, str(exc))

    if descriptor is None:
        result["passed"] = False
        result["status"] = "error"
        _write_report(report_dir, result)
        print("[validate-generated-asset] FAIL — descriptor missing or unparseable")
        sys.exit(1)

    unreal_path = descriptor.get("unreal_path", "")

    # -- Registry -----------------------------------------------------------
    registry = load_generated_asset_registry(REPO_ROOT)
    check("registry_owns_asset", asset_id in registry,
          "not found in worldforge_generated_asset_registry.json")

    # -- Identity / type ----------------------------------------------------
    check("asset_type_is_static_mesh", descriptor.get("asset_type") == "static_mesh",
          "asset_type={}".format(descriptor.get("asset_type")))
    check("source_is_houdini", descriptor.get("source") == "houdini",
          "source={}".format(descriptor.get("source")))
    check("hda_name_present", bool(descriptor.get("hda_name")), "hda_name missing")

    # -- Path ownership (the load-bearing intake guarantees) ----------------
    check("path_under_worldforge_owned", unreal_path.startswith(ALLOWED_ROOT),
          "must be under {} — got {}".format(ALLOWED_ROOT, unreal_path))
    check("path_not_houdini_temp_or_bake", not is_forbidden_path(unreal_path),
          "registered path is a forbidden Houdini Temp/Bake path: {}".format(unreal_path))

    # -- Flags --------------------------------------------------------------
    check("generated_owned_true", descriptor.get("generated_owned") is True,
          "generated_owned={}".format(descriptor.get("generated_owned")))
    check("not_temporary", descriptor.get("temporary") is False,
          "temporary={}".format(descriptor.get("temporary")))

    # -- PCG eligibility + desert compatibility (machine-readable) ----------
    check("pcg_allowed_true", descriptor.get("pcg_allowed") is True,
          "pcg_allowed={}".format(descriptor.get("pcg_allowed")))
    check("desert_compatible", "desert" in (descriptor.get("biome") or []),
          "biome={}".format(descriptor.get("biome")))
    in_catalog = _catalog_has(descriptor.get("asset_catalog", ""),
                              descriptor.get("placement_category", ""), unreal_path)
    check("catalog_membership", in_catalog,
          "PCG eligibility requires {} listed in {}.{}".format(
              unreal_path, descriptor.get("asset_catalog"), descriptor.get("placement_category")))

    # -- Provenance ---------------------------------------------------------
    check("provenance_exists", bool(descriptor.get("provenance")),
          "provenance block absent from descriptor")

    # -- UE presence (warn_only until relocate has been run) ----------------
    ue_report = report_dir / "ue_generated_asset_report.json"
    ue_ok = False
    ue_detail = "run 'make relocate-houdini-asset' (UE) to materialize + verify the StaticMesh"
    if ue_report.is_file():
        try:
            ue_rpt = json.loads(ue_report.read_text(encoding="utf-8"))
            ue_ok = bool(ue_rpt.get("passed")) and ue_rpt.get("is_static_mesh") is True
            ue_detail = "ue path={} static_mesh={}".format(
                ue_rpt.get("unreal_path"), ue_rpt.get("is_static_mesh"))
        except Exception:
            ue_ok = False
    check("asset_exists_in_ue_as_static_mesh", ue_ok, ue_detail, warn_only=True)

    # -- Result -------------------------------------------------------------
    result["unreal_path"] = unreal_path
    result["pcg_allowed"] = descriptor.get("pcg_allowed")
    result["biome"] = descriptor.get("biome")
    result["passed"] = len(result["failures"]) == 0
    result["status"] = "ok" if result["passed"] else "fail"
    _write_report(report_dir, result)

    verdict = "PASS" if result["passed"] else "FAIL"
    n_warn = len(result.get("warnings", []))
    print("[validate-generated-asset] {} — {} ({} failure(s), {} warning(s))".format(
        verdict, asset_id, len(result["failures"]), n_warn))
    print("[validate-generated-asset]   path={} pcg_allowed={} biome={}".format(
        unreal_path, descriptor.get("pcg_allowed"), descriptor.get("biome")))
    for f in result["failures"]:
        print("[validate-generated-asset]   FAIL: {}".format(f))
    for w in result.get("warnings", []):
        print("[validate-generated-asset]   WARN: {}".format(w))
    sys.exit(0 if result["passed"] else 1)


def _write_report(report_dir: Path, result: dict):
    rpt_path = report_dir / "validate_generated_asset_report.json"
    with rpt_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("[validate-generated-asset] report -> {}".format(rpt_path.relative_to(REPO_ROOT)))


if __name__ == "__main__":
    main()
