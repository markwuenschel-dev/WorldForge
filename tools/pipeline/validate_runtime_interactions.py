#!/usr/bin/env python3
"""validate_runtime_interactions.py — WorldForge v1.6 interaction actor gate (Agent 3C).

Validates every materialized RuntimeInteractionActor against the frozen contract
(positive radius, supported verb, state key + event bindings, LOS flag) and the
structural rules: its mission exists, and no two actors claim the same
(map_id, objective_id). Radius-zero, unsupported-verb, and duplicate-objective
actors fail here for their owning codes.

Usage:
    python tools/pipeline/validate_runtime_interactions.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/runtime/interactions/validate_runtime_interactions_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import runtime_interaction_contract as IC
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

MISSION_CATALOG_REL = "procedural/generated/worldforge_mission_catalog.json"


def load_actors():
    d = REPO_ROOT / IC.INTERACTION_GENERATED_REL
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 interaction actor gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    missions = (json.loads((REPO_ROOT / MISSION_CATALOG_REL).read_text(encoding="utf-8"))
                .get("missions") or {})
    actors = load_actors()
    if not actors:
        rep.error("no interaction actors — run 'make runtime-interaction-actors' first")

    seen = {}
    for aid in sorted(actors):
        a = actors[aid]
        for name, ok, detail, code in IC.validate_interaction_actor(a, strict=strict):
            rep.check("{}::{}".format(aid, name), ok, detail, code=code)
        rep.check("{}::mission_exists".format(aid), a.get("mission_id") in missions,
                  "mission {!r} missing".format(a.get("mission_id")),
                  code=C.INTERACTION_MISSION_BRIDGE_FAILURE)
        key = (a.get("map_id"), a.get("objective_id"))
        rep.check("{}::unique_objective".format(aid), key not in seen,
                  "duplicate objective actor for {} (also {})".format(key, seen.get(key)),
                  code=C.INTERACTION_ACTOR_DUPLICATE)
        seen.setdefault(key, aid)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-runtime-interactions", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(actors),
                            report_type="wf.runtime.interaction_actor_materialization.v1",
                            extra={"actors": len(actors)}))
    rep.write(REPO_ROOT / IC.INTERACTION_REPORTS_REL, "validate_runtime_interactions_report.json")
    rep.print_summary("validate-runtime-interactions")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
