#!/usr/bin/env python3
"""test_negative_entity.py — WorldForge v1.0x entity-substrate negative harness.

Builds KNOWN-BAD entity-anchor overlays in memory (and, for spot coverage, in a
temp overlay dir) and asserts each validator's importable core FAILS with the
correct FailureCode. This is the anti-fake-green proof: the validators must
actually reject the defects the brief enumerates, not just pass the good pack.

Bad fixtures exercised:
  1. spawn zone inside player_start          -> NPC_SPAWN_FAILURE
  2. enemy spawn inside a safe zone           -> ENTITY_ANCHOR_FAILURE
  3. a floating anchor                        -> ENTITY_ANCHOR_FAILURE
  4. spawn density over budget                -> ENTITY_DENSITY_EXCEEDED
  5. an anchor missing provenance             -> ENTITY_ANCHOR_FAILURE
  6. an invalid faction tag                   -> ENTITY_ANCHOR_FAILURE
  7. POI not encounter-ready                  -> ENCOUNTER_READINESS_FAILURE

Prints ``NEGATIVE OK: <n> fixtures failed as expected`` and exits 0 iff every
known-bad fixture correctly failed with its expected code (exit 1 otherwise).

Usage:
    PYTHONUTF8=1 python tools/pipeline/test_negative_entity.py
"""

import copy
import sys
import tempfile
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from validation_report import ValidationReport
from failure_codes import FailureCode
from world_pack_maps import enumerate_maps
import generate_entity_anchors as G
import validate_entity_anchors as VEA
import validate_npc_spawns as VNS
import validate_encounter_readiness as VER

PACK = "desert_mvp_world"


def failing_codes(rep):
    """Codes of blocking, failing checks in a finalized report."""
    return {c.get("code") for c in rep.checks.values()
            if not c["ok"] and c["blocking"] and c.get("code")}


def run_core(check_map, overlay):
    """Run a validator's per-map core on one overlay under strict; return report."""
    rep = ValidationReport("world_pack_id", "neg", strict=True)
    check_map(rep, "neg_map", overlay, True)
    rep.finalize()
    return rep


def first_of(anchors, atype):
    for a in anchors:
        if a.get("type") == atype:
            return a
    return None


