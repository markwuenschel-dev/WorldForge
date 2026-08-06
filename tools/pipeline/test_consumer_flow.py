#!/usr/bin/env python3
"""test_consumer_flow.py -- the consumer-proof gate.

    cd tools && PYTHONUTF8=1 python pipeline/test_consumer_flow.py

Asserts the three things the consumer proof actually rests on:

  1. both shipped consumers pass every Core stage
  2. they are substantially DIFFERENT -- asserted field by field, because two
     profiles that differ only by name would pass identically and prove nothing;
     the proof is exactly as strong as the distance between the consumers
  3. neither may be labelled caller-originated, and an adapter carrying
     generation logic is rejected

The Core boundary proof itself is exercised here too: capture, run both
consumers, verify. That is the platform claim, and a claim nobody re-runs decays
into a claim nobody checks.
"""

import json
import os
import sys
import tempfile

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import core_boundary_proof as CBP            # noqa: E402
from consumers import adapter as ADP         # noqa: E402
from pipeline import run_consumer_flow as RCF  # noqa: E402

CONSUMERS = ("demoarena", "demoexpanse")
FAILURES = []


def check(name, ok, detail=""):
    if not ok:
        FAILURES.append("{}: {}".format(name, detail))
    print("  {:5} {}".format("PASS" if ok else "FAIL", name))


def main():
    print("consumer-proof gate")

    reports = {}
    for cid in CONSUMERS:
        rep = RCF.run_consumer(cid)
        reports[cid] = rep
        check("flow.{}.green".format(cid), rep["green"],
              "stages_failed={} {}".format(
                  rep["stages_failed"],
                  [s for s in rep["stages"] if s["status"] != "ok"][:2]))
        check("flow.{}.not_caller_originated".format(cid),
              rep["caller_originated"] is False,
              "a WorldForge-authored demonstration must never be labelled "
              "caller-originated (WF1288)")

    # --- 2. the consumers really are far apart --------------------------------
    a, b = reports["demoarena"]["profile_shape"], reports["demoexpanse"]["profile_shape"]
    for field in ("game_type", "visual_language", "camera_mode",
                  "rollback_granularity", "unknown_handling", "density_class"):
        check("differ.{}".format(field), a[field] != b[field],
              "both consumers report {}={!r}; a shared value here means this "
              "axis is untested".format(field, a[field]))

    check("differ.extent_orders_of_magnitude",
          b["extent_m2"] >= a["extent_m2"] * 100,
          "extents {} vs {} are too close to stress budgets differently".format(
              a["extent_m2"], b["extent_m2"]))
    check("differ.locomotion_modes",
          set(a["locomotion_modes"]) != set(b["locomotion_modes"]),
          "identical locomotion means identical traversal reasoning")

    # Different constraint CLASSES, not just different counts: demoexpanse
    # carries a declared_unknown, demoarena does not.
    ka = set(reports["demoarena"]["constraint_classes"])
    kb = set(reports["demoexpanse"]["constraint_classes"])
    check("differ.constraint_classes_used", ka != kb,
          "both consumers exercise the same constraint classes {}".format(ka))

    # --- 3. the rails ---------------------------------------------------------
    dirty = ADP._example_adapter()
    dirty["placement_algorithm"] = "poisson_disc"   # a GENERATION_LOGIC_FIELD
    codes = {c for (_n, ok, _d, c) in
             ADP.validate_adapter_has_no_generation_logic(dirty, "x = 1\n")
             if not ok and c}
    check("rail.generation_logic_rejected",
          "WF1287_CORE_ADAPTER_CONTAINS_GENERATION_LOGIC" in codes,
          "codes={}".format(sorted(codes)))

    unread = ADP.validate_adapter_has_no_generation_logic(ADP._example_adapter(), None)
    check("rail.unread_source_is_not_a_pass",
          any(not ok for (_n, ok, _d, _c) in unread),
          "source_text=None must report NOT CHECKED, never clean")

    # --- the boundary proof, run for real -------------------------------------
    with tempfile.TemporaryDirectory() as td:
        base_path = os.path.join(td, "base.json")
        baseline = CBP.capture()
        check("proof.baseline_is_not_vacuous", baseline["file_count"] > 0,
              "a baseline over zero files makes every verify vacuously pass")
        with open(base_path, "w", encoding="utf-8") as fh:
            json.dump(baseline, fh)

        for cid in CONSUMERS:
            RCF.run_consumer(cid)

        after = CBP.capture()
        result = CBP.compare(baseline, after)
        check("proof.core_untouched_by_both_consumers", result["unchanged"],
              "modified={} added={} removed={}".format(
                  result["modified"], result["added"], result["removed"]))

        # negative control: the proof must NOTICE a change, or its silence
        # above means nothing at all.
        tampered = json.loads(json.dumps(baseline))
        tampered["files"]["tri.py"] = "sha256:" + "0" * 64
        tampered["core_digest"] = "sha256:" + "0" * 64
        neg = CBP.compare(tampered, after)
        check("proof.negative_control_detects_a_change",
              not neg["unchanged"] and "tri.py" in neg["modified"],
              "the proof failed to notice a tampered baseline: {}".format(neg))

    print("")
    if FAILURES:
        print("CONSUMER-PROOF GATE: RED ({} failure(s))".format(len(FAILURES)))
        for f in FAILURES:
            print("  - {}".format(f))
        return 1
    print("CONSUMER-PROOF GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
