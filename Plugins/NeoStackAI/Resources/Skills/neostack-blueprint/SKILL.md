---
name: neostack-blueprint
description: How to create and edit Unreal Blueprints through `execute_script`. Use when the user asks to make a new Blueprint, add variables/components/functions, or author/modify nodes in any Blueprint event or function graph. All operations go through one Lua tool — this skill teaches the working patterns and the failure modes that aren't obvious from `help()`.
---

# Editing Blueprints

You only have one tool: `execute_script`. It runs Lua against the live editor. Everything below is Lua you should write inside that tool's `script` argument.

**Nothing survives between calls.** Each `execute_script` runs in a fresh Lua state, so
locals — including your `bp` handle — are gone next call. Re-`open_asset` at the top of
every script. Node handles are the exception: they're deterministic GUIDs and stay
valid, so you can carry one across calls as a literal string.

## The shape of a Blueprint task

1. **Get the BP object.** `create_asset` (new) or `open_asset` (existing) returns the *enriched table* — call methods on it directly.
2. **Mutate.** Variables/components/functions via methods on the BP. Graph nodes via `find_nodes` → `add_node` → `connect` / `set_pin`.
3. **Verify.** `read_graph` to confirm topology, `bp:info()` for a summary.
4. **Persist.** `bp:compile()` then `bp:save()`.

You do not need to call `compile`/`save` after every step. Batch your edits in one script, then verify, then save.

## Creating

```lua
local bp = create_asset("/Game/BP_MyActor", "Blueprint")            -- defaults to Actor parent
local bp = create_asset("/Game/BP_Hero", "Blueprint", {ParentClass="Character"})
local bp = create_asset("/Game/BP_Child", "Blueprint", {
  ParentClass="/Game/BP_Parent",                                    -- Blueprint asset path
})
```

`create_asset` for a Blueprint returns the **enriched BP object directly** (not just `{path, type, class}` like other asset types). It auto-opens the BP and seeds the default events.

Common parents: `Actor`, `Character`, `Pawn`, `PlayerController`, `GameModeBase`, `HUD`, `ActorComponent`, `AnimInstance`.
For a Blueprint parent, pass its raw asset path as shown above; the factory resolves
that asset's generated class.

If the path already exists, `create_asset` will fail. Either pick a different name or `delete_asset(path)` first.

## Variables

```lua
bp:add_variable("Health", "float")
bp:add_variable("StartLocation", "vector")
bp:add_variable("EnemyNames", "string[]")              -- array
bp:add_variable("ScoreByName", "map:string:int")        -- map
bp:add_variable("VisitedTags", "set:name")              -- set
```

**Defaults go in the third argument**, not a separate call:

```lua
bp:add_variable("AmmoCount", "int", {default = 30})
bp:add_variable("CooldownTime", "float", {default = 1.5})
bp:add_variable("bIsAlive", "bool", {default = true})
bp:add_variable("SpawnOffset", "vector", {default = {x=0, y=0, z=200}})
bp:add_variable("Facing", "rotator", {default = {yaw = 90}})
bp:add_variable("Tint", "linearcolor", {default = {r=1, g=0.5, b=0}})   -- a defaults to 1
```

Tables work for `vector`, `vector2d`, `rotator` and `color`/`linearcolor`, in either
key case. **Any other struct needs UE export text** — `{default = "(X=0,Y=0,Z=200)"}` —
and passing a table for one is refused with a message saying so, rather than quietly
storing zeros.

`opts` also takes `category` and `tooltip`. Read the full list with `bp:help()`.

**A reference to another Blueprint** is typed by its asset path *or* its generated
class name — both resolve to the same `Object(BP_Target_C)`:

```lua
bp:add_variable("WeaponRef", "/Game/BP_Weapon")   -- asset path — works
bp:add_variable("WeaponRef", "BP_Weapon_C")       -- generated class — also works
bp:add_variable("WeaponRef", "BP_Weapon")         -- bare asset name — FAILS
```

