---
name: neostack-niagara
description: How to author Niagara VFX systems through `execute_script`. Use when the user asks to create a Niagara system, add or modify emitters, set module parameters, build curve-driven scale/color, configure renderers, or expose user parameters. Niagara is enrichment-only — the methods live on the table returned by `open_asset`.
---

# Niagara

The `Niagara` domain doesn't have global functions. Everything goes through methods on the asset table:

```lua
local ns = open_asset("/Game/NS_Foo")     -- existing system
local ns = create_asset("/Game/NS_Foo", "/Script/Niagara.NiagaraSystem")   -- NEW: see below
```

Use `ns:help()` for the full method list, `ns:info()` for a structured summary.

## Creating a system

There is currently no `niagara` alias in `list_asset_types()`. Pass the full class path:

```lua
local ns = create_asset("/Game/NS_Foo", "/Script/Niagara.NiagaraSystem")
```

A blank system has no emitters. Templates supply complete pre-wired emitters.

### Complete template-based fountain

This sequence was verified against the UE 5.8 Fountain emitter. Static-switch
selectors and their gated values use two calls: set the selector, then set the
newly active input. The binding rejects inactive inputs instead of creating an
orphan rapid-iteration value that compiles but has no visual effect.

```lua
local path = "/Game/VFX/NS_CyanFountain"
local ns = create_asset(path, "/Script/Niagara.NiagaraSystem")
assert(ns)

assert(ns:add("emitter", {
  name = "CyanFountain",
  template_asset = "/Niagara/DefaultAssets/Templates/Emitters/Fountain.Fountain",
}))

assert(ns:configure("module", "SpawnRate", {
  emitter = "CyanFountain",
  stage = "EmitterUpdate",
  parameters = { SpawnRate = 24.0 },
}))

assert(ns:configure("module", "ScaleColor", {
  emitter = "CyanFountain",
  stage = "ParticleUpdate",
  parameters = {
    ["Scale Mode"] = "RGBA Together",
  },
}))
assert(ns:configure("module", "ScaleColor", {
  emitter = "CyanFountain",
  stage = "ParticleUpdate",
  parameters = {
    ["Scale RGBA"] = { x = 0.05, y = 1.25, z = 4.0, w = 1.0 },
  },
}))

local result = ns:compile()
assert(result and result.success)
assert(ns:save())
```

Verify the emitter, module stages, renderer, mode, and rapid-iteration value in
a fresh call. Do not infer template contents:

```lua
local ns = open_asset("/Game/VFX/NS_CyanFountain")
local info = ns:info()
assert(info and info.emitter_count == 1)

local renderers = ns:list("renderers", { emitter = "CyanFountain" })
assert(renderers and #renderers == 1 and renderers[1].type == "Sprite")

local rate = ns:get("module", {
  emitter = "CyanFountain",
  stage = "EmitterUpdate",
  module_name = "SpawnRate",
}, "SpawnRate")
assert(rate and rate.value == 24.0 and rate.value_mode == "rapid_iteration")

local mode = ns:get("module", {
  emitter = "CyanFountain",
  stage = "ParticleUpdate",
  module_name = "ScaleColor",
}, "Scale Mode")
assert(mode and mode.value == "RGBA Together")
```

### Complete non-template cube-ring effect

Use this when visual proof must distinguish authored output from a template.
This verified UE 5.8 recipe starts from `Minimal`, adds its own spawn, shape,
velocity, solver, mesh, and material configuration, and removes the template's
Sprite renderer. The result is a sparse ring of rising emissive magenta cubes,
not a recolored Fountain.

Create an unlit particle-color material first:

