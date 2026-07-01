#!/usr/bin/env python3
"""validate_slice_pack.py — aggregate per-slice validation results for a pack.

v0.9: migrated onto the shared ``ValidationReport`` helper (one report shape, one
strict-mode semantics) and stable ``FailureCode``s, and the aggregation is now a
pure cached-report consumer.

This aggregator CONSUMES the per-slice
``procedural/reports/slices/<biome>/<name>/validate_slice_report.json`` that the
tooling produced by driving the editor via ``make validate-slice``:

  - cached report PASS              -> PASS
  - cached report PASS w/ real WARN -> WARN   (blocking under --strict)
  - cached report PASS w/ WARN_ONLY -> WARN_ONLY (never blocking)
  - cached report FAIL              -> FAIL   (parent fails)
  - cached report unreadable        -> FAIL   (WF001)
  - no cached report                -> FAIL   (WF080; run 'make validate-slice'
                                       to drive the editor and produce it)

Strict threads through: a child whose own report is blocking makes the parent
block; a child with a genuine soft WARN makes the parent block under ``--strict``.

Usage:
    python tools/pipeline/validate_slice_pack.py --pack procedural/slice_packs/desert_poi_lite.yaml [--deep] [--strict]

Writes:
    procedural/reports/packs/<pack_id>/validate_pack_report.json
    (canonical v0.9 shape PLUS the legacy aggregate keys pack_id/biome/total/
     pass/fail/missing/error/slices that existing consumers read)

Exit 0 = PASS (status ok|warn), 1 = FAIL (status fail|error).
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML is required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode


def _judge_slice(rep, key, name, report_path):
    """Consume one cached validate_slice_report.json and route it to a verdict.

    Returns a legacy-shaped row dict for the aggregate report's ``slices`` list.
    """
    if not report_path.is_file():
        rep.ue_check(
            key, False,
            "no validate_slice_report.json — run 'make validate-slice' (UE) for {}".format(name),
            code=FailureCode.UE_ARTIFACT_MISSING)
        return {"name": name, "status": "fail", "ue_missing": True}

    try:
        child = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        rep.check(key, False, "could not read report: {}".format(exc),
                  code=FailureCode.DESCRIPTOR_UNPARSEABLE)
        return {"name": name, "status": "error", "error": str(exc)}

    checks = child.get("checks", {})
    total = len(checks)
    n_ok = sum(1 for v in checks.values() if isinstance(v, dict) and v.get("ok"))
    passed = bool(child.get("passed"))
    counts = child.get("counts") or {}
    fails = child.get("failures", []) or []
    warns = child.get("warnings", []) or []

    if not passed:
        rep.check(
            key, False,
            "child FAIL ({}/{}): {}".format(n_ok, total, "; ".join(fails) or child.get("status", "fail")),
            code=FailureCode.CHILD_VALIDATION_FAILED)
        return {"name": name, "status": "fail", "checks_passed": n_ok,
                "checks_total": total, "failures": fails}

    # Passed (no blocking failure). Reflect any soft warnings upward.
    if warns or child.get("status") == "warn":
        real_warn = int(counts.get("WARN", 0)) > 0
        if real_warn:
            # Genuine soft warning in the child -> blocks the parent under --strict.
            rep.check(key, False,
                      "child WARN ({}/{}): {}".format(n_ok, total, "; ".join(warns)),
                      warn_only=True, code=FailureCode.CHILD_VALIDATION_FAILED)
            return {"name": name, "status": "warn", "checks_passed": n_ok, "checks_total": total}
        # Legacy report (no counts) or explicit WARN_ONLY -> never blocking.
        rep.warn_only(key, False,
                      "child WARN_ONLY ({}/{}): {}".format(n_ok, total, "; ".join(warns)))
        return {"name": name, "status": "warn", "checks_passed": n_ok, "checks_total": total}

    rep.check(key, True, "PASS {}/{}".format(n_ok, total))
    return {"name": name, "status": "pass", "checks_passed": n_ok, "checks_total": total}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Aggregate per-slice validation reports for a pack (no UE launch).")
    parser.add_argument("--pack", required=True, help="path to a slice pack YAML")
    parser.add_argument("--read-only", action="store_true",
                        help="(retained for compatibility; aggregation is always read-only now)")
    parser.add_argument("--deep", action="store_true",
                        help="(retained for compatibility; deep checks are recorded in the cached "
                             "per-slice UE report, which this aggregator consumes)")
    parser.add_argument("--strict", action="store_true",
                        help="Treat genuine child WARNs as blocking (also via STRICT=1).")
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()

    pack_path = Path(args.pack)
    if not pack_path.is_absolute():
        pack_path = REPO_ROOT / pack_path
    if not pack_path.is_file():
        sys.stderr.write("ERROR: pack spec not found: {}\n".format(pack_path))
        return 1

    with pack_path.open("r", encoding="utf-8") as fh:
        pack = yaml.safe_load(fh)

    pack_id = pack.get("pack_id", pack_path.stem)
    biome = pack.get("biome", "unknown")
    slices = pack.get("slices", [])

    print("PACK: {}  ({} slices, biome={}, strict={})".format(
        pack_id, len(slices), biome, "on" if strict else "off"))

    rep = ValidationReport("pack_id", pack_id, strict=strict)
    results = []

    for entry in slices:
        name = entry.get("name", "<unnamed>")
        report_path = (REPO_ROOT / "procedural" / "reports" / "slices" / biome
                       / name / "validate_slice_report.json")
        row = _judge_slice(rep, "slice:{}".format(name), name, report_path)
        results.append(row)
        cp = row.get("checks_passed")
        ct = row.get("checks_total")
        suffix = " {}/{}".format(cp, ct) if cp is not None else ""
        print("  {:<40} {:<8}{}".format(name, row["status"].upper(), suffix))

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_warn = sum(1 for r in results if r["status"] == "warn")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_missing = sum(1 for r in results if r.get("ue_missing"))
    n_error = sum(1 for r in results if r["status"] == "error")
    total = len(results)

    summary_parts = ["{}/{} PASS".format(n_pass, total)]
    if n_warn:
        summary_parts.append("{} WARN".format(n_warn))
    if n_fail:
        summary_parts.append("{} FAIL".format(n_fail))
    if n_missing:
        summary_parts.append("{} UE-REPORT-MISSING".format(n_missing))
    if n_error:
        summary_parts.append("{} ERROR".format(n_error))
    print("RESULT: {}".format(", ".join(summary_parts)))

    rep.finalize()

    # Canonical v0.9 report PLUS legacy aggregate keys (additive; existing
    # consumers read pack_id/total/pass/fail/missing/error/slices).
    out = rep.to_dict()
    out.update({
        "pack_id": pack_id,
        "biome": biome,
        "total": total,
        "pass": n_pass,
        "warn": n_warn,
        "fail": n_fail,
        "missing": n_missing,  # slices whose UE validate report is absent (now a FAIL)
        "error": n_error,
        "slices": results,
    })

    out_dir = REPO_ROOT / "procedural" / "reports" / "packs" / pack_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "validate_pack_report.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("Report: {}".format(out_path.relative_to(REPO_ROOT).as_posix()))

    rep.print_summary("validate-slice-pack")
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