def main():
    _, maps = enumerate_maps(PACK)
    baseline = None
    for m in maps:
        if m.spec_exists:
            baseline = G.build_overlay(m, None)
            break
    if baseline is None:
        print("NEGATIVE HARNESS ERROR: no baseline overlay could be built")
        return 1

    # -- sanity: the GOOD baseline must pass all three cores ---------------
    sanity = []
    for label, cm in (("entity", VEA.check_map), ("npc", VNS.check_map),
                      ("encounter", VER.check_map)):
        rep = run_core(cm, copy.deepcopy(baseline))
        if not rep.passed:
            sanity.append("{}: baseline unexpectedly FAILED ({})".format(
                label, "; ".join(rep.failures)))
    if sanity:
        for s in sanity:
            print("NEGATIVE HARNESS ERROR:", s)
        return 1

    fixtures = []  # (name, check_map, mutated_overlay, expected_code)

    ps = baseline["world_model"]["player_start"]
    safe = baseline["world_model"]["safe_zones"][0]

    # F1: spawn zone dropped onto player_start -> NPC_SPAWN_FAILURE
    o1 = copy.deepcopy(baseline)
    z = first_of(o1["anchors"], "npc_spawn_zone")
    z["position"] = [ps[0], ps[1], ps[2]]
    fixtures.append(("spawn_inside_player_start", VNS.check_map, o1,
                     FailureCode.NPC_SPAWN_FAILURE))

    # F2: enemy spawn moved inside the safe zone (but clear of player_start) -> ENTITY_ANCHOR_FAILURE
    o2 = copy.deepcopy(baseline)
    e = first_of(o2["anchors"], "enemy_spawn_zone")
    e["position"] = [safe["center"][0] + 1000, safe["center"][1], safe["center"][2]]
    e["allow_in_safe_zone"] = False
    fixtures.append(("enemy_inside_safe_zone", VEA.check_map, o2,
                     FailureCode.ENTITY_ANCHOR_FAILURE))

    # F3: a floating anchor (z far above its ground) -> ENTITY_ANCHOR_FAILURE
    o3 = copy.deepcopy(baseline)
    idle = first_of(o3["anchors"], "idle_anchor")
    idle["position"] = [idle["position"][0], idle["position"][1], idle["ground_z"] + 5000]
    fixtures.append(("floating_anchor", VEA.check_map, o3,
                     FailureCode.ENTITY_ANCHOR_FAILURE))

    # F4: spawn density over budget (per-zone capacity blown) -> ENTITY_DENSITY_EXCEEDED
    o4 = copy.deepcopy(baseline)
    z4 = first_of(o4["anchors"], "enemy_spawn_zone")
    z4["capacity"] = o4["density_budget"]["max_capacity_per_zone"] + 50
    fixtures.append(("density_over_budget", VNS.check_map, o4,
                     FailureCode.ENTITY_DENSITY_EXCEEDED))

    # F5: an anchor missing provenance -> ENTITY_ANCHOR_FAILURE
    o5 = copy.deepcopy(baseline)
    o5["anchors"][0].pop("provenance", None)
    fixtures.append(("missing_provenance", VEA.check_map, o5,
                     FailureCode.ENTITY_ANCHOR_FAILURE))

    # F6: an invalid faction tag -> ENTITY_ANCHOR_FAILURE
    o6 = copy.deepcopy(baseline)
    f = first_of(o6["anchors"], "faction_ownership_anchor")
    f["faction_tag"] = "aliens_not_a_real_faction"
    fixtures.append(("invalid_faction_tag", VEA.check_map, o6,
                     FailureCode.ENTITY_ANCHOR_FAILURE))

    # F7: POI stripped of encounter surface -> ENCOUNTER_READINESS_FAILURE
    o7 = copy.deepcopy(baseline)
    o7["anchors"] = [a for a in o7["anchors"]
                     if a.get("type") not in ("encounter_anchor", "enemy_spawn_zone")]
    fixtures.append(("not_encounter_ready", VER.check_map, o7,
                     FailureCode.ENCOUNTER_READINESS_FAILURE))

    # -- run every fixture -------------------------------------------------
    passed = 0
    failed = []
    for name, cm, overlay, expected in fixtures:
        rep = run_core(cm, overlay)
        codes = failing_codes(rep)
        if (not rep.passed) and expected in codes:
            passed += 1
            print("  ok  {:<26} -> failed as expected with {}".format(name, expected))
        else:
            failed.append(name)
            print("  BAD {:<26} -> expected {} to block; got passed={} codes={}".format(
                name, expected, rep.passed, sorted(c for c in codes if c)))

    # -- spot-check: a validator core also fails when reading a bad overlay
    #    from an injected overlay DIR (proves overlay_dir override path) ---
    with tempfile.TemporaryDirectory() as td:
        bad = copy.deepcopy(baseline)
        first_of(bad["anchors"], "enemy_spawn_zone")["faction_tag"] = "aliens_bad"
        Path(td, "neg_only.json").write_text(json.dumps(bad), encoding="utf-8")
        loaded = G.load_overlay("neg_only", overlay_dir=td)
        rep = run_core(VEA.check_map, loaded)
        if (not rep.passed) and FailureCode.ENTITY_ANCHOR_FAILURE in failing_codes(rep):
            passed += 1
            print("  ok  {:<26} -> failed as expected with {}".format(
                "overlay_dir_injection", FailureCode.ENTITY_ANCHOR_FAILURE))
        else:
            failed.append("overlay_dir_injection")
            print("  BAD overlay_dir_injection    -> did not fail as expected")

    total = len(fixtures) + 1
    if failed:
        print("NEGATIVE FAILED: {}/{} fixtures did not fail as expected: {}".format(
            len(failed), total, ", ".join(failed)))
        return 1
    print("NEGATIVE OK: {} fixtures failed as expected".format(passed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
