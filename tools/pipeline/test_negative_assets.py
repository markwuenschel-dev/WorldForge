#!/usr/bin/env python3
"""test_negative_assets.py — WorldForge v1.5 Wave-2 AssetAcquisitionForge NEGATIVE gate.

Every known-bad ASSET fixture under tests/fixtures/invalid_assets/ must be REJECTED
by the acquisition lane that owns its defect. This mirrors the v1.2
test_negative_sources.py / test_negative_mesh.py reference harnesses in shape and
safety: a valid base record (a real candidate / approval / quarantine / catalog
record on disk) is CLONED, ONE targeted patch turns it bad, the clone is injected
as a fresh temp record (``__negasset_<case>.json``) into the owning generated
store, the owning validator (or schema-gate) is run as a subprocess, its non-zero
exit AND the presence of the expected FailureCode in its failing checks are
asserted, and the temp record is deleted in a finally.

Because the harness only ADDS temp files (never mutates a committed record) and
deletes them in a finally, the real acquisition stores (needs/, candidates/,
approvals/, quarantine/, catalog/) are never left dirty even on an assertion
failure or a crash mid-run. After the whole sweep the harness proves the stores
self-healed (no __negasset_* leakage) and re-runs the seven v1.5 asset integrity
gates + the schema gates green.

A fixture that is WRONGLY ACCEPTED (owning validator passes, or fails without the
expected code) is a blocking ASSET_NEGATIVE_FIXTURE_FAILURE.

Report: procedural/reports/assets/test_negative_assets/test_negative_assets_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/test_negative_assets.py \
        --pack encounter_loop_world --strict
"""

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "tools" / "pipeline"
sys.path.insert(0, str(PIPELINE))

import asset_paths  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402

PY = sys.executable
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "invalid_assets"
NEG_CODE = FailureCode.ASSET_NEGATIVE_FIXTURE_FAILURE
NEG_PREFIX = "__negasset_"
REPORT_TYPE = "wf.asset.negative.v1"

# record_type -> (store dir, identity field). The base record cloned for each
# fixture is a real, currently-green record of this type.
RECORD_TYPES = {
    "candidate": (asset_paths.CANDIDATES_DIR, "candidate_id"),
    "approval": (asset_paths.APPROVALS_DIR, "approval_id"),
    "quarantine": (asset_paths.QUARANTINE_RECORDS_DIR, "quarantine_id"),
    "catalog": (asset_paths.CATALOG_DIR, "asset_id"),
}

# The seven v1.5 asset integrity gates + schema gates, re-run to prove self-heal.
SELFHEAL_VALIDATORS = (
    "validate_asset_licenses.py",
    "validate_asset_provenance.py",
    "validate_asset_hashes.py",
    "validate_asset_quarantine.py",
    "validate_asset_package_policy.py",
    "validate_asset_approval_flow.py",
    "validate_asset_catalog.py",
    "validate_asset_need.py",
    "validate_asset_candidate.py",
    "validate_asset_approval.py",
    "validate_asset_quarantine_schema.py",
    "validate_asset_catalog_schema.py",
)


# =============================================================================
# helpers
# =============================================================================
def _code_value(name):
    return getattr(FailureCode, name, None)


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


def _load_first(store_dir):
    """Return (path, dict) of the first real record in a store, or (None, None)."""
    if not store_dir.is_dir():
        return None, None
    for p in sorted(store_dir.glob("*.json")):
        if p.name.startswith(NEG_PREFIX):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict):
            return p, data
    return None, None


def _first_quarantine_hash_and_path():
    """A real (local_quarantine_path, content_sha256) pair for the mismatch case."""
    qdir = asset_paths.QUARANTINE_RECORDS_DIR
    if not qdir.is_dir():
        return None, None
    for p in sorted(qdir.glob("*.json")):
        if p.name.startswith(NEG_PREFIX):
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        ch = (rec.get("hashes") or {}).get("content_sha256")
        path = rec.get("local_quarantine_path")
        if ch and path:
            return path, ch
    return None, None


def _mutate_hash(h):
    """Return a hash string guaranteed to differ from ``h`` (same shape)."""
    s = str(h)
    if not s:
        return "sha256:" + "0" * 64
    last = s[-1]
    return s[:-1] + ("0" if last != "0" else "1")


def _apply_patch(rec, patch):
    """Apply a fixture patch (set/delete + special directives) to a cloned record."""
    if patch.get("mismatch_from_quarantine"):
        path, ch = _first_quarantine_hash_and_path()
        if path and ch:
            rec["source_path"] = path
            rec["source_hash"] = _mutate_hash(ch)
    for dotted, value in (patch.get("set") or {}).items():
        _set_dotted(rec, dotted, value)
    for dotted in (patch.get("delete") or []):
        _del_dotted(rec, dotted)
    return rec