The bare name is the one that doesn't resolve: `unknown type. Use: bool, int, float,
… or a class/struct name`. If you see that error on what looks like a valid class,
you've dropped either the path or the `_C`.

Type DSL: `int`, `float`, `bool`, `string`, `name`, `text`, `vector`, `rotator`, `transform`, `<class-name>`, `<class-name>[]`, `set:<t>`, `map:<k>:<v>`. `bp:add_variable` returns `true` / `nil`.

`bp.variables` is a snapshot taken when you opened the BP — it does **not** auto-refresh after `add_variable`. To see fresh variables, re-call `open_asset` or `bp:refresh()`.

### Reading a variable's actual default back

Use **`bp:get(name)`**. One call, no compile needed, returns the value directly:

```lua
bp:get("AmmoCount")   --> 30
bp:get("DoorName")    --> "FrontDoor"
```

`bp.variables` and `bp:info()` describe a variable's **shape** only — name, type,
category, edit flags. Neither carries a value, so a default that silently failed to
apply looks identical to one that worked. Container-ness is a separate field, not part
of the type string: an `int[]` reads back as `type="int", container="array"`.

For a bulk sweep of every property on the compiled class, `class_properties` takes the
generated class — dotted, `_C` suffix — after a compile:

```lua
class_properties("/Game/BP_MyActor.BP_MyActor_C", {editable_only = false})
```

Get that target form wrong and it does not error: the plain asset path, the BP handle,
or `path.."_C"` without the dot all return the **UBlueprint asset's own** editor
metadata (`CompileMode`, `ThumbnailInfo`, …) — a plausible-looking answer to a
different question. Prefer `bp:get` unless you genuinely want all ~100 properties.

### Referencing another Blueprint

A variable typed as another Blueprint just takes that asset's path as its type string —
there is no separate object-reference syntax:

```lua
bp:add_variable("TargetChar", "/Game/BP_ProbeChar")   -- object ref to that BP
```

To then call a function on it, do **not** search by the bare function name — `find_nodes`
is a fuzzy text match and will hand back unrelated nodes from across the engine. Spawn
the getter first, then search *from its output pin*, which filters the action list to
what is actually callable on that type:

```lua
local getter = g:add_node("Get TargetChar", 0, 0)          -- plain string is fine here
local hits = find_nodes({
  query = "MyFunction", asset_path = bp.path, graph_name = "EventGraph",
  from_handle = getter.handle, from_pin = "Target Char",   -- display name, with the space
})
hits[1].from_handle, hits[1].from_pin = getter.handle, "Target Char"
local call = g:add_node(hits[1], 400, 0)                   -- spawns already wired
```

## The BP and graph objects

`bp:help()` lists everything, but these are the ones you'll reach for:

```lua
bp:add_variable(n, type, opts)   bp:add_function(n, {params=…, returns=…})
bp:add_component(n, class, parent?)   bp:add_custom_event(n, {params=…})
bp:add_event_dispatcher(n, params)    bp:add_timeline(n, {length=, tracks=})
bp:add_interface("/Game/Full/Path")   bp:override_function(name)
bp:compile()   bp:save()   bp:refresh()
bp.graphs["EventGraph"]   bp.variables   bp.components   bp.interfaces
```

Reading and writing values:

```lua
bp:get("Health")                        -- a Blueprint variable's default
bp:get("SpringArm", "TargetArmLength")  -- a component property (two-arg form)
bp:set("Health", 100)                   -- the BP's own default
bp:set("SpringArm", "TargetArmLength", 400)
```

**`params` entries take either spelling** — `{name="Damage", type="float"}` or the
positional `{"Damage", "float"}`.

### Network RPC custom events

Create server, client, or multicast RPCs through the same generic custom-event verb:

```lua
local event = assert(bp:add_custom_event("ServerRequestMove", {
  params = {{name="Direction", type="int"}},
  replicated = "server",
  reliable = true,
}))
assert(event.replicated == "server" and event.reliable == true)
assert(event.param_count == 1)
assert(event.params[1].name == "Direction"
  and event.params[1].type == "int"
    and event.params[1].direction == "output")
