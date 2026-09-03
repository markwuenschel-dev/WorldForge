---
name: neostack-pcg
description: Create, edit, generate, inspect, and visually verify Unreal Engine PCG graphs and their level components through `execute_script`. Use for procedural point generation, PCG graph nodes and edges, graph parameters or instances, component assignment, regeneration, and debugging empty PCG output.
---

# Authoring PCG through `execute_script`

Use Lua against the live editor. Start with:

```lua
help("PCG")
help("AddNode")
help("Connect")
```

Do not wrap `help(...)` in `log(...)`; help already prints its result.

Lua state is fresh on every `execute_script` call. Keep asset paths and actor
labels as literal strings, then re-open the graph and level in each pass.
Node handles persist because they are editor GUIDs, but discovering them again
with `read_graph` or `pcg:list("nodes")` is usually clearer.

## Work in four passes

1. Create a unique graph and map, then author nodes and edges.
2. Place a bounded host actor, add a `PCGComponent`, and assign the graph.
3. Re-open everything in a fresh call and verify properties, edges, and component
   assignment before generation.
4. Generate, wait for fresh component state, and inspect multiple screenshots.
   Change one node property, regenerate, and prove the visual output changes.

Never accept `generate()`'s returned count as render proof. It counts matching
components that were triggered; UE schedules their work asynchronously. Confirm
fresh `generated=true` state and read the returned images.

## End-to-end visual proof

Choose a run-specific slug once. Do not reuse another agent's path:

```lua
local slug = "PCG_GridProof_R7A" -- replace with a unique task/agent/round slug
local root = "/Game/NeoStackSkillRuns/" .. slug
local graph_path = root .. "/G_" .. slug
local level_path = root .. "/L_" .. slug

assert(not asset_exists(graph_path), "graph path already exists; choose a new slug")
assert(not asset_exists(level_path), "level path already exists; choose a new slug")
assert(create_level(level_path, { open = true }))

local graph = assert(create_asset(graph_path, "PCGGraph"))

local function first_pin(node, field)
  local pins = assert(node[field], "missing " .. field)
  local pin = assert(pins[1], "no pin in " .. field)
  if type(pin) == "table" then
    return assert(pin.name or pin.label or pin.pin or pin.display_name)
  end
  return pin
end

local grid = assert(add_node(graph_path, "Create Points Grid", -300, 0))
local debug = assert(add_node(graph_path, "Debug", 250, 0))
assert(connect(
  grid.handle, first_pin(grid, "pins_out"),
  debug.handle, first_pin(debug, "pins_in")
))

local function node_at(nodes, x, y)
  for _, node in ipairs(nodes) do
    if node.x == x and node.y == y then return node end
  end
end

local grid_entry = assert(node_at(graph:list("nodes"), -300, 0))
local debug_entry = assert(node_at(graph:list("nodes"), 250, 0))

-- Configure one property per call. A warning on one key must not be hidden by
-- another successful key in the same configure call.
assert(graph:configure("node", { index = grid_entry.index, title = "Proof Grid" }))
assert(graph:configure("node", {
  index = grid_entry.index,
  GridExtents = "(X=400,Y=400,Z=0)",
}))
assert(graph:configure("node", {
  index = grid_entry.index,
  CellSize = "(X=160,Y=160,Z=100)",
}))
assert(graph:configure("node", {
  index = grid_entry.index,
  PointSteepness = 1.0,
}))
assert(graph:configure("node", { index = debug_entry.index, title = "Proof Preview" }))
assert(graph:save())

local level = assert(open_level())
local host_label = slug .. "_BoundsHost"
local component_name = slug .. "_PCG"

-- The StaticMeshActor's registered primitive supplies finite actor bounds to
-- the PCG component. A bare Actor with only a scene root does not.
assert(level:add("actor", {
  mesh = "/Engine/BasicShapes/Cube",
  label = host_label,
  location = { x = 0, y = 0, z = -60 },
  scale = { x = 10, y = 10, z = 0.2 },
}))
assert(add_component(host_label, {
  type = "/Script/PCG.PCGComponent",
  name = component_name,
}))
assert(configure_component(host_label, component_name, {
  property = {
    bActivated = "True",
    bIsComponentPartitioned = "False",
    GenerationTrigger = "GenerateOnDemand",
    InputType = "Actor",
    bParseActorComponents = "True",
  },
}))
assert(invoke(
  { actor_label = host_label, component = component_name },
  "SetGraph",
  { { path = graph_path } }
))
assert(level:save())
```