```lua
local material_path = "/Game/VFX/M_CustomNiagaraCube"
local mat = create_asset(material_path, "Material")
assert(mat)
assert(mat:set("ShadingModel", "MSM_Unlit"))
assert(mat:set("TwoSided", true))
assert(mat:set("bUsedWithNiagaraMeshParticles", true))

local color = add_node(
  material_path, "MaterialGraph", "ParticleColor", -400, 0
)
assert(color)

local graph = read_graph(material_path, "MaterialGraph")
local root
for _, node in ipairs(graph.nodes or {}) do
  if node.type == "MaterialGraphNode_Root" then
    root = node
    break
  end
end
assert(root)
assert(connect(color.handle, "RGB", root.handle, "Emissive Color"))
assert(mat:save())
```

Create the system:

```lua
local system_path = "/Game/VFX/NS_CustomCubeRing"
local ns = create_asset(
  system_path,
  "/Script/Niagara.NiagaraSystem"
)
assert(ns)

assert(ns:add("emitter", {
  name = "CustomCubes",
  template_asset =
    "/Niagara/DefaultAssets/Templates/Emitters/Minimal.Minimal",
}))

assert(ns:add("module", {
  emitter = "CustomCubes",
  stage = "EmitterUpdate",
  module_path = "/Niagara/Modules/Emitter/SpawnRate.SpawnRate",
}))
assert(ns:configure("module", "SpawnRate", {
  emitter = "CustomCubes",
  stage = "EmitterUpdate",
  parameters = { SpawnRate = 3.0 },
}))

assert(ns:configure("module", "InitializeParticle", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  parameters = { Lifetime = 5.0 },
}))
assert(ns:configure("module", "InitializeParticle", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  parameters = {
    ["Color Mode"] = "Direct Set",
  },
}))
assert(ns:configure("module", "InitializeParticle", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  parameters = {
    Color = { r = 6.0, g = 0.02, b = 3.0, a = 1.0 },
  },
}))
assert(ns:configure("module", "InitializeParticle", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  parameters = {
    ["Mesh Scale Mode"] = "Non-Uniform",
  },
}))

-- Fresh discovery must expose this active default-backed input before it has
-- an authored RI value.
local scale_inputs = assert(ns:list("module_inputs", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  module_name = "InitializeParticle",
}))
local scale_input
for _, input in ipairs(scale_inputs) do
  if input.name == "Mesh Scale" then scale_input = input end
end
assert(scale_input and scale_input.active == true)

assert(ns:configure("module", "InitializeParticle", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  parameters = {
    ["Mesh Scale"] = { x = 0.10, y = 0.55, z = 0.18 },
  },
}))

assert(ns:add("module", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  module_path =
    "/Niagara/Modules/Spawn/Location/V2/ShapeLocation.ShapeLocation",
}))
assert(ns:configure("module", "ShapeLocation", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  parameters = { ["Shape Primitive"] = "Ring / Disc" },
}))
assert(ns:configure("module", "ShapeLocation", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  parameters = { ["Ring Radius"] = 350.0 },
}))

assert(ns:add("module", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  module_path =
    "/Niagara/Modules/Spawn/Velocity/AddVelocity.AddVelocity",
}))
assert(ns:configure("module", "AddVelocity", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  parameters = {
    Velocity = { x = 70.0, y = 25.0, z = 95.0 },
  },
}))

assert(ns:add("module", {
  emitter = "CustomCubes",
  stage = "ParticleUpdate",
  module_path =
    "/Niagara/Modules/Solvers/SolveForcesAndVelocity.SolveForcesAndVelocity",
}))
```

Configure the renderer through its real UE 5.8 struct fields. `Mesh` is not a
flat renderer property. `Meshes` is an array of mesh-entry structs, and
`OverrideMaterials` is an array of `FNiagaraMeshMaterialOverride` structs:

