#!/usr/bin/env python3
"""validate_runtime_interaction_verbs.py — WorldForge v1.6 verb gate (Agent 3B).

Proves each materialized interaction actor's verb is supported, matches the verb
its mission archetype maps to, emits that archetype's success event, and writes a
mission state key. This is the "each verb must emit an event and mutate state"
contract from the brief — an actor carrying a verb that does not match its
archetype, or that emits the wrong event, fails here.

Usage:
    python tools/pipeline/validate_runtime_interaction_verbs.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/runtime/interactions/validate_runtime_interaction_verbs_report.json
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.6 interaction verb gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    C = FailureCode

    rep = ValidationReport("pack", args.pack, strict=strict)
    d = REPO_ROOT / IC.INTERACTION_GENERATED_REL
    actors = sorted(d.glob("*.json")) if d.is_dir() else []
    if not actors:
        rep.error("no interaction actors — run 'make runtime-interaction-actors' first")

    verbs_seen = set()
    for p in actors:
        a = json.loads(p.read_text(encoding="utf-8"))
        aid = a.get("interaction_actor_id", p.stem)
        verb = a.get("verb")
        archetype = a.get("mission_archetype")
        verbs_seen.add(verb)
        rep.check("{}::verb_supported".format(aid), verb in IC.INTERACTION_VERBS,
                  "verb {!r} unsupported".format(verb), code=C.INTERACTION_VERB_UNSUPPORTED)
        expected_verb = IC.MISSION_ARCHETYPE_VERBS.get(archetype)
        rep.check("{}::verb_matches_archetype".format(aid), verb == expected_verb,
                  "verb {!r} != archetype {!r} verb {!r}".format(verb, archetype, expected_verb),
                  code=C.INTERACTION_VERB_UNSUPPORTED)
        rep.check("{}::emits_archetype_event".format(aid),
                  a.get("event_emitted") == IC.event_for_archetype(archetype),
                  "event {!r} != expected {!r}".format(
                      a.get("event_emitted"), IC.event_for_archetype(archetype)),
                  code=C.INTERACTION_EVENT_INVALID)
        rep.check("{}::writes_state_key".format(aid), bool(a.get("state_key_written")),
                  "actor must write a mission state key", code=C.INTERACTION_STATE_KEY_MISSING)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-runtime-interaction-verbs", pack=args.pack,
                            strict=strict, status=rep.status, record_count=len(actors),
                            report_type="wf.runtime.interaction_actor_materialization.v1",
                            extra={"verbs_seen": sorted(verbs_seen)}))
    rep.write(REPO_ROOT / IC.INTERACTION_REPORTS_REL,
              "validate_runtime_interaction_verbs_report.json")
    rep.print_summary("validate-runtime-interaction-verbs")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
