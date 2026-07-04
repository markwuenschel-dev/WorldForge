#!/usr/bin/env python3
"""test_negative_encounter.py — WorldForge v1.4 EncounterForge negative-fixture gate (Lane G).

Every known-bad encounter fixture under tests/fixtures/invalid_encounters/ must
be REJECTED by the validator that owns its defect, and every deliberately
doctored beta-playtest / balance artifact must be caught by the Lane E/F report
gates. A negative harness only earns trust if it proves it left NOTHING behind —
so after exercising every case it re-asserts the real encounter catalog is
byte-for-byte healed (exactly 120 encounters, no __negenc_* leakage) and
spot-reruns the contract + beta-report + balance-report gates green.

Two phases (mirrors test_negative_mission.py):

  1. ENCOUNTER-INJECTION — for every fixture, materialize a temp encounter.json
     under a unique id (__negenc_<case>). Every occurrence of the fixture's
     original encounter_id is rewritten to the temp id so the injected record
     stays internally consistent (state-key namespacing, anchor/condition ids)
     and ONLY the injected defect can fire. A catalog record is injected, the
     SPECIFIC owning validator runs as a subprocess, and it must exit non-zero.
     Catalog bytes are restored and the temp tree deleted in a finally.

  2. REPORT-DOCTORING — doctor ONE healthy encounter's beta playtest report
     (success claimed while a mode failed), ONE encounter's playtest contract
     (encounter_* modes stripped — a playtest that ignores the encounter), and
     ONE balance report (band doctored to 'light' on a harder encounter). The
     owning report gate must reject each; original bytes + mtimes restored.

A case that is wrongly ACCEPTED is a validator hole and fails this harness.
Exit 0 iff every case was rejected AND the catalog self-healed.

Report: procedural/reports/encounters/test_negative_encounter/test_negative_encounter_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/test_negative_encounter.py --pack encounter_loop_world --strict
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

import encounter_contract as EC  # noqa: E402
from encounter_catalog import catalog_path, load_encounter_catalog, save_encounter_catalog  # noqa: E402
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

PY = sys.executable
FIXTURES_DIR = REPO_ROOT / EC.ENCOUNTER_INVALID_FIXTURES_REL
GEN_ROOT = REPO_ROOT / EC.ENCOUNTER_GENERATED_REL
BETA_DIR = REPO_ROOT / EC.PLAYTEST_BETA_REPORTS_REL
BALANCE_DIR = REPO_ROOT / EC.BALANCE_REPORTS_REL
NEG_CODE = FailureCode.ENCOUNTER_CONTRACT_FAILURE
EXPECTED_ENCOUNTER_COUNT = 120
TEMP_PREFIX = "__negenc_"

# Each encounter fixture -> the SPECIFIC validator that owns its single defect.
# (difficulty_band_unclassified also trips the contract taxonomy gate; the
#  band-honesty owner is the pressure validator — stored band must equal the
#  recomputed band. no_safe_recovery: contract accepts an empty-but-present
#  safe_zones list, so the pacing validator owns "no safe recovery after
#  pressure" — verified, documented here.)
ENCOUNTER_CASES = {
    "missing_mission_link": ("validate_encounter_contract.py", FailureCode.ENCOUNTER_CONTRACT_FAILURE),
    "missing_biome_link": ("validate_encounter_contract.py", FailureCode.ENCOUNTER_CONTRACT_FAILURE),
    "missing_objective_link": ("validate_encounter_contract.py", FailureCode.ENCOUNTER_CONTRACT_FAILURE),
    "missing_pressure_budget": ("validate_encounter_contract.py", FailureCode.ENCOUNTER_CONTRACT_FAILURE),
    "missing_playtest_contract": ("validate_encounter_contract.py", FailureCode.ENCOUNTER_CONTRACT_FAILURE),
    "spawn_group_missing_anchor": ("validate_spawn_groups.py", FailureCode.ENCOUNTER_SPAWN_GROUP_FAILURE),
    "spawn_inside_player_start": ("validate_spawn_groups.py", FailureCode.ENCOUNTER_SPAWN_GROUP_FAILURE),
    "spawn_inside_objective_interaction": ("validate_spawn_groups.py", FailureCode.ENCOUNTER_SPAWN_GROUP_FAILURE),
    "patrol_path_disconnected": ("validate_encounter_anchors.py", FailureCode.ENCOUNTER_ANCHOR_FAILURE),
    "ambush_no_escape": ("validate_encounter_archetypes.py", FailureCode.ENCOUNTER_ARCHETYPE_FAILURE),
    "hazard_covers_all_routes": ("validate_encounter_routes.py", FailureCode.ENCOUNTER_ROUTE_FAILURE),
    "hazard_lacks_visual_marker": ("validate_encounter_biome_compatibility.py", FailureCode.ENCOUNTER_BIOME_COMPATIBILITY_FAILURE),
    "encounter_blocks_required_route": ("validate_encounter_routes.py", FailureCode.ENCOUNTER_ROUTE_FAILURE),
    "pressure_over_budget": ("validate_encounter_pressure.py", FailureCode.ENCOUNTER_PRESSURE_FAILURE),
    "difficulty_band_unclassified": ("validate_encounter_pressure.py", FailureCode.ENCOUNTER_PRESSURE_FAILURE),
    "first_pressure_at_player_start": ("validate_encounter_pacing.py", FailureCode.ENCOUNTER_PACING_FAILURE),
    "no_safe_recovery": ("validate_encounter_pacing.py", FailureCode.ENCOUNTER_PACING_FAILURE),
    "resource_reward_without_resolution": ("validate_encounter_rewards.py", FailureCode.ENCOUNTER_REWARD_FAILURE),
    "defensive_holdout_no_cover": ("validate_encounter_archetypes.py", FailureCode.ENCOUNTER_ARCHETYPE_FAILURE),
    "roaming_threat_covers_safe_routes": ("validate_encounter_anchors.py", FailureCode.ENCOUNTER_ANCHOR_FAILURE),
    "extraction_blocks_exit": ("validate_encounter_routes.py", FailureCode.ENCOUNTER_ROUTE_FAILURE),
    "state_never_resolves": ("validate_encounter_state.py", FailureCode.ENCOUNTER_STATE_FAILURE),
    "completion_not_saved": ("validate_encounter_save_load.py", FailureCode.ENCOUNTER_SAVE_LOAD_FAILURE),
    "mission_completes_while_encounter_unmet": ("validate_encounter_mission_compatibility.py", FailureCode.ENCOUNTER_MISSION_COMPATIBILITY_FAILURE),
}

# Self-heal spot check: the three ledger-level gates that would catch leakage.
SELFHEAL_VALIDATORS = (
    "validate_encounter_contract.py",
    "validate_playtest_beta_reports.py",
    "validate_balance_reports.py",
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
    """Remove any stray __negenc_* encounter dirs (defensive)."""
    if GEN_ROOT.is_dir():
        for d in GEN_ROOT.iterdir():
            if d.is_dir() and d.name.startswith(TEMP_PREFIX):
                shutil.rmtree(d, ignore_errors=True)


# =============================================================================
# phase 1 — encounter injection
# =============================================================================
def _inject_encounter(temp_id, fixture, pack):
    """Write a temp encounter.json and inject a catalog record. Returns out_dir.

    The fixture's original encounter_id is rewritten to temp_id EVERYWHERE it
    appears (anchor ids, condition ids, state-key names, persist keys), so the
    injected encounter carries exactly one defect — the fixture's.
    """
    orig_id = fixture.get("encounter_id") or ""
    blob = json.dumps(fixture)
    if orig_id:
        blob = blob.replace(orig_id, temp_id)
    enc = json.loads(blob)
    enc["encounter_id"] = temp_id

    out_dir = GEN_ROOT / temp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    enc["encounter_path"] = (out_dir / "encounter.json").relative_to(REPO_ROOT).as_posix()
    (out_dir / "encounter.json").write_text(
        json.dumps(enc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    catalog = load_encounter_catalog(REPO_ROOT)
    catalog.setdefault("encounters", {})[temp_id] = {
        "encounter_id": temp_id,
        "mission_id": enc.get("mission_id"),
        "pack_id": pack,
        "biome_family": enc.get("biome_family"),
        "mission_archetype": enc.get("mission_archetype"),
        "encounter_archetype": enc.get("encounter_archetype"),
        "encounter_profile": enc.get("encounter_profile"),
        "difficulty_band": enc.get("difficulty_band"),
        "encounter_path": enc["encounter_path"],
        "ownership_class": "generated_owned",
        "playtest_beta_status": "pending",
        "balance_status": "pending",
    }
    save_encounter_catalog(REPO_ROOT, catalog)
    return out_dir


def encounter_injection_phase(rep, pack, strict):
    cat_file = catalog_path(REPO_ROOT)
    for case in sorted(ENCOUNTER_CASES):
        script, code = ENCOUNTER_CASES[case]
        fx = FIXTURES_DIR / (case + ".json")
        if not fx.is_file():
            rep.check("inject::{}".format(case), False,
                      "fixture missing: {}".format(fx), code=NEG_CODE)
            print("FAIL  MISSING fixture: {}".format(fx.name))
            continue
        try:
            fixture = json.loads(fx.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            rep.check("inject::{}".format(case), False,
                      "fixture unparseable: {}".format(exc), code=NEG_CODE)
            continue

        temp_id = TEMP_PREFIX + case
        backup = cat_file.read_bytes() if cat_file.is_file() else None
        out_dir = GEN_ROOT / temp_id
        try:
            out_dir = _inject_encounter(temp_id, fixture, pack)
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
# phase 2 — report / contract doctoring (in place, byte-restored)
# =============================================================================
def _beta_report_path(eid):
    return BETA_DIR / "{}.json".format(eid)


def _balance_report_path(eid):
    return BALANCE_DIR / "{}.json".format(eid)


def _doctor_beta_success_without_completion(target):
    """Beta report claims completed=True while a declared mode failed."""
    rp = _beta_report_path(target)
    report = json.loads(rp.read_text(encoding="utf-8"))
    report["completed"] = True
    modes = report.get("modes") or {}
    if modes:
        first = sorted(modes)[0]
        modes[first] = dict(modes.get(first) or {})
        modes[first]["passed"] = False
    report["modes"] = modes
    rp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                  encoding="utf-8")
    return [rp]


def _doctor_playtest_ignores_encounter(target):
    """Encounter's playtest contract stripped of every encounter_* beta mode."""
    ep = EC.encounter_path(target, REPO_ROOT)
    enc = json.loads(ep.read_text(encoding="utf-8"))
    pt = enc.get("playtest_contract") or {}
    pt["modes"] = [m for m in (pt.get("modes") or [])
                   if not str(m).startswith("encounter_")]
    enc["playtest_contract"] = pt
    ep.write_text(json.dumps(enc, indent=2), encoding="utf-8")
    return [ep]