```lua
-- Minimal begins with one Sprite renderer. Add a COMPLETE Mesh renderer as
-- index 1. A bare Mesh renderer is rejected and rolled back because UE skips
-- null mesh entries at runtime even though Niagara compilation remains clean.
assert(ns:add("renderer", {
  emitter = "CustomCubes",
  type = "Mesh",
  properties = {
    Meshes = {{
      Mesh = "/Engine/BasicShapes/Cube.Cube",
    }},
  },
}))

assert(ns:remove("renderer", {
  emitter = "CustomCubes",
  index = 0,
}))

-- Mesh is now index 0.
assert(ns:configure("renderer", {
  emitter = "CustomCubes",
  index = 0,
}, {
  properties = {
    bOverrideMaterials = true,
    OverrideMaterials = {{
      ExplicitMat = "/Game/VFX/M_CustomNiagaraCube.M_CustomNiagaraCube",
    }},
  },
}))

local compiled = ns:compile()
assert(compiled and compiled.success)
assert(ns:save())
```

Read the modules, selector values, vector/color values, sole Mesh renderer,
`Meshes[1].Mesh`, `bOverrideMaterials == true`, and
`OverrideMaterials[1].ExplicitMat` again in a fresh script. Require exactly one
renderer and require it to be Mesh; leaving the Minimal template Sprite in
place can make an incomplete custom renderer look successful. Do not accept
only the renderer type or compile result.

### Invalid settings fail closed

Module parameter batches preflight input names and literal enum/bool/struct
values. Renderer property batches validate a duplicate first. A bad field
returns `false` or `nil` without changing a valid companion value or leaving a
default renderer behind:

```lua
assert(ns:configure("module", "InitializeParticle", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  parameters = { ["Mesh Scale Mode"] = "Uniform" },
}))
assert(ns:configure("module", "InitializeParticle", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  parameters = { ["Mesh Uniform Scale"] = 0.30 },
}))

local ok = ns:configure("module", "InitializeParticle", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  parameters = {
    -- Hidden while Mesh Scale Mode is Uniform. Using this vector used to
    -- report success but leave the visible mesh at its template scale.
    ["Mesh Scale"] = { x = 0.7, y = 0.7, z = 0.7 },
  },
})
assert(ok == false)

local scale = ns:get("module", {
  emitter = "CustomCubes",
  stage = "ParticleSpawn",
  module_name = "InitializeParticle",
}, "Mesh Uniform Scale")
assert(scale and math.abs(scale.value - 0.30) < 0.001)

local added = ns:add("renderer", {
  emitter = "CustomCubes",
  type = "Mesh",
  properties = {
    Mesh = "/Engine/BasicShapes/Cube.Cube", -- wrong flat field
  },
})
assert(added == nil)

-- Also rejected atomically: the engine ignores OverrideMaterials unless its
-- separate gate is enabled.
local bad_override = ns:configure("renderer", {
  emitter = "CustomCubes",
  index = 0,
}, {
  properties = {
    OverrideMaterials = {{
      ExplicitMat = "/Game/VFX/M_CustomNiagaraCube.M_CustomNiagaraCube",
    }},
  },
})
assert(bad_override == nil)
```

Stop on either result and fix the request. Never continue because one field in
the same batch looked valid.

## The element types

`add` / `remove` / `list` / `configure` / `get` operate on these element types:

| Type                  | What it is                                              |
|-----------------------|---------------------------------------------------------|
| `emitter`             | Standard (graph-based) emitter                          |
| `stateless_emitter`   | Stateless (lightweight) emitter                         |
| `module`              | A module function call inside a stage                   |
| `assignment_module`   | A "Set Variable" assignment with target attributes      |
| `stateless_module`    | A module on a stateless emitter                         |
| `renderer`            | Sprite / mesh / ribbon / light / etc.                   |
| `user_parameter`      | A user-exposed parameter on the system                  |
| `event_handler`       | An event handler on an emitter                          |
| `simulation_stage`    | A simulation stage on an emitter                        |
| `spawn_info`          | Spawn info entry on a stateless emitter                 |

## Adding emitters from templates

