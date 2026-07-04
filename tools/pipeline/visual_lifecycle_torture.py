#!/usr/bin/env python3
"""visual_lifecycle_torture.py — WorldForge v1.3.5 VisualFidelity lifecycle torture (Agent 7).

Proves the GENERATED visual layer — the 60 environment rigs + 60 dressing plans +
the visual catalog — survives the full hostile lifecycle

    corrupt -> detect -> repair -> (megascans protection) -> destroy -> rebuild -> revalidate

on a GENERATED-OWNED scope only. Mirrors mission_lifecycle_torture.py in shape and
reporting, adapted to the v1.3.5 visual layer. The Megascans SOURCE is third-party,
licensed, and READ-ONLY: the destroy routine must refuse to touch it, and the
external asset catalog must be byte-identical before and after the destroy.

Phases:

  1. BASELINE — deterministic full regen (scan_megascans_visual_assets +
     materialize_environment_rigs + create_visual_dressing), then confirm 60 rigs,
     60 dressing plans, and every visual validator green.

  2. CORRUPTION -> DETECT -> REPAIR — for each mode: apply ONE corruption, assert the
     OWNING validator FLAGS it (exits non-zero), then repair by a full regen and
     confirm it goes green again:
       * delete one rig JSON        -> validate_environment_rig
       * strip one sky to a name     -> validate_sky_materialization
       * delete one dressing plan    -> validate_world_dressing
     A corruption that goes UNDETECTED is a CORRUPTION_UNDETECTED failure.

  3. MEGASCANS DESTROY-PROTECTION — assert the visual destroy routine is scoped to
     generated_owned artifacts and would NEVER delete a third-party Megascans source
     asset (0 external deletions; every external catalog asset stays
     third_party_owned / repair-destroy-protected).

  4. DESTROY — back up then remove every generated-owned rig + dressing + the visual
     catalog (scoped to the generated tree), assert the external asset catalog is
     byte-identical (READ-ONLY protected), and confirm the validators refuse to
     fake-green (non-zero exit) with no rigs.

  5. REBUILD / REVALIDATE — full regen; confirm 60 rigs, 60 dressing, all validators green.

A master snapshot of the visual catalog bytes + the generated rigs/dressing trees +
the visual asset catalog is taken up front and restored in a finally, so the working
tree is left byte-identical even if a phase raises mid-run.

  6. POST-RESTORE — after the finally restore, re-run the suite so the final state is
     proven fully restored (60 rigs, 60 dressing, all validators green).

Report: procedural/reports/visual/visual_lifecycle_torture/visual_lifecycle_torture_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/visual_lifecycle_torture.py --pack mission_loop_world --strict
"""

import argparse
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

import visual_contract as VC  # noqa: E402
import external_asset_contract as EAC  # noqa: E402
from visual_catalog import load_visual_catalog  # noqa: E402
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

PY = sys.executable
LIF = FailureCode.VISUAL_LIFECYCLE_FAILURE
EXPECTED_MAP_COUNT = 60

ENV_RIGS_DIR = REPO_ROOT / VC.ENV_RIGS_REL
DRESSING_DIR = REPO_ROOT / VC.DRESSING_REL
VISUAL_CATALOG = REPO_ROOT / VC.VISUAL_CATALOG_REL
VISUAL_ASSET_CATALOG = REPO_ROOT / VC.VISUAL_ASSET_CATALOG_REL
EXTERNAL_CATALOG = REPO_ROOT / EAC.EXTERNAL_CATALOG_REL

ALL_VALIDATORS = (
    "validate_visual_asset_coverage.py",
    "validate_surface_materialization.py",
    "validate_world_dressing.py",
    "validate_environment_rig.py",
    "validate_sky_materialization.py",
    "validate_fog_materialization.py",
    "validate_cloud_materialization.py",
    "validate_lighting_exposure.py",
    "validate_post_process_profiles.py",
    "validate_weather_vfx.py",
    "validate_visual_readability.py",
    "validate_visual_budgets.py",
    "validate_visual_package.py",
)


