#!/usr/bin/env python3
"""encounter_lifecycle_torture.py — WorldForge v1.4 EncounterForge lifecycle torture (Lane G).

Proves the GENERATED encounter catalog + its 120 encounters + their beta
playtest and balance reports survive the full hostile lifecycle

    corrupt -> detect -> repair -> destroy -> rebuild -> revalidate

on a GENERATED-OWNED scope only. Mirrors mission_lifecycle_torture.py in shape
and reporting, adapted to the v1.4 encounter layer (encounters + catalog +
PlaytestForge Beta + BalanceForge reports).

Phases:

  1. BASELINE — deterministic full regen (create_encounters +
     run_playtest_forge_beta + run_balance_forge), then confirm the catalog
     holds exactly 120 encounters and the revalidation suite is green.

  2. CORRUPTION -> DETECT -> REPAIR — for each mode: apply ONE corruption,
     assert the OWNING detector FLAGS it (a validator exits non-zero, or the
     harness-owned disk-vs-catalog scan finds the orphan/ghost), then repair by
     a full regen and confirm the detector goes green again. A corruption that
     goes UNDETECTED is a CORRUPTION_UNDETECTED failure. The
     destroy_human_owned_dependency_attempt mode drives the torture's own
     destroy guard against a THIRD-PARTY (Megascans) external asset record and
     asserts the guard REFUSES — read-only; nothing third-party is ever touched.

  3. DESTROY — back up then remove every generated-owned encounter dir +
     catalog record through the ownership guard (anything not generated_owned
     is refused), then confirm the catalog is empty and the validators refuse
     to fake-green (non-zero exit on an empty catalog).

  4. REBUILD / REVALIDATE — full regen; confirm 120 encounters and the
     revalidation suite green.

A master snapshot of the catalog + generated encounters tree + beta/balance
report trees is taken up front and restored in a finally.

  5. POST-RESTORE — after the finally restore, re-run create_encounters +
     run_playtest_forge_beta + run_balance_forge so the on-disk reports reflect
     the healed 120-encounter state, and prove the final state is fully
     restored (120 encounters, revalidation suite green).

Report: procedural/reports/encounters/encounter_lifecycle_torture/encounter_lifecycle_torture_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/encounter_lifecycle_torture.py --pack encounter_loop_world --strict
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

import encounter_contract as EC  # noqa: E402
import external_asset_contract as EAC  # noqa: E402
from encounter_catalog import (  # noqa: E402
    catalog_path, load_encounter_catalog, remove_encounter, save_encounter_catalog,
)
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

PY = sys.executable
LIF = FailureCode.ENCOUNTER_LIFECYCLE_FAILURE
EXPECTED_ENCOUNTER_COUNT = 120

# The revalidation suite (brief: contract + pressure + beta reports).
REVALIDATE = (
    "validate_encounter_contract.py",
    "validate_encounter_pressure.py",
    "validate_playtest_beta_reports.py",
)


# =============================================================================
# subprocess + snapshot helpers (mirrors mission_lifecycle_torture.py)
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
    """Deterministic full regen: 120 encounters + beta reports + balance reports.

    create_encounters rewrites every encounter.json (and re-upserts the
    catalog), so run_playtest_forge_beta AND run_balance_forge MUST follow to
    re-emit non-stale evidence. This is the canonical repair / rebuild.
    """
    rc1, t1 = _run("create_encounters.py", ["--pack", pack] + _strict_args(strict), strict)
    rc2, t2 = _run("run_playtest_forge_beta.py", ["--pack", pack] + _strict_args(strict), strict)
    rc3, t3 = _run("run_balance_forge.py", ["--pack", pack] + _strict_args(strict), strict)
    ok = (rc1 == 0) and (rc2 == 0) and (rc3 == 0)
    return ok, "create rc={} ({}); beta rc={} ({}); balance rc={} ({})".format(
        rc1, t1, rc2, t2, rc3, t3)


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
            # prune now-empty orphan dirs (e.g. an encounter dir absent from snap)
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
        REPO_ROOT / EC.ENCOUNTER_GENERATED_REL,
        # The FULL encounter reports tree (includes playtest_beta + balance):
        # detect-phase validator subprocesses rewrite per-command reports with
        # 'fail' status while corruption is live; restoring the whole tree
        # guarantees on-disk reports reflect the healed state, so the final
        # report-integrity scan never sees a laundered detect-phase failure.
        # The torture's own report is written AFTER the restore, so it survives.
        REPO_ROOT / EC.ENCOUNTER_REPORTS_REL,
    ]


# =============================================================================
# small catalog / encounter helpers
# =============================================================================
def _catalog_encounter_ids():
    return sorted((load_encounter_catalog(REPO_ROOT).get("encounters") or {}).keys())


def _disk_encounter_ids():
    """Encounter ids materialized on disk (<id>/encounter.json under the tree)."""
    root = REPO_ROOT / EC.ENCOUNTER_GENERATED_REL
    ids = []
    for f in glob.glob(str(root / "*" / "encounter.json")):
        ids.append(Path(f).parent.name)
    return sorted(ids)


def _load_enc(eid):
    enc, _err = EC.load_encounter(eid)
    return enc or {}


def _write_enc(eid, enc):
    p = EC.encounter_path(eid)
    p.write_text(json.dumps(enc, indent=2), encoding="utf-8")


def _eid_where(pred):
    for eid in _catalog_encounter_ids():
        enc = _load_enc(eid)
        if enc and pred(enc):
            return eid
    return None


# =============================================================================
# ownership guard — THE destroy path. Refuses anything not generated-owned.
# =============================================================================
def _destroy_allowed(record):
    """(allowed, why). The torture's destroy routine goes through this guard for
    EVERY record it would remove; third-party / protected records are refused."""
    rec = record or {}
    if rec.get("ownership_class") != "generated_owned":
        return False, "ownership_class={!r} != 'generated_owned'".format(
            rec.get("ownership_class"))
    if rec.get("third_party_owned"):
        return False, "third_party_owned flag set"
    if rec.get("repair_destroy_protected"):
        return False, "repair_destroy_protected flag set"
    return True, "generated_owned"


# =============================================================================
# corruption modes — each: apply(pack, strict) -> detail ;
# detect(pack, strict) -> (flagged, detail). Post-repair the same detect must
# return (False, ..). ghost-record repair also prunes the harness's own ghost.
# =============================================================================
_GHOST_KEY = ["__torture_ghost__"]  # mutable holder for the duplicate-record key


def _detect_via_validator(script):
    def _detect(pack, strict):
        rc, tail = _run(script, ["--pack", pack] + _strict_args(strict), strict)
        return (rc != 0), "{} rc={} ({})".format(script, rc, tail)
    return _detect


def _apply_delete_encounter_definition(pack, strict):
    target = _catalog_encounter_ids()[0]
    EC.encounter_path(target).unlink()
    return "deleted encounter.json for {}".format(target)


def _apply_delete_spawn_group(pack, strict):
    target = _catalog_encounter_ids()[0]
    enc = _load_enc(target)
    enc["spawn_groups"] = []
    _write_enc(target, enc)
    return "deleted every spawn group of {}".format(target)


def _apply_delete_spawn_anchor(pack, strict):
    target = _catalog_encounter_ids()[0]
    enc = _load_enc(target)
    enc["spawn_anchors"] = []
    _write_enc(target, enc)
    return "deleted every spawn anchor of {} (group refs dangle)".format(target)


def _apply_delete_cover_anchor(pack, strict):
    target = _eid_where(lambda e: e.get("encounter_archetype") in
                        ("guarded_objective", "defensive_holdout", "ambush_choke")
                        and bool(e.get("cover_anchors")))
    enc = _load_enc(target)
    enc["cover_anchors"] = []
    _write_enc(target, enc)
    return "deleted cover anchors of cover-required encounter {}".format(target)


def _apply_delete_hazard_zone(pack, strict):
    target = _eid_where(lambda e: e.get("encounter_archetype") == "hazard_field")
    enc = _load_enc(target)
    enc["hazard_zones"] = []
    _write_enc(target, enc)
    return "deleted hazard zones of hazard_field encounter {}".format(target)


def _apply_delete_state_key(pack, strict):
    target = _catalog_encounter_ids()[0]
    enc = _load_enc(target)
    enc["state_keys"] = []
    _write_enc(target, enc)
    return "deleted every encounter state key of {}".format(target)


def _apply_delete_completion_condition(pack, strict):
    target = _catalog_encounter_ids()[0]
    enc = _load_enc(target)
    enc["completion_conditions"] = []
    _write_enc(target, enc)
    return "deleted every completion condition of {}".format(target)


def _apply_delete_reward_hook(pack, strict):
    target = _catalog_encounter_ids()[0]
    enc = _load_enc(target)
    enc["reward_hooks"] = []
    _write_enc(target, enc)
    return "deleted every reward hook of {}".format(target)


def _apply_corrupt_pressure_budget(pack, strict):
    target = _catalog_encounter_ids()[0]
    enc = _load_enc(target)
    enc["pressure_budget"] = 1.0
    _write_enc(target, enc)
    return "pressure_budget of {} corrupted to 1.0".format(target)


def _apply_corrupt_difficulty_band(pack, strict):
    target = _catalog_encounter_ids()[0]
    enc = _load_enc(target)
    enc["difficulty_band"] = "trivial" if enc.get("difficulty_band") != "trivial" \
        else "extreme"
    _write_enc(target, enc)
    return "difficulty_band of {} corrupted to {!r}".format(
        target, enc["difficulty_band"])


def _apply_corrupt_beta_report(pack, strict):
    target = _catalog_encounter_ids()[0]
    rp = REPO_ROOT / EC.PLAYTEST_BETA_REPORTS_REL / "{}.json".format(target)
    data = rp.read_bytes()
    rp.write_bytes(data[: max(len(data) // 2, 1)])  # truncate -> unparseable
    return "truncated beta playtest report for {}".format(target)


def _apply_orphan_encounter_record(pack, strict):
    target = _catalog_encounter_ids()[0]
    catalog = load_encounter_catalog(REPO_ROOT)
    catalog = remove_encounter(catalog, target)
    save_encounter_catalog(REPO_ROOT, catalog)
    return "removed catalog record for {} (orphan encounter.json left on disk)".format(target)


def _detect_orphan(pack, strict):
    """Harness-owned disk-vs-catalog scan: an encounter.json on disk with no
    catalog record, and a catalog below the 120 baseline."""
    cat = set(_catalog_encounter_ids())
    disk = set(_disk_encounter_ids())
    orphans = sorted(disk - cat)
    detected = bool(orphans) and len(cat) < EXPECTED_ENCOUNTER_COUNT
    return detected, "orphans_on_disk={} catalog_count={}".format(orphans[:4], len(cat))


def _apply_duplicate_encounter_record(pack, strict):
    src = _catalog_encounter_ids()[0]
    ghost = "__torture_dup_{}".format(src)
    catalog = load_encounter_catalog(REPO_ROOT)
    entry = dict((catalog.get("encounters") or {}).get(src) or {})
    entry["encounter_id"] = ghost
    catalog.setdefault("encounters", {})[ghost] = entry
    save_encounter_catalog(REPO_ROOT, catalog)
    _GHOST_KEY[0] = ghost
    return "cloned catalog record {} under ghost key {} (no dir on disk)".format(src, ghost)


def _detect_ghost(pack, strict):
    """Harness-owned scan: a catalog record with no encounter.json on disk."""
    cat = set(_catalog_encounter_ids())
    disk = set(_disk_encounter_ids())
    ghosts = sorted(cat - disk)
    return bool(ghosts), "ghost_records={} catalog_count={}".format(ghosts[:4], len(cat))


def _repair_duplicate_record(pack, strict):
    """The disk-vs-catalog reconciliation no validator owns: prune the ghost
    record the torture injected, then run the canonical regen."""
    catalog = load_encounter_catalog(REPO_ROOT)
    (catalog.get("encounters") or {}).pop(_GHOST_KEY[0], None)
    save_encounter_catalog(REPO_ROOT, catalog)
    return _regen(pack, strict)


def _apply_route_blocking_encounter(pack, strict):
    import mission_contract as MC
    target = _catalog_encounter_ids()[0]
    enc = _load_enc(target)
    mission, _ = MC.load_mission(enc.get("mission_id") or "")
    corridor = EC.densify_route(
        ((mission or {}).get("required_route") or {}).get("waypoints"))
    enc["spawn_anchors"] = [
        {"id": "torture_block_{}".format(i), "kind": "spawn",
         "world_position": list(wp), "valid_spawn": True}
        for i, wp in enumerate(corridor)]
    enc.setdefault("pacing_target", {})["max_route_blockage_ratio"] = 0.05
    _write_enc(target, enc)
    return "spawns moved onto the required route of {} + blockage target tightened".format(target)


def _apply_objective_blocking_spawn(pack, strict):
    import mission_contract as MC
    target = _catalog_encounter_ids()[0]
    enc = _load_enc(target)
    mission, _ = MC.load_mission(enc.get("mission_id") or "")
    obj = ((mission or {}).get("objective_anchors") or [{}])[0].get("world_position")
    for a in enc.get("spawn_anchors") or []:
        a["world_position"] = list(obj or [0.0, 0.0, 0.0])
    _write_enc(target, enc)
    return "spawn anchors of {} moved onto the mission objective".format(target)


def _run_destroy_guard_attempt(rep, pack, strict):
    """Attempt to destroy a THIRD-PARTY (Megascans) external asset record via the
    torture's own destroy guard and assert it is REFUSED. Read-only: when the
    guard refuses, no deletion is even attempted."""
    ext_path = REPO_ROOT / EAC.EXTERNAL_CATALOG_REL
    before = ext_path.read_bytes() if ext_path.is_file() else None
    assets = (EAC.load_external_catalog(REPO_ROOT) or {}).get("assets") or {}
    mega = sorted(a for a in assets if a.startswith("megascans_")) or sorted(assets)
    target = mega[0] if mega else None
    rep.check("mode::destroy_human_owned_dependency_attempt::target_exists",
              target is not None,
              "no external (Megascans) asset record to test the guard against",
              code=LIF)
    if target is None:
        return
    allowed, why = _destroy_allowed(assets.get(target))
    rep.check("mode::destroy_human_owned_dependency_attempt::refused",
              not allowed,
              "destroy guard verdict for {!r}: allowed={} ({})".format(
                  target, allowed, why), code=LIF)
    after = ext_path.read_bytes() if ext_path.is_file() else None
    rep.check("mode::destroy_human_owned_dependency_attempt::external_catalog_untouched",
              before == after,
              "external asset catalog bytes changed during the destroy attempt",
              code=LIF)


# Ordered modes. Entries are (name, apply, detect, repair_or_None); the guard
# attempt is a custom, self-contained mode ((name, None, None, run_fn)).
CORRUPTION_MODES = (
    ("delete_encounter_definition", _apply_delete_encounter_definition,
     _detect_via_validator("validate_encounter_contract.py"), None),
    ("delete_spawn_group", _apply_delete_spawn_group,
     _detect_via_validator("validate_spawn_groups.py"), None),
    ("delete_spawn_anchor", _apply_delete_spawn_anchor,
     _detect_via_validator("validate_spawn_groups.py"), None),
    ("delete_cover_anchor", _apply_delete_cover_anchor,
     _detect_via_validator("validate_encounter_archetypes.py"), None),
    ("delete_hazard_zone", _apply_delete_hazard_zone,
     _detect_via_validator("validate_encounter_archetypes.py"), None),
    ("delete_encounter_state_key", _apply_delete_state_key,
     _detect_via_validator("validate_encounter_state.py"), None),
    ("delete_completion_condition", _apply_delete_completion_condition,
     _detect_via_validator("validate_encounter_contract.py"), None),
    ("delete_reward_hook", _apply_delete_reward_hook,
     _detect_via_validator("validate_encounter_rewards.py"), None),
    ("corrupt_pressure_budget", _apply_corrupt_pressure_budget,
     _detect_via_validator("validate_encounter_pressure.py"), None),
    ("corrupt_difficulty_band", _apply_corrupt_difficulty_band,
     _detect_via_validator("validate_encounter_pressure.py"), None),
    ("corrupt_playtest_beta_report", _apply_corrupt_beta_report,
     _detect_via_validator("validate_playtest_beta_reports.py"), None),
    ("orphan_encounter_record", _apply_orphan_encounter_record, _detect_orphan, None),
    ("duplicate_encounter_record", _apply_duplicate_encounter_record,
     _detect_ghost, _repair_duplicate_record),
    ("route_blocking_encounter", _apply_route_blocking_encounter,
     _detect_via_validator("validate_encounter_routes.py"), None),
    ("objective_blocking_spawn", _apply_objective_blocking_spawn,
     _detect_via_validator("validate_spawn_groups.py"), None),
    ("destroy_human_owned_dependency_attempt", None, None, _run_destroy_guard_attempt),
)


# =============================================================================
# phases
# =============================================================================
def _assert_green_suite(rep, prefix, pack, strict):
    for script in REVALIDATE:
        ok, rc, tail = _validator_green(script, pack, strict)
        rep.check("{}::{}".format(prefix, script.replace(".py", "")), ok,
                  "{} rc={} ({})".format(script, rc, tail), code=LIF)


def baseline_phase(rep, pack, strict):
    ok, detail = _regen(pack, strict)
    rep.check("baseline::regen", ok, detail, code=LIF)
    n = len(_catalog_encounter_ids())
    rep.check("baseline::encounter_count", n == EXPECTED_ENCOUNTER_COUNT,
              "catalog has {} encounters (expected {})".format(n, EXPECTED_ENCOUNTER_COUNT),
              code=LIF)
    _assert_green_suite(rep, "baseline", pack, strict)


def corruption_phase(rep, pack, strict):
    for name, apply_fn, detect_fn, repair_fn in CORRUPTION_MODES:
        if apply_fn is None and callable(repair_fn):
            # self-contained custom mode (destroy-guard attempt)
            repair_fn(rep, pack, strict)
            continue
        try:
            detail = apply_fn(pack, strict)

            # -- detect: the owning detector must FLAG the corruption ----------
            detected, ddetail = detect_fn(pack, strict)
            rep.check("mode::{}::detected".format(name), detected,
                      "corruption {}: {} -> {}".format(
                          "DETECTED" if detected else "UNDETECTED", detail, ddetail),
                      code=FailureCode.CORRUPTION_UNDETECTED if not detected else LIF)

            # -- repair: full regen (create + beta + balance) -------------------
            if repair_fn is not None:
                ok, rdetail = repair_fn(pack, strict)
            else:
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
    """Scoped destroy through the ownership guard: back up then remove every
    generated-owned encounter dir + catalog record; refuse everything else."""
    ids = _catalog_encounter_ids()
    catalog = load_encounter_catalog(REPO_ROOT)
    entries = catalog.get("encounters") or {}
    removed = 0
    refused = []
    for eid in ids:
        enc, _err = EC.load_encounter(eid)
        entry = entries.get(eid) or {}
        ok_entry, why_entry = _destroy_allowed(entry)
        ok_file, why_file = _destroy_allowed(enc)
        if not (ok_entry and ok_file):
            refused.append((eid, why_entry if not ok_entry else why_file))
            continue
        edir = EC.encounter_path(eid).parent
        if edir.is_dir():
            shutil.copytree(str(edir), str(Path(backup_dir) / eid), dirs_exist_ok=True)
            shutil.rmtree(str(edir), ignore_errors=True)
        catalog = remove_encounter(catalog, eid)
        removed += 1
    save_encounter_catalog(REPO_ROOT, catalog)

    rep.check("destroy::none_refused", not refused,
              "destroy refused generated-owned encounters (guard misfire): {}".format(
                  refused[:4]), code=LIF)
    rep.check("destroy::all_removed", removed == EXPECTED_ENCOUNTER_COUNT,
              "removed {} generated-owned encounters (expected {})".format(
                  removed, EXPECTED_ENCOUNTER_COUNT), code=LIF)
    remaining = len(_catalog_encounter_ids())
    rep.check("destroy::catalog_empty", remaining == 0,
              "catalog holds {} record(s) after destroy (expected 0)".format(remaining),
              code=LIF)
    # With an empty catalog the validators must REFUSE to fake-green.
    rc, tail = _run("validate_encounter_contract.py",
                    ["--pack", pack] + _strict_args(strict), strict)
    rep.check("destroy::validators_report_zero", rc != 0,
              "validate_encounter_contract rc={} on empty catalog (expected non-zero) ({})".format(
                  rc, tail), code=LIF)


def rebuild_phase(rep, pack, strict):
    ok, detail = _regen(pack, strict)
    rep.check("rebuild::regen", ok, detail, code=LIF)
    n = len(_catalog_encounter_ids())
    rep.check("rebuild::encounter_count", n == EXPECTED_ENCOUNTER_COUNT,
              "catalog has {} encounters (expected {})".format(n, EXPECTED_ENCOUNTER_COUNT),
              code=LIF)
    _assert_green_suite(rep, "rebuild", pack, strict)


# =============================================================================
# main
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.4 EncounterForge lifecycle torture / regression gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)

    master_dir = tempfile.mkdtemp(prefix="wf_encounter_torture_master_")
    destroy_backup = tempfile.mkdtemp(prefix="wf_encounter_torture_destroy_")
    mapping = _snapshot_tree(_master_snapshot_paths(), master_dir)
    try:
        print("[encounter-lifecycle-torture] BASELINE")
        baseline_phase(rep, args.pack, strict)
        print("[encounter-lifecycle-torture] CORRUPTION ({} modes)".format(
            len(CORRUPTION_MODES)))
        corruption_phase(rep, args.pack, strict)
        print("[encounter-lifecycle-torture] DESTROY")
        destroy_phase(rep, args.pack, strict, destroy_backup)
        print("[encounter-lifecycle-torture] REBUILD / REVALIDATE")
        rebuild_phase(rep, args.pack, strict)
    finally:
        _restore_tree(mapping)
        shutil.rmtree(master_dir, ignore_errors=True)
        shutil.rmtree(destroy_backup, ignore_errors=True)

    # -- POST-RESTORE: re-run create + beta + balance so on-disk reports reflect
    # the healed state, and prove the final state is fully restored.
    print("[encounter-lifecycle-torture] POST-RESTORE")
    ok, detail = _regen(args.pack, strict)
    rep.check("final::regen", ok, detail, code=LIF)
    final_n = len(_catalog_encounter_ids())
    rep.check("final::catalog_restored", final_n == EXPECTED_ENCOUNTER_COUNT,
              "post-restore catalog has {} encounters (expected {})".format(
                  final_n, EXPECTED_ENCOUNTER_COUNT), code=LIF)
    _assert_green_suite(rep, "final", args.pack, strict)

    rep.finalize()
    rep.set_meta(build_meta(command="encounter-lifecycle-torture", pack=args.pack,
                            strict=strict, torture=True, status=rep.status,
                            record_count=len(CORRUPTION_MODES),
                            extra={"corruption_modes": [m[0] for m in CORRUPTION_MODES],
                                   "expected_encounter_count": EXPECTED_ENCOUNTER_COUNT,
                                   "final_encounter_count": len(_catalog_encounter_ids()),
                                   "revalidators": [s.replace(".py", "") for s in REVALIDATE]}))
    report_dir = REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "encounter_lifecycle_torture"
    rep.write(report_dir, "encounter_lifecycle_torture_report.json")
    rep.print_summary("encounter-lifecycle-torture")
    print("[encounter-lifecycle-torture] corrupt->detect->repair->destroy->rebuild->"
          "revalidate cycle run ({} corruption modes); final catalog={}".format(
              len(CORRUPTION_MODES), len(_catalog_encounter_ids())))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
