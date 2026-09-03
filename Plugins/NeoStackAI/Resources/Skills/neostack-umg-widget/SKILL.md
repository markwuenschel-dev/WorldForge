---
name: neostack-umg-widget
description: Build, style, wire, inspect, and verify Unreal UMG Widget Blueprints through `execute_script`. Use for HUDs, menus, inventory screens, dialogs, dashboards, WidgetBlueprint trees, CanvasPanel layout, widget properties and slots, button events, property bindings, widget animations, named slots, or visual UMG screenshot verification.
---

# Authoring UMG Widget Blueprints

Use `create_asset(path, "WidgetBlueprint")` for a new widget or
`open_asset(path)` for an existing one. Both return a Blueprint table enriched
with widget-tree, binding, animation, and visual-layout methods.

Each `execute_script` call starts a fresh Lua state. Re-open the asset at the
start of every call. Persist with `bp:compile()` and `bp:save()`, then verify in
a separate call.

## Working sequence

1. Create the root and widget tree.
2. Configure widget properties and parent-slot layout.
3. Add variables, events, bindings, or animations.
4. Compile and save.
5. Re-open in a fresh script and inspect the stored state.
6. Capture `screenshot({mode="asset", asset=path})` and read the image.

Do not infer success from a clean compile alone. UMG can compile while
rendering empty, clipped, off-screen, or with the wrong scale.

## End-to-end HUD workflow

Run the following scripts in order.

### 1. Build, style, and add mechanics

```lua
local path = "/Game/UI/WBP_FieldRelay"
local bp = create_asset(path, "WidgetBlueprint")

local ACCENT = "(R=0.95,G=0.42,B=0.08,A=1)"
local FG     = "(R=0.91,G=0.93,B=0.94,A=1)"
local MUTED  = "(R=0.43,G=0.47,B=0.52,A=1)"
local VOID   = "(R=0.012,G=0.016,B=0.022,A=1)"
local PANEL  = "(R=0.026,G=0.034,B=0.046,A=0.98)"
local MONO   = "/Engine/EngineFonts/DroidSansMono.DroidSansMono"
local SANS   = "/Engine/EngineFonts/Roboto.Roboto"

-- A fresh WidgetBlueprint has no root.
bp:add_widget("CanvasPanel", {name="Root"})

-- Canvas decoration and content are siblings so ZOrder is explicit.
bp:add_widget("Border", {name="Void", parent="Root"})
bp:configure_widget("Void", {
  BrushColor = VOID,
  slot = {
    LayoutData = "(Anchors=(Minimum=(X=0,Y=0),Maximum=(X=1,Y=1)),"
      .. "Offsets=(Left=0,Top=0,Right=0,Bottom=0),Alignment=(X=0,Y=0))",
    ZOrder = 0,
  },
})

bp:add_widget("Border", {name="SignalRail", parent="Root"})
bp:configure_widget("SignalRail", {
  BrushColor = ACCENT,
  slot = {
    LayoutData = "(Anchors=(Minimum=(X=0,Y=0),Maximum=(X=0,Y=1)),"
      .. "Offsets=(Left=36,Top=36,Right=4,Bottom=36),Alignment=(X=0,Y=0))",
    ZOrder = 2,
  },
})

bp:add_widget("Border", {name="Shell", parent="Root"})
bp:configure_widget("Shell", {
  BrushColor = PANEL,
  Padding = "(Left=54,Top=46,Right=54,Bottom=46)",
  slot = {
    LayoutData = "(Anchors=(Minimum=(X=0,Y=0),Maximum=(X=1,Y=1)),"
      .. "Offsets=(Left=60,Top=36,Right=48,Bottom=36),Alignment=(X=0,Y=0))",
    ZOrder = 1,
  },
})

bp:add_widget("VerticalBox", {name="Main", parent="Shell"})

bp:add_widget("Spacer", {name="Headroom", parent="Main"})
bp:configure_widget("Headroom", {Size="(X=0,Y=5)"})

bp:add_widget("TextBlock", {name="Eyebrow", parent="Main"})
bp:configure_widget("Eyebrow", {
  Text = "FIELD OPS  //  LIVE TELEMETRY",
  Font = {FontObject=MONO, Size=11, LetterSpacing=280},
  ColorAndOpacity = "(SpecifiedColor=" .. ACCENT .. ")",
  slot = {Padding={bottom=12}},
})

bp:add_widget("TextBlock", {name="Hero", parent="Main"})
bp:configure_widget("Hero", {
  Text = "ORBITAL RELAY",
  Font = {FontObject=MONO, Size=58, LetterSpacing=-28},
  ColorAndOpacity = "(SpecifiedColor=" .. FG .. ")",
  slot = {Padding={bottom=4}},
})

bp:add_widget("TextBlock", {name="Deck", parent="Main"})
bp:configure_widget("Deck", {
  Text = "SECTOR 18-K  /  UPLINK WINDOW 00:47",
  Font = {FontObject=SANS, TypefaceFontName="Light", Size=17},
  ColorAndOpacity = "(SpecifiedColor=" .. MUTED .. ")",
  slot = {Padding={bottom=28}},
})

bp:add_widget("TextBlock", {name="ProgressLabel", parent="Main"})
bp:configure_widget("ProgressLabel", {
  Text = "UPLINK STABILITY",
  Font = {FontObject=MONO, Size=10, LetterSpacing=240},
  ColorAndOpacity = "(SpecifiedColor=" .. ACCENT .. ")",
  slot = {Padding={bottom=8}},
})

bp:add_widget("ProgressBar", {
  name="Stability", parent="Main", is_variable=true,
})
bp:configure_widget("Stability", {
  Percent = 0.87,
  FillColorAndOpacity = ACCENT,
  slot = {Padding={bottom=30}},
})

bp:add_widget("Button", {
  name="EngageBtn", parent="Main", is_variable=true,
})
bp:configure_widget("EngageBtn", {
  BackgroundColor = "(R=0.18,G=0.075,B=0.018,A=1)",
  slot = {HorizontalAlignment="HAlign_Left"},
})

bp:add_widget("TextBlock", {name="EngageLabel", parent="EngageBtn"})
bp:configure_widget("EngageLabel", {
  Text = "ENGAGE RELAY  //  01",
  Font = {FontObject=MONO, Size=13, LetterSpacing=160},
  ColorAndOpacity = "(SpecifiedColor=" .. FG .. ")",
  slot = {
    Padding={left=24,top=14,right=24,bottom=14},
    HorizontalAlignment="HAlign_Center",
    VerticalAlignment="VAlign_Center",
  },
})

-- A graph-facing value, a widget delegate, and an animation asset.
bp:add_variable("UplinkPercent", "float", {default=0.87})
bp:bind_event("EngageBtn", "OnClicked", "OnEngageClicked")
bp:add_animation("IntroPulse")
bp:configure_animation("IntroPulse", {
  duration=0.75, display_name="Intro Pulse",
})
bp:set_desired_focus("EngageBtn")

local compile = bp:compile()
if not compile or not compile.success then
  error("Widget compile failed")
end
bp:save()
```

