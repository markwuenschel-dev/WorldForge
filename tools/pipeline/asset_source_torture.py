#!/usr/bin/env python3
"""asset_source_torture.py — WorldForge v1.5 Wave-2 AssetAcquisition TORTURE gate.

Where test_negative_assets.py proves the acquisition lanes reject known-bad
FIXTURES (added, then deleted), this gate is the active-attack sibling: it mutates
REAL committed acquisition state, proves the owning validator CATCHES the attack
with the owning FailureCode, and restores the record byte-for-byte in a finally.
Nothing is left mutated even on an assertion failure or a crash mid-run, and the
live Megascans cache on disk is NEVER touched — only the generated JSON records
(and, for the report-integrity attack, a throwaway temp reports dir) are mutated.

Attacks (each caught with the owning code, then reverted):

  1. corrupt_quarantined_content_hash — flip the content_sha256 of a real
     quarantine record a catalog entry derives from; validate_asset_hashes must
     catch ASSET_HASH_MISMATCH ("the downloaded bytes changed under a fixed hash").
  2. mutate_catalog_hash_after_approval — flip a real catalog record's source_hash;
     validate_asset_hashes must catch ASSET_HASH_MISMATCH.
  3. remove_license_snapshot — clear a real catalog record's license url+snapshot;
     validate_asset_provenance must catch ASSET_PROVENANCE_MISSING.
  4. move_asset_outside_quarantine_root — repoint a real quarantine record's local
     path off every quarantine root; validate_asset_quarantine must catch
     ASSET_QUARANTINE_FAILURE.
  5. flip_megascans_to_generated_owned — mark a real Megascans quarantine record
     generated_owned (ownership conflict); validate_asset_quarantine must catch
     ASSET_OWNERSHIP_FAILURE (source ownership separation).
  6. attempt_destroy_third_party_source — authorize repair/destroy on a real
     third-party catalog record; validate_asset_catalog must REFUSE it with
     ASSET_OWNERSHIP_FAILURE (protected lifecycle).
  7. inject_stale_zero_record_report — drop a zero-record success report into a
     throwaway reports dir; validate_report_integrity must catch REPORT_ZERO_RECORD.

Report: procedural/reports/assets/asset_source_torture/asset_source_torture_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/asset_source_torture.py \
        --pack encounter_loop_world --strict
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "tools" / "pipeline"
sys.path.insert(0, str(PIPELINE))

import asset_paths  # noqa: E402
import validate_report_integrity as VRI  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402

PY = sys.executable
NEG_CODE = FailureCode.ASSET_NEGATIVE_FIXTURE_FAILURE
REPORT_TYPE = "wf.asset.torture.v1"


# =============================================================================
# helpers
# =============================================================================
def _norm_path(p):
    return str(p or "").replace("\\", "/").strip().rstrip("/").lower()


def _mutate_hash(h):
    s = str(h)
    if not s:
        return "sha256:" + "0" * 64
    return s[:-1] + ("0" if s[-1] != "0" else "1")


def _run_validator(script, pack, strict):
    path = PIPELINE / script
    if not path.is_file():
        return None, "script missing: {}".format(script)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if strict:
        env["STRICT"] = "1"
    extra = ["--pack", pack] + (["--strict"] if strict else [])
    proc = subprocess.run([PY, str(path)] + extra, cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True)
    tail = " | ".join((proc.stdout or "").strip().splitlines()[-1:])[:200]
    return proc.returncode, tail


def _failing_codes(script):
    stem = script[:-3] if script.endswith(".py") else script
    report_dir, filename = asset_paths.report_path("assets", stem)
    rpath = report_dir / filename
    codes = set()
    if not rpath.is_file():
        return codes
    try:
        data = json.loads(rpath.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return codes
    for c in (data.get("checks") or {}).values():
        if not c.get("ok") and c.get("blocking") and c.get("code"):
            codes.add(c["code"])
    return codes


def _first_record(store_dir):
    if not store_dir.is_dir():
        return None
    for p in sorted(store_dir.glob("*.json")):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        return p
    return None


def _quarantine_referenced_by_catalog():
    """The quarantine record file a real catalog entry derives from (for mismatch)."""
    qbypath = {}
    for p in sorted(asset_paths.QUARANTINE_RECORDS_DIR.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        qbypath[_norm_path(rec.get("local_quarantine_path"))] = p
    for p in sorted(asset_paths.CATALOG_DIR.glob("*.json")):
        try:
            cat = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        qp = qbypath.get(_norm_path(cat.get("source_path")))
        if qp is not None:
            return qp
    return None


# =============================================================================
# generic record-mutation attack (backup bytes -> mutate -> run -> restore)
# =============================================================================
def _attack(rep, name, record_path, mutate, script, expected_name, pack, strict):
    expected = getattr(FailureCode, expected_name, None)
    if record_path is None or not record_path.is_file():
        rep.check("torture::{}".format(name), False,
                  "no real record available to attack", code=NEG_CODE)
        print("FAIL  {} (no target record)".format(name))
        return
    if expected is None:
        rep.check("torture::{}".format(name), False,
                  "unknown expected_code {!r}".format(expected_name), code=NEG_CODE)
        print("FAIL  {} (unknown code)".format(name))
        return

    backup = record_path.read_bytes()
    try:
        rec = json.loads(backup.decode("utf-8"))
        mutate(rec)
        record_path.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        rc, tail = _run_validator(script, pack, strict)
        caught = rc is not None and rc != 0
        codes = _failing_codes(script)
        code_present = expected in codes
        ok = caught and code_present
        if not caught:
            detail = "attack NOT CAUGHT by {} (rc={}); expected {}".format(
                script, rc, expected_name)
        elif not code_present:
            detail = "{} failed (rc={}) but WITHOUT {} (got {})".format(
                script, rc, expected_name, sorted(codes))
        else:
            detail = "attack caught by {} with {} (rc={})".format(
                script, expected_name, rc)
        rep.check("torture::{}".format(name), ok, detail, code=NEG_CODE)
        print("{}  {} -> {} [{}] {}".format(
            "PASS" if ok else "FAIL", name, script, expected_name,
            "" if ok else "({})".format(tail)))
    finally:
        record_path.write_bytes(backup)


# =============================================================================
# report-integrity attack (throwaway temp reports dir; no real file touched)
# =============================================================================
def _attack_report_integrity(rep, pack):
    expected = FailureCode.REPORT_ZERO_RECORD
    with tempfile.TemporaryDirectory(prefix="wf_asset_torture_ri_") as tmp:
        meta = build_meta(command="validate-asset-catalog", pack=pack, strict=True,
                          status="ok", failure_count=0, record_count=0)
        (Path(tmp) / "validate_asset_catalog_report.json").write_text(
            json.dumps({"pack": pack, "checks": {}, "failures": [], "passed": True,
                        "status": "ok", "meta": meta}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        ri = VRI.validate_pack(pack, strict=True, reports_dir=tmp)
        ri.finalize()
        codes = {c.get("code") for c in ri.checks.values()
                 if not c.get("ok") and c.get("blocking") and c.get("code")}
        ok = (not ri.passed) and expected in codes
        detail = ("stale zero-record report caught with {}".format(expected) if ok
                  else "zero-record report NOT caught (passed={}, codes={})".format(
                      ri.passed, sorted(codes)))
        rep.check("torture::inject_stale_zero_record_report", ok, detail, code=NEG_CODE)
        print("{}  inject_stale_zero_record_report -> report-integrity [{}]".format(
            "PASS" if ok else "FAIL", "REPORT_ZERO_RECORD"))


# =============================================================================
# self-heal
# =============================================================================
SELFHEAL_VALIDATORS = (
    "validate_asset_licenses.py",
    "validate_asset_provenance.py",
    "validate_asset_hashes.py",
    "validate_asset_quarantine.py",
    "validate_asset_package_policy.py",
    "validate_asset_approval_flow.py",
    "validate_asset_catalog.py",
)


def selfheal_check(rep, pack, strict):
    for script in SELFHEAL_VALIDATORS:
        rc, tail = _run_validator(script, pack, strict)
        rep.check("selfheal::{}".format(script[:-3]), rc == 0,
                  "{} rc={} ({})".format(script, rc, tail), code=NEG_CODE)


# =============================================================================
# main
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.5 AssetAcquisition active-attack torture gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)

    quar_pair = _quarantine_referenced_by_catalog()
    quar_any = _first_record(asset_paths.QUARANTINE_RECORDS_DIR)
    cat_any = _first_record(asset_paths.CATALOG_DIR)

    print("[asset-torture] active-attack cases")

    # 1. corrupt a downloaded quarantined asset's content hash -> mismatch caught.
    _attack(rep, "corrupt_quarantined_content_hash", quar_pair,
            lambda r: r.__setitem__("hashes", dict(r.get("hashes") or {},
                                    content_sha256=_mutate_hash((r.get("hashes") or {}).get("content_sha256")))),
            "validate_asset_hashes.py", "ASSET_HASH_MISMATCH", args.pack, strict)

    # 2. mutate a catalog hash after approval -> mismatch caught.
    _attack(rep, "mutate_catalog_hash_after_approval", cat_any,
            lambda r: r.__setitem__("source_hash", _mutate_hash(r.get("source_hash"))),
            "validate_asset_hashes.py", "ASSET_HASH_MISMATCH", args.pack, strict)

    # 3. remove the license snapshot -> provenance caught.
    def _strip_license(r):
        r["license_url"] = ""
        r["license_snapshot"] = ""
    _attack(rep, "remove_license_snapshot", cat_any, _strip_license,
            "validate_asset_provenance.py", "ASSET_PROVENANCE_MISSING", args.pack, strict)

    # 4. move an asset outside a quarantine root -> quarantine caught.
    _attack(rep, "move_asset_outside_quarantine_root", quar_any,
            lambda r: r.__setitem__("local_quarantine_path", "D:/Loose/Escaped/asset"),
            "validate_asset_quarantine.py", "ASSET_QUARANTINE_FAILURE", args.pack, strict)

    # 5. flip a Megascans record to generated_owned -> ownership separation caught.
    def _flip_generated(r):
        r["generated_owned"] = True
        r["ownership_class"] = ""
    _attack(rep, "flip_megascans_to_generated_owned", quar_any, _flip_generated,
            "validate_asset_quarantine.py", "ASSET_OWNERSHIP_FAILURE", args.pack, strict)

    # 6. attempt to destroy a third-party source -> must be refused.
    _attack(rep, "attempt_destroy_third_party_source", cat_any,
            lambda r: r.__setitem__("lifecycle_policy",
                                    {"repair_allowed": True, "destroy_allowed": True}),
            "validate_asset_catalog.py", "ASSET_OWNERSHIP_FAILURE", args.pack, strict)

    # 7. inject a stale/zero-record report -> report-integrity caught.
    _attack_report_integrity(rep, args.pack)

    print("[asset-torture] SELF-HEAL check")
    selfheal_check(rep, args.pack, strict)

    rep.finalize()
    rep.set_meta(build_meta(
        command="asset-source-torture", pack=args.pack, strict=strict, torture=True,
        report_type=REPORT_TYPE, status=rep.status, record_count=7,
        extra={"attacks": [
            "corrupt_quarantined_content_hash", "mutate_catalog_hash_after_approval",
            "remove_license_snapshot", "move_asset_outside_quarantine_root",
            "flip_megascans_to_generated_owned", "attempt_destroy_third_party_source",
            "inject_stale_zero_record_report"]}))
    report_dir, filename = asset_paths.report_path("assets", "asset_source_torture")
    rep.write(report_dir, filename)
    rep.print_summary("asset-torture")
    print("[asset-torture] 7 active-attack cases exercised")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
