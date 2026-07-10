#!/usr/bin/env python3
r"""package_slice.py — v2.0 Wave P: build + package the vertical slice artifact.

Drives UE's RunUAT BuildCookRun to cook the 12 slice maps and produce a staged,
archived Windows build of the WorldForge game target, then writes a
SlicePackageReport pointing at the real artifact (validated against
slice_contracts.validate_slice_package_report BEFORE writing, so a report can
never claim a package that is not on disk).

Per repo policy (brief §12) the bulky build output under Build/ is NOT committed;
only the SlicePackageReport (with package_path, size, and git_sha == HEAD) is
committed as the inspectable proof.

Usage:
    # from PowerShell (spaced path); git must be on PATH for a real git_sha
    python tools/pipeline/package_slice.py --pack encounter_loop_world
    python tools/pipeline/package_slice.py --skip-build   # (re)write report from an
                                                          # existing archived build
Reports -> procedural/reports/slice/package/slice_package_<slice_id>.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
from report_meta import git_sha
import os

SLICE_ID = "worldforge_vertical_slice"
BUILD_TARGET = "WorldForgeVerticalSlice"
ARCHIVE_DIR = REPO_ROOT / "Build" / BUILD_TARGET
PACKAGE_REPORT_DIR = REPO_ROOT / SX.SLICE_PACKAGE_REPORTS_REL

UE_ROOT = os.environ.get("WF_UE_ROOT", "C:/Program Files/Epic Games/UE_5.7")
RUNUAT = "{}/Engine/Build/BatchFiles/RunUAT.bat".format(UE_ROOT)
UPROJECT = str(REPO_ROOT / "WorldForge.uproject").replace("\\", "/")


def _slice_maps():
    m = json.loads((REPO_ROOT / SX.SLICE_MANIFEST_REL).read_text(encoding="utf-8"))
    return sorted(m.get("maps", []))


def run_uat(maps, config="Development", timeout=3600):
    map_arg = "+".join(maps)
    cmd = [
        RUNUAT, "BuildCookRun",
        "-project={}".format(UPROJECT),
        "-noP4", "-nocompileeditor", "-utf8output", "-unattended",
        "-platform=Win64", "-clientconfig={}".format(config),
        "-cook", "-build", "-stage", "-pak", "-archive",
        "-archivedirectory={}".format(str(ARCHIVE_DIR).replace("\\", "/")),
        "-Map={}".format(map_arg),
    ]
    print("[package] RunUAT BuildCookRun over {} maps -> {}".format(len(maps), ARCHIVE_DIR))
    log = REPO_ROOT / "scratchpad" / "wave_p_package.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8", errors="ignore") as fh:
        p = subprocess.run(cmd, cwd=str(REPO_ROOT), stdout=fh,
                           stderr=subprocess.STDOUT, timeout=timeout)
    print("[package] UAT rc={} (log: scratchpad/wave_p_package.log)".format(p.returncode))
    return p.returncode


def find_exe():
    """Locate the archived game .exe under the archive dir (Windows/ staged)."""
    if not ARCHIVE_DIR.is_dir():
        return None
    cands = [p for p in ARCHIVE_DIR.rglob("*.exe")
             if "WorldForge" in p.name and "Editor" not in p.name]
    cands.sort(key=lambda p: p.stat().st_size, reverse=True)
    return cands[0] if cands else None


def _cooked_asset_count():
    staged = list(ARCHIVE_DIR.rglob("*.pak")) if ARCHIVE_DIR.is_dir() else []
    return ["{} ({} bytes)".format(p.name, p.stat().st_size) for p in staged]


def write_report(maps):
    exe = find_exe()
    exists = exe is not None and exe.is_file()
    size = exe.stat().st_size if exists else 0
    rel = str(exe.relative_to(REPO_ROOT)).replace("\\", "/") if exists else ""
    assets = _cooked_asset_count()
    entrypoint = maps[0] if maps else ""
    doc = {
        "package_report_id": "slice_package_{}".format(SLICE_ID),
        "slice_id": SLICE_ID,
        "pack_id": "encounter_loop_world",
        "build_target": BUILD_TARGET,
        "package_path": rel or "Build/{}/Windows/WorldForge.exe".format(BUILD_TARGET),
        "package_exists": exists,
        "package_size_bytes": size,
        "build_config": "Development",
        "maps_included": list(maps),
        "assets_included": assets,
        "runtime_entrypoint": entrypoint,
        "created_at": "live",
        "git_sha": git_sha(),
        "failure_codes": [] if (exists and size > 0) else ["WF675_SLICE_PACKAGE_MISSING"],
        "schema_version": SX.RT_SLICE_PACKAGE_REPORT,
        "report_type": SX.RT_SLICE_PACKAGE_REPORT,
    }
    fails = [c for c in SX.validate_slice_package_report(doc, strict=True) if not c[1]]
    if fails:
        print("[package] report failed schema (not writing): {}".format([c[0] for c in fails][:5]))
        return 1, doc
    PACKAGE_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = PACKAGE_REPORT_DIR / "slice_package_{}.json".format(SLICE_ID)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("[package] {} — exists={} size={} -> {}".format(
        "OK" if exists else "PACKAGE MISSING", exists, size, out.name))
    return (0 if exists and size > 0 else 1), doc


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 Wave P — build + package the slice.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--skip-build", action="store_true",
                    help="skip UAT; just (re)write the report from an existing build")
    ap.add_argument("--config", default="Development")
    ap.add_argument("--timeout", type=int, default=3600)
    args, _ = ap.parse_known_args(argv)

    maps = _slice_maps()
    if not args.skip_build:
        rc = run_uat(maps, config=args.config, timeout=args.timeout)
        if rc != 0:
            print("[package] UAT failed rc={} — writing package-missing report".format(rc))
    code, _ = write_report(maps)
    sys.exit(code)


if __name__ == "__main__":
    main()
