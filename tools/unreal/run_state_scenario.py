r"""
run_state_scenario.py (UE5 Python)

Runtime StateForge UE bridge — applies a simulated scenario result in-editor and
reads the MPC render-mirror back, proving the data-layer expectation matches the
live UWorldStateSubsystem -> MPC_WorldState path.

Reads result.json (JSON only — UE scripts must not use PyYAML) produced by
run_state_sim.py, applies each post-state value via the WorldForge.SetState
console command (the same path the console tracer uses), then reads back the
curated MPC scalar params and compares them to expected_mpc.

Writes a UE report consumed by validate_runtime_state.py:
    procedural/reports/scenarios/<run_id>/ue_state_scenario_report.json

Run inside the editor with the scenario's slice map open so the world's
UWorldStateSubsystem and MPC_WorldState instance are live.

Usage:
    py tools/unreal/run_state_scenario.py \
        --result procedural/generated/scenarios/<run_id>/result.json \
        --project-root .
"""

import argparse
import json
import os

import unreal

MPC_PATH = "/CoreTerrainMaterials/State/MPC_WorldState"
_EPS = 1e-3


def _editor_world():
    try:
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        return ues.get_editor_world()
    except Exception:
        try:
            return unreal.EditorLevelLibrary.get_editor_world()
        except Exception:
            return None


def main():
    ap = argparse.ArgumentParser(description="Apply a runtime-state scenario result in UE and read back the MPC.")
    ap.add_argument("--result", required=True, help="Path to run_state_sim result.json")
    ap.add_argument("--project-root", default=".", help="Repo root (for report output)")
    args = ap.parse_args()

    repo_root = os.path.abspath(args.project_root)
    result_path = args.result
    if not os.path.isabs(result_path):
        result_path = os.path.join(repo_root, result_path)

    with open(result_path, "r", encoding="utf-8") as fh:
        descriptor = json.load(fh)

    run_id = descriptor.get("run_id", "unknown")
    scope = descriptor.get("scope", "Region")
    context_id = descriptor.get("context_id", "")
    after_state = descriptor.get("after_state", {})
    expected_mpc = descriptor.get("expected_mpc", {})

    report = {
        "run_id": run_id,
        "applied": {},
        "mpc_readback": {},
        "checks": {},
        "passed": False,
    }

    world = _editor_world()
    if world is None:
        report["error"] = "no editor world; open the scenario's slice map first"
        unreal.log_error("[run-state-scenario] {}".format(report["error"]))
        _write_report(repo_root, run_id, report)
        return

    # -- Apply each post-state value via the console tracer ------------------
    for key, value in after_state.items():
        cmd = "WorldForge.SetState {} {} {} {}".format(scope, context_id, key, value)
        unreal.SystemLibrary.execute_console_command(world, cmd)
        report["applied"][key] = value
        unreal.log("[run-state-scenario] {}".format(cmd))

    # -- Read back the curated MPC scalar params ----------------------------
    mpc = unreal.load_asset(MPC_PATH)
    all_ok = bool(mpc)
    if not mpc:
        report["error"] = "MPC_WorldState not found at {}".format(MPC_PATH)
    else:
        for param, expected in expected_mpc.items():
            try:
                # MPC scalar get/set live on UKismetMaterialLibrary, exposed to
                # Python as unreal.MaterialLibrary.
                got = unreal.MaterialLibrary.get_scalar_parameter_value(
                    world, mpc, unreal.Name(param))
            except Exception as exc:
                got = None
                report["checks"]["readback_{}".format(param)] = "error: {}".format(exc)
            report["mpc_readback"][param] = got
            ok = got is not None and abs(float(got) - float(expected)) < _EPS
            report["checks"][param] = {"expected": expected, "got": got, "ok": ok}
            all_ok = all_ok and ok

    report["passed"] = all_ok
    # convenience scalar used by the validator's warn-only readback display
    if len(expected_mpc) == 1:
        only = next(iter(expected_mpc))
        report["mpc_readback_value"] = report["mpc_readback"].get(only)
    _write_report(repo_root, run_id, report)
    unreal.log("[run-state-scenario] {} — {}".format("PASS" if all_ok else "FAIL", run_id))


def _write_report(repo_root, run_id, report):
    out_dir = os.path.join(repo_root, "procedural", "reports", "scenarios", run_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "ue_state_scenario_report.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    unreal.log("[run-state-scenario] report -> {}".format(out_path))


if __name__ == "__main__":
    main()
