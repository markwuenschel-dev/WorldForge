#!/usr/bin/env python3
"""generate_progression_state.py — WorldForge v1.9 Wave 2 progression-lane producer.

THE producer for the progression lane. Draws the deterministic authoring scenario
set from reward_forge.build_authoring_scenarios() (the shared, stable spine) and
materializes every reward/progression evidence record to disk. Every record is
contract-validated with its matching reward_contracts.validate_* at strict=True
BEFORE it is written — an invalid record is skipped and reported, never written
(no invalid record ever reaches disk). Deterministic: no wall-clock / RNG; the
only timestamps come from build_meta.

Outputs (per scenario, in scenario order):
  * each grant_events record  -> REWARD_EVENT_GENERATED_REL/{event_id}.json
  * inventory_state           -> procedural/generated/progression/inventory/{scenario_id}.json
  * progression_state         -> procedural/generated/progression/progression/{scenario_id}.json
  * each unlock_states record -> procedural/generated/progression/unlocks/{unlock_id}__{scenario_id}.json
  * reward_completion         -> REWARD_COMPLETION_REPORTS_REL/reward_completion_{scenario_id}.json
  * reward_telemetry          -> REWARD_TELEMETRY_REPORTS_REL/reward_telemetry_{scenario_id}.json
    (this path MUST equal reward_completion["telemetry_path"] so it resolves)

Report -> procedural/reports/progression/generate_progression_state_report.json.
Fails (no zero-scenario success) if build_authoring_scenarios() yields nothing.

Acceptance: `python tools/pipeline/generate_progression_state.py --pack encounter_loop_world --strict`.
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

PROGRESSION_INVENTORY_REL = "procedural/generated/progression/inventory"
PROGRESSION_PROGRESSION_REL = "procedural/generated/progression/progression"
PROGRESSION_UNLOCKS_REL = "procedural/generated/progression/unlocks"
GEN_CODE = FailureCode.PROGRESSION_STATE_INVALID


def _write_json(rel_dir, filename, obj):
    """Write obj as pretty JSON under REPO_ROOT/rel_dir/filename; return the path."""
    out_dir = REPO_ROOT / rel_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / filename
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def _emit(rep, record, validate_fn, rel_dir, filename, label):
    """Validate a record at strict=True; write it iff clean, else skip+report.

    Returns 1 if written, 0 if skipped (invalid). NEVER writes an invalid record.
    """
    fails = [c for c in validate_fn(record, strict=True) if not c[1]]
    if fails:
        rep.check("gen::{}::valid".format(label), False,
                  "invalid {} not written: {}".format(label, [c[0] for c in fails][:4]),
                  code=GEN_CODE)
        return 0
    _write_json(rel_dir, filename, record)
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    scenarios = RF.build_authoring_scenarios()
    rep.check("gen::nonzero", len(scenarios) > 0,
              "build_authoring_scenarios produced {} scenario(s) (no zero-scenario "
              "success)".format(len(scenarios)), code=GEN_CODE)

    written = 0
    for sc in scenarios:
        sid = sc["scenario_id"]
        # grant events
        for ev in sc["grant_events"]:
            written += _emit(rep, ev, RX.validate_reward_grant_event,
                             RX.REWARD_EVENT_GENERATED_REL, "{}.json".format(ev["event_id"]),
                             "grant_event::{}".format(ev["event_id"]))
        # inventory state
        written += _emit(rep, sc["inventory_state"], RX.validate_inventory_state,
                         PROGRESSION_INVENTORY_REL, "{}.json".format(sid),
                         "inventory::{}".format(sid))
        # progression state
        written += _emit(rep, sc["progression_state"], RX.validate_progression_state,
                         PROGRESSION_PROGRESSION_REL, "{}.json".format(sid),
                         "progression::{}".format(sid))
        # unlock states
        for unl in sc["unlock_states"]:
            written += _emit(rep, unl, RX.validate_unlock_state,
                             PROGRESSION_UNLOCKS_REL,
                             "{}__{}.json".format(unl["unlock_id"], sid),
                             "unlock::{}__{}".format(unl["unlock_id"], sid))
        # reward completion report
        written += _emit(rep, sc["reward_completion"], RX.validate_reward_completion_report,
                         RX.REWARD_COMPLETION_REPORTS_REL,
                         "reward_completion_{}.json".format(sid),
                         "reward_completion::{}".format(sid))
        # reward telemetry — validated as a completion telemetry stream.
        written += _emit(
            rep, sc["reward_telemetry"],
            lambda o, strict=False: RX.validate_reward_telemetry(o, strict=strict, require_completion=True),
            RX.REWARD_TELEMETRY_REPORTS_REL, "reward_telemetry_{}.json".format(sid),
            "reward_telemetry::{}".format(sid))
        # The completion's telemetry_path MUST resolve to the file we just wrote.
        tel_path = sc["reward_completion"]["telemetry_path"]
        expected = "{}/reward_telemetry_{}.json".format(RX.REWARD_TELEMETRY_REPORTS_REL, sid)
        rep.check("gen::telemetry_path::{}".format(sid), tel_path == expected,
                  "reward_completion telemetry_path {!r} must equal {!r}".format(tel_path, expected),
                  code=FailureCode.REWARD_TELEMETRY_MISSING)

    rep.finalize()
    rep.set_meta(build_meta(command="generate-progression-state", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(scenarios),
                            report_type="wf.reward.progression_generate_report.v1",
                            records_total=len(scenarios),
                            extra={"records_written": written}))
    rep.write(REPO_ROOT / RX.PROGRESSION_REPORTS_REL, "generate_progression_state_report.json")
    rep.print_summary("generate-progression-state")
    print("[generate-progression-state] {} scenario(s), {} record(s) written".format(
        len(scenarios), written))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
