#!/usr/bin/env python3
"""tools/bridge/far_side.py — the FAR SIDE of the live bridge; runs INSIDE UE 5.8.

This file never runs in the WorldForge python. It is handed to a *separate* UE 5.8
project's editor via ``-ExecutePythonScript=`` and executes inside that process, on
the other side of the repository boundary. It answers one bridge request and writes
a single evidence JSON back into the target project.

Everything it reports is OBSERVED from the running process:

  * ``observed_engine``  — ``unreal.SystemLibrary.get_engine_version()``, i.e. the
    engine that is actually executing this code. NOT read from a .uproject or an
    ini, because a config file states intent and can lie about what booted.
  * ``resolved_uproject`` — ``unreal.Paths.get_project_file_path()``, the project the
    editor actually opened.
  * ``resolved_target_repository`` / ``resolved_target_commit`` — resolved by asking
    git *in the target project's own working tree*, so the far side reports its own
    repo identity rather than inheriting the caller's.
  * ``plugin_loaded`` — proven by the plugin's C++ UCLASSes being present in the
    reflection registry. A UCLASS only registers when its module DLL is loaded, so
    this cannot be true for a plugin that is merely on disk.

The real operation (``materialize_recipe_asset``) constructs a plugin-owned UCLASS
(``UMaterialRecipeDataAsset`` from WorldForgeCore), stamps the bridge operation_id
into its provenance, serialises it through UE's package system to a real .uasset on
disk inside the target project, then reloads it from disk and verifies the round
trip. It is deliberately an operation that CANNOT succeed unless the plugin's code
is genuinely loaded and running in this editor.

Configuration is entirely by environment (no baked machine paths):
    WF_BRIDGE_OPERATION_ID       the id to echo end-to-end
    WF_BRIDGE_EVIDENCE_OUT       absolute Windows path for the evidence JSON
    WF_BRIDGE_REQUIRED_PLUGIN    plugin the operation depends on
    WF_BRIDGE_REQUESTED_OPERATION  the bounded operation to perform
    WF_BRIDGE_ASSET_DIR          /Game path the operation authors into

On any failure it still writes evidence, with operation_completed=False and the
exception recorded. It never invents a success.
"""

import json
import os
import subprocess
import sys
import traceback

import unreal  # noqa: F401  (only importable inside a UE process)

MARKER = "WF_BRIDGE_FAR_SIDE"

# The capabilities the handshake probes. Each is a plugin-owned reflection symbol:
# present in `unreal` only when the WorldForge module DLL actually loaded.
_EXPECTED_CAPABILITIES = (
    ("WorldForgeCore.MaterialRecipeDataAsset", "MaterialRecipeDataAsset"),
    ("WorldForgeCore.PlacementRulesDataAsset", "PlacementRulesDataAsset"),
    ("WorldForgeCore.WorldStateSubsystem", "WorldStateSubsystem"),
)


def _git(args, cwd):
    """Run git in the TARGET project's tree; return stripped stdout or None."""
    try:
        out = subprocess.check_output(
            ["git"] + args, cwd=cwd, stderr=subprocess.DEVNULL)
        return out.decode("utf-8", "replace").strip()
    except Exception:
        return None


def _project_dir():
    """Absolute, normalised path to the target project directory."""
    return os.path.abspath(unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.project_dir())).replace("\\", "/")


def _rel_to_project(abs_path, project_dir):
    """Project-relative posix path, or None when the path is outside the project.

    Returning None for an outside path is deliberate: evidence that does not live
    inside the target project is not this project's evidence.
    """
    a = os.path.abspath(abs_path).replace("\\", "/")
    p = project_dir.rstrip("/") + "/"
    return a[len(p):] if a.lower().startswith(p.lower()) else None


def capability_handshake():
    """Probe the plugin's reflected surface. available=True only if truly present."""
    caps = []
    for cap_id, symbol in _EXPECTED_CAPABILITIES:
        present = hasattr(unreal, symbol)
        caps.append({
            "capability_id": cap_id,
            "available": bool(present),
            "evidence": "unreal.{} {} in reflection registry".format(
                symbol, "present" if present else "ABSENT"),
        })
    return caps


def plugin_on_disk(project_dir, plugin_name):
    """True iff the plugin's .uplugin really exists inside the target project."""
    return os.path.isfile(os.path.join(
        project_dir, "Plugins", plugin_name, "{}.uplugin".format(plugin_name)))


