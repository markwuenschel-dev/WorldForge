---
name: neostack-control-rig
description: Author and verify Unreal Control Rig assets through execute_script. Use when the user asks for a Control Rig hierarchy, controls, animation channels, control settings, poses, RigVM graph discovery, or visual Control Rig proof.
---

# Control Rig authoring

Everything below is Lua for `execute_script`. Each call starts a fresh Lua
state, so reopen the Control Rig at the start of every call.

The reliable workflow is:

1. Duplicate a genuine UE 5.8 Control Rig asset into a unique `/Game` path and
   convert the module fixture to a standalone rig.
2. Call `cr:help()` and `cr:list("graphs")`; do not guess the graph name.
3. Add the hierarchy from parent to child.
4. Configure controls and author values, checking every return.
5. Save, then reopen in a fresh call and verify hierarchy, settings, values, and
   graph names.
6. Capture and read at least two visibly different posed states.

A valid hierarchy and clean graph readback are not visual proof. A Control Rig
can contain the requested elements while its controls are hidden, unposed, or
at the wrong scale.

## Start from a genuine Control Rig

UE 5.8 enables Blueprint-independent Control Rig assets. The legacy
`ControlRigBlueprint` factory is unavailable in that mode, and NeoStack refuses
to report a plain or uninitialised Blueprint as a Control Rig. Duplicate a
known genuine asset instead:

```lua
local path = "/Game/Rigs/CR_NeoProof"
assert(not asset_exists(path), "choose a fresh destination path")

local copied = duplicate_asset(
  "/ControlRig/Modules/Modules58/Root",
  "CR_NeoProof",
  "/Game/Rigs"
)
assert(copied and copied.success, copied and copied.error or "duplicate failed")

local cr = open_asset(path)
assert(cr and string.find(cr.type, "ControlRig"))
assert(cr:make_standalone())
assert(cr:save())
```

`cr:save()` finalizes pending RigVM graph mutations before the existing
compile, preview synchronization, and package save. A successful return means
those graph edits are included in the saved package rather than deferred until
after the save.

`duplicate_asset` returns a result table; success is `copied.success`, not the
truthiness of the table itself. Use a unique destination name for each task.
Do not substitute a generic Blueprint asset: it does not provide the Control
Rig hierarchy/controller this API requires.

The source asset above is the UE 5.8 Control Rig module fixture exercised by the
binding tests. `make_standalone()` is required immediately after duplication:
the module preview is not proof of a standalone authored rig, and conversion
resets module-authored hierarchy state, then UE reimports bones and sockets from
the fixture's preview skeletal mesh. Existing skeleton elements such as
`root`, `pelvis`, or `spine_01` may therefore remain. Add your uniquely named
hierarchy only after conversion and do not assert that the asset is otherwise
empty. The call is idempotent once the asset is standalone.

If the fixture is unavailable in a different engine installation, locate
another genuine Control Rig asset first and duplicate that; do not change asset
type as a workaround.

## Discover the actual asset shape

The enriched Control Rig table has its own `help()` method. Unlike top-level
`help("Domain")`, this method returns a string, so print the returned text:

```lua
local cr = assert(open_asset("/Game/Rigs/CR_NeoProof"))
local docs = assert(cr:help())
print(docs)

local graphs = assert(cr:list("graphs"))
assert(#graphs > 0)
for i, graph_name in ipairs(graphs) do
  print("graph", i, graph_name)
end

local first_graph = assert(read_graph(cr.path, graphs[1]))
print("nodes", #(first_graph.nodes or {}))

local shapes = assert(cr:list("shape_names"))
assert(#shapes > 0)
for i, shape_name in ipairs(shapes) do
  print("shape", i, shape_name)
end
```

`list("graphs")` returns an array of graph-name strings from the asset's real
editor graphs. Never assume a RigVM model display name such as `RigVMModel`,
and never treat the array entries as graph objects. Every returned string is
accepted by `read_graph(cr.path, graph_name)`. A graph whose simple UObject name
is unique is returned by that name; duplicate nested names are returned as
unique asset-relative graph paths.

Unknown list types return `nil` and emit `[FAIL]`; they do not fall back to all
hierarchy elements:

```lua
assert(cr:list("not_a_real_list_type") == nil)
```

## End-to-end hierarchy and pose

Add parents before children. `transform` on bones and nulls uses nested
`location`, `rotation`, and `scale` tables:

```lua
local path = "/Game/Rigs/CR_NeoProof"
local cr = assert(open_asset(path))

assert(cr:add("bone", {
  name = "NS_ProofRoot",
  transform = {
    location = {x=0, y=0, z=0},
    rotation = {pitch=0, yaw=0, roll=0},
    scale = {x=1, y=1, z=1},
  },
}))

assert(cr:add("bone", {
  name = "NS_ProofTip",
  parent = "NS_ProofRoot",
  transform = {
    location = {x=0, y=0, z=12},
    rotation = {pitch=0, yaw=0, roll=0},
    scale = {x=1, y=1, z=1},
  },
}))

assert(cr:add("null", {
  name = "NS_ProofSpace",
  parent = "NS_ProofRoot",
  transform = {location={x=0, y=0, z=0}},
}))

assert(cr:add("control", {
  name = "NS_ProofControl",
  parent = "NS_ProofSpace",
  control_type = "EulerTransform",
  anim_type = "AnimationControl",
  display_name = "Neo Proof",
  shape_visible = true,
}))

assert(cr:configure("control", "NS_ProofControl", {
  control_type = "EulerTransform",
  anim_type = "AnimationControl",
  display_name = "Neo Proof",
  shape_visible = true,
  shape_name = "Box_Solid",
  shape_color = "(R=0.0,G=0.8,B=1.0,A=1.0)",
  shape_transform = {scale={x=2.0, y=2.0, z=2.0}},
}))

assert(cr:add_animation_channel({
  name = "NS_ProofBlend",
  parent_control = "NS_ProofControl",
  control_type = "Float",
}))

local state_a = {
  tx = -8, ty = 0, tz = 0,
  pitch = 0, yaw = -30, roll = 0,
  sx = 1, sy = 1, sz = 1,
}
assert(cr:set_control_value(
  "NS_ProofControl", state_a, {value_type="initial"}))
assert(cr:set_control_value("NS_ProofControl", state_a))

assert(cr:clear_selection())
assert(cr:save())
```

`add_animation_channel` requires an existing **control** as
`parent_control`. Its `control_type` is strict: misspellings return `nil` and
do not leave a channel behind.

Value fields depend on control type:

| Control type | Value fields |
|---|---|
| `Bool` | `value` |
| `Float`, `ScaleFloat`, `Integer` | `x` |
| `Vector2D` | `x`, `y` |
| `Position`, `Scale`, `Rotator` | `x`, `y`, `z` |
| `EulerTransform`, `Transform` | `tx`, `ty`, `tz`, `pitch`, `yaw`, `roll`, `sx`, `sy`, `sz` |
| `TransformNoScale` | `tx`, `ty`, `tz`, `pitch`, `yaw`, `roll` |

`TransformNoScale` explicitly rejects `sx`, `sy`, or `sz`; remove those fields
instead of retrying with a different value.

Use `{value_type="initial"}`, `{value_type="minimum"}`, or
`{value_type="maximum"}` as the optional third argument when that is the value
being authored. The default is `"current"`:

```lua
assert(cr:set_control_value(
  "NS_ProofControl",
  {tx=0, ty=0, tz=100, pitch=0, yaw=0, roll=0, sx=1, sy=1, sz=1},
  {value_type="initial"}
))
```

## Fresh structural and value verification

Do this in another `execute_script` call. Lists read the current hierarchy, but
reopening prevents a stale Lua asset table from being mistaken for persistence:

```lua
local path = "/Game/Rigs/CR_NeoProof"
local cr = assert(open_asset(path))

local info = assert(cr:info())
assert(info.total_count > 0)
assert(info.bone_count >= 2)

local function by_name(rows, wanted)
  for _, row in ipairs(rows) do
    if row.name == wanted then return row end
  end
end

local bones = assert(cr:list("bones"))
local controls = assert(cr:list("controls"))
local root = assert(by_name(bones, "NS_ProofRoot"))
local tip = assert(by_name(bones, "NS_ProofTip"))
local ctrl = assert(by_name(controls, "NS_ProofControl"))
local channel = assert(by_name(controls, "NS_ProofBlend"))

assert(tip.parent == "NS_ProofRoot")
assert(ctrl.parent == "NS_ProofSpace")
assert(ctrl.control_type == "EulerTransform")
assert(ctrl.shape_visible == true)
assert(ctrl.shape_name == "Box_Solid")
assert(channel.parent == "NS_ProofControl")
assert(channel.control_type == "Float")

local pose = assert(cr:get_control_value("NS_ProofControl"))
assert(pose.control_type == "EulerTransform")
assert(pose.tx == -8 and pose.tz == 0 and pose.yaw == -30)

local graphs = assert(cr:list("graphs"))
assert(#graphs > 0)
assert(read_graph(cr.path, graphs[1]))
```

`info()` exposes both convention-compliant count names (`bone_count`,
`control_count`, `total_count`, `variable_count`) and legacy mirrors (`bones`,
`controls`, `total`, `variables`). Prefer the `*_count` fields.

## Strict configure verification

Control type and animation type are engine enum names, not free-form strings.
Valid control types include `Bool`, `Float`, `Integer`, `Vector2D`, `Position`,
`Scale`, `Rotator`, `Transform`, `TransformNoScale`, `EulerTransform`, and
`ScaleFloat`. `Int` remains an accepted alias for `Integer`.

