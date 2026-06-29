#!/usr/bin/env python3
r"""
validate_slice.py (UE5 Python) -- WorldForge slice factory, validator.

Opens the saved map a slice spec points at and asserts the slice is real and wired:

    map asset exists + loads, world name matches
    terrain actor present, terrain MI matches the spec
    PCG actor present, references the spec's PCG graph + placement DataAsset
    region marker present, region_id + state key/before/after match the spec
    placement DataAsset resolves
    MPC bridge works (SetState(after) -> MPC readback == after)

Writes <output_dir>/validate_slice_report.json and logs PASS/FAIL. JSON only.
Spec resolution mirrors create_slice_map.py (--spec / $WF_SLICE_SPEC / fixed pointer).
"""

import argparse
import json
import os
import traceback

import unreal

TAG_REGION = "wf_region"
TAG_STATE_KEY = "wf_state_key"
TAG_STATE_BEFORE = "wf_state_before"
TAG_STATE_AFTER = "wf_state_after"
TAG_SLICE = "wf_slice"
TAG_PCG = "wf_pcg"
TAG_PCG_GRAPH = "wf_pcg_graph"
TAG_PLACEMENT_DA = "wf_placement_da"
TAG_TERRAIN = "wf_terrain"

MPC_PATH = "/CoreTerrainMaterials/State/MPC_WorldState"
MPC_PRESSURE_PARAM = "IndustrialPressure"


def log(m):
    unreal.log("[validate-slice] {}".format(m))


def _les():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def _eas():
    return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)


def _world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def _tags(actor):
    out = []
    try:
        for t in actor.tags:
            out.append(str(t))
    except Exception:
        pass
    return out


def _has_tag(actor, name):
    return name in _tags(actor)


def _tag_value(actor, prefix):
    """Return the value of a 'prefix:value' tag, or None."""
    pfx = prefix + ":"
    for t in _tags(actor):
        if t.startswith(pfx):
            return t[len(pfx):]
    return None


def _find(actors, predicate):
    for a in actors:
        try:
            if predicate(a):
                return a
        except Exception:
            pass
    return None


