#!/usr/bin/env python3
"""validate_npc_perception.py — WorldForge v1.7 Wave R perception gate.

Proves the NPC perception layer genuinely ran: for every behavior-complete
scenario the live telemetry must carry both a perception CHECK and a perception
DETECTION event (the C++ AWFNPCPawn measured its distance to the real, moving
player and detected it within its perception radius), and the completion report's
perception_result must be pass. A run whose NPCs never perceived the player is not
active behavior and fails here. FAIL-CLOSED.

Acceptance: `python tools/pipeline/validate_npc_perception.py --pack encounter_loop_world --strict`.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import npc_contracts as NX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

COMPLETION_DIR = REPO_ROOT / NX.COMPLETION_REPORTS_REL
TELEMETRY_DIR = REPO_ROOT / NX.TELEMETRY_REPORTS_REL
SKIP = {"npc_behavior_rollup.json", "run_npc_behavior_batch_gate_report.json"}
PERCEPTION_EVENTS = ("behavior.perception.checked", "behavior.perception.detected")


def _events(sid):
    f = TELEMETRY_DIR / "{}.json".format(sid)
    if not f.is_file():
        return None
    try:
        return {e.get("event_type") for e in json.loads(f.read_text(encoding="utf-8")).get("events", [])}
    except Exception:  # noqa: BLE001
        return set()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    files = sorted(COMPLETION_DIR.glob("bs_*.json")) if COMPLETION_DIR.is_dir() else []
    rep.check("perception::present", len(files) > 0,
              "no completion reports (run the NPC behavior batch)",
              code=FailureCode.NPC_PERCEPTION_FAILURE)

    bad = 0
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if r.get("completion_class") != NX.SUCCESS_COMPLETION_CLASS:
            continue
        sid = r["behavior_scenario_id"]
        if r.get("perception_result") != "pass":
            bad += 1
            rep.check("perc::{}::result".format(sid), False, "perception_result != pass",
                      code=FailureCode.NPC_PERCEPTION_FAILURE)
        evs = _events(sid)
        missing = [e for e in PERCEPTION_EVENTS if evs is not None and e not in evs]
        if evs is None or missing:
            bad += 1
            rep.check("perc::{}::events".format(sid), False,
                      "perception telemetry missing: {}".format(missing or "no telemetry"),
                      code=FailureCode.NPC_PERCEPTION_FAILURE)

    rep.check("perception::all_ok", bad == 0,
              "{} perception check failure(s)".format(bad), code=FailureCode.NPC_PERCEPTION_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-perception", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files), report_type=NX.RT_TELEMETRY,
                            records_total=len(files)))
    rep.write(COMPLETION_DIR, "validate_npc_perception_report.json")
    rep.print_summary("validate-npc-perception")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
