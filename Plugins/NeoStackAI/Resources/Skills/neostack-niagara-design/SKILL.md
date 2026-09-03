---
name: neostack-niagara-design
description: How to design Niagara VFX effects from intent — explosions, fire, smoke, sparks, auras, portals, beams, bullet impacts, tire smoke, water splashes, magic missiles, etc. Covers template-by-mood selection, the "delayed once" recipe, mild-vs-powerful dialing, color curve archetypes, multi-emitter composition, HDR/emissive feel, local-space attached effects, force modules, Light renderers, and genre playbooks (shooter / racing / swimming / magic / cinematic). Layers on top of `neostack-niagara` (mechanics) — read that first for binding details.
---

# Designing Niagara VFX

`neostack-niagara` is the mechanics — `add()`, `configure()`, `list()`, value modes, scratch-pad scripts. This skill is the craft: turning "make me a mild explosion 5 seconds in" into the right template + the right ~5 parameter changes that produce *that specific feel*.

## The shape of a designed effect

```lua
local ns = create_asset("/Game/VFX/NS_X", "/Script/Niagara.NiagaraSystem")

-- 1. Pick the template that fits the MOOD (table below)
ns:add("emitter", { name="Main",
  template_asset = "/Niagara/DefaultAssets/Templates/Emitters/<Template>.<Template>" })

-- 2. Set timing FIRST (Loop Behavior + Loop Delay + UseLoopDelay)
-- 3. Dial intensity (Spawn Count / Spawn Rate)
-- 4. Apply a COLOR CURVE if the effect should change color over particle lifetime
-- 5. Layer secondary emitters if needed (smoke under flash, debris under burst, motes around aura)
-- 6. Add forces if motion needs character (curl noise = swirl, vortex = spiral, drag = slow-down)
-- 7. Add a Light renderer if it should affect scene lighting
-- 8. Compile + save
ns:compile()
ns:save()
```

## The five rules nothing else matters more than

1. **Pick the template that matches the MOOD, not the literal verb.** "Explosion" isn't a template — `OmnidirectionalBurst` for the kinetic feel, `SimpleSpriteBurst` for a flash, `UpwardMeshBurst` for chunky debris. Reach for the look, not the noun.
2. **Mild vs powerful is a dial, not a different effect.** Same template, change Spawn Count and particle scale: 25 = puff, 80 = blast, 200 = catastrophic. Don't reach for a different template just because the request changed adjective.
3. **Color carries 60% of the read.** A muted `(0.6, 0.6, 0.6)` smoke and a saturated `(1.0, 0.4, 0.05)` ember can be the *exact same emitter*. The color curve is where mood lives — see archetypes below.
4. **Real explosions are 3 emitters minimum.** Flash (1 huge brief particle) + Smoke (50–80 slow) + Debris (10–20 mesh chunks). Single-emitter explosions read as "particle effect," not "explosion." Same applies to magic casts, splashes, impacts.
5. **HDR (>1.0 channels) is what makes things glow.** A "bright" cyan beam is `(R=0.4, G=2.5, B=4.0)`, not `(R=0, G=1, B=1)`. Used with additive materials on Sprite or Ribbon renderers, this is what reads as emissive. Without HDR, your beam looks painted.

## Template-by-mood matrix

These ship with the engine — pass the full path to `add("emitter", {template_asset=...})`.