# =============================================================================
# subprocess + snapshot helpers (mirror mission_lifecycle_torture.py)
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
    """Deterministic full regen of the visual layer (the canonical repair/rebuild)."""
    rc0, t0 = _run("scan_megascans_visual_assets.py", ["--lib", "megascans"] + _strict_args(strict), strict)
    rc1, t1 = _run("materialize_environment_rigs.py", ["--pack", pack] + _strict_args(strict), strict)
    rc2, t2 = _run("create_visual_dressing.py", ["--pack", pack] + _strict_args(strict), strict)
    ok = rc0 == 0 and rc1 == 0 and rc2 == 0
    return ok, "scan rc={} ({}); materialize rc={} ({}); dressing rc={} ({})".format(rc0, t0, rc1, t1, rc2, t2)


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
            for rel in snap_files:
                dst = live / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(snap / rel), str(dst))
        else:
            if snap.is_file():
                live.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(snap), str(live))


def _master_snapshot_paths():
    return [p for p in (VISUAL_CATALOG, VISUAL_ASSET_CATALOG, ENV_RIGS_DIR, DRESSING_DIR) if p.exists()]


# =============================================================================
# small helpers
# =============================================================================
def _rig_files():
    return sorted(ENV_RIGS_DIR.glob("*.json")) if ENV_RIGS_DIR.is_dir() else []


def _dressing_files():
    return sorted(DRESSING_DIR.glob("*.json")) if DRESSING_DIR.is_dir() else []


def _catalog_slice_ids():
    return sorted((load_visual_catalog(REPO_ROOT).get("maps") or {}).keys())


def _assert_green_suite(rep, prefix, pack, strict):
    for script in ALL_VALIDATORS:
        rc, tail = _run(script, ["--pack", pack] + _strict_args(strict), strict)
        rep.check("{}::{}".format(prefix, script.replace(".py", "")), rc == 0,
                  "{} rc={} ({})".format(script, rc, tail), code=LIF)


def _assert_counts(rep, prefix):
    nr, nd = len(_rig_files()), len(_dressing_files())
    rep.check("{}::rig_count".format(prefix), nr == EXPECTED_MAP_COUNT,
              "{} rigs (expected {})".format(nr, EXPECTED_MAP_COUNT), code=LIF)
    rep.check("{}::dressing_count".format(prefix), nd == EXPECTED_MAP_COUNT,
              "{} dressing plans (expected {})".format(nd, EXPECTED_MAP_COUNT), code=LIF)


# =============================================================================
# corruption modes — apply(pack,strict)->detail ; detect(pack,strict)->(bool,detail)
# =============================================================================
def _apply_delete_rig(pack, strict):
    target = _rig_files()[0]
    target.unlink()
    return "deleted rig JSON {}".format(target.name)