`bind_event` promotes the widget to a variable if needed and adds the delegate
event node to `EventGraph`. `add_animation` creates the animation and its
MovieScene timing; it does not invent visual property tracks.

### 2. Add a property binding after the class exists

Compile once before resolving a variable-backed property binding. Then use a
fresh call:

```lua
local path = "/Game/UI/WBP_FieldRelay"
local bp = open_asset(path)

local ok = bp:add_binding({
  object_name = "Stability",
  property_name = "Percent",
  source_property = "UplinkPercent",
  kind = "Property",
})
if not ok then error("Percent binding failed") end

bp:compile()
bp:save()
```

For a function binding, create a compatible Blueprint function and pass
`function_name` with `kind="Function"`.

### 3. Verify from stored state and pixels

```lua
local path = "/Game/UI/WBP_FieldRelay"
local bp = open_asset(path)
local info = bp:widget_info()

log("widgets=" .. tostring(info.widget_count))
log("panels=" .. tostring(info.panel_count))
log("animations=" .. tostring(info.animation_count))
log("bindings=" .. tostring(info.binding_count))
log("root=" .. tostring(info.root_widget))
log("focus=" .. tostring(bp:get_desired_focus()))

local tree = bp:validate_widget_tree()
if not tree.ok then error("Widget tree contains a cycle") end

for _, binding in ipairs(bp:list_bindings()) do
  log(binding.object_name .. "." .. binding.property_name
    .. " <- " .. tostring(binding.source_property))
end

local graph = read_graph(path, "EventGraph")
for _, node in ipairs(graph.nodes) do
  if string.find(node.name, "Engage") or string.find(node.name, "Clicked") then
    log("event node=" .. node.name)
  end
end

local compile_log = read_log("compile", {Asset=path})
for _, line in ipairs(compile_log) do
  log(tostring(line.message or line.text or line))
end

screenshot({mode="asset", asset=path, max_dimension=1600})
```

