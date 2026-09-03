---
name: neostack-material
description: Create, edit, instance, compile, and visually verify Unreal materials through `execute_script`. Use when the user asks for a Material or Material Instance, a shader graph, exposed scalar/vector/texture parameters, emissive or surface shading, or a material preview. Covers the generic asset/graph workflow, source-versus-preview ordering, node property discovery, instance overrides, and render verification.
---

# Editing materials

Use `execute_script` for every operation. Each call gets a fresh Lua state, so
re-`open_asset(path)` at the start of later calls.

Materials do not add a separate `mat:*` graph API. Combine:

- `create_asset` / `open_asset` for material properties and saving
- `add_node`, `set_node_property`, `connect`, and `read_graph` for the graph
- `read_log("compile", ...)` for diagnostics
- `screenshot` for the result that actually renders

## The material workflow

1. Create or open the Material.
2. Set source UProperties such as `ShadingModel`, `BlendMode`, and `TwoSided`.
3. Add graph expressions and configure their editable properties.
4. Read the graph to find the root and real pin names.
5. Connect the graph.
6. Call `mat:save()` to copy the editor preview graph back to the source asset.
7. Verify in a fresh call with `read_graph`, `read_log`, and `screenshot`.

### Keep animated color layers visually separable

When a design needs a persistent dark base, moving bright bands, and a second
color pulse, do not add both bright colors across the whole surface. Build one
bounded band mask, apply the primary color through that mask, and apply the
secondary pulse through a complementary mask such as `OneMinus(band_mask)`.
Add both contributions over the dark base with independently tunable
intensities. This keeps the base readable and prevents the two emissive layers
from washing into white.

Choose the motion and pulse periods before capturing evidence. Capture from one
fixed camera at deliberately separated phases rather than taking repeated
screenshots at arbitrary delays; a delay can alias back to the same phase even
when the graph is animated. Record both timestamps and hashes, then inspect both
images for a visible pattern or color change.

### Set source properties before graph edits

Set source-side properties before the first `add_node`:

```lua
local path = "/Game/Materials/M_Glow"
local mat = create_asset(path, "Material")
mat:set("ShadingModel", "MSM_Unlit")
mat:set("TwoSided", true)
```

Opening the Material editor creates a transient preview material. Graph operations
target that preview, while `mat:set(...)` targets the source asset. A later
`mat:save()` copies preview to source. If you set `ShadingModel` or `BlendMode` after
graph editing begins, that preview-to-source copy can replace the late source write.

## End-to-end: parameterized emissive material

This is a complete runnable construction:

```lua
local path = "/Game/Materials/M_Glow"
local mat = create_asset(path, "Material")
if not mat then return "create failed" end

-- Source property first.
if not mat:set("ShadingModel", "MSM_Unlit") then
  return "could not set ShadingModel"
end

-- Material expression class names have no spaces.
local color = add_node(path, "MaterialGraph", "VectorParameter", -650, -80)
local strength = add_node(path, "MaterialGraph", "ScalarParameter", -650, 180)
local multiply = add_node(path, "MaterialGraph", "Multiply", -300, 20)
if not color or not strength or not multiply then return "node creation failed" end

set_node_property(color.handle, "ParameterName", "GlowColor")
set_node_property(color.handle, "DefaultValue", "(R=1,G=0.02,B=0,A=1)")
set_node_property(strength.handle, "ParameterName", "GlowStrength")
set_node_property(strength.handle, "DefaultValue", 3.0)

-- Find the real root instead of assuming a handle.
local graph = read_graph(path, "MaterialGraph")
local root
for _, node in ipairs(graph.nodes or {}) do
  if node.type == "MaterialGraphNode_Root" then root = node; break end
end
if not root then return "material root not found" end

if not connect(color.handle, "RGB", multiply.handle, "A") then return "color wire failed" end
if not connect(strength.handle, "Output", multiply.handle, "B") then return "strength wire failed" end
if not connect(multiply.handle, "Output", root.handle, "Emissive Color") then
  return "root wire failed"
end

mat:save()
return path
```

The working pins are:

| Expression | Inputs | Outputs |
|---|---|---|
| `VectorParameter` | — | `RGB`, `R`, `G`, `B`, `A`, `RGBA` |
| `ScalarParameter` | — | `Output` |
| `Multiply` | `A`, `B` | `Output` |
| Material root | material channels | — |

Use the whole display pin name on the root: `Emissive Color`, `Base Color`,
`Roughness`, `Metallic`, `Normal`, and so on.

`"Vector Parameter"` does not resolve; the schema expression name is
`"VectorParameter"`. Failed calls return `nil` and log `[FAIL]`.

## Discover node properties before guessing

`set_node_property` writes editable properties on the underlying
`UMaterialExpression`, not graph pins:

```lua
local node = add_node(path, "MaterialGraph", "TextureSampleParameter2D", -500, 0)
local props = list_node_properties(node.handle)
for _, prop in ipairs(props or {}) do
  log(tostring(prop.name) .. " = " .. tostring(prop.value))
end
```

