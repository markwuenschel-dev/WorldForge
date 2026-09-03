---
name: neostack-metasound
description: Author and objectively verify Unreal MetaSound Sources and Patches through execute_script. Use when the user asks for MetaSound audio graphs, oscillator sources, output formats, DSP measurements, channel proof, or rendered WAV evidence.
---

# MetaSound authoring

Everything below is Lua for `execute_script`. Start with
`metasound_authoring()`. The reliable source workflow is:

1. Build to a fresh `/Game/...` asset path.
2. Inspect the returned document shape.
3. Save the created asset.
4. Reopen and inspect it in a fresh tool call.
5. Render it through UE's sound generator.
6. Require finite, nonzero metrics for every channel, validate the PCM16 WAV
   header and file size, and compare measured frequency when pitch matters.

A valid graph and a clean editor compile are not audio proof. Use
`render_source`; it fails instead of returning a proof table when the rendered
signal or any requested output channel is silent or non-finite.

## Build two distinguishable sources

Choose a unique alphanumeric run token and keep it across the following calls.
Do not reuse a path: `build_source` rejects an existing destination before the
asset tools can show an overwrite modal.

```lua
local run = "MS_Example_482913" -- replace with a unique token
local low_path = "/Game/Audio/" .. run .. "_440"
local high_path = "/Game/Audio/" .. run .. "_880"
local ms = metasound_authoring()
assert(ms)

local low = ms:build_source(low_path, {
  frequency_input = "ProofFrequency",
  frequency = 440.0,
  output_format = "Stereo",
  sample_rate = 48000,
  block_rate = 100.0,
  one_shot = false,
  frequency_display_name = "Proof Frequency",
  frequency_advanced = false,
  sine_comment = "440 Hz proof oscillator",
  sine_comment_visible = true,
  sine_x = 180,
  sine_y = 80,
})
assert(low)
assert(low.asset_class == "MetaSoundSource")
assert(low.output_format == "Stereo")
assert(low.input_count >= 1)
assert(low.output_count >= 2)
assert(low.edge_count >= 3) -- frequency edge plus both audio output edges

local high = ms:build_source(high_path, {
  frequency_input = "ProofFrequency",
  frequency = 880.0,
  output_format = "Stereo",
  sample_rate = 48000,
  block_rate = 100.0,
  one_shot = false,
  frequency_display_name = "Proof Frequency",
  frequency_advanced = false,
  sine_comment = "880 Hz proof oscillator",
  sine_comment_visible = true,
})
assert(high and high.output_format == "Stereo")

local low_asset = open_asset(low_path)
local high_asset = open_asset(high_path)
assert(low_asset and low_asset:save())
assert(high_asset and high_asset:save())

print("created", low_path, high_path)
```

`build_source(path, opts)` requires the options table and returns a document-info
table or `nil`. Its source-specific fields include `asset_class`,
`output_format`, `quality`, `block_rate_override`, and
`sample_rate_override`. Common document fields include `asset_name`,
`asset_path`, `class_name`, `input_count`, `output_count`, `node_count`,
`edge_count`, `variable_count`, `page_count`, `inputs`, `outputs`, and `nodes`.

The source graph contains a float graph input connected to a native
`UE:Sine:Audio` node. The sine output is connected to every audio output created
for the requested format; it is not enough to set `output_format` without those
edges.

Supported `output_format` values are `Mono`, `Stereo`, `Quad`, `FiveDotOne`
(`5.1`), and `SevenDotOne` (`7.1`). Unknown values return `nil`; they do not
silently fall back to Mono. Defaults are frequency `220`, format `Mono`,
sample rate `48000`, block rate `100`, and `one_shot=true`.

## Verify serialized graph state in a fresh call

Re-enter the same unique run token:

```lua
local run = "MS_Example_482913"
local low_path = "/Game/Audio/" .. run .. "_440"
local high_path = "/Game/Audio/" .. run .. "_880"
local ms = metasound_authoring()

local function find_named(rows, name)
  for _, row in ipairs(rows or {}) do
    if row.name == name then return row end
  end
end

local low = ms:info(low_path)
local high = ms:info(high_path)
assert(low and low.valid and high and high.valid)
assert(low.asset_class == "MetaSoundSource")
assert(low.output_format == "Stereo" and high.output_format == "Stereo")
assert(low.edge_count >= 3 and high.edge_count >= 3)

local low_frequency = find_named(low.inputs, "ProofFrequency")
local high_frequency = find_named(high.inputs, "ProofFrequency")
assert(low_frequency and low_frequency.type == "Float")
assert(high_frequency and high_frequency.type == "Float")
assert(math.abs(low_frequency.default.value - 440.0) < 0.01)
assert(math.abs(high_frequency.default.value - 880.0) < 0.01)
assert(low_frequency.display_name == "Proof Frequency")
assert(low_frequency.advanced_display == false)
```

`info(path)` accepts a long package path or object path and returns the same
document-info shape, or `nil` when the path is invalid or is not a MetaSound
asset. Inputs and outputs are one-based arrays. An input's `default` is a table
with `type`, `text`, `array_count`, and, for supported literal types, `value`.

## Render and prove every channel

`render_source(path, opts?)` accepts an optional options table. With no table,
it uses 48000 Hz, 1024 block frames, 0.25 seconds, and a 5-second compile
timeout. This example specifies the measurement controls so the two sources
differ only in their authored frequency:

```lua
local run = "MS_Example_482913"
local low_path = "/Game/Audio/" .. run .. "_440"
local high_path = "/Game/Audio/" .. run .. "_880"
local ms = metasound_authoring()

local render_opts = {
  sample_rate = 48000,
  block_frames = 1024,
  duration_seconds = 0.25,
  compile_timeout_seconds = 5.0,
}

local low = ms:render_source(low_path, render_opts)
local high = ms:render_source(high_path, render_opts)
assert(low and high)

local function verify_stereo_pcm16(proof)
  assert(proof.sample_rate == 48000)
  assert(proof.channels == 2)
  assert(proof.frame_count == 12000)
  assert(proof.sample_count == proof.frame_count * proof.channels)
  assert(proof.finite_samples == proof.sample_count)
  assert(proof.nonzero_samples > 1000)
  assert(proof.peak > 0.5 and proof.rms > 0.5)

  assert(proof.channel_metric_count == proof.channels)
  for channel_index = 1, proof.channels do
    local channel = proof.channel_metrics[channel_index]
    assert(channel and channel.channel == channel_index)
    assert(channel.finite_samples == proof.frame_count)
    assert(channel.nonzero_samples > 1000)
    assert(channel.peak > 0.5 and channel.rms > 0.5)
  end

  assert(proof.wav_header_bytes == 44)
  assert(proof.wav_header_channels == proof.channels)
  assert(proof.wav_header_sample_rate == proof.sample_rate)
  assert(proof.wav_header_bits_per_sample == 16)
  assert(proof.wav_pcm_data_bytes == proof.sample_count * 2)
  assert(proof.wav_byte_count ==
    proof.wav_header_bytes + proof.wav_pcm_data_bytes)

  local wav = file_info(proof.wav_path)
  assert(wav and wav.exists)
  assert(wav.size == proof.wav_byte_count)
end

verify_stereo_pcm16(low)
verify_stereo_pcm16(high)

assert(math.abs(low.estimated_frequency_hz - 440.0) <= 6.0)
assert(math.abs(high.estimated_frequency_hz - 880.0) <= 6.0)
assert(high.estimated_frequency_hz > low.estimated_frequency_hz * 1.9)

print("low_wav", low.wav_path, "measured_hz", low.estimated_frequency_hz)
print("high_wav", high.wav_path, "measured_hz", high.estimated_frequency_hz)
```

The proof table contains:

- Render shape: `sample_rate`, `channels`, `frame_count`, `sample_count`
- Whole signal: `finite_samples`, `nonzero_samples`, `peak`, `rms`,
  `positive_crossings`, `estimated_frequency_hz`
