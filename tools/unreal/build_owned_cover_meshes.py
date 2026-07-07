#!/usr/bin/env python3
r"""build_owned_cover_meshes.py (UE5 Python) — WorldForge v1.5 Wave-3.

Live editor driver that MATERIALIZES the generated-owned baseline cover meshes.
For every owned-cover spec written headlessly by the realization resolver
(procedural/generated/realization/owned_cover_meshes/*.json) this creates a real
StaticMesh asset at the spec's ``final_asset_path`` by duplicating the engine
BasicShapes/Cube (a credible, collidable box cover proxy) into the WorldForge-
owned tree. The duplicated mesh keeps the cube's simple box collision so it
BlockAll-blocks; the actual footprint/height is applied per-anchor at placement
time by replace_cover_proxies_ue.py (cube = 100uu, scaled by bounds/height).

These baseline meshes are the HYBRID-RULE safety net: replace_cover_proxies_ue.py
falls back to them whenever a binding's resolved catalog asset is missing, so no
encounter is ever left showing a raw cube where a baseline exists.

Guards:
  * refuses any final path outside /Game/WorldForge/Generated/ (forbidden-path).
  * asserts the created/exists asset IS a unreal.StaticMesh.
  * idempotent: an already-present owned mesh is verified, not re-created.

Report (honest, carries live_built):
    procedural/reports/realization/build_owned_cover_meshes/
        build_owned_cover_meshes_report.json

Run (inside the UE 5.7 editor):
    "<UE>/UnrealEditor-Cmd.exe" "D:/Unreal Projects/WorldForge/WorldForge.uproject" ^
        -ExecutePythonScript="tools/unreal/build_owned_cover_meshes.py" ^
        -unattended -nopause -nosplash -stdout
"""

import json
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = REPO_ROOT / "procedural" / "generated" / "realization" / "owned_cover_meshes"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "realization" / "build_owned_cover_meshes"
REPORT_NAME = "build_owned_cover_meshes_report.json"

SOURCE_CUBE = "/Engine/BasicShapes/Cube"
OWNED_PREFIX = "/Game/WorldForge/Generated/"
SCHEMA_VERSION = "wf.realization.build_owned_cover_meshes.v1"


def _load_specs():
    """Return list of (spec_path, spec_dict); tolerate an empty/absent dir."""
    if not SPEC_DIR.is_dir():
        return []
    specs = []
    for p in sorted(SPEC_DIR.glob("*.json")):
        try:
            specs.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except Exception as exc:  # noqa: BLE001
            specs.append((p, {"_parse_error": str(exc)}))
    return specs


def _is_forbidden(path):
    return not (path or "").startswith(OWNED_PREFIX)


def build_one(unreal, spec):
    """Create/verify one owned-cover StaticMesh. Returns a report row dict."""
    dst = spec.get("final_asset_path") or ""
    asset_id = spec.get("asset_id") or spec.get("cover_mesh_id") or Path(dst).name or "unknown"
    row = {"asset_id": asset_id, "final_asset_path": dst,
           "height_class": spec.get("height_class"),
           "collision_profile": spec.get("collision_profile", "BlockAll"),
           "created": False, "already_present": False,
           "is_static_mesh": False, "ownership_class": "generated_owned",
           "error": None}

    if spec.get("_parse_error"):
        row["error"] = "spec parse error: {}".format(spec["_parse_error"])
        return row
    if not dst:
        row["error"] = "spec missing final_asset_path"
        return row
    if _is_forbidden(dst):
        row["error"] = "forbidden final path (must start with {}): {}".format(OWNED_PREFIX, dst)
        return row

    eal = unreal.EditorAssetLibrary
    try:
        if eal.does_asset_exist(dst):
            row["already_present"] = True
        else:
            if not eal.does_asset_exist(SOURCE_CUBE):
                row["error"] = "source cube missing: {}".format(SOURCE_CUBE)
                return row
            dst_dir = dst.rsplit("/", 1)[0]
            if not eal.does_directory_exist(dst_dir):
                eal.make_directory(dst_dir)
            if not eal.duplicate_asset(SOURCE_CUBE, dst):
                row["error"] = "duplicate_asset failed: {} -> {}".format(SOURCE_CUBE, dst)
                return row
            eal.save_asset(dst)
            row["created"] = True

        obj = unreal.load_asset(dst)
        is_sm = bool(obj) and isinstance(obj, unreal.StaticMesh)
        row["is_static_mesh"] = is_sm
        if not is_sm:
            row["error"] = "asset is not a StaticMesh: {}".format(dst)
            return row

        # Keep the cube's built-in simple box collision so the baseline BlockAll-
        # blocks. Best-effort ensure simple+complex collision is enabled.
        try:
            bs = obj.get_editor_property("body_setup")
            if bs:
                bs.set_editor_property(
                    "collision_trace_flag",
                    unreal.CollisionTraceFlag.CTF_USE_SIMPLE_AND_COMPLEX)
                eal.save_asset(dst)
        except Exception as exc:  # noqa: BLE001
            row["collision_note"] = "collision_trace_flag warn: {}".format(exc)
    except Exception as exc:  # noqa: BLE001
        row["error"] = str(exc)
    return row


def main():
    try:
        import unreal
    except ImportError:
        sys.stderr.write("ERROR: run inside the Unreal editor "
                         "(UnrealEditor-Cmd -ExecutePythonScript).\n")
        return 2

    specs = _load_specs()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    if not specs:
        unreal.log_warning("[build-owned-cover] no owned-cover specs at {} "
                           "(resolver not run?); writing empty report".format(SPEC_DIR))

    for _p, spec in specs:
        row = build_one(unreal, spec)
        rows.append(row)
        if row["error"]:
            unreal.log_error("[build-owned-cover] FAIL {}: {}".format(
                row["asset_id"], row["error"]))
        else:
            unreal.log("[build-owned-cover] {} -> {} (created={}, present={})".format(
                row["asset_id"], row["final_asset_path"],
                row["created"], row["already_present"]))

    created = sum(1 for r in rows if r["created"])
    present = sum(1 for r in rows if r["already_present"])
    failed = [r for r in rows if r["error"]]
    report = {
        "command": "build_owned_cover_meshes",
        "schema_version": SCHEMA_VERSION,
        "live_built": True,
        "spec_dir": str(SPEC_DIR),
        "total_specs": len(rows),
        "created_count": created,
        "already_present_count": present,
        "failed_count": len(failed),
        "status": "ok" if not failed else "error",
        "assets": rows,
    }
    (REPORT_DIR / REPORT_NAME).write_text(json.dumps(report, indent=2), encoding="utf-8")
    unreal.log("[build-owned-cover] DONE — {} specs, {} created, {} present, {} failed".format(
        len(rows), created, present, len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
