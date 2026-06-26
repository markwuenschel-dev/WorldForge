#!/usr/bin/env python3
r"""
update_slice_placement_tags.py (UE5 Python) -- WorldForge v0.5 placement tag updater.

Reads the staged placement DA JSON from the fixed pointer:
    procedural/reports/slices/_active_placement_da.json

Opens the slice's saved map, finds the PCG actor (tagged wf_pcg), and
adds/updates placement preset tags:
    wf_placement_preset:<placement_preset_id>
    wf_placement_da_id:<da_id>

Saves the map. Writes:
    procedural/reports/slices/<biome>/<slice_id>/update_placement_tags_report.json
"""

import json
import os
import traceback

import unreal

ROOT = os.path.normpath(unreal.Paths.project_dir())
STAGING = os.path.join(ROOT, "procedural", "reports", "slices", "_active_placement_da.json")

TAG_PCG = "wf_pcg"
TAG_PLACEMENT_PRESET = "wf_placement_preset"
TAG_PLACEMENT_DA_ID = "wf_placement_da_id"


def log(m):
    unreal.log("[update-placement-tags] {}".format(m))


def _les():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def _eas():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _tags(actor):
    try:
        return [str(t) for t in actor.tags]
    except Exception:
        return []


def _has_tag(actor, name):
    return name in _tags(actor)


def _set_tags(actor, new_tags):
    actor.tags = new_tags


def _update_tag(tags, prefix, value):
    """Remove existing prefix:<*> tags and add prefix:<value>. Returns updated list."""
    pfx = "{}:".format(prefix)
    cleaned = [t for t in tags if not t.startswith(pfx)]
    cleaned.append("{}:{}".format(prefix, value))
    return cleaned


def main():
    log("reading staged placement DA: {}".format(STAGING))
    if not os.path.isfile(STAGING):
        raise SystemExit("[update-placement-tags] staged DA not found: {}".format(STAGING))

    with open(STAGING, "r", encoding="utf-8") as f:
        da = json.load(f)

    slice_id = da.get("slice_id", "unknown")
    biome = da.get("biome", "unknown")
    placement_preset_id = da.get("placement_preset_id", "")
    da_id = da.get("da_id", "")
    map_path = da.get("map_path", "/Game/WorldForge/Maps/{}".format(slice_id))

    out_dir = os.path.join(ROOT, "procedural", "reports", "slices", biome, slice_id)
    os.makedirs(out_dir, exist_ok=True)

    report = {
        "slice_id": slice_id,
        "map_path": map_path,
        "placement_preset_id": placement_preset_id,
        "da_id": da_id,
        "warnings": [],
        "errors": [],
    }

    try:
        if not unreal.EditorAssetLibrary.does_asset_exist(map_path):
            report["warnings"].append("map not found: {} — tags not updated".format(map_path))
            report["passed"] = False
            report["status"] = "warning"
            log("WARNING: map not found, skipping tag update")
        else:
            loaded = _les().load_level(map_path)
            if not loaded:
                raise RuntimeError("load_level returned False for {}".format(map_path))
            log("loaded map: {}".format(map_path))

            actors = _eas().get_all_level_actors()
            pcg = None
            for a in actors:
                try:
                    if _has_tag(a, TAG_PCG):
                        pcg = a
                        break
                except Exception:
                    pass

            if pcg is None:
                report["warnings"].append("PCG actor (wf_pcg) not found — tags not updated")
                report["passed"] = False
                report["status"] = "warning"
                log("WARNING: PCG actor not found")
            else:
                current_tags = _tags(pcg)
                updated = _update_tag(current_tags, TAG_PLACEMENT_PRESET, placement_preset_id)
                updated = _update_tag(updated, TAG_PLACEMENT_DA_ID, da_id)
                _set_tags(pcg, updated)
                log("updated PCG tags: preset={} da_id={}".format(placement_preset_id, da_id))

                _les().save_current_level()
                report["passed"] = True
                report["status"] = "ok"
                report["tags_set"] = {
                    TAG_PLACEMENT_PRESET: placement_preset_id,
                    TAG_PLACEMENT_DA_ID: da_id,
                }
                log("map saved")

    except Exception as exc:
        report["passed"] = False
        report["status"] = "error"
        report["errors"].append(str(exc))
        report["traceback"] = traceback.format_exc()
        log("ERROR: {}".format(exc))

    report_path = os.path.join(out_dir, "update_placement_tags_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    verdict = "PASS" if report.get("passed") else "FAIL/WARN"
    log("update_slice_placement_tags: {} -- {}".format(verdict, report_path))


if __name__ == "__main__":
    main()