- Per-channel signal: `channel_metric_count`, `channel_metrics`; each channel
  has `channel`, `finite_samples`, `nonzero_samples`, `peak`, and `rms`
- WAV evidence: `wav_path`, `wav_byte_count`, `wav_header_bytes`,
  `wav_header_channels`, `wav_header_sample_rate`,
  `wav_header_bits_per_sample`, and `wav_pcm_data_bytes`

Frames count time steps; samples are interleaved channel values. Therefore a
stereo render has `sample_count == frame_count * 2`. The WAV is written under
the project's `Saved/NeoStackAI/MetaSound` directory with a unique filename.

Valid render bounds are:

| Option | Allowed | Default |
|---|---:|---:|
| `sample_rate` | 8000–192000 | 48000 |
| `block_frames` | 64–8192 | 1024 |
| `duration_seconds` | 0.05–5.0 | 0.25 |
| `compile_timeout_seconds` | 0.1–30.0 | 5.0 |

## Build a float pass-through patch

Use `build_patch(path, opts)` when the requested asset is a patch rather than a
playable source:

```lua
local ms = metasound_authoring()
local info = ms:build_patch("/Game/Audio/MS_ControlPatch_482913", {
  input = "Control",
  output = "Result",
  variable = "StoredValue",
  default = 0.625,
  output_default = 0.0,
  variable_default = 0.875,
  input_display_name = "Control",
  output_display_name = "Result",
  input_advanced = false,
  output_advanced = false,
  input_comment = "Pass-through control",
  input_comment_visible = true,
  input_x = -450,
  input_y = -120,
})
assert(info and info.asset_class == "MetaSoundPatch")
assert(info.input_count == 1 and info.output_count == 1)
assert(info.edge_count >= 1 and info.variable_count == 1)
local asset = open_asset("/Game/Audio/MS_ControlPatch_482913")
assert(asset and asset:save())
```

`render_source` only accepts a `MetaSoundSource`; a patch is document data, not
a directly playable sound source.

## Failure modes

| Symptom | Cause and fix |
|---|---|
| `build_source` or `build_patch` returns `nil` on a plausible path | The destination already exists, or the long package/object path is malformed. Choose a fresh `/Game/...` path. |
| An unknown format creates Mono | It does not: valid formats are the exact set above. Check the `nil` return and `[FAIL]` text. |
| The source looks correct but emits nothing | Do not accept document counts. Call `render_source`; it rejects a silent or non-finite whole signal and rejects each silent channel independently. |
| Stereo reports two outputs but one side is missing | Require both `channel_metrics[1]` and `[2]` to have one finite sample per frame and nonzero peak/RMS. |
| The WAV exists but may be stale or truncated | Use the unique returned `wav_path`; require its on-disk size to equal `wav_byte_count`, and verify header, channel, rate, PCM16, and data-byte fields. |
| 440 Hz and 880 Hz produce indistinguishable evidence | Hold render options fixed and compare `estimated_frequency_hz`; require the high result to be about twice the low result. |
| Asset disappears after restart | Builders mark the package dirty but do not save it. Open the created asset and call `:save()`. |
| `render_source` returns `nil` after a slow compile | Read `[FAIL]`; only increase `compile_timeout_seconds` within 0.1–30 seconds after confirming the graph genuinely needs it. |
| Sample count seems twice the expected duration | `sample_count` is interleaved across channels. Use `frame_count` for duration. |
| A failed call does not raise | NeoStack failures return `nil` and emit `[FAIL]`. Check every return value. |

## Discovery escape hatches

- `help("MetaSound")` — registered entry points and signatures
- `metasound_authoring():info(path)` — serialized frontend document state
- `open_asset(path):info()` — generic asset metadata
- `file_info(proof.wav_path)` — independent existence and byte-size readback
- `report_issue("...")` — only after an exact reproducible API gap remains

Do not wrap `help()` in `log()`; it already prints.
