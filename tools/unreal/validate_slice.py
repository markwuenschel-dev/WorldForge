#!/usr/bin/env python3
r"""
validate_slice.py (UE5 Python) -- WorldForge slice factory, validator.

Opens the saved map a slice spec points at and asserts the slice is real and wired:

    map asset exists + loads, world name matches
    terrain actor present, terrain MI matches the spec
    PCG actor present, references the spec's PCG graph + placement DataAsset
    region marker present, region_id + state key/before/after match the spec
    placement DataAsset resolves
    MPC bridge requires an owning native state writer for a runtime readback

Writes <output_dir>/validate_slice_report.json and logs PASS/FAIL. JSON only.
Spec resolution mirrors create_slice_map.py (--spec / $WF_SLICE_SPEC / fixed pointer).
"""

import argparse
import json
import os
import sys
import traceback

import unreal

# v0.9: import the shared validation contract helper. This script runs inside the
# UE python interpreter, so resolve the repo's tools/pipeline dir from the project
# directory (mirrors how the pipeline-side validators sys.path.insert their imports)
# and resolve strict via strict_from_env() ONLY — there is no reliable argv/env CLI
# parse here; the Makefile forwards STRICT=1 into the editor subprocess env.
_PIPELINE_DIR = os.path.join(os.path.normpath(unreal.Paths.project_dir()), "tools", "pipeline")
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

TAG_REGION = "wf_region"
TAG_STATE_KEY = "wf_state_key"
TAG_STATE_BEFORE = "wf_state_before"
TAG_STATE_AFTER = "wf_state_after"
TAG_SLICE = "wf_slice"
TAG_PCG = "wf_pcg"
TAG_PCG_GRAPH = "wf_pcg_graph"
TAG_PLACEMENT_DA = "wf_placement_da"
TAG_TERRAIN = "wf_terrain"

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


# v1.1 — the curated MPC render-mirror scalar spine. Keep in sync with
# UWorldStateSubsystem::GetCuratedMpcParams() (WorldStateSubsystem.cpp): only these
# state keys push into MPC_WorldState. All other keys (biome state keys such as
# canopy_growth) are canonical in-memory state but intentionally OFF the render
# mirror, so the MPC readback check is NOT applicable to them (validated instead by
# the runtime-state scenario save/load round-trip).
CURATED_MPC_KEYS = {"industrial_pressure"}


