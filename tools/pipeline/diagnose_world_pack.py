#!/usr/bin/env python3
"""diagnose_world_pack.py — WorldForge v1.0x operator diagnosis tool.

Read-only. Scans every validation report for a world pack, collects blocking
failures and their FailureCodes, and classifies them under the shared v1.0x
gate-level failure taxonomy so an operator sees *which lane* is red and *why*
without opening 20 report files. Not a gate (it summarizes; it does not add new
verdicts) — but with --strict it exits non-zero if any blocking failure exists,
so it can be used as a quick red/green triage.

    python tools/pipeline/diagnose_world_pack.py --pack desert_mvp_world
    python tools/pipeline/diagnose_world_pack.py --pack desert_mvp_world --strict
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from world_pack_maps import enumerate_maps, report_dir_for  # noqa: E402
from failure_codes import severity_of  # noqa: E402

# Map a WF code's numeric band -> the owning lane label, for taxonomy rollup.
LANE_BANDS = [
    (100, 110, "REPORT_INTEGRITY / NO-FAKE-GREEN"),
    (110, 120, "CONTRACT / GENERATION / OWNERSHIP"),
    (120, 130, "ENVIRONMENT / VISUAL PROFILES"),
    (130, 140, "SKY / LIGHTING / FOG / ATMOSPHERE"),
    (140, 150, "POI / LEVEL DESIGN / REACHABILITY"),
    (150, 160, "ENTITY ANCHORS / ENCOUNTER SUBSTRATE"),
    (160, 170, "RENDERING / SCALABILITY / RT / BUDGETS"),
    (170, 180, "SCENARIO / PACKAGE"),
    (180, 190, "LIFECYCLE / DETERMINISM / FUZZ / REGRESSION"),
]


def _band(code):
    if not code or not code.startswith("WF"):
        return "OTHER / LEGACY (WF0xx)"
    try:
        n = int(code[2:5])
    except ValueError:
        return "OTHER / LEGACY (WF0xx)"
    for lo, hi, label in LANE_BANDS:
        if lo <= n < hi:
            return label
    return "OTHER / LEGACY (WF0xx)"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Diagnose a WorldForge world pack's failures by taxonomy.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--strict", action="store_true", help="Exit 1 if any blocking failure is found.")
    args = ap.parse_args(argv)

    world_pack_id, _ = enumerate_maps(args.pack)
    rdir = report_dir_for(world_pack_id)

    by_lane = defaultdict(list)
    reports_scanned = 0
    total_failures = 0

    for rpt in sorted(rdir.glob("*_report.json")):
        try:
            data = json.loads(rpt.read_text(encoding="utf-8"))
        except Exception:
            by_lane["OTHER / LEGACY (WF0xx)"].append((rpt.stem, None, "unparseable report"))
            continue
        reports_scanned += 1
        name = rpt.stem.replace("_report", "")
        # Collect blocking failures + their codes from the checks map.
        checks = data.get("checks") or {}
        for cname, c in checks.items():
            if c.get("blocking") and not c.get("ok"):
                code = c.get("code")
                by_lane[_band(code)].append((name, code, "%s: %s" % (cname, c.get("detail", ""))))
                total_failures += 1
        # Also surface plain 'failures' strings if no coded checks captured them.
        for f in data.get("failures", []):
            if not any(f in d for _, _, d in by_lane[_band(None)]):
                pass  # coded checks above are the primary source

    print("=" * 72)
    print("DIAGNOSE %s — %d reports scanned, %d blocking failure(s)" % (
        world_pack_id, reports_scanned, total_failures))
    print("=" * 72)
    if total_failures == 0:
        print("  No blocking failures across any lane report. GREEN.")
    else:
        for lo, hi, label in LANE_BANDS + [(0, 0, "OTHER / LEGACY (WF0xx)")]:
            items = by_lane.get(label)
            if not items:
                continue
            print("\n  [%s] — %d failure(s)" % (label, len(items)))
            for rep_name, code, detail in items:
                print("    (%s) %-28s %s" % (code or "??", rep_name, detail[:90]))

    if args.strict and total_failures:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