Then set only fields the list exposes:

```lua
set_node_property(node.handle, "ParameterName", "BaseTexture")
```

An unknown property returns `nil` and the failure lists the editable fields. Treat
that output as discovery; do not substitute a similar-looking UProperty name.

Some material expressions expose literal inputs as graph pins instead of editable
properties. Read `pins_in` / `pins_out` from `read_graph` before choosing between
`set_pin` and `set_node_property`.

## Material Instances

Create the base graph first, save it, then create the instance with the exact
`ParentMaterial` option:

```lua
local mi = create_asset(
  "/Game/Materials/MI_Glow_Blue",
  "MaterialInstanceConstant",
  {ParentMaterial="/Game/Materials/M_Glow"}
)
```

Discover the inherited parameter surface before writing overrides:

```lua
local mi = open_asset("/Game/Materials/MI_Glow_Blue")
local names = mi:list("parameter_names")

for _, name in ipairs(names.scalars or {}) do log("scalar " .. tostring(name)) end
for _, name in ipairs(names.vectors or {}) do log("vector " .. tostring(name)) end
```

Configure parameters by type:

```lua
mi:configure("vector", {
  name="GlowColor",
  r=0, g=0.05, b=1, a=1,
})
mi:configure("scalar", {
  name="GlowStrength",
  value=1.5,
})
mi:save()
```

The binding validates inherited parameters. A misspelled or nonexistent name returns
`nil` and does not create an orphan override.

Verify overrides in a fresh call:

```lua
local mi = open_asset("/Game/Materials/MI_Glow_Blue")
for _, parameter in ipairs(mi:list("parameters") or {}) do
  log(tostring(parameter.name) .. "=" .. tostring(parameter.value))
end
```

Use `mi:help()` for texture, static-switch, base-property, layer, and other
Material Instance operations. Do not copy every available `configure` type into a
task script—discover the exact inherited parameter first.

## Verification is three separate checks

### 1. Read the persisted topology

Use a fresh `execute_script` call:

```lua
local graph = read_graph("/Game/Materials/M_Glow", "MaterialGraph")
log("nodes=" .. tostring(#(graph.nodes or {})))
log("connections=" .. tostring(graph.connection_count or 0))
```

Inspect `graph.connections`, or each node's `connections_in` /
`connections_out`, when the exact source-to-destination wire matters.

### 2. Compile and read diagnostics

```lua
local result = read_log("compile", {asset="/Game/Materials/M_Glow"})
log("status=" .. tostring(result.status))
log("errors=" .. tostring(result.error_count or 0))
for _, entry in ipairs(result.entries or {}) do
  log(tostring(entry.message or entry.text or entry))
end
```

A clean compile proves shader validity, not that the intended expression reaches an
output.

### 3. Inspect the rendered preview

```lua
return screenshot({
  mode="asset",
  asset="/Game/Materials/M_Glow",
  max_dimension=1200,
})
```

Read the returned image. Check the gross requirement:

- Is the preview mesh visible?
- Is it the requested color?
- Is emissive output actually bright?
- Does a texture show non-flat variation?
- Is transparency/two-sided behavior visible from an appropriate view?

Never accept node counts or compile success as visual proof. A disconnected material
can compile cleanly and render black.

## Failure modes

| Symptom | Cause / fix |
|---|---|
| `add_node("Vector Parameter")` returns `nil` | Use the schema class name `VectorParameter` without spaces. |
| Two exact `TextureSampleParameter2D` matches are reported | The schema exposed two equivalent actions; the binding deterministically uses the first. Verify the returned node type and continue. |
| `set_node_property` says a field is missing | Call `list_node_properties(handle)` and use the returned editable name. |
| A node exists but the preview ignores it | It is not wired to the Material root, or it is wired to the wrong root input. Read graph connections. |
| A source property reverts after save | It was set after the preview editor opened. Recreate or set it before the first graph edit, then save. |
| An in-script read looks stale | Re-open/read in a fresh `execute_script` call. |
| Material Instance override returns `nil` | The name/type/association is not in `list("parameter_names")`; fix the request instead of forcing an orphan override. |
| Compile is clean but the preview is black/flat | Compile is not render proof. Inspect connections and the screenshot. |
| A graph change disappears after restart | `read_log("compile")` does not persist the preview graph. Call `mat:save()`. |

## Discovery escape hatches

- `help("CreateAsset")` — supported asset types and creation options.
- `help("AddNode")`, `help("SetNodeProperty")`, `help("Connect")`,
  `help("ReadGraph")` — generic graph operations.
- `mat:help()` — generic asset operations.
- `mi:help()` — Material Instance `list` / `configure` / `remove` operations.
- `list_node_properties(handle)` — editable expression properties and current values.
- `read_graph(path, "MaterialGraph")` — real nodes, pins, and connections.
- `report_issue("...")` — use only after a minimal live reproduction shows missing
  or incorrect behavior.

Do not wrap `help(...)` in `log(...)`; `help` already writes to the trace.
