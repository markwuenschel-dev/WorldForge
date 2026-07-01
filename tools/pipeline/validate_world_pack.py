#!/usr/bin/env python3
"""validate_world_pack.py — WorldForge world pack validator.

Runs validate_slice_pack.py for each referenced slice pack, then aggregates the
per-pack results.

v0.9: migrated onto the shared ``ValidationReport`` helper (one report shape, one
strict-mode semantics) and stable ``FailureCode``s. ``--strict`` / ``STRICT=1``
threads through to each child slice-pack run (so a child's genuine WARN blocks),
and into how this validator judges each child's report:

  - child pack PASS                 -> PASS
  - child pack WARN (soft)          -> WARN   (blocking under --strict)
  - child pack WARN_ONLY            -> WARN_ONLY (never blocking)
  - child pack FAIL / non-zero exit -> FAIL   (parent fails)

This aggregator does not launch UE itself: the child slice-pack validator
consumes cached per-slice UE reports produced by driving the editor via
``make validate-slice``. A slice whose UE report is absent is a FAIL (run the
editor to produce it).

Usage:
    python tools/pipeline/validate_world_pack.py \
        --pack procedural/world_packs/desert_production_seed.yaml [--deep] [--strict]

Exit 0 = PASS (status ok|warn), 1 = FAIL (status fail|error).
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode

VALIDATE_PACK_SCRIPT = REPO_ROOT / "tools" / "pipeline" / "validate_slice_pack.py"


def _run_validate_pack(slice_pack_path, deep, read_only, strict):
    """Run validate_slice_pack.py for one pack and return its exit code."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if strict:
        env["STRICT"] = "1"
    cmd = [sys.executable, str(VALIDATE_PACK_SCRIPT), "--pack", str(slice_pack_path)]
    if deep:
        cmd.append("--deep")
    if read_only:
        cmd.append("--read-only")
    if strict:
        cmd.append("--strict")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env)
    return result.returncode


def _judge_pack(rep, key, pack_id, rc, rpt_path, slice_count):
    """Judge one child slice-pack report into a verdict; return a legacy row dict."""
    child = {}
    if rpt_path.is_file():
        try:
            child = json.loads(rpt_path.read_text(encoding="utf-8"))
        except Exception:
            child = {}

    n_pass = int(child.get("pass", 0))
    n_total = int(child.get("total", slice_count))
    child_status = child.get("status")
    counts = child.get("counts") or {}

    if rc != 0:
        rep.check(key, False,
                  "child pack FAIL ({}/{}) status={}".format(n_pass, n_total, child_status or "fail"),
                  code=FailureCode.CHILD_VALIDATION_FAILED)
        status = "fail"
    elif child_status == "warn" or child.get("warnings"):
        real_warn = int(counts.get("WARN", 0)) > 0
        if real_warn:
            rep.check(key, False, "child pack WARN ({}/{})".format(n_pass, n_total),
                      warn_only=True, code=FailureCode.CHILD_VALIDATION_FAILED)
            status = "warn"
        else:
            rep.warn_only(key, False, "child pack WARN_ONLY ({}/{})".format(n_pass, n_total))
            status = "warn"
    else:
        rep.check(key, True, "PASS ({}/{})".format(n_pass, n_total))
        status = "pass"

    return {"pack_id": pack_id, "status": status, "pass": n_pass, "total": n_total}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate all slice packs in a world pack.")
    ap.add_argument("--pack", required=True, help="Path to world pack YAML")
    ap.add_argument("--deep", action="store_true", help="Enable deep per-slice validation")
    ap.add_argument("--read-only", action="store_true",
                    help="(retained for compatibility; aggregation never launches UE now)")
    ap.add_argument("--strict", action="store_true",
                    help="Treat genuine child WARNs as blocking (also via STRICT=1); threads to children.")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()

    pack_path = Path(args.pack)
    if not pack_path.is_absolute():
        pack_path = REPO_ROOT / pack_path
    if not pack_path.is_file():
        sys.stderr.write("ERROR: world pack not found: {}\n".format(pack_path))
        sys.exit(1)

    with pack_path.open("r", encoding="utf-8") as fh:
        world_pack = yaml.safe_load(fh)

    world_pack_id = world_pack.get("world_pack_id", pack_path.stem)
    packs = world_pack.get("packs", [])

    print("=== Validate World Pack: {} ({} slice packs, strict={}) ===".format(
        world_pack_id, len(packs), "on" if strict else "off"))

    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)
    pack_results = []
    total_slices = 0
    total_pass = 0

    for pack_entry in packs:
        pack_id = pack_entry.get("pack_id", "<unknown>")
        pack_rel = pack_entry.get("pack_path", "")
        slice_pack_path = REPO_ROOT / pack_rel if pack_rel else None
        key = "pack:{}".format(pack_id)

        if not slice_pack_path or not slice_pack_path.is_file():
            print("[{}] ERROR: pack file not found: {}".format(pack_id, pack_rel))
            rep.check(key, False, "pack file not found: {}".format(pack_rel),
                      code=FailureCode.SPEC_INVALID)
            pack_results.append({"pack_id": pack_id, "status": "error", "pass": 0, "total": 0})
            continue

        # Count slices for reporting.
        try:
            with slice_pack_path.open("r", encoding="utf-8") as fh:
                sp = yaml.safe_load(fh)
            slice_count = len(sp.get("slices", []))
        except Exception:
            slice_count = 0

        print("\n--- Validating pack: {} ({} slices) ---".format(pack_id, slice_count))
        rc = _run_validate_pack(slice_pack_path, deep=args.deep,
                                read_only=args.read_only, strict=strict)

        rpt_path = REPO_ROOT / "procedural" / "reports" / "packs" / pack_id / "validate_pack_report.json"
        row = _judge_pack(rep, key, pack_id, rc, rpt_path, slice_count)
        total_slices += row["total"]
        total_pass += row["pass"]
        pack_results.append(row)
        print("[{}] {} ({}/{})".format(pack_id, row["status"].upper(), row["pass"], row["total"]))

    print("\n=== World Pack '{}': {}/{} total slices PASS ===".format(
        world_pack_id, total_pass, total_slices))

    rep.finalize()

    report_dir = REPO_ROOT / "procedural" / "reports" / "world_packs" / world_pack_id
    report_dir.mkdir(parents=True, exist_ok=True)

    out = rep.to_dict()
    out.update({
        "world_pack_id": world_pack_id,
        "packs": pack_results,
        "total_slices": total_slices,
        "total_pass": total_pass,
        "passed": rep.passed,
        "deep": args.deep,
    })
    out_path = report_dir / "validate_world_pack_report.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("Report: procedural/reports/world_packs/{}/validate_world_pack_report.json".format(world_pack_id))

    rep.print_summary("validate-world-pack")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