```lua
local templates = ns:list("emitter_templates")
-- common entries: Fountain, ConfettiBurst, DirectionalBurst, OmnidirectionalBurst,
--                 SimpleSpriteBurst, UpwardMeshBurst, …

ns:add("emitter", {
  name = "MyFountain",
  template_asset = "/Niagara/DefaultAssets/Templates/Emitters/Fountain.Fountain",
})
```

`name` and `template_asset` are both required. `template_asset` must be the **full asset path** (not the friendly name). Empty emitters cannot be created — the engine requires a template.

## Stage names

Modules live inside a stage of an emitter (or directly on the system):

- `SystemSpawn`, `SystemUpdate` — system-level
- `EmitterSpawn`, `EmitterUpdate` — emitter-level (one-shot at emitter init / per-frame at emitter level)
- `ParticleSpawn`, `ParticleUpdate` — per-particle

A stage name is required for `list("modules")`, `configure("module")`, `get("module")`, etc.

## Listing modules and their inputs

```lua
ns:list("modules", {emitter="MyFountain", stage="ParticleSpawn"})
-- → [{name="InitializeParticle", index=0, enabled=true, script="/Niagara/.../InitializeParticle"}, ...]

ns:list("module_inputs", {emitter="MyFountain", stage="EmitterUpdate", module_name="SpawnRate"})
-- → [{name="SpawnRate", value=90.0, value_mode="rapid_iteration", type="NiagaraFloat", full_name="Constants.MyFountain.SpawnRate.SpawnRate"}, ...]
```

Note: the key is `module_name`, **not** `module`. Unrecognised keys produce a `[WARN] key 'X' was not consumed` line — useful for catching typos.

`value_mode` tells you where the value lives:

- `default` — a real default-backed stack input with no authored RI override
  yet. Check `active`; set selector inputs first, then discover again.
- `rapid_iteration` — in the script's RI param store, can be set as a literal
- `pin` — a static-switch / override-pin input (set with `{value="..."}`)
- `dynamic_input`, `linked`, `data_interface`, `curve` — graph-structural; set via `{mode="…"}`

Every entry also reports `active`. A valid default-backed input remains visible
while inactive, but `configure("module")` rejects writing it until the selector
makes it active. `authored=false` means discovery is describing the resolved UE
stack input rather than claiming a stored RI value exists. A specific
`get("module", ..., input)` returns the same `default`/`active` metadata before
the first write and the authored RI value afterward.

## Setting module input values

### Literal values (rapid iteration)

```lua
ns:configure("module", "SpawnRate", {
  emitter = "MyFountain",
  stage = "EmitterUpdate",
  parameters = {
    SpawnRate = 200.0,
    ["Spawn Probability"] = 0.5,
    SpawnGroup = 5,
  },
})
```

Keys are the **input names as shown by `list("module_inputs")`** (short form, with spaces if any — quote them). Returns `true` and `[OK] configure -> N set`.

### Advanced modes

For non-literal values, pass a table with `mode`:

```lua
parameters = {
  -- Bind to a parameter
  Position    = {mode="linked", parameter="Particles.Position"},
  -- Embed HLSL — see "HLSL syntax" below; this is an EXPRESSION, no `return`.
  Speed       = {mode="hlsl", code="1.0 + sin(EngineTime)"},
  -- Replace with a dynamic input script
  Velocity    = {mode="dynamic_input", script="/Niagara/DynamicInputs/Velocity/Add.Add"},
  -- Curves: NiagaraDataInterface{Curve, ColorCurve, Vector2DCurve, VectorCurve, Vector4Curve}
  Alpha       = {mode="curve", keys={{time=0, value=1, interp="linear"}, {time=1, value=0}}},
  Color       = {mode="color_curve", keys={
                  {time=0, color={r=1,g=1,b=1,a=1}},
                  {time=1, color={r=1,g=0,b=0,a=0}}}},
  -- Reset to default (clears any override / RI override)
  WhateverInput = {mode="reset"},
}
```

