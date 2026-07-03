#!/usr/bin/env python3
"""mesh_lifecycle_torture.py — WorldForge v1.2 MeshForge Intake lifecycle torture (Agent 7).

Proves the GENERATED mesh catalog survives the full hostile lifecycle
corrupt -> detect -> repair -> destroy -> rebuild -> revalidate, on a
GENERATED-OWNED scope only. Mirrors the v1.0x lifecycle_torture.py in shape and
reporting, adapted to the v1.2 mesh catalog.

Phases:

  1. BASELINE — re-run create_mesh_assets (deterministic rebuild), then confirm
     all 10 mesh validators are green and the catalog holds exactly 24 assets.

  2. CORRUPTION — for each mode: apply, assert the OWNING validator DETECTS it,
     then "repair" by re-running create_mesh_assets (repair_policy
     regenerate_from_recipe) and confirm the validator goes green again:
       * delete one generated descriptor.json   -> validate_mesh_catalog flags it
       * delete one catalog record (orphan)      -> validate_mesh_catalog flags it
       * move a final path to a Temp path         -> validate_mesh_final_paths flags it
     A corruption that goes UNDETECTED is a CORRUPTION_UNDETECTED failure.

  3. OWNERSHIP SAFETY — assert the destroy guard (destroy_policy
     generated_owned_only) would REFUSE any human-owned / unowned-final entry and
     would permit every (generated-owned) real entry. Since all 24 assets are
     generated-owned, this proves the guard exists and would fire.

  4. DESTROY — remove every generated-owned descriptor + catalog record (scoped to
     the owned tree), then confirm the catalog is empty.

  5. REBUILD / REVALIDATE — re-run create_mesh_assets; confirm 24 assets and all
     10 validators green.

A master snapshot of the catalog + generated mesh tree + definitions is taken up
front and restored in a finally, so the working tree is left byte-identical to its
pre-torture state even if a phase raises mid-run. Never touches human-owned assets.

Report: procedural/reports/mesh/mesh_lifecycle_torture/mesh_lifecycle_torture_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/mesh_lifecycle_torture.py --pack biome_expansion_world --strict
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

import mesh_contract as MC  # noqa: E402
from mesh_catalog import (  # noqa: E402
    catalog_path, load_mesh_catalog, remove_catalog_entry, save_mesh_catalog,
)
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

PY = sys.executable
LIF = FailureCode.MESH_LIFECYCLE_FAILURE
EXPECTED_ASSET_COUNT = len(list((REPO_ROOT / "procedural" / "definitions" / "mesh_assets").glob("*.yaml")))

ALL_VALIDATORS = (
    "validate_mesh_contract.py",
    "validate_mesh_catalog.py",
    "validate_mesh_provenance.py",
    "validate_mesh_final_paths.py",
    "validate_mesh_material_bindings.py",
    "validate_mesh_collision_bounds.py",
    "validate_mesh_pcg_eligibility.py",
    "validate_mesh_biome_compatibility.py",
    "validate_mesh_rendering_budgets.py",
    "validate_mesh_package.py",
)


# =============================================================================
# subprocess + snapshot helpers (mirrors lifecycle_torture.py)
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


def _rebuild(pack, strict):
    """Deterministic rebuild via create_mesh_assets (repair = regenerate_from_recipe)."""
    return _run("create_mesh_assets.py", ["--pack", pack] + _strict_args(strict), strict)


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
        REPO_ROOT / MC.MESH_GENERATED_REL,
        REPO_ROOT / MC.MESH_DEFINITIONS_REL,
    ]


# =============================================================================
# small catalog / descriptor helpers
# =============================================================================
def _catalog_asset_ids():
    return sorted((load_mesh_catalog(REPO_ROOT).get("assets") or {}).keys())


def _load_descriptor(asset_id):
    p = MC.mesh_descriptor_path(asset_id, REPO_ROOT)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_destroyable(descriptor):
    """destroy_policy generated_owned_only: only owned, generated, owned-final assets.

    A human-owned entry, a non-generated entry, or one whose final path is outside
    the owned roots must be refused.
    """
    if not isinstance(descriptor, dict):
        return False
    if descriptor.get("human_owned") is True:
        return False
    if descriptor.get("generated_owned") is not True:
        return False
    if not MC.is_allowed_final_path(descriptor.get("final_asset_path", "")):
        return False
    return True


# =============================================================================
# phases
# =============================================================================
def baseline_phase(rep, pack, strict):
    rc, tail = _rebuild(pack, strict)
    rep.check("baseline::rebuild", rc == 0,
              "create_mesh_assets rc={} ({})".format(rc, tail), code=LIF)
    n = len(_catalog_asset_ids())
    rep.check("baseline::asset_count", n == EXPECTED_ASSET_COUNT,
              "catalog has {} assets (expected {})".format(n, EXPECTED_ASSET_COUNT), code=LIF)
    for script in ALL_VALIDATORS:
        ok, rc, tail = _validator_green(script, pack, strict)
        rep.check("baseline::{}".format(script.replace(".py", "")), ok,
                  "{} rc={} ({})".format(script, rc, tail), code=LIF)


def _corruption_delete_descriptor(pack, strict):
    """Delete one generated descriptor.json. Detector: validate_mesh_catalog."""
    target = _catalog_asset_ids()[0]
    desc = MC.mesh_descriptor_path(target, REPO_ROOT)
    desc.unlink()
    return "validate_mesh_catalog.py", target, "deleted descriptor.json for {}".format(target)


def _corruption_delete_record(pack, strict):
    """Delete one catalog record (leaving descriptor on disk => orphan)."""
    target = _catalog_asset_ids()[0]
    catalog = load_mesh_catalog(REPO_ROOT)
    catalog = remove_catalog_entry(catalog, target)
    save_mesh_catalog(REPO_ROOT, catalog)
    return "validate_mesh_catalog.py", target, "removed catalog record for {}".format(target)


def _corruption_temp_final_path(pack, strict):
    """Move one asset's final path to a Temp path. Detector: validate_mesh_final_paths."""
    target = _catalog_asset_ids()[0]
    desc_path = MC.mesh_descriptor_path(target, REPO_ROOT)
    descriptor = json.loads(desc_path.read_text(encoding="utf-8"))
    descriptor["final_asset_path"] = "/Game/HoudiniEngine/Temp/Leaked/SM_{}".format(target)
    desc_path.write_text(json.dumps(descriptor, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    return "validate_mesh_final_paths.py", target, "moved final path to Temp for {}".format(target)


CORRUPTION_MODES = {
    "delete_generated_descriptor": _corruption_delete_descriptor,
    "delete_catalog_record": _corruption_delete_record,
    "final_path_moved_to_temp": _corruption_temp_final_path,
}


def corruption_phase(rep, pack, strict):
    for mode in sorted(CORRUPTION_MODES):
        apply_fn = CORRUPTION_MODES[mode]
        try:
            detector, target, detail = apply_fn(pack, strict)

            # -- detect: the owning validator must now FAIL -------------------
            green, rc, tail = _validator_green(detector, pack, strict)
            detected = not green
            rep.check("mode::{}::detected".format(mode), detected,
                      "corruption {}: {} -> {} rc={} ({})".format(
                          "DETECTED" if detected else "UNDETECTED", detail, detector, rc, tail),
                      code=FailureCode.CORRUPTION_UNDETECTED if not detected else LIF)

            # -- repair: regenerate_from_recipe (create_mesh_assets) ----------
            rc, rtail = _rebuild(pack, strict)
            green2, rc2, tail2 = _validator_green(detector, pack, strict)
            repaired = (rc == 0) and green2
            rep.check("mode::{}::repaired".format(mode), repaired,
                      "repair rebuild rc={}; post-repair {} green={} ({})".format(
                          rc, detector, green2, tail2),
                      code=FailureCode.MESH_REPAIR_FAILURE if not repaired else LIF)
        except Exception as exc:  # noqa: BLE001
            rep.check("mode::{}::ran".format(mode), False,
                      "corruption harness raised: {}".format(exc), code=LIF)
            # Best-effort re-heal so later phases start clean.
            _rebuild(pack, strict)


def ownership_safety_phase(rep, pack, strict):
    """The destroy guard must refuse human-owned / unowned-final and permit owned."""
    human_owned = {
        "asset_id": "__synthetic_human_owned",
        "human_owned": True,
        "generated_owned": False,
        "final_asset_path": "/Game/HumanAuthored/Meshes/SM_DoNotTouch",
    }
    unowned_final = {
        "asset_id": "__synthetic_unowned_final",
        "human_owned": False,
        "generated_owned": True,
        "final_asset_path": "/Game/ExternalUnowned/Meshes/SM_Foreign",
    }
    rep.check("ownership::guard_refuses_human_owned", not _is_destroyable(human_owned),
              "destroy guard must refuse human_owned entry",
              code=FailureCode.MESH_DESTROY_FAILURE)
    rep.check("ownership::guard_refuses_unowned_final", not _is_destroyable(unowned_final),
              "destroy guard must refuse entry with final path outside owned roots",
              code=FailureCode.MESH_DESTROY_FAILURE)

    # Every real (generated-owned) asset must be destroyable by the guard.
    ids = _catalog_asset_ids()
    non_destroyable = [aid for aid in ids if not _is_destroyable(_load_descriptor(aid) or {})]
    rep.check("ownership::all_generated_owned_destroyable", not non_destroyable,
              "generated-owned assets the guard would wrongly refuse: {}".format(non_destroyable),
              code=FailureCode.MESH_DESTROY_FAILURE)


def destroy_phase(rep, pack, strict):
    """Scoped destroy: remove every generated-owned descriptor + catalog record."""
    ids = _catalog_asset_ids()
    catalog = load_mesh_catalog(REPO_ROOT)
    removed = 0
    refused = []
    for aid in ids:
        descriptor = _load_descriptor(aid)
        if not _is_destroyable(descriptor or {}):
            refused.append(aid)   # guard would refuse — must not happen for the 24
            continue
        # remove the generated descriptor dir (owned tree only) + catalog record
        shutil.rmtree(MC.mesh_descriptor_path(aid, REPO_ROOT).parent, ignore_errors=True)
        catalog = remove_catalog_entry(catalog, aid)
        removed += 1
    save_mesh_catalog(REPO_ROOT, catalog)

    rep.check("destroy::none_refused", not refused,
              "destroy refused generated-owned assets (guard misfire): {}".format(refused),
              code=FailureCode.MESH_DESTROY_FAILURE)
    rep.check("destroy::all_removed", removed == EXPECTED_ASSET_COUNT,
              "removed {} generated-owned assets (expected {})".format(removed, EXPECTED_ASSET_COUNT),
              code=FailureCode.MESH_DESTROY_FAILURE)
    remaining = len(_catalog_asset_ids())
    rep.check("destroy::catalog_empty", remaining == 0,
              "catalog holds {} record(s) after destroy (expected 0)".format(remaining),
              code=FailureCode.MESH_DESTROY_FAILURE)


def rebuild_phase(rep, pack, strict):
    rc, tail = _rebuild(pack, strict)
    rep.check("rebuild::create_mesh_assets", rc == 0,
              "create_mesh_assets rc={} ({})".format(rc, tail), code=LIF)
    n = len(_catalog_asset_ids())
    rep.check("rebuild::asset_count", n == EXPECTED_ASSET_COUNT,
              "catalog has {} assets (expected {})".format(n, EXPECTED_ASSET_COUNT), code=LIF)
    for script in ALL_VALIDATORS:
        ok, rc, tail = _validator_green(script, pack, strict)
        rep.check("rebuild::{}".format(script.replace(".py", "")), ok,
                  "{} rc={} ({})".format(script, rc, tail), code=LIF)


# =============================================================================
# main
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.2 MeshForge Intake lifecycle torture / regression gate.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)

    master_dir = tempfile.mkdtemp(prefix="wf_mesh_torture_master_")
    mapping = _snapshot_tree(_master_snapshot_paths(), master_dir)
    try:
        print("[mesh-lifecycle-torture] BASELINE")
        baseline_phase(rep, args.pack, strict)
        print("[mesh-lifecycle-torture] CORRUPTION ({} modes)".format(len(CORRUPTION_MODES)))
        corruption_phase(rep, args.pack, strict)
        print("[mesh-lifecycle-torture] OWNERSHIP SAFETY")
        ownership_safety_phase(rep, args.pack, strict)
        print("[mesh-lifecycle-torture] DESTROY")
        destroy_phase(rep, args.pack, strict)
        print("[mesh-lifecycle-torture] REBUILD / REVALIDATE")
        rebuild_phase(rep, args.pack, strict)
    finally:
        _restore_tree(mapping)
        shutil.rmtree(master_dir, ignore_errors=True)

    # -- post-restore: the tree must be byte-identical to its pre-torture state
    final_n = len(_catalog_asset_ids())
    rep.check("final::catalog_restored", final_n == EXPECTED_ASSET_COUNT,
              "post-restore catalog has {} assets (expected {})".format(final_n, EXPECTED_ASSET_COUNT),
              code=LIF)
    ok, rc, tail = _validator_green("validate_mesh_catalog.py", args.pack, strict)
    rep.check("final::catalog_validator_green", ok,
              "post-restore validate_mesh_catalog rc={} ({})".format(rc, tail), code=LIF)

    rep.finalize()
    rep.set_meta(build_meta(command="mesh-lifecycle-torture", pack=args.pack, strict=strict,
                            torture=True, status=rep.status, record_count=len(CORRUPTION_MODES),
                            extra={"corruption_modes": sorted(CORRUPTION_MODES),
                                   "expected_asset_count": EXPECTED_ASSET_COUNT}))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "mesh_lifecycle_torture"
    rep.write(report_dir, "mesh_lifecycle_torture_report.json")
    rep.print_summary("mesh-lifecycle-torture")
    print("[mesh-lifecycle-torture] corrupt->detect->repair->destroy->rebuild->revalidate "
          "cycle run ({} corruption modes)".format(len(CORRUPTION_MODES)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