def validate_spec(spec, root, deep=False):
    """Validate one materialized slice against its spec. Returns the ValidationReport.

    Factored out of main() so a single-session batch driver can validate many slices
    without re-booting the editor per slice.
    """
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

    # v0.9: build a shared ValidationReport. Strict is resolved from the env only
    # (the Makefile forwards STRICT=1 into the editor subprocess). This script runs
    # *inside* UE, so it can directly observe materialized Content — none of these
    # The two historically warn_only checks (player_start,
    # nav_bounds) and the "preset id omitted" cases are legacy back-compat warnings
    # (pre-v0.4 maps lack them), so they map to WARN_ONLY (never blocking, even strict).
    rep = ValidationReport("slice_id", spec["slice_id"], strict=strict_from_env())
    mpc_readback = None
    errors = []
    traceback_str = None

    def check(name, ok, detail="", warn_only=False, code=None):
        # warn_only -> WARN_ONLY (legacy compat, never blocks); else PASS/FAIL.
        if warn_only:
            return rep.warn_only(name, ok, detail, code=code)
        return rep.check(name, ok, detail, code=code)

    try:
        if not check("map_exists", unreal.EditorAssetLibrary.does_asset_exist(map_path), map_path,
                     code=FailureCode.MAP_INVALID):
            raise SystemExit("map missing -- cannot continue")
        loaded = _les().load_level(map_path)
        check("map_loads", bool(loaded), map_path, code=FailureCode.MAP_INVALID)
        world = _world()
        wname = world.get_name() if world else None
        check("world_matches", wname == expected_world,
              "world={} expected={}".format(wname, expected_world), code=FailureCode.MAP_INVALID)

        actors = _eas().get_all_level_actors()

        ground = _find(actors, lambda a: _has_tag(a, TAG_TERRAIN))
        if check("terrain_actor", ground is not None, "tag {}".format(TAG_TERRAIN),
                 code=FailureCode.SPEC_INVALID):
            assigned = None
            try:
                m = ground.static_mesh_component.get_material(0)
                assigned = m.get_path_name().split(".")[0] if m else None
            except Exception as e:  # noqa: BLE001
                assigned = "error: {}".format(e)
            check("terrain_material_matches", assigned == mi_path,
                  "assigned={} expected={}".format(assigned, mi_path), code=FailureCode.SPEC_INVALID)

        pcg = _find(actors, lambda a: _has_tag(a, TAG_PCG))
        if check("pcg_actor", pcg is not None, "tag {}".format(TAG_PCG), code=FailureCode.SPEC_INVALID):
            check("pcg_graph_linked", _tag_value(pcg, TAG_PCG_GRAPH) == pcg_path,
                  "graph={} expected={}".format(_tag_value(pcg, TAG_PCG_GRAPH), pcg_path),
                  code=FailureCode.SPEC_INVALID)
            check("placement_da_linked", _tag_value(pcg, TAG_PLACEMENT_DA) == da_path,
                  "da={} expected={}".format(_tag_value(pcg, TAG_PLACEMENT_DA), da_path),
                  code=FailureCode.SPEC_INVALID)

        marker = _find(actors, lambda a: _tag_value(a, TAG_REGION) == region_id)
        if check("region_marker", marker is not None, "wf_region:{}".format(region_id),
                 code=FailureCode.SPEC_INVALID):
            check("state_key_matches", _tag_value(marker, TAG_STATE_KEY) == state.get("key"),
                  "key={} expected={}".format(_tag_value(marker, TAG_STATE_KEY), state.get("key")),
                  code=FailureCode.SPEC_INVALID)
            check("state_before_matches",
                  _tag_value(marker, TAG_STATE_BEFORE) == str(state.get("before")),
                  "before={}".format(_tag_value(marker, TAG_STATE_BEFORE)), code=FailureCode.SPEC_INVALID)
            check("state_after_matches",
                  _tag_value(marker, TAG_STATE_AFTER) == str(state.get("after")),
                  "after={}".format(_tag_value(marker, TAG_STATE_AFTER)), code=FailureCode.SPEC_INVALID)

        check("placement_da_resolves",
              da_path is not None and unreal.EditorAssetLibrary.load_asset(da_path) is not None, da_path,
              code=FailureCode.SPEC_INVALID)

        # MPC bridge: only curated render keys project into MPC_WorldState. Runtime
        # proof for one of those keys must come from an owning native writer, because
        # editor Python cannot acquire a FWorldForgeStateWriteLease.
        state_key = str(state.get("key", ""))
        curated = state_key in CURATED_MPC_KEYS
        if curated:
            check("mpc_bridge", False,
                  "native state-write authority is required; editor Python cannot acquire a world-state write lease",
                  code=FailureCode.UE_STATE_NOT_APPLIED)
        else:
            rep.skip("mpc_bridge",
                     "state key '{}' is off the curated MPC render spine by design; "
                     "canonical round-trip validated by runtime-state scenario".format(state_key))

        # player_start and nav_bounds are warn_only for backwards compat with pre-v0.4 maps
        # -> WARN_ONLY: intentionally non-blocking forever (legacy compat).
        ps = _find(actors, lambda a: isinstance(a, unreal.PlayerStart))
        check("player_start", ps is not None, "PlayerStart actor (legacy compat: pre-v0.4 maps may lack one)",
              warn_only=True)

        nav = _find(actors, lambda a: isinstance(a, unreal.NavMeshBoundsVolume))
        check("nav_bounds", nav is not None, "NavMeshBoundsVolume actor (legacy compat: pre-v0.4 maps may lack one)",
              warn_only=True)

        # terrain_forge checks — run when spec contains a terrain_forge block
        terrain_forge = spec.get("terrain_forge")
        poi_forge = spec.get("poi_forge")
        if terrain_forge:
            tf_desc_rel = terrain_forge.get("descriptor_path", "")
            tf_desc_full = os.path.join(root, tf_desc_rel.replace("/", os.sep))
            check("terrain_forge_descriptor_exists",
                  bool(tf_desc_rel) and os.path.isfile(tf_desc_full),
                  "descriptor_path={}".format(tf_desc_rel), code=FailureCode.DESCRIPTOR_MISSING)
            # v1.1 — a definition_only terrain form (biome tier) declares no raster
            # artifacts (heightmap/masks are empty by design); the descriptor above IS
            # the artifact. Requiring raster files would check the wrong thing, so mark
            # those checks NOT_APPLICABLE. Raster-backed terrain (desert) is unaffected.
            definition_only = bool(terrain_forge.get("definition_only"))
            for artifact_key in ("heightmap", "slope_mask", "placement_mask", "nav_safe_mask"):
                rel = terrain_forge.get(artifact_key, "")
                full = os.path.join(root, rel.replace("/", os.sep)) if rel else ""
                if definition_only and not rel:
                    rep.skip("terrain_forge_{}_exists".format(artifact_key),
                             "definition_only terrain declares no {} raster (definition is the artifact)".format(artifact_key))
                    continue
                check("terrain_forge_{}_exists".format(artifact_key),
                      bool(rel) and os.path.isfile(full),
                      "path={}".format(rel), code=FailureCode.ARTIFACT_MISSING)
            # Verify the terrain actor carries the wf_terrain_forge tag.
            terrain_forge_actor = _find(actors, lambda a: "wf_terrain_forge" in _tags(a))
            check("terrain_forge_actor_tagged", terrain_forge_actor is not None,
                  "no actor with wf_terrain_forge tag found in map", code=FailureCode.SPEC_INVALID)
            if terrain_forge_actor is not None:
                expected_tf_name = terrain_forge.get("terrain_name", "")
                actual_tf_name = _tag_value(terrain_forge_actor, "wf_terrain_name")
                check("terrain_forge_name_matches",
                      actual_tf_name == expected_tf_name,
                      "actor tag wf_terrain_name={} expected={}".format(actual_tf_name, expected_tf_name),
                      code=FailureCode.SPEC_INVALID)
                expected_pm = terrain_forge.get("placement_mask", "")
                actual_pm = _tag_value(terrain_forge_actor, "wf_terrain_placement_mask")
                check("terrain_forge_placement_mask_tagged",
                      actual_pm == expected_pm,
                      "tag wf_terrain_placement_mask={} expected={}".format(actual_pm, expected_pm),
                      code=FailureCode.SPEC_INVALID)

        # poi_forge checks — run when spec contains a poi_forge block
        if poi_forge:
            poi_actor = _find(actors, lambda a: _has_tag(a, "wf_poi_forge"))
            if check("poi_forge_actor", poi_actor is not None, "no actor with wf_poi_forge tag",
                     code=FailureCode.SPEC_INVALID):
                expected_poi_type = poi_forge.get("poi_type", "")
                actual_poi_type = _tag_value(poi_actor, "wf_poi_type")
                check("poi_forge_type_matches",
                      actual_poi_type == expected_poi_type,
                      "actor tag wf_poi_type={} expected={}".format(actual_poi_type, expected_poi_type),
                      code=FailureCode.SPEC_INVALID)
                expected_poi_name = poi_forge.get("poi_name", "")
                actual_poi_name = _tag_value(poi_actor, "wf_poi_name")
                check("poi_forge_name_matches",
                      actual_poi_name == expected_poi_name,
                      "actor tag wf_poi_name={} expected={}".format(actual_poi_name, expected_poi_name),
                      code=FailureCode.SPEC_INVALID)
                expected_bounds_id = poi_forge.get("bounds_id", "primary_bounds")
                actual_bounds_id = _tag_value(poi_actor, "wf_poi_bounds")
                check("poi_forge_bounds_tagged",
                      actual_bounds_id == expected_bounds_id,
                      "tag wf_poi_bounds={} expected={}".format(actual_bounds_id, expected_bounds_id),
                      code=FailureCode.SPEC_INVALID)

        # DEEP checks — only run when _validate_config.json has {"deep": true}
        if deep:
            log("deep validation enabled")

            # placement preset file must exist on disk. Prefer the spec's own
            # placement_preset_path (biome slices live under placement/biomes/<biome>/);
            # fall back to the legacy placement/<biome>/ reconstruction for older specs.
            placement_preset_id = spec.get("placement_preset_id")
            if placement_preset_id:
                preset_rel = spec.get("placement_preset_path")
                if preset_rel:
                    preset_path = os.path.join(root, preset_rel.replace("/", os.sep))
                else:
                    preset_biome = spec.get("biome", "desert")
                    preset_path = os.path.join(root, "procedural", "definitions", "placement",
                                               preset_biome, placement_preset_id + ".yaml")
                check("placement_preset_exists",
                      os.path.isfile(preset_path),
                      "preset={} path={}".format(placement_preset_id, preset_path),
                      code=FailureCode.RECIPE_MISSING)
            else:
                check("placement_preset_exists", False,
                      "no placement_preset_id in spec (legacy compat: pre-v0.5 slices lack it)",
                      warn_only=True)

            # state preset file must exist on disk (warn_only if omitted — v0.4 slices lack it)
            state_preset_id = spec.get("state_preset_id")
            if state_preset_id:
                state_biome = spec.get("biome", "desert")
                state_path = os.path.join(root, "procedural", "definitions", "state",
                                          state_biome, state_preset_id + ".yaml")
                check("state_preset_exists",
                      os.path.isfile(state_path),
                      "preset={} path={}".format(state_preset_id, state_path),
                      code=FailureCode.RECIPE_MISSING)
            else:
                check("state_preset_exists", False,
                      "no state_preset_id in spec (legacy compat: pre-v0.4 slices lack it)",
                      warn_only=True)

            # per-slice placement DA JSON descriptor
            da_desc_path = os.path.join(root, "procedural", "generated", "placement",
                                        spec["slice_id"] + "_da.json")
            check("placement_da_exists",
                  os.path.isfile(da_desc_path),
                  "path={}".format(da_desc_path), code=FailureCode.DESCRIPTOR_MISSING)

            # budget config present (content validated by validate_budget.py on pipeline side)
            budget_path = os.path.join(root, "procedural", "definitions", "budgets", "desert_default.yaml")
            check("budget_config_loaded", os.path.isfile(budget_path),
                  "budget file missing: {}".format(budget_path), code=FailureCode.BUDGET_PROFILE_MISSING)

            # poi_forge descriptor file must exist when poi_forge is in spec
            if poi_forge:
                poi_desc_rel = poi_forge.get("descriptor_path", "")
                poi_desc_full = os.path.join(root, poi_desc_rel.replace("/", os.sep)) if poi_desc_rel else ""
                check("poi_forge_descriptor_exists",
                      bool(poi_desc_rel) and os.path.isfile(poi_desc_full),
                      "descriptor_path={}".format(poi_desc_rel), code=FailureCode.DESCRIPTOR_MISSING)
                expected_anchor_count = len(poi_forge.get("anchors", []))
                poi_anchors = [a for a in actors if _has_tag(a, "wf_poi_anchor") and
                               _tag_value(a, "wf_poi_name") == poi_forge.get("poi_name", "")]
                check("poi_forge_anchors_spawned",
                      len(poi_anchors) == expected_anchor_count,
                      "found {} anchor actors expected {}".format(len(poi_anchors), expected_anchor_count),
                      code=FailureCode.SPEC_INVALID)

        rep.finalize()
    except SystemExit as se:
        rep.error(str(se))
        errors = [str(se)]
    except Exception as exc:  # noqa: BLE001
        rep.error(str(exc))
        errors = [str(exc)]
        traceback_str = traceback.format_exc()
        log("ERROR: {}".format(exc))

    # Write the canonical v0.9 report, preserving legacy extras (map / mpc_readback /
    # errors / traceback) so existing consumers (run_slice_ue.py, validate_slice_pack.py)
    # keep working unchanged.
    out = rep.to_dict()
    out["map"] = map_path
    if mpc_readback is not None:
        out["mpc_readback"] = mpc_readback
    if errors:
        out["errors"] = errors
    if traceback_str:
        out["traceback"] = traceback_str
    with open(os.path.join(out_dir, "validate_slice_report.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    verdict = "PASS" if rep.passed else "FAIL"
    log("validate_slice: {} ({} failure(s))".format(verdict, len(rep.failures)))
    for r in rep.failures:
        log("  - {}".format(r))
    return rep


def _read_deep(root):
    config_path = os.path.join(root, "procedural", "reports", "slices", "_validate_config.json")
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f).get("deep", False)
        except Exception:
            return False
    return False


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
    validate_spec(spec, root, deep=_read_deep(root))


if __name__ == "__main__":
    main()
