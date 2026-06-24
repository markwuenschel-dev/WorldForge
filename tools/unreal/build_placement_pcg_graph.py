#!/usr/bin/env python3
r"""
build_placement_pcg_graph.py (UE5 Python)

Builds the human-owned PCG template PlacementForge feeds (forge_design_decisions
D13): Input -> Surface Sampler -> Static Mesh Spawner -> Output. The scatter
DENSITY is exposed via the Surface Sampler's points_per_squared_meter, which the
state driver (apply_placement_state.py) sets live from
WorldStateSubsystem.GetStateValue — proving the placement-reacts-to-world-state chain.

Idempotent: if the graph exists it clears non-IO nodes and rebuilds (never deletes
the asset — deleting a live PCG asset corrupts it in memory).

Placeholder spawn mesh = /Engine/BasicShapes/Cube (the real foliage meshes are soft
refs that live in the consuming game project, not this tooling repo).
"""

import unreal

GRAPH_PATH = "/Game/Procedural/PCG/PCG_FoliageScatter"
MESH_PATH = "/Engine/BasicShapes/Cube.Cube"
DEFAULT_POINTS_PER_SQM = 0.05  # ~1 cube per 4.5m x 4.5m; cubes are big


def _labels(node, prop):
    out = []
    for p in node.get_editor_property(prop):
        try:
            out.append(str(p.get_editor_property("properties").get_editor_property("label")))
        except Exception:
            out.append("?")
    return out


def _first_label(node, prop, prefer=()):
    labels = _labels(node, prop)
    for want in prefer:
        for l in labels:
            if l.lower() == want.lower():
                return l
    return labels[0] if labels else None


def _set_spawner_mesh(settings, mesh):
    """Configure the StaticMeshSpawner's weighted mesh selector with one entry."""
    try:
        settings.set_mesh_selector_type(unreal.PCGMeshSelectorWeighted)
        sel = settings.get_editor_property("mesh_selector_instance")
        entry = unreal.PCGMeshSelectorWeightedEntry()
        desc = entry.get_editor_property("descriptor")
        desc.set_editor_property("static_mesh", mesh)
        entry.set_editor_property("descriptor", desc)
        entry.set_editor_property("weight", 1)
        sel.set_editor_property("mesh_entries", [entry])
        return {"mesh_selector": "PCGMeshSelectorWeighted", "entries": 1}
    except Exception as e:
        # Don't fail the whole build — report the selector shape so we can adjust.
        return {"mesh_selector_error": str(e),
                "selector_type": str(settings.get_editor_property("mesh_selector_type")),
                "selector_props": sorted(m for m in dir(settings.get_editor_property("mesh_selector_instance"))
                                         if "mesh" in m.lower() or "entr" in m.lower())}


def build():
    at = unreal.AssetToolsHelpers.get_asset_tools()
    pkg, name = GRAPH_PATH.rsplit("/", 1)

    if unreal.EditorAssetLibrary.does_asset_exist(GRAPH_PATH):
        graph = unreal.EditorAssetLibrary.load_asset(GRAPH_PATH)
        inp = graph.get_input_node()
        outp = graph.get_output_node()
        to_remove = [n for n in graph.get_editor_property("nodes") if n != inp and n != outp]
        if to_remove:
            graph.remove_nodes(to_remove)
    else:
        graph = at.create_asset(name, pkg, unreal.PCGGraph, unreal.PCGGraphFactory())
        inp = graph.get_input_node()
        outp = graph.get_output_node()

    mesh = unreal.load_asset(MESH_PATH)
    if not mesh:
        raise RuntimeError(f"placeholder mesh not found: {MESH_PATH}")

    ss_node, ss_settings = graph.add_node_of_type(unreal.PCGSurfaceSamplerSettings)
    sm_node, sm_settings = graph.add_node_of_type(unreal.PCGStaticMeshSpawnerSettings)

    ss_settings.set_editor_property("points_per_squared_meter", DEFAULT_POINTS_PER_SQM)
    mesh_result = _set_spawner_mesh(sm_settings, mesh)

    # Wire Input -> SurfaceSampler -> SpawnMesh -> Output using read-back labels.
    in_out = _first_label(inp, "output_pins", prefer=("Input", "Out", "Landscape"))
    ss_in = _first_label(ss_node, "input_pins", prefer=("Surface", "In"))
    ss_out = _first_label(ss_node, "output_pins", prefer=("Out",))
    sm_in = _first_label(sm_node, "input_pins", prefer=("In",))
    sm_out = _first_label(sm_node, "output_pins", prefer=("Out",))
    out_in = _first_label(outp, "input_pins", prefer=("Output", "In"))

    wiring = []
    if in_out and ss_in:
        graph.add_edge(inp, in_out, ss_node, ss_in); wiring.append(f"Input.{in_out}->Sampler.{ss_in}")
    graph.add_edge(ss_node, ss_out, sm_node, sm_in); wiring.append(f"Sampler.{ss_out}->Spawner.{sm_in}")
    graph.add_edge(sm_node, sm_out, outp, out_in); wiring.append(f"Spawner.{sm_out}->Output.{out_in}")

    unreal.EditorAssetLibrary.save_loaded_asset(graph)

    return {
        "status": "ok",
        "graph": GRAPH_PATH,
        "mesh": MESH_PATH,
        "points_per_squared_meter": DEFAULT_POINTS_PER_SQM,
        "wiring": wiring,
        "mesh_result": mesh_result,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(build(), indent=2))
