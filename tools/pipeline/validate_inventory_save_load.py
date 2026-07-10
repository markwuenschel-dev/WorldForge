#!/usr/bin/env python3
"""validate_inventory_save_load.py — WorldForge v1.9 inventory save/load gate.

Proves durable-inventory PERSISTENCE at the model level for every generated
InventoryState under ``procedural/generated/progression/inventory/*.json``: each
state is round-tripped through reward_forge.save_load_roundtrip(state, "inventory")
(serialize -> reload -> recompute content hash -> assert stable) and must return
ok=True (INVENTORY_SAVE_LOAD_FAILED). It ALSO confirms the state persists to the
DEDICATED WFInventory_State slot and never a combat/mission/npc slot.

Per-scenario proof files are written to
REWARD_SAVE_LOAD_REPORTS_REL/inventory_save_load_{scenario_id}.json (each with its
own meta block), plus a rollup gate report.

ANTI-FAKE-GREEN: fail-closed (RED with zero states on disk) and DOGFOODS the
round-trip against a synthetic known-bad (an inventory whose inventory_hash no
longer matches its items) which must fail the round-trip.

Acceptance: `python tools/pipeline/validate_inventory_save_load.py --pack encounter_loop_world --strict`.
Reports -> procedural/reports/rewards/save_load/validate_inventory_save_load_report.json
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_forge as RF
import reward_contracts as RX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

INVENTORY_DIR = REPO_ROOT / "procedural/generated/progression/inventory"
SAVELOAD_DIR = REPO_ROOT / RX.REWARD_SAVE_LOAD_REPORTS_REL
CODE = FailureCode.INVENTORY_SAVE_LOAD_FAILED


def _roundtrip_checks(state):
    """Return (name, ok, detail, code) tuples proving one inventory state persists.
    Shared by the live path and the dogfood so they can never diverge."""
    ch = []
    ok, detail = RF.save_load_roundtrip(state, "inventory")
    ch.append(("roundtrip_stable", ok, "inventory save/load: {}".format(detail), CODE))
    sk = state.get("save_load_key") if isinstance(state, dict) else None
    ch.append(("dedicated_slot", sk == RX.INVENTORY_SAVE_SLOT,
               "inventory save_load_key must be {!r} (got {!r})".format(RX.INVENTORY_SAVE_SLOT, sk),
               CODE))
    ch.append(("not_forbidden_slot", isinstance(sk, str) and sk not in RX.FORBIDDEN_SAVE_SLOTS,
               "inventory save slot must not reuse a combat/mission/npc slot", CODE))
    return ch


def _dogfood(rep):
    good = RX._example_inventory_state()
    bad = RX._example_inventory_state()
    bad["inventory_hash"] = "inv:deadbeefdeadbeef"  # no longer matches items
    good_fails = [c for c in _roundtrip_checks(good) if not c[1]]
    bad_fails = [c for c in _roundtrip_checks(bad) if not c[1]]
    rep.check("dogfood::valid_roundtrip_passes", not good_fails,
              "coherent inventory round-trips stable ({})".format(
                  "0 fail" if not good_fails else [c[0] for c in good_fails][:4]), code=CODE)
    rep.check("dogfood::hash_drift_rejected", len(bad_fails) > 0,
              "inventory with mismatched inventory_hash fails round-trip", code=CODE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    _dogfood(rep)

    files = sorted(INVENTORY_DIR.glob("*.json")) if INVENTORY_DIR.is_dir() else []
    rep.check("inventory_save_load::present", len(files) > 0,
              "no generated inventory states found (run generate_progression_state.py)",
              code=CODE)

    verified = 0
    bad = 0
    for f in files:
        sid = f.stem
        try:
            state = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            bad += 1
            rep.check("sl::{}::readable".format(sid), False, "inventory state unreadable", code=CODE)
            continue
        checks = _roundtrip_checks(state)
        sub_fails = 0
        for name, ok, detail, code in checks:
            if not ok:
                bad += 1
                sub_fails += 1
                rep.check("sl::{}::{}".format(sid, name), False, detail, code=code)
        proof = {
            "scenario_id": sid, "save_load_key": state.get("save_load_key"),
            "kind": "inventory", "roundtrip_ok": sub_fails == 0,
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d, _ in checks],
        }
        proof["meta"] = build_meta(command="validate-inventory-save-load", pack=args.pack,
                                   strict=strict, status="pass" if sub_fails == 0 else "fail",
                                   record_count=1, report_type="wf.reward.inventory_save_load_proof.v1",
                                   report_id_suffix=sid, records_total=1,
                                   records_failed=1 if sub_fails else 0)
        SAVELOAD_DIR.mkdir(parents=True, exist_ok=True)
        (SAVELOAD_DIR / "inventory_save_load_{}.json".format(sid)).write_text(
            json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if sub_fails == 0:
            verified += 1

    rep.check("inventory_save_load::all_verified", bad == 0,
              "{} inventory save/load failure(s) across {} state(s)".format(bad, len(files)),
              code=CODE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-inventory-save-load", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files),
                            report_type="wf.reward.inventory_save_load_report.v1",
                            records_total=len(files), extra={"verified": verified}))
    rep.write(SAVELOAD_DIR, "validate_inventory_save_load_report.json")
    rep.print_summary("validate-inventory-save-load")
    print("[validate-inventory-save-load] {} inventory state(s), {} persistence-verified".format(
        len(files), verified))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
