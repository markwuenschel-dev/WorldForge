#!/usr/bin/env python3
"""validate_reward_tables.py — WorldForge v1.9 reward-table gate + cross-ref.

Loads every generated reward table under
``procedural/generated/rewards/tables/`` and, for each:
  * contract-validates it with ``RX.validate_reward_table(t, strict=True)`` (zero
    failures) — the schema honesty invariants;
  * cross-refs every entry ``item_id`` to a real file under
    ``procedural/generated/rewards/equipment/`` and every entry ``unlock_id`` to a
    real id in ``procedural/generated/rewards/unlock_catalog.json``
    (``ASSET_REFERENCE_FAILURE``) — a table that grants an item/unlock that does
    not exist in the catalog is a dangling reference, not a valid reward;
  * asserts ``budget_min <= budget_max`` (``REWARD_BUDGET_EXCEEDED``).

Fails if zero tables are found (no zero-record success). Report ->
``procedural/reports/rewards/tables/validate_reward_tables_report.json``.

Acceptance: `PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_reward_tables.py --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

EQUIPMENT_GENERATED_REL = "procedural/generated/rewards/equipment"
UNLOCK_CATALOG_REL = "procedural/generated/rewards/unlock_catalog.json"
REPORT_REL = "procedural/reports/rewards/tables"
C = FailureCode


def _load_tables(d):
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                out.append((p.stem, json.loads(p.read_text(encoding="utf-8"))))
            except Exception as exc:  # noqa: BLE001
                out.append((p.stem, {"__parse_error__": str(exc)}))
    return out


def _catalog_unlock_ids():
    p = REPO_ROOT / UNLOCK_CATALOG_REL
    if not p.is_file():
        return None  # signals catalog missing -> cross-ref cannot resolve
    try:
        cat = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return {u.get("unlock_id") for u in cat.get("unlocks", []) if isinstance(u, dict)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    tables = _load_tables(REPO_ROOT / RX.REWARD_TABLE_GENERATED_REL)
    equipment_dir = REPO_ROOT / EQUIPMENT_GENERATED_REL
    unlock_ids = _catalog_unlock_ids()

    rep.check("reward-tables::nonzero", len(tables) > 0,
              "found {} reward table(s) under {} (run generate_reward_tables.py first)".format(
                  len(tables), RX.REWARD_TABLE_GENERATED_REL),
              code=C.REWARD_TABLE_INVALID)
    rep.check("reward-tables::unlock_catalog_present", unlock_ids is not None,
              "unlock catalog missing/unparseable at {} (run generate_unlock_catalog.py)".format(
                  UNLOCK_CATALOG_REL),
              code=C.ASSET_REFERENCE_FAILURE)

    for stem, t in tables:
        tid = t.get("reward_table_id", stem) if isinstance(t, dict) else stem
        # Contract validation — zero failures under strict.
        fails = [c[0] for c in RX.validate_reward_table(t, strict=True) if not c[1]] \
            if isinstance(t, dict) else ["not_an_object"]
        rep.check("reward-tables::{}::contract_valid".format(tid), not fails,
                  "contract failures: {}".format(fails[:6]), code=C.REWARD_TABLE_INVALID)

        if not isinstance(t, dict):
            continue

        # Budget sanity (independent of the contract's own range check).
        bmin, bmax = t.get("budget_min"), t.get("budget_max")
        rep.check("reward-tables::{}::budget_range".format(tid),
                  isinstance(bmin, (int, float)) and isinstance(bmax, (int, float)) and bmin <= bmax,
                  "budget_min ({}) must be <= budget_max ({})".format(bmin, bmax),
                  code=C.REWARD_BUDGET_EXCEEDED)

        # Cross-ref every entry's item_id / unlock_id against the real catalogs.
        for entry in (t.get("reward_entries") or []):
            if not isinstance(entry, dict):
                continue
            eid = entry.get("reward_entry_id", "?")
            item_id = entry.get("item_id")
            unlock_id = entry.get("unlock_id")
            if item_id:
                resolved = (equipment_dir / "{}.json".format(item_id)).is_file()
                rep.check("reward-tables::{}::{}::item_ref".format(tid, eid), resolved,
                          "entry item_id {!r} does not resolve to a file under {}".format(
                              item_id, EQUIPMENT_GENERATED_REL),
                          code=C.ASSET_REFERENCE_FAILURE)
            if unlock_id:
                resolved = isinstance(unlock_ids, set) and unlock_id in unlock_ids
                rep.check("reward-tables::{}::{}::unlock_ref".format(tid, eid), resolved,
                          "entry unlock_id {!r} not present in unlock catalog {}".format(
                              unlock_id, UNLOCK_CATALOG_REL),
                          code=C.ASSET_REFERENCE_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-reward-tables", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(tables),
                            report_type="wf.reward.reward_table_check.v1",
                            records_total=len(tables)))
    rep.write(REPO_ROOT / REPORT_REL, "validate_reward_tables_report.json")
    rep.print_summary("validate-reward-tables")
    print("[validate-reward-tables] {} table(s) cross-ref validated".format(len(tables)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
