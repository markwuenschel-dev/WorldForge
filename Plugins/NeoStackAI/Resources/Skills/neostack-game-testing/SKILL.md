---
name: neostack-game-testing
description: How to run autonomous Unreal game playtests through NeoStack Lua. Use when the user asks an agent to test gameplay, play a level, verify input behavior, reproduce a bug in PIE, inspect screenshots/logs during play, or create an automated game-testing loop.
---

# Game Testing

Use `execute_script` with NeoStack's `playtest_*` Lua helpers. Keep a test loop structured: start PIE, wait until ready, mark logs/screens, act, assert, stop PIE.

## Basic Loop

```lua
local target_map = "/Game/Maps/TargetMap"
playtest_start({map=target_map})
local ready = playtest_wait_for_pie({timeout=5})
if not ready.ok then
  playtest_stop()
  playtest_wait_until(function()
    local status = playtest_status()
    return not status.queued and not status.in_progress
  end, {timeout=5, interval=0.05})
  return ready
end

local logs = playtest_log_marker()
local before = playtest_screenshot_marker()

playtest_key({key="W", event="pressed"})
playtest_wait_frames(10)
playtest_key({key="W", event="released"})

local changed = playtest_assert_screenshot_changed(before)
local begin_play = playtest_assert_log_contains("BeginPlay", {since=logs, timeout=2})

playtest_stop()
return {changed=changed, begin_play=begin_play}
```

## What To Use

- `playtest_status()` - check PIE state.
- `playtest_start(opts?)` / `playtest_stop()` - lifecycle. For deterministic
  multiplayer, pass `clients`, `network_mode`, and
  `run_under_one_process=true`.
- `playtest_wait_for_pie({timeout=5})` - wait before input.
- `playtest_wait(seconds)` / `playtest_wait_frames(n)` - let game/editor tick.
- `playtest_read_state(opts)` - read one live PIE actor, transform, and selected
  reflected properties without relying on console text.
- `playtest_observe({pie_instance=id})` - screenshot one exact PIE viewport
  through the agent image pipeline.
- `playtest_screenshot_marker({pie_instance=id})` - lightweight viewport hash
  for one exact PIE instance.
- `playtest_assert_screenshot_changed(before, after?)` - verify visible change.
- `playtest_log_marker()` - scope log checks to new output.
- `playtest_assert_log_contains(text, {since=marker, timeout=3})` - verify events.
- `playtest_assert(name, fn)` / `playtest_wait_until(fn, opts)` - custom checks.

## Read Live State

Use exact, case-sensitive selectors. Supply one or more selectors; they combine
with AND semantics. Use `actor` for an exact object name or path, `label` for an
exact editor label, `class` for an exact class name or path, and `tag` for exact
tag text. Ambiguous matches fail and return path-sorted `candidates`.

```lua
local state = playtest_read_state({
  class="/Game/Runner/BP_Runner.BP_Runner_C",
  properties={"CurrentLane", "Score"},
  pie_instance=0,
})
if not state.ok then return state end

local lane = state.properties.CurrentLane.value
local lane_text = state.properties.CurrentLane.serialized
local property_type = state.properties.CurrentLane.type
local location = state.actor.location
```

Property names are exact and case-sensitive. Each requested property returns
`{type, value, serialized}`: compare `value` for typed assertions and record
`serialized` for stable evidence. Use `component="ExactName"` to target an
exact component name/path/class instead of the actor. Read again after every
action; returned tables are snapshots, not live handles.

## Multiple PIE Clients

Keep all peers in one editor process so NeoStack can target their worlds and
viewports:

```lua
local map = "/Game/Maps/TargetMap"
local started = playtest_start({
  map=map,
  clients=2,
  network_mode="listen_server",
  run_under_one_process=true,
})
if not started.ok then return started end

local ready = playtest_wait_until(function()
  local status = playtest_status()
  if not status.playing or status.instance_count ~= 2 then return false end
  for _, instance in ipairs(status.instances or {}) do
    if not instance.has_viewport
        or not string.find(instance.map or "", "TargetMap", 1, true) then
      return false
    end
  end
  return true
end, {timeout=20, interval=0.1})
if not ready.passed then
  playtest_stop()
  return ready
end

local status = playtest_status()
local server, client
for _, instance in ipairs(status.instances) do
  if instance.net_mode == "listen_server" then server = instance end
  if instance.net_mode == "client" then client = instance end
end

local before = playtest_read_state({
  pie_instance=client.pie_instance,
  class="/Game/BP_Player.BP_Player_C",
  properties={"Controller", "CurrentLane"},
})
playtest_key({
  pie_instance=client.pie_instance,
  key="D",
  event="pressed",
})
playtest_wait_frames(3)
playtest_key({
  pie_instance=client.pie_instance,
  key="D",
  event="released",
})
playtest_wait_frames(3)
local after = playtest_read_state({
  pie_instance=client.pie_instance,
  class="/Game/BP_Player.BP_Player_C",
  properties={"Controller", "CurrentLane"},
})
local client_view = playtest_observe({pie_instance=client.pie_instance})
```

