#!/usr/bin/env python3
"""test_negative_validators.py — WorldForge v1.0x MASTER negative-validator harness.

A validator that only ever passes is worthless: the whole no-fake-green shield
rests on proof that every gate REJECTS known-bad input. This master harness
enforces that proof in two ways:

1. Auto-discovers every sibling ``test_negative_*.py`` (environment, poi, entity,
   slfa, rendering, and the legacy recipes/placement/generated_asset harnesses,
   plus any corruption harness that appears), runs each as a subprocess with
   PYTHONUTF8=1, and requires every one to exit 0. Each sub-harness already
   asserts its own known-bad fixtures fail for the right FailureCode.

2. Directly proves the report-integrity gate itself has teeth by constructing a
   temp reports dir containing, one at a time, (a) an empty report, (b) a report
   missing its meta block, (c) a zero-record report, and (d) a report whose
   status=ok but which carries failures, then asserting
   ``validate_report_integrity.validate_pack(..., reports_dir=tmp, strict=True)``
   FAILS with the expected WF10x code for each.

Exits 0 iff EVERY sub-harness passed AND report-integrity's own negative fixtures
each failed with the correct code.

Run:
    PYTHONUTF8=1 python tools/pipeline/test_negative_validators.py --pack desert_mvp_world --strict
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

from failure_codes import FailureCode
from report_meta import build_meta
import validate_report_integrity as VRI

SELF = Path(__file__).name


# ---------------------------------------------------------------------------
# 1. Sub-harness discovery + execution
# ---------------------------------------------------------------------------
def discover_sub_harnesses():
    """Every test_negative_*.py sibling except this master harness."""
    return sorted(
        p for p in PIPELINE.glob("test_negative_*.py") if p.name != SELF
    )


def run_sub_harness(path, pack, strict):
    """Run one sub-harness as a subprocess; return (ok, returncode, tail)."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    if strict:
        env["STRICT"] = "1"
    # Sub-harnesses accept no args in the legacy contract; pass none for safety.
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(REPO_ROOT), env=env,
        capture_output=True, text=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = ""
    for line in reversed(out.strip().splitlines()):
        if line.strip():
            tail = line.strip()
            break
    return proc.returncode == 0, proc.returncode, tail


# ---------------------------------------------------------------------------
# 2. Report-integrity's own negative fixtures
# ---------------------------------------------------------------------------
def _failing_codes(rep):
    codes = set()
    for c in rep.checks.values():
        if not c["ok"] and c.get("blocking") and c.get("code"):
            codes.add(c["code"])
    return codes


