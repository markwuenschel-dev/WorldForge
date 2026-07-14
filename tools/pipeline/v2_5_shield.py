#!/usr/bin/env python3
"""v2_5_shield.py — WorldForge v2.5 UE 5.7→5.8 Transition shield.

FAIL-CLOSED: a gate whose script is missing, or that returns non-zero, turns the shield
RED. Later waves turn unbuilt gates green; the verdict always tracks the real state — an
unbuilt topology/conversion/plugin/capability/regression/baseline/bridge/hostile gate is
honestly RED.

Do NOT stub a missing gate green: a gate whose script or evidence report is absent is
honestly RED, and the verdict always tracks the real state.

Gate lanes:
  (always)         transition contract spine   → validate_transition_contracts.py --strict
  --topology       transition topology         → validate_transition_topology.py
  --conversion     conversion manifest         → validate_conversion_manifest.py
                   inventory root coverage     → validate_inventory_root_coverage.py
                   conversion audit            → validate_conversion_audit.py
                   map census reconciliation   → validate_map_census_reconciliation.py
  --plugin         plugin build                → validate_plugin_build.py
  --capability     capability manifest         → validate_capability_manifest.py
  --regression     transition regression       → transition_regression.py --strict
  --baseline       transition baseline         → validate_transition_baseline.py --strict
  --bridge         Gloamstead bridge (DRY)     → validate_gloam_bridge.py --strict
                   Gloamstead bridge (LIVE)    → validate_gloam_bridge_live.py --strict
  --hostile        hostile suite               → transition_negatives.py
                                               + transition_fuzz.py --strict
                                               + transition_report_integrity.py
                                                   procedural/reports/ue5_8 --strict
                                               + transition_hygiene.py
                                               + run_transition_known_bads.py
                                               + run_transition_torture.py
                                               + run_v2_5_1_known_bads.py
  --regressions    prior authoring shields (opt-in): v2.4/v2.3/v2.2

v2.5.1 — WHY THE NEW GATES CARRY NO NEW FLAGS
---------------------------------------------
The four v2.5.1 gates ride the EXISTING flags whose claims they prove, rather than
opt-in flags of their own. `--conversion` already claims "the conversion is sound" and
`--bridge` already claims "the bridge is ready"; the v2.5.1 gates are what makes those
claims true. Behind a new flag they would be optional — and an anti-fake-green gate you
can forget to pass is not a gate. Anyone running the documented v2.5 acceptance command
below now gets the v2.5.1 hardening automatically, with no command change.

THE BRIDGE, SPECIFICALLY. v2.5's `--bridge` was satisfied by `validate_gloam_bridge.py`
alone — a gate over a REJECTING DRY PROBE. A dry probe asserts that NOTHING ran: it is
green precisely when no far side was touched, which makes it a NEGATIVE test, and a
negative test can never satisfy the POSITIVE claim "the bridge works against a separate
UE 5.8 project". `--bridge` now requires BOTH gates, so the dry probe alone can no longer
green the lane. The live gate demands execution_mode=live, runtime_executed=true,
observed_runtime_engine=5.8, plugin_loaded=true, operation_completed=true and
evidence_count>0, and re-derives the evidence hashes from the bytes on disk. The dry probe
is KEPT, unchanged, as the negative test it always was — and is additionally submitted to
the live gate as a known-bad, where it must go RED.

Honors a global --strict, threaded to gate scripts that accept it, exactly as
v2_4_shield.py threads its flags. Uses argparse with parse_known_args.

Acceptance: (canonical command surface — `make` is not installed, run directly)
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_5_shield.py --strict \
        --topology --conversion --plugin --capability --regression --baseline --bridge --hostile
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def run(label, relpath, *a):
    script_path = REPO_ROOT / relpath
    if not script_path.is_file():
        print("  [FAIL] {}  (gate not yet implemented: {})".format(label, relpath))
        return label, False
    rc = subprocess.run([PY, str(script_path), *[str(x) for x in a]],
                        cwd=str(REPO_ROOT)).returncode
    print("  [{}] {}".format("PASS" if rc == 0 else "FAIL", label))
    return label, rc == 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v2.5 UE 5.7->5.8 Transition shield.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--topology", action="store_true")
    ap.add_argument("--conversion", action="store_true")
    ap.add_argument("--plugin", action="store_true")
    ap.add_argument("--capability", action="store_true")
    ap.add_argument("--regression", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--bridge", action="store_true")
    ap.add_argument("--hostile", action="store_true")
    ap.add_argument("--regressions", action="store_true")
    for flag in ("--deep", "--jobs", "--cases"):
        ap.add_argument(flag, nargs="?", default=None)
    args, _ = ap.parse_known_args(argv)
    P = ["--pack", args.pack]
    s = ["--strict"] if args.strict else []
    PL = "tools/pipeline"

    print("=" * 72)
    print("WorldForge v2.5 UE 5.7->5.8 Transition — pack={}".format(args.pack))
    print("=" * 72)

    results = []
    # --- Transition contract spine (always) --------------------------------
    results.append(run("transition-contracts", PL + "/validate_transition_contracts.py", "--strict"))

    # --- Topology (--topology) ---------------------------------------------
    if args.topology:
        results.append(run("transition-topology", PL + "/validate_transition_topology.py", *s))

    # --- Conversion manifest (--conversion) --------------------------------
    # Four gates, in evidence order: is the inventory the real artifact, does it cover
    # every content root, is every package classified from real evidence, and is the
    # map-count delta explained? A green here is the whole v2.5.1 conversion claim.
    if args.conversion:
        results.append(run("conversion-manifest", PL + "/validate_conversion_manifest.py", *s))
        # Root drift: an inventory that silently omits a content root under-reports the
        # conversion and every downstream count inherits the omission.
        results.append(run("root-coverage", PL + "/validate_inventory_root_coverage.py", *s))
        # real_manifest / common_keyspace / unclassified=0 / unaccounted_deletions=0,
        # plus the v2.5 guard that no version claim is made without a version delta.
        results.append(run("conversion-audit", PL + "/validate_conversion_audit.py", *s))
        # The 131-vs-124 map delta: every 5.7-only package carries an evidence-backed
        # classification, or unclassified != 0 and this stays RED.
        results.append(run("census-reconcile", PL + "/validate_map_census_reconciliation.py", *s))

    # --- Plugin build (--plugin) -------------------------------------------
    if args.plugin:
        results.append(run("plugin-build", PL + "/validate_plugin_build.py", *s))

    # --- Capability manifest (--capability) --------------------------------
    if args.capability:
        results.append(run("capability-manifest", PL + "/validate_capability_manifest.py", *s))

    # --- Regression (--regression) -----------------------------------------
    if args.regression:
        results.append(run("transition-regression", PL + "/transition_regression.py", "--strict"))

    # --- Baseline (--baseline) ---------------------------------------------
    if args.baseline:
        results.append(run("transition-baseline", PL + "/validate_transition_baseline.py", "--strict"))

    # --- Gloamstead bridge (--bridge) --------------------------------------
    # BOTH gates are required. The dry probe is the NEGATIVE (green when nothing ran);
    # the live gate is the POSITIVE (green only when a real UE 5.8 editor really executed
    # in a separate repository). Requiring only the first is the v2.5 bug: it let a
    # rejecting dry probe stand in for a live run. Keeping both means the negative keeps
    # its value and can no longer be mistaken for the positive.
    if args.bridge:
        results.append(run("gloam-bridge", PL + "/validate_gloam_bridge.py", "--strict"))
        results.append(run("gloam-bridge-live", PL + "/validate_gloam_bridge_live.py",
                           "--strict"))

    # --- Hostile suite (--hostile) -----------------------------------------
    if args.hostile:
        results.append(run("transition-negatives", PL + "/transition_negatives.py", *s))
        results.append(run("transition-fuzz", PL + "/transition_fuzz.py", "--strict"))
        results.append(run("transition-report-integrity", PL + "/transition_report_integrity.py",
                           "procedural/reports/ue5_8", "--strict"))
        results.append(run("transition-hygiene", PL + "/transition_hygiene.py", *s))
        results.append(run("transition-known-bads", PL + "/run_transition_known_bads.py", *s))
        results.append(run("transition-torture", PL + "/run_transition_torture.py", *s))
        # v2.5.1 hostile catalogue: the 9 vectors that must never recur, each driven
        # through the REAL validator and required to be rejected BY ITS OWNING CHECK.
        results.append(run("v2.5.1-known-bads", PL + "/run_v2_5_1_known_bads.py", *s))

    # --- Regression lane (opt-in prior authoring shields) ------------------
    if args.regressions:
        results.append(run("regress:v2.4", PL + "/v2_4_shield.py", *P, *s, "--tactical"))
        results.append(run("regress:v2.3", PL + "/v2_3_shield.py", *P, *s, "--streaming", "--worldscale"))
        results.append(run("regress:v2.2", PL + "/v2_2_shield.py", *P, *s, "--quests", "--factions"))

    failed = [lbl for lbl, ok in results if not ok]
    print("=" * 72)
    verdict = "GREEN" if not failed else "RED"
    print("v2.5 shield: {} — {}/{} gates passed".format(
        verdict, len(results) - len(failed), len(results)))
    if failed:
        print("  FAILED (fail-closed — awaiting v2.5 transition waves): {}".format(failed))
    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
