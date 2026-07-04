#!/usr/bin/env python3
"""test_negative_mesh.py — WorldForge v1.2 MeshForge Intake negative-fixture gate (Agent 7).

Every known-bad mesh-asset fixture under tests/fixtures/invalid_mesh_assets/ must
be REJECTED by the layer that owns its defect. A negative harness only earns trust
if it also proves it left nothing behind — so after exercising every fixture it
re-asserts the real catalog is byte-for-byte healed (exactly 24 assets, no
__negfix_* leakage) and re-runs all 10 mesh validators green.

Two phases:

  1. INTAKE — for every fixture in the intake set, run register_mesh_asset.py
     (--definition-path <fixture> --strict) as a subprocess and assert it exits
     non-zero (the intake gate refuses the definition before writing anything).

  2. DIMENSION — for every dimension fixture, safely inject a materialized
     descriptor + catalog record for a unique temp asset id (__negfix_<case>),
     run the SPECIFIC owning validator, and assert it exits non-zero (the injected
     bad asset makes that lane fail). The real catalog bytes are backed up in
     memory and restored in a finally, and the temp descriptor tree is deleted,
     so the real catalog/tree is never left dirty even on assertion failure.

After the dimension phase the harness reloads the catalog and proves it self-healed
(24 assets, no __negfix_* records/dirs, all 10 validators green). A fixture that is
wrongly ACCEPTED is a MESH_NEGATIVE_FIXTURE_FAILURE. Exit 0 iff every fixture was
rejected AND the catalog self-healed.

Report: procedural/reports/mesh/test_negative_mesh/test_negative_mesh_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/test_negative_mesh.py --pack biome_expansion_world --strict
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "tools" / "pipeline"
sys.path.insert(0, str(PIPELINE))

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

import mesh_contract as MC  # noqa: E402
from mesh_catalog import (  # noqa: E402
    catalog_path, load_mesh_catalog, save_mesh_catalog, upsert_catalog_entry,
)
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

PY = sys.executable
FIXTURES_DIR = REPO_ROOT / MC.MESH_INVALID_FIXTURES_REL
REGISTRAR = PIPELINE / "register_mesh_asset.py"
NEG_CODE = FailureCode.MESH_NEGATIVE_FIXTURE_FAILURE

# Fixtures the INTAKE gate (register_mesh_asset) must refuse.
INTAKE_CASES = (
    "bad_temp_final_path",
    "bad_intermediate_final_path",
    "bad_unowned_root",
    "missing_source_hash",
    "unknown_source_type",
    "unknown_mesh_family",
    "generated_owned_false",
    "human_owned_true",
    "missing_required_field",
    "unknown_field_strict",
)

# Fixtures a SPECIFIC downstream validator must reject once injected into the
# catalog. Maps case -> the owning validator script.
DIMENSION_VALIDATOR = {
    "zero_bounds": "validate_mesh_collision_bounds.py",
    "bounds_too_large": "validate_mesh_collision_bounds.py",
    "missing_collision_profile": "validate_mesh_collision_bounds.py",
    "material_incompatible_biome": "validate_mesh_material_bindings.py",
    "material_path_missing": "validate_mesh_material_bindings.py",
    "pcg_allowed_without_rules": "validate_mesh_pcg_eligibility.py",
    "pcg_disallowed_consumed": "validate_mesh_pcg_eligibility.py",
    "missing_pcg_eligibility": "validate_mesh_pcg_eligibility.py",
    "overbudget_raytrace_no_policy": "validate_mesh_rendering_budgets.py",
}

# The full 10-validator mesh gate, re-run to prove the catalog self-healed.
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

EXPECTED_ASSET_COUNT = len(list((REPO_ROOT / "procedural" / "definitions" / "mesh_assets").glob("*.yaml")))


# =============================================================================
# subprocess helpers
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


def _run_registrar(fixture, strict):
    extra = ["--definition-path", str(fixture)]
    if strict:
        extra.append("--strict")
    return _run("register_mesh_asset.py", extra, strict)


# =============================================================================
# safe catalog injection
# =============================================================================
def _inject_descriptor(temp_id, fixture):
    """Materialize a descriptor.json for a temp asset from a fixture. Returns desc."""
    out_dir = REPO_ROOT / MC.MESH_GENERATED_REL / temp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    desc = dict(fixture)
    desc["asset_id"] = temp_id
    desc["descriptor_path"] = (out_dir / "descriptor.json").relative_to(REPO_ROOT).as_posix()
    desc["provenance"] = {
        "generator": "test_negative_mesh",
        "generator_version": "1.2.0",
        "inputs": [],
        "note": "negative-fixture injection stub (transient; restored in finally)",
    }
    desc["provenance_id"] = "prov_{}".format(temp_id)
    desc["registry_id"] = "mesh_catalog:{}".format(temp_id)
    desc["registry_owner"] = "worldforge_mesh_catalog"
    with (out_dir / "descriptor.json").open("w", encoding="utf-8") as fh:
        json.dump(desc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return desc, out_dir


def _catalog_entry(temp_id, fixture, desc):
    """Build a catalog entry for the injected temp asset from the fixture fields."""
    return {
        "asset_id": temp_id,
        "mesh_family": fixture.get("mesh_family"),
        "source_type": fixture.get("source_type"),
        "final_asset_path": fixture.get("final_asset_path"),
        "registry_id": desc["registry_id"],
        "provenance_id": desc["provenance_id"],
        "pcg_eligibility": fixture.get("pcg_eligibility"),
        "biome_compatibility": fixture.get("biome_compatibility"),
        "poi_compatibility": fixture.get("poi_compatibility"),
        "material_bindings": fixture.get("material_bindings"),
        "collision_profile": fixture.get("collision_profile"),
        "bounds": fixture.get("bounds"),
        "budget_class": fixture.get("budget_class"),
        "descriptor_path": desc["descriptor_path"],
        "package_status": "pending",
        "validation_status": "pending",
        "lifecycle_status": "created",
    }


# =============================================================================
# phases
# =============================================================================
def intake_phase(rep, strict):
    """Every intake fixture must be refused by register_mesh_asset (non-zero exit)."""
    for case in INTAKE_CASES:
        fx = FIXTURES_DIR / (case + ".yaml")
        if not fx.is_file():
            rep.check("intake::{}".format(case), False,
                      "fixture missing: {}".format(fx), code=NEG_CODE)
            print("FAIL  MISSING fixture: {}".format(fx.name))
            continue
        rc, tail = _run_registrar(fx, strict)
        rejected = rc is not None and rc != 0
        rep.check("intake::{}".format(case), rejected,
                  "registrar rc={} ({})".format(rc, tail), code=NEG_CODE)
        print("{}  intake {} (registrar rc={})".format(
            "PASS" if rejected else "FAIL  ACCEPTED", case, rc))


def dimension_phase(rep, pack, strict):
    """Inject each dimension fixture and assert its owning validator rejects it.

    The real catalog bytes are backed up and restored in a finally, and the temp
    descriptor tree is deleted, so a mid-run failure can never leave the tree dirty.
    """
    cat_file = catalog_path(REPO_ROOT)
    for case in sorted(DIMENSION_VALIDATOR):
        script = DIMENSION_VALIDATOR[case]
        fx = FIXTURES_DIR / (case + ".yaml")
        if not fx.is_file():
            rep.check("dimension::{}".format(case), False,
                      "fixture missing: {}".format(fx), code=NEG_CODE)
            print("FAIL  MISSING fixture: {}".format(fx.name))
            continue
        fixture = yaml.safe_load(fx.read_text(encoding="utf-8")) or {}
        temp_id = "__negfix_{}".format(case)
        backup = cat_file.read_bytes() if cat_file.is_file() else None
        out_dir = REPO_ROOT / MC.MESH_GENERATED_REL / temp_id
        try:
            desc, out_dir = _inject_descriptor(temp_id, fixture)
            catalog = load_mesh_catalog(REPO_ROOT)
            catalog = upsert_catalog_entry(catalog, _catalog_entry(temp_id, fixture, desc))
            save_mesh_catalog(REPO_ROOT, catalog)

            rc, tail = _run(script, ["--pack", pack] + (["--strict"] if strict else []), strict)
            rejected = rc is not None and rc != 0
            rep.check("dimension::{}".format(case), rejected,
                      "{} rc={} ({})".format(script, rc, tail), code=NEG_CODE)
            print("{}  dimension {} -> {} (rc={})".format(
                "PASS" if rejected else "FAIL  ACCEPTED", case, script, rc))
        finally:
            if backup is not None:
                cat_file.write_bytes(backup)
            shutil.rmtree(out_dir, ignore_errors=True)


def selfheal_check(rep, pack, strict):
    """Prove the real catalog + generated tree are byte-for-byte healed."""
    catalog = load_mesh_catalog(REPO_ROOT)
    assets = catalog.get("assets") or {}
    n = len(assets)
    rep.check("selfheal::asset_count", n == EXPECTED_ASSET_COUNT,
              "catalog has {} assets (expected {})".format(n, EXPECTED_ASSET_COUNT),
              code=FailureCode.MESH_CATALOG_FAILURE)

    stray_records = sorted(a for a in assets if a.startswith("__negfix"))
    rep.check("selfheal::no_negfix_records", not stray_records,
              "stray negfix catalog records: {}".format(stray_records),
              code=FailureCode.MESH_CATALOG_FAILURE)

    gen_root = REPO_ROOT / MC.MESH_GENERATED_REL
    stray_dirs = sorted(
        p.name for p in gen_root.iterdir()
        if p.is_dir() and p.name.startswith("__negfix")
    ) if gen_root.is_dir() else []
    rep.check("selfheal::no_negfix_dirs", not stray_dirs,
              "stray negfix descriptor dirs: {}".format(stray_dirs),
              code=FailureCode.MESH_CATALOG_FAILURE)

    for script in ALL_VALIDATORS:
        rc, tail = _run(script, ["--pack", pack] + (["--strict"] if strict else []), strict)
        rep.check("selfheal::{}".format(script.replace(".py", "")),
                  rc == 0, "{} rc={} ({})".format(script, rc, tail),
                  code=FailureCode.MESH_CATALOG_FAILURE)


# =============================================================================
# main
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.2 MeshForge Intake negative-fixture gate.")
    ap.add_argument("--pack", default="biome_expansion_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)

    if not FIXTURES_DIR.is_dir():
        rep.error("no invalid mesh fixtures dir: {}".format(FIXTURES_DIR))
    else:
        print("[mesh-negative] INTAKE phase ({} fixtures)".format(len(INTAKE_CASES)))
        intake_phase(rep, strict)
        print("[mesh-negative] DIMENSION phase ({} fixtures)".format(len(DIMENSION_VALIDATOR)))
        dimension_phase(rep, args.pack, strict)
        print("[mesh-negative] SELF-HEAL check")
        selfheal_check(rep, args.pack, strict)

    n_fixtures = len(INTAKE_CASES) + len(DIMENSION_VALIDATOR)
    rep.finalize()
    rep.set_meta(build_meta(command="mesh-negative-validators", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n_fixtures,
                            extra={"intake_fixtures": list(INTAKE_CASES),
                                   "dimension_fixtures": sorted(DIMENSION_VALIDATOR)}))
    report_dir = REPO_ROOT / MC.MESH_REPORTS_REL / "test_negative_mesh"
    rep.write(report_dir, "test_negative_mesh_report.json")
    rep.print_summary("mesh-negative")
    print("[mesh-negative] {} fixtures exercised ({} intake + {} dimension)".format(
        n_fixtures, len(INTAKE_CASES), len(DIMENSION_VALIDATOR)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
