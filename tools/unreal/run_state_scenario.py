r"""
run_state_scenario.py (UE5 Python)

Runtime StateForge UE bridge — records whether an editor-side runtime check can
obtain native state-write authority.

Reads result.json (JSON only — UE scripts must not use PyYAML) produced by
run_state_sim.py. Editor Python intentionally cannot acquire a native
FWorldForgeStateWriteLease, so this script writes an explicit unavailable result
instead of forging state through reflection, an MPC edit, or a console command.

Writes a UE report consumed by validate_runtime_state.py:
    procedural/reports/scenarios/<run_id>/ue_state_scenario_report.json

Run inside the editor with the scenario's slice map open when an owning native
writer is available.

Usage:
    py tools/unreal/run_state_scenario.py \
        --result procedural/generated/scenarios/<run_id>/result.json \
        --project-root .
"""

import argparse
import json
import os

import unreal

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
    ap = argparse.ArgumentParser(
        description="Report native write-authority availability for a runtime-state scenario in UE.")
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

    authority_error = (
        "native state-write authority is required; editor Python cannot acquire "
        "a world-state write lease")
    report["authority"] = {"status": "native_authority_required", "detail": authority_error}
    report["checks"]["native_write_authority"] = {"ok": False, "detail": authority_error}
    report["error"] = authority_error
    _write_report(repo_root, run_id, report)
    unreal.log_error("[run-state-scenario] FAIL — {}: {}".format(run_id, authority_error))


def _stamp(repo_root, report):
    """When this ran, and at which revision. Written by the PRODUCER.

    Without these two fields the report is ungradeable for freshness, and a
    validator has no honest option but to accept a result of unknown age --
    which is how a runtime-behaviour claim from months ago kept certifying a
    gate. mtime cannot substitute: it moves when a file is copied and says
    nothing about when the editor actually ran.
    """
    import datetime
    import subprocess
    report["timestamp"] = datetime.datetime.now(
        datetime.timezone.utc).replace(microsecond=0).isoformat()
    sha = None
    try:
        proc = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=20)
        if proc.returncode == 0:
            sha = proc.stdout.strip() or None
    except Exception:  # noqa: BLE001 -- a missing git is not a reason to die
        sha = None
    # Recorded as an explicit unknown rather than omitted: a validator must be
    # able to tell "we could not read the revision" from "nobody thought to".
    report["git_sha"] = sha or "unknown"
    return report


def _write_report(repo_root, run_id, report):
    _stamp(repo_root, report)
    out_dir = os.path.join(repo_root, "procedural", "reports", "scenarios", run_id)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "ue_state_scenario_report.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    unreal.log("[run-state-scenario] report -> {}".format(out_path))


if __name__ == "__main__":
    main()
