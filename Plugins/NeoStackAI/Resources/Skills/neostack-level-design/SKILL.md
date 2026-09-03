---
name: neostack-level-design
description: Create, edit, compose, save, and visually verify Unreal Engine levels through `execute_script`. Use when the user asks to build or modify a map, place or configure actors and meshes, arrange folders, add lights or cameras, duplicate level content, manage actor components or properties, inspect level state, or capture clean level screenshots.
---

# Level design through `execute_script`

Use Lua against the live editor. Start with `help("LevelDesign")`, then open a
fresh level handle in every call:

```lua
local level = open_level()
if not level then error("No editor level is available") end
```

Lua state does not survive between calls. Re-run `open_level()` for every
mutation and every verification pass.

## Work in four passes

1. Discover the live signatures with `help("LevelDesign")` and
   `print(open_level():help())`.
2. Build a labeled, foldered composition.
3. Re-open the level in a fresh call and verify actors, properties, and counts.
4. Save, verify the package path, and pass a clean visual gate.

Do not treat a non-nil mutation result as final proof. Read the affected state
again in a separate `execute_script` call.

## Create or open a level

Use `open_level()` to edit the current map. When the task requires a new map,
the current LevelDesign help exposes:

```lua
create_level("/Game/Levels/L_Courtyard", {
  template = "basic",
  open = true,
})
```

Use a `/Game/...` package path without `.umap`. `open=true` makes the new map
the active editor world. If the level already exists, load it explicitly:

```lua
load_level("/Game/Levels/L_Courtyard")
local level = open_level()
```

To preserve an unsaved current world under a new name:

```lua
assert(save_level_as("/Game/Levels/L_Courtyard"))
```

Verify the save in a fresh call:

```lua
local level = open_level()
local info = level:info()
print(info.package_name, info.world_name)
assert(info.package_name == "/Game/Levels/L_Courtyard")
assert(asset_exists("/Game/Levels/L_Courtyard"))
```

## Build a small composition

Create every actor with a deliberate label and folder. Labels are the stable
inputs for later configure, selection, duplication, component, and property
operations.

```lua
local level = open_level()
local root = "Courtyard"
local geo = root .. "/Geometry"
local lighting = root .. "/Lighting"
local cameras = root .. "/Cameras"

local function need(value, operation)
  if value == nil or value == false then
    error("Level operation failed: " .. operation)
  end
  return value
end

need(level:add("folder", { path = root }), "root folder")
need(level:add("folder", { path = geo }), "geometry folder")
need(level:add("folder", { path = lighting }), "lighting folder")
need(level:add("folder", { path = cameras }), "camera folder")

need(level:add("actor", {
  mesh = "/Engine/BasicShapes/Cube",
  location = { x = 0, y = 0, z = -25 },
  scale = { x = 12, y = 10, z = 0.25 },
  label = "Courtyard_Ground",
  folder = geo,
}), "ground")

need(level:add("actor", {
  mesh = "/Engine/BasicShapes/Cylinder",
  location = { x = 0, y = 0, z = 60 },
  scale = { x = 1.8, y = 1.8, z = 1.4 },
  label = "Courtyard_Pedestal",
  folder = geo,
}), "pedestal")

need(level:add("actor", {
  mesh = "/Engine/BasicShapes/Sphere",
  location = { x = 0, y = 0, z = 230 },
  scale = { x = 1.35, y = 1.35, z = 1.35 },
  label = "Courtyard_Orb",
  folder = geo,
}), "orb")

need(level:add("light", {
  type = "point",
  location = { x = -320, y = -180, z = 380 },
  intensity = 1800,
  color = "255,80,35",
  label = "Courtyard_WarmKey",
  folder = lighting,
}), "warm key")

need(level:add("light", {
  type = "spot",
  location = { x = 0, y = -700, z = 650 },
  rotation = { pitch = -35, yaw = 90, roll = 0 },
  intensity = 2200,
  color = "255,230,190",
  label = "Courtyard_RimSpot",
  folder = lighting,
}), "rim spot")

need(level:add("actor", {
  class = "CameraActor",
  location = { x = -1100, y = -1100, z = 720 },
  rotation = { pitch = -20, yaw = 45, roll = 0 },
  label = "Courtyard_Camera",
  folder = cameras,
}), "camera")

need(level:save(), "save")
```

