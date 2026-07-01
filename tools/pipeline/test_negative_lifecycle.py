#!/usr/bin/env python3
"""test_negative_lifecycle.py — WorldForge v1.0x lifecycle negative harness (Agent 7).

Proves the corruption DETECTORS have teeth: a representative subset of corruption
modes is applied (each snapshot+restored), and for each we assert the lifecycle
detector core FAILS / classifies it. We also assert:

  * an UNDETECTED corruption would surface as ``CORRUPTION_UNDETECTED`` (via the
    shared ``classify_corruption`` rule on a clean, uncorrupted tree), and
  * ``touch_human_owned_asset`` is REFUSED — the human-owned asset stays
    byte-identical (guard held), and a violation would be
    ``REPAIR_TOUCHED_HUMAN_OWNED``.

Prints ``NEGATIVE OK: <n> fixtures failed as expected`` and exits 0 iff every
known-bad fixture was correctly detected AND the tree was fully restored.

Usage:
    PYTHONUTF8=1 python tools/pipeline/test_negative_lifecycle.py
"""

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode  # noqa: E402
import corrupt_world_pack as C  # noqa: E402
import lifecycle_torture as T  # noqa: E402

PACK = "desert_mvp_world"

# Representative subset spanning every detector family.
SUBSET = (
    "delete_generated_asset",       # validator: validate_pois
    "orphan_generated_asset",       # repair dry-run
    "bad_generated_path",           # audit
    "duplicate_manifest_record",    # registry integrity
    "remove_material_reference",    # ownership cross-check
    "remove_poi_reference",         # ownership cross-check
    "remove_entity_anchor",         # validator: entity anchors
    "remove_environment_profile",   # validator: environment contract
    "remove_lighting_profile",      # validator: environment contract
    "stale_report",                 # report integrity / staleness
    "partial_destroy",              # validator: validate_pois
    "partial_repair",               # validator: entity anchors
)


def _hash_generated():
    import hashlib
    h = hashlib.sha256()
    for base in (C.LEVEL_DESIGN_DIR, C.ENTITY_ANCHORS_DIR, C.PLACEMENT_DIR):
        for f in sorted(base.rglob("*.json")):
            h.update(f.name.encode("utf-8"))
            h.update(f.read_bytes())
    h.update(C.REGISTRY_PATH.read_bytes() if C.REGISTRY_PATH.is_file() else b"NONE")
    sp = REPO_ROOT / "procedural" / "slices" / "desert" / "generated"
    for f in sorted(sp.rglob("*.json")):
        h.update(f.name.encode("utf-8"))
        h.update(f.read_bytes())
    return h.hexdigest()


def main():
    target = C.default_target(PACK)
    strict = True
    passed_fixtures = 0
    failures = []
    baseline = _hash_generated()

    # 1. Each corruption mode must be DETECTED and correctly classified.
    for mode in SUBSET:
        snap = tempfile.mkdtemp(prefix="wf_neg_{}_".format(mode))
        manifest = None
        try:
            manifest = C.apply_corruption(mode, PACK, target, snap_dir=snap)
            detected, code, detail = T.run_detector(mode, PACK, target, manifest, strict)
            classified = T.classify_corruption(mode, detected, code)
            if detected and classified == code and code is not None:
                passed_fixtures += 1
                print("NEG ok  {:<28} detected -> {} ({})".format(mode, code, detail))
            else:
                failures.append("{}: detected={} classified={} detail={}".format(
                    mode, detected, classified, detail))
                print("NEG FAIL {:<28} NOT detected/classified ({})".format(mode, detail))
        except Exception as exc:  # noqa: BLE001
            failures.append("{}: harness raised {}".format(mode, exc))
            print("NEG FAIL {:<28} raised {}".format(mode, exc))
        finally:
            if manifest is not None:
                C.restore(manifest)

    # 2. An UNDETECTED corruption must classify as CORRUPTION_UNDETECTED.
    #    On a clean (restored) tree, the validate_pois detector reports no failure;
    #    classify_corruption(detected=False) must yield CORRUPTION_UNDETECTED.
    clean_detected, clean_code, _d = T.run_detector(
        "delete_generated_asset", PACK, target, {}, strict)
    undetected_code = T.classify_corruption("delete_generated_asset", False, clean_code)
    if not clean_detected and undetected_code == FailureCode.CORRUPTION_UNDETECTED:
        passed_fixtures += 1
        print("NEG ok  {:<28} clean tree -> would surface {}".format(
            "undetected_rule", undetected_code))
    else:
        failures.append("undetected_rule: clean_detected={} code={}".format(
            clean_detected, undetected_code))

    # 3. touch_human_owned_asset must be REFUSED (human asset byte-identical).
    snap = tempfile.mkdtemp(prefix="wf_neg_touch_")
    manifest = C.apply_corruption("touch_human_owned_asset", PACK, target, snap_dir=snap)
    guard_held, code, detail = T.run_detector("touch_human_owned_asset", PACK, target, manifest, strict)
    C.restore(manifest)
    if guard_held and code == FailureCode.REPAIR_TOUCHED_HUMAN_OWNED:
        passed_fixtures += 1
        print("NEG ok  {:<28} guard held (human untouched): {}".format("touch_human_owned", detail))
    else:
        failures.append("touch_human_owned: guard_held={} ({})".format(guard_held, detail))

    # 4. Tree must be fully restored.
    restored_clean = _hash_generated() == baseline
    if not restored_clean:
        failures.append("working tree not restored after negative fixtures")

    total = len(SUBSET) + 2
    if failures:
        print("")
        for f in failures:
            print("  FAIL: {}".format(f))
        print("NEGATIVE FAILED: {}/{} fixtures behaved correctly".format(passed_fixtures, total))
        return 1
    print("NEGATIVE OK: {} fixtures failed as expected (tree restored clean)".format(passed_fixtures))
    return 0


if __name__ == "__main__":
    sys.exit(main())