def materialize_recipe_asset(operation_id, asset_dir):
    """The REAL operation: author, save, and reload a plugin-owned .uasset.

    Returns (ok, detail, absolute_uasset_path_or_None). Succeeds only if the plugin
    class instantiates, serialises to disk, and survives a reload with the bridge
    operation_id intact.
    """
    asset_name = "WFBridgeRecipe_{}".format(operation_id)
    package_path = "{}/{}".format(asset_dir.rstrip("/"), asset_name)
    detail = {}

    # Start from a clean slate. Without this a re-run would find the previous run's
    # asset, create_asset would return None, and the operation would fail. More
    # importantly: the artifact this run reports MUST be the one this run authored,
    # never a leftover that happens to sit at the same path.
    if unreal.EditorAssetLibrary.does_asset_exist(package_path):
        unreal.EditorAssetLibrary.delete_asset(package_path)

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    asset = tools.create_asset(asset_name, asset_dir,
                               unreal.MaterialRecipeDataAsset, None)
    if asset is None:
        return False, {"error": "create_asset returned None"}, None

    # Stamp the bridge operation into the asset's provenance so the artifact itself
    # is bound to this operation and cannot be reused by another.
    asset.set_editor_property("recipe_id", "wf_bridge_live")
    asset.set_editor_property("source_commit", operation_id)
    asset.set_editor_property("generator_name", "worldforge-gloam-bridge-live")
    asset.set_editor_property("schema_version", "wf.transition.gloam_bridge_live.v1")

    if not unreal.EditorAssetLibrary.save_asset(package_path, only_if_is_dirty=False):
        return False, {"error": "save_asset failed", "package": package_path}, None

    # Reload from disk: proves the bytes really landed and deserialise through the
    # plugin's UCLASS, not just that an in-memory object existed.
    unreal.EditorAssetLibrary.load_asset(package_path)
    reloaded = unreal.EditorAssetLibrary.load_asset(package_path)
    if reloaded is None:
        return False, {"error": "reload returned None", "package": package_path}, None

    got_commit = str(reloaded.get_editor_property("source_commit"))
    got_recipe = str(reloaded.get_editor_property("recipe_id"))
    detail = {
        "package_path": package_path,
        "class": reloaded.get_class().get_name(),
        "roundtrip_source_commit": got_commit,
        "roundtrip_recipe_id": got_recipe,
    }
    if got_commit != operation_id:
        detail["error"] = "operation_id did not survive the asset round trip"
        return False, detail, None

    uasset = os.path.join(
        unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_content_dir()),
        package_path[len("/Game/"):] + ".uasset")
    if not os.path.isfile(uasset):
        detail["error"] = "no .uasset on disk at {}".format(uasset)
        return False, detail, None
    return True, detail, uasset


def main():
    operation_id = os.environ.get("WF_BRIDGE_OPERATION_ID", "")
    evidence_out = os.environ.get("WF_BRIDGE_EVIDENCE_OUT", "")
    plugin_name = os.environ.get("WF_BRIDGE_REQUIRED_PLUGIN", "WorldForge")
    requested = os.environ.get("WF_BRIDGE_REQUESTED_OPERATION", "materialize_recipe_asset")
    asset_dir = os.environ.get("WF_BRIDGE_ASSET_DIR", "/Game/WFBridge")

    project_dir = _project_dir()
    uproject_abs = unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.get_project_file_path()).replace("\\", "/")

    ev = {
        "marker": MARKER,
        # Echoed straight back so the near side can prove end-to-end continuity.
        "operation_id": operation_id,
        "requested_operation": requested,
        # OBSERVED from the running editor — not from any config file.
        "observed_engine": unreal.SystemLibrary.get_engine_version(),
        "observed_project": unreal.Paths.get_project_file_path().rsplit("/", 1)[-1]
                            .rsplit(".", 1)[0],
        "resolved_uproject": _rel_to_project(uproject_abs, project_dir),
        # Resolved by the FAR SIDE, in its own working tree.
        "resolved_target_repository": None,
        "resolved_target_commit": None,
        "plugin_present": plugin_on_disk(project_dir, plugin_name),
        "plugin_loaded": False,
        "plugin_capability_manifest": [],
        "capability_handshake_ok": False,
        "operation_completed": False,
        "operation_detail": {},
        "artifacts": [],
        "error": None,
    }

    top = _git(["rev-parse", "--show-toplevel"], project_dir)
    if top:
        ev["resolved_target_repository"] = os.path.basename(top.rstrip("/"))
        ev["resolved_target_commit"] = _git(["rev-parse", "HEAD"], project_dir)

    try:
        caps = capability_handshake()
        ev["plugin_capability_manifest"] = caps
        ev["capability_handshake_ok"] = bool(caps) and all(c["available"] for c in caps)
        # A plugin UCLASS in the reflection registry IS the load proof.
        ev["plugin_loaded"] = ev["capability_handshake_ok"]

        if not ev["plugin_loaded"]:
            ev["error"] = "plugin not loaded; refusing to run the operation"
        else:
            ok, detail, uasset = materialize_recipe_asset(operation_id, asset_dir)
            ev["operation_completed"] = bool(ok)
            ev["operation_detail"] = detail
            if ok and uasset:
                rel = _rel_to_project(uasset, project_dir)
                if rel:
                    ev["artifacts"].append(rel)
    except Exception as exc:  # never fabricate a success
        ev["error"] = "{}: {}".format(type(exc).__name__, exc)
        ev["traceback"] = traceback.format_exc()

    # The evidence file is itself an artifact, recorded project-relative.
    if evidence_out:
        rel_ev = _rel_to_project(evidence_out, project_dir)
        if rel_ev:
            ev["artifacts"].append(rel_ev)
        os.makedirs(os.path.dirname(evidence_out), exist_ok=True)
        with open(evidence_out, "w", encoding="utf-8") as fh:
            json.dump(ev, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    unreal.log("{} {}".format(MARKER, json.dumps(
        {k: ev[k] for k in ("operation_id", "observed_engine", "plugin_loaded",
                            "operation_completed", "resolved_target_commit")})))
    sys.stdout.flush()


main()
