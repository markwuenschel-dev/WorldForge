#!/usr/bin/env python3
r"""runtime_playtest_pack.py (UE5 Python) — WorldForge v1.6 LiveRuntimeForge driver.

The single-session UE runtime driver PlaytestForge Gamma consumes. It boots the
editor ONCE and, for every runtime scenario in
procedural/generated/runtime/scenarios/, drives a controlled pawn through the
real map and emits a completion report + telemetry stream that the offline
pipeline (run_playtest_forge_gamma.py) reads back.

Per scenario it must, in order:
    1. load the scenario's map
    2. spawn WF_RuntimeTestPawn at the spawn anchor and POSSESS it
    3. execute the route plan through navmesh/collision (NO teleport)
    4. approach the interaction actor and trigger its verb
    5. record telemetry events (scenario.started ... scenario.completed)
    6. verify mission state mutated
    7. save, reload, verify state persisted
    8. write procedural/reports/runtime/completion/<sid>.json (completed_runtime
       ONLY if every step above genuinely happened) + telemetry/<sid>.json

Runtime-truth rules enforced here, not just downstream:
    * completed_runtime is written ONLY with a real telemetry stream, a mutated
      state, and a verified save/load — otherwise a failed_* class + owning code.
    * teleport is never used to reach an objective.
    * UE errors are NEVER swallowed: any exception is logged with full traceback
      and the scenario is marked failed with RUNTIME_DRIVER_FAILURE.

Run headless (forward slashes; absolute uproject path):
    UnrealEditor-Cmd "D:/Unreal Projects/WorldForge/WorldForge.uproject" \
        -ExecutePythonScript="D:/Unreal Projects/WorldForge/tools/unreal/runtime_playtest_pack.py" \
        -unattended -nopause -stdout -nosplash

Prerequisite (v1.6 Agent 2B): the WF_RuntimeTestPawn / WF_RuntimeTestController /
WF_RuntimeInteractionComponent runtime classes must exist in the project. If they
are absent the driver FAILS LOUDLY (RUNTIME_PAWN_SPAWN_FAILURE) rather than
emitting a fake completion.
"""

import json
import os
import sys
import traceback

try:
    import unreal
except ImportError:  # not running inside the editor
    sys.stderr.write(
        "[runtime_playtest_pack] FATAL: this driver must run inside UnrealEditor-Cmd "
        "via -ExecutePythonScript. `import unreal` failed.\n")
    sys.exit(2)

ROOT = os.path.normpath(unreal.Paths.project_dir()).replace("\\", "/")
SCENARIO_DIR = ROOT + "/procedural/generated/runtime/scenarios"
COMPLETION_DIR = ROOT + "/procedural/reports/runtime/completion"
TELEMETRY_DIR = ROOT + "/procedural/reports/runtime/telemetry"

RUNTIME_PAWN_CLASS = "WF_RuntimeTestPawn"

# Failure codes mirrored from tools/pipeline/failure_codes.py (kept in sync).
FC_PAWN_SPAWN = "WF444_RUNTIME_PAWN_SPAWN_FAILURE"
FC_POSSESSION = "WF445_RUNTIME_PAWN_POSSESSION_FAILURE"
FC_MAP_LOAD = "WF442_RUNTIME_MAP_LOAD_FAILURE"
FC_DRIVER = "WF455_RUNTIME_DRIVER_FAILURE"


def _log(msg):
    unreal.log("[runtime_playtest_pack] " + msg)


def _err(msg):
    unreal.log_error("[runtime_playtest_pack] " + msg)


def _write(path, obj):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def _load_scenarios():
    out = {}
    if not os.path.isdir(SCENARIO_DIR):
        return out
    for name in sorted(os.listdir(SCENARIO_DIR)):
        if name.endswith(".json"):
            with open(os.path.join(SCENARIO_DIR, name), encoding="utf-8") as fh:
                out[name[:-5]] = json.load(fh)
    return out


def _runtime_pawn_available():
    """True iff the project actually provides the WF runtime pawn class. Without
    it there is no honest way to spawn+possess, so the driver must fail, not fake."""
    try:
        return unreal.load_class(None, "/Game/WorldForge/Runtime/{0}.{0}_C".format(
            RUNTIME_PAWN_CLASS)) is not None
    except Exception:
        return False


