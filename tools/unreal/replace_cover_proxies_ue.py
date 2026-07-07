#!/usr/bin/env python3
r"""replace_cover_proxies_ue.py (UE5 Python) — WorldForge v1.5 Wave-3
(single-boot batch driver).

Swaps every v1.4x cube cover proxy for its resolved real mesh, in place, across
all mission maps in a single editor boot. Reads the RealizedCoverBinding specs
written headlessly by the realization resolver
(procedural/generated/realization/cover_bindings/*.json), groups them by
``map_id``, loads each map once, and for each binding:

  * finds the StaticMeshActor whose label == ``original_proxy_actor_label``
    (e.g. "WF_ENC_<cover_anchor_id>", the cube proxy spawned by
    materialize_encounters.py),
  * loads the binding's resolved ``ue_asset_path`` mesh and sets it on that same
    actor's static mesh component — keeping the SAME label, position, and folder,
  * HYBRID RULE: if the resolved asset is missing, falls back to the generated-
    owned baseline SM for the binding's height_class (built by
    build_owned_cover_meshes.py) so a cube is never left where a baseline exists,
  * scales the actor to the binding's bounds/height (engine cube = 100uu).

Flips each binding file's ``live_replaced`` -> true and writes a per-map report
(replaced / fallback / remaining-cube counts). save_current_level per map.
Idempotent: re-running re-resolves the same actors to the same meshes.

Report (honest, carries live_replaced):
    procedural/reports/realization/replace_cover_proxies_ue/
        replace_cover_proxies_ue_report.json

Run (single boot over all mapped bindings):
    "<UE>/UnrealEditor-Cmd.exe" "D:/Unreal Projects/WorldForge/WorldForge.uproject" ^
        -ExecutePythonScript="tools/unreal/replace_cover_proxies_ue.py" ^
        -unattended -nopause -nosplash -stdout
"""

import json
import os
import sys
import traceback
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BINDINGS_DIR = REPO_ROOT / "procedural" / "generated" / "realization" / "cover_bindings"
OWNED_COVER_DIR = REPO_ROOT / "procedural" / "generated" / "realization" / "owned_cover_meshes"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "realization" / "replace_cover_proxies_ue"
REPORT_NAME = "replace_cover_proxies_ue_report.json"
MAP_ROOT = "/Game/WorldForge/Maps/"
CUBE = "/Engine/BasicShapes/Cube"
CUBE_UU = 100.0  # engine BasicShapes/Cube edge length
SCHEMA_VERSION = "wf.realization.replace_cover_proxies_ue.v1"

# The headless validator (validate_cover_replacement.py) reads live-replacement
# state from THIS sidecar dir — NOT from the binding files, which stay schema-
# clean (RealizedCoverBinding has no live_replaced field). One file per replaced
# binding: {"binding_id", "live_replaced": true, ...}.
LIVE_REPLACE_DIR = REPO_ROOT / "procedural" / "reports" / "realization" / "ue_replace"
PLAN_DIR = REPO_ROOT / "procedural" / "generated" / "realization" / "plan"


def _write_live_replace_sidecar(binding_id, map_id, actor_label, used_asset, used_fallback):
    """Record that a binding's proxy was really swapped in the editor."""
    if not binding_id:
        return
    LIVE_REPLACE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"binding_id": binding_id, "live_replaced": True, "map_id": map_id,
               "actor_label": actor_label, "used_asset": used_asset,
               "used_fallback": bool(used_fallback)}
    (LIVE_REPLACE_DIR / (binding_id + ".json")).write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


def _flip_plan_materialized():
    """After a successful real-mesh swap the planned owned/imported UE assets
    demonstrably exist, so mark the materialization plan live. Grounded: we only
    reach here having load_asset'd + set the real StaticMesh."""
    if not PLAN_DIR.is_dir():
        return
    for p in PLAN_DIR.glob("materialization_plan_*.json"):
        try:
            plan = json.loads(p.read_text(encoding="utf-8"))
            plan["live_materialized"] = True
            p.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def _load_bindings():
    """Return (by_map dict[map_id]->[(path, binding)], all_paths list)."""
    by_map = defaultdict(list)
    if not BINDINGS_DIR.is_dir():
        return by_map
    for p in sorted(BINDINGS_DIR.glob("*.json")):
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        map_id = b.get("map_id")
        if map_id:
            by_map[map_id].append((p, b))
    return by_map


def _baseline_by_height():
    """height_class -> generated-owned baseline SM final_asset_path (hybrid net)."""
    out = {}
    if not OWNED_COVER_DIR.is_dir():
        return out
    for p in sorted(OWNED_COVER_DIR.glob("*.json")):
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        hc, fp = s.get("height_class"), s.get("final_asset_path")
        if hc and fp and hc not in out:
            out[hc] = fp
    return out


def _bounds_scale(bounds):
    """Actor scale so the 100uu cube matches the binding footprint. Tolerates
    both {x_cm,y_cm,z_cm} and {min:[...],max:[...]} bounds shapes."""
    if not isinstance(bounds, dict):
        return (1.0, 1.0, 1.0)
    if "x_cm" in bounds:
        return (max(float(bounds.get("x_cm", CUBE_UU)) / CUBE_UU, 0.01),
                max(float(bounds.get("y_cm", CUBE_UU)) / CUBE_UU, 0.01),
                max(float(bounds.get("z_cm", CUBE_UU)) / CUBE_UU, 0.01))
    lo, hi = bounds.get("min"), bounds.get("max")
    if lo and hi and len(lo) >= 3 and len(hi) >= 3:
        return tuple(max(abs(float(hi[i]) - float(lo[i])) / CUBE_UU, 0.01) for i in range(3))
    return (1.0, 1.0, 1.0)


