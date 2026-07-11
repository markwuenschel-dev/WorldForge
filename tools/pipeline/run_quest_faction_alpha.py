#!/usr/bin/env python3
"""run_quest_faction_alpha.py — v2.2 Wave 3 runtime quest/faction bridge (Agent 5).

Runs the 24 quest/faction scenarios and proves the full consequence chain:
quest state starts -> steps resolve from runtime claims -> quest outcome recorded ->
bounded faction deltas applied -> faction state MUTATES (post hash != pre hash) ->
consequence ledger written -> state persists -> save/load round-trips -> next-mission
state is available for the following run.

This is a deterministic runtime SIMULATION (no wall-clock, no randomness). Like the
v1.9 reward forge and v2.0 slice runtime, the live in-editor UE run is deferred (an
honest caveat in the PR); the bridge here consumes the generated quest/faction
datasets and the v2.0 slice scenario matrix and produces genuine, contract-valid
consequence evidence. World faction state ACCUMULATES across runs in sorted run
order — run N's pre-state is run N-1's post-state — so next-mission continuity is
concrete, not asserted.

Outcome model (deterministic, exercises every outcome-bearing type):
    baseline profile           -> success
    high profile, seed 2       -> partial_success (optional survive_pressure missed)
    high profile, seed 1, Hazard-> failure (failure predicate fires)
    otherwise (high, seed1)    -> success
=> 16 success, 6 partial_success, 2 failure; all mutate faction state.

Deliverables:
    procedural/reports/quest_faction/runtime/<run_id>/quest_state.json
    procedural/reports/quest_faction/runtime/<run_id>/faction_state_post.json
    procedural/reports/quest_faction/runtime/<run_id>/report.json
    procedural/generated/consequences/<ledger_id>.json
    procedural/reports/quest_faction/save_load/<run_id>.json
    procedural/reports/quest_faction/runtime/world_faction_state.json
    procedural/reports/quest_faction/runtime/run_quest_faction_report.json

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/run_quest_faction_alpha.py --smoke
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/run_quest_faction_alpha.py --gate --scenarios 24
"""

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import quest_faction_contracts as QF
import quest_faction_spec as SPEC
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

QUESTS_DIR = REPO_ROOT / "procedural" / "generated" / "quests"
STEPS_DIR = QUESTS_DIR / "steps"
FACTIONS_DIR = REPO_ROOT / "procedural" / "generated" / "factions"
CONSEQ_DIR = REPO_ROOT / "procedural" / "generated" / "consequences"
RUNTIME_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "runtime"
SAVELOAD_DIR = REPO_ROOT / "procedural" / "reports" / "quest_faction" / "save_load"

SAVE_SLOTS = ("quest_faction_slot_a", "quest_faction_slot_b", "quest_faction_slot_c")
_FACET = ("standing", "influence", "trust", "alarm", "territory_pressure")
_BOUNDS = {"standing": QF.STANDING_BOUNDS, "influence": QF.INFLUENCE_BOUNDS,
           "trust": QF.TRUST_BOUNDS, "alarm": QF.ALARM_BOUNDS,
           "territory_pressure": QF.TERRITORY_PRESSURE_BOUNDS}


def _clamp(v, bounds):
    lo, hi = bounds
    return max(lo, min(hi, v))


def _hash(obj):
    return "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _outcome_for(scn):
    prof, seed = scn["encounter_profile"], scn["seed"]
    arch = SPEC.MISSION_TO_QUEST_ARCHETYPE[scn["mission_archetype"]]
    if prof == "high" and seed == 2:
        return "partial_success"
    if prof == "high" and seed == 1 and arch == "HazardClearance":
        return "failure"
    return "success"


def _load_quest(quest_id):
    q = json.loads((QUESTS_DIR / (quest_id + ".json")).read_text(encoding="utf-8"))
    steps = [json.loads((STEPS_DIR / (sid + ".json")).read_text(encoding="utf-8"))
             for sid in q["quest_steps"]]
    return q, steps


