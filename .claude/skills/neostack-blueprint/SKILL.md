---
name: neostack-blueprint
description: How to create and edit Unreal Blueprints through `execute_script`. Use when the user asks to make a new Blueprint, add variables/components/functions, or author/modify nodes in any Blueprint event or function graph. All operations go through one Lua tool — this skill teaches the working patterns and the failure modes that aren't obvious from `help()`.
---

# Editing Blueprints

You only have one tool: `execute_script`. It runs Lua against the live editor. Everything below is Lua you should write inside that tool's `script` argument.

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
```

`create_asset` for a Blueprint returns the **enriched BP object directly** (not just `{path, type, class}` like other asset types). It auto-opens the BP and seeds the default events.

Common parents: `Actor`, `Character`, `Pawn`, `PlayerController`, `GameModeBase`, `HUD`, `ActorComponent`, `AnimInstance`.

If the path already exists, `create_asset` will fail. Either pick a different name or `delete_asset(path)` first.

## Variables

```lua
bp:add_variable("Health", "float")
bp:add_variable("StartLocation", "vector")
bp:add_variable("EnemyNames", "string[]")              -- array
bp:add_variable("ScoreByName", "map:string:int")        -- map
bp:add_variable("VisitedTags", "set:name")              -- set
```

Type DSL: `int`, `float`, `bool`, `string`, `name`, `text`, `vector`, `rotator`, `transform`, `<class-name>`, `<class-name>[]`, `set:<t>`, `map:<k>:<v>`. `bp:add_variable` returns `true` / `nil`.

`bp.variables` is a snapshot taken when you opened the BP — it does **not** auto-refresh after `add_variable`. To see fresh variables, re-call `open_asset` or `bp:list_properties()`.

## Graphs and nodes

The default Actor BP has two graphs: `EventGraph` (BeginPlay, ActorBeginOverlap, Tick) and `UserConstructionScript` (Construction Script). Get handles via `read_graph`:

```lua
local rg = read_graph("/Game/BP_MyActor", "EventGraph")
for _, n in ipairs(rg.nodes) do
  log(n.handle, n.name)
end
```

Node handles are deterministic GUIDs. Same node = same handle every run, so you can persist a handle in a comment or a const at the top of a long script. **What does NOT persist across script calls** is the session's spawner cache (`_spawner_id` / `_action_id` from `find_nodes`) — re-call `find_nodes` each script.

### Spawning a node

```lua
local hits = find_nodes("Print String", "/Game/BP_MyActor", "EventGraph", 5)
local node = add_node("/Game/BP_MyActor", "EventGraph", hits[1], 400, 0)
-- node = {handle, name, pins_in[], pins_out[]}
```

Pass the **whole hit table** as the `node` argument. It carries either `_spawner_id` (Blueprint action database) or `_action_id` (schema action) — `add_node` picks the right path. Do not strip those fields.

`find_nodes` is fuzzy — give it the user-facing node name. `find_nodes("delay")` returns Delay, Delay Until Next Frame, Delay Until Next Tick. Pick by `score` (highest = best) or by inspecting `name`.

### Connecting

```lua
connect(begin_play_handle, "then", print_handle, "execute")
```

Pin names are case-insensitive. **The exec output on event nodes is `then`**, not `exec` or `Then`. The exec input on most function-call nodes is `execute`. Common pins:

| Node           | exec in    | exec out |
|----------------|------------|----------|
| Event BeginPlay/Tick/etc. | (n/a)      | `then`   |
| Function-call (Print String, Delay, function calls) | `execute`  | `then`   |
| Branch         | `execute`  | `True`, `False` |
| Sequence       | `execute`  | `then 0`, `then 1`, … |

**Exec output pins allow only one connection.** Connecting a new node to an already-connected exec out silently replaces the old connection. Read the graph first if you're not sure whether the pin is free.

### Setting pin defaults

```lua
set_pin(print_handle, "In String", "Hello world")
set_pin(node_h, "Location", {x=100, y=0, z=50})              -- struct pin
set_pin(node_h, "Color", {r=1, g=0.5, b=0, a=1})             -- LinearColor
```

`set_pin` only sets the literal default; it does not break existing connections. If a pin is already wired, the default is ignored at runtime — disconnect first if needed.

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

## Failure modes you'll actually see

| Symptom                                          | Cause / fix                                             |
|--------------------------------------------------|---------------------------------------------------------|
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
- `bp:list_properties()` — all member variables with their types/flags.
- `report_issue("…")` — last-resort escape when the API genuinely doesn't cover what the user asked for.

Don't wrap `help(...)` in `log(...)` — `help` already prints to the trace.
