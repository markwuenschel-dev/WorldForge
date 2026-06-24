#!/usr/bin/env python3
r"""
trace_industrial_pressure.py (UE5 Python)

Desert Industrialized Slice -- in-engine propagation tracer (PlacementForge D13,
StateForge D9-D11). Proves the existing slice reacts to one driving state key
(industrial_pressure) BEFORE any presets/orchestration are built.

It drives state through the REAL path the contract mandates -- the
`WorldForge.SetState` console command, which calls UWorldStateSubsystem::SetStateValue
-> in-memory store -> curated MPC mirror. It NEVER edits the MPC directly. Then it
reads back the observable side effect (MPC_WorldState.IndustrialPressure) and computes
the placement response from the (regenerated) PlacementRulesDataAsset:

    effective_density = base_density * lerp(density_at_state_zero, density_at_state_one, state)

Outputs (read from WSL afterwards):
    procedural/reports/slices/desert_industrialized/state_0_00.json
    procedural/reports/slices/desert_industrialized/state_0_75.json
    procedural/reports/slices/desert_industrialized/summary.json

NOTE on scope: PushToMpc is global (the MPC is a render-only projection, D10) -- the
material reacts to the LAST industrial_pressure set, regardless of context id. That is
expected for the thin spine. The placement numbers below model the per-region response
the human-owned PCG graph would apply per cell.

Pure stdlib + unreal. Headless-safe: writes a report even on failure; uses unreal.log
(print() is dropped from the captured commandlet log).
"""

import json
import os
import sys
import traceback

import unreal

DRIVING_KEY = "industrial_pressure"
MPC_PARAM = "IndustrialPressure"
MPC_PATH = "/CoreTerrainMaterials/State/MPC_WorldState"
SCOPE = "Region"
CONTEXT_ID = "Desert_Valley_01"
STATES = [0.0, 0.75]
MANIFEST_REL = "procedural/manifests/placement/reclaimed_desert_foliage.json"
REPORT_REL = "procedural/reports/slices/desert_industrialized"


def _log(msg):
    unreal.log("[trace_industrial_pressure] {}".format(msg))


def _project_root():
    # Paths.project_dir() -> the .uproject directory (repo root for this project).
    return os.path.normpath(unreal.Paths.project_dir())


def _get_editor_world():
    try:
        ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        world = ues.get_editor_world()
        if world:
            return world
    except Exception as exc:  # noqa: BLE001
        _log("UnrealEditorSubsystem.get_editor_world failed: {}".format(exc))
    # Fallback for older API surface.
    return unreal.EditorLevelLibrary.get_editor_world()


def _regenerate_data_asset(root, manifest):
    """Best-effort: rebuild the DA from the manifest so foliage numbers aren't stale.
    Reuses create_placement_data_asset.create_or_update if importable."""
    try:
        tools_dir = os.path.dirname(os.path.abspath(__file__))
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import create_placement_data_asset as cpda
        result = cpda.create_or_update(manifest)
        _log("DA regenerated: {}".format(result))
        return result
    except Exception as exc:  # noqa: BLE001
        _log("DA regen skipped/failed ({}); foliage numbers read from existing DA".format(exc))
        return {"status": "skipped", "reason": str(exc)}


def _lerp(a, b, t):
    return a + (b - a) * t


def _species_response(asset, state):
    """Compute the per-species effective density the PCG graph would apply at `state`."""
    out = []
    species = asset.get_editor_property("species") if asset else []
    for rule in species:
        species_id = str(rule.get_editor_property("species_id"))
        base = float(rule.get_editor_property("base_density"))
        d0 = float(rule.get_editor_property("density_at_state_zero"))
        d1 = float(rule.get_editor_property("density_at_state_one"))
        key = str(rule.get_editor_property("state_key"))
        modulated = (key == DRIVING_KEY)
        mult = _lerp(d0, d1, state) if modulated else 1.0
        out.append({
            "species_id": species_id,
            "state_key": key,
            "modulated_by_driving_key": modulated,
            "base_density": base,
            "density_at_state_zero": d0,
            "density_at_state_one": d1,
            "effective_density": round(base * mult, 4),
        })
    return out


def main():
    root = _project_root()
    report_dir = os.path.join(root, REPORT_REL)
    os.makedirs(report_dir, exist_ok=True)

    summary = {
        "slice": "desert_industrialized",
        "driving_key": DRIVING_KEY,
        "scope": SCOPE,
        "context_id": CONTEXT_ID,
        "states": STATES,
        "steps": [],
        "errors": [],
    }

    try:
        world = _get_editor_world()
        summary["editor_world"] = str(world.get_name()) if world else None
        _log("editor world: {}".format(summary["editor_world"]))

        # Load manifest + regenerate DA so the placement response is current.
        with open(os.path.join(root, MANIFEST_REL), "r", encoding="utf-8") as f:
            manifest = json.load(f)
        summary["data_asset_regen"] = _regenerate_data_asset(root, manifest)

        da_path = manifest["ue"]["data_asset_path"]
        da = unreal.EditorAssetLibrary.load_asset(da_path)
        summary["data_asset_path"] = da_path
        summary["data_asset_loaded"] = bool(da)

        mpc = unreal.EditorAssetLibrary.load_asset(MPC_PATH)
        summary["mpc_loaded"] = bool(mpc)
        if not mpc:
            summary["errors"].append("MPC_WorldState not found at {}".format(MPC_PATH))

        for state in STATES:
            cmd = "WorldForge.SetState {} {} {} {}".format(SCOPE, CONTEXT_ID, DRIVING_KEY, state)
            _log("exec: {}".format(cmd))
            unreal.SystemLibrary.execute_console_command(world, cmd)

            # Read back the LIVE per-world MPC instance value (the observable side
            # effect of the subsystem's PushToMpc). UKismetMaterialLibrary is exposed
            # to Python as unreal.MaterialLibrary. This is read-only observation; the
            # WRITE path stays the console command -> subsystem -> MPC (never direct).
            mpc_readback = None
            if mpc:
                mpc_readback = unreal.MaterialLibrary.get_scalar_parameter_value(
                    world, mpc, MPC_PARAM)

            step = {
                "set_value": state,
                "console_command": cmd,
                "mpc_param": MPC_PARAM,
                "mpc_readback": (round(mpc_readback, 4) if mpc_readback is not None else None),
                "mpc_matches_set": (mpc_readback is not None and abs(mpc_readback - state) < 1e-4),
                "species_response": _species_response(da, state),
            }
            summary["steps"].append(step)

            tag = "state_{:.2f}".format(state).replace(".", "_")
            with open(os.path.join(report_dir, "{}.json".format(tag)), "w", encoding="utf-8") as f:
                json.dump(step, f, indent=2)
            _log("{} -> MPC.{} readback={}".format(cmd, MPC_PARAM, step["mpc_readback"]))

        summary["status"] = "ok" if not summary["errors"] else "ok_with_warnings"

    except Exception as exc:  # noqa: BLE001
        summary["status"] = "error"
        summary["errors"].append(str(exc))
        summary["traceback"] = traceback.format_exc()
        _log("ERROR: {}".format(exc))

    with open(os.path.join(report_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    _log("summary written: {}".format(os.path.join(report_dir, "summary.json")))


if __name__ == "__main__":
    main()