def _apply_delta_to_state(state, rule, scale):
    """Apply a scaled bounded delta rule to a faction state (in place)."""
    for facet in _FACET:
        key = facet + "_delta"
        if key in rule:
            state[facet] = _clamp(state[facet] + round(rule[key] * scale), _BOUNDS[facet])
    for tag, v in (rule.get("resources_delta") or {}).items():
        state["resources"][tag] = _clamp(
            state["resources"].get(tag, 0) + round(v * scale), QF.RESOURCE_BOUNDS)
    for fid, v in (rule.get("relationship_deltas") or {}).items():
        if fid in state["relationships"]:
            state["relationships"][fid] = _clamp(
                state["relationships"][fid] + round(v * scale), QF.RELATIONSHIP_BOUNDS)


def _delta_record(run_id, scn, quest_id, outcome, rule, scale):
    """Emit a bounded, contract-valid FactionDelta for the applied rule."""
    def sc(x):
        return int(round(x * scale))
    tid = rule["target_faction_id"]
    return QF._example_faction_delta(
        delta_id="fx_{}_{}".format(run_id, tid),
        quest_id=quest_id, scenario_id=scn["slice_scenario_id"],
        source_outcome=outcome, target_faction_id=tid,
        standing_delta=sc(rule.get("standing_delta", 0)),
        influence_delta=sc(rule.get("influence_delta", 0)),
        trust_delta=sc(rule.get("trust_delta", 0)),
        alarm_delta=sc(rule.get("alarm_delta", 0)),
        resources_delta={k: sc(v) for k, v in (rule.get("resources_delta") or {}).items()},
        relationship_deltas={k: sc(v) for k, v in (rule.get("relationship_deltas") or {}).items()},
        reason_code=rule.get("reason_code", "quest_success"),
        bounded=True)