Read the returned image. Check that content is visible, colors are correct,
text is not clipped, the progress fill is near 87%, and the button is at a
usable scale.

## Tree and slot rules

A WidgetBlueprint has one root. Omit `parent` only for that first widget:

```lua
bp:add_widget("CanvasPanel", {name="Root"})
bp:add_widget("VerticalBox", {name="Stack", parent="Root"})
```

Names are unique across the entire tree. `Button`, `Border`, `SizeBox`,
`ScaleBox`, `NamedSlot`, `RetainerBox`, and `InvalidationBox` accept one child.
A rejected second child returns `nil` and leaves the tree unchanged.

Inspect live tree state with:

```lua
bp:list_widgets()
bp:find_widgets({type="TextBlock"})
local w = bp:get_widget("Hero")
log(w.type)
log(w.slot_type)
for key, value in pairs(w.props) do log(key .. "=" .. tostring(value)) end
for key, value in pairs(w.slot_props) do log(key .. "=" .. tostring(value)) end
```

Read slot state from `slot_props`, not `.slot`. Write it through
`configure_widget(..., {slot={...}})`.

### CanvasPanel layout

Canvas slots store anchors, offsets, and alignment inside `LayoutData`.

```lua
bp:configure_widget("Stack", {
  slot = {
    LayoutData = "(Anchors=(Minimum=(X=0,Y=0),Maximum=(X=1,Y=1)),"
      .. "Offsets=(Left=32,Top=32,Right=32,Bottom=32),Alignment=(X=0,Y=0))",
    ZOrder = 5,
  },
})
```

Agent-friendly aliases also work:

```lua
bp:configure_widget("Badge", {
  slot = {
    Position={x=20,y=20},
    Size={x=240,y=48},
    Anchors={minimum={x=0,y=0}, maximum={x=0,y=0}},
    Alignment={x=0,y=0},
    ZOrder=3,
    AutoSize=false,
  },
})
```

For a point anchor (`minimum == maximum`), `Right` and `Bottom` are width and
height. For a stretch anchor, they are right and bottom insets. Always set
`Alignment` explicitly.

Other panel slots expose flat properties such as `Padding`,
`HorizontalAlignment`, `VerticalAlignment`, and
`Size="(SizeRule=Fill,Value=1.0)"`.

## Property writes and atomic reference failures

`configure_widget` accepts scalar values, nested Lua tables, and UE ImportText.
It returns `{ok=true, changes=N, warnings=N}` if at least one change applies,
or `nil` if none apply. Check both the return and warning lines.

```lua
local result = bp:configure_widget("Hero", {
  Text = "RELAY ONLINE",
  AutoWrapText = false,
  ColorAndOpacity = "(SpecifiedColor=(R=1,G=0.42,B=0.08,A=1))",
})
if not result then error("No properties changed") end
if result.warnings > 0 then error("Property configure was only partial") end
```

Font and font-material object references are preflighted atomically. A missing
or wrong-type `FontObject`/`FontMaterial` returns `nil`; it does not clear the
previous object or partially apply the requested size, typeface, or spacing.

```lua
local result = bp:configure_widget("Hero", {
  Font = {
    FontObject="/Engine/EngineFonts/DoesNotExist.DoesNotExist",
    Size=18,
    LetterSpacing=80,
  },
})
if result ~= nil then error("Invalid font reference unexpectedly applied") end

-- Verify the old FontObject, Size, and LetterSpacing in a fresh script:
local stored = open_asset("/Game/UI/WBP_FieldRelay"):get_widget("Hero")
log(stored.props.Font)
```

Use real engine fonts:

- `/Engine/EngineFonts/Roboto.Roboto`
- `/Engine/EngineFonts/DroidSansMono.DroidSansMono`

There is no `/Engine/EngineFonts/RobotoMono.RobotoMono`.

## Event, animation, and binding recipes

Discover a widget's delegates before binding:

```lua
for _, event in ipairs(bp:list_events("EngageBtn")) do
  log(event.name .. " bindable=" .. tostring(event.bindable))
end
bp:bind_event("EngageBtn", "OnClicked")
```

Inspect and manage animations:

```lua
bp:list_animations()
bp:get_animation("IntroPulse")
bp:configure_animation("IntroPulse", {start_time=0, duration=1.25})
bp:rename_animation("IntroPulse", "RelayIntro")
bp:remove_animation("RelayIntro")
```

Use `rename_animation` for a real rename. Changing `display_name` only changes
the label. Adding an animation with an existing name returns `nil` and leaves
the animation count unchanged.