def _doctor_balance_marks_invalid_valid(target):
    """Balance report band doctored to 'light' on a harder encounter."""
    bp = _balance_report_path(target)
    report = json.loads(bp.read_text(encoding="utf-8"))
    report["difficulty_band"] = "light"
    bp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                  encoding="utf-8")
    return [bp]


# case -> (doctor_fn, owning validator script, failure code)
DOCTOR_CASES = {
    "success_without_completion": (
        _doctor_beta_success_without_completion,
        "validate_playtest_beta_reports.py",
        FailureCode.PLAYTEST_BETA_REPORT_FAILURE),
    "playtest_ignores_encounter": (
        _doctor_playtest_ignores_encounter,
        "validate_playtest_beta_contract.py",
        FailureCode.PLAYTEST_BETA_CONTRACT_FAILURE),
    "balance_marks_invalid_valid": (
        _doctor_balance_marks_invalid_valid,
        "validate_balance_reports.py",
        FailureCode.BALANCE_REPORT_FAILURE),
}


def report_doctoring_phase(rep, pack, strict, targets):
    for case in sorted(DOCTOR_CASES):
        doctor, script, code = DOCTOR_CASES[case]
        target = targets[case]
        if target is None:
            rep.check("doctor::{}".format(case), False,
                      "no doctoring target available", code=code)
            continue
        touched = []
        original = _snapshot([_beta_report_path(target),
                              _balance_report_path(target),
                              EC.encounter_path(target, REPO_ROOT)])
        try:
            touched = doctor(target)
            rc, tail = _run(script, ["--pack", pack] + (["--strict"] if strict else []), strict)
            rejected = rc is not None and rc != 0
            rep.check("doctor::{}".format(case), rejected,
                      "{} on {} rc={} ({})".format(script, target, rc, tail), code=code)
            print("{}  doctor {} -> {} (rc={})".format(
                "PASS" if rejected else "FAIL  ACCEPTED", case, script, rc))
        except Exception as exc:  # noqa: BLE001
            rep.check("doctor::{}".format(case), False,
                      "doctoring harness raised: {} (touched={})".format(exc, touched),
                      code=code)
        finally:
            _restore(original)