Curve key interp options: `linear`, `cubic`, `constant`.

#### HLSL syntax — expression, not statement

`mode="hlsl"` takes an **expression**, not a function body. The engine wraps your code
as `Out_X = (Type)(YOUR_CODE);` (`NiagaraHlslTranslator.cpp:8920`), so a `return` keyword
ends up inside parentheses and the VM compiler fails with "unexpected RETURN".

```lua
-- ✓ Right — particle-side expression (Particles.NormalizedAge is in scope per-particle)
Color = {mode="hlsl", code="lerp(float3(1,1,1), float3(1,0,0), Particles.NormalizedAge)"}
-- ✗ Wrong — produces "unexpected RETURN"
Speed = {mode="hlsl", code="return 1.0 + sin(0.5);"}
```

If you write a `return`-prefixed snippet, the binding logs a `[WARN]` immediately so the
mistake is visible before you hit the engine's confusing error.

**HLSL variable scope is restricted.** A custom expression can only reference variables
that have been *encountered earlier* in the compiled script — not arbitrary engine
globals. Common references that DO work:

- Particle-side: `Particles.NormalizedAge`, `Particles.Lifetime`, `Particles.Velocity.x` (any attribute already on the particle)
- System-side: only attributes already written by an earlier module in the stack

`EngineTime` and `Engine.Owner.SystemAge` will fail with `Cannot use variable in custom
expression, it hasn't been encountered yet`. For time-driven math, drive a User
parameter from blueprint code (`set_user_parameter` at runtime) and reference
`User.YourParam` from the HLSL.

For multi-statement logic or things that need engine globals, write a scratch-pad script
instead — `mode="hlsl"` is for one-liners that touch already-in-scope attributes.

### Static switch / non-RI inputs

For boolean static-switch pins:

```lua
parameters = { ["Use Spawn Probability"] = {value="true"} }
```

For **enum**-typed static-switch pins (every `*_Mode` input on `InitializeParticle`,
`UpdateMeshOrientation.Orientation Method`, `EmitterState.LoopBehavior`, etc.), pass the
authored enum name as a plain string — no wrapper needed:

```lua
parameters = {
  ["Lifetime Mode"]      = "Direct Set",         -- ENiagara_LifetimeMode
  ["Color Mode"]         = "Random Range Linear",-- ENiagara_ColorInitializationMode
  ["Orientation Method"] = "Rotation Rate",      -- ENiagara_UpdateMeshOrientationMode
}
```

The binding resolves the enum name through `NeoLuaEnum::ParseRuntime` against the pin's
`UEnum`, so authored names, `EWhatever::ValueName` form, and display-name aliases all
work. If the name doesn't match anything, the error message lists the valid options.

Make the selector call first, then inspect `list("module_inputs", ...)` or the
module schema and set the active value in a second call. In UE 5.8, for example,
`Mesh Scale Mode = "Uniform"` activates scalar `Mesh Uniform Scale`; vector
`Mesh Scale` is inactive and is rejected. Never infer a gated input name from
the mode label.

Round-trip is symmetric: `get` returns the enum's authored name as a string. To force the
underlying int (rare), pass `{value=N}` as before.

## Reading values back

```lua
local v = ns:get("module", {emitter="MyFountain", stage="EmitterUpdate", module_name="SpawnRate"}, "SpawnRate")
-- v = {name="SpawnRate", type="NiagaraFloat", value=200.0, value_mode="rapid_iteration", full_name="…"}
```

Or get the whole module:

```lua
ns:get("module", {emitter="MyFountain", stage="EmitterUpdate", module_name="SpawnRate"})
-- → {enabled=true, name="SpawnRate", inputs=[{name=…, value=…, …}, …]}
```

## Module lifecycle