Inspect and remove bindings:

```lua
bp:list_bindings()
bp:remove_binding({
  object_name="Stability",
  property_name="Percent",
})
```

## Named slots and subtree reuse

```lua
bp:add_named_slot("ContentArea", {parent="Root"})
bp:add_widget("TextBlock", {name="InjectedTitle", parent="Root"})
bp:set_named_slot_content("ContentArea", "InjectedTitle")
bp:list_named_slots()

local text = bp:export_widgets("InjectedTitle")
local other = open_asset("/Game/UI/WBP_Other")
other:import_widgets(text, {parent="OtherRoot"})
```

Clearing named-slot content with `nil` destroys the previous content widget.
Cycle checks reject the slot itself, the root, and ancestors.

## Clean preview versus Designer capture

The default asset screenshot creates an independent runtime `Previewing`
widget. It does not reuse the Widget Designer's `Designing | ShowOutline`
instance, so dashed Designer bounds are absent:

```lua
screenshot({
  mode="asset",
  asset="/Game/UI/WBP_FieldRelay",
  widget_capture="preview",
  max_dimension=1600,
})
```

Use Designer mode only to debug the editor surface, rulers, safe-zone chrome,
selection outlines, or current pan and zoom:

```lua
screenshot({
  mode="asset",
  asset="/Game/UI/WBP_FieldRelay",
  widget_capture="designer",
  max_dimension=1600,
})
```

Designer mode requires an available Widget Designer tab and can fail cleanly
with `Could not find or open the Widget Blueprint Designer tab`. Preview mode
requires a generated class, widget tree, and editor world; compile the asset
first if it reports an incomplete WidgetBlueprint.

## Failure modes

| Symptom | Cause and correction |
|---|---|
| `root widget 'X' already exists` | A WidgetBlueprint has one root. Add the new widget with `parent=`. |
| `parent 'X' not found or not a panel` | The parent is missing or is a leaf. Use `find_widgets({is_panel=true})`. |
| `parent 'X' cannot accept more children` | The parent is a single-child container. Add an HBox/VBox/Overlay as its one child. |
| `configure_widget` returns `nil` | No requested change applied. Read the preceding `[WARN]` lines and inspect `get_widget(name).props`. |
| `configure_widget` reports changes plus warnings | Only valid keys applied. Treat this as partial success and correct the rejected keys. |
| Missing font path returns `nil` | The reference was rejected atomically. Use Roboto or DroidSansMono; the previous complete font remains intact. |
| Anchors appear ignored | Canvas anchors are inside `slot.LayoutData`, or use the Canvas aliases shown above. |
| Widget is centered or off-screen | `Alignment` was omitted or point-anchor width/height was mistaken for edge insets. |
| First label is cap-clipped | Put a 4–8 px Spacer first in the VBox and reorder it to index `0`. |
| `bind_event` says event not found | Query `list_events(widget_name)` and use the exact delegate name. |
| Property binding cannot resolve its source | Compile after creating the variable/function, re-open, then add the binding. |
| Duplicate animation returns `nil` | The name already exists. Reuse, rename, or remove it; no duplicate is created. |
| Compile is clean but capture is empty | Verify root/anchors/size, then inspect the preview screenshot rather than compile counts. |
| Preview capture reports incomplete WidgetBlueprint | Compile once so a generated class exists and ensure the asset has a widget tree. |
| Designer capture cannot open its tab | Use default `widget_capture="preview"` unless editor-surface chrome is the subject. |
| `bp.variables` looks stale | Re-open the asset. Widget-tree reads are live, but Blueprint snapshots can be stale across calls. |

## Discovery and verification

- `help("WidgetBlueprint")` — signatures and return shapes.
- `bp:help()` — Blueprint and WidgetBlueprint methods together.
- `bp:widget_info()` — root and widget/panel/animation/binding counts.
- `bp:get_widget(name)` — stored widget properties and `slot_props`.
- `bp:list_widgets(filter?)` / `bp:find_widgets(query)` — tree discovery.
- `bp:list_events(source?)` — exact bindable delegate names.
- `bp:list_animations()` / `bp:get_animation(name)` — animation state.
- `bp:list_bindings()` — property/function bindings.
- `class_properties("/Script/UMG.TextBlock")` — reflected editable properties.
- `read_graph(path, "EventGraph")` — event-node verification.
- `read_log("compile", {Asset=path})` — fresh compile evidence.
- `report_issue("...")` — use only when the live API cannot represent the task.

Do not wrap `help(...)` in `log(...)`; `help` already writes to the trace.
