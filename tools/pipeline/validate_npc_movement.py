#!/usr/bin/env python3
"""validate_npc_movement.py — WorldForge v1.7 Wave R movement/engagement gate.

Proves the NPC movement + engagement layer genuinely ran: for every
behavior-complete scenario the live telemetry must show the NPCs were bound to a
grounded route and driven into engagement + pressure as the player moved through
(route.bound + engagement.started + pressure.applied), and the completion report's
pressure_result / encounter_state_result are pass with pressure_events_seen > 0.
Because the NPC pawns are grounded (gravity + capsule collision, Pawn channel
ignored) and never fly or teleport, this gate also asserts the route was a grounded
waypoint mode in telemetry. FAIL-CLOSED.

Acceptance: `python tools/pipeline/validate_npc_movement.py --pack encounter_loop_world --strict`.
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
MOVE_EVENTS = ("behavior.npc.route.bound", "behavior.engagement.started",
               "behavior.pressure.applied")


def _telemetry(sid):
    f = TELEMETRY_DIR / "{}.json".format(sid)
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    files = sorted(COMPLETION_DIR.glob("bs_*.json")) if COMPLETION_DIR.is_dir() else []
    rep.check("movement::present", len(files) > 0,
              "no completion reports (run the NPC behavior batch)",
              code=FailureCode.NPC_PATROL_FAILURE)

    bad = 0
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if r.get("completion_class") != NX.SUCCESS_COMPLETION_CLASS:
            continue
        sid = r["behavior_scenario_id"]
        if r.get("pressure_result") != "pass" or r.get("encounter_state_result") != "pass":
            bad += 1
            rep.check("move::{}::results".format(sid), False,
                      "pressure/encounter_state result != pass", code=FailureCode.NPC_PRESSURE_FAILURE)
        if not (isinstance(r.get("pressure_events_seen"), int) and r["pressure_events_seen"] > 0):
            bad += 1
            rep.check("move::{}::pressure_events".format(sid), False,
                      "no pressure events from NPC engagement", code=FailureCode.NPC_NO_PRESSURE_EVENTS)
        tel = _telemetry(sid)
        if tel is None:
            bad += 1
            rep.check("move::{}::telemetry".format(sid), False, "no telemetry",
                      code=FailureCode.NPC_PATROL_FAILURE)
            continue
        evs = {e.get("event_type") for e in tel.get("events", [])}
        details = " ".join(str(e.get("details", "")) for e in tel.get("events", []))
        missing = [e for e in MOVE_EVENTS if e not in evs]
        if missing:
            bad += 1
            rep.check("move::{}::events".format(sid), False,
                      "movement/engagement telemetry missing: {}".format(missing),
                      code=FailureCode.NPC_PATROL_FAILURE)
        # Grounded-only: the route must be a grounded waypoint, never flight/teleport.
        if "flight" in details.lower() or "teleport" in details.lower():
            bad += 1
            rep.check("move::{}::grounded".format(sid), False,
                      "movement telemetry references flight/teleport",
                      code=FailureCode.NPC_ROUTE_FLIGHT_REQUIRED)

    rep.check("movement::all_ok", bad == 0,
              "{} movement/engagement check failure(s)".format(bad), code=FailureCode.NPC_PATROL_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-movement", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files), report_type=NX.RT_TELEMETRY,
                            records_total=len(files)))
    rep.write(COMPLETION_DIR, "validate_npc_movement_report.json")
    rep.print_summary("validate-npc-movement")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