Discover instance IDs from `playtest_status().instances`; do not assume their
numbers or array order. Require the expected map on every peer before acting.
Client contexts and viewports may exist briefly while the client is still
travelling from a temporary map.

Every targeted input, console, or Enhanced Input result reports its resolved
`pie_instance`, world, and net mode. Check that identity, then read the intended
game state from the same instance. Delivery is not gameplay success. A client
may only see an unpossessed `ROLE_SimulatedProxy`; if its `Controller` property
is empty, fix the game's spawn, possession, or replication setup before
blaming input targeting.

## Input

```lua
playtest_key({pie_instance=0, key="SpaceBar", event="pressed"})
playtest_wait_frames(1) -- let the player-input tick dispatch the edge
playtest_key({pie_instance=0, key="SpaceBar", event="released"})
playtest_axis({pie_instance=0, key="Gamepad_LeftX", value=1.0})
playtest_click({pie_instance=0, x=0.5, y=0.5, normalized=true})
playtest_console("stat fps", {pie_instance=0})
```

If the Enhanced Input extension is loaded:

```lua
playtest_input_action({
  pie_instance=0,
  action="/Game/Input/IA_Jump",
  value=true,
  mode="pulse",
})
playtest_input_mapping({
  pie_instance=0,
  mapping="Move",
  value={x=1,y=0},
  mode="pulse",
})
```

Treat `playtest_key().consumed` as advisory. Raw Blueprint key events can run
even when no legacy Action Mapping reports the key as consumed. Prove input by
reading the resulting game state after at least one frame.

## Testing Rules

- Pass the exact target asset path in `playtest_start({map=...})` unless the
  current editor map is itself the behavior under test. The editor can be on
  an unsaved `Untitled` world and silently spawn a default pawn otherwise.
- Put the dependent lifecycle—start, baseline read, input, later reads,
  observations, and stop—inside one `execute_script` call. Lua state is not
  shared across calls, and fragmented probes can strand PIE on failure.
- Prefer `playtest_read_state` and scoped logs for exact assertions.
- For visual behavior, also call `playtest_observe()` and inspect the returned
  image; a compile result or property read cannot prove rendering.
- Screenshot hash changes can happen from TAA, sky, particles, or camera jitter; use it as "frame changed", not proof of intent.
- For multiplayer visuals, capture and inspect each exact `pie_instance`.
  Headless `-nullrhi` tests cannot provide meaningful framebuffer evidence.
- Always stop PIE on failure paths when the script started it, then wait until
  both `queued` and `in_progress` are false before starting another session.
- Return structured tables with `ok`, `passed`, `message`, and useful evidence.

## Failure Modes

| Symptom | Cause / fix |
|---|---|
| `status="no_pie"` | Start PIE and wait with `playtest_wait_for_pie`. |
| World map is `Untitled` or actor is `DefaultPawn` | The wrong editor world started. Stop PIE and restart with the exact `map` asset path. |
| `actor_ambiguous` | Add an exact label, class, tag, or object path; inspect sorted `candidates`. |
| `property_not_found` | Use the exact reflected property name and casing. |
| `write_failed` says the property cannot be edited on instances | Keep the safety boundary. If runtime control is intentional, expose a one-input BlueprintCallable `Set<Property>` function with the same scalar type; `playtest_write_state` discovers it and reports `write_mode="runtime_setter"`. Only make a property instance-editable when designers should genuinely edit it. |
| Key call succeeds but state does not change | Wait at least one frame, then inspect state; do not use `consumed` as the behavior assertion. |
| Two instances exist but a client still reports a temporary map | Wait until every instance reports the requested map and a viewport. |
| Correct client identity but gameplay does not change | Read the target pawn's `Controller` and role. An empty controller on a simulated proxy is a game spawn or possession problem. |
| Explicit instance reports no viewport | The target may be a dedicated server or still starting. Never fall back to another client. |

## Good Failure Report

```lua
return {
  ok = false,
  message = "Jump input did not produce expected log",
  screenshot = playtest_observe({max_dimension=512}),
  status = playtest_status(),
}
```