```

`replicated` accepts `server`, `client`, `multicast`, or `none`. `reliable=true`
is refused unless the event is networked. Upserting an event replaces only options
you supplied; an explicit `params={}` clears its parameter pins. Invalid modes,
malformed parameter entries, duplicate parameter names, and unknown types fail
before the graph is changed. Returned `params` is the exact stored signature, split
into canonical fields: an input type such as `class:Actor` reads back as
`type="class", sub_type="Actor"`; arrays, sets, and maps also carry `container`.
If UE canonicalizes a requested name, the whole upsert is rejected and the prior
signature, links, flags, and package cleanliness are restored. Accepted replacement
disconnects the removed pins from both ends. Rollback restores exact reciprocal
endpoints before notifying reconstructing peer nodes. Inherited overrides are read
through their compiler-effective parent RPC flags; a conflicting mode is refused.

After compile/save, reopen and verify the persisted flags instead of trusting the
creation call:

```lua
local fresh = assert(open_asset("/Game/BP_MyActor"))
assert(fresh:get("ServerRequestMove", "replicated") == "server")
assert(fresh:get("ServerRequestMove", "reliable") == true)
assert(fresh:get("ServerRequestMove", "param_count") == 1)
```

For an existing member variable, replication is metadata:

```lua
assert(bp:set_property("CurrentLane", {replicated=true}))
bp:refresh()
assert(bp.variables.CurrentLane.replicated == true)
```

RepNotify takes the exact name of an existing zero-parameter, zero-return
Blueprint function. Verify the handler name, not only the boolean flag:

```lua
assert(bp:add_function("OnRep_CurrentLane"))
assert(bp:set_property("CurrentLane", {
  rep_notify = "OnRep_CurrentLane",
}))
bp:refresh()
local lane = assert(bp.variables.CurrentLane)
assert(lane.replicated == true and lane.rep_notify == true)
assert(lane.rep_notify_function == "OnRep_CurrentLane")
```

`rep_notify=false` clears only the notifier and leaves ordinary replication
enabled. `replicated=false` clears replication, RepNotify, and the handler name.
Boolean `true`, missing functions, and functions with parameters or returns are
refused before mutation. When `replicated` and `rep_notify` are supplied together,
the bundle is validated and committed atomically; contradictory or malformed
options leave both the flags and handler unchanged.
Valid inherited RepNotify handlers are accepted through the compiler-effective
skeleton function; inherited handlers with parameters or returns are refused.

Use two script calls when you also need call nodes. First add/compile/save the custom
event. In a fresh script, `find_nodes("ServerRequestMove", path, "EventGraph")`,
select the exact callable action by name, owning class, and input pins, then spawn and
wire it. Action-database discovery is not guaranteed to see a just-created event
before Blueprint skeleton regeneration.

**Attach a component by passing the parent as the third argument:**
`bp:add_component("Camera", "CameraComponent", "SpringArm")`. Omit it and the
component attaches to the root.

**Component classes need the `Component` suffix** — the actor class name is not the
component class name. `add_component("Glow", "PointLight")` fails with *"Class not
found or not a component type"*; you want `PointLightComponent`. Likewise
`StaticMeshComponent`, `SpringArmComponent`, `CameraComponent`, `AudioComponent`.

**Always give `add_interface` a full asset path.** A bare short name resolves against
every matching asset in the project and can silently attach the wrong one — check
`bp.interfaces[n].class_path` if you need to be sure which one landed.

**Names collide with inherited properties.** `Tags`, `Owner`, `Role` and friends
already exist on `AActor`, so `add_variable("Tags", …)` fails — it names the parent
class in the error. Pick another name; the type string is not the problem.

A graph object carries the same verbs as the globals, scoped to that graph — so you
can skip re-passing the path and graph name:

```lua
local g = bp.graphs["EventGraph"]
g:add_node(hit, x, y)    g:connect(a, "then", b, "execute")
g:set_pin(h, pin, value) g:delete_node(h)
```

`bp.graphs` is keyed by name **and** by index — iterate with `type(k)=="number"` to
avoid visiting everything twice. A timeline's name does *not* resolve here even though
`info().num_graphs` counts it; an event dispatcher's does.

## Graphs and nodes

The default Actor BP has two graphs: `EventGraph` (BeginPlay, ActorBeginOverlap, Tick) and `UserConstructionScript` (Construction Script). Get handles via `read_graph`:

```lua
local rg = read_graph("/Game/BP_MyActor", "EventGraph")
for _, n in ipairs(rg.nodes) do
  log(n.handle, n.name)
