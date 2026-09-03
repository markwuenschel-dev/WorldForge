---
name: neostack-animbp
description: Create and edit Unreal Engine Animation Blueprints through `execute_script`. Use when the user asks to create an AnimBlueprint for a skeleton, add or wire an animation state machine, author states or transitions, update animation variables in EventGraph, play sequences in state graphs, create an AnimLayerInterface, add animation layers, or compile and verify AnimBP graph topology.
---

# Animation Blueprints through `execute_script`

Use the enriched Blueprint handle returned by `create_asset` or `open_asset`.
AnimBP authoring lives on that handle; there is no separate AnimBP global.

```lua
local bp = open_asset("/Game/Characters/ABP_Hero")
if not bp then error("Animation Blueprint not found") end
print(bp:help())
```

Every `execute_script` call starts a fresh Lua state. Re-open the asset at the
start of each call. Graph and node handles are deterministic, but `find_nodes`
search-result IDs are session-local; re-run `find_nodes` before spawning from a
search result in a later call.

## Use this order

1. Create the AnimBlueprint with its real target skeleton.
2. Add variables.
3. Author EventGraph updates.
4. Create the state machine, states, entry link, and transitions.
5. Populate each state graph and wire the state machine to Output Pose.
6. Wire transition rules with caller-chosen thresholds.
7. Compile, save, and verify from a fresh call.

Do not infer success from the absence of a Lua exception. Mutating Blueprint
calls return nil and log `[FAIL]` when rejected; check every return.

## Create a standard AnimBlueprint

Supply `ParentClass="AnimInstance"` and a `TargetSkeleton` asset path:

```lua
local path = "/Game/Characters/ABP_Hero"
local skeleton_path = "/Game/Characters/Mannequin/SK_Mannequin_Skeleton"

if asset_exists(path) then error("Asset already exists: " .. path) end

local bp = create_asset(path, "AnimBlueprint", {
  ParentClass = "AnimInstance",
  TargetSkeleton = skeleton_path,
})
assert(bp, "AnimBlueprint creation failed")
```

Use the `USkeleton` asset path, not the SkeletalMesh path. If the target
skeleton is unknown, find the project asset first rather than guessing. A
template AnimBlueprint can be created with `bTemplate=true`, but use a real
`TargetSkeleton` for a normal character AnimBP.

The live reference `/Game/_SkillExplore_AnimBP/ABP_LocomotionProbe` verified
`AnimInstance` as the parent class.

## Add animation variables

Add the locomotion value before spawning getter and setter nodes:

```lua
local bp = open_asset("/Game/Characters/ABP_Hero")
assert(bp:add_variable("Speed", "float", {
  category = "Locomotion",
  default = 0.0,
}))
```

The live reference contains exactly one authored variable:
`Speed`, type `float`, category `Locomotion`.

`bp.variables` is a snapshot. Re-open the asset or call `bp:refresh()` before
using it as verification.

## Update Speed in EventGraph

The verified EventGraph topology is:

```text
Event BlueprintUpdateAnimation
    └─exec─> Set Speed

TryGetPawnOwner
    └─> GetVelocity
          └─> Vector Length XY
                 └─> Set Speed.Speed
```

The exact live node titles are:

- `Event BlueprintUpdateAnimation`
- `TryGetPawnOwner`
- `GetVelocity`
- `Vector Length XY`
- `Set Speed`

Search and spawn nodes in the AnimBP's `EventGraph`:

```lua
local path = "/Game/Characters/ABP_Hero"
local graph = "EventGraph"

local function spawn_exact(title, x, y)
  local hits = find_nodes(title, path, graph, 10)
  for _, hit in ipairs(hits or {}) do
    if hit.name == title then
      return add_node(path, graph, hit, x, y)
    end
  end
  error("Exact node not found: " .. title)
end

local update = spawn_exact("Event BlueprintUpdateAnimation", 0, 0)
local owner = spawn_exact("TryGetPawnOwner", 0, 220)
local velocity = spawn_exact("GetVelocity", 300, 220)
local length_xy = spawn_exact("Vector Length XY", 600, 220)
local set_speed = spawn_exact("Set Speed", 900, 0)

assert(update and owner and velocity and length_xy and set_speed)
```

Use the pin names returned in `pins_in` and `pins_out` to wire the verified
topology. Do not guess a pin when the node result already exposes it. The
generic event/function convention still applies: event exec-out is normally
`then`, and function exec-in is normally `execute`, but read the actual node
pins before connecting.

After wiring, verify in a fresh call:

```lua
local graph = read_graph("/Game/Characters/ABP_Hero", "EventGraph")
for _, node in ipairs(graph.nodes or {}) do
  print(node.name, node.handle)
end
```

## Create the locomotion state machine

Call `add_state_machine` with one argument. The implementation does not take a
graph parameter even though older help text showed `graph?`.

```lua
local bp = open_asset("/Game/Characters/ABP_Hero")

local sm = bp:add_state_machine("Locomotion")
assert(sm)

local idle = bp:add_state("Locomotion", "Idle")
local walk = bp:add_state("Locomotion", "Walk")
assert(idle and walk)

local entry = bp:add_transition("Locomotion", "Entry", "Idle")
assert(entry and entry.kind == "entry")

local idle_to_walk = bp:add_transition("Locomotion", "Idle", "Walk")
assert(idle_to_walk)
assert(idle_to_walk.result_handle ~= "none")
```

`Entry -> Idle` directly sets the initial state. It does not create a rule graph,
and its returned `result_handle` is `"none"`. A state-to-state transition creates
a rule graph and returns its `graph` selector and `result_handle`; carry those
returned values forward rather than reconstructing graph names.

The live `Locomotion` state-machine graph contained:

- `Locomotion` with `type="AnimStateEntryNode"` (the entry node's readback
  name is the state-machine name, not the literal string `Entry`)
- `Idle`
- `Walk`
- `Idle to Walk`

When verifying the entry link, select the node by
`type=="AnimStateEntryNode"` and inspect its output link. Continue to pass the
literal `"Entry"` only to `add_transition`; the authoring selector and the
readback node name intentionally differ.

## Populate Idle and Walk

Each verified state contains one `Sequence Player` wired into one
`Output Animation Pose`:

| State | Verified sequence |
| --- | --- |
| Idle | `Tutorial_Idle` |
| Walk | `Tutorial_Walk_Fwd` |

Use the actual sequence asset paths supplied by the task. Do not substitute an
asset with the same short name from another folder.

```lua
local path = "/Game/Characters/ABP_Hero"
local idle_sequence_path = "/Game/Animations/Tutorial_Idle"
local walk_sequence_path = "/Game/Animations/Tutorial_Walk_Fwd"

local bp = open_asset(path)
local idle_graph = bp.graphs["Locomotion/Idle"]
local walk_graph = bp.graphs["Locomotion/Walk"]
assert(idle_graph and walk_graph)

local idle_player = idle_graph:add_node("Sequence Player", 0, 0)
local walk_player = walk_graph:add_node("Sequence Player", 0, 0)
assert(idle_player and walk_player)

assert(idle_graph:set_pin(idle_player.handle, "Sequence", idle_sequence_path))
assert(walk_graph:set_pin(walk_player.handle, "Sequence", walk_sequence_path))
```

Read each state graph to locate its existing `Output Animation Pose` node and
inspect the player's pose output and result input. Connect those returned pose
pins; the verified final topology is:

```text
Sequence Player (Tutorial_Idle)     -> Output Animation Pose
Sequence Player (Tutorial_Walk_Fwd) -> Output Animation Pose
```

Do not create another output node. `add_state` creates the state graph and its
output node.

## Wire AnimGraph

The verified `AnimGraph` contains the `Locomotion` state-machine node connected
to `Output Pose`.

```lua
local graph = read_graph("/Game/Characters/ABP_Hero", "AnimGraph")
for _, node in ipairs(graph.nodes or {}) do
  print(node.name, node.handle)
end
```

Use the state-machine handle returned by `add_state_machine`, find the existing
`Output Pose`, inspect both pose pins, and connect them. Do not add a second
state-machine node after a failed connection; re-read the graph and fix the
pin selection.

## Wire Idle to Walk

The verified transition-rule topology is:

```text
Get Speed -> float > float -> Result
```

Open the rule graph using the `graph` selector returned by
`add_transition("Locomotion", "Idle", "Walk")`. Spawn the exact getter and
comparison nodes:

```lua
local path = "/Game/Characters/ABP_Hero"
local bp = open_asset(path)
local transition = bp.graphs["Locomotion/Idle->Walk"]
assert(transition)

local speed = transition:add_node("Get Speed", 0, 0)
local greater = transition:add_node("float > float", 300, 0)
assert(speed and greater)
```

The rule graph already owns its `Result` node. Read the graph, then:

1. Connect `Get Speed` to the first comparison input.
2. Set the other comparison input to the caller's requested walk threshold.
3. Connect the comparison boolean output to `Result`.