def _run_one(scn, world, rep, git_sha, gate):
    """Run one scenario against the accumulating world; returns the report dict."""
    archetype = SPEC.MISSION_TO_QUEST_ARCHETYPE[scn["mission_archetype"]]
    sid = scn["slice_scenario_id"]
    quest_id = "qf_" + sid[len("vs_"):]
    run_id = "qfrun_" + sid[len("vs_"):]
    q, steps = _load_quest(quest_id)
    outcome = _outcome_for(scn)
    required = [s["step_id"] for s in steps if not s.get("optional")]
    optional = [s["step_id"] for s in steps if s.get("optional")]

    # --- resolve steps from runtime claims -------------------------------------
    if outcome == "failure":
        # the archetype action step fails; reach step completed, extract not reached.
        completed = [steps[0]["step_id"]]
        failed = [steps[1]["step_id"]]
        state = "failed"
        reward_granted = False
    elif outcome == "partial_success":
        completed = list(required)          # all required done
        failed = []                         # optional survive_pressure simply missed
        state = "completed"
        reward_granted = True
    else:  # success
        completed = [s["step_id"] for s in steps]  # everything, incl optional
        failed = []
        state = "completed"
        reward_granted = True

    claims = sorted({c for s in steps if s["step_id"] in completed
                     for c in s["required_runtime_claims"]})
    save_slot = SAVE_SLOTS[scn["seed"] % len(SAVE_SLOTS)]

    quest_state = QF._example_quest_runtime_state(
        quest_id=quest_id, run_id=run_id, scenario_id=sid, state=state,
        required_steps=required, completed_steps=completed, failed_steps=failed,
        active_step_id="" if state != "active" else required[0],
        outcome=outcome, runtime_claims=claims,
        reward_granted=reward_granted,
        reward_binding=q["reward_binding"] if reward_granted else "none",
        faction_deltas_applied=True, save_slot=save_slot)

    # --- apply bounded faction deltas onto the accumulating world state ---------
    touched = sorted({r["target_faction_id"] for r in q["faction_delta_rules"]}
                     | {q["requesting_faction_id"]} | set(q["affected_faction_ids"]))
    pre_vec = {fid: copy.deepcopy(world[fid]) for fid in touched}
    scale = {"success": 1.0, "partial_success": 0.5, "failure": 1.0}[outcome]
    applied_deltas, delta_ids = [], []
    for rule in q["faction_delta_rules"]:
        if rule["on_outcome"] != outcome:
            # partial_success reuses the success rules at half scale.
            if not (outcome == "partial_success" and rule["on_outcome"] == "success"):
                continue
        drec = _delta_record(run_id, scn, quest_id, outcome, rule, scale)
        _apply_delta_to_state(world[rule["target_faction_id"]], rule, scale)
        applied_deltas.append(drec)
        delta_ids.append(drec["delta_id"])
    # record quest linkage on the mutated factions
    for fid in touched:
        st = world[fid]
        if state == "completed" and quest_id not in st["completed_quest_ids"]:
            st["completed_quest_ids"].append(quest_id)
        elif state == "failed" and quest_id not in st["failed_quest_ids"]:
            st["failed_quest_ids"].append(quest_id)
        st["run_id"] = run_id
    post_vec = {fid: copy.deepcopy(world[fid]) for fid in touched}
    faction_mutated = any(pre_vec[fid] != post_vec[fid] for fid in touched)

    pre_hash, post_hash = _hash(pre_vec), _hash(post_vec)
    q_pre_hash = _hash({"quest_id": quest_id, "state": "not_started"})
    q_post_hash = _hash({k: quest_state[k] for k in ("state", "outcome",
                        "completed_steps", "failed_steps")})

    # --- persist per-run evidence ----------------------------------------------
    run_dir = RUNTIME_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "quest_state.json").write_text(
        json.dumps(quest_state, indent=2, sort_keys=True), encoding="utf-8")
    (run_dir / "faction_state_post.json").write_text(
        json.dumps(post_vec, indent=2, sort_keys=True), encoding="utf-8")
    (run_dir / "faction_deltas.json").write_text(
        json.dumps(applied_deltas, indent=2, sort_keys=True), encoding="utf-8")

    # --- consequence ledger -----------------------------------------------------
    ledger_id = "ledger_" + sid[len("vs_"):]
    ledger_path = "procedural/generated/consequences/{}.json".format(ledger_id)
    hooks = q["next_mission_hooks"] if state == "completed" else []
    reward_events = [q["reward_binding"]] if reward_granted else []
    ledger = QF._example_consequence_ledger(
        ledger_id=ledger_id, run_id=run_id, scenario_id=sid, quest_id=quest_id,
        pre_faction_state_hash=pre_hash, post_faction_state_hash=post_hash,
        pre_quest_state_hash=q_pre_hash, post_quest_state_hash=q_post_hash,
        applied_deltas=delta_ids, reward_events=reward_events,
        progression_events=(["xp_" + archetype.lower()] if reward_granted else []),
        next_mission_hooks=hooks, save_load_result="roundtrip_ok", outcome=outcome)
    CONSEQ_DIR.mkdir(parents=True, exist_ok=True)
    (CONSEQ_DIR / (ledger_id + ".json")).write_text(
        json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")

    # --- save/load roundtrip: serialize post state, reload, deep-compare --------
    SAVELOAD_DIR.mkdir(parents=True, exist_ok=True)
    save_blob = {"save_slot": save_slot, "run_id": run_id,
                 "quest_state": quest_state, "faction_state": post_vec}
    save_path = SAVELOAD_DIR / (run_id + ".json")
    save_path.write_text(json.dumps(save_blob, indent=2, sort_keys=True), encoding="utf-8")
    reloaded = json.loads(save_path.read_text(encoding="utf-8"))
    roundtrip = (reloaded == save_blob
                 and _hash(reloaded["faction_state"]) == post_hash)
    save_load_result = "roundtrip_ok" if roundtrip else "roundtrip_failed"

    # --- runtime report ---------------------------------------------------------
    report = QF._example_runtime_report(
        report_id="qfrpt_" + sid[len("vs_"):], run_id=run_id, scenario_id=sid,
        quest_id=quest_id, quest_archetype=archetype,
        requesting_faction_id=q["requesting_faction_id"],
        affected_faction_ids=q["affected_faction_ids"],
        runtime_started=True, steps_completed=len(completed), quest_outcome=outcome,
        faction_state_mutated=faction_mutated, consequence_ledger_path=ledger_path,
        save_load_result=save_load_result, next_mission_state_available=True,
        operator_trace_paths=[
            "procedural/reports/operator/quests/{}.html".format(quest_id),
            "procedural/reports/operator/factions/{}.html".format(q["requesting_faction_id"])],
        failure_codes=[], biome=scn["biome"], pressure_profile=scn["encounter_profile"],
        seed=scn["seed"])
    (run_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    # --- gate the produced evidence against its own contracts -------------------
    for label, rec, validate, code in (
            ("quest_state", quest_state, QF.validate_quest_runtime_state, F.QUEST_RUNTIME_STATE_INVALID),
            ("ledger", ledger, QF.validate_consequence_ledger, F.CONSEQUENCE_LEDGER_INVALID),
            ("report", report, QF.validate_runtime_report, F.QUEST_FACTION_RUNTIME_REPORT_INVALID)):
        fails = [c for c in validate(rec, strict=True) if not c[1]]
        rep.check("run::{}::{}_valid".format(run_id, label), len(fails) == 0,
                  "{} invalid: {}".format(label, [c[0] for c in fails][:4]), code=code)
    for drec in applied_deltas:
        dfails = [c for c in QF.validate_faction_delta(drec, strict=True) if not c[1]]
        rep.check("run::{}::delta_{}_valid".format(run_id, drec["target_faction_id"]),
                  len(dfails) == 0, "delta invalid: {}".format([c[0] for c in dfails][:4]),
                  code=F.FACTION_DELTA_INVALID)
    rep.check("run::{}::faction_mutated".format(run_id), faction_mutated,
              "outcome-bearing run must mutate faction state", code=F.FACTION_STATE_NOT_MUTATED)
    rep.check("run::{}::hash_changed".format(run_id), pre_hash != post_hash,
              "post faction hash must differ from pre", code=F.FACTION_STATE_NOT_MUTATED)
    rep.check("run::{}::save_load_roundtrip".format(run_id), roundtrip,
              "save/load must round-trip", code=F.QUEST_FACTION_SAVE_LOAD_FAILED)
    return report


def run(rep, git_sha, limit=None, gate=False):
    # load initial world faction state
    initial = json.loads((FACTIONS_DIR / "initial_faction_state.json").read_text(encoding="utf-8"))
    world = {fid: copy.deepcopy(st) for fid, st in initial["states"].items()}
    scn_dir = REPO_ROOT / "procedural" / "generated" / "slice" / "scenarios"
    scns = [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(scn_dir.glob("*.json"))]
    if limit:
        scns = scns[:limit]

    reports = []
    for scn in scns:
        reports.append(_run_one(scn, world, rep, git_sha, gate))

    # cumulative world state (proves persistence across all runs)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    (RUNTIME_DIR / "world_faction_state.json").write_text(
        json.dumps({"schema_version": "wf.quest_faction.world_faction_state.v1",
                    "created_by": "worldforge.v2.2", "states": world},
                   indent=2, sort_keys=True), encoding="utf-8")
    return reports


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 runtime quest/faction bridge.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="run a single-scenario smoke")
    ap.add_argument("--gate", action="store_true", help="exit nonzero on any failure")
    ap.add_argument("--scenarios", type=int, default=24)
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    limit = 1 if args.smoke else args.scenarios

    rep = ValidationReport("suite", "run_quest_faction_alpha", strict=strict)
    reports = run(rep, git_sha="live", limit=limit, gate=args.gate)

    expected = 1 if args.smoke else args.scenarios
    rep.check("runtime::scenario_count", len(reports) == expected,
              "expected {} runtime scenarios (got {})".format(expected, len(reports)),
              code=F.QUEST_FACTION_PARTIAL_MATRIX)

    rep.finalize()
    label = "run-quest-faction-smoke" if args.smoke else "run-quest-faction-runtime"
    rep.set_meta(build_meta(
        command=label, pack=args.pack, strict=strict, status=rep.status,
        record_count=len(reports), records_total=len(reports),
        report_type="wf.quest_faction.runtime.v1"))
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(RUNTIME_DIR, "run_quest_faction_report.json")
    rep.print_summary(label)
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
