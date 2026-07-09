#!/usr/bin/env python3
"""validate_npc_runtime_core.py — WorldForge v1.7 Wave R runtime-core gate.

Proves the NPC runtime CORE genuinely executed for every behavior-complete
scenario: NPCs were spawned in-engine (npc_count > 0), the controller/behavior was
initialized and the route bound (spawn_result / route_binding_result = pass), and
the run carries the runtime-core telemetry events (npc.spawned +
npc.possessed_or_initialized + npc.route.bound). This is the runtime counterpart to
the schema-layer spawn/route gates — it reads the LIVE evidence the C++
AWFEncounterManager / AWFNPCPawn emitted, not the authoring data. FAIL-CLOSED.

Acceptance: `python tools/pipeline/validate_npc_runtime_core.py --pack encounter_loop_world --strict`.
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
CORE_EVENTS = ("behavior.npc.spawned", "behavior.npc.possessed_or_initialized",
               "behavior.npc.route.bound")


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
    rep.check("runtime_core::present", len(files) > 0,
              "no completion reports (run the NPC behavior batch)",
              code=FailureCode.NPC_RUNTIME_SPAWN_FAILURE)

    bad = 0
    for f in files:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if r.get("completion_class") != NX.SUCCESS_COMPLETION_CLASS:
            continue
        sid = r["behavior_scenario_id"]
        if not (isinstance(r.get("npc_count"), int) and r["npc_count"] > 0):
            bad += 1
            rep.check("core::{}::spawned".format(sid), False, "zero NPCs spawned at runtime",
                      code=FailureCode.NPC_RUNTIME_SPAWN_FAILURE)
        if r.get("spawn_result") != "pass":
            bad += 1
            rep.check("core::{}::spawn_result".format(sid), False, "spawn_result != pass",
                      code=FailureCode.NPC_RUNTIME_SPAWN_FAILURE)
        if r.get("route_binding_result") != "pass":
            bad += 1
            rep.check("core::{}::route".format(sid), False, "route_binding_result != pass",
                      code=FailureCode.NPC_ROUTE_BINDING_FAILURE)
        evs = _events(sid)
        missing = [e for e in CORE_EVENTS if evs is not None and e not in evs]
        if evs is None or missing:
            bad += 1
            rep.check("core::{}::events".format(sid), False,
                      "runtime-core telemetry missing: {}".format(missing or "no telemetry"),
                      code=FailureCode.NPC_CONTROLLER_INIT_FAILURE)

    rep.check("runtime_core::all_ok", bad == 0,
              "{} runtime-core check failure(s)".format(bad),
              code=FailureCode.NPC_RUNTIME_SPAWN_FAILURE)
    rep.finalize()
    rep.set_meta(build_meta(command="validate-npc-runtime-core", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(files), report_type=NX.RT_COMPLETION,
                            records_total=len(files)))
    rep.write(COMPLETION_DIR, "validate_npc_runtime_core_report.json")
    rep.print_summary("validate-npc-runtime-core")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