def _write(dirpath, filename, obj):
    (Path(dirpath) / filename).write_text(
        json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fx_empty_report(d):
    """(a) An empty report object."""
    _write(d, "validate_sky_report.json", {})
    return "empty_report", FailureCode.REPORT_EMPTY


def fx_missing_meta(d):
    """(b) A meta-required gate report with no meta block at all."""
    _write(d, "validate_lighting_report.json", {
        "world_pack_id": "desert_mvp_world",
        "checks": {
            "a": {"ok": True, "verdict": "PASS", "blocking": False},
            "b": {"ok": True, "verdict": "PASS", "blocking": False},
            "c": {"ok": True, "verdict": "PASS", "blocking": False},
        },
        "failures": [],
        "passed": True,
        "status": "ok",
    })
    return "missing_meta", FailureCode.REPORT_INTEGRITY_FAILURE


def fx_zero_record(d):
    """(c) A fully-metaed report that validated zero records yet claims success."""
    meta = build_meta(command="validate-sky", pack="desert_mvp_world", strict=True,
                      status="ok", failure_count=0, record_count=0)
    _write(d, "validate_sky_report.json", {
        "world_pack_id": "desert_mvp_world",
        "checks": {},
        "failures": [],
        "passed": True,
        "status": "ok",
        "meta": meta,
    })
    return "zero_record", FailureCode.REPORT_ZERO_RECORD


def fx_partial_success(d):
    """(d) A report with failures but status=ok / passed=True (laundered)."""
    meta = build_meta(command="validate-fog", pack="desert_mvp_world", strict=True,
                      status="ok", failure_count=1, record_count=2)
    _write(d, "validate_fog_report.json", {
        "world_pack_id": "desert_mvp_world",
        "checks": {
            "ok_one": {"ok": True, "verdict": "PASS", "blocking": False},
            "bad_one": {"ok": False, "verdict": "FAIL", "blocking": True,
                        "detail": "boom", "code": FailureCode.FOG_PROFILE_FAILURE},
        },
        "failures": ["bad_one: boom"],
        "passed": True,
        "status": "ok",
        "meta": meta,
    })
    return "partial_success_as_success", FailureCode.PARTIAL_SUCCESS_AS_SUCCESS


REPORT_INTEGRITY_FIXTURES = [
    fx_empty_report,
    fx_missing_meta,
    fx_zero_record,
    fx_partial_success,
]


def run_report_integrity_fixtures(pack):
    """Return (results, all_ok) where results is [(name, expected, ok, detail)]."""
    results = []
    for fx in REPORT_INTEGRITY_FIXTURES:
        with tempfile.TemporaryDirectory(prefix="wf_neg_ri_") as tmp:
            name, expected = fx(tmp)
            rep = VRI.validate_pack(pack, strict=True, reports_dir=tmp)
            rep.finalize()
            codes = _failing_codes(rep)
            if rep.passed:
                results.append((name, expected, False, "validator PASSED a known-bad report"))
            elif expected not in codes:
                results.append((name, expected, False,
                                "failed but without {} (got {})".format(expected, sorted(codes))))
            else:
                results.append((name, expected, True, "failed as expected with {}".format(expected)))
    all_ok = all(r[2] for r in results)
    return results, all_ok


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Master negative-validator harness (no fake green).")
    ap.add_argument("--pack", default="desert_mvp_world", help="World pack id (passed through).")
    ap.add_argument("--strict", action="store_true", help="Strict mode; also via STRICT=1.")
    args = ap.parse_args(argv)
    strict = args.strict or str(os.environ.get("STRICT", "")).strip().lower() in ("1", "true", "yes", "on")

    print("=" * 72)
    print("WorldForge v1.0x — MASTER NEGATIVE VALIDATOR HARNESS")
    print("pack={} strict={}".format(args.pack, "on" if strict else "off"))
    print("=" * 72)

    # -- part 1: report-integrity's own teeth -------------------------------
    print("\n[report-integrity self-negatives]")
    ri_results, ri_ok = run_report_integrity_fixtures(args.pack)
    for name, expected, ok, detail in ri_results:
        print("  {:4}  {:32} {}".format("OK" if ok else "FAIL", name, detail))

    # -- part 2: every sub-harness ------------------------------------------
    sub = discover_sub_harnesses()
    print("\n[sub-harnesses]  discovered {}".format(len(sub)))
    sub_rows = []
    for path in sub:
        ok, rc, tail = run_sub_harness(path, args.pack, strict)
        sub_rows.append((path.name, ok, rc, tail))
        print("  {:4}  {:36} rc={}  {}".format("OK" if ok else "FAIL", path.name, rc, tail))

    # -- roll-up ------------------------------------------------------------
    total = len(sub_rows) + 1  # sub-harnesses + report-integrity self-check as one unit
    green = sum(1 for _, ok, _, _ in sub_rows if ok) + (1 if ri_ok else 0)

    print("\n" + "-" * 72)
    print("report-integrity self-negatives: {}".format(
        "GREEN" if ri_ok else "RED ({} bad)".format(sum(1 for r in ri_results if not r[2]))))
    failed_sub = [n for n, ok, _, _ in sub_rows if not ok]
    if failed_sub:
        print("sub-harnesses RED: {}".format(", ".join(failed_sub)))

    all_green = ri_ok and not failed_sub
    print("NEGATIVE VALIDATORS OK: {}/{} harnesses green".format(green, total))
    print("-" * 72)
    return 0 if all_green else 1


if __name__ == "__main__":
    sys.exit(main())