def _apply_strip_sky(pack, strict):
    target = _rig_files()[0]
    rig = json.loads(target.read_text(encoding="utf-8"))
    for c in rig.get("components") or []:
        if c.get("component") == VC.COMP_SKY_ATMOSPHERE:
            c["params"] = {}  # a name-only sky (no luminance/colors)
    target.write_text(json.dumps(rig, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return "stripped SkyAtmosphere params for {}".format(target.stem)


def _apply_delete_dressing(pack, strict):
    target = _dressing_files()[0]
    target.unlink()
    return "deleted dressing plan {}".format(target.name)


def _detect_via_validator(script):
    def _detect(pack, strict):
        rc, tail = _run(script, ["--pack", pack] + _strict_args(strict), strict)
        return (rc != 0), "{} rc={} ({})".format(script, rc, tail)
    return _detect


CORRUPTION_MODES = (
    ("delete_rig_json", _apply_delete_rig, _detect_via_validator("validate_environment_rig.py")),
    ("strip_sky", _apply_strip_sky, _detect_via_validator("validate_sky_materialization.py")),
    ("delete_dressing_plan", _apply_delete_dressing, _detect_via_validator("validate_world_dressing.py")),
)


# =============================================================================
# phases
# =============================================================================
def baseline_phase(rep, pack, strict):
    ok, detail = _regen(pack, strict)
    rep.check("baseline::regen", ok, detail, code=LIF)
    _assert_counts(rep, "baseline")
    _assert_green_suite(rep, "baseline", pack, strict)


def corruption_phase(rep, pack, strict):
    for name, apply_fn, detect_fn in CORRUPTION_MODES:
        try:
            detail = apply_fn(pack, strict)
            detected, ddetail = detect_fn(pack, strict)
            rep.check("mode::{}::detected".format(name), detected,
                      "corruption {}: {} -> {}".format(
                          "DETECTED" if detected else "UNDETECTED", detail, ddetail),
                      code=FailureCode.CORRUPTION_UNDETECTED if not detected else LIF)

            ok, rdetail = _regen(pack, strict)
            still, sdetail = detect_fn(pack, strict)
            repaired = ok and not still
            rep.check("mode::{}::repaired".format(name), repaired,
                      "repair regen ok={} ({}); post-repair still-flagged={} ({})".format(
                          ok, rdetail, still, sdetail), code=LIF)
        except Exception as exc:  # noqa: BLE001
            rep.check("mode::{}::ran".format(name), False,
                      "corruption harness raised: {}".format(exc), code=LIF)
            _regen(pack, strict)  # best-effort re-heal so later modes start clean


def _destroy_candidates():
    """The generated-owned visual artifacts a destroy would target: every rig +
    dressing file that declares ownership_class=generated_owned. Files that do NOT
    declare generated ownership are REFUSED (never deleted)."""
    candidates, refused = [], []
    for f in _rig_files() + _dressing_files():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            refused.append(f)
            continue
        if data.get("ownership_class") == VC.OWNERSHIP_GENERATED:
            candidates.append(f)
        else:
            refused.append(f)
    return candidates, refused


def megascans_protection_phase(rep, pack, strict):
    """Assert the destroy routine is scoped to generated_owned artifacts and can
    never target a third-party Megascans source asset."""
    candidates, refused = _destroy_candidates()
    rep.check("protect::destroy_scope_generated_only", not refused,
              "destroy would target non-generated artifacts (guard misfire): {}".format(
                  [f.name for f in refused]), code=LIF)

    # No destroy candidate lives in the external/megascans source scope.
    ext_scope = str(EXTERNAL_CATALOG.resolve())
    leaked = [f for f in candidates if str(f.resolve()) == ext_scope]
    rep.check("protect::zero_external_deletions", not leaked,
              "destroy set includes third-party source paths: {}".format([str(f) for f in leaked]),
              code=FailureCode.THIRD_PARTY_ASSET_DESTROY_RISK)

    # Every external asset the visual layer derives from is third-party + protected.
    ext_assets = (EAC.load_external_catalog(REPO_ROOT).get("assets") or {})
    not_protected = sorted(
        aid for aid, e in ext_assets.items()
        if e.get("ownership_class") != VC.OWNERSHIP_THIRD_PARTY or e.get("generated_owned") is True)
    rep.check("protect::externals_third_party", not not_protected,
              "external assets not third-party-protected: {}".format(not_protected),
              code=FailureCode.EXTERNAL_ASSET_OWNERSHIP_FAILURE)
    rep.check("protect::external_catalog_present", EXTERNAL_CATALOG.is_file(),
              "external asset catalog present (READ-ONLY source): {}".format(EXTERNAL_CATALOG), code=LIF)


def destroy_phase(rep, pack, strict, backup_dir):
    """Scoped destroy: remove every generated-owned rig + dressing + the visual
    catalog, asserting the external Megascans source is byte-identical afterward."""
    ext_before = EXTERNAL_CATALOG.read_bytes() if EXTERNAL_CATALOG.is_file() else None

    candidates, refused = _destroy_candidates()
    removed = 0
    for f in candidates:
        rel = f.relative_to(REPO_ROOT)
        dst = Path(backup_dir) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(f), str(dst))
        f.unlink()
        removed += 1
    if VISUAL_CATALOG.is_file():
        shutil.copy2(str(VISUAL_CATALOG), str(Path(backup_dir) / VISUAL_CATALOG.name))
        VISUAL_CATALOG.unlink()

    rep.check("destroy::none_refused", not refused,
              "destroy refused generated-owned artifacts (guard misfire): {}".format(
                  [f.name for f in refused]), code=LIF)
    rep.check("destroy::all_removed", removed == EXPECTED_MAP_COUNT * 2,
              "removed {} generated artifacts (expected {})".format(removed, EXPECTED_MAP_COUNT * 2),
              code=LIF)
    rep.check("destroy::rigs_gone", len(_rig_files()) == 0,
              "{} rig files remain after destroy".format(len(_rig_files())), code=LIF)

    # READ-ONLY protection: the Megascans source catalog is byte-identical.
    ext_after = EXTERNAL_CATALOG.read_bytes() if EXTERNAL_CATALOG.is_file() else None
    rep.check("destroy::megascans_untouched", ext_before == ext_after,
              "external asset catalog changed during destroy (Megascans source must be READ-ONLY)",
              code=FailureCode.THIRD_PARTY_ASSET_DESTROY_RISK)

    # With no rigs the validators must REFUSE to fake-green (non-zero exit).
    rc, tail = _run("validate_environment_rig.py", ["--pack", pack] + _strict_args(strict), strict)
    rep.check("destroy::validators_report_zero", rc != 0,
              "validate_environment_rig rc={} on empty rig set (expected non-zero) ({})".format(rc, tail),
              code=LIF)


def rebuild_phase(rep, pack, strict):
    ok, detail = _regen(pack, strict)
    rep.check("rebuild::regen", ok, detail, code=LIF)
    _assert_counts(rep, "rebuild")
    _assert_green_suite(rep, "rebuild", pack, strict)


# =============================================================================
# main
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.3.5 VisualFidelity lifecycle torture / regression gate.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)

    master_dir = tempfile.mkdtemp(prefix="wf_visual_torture_master_")
    destroy_backup = tempfile.mkdtemp(prefix="wf_visual_torture_destroy_")
    mapping = _snapshot_tree(_master_snapshot_paths(), master_dir)
    try:
        print("[visual-lifecycle-torture] BASELINE")
        baseline_phase(rep, args.pack, strict)
        print("[visual-lifecycle-torture] CORRUPTION ({} modes)".format(len(CORRUPTION_MODES)))
        corruption_phase(rep, args.pack, strict)
        print("[visual-lifecycle-torture] MEGASCANS DESTROY-PROTECTION")
        megascans_protection_phase(rep, args.pack, strict)
        print("[visual-lifecycle-torture] DESTROY")
        destroy_phase(rep, args.pack, strict, destroy_backup)
        print("[visual-lifecycle-torture] REBUILD / REVALIDATE")
        rebuild_phase(rep, args.pack, strict)
    finally:
        _restore_tree(mapping)
        shutil.rmtree(master_dir, ignore_errors=True)
        shutil.rmtree(destroy_backup, ignore_errors=True)

    # -- POST-RESTORE: re-run the suite so the final restored state is proven green.
    print("[visual-lifecycle-torture] POST-RESTORE")
    _assert_counts(rep, "final")
    ok, detail = _regen(args.pack, strict)
    rep.check("final::regen", ok, detail, code=LIF)
    _assert_green_suite(rep, "final", args.pack, strict)

    rep.finalize()
    rep.set_meta(build_meta(command="visual-lifecycle-torture", pack=args.pack, strict=strict,
                            torture=True, status=rep.status, record_count=len(CORRUPTION_MODES),
                            extra={"corruption_modes": [m[0] for m in CORRUPTION_MODES],
                                   "expected_map_count": EXPECTED_MAP_COUNT,
                                   "final_rig_count": len(_rig_files()),
                                   "final_dressing_count": len(_dressing_files()),
                                   "validators": [s.replace(".py", "") for s in ALL_VALIDATORS]}))
    rep.write(REPO_ROOT / VC.VISUAL_REPORTS_REL / "visual_lifecycle_torture",
              "visual_lifecycle_torture_report.json")
    rep.print_summary("visual-lifecycle-torture")
    print("[visual-lifecycle-torture] corrupt->detect->repair->protect->destroy->rebuild->revalidate "
          "cycle run ({} modes); final rigs={} dressing={}".format(
              len(CORRUPTION_MODES), len(_rig_files()), len(_dressing_files())))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
