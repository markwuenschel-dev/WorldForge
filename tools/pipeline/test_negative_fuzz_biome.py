#!/usr/bin/env python3
"""test_negative_fuzz_biome.py — proves fuzz_biome_matrix has teeth (Agent 7).

A fuzzer that only ever passes is worthless: the anti-fake-green guarantee rests
on proof that the biome fuzzer FAILS when the matrix would let an illegal world
through. This harness proves that in both directions, without touching the real
frozen contract:

  1. CLEAN run — the real ``rules_accept`` oracle over the real biome contract
     must PASS (every valid combo accepted, every invalid combo rejected, no
     crashes, no mismatches).

  2. HOLED run — inject a fake-green oracle that ACCEPTS every combination
     (simulating a matrix that lost its teeth). Every deliberately-invalid case
     the fuzzer synthesizes is now wrongly accepted, so the fuzzer MUST flag
     ``BIOME_FUZZ_FAILURE`` fake-green mismatches and the run MUST fail.

  3. OVER-STRICT run — inject an oracle that REJECTS everything; the valid
     baseline cases must now fail (proving the fuzzer also catches over-strict
     rejection, not just fake-green).

Exits 0 iff the detector works in all three directions, else 1. No report is
written and the working tree is untouched (all runs are in-memory).

Run:
    PYTHONUTF8=1 python tools/pipeline/test_negative_fuzz_biome.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode  # noqa: E402
import fuzz_biome_matrix as F  # noqa: E402

PACK = "biome_expansion_world"
CASES = 100
BFUZZ = FailureCode.BIOME_FUZZ_FAILURE


def _fake_green_oracle(biome, bindings, matrix):
    """A holed matrix: accepts EVERYTHING (loses all teeth)."""
    return True, "FORCED ACCEPT (hole)"


def _over_strict_oracle(biome, bindings, matrix):
    """A paranoid matrix: rejects EVERYTHING."""
    return False, "FORCED REJECT (over-strict)"


def _fuzz_codes(rep):
    """Return the set of failure codes on failing checks in a report."""
    return {c.get("code") for c in rep.checks.values()
            if not c["ok"] and c.get("code")}


def main():
    problems = []

    # --- 1. CLEAN run passes --------------------------------------------------
    rep_clean, _wid, tally = F.validate_pack(PACK, CASES, strict=True)
    rep_clean.finalize()
    if not rep_clean.passed:
        problems.append("CLEAN run should PASS but failed: {}".format(
            rep_clean.failures[:3]))
    if tally["mismatches"] or tally["crashes"]:
        problems.append("CLEAN run had mismatches={} crashes={}".format(
            tally["mismatches"], tally["crashes"]))
    if not (tally["valid"] > 0 and tally["cleanly_rejected"] > 0):
        problems.append("CLEAN run failed to exercise both valid and invalid "
                        "combos: {}".format(tally))
    print("[negative-fuzz-biome] clean: passed={} valid={} rejected={} "
          "mismatches={} crashes={}".format(
              rep_clean.passed, tally["valid"], tally["cleanly_rejected"],
              tally["mismatches"], tally["crashes"]))

    # --- 2. HOLED (fake-green) run must be CAUGHT -----------------------------
    rep_hole, _wid, tally_h = F.validate_pack(PACK, CASES, strict=True,
                                              accept_fn=_fake_green_oracle)
    rep_hole.finalize()
    if rep_hole.passed:
        problems.append("FAKE-GREEN oracle went UNDETECTED — fuzzer passed a "
                        "matrix with no teeth (this is the exact hole the gate "
                        "exists to catch)")
    if BFUZZ not in _fuzz_codes(rep_hole):
        problems.append("FAKE-GREEN failures not tagged {}: codes={}".format(
            BFUZZ, _fuzz_codes(rep_hole)))
    if tally_h["mismatches"] <= 0:
        problems.append("FAKE-GREEN run recorded no mismatches (expected the "
                        "invalid cases to be caught): {}".format(tally_h))
    # The fake-green mismatches must specifically be invalid-accepted holes.
    hole_details = [c["detail"] for c in rep_hole.checks.values()
                    if not c["ok"] and "FAKE-GREEN" in c.get("detail", "")]
    if not hole_details:
        problems.append("FAKE-GREEN run produced no 'FAKE-GREEN' mismatch detail")
    print("[negative-fuzz-biome] holed: passed={} mismatches={} fuzz_code_seen={} "
          "fake_green_hits={}".format(
              rep_hole.passed, tally_h["mismatches"], BFUZZ in _fuzz_codes(rep_hole),
              len(hole_details)))

    # --- 3. OVER-STRICT run must be CAUGHT too --------------------------------
    rep_strict, _wid, tally_s = F.validate_pack(PACK, CASES, strict=True,
                                                accept_fn=_over_strict_oracle)
    rep_strict.finalize()
    if rep_strict.passed:
        problems.append("OVER-STRICT oracle went UNDETECTED — fuzzer passed a "
                        "matrix that rejects valid worlds")
    if tally_s["mismatches"] <= 0:
        problems.append("OVER-STRICT run recorded no mismatches: {}".format(tally_s))
    print("[negative-fuzz-biome] over-strict: passed={} mismatches={}".format(
        rep_strict.passed, tally_s["mismatches"]))

    # --- verdict --------------------------------------------------------------
    if problems:
        print("\n[negative-fuzz-biome] FAIL — detector is broken:")
        for p in problems:
            print("  - {}".format(p))
        return 1
    print("\n[negative-fuzz-biome] PASS — fuzz_biome_matrix catches fake-green "
          "AND over-strict matrix holes, and greenlights a clean contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
