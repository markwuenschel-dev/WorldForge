#!/usr/bin/env python3
"""validate_quest_faction_save_load.py — v2.2 Wave 3 save/load roundtrip gate.

Proves quest/faction consequence state persists across a save/load boundary: for
each of the 24 runs there is a save blob, it deserializes cleanly, its faction-state
hash matches the run's consequence-ledger post_faction_state_hash (the SAVED state is
the MUTATED state, not the pre-state), and the save slot is one of the dedicated
quest/faction slots. A run whose report claims save_load_result=roundtrip_ok but has
no matching, hash-consistent save blob fails here.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_quest_faction_save_load.py --strict
Reports -> procedural/reports/quest_faction/save_load/validate_quest_faction_save_load_report.json
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import quest_faction_contracts as QF
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

RUNTIME_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "runtime"
SAVELOAD_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "save_load"
CONSEQ_DIR = REPO_ROOT / "procedural" / "generated" / "consequences"

SAVE_SLOTS = ("quest_faction_slot_a", "quest_faction_slot_b", "quest_faction_slot_c")


def _hash(obj):
    return "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def validate(rep):
    run_dirs = sorted([d for d in RUNTIME_DIR.iterdir()
                       if d.is_dir() and (d / "report.json").is_file()])
    rep.check("save_load::runs_present", len(run_dirs) == QF.EXPECTED_SCENARIO_COUNT,
              "expected {} runs (got {})".format(QF.EXPECTED_SCENARIO_COUNT, len(run_dirs)),
              code=F.QUEST_FACTION_PARTIAL_MATRIX)

    n = 0
    for d in run_dirs:
        report = json.loads((d / "report.json").read_text(encoding="utf-8"))
        rid = report["run_id"]
        n += 1
        sp = SAVELOAD_DIR / (rid + ".json")
        rep.check("sl::{}::save_present".format(rid), sp.is_file(),
                  "save blob missing for run {}".format(rid),
                  code=F.QUEST_FACTION_SAVE_LOAD_MISSING)
        if not sp.is_file():
            continue
        # deserialize cleanly
        try:
            blob = json.loads(sp.read_text(encoding="utf-8"))
            loaded = True
        except Exception:
            blob, loaded = None, False
        rep.check("sl::{}::deserialize".format(rid), loaded,
                  "save blob does not deserialize", code=F.QUEST_FACTION_SAVE_LOAD_FAILED)
        if not loaded:
            continue
        # save slot is a dedicated quest/faction slot
        rep.check("sl::{}::dedicated_slot".format(rid),
                  blob.get("save_slot") in SAVE_SLOTS,
                  "save must use a dedicated quest/faction slot (got {})".format(
                      blob.get("save_slot")),
                  code=F.QUEST_FACTION_SAVE_LOAD_FAILED)
        # the SAVED faction state must equal the ledger post-state hash (mutated, not pre)
        ledger_path = REPO_ROOT / report["consequence_ledger_path"]
        if ledger_path.is_file():
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            saved_hash = _hash(blob.get("faction_state"))
            rep.check("sl::{}::saved_is_post_state".format(rid),
                      saved_hash == ledger.get("post_faction_state_hash"),
                      "saved faction-state hash must match ledger post hash "
                      "(got {} vs {})".format(saved_hash, ledger.get("post_faction_state_hash")),
                      code=F.QUEST_FACTION_SAVE_LOAD_FAILED)
        # report claim must be consistent with real roundtrip
        rep.check("sl::{}::report_claim_consistent".format(rid),
                  report.get("save_load_result") == "roundtrip_ok",
                  "report save_load_result must be roundtrip_ok",
                  code=F.QUEST_FACTION_SAVE_LOAD_FAILED)
        # quest_state in the blob round-trips its own contract
        qs = blob.get("quest_state", {})
        qfails = [c for c in QF.validate_quest_runtime_state(qs, strict=True) if not c[1]]
        rep.check("sl::{}::reloaded_quest_valid".format(rid), len(qfails) == 0,
                  "reloaded quest state invalid: {}".format([c[0] for c in qfails][:4]),
                  code=F.QUEST_FACTION_SAVE_LOAD_FAILED)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 save/load roundtrip gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    n = validate(rep)

    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-quest-faction-save-load", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.quest_faction.save_load_validation.v1"))
    SAVELOAD_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(SAVELOAD_DIR, "validate_quest_faction_save_load_report.json")
    rep.print_summary("validate-quest-faction-save-load")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
