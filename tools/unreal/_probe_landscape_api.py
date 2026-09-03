#!/usr/bin/env python3
"""_probe_landscape_api.py -- ASK the engine what landscape API it has.

WHY A PROBE AND NOT AN IMPLEMENTATION
-------------------------------------
This repository has already paid for guessing an engine convention. The sink
applied the wrong rotation to every actor for weeks because ``unreal.Rotator``'s
positional order is (roll, pitch, yaw) and the payload was ordered
(pitch, yaw, roll); the fix was to PROBE the live engine rather than derive it.
The mesh-synthesis notes say the same thing in the same words: "UE 5.8
mesh-synthesis API, learned by probing (do not guess these)".

A landscape is the harder case. ``op_landscape_live_0001`` proved that spawning
``unreal.Landscape`` as an actor yields a ``LandscapePlaceholder``, so whatever
builds a real ``ALandscape`` is not the actor-spawn path. Rather than guess
which of several plausible APIs is the real one, this script reports what
actually exists in THIS engine build and writes it down.

It mutates nothing. It creates no asset, spawns no actor, opens no map.

ENVIRONMENT CONTRACT
--------------------
    WF_LP_OUT   absolute path for the probe report JSON (REQUIRED)
"""

import json
import os
import traceback

REPORT_SCHEMA = "wf.core.landscape_api_probe.v1"

# Candidate entry points, each a plausible way to create a landscape. The probe
# reports which exist; it does not assume any of them is the answer.
CANDIDATE_TYPES = (
    "Landscape", "LandscapeProxy", "LandscapeStreamingProxy",
    "LandscapeSubsystem", "LandscapeEditorSubsystem", "LandscapeInfo",
    "LandscapeComponent", "LandscapeLayerInfoObject",
    "LandscapeEditorObject", "LandscapePlaceholder",
    "NewLandscapeParameters", "LandscapeImportLayerInfo",
    "EditorActorSubsystem", "LevelEditorSubsystem",
)

# Function-shaped names worth asking about on whatever we find.
CANDIDATE_METHODS = (
    "create_landscape", "new_landscape", "import_landscape",
    "create_landscape_from_heightmap", "set_heightmap_data",
    "set_heightmap", "import_heightmap", "get_heightmap_data",
    "landscape_import_heightmap", "create", "import_from_heightmap",
    "change_component_setting", "resize_landscape",
)


def _members(obj, wanted):
    """Names on obj that look like our candidates, plus a full callable list."""
    have, allnames = [], []
    for name in dir(obj):
        if name.startswith("_"):
            continue
        allnames.append(name)
        if name in wanted:
            have.append(name)
    return have, allnames


def main():
    doc = {"report_schema": REPORT_SCHEMA, "engine_version": None,
           "types": {}, "subsystems": {}, "editor_util": {},
           "error": None, "traceback": None, "notes": []}
    out = os.environ.get("WF_LP_OUT")
    try:
        import unreal
        try:
            doc["engine_version"] = str(unreal.SystemLibrary.get_engine_version())
        except Exception:  # noqa: BLE001
            pass

        for tname in CANDIDATE_TYPES:
            t = getattr(unreal, tname, None)
            if t is None:
                doc["types"][tname] = {"exists": False}
                continue
            entry = {"exists": True, "repr": str(t)}
            try:
                hits, allnames = _members(t, CANDIDATE_METHODS)
                entry["candidate_methods"] = hits
                entry["member_count"] = len(allnames)
                # Only keep names that plausibly relate, to keep the report readable.
                entry["landscape_ish_members"] = sorted(
                    n for n in allnames
                    if any(k in n.lower() for k in
                           ("landscape", "height", "import", "create", "layer")))
            except Exception as exc:  # noqa: BLE001
                entry["introspection_error"] = "{}: {}".format(
                    type(exc).__name__, exc)
            doc["types"][tname] = entry

        # Subsystems have to be fetched, not just referenced.
        for sname in ("LandscapeSubsystem", "LandscapeEditorSubsystem",
                      "EditorActorSubsystem", "LevelEditorSubsystem"):
            cls = getattr(unreal, sname, None)
            if cls is None:
                doc["subsystems"][sname] = {"exists": False}
                continue
            got = None
            how = None
            for getter in ("get_editor_subsystem", "get_engine_subsystem"):
                fn = getattr(unreal, getter, None)
                if fn is None:
                    continue
                try:
                    got = fn(cls)
                    how = getter
                    if got is not None:
                        break
                except Exception as exc:  # noqa: BLE001
                    doc["subsystems"].setdefault(sname, {})[getter + "_error"] = \
                        "{}: {}".format(type(exc).__name__, exc)
            entry = {"exists": True, "resolved": got is not None, "via": how}
            if got is not None:
                hits, allnames = _members(got, CANDIDATE_METHODS)
                entry["candidate_methods"] = hits
                entry["landscape_ish_members"] = sorted(
                    n for n in allnames
                    if any(k in n.lower() for k in
                           ("landscape", "height", "import", "create", "layer")))
            doc["subsystems"][sname] = entry

        # Free functions and library statics that mention landscape/heightmap.
        try:
            doc["editor_util"]["unreal_module_landscape_names"] = sorted(
                n for n in dir(unreal)
                if "landscape" in n.lower() and not n.startswith("_"))
        except Exception:  # noqa: BLE001
            pass

    except Exception as exc:  # noqa: BLE001
        doc["error"] = "{}: {}".format(type(exc).__name__, exc)
        doc["traceback"] = traceback.format_exc()
    finally:
        if out:
            try:
                with open(out, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh, indent=2, sort_keys=True)
            except Exception:  # noqa: BLE001
                pass
        try:
            import unreal
            unreal.SystemLibrary.quit_editor()
        except Exception:  # noqa: BLE001
            pass


main()