def main():
    ap = argparse.ArgumentParser(description="Validate a generated WorldForge slice map.")
    ap.add_argument("--spec", default=None)
    ap.add_argument("--project-root", default=".")
    args = ap.parse_args()

    root = os.path.normpath(unreal.Paths.project_dir())
    DEFAULT_SPEC_REL = "procedural/reports/slices/_active_slice_spec.json"
    chosen = args.spec or os.environ.get("WF_SLICE_SPEC") or os.path.join(root, DEFAULT_SPEC_REL)
    spec_path = chosen if os.path.isabs(chosen) else os.path.join(root, chosen)
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)

    # Read deep-validation config written by run_slice_ue.py --deep.
    config_path = os.path.join(root, "procedural", "reports", "slices", "_validate_config.json")
    deep = False
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                deep = json.load(f).get("deep", False)
        except Exception:
            deep = False

    map_path = spec["map"]
    region_id = spec["region_id"]
    state = spec["state"]
    mi_path = spec["terrain"]["material_mi"]
    placement = spec.get("placement", {})
    da_path = placement.get("data_asset")
    pcg_path = placement.get("pcg_graph")
    out_dir = os.path.join(root, spec.get("output_dir", "procedural/reports/slices/_unsorted/" + spec["slice_id"]))
    os.makedirs(out_dir, exist_ok=True)
    expected_world = map_path.rstrip("/").rsplit("/", 1)[-1]

    result = {"slice_id": spec["slice_id"], "map": map_path, "checks": {}, "failures": []}
    fail = result["failures"].append

    def check(name, ok, detail="", warn_only=False):
        result["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok and not warn_only:
            fail("{}: {}".format(name, detail or "failed"))
        return ok

    try:
        if not check("map_exists", unreal.EditorAssetLibrary.does_asset_exist(map_path), map_path):
            raise SystemExit("map missing -- cannot continue")
        loaded = _les().load_level(map_path)
        check("map_loads", bool(loaded), map_path)
        world = _world()
        wname = world.get_name() if world else None
        check("world_matches", wname == expected_world, "world={} expected={}".format(wname, expected_world))

        actors = _eas().get_all_level_actors()

        ground = _find(actors, lambda a: _has_tag(a, TAG_TERRAIN))
        if check("terrain_actor", ground is not None, "tag {}".format(TAG_TERRAIN)):
            assigned = None
            try:
                m = ground.static_mesh_component.get_material(0)
                assigned = m.get_path_name().split(".")[0] if m else None
            except Exception as e:  # noqa: BLE001
                assigned = "error: {}".format(e)
            check("terrain_material_matches", assigned == mi_path,
                  "assigned={} expected={}".format(assigned, mi_path))

        pcg = _find(actors, lambda a: _has_tag(a, TAG_PCG))
        if check("pcg_actor", pcg is not None, "tag {}".format(TAG_PCG)):
            check("pcg_graph_linked", _tag_value(pcg, TAG_PCG_GRAPH) == pcg_path,
                  "graph={} expected={}".format(_tag_value(pcg, TAG_PCG_GRAPH), pcg_path))
            check("placement_da_linked", _tag_value(pcg, TAG_PLACEMENT_DA) == da_path,
                  "da={} expected={}".format(_tag_value(pcg, TAG_PLACEMENT_DA), da_path))

        marker = _find(actors, lambda a: _tag_value(a, TAG_REGION) == region_id)
        if check("region_marker", marker is not None, "wf_region:{}".format(region_id)):
            check("state_key_matches", _tag_value(marker, TAG_STATE_KEY) == state.get("key"),
                  "key={} expected={}".format(_tag_value(marker, TAG_STATE_KEY), state.get("key")))
            check("state_before_matches",
                  _tag_value(marker, TAG_STATE_BEFORE) == str(state.get("before")),
                  "before={}".format(_tag_value(marker, TAG_STATE_BEFORE)))
            check("state_after_matches",
                  _tag_value(marker, TAG_STATE_AFTER) == str(state.get("after")),
                  "after={}".format(_tag_value(marker, TAG_STATE_AFTER)))

        check("placement_da_resolves",
              da_path is not None and unreal.EditorAssetLibrary.load_asset(da_path) is not None, da_path)

        # MPC bridge: drive to the slice's `after` state and confirm the MPC mirror.
        after = state.get("after", 0.75)
        try:
            unreal.SystemLibrary.execute_console_command(
                world, "WorldForge.SetState {} {} {} {}".format(
                    state.get("scope", "Region"), state.get("context_id"), state.get("key"), after))
            mpc = unreal.EditorAssetLibrary.load_asset(MPC_PATH)
            val = float(unreal.MaterialLibrary.get_scalar_parameter_value(world, mpc, MPC_PRESSURE_PARAM))
            result["mpc_readback"] = round(val, 4)
            check("mpc_bridge", abs(val - float(after)) < 1e-4,
                  "readback={} expected={}".format(round(val, 4), after))
        except Exception as e:  # noqa: BLE001
            check("mpc_bridge", False, "exception: {}".format(e))

        # player_start and nav_bounds are warn_only for backwards compat with pre-v0.4 maps
        ps = _find(actors, lambda a: isinstance(a, unreal.PlayerStart))
        check("player_start", ps is not None, "PlayerStart actor", warn_only=True)

        nav = _find(actors, lambda a: isinstance(a, unreal.NavMeshBoundsVolume))
        check("nav_bounds", nav is not None, "NavMeshBoundsVolume actor", warn_only=True)

        # terrain_forge checks — run when spec contains a terrain_forge block
        terrain_forge = spec.get("terrain_forge")
        poi_forge = spec.get("poi_forge")
        if terrain_forge:
            tf_desc_rel = terrain_forge.get("descriptor_path", "")
            tf_desc_full = os.path.join(root, tf_desc_rel.replace("/", os.sep))
            check("terrain_forge_descriptor_exists",
                  bool(tf_desc_rel) and os.path.isfile(tf_desc_full),
                  "descriptor_path={}".format(tf_desc_rel))
            for artifact_key in ("heightmap", "slope_mask", "placement_mask", "nav_safe_mask"):
                rel = terrain_forge.get(artifact_key, "")
                full = os.path.join(root, rel.replace("/", os.sep)) if rel else ""
                check("terrain_forge_{}_exists".format(artifact_key),
                      bool(rel) and os.path.isfile(full),
                      "path={}".format(rel))
            # Verify the terrain actor carries the wf_terrain_forge tag.
            terrain_forge_actor = _find(actors, lambda a: "wf_terrain_forge" in _tags(a))
            check("terrain_forge_actor_tagged", terrain_forge_actor is not None,
                  "no actor with wf_terrain_forge tag found in map")
            if terrain_forge_actor is not None:
                expected_tf_name = terrain_forge.get("terrain_name", "")
                actual_tf_name = _tag_value(terrain_forge_actor, "wf_terrain_name")
                check("terrain_forge_name_matches",
                      actual_tf_name == expected_tf_name,
                      "actor tag wf_terrain_name={} expected={}".format(actual_tf_name, expected_tf_name))
                expected_pm = terrain_forge.get("placement_mask", "")
                actual_pm = _tag_value(terrain_forge_actor, "wf_terrain_placement_mask")
                check("terrain_forge_placement_mask_tagged",
                      actual_pm == expected_pm,
                      "tag wf_terrain_placement_mask={} expected={}".format(actual_pm, expected_pm))

        # poi_forge checks — run when spec contains a poi_forge block
        if poi_forge:
            poi_actor = _find(actors, lambda a: _has_tag(a, "wf_poi_forge"))
            if check("poi_forge_actor", poi_actor is not None, "no actor with wf_poi_forge tag"):
                expected_poi_type = poi_forge.get("poi_type", "")
                actual_poi_type = _tag_value(poi_actor, "wf_poi_type")
                check("poi_forge_type_matches",
                      actual_poi_type == expected_poi_type,
                      "actor tag wf_poi_type={} expected={}".format(actual_poi_type, expected_poi_type))
                expected_poi_name = poi_forge.get("poi_name", "")
                actual_poi_name = _tag_value(poi_actor, "wf_poi_name")
                check("poi_forge_name_matches",
                      actual_poi_name == expected_poi_name,
                      "actor tag wf_poi_name={} expected={}".format(actual_poi_name, expected_poi_name))
                expected_bounds_id = poi_forge.get("bounds_id", "primary_bounds")
                actual_bounds_id = _tag_value(poi_actor, "wf_poi_bounds")
                check("poi_forge_bounds_tagged",
                      actual_bounds_id == expected_bounds_id,
                      "tag wf_poi_bounds={} expected={}".format(actual_bounds_id, expected_bounds_id))

        # DEEP checks — only run when _validate_config.json has {"deep": true}
        if deep:
            log("deep validation enabled")

            # placement preset file must exist on disk
            placement_preset_id = spec.get("placement_preset_id")
            if placement_preset_id:
                preset_biome = spec.get("biome", "desert")
                preset_path = os.path.join(root, "procedural", "definitions", "placement",
                                           preset_biome, placement_preset_id + ".yaml")
                check("placement_preset_exists",
                      os.path.isfile(preset_path),
                      "preset={} path={}".format(placement_preset_id, preset_path))
            else:
                check("placement_preset_exists", False, "no placement_preset_id in spec", warn_only=True)

            # state preset file must exist on disk (warn_only if omitted — v0.4 slices lack it)
            state_preset_id = spec.get("state_preset_id")
            if state_preset_id:
                state_biome = spec.get("biome", "desert")
                state_path = os.path.join(root, "procedural", "definitions", "state",
                                          state_biome, state_preset_id + ".yaml")
                check("state_preset_exists",
                      os.path.isfile(state_path),
                      "preset={} path={}".format(state_preset_id, state_path))
            else:
                check("state_preset_exists", False,
                      "no state_preset_id in spec", warn_only=True)

            # per-slice placement DA JSON descriptor
            da_desc_path = os.path.join(root, "procedural", "generated", "placement",
                                        spec["slice_id"] + "_da.json")
            check("placement_da_exists",
                  os.path.isfile(da_desc_path),
                  "path={}".format(da_desc_path))

            # budget config present (content validated by validate_budget.py on pipeline side)
            budget_path = os.path.join(root, "procedural", "definitions", "budgets", "desert_default.yaml")
            check("budget_config_loaded", os.path.isfile(budget_path),
                  "budget file missing: {}".format(budget_path))

            # poi_forge descriptor file must exist when poi_forge is in spec
            if poi_forge:
                poi_desc_rel = poi_forge.get("descriptor_path", "")
                poi_desc_full = os.path.join(root, poi_desc_rel.replace("/", os.sep)) if poi_desc_rel else ""
                check("poi_forge_descriptor_exists",
                      bool(poi_desc_rel) and os.path.isfile(poi_desc_full),
                      "descriptor_path={}".format(poi_desc_rel))
                expected_anchor_count = len(poi_forge.get("anchors", []))
                poi_anchors = [a for a in actors if _has_tag(a, "wf_poi_anchor") and
                               _tag_value(a, "wf_poi_name") == poi_forge.get("poi_name", "")]
                check("poi_forge_anchors_spawned",
                      len(poi_anchors) == expected_anchor_count,
                      "found {} anchor actors expected {}".format(len(poi_anchors), expected_anchor_count))

        result["passed"] = not result["failures"]
        result["status"] = "ok"
    except SystemExit as se:
        result["passed"] = False
        result["status"] = "error"
        result["errors"] = [str(se)]
    except Exception as exc:  # noqa: BLE001
        result["passed"] = False
        result["status"] = "error"
        result["errors"] = [str(exc)]
        result["traceback"] = traceback.format_exc()
        log("ERROR: {}".format(exc))

    with open(os.path.join(out_dir, "validate_slice_report.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    verdict = "PASS" if result.get("passed") else "FAIL"
    log("validate_slice: {} ({} failure(s))".format(verdict, len(result["failures"])))
    for r in result["failures"]:
        log("  - {}".format(r))


if __name__ == "__main__":
    main()