| If the user wants… | Reach for | Why |
|---|---|---|
| Explosion / blast / boom | `Emitters/OmnidirectionalBurst` | Radial 360° spawn, gravity, drag — the "stuff flies outward and slows" pattern |
| Flash / pop / spark of light | `Emitters/SimpleSpriteBurst` | One bright sprite, fast lifetime — what reads as "snap of light" |
| Directional spray / cone | `Emitters/DirectionalBurst` | Spawn velocity in a cone — for muzzle flashes, blood spray, geyser |
| Confetti / celebration / debris shower | `Emitters/ConfettiBurst` | Multi-color rotating sprites, gravity, drag |
| Mesh debris / rubble | `Emitters/UpwardMeshBurst` | Pre-wired mesh renderer; just swap mesh + scale + count |
| Fountain / continuous spawn | `Emitters/Fountain` | Continuous spawn rate, gravity, simple lifetime — base for fire, water spray, ember stream |
| Atmospheric / dust / drifting | `Emitters/HangingParticulates` | Slow ambient particles with subtle motion — base for fog, embers, snow, magic motes |
| Looping single particle | `Emitters/SingleLoopingParticle` | One particle that loops infinitely — useful for orbs, swirling auras |
| Energy beam / laser | `Emitters/DynamicBeam` or `Emitters/StaticBeam` | Pre-wired ribbon renderer between two points |
| Trail behind a moving point | `Emitters/LocationBasedRibbon` | Ribbon that follows the emitter location — bullet trails, magic missile tails |
| Empty starter | `Emitters/Minimal` | Almost nothing wired — only when you want to build from scratch |

When unsure, start with **Fountain** for continuous and **OmnidirectionalBurst** for one-shot. Both are easiest to reskin.

## The "delayed once" recipe (the most-asked failure case)

> "Make me a mild explosion 5 seconds after activation."

Wire **three parameters on `EmitterState`** in one configure call:

```lua
ns:add("emitter", { name="Burst",
  template_asset = "/Niagara/DefaultAssets/Templates/Emitters/OmnidirectionalBurst.OmnidirectionalBurst" })

ns:configure("module", "EmitterState", {
  emitter = "Burst", stage = "EmitterUpdate",
  parameters = {
    UseLoopDelay   = {value="true"},   -- enables the gate
    ["Loop Delay"] = 5.0,               -- seconds before the (first) loop fires
    ["Loop Behavior"] = "Once",         -- fire exactly one time
  },
})
```

All three are needed. `Loop Delay = 5.0` alone does nothing without `UseLoopDelay = true`. `Loop Behavior = "Once"` is the difference between "fires once after 5s" and "fires every 5s forever."

For other timing patterns:

| Want | Loop Behavior | UseLoopDelay | Loop Delay | Loop Duration |
|---|---|---|---|---|
| Fires immediately, once | `Once` | false | — | doesn't matter |
| Fires after N seconds, once | `Once` | true | N | doesn't matter |
| Fires every N seconds forever | `Multiple` | true | N | (per-loop length) |
| Continuous emission forever | `Infinite` | false | — | — |
| Burst every N seconds, K times | `Multiple` + `UseLoopCountLimit=true` + `Loop Count Limit=K` | true | N | — |

## Mild vs powerful — the dial

Same template, different feel. The four knobs that matter most:

| Knob | Where | Mild | Powerful |
|---|---|---|---|
| Spawn Count (burst) | `SpawnBurst_Instantaneous` | 15–30 | 100–250 |
| Spawn Rate (continuous) | `SpawnRate` | 5–20/sec | 100–500/sec |
| Particle scale | `InitializeParticle.SpriteSize` or `MeshScale` | small (~10–30 unit) | large (~100–300 unit) |
| Color intensity (HDR) | Color or color curve | A=0.7–1.0, RGB ≤ 1.0 | A=1.0, RGB > 1.0 (e.g. 4.0 cyan) |

Lifetime is usually the wrong knob — long-lifetime mild effects look like *weak versions of the same thing*, not "mild." Keep lifetime in the 0.5–2s range and dial the count + size.

## Color curve archetypes

A good color curve has **3–5 keys**, alpha goes from low → high → low (so particles fade in *and* out), and the dominant hue shifts to suggest energy decay. Copy these as starting points:

```lua
-- Fire / ember (warm, decaying)
ColorCurve = { mode="color_curve", keys={
  {time=0.00, color={r=1.0, g=0.85, b=0.40, a=0.0}},   -- warm dim, invisible
  {time=0.15, color={r=1.0, g=0.55, b=0.10, a=1.0}},   -- bright orange peak
  {time=0.55, color={r=0.8, g=0.30, b=0.05, a=0.8}},   -- amber
  {time=1.00, color={r=0.2, g=0.10, b=0.02, a=0.0}},   -- fade to dark
}}

-- Magic / arcane (cool, pulsing)
ColorCurve = { mode="color_curve", keys={
  {time=0.0, color={r=0.5, g=0.9, b=1.0, a=0.2}},      -- dim cyan
  {time=0.4, color={r=0.6, g=0.4, b=1.0, a=1.0}},      -- bright magenta
  {time=1.0, color={r=0.2, g=0.1, b=0.4, a=0.0}},      -- fade dark purple
}}

-- Smoke (neutral, slow)
ColorCurve = { mode="color_curve", keys={
  {time=0.0, color={r=0.4, g=0.4, b=0.4, a=0.0}},      -- dark, invisible
  {time=0.2, color={r=0.5, g=0.5, b=0.5, a=0.6}},      -- mid gray peak
  {time=1.0, color={r=0.7, g=0.7, b=0.7, a=0.0}},      -- light gray, faded
}}

-- Blood / impact (dark to bright)
ColorCurve = { mode="color_curve", keys={
  {time=0.0, color={r=0.3, g=0.02, b=0.02, a=1.0}},
  {time=0.3, color={r=0.6, g=0.05, b=0.05, a=0.9}},
  {time=1.0, color={r=0.15, g=0.0, b=0.0, a=0.0}},
}}

-- Electric / energy beam (pure HDR, very saturated)
ColorCurve = { mode="color_curve", keys={
  {time=0.0, color={r=0.3, g=2.0, b=4.0, a=0.0}},      -- HDR cyan, dim
  {time=0.5, color={r=0.6, g=3.0, b=5.0, a=1.0}},      -- HDR cyan, full
  {time=1.0, color={r=0.1, g=0.5, b=1.0, a=0.0}},      -- fade
}}

-- Water / splash (white-blue, brief)
ColorCurve = { mode="color_curve", keys={
  {time=0.0, color={r=0.8, g=0.95, b=1.0, a=0.0}},
  {time=0.2, color={r=0.95, g=0.98, b=1.0, a=0.9}},    -- white peak
  {time=1.0, color={r=0.6, g=0.8, b=0.95, a=0.0}},     -- fade blue
}}
```

Apply a curve via the **`ScaleColor` module** in `ParticleUpdate`:

```lua
ns:configure("module", "ScaleColor", {
  emitter="Main", stage="ParticleUpdate",
  parameters = { ColorCurve = <one of the above> },
})
```

## Multi-emitter composition

Single-emitter effects look thin. The pattern that consistently reads as cinematic:

| Effect | Layer 1 (foreground) | Layer 2 (mid) | Layer 3 (background) |
|---|---|---|---|
| Explosion | Flash (1 huge brief sprite) | Debris (mesh, kinetic) | Smoke (50–80, slow drift) |
| Magic cast | Aura sprite (1 looping) | Cast burst (sprite, brief) | Rising motes (HangingParticulates) |
| Tire smoke trail | Smoke (continuous, local-space) | Sparks (occasional burst) | Dust (sprite, low alpha) |
| Bullet impact | Sparks (mesh, fast burst) | Smoke (small, brief) | Light renderer (very brief flash) |
| Splash / water entry | Splash drops (mesh particles) | Mist (sprite, slow) | Foam ring (ribbon) |
| Portal | Inner glow (sprite, looping) | Ribbon ring (rotating) | Rising motes (HangingParticulates) |

Wire each as a separate emitter on the same system. Set them all to the same `Loop Behavior` (Once for impacts, Infinite for ambient). The eye reads the composite as one effect.

## HDR for emissive feel

Anything that should *glow* (beams, magic, electricity, hot fire, neon) needs HDR color values on additive renderers. A regular `(R=0, G=1, B=1, A=1)` cyan looks painted; `(R=0.4, G=2.5, B=4.0, A=1)` blooms.

