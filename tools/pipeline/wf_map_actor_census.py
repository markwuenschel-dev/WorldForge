"""wf_map_actor_census.py — in-editor UE map actor census (run via -ExecutePythonScript).

Enumerates every /Game map via the AssetRegistry, loads each level, and records its actor
count + per-class histogram + load status. Emitted as deterministic JSON so the SAME script,
run under UE 5.7 (authoritative before) and UE 5.8 (after-load), yields a diffable census that
proves whether the 5.7 -> 5.8 load drops any actor (WF1014 CONVERSION_ACTOR_LOSS).

Runs headless under `-nullrhi -unattended`. Output path + engine tag come from env:
    WF_CENSUS_OUT   — absolute path to write the census JSON (required)
    WF_CENSUS_TAG   — free label recorded in the census (e.g. "ue58_preresave")

This script READS levels only (loads them into the transient editor world); it does NOT save
or modify any asset — the authoritative resave is a separate commandlet pass.
"""
import json
import os

import unreal  # provided by the UE Python runtime

OUT = os.environ.get("WF_CENSUS_OUT")
TAG = os.environ.get("WF_CENSUS_TAG", "untagged")


def _log(msg):
    unreal.log("[wf-census] " + msg)


def _list_maps():
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    # World assets == maps. ClassPaths API varies across 5.x; try modern then legacy.
    maps = []
    try:
        f = unreal.ARFilter(class_paths=[unreal.TopLevelAssetPath("/Script/Engine", "World")],
                            recursive_classes=True, package_paths=["/Game"], recursive_paths=True)
        maps = [str(a.package_name) for a in ar.get_assets(f)]
    except Exception as e:  # noqa: BLE001
        _log("modern ARFilter failed ({}), falling back to class_names".format(e))
        f = unreal.ARFilter(class_names=["World"], package_paths=["/Game"], recursive_paths=True)
        maps = [str(a.package_name) for a in ar.get_assets(f)]
    return sorted(set(maps))


def _census_one(pkg):
    entry = {"map": pkg, "loaded": False, "actor_count": None, "class_histogram": {},
             "error": None}
    try:
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        ok = les.load_level(pkg)
        entry["loaded"] = bool(ok)
        if ok:
            actors = unreal.EditorActorSubsystem().get_all_level_actors()
            hist = {}
            for a in actors:
                cls = a.get_class().get_name()
                hist[cls] = hist.get(cls, 0) + 1
            entry["actor_count"] = len(actors)
            entry["class_histogram"] = dict(sorted(hist.items()))
    except Exception as e:  # noqa: BLE001
        entry["error"] = str(e)
    return entry


def main():
    if not OUT:
        _log("ERROR: WF_CENSUS_OUT not set")
        return
    maps = _list_maps()
    _log("censusing {} maps (tag={})".format(len(maps), TAG))
    entries = [_census_one(m) for m in maps]
    total_actors = sum(e["actor_count"] or 0 for e in entries)
    loaded = sum(1 for e in entries if e["loaded"])
    doc = {
        "tag": TAG,
        "engine_version": "{}.{}.{}".format(
            unreal.SystemLibrary.get_engine_version().split("-")[0], "", "").split(".")[0]
        if False else unreal.SystemLibrary.get_engine_version(),
        "map_count": len(maps),
        "maps_loaded": loaded,
        "total_actor_count": total_actors,
        "maps": entries,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
    _log("wrote census: {} maps, {} loaded, {} actors -> {}".format(
        len(maps), loaded, total_actors, OUT))


main()
