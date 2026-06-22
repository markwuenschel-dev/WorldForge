---
name: neostack-game-testing
description: How to run autonomous Unreal game playtests through NeoStack Lua. Use when the user asks an agent to test gameplay, play a level, verify input behavior, reproduce a bug in PIE, inspect screenshots/logs during play, or create an automated game-testing loop.
tags: [neostack, playtest, game-testing, unreal, pie]
---

# Game Testing

Use `execute_script` with NeoStack's `playtest_*` Lua helpers. Keep a test loop structured: start PIE, wait until ready, mark logs/screens, act, assert, stop PIE.

## Basic Loop

```lua
playtest_start()
local ready = playtest_wait_for_pie({timeout=5})
if not ready.ok then return ready end

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
- `playtest_start(opts?)` / `playtest_stop()` - lifecycle.
- `playtest_wait_for_pie({timeout=5})` - wait before input.
- `playtest_wait(seconds)` / `playtest_wait_frames(n)` - let game/editor tick.
- `playtest_observe()` - screenshot through the agent image pipeline.
- `playtest_screenshot_marker()` - lightweight viewport hash for comparisons.
- `playtest_assert_screenshot_changed(before, after?)` - verify visible change.
- `playtest_log_marker()` - scope log checks to new output.
- `playtest_assert_log_contains(text, {since=marker, timeout=3})` - verify events.
- `playtest_assert(name, fn)` / `playtest_wait_until(fn, opts)` - custom checks.

## Input

```lua
playtest_key({key="Space", event="pressed"})
playtest_key({key="Space", event="released"})
playtest_axis({key="Gamepad_LeftX", value=1.0})
playtest_click({x=0.5, y=0.5, normalized=true})
playtest_console("stat fps")
```

If the Enhanced Input extension is loaded:

```lua
playtest_input_action({action="/Game/Input/IA_Jump", value=true, mode="pulse"})
playtest_input_mapping({mapping="Move", value={x=1,y=0}, mode="pulse"})
```

## Testing Rules

- Keep marker variables inside one `execute_script` call; Lua state is not shared across calls.
- Prefer logs and game state assertions over screenshots when possible.
- Screenshot hash changes can happen from TAA, sky, particles, or camera jitter; use it as "frame changed", not proof of intent.
- Always stop PIE on failure paths when the script started it.
- Return structured tables with `ok`, `passed`, `message`, and useful evidence.

## Good Failure Report

```lua
return {
  ok = false,
  message = "Jump input did not produce expected log",
  screenshot = playtest_observe({max_dimension=512}),
  status = playtest_status(),
}
```