`add("actor")` requires either `mesh` or `class`. Missing both returns nil and
must leave no actor behind. `add("light")` accepts `point`, `spot`,
`directional`, or `sky`; provide labels and folders just as for mesh actors.

## Configure and duplicate actors

Use `configure("actor", label, params)` for transforms, labels, folders, mesh,
material, and supported properties:

```lua
local level = open_level()
assert(level:configure("actor", "Courtyard_Orb", {
  location = { x = 0, y = 0, z = 260 },
  scale = { x = 1.5, y = 1.5, z = 1.5 },
  folder = "Courtyard/Geometry",
}))
```

Duplicate one actor with an explicit label:

```lua
local copy = duplicate_actor("Courtyard_Pedestal", {
  offset = { x = 0, y = 420, z = 0 },
  new_label = "Courtyard_Pedestal_Right",
})
assert(copy)

local level = open_level()
assert(level:configure("actor", copy.label, {
  folder = "Courtyard/Geometry",
}))
```

Bulk duplication returns actor tables. Relabel and refolder every result because
the engine generates their initial labels:

```lua
local copies = duplicate_actors(
  { "Courtyard_Pedestal", "Courtyard_Orb" },
  { offset = { x = 0, y = 420, z = 0 } }
)
assert(copies and #copies == 2)

local level = open_level()
local labels = { "Courtyard_Pedestal_Copy", "Courtyard_Orb_Copy" }
for i = 1, #copies do
  assert(level:configure("actor", copies[i].label, {
    label = labels[i],
    folder = "Courtyard/Geometry",
  }))
end
```

Selection is additive until cleared:

```lua
deselect_all()
assert(select_actor("Courtyard_Pedestal"))
assert(select_actor("Courtyard_Orb"))
local selected = get_selected_actors()
assert(#selected == 2)
```

## Components and properties

Discover component names before addressing them:

```lua
local components = list_actor_components("Courtyard_Orb")
for i = 1, #components do
  print(components[i].name, components[i].class)
end
```

Read a component or actor property in a fresh call:

```lua
print(get_actor_property("Courtyard_Orb", "RelativeScale3D"))

local props = get_component_properties(
  "Courtyard_Orb",
  "StaticMeshComponent0",
  { all = true, changed_only = false }
)
```

`get_actor_property` and `set_actor_property` try the actor first, then its root
component. Check the structured write result and read the stored value again:

```lua
local ok, details = set_actor_property(
  "Courtyard_WarmKey",
  "Intensity",
  1800
)
assert(ok)
assert(details.status == "updated")
print(details.target, details.stored_value)
```

Fresh verification:

```lua
assert(get_actor_property("Courtyard_WarmKey", "Intensity") == "1800.000000")
```

For explicit component lifecycle operations, use the signatures returned by
`help("LevelDesign")`:

```lua
local component = add_component("Courtyard_Pedestal", {
  type = "PointLightComponent",
  name = "AccentLight",
})
assert(component)

assert(configure_component("Courtyard_Pedestal", "AccentLight", {
  intensity = 800,
  color = "80,120,255",
}))

assert(remove_component("Courtyard_Pedestal", "AccentLight"))
```

## Verify structure and persistence

Filter by the label prefix and inspect every returned actor:

```lua
local level = open_level()
local actors = level:list("actors", { name = "Courtyard_" })
for i = 1, #actors do
  local actor = actors[i]
  print(
    actor.label,
    actor.class,
    actor.folder,
    actor.location.x,
    actor.location.y,
    actor.location.z
  )
end
-- The full example above creates six originals and three duplicates.
assert(#actors == 9)
```

