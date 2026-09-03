---
name: neostack-sequencer
description: Author and verify Unreal Level Sequences through execute_script. Use when the user asks for Sequencer animation, keyed transforms, camera cuts, timeline ranges, tracks, sections, markers, or subsequences.
---

# Sequencer authoring

Everything below is Lua for `execute_script`. Each call starts a fresh Lua
state, so reopen the sequence and level in every call. Sequence and node handles
do not carry between calls.

The reliable workflow is:

1. Put deliberately labelled actors in the level and save it.
2. Create a `LevelSequence`, set rates and the playback range.
3. Add possessable bindings, tracks, and keys.
4. Save, then reopen in a fresh call and inspect `info()`, bindings, channels,
   and keyframes.
5. Open the Sequencer editor, evaluate at two or more in-range display frames,
   and capture the level viewport. A clean asset or plausible key table is not
   visual proof.

## End-to-end moving actor

First make the level actors. The labels are what the sequence binding consumes:

```lua
local level_path = "/Game/Maps/L_TemporalProof"
assert(create_level(level_path, {
  world_partition = false,
  open = true,
}))

-- create_level returns a success boolean, not the level handle.
local level = assert(open_level())

assert(level:add("actor", {
  mesh = "/Engine/BasicShapes/Cube",
  location = { x = 0, y = -300, z = 50 },
  mobility = "movable",
  label = "TemporalCube",
}))

assert(level:add("actor", {
  class = "/Script/Engine.CameraActor",
  location = { x = -1000, y = 0, z = 400 },
  rotation = { pitch = -20, yaw = 0, roll = 0 },
  mobility = "movable",
  label = "RenderCamera",
}))

-- Camera FOV belongs to the CameraComponent, not the CameraActor.
assert(configure_component(
  "RenderCamera",
  "CameraComponent",
  { property = { FieldOfView = "60.0" } }
))

assert(level:save())
```

In a fresh call, reload the map and verify its persisted partition state:

```lua
assert(load_level("/Game/Maps/L_TemporalProof"))
local level = assert(open_level())
local level_info = assert(level:info())
assert(level_info.world_partition == false)
```

Transform-bound scene actors must be `movable`. Freshly list the actor and
require `mobility == "movable"` before authoring the sequence. A static actor
can have valid keys and a changing Sequencer time while remaining visually
frozen.

Create maps only with `create_level(path, opts)` or by saving the currently
open level through `save_level_as(path)`. `create_level` requires the content
path and returns a success boolean; call `open_level()` afterward to obtain the
level handle. `create_asset(path, "World")` is rejected because a generic
standalone `UWorld` does not participate in the editor map lifecycle.

Freshly verify camera FOV before authoring the camera cut:

```lua
local camera_props = assert(get_component_properties(
  "RenderCamera",
  "CameraComponent",
  { filter = "FieldOfView", changed_only = false }
))

local stored_fov
for _, row in ipairs(camera_props) do
  if row.name == "FieldOfView" then
    stored_fov = tonumber(row.value)
  end
end
assert(stored_fov and math.abs(stored_fov - 60.0) < 0.001)
```

`level:configure("actor", ...)` takes the actor label as its second argument:
`level:configure("actor", "RenderCamera", params)`. Do not pass the params
table in place of the label.

Create and author the sequence:

```lua
local path = "/Game/Cinematics/SEQ_TemporalCube"
local seq = create_asset(path, "LevelSequence")
assert(seq)

assert(seq:configure("sequence", {
  display_rate = 24,
  tick_resolution = 24000,
  evaluation_type = "with_sub_frames",
}))
assert(seq:set_playback_range(0, 4))

assert(seq:add("binding", {
  actor_name = "TemporalCube",
  name = "TemporalCube",
}))
assert(seq:add("binding", {
  actor_name = "RenderCamera",
  name = "RenderCamera",
}))

-- Track creation returns true, not a track handle.
assert(seq:add("track", {
  binding = "TemporalCube",
  track_type = "3DTransform",
  start_time = 0,
  end_time = 4,
}))

assert(seq:set_transforms({
  binding = "TemporalCube",
  time = 0,
  location = { x = 0, y = -300, z = 50 },
  rotation = { pitch = 0, yaw = 0, roll = 0 },
  scale = { x = 1, y = 1, z = 1 },
  interp = "linear",
}))
assert(seq:set_transforms({
  binding = "TemporalCube",
  time = 2,
  location = { x = 0, y = 0, z = 200 },
  rotation = { pitch = 0, yaw = 180, roll = 0 },
  scale = { x = 1.5, y = 1.5, z = 1.5 },
  interp = "linear",
}))
assert(seq:set_transforms({
  binding = "TemporalCube",
  time = 4,
  location = { x = 0, y = 300, z = 50 },
  rotation = { pitch = 0, yaw = 360, roll = 0 },
  scale = { x = 0.7, y = 0.7, z = 0.7 },
  interp = "linear",
}))

assert(seq:add("track", {
  track_type = "CameraCut",
  start_time = 0,
  end_time = 4,
  camera_binding = "RenderCamera",
}))

assert(seq:save())
```