end
```

Node handles are deterministic GUIDs. Same node = same handle every run, so you can persist a handle in a comment or a const at the top of a long script. **What does NOT persist across script calls** is the session's spawner cache (`_spawner_id` / `_action_id` from `find_nodes`) — re-call `find_nodes` each script. Inside one script, results may be safely preflighted before the first mutation and then spawned later in the same batch: the session owns transient Blueprint spawners until the script ends, and Blueprint skeleton regeneration is deferred to the end-of-script graph finalizer.

### Spawning a node

```lua
local hits = find_nodes("Print String", "/Game/BP_MyActor", "EventGraph", 5)
local node = add_node("/Game/BP_MyActor", "EventGraph", hits[1], 400, 0)
-- node = {handle, name, pins_in[], pins_out[]}
```

Pass the **whole hit table** as the `node` argument. It carries either `_spawner_id` (Blueprint action database) or `_action_id` (schema action) — `add_node` picks the right path. Do not strip those fields.

`find_nodes` is fuzzy — give it the user-facing node name. `find_nodes("delay")` returns Delay, Delay Until Next Frame, Delay Until Next Tick. Pick by `score` (highest = best) or by inspecting `name`.

**Flow control macros are ordinary results.** `For Each Loop`, `For Each Loop with
Break`, `Reverse for Each Loop`, `For Loop`, `While Loop`, `Do Once`, `Flip Flop` all
come back from `find_nodes` and spawn like anything else. Don't hand-roll an index
loop out of `Length`/`Less`/`Branch` — search for the macro. Note the array variant is
plain `For Each Loop`; `For Each Loop (Set)` and `(Map)` are different nodes for
different container types.

`For Each Loop`'s pins are `Exec` / `Array` in, `Loop Body` / `Array Element` /
`Completed` out — its exec-in is **`Exec`**, not `execute`.

**Wire a wildcard node's INPUT before its outputs.** `For Each Loop`'s `Array` pin is
a wildcard, and the first connection you make resolves the whole node's type. Connect
`Array Element → Print String.In String` first and the loop silently becomes an array
*of strings*; your real `vector[]` then refuses to attach —
`Array of Vectors is not compatible with Array of Strings`. Wire
`Get Waypoints → Array` first, then the element output, and the engine inserts any
needed conversion node for you. The same ordering rule applies to every promotable
node — `Add`, `Less`, `Select`, and friends.

**Bare-name search does not work across Blueprints.** Looking for a function that
lives on *another* Blueprint by name alone returns fuzzy engine matches, never the one
you want. Spawn a getter for a variable of that type first, then search from its
output pin with `from_handle` / `from_pin` — that filters the action list to what is
actually callable on that type. This is required, not an optimisation.

### Connecting

```lua
local ok, details = connect(begin_play_handle, "then", print_handle, "execute")
-- details.method is "direct", "conversion", or "bridge"
```

Pin names are case-insensitive. **The exec output on event nodes is `then`**, not `exec` or `Then`. The exec input on most function-call nodes is `execute`. Common pins:

The first return remains `true`/`nil`, so existing `if connect(...) then` code is compatible. Use the optional second return when you need to know whether UE inserted a conversion node.

| Node           | exec in    | exec out |
|----------------|------------|----------|
| Event BeginPlay/Tick/etc. | (n/a)      | `then`   |
| Function-call (Print String, Delay, function calls) | `execute`  | `then`   |
| Branch         | `execute`  | `True`, `False` |
| Sequence       | `execute`  | `then 0`, `then 1`, … |

**Exec output pins allow only one connection.** Connecting a new node to an already-connected exec out silently replaces the old connection. Read the graph first if you're not sure whether the pin is free.

### Setting pin defaults

```lua
local ok, details = set_pin(print_handle, "In String", "Hello world")
-- details.stored_value is UE's normalized value; no get_pin confirmation read needed
set_pin(node_h, "Location", {x=100, y=0, z=50})              -- struct pin
set_pin(node_h, "Color", {r=1, g=0.5, b=0, a=1})             -- LinearColor
set_pin(delay_h, "Duration", 2.5)                            -- numbers are fine
set_pin(branch_h, "Condition", false)                        -- so are bools
```

**Pin names are display names, with spaces.** A variable getter's output pin is
`"Target Char"`, not `"TargetChar"` and not `"Return Value"`. Read the real name off
`pins_in` / `pins_out` rather than guessing — or trigger the failure once and read it
out of the error, which lists every available pin with its type.

`set_pin` only sets the literal default; it does not break existing connections. If a pin is already wired, the default is ignored at runtime — disconnect first if needed.
Its first return remains `true`/`nil`; the optional details table includes `requested_value`, `stored_value`, and `format_normalized`.

### Auto-connect on spawn

You can fold "spawn + connect" into one call by setting `from_handle` / `from_pin` on the hit table:

```lua
local hits = find_nodes("Delay", "/Game/BP_MyActor", "EventGraph")
hits[1].from_handle = begin_play_handle
hits[1].from_pin = "then"
add_node("/Game/BP_MyActor", "EventGraph", hits[1], 800, 0)
```

Same single-connection caveat — if `begin_play.then` was already wired to something, this replaces it.

## Reading the graph back

`read_graph` returns `{graph_name, graph_guid, nodes = [...]}`. Each node has `pins_in` and `pins_out`. Each pin:

| Field            | Meaning                                             |
|------------------|-----------------------------------------------------|
| `name`           | Display name (use this for `connect`/`set_pin`)     |
| `raw_name`       | Internal pin id (no spaces)                         |
| `type`           | `exec`, `string`, `bool`, `real`, `struct`, …       |
| `direction`      | `input` / `output`                                  |
| `connected`      | bool                                                |
| `linked_to_count`| int                                                 |
| `linked_to`      | array of `{node_id, node_title, pin_name}` records  |
| `default`        | string-formatted default value (for unconnected input pins) |
| `is_hidden`, `is_orphaned` | bool                                      |

The field is `linked_to`, **not** `connections` — the inline help text says "connections" but the actual returned key is `linked_to`.

## End-of-script finalization

`FLuaGraphFinalizer` runs once at the end of every script execution: it compiles dirty graphs and marks the asset modified. So:

- You don't need to call `bp:compile()` between mutations within a single script.
- You **do** need to call `bp:save()` for the change to survive editor restart.
- `bp:save()` first finalizes this Blueprint's pending graph batch, then saves
  it. On success, a fresh script sees `bp:info().package_dirty == false`.
  Mutating the graph again after that save registers a new pending batch.
- An in-script `read_graph` after a mutation may show the topology without all metadata populated. If something looks wrong, the most reliable verification is a *fresh script* whose first call is `read_graph`.

## End-to-end pattern

```lua
-- 1. Create
local bp = create_asset("/Game/BP_HelloActor", "Blueprint")