Use `level:info()` for package and aggregate checks. Its level summary includes
`package_name`, `path`, `world_name`, `actor_count`, `landscape_count`,
`light_count`, `folder_count`, `folders`, and bounds when valid.

Use serialization for deeper inspection or reproducibility:

```lua
local level = open_level()
local actors = level:serialize("table")
local recreation_script = level:serialize("script")
assert(type(actors) == "table")
assert(type(recreation_script) == "string")
```

Run Unreal's native Map Check directly before accepting or saving a composed
level:

```lua
local check = assert(open_level():map_check())
assert(check.passed, "Map Check reported " .. tostring(check.errors) .. " error(s)")
if not check.clean then
  log("Map Check warnings: " .. tostring(check.warnings))
end
```

`passed` means the current run has no errors; `clean` means it has neither
errors nor warnings. The `errors`, `warnings`, and `issue_count` fields always
describe this invocation. By default Map Check clears its message-log page
first. For diagnostics that must append to the existing page, call
`map_check({clear_log=false})`; its `page_error_count`,
`page_warning_count`, and `page_issue_count` fields then expose cumulative page
totals while the non-`page_` fields remain per-run deltas. Use
`deprecated_only=true` only when explicitly checking deprecated actors.

Call `level:save()` after edits to an already-named map. Use `save_level_as(path)`
only when assigning or changing the map package path.

## Pass the visual gate

Capture from deliberate viewpoints with `mode="level"` and
`hide_overlays=true`:

```lua
screenshot({
  mode = "level",
  location = { x = -950, y = -550, z = 260 },
  rotation = { pitch = 0, yaw = 30, roll = 0 },
  fov = 62,
  view_mode = "lit",
  hide_overlays = true,
  max_dimension = 1600,
  wait_for_ready_ms = 1800,
})
```

Capture at least two materially different viewpoints. For animated content,
capture at least two distinct animation frames; one still cannot prove motion.
Inspect every returned image and verify:

- All intended geometry is visible.
- Object count and duplication count match the fresh actor listing.
- Scale and spacing read correctly from the chosen viewpoints.
- Intended light or material colors are visible without destructive clipping.
- No editor icons, selection outlines, widgets, or transform gizmos remain.

If the image is empty, aimed at unrelated terrain, or still contains editor
overlays, do not accept it. Adjust the camera only when the scene data is
correct; otherwise stop and localize the capture defect.

## Failure modes

| Symptom | Cause and response |
| --- | --- |
| `open_level()` returns nil | No usable editor world is active. Open a map and retry. |
| `add("actor")` returns nil | Supply a valid `mesh` or actor `class`; verify the path/class with discovery first. |
| A mutation logs success but the read looks stale | Re-open the level and verify in a new `execute_script` call. |
| Duplicate labels are engine-generated | Relabel and refolder each table returned by `duplicate_actors`. |
| Property write fails | Inspect `details.status` and `details.error`; do not assume actor and root-component properties share a target. |
| Map Check returns nil | Stop PIE and verify an editor world is active; malformed options are rejected instead of coerced. |
| Map Check passes but is not clean | Errors are zero but warnings remain. Inspect the native `MapCheck` message log instead of treating warnings as errors. |
| Save fails | Confirm a writable `/Game/...` package path and inspect the exact editor log. |
| Screenshot misses the scene | Use explicit camera transforms or `focus_actor`, then inspect the returned image rather than trusting the text response. |
| `hide_overlays=true` still shows editor chrome | Treat the screenshot as failed and report the capture defect; do not use it as visual proof. |

Use `help("LevelDesign")`, `print(open_level():help())`, `level:info()`, component
property reads, and fresh actor listings as discovery escape hatches. When the
binding behaves differently from its help or cannot complete the requested
task, call `report_issue(...)` with the minimal reproduction before reporting
the gap.