def _run_validator(script, pack, strict):
    """Run an asset validator/schema-gate as a subprocess; return (rc, tail)."""
    path = PIPELINE / script
    if not path.is_file():
        return None, "script missing: {}".format(script)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if strict:
        env["STRICT"] = "1"
    extra = ["--pack", pack]
    if strict:
        extra.append("--strict")
    proc = subprocess.run([PY, str(path)] + extra, cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True)
    tail = " | ".join((proc.stdout or "").strip().splitlines()[-1:])[:200]
    return proc.returncode, tail


def _failing_codes(script):
    """Read the report a validator just wrote; return the set of blocking-fail codes."""
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


# =============================================================================
# one negative case
# =============================================================================
def _run_case(rep, fx, pack, strict, bases, created):
    case = fx["case"]
    rtype = fx["record_type"]
    script = fx["owning_validator"]
    patch = fx.get("patch") or {}
    expected_name = fx.get("expected_code", "")
    expected_value = _code_value(expected_name)

    if rtype not in RECORD_TYPES:
        rep.check("asset_negative::{}".format(case), False,
                  "unknown record_type {!r}".format(rtype), code=NEG_CODE)
        print("FAIL  {} (unknown record_type)".format(case))
        return
    if expected_value is None:
        rep.check("asset_negative::{}".format(case), False,
                  "unknown expected_code {!r}".format(expected_name), code=NEG_CODE)
        print("FAIL  {} (unknown expected_code)".format(case))
        return

    base_path, base_rec = bases[rtype]
    if base_rec is None:
        rep.check("asset_negative::{}".format(case), False,
                  "no valid base {} record on disk".format(rtype), code=NEG_CODE)
        print("FAIL  {} (no base record)".format(case))
        return

    store_dir, id_field = RECORD_TYPES[rtype]
    temp_id = NEG_PREFIX + case
    temp_path = store_dir / (temp_id + ".json")

    try:
        rec = copy.deepcopy(base_rec)
        rec[id_field] = temp_id
        _apply_patch(rec, patch)
        store_dir.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        created.append(temp_path)

        rc, tail = _run_validator(script, pack, strict)
        rejected = rc is not None and rc != 0
        codes = _failing_codes(script)
        code_present = expected_value in codes

        ok = rejected and code_present
        if not rejected:
            detail = "WRONGLY ACCEPTED by {} (rc={}); expected {}".format(
                script, rc, expected_name)
        elif not code_present:
            detail = "{} rejected (rc={}) but WITHOUT {} (got {})".format(
                script, rc, expected_name, sorted(codes))
        else:
            detail = "{} rejected with {} (rc={})".format(script, expected_name, rc)
        rep.check("asset_negative::{}".format(case), ok, detail, code=NEG_CODE)
        print("{}  {} -> {} [{}] {}".format(
            "PASS" if ok else "FAIL", case, script, expected_name,
            "" if ok else "({})".format(tail)))
    finally:
        if temp_path.exists():
            temp_path.unlink()


# =============================================================================
# self-heal
# =============================================================================
def selfheal_check(rep, pack, strict):
    strays = []
    for store_dir, _id in RECORD_TYPES.values():
        if store_dir.is_dir():
            strays += [p.name for p in store_dir.glob(NEG_PREFIX + "*.json")]
    rep.check("selfheal::no_negasset_records", not strays,
              "stray negative-fixture records: {}".format(sorted(strays)),
              code=NEG_CODE)

    for script in SELFHEAL_VALIDATORS:
        rc, tail = _run_validator(script, pack, strict)
        rep.check("selfheal::{}".format(script[:-3]), rc == 0,
                  "{} rc={} ({})".format(script, rc, tail), code=NEG_CODE)


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
            out.append({"case": p.stem, "record_type": "invalid",
                        "owning_validator": "", "_parse_error": str(exc)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.5 AssetAcquisitionForge negative-fixture gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    fixtures = _load_fixtures()

    bases = {}
    for rtype, (store_dir, _id) in RECORD_TYPES.items():
        bases[rtype] = _load_first(store_dir)

    created = []
    try:
        if not fixtures:
            rep.error("no asset negative fixtures under {}".format(FIXTURES_DIR))
        else:
            print("[asset-negative] {} fixtures".format(len(fixtures)))
            for fx in fixtures:
                if fx.get("_parse_error"):
                    rep.check("asset_negative::{}".format(fx.get("case")), False,
                              "fixture unparseable: {}".format(fx["_parse_error"]),
                              code=NEG_CODE)
                    continue
                _run_case(rep, fx, args.pack, strict, bases, created)
    finally:
        for p in created:
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass

    print("[asset-negative] SELF-HEAL check")
    selfheal_check(rep, args.pack, strict)

    rep.finalize()
    rep.set_meta(build_meta(
        command="asset-negative-validators", pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status, record_count=len(fixtures),
        extra={"fixtures": sorted(fx.get("case") for fx in fixtures),
               "by_owner": sorted(set(fx.get("owning_validator", "") for fx in fixtures))}))
    report_dir, filename = asset_paths.report_path("assets", "test_negative_assets")
    rep.write(report_dir, filename)
    rep.print_summary("asset-negative")
    print("[asset-negative] {} asset fixtures exercised".format(len(fixtures)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
