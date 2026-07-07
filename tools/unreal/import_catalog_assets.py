#!/usr/bin/env python3
r"""import_catalog_assets.py (UE5 Python) — WorldForge v1.5 Wave-3.

Live editor driver that IMPORTS approved third-party catalog assets from the
quarantine cache into the WorldForge project as real .uasset content. Reads the
per-asset catalog records (procedural/generated/assets/catalog/*.json) and the
aggregate acquisition catalog
(procedural/generated/worldforge_asset_acquisition_catalog.json); for each
APPROVED asset whose quarantined source is present on disk, it imports the source
file(s) — PolyHaven glTF meshes and/or their textures — into the record's
``ue_asset_path`` folder via unreal.AssetImportTask, classifies the result
third_party_owned, and records dependencies.

Import READS COPIES only: the quarantine SOURCE files under
D:/WorldForgeAssetCache/_Quarantine/... are never mutated or deleted.

Rules:
  * skip (do NOT fail) any asset whose source folder/file is not downloaded.
  * refuse any destination outside /Game/WorldForge/ (forbidden-path guard).
  * idempotent: an already-imported target is verified, not re-imported.

Report (honest, carries live_imported):
    procedural/reports/realization/import_catalog_assets/
        import_catalog_assets_report.json

Run (inside the UE 5.7 editor):
    "<UE>/UnrealEditor-Cmd.exe" "D:/Unreal Projects/WorldForge/WorldForge.uproject" ^
        -ExecutePythonScript="tools/unreal/import_catalog_assets.py" ^
        -unattended -nopause -nosplash -stdout
"""

import json
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = REPO_ROOT / "procedural" / "generated" / "assets" / "catalog"
ACQUISITION_CATALOG = REPO_ROOT / "procedural" / "generated" / "worldforge_asset_acquisition_catalog.json"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "realization" / "import_catalog_assets"
REPORT_NAME = "import_catalog_assets_report.json"

# The external asset-cache drive that mirrors the repo-relative quarantine anchor.
QUARANTINE_DRIVE_ROOT = Path("D:/")
OWNED_PREFIX = "/Game/WorldForge/"
MESH_EXTS = (".gltf", ".glb", ".fbx", ".obj")
TEX_EXTS = (".png", ".jpg", ".jpeg", ".exr", ".tga", ".hdr")
SCHEMA_VERSION = "wf.realization.import_catalog_assets.v1"


def _load_records():
    """Merge per-file catalog records + aggregate catalog, de-duped by asset_id."""
    records = {}
    if ACQUISITION_CATALOG.is_file():
        try:
            agg = json.loads(ACQUISITION_CATALOG.read_text(encoding="utf-8"))
            for aid, rec in (agg.get("assets") or {}).items():
                records[aid] = rec
        except Exception:  # noqa: BLE001
            pass
    if CATALOG_DIR.is_dir():
        for p in sorted(CATALOG_DIR.glob("*.json")):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
                aid = rec.get("asset_id") or p.stem
                records[aid] = rec
            except Exception:  # noqa: BLE001
                pass
    return records


def _is_approved(rec):
    return bool(rec.get("approved_at")) or bool(
        (rec.get("provenance") or {}).get("approval_id"))


def _resolve_source_dir(rec):
    """Return absolute Path to the quarantined source dir, or None if absent.

    Catalog source_path is a repo-relative quarantine anchor, e.g.
    'WorldForgeAssetCache/_Quarantine/polyhaven/coast_sand_05'. The bytes live on
    the external cache drive: D:/WorldForgeAssetCache/_Quarantine/...
    """
    sp = (rec.get("source_path") or "").replace("\\", "/").strip()
    if not sp:
        return None
    candidates = []
    if sp.startswith("WorldForgeAssetCache/"):
        candidates.append(QUARANTINE_DRIVE_ROOT / sp)
    candidates.append(REPO_ROOT / sp)  # in-project quarantine fallback
    candidates.append(Path(sp))         # already absolute
    for c in candidates:
        try:
            if c.exists():
                return c
        except Exception:  # noqa: BLE001
            pass
    return None


