#!/usr/bin/env python3
"""test_negative_sources.py — WorldForge v1.2 addendum SOURCE negative-fixture gate (Agent 7).

Every known-bad SOURCE fixture under tests/fixtures/invalid_sources/ must be
REJECTED by the source lane that owns its defect. This mirrors the v1.2
test_negative_mesh.py reference harness in shape and safety: a bad record is
injected into the OWNING catalog (in-memory byte backup taken first), the owning
validator is run as a subprocess, its non-zero exit is asserted, and the catalog
is restored in a finally — so the real mesh catalog (42), the external catalog
(51), and every generated descriptor tree are never left dirty even on an
assertion failure or a crash mid-run.

Two fixture families (addendum §5/§6/§8/§14):

  HOUDINI — a bad ``houdini_generated`` mesh descriptor + catalog entry is
    injected (cloned from a real houdini asset, ONE targeted mutation applied),
    and the owning houdini validator is run with HOUDINI=metadata_only.

  MEGASCANS — a bad external record is injected into the external asset catalog
    (cloned from a real Megascans record, ONE targeted mutation applied), and the
    owning external/megascans validator is run.

  (plus the SEPARATION case external_in_generated_catalog, which injects a
   third_party_owned record into the MESH catalog and asserts
   validate_source_ownership_separation rejects it.)

Because each injected record is a CLONE of a real, currently-green record with a
single mutation, the owning validator fails for exactly the injected defect — no
other reason. After every case the harness restores both catalogs and proves the
source lanes self-healed (mesh == 42, external == 51, no __negsrc leakage, all
source validators green again). A fixture wrongly ACCEPTED is tagged with the
FailureCode of its lane. Exit 0 iff every fixture was rejected AND the source
state self-healed.

The two NON-NEGOTIABLE rules (addendum §14) this gate proves cannot be violated:
  (1) repair/destroy must NEVER treat a Megascans source asset like generated
      output  (source_marked_generated_owned / not_repair_destroy_protected /
      raw_asset_destroy_allowed_true / external_in_generated_catalog).
  (2) a Houdini source HDA and its baked output are NOT the same ownership class
      (hda_marked_generated_owned / unknown_hda_ownership_class).

Report: procedural/reports/mesh/test_negative_sources/test_negative_sources_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 HOUDINI=metadata_only \
        python tools/pipeline/test_negative_sources.py --pack biome_expansion_world --strict
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

import mesh_contract as MC  # noqa: E402
import external_asset_contract as EAC  # noqa: E402
import houdini_contract as HC  # noqa: E402
from mesh_catalog import (  # noqa: E402
    catalog_path, load_mesh_catalog, save_mesh_catalog, upsert_catalog_entry,
)
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

PY = sys.executable
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "invalid_sources"
NEG_CODE_DEFAULT = FailureCode.SOURCE_OWNERSHIP_SEPARATION_FAILURE

# Map a fixture's declared expected_code name -> the concrete FailureCode string,
# so a wrongly-accepted fixture is tagged with the code of the lane it belongs to.
def _code_for(name):
    return getattr(FailureCode, name, NEG_CODE_DEFAULT)

# The 12 source validators (with the CLI arg style each takes) re-run to prove the
# source state self-healed after the whole negative sweep.
SELFHEAL_VALIDATORS = (
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

EXPECTED_MESH_COUNT = len(load_mesh_catalog(REPO_ROOT).get("assets") or {})
EXPECTED_EXTERNAL_COUNT = len(EAC.load_external_catalog(REPO_ROOT).get("assets") or {})

# Temp id prefix for every injected record / descriptor / report — used for
# leak-detection in the self-heal check.
NEG_PREFIX = "__negsrc_"


# =============================================================================
# subprocess helper
# =============================================================================
def _run(script, arg_style, pack, lib, strict):
    """Run a source validator as a subprocess; return (returncode, tail)."""
    path = PIPELINE / script
    if not path.is_file():
        return None, "script missing: {}".format(script)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["HOUDINI"] = "metadata_only"
    if strict:
        env["STRICT"] = "1"
    if arg_style == "lib":
        extra = ["--lib", lib]
    else:
        extra = ["--pack", pack]
    if strict:
        extra.append("--strict")
    proc = subprocess.run([PY, str(path)] + extra, cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True)
    tail = " | ".join((proc.stdout or "").strip().splitlines()[-1:])[:200]
    return proc.returncode, tail


# =============================================================================
# base-record loaders (clone real, currently-green records at runtime)
# =============================================================================
def _first_houdini_descriptor():
    catalog = load_mesh_catalog(REPO_ROOT)
    for aid, _entry in HC.iter_houdini_assets(catalog):
        p = MC.mesh_descriptor_path(aid, REPO_ROOT)
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def _first_generated_descriptor():
    """First NON-houdini generated mesh descriptor (base for the separation case)."""
    catalog = load_mesh_catalog(REPO_ROOT)
    for aid, entry in sorted((catalog.get("assets") or {}).items()):
        if entry.get("source_type") == "houdini_generated":
            continue
        p = MC.mesh_descriptor_path(aid, REPO_ROOT)
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def _first_external_record():
    catalog = EAC.load_external_catalog(REPO_ROOT)
    assets = catalog.get("assets") or {}
    for aid in sorted(assets):
        return copy.deepcopy(assets[aid])
    return None


# =============================================================================
# patch application
# =============================================================================
def _set_dotted(obj, dotted, value):
    keys = dotted.split(".")
    cur = obj
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def _del_dotted(obj, dotted):
    keys = dotted.split(".")
    cur = obj
    for k in keys[:-1]:
        if not isinstance(cur, dict) or k not in cur:
            return
        cur = cur[k]
    if isinstance(cur, dict):
        cur.pop(keys[-1], None)


def _apply_patch(record, patch, temp_id, tmp_dirs):
    """Apply a fixture patch to a cloned record in place. Writes temp report files
    (tracked in tmp_dirs for finally-cleanup) for failed/missing report cases."""
    for dotted, value in (patch.get("set") or {}).items():
        _set_dotted(record, dotted, value)
    for dotted in (patch.get("delete") or []):
        _del_dotted(record, dotted)

    stage = patch.get("failed_report")
    if stage:
        rdir = REPO_ROOT / MC.MESH_REPORTS_REL / temp_id
        rdir.mkdir(parents=True, exist_ok=True)
        tmp_dirs.append(rdir)
        intake = record.get("houdini_intake") or {}
        report = {
            "stage": stage,
            "status": "failed",
            "hda_id": intake.get("hda_id"),
            "generated_at_utc": "2026-07-04T00:00:00+00:00",
            "note": "negative-fixture failed-report stub (transient; deleted in finally)",
        }
        rpath = rdir / "{}_report.json".format(stage)
        rpath.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
        _set_dotted(record, "houdini_intake.{}_report".format(stage),
                    rpath.relative_to(REPO_ROOT).as_posix())

    miss = patch.get("missing_report")
    if miss:
        _set_dotted(record, "houdini_intake.{}_report".format(miss),
                    "procedural/reports/mesh/{}_missing/{}_report.json".format(temp_id, miss))


# =============================================================================
# mesh-side injection (houdini + separation): temp descriptor + catalog entry
# =============================================================================
def _mesh_catalog_entry(temp_id, desc):
    return {
        "asset_id": temp_id,
        "mesh_family": desc.get("mesh_family"),
        "source_type": desc.get("source_type"),
        "final_asset_path": desc.get("final_asset_path"),
        "registry_id": "mesh_catalog:{}".format(temp_id),
        "provenance_id": desc.get("provenance_id"),
        "pcg_eligibility": desc.get("pcg_eligibility"),
        "biome_compatibility": desc.get("biome_compatibility"),
        "poi_compatibility": desc.get("poi_compatibility"),
        "material_bindings": desc.get("material_bindings"),
        "collision_profile": desc.get("collision_profile"),
        "bounds": desc.get("bounds"),
        "budget_class": desc.get("budget_class"),
        "descriptor_path": desc.get("descriptor_path"),
        "package_status": "pending",
        "validation_status": "pending",
        "lifecycle_status": "created",
    }


def _inject_mesh(temp_id, base_desc, patch, tmp_dirs):
    """Clone a real mesh descriptor, apply the patch, write descriptor + catalog
    entry. Returns the descriptor output dir (for finally-cleanup)."""
    desc = copy.deepcopy(base_desc)
    desc["asset_id"] = temp_id
    out_dir = REPO_ROOT / MC.MESH_GENERATED_REL / temp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    desc["descriptor_path"] = (out_dir / "descriptor.json").relative_to(REPO_ROOT).as_posix()

    _apply_patch(desc, patch, temp_id, tmp_dirs)

    (out_dir / "descriptor.json").write_text(
        json.dumps(desc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    catalog = load_mesh_catalog(REPO_ROOT)
    catalog = upsert_catalog_entry(catalog, _mesh_catalog_entry(temp_id, desc))
    save_mesh_catalog(REPO_ROOT, catalog)
    return out_dir


def _inject_external(temp_id, base_rec, patch, tmp_dirs):
    """Clone a real external record, apply the patch, upsert into the external
    catalog under a fresh id."""
    rec = copy.deepcopy(base_rec)
    rec["external_asset_id"] = temp_id
    _apply_patch(rec, patch, temp_id, tmp_dirs)
    catalog = EAC.load_external_catalog(REPO_ROOT)
    catalog = EAC.upsert_external_entry(catalog, rec)
    EAC.save_external_catalog(catalog, REPO_ROOT)


# =============================================================================
# one negative case (inject -> run owning validator -> assert reject -> restore)
# =============================================================================
def _run_case(rep, fx, pack, lib, strict, bases):
    case = fx["case"]
    family = fx["family"]
    script = fx["owning_validator"]
    arg_style = fx.get("validator_arg", "pack")
    patch = fx.get("patch") or {}
    code = _code_for(fx.get("expected_code", ""))
    temp_id = NEG_PREFIX + case

    mesh_file = catalog_path(REPO_ROOT)
    ext_file = EAC.external_catalog_path(REPO_ROOT)
    mesh_backup = mesh_file.read_bytes() if mesh_file.is_file() else None
    ext_backup = ext_file.read_bytes() if ext_file.is_file() else None
    tmp_dirs = []
    out_dir = None

    try:
        if family in ("houdini", "separation"):
            base = bases["houdini"] if family == "houdini" else bases["generated"]
            if base is None:
                rep.check("source_negative::{}".format(case), False,
                          "no base {} descriptor available".format(family), code=code)
                print("FAIL  {} (no base descriptor)".format(case))
                return
            out_dir = _inject_mesh(temp_id, base, patch, tmp_dirs)
        else:  # megascans
            base = bases["external"]
            if base is None:
                rep.check("source_negative::{}".format(case), False,
                          "no base external record available", code=code)
                print("FAIL  {} (no base external record)".format(case))
                return
            _inject_external(temp_id, base, patch, tmp_dirs)

        rc, tail = _run(script, arg_style, pack, lib, strict)
        rejected = rc is not None and rc != 0
        rep.check("source_negative::{}".format(case), rejected,
                  "{} rc={} ({})".format(script, rc, tail), code=code)
        print("{}  {} -> {} (rc={})".format(
            "PASS" if rejected else "FAIL  ACCEPTED", case, script, rc))
    finally:
        if mesh_backup is not None:
            mesh_file.write_bytes(mesh_backup)
        if ext_backup is not None:
            ext_file.write_bytes(ext_backup)
        if out_dir is not None:
            shutil.rmtree(out_dir, ignore_errors=True)
        for d in tmp_dirs:
            shutil.rmtree(d, ignore_errors=True)


# =============================================================================
# self-heal check
# =============================================================================
def selfheal_check(rep, pack, lib, strict):
    mesh_n = len(load_mesh_catalog(REPO_ROOT).get("assets") or {})
    ext_n = len(EAC.load_external_catalog(REPO_ROOT).get("assets") or {})
    rep.check("selfheal::mesh_count", mesh_n == EXPECTED_MESH_COUNT,
              "mesh catalog has {} assets (expected {})".format(mesh_n, EXPECTED_MESH_COUNT),
              code=FailureCode.MESH_CATALOG_FAILURE)
    rep.check("selfheal::external_count", ext_n == EXPECTED_EXTERNAL_COUNT,
              "external catalog has {} records (expected {})".format(ext_n, EXPECTED_EXTERNAL_COUNT),
              code=FailureCode.MEGASCANS_CATALOG_FAILURE)

    mesh_assets = load_mesh_catalog(REPO_ROOT).get("assets") or {}
    ext_assets = EAC.load_external_catalog(REPO_ROOT).get("assets") or {}
    stray_records = sorted([a for a in mesh_assets if a.startswith(NEG_PREFIX)]
                           + [a for a in ext_assets if a.startswith(NEG_PREFIX)])
    rep.check("selfheal::no_negsrc_records", not stray_records,
              "stray negative-fixture catalog records: {}".format(stray_records),
              code=FailureCode.MESH_CATALOG_FAILURE)

    gen_root = REPO_ROOT / MC.MESH_GENERATED_REL
    stray_dirs = sorted(p.name for p in gen_root.iterdir()
                        if p.is_dir() and p.name.startswith(NEG_PREFIX)) if gen_root.is_dir() else []
    rep.check("selfheal::no_negsrc_dirs", not stray_dirs,
              "stray negative-fixture descriptor dirs: {}".format(stray_dirs),
              code=FailureCode.MESH_CATALOG_FAILURE)

    for script, arg_style in SELFHEAL_VALIDATORS:
        rc, tail = _run(script, arg_style, pack, lib, strict)
        rep.check("selfheal::{}".format(script.replace(".py", "")), rc == 0,
                  "{} rc={} ({})".format(script, rc, tail),
                  code=FailureCode.SOURCE_OWNERSHIP_SEPARATION_FAILURE)


# =============================================================================
# main
# =============================================================================
def _load_fixtures():
    if not FIXTURES_DIR.is_dir():
        return []
    out = []
    for p in sorted(FIXTURES_DIR.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            out.append({"case": p.stem, "family": "invalid", "owning_validator": "",
                        "_parse_error": str(exc)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.2 addendum source negative-fixture gate.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--lib", default="megascans")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    fixtures = _load_fixtures()

    # Master byte-backup of both catalogs (defense in depth beside per-case restore).
    mesh_file = catalog_path(REPO_ROOT)
    ext_file = EAC.external_catalog_path(REPO_ROOT)
    mesh_master = mesh_file.read_bytes() if mesh_file.is_file() else None
    ext_master = ext_file.read_bytes() if ext_file.is_file() else None

    bases = {
        "houdini": _first_houdini_descriptor(),
        "generated": _first_generated_descriptor(),
        "external": _first_external_record(),
    }

    try:
        if not fixtures:
            rep.error("no source negative fixtures under {}".format(FIXTURES_DIR))
        else:
            print("[source-negative] {} fixtures".format(len(fixtures)))
            for fx in fixtures:
                if fx.get("_parse_error"):
                    rep.check("source_negative::{}".format(fx.get("case")), False,
                              "fixture unparseable: {}".format(fx["_parse_error"]),
                              code=NEG_CODE_DEFAULT)
                    continue
                _run_case(rep, fx, args.pack, args.lib, strict, bases)
    finally:
        if mesh_master is not None:
            mesh_file.write_bytes(mesh_master)
        if ext_master is not None:
            ext_file.write_bytes(ext_master)

    print("[source-negative] SELF-HEAL check")
    selfheal_check(rep, args.pack, args.lib, strict)

    rep.finalize()
    rep.set_meta(build_meta(command="source-negative-validators", pack=args.pack,
                            strict=strict, status=rep.status, record_count=len(fixtures),
                            extra={"fixtures": sorted(fx.get("case") for fx in fixtures),
                                   "houdini_cases": sorted(fx.get("case") for fx in fixtures
                                                           if fx.get("family") == "houdini"),
                                   "megascans_cases": sorted(fx.get("case") for fx in fixtures
                                                             if fx.get("family") == "megascans"),
                                   "separation_cases": sorted(fx.get("case") for fx in fixtures
                                                              if fx.get("family") == "separation")}))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "test_negative_sources"
    rep.write(report_dir, "test_negative_sources_report.json")
    rep.print_summary("source-negative")
    print("[source-negative] {} source fixtures exercised".format(len(fixtures)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