```lua
ns:enable_module({emitter="MyFountain", stage="EmitterUpdate", module_name="SpawnRate", enabled=false})
ns:move_module({emitter="MyFountain", stage="EmitterUpdate", module_name="SpawnRate", new_index=0})
```

## Emitter properties

```lua
ns:configure("emitter", "MyFountain", {
  enabled = true,
  properties = {
    SimTarget         = "GPUComputeSim",   -- or "CPUSim"
    bLocalSpace       = true,
    bDeterminism      = true,
    CalculateBoundsMode = "Fixed",
    FixedBounds       = {min={x=-100,y=-100,z=-100}, max={x=100,y=100,z=100}},
  },
})
```

Field names resolve case-insensitively with snake_case + b-prefix variants — `fixed_bounds` → `FixedBounds`, `local_space` → `bLocalSpace`. Enum values use the authored names exactly: `SortMode="ViewDepth"`, `SimTarget="GPUComputeSim"`.

Other configurable scopes: `system`, `simulation_stage`, `event_handler`, `stateless_emitter`, `stateless_module`, `spawn_info`, `renderer`.

## User parameters

```lua
ns:add("user_parameter", {name="MySpeed", type="Float", default=1.0})
ns:set_user_parameter({name="MySpeed", value=2.5})
ns:get("user_parameter", "MySpeed")    -- → 2.5
ns:rename_user_parameter({old_name="MySpeed", new_name="Speed"})  -- propagates through scripts
```

Supported types: `Float`, `Int`, `Bool`, `Vector`, `Vector2`, `Vector4`, `Color`, `Quat`, `Position`, `Matrix`, plus data interfaces.

## Renderers

```lua
ns:list("renderer_types")              -- discoverable (Sprite, Mesh, Ribbon, Light, …)
ns:add("renderer", {emitter="MyFountain", type="Mesh"})
ns:configure("renderer", {emitter="MyFountain", index=1}, {
  properties={
    Meshes={{Mesh="/Engine/BasicShapes/Cube.Cube"}},
  },
})
ns:configure("renderer", {emitter="MyFountain", index=0}, {properties={SortMode="ViewDepth"}})
```

## Persistence

```lua
ns:compile()    -- returns {success, errors, warnings}
ns:save()       -- returns true
```

Niagara has its own compile pipeline (separate from `FLuaGraphFinalizer`). The plugin auto-recompiles when needed (e.g. when RI is baked out and you change a literal). You usually don't need to call `compile()` manually unless you want to *check* for errors with `validate()` / `run_validation()` first.

## Verification gotcha

In-script reads after a mutation may show stale data because the parameter store update isn't fully published until the script ends. **Verify in a fresh script** (a separate `execute_script` call):

```lua
-- Script 1: mutate
ns:configure("module", "SpawnRate", {emitter="F", stage="EmitterUpdate", parameters={SpawnRate=200}})

-- Script 2: verify (fresh execute_script)
local inputs = ns:list("module_inputs", {emitter="F", stage="EmitterUpdate", module_name="SpawnRate"})
```

### Visual verification requires editor time between calls

Niagara can compile cleanly while rendering nothing. Always inspect at least two
returned images and check gross emission, color, scale, and count.

Opening a system and waiting inside the same `execute_script` call is not a
simulation warmup: the call occupies the editor thread. Likewise,
`wait_for_ready_ms` prepares capture but does not advance Niagara. Use separate
calls so the editor can tick between them:

```lua
-- Call 1: open the editor preview, then end the call.
open_asset("/Game/VFX/NS_CyanFountain")
```

```lua
-- Call 2, after editor time has elapsed: inspect the returned image.
screenshot({
  mode = "asset",
  asset = "/Game/VFX/NS_CyanFountain",
  max_dimension = 1600,
  wait_for_ready_ms = 100,
})
```

```lua
-- Call 3, after more editor time: inspect this image too.
screenshot({
  mode = "asset",
  asset = "/Game/VFX/NS_CyanFountain",
  max_dimension = 1600,
  wait_for_ready_ms = 100,
})
```

