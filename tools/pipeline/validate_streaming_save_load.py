#!/usr/bin/env python3
"""validate_streaming_save_load.py — v2.3 Wave 4 cross-tile save/load gate.

Proves cross-tile state survives save/load: for each of the 24 runs there is a
CrossTileSaveState that is contract-valid, round-trips, carries a tile_state_hash for
every visited/loaded tile, links a resolvable player_location_anchor_id, and carries
mission/quest/faction state hashes (quest/faction present because every streamed
mission binds a v2.2 quest). A run whose report claims roundtrip_ok with no matching,
hash-complete save state fails here.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_streaming_save_load.py --strict
Reports -> procedural/reports/streaming/save_load/validate_streaming_save_load_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import streaming_contracts as SC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

RUNTIME_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "runtime"
SAVELOAD_DIR = REPO_ROOT / "procedural" / "reports" / "streaming" / "save_load"
ANCHORS_DIR = REPO_ROOT / "procedural" / "generated" / "anchors"
REPORT_DIR = SAVELOAD_DIR


def validate(rep):
    anchor_ids = {p.stem for p in ANCHORS_DIR.glob("*.json")}
    run_dirs = sorted([d for d in RUNTIME_DIR.iterdir()
                       if d.is_dir() and (d / "report.json").is_file()])
    rep.check("save_load::runs_24", len(run_dirs) == SC.EXPECTED_SCENARIO_COUNT,
              "expected 24 runs (got {})".format(len(run_dirs)), code=F.STREAMING_PARTIAL_MATRIX)
    n = 0
    for d in run_dirs:
        report = json.loads((d / "report.json").read_text(encoding="utf-8"))
        rid = report["run_id"]
        n += 1
        sp = SAVELOAD_DIR / (rid + ".json")
        rep.check("sl::{}::present".format(rid), sp.is_file(),
                  "save state missing for run {}".format(rid), code=F.STREAMING_CROSS_TILE_SAVE_MISSING)
        if not sp.is_file():
            continue
        ss = json.loads(sp.read_text(encoding="utf-8"))
        fails = [c for c in SC.validate_cross_tile_save_state(ss, strict=True) if not c[1]]
        rep.check("sl::{}::contract".format(rid), len(fails) == 0,
                  "save state invalid: {}".format([c[0] for c in fails][:4]),
                  code=F.STREAMING_CROSS_TILE_SAVE_FAILED)
        rep.check("sl::{}::roundtrip".format(rid), ss.get("roundtrip_result") == "roundtrip_ok",
                  "save state must be roundtrip_ok", code=F.STREAMING_CROSS_TILE_SAVE_FAILED)
        # tile hashes for every loaded tile
        loaded = ss.get("loaded_tile_ids", [])
        hashes = ss.get("tile_state_hashes", {})
        rep.check("sl::{}::tile_hashes_complete".format(rid),
                  isinstance(hashes, dict) and all(t in hashes for t in loaded) and len(hashes) >= 2,
                  "every loaded tile needs a state hash", code=F.STREAMING_CROSS_TILE_SAVE_MISSING)
        # player anchor resolves
        rep.check("sl::{}::player_anchor_resolves".format(rid),
                  ss.get("player_location_anchor_id") in anchor_ids,
                  "player_location_anchor_id must resolve to a real anchor",
                  code=F.STREAMING_ANCHOR_INVALID)
        # mission/quest/faction hashes present (quest/faction required — v2.2 hooks)
        for f in ("mission_state_hash", "quest_state_hash", "faction_state_hash"):
            rep.check("sl::{}::{}".format(rid, f), bool(ss.get(f)),
                      "{} required (v2.2 quest/faction hooks active)".format(f),
                      code=F.STREAMING_QUEST_STATE_MISSING if "quest" in f
                      else (F.STREAMING_FACTION_STATE_MISSING if "faction" in f
                            else F.STREAMING_CROSS_TILE_SAVE_MISSING))
        # report claim consistent
        rep.check("sl::{}::report_claim_consistent".format(rid),
                  report.get("cross_tile_save_load_result") == "roundtrip_ok",
                  "runtime report save/load result must be roundtrip_ok",
                  code=F.STREAMING_CROSS_TILE_SAVE_FAILED)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 cross-tile save/load gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)
    n = validate(rep)
    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-streaming-save-load", pack=args.pack, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.streaming.save_load_validation.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_streaming_save_load_report.json")
    rep.print_summary("validate-streaming-save-load")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