After a successful configure, read the settings back through
`list("controls")`. Control rows include `control_type`, `anim_type`,
`display_name` when set, `shape_visible`, `shape_name` when set, and
`shape_color`, the initial-local `shape_transform`, and `has_limits`:

```lua
local cr = assert(open_asset("/Game/Rigs/CR_NeoProof"))
assert(cr:configure("control", "NS_ProofControl", {
  control_type = "Transform",
  display_name = "Transform Proof",
  shape_visible = true,
}))

local stored
for _, row in ipairs(cr:list("controls")) do
  if row.name == "NS_ProofControl" then stored = row end
end
assert(stored)
assert(stored.control_type == "Transform")
assert(stored.anim_type == "AnimationControl")
assert(stored.display_name == "Transform Proof")
assert(stored.shape_visible == true)
assert(stored.shape_color.r >= 0 and stored.shape_color.a == 1)
assert(stored.shape_transform.scale.x > 0)
assert(cr:save())
```

Shape colors and transforms are stored as engine floats. Compare decimal
readbacks with a tolerance rather than Lua `==`:

```lua
local function near(actual, expected, tolerance)
  return math.abs(actual - expected) <= (tolerance or 0.001)
end
assert(near(stored.shape_color.r, 0.1))
assert(near(stored.shape_transform.scale.x, 2.0))
```

An invalid enum makes the whole settings update fail. It must not apply other
keys from the same table:

```lua
local cr = assert(open_asset("/Game/Rigs/CR_NeoProof"))

local function find_control()
  for _, row in ipairs(cr:list("controls")) do
    if row.name == "NS_ProofControl" then return row end
  end
end

local before = assert(find_control())
local ok = cr:configure("control", "NS_ProofControl", {
  control_type = "DefinitelyNotAControlType",
  shape_visible = not before.shape_visible,
})
assert(ok == nil)

local after = assert(find_control())
assert(after.control_type == before.control_type)
assert(after.shape_visible == before.shape_visible)
```

Failures return `nil` and print `[FAIL]`; they do not raise by themselves.
Check return values. A Lua `pcall` around a failed binding call can still report
that Lua execution succeeded.

## Multiple-state visual proof

Pose the control in one call, let the editor update, and capture in the next.
Do not capture only the default pose. Clear hierarchy selection before every
capture: Unreal's selection highlight replaces the authored control color and
cannot prove the requested color. After each save, run `sync_preview()` in its
own fresh `execute_script` call. Capture in the following call. UE 5.8 can have
no debug Control Rig attached immediately after opening the asset editor;
`sync_preview()` creates and attaches that host, copies the authoritative
hierarchy and pose into it, and verifies every copied element. The MCP call
boundary then lets the editor finish attaching that host before screenshot
rendering begins.

State A:

```lua
local cr = assert(open_asset("/Game/Rigs/CR_NeoProof"))
local pose = {
  tx=-8, ty=0, tz=0,
  pitch=0, yaw=-30, roll=0,
  sx=1, sy=1, sz=1,
}
assert(cr:set_control_value(
  "NS_ProofControl", pose, {value_type="initial"}))
assert(cr:set_control_value("NS_ProofControl", pose))
assert(cr:save())
```

```lua
local cr = assert(open_asset("/Game/Rigs/CR_NeoProof"))
assert(cr:sync_preview())
assert(cr:clear_selection())
```

Run the screenshot in the next `execute_script` call:

```lua
local cr = assert(open_asset("/Game/Rigs/CR_NeoProof"))
assert(cr:clear_selection())
screenshot({
  mode="asset",
  asset="/Game/Rigs/CR_NeoProof",
  max_dimension=1600,
  wait_for_ready_ms=1500,
  orbit_yaw=-90,
  orbit_pitch=-15,
  orbit_distance=50,
})
```

State B:

```lua
local cr = assert(open_asset("/Game/Rigs/CR_NeoProof"))
local pose = {
  tx=8, ty=0, tz=0,
  pitch=0, yaw=60, roll=0,
  sx=1, sy=1, sz=1,
}
assert(cr:set_control_value(
  "NS_ProofControl", pose, {value_type="initial"}))
assert(cr:set_control_value("NS_ProofControl", pose))
assert(cr:save())
```

```lua
local cr = assert(open_asset("/Game/Rigs/CR_NeoProof"))
assert(cr:sync_preview())
assert(cr:clear_selection())
```

Run the screenshot in the next `execute_script` call:

```lua
local cr = assert(open_asset("/Game/Rigs/CR_NeoProof"))
assert(cr:clear_selection())
screenshot({
  mode="asset",
  asset="/Game/Rigs/CR_NeoProof",
  max_dimension=1600,
  wait_for_ready_ms=1500,
  orbit_yaw=-90,
  orbit_pitch=-15,
  orbit_distance=50,
})
```