-- 2. Variables
bp:add_variable("Greeting", "string")

-- 3. Find BeginPlay
local rg = read_graph("/Game/BP_HelloActor", "EventGraph")
local begin_play
for _, n in ipairs(rg.nodes) do
  if n.name == "Event BeginPlay" then begin_play = n.handle end
end

-- 4. Spawn Print String, auto-connected to BeginPlay.then
local hits = find_nodes("Print String", "/Game/BP_HelloActor", "EventGraph", 1)
hits[1].from_handle = begin_play
hits[1].from_pin = "then"
local print_node = add_node("/Game/BP_HelloActor", "EventGraph", hits[1], 400, 0)

-- 5. Set the message
set_pin(print_node.handle, "In String", "Hello from NSAI!")

-- 6. Persist
bp:compile()
bp:save()
```

## How failure reaches you

**Failed calls do not raise Lua errors.** `connect`, `add_node`, `set_pin` and
`delete_node` all return `nil` on failure and print a `[FAIL] …` line to the tool
output. Your script keeps running. So:

- `pcall` tells you nothing useful here — it reports success for a failed call.
  Check the **return value**.
- A batch that half-worked leaves the successful half applied. If a script does stop
  early, you'll see `Lua stopped with an error after committed graph edits` — resume
  from where it broke, don't blindly replay the whole batch.

The `[FAIL]` text is worth reading rather than guessing around: it names the real pin,
with types. `from_pin "Return Value" not found on node "286…". Available: Target Char
(out, object<BP_ProbeChar_C>)` tells you the answer outright.

## Failure modes you'll actually see

| Symptom                                          | Cause / fix                                             |
|--------------------------------------------------|---------------------------------------------------------|
| `class_properties` returns `CompileMode`, `ThumbnailInfo`, … | You targeted the Blueprint asset, not its class. Use `"<path>.<Name>_C"` — dotted, `_C` suffix. |
| Variable default seems not to apply              | `bp.variables` never carries values. Read it with `bp:get(name)`. |
| `add_variable(n, "BP_Door")` → `unknown type`    | Blueprint classes need the asset path or the `_C` name. Bare asset name doesn't resolve. |
| `find_nodes("MyFunc")` returns unrelated engine nodes | Bare-name search is fuzzy text. For anything on another Blueprint, search from a typed pin with `from_handle`/`from_pin` — it's required, not an optimisation. |
| `pcall` says success but nothing changed         | Failures return `nil` rather than raising. Check the return value, not `pcall`. |
| Just-spawned `Subtract` says `FrameNumber - Int` | Promotable operator, still wildcard. Wire float pins and it resolves to `float - float`. Not a bug. |
| Deprecated call compiles with 0 warnings         | Warnings only surface for nodes on an executed path. Wire the exec pin first. |
| `bp.graphs["MyTimeline"]` is `nil`               | Timelines are counted by `num_graphs` but aren't addressable there. Dispatchers are. |
| `ipairs(pin.linked_to)` → `attempt to index a nil value` | `linked_to` is `nil` when the pin is unconnected, not an empty table. Guard with `pin.linked_to or {}`. |
| Reading a graph back, nothing links from `then`  | Exec-out pin names vary by node. `Delay`'s is `Completed`. Read `pins_out` instead of assuming `then`. |
| `bp:set(name, nil, value)` killed the script     | Property name must be a non-empty string. Use `set(prop, value)` for the BP's own defaults, `set(target, prop, value)` for a component. |
| `connect -> target node "X" not found`            | Stale or wrong handle. Re-run `read_graph`.            |
| `set_pin` succeeds but value seems ignored      | The pin is already wired — `set_pin` only sets the literal default. Disconnect or rewire. |
| `find_nodes` returns 0 hits                      | Wrong asset path or graph name; or the node isn't valid in that graph context (e.g. UI nodes in actor BPs). |
| Mutations look missing in `bp.variables`/`bp.graphs` | Snapshot is stale. Re-call `open_asset` or use `read_graph` for graphs. |
| `create_asset` returns nil                       | Path already exists. Use `asset_exists(path)` first; `delete_asset(path)` if you want to replace. |

## Discovery escape hatches

- `help("AddNode")` / `help("Connect")` / `help("SetPin")` / `help("FindNodes")` / `help("ReadGraph")` / `help("AddVariable")` — domain function lists.
- `bp:help()` — methods available on the BP object (variables, components, functions, custom events, timelines, state machines, interfaces, event dispatchers, comments).
- `bp:info()` — structured summary of the BP's contents.
- `bp:list_events()` — events defined or overridden in this BP.
- `bp:list_properties("self")` — member variables with types/flags. The target argument
  is required; calling it bare raises a Lua error and kills the rest of your script.
- `report_issue("…")` — last-resort escape when the API genuinely doesn't cover what the user asked for.

Don't wrap `help(...)` in `log(...)` — `help` already prints to the trace.