`set_playback_range(0, 4)` produces the half-open range `[0, 4)`. At 24 fps,
frame 95 is the last display frame inside it; frame 96 wraps to the start in the
Sequencer editor. Put an end key at 4 seconds if interpolation needs that
boundary, but do not use frame 96 as the visual end-state proof.

## Fresh structural verification

Do this in another tool call:

```lua
local seq = open_asset("/Game/Cinematics/SEQ_TemporalCube")
assert(seq)

local info = seq:info()
assert(info.display_rate == 24)
assert(info.tick_resolution == 24000)
assert(info.playback_start == 0)
assert(info.playback_end == 4)
assert(info.possessables == 2)
assert(info.camera_cuts == 1)

local channels = seq:list("channels", {
  binding = "TemporalCube",
  track_type = "3DTransform",
  track_index = 0,
  section_index = 0,
})
assert(#channels == 10)

-- Channel indices are zero-based. Location.Y is 1 and Location.Z is 2.
local y = seq:list("keyframes", {
  binding = "TemporalCube",
  track_type = "3DTransform",
  channel = 1,
  track_index = 0,
  section = 0,
})
assert(#y == 3)
assert(y[1].time == 0 and y[2].time == 2 and y[3].time == 4)
```

The transform channel order proven on UE 5.8 is:

| Index | Channel |
|---:|---|
| 0–2 | `Location.X`, `Location.Y`, `Location.Z` |
| 3–5 | `Rotation.X`, `Rotation.Y`, `Rotation.Z` |
| 6–8 | `Scale.X`, `Scale.Y`, `Scale.Z` |
| 9 | `Weight` |

Prefer `set_transforms()` for whole transforms. Use `add("keyframe", ...)` only
when a specific channel or a non-transform track requires it:

```lua
assert(seq:add("keyframe", {
  binding = "TemporalCube",
  track_type = "3DTransform",
  track_index = 0,
  section_index = 0,
  channel_index = 2,
  time = 1.25,
  value = 325,
  interp = "cubic",
}))
```

## Evaluate and capture multiple times

Open the sequence editor before using the editor blueprint library. Its
`SetCurrentTime` input is an integer display frame in UE 5.8:

```lua
local sequence = "/Game/Cinematics/SEQ_TemporalCube"
local level_path = "/Game/Maps/L_TemporalProof"
local lib = "/Script/LevelSequenceEditor.LevelSequenceEditorBlueprintLibrary"

assert(load_level(level_path))
assert(open_editor(sequence))
assert(invoke(lib, "SetCurrentTime", { NewFrame = 0 }))
assert(invoke(lib, "ForceUpdate"))

local actors = open_level():list("actors", { label = "TemporalCube" })
assert(#actors == 1)
print("frame0", actors[1].location.x, actors[1].location.y, actors[1].location.z)
print("rotation", actors[1].rotation.pitch, actors[1].rotation.yaw, actors[1].rotation.roll)
print("scale", actors[1].scale.x, actors[1].scale.y, actors[1].scale.z)

local function angle_delta_degrees(a, b)
  return math.abs(((a - b + 180) % 360) - 180)
end
assert(angle_delta_degrees(actors[1].rotation.yaw, 0) < 0.001)

screenshot({
  mode = "level",
  max_dimension = 1600,
  wait_for_ready_ms = 150,
  hide_overlays = true,
  location = { x = -1000, y = 0, z = 500 },
  rotation = { pitch = -22, yaw = 0, roll = 0 },
  fov = 60,
  view_mode = "lit",
})
```

