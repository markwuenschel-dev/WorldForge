#!/usr/bin/env python3
"""validate_slice_pack.py

Run validate_slice (via headless UE) for every slice in a pack spec, then
aggregate the results. Slices with existing up-to-date reports are re-validated
(validation is cheap — the map is already built).

Usage:
    python tools/pipeline/validate_slice_pack.py --pack procedural/slice_packs/desert_foundation.yaml

Exit code:
    0  all slices PASS
    1  any slice FAILs or errors
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
    sys.stderr.write("ERROR: PyYAML is required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_UE_SCRIPT = REPO_ROOT / "tools" / "pipeline" / "run_slice_ue.py"


def _run_validate(spec_path: Path, deep: bool = False) -> bool:
    """Run validate_slice via headless UE for one slice. Returns True on PASS."""
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    cmd = [sys.executable, str(RUN_UE_SCRIPT), "--script", "validate_slice.py", "--spec", str(spec_path)]
    if deep:
        cmd.append("--deep")
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env)
    return result.returncode == 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate all slices in a pack via headless UE and aggregate results."
    )
    parser.add_argument("--pack", required=True, help="path to a slice pack YAML")
    parser.add_argument("--read-only", action="store_true",
                        help="skip UE validation, only aggregate existing reports")
    parser.add_argument("--deep", action="store_true",
                        help="enable deep validation checks per slice (DEEP=1 mode)")
    args = parser.parse_args(argv)

    pack_path = Path(args.pack)
    if not pack_path.is_absolute():
        pack_path = REPO_ROOT / pack_path
    if not pack_path.is_file():
        sys.stderr.write(f"ERROR: pack spec not found: {pack_path}\n")
        return 1

    with pack_path.open("r", encoding="utf-8") as fh:
        pack = yaml.safe_load(fh)

    pack_id = pack.get("pack_id", pack_path.stem)
    biome = pack.get("biome", "unknown")
    slices = pack.get("slices", [])

    print(f"PACK: {pack_id}  ({len(slices)} slices, biome={biome})")

    results = []
    any_fail = False

    for entry in slices:
        name = entry.get("name", "<unnamed>")
        spec_path = REPO_ROOT / "procedural" / "slices" / biome / "generated" / (name + ".json")
        report_path = (
            REPO_ROOT
            / "procedural"
            / "reports"
            / "slices"
            / biome
            / name
            / "validate_slice_report.json"
        )

        if not args.read_only:
            if not spec_path.is_file():
                print(f"  {name:<40} SKIP     (no spec — run create-slice-pack first)")
                results.append({"name": name, "status": "missing"})
                continue
            print(f"  {name:<40} validating ...", flush=True)
            ue_ok = _run_validate(spec_path, deep=args.deep)
            if not ue_ok:
                print(f"  {name:<40} FAIL     (UE validate returned non-zero)")
                results.append({"name": name, "status": "fail"})
                any_fail = True
                continue

        if not report_path.is_file():
            print(f"  {name:<40} MISSING  (no report)")
            results.append({"name": name, "status": "missing"})
            continue

        try:
            rep = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"  {name:<40} ERROR    (could not read report: {exc})")
            results.append({"name": name, "status": "error", "error": str(exc)})
            any_fail = True
            continue

        passed = bool(rep.get("passed"))
        checks = rep.get("checks", {})
        checks_total = len(checks)
        checks_passed = sum(1 for v in checks.values() if isinstance(v, dict) and v.get("ok"))

        if passed:
            status_str = "PASS"
            row_status = "pass"
        else:
            status_str = "FAIL"
            row_status = "fail"
            any_fail = True

        print(f"  {name:<40} {status_str:<8} {checks_passed}/{checks_total}")
        row = {
            "name": name,
            "status": row_status,
            "checks_passed": checks_passed,
            "checks_total": checks_total,
        }
        if not passed:
            row["failures"] = rep.get("failures", [])
        results.append(row)

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_missing = sum(1 for r in results if r["status"] == "missing")
    n_error = sum(1 for r in results if r["status"] == "error")
    total = len(results)

    summary_parts = [f"{n_pass}/{total} PASS"]
    if n_fail:
        summary_parts.append(f"{n_fail} FAIL")
    if n_missing:
        summary_parts.append(f"{n_missing} MISSING")
    if n_error:
        summary_parts.append(f"{n_error} ERROR")
    print(f"RESULT: {', '.join(summary_parts)}")

    report_out = {
        "pack_id": pack_id,
        "biome": biome,
        "total": total,
        "pass": n_pass,
        "fail": n_fail,
        "missing": n_missing,
        "error": n_error,
        "slices": results,
    }

    out_dir = REPO_ROOT / "procedural" / "reports" / "packs" / pack_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "validate_pack_report.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(report_out, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Report: {out_path.relative_to(REPO_ROOT).as_posix()}")

    has_missing = n_missing > 0 and not args.read_only
    return 1 if (any_fail or has_missing) else 0


if __name__ == "__main__":
    sys.exit(main())
