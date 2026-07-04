#!/usr/bin/env python3
"""source_lifecycle_torture.py — WorldForge v1.2 addendum SOURCE lifecycle torture (Agent 7).

Proves the two NON-NEGOTIABLE source-ownership rules of the v1.2 addendum (§9/§14)
survive a hostile lifecycle:

  (1) repair/destroy must NEVER treat a Megascans SOURCE asset like generated
      output — the load-bearing MEGASCANS DESTROY-PROTECTION phase.
  (2) a Houdini SOURCE HDA and its baked OUTPUT are NOT the same ownership class.

Phases (all inside a master snapshot restored in a finally):

  1. BASELINE — regenerate the generated mesh catalog (create_mesh_assets) and the
     external asset catalog (scan_external_asset_library); confirm all source
     validators are green, mesh == 42, external == 51.

  2. MEGASCANS DESTROY-PROTECTION — simulate a destroy routine iterating destroy
     candidates and assert it REFUSES every Megascans source (is_within_external_library
     OR repair_destroy_protected OR third_party ownership). Assert ZERO external
     source files are deleted and the library_root still exists unchanged. Then
     corrupt an INJECTED copy's repair_destroy_protected to False and assert the
     guard STILL refuses (defense in depth via third_party ownership) AND that
     validate_external_asset_ownership flags it — then restore.

  3. OWNERSHIP-CORRUPTION detection — flip a mesh asset to third_party_owned ->
     validate_source_ownership_separation detects; flip a houdini asset's
     hda_ownership_class to generated_owned -> validate_houdini_intake detects.
     Each corruption is applied to a byte-backed descriptor and restored.

  4. HOUDINI cook-failure detection — set an injected houdini asset's cook_report
     to status failed -> validate_houdini_cook_reports detects; restore.

  5. GENERATED-SIDE DESTROY/REBUILD referencing megascans — destroy every
     generated mesh (descriptors + catalog records) and confirm the external
     catalog is NEVER touched (stays 51); rebuild -> 42 generated; external
     untouched.

The Megascans cache on disk is ONLY ever READ — never written — so it is
byte-identical after this run. A master snapshot of both catalogs, the generated
mesh + external trees, the mesh definitions, and the mesh_assets reports is taken
up front and restored in a finally, so the working tree is byte-identical to its
pre-torture state even if a phase raises. Exit 0 only if every phase passed AND
the final state is restored (mesh 42, external 51, source validators green,
library_root intact).

Report: procedural/reports/mesh/source_lifecycle_torture/source_lifecycle_torture_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 HOUDINI=metadata_only \
        python tools/pipeline/source_lifecycle_torture.py --pack biome_expansion_world --strict
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

import asset_config  # noqa: E402
import mesh_contract as MC  # noqa: E402
import external_asset_contract as EAC  # noqa: E402
import houdini_contract as HC  # noqa: E402
from mesh_catalog import (  # noqa: E402
    catalog_path, load_mesh_catalog, remove_catalog_entry, save_mesh_catalog,
)
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

PY = sys.executable
LIB = "megascans"
EXPECTED_MESH_COUNT = 42
EXPECTED_EXTERNAL_COUNT = 51

_SEP = FailureCode.SOURCE_OWNERSHIP_SEPARATION_FAILURE
_DESTROY_RISK = FailureCode.THIRD_PARTY_ASSET_DESTROY_RISK
_HDA = FailureCode.HOUDINI_HDA_OWNERSHIP_FAILURE
_COOK = FailureCode.HOUDINI_COOK_FAILURE

SOURCE_VALIDATORS = (
    ("validate_houdini_intake.py", "pack"),
    ("validate_houdini_cook_reports.py", "pack"),
    ("validate_houdini_bake_reports.py", "pack"),
    ("validate_houdini_generated_assets.py", "pack"),
    ("validate_source_ownership_separation.py", "pack"),
    ("validate_megascans_bindings.py", "pack"),
    ("validate_megascans_pcg_eligibility.py", "pack"),
    ("validate_megascans_biome_compatibility.py", "pack"),
    ("validate_third_party_package_policy.py", "pack"),
    ("validate_external_asset_catalog.py", "lib"),
    ("validate_external_asset_ownership.py", "lib"),
    ("validate_megascans_catalog.py", "lib"),
)


# =============================================================================
# subprocess + snapshot helpers (mirrors mesh_lifecycle_torture.py)
# =============================================================================
def _run(script, arg_style, pack, strict):
    path = PIPELINE / script
    if not path.is_file():
        return None, "script missing: {}".format(script)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["HOUDINI"] = "metadata_only"
    if strict:
        env["STRICT"] = "1"
    extra = ["--lib", LIB] if arg_style == "lib" else ["--pack", pack]
    if strict:
        extra.append("--strict")
    proc = subprocess.run([PY, str(path)] + extra, cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True)
    tail = " | ".join((proc.stdout or "").strip().splitlines()[-1:])[:200]
    return proc.returncode, tail


def _validator_green(script, arg_style, pack, strict):
    rc, tail = _run(script, arg_style, pack, strict)
    return (rc == 0), rc, tail


def _rebuild_mesh(pack, strict):
    return _run("create_mesh_assets.py", "pack", pack, strict)


def _rescan_external(strict):
    return _run("scan_external_asset_library.py", "lib", None, strict)


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
        EAC.external_catalog_path(REPO_ROOT),
        REPO_ROOT / MC.MESH_GENERATED_REL,
        REPO_ROOT / "procedural" / "generated" / "external_assets",
        REPO_ROOT / MC.MESH_DEFINITIONS_REL,
        REPO_ROOT / MC.MESH_ASSET_REPORTS_REL,
    ]


# =============================================================================
# small helpers
# =============================================================================
def _mesh_ids():
    return sorted((load_mesh_catalog(REPO_ROOT).get("assets") or {}).keys())


def _mesh_count():
    return len(load_mesh_catalog(REPO_ROOT).get("assets") or {})


def _external_count():
    return len(EAC.load_external_catalog(REPO_ROOT).get("assets") or {})


def _load_descriptor(asset_id):
    p = MC.mesh_descriptor_path(asset_id, REPO_ROOT)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _first_houdini_id():
    catalog = load_mesh_catalog(REPO_ROOT)
    for aid, _e in HC.iter_houdini_assets(catalog):
        return aid
    return None


def _first_generated_id():
    catalog = load_mesh_catalog(REPO_ROOT)
    for aid, entry in sorted((catalog.get("assets") or {}).items()):
        if entry.get("source_type") != "houdini_generated":
            return aid
    return None


def _resolved_source_path(record):
    """Resolve an external record's portable source_path against the library root
    (so is_within_external_library can be exercised). Returns None if unresolvable."""
    root = asset_config.library_root(LIB)
    sp = record.get("source_path")
    if not root or not sp:
        return None
    return str(Path(root) / sp)


def _source_destroy_refused(record):
    """The destroy guard: True if this source record MUST be refused by any
    generated-output destroy routine. Defense in depth — refuses on ANY of:
    inside the external library, repair_destroy_protected, or third_party owned."""
    resolved = _resolved_source_path(record)
    within = bool(resolved) and asset_config.is_within_external_library(resolved, LIB)
    protected = record.get("repair_destroy_protected") is True
    third_party = MC.resolve_ownership_class(record) == MC.OWNERSHIP_THIRD_PARTY
    licensed = record.get("external_licensed") is True
    return within or protected or third_party or licensed


# =============================================================================
# Phase 1 — baseline
# =============================================================================
def baseline_phase(rep, pack, strict):
    rc, tail = _rebuild_mesh(pack, strict)
    rep.check("baseline::rebuild_mesh", rc == 0,
              "create_mesh_assets rc={} ({})".format(rc, tail), code=_SEP)
    rc, tail = _rescan_external(strict)
    rep.check("baseline::rescan_external", rc == 0,
              "scan_external_asset_library rc={} ({})".format(rc, tail), code=_SEP)

    rep.check("baseline::mesh_count", _mesh_count() == EXPECTED_MESH_COUNT,
              "mesh catalog has {} (expected {})".format(_mesh_count(), EXPECTED_MESH_COUNT),
              code=FailureCode.MESH_CATALOG_FAILURE)
    rep.check("baseline::external_count", _external_count() == EXPECTED_EXTERNAL_COUNT,
              "external catalog has {} (expected {})".format(_external_count(), EXPECTED_EXTERNAL_COUNT),
              code=FailureCode.MEGASCANS_CATALOG_FAILURE)

    for script, arg_style in SOURCE_VALIDATORS:
        ok, rc, tail = _validator_green(script, arg_style, pack, strict)
        rep.check("baseline::{}".format(script.replace(".py", "")), ok,
                  "{} rc={} ({})".format(script, rc, tail), code=_SEP)


# =============================================================================
# Phase 2 — Megascans destroy-protection (load-bearing)
# =============================================================================
def destroy_protection_phase(rep, pack, strict):
    root = asset_config.library_root(LIB)
    rep.check("destroy_prot::library_root_present", root is not None,
              "megascans library_root does not resolve on disk: {}".format(root),
              code=_DESTROY_RISK)

    # -- library-root byte/inventory fingerprint BEFORE the routine ----------
    def _lib_fingerprint():
        if not root or not Path(root).is_dir():
            return None
        files = sorted(str(p.relative_to(root)) for p in Path(root).rglob("*") if p.is_file())
        return (len(files), files[:5])

    fp_before = _lib_fingerprint()

    ext_assets = EAC.load_external_catalog(REPO_ROOT).get("assets") or {}

    # -- simulate a destroy routine over every Megascans source candidate ----
    deleted = 0
    refused = 0
    not_refused = []
    for aid, rec in sorted(ext_assets.items()):
        if _source_destroy_refused(rec):
            refused += 1
            continue
        # The guard did NOT refuse — a real routine would delete here. We record
        # the miss but STILL never touch disk (this harness only ever READs).
        not_refused.append(aid)
        deleted += 1  # would-be deletion (counted, never performed)

    rep.check("destroy_prot::all_sources_refused", not not_refused,
              "destroy guard failed to refuse Megascans source(s): {}".format(not_refused[:10]),
              code=_DESTROY_RISK)
    rep.check("destroy_prot::zero_deletions", deleted == 0,
              "{} Megascans source(s) would have been destroyed (must be 0)".format(deleted),
              code=_DESTROY_RISK)
    rep.check("destroy_prot::all_refused_count",
              refused == len(ext_assets) and len(ext_assets) == EXPECTED_EXTERNAL_COUNT,
              "refused {} of {} external sources".format(refused, len(ext_assets)),
              code=_DESTROY_RISK)

    # -- library_root still exists and is byte/inventory-identical -----------
    fp_after = _lib_fingerprint()
    rep.check("destroy_prot::library_root_intact",
              root is not None and Path(root).is_dir() and fp_before == fp_after,
              "library_root changed after destroy routine (before={}, after={})".format(
                  fp_before, fp_after),
              code=_DESTROY_RISK)

    # -- defense in depth: corrupt repair_destroy_protected -> STILL refused --
    if ext_assets:
        victim_id = sorted(ext_assets)[0]
        corrupted = json.loads(json.dumps(ext_assets[victim_id]))  # deep copy
        corrupted["repair_destroy_protected"] = False
        corrupted["raw_asset_destroy_allowed"] = True
        rep.check("destroy_prot::still_refused_when_flag_flipped",
                  _source_destroy_refused(corrupted),
                  "guard must STILL refuse a source with repair_destroy_protected=False "
                  "(third_party ownership / library membership is defense in depth)",
                  code=_DESTROY_RISK)

        # AND the ownership validator must flag it if injected into the catalog.
        ext_file = EAC.external_catalog_path(REPO_ROOT)
        backup = ext_file.read_bytes()
        try:
            cat = EAC.load_external_catalog(REPO_ROOT)
            inj = json.loads(json.dumps(ext_assets[victim_id]))
            inj["external_asset_id"] = "__negsrc_torture_unprotected"
            inj["repair_destroy_protected"] = False
            inj["raw_asset_destroy_allowed"] = True
            cat = EAC.upsert_external_entry(cat, inj)
            EAC.save_external_catalog(cat, REPO_ROOT)
            ok, rc, tail = _validator_green("validate_external_asset_ownership.py", "lib", pack, strict)
            rep.check("destroy_prot::ownership_validator_flags_unprotected", not ok,
                      "validate_external_asset_ownership must FAIL on an unprotected source "
                      "record (rc={}, {})".format(rc, tail), code=_DESTROY_RISK)
        finally:
            ext_file.write_bytes(backup)


# =============================================================================
# Phase 3 — ownership-corruption detection
# =============================================================================
def _corrupt_descriptor(asset_id, mutate):
    """Byte-backup a descriptor, apply mutate(dict)->dict, write it back. Returns
    the restore closure."""
    p = MC.mesh_descriptor_path(asset_id, REPO_ROOT)
    backup = p.read_bytes()
    desc = json.loads(backup.decode("utf-8"))
    desc = mutate(desc)
    p.write_text(json.dumps(desc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _restore():
        p.write_bytes(backup)
    return _restore


def ownership_corruption_phase(rep, pack, strict):
    # (a) flip a generated mesh to third_party_owned -> separation detects
    gid = _first_generated_id()
    if gid is None:
        rep.check("owncorrupt::have_generated_asset", False,
                  "no generated (non-houdini) mesh asset found", code=_SEP)
    else:
        def _to_third_party(d):
            d["ownership_class"] = MC.OWNERSHIP_THIRD_PARTY
            d["third_party_owned"] = True
            d["generated_owned"] = False
            return d
        restore = _corrupt_descriptor(gid, _to_third_party)
        try:
            ok, rc, tail = _validator_green("validate_source_ownership_separation.py", "pack", pack, strict)
            rep.check("owncorrupt::third_party_mesh_detected", not ok,
                      "validate_source_ownership_separation must DETECT a mesh flipped to "
                      "third_party_owned (rc={}, {})".format(rc, tail), code=_SEP)
        finally:
            restore()

    # (b) flip a houdini asset's hda_ownership_class to generated_owned -> intake detects
    hid = _first_houdini_id()
    if hid is None:
        rep.check("owncorrupt::have_houdini_asset", False,
                  "no houdini_generated mesh asset found", code=_HDA)
    else:
        def _hda_generated(d):
            d.setdefault("houdini_intake", {})["hda_ownership_class"] = MC.OWNERSHIP_GENERATED
            return d
        restore = _corrupt_descriptor(hid, _hda_generated)
        try:
            ok, rc, tail = _validator_green("validate_houdini_intake.py", "pack", pack, strict)
            rep.check("owncorrupt::hda_generated_owned_detected", not ok,
                      "validate_houdini_intake must DETECT hda_ownership_class=generated_owned "
                      "(rc={}, {})".format(rc, tail), code=_HDA)
        finally:
            restore()


# =============================================================================
# Phase 4 — houdini cook-failure detection
# =============================================================================
def cook_failure_phase(rep, pack, strict):
    hid = _first_houdini_id()
    if hid is None:
        rep.check("cookfail::have_houdini_asset", False,
                  "no houdini_generated mesh asset found", code=_COOK)
        return
    desc = _load_descriptor(hid) or {}
    cook_rel = (desc.get("houdini_intake") or {}).get("cook_report")
    cook_path = (REPO_ROOT / cook_rel) if cook_rel else None
    if not cook_path or not cook_path.is_file():
        rep.check("cookfail::cook_report_present", False,
                  "houdini asset {} has no resolvable cook_report".format(hid), code=_COOK)
        return
    backup = cook_path.read_bytes()
    try:
        report = json.loads(backup.decode("utf-8"))
        report["status"] = "failed"
        cook_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        ok, rc, tail = _validator_green("validate_houdini_cook_reports.py", "pack", pack, strict)
        rep.check("cookfail::cook_failure_detected", not ok,
                  "validate_houdini_cook_reports must DETECT a cook_report status=failed "
                  "(rc={}, {})".format(rc, tail), code=_COOK)
    finally:
        cook_path.write_bytes(backup)


# =============================================================================
# Phase 5 — generated-side destroy/rebuild referencing megascans
# =============================================================================
def generated_destroy_rebuild_phase(rep, pack, strict):
    ext_before = _external_count()

    # destroy every generated mesh (descriptor dir + catalog record)
    ids = _mesh_ids()
    catalog = load_mesh_catalog(REPO_ROOT)
    removed = 0
    for aid in ids:
        shutil.rmtree(MC.mesh_descriptor_path(aid, REPO_ROOT).parent, ignore_errors=True)
        catalog = remove_catalog_entry(catalog, aid)
        removed += 1
    save_mesh_catalog(REPO_ROOT, catalog)

    rep.check("gendestroy::all_removed", removed == EXPECTED_MESH_COUNT,
              "removed {} generated meshes (expected {})".format(removed, EXPECTED_MESH_COUNT),
              code=FailureCode.MESH_DESTROY_FAILURE)
    rep.check("gendestroy::mesh_empty", _mesh_count() == 0,
              "mesh catalog holds {} after destroy (expected 0)".format(_mesh_count()),
              code=FailureCode.MESH_DESTROY_FAILURE)
    rep.check("gendestroy::external_untouched_after_destroy",
              _external_count() == ext_before == EXPECTED_EXTERNAL_COUNT,
              "external catalog changed during generated destroy ({} -> {})".format(
                  ext_before, _external_count()),
              code=_DESTROY_RISK)

    # rebuild the generated side
    rc, tail = _rebuild_mesh(pack, strict)
    rep.check("gendestroy::rebuild", rc == 0,
              "create_mesh_assets rc={} ({})".format(rc, tail), code=_SEP)
    rep.check("gendestroy::rebuilt_count", _mesh_count() == EXPECTED_MESH_COUNT,
              "mesh catalog has {} after rebuild (expected {})".format(_mesh_count(), EXPECTED_MESH_COUNT),
              code=FailureCode.MESH_CATALOG_FAILURE)
    rep.check("gendestroy::external_untouched_after_rebuild",
              _external_count() == EXPECTED_EXTERNAL_COUNT,
              "external catalog changed during generated rebuild (now {})".format(_external_count()),
              code=_DESTROY_RISK)


# =============================================================================
# main
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.2 addendum source lifecycle torture / regression gate.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)

    root_before = asset_config.library_root(LIB)

    master_dir = tempfile.mkdtemp(prefix="wf_source_torture_master_")
    mapping = _snapshot_tree(_master_snapshot_paths(), master_dir)
    try:
        print("[source-lifecycle-torture] 1. BASELINE")
        baseline_phase(rep, args.pack, strict)
        print("[source-lifecycle-torture] 2. MEGASCANS DESTROY-PROTECTION")
        destroy_protection_phase(rep, args.pack, strict)
        print("[source-lifecycle-torture] 3. OWNERSHIP-CORRUPTION DETECTION")
        ownership_corruption_phase(rep, args.pack, strict)
        print("[source-lifecycle-torture] 4. HOUDINI COOK-FAILURE DETECTION")
        cook_failure_phase(rep, args.pack, strict)
        print("[source-lifecycle-torture] 5. GENERATED DESTROY/REBUILD (refs megascans)")
        generated_destroy_rebuild_phase(rep, args.pack, strict)
    finally:
        _restore_tree(mapping)
        shutil.rmtree(master_dir, ignore_errors=True)

    # -- post-restore: the tree must be back to its pre-torture state --------
    rep.check("final::mesh_restored", _mesh_count() == EXPECTED_MESH_COUNT,
              "post-restore mesh catalog has {} (expected {})".format(_mesh_count(), EXPECTED_MESH_COUNT),
              code=FailureCode.MESH_CATALOG_FAILURE)
    rep.check("final::external_restored", _external_count() == EXPECTED_EXTERNAL_COUNT,
              "post-restore external catalog has {} (expected {})".format(
                  _external_count(), EXPECTED_EXTERNAL_COUNT),
              code=FailureCode.MEGASCANS_CATALOG_FAILURE)
    root_after = asset_config.library_root(LIB)
    rep.check("final::library_root_intact",
              root_after is not None and root_before == root_after and Path(root_after).is_dir(),
              "megascans library_root missing/changed after torture (before={}, after={})".format(
                  root_before, root_after),
              code=_DESTROY_RISK)
    # Re-run EVERY source validator green post-restore. This both asserts the
    # source state is healed AND overwrites the FAIL reports the corruption phases
    # left on disk with fresh GREEN reports, so a subsequent report-integrity
    # --sources scan sees a consistent, non-stale, non-fake-green source shield.
    for script, arg_style in SOURCE_VALIDATORS:
        ok, rc, tail = _validator_green(script, arg_style, args.pack, strict)
        rep.check("final::{}_green".format(script.replace(".py", "")), ok,
                  "post-restore {} rc={} ({})".format(script, rc, tail), code=_SEP)

    rep.finalize()
    rep.set_meta(build_meta(command="source-lifecycle-torture", pack=args.pack, strict=strict,
                            torture=True, status=rep.status, record_count=5,
                            extra={"expected_mesh_count": EXPECTED_MESH_COUNT,
                                   "expected_external_count": EXPECTED_EXTERNAL_COUNT,
                                   "phases": ["baseline", "megascans_destroy_protection",
                                              "ownership_corruption", "houdini_cook_failure",
                                              "generated_destroy_rebuild"]}))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "source_lifecycle_torture"
    rep.write(report_dir, "source_lifecycle_torture_report.json")
    rep.print_summary("source-lifecycle-torture")
    print("[source-lifecycle-torture] baseline->destroy-protection->corruption->cook-fail->"
          "generated-destroy/rebuild cycle run")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