```lua
-- On the Color module (or InitializeParticle.Color)
parameters = { Color = { r=0.4, g=2.5, b=4.0, a=1.0 } }
```

The renderer needs to be using an additive material for HDR to actually bloom. Default sprite material in Niagara templates is usually translucent, not additive — verify by checking the bloom/post-process result. If it's not glowing, switch the renderer's material to one that uses additive blending.

## Local-space and motion-following

For effects attached to a moving actor (vehicle exhaust, character trail, weapon glow), set the emitter to local space:

```lua
ns:configure("emitter", "Main", {
  properties = { bLocalSpace = true },
})
```

Local space means particles spawn and move *relative to the emitter*, so when the actor moves, the existing particles move with it (instead of being left behind). For trails that should be left behind (skid marks, smoke trails), keep `bLocalSpace = false`.

## Force modules — adding character to motion

Default templates have basic gravity + drag. Add these from the 192-module library to give motion more feel:

```lua
ns:add("module", {
  emitter = "Main", stage = "ParticleUpdate",
  path = "/Niagara/Modules/Update/Forces/V2/CurlNoiseForce.CurlNoiseForce",
})
```

| Force | Path | Use for |
|---|---|---|
| `CurlNoiseForce` | `/Niagara/Modules/Update/Forces/V2/CurlNoiseForce.CurlNoiseForce` | Turbulent / swirly motion (smoke, fog, dust) |
| `VortexForce` | `/Niagara/Modules/Update/Forces/.../VortexForce.VortexForce` | Spiral around an axis (tornadoes, magic vortexes) |
| `PointAttractionForce` | `/Niagara/Modules/Update/Forces/.../PointAttractionForce.PointAttractionForce` | Pull particles toward a point (gathering effects) |
| `LineAttractionForce` | `/Niagara/Modules/Update/Forces/.../LineAttractionForce.LineAttractionForce` | Pull along an axis (beam confinement) |
| `WindForce` | `/Niagara/Modules/Update/Forces/.../WindForce.WindForce` | Directional drift (atmospheric) |
| `Drag` | already in most templates | Slowdown — INCREASE for thick smoke, DECREASE for free debris |

For paths, use `ns:list("available_modules", {emitter, stage})` and read the `path` field — full paths vary slightly between UE versions.

## Light renderer — explosions that light the scene

A burst-with-light-renderer reads dramatically more "real" than a burst alone, because the ground actually brightens for a frame:

```lua
ns:add("renderer", { emitter="Burst", type="Light" })
```

The Light renderer particle attaches a UE Point Light to each particle. For an explosion, configure the light to:

- Be very brief (`Lifetime` ~0.2s on the particles)
- Have high intensity
- Match the warm orange of the explosion

The Light renderer is what separates "muzzle flash" from "muzzle flash that lights the wall."

## User parameters for runtime control

Effects you want gameplay to drive (charge level, spell power, boost intensity) need user parameters:

```lua
ns:add("user_parameter", { name="Intensity", type="Float", default=1.0 })
```

Then bind a module input to it via `linked` mode:

```lua
ns:configure("module", "SpawnRate", {
  emitter="Main", stage="EmitterUpdate",
  parameters = { SpawnRate = { mode="linked", parameter="User.Intensity" } },
})
```

At runtime, blueprint code calls `Set Niagara Variable (Float)` on the spawned NiagaraComponent with name `Intensity` to scale the effect live.

Common runtime parameters worth exposing:

| Param | Type | Drives |
|---|---|---|
| `Intensity` | Float | spawn rate / count / scale |
| `Color` | LinearColor | base tint |
| `Direction` | Vector | velocity direction (for projectile-direction-aware effects) |
| `Lifetime` | Float | particle lifetime override |
| `Charge` | Float | curve sample position (for charge-up effects) |

## Genre playbooks

### Shooter

