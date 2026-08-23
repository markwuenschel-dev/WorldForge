#!/usr/bin/env python3
r"""wfcore_environment_far_side.py -- measure the LIVE plugin environment.

Runs INSIDE the editor:

    UnrealEditor-Cmd <uproject> -ExecutePythonScript=<this> \
        -unattended -nopause -nosplash -nullrhi -stdout

Env:
    WF_ENV_OUT   (required) where the JSON evidence document is written

WHY THIS EXISTS
---------------
Two plugin descriptors in this project were renamed to ``.uplugin.disabled`` to
make the 5.8 build succeed. That is an environment change, and an environment
change that is only described in prose is indistinguishable from one nobody made.
This measures the environment instead: which plugins the engine actually mounted,
at which version, and -- the part that matters here -- from WHICH DIRECTORY.

The directory is load-bearing because a plugin name can resolve to more than one
copy on disk. Reporting only "NeoStackAI is enabled" would be true and useless: it
would read identically whether the project-local copy or the engine marketplace
copy answered. ``get_plugin_base_dir`` is what makes the difference observable.

HOUSE PATTERN (scene_survey_far_side.py)
----------------------------------------
Inputs from env vars, parsed defensively. One deterministic JSON file, never
stdout. Every engine call individually guarded, degrading to ``None`` plus a
recorded reason -- ``None`` means NOT OBSERVED and is distinct from a measured
``False``. A top-level catch-all so a crash still writes a document: a far side
that dies silently is indistinguishable from one that never started.
"""

import json
import os
import traceback

try:
    import unreal
except Exception:  # pragma: no cover - only ever true outside the editor
    unreal = None

DOC_SCHEMA = "wf.core.execution_environment_observation.v1"


def _safe(fn, *a, **k):
    """Call an engine API, returning (value, error_reason). Never raises."""
    try:
        return fn(*a, **k), None
    except Exception as exc:  # noqa: BLE001
        return None, "{}: {}".format(type(exc).__name__, exc)


def _norm(path):
    if not isinstance(path, str) or not path:
        return None
    return os.path.normpath(path).replace("\\", "/")


def observe():
    doc = {
        "document_schema": DOC_SCHEMA,
        "observed_engine_version": None,
        "observed_uproject": None,
        "enabled_plugin_names": None,
        "plugins": {},
        "errors": [],
    }
    if unreal is None:
        doc["errors"].append("the unreal module is not importable; nothing was observed")
        return doc

    v, err = _safe(unreal.SystemLibrary.get_engine_version)
    doc["observed_engine_version"] = v
    if err:
        doc["errors"].append("engine_version: " + err)

    v, err = _safe(unreal.Paths.get_project_file_path)
    doc["observed_uproject"] = _norm(v)
    if err:
        doc["errors"].append("uproject: " + err)

    lib = getattr(unreal, "PluginBlueprintLibrary", None)
    if lib is None:
        doc["errors"].append(
            "PluginBlueprintLibrary is not reflected; plugin mounting could not "
            "be observed at all. This is NOT evidence that plugins are absent.")
        return doc

    names, err = _safe(lib.get_enabled_plugin_names)
    if err:
        doc["errors"].append("get_enabled_plugin_names: " + err)
    else:
        doc["enabled_plugin_names"] = sorted(str(n) for n in (names or []))

    # Probe each enabled plugin individually. A per-plugin failure degrades that
    # plugin's record to None rather than losing the whole document.
    for name in (doc["enabled_plugin_names"] or []):
        rec = {"mounted": None, "version_name": None, "base_dir": None,
               "descriptor": None, "errors": []}

        val, e = _safe(lib.is_plugin_mounted, name)
        rec["mounted"] = val if isinstance(val, bool) else None
        if e:
            rec["errors"].append("is_plugin_mounted: " + e)

        val, e = _safe(lib.get_plugin_version_name, name)
        rec["version_name"] = val if isinstance(val, str) and val else None
        if e:
            rec["errors"].append("get_plugin_version_name: " + e)

        val, e = _safe(lib.get_plugin_base_dir, name)
        rec["base_dir"] = _norm(val)
        if e:
            rec["errors"].append("get_plugin_base_dir: " + e)

        val, e = _safe(lib.get_plugin_descriptor_file_path, name)
        rec["descriptor"] = _norm(val)
        if e:
            rec["errors"].append("get_plugin_descriptor_file_path: " + e)

        doc["plugins"][name] = rec

    return doc


def main():
    out = os.environ.get("WF_ENV_OUT") or ""
    doc = {"document_schema": DOC_SCHEMA,
           "errors": ["observation did not run"]}
    try:
        doc = observe()
    except Exception as exc:  # noqa: BLE001
        doc = {"document_schema": DOC_SCHEMA,
               "errors": ["observe() raised: {}: {}".format(
                   type(exc).__name__, exc)],
               "traceback": traceback.format_exc()}

    if out:
        try:
            d = os.path.dirname(os.path.abspath(out))
            if d and not os.path.isdir(d):
                os.makedirs(d)
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2, sort_keys=True, allow_nan=False)
        except Exception as exc:  # noqa: BLE001
            try:
                unreal.log_error("WF_ENV write failed: {}".format(exc))
            except Exception:  # noqa: BLE001
                pass


try:
    main()
finally:
    # A bare -ExecutePythonScript boot otherwise hangs until the timeout.
    try:
        unreal.SystemLibrary.quit_editor()
    except Exception:  # noqa: BLE001
        try:
            unreal.SystemLibrary.execute_console_command(None, "QUIT_EDITOR")
        except Exception:  # noqa: BLE001
            pass