`Create Points Grid` produces real point data. The UE 5.8 `Debug` element
materializes that data in the editor using PCG's debug point mesh. This is a
deliberate proof sink: it makes an otherwise data-only graph visible without
requiring a preconfigured Static Mesh Spawner selector.

### Verify the mutation and assignment in a fresh call

```lua
local slug = "PCG_GridProof_R7A"
local root = "/Game/NeoStackSkillRuns/" .. slug
local graph_path = root .. "/G_" .. slug
local level_path = root .. "/L_" .. slug
local host_label = slug .. "_BoundsHost"
local component_name = slug .. "_PCG"

assert(load_level(level_path))
local graph = assert(open_asset(graph_path))

local function find_node(title)
  for _, node in ipairs(graph:list("nodes")) do
    if node.title == title then return node end
  end
end

local function property(node, name)
  for _, entry in ipairs(node.properties or {}) do
    if entry.name == name then return entry.value end
  end
end

local grid = assert(find_node("Proof Grid"))
local debug = assert(find_node("Proof Preview"))
local extents = assert(property(grid, "GridExtents"))
local cell_size = assert(property(grid, "CellSize"))
local steepness = assert(property(grid, "PointSteepness"))
assert(string.find(extents, "X=400", 1, true))
assert(string.find(extents, "Y=400", 1, true))
assert(string.find(cell_size, "X=160", 1, true))
assert(string.find(cell_size, "Y=160", 1, true))
assert(tonumber(steepness) == 1.0)

local edges = graph:list("edges")
local connected = false
for _, edge in ipairs(edges) do
  if edge.from_node == "Proof Grid" and edge.to_node == "Proof Preview" then
    connected = true
  end
end
assert(connected, "fresh PCG edge readback is missing")

local components = graph:list("components")
assert(#components == 1, "expected exactly one component using this unique graph")
local component = components[1]
assert(component.actor_label == host_label)
assert(component.component_name == component_name)
assert(string.find(component.graph_path, graph_path, 1, true))
assert(component.activated == true)
assert(component.generation_trigger == "GenerateOnDemand")
assert(component.input_type == "Actor")
assert(component.parse_actor_components == true)

local level = assert(open_level())
local hosts = level:list("actors", { name = host_label })
assert(#hosts == 1, "bounded host actor is missing")
print("verified", extents, cell_size, component.generated)
```

This fresh read is the mutation gate. Do not generate if the values or edge are
wrong; fix the authoring call first.

### Capture before, dense, and sparse states

Load the level once and capture the untouched baseline before generation. This
should show one finite bounds host but no repeated point grid:

```lua
assert(load_level("/Game/NeoStackSkillRuns/PCG_GridProof_R7A/L_PCG_GridProof_R7A"))
return screenshot({
  mode = "level",
  location = { x = -1200, y = -1200, z = 900 },
  rotation = { pitch = -32, yaw = 45, roll = 0 },
  fov = 58,
  view_mode = "wireframe",
  hide_overlays = true,
  max_dimension = 1600,
  wait_for_ready_ms = 1800,
})
```

Read the returned image. Then trigger the dense state without reloading the
level:

```lua
local graph = assert(open_asset(
  "/Game/NeoStackSkillRuns/PCG_GridProof_R7A/G_PCG_GridProof_R7A"
))
assert(graph:generate(true) == 1)
```

Generation is asynchronous. In subsequent fresh calls, poll without busy
waiting:

```lua
local graph = assert(open_asset(
  "/Game/NeoStackSkillRuns/PCG_GridProof_R7A/G_PCG_GridProof_R7A"
))
local components = graph:list("components")
assert(#components == 1)
print("generated", components[1].generated)
```

Once it prints `true`, capture in a fresh Lua call but **do not call
`load_level` again**. Loading the map resets the editor-only PCG preview and
can change `generated` back to false. Repeat the same Wireframe camera directly:

```lua
return screenshot({
  mode = "level",
  location = { x = -1200, y = -1200, z = 900 },
  rotation = { pitch = -32, yaw = 45, roll = 0 },
  fov = 58,
  view_mode = "wireframe",
  hide_overlays = true,
  max_dimension = 1600,
  wait_for_ready_ms = 1800,
})
```

Read the image and verify a regular, centered grid of debug boxes is visible
above the host. Wireframe is deliberate: the Debug boxes touch at full point
scale, so Unlit renders them as one solid white slab and hides the density
difference. The trigger count and `generated=true` are not substitutes for the
image.

Now change exactly one variable:

```lua
local graph = assert(open_asset(
  "/Game/NeoStackSkillRuns/PCG_GridProof_R7A/G_PCG_GridProof_R7A"
))
local grid
for _, node in ipairs(graph:list("nodes")) do
  if node.title == "Proof Grid" then grid = node end
end
assert(grid)
assert(graph:configure("node", {
  index = grid.index,
  CellSize = "(X=320,Y=320,Z=100)",
}))
assert(graph:save())
```

Verify `CellSize` contains `X=320` and `Y=320` in a fresh call, then call
`generate(true)`, poll fresh component state, and capture the same Wireframe
camera again without reloading the level. Read both generated images side by
side: the second state must be visibly sparser while retaining the same
extents, color family, scale, and center. Capture one alternate Wireframe
viewpoint as a final occlusion check:

```lua
return screenshot({
  mode = "level",
  location = { x = 1200, y = -1200, z = 700 },
  rotation = { pitch = -27, yaw = 135, roll = 0 },
  fov = 58,
  view_mode = "wireframe",
  hide_overlays = true,
  max_dimension = 1600,
  wait_for_ready_ms = 1800,
})
```

Reject blank, unchanged, off-camera, or overlay-obscured captures. Judge gross
correctness: output exists, its density changes in the expected direction, its
scale fits the host bounds, and it is centered where authored.

## Graph operations and readback

PCG graph structure uses the ordinary graph functions:

```lua
local node = add_node(graph_path, "Surface Sampler", 0, 0)
local ok = connect(node_a.handle, output_pin, node_b.handle, input_pin)
local graph_state = read_graph(graph_path)
local ok = delete_node(node.handle)
```

Pass display pin names returned by `pins_in` and `pins_out`; do not guess them.
`read_graph(path)` returns `nodes` and top-level `connections`. The PCG-specific
`pcg:list("edges")` reads backing `UPCGEdge` state. For important edits, check
both views in a fresh call.

Use `pcg:list("node_types", { query = "grid" })` when a schema action name is
uncertain. Use `pcg:list("nodes")` to get each node's zero-based `index`,
settings class, enabled/debug state, editor position, and editable properties.
Lua arrays are one-based, but `configure("node", {index=...})` expects the
returned zero-based `entry.index`.

Add graph parameters through the PCG object:

```lua
assert(pcg:add("parameter", {
  name = "Density",
  type = "Float",
  value = 4.0,
}))
assert(pcg:configure("parameter", {
  name = "Density",
  value = 8.0,
}))
```

Re-open the graph and read `pcg:list("parameters")` before relying on the value.

## Failure modes

| Symptom | Cause and response |
| --- | --- |
| `create_asset` returns nil | The path exists or PCG is unavailable. Choose a unique path; do not overwrite another run. |
| `add_node` is ambiguous or returns nil | Use `pcg:list("node_types", {query=...})`, then pass the exact schema action title. |
| `configure("node")` warns that a property was not found | Read `entry.properties` and use the exact case-sensitive property name. A typo must not be documented as a workaround. |
| A multi-key configure returns true but one key warned | Retry one property per call and verify every value freshly. Success means at least one property changed, not that every supplied key changed. |
| `generate()` returns `0` | No level component references this graph. Check `graph:list("components")` and the exact `SetGraph` target. |
| `generate()` returns `1` but the image is blank | The call only triggered a component. Check fresh `generated` state, valid primitive-backed host bounds, graph edges, and a visual sink such as `Debug`. Do not reload the level after the preview reaches `generated=true`. |
| A bare host actor generates nothing | A scene root has no useful primitive bounds. Use a StaticMeshActor/volume or add a registered primitive component before the `PCGComponent`. |
| Dense and sparse screenshots look identical | The `CellSize` mutation did not persist, regeneration has not completed, the level was reloaded, or Unlit merged touching Debug boxes into one slab. Verify one variable at a time and reuse the same Wireframe camera. |
| Graph state looks stale after mutation | End the script and re-open the graph in a new call. Do not certify an in-script snapshot. |
| `pcall` reports success after a failed operation | Binding failures usually return `nil` and log `[FAIL]`; check every return value explicitly. |

## Discovery escape hatches

- `help("PCG")` — enrichment signatures.
- `pcg:help()` — graph-specific examples.
- `pcg:info()` — graph summary, node count, parameters, and grid metadata.
- `pcg:list("node_types", {query="..."})` — available settings classes/actions.
- `pcg:list("nodes")` / `pcg:list("edges")` / `pcg:list("components")` — fresh
  structural and level assignment evidence.
- `read_graph(graph_path)` — editor-node handles, pins, and connections.
- `report_issue("...")` — use only after a minimal fresh-call reproduction shows
  the API cannot perform a required operation.