| Effect | Recipe |
|---|---|
| Muzzle flash | `SimpleSpriteBurst` (1 particle, 0.05s lifetime) + brief Light renderer + HDR warm color |
| Bullet impact spark | `OmnidirectionalBurst` cone, mesh-particles via `UpwardMeshBurst` mesh swap to small chunks, brief Light, ember color curve |
| Tracer round | `LocationBasedRibbon` with HDR color, attached to projectile (local-space + bLocalSpace=true) |
| Smoke grenade | `HangingParticulates` infinite + `CurlNoiseForce` + smoke color curve, low spawn rate (8/sec), long lifetime (8–15s) |
| Blood splatter | `DirectionalBurst` cone, mesh particles (small spheres), gravity, blood color curve |
| Big explosion | Flash + Smoke + Debris + Light + Shockwave (4 emitters, all Once) |

### Racing

| Effect | Recipe |
|---|---|
| Tire smoke (drift) | `HangingParticulates` infinite, `bLocalSpace=true`, `CurlNoiseForce`, neutral gray color curve, spawn rate scaled by tire speed (linked user param) |
| Boost flames | `Fountain` infinite, additive HDR cyan/orange curve, cone velocity, `bLocalSpace=true` |
| Exhaust | `Fountain` low rate, dark gray fading curve, slight upward velocity |
| Spark on collision | `OmnidirectionalBurst` Once, mesh tiny chunks, `Light` renderer, brief lifetime |
| Dust kick-up | `DirectionalBurst` Once, mesh rocks, gravity, brown color curve |

### Swimming / water

| Effect | Recipe |
|---|---|
| Bubble rise | `Fountain` infinite, `GravityForce` set to -980 (negative = buoyant), white-cyan color curve |
| Surface splash | `DirectionalBurst` Once, sprite particles, `Drag` high for spray feel, water color curve |
| Underwater god rays | `Light` renderer + thin blue ribbon, very low alpha, slow drift |
| Foam wake | `LocationBasedRibbon` along surface, white color, fades over time |

### Magic / RPG

| Effect | Recipe |
|---|---|
| Aura ring | `Fountain` infinite + `HangingParticulates` infinite (motes), magic color curve, looping |
| Magic missile trail | `LocationBasedRibbon` HDR magic color, attached to projectile |
| Portal | `Fountain` ring + ribbon ring rotating + rising motes (3 emitters, all Infinite) |
| Cast burst | `SimpleSpriteBurst` Once + `Light` renderer + brief HDR color |
| Healing aura | `Fountain` infinite low-rate, soft warm-green color curve, `bLocalSpace=true` (follows caster) |

### Cinematic / atmospheric

| Effect | Recipe |
|---|---|
| Drifting embers | `HangingParticulates` infinite, `WindForce`, ember color curve, low rate (8/sec) |
| Atmospheric fog | `HangingParticulates` infinite, `CurlNoiseForce`, neutral gray color, very long lifetime |
| Falling leaves / snow | `Fountain` inverted, mesh leaf particles, `WindForce`, slow rotation |
| Dust motes (in light shaft) | `HangingParticulates` infinite, very low alpha, very slow motion, near-stationary |

## End-to-end mini example — bullet impact spark