def _failed_report(scen, cclass, code, owner, detail):
    sid = scen.get("runtime_scenario_id")
    _err("{}: {} ({})".format(sid, detail, code))
    return {
        "report_id": "{}:completion".format(sid),
        "report_type": "wf.runtime.completion_report.v1",
        "schema_version": "wf.runtime.completion_report.v1",
        "pack": scen.get("pack"), "runtime_scenario_id": sid,
        "map_id": scen.get("map_id"), "mission_id": scen.get("mission_id"),
        "encounter_id": scen.get("encounter_id"), "biome": scen.get("biome"),
        "status": "fail", "completion_class": cclass, "failure_code": code,
        "failure_owner": owner, "spawn_result": "fail", "possession_result": "skipped",
        "route_result": "skipped", "interaction_result": "skipped",
        "state_result": "skipped", "save_load_result": "skipped",
        "telemetry_path": None, "screenshot_paths": [], "replay_path": None,
        "runtime_duration_seconds": 0.0, "distance_traveled": 0.0,
        "objective_events_seen": [], "state_transitions_seen": [],
        "created_at": "live", "git_commit": "live", "detail": detail,
    }


def run_scenario(sid, scen):
    """Drive one scenario. Returns (completion_report_dict, ok_bool).

    NOTE: steps 2-7 require the WF runtime pawn/interaction classes (v1.6 Agent
    2B). This driver loads the map and refuses to fabricate completion when those
    classes are absent — it fails with the owning code so the gap is visible.
    """
    try:
        # 1) load the map (mission maps live under /Game/WorldForge/Maps/)
        map_path = "/Game/WorldForge/Maps/{}".format(scen.get("map_id"))
        loaded = unreal.EditorLoadingAndSavingUtils.load_map(map_path)
        if loaded is None:
            return _failed_report(scen, "failed_navmesh", FC_MAP_LOAD, "map_load",
                                  "could not load map {}".format(map_path)), False

        # 2) spawn + possess — requires the WF runtime pawn class.
        if not _runtime_pawn_available():
            return _failed_report(
                scen, "failed_spawn", FC_PAWN_SPAWN, "spawn",
                "WF_RuntimeTestPawn class not found in project — build v1.6 Agent 2B "
                "runtime pawn/interaction classes before live traversal"), False

        # 3-7) route execution, interaction, state, save/load.
        # TODO(v1.6 Agent 2D/2E): drive WF_RuntimeTestController along the route
        # plan via navmesh, trigger the interaction verb, verify state + save/load,
        # emit telemetry, and only then build a completed_runtime report. Until the
        # runtime pawn is present this path is unreachable (guarded above), so the
        # driver never emits a fake completed_runtime.
        return _failed_report(scen, "failed_possession", FC_POSSESSION, "possession",
                              "runtime traversal not yet implemented in-project"), False
    except Exception:  # never swallow UE errors
        tb = traceback.format_exc()
        return _failed_report(scen, "failed_report_integrity", FC_DRIVER, "driver",
                              "driver exception:\n" + tb), False


def main():
    scenarios = _load_scenarios()
    _log("loaded {} runtime scenarios from {}".format(len(scenarios), SCENARIO_DIR))
    if not scenarios:
        _err("no runtime scenarios — run 'make runtime-scenarios' first")
        sys.exit(1)

    n_completed, n_failed = 0, 0
    for sid in sorted(scenarios):
        report, ok = run_scenario(sid, scenarios[sid])
        _write("{}/{}.json".format(COMPLETION_DIR, sid), report)
        if ok and report.get("completion_class") == "completed_runtime":
            n_completed += 1
        else:
            n_failed += 1

    rollup = {"driver": "runtime_playtest_pack", "scenarios": len(scenarios),
              "completed_runtime": n_completed, "failed": n_failed}
    _write("{}/_runtime_driver_rollup.json".format(COMPLETION_DIR), rollup)
    _log("done: {}/{} completed_runtime, {} failed".format(
        n_completed, len(scenarios), n_failed))
    # Nonzero unless every scenario genuinely completed — no partial-as-success.
    sys.exit(0 if n_completed == len(scenarios) and n_completed > 0 else 1)


if __name__ == "__main__":
    main()
