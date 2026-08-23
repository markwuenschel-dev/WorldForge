#!/usr/bin/env python3
"""wfcore_mesh_synthesis -- build a StaticMesh asset from a synthesis spec.

FAR SIDE. Runs inside the UE interpreter, reads its inputs from the environment,
writes exactly one JSON document, and never uses stdout as an evidence channel --
the same contract ``wfcore_unreal_sink.py`` follows, for the same reasons.

WHY ASSET CREATION IS NOT A WORLD MUTATION
-------------------------------------------
The transaction sink exists to change a level under a bound that can be undone by
removing what it added. An asset is different: it outlives the level, other
things reference it, and "un-creating" one that something already points at is
not a rollback but a break. Folding this into the sink would have handed it a
compensation it cannot honestly provide, so synthesis is its own step with its
own honest limit -- stated below rather than implied.

WHAT THIS WILL NOT DO
---------------------
It refuses to overwrite an existing asset. Silently replacing a mesh that a level
already references would change worlds nobody rebuilt, and it is exactly the kind
of quiet action the ownership rails exist to prevent. Re-running with the same
path is an error, not an update.

ENVIRONMENT CONTRACT
--------------------
    WF_MS_SPEC   absolute path to a wf.core.terrain_mesh_plan.v1 document (REQUIRED)
    WF_MS_OUT    absolute path for the result JSON                        (REQUIRED)
"""

import json
import os
import traceback

FAR_SIDE_SCHEMA = "wf.core.mesh_synthesis_result.v1"

# Declared literally: an ImportError at module scope inside the UE interpreter
# would kill this before any evidence could be written.
FC_SPEC_INVALID = "WF1293_CORE_PLACEMENT_PLAN_INVALID"
FC_SYNTHESIS_FAILED = "WF1278_CORE_SINK_APPLY_FAILED"
FC_WOULD_OVERWRITE = "WF1279_CORE_SINK_NO_COMPENSATION"


def _doc():
    return {"far_side_schema": FAR_SIDE_SCHEMA, "spec_path": None,
            "asset_path": None, "created": False, "saved": False,
            "vertex_count": None, "triangle_count": None,
            "observed_bounds_cm": None, "failure_codes": [], "error": None,
            "traceback": None, "notes": []}


def main():
    doc = _doc()
    out = os.environ.get("WF_MS_OUT")
    try:
        import unreal
        spec_path = os.environ.get("WF_MS_SPEC")
        doc["spec_path"] = spec_path
        if not spec_path or not os.path.isfile(spec_path):
            doc["error"] = "WF_MS_SPEC is unset or not a file"
            doc["failure_codes"].append(FC_SPEC_INVALID)
            return doc

        with open(spec_path, encoding="utf-8") as fh:
            spec = json.load(fh)
        if spec.get("refused"):
            doc["error"] = "spec is a refusal, not a plan: {}".format(
                spec.get("refusal_reason"))
            doc["failure_codes"].append(FC_SPEC_INVALID)
            return doc

        asset_path = spec.get("asset_path")
        verts = spec.get("vertices") or []
        tris = spec.get("triangles") or []
        doc["asset_path"] = asset_path
        if not asset_path or not verts or not tris:
            doc["error"] = "spec carries no asset_path/vertices/triangles"
            doc["failure_codes"].append(FC_SPEC_INVALID)
            return doc

        # REFUSE rather than replace. See the module docstring.
        if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            doc["error"] = (
                "an asset already exists at {}. Refusing to overwrite: a level "
                "may reference it, and replacing it would change a world nobody "
                "rebuilt".format(asset_path))
            doc["failure_codes"].append(FC_WOULD_OVERWRITE)
            return doc

        # The asset is created FIRST and built into, rather than built in
        # memory and copied. A transient StaticMesh is not a loaded asset, so
        # duplicate_loaded_asset returns None for it -- learned by trying it.
        pkg_path, _sep, asset_name = asset_path.rpartition("/")
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        mesh = tools.create_asset(asset_name, pkg_path, unreal.StaticMesh, None)
        if mesh is None:
            doc["error"] = ("create_asset returned None for {} in {}; no factory "
                            "is available for StaticMesh in this build and the "
                            "default path did not work either".format(
                                asset_name, pkg_path))
            doc["failure_codes"].append(FC_SYNTHESIS_FAILED)
            return doc

        desc = mesh.create_static_mesh_description()
        vids = []
        for v in verts:
            vid = desc.create_vertex()
            desc.set_vertex_position(vid, unreal.Vector(v[0], v[1], v[2]))
            vids.append(vid)
        group = desc.create_polygon_group()
        for t in tris:
            instances = [desc.create_vertex_instance(vids[i]) for i in t]
            desc.create_triangle(group, instances)
        mesh.build_from_static_mesh_descriptions([desc])
        doc["notes"].append("built description: {} vertices, {} triangles".format(
            len(verts), len(tris)))

        doc["created"] = True
        doc["saved"] = bool(unreal.EditorAssetLibrary.save_asset(asset_path))

        # Re-observed from the asset that now exists, not from the spec we were
        # handed: the point of this record is what is on disk.
        try:
            back = unreal.EditorAssetLibrary.load_asset(asset_path)
            doc["triangle_count"] = int(back.get_num_triangles(0))
            doc["vertex_count"] = int(back.get_num_vertices(0))
            b = back.get_bounds().box_extent
            doc["observed_bounds_cm"] = [round(b.x, 3), round(b.y, 3),
                                         round(b.z, 3)]
        except Exception as exc:  # noqa: BLE001
            doc["notes"].append("re-observation partial: {}: {}".format(
                type(exc).__name__, exc))
        return doc
    except Exception as exc:  # noqa: BLE001
        doc["error"] = "{}: {}".format(type(exc).__name__, exc)
        doc["traceback"] = traceback.format_exc()
        doc["failure_codes"].append(FC_SYNTHESIS_FAILED)
        return doc
    finally:
        if out:
            try:
                with open(out, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh, indent=2, sort_keys=True)
            except OSError:
                pass
        try:
            import unreal as _u
            _u.SystemLibrary.quit_editor()
        except Exception:  # noqa: BLE001
            pass


main()
