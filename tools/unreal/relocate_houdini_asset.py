r"""
relocate_houdini_asset.py (UE5 Python)

Houdini asset-intake bridge — materializes ONE WorldForge-owned generated
StaticMesh by duplicating a baked Houdini asset out of /Game/HoudiniEngine/Bake
(or Temp) into the WorldForge-owned tree, then asserts the result is a
StaticMesh. This is the narrow asset-intake sidecar — NOT MeshForge.

Reads the descriptor JSON written by register_generated_asset.py (JSON only —
UE scripts must not use PyYAML) for source_bake_path -> unreal_path.

Refuses to write into a forbidden Houdini Temp/Bake destination (Risk 2).

Writes a UE report consumed by validate_generated_asset.py:
    procedural/reports/generated_assets/<asset_id>/ue_generated_asset_report.json

Usage (inside UE editor python / headless):
    py tools/unreal/relocate_houdini_asset.py \
        --descriptor procedural/generated/generated_assets/rock_generator_desert_01/descriptor.json \
        --project-root .
"""

import argparse
import json
import os
import sys

import unreal

FORBIDDEN_PREFIXES = ("/Game/HoudiniEngine/Temp", "/Game/HoudiniEngine/Bake")


def _is_forbidden(path):
    p = (path or "").rstrip("/")
    return any(p == pre or p.startswith(pre + "/") for pre in FORBIDDEN_PREFIXES)


def main():
    ap = argparse.ArgumentParser(description="Relocate a baked Houdini asset into WorldForge ownership.")
    ap.add_argument("--descriptor", required=True, help="Path to generated-asset descriptor.json")
    ap.add_argument("--project-root", default=".", help="Repo root (for report output)")
    args = ap.parse_args()

    repo_root = os.path.abspath(args.project_root)
    desc_path = args.descriptor
    if not os.path.isabs(desc_path):
        desc_path = os.path.join(repo_root, desc_path)

    with open(desc_path, "r", encoding="utf-8") as fh:
        descriptor = json.load(fh)

    asset_id = descriptor.get("asset_id", "unknown")
    src = descriptor.get("source_bake_path", "")
    dst = descriptor.get("unreal_path", "")

    report = {
        "asset_id": asset_id,
        "source_bake_path": src,
        "unreal_path": dst,
        "checks": {},
        "passed": False,
        "is_static_mesh": False,
    }

    def fail(msg):
        report["error"] = msg
        unreal.log_error("[relocate-houdini-asset] {}".format(msg))
        _write_report(repo_root, asset_id, report)
        sys.exit(1)

    if _is_forbidden(dst):
        fail("destination is a forbidden Houdini Temp/Bake path: {}".format(dst))
    if not dst.startswith("/Game/WorldForge/Generated/"):
        fail("destination must be WorldForge-owned (/Game/WorldForge/Generated/...): {}".format(dst))

    eal = unreal.EditorAssetLibrary

    if eal.does_asset_exist(dst):
        report["checks"]["already_present"] = True
        unreal.log("[relocate-houdini-asset] destination already exists: {}".format(dst))
    else:
        if not src or not eal.does_asset_exist(src):
            fail("source bake asset not found: {}".format(src))
        dst_dir = dst.rsplit("/", 1)[0]
        if not eal.does_directory_exist(dst_dir):
            eal.make_directory(dst_dir)
        if not eal.duplicate_asset(src, dst):
            fail("duplicate_asset failed: {} -> {}".format(src, dst))
        eal.save_asset(dst)
        report["checks"]["duplicated"] = True
        unreal.log("[relocate-houdini-asset] {} -> {}".format(src, dst))

    obj = unreal.load_asset(dst)
    is_sm = bool(obj) and isinstance(obj, unreal.StaticMesh)
    report["is_static_mesh"] = is_sm
    report["checks"]["is_static_mesh"] = is_sm
    if not is_sm:
        fail("relocated asset is not a StaticMesh: {}".format(dst))

    report["passed"] = True
    _write_report(repo_root, asset_id, report)
    unreal.log("[relocate-houdini-asset] PASS — {} is a StaticMesh at {}".format(asset_id, dst))


def _write_report(repo_root, asset_id, report):
    out_dir = os.path.join(repo_root, "procedural", "reports", "generated_assets", asset_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "ue_generated_asset_report.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    unreal.log("[relocate-houdini-asset] report -> {}".format(out_path))


if __name__ == "__main__":
    main()
