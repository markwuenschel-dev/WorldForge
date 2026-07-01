#!/usr/bin/env python3
"""test_negative_poi.py — WorldForge v1.0x POI/level-design negative harness.

Constructs KNOWN-BAD overlays and asserts each validator's importable core FAILS
with the correct FailureCode. If a broken overlay slips through as PASS, the gate
is fake-green and this harness exits non-zero.

Fixtures:
  1. floating POI                         -> validate_pois         POI_PLACEMENT_INVALID
  2. POI out of terrain bounds            -> validate_pois         POI_PLACEMENT_INVALID
  3. POI missing provenance               -> validate_pois         POI_USABILITY_FAILURE
  4. primary POI unreachable from spawn   -> validate_reachability REACHABILITY_FAILURE
  5. graph edge to a nonexistent node     -> validate_poi_graph    POI_GRAPH_FAILURE
  6. all POIs clustered in one corner     -> validate_level_design LEVEL_DESIGN_FAILURE

Each fixture is injected as an overlay DICT into the validator's ``check_overlay``
core (the cores also accept an overlay-dir override; see validate_*.py).

Usage:
    PYTHONUTF8=1 python tools/pipeline/test_negative_poi.py
"""

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from validation_report import ValidationReport
from failure_codes import FailureCode
from world_pack_maps import enumerate_maps
from generate_level_design import build_overlay, bounds_from_center

import validate_pois
import validate_level_design
import validate_reachability
import validate_poi_graph


def _baseline_overlay():
    """A genuinely-valid overlay built from the first real map spec."""
    world_pack_id, maps = enumerate_maps("desert_mvp_world")
    for m in maps:
        if m.spec_exists:
            return build_overlay(m, world_pack_id)
    raise SystemExit("no spec available to build a baseline overlay")


def _run(checkfn, overlay):
    """Run a validator core on one overlay; return (passed, blocking_codes)."""
    rep = ValidationReport("world_pack_id", "negative", strict=True)
    checkfn(rep, overlay.get("slice_id", "neg"), overlay)
    rep.finalize()
    codes = {c.get("code") for c in rep.checks.values()
             if not c["ok"] and c.get("blocking") and c.get("code")}
    return rep.passed, codes


def _sanity_good(base):
    """The pristine baseline MUST pass every core (guards against over-strict checks)."""
    for label, fn in (("pois", validate_pois.check_overlay),
                      ("level_design", validate_level_design.check_overlay),
                      ("reachability", validate_reachability.check_overlay),
                      ("poi_graph", validate_poi_graph.check_overlay)):
        passed, codes = _run(fn, copy.deepcopy(base))
        if not passed:
            print("SANITY FAIL: baseline overlay rejected by {} ({})".format(label, codes))
            return False
    return True


def _fixtures(base):
    out = []

    # 1. floating POI
    f = copy.deepcopy(base)
    f["pois"][0]["world_position"][2] = 9_000_000.0
    out.append(("floating_poi", validate_pois.check_overlay, f,
                FailureCode.POI_PLACEMENT_INVALID))

    # 2. POI out of terrain bounds
    f = copy.deepcopy(base)
    f["pois"][1]["world_position"] = [9_000_000.0, 9_000_000.0, 0.0]
    f["pois"][1]["bounds"] = bounds_from_center([9_000_000.0, 9_000_000.0], 1500, 1500, 0.0, 800.0)
    out.append(("poi_out_of_terrain", validate_pois.check_overlay, f,
                FailureCode.POI_PLACEMENT_INVALID))

    # 3. POI missing provenance
    f = copy.deepcopy(base)
    f["pois"][0].pop("provenance", None)
    out.append(("poi_missing_provenance", validate_pois.check_overlay, f,
                FailureCode.POI_USABILITY_FAILURE))

    # 4. primary POI unreachable from player_start (drop the only spawn->primary edge)
    f = copy.deepcopy(base)
    f["graph"]["edges"] = [e for e in f["graph"]["edges"]
                           if not (e["from"] == "player_start" and e["to"] == "primary_poi")]
    out.append(("primary_unreachable", validate_reachability.check_overlay, f,
                FailureCode.REACHABILITY_FAILURE))

    # 5. graph edge to a nonexistent node
    f = copy.deepcopy(base)
    f["graph"]["edges"].append({"from": "player_start", "to": "ghost_node", "kind": "reachable"})
    out.append(("dangling_edge", validate_poi_graph.check_overlay, f,
                FailureCode.POI_GRAPH_FAILURE))

    # 6. all POIs clustered in one corner
    f = copy.deepcopy(base)
    corner = [-25000.0, -25000.0, 0.0]
    for p in f["pois"]:
        p["world_position"] = list(corner)
        p["bounds"] = bounds_from_center(corner, 1500, 1500, 0.0, 800.0)
    out.append(("clustered_corner", validate_level_design.check_overlay, f,
                FailureCode.LEVEL_DESIGN_FAILURE))

    return out


def main():
    base = _baseline_overlay()
    if not _sanity_good(base):
        return 1

    fixtures = _fixtures(base)
    failed_as_expected = 0
    problems = []
    for name, fn, overlay, expected_code in fixtures:
        passed, codes = _run(fn, overlay)
        if passed:
            problems.append("{}: ACCEPTED a known-bad overlay (should FAIL)".format(name))
        elif expected_code not in codes:
            problems.append("{}: failed but wrong code(s) {} (expected {})".format(
                name, sorted(codes), expected_code))
        else:
            failed_as_expected += 1
            print("  OK  {}: FAILED with {}".format(name, expected_code))

    print()
    if problems:
        print("NEGATIVE HARNESS FAILED:")
        for p in problems:
            print("  - {}".format(p))
        return 1
    print("NEGATIVE OK: {} fixtures failed as expected".format(failed_as_expected))
    return 0


if __name__ == "__main__":
    sys.exit(main())