Repeat in separate calls with `NewFrame = 48` and `NewFrame = 95`. Read the
returned images. Confirm gross movement, scale, and pose changes, and confirm the
fresh actor `location`, `rotation`, and `scale` tables change too. Do not accept
frame 0 alone or substitute stored key values for evaluated actor readback.
Rotator components are normalized by UE: for example, an interpolated authored
yaw of `301.875` can read back as `-58.125`. Compare angles modulo 360 with
`angle_delta_degrees`, not with raw numeric equality.

## Other common operations

```lua
-- Discover only track classes supported by this sequence.
local supported = seq:list("track_types")

-- Timeline markers use tick-resolution frame numbers, not display frames.
assert(seq:add("marked_frame", {
  frame = 48000, -- 2 seconds at 24000 ticks/sec
  label = "Apex",
  color = { hex = "#FFAA00FF" },
}))

-- Add a nested sequence.
assert(seq:add_subsequence({
  sequence_path = "/Game/Cinematics/SEQ_Insert",
  start_time = 1,
  end_time = 3,
  row_index = 0,
}))

-- Inspect the actual authored hierarchy and timing.
local dump = seq:list("bindings")
```

`configure("sequence", {tick_resolution=...})` migrates existing times; it does
not reinterpret the old frame numbers. Still verify marker and key times in a
fresh call after changing it.

## Failure modes

| Symptom | Cause and fix |
|---|---|
| `add("track")` succeeds, then indexing its result fails | Track creation returns boolean. Use `list("bindings")` or `list("channels")` for the created track. |
| Possessable binding fails | The actor label must already exist in the currently open level. Save the level first and use the exact label. |
| `create_level()` reports `expected string` | Pass the required content path: `create_level(path, opts)`. It returns success; get the handle with `open_level()`. |
| A non-WP create receipt is the only partition evidence | Reload the saved map and require `open_level():info().world_partition == false`. The field is read from the live UE world. |
| Camera FOV remains 90 | FOV is on `CameraComponent`. Use `configure_component(..., {property={FieldOfView="60.0"}})` and freshly read it with `get_component_properties`. |
| `configure("actor")` says name/label required | The signature is `level:configure("actor", label, params)`; the label is a separate second argument. |
| Keys exist but the actor never changes | Open the sequence editor, set an in-range display frame, call `ForceUpdate`, and inspect the same bound level. |
| Time changes but the actor remains at its first key | Freshly list the bound actor and require `mobility == "movable"`. Spawn it with `mobility = "movable"` or configure it before binding. |
| Location changes but evaluated scale seems unavailable | Fresh actor rows expose `actor.scale.{x,y,z}`. Re-list after every `ForceUpdate`; do not substitute stale sequence-key data. |
| An evaluated yaw above 180 reads back negative | UE normalizes Rotators. Compare modulo 360 with `abs(((actual - expected + 180) % 360) - 180)`, then apply a tolerance. |
| Frame 96 looks like frame 0 in a 4-second 24-fps sequence | Playback upper bounds are exclusive. Capture frame 95. |
| Empty or wrong channels | Discover with `list("channels", descriptor)` and use its zero-based `index`; do not guess channel order for non-transform tracks. |
| A fresh read disagrees with the mutation call | Trust the fresh call. Reopen the asset; locals and snapshots do not survive. |
| A failed call does not raise | NeoStack failures return `nil` and emit `[FAIL]`. Check every mutation result. |

## Discovery escape hatches

- `seq:help()` — full Sequencer verb and parameter catalog
- `seq:info()` — rates, ranges, binding/track/camera-cut counts
- `seq:list("track_types")` — track classes supported by this sequence
- `seq:list("bindings")` — binding, track, section, and timing dump
- `seq:list("channels", descriptor)` and `seq:list("keyframes", descriptor)`
- `class_methods("/Script/LevelSequenceEditor.LevelSequenceEditorBlueprintLibrary")`
- `report_issue("...")` — only after a reproducible API gap remains

Do not wrap `help()` in `log()`; it already prints.
