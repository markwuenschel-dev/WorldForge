#!/usr/bin/env python3
"""validate_runtime_mission_completion_bridge.py — WorldForge v1.6 completion bridge (Agent 3D).

Connects interaction events to mission completion: for every runtime scenario,
its required interaction must be backed by a materialized interaction actor on the
same map whose emitted event equals the scenario's expected_event, and whose
state key equals the scenario's expected_state_transition key. This is what makes
"the pawn does the interaction -> the mission completes" a real, checkable wire
rather than an assumption. A scenario whose objective has no backing actor, or
whose event/state key does not line up, fails here.

Usage:
    python tools/pipeline/validate_runtime_mission_completion_bridge.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/runtime/interactions/validate_runtime_mission_completion_bridge_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_interaction_contract as IC
import runtime_scenario_contract as SC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode


def _load_dir(rel):
    d = REPO_ROOT / rel
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 mission completion bridge gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    scenarios = _load_dir(SC.SCENARIO_GENERATED_REL)
    actors = list(_load_dir(IC.INTERACTION_GENERATED_REL).values())
    if not scenarios:
        rep.error("no runtime scenarios — run 'make runtime-scenarios' first")
    if not actors:
        rep.error("no interaction actors — run 'make runtime-interaction-actors' first")

    # Index actors by (map_id, event_emitted) and (map_id, state_key_written).
    by_event = {(a.get("map_id"), a.get("event_emitted")) for a in actors}
    by_state = {(a.get("map_id"), a.get("state_key_written")) for a in actors}

    for sid in sorted(scenarios):
        scen = scenarios[sid]
        map_id = scen.get("map_id")
        ris = scen.get("required_interactions") or []
        for i, ri in enumerate(ris):
            ev = ri.get("expected_event") if isinstance(ri, dict) else None
            rep.check("{}::actor_emits_event[{}]".format(sid, i), (map_id, ev) in by_event,
                      "no interaction actor on {} emits {!r}".format(map_id, ev),
                      code=C.INTERACTION_EVENT_MISSING)
        for j, tr in enumerate(scen.get("expected_state_transitions") or []):
            key = tr.get("key") if isinstance(tr, dict) else None
            rep.check("{}::actor_writes_state[{}]".format(sid, j), (map_id, key) in by_state,
                      "no interaction actor on {} writes state key {!r}".format(map_id, key),
                      code=C.INTERACTION_STATE_MUTATION_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-runtime-mission-completion-bridge", pack=args.pack,
                            strict=strict, status=rep.status, record_count=len(scenarios),
                            report_type="wf.runtime.interaction_actor_materialization.v1",
                            extra={"scenarios": len(scenarios), "actors": len(actors)}))
    rep.write(REPO_ROOT / IC.INTERACTION_REPORTS_REL,
              "validate_runtime_mission_completion_bridge_report.json")
    rep.print_summary("validate-runtime-mission-completion-bridge")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