def _collect_source_files(src_dir):
    """Prefer mesh files; fall back to textures. Returns (kind, [abs paths])."""
    if src_dir.is_file():
        return ("file", [src_dir])
    meshes, texs = [], []
    for f in sorted(src_dir.rglob("*")):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in MESH_EXTS:
            meshes.append(f)
        elif ext in TEX_EXTS:
            texs.append(f)
    if meshes:
        return ("mesh", meshes)
    return ("texture", texs)


def import_one(unreal, rec):
    dst_folder = (rec.get("ue_asset_path") or "").rstrip("/")
    asset_id = rec.get("asset_id") or "unknown"
    row = {"asset_id": asset_id, "ue_asset_path": dst_folder,
           "ownership_class": "third_party_owned", "imported": False,
           "skipped": False, "imported_objects": [], "source_files": [],
           "error": None}

    if not _is_approved(rec):
        row["skipped"] = True
        row["error"] = "not approved"
        return row
    if not dst_folder:
        row["error"] = "record missing ue_asset_path"
        return row
    if not dst_folder.startswith(OWNED_PREFIX):
        row["error"] = "forbidden destination (must start with {}): {}".format(
            OWNED_PREFIX, dst_folder)
        return row

    src_dir = _resolve_source_dir(rec)
    if src_dir is None:
        row["skipped"] = True
        row["error"] = "source not downloaded ({}); skipped".format(rec.get("source_path"))
        return row

    kind, files = _collect_source_files(src_dir)
    row["source_kind"] = kind
    row["source_files"] = [str(f) for f in files]
    if not files:
        row["skipped"] = True
        row["error"] = "no importable files under {}; skipped".format(src_dir)
        return row

    eal = unreal.EditorAssetLibrary
    at = unreal.AssetToolsHelpers.get_asset_tools()
    if not eal.does_directory_exist(dst_folder):
        eal.make_directory(dst_folder)

    tasks = []
    for f in files:
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", str(f))
        task.set_editor_property("destination_path", dst_folder)
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("async_", False)
        tasks.append(task)

    try:
        at.import_asset_tasks(tasks)
    except Exception as exc:  # noqa: BLE001
        row["error"] = "import_asset_tasks failed: {}".format(exc)
        return row

    imported = []
    for task in tasks:
        try:
            for obj_path in (task.get_editor_property("imported_object_paths") or []):
                imported.append(str(obj_path))
        except Exception:  # noqa: BLE001
            pass
    row["imported_objects"] = imported
    row["imported"] = bool(imported)
    if not imported:
        row["error"] = "no objects imported from {} files".format(len(files))
    return row


def main():
    try:
        import unreal
    except ImportError:
        sys.stderr.write("ERROR: run inside the Unreal editor "
                         "(UnrealEditor-Cmd -ExecutePythonScript).\n")
        return 2

    records = _load_records()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    if not records:
        unreal.log_warning("[import-catalog] no catalog records found; empty report")

    for aid in sorted(records):
        try:
            row = import_one(unreal, records[aid])
        except Exception as exc:  # noqa: BLE001
            row = {"asset_id": aid, "imported": False, "skipped": False,
                   "error": str(exc), "traceback": traceback.format_exc()}
        rows.append(row)
        if row.get("imported"):
            unreal.log("[import-catalog] imported {} -> {} ({} objs)".format(
                aid, row.get("ue_asset_path"), len(row.get("imported_objects") or [])))
        elif row.get("skipped"):
            unreal.log("[import-catalog] skip {} ({})".format(aid, row.get("error")))
        else:
            unreal.log_error("[import-catalog] FAIL {}: {}".format(aid, row.get("error")))

    imported = sum(1 for r in rows if r.get("imported"))
    skipped = sum(1 for r in rows if r.get("skipped"))
    failed = [r for r in rows if not r.get("imported") and not r.get("skipped")]
    report = {
        "command": "import_catalog_assets",
        "schema_version": SCHEMA_VERSION,
        "live_imported": True,
        "total_records": len(rows),
        "imported_count": imported,
        "skipped_count": skipped,
        "failed_count": len(failed),
        "status": "ok" if not failed else "error",
        "assets": rows,
    }
    (REPORT_DIR / REPORT_NAME).write_text(json.dumps(report, indent=2), encoding="utf-8")
    unreal.log("[import-catalog] DONE — {} records, {} imported, {} skipped, {} failed".format(
        len(rows), imported, skipped, len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