# =============================================================================
# self-heal
# =============================================================================
def selfheal_check(rep, pack, strict):
    catalog = load_encounter_catalog(REPO_ROOT)
    encounters = catalog.get("encounters") or {}
    n = len(encounters)
    rep.check("selfheal::encounter_count", n == EXPECTED_ENCOUNTER_COUNT,
              "catalog has {} encounters (expected {})".format(n, EXPECTED_ENCOUNTER_COUNT),
              code=NEG_CODE)

    stray_records = sorted(e for e in encounters if e.startswith(TEMP_PREFIX))
    rep.check("selfheal::no_temp_records", not stray_records,
              "stray temp catalog records: {}".format(stray_records), code=NEG_CODE)

    stray_dirs = sorted(
        p.name for p in GEN_ROOT.iterdir()
        if p.is_dir() and p.name.startswith(TEMP_PREFIX)
    ) if GEN_ROOT.is_dir() else []
    rep.check("selfheal::no_temp_dirs", not stray_dirs,
              "stray temp encounter dirs: {}".format(stray_dirs), code=NEG_CODE)

    for script in SELFHEAL_VALIDATORS:
        rc, tail = _run(script, ["--pack", pack] + (["--strict"] if strict else []), strict)
        rep.check("selfheal::{}".format(script.replace(".py", "")),
                  rc == 0, "{} rc={} ({})".format(script, rc, tail), code=NEG_CODE)


