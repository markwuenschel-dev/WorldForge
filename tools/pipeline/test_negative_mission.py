#!/usr/bin/env python3
"""test_negative_mission.py — WorldForge v1.3 MissionForge negative-fixture gate (Agent 6).

Every known-bad mission fixture under tests/fixtures/invalid_missions/ must be
REJECTED by the validator that owns its defect, and every deliberately-doctored
playtest report must be caught by the PlaytestForge report gate. A negative harness
only earns trust if it proves it left NOTHING behind — so after exercising every
case it re-asserts the real mission catalog is byte-for-byte healed (exactly 60
missions, no __negmis_* leakage) and re-runs the full mission+playtest gate green.

Two phases:

  1. MISSION-INJECTION — for every fixture, safely materialize a temp mission.json
     for a unique id (__negmis_<case>), inject a catalog record, run the SPECIFIC
     owning validator as a subprocess, and assert it exits non-zero (the injected
     bad mission makes that lane fail). The real catalog bytes are backed up in
     memory and restored in a finally, and the temp mission tree is deleted, so a
     mid-run failure can never leave the catalog/tree dirty.

  2. PLAYTEST-DOCTORING — for every playtest case, doctor ONE healthy mission's
     per-mission playtest report (temp copy in memory), run
     validate_playtest_reports, and assert it exits non-zero. The original report
     bytes + mtimes are restored in a finally.

After both phases the harness reloads the catalog and proves it self-healed (60
missions, no __negmis_* records/dirs, all mission+playtest validators green, and
run_playtest_forge completes 60/60). A case that is wrongly ACCEPTED is a
MISSION_CONTRACT_FAILURE (or the case's lane code). Exit 0 iff every case was
rejected AND the catalog self-healed. A global finally restores the catalog and
all playtest reports to their exact starting bytes so the run is git-clean.

Report: procedural/reports/missions/test_negative_mission/test_negative_mission_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/test_negative_mission.py --pack mission_loop_world --strict
"""

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "tools" / "pipeline"
sys.path.insert(0, str(PIPELINE))

import mission_contract as MC  # noqa: E402
import playtest_contract as PC  # noqa: E402
from mission_catalog import catalog_path, load_mission_catalog  # noqa: E402
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

PY = sys.executable
FIXTURES_DIR = REPO_ROOT / MC.MISSION_INVALID_FIXTURES_REL
GEN_ROOT = REPO_ROOT / MC.MISSION_GENERATED_REL
PLAYTEST_DIR = REPO_ROOT / PC.PLAYTEST_REPORTS_REL
NEG_CODE = FailureCode.MISSION_CONTRACT_FAILURE
EXPECTED_MISSION_COUNT = 60
TEMP_PREFIX = "__negmis_"

# Each mission fixture -> the SPECIFIC validator that owns its single defect.
MISSION_CASES = {
    "missing_start_anchor": ("validate_mission_graph.py", FailureCode.MISSION_GRAPH_FAILURE),
    "missing_objective_anchor": ("validate_mission_objectives.py", FailureCode.MISSION_OBJECTIVE_FAILURE),
    "objective_unreachable": ("validate_mission_routes.py", FailureCode.MISSION_ROUTE_FAILURE),
    "route_crosses_blocked_terrain": ("validate_mission_placement.py", FailureCode.MISSION_PLACEMENT_FAILURE),
    "incompatible_biome": ("validate_mission_biome_compatibility.py", FailureCode.MISSION_BIOME_COMPATIBILITY_FAILURE),
    "missing_mesh_asset": ("validate_mission_dependencies.py", FailureCode.MISSION_MESH_DEPENDENCY_FAILURE),
    "missing_megascans_reference": ("validate_mission_dependencies.py", FailureCode.MISSION_MESH_DEPENDENCY_FAILURE),
    "entity_anchor_invalid": ("validate_mission_entity_anchors.py", FailureCode.MISSION_GRAPH_FAILURE),
    "completion_never_fires": ("validate_mission_state.py", FailureCode.MISSION_STATE_FAILURE),
    "reward_missing": ("validate_mission_rewards.py", FailureCode.MISSION_REWARD_FAILURE),
    "state_key_missing": ("validate_mission_state.py", FailureCode.MISSION_STATE_FAILURE),
    "save_load_loses_completion": ("validate_mission_save_load.py", FailureCode.MISSION_SAVE_LOAD_FAILURE),
}

# The full mission + playtest validator gate, re-run to prove self-heal.
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
# subprocess helper
# =============================================================================
def _run(script, extra, strict):
    """Run a pipeline script as a subprocess; return (returncode, tail)."""
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


# =============================================================================
# byte snapshots (git-clean insurance)
# =============================================================================
def _snapshot(paths):
    """Return {path: (bytes, atime, mtime)} for existing files."""
    snap = {}
    for p in paths:
        if p.is_file():
            st = p.stat()
            snap[p] = (p.read_bytes(), st.st_atime, st.st_mtime)
    return snap