Reject the result if both frames are empty, identical when motion is expected,
or show the wrong gross color/scale/count. An empty first frame is not proof of
failure; t=0 and loop-reset frames can legitimately contain no particles.

### Deterministic level-hosted proof

The Niagara asset preview can return its background with zero particles even
for an untouched engine template. When that happens, do not diagnose the
system from the empty preview. Host the system in a native Niagara actor and
advance the component synchronously before each level capture:

```lua
create_level("/Game/VFX/L_CustomCubeProof", {
  template = "basic",
  open = true,
})

local level = open_level()
assert(level:add("actor", {
  class = "/Script/Niagara.NiagaraActor",
  location = { x = 0, y = 0, z = 150 },
  label = "CustomNiagaraActor",
}))
assert(configure_component(
  "CustomNiagaraActor",
  "NiagaraComponent0",
  {
    property = {
      Asset = "/Game/VFX/NS_CustomCubeRing",
    },
  }
))
assert(level:save())
```

Capture two frames in separate calls. Reloading before each call makes the
tick count deterministic:

```lua
assert(load_level("/Game/VFX/L_CustomCubeProof"))
local component = {
  actor_label = "CustomNiagaraActor",
  component = "NiagaraComponent0",
}
assert(invoke(component, "Activate", { true }))
assert(invoke(component, "AdvanceSimulation", { 45, 0.0333333 }))

screenshot({
  mode = "level",
  max_dimension = 1600,
  wait_for_ready_ms = 150,
  hide_overlays = true,
  location = { x = -1000, y = 0, z = 250 },
  rotation = { pitch = -5, yaw = 0, roll = 0 },
  fov = 70,
  view_mode = "lit",
})
```

Repeat with `AdvanceSimulation({90, 0.0333333})`. The two returned images must
show cube meshes, the authored magenta color, the expected sparse count, and
different positions/counts. A default Fountain sprite, empty background, or
unchanged pair fails the gate.

## Discovery escape hatches

- `ns:help()` — every method on the system object
- `ns:info()` — emitter/module/renderer/user-param counts
- `ns:list("emitters" | "modules" | "renderers" | "user_parameters" | "event_handlers" | "simulation_stages" | "module_inputs" | "dynamic_inputs" | "scratch_pad_scripts" | "available_modules" | "emitter_templates" | "stateless_modules" | "spawn_infos")`
- `ns:list("renderer_types")` — discover what `add("renderer", {type=…})` accepts
- `ns:list("parameter_definitions")` — system-bound parameter definitions
- `ns:validate()` / `ns:run_validation()` — engine validation report
- `report_issue("…")` — last-resort escape when something's truly missing

## Versioning (advanced)

Niagara emitters can be versioned (multiple variants of the same template):

```lua
ns:version("list",   {emitter="MyFountain"})
ns:version("add",    {emitter="MyFountain", major=2, minor=0})
ns:version("expose", {emitter="MyFountain", major=2, minor=0})
ns:version("delete", {emitter="MyFountain", version_guid="…"})
```

## Scratch-pad scripts

Per-system Niagara scripts you can author and reference from modules. Scratch-pad
scripts use **dedicated methods**, not the generic `add()` dispatcher — `add("scratch_pad_script", ...)` will fail with `unknown type`.

```lua
ns:list("scratch_pad_scripts")
ns:create_scratch_pad_script({name="MyDI", type="DynamicInput"})  -- type=, NOT usage=
ns:rename_scratch_pad_script({old_name="MyDI", new_name="VelocityDI"})
ns:delete_scratch_pad_script({name="VelocityDI"})
```

Valid `type=` values: `Module`, `DynamicInput`, `Function` (case-insensitive). Default is `Module`.

To use a scratch-pad script as a module input, target it with `{scratch_pad="<name>"}` instead of `{emitter, stage}`.