Never rely on the comparison node's autogenerated threshold. The live reference
verified the node topology, not a universal threshold value. Read back the
stored pin value after `set_pin`.

## Compile, save, and verify fresh

Compile and inspect the structured result before saving:

```lua
local bp = open_asset("/Game/Characters/ABP_Hero")
local compiled = bp:compile()
assert(compiled and compiled.success)
assert(compiled.error_count == 0)
assert(bp:save())
```

Verify from a new `execute_script` call:

```lua
local path = "/Game/Characters/ABP_Hero"
local bp = open_asset(path)
local info = bp:info()

assert(info.is_anim_bp == true)
assert(info.parent_class == "AnimInstance")

for _, variable in ipairs(bp.variables or {}) do
  print(variable.name, variable.type, variable.category)
end

for _, graph in ipairs(info.graphs or {}) do
  print(graph.name, graph.type, graph.num_nodes)
end

for _, graph_name in ipairs({
  "EventGraph",
  "AnimGraph",
  "Locomotion",
  "Locomotion/Idle",
  "Locomotion/Walk",
  "Locomotion/Idle->Walk",
}) do
  local graph = read_graph(path, graph_name)
  assert(graph and graph.nodes)
end
```

The live reference's fresh dump reported 7 canonical graphs and 19 nodes. Treat
those numbers as evidence for that exact reference topology, not as defaults
for every AnimBlueprint.

## Create an AnimLayerInterface

Create the interface through `create_asset`, then add animation-layer graphs on
the returned enriched handle:

```lua
local path = "/Game/Characters/ALI_Traversal"
local ali = create_asset(path, "AnimLayerInterface")
assert(ali)

local info = ali:info()
assert(info.is_anim_bp == true)

local layer = ali:add_anim_layer("TraversalPose")
assert(layer)
assert(layer.name == "TraversalPose")

local compiled = ali:compile()
assert(compiled.success)
assert(compiled.error_count == 0)
assert(ali:save())
```

Fresh verification:

```lua
local ali = open_asset("/Game/Characters/ALI_Traversal")
local info = ali:info()
assert(info.is_anim_bp == true)

local found = false
for _, graph in ipairs(info.graphs or {}) do
  if graph.name == "TraversalPose" then found = true end
end
assert(found)
```

The fixed live reference `/Game/_SkillRootVerify/ALI_RootVerify` was created as
an Animation Blueprint interface, accepted
`add_anim_layer("RootVerifyPose")`, compiled with zero errors, and saved.

Use `add_anim_layer` for layer graphs. Do not use `override_function` for
animation layers.

## Discovery

- Call `bp:help()` after `open_asset`; it is the authoritative Blueprint method
  list for state machines and animation layers.
- Call `bp:info()` for `is_anim_bp`, parent class, counts, and graph inventory.
- Use `read_graph(path, selector)` to verify existing nodes and real pin names.
- Use `find_nodes(query, path, selector)` when direct graph
  `add_node("Title")` is ambiguous.
- Inspect `pins_in`, `pins_out`, `linked_to`, and stored defaults before wiring.
- Use `report_issue(...)` when the live graph contradicts these verified shapes
  or a correct-looking graph fails compilation.

## Failure modes

| Symptom | Cause and response |
| --- | --- |
| AnimBlueprint creation returns nil | Supply `ParentClass="AnimInstance"` and a valid `TargetSkeleton`; verify the asset path first. |
| `add_state_machine` says `AnimGraph not found` | Open the AnimBP in the editor, re-open its handle, and retry. |
| Duplicate state-machine or state creation returns nil | Re-read `bp:info()` and reuse the existing graph instead of replaying creation. |
| `Entry -> Idle` creates no rule graph | Expected: entry links return `kind="entry"` and `result_handle="none"`. |
| Transition graph cannot be found | Carry `transition.graph` from `add_transition`, or inspect `bp:info().graphs` after refresh. |
| Sequence Player uses the wrong clip | Set its `Sequence` pin to the full intended asset path and read the stored value back. |
| State compiles but contributes no pose | Verify Sequence Player is connected to the existing `Output Animation Pose`. |
| Transition always passes or never passes | Set the comparison threshold explicitly; do not rely on an autogenerated pin default. |
| `add_anim_layer` returns nil | Use a non-empty unique layer name on an AnimBlueprint or AnimLayerInterface handle. |
| Compile reports errors | Stop before save, read every affected graph fresh, and inspect compiler log output. |
| In-script graph inventory looks stale | Re-open the asset in a new `execute_script` call before judging the mutation. |