Read both returned images. Confirm the cyan control is visible at a useful
scale and that its gross position and rotation differ between A and B. Also
confirm each state with a fresh `get_control_value` call. If the two images do
not visibly differ, the visual requirement is not proved even if numeric
readback is correct; report the visual gap rather than calling the rig done.

## Common operations

```lua
local cr = assert(open_asset("/Game/Rigs/CR_NeoProof"))

-- Reposition an existing hierarchy element's initial global transform.
assert(cr:configure("bone", "NS_ProofTip", {
  transform = {location={x=25, y=0, z=180}},
}))

-- Reparent or rename by hierarchy name.
assert(cr:reparent("NS_ProofControl", "NS_ProofSpace"))
assert(cr:rename("NS_ProofTip", "NS_ProofEnd"))

-- Variables are Control Rig member variables, not hierarchy elements.
assert(cr:add("variable", {
  name="Reach",
  type="float",
  default_value="100.0",
}))
assert(cr:configure("variable", "Reach", {value="175.0"}))

-- Inspect persisted variable defaults and hierarchy totals.
for _, variable in ipairs(cr:list("variables")) do
  print(variable.name, variable.type, variable.default_value)
end
local summary = cr:info()

assert(cr:save())
```

## Failure modes

| Symptom | Cause and fix |
|---|---|
| New “Control Rig” opens as a plain Blueprint or has no hierarchy | UE 5.8 legacy factory creation is unavailable. Duplicate a genuine Control Rig asset. |
| Duplicated fixture says “Switch to Standalone Rig” | Call `make_standalone()` before adding hierarchy elements. Conversion resets module-authored hierarchy state, then may reimport preview-skeleton bones and sockets. |
| First post-save asset capture is missing the control or uses a default color | Reopen and call `cr:sync_preview()` in its own `execute_script`; capture in the following call. This creates or updates the debug host and gives the editor one call boundary to attach it. |
| Control shape appears with UE's gray checkerboard/default material | Keep `wait_for_ready_ms` at 1500 or higher. The screenshot tool's 1500 ms default warms shader and material state; do not override it with a shorter wait for proof captures. |
| Shape setting reads back but nothing renders | Discover with `list("shape_names")` and use a returned renderable name. Invalid names are rejected atomically. Save to synchronize the authoring hierarchy and pose into the preview instance. |
| `duplicate_asset` result is truthy but duplication failed | The result is always a table. Require `result.success == true` and read `result.error`. |
| `read_graph` fails for a guessed graph | Graph names are asset-specific. Use `cr:list("graphs")`, then pass one returned string. |
| Child add returns `nil` | Its `parent` does not exist yet or the name is wrong. Add parent-first and verify with `list`. |
| Configure says `[OK]` but assumed fields seem absent | `list("controls")` exposes `control_type`, `anim_type`, display/shape settings, exact shape color, and initial-local shape transform. Verify those rows and control values through their documented read paths. |
| Invalid enum plus another setting appears not to apply | Expected atomic rejection. Fix `control_type` or `anim_type`; the binding cancels the update. |
| Animation channel add fails | `parent_control` must name an existing element of type Control. |
| Transform value reads zeros | Use `tx`/`ty`/`tz` for `EulerTransform`, `Transform`, and `TransformNoScale`; `x`/`y`/`z` are for vector-like controls. |
| `TransformNoScale` rejects the value | Remove scale fields; that engine value type has no scale storage. |
| `pcall` reports success after `[FAIL]` | Binding failures return `nil` instead of raising. Check the call's return value. |
| Hierarchy and values pass but screenshots look identical | Numeric proof is not visual proof. Ensure the control is visible, capture distinct poses in separate calls, and inspect both images. |
| Later call cannot use `cr` | Lua locals do not survive calls. Reopen the asset each time. |

## Discovery escape hatches

- `cr:help()` — Control Rig hierarchy, settings, values, selection, metadata,
  and channel methods; print its returned string.
- `cr:list("graphs")` — real editor graph names accepted by `read_graph`.
- `cr:list("shape_names")` — renderable control shapes for this asset.
- `cr:list("controls")`, `cr:list("bones")`, `cr:list("nulls")`, and
  `cr:list("all")` — hierarchy readback.
- `cr:list("variables")` — member-variable type and default readback.
- `cr:info()` — hierarchy and member-variable counts.
- `cr:sync_preview()` — create or refresh the current asset-editor debug
  instance; call it one `execute_script` before visual capture.
- `read_graph(cr.path, graph_name)` — structural graph inspection after graph
  discovery.
- `report_issue("...")` — only after a reproducible Control Rig API gap remains.