# =============================================================================
# main
# =============================================================================
def _pick_targets():
    """Choose healthy doctoring targets from the real catalog."""
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted((catalog.get("encounters") or {}).keys())
    first = eids[0] if eids else None

    hard = None
    for eid in eids:
        enc, _err = EC.load_encounter(eid)
        if enc and enc.get("difficulty_band") == "hard":
            hard = eid
            break
    if hard is None:  # fall back to any non-light band
        for eid in eids:
            enc, _err = EC.load_encounter(eid)
            if enc and enc.get("difficulty_band") not in (None, "light"):
                hard = eid
                break
    return {
        "success_without_completion": first,
        "playtest_ignores_encounter": first,
        "balance_marks_invalid_valid": hard or first,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.4 EncounterForge negative-fixture gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)

    targets = _pick_targets()
    # Global byte snapshot: catalog + every file any doctoring case touches.
    global_paths = [catalog_path(REPO_ROOT)]
    for eid in {t for t in targets.values() if t}:
        global_paths += [_beta_report_path(eid), _balance_report_path(eid),
                         EC.encounter_path(eid, REPO_ROOT)]
    # ...plus every owning validator's command report: the injection/doctoring
    # subprocesses rewrite those with 'fail' status while a fixture is live, and
    # the shield's final report-integrity scan must never see detect-phase dirt.
    owning_scripts = {script for script, _code in ENCOUNTER_CASES.values()}
    owning_scripts |= {script for _fn, script, _code in DOCTOR_CASES.values()}
    for script in sorted(owning_scripts):
        stem = script.replace(".py", "")
        global_paths.append(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / stem
                            / "{}_report.json".format(stem))
    global_snap = _snapshot(global_paths)

    n_cases = len(ENCOUNTER_CASES) + len(DOCTOR_CASES)
    try:
        if not FIXTURES_DIR.is_dir():
            rep.error("no invalid encounter fixtures dir: {}".format(FIXTURES_DIR))
        elif targets["success_without_completion"] is None:
            rep.error("no encounters in catalog — run create_encounters + "
                      "run_playtest_forge_beta + run_balance_forge first")
        else:
            print("[encounter-negative] ENCOUNTER-INJECTION phase ({} fixtures)".format(
                len(ENCOUNTER_CASES)))
            encounter_injection_phase(rep, args.pack, strict)
            print("[encounter-negative] REPORT-DOCTORING phase ({} cases, targets={})".format(
                len(DOCTOR_CASES), sorted(set(t for t in targets.values() if t))))
            report_doctoring_phase(rep, args.pack, strict, targets)
            print("[encounter-negative] SELF-HEAL check")
            selfheal_check(rep, args.pack, strict)
    finally:
        _restore(global_snap)
        _purge_temp_dirs()

    rep.finalize()
    rep.set_meta(build_meta(command="encounter-negative-validators", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n_cases,
                            extra={"cases_exercised": n_cases,
                                   "encounter_fixtures": sorted(ENCOUNTER_CASES),
                                   "doctor_cases": sorted(DOCTOR_CASES),
                                   "doctor_targets": targets}))
    report_dir = REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "test_negative_encounter"
    rep.write(report_dir, "test_negative_encounter_report.json")
    rep.print_summary("encounter-negative")
    print("[encounter-negative] {} cases exercised ({} injection + {} doctoring)".format(
        n_cases, len(ENCOUNTER_CASES), len(DOCTOR_CASES)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