```lua
local ns = create_asset("/Game/VFX/NS_BulletImpact", "/Script/Niagara.NiagaraSystem")

-- Sparks: directional outward burst (kinetic)
ns:add("emitter", { name="Sparks",
  template_asset = "/Niagara/DefaultAssets/Templates/Emitters/OmnidirectionalBurst.OmnidirectionalBurst" })
ns:configure("module", "EmitterState", {
  emitter="Sparks", stage="EmitterUpdate",
  parameters = { ["Loop Behavior"] = "Once" },
})
ns:configure("module", "SpawnBurst_Instantaneous", {
  emitter="Sparks", stage="EmitterUpdate",
  parameters = { ["Spawn Count"] = 18 },
})
ns:configure("module", "ScaleColor", {
  emitter="Sparks", stage="ParticleUpdate",
  parameters = {
    ColorCurve = { mode="color_curve", keys={
      {time=0.00, color={r=1.5, g=1.2, b=0.4, a=0.0}},   -- HDR warm, dim
      {time=0.10, color={r=1.5, g=0.9, b=0.2, a=1.0}},   -- HDR ember peak
      {time=0.50, color={r=0.8, g=0.3, b=0.05, a=0.7}},
      {time=1.00, color={r=0.1, g=0.05, b=0.0, a=0.0}},
    }},
  },
})

-- Smoke: brief small puff
ns:add("emitter", { name="Smoke",
  template_asset = "/Niagara/DefaultAssets/Templates/Emitters/OmnidirectionalBurst.OmnidirectionalBurst" })
ns:configure("module", "EmitterState", {
  emitter="Smoke", stage="EmitterUpdate",
  parameters = { ["Loop Behavior"] = "Once" },
})
ns:configure("module", "SpawnBurst_Instantaneous", {
  emitter="Smoke", stage="EmitterUpdate",
  parameters = { ["Spawn Count"] = 12 },
})
ns:configure("module", "ScaleColor", {
  emitter="Smoke", stage="ParticleUpdate",
  parameters = {
    ColorCurve = { mode="color_curve", keys={
      {time=0.0, color={r=0.4, g=0.4, b=0.4, a=0.0}},
      {time=0.2, color={r=0.5, g=0.5, b=0.5, a=0.5}},
      {time=1.0, color={r=0.7, g=0.7, b=0.7, a=0.0}},
    }},
  },
})

-- Light renderer on Sparks for that "lights the wall" feel
ns:add("renderer", { emitter="Sparks", type="Light" })

ns:compile()
ns:save()
```

3 emitters (would be 4 with mesh debris on a hard surface), color curves, light renderer, ~30 lines of Lua. Compiles clean, reads as a real impact.

## Anti-patterns (the AI-slop checklist)

| Don't | Do |
|---|---|
| Single-emitter explosions | Always 3+ emitters: flash, smoke, debris (+ light) |
| LDR `(0,1,1)` for "glowing" cyan | HDR `(0.4, 2.5, 4.0)` on additive material |
| Same color all lifetime | Color curve with 3–5 keys, alpha fade in + out |
| Long lifetime to dial down intensity | Reduce Spawn Count instead — keep lifetime tight (0.5–2s for impacts) |
| Default sprite size | Set explicitly via `InitializeParticle.SpriteSize` — defaults are arbitrary |
| Setting `Loop Delay` without `UseLoopDelay` | Both required, else delay is ignored |
| Reaching for new templates per request | Same template + different parameters covers 80% of asks |
| Forgetting `bLocalSpace=true` for vehicle/character-attached effects | Causes particles to lag behind the moving actor |
| Skipping the Light renderer on impacts/explosions | Major loss of "feels real" — the scene-lighting is half the reason cinematic VFX work |
| Hand-tuning HLSL with `EngineTime` | Doesn't compile — Niagara HLSL has restricted variable scope. Use User parameters driven from blueprint, or particle-side attributes |

## Discovery escape hatches

When you don't know what to dial:

- `ns:list("emitter_templates")` — the 49 ship-with-engine templates by friendly name
- `ns:list("available_modules", {emitter, stage})` — every module that can be added at this stage (192+)
- `ns:list("module_inputs", {emitter, stage, module_name})` — what to dial on this module
- `ns:get("module", {…})` — current state including default values
- `ns:get("emitter", "X")` — emitter properties including SimTarget, bLocalSpace, etc.
- `ns:list("renderer_types", {emitter})` — discoverable renderer types
- `ns:info()` — counts (emitters, modules, renderers, user_params) — fastest sanity check

## What this skill stops at

For wiring, lifecycle methods, the verification-in-fresh-script rule, advanced static-switch and value-mode forms, scratch-pad authoring, versioning, and event handler / simulation stage configurer signatures — see **`neostack-niagara`** (mechanics).

This skill is the *taste*. That one is the *toolkit*.
