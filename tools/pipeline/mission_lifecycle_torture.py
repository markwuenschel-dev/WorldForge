#!/usr/bin/env python3
"""mission_lifecycle_torture.py — WorldForge v1.3 MissionForge lifecycle torture (Agent 7).

Proves the GENERATED mission catalog + its 60 composed mission loops + their
per-mission playtest reports survive the full hostile lifecycle

    corrupt -> detect -> repair -> destroy -> rebuild -> revalidate

on a GENERATED-OWNED scope only. Mirrors mesh_lifecycle_torture.py in shape and
reporting, adapted to the v1.3 mission layer (missions + catalog + PlaytestForge
reports).

Phases:

  1. BASELINE — deterministic full regen (create_mission_loops + run_playtest_forge),
     then confirm the catalog holds exactly 60 missions, all mission/playtest
     validators are green, and PlaytestForge completes 60/60.

  2. CORRUPTION -> DETECT -> REPAIR — for each mode: apply ONE corruption, assert the
     OWNING detector FLAGS it (a validator exits non-zero, or the on-disk orphan is
     found), then "repair" by a full regen and confirm the detector goes green again:
       * delete one mission's mission.json     -> validate_mission_contract (loads FAIL)
       * delete one catalog record (orphan)    -> harness orphan scan (disk vs catalog)
       * zero all state deltas in one mission   -> validate_mission_state (no world change)
       * break one route (avoids_hazards False) -> validate_mission_routes
       * delete one playtest report             -> validate_playtest_reports (missing)
     A corruption that goes UNDETECTED is a CORRUPTION_UNDETECTED failure.

  3. DESTROY — back up then remove every generated-owned mission descriptor + catalog
     record (scoped to the generated tree), then confirm the catalog is empty and the
     validators report zero missions (error / non-zero exit).

  4. REBUILD / REVALIDATE — full regen; confirm 60 missions, all validators green, and
     60/60 playtest completion.

A master snapshot of the catalog bytes + the generated missions tree + the playtest
reports tree is taken up front and restored in a finally, so the working tree is left
byte-identical to its pre-torture state even if a phase raises mid-run.

  5. POST-RESTORE — after the finally restore, re-run the validators + PlaytestForge so
     the on-disk reports reflect the healed 60-mission state and prove the final state
     is fully restored (60 missions, all validators green, 60/60 playtest).

Report: procedural/reports/missions/mission_lifecycle_torture/mission_lifecycle_torture_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/mission_lifecycle_torture.py --pack mission_loop_world --strict
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "tools" / "pipeline"
sys.path.insert(0, str(PIPELINE))

import mission_contract as MC  # noqa: E402
import playtest_contract as PC  # noqa: E402
from mission_catalog import (  # noqa: E402
    catalog_path, load_mission_catalog, remove_mission, save_mission_catalog,
)
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

PY = sys.executable
LIF = FailureCode.LIFECYCLE_FAILURE
EXPECTED_MISSION_COUNT = 60

# The v1.3 mission + playtest validator suite (brief: the "green" gate).
ALL_VALIDATORS = (
    "validate_mission_contract.py",
    "validate_mission_graph.py",
    "validate_mission_objectives.py",
    "validate_mission_placement.py",
    "validate_mission_biome_compatibility.py",
    "validate_mission_routes.py",
    "validate_mission_state.py",
    "validate_mission_save_load.py",
    "validate_mission_rewards.py",
    "validate_mission_dependencies.py",
    "validate_mission_mesh_usage.py",
    "validate_mission_entity_anchors.py",
    "validate_playtest_contract.py",
    "validate_playtest_reports.py",
)


# =============================================================================
# subprocess + snapshot helpers (mirrors mesh_lifecycle_torture.py)
# =============================================================================
def _run(script, extra, strict):
    path = PIPELINE / script
    if not path.is_file():
        return None, "script missing: {}".format(script)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if strict:
        env["STRICT"] = "1"
    proc = subprocess.run([PY, str(path)] + extra, cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True)
    tail = " | ".join((proc.stdout or "").strip().splitlines()[-1:])[:200]
    return proc.returncode, tail


def _strict_args(strict):
    return ["--strict"] if strict else []


def _regen(pack, strict):
    """Deterministic full regen: regenerate all 60 missions + all playtest reports.

    create_mission_loops rewrites every mission.json (and re-upserts the catalog),
    so run_playtest_forge MUST follow to re-emit non-stale playtest reports. This is
    the canonical repair / rebuild for the mission layer.
    """
    rc1, t1 = _run("create_mission_loops.py", ["--pack", pack] + _strict_args(strict), strict)
    rc2, t2 = _run("run_playtest_forge.py", ["--pack", pack] + _strict_args(strict), strict)
    ok = (rc1 == 0) and (rc2 == 0)
    return ok, "create rc={} ({}); playtest rc={} ({})".format(rc1, t1, rc2, t2)


def _validator_green(script, pack, strict):
    rc, tail = _run(script, ["--pack", pack] + _strict_args(strict), strict)
    return (rc == 0), rc, tail


def _snapshot_tree(paths, dest):
    dest = Path(dest)
    mapping = []
    for p in paths:
        p = Path(p)
        rel = p.relative_to(REPO_ROOT)
        target = dest / rel
        if p.is_dir():
            shutil.copytree(str(p), str(target), dirs_exist_ok=True)
        elif p.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(p), str(target))
        mapping.append((p, target, p.is_dir()))
    return mapping


def _restore_tree(mapping):
    for live, snap, is_dir in mapping:
        if is_dir:
            live_files = {q.relative_to(live) for q in live.rglob("*") if q.is_file()} if live.is_dir() else set()
            snap_files = {q.relative_to(snap) for q in snap.rglob("*") if q.is_file()} if snap.is_dir() else set()
            for extra in live_files - snap_files:
                try:
                    (live / extra).unlink()
                except OSError:
                    pass
            # prune now-empty orphan dirs (e.g. a mission dir that did not exist in snap)
            for rel in live_files - snap_files:
                d = (live / rel).parent
                try:
                    if d.is_dir() and not any(d.iterdir()):
                        d.rmdir()
                except OSError:
                    pass
            for rel in snap_files:
                dst = live / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(snap / rel), str(dst))
        else:
            if snap.is_file():
                live.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(snap), str(live))


def _master_snapshot_paths():
    return [
        catalog_path(REPO_ROOT),
        REPO_ROOT / MC.MISSION_GENERATED_REL,
        REPO_ROOT / PC.PLAYTEST_REPORTS_REL,
    ]


# =============================================================================
# small catalog / mission helpers
# =============================================================================
def _catalog_mission_ids():
    return sorted((load_mission_catalog(REPO_ROOT).get("missions") or {}).keys())


def _disk_mission_ids():
    """Mission ids materialized on disk (a <id>/mission.json under the generated tree)."""
    root = REPO_ROOT / MC.MISSION_GENERATED_REL
    ids = []
    for f in glob.glob(str(root / "*" / "mission.json")):
        ids.append(Path(f).parent.name)
    return sorted(ids)


def _write_mission(mid, mission):
    p = MC.mission_path(mid, REPO_ROOT)
    p.write_text(json.dumps(mission, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _playtest_completion():
    """(completed, total) read from the run_playtest_forge report, or (None, None)."""
    rp = REPO_ROOT / MC.MISSION_REPORTS_REL / "run_playtest_forge" / "run_playtest_forge_report.json"
    if not rp.is_file():
        return None, None
    try:
        meta = (json.loads(rp.read_text(encoding="utf-8")).get("meta") or {})
        return meta.get("missions_completed"), meta.get("missions_total")
    except Exception:  # noqa: BLE001
        return None, None


# =============================================================================
# corruption modes — each: apply(pack, strict) -> detail ; detect(pack, strict) -> (bool, detail)
# `detect` returns (True, ..) when the corruption is FLAGGED (validator non-zero /
# orphan found), so after a repair the same detect must return (False, ..) = green.
# =============================================================================
def _apply_delete_mission_json(pack, strict):
    target = _catalog_mission_ids()[0]
    MC.mission_path(target, REPO_ROOT).unlink()
    return "deleted mission.json for {}".format(target)


def _detect_via_validator(script):
    def _detect(pack, strict):
        rc, tail = _run(script, ["--pack", pack] + _strict_args(strict), strict)
        return (rc != 0), "{} rc={} ({})".format(script, rc, tail)
    return _detect


def _apply_delete_catalog_record(pack, strict):
    target = _catalog_mission_ids()[0]
    catalog = load_mission_catalog(REPO_ROOT)
    catalog = remove_mission(catalog, target)
    save_mission_catalog(REPO_ROOT, catalog)
    return "removed catalog record for {} (orphan mission.json left on disk)".format(target)


def _detect_orphan(pack, strict):
    """No v1.3 validator scans the disk for orphans, so the torture owns this check:
    a mission.json on disk with no catalog record, and a catalog below the baseline."""
    cat = set(_catalog_mission_ids())
    disk = set(_disk_mission_ids())
    orphans = sorted(disk - cat)
    detected = bool(orphans) and len(cat) < EXPECTED_MISSION_COUNT
    return detected, "orphans_on_disk={} catalog_count={}".format(orphans, len(cat))


def _apply_zero_state_deltas(pack, strict):
    target = _catalog_mission_ids()[0]
    m, _ = MC.load_mission(target, REPO_ROOT)
    for s in (m.get("state_keys") or []):
        if isinstance(s, dict):
            s["delta"] = 0
            s["expected_final"] = s.get("initial")   # keep final honest -> isolate "no change"
    _write_mission(target, m)
    return "zeroed all state deltas for {} (mission changes no world state)".format(target)


def _apply_break_route(pack, strict):
    target = _catalog_mission_ids()[0]
    m, _ = MC.load_mission(target, REPO_ROOT)
    route = m.get("required_route") or {}
    route["avoids_hazards"] = False           # route no longer claims a verified safe path
    m["required_route"] = route
    _write_mission(target, m)
    return "set required_route.avoids_hazards=False for {}".format(target)


def _apply_delete_playtest_report(pack, strict):
    target = _catalog_mission_ids()[0]
    rp = REPO_ROOT / PC.PLAYTEST_REPORTS_REL / "{}.json".format(target)
    if rp.is_file():
        rp.unlink()
    return "deleted playtest report for {}".format(target)


# ordered (brief order); each mode fully self-heals via _regen on repair.
CORRUPTION_MODES = (
    ("delete_mission_json", _apply_delete_mission_json,
     _detect_via_validator("validate_mission_contract.py")),
    ("delete_catalog_record", _apply_delete_catalog_record, _detect_orphan),
    ("zero_state_deltas", _apply_zero_state_deltas,
     _detect_via_validator("validate_mission_state.py")),
    ("break_route", _apply_break_route,
     _detect_via_validator("validate_mission_routes.py")),
    ("delete_playtest_report", _apply_delete_playtest_report,
     _detect_via_validator("validate_playtest_reports.py")),
)


# =============================================================================
# phases
# =============================================================================
def _assert_green_suite(rep, prefix, pack, strict):
    for script in ALL_VALIDATORS:
        ok, rc, tail = _validator_green(script, pack, strict)
        rep.check("{}::{}".format(prefix, script.replace(".py", "")), ok,
                  "{} rc={} ({})".format(script, rc, tail), code=LIF)


def _assert_playtest_full(rep, prefix):
    done, total = _playtest_completion()
    rep.check("{}::playtest_60_of_60".format(prefix),
              done == EXPECTED_MISSION_COUNT and total == EXPECTED_MISSION_COUNT,
              "playtest completion {}/{} (expected {}/{})".format(
                  done, total, EXPECTED_MISSION_COUNT, EXPECTED_MISSION_COUNT), code=LIF)


def baseline_phase(rep, pack, strict):
    ok, detail = _regen(pack, strict)
    rep.check("baseline::regen", ok, detail, code=LIF)
    n = len(_catalog_mission_ids())
    rep.check("baseline::mission_count", n == EXPECTED_MISSION_COUNT,
              "catalog has {} missions (expected {})".format(n, EXPECTED_MISSION_COUNT), code=LIF)
    _assert_green_suite(rep, "baseline", pack, strict)
    _assert_playtest_full(rep, "baseline")


def corruption_phase(rep, pack, strict):
    for name, apply_fn, detect_fn in CORRUPTION_MODES:
        try:
            detail = apply_fn(pack, strict)

            # -- detect: the owning detector must FLAG the corruption ----------
            detected, ddetail = detect_fn(pack, strict)
            rep.check("mode::{}::detected".format(name), detected,
                      "corruption {}: {} -> {}".format(
                          "DETECTED" if detected else "UNDETECTED", detail, ddetail),
                      code=FailureCode.CORRUPTION_UNDETECTED if not detected else LIF)

            # -- repair: full regen (create_mission_loops + run_playtest_forge) -
            ok, rdetail = _regen(pack, strict)
            still, sdetail = detect_fn(pack, strict)
            repaired = ok and not still
            rep.check("mode::{}::repaired".format(name), repaired,
                      "repair regen ok={} ({}); post-repair still-flagged={} ({})".format(
                          ok, rdetail, still, sdetail), code=LIF)
        except Exception as exc:  # noqa: BLE001
            rep.check("mode::{}::ran".format(name), False,
                      "corruption harness raised: {}".format(exc), code=LIF)
            _regen(pack, strict)   # best-effort re-heal so later modes start clean


def destroy_phase(rep, pack, strict, backup_dir):
    """Scoped destroy: back up then remove every generated-owned mission + catalog record."""
    ids = _catalog_mission_ids()
    catalog = load_mission_catalog(REPO_ROOT)
    missions = catalog.get("missions") or {}
    removed = 0
    refused = []
    for mid in ids:
        m, _ = MC.load_mission(mid, REPO_ROOT)
        entry = missions.get(mid) or {}
        owned = (m or {}).get("ownership_class") == "generated_owned"
        if not owned:
            refused.append(mid)   # guard: never destroy a non-generated mission
            continue
        mdir = MC.mission_path(mid, REPO_ROOT).parent
        if mdir.is_dir():
            shutil.copytree(str(mdir), str(Path(backup_dir) / mid), dirs_exist_ok=True)
            shutil.rmtree(str(mdir), ignore_errors=True)
        catalog = remove_mission(catalog, mid)
        removed += 1
    save_mission_catalog(REPO_ROOT, catalog)

    rep.check("destroy::none_refused", not refused,
              "destroy refused generated-owned missions (guard misfire): {}".format(refused),
              code=LIF)
    rep.check("destroy::all_removed", removed == EXPECTED_MISSION_COUNT,
              "removed {} generated-owned missions (expected {})".format(removed, EXPECTED_MISSION_COUNT),
              code=LIF)
    remaining = len(_catalog_mission_ids())
    rep.check("destroy::catalog_empty", remaining == 0,
              "catalog holds {} record(s) after destroy (expected 0)".format(remaining), code=LIF)
    # With an empty catalog the validators must REFUSE to fake-green (non-zero exit).
    rc, tail = _run("validate_mission_contract.py", ["--pack", pack] + _strict_args(strict), strict)
    rep.check("destroy::validators_report_zero", rc != 0,
              "validate_mission_contract rc={} on empty catalog (expected non-zero) ({})".format(rc, tail),
              code=LIF)


def rebuild_phase(rep, pack, strict):
    ok, detail = _regen(pack, strict)
    rep.check("rebuild::regen", ok, detail, code=LIF)
    n = len(_catalog_mission_ids())
    rep.check("rebuild::mission_count", n == EXPECTED_MISSION_COUNT,
              "catalog has {} missions (expected {})".format(n, EXPECTED_MISSION_COUNT), code=LIF)
    _assert_green_suite(rep, "rebuild", pack, strict)
    _assert_playtest_full(rep, "rebuild")


# =============================================================================
# main
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.3 MissionForge lifecycle torture / regression gate.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)

    master_dir = tempfile.mkdtemp(prefix="wf_mission_torture_master_")
    destroy_backup = tempfile.mkdtemp(prefix="wf_mission_torture_destroy_")
    mapping = _snapshot_tree(_master_snapshot_paths(), master_dir)
    try:
        print("[mission-lifecycle-torture] BASELINE")
        baseline_phase(rep, args.pack, strict)
        print("[mission-lifecycle-torture] CORRUPTION ({} modes)".format(len(CORRUPTION_MODES)))
        corruption_phase(rep, args.pack, strict)
        print("[mission-lifecycle-torture] DESTROY")
        destroy_phase(rep, args.pack, strict, destroy_backup)
        print("[mission-lifecycle-torture] REBUILD / REVALIDATE")
        rebuild_phase(rep, args.pack, strict)
    finally:
        _restore_tree(mapping)
        shutil.rmtree(master_dir, ignore_errors=True)
        shutil.rmtree(destroy_backup, ignore_errors=True)

    # -- POST-RESTORE: re-run the suite + PlaytestForge so on-disk reports reflect
    # the healed state, and prove the final state is fully restored.
    print("[mission-lifecycle-torture] POST-RESTORE")
    final_n = len(_catalog_mission_ids())
    rep.check("final::catalog_restored", final_n == EXPECTED_MISSION_COUNT,
              "post-restore catalog has {} missions (expected {})".format(final_n, EXPECTED_MISSION_COUNT),
              code=LIF)
    pt_ok, pt_tail = _run("run_playtest_forge.py", ["--pack", args.pack] + _strict_args(strict), strict)
    rep.check("final::playtest_exit_ok", pt_ok == 0,
              "post-restore run_playtest_forge rc={} ({})".format(pt_ok, pt_tail), code=LIF)
    _assert_playtest_full(rep, "final")
    _assert_green_suite(rep, "final", args.pack, strict)

    rep.finalize()
    done, total = _playtest_completion()
    rep.set_meta(build_meta(command="mission-lifecycle-torture", pack=args.pack, strict=strict,
                            torture=True, status=rep.status, record_count=len(CORRUPTION_MODES),
                            extra={"corruption_modes": [m[0] for m in CORRUPTION_MODES],
                                   "expected_mission_count": EXPECTED_MISSION_COUNT,
                                   "final_mission_count": len(_catalog_mission_ids()),
                                   "final_playtest_completed": done,
                                   "final_playtest_total": total,
                                   "validators": [s.replace(".py", "") for s in ALL_VALIDATORS]}))
    report_dir = REPO_ROOT / MC.MISSION_REPORTS_REL / "mission_lifecycle_torture"
    rep.write(report_dir, "mission_lifecycle_torture_report.json")
    rep.print_summary("mission-lifecycle-torture")
    print("[mission-lifecycle-torture] corrupt->detect->repair->destroy->rebuild->revalidate "
          "cycle run ({} corruption modes); final {}/{} playtest, catalog={}".format(
              len(CORRUPTION_MODES), done, total, len(_catalog_mission_ids())))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