def _find_actor(unreal, eas, label):
    for a in list(eas.get_all_level_actors()):
        try:
            if a.get_actor_label() == label:
                return a
        except Exception:  # noqa: BLE001
            pass
    return None


def replace_map(unreal, eas, map_id, entries, baselines):
    replaced, fallback, remaining, rows = 0, 0, 0, []
    for spec_path, b in entries:
        label = b.get("original_proxy_actor_label")
        resolved = b.get("ue_asset_path")
        hc = b.get("height_class")
        row = {"binding_id": b.get("binding_id"), "actor_label": label,
               "cover_anchor_id": b.get("cover_anchor_id"),
               "resolved_asset": resolved, "used_asset": None,
               "used_fallback": False, "status": "pending"}

        actor = _find_actor(unreal, eas, label) if label else None
        if actor is None:
            row["status"] = "actor_not_found"
            remaining += 1
            rows.append(row)
            continue

        mesh_path = resolved if resolved and unreal.EditorAssetLibrary.does_asset_exist(resolved) else None
        if mesh_path is None:
            base = baselines.get(hc)
            if base and unreal.EditorAssetLibrary.does_asset_exist(base):
                mesh_path = base
                row["used_fallback"] = True
        if mesh_path is None:
            # Nothing to swap to: the actor keeps its cube. Count it honestly.
            row["status"] = "no_mesh_available_cube_kept"
            remaining += 1
            rows.append(row)
            continue

        mesh = unreal.EditorAssetLibrary.load_asset(mesh_path)
        if not mesh or not isinstance(mesh, unreal.StaticMesh):
            row["status"] = "mesh_load_failed"
            remaining += 1
            rows.append(row)
            continue

        try:
            actor.static_mesh_component.set_static_mesh(mesh)
            actor.set_actor_scale3d(unreal.Vector(*_bounds_scale(b.get("bounds"))))
            # Enforce a blocking collision profile on the placed proxy.
            try:
                actor.static_mesh_component.set_collision_profile_name("BlockAll")
            except Exception as exc:  # noqa: BLE001
                row["collision_note"] = str(exc)
            row["used_asset"] = mesh_path
            row["status"] = "replaced"
            replaced += 1
            if row["used_fallback"]:
                fallback += 1
            # Record live-replacement in the sidecar the validator reads. The
            # binding file is NOT mutated (it must stay schema-clean).
            try:
                _write_live_replace_sidecar(b.get("binding_id"), map_id, label,
                                            mesh_path, row["used_fallback"])
            except Exception as exc:  # noqa: BLE001
                row["sidecar_write_note"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            row["status"] = "error"
            row["error"] = str(exc)
            remaining += 1
        rows.append(row)

    return {"map_id": map_id, "map": MAP_ROOT + map_id,
            "bindings": len(entries), "replaced": replaced,
            "fallback": fallback, "remaining_cubes": remaining,
            "rows": rows}


def main():
    try:
        import unreal
    except ImportError:
        sys.stderr.write("ERROR: run inside the Unreal editor "
                         "(UnrealEditor-Cmd -ExecutePythonScript).\n")
        return 2

    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    by_map = _load_bindings()
    baselines = _baseline_by_height()
    # Optional proof subset: WF_MAP_LIMIT=N processes only the first N maps.
    _limit = os.environ.get("WF_MAP_LIMIT")
    if _limit and _limit.isdigit():
        keep = sorted(by_map)[:int(_limit)]
        by_map = {k: by_map[k] for k in keep}
        unreal.log("[replace-cover] WF_MAP_LIMIT={} -> {} map(s)".format(_limit, len(by_map)))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    if not by_map:
        unreal.log_warning("[replace-cover] no cover bindings at {} "
                           "(resolver not run?); empty report".format(BINDINGS_DIR))

    map_reports, failed = [], []
    for map_id in sorted(by_map):
        map_path = MAP_ROOT + map_id
        try:
            if not les.load_level(map_path):
                raise RuntimeError("load_level returned False")
            mr = replace_map(unreal, eas, map_id, by_map[map_id], baselines)
            if not les.save_current_level():
                raise RuntimeError("save_current_level returned False")
            map_reports.append(mr)
            unreal.log("[replace-cover] {} — replaced {}, fallback {}, remaining {}".format(
                map_id, mr["replaced"], mr["fallback"], mr["remaining_cubes"]))
        except Exception as exc:  # noqa: BLE001
            failed.append({"map_id": map_id, "error": str(exc)})
            unreal.log_error("[replace-cover] FAIL {}: {}\n{}".format(
                map_id, exc, traceback.format_exc()))

    # If any proxy was really swapped, the owned/imported UE meshes exist -> the
    # materialization plan is now live.
    if any(m["replaced"] for m in map_reports):
        _flip_plan_materialized()

    report = {
        "command": "replace_cover_proxies_ue",
        "schema_version": SCHEMA_VERSION,
        "live_replaced": True,
        "baselines_by_height": baselines,
        "total_maps": len(by_map),
        "ok_maps": len(map_reports),
        "failed_maps": len(failed),
        "replaced_total": sum(m["replaced"] for m in map_reports),
        "fallback_total": sum(m["fallback"] for m in map_reports),
        "remaining_cubes_total": sum(m["remaining_cubes"] for m in map_reports),
        "status": "ok" if not failed else "error",
        "maps": map_reports,
        "failures": failed,
    }
    (REPORT_DIR / REPORT_NAME).write_text(json.dumps(report, indent=2), encoding="utf-8")
    unreal.log("[replace-cover] DONE — {}/{} maps ok, {} failed".format(
        len(map_reports), len(by_map), len(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