def _restore(snap):
    for p, (data, at, mt) in snap.items():
        p.write_bytes(data)
        try:
            os.utime(p, (at, mt))
        except OSError:  # pragma: no cover
            pass


def _purge_temp_dirs():
    """Remove any stray __negmis_* mission dirs (defensive)."""
    if GEN_ROOT.is_dir():
        for d in GEN_ROOT.iterdir():
            if d.is_dir() and d.name.startswith(TEMP_PREFIX):
                shutil.rmtree(d, ignore_errors=True)


# =============================================================================
# phase 1 — mission injection
# =============================================================================
def _inject_mission(temp_id, mission):
    """Write a temp mission.json and inject a catalog record. Returns out_dir."""
    out_dir = GEN_ROOT / temp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    m = copy.deepcopy(mission)
    m["mission_id"] = temp_id
    m["mission_path"] = (out_dir / "mission.json").relative_to(REPO_ROOT).as_posix()
    (out_dir / "mission.json").write_text(
        json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    catalog = load_mission_catalog(REPO_ROOT)
    catalog.setdefault("missions", {})[temp_id] = {
        "mission_id": temp_id,
        "mission_archetype": m.get("mission_archetype"),
        "biome_family": m.get("biome_family"),
        "source_map": (m.get("source_map") or {}).get("slice_id"),
        "mission_path": m["mission_path"],
        "validation_status": "pending",
        "lifecycle_status": "created",
    }
    _write_catalog(catalog)
    return out_dir


def _write_catalog(catalog):
    cat_file = catalog_path(REPO_ROOT)
    cat_file.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def mission_injection_phase(rep, pack, strict):
    cat_file = catalog_path(REPO_ROOT)
    for case in sorted(MISSION_CASES):
        script, code = MISSION_CASES[case]
        fx = FIXTURES_DIR / (case + ".json")
        if not fx.is_file():
            rep.check("inject::{}".format(case), False,
                      "fixture missing: {}".format(fx), code=NEG_CODE)
            print("FAIL  MISSING fixture: {}".format(fx.name))
            continue
        try:
            mission = json.loads(fx.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            rep.check("inject::{}".format(case), False,
                      "fixture unparseable: {}".format(exc), code=NEG_CODE)
            continue

        temp_id = TEMP_PREFIX + case
        backup = cat_file.read_bytes() if cat_file.is_file() else None
        out_dir = GEN_ROOT / temp_id
        try:
            out_dir = _inject_mission(temp_id, mission)
            rc, tail = _run(script, ["--pack", pack] + (["--strict"] if strict else []), strict)
            rejected = rc is not None and rc != 0
            rep.check("inject::{}".format(case), rejected,
                      "{} rc={} ({})".format(script, rc, tail), code=code)
            print("{}  inject {} -> {} (rc={})".format(
                "PASS" if rejected else "FAIL  ACCEPTED", case, script, rc))
        finally:
            if backup is not None:
                cat_file.write_bytes(backup)
            shutil.rmtree(out_dir, ignore_errors=True)


# =============================================================================
# phase 2 — playtest report doctoring
# =============================================================================
def _report_path(mid):
    return PLAYTEST_DIR / "{}.json".format(mid)


def _doctor_success_without_completing(report):
    """completed True but a declared mode failed -> contradictory report."""
    report["completed"] = True
    modes = report.setdefault("modes", {})
    key = "graph_playtest" if "graph_playtest" in modes else (sorted(modes)[0] if modes else None)
    if key is not None:
        modes[key] = dict(modes.get(key) or {})
        modes[key]["passed"] = False
    return report, False


def _doctor_skips_required_step(report):
    """Report omits a declared mode -> skips a required step."""
    modes = report.setdefault("modes", {})
    for drop in ("budget_safe_playtest", "save_load_playtest"):
        if drop in modes:
            modes.pop(drop)
            break
    return report, False


def _doctor_partial_marked_success(report):
    """completed True != expected_completion (marked success anyway)."""
    report["completed"] = True
    report["expected_completion"] = False
    return report, False


def _doctor_route_report_stale(report):
    """Content unchanged; the file mtime is set older than mission.json."""
    return report, True  # stale flag handled by caller


PLAYTEST_CASES = {
    "playtest_reports_success_without_completing": (_doctor_success_without_completing, FailureCode.PLAYTEST_REPORT_FAILURE),
    "playtest_skips_required_step": (_doctor_skips_required_step, FailureCode.PLAYTEST_REPORT_FAILURE),
    "partial_mission_success_marked_success": (_doctor_partial_marked_success, FailureCode.PLAYTEST_COMPLETION_FAILURE),
    "playtest_route_report_stale": (_doctor_route_report_stale, FailureCode.PLAYTEST_REPORT_FAILURE),
}


def playtest_doctoring_phase(rep, pack, strict, target_mid):
    rp = _report_path(target_mid)
    mp = MC.mission_path(target_mid)
    if not rp.is_file():
        rep.error("no playtest report for target {} — run run_playtest_forge.py".format(target_mid))
        return
    original = _snapshot([rp])

    for case in sorted(PLAYTEST_CASES):
        doctor, code = PLAYTEST_CASES[case]
        try:
            report = json.loads(rp.read_text(encoding="utf-8"))
            report, make_stale = doctor(copy.deepcopy(report))
            rp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if make_stale and mp.is_file():
                old = mp.stat().st_mtime - 600.0  # 10 min before the mission.json
                os.utime(rp, (old, old))
            rc, tail = _run("validate_playtest_reports.py",
                            ["--pack", pack] + (["--strict"] if strict else []), strict)
            rejected = rc is not None and rc != 0
            rep.check("playtest::{}".format(case), rejected,
                      "validate_playtest_reports rc={} ({})".format(rc, tail), code=code)
            print("{}  playtest {} (rc={})".format(
                "PASS" if rejected else "FAIL  ACCEPTED", case, rc))
        finally:
            _restore(original)


# =============================================================================
# self-heal
# =============================================================================
def selfheal_check(rep, pack, strict):
    catalog = load_mission_catalog(REPO_ROOT)
    missions = catalog.get("missions") or {}
    n = len(missions)
    rep.check("selfheal::mission_count", n == EXPECTED_MISSION_COUNT,
              "catalog has {} missions (expected {})".format(n, EXPECTED_MISSION_COUNT),
              code=FailureCode.MISSION_CONTRACT_FAILURE)

    stray_records = sorted(m for m in missions if m.startswith(TEMP_PREFIX))
    rep.check("selfheal::no_temp_records", not stray_records,
              "stray temp catalog records: {}".format(stray_records),
              code=FailureCode.MISSION_CONTRACT_FAILURE)

    stray_dirs = sorted(
        p.name for p in GEN_ROOT.iterdir()
        if p.is_dir() and p.name.startswith(TEMP_PREFIX)
    ) if GEN_ROOT.is_dir() else []
    rep.check("selfheal::no_temp_dirs", not stray_dirs,
              "stray temp mission dirs: {}".format(stray_dirs),
              code=FailureCode.MISSION_CONTRACT_FAILURE)

    for script in ALL_VALIDATORS:
        rc, tail = _run(script, ["--pack", pack] + (["--strict"] if strict else []), strict)
        rep.check("selfheal::{}".format(script.replace(".py", "")),
                  rc == 0, "{} rc={} ({})".format(script, rc, tail),
                  code=FailureCode.MISSION_CONTRACT_FAILURE)

    rc, tail = _run("run_playtest_forge.py",
                    ["--pack", pack] + (["--strict"] if strict else []), strict)
    rep.check("selfheal::run_playtest_forge", rc == 0,
              "run_playtest_forge rc={} ({})".format(rc, tail),
              code=FailureCode.PLAYTEST_COMPLETION_FAILURE)


# =============================================================================
# main
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.3 MissionForge negative-fixture gate.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)

    # Global byte snapshot: catalog + every playtest report. run_playtest_forge in
    # self-heal regenerates these; restoring the snapshot keeps the run git-clean.
    global_paths = [catalog_path(REPO_ROOT)]
    if PLAYTEST_DIR.is_dir():
        global_paths += sorted(PLAYTEST_DIR.glob("*.json"))
    global_snap = _snapshot(global_paths)

    catalog0 = load_mission_catalog(REPO_ROOT)
    target_mid = sorted((catalog0.get("missions") or {}).keys())
    target_mid = target_mid[0] if target_mid else None

    n_cases = len(MISSION_CASES) + len(PLAYTEST_CASES)
    try:
        if not FIXTURES_DIR.is_dir():
            rep.error("no invalid mission fixtures dir: {}".format(FIXTURES_DIR))
        elif target_mid is None:
            rep.error("no missions in catalog — run create_mission_loops + run_playtest_forge first")
        else:
            print("[mission-negative] MISSION-INJECTION phase ({} fixtures)".format(len(MISSION_CASES)))
            mission_injection_phase(rep, args.pack, strict)
            print("[mission-negative] PLAYTEST-DOCTORING phase ({} cases, target={})".format(
                len(PLAYTEST_CASES), target_mid))
            playtest_doctoring_phase(rep, args.pack, strict, target_mid)
            print("[mission-negative] SELF-HEAL check")
            selfheal_check(rep, args.pack, strict)
    finally:
        _restore(global_snap)
        _purge_temp_dirs()

    rep.finalize()
    rep.set_meta(build_meta(command="mission-negative-validators", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n_cases,
                            extra={"mission_fixtures": sorted(MISSION_CASES),
                                   "playtest_cases": sorted(PLAYTEST_CASES),
                                   "self_heal_target": target_mid}))
    report_dir = REPO_ROOT / MC.MISSION_REPORTS_REL / "test_negative_mission"
    rep.write(report_dir, "test_negative_mission_report.json")
    rep.print_summary("mission-negative")
    print("[mission-negative] {} cases exercised ({} injection + {} playtest)".format(
        n_cases, len(MISSION_CASES), len(PLAYTEST_CASES)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
