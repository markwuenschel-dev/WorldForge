---
name: neostack-widget
description: How to author UMG Widget Blueprints (UWidgetBlueprint) through `execute_script`. Use when the user asks to build a HUD, menu, inventory, dialog, or any other UI widget — adding/configuring widgets, slot layout, animations, property/event bindings, named slots, desired focus, export/import. Builds on `neostack-blueprint` for the shared graph/variable workflow.
---

# Editing Widget Blueprints

A Widget Blueprint is just a Blueprint with an extra **widget tree** layered on top. The graph/variable/event side works exactly like `neostack-blueprint` — read that first. This skill covers what's *different*:

1. The widget tree (`add_widget`, `configure_widget`, slots)
2. Animations
3. Property bindings (NOT the same as event bindings)
4. Named slots and desired focus
5. UMG-specific node patterns (`bind_event`, `list_events`)
6. Export / import

## The shape of a widget task

```lua
-- 1. Get the widget BP (enriched table — same as a Blueprint, with extra widget methods)
local bp = create_asset("/Game/UI/WBP_HUD", "WidgetBlueprint")    -- new
local bp = open_asset("/Game/UI/WBP_HUD")                         -- existing

-- 2. Build the widget tree first (or last — order doesn't matter)
bp:add_widget("CanvasPanel", {name="Root"})                       -- the root MUST exist before children
bp:add_widget("VerticalBox",  {name="Stack", parent="Root"})
bp:add_widget("ProgressBar",  {name="Health", parent="Stack", is_variable=true})

-- 3. Style with configure_widget (any UProperty, plus shortcuts)
bp:configure_widget("Health", {Percent=0.6, FillColorAndOpacity="(R=0.2,G=0.9,B=0.3,A=1)"})

-- 4. Wire events / property bindings (see sections below)

-- 5. Persist
bp:compile()
bp:save()
```

`bp:widget_info()` is the one-liner for "what's in this widget?" — counts widgets, panels, animations, bindings, named slots, and the root widget name.

## The widget tree

A fresh `WidgetBlueprint` has **no root**. Your first `add_widget` call must omit `parent` to install the root. Subsequent widgets need an explicit `parent=`.

```lua
bp:add_widget("CanvasPanel", {name="Root"})                       -- root (no parent)
bp:add_widget("VerticalBox", {name="VB", parent="Root"})
bp:add_widget("Button",      {name="PlayBtn", parent="VB", is_variable=true})
```

`is_variable=true` exposes the widget as a member variable so the graph can reference it. **`bind_event` auto-promotes**, so you only need this flag when you want a variable but no event binding.

### Type names you can pass

Bare class names work for any UWidget subclass: `CanvasPanel`, `VerticalBox`, `HorizontalBox`, `Overlay`, `GridPanel`, `UniformGridPanel`, `WidgetSwitcher`, `ScrollBox`, `SizeBox`, `ScaleBox`, `Border`, `Button`, `TextBlock`, `RichTextBlock`, `EditableTextBox`, `MultiLineEditableTextBox`, `Image`, `ProgressBar`, `Slider`, `CheckBox`, `ComboBoxString`, `Spacer`, `Throbber`, `CircularThrobber`, `NamedSlot`. For anything custom, pass a full path like `/Game/UI/WBP_PlayerCard.WBP_PlayerCard_C`.

### Tree ops

| Method | Notes |
|---|---|
| `bp:list_widgets(filter?)` | full tree with `depth`, `parent`, `slot` (filter is name/type substring) |
| `bp:get_widget(name)` | widget + flat `props` map + `slot_props` (see slot section) |
| `bp:find_widgets(query)` | string name OR `{type=, name=, is_variable=, is_panel=}` |
| `bp:rename_widget(old, new)` | spaces auto-stripped; updates bindings, animation refs, navigation refs, variable GUID map |
| `bp:reparent_widget(name, new_parent, index?)` | preflighted: rejects self, ancestors-of-self, non-panels, single-child overflow |
| `bp:reorder_widget(name, index)` | within current parent only |
| `bp:duplicate_widget(name, new_name?)` | clones subtree next to source; auto-names if omitted |
| `bp:remove_widget(name)` | removes subtree. **Removing the root nukes the entire tree silently.** |

### Single-child containers

`Border`, `NamedSlot`, `SizeBox`, `ScaleBox`, `Button`, `RetainerBox`, `InvalidationBox` accept exactly one child. `add_widget` rejects a second child with `parent 'X' cannot accept more children`.

## configure_widget — properties and slots

```lua
bp:configure_widget("Health", {
  Percent = 0.65,
  FillColorAndOpacity = "(R=0.2,G=0.9,B=0.3,A=1)",
  ToolTipText = "Player health",       -- or use the `tooltip="..."` shortcut
  is_variable = true,                  -- shortcut: promote to member variable
  visibility  = "Visible",             -- shortcut: SelfHitTestInvisible / Hidden / Collapsed / HitTestInvisible
  slot = { Padding = {left=10, top=4, right=10, bottom=4} },
})
```

Values can be Lua scalars, Lua tables (auto-converted to UE struct format), or full UE ImportText strings. Use `bp:get_widget(name).props` to see the current ImportText format for any property.

### The slot is on `slot_props`, not `slot`

`bp:get_widget(name)` returns the slot data under **`slot_props`** (and a duplicate `slot_properties`). The inline help mentions `.slot` — that's wrong. Use `slot_props`.

```lua
local w = bp:get_widget("Health")
log(w.slot_type)            -- e.g. "VerticalBoxSlot"
for k, v in pairs(w.slot_props) do log(k .. "=" .. tostring(v)) end
```

To **set** the slot, configure_widget takes `slot = { ... }`:

```lua
bp:configure_widget("Health", { slot = { Padding = {left=10, top=4, right=10, bottom=4} } })
```

### CanvasPanelSlot anchors — use `LayoutData`

This trips everyone. CanvasPanelSlot's actual UProperties are `LayoutData`, `bAutoSize`, `ZOrder`. **Anchors, Offsets, and Alignment are nested inside `LayoutData`** (an FAnchorData struct). Setting them directly fails:

```lua
-- ❌ WRONG — these warn "property not found on slot"
bp:configure_widget("Stack", {
  slot = { Anchors=..., Offsets=..., Alignment=... }
})

-- ✅ RIGHT — wrap in LayoutData
bp:configure_widget("Stack", {
  slot = {
    LayoutData = "(Anchors=(Minimum=(X=0,Y=0),Maximum=(X=1,Y=1)),Offsets=(Left=20,Top=20,Right=20,Bottom=20),Alignment=(X=0,Y=0))",
    bAutoSize = false,
    ZOrder = 0,
  }
})
```

For other slots (`VerticalBoxSlot`, `HorizontalBoxSlot`, `OverlaySlot`, `BorderSlot`, `GridSlot`, `UniformGridSlot`, `ScrollBoxSlot`, `WidgetSwitcherSlot`) the obvious flat keys work: `Padding`, `HorizontalAlignment` (`HAlign_Fill|Left|Center|Right`), `VerticalAlignment` (`VAlign_Fill|Top|Center|Bottom`), `Size = "(SizeRule=Fill,Value=1.0)"`.

### Padding accepts multiple shapes

```lua
slot = { Padding = {left=10, top=4, right=10, bottom=4} }   -- lowercase keys (preferred)
slot = { Padding = {Left=10, Top=4, Right=10, Bottom=4} }   -- PascalCase keys
slot = { Padding = {top=8} }                                -- omitted sides default to 0
slot = { Padding = {horizontal=10, vertical=4} }             -- left/right and top/bottom shorthand
slot = { Padding = "(Left=10,Top=4,Right=10,Bottom=4)" }    -- ImportText
slot = { Padding = 12 }                                      -- uniform padding
slot = { Padding = {10,4,10,4} }                             -- left, top, right, bottom
```

### SizeBox override properties

For SizeBox override toggles, use the real UE property names:

```lua
bp:configure_widget("Panel", {
  bOverride_WidthOverride = true,
  WidthOverride = 320,
})
```

Do not use `bWidthOverride`; the editable bool is `bOverride_WidthOverride`.

### TextBlock fonts

Set `Font` with either a table or UE ImportText. `FontObject` is resolved from a content path, so verify it round-trips in `bp:get_widget(name).props.Font` before relying on the face:

```lua
bp:configure_widget("Title", {
  Font = {
    FontObject = "/Engine/EngineFonts/RobotoMono.RobotoMono",
    TypefaceFontName = "Bold",
    Size = 28,
    LetterSpacing = 80,
  },
})

bp:configure_widget("Title", {
  Font = "(FontObject=Font'/Engine/EngineFonts/Roboto.Roboto',TypefaceFontName=\"Regular\",Size=18)",
})
```

### configure_widget return values are structured

`configure_widget` returns `{ok=true, changes=N, warnings=N}` when at least one change was applied, and returns nil when no requested change applied. Watch for non-zero `warnings` and `[WARN]` lines in the trace. After a configure, call `bp:get_widget(name).props.<Property>` or `bp:get_widget(name).slot_props.<Property>` to confirm the value landed.

## Property bindings (NOT event bindings)

Property bindings are blueprint-level "drive this property from a function/variable" rules. They're separate from `bind_event`.

```lua
-- Bind Health.Percent to a member variable named HealthPercent (float)
bp:add_variable("HealthPercent", "float")
bp:add_binding({
  object_name = "Health",
  property_name = "Percent",
  source_property = "HealthPercent",
  kind = "Property",
})

-- Bind Title.Text to a UFunction returning FText
bp:add_function("GetTitleText", { outputs={ {name="ReturnValue", type="text"} } })
bp:add_binding({
  object_name = "Title",
  property_name = "Text",
  function_name = "GetTitleText",
  kind = "Function",
})

bp:list_bindings()                                     -- inspect
bp:remove_binding({object_name="Title", property_name="Text"})   -- delete
```

`add_binding` validates that the property is bindable on the target widget class. `[FAIL] property is not bindable on TextBlock` means the property has no binding delegate (most cosmetic UProperties don't — `Text`, `Percent`, `ColorAndOpacity` do).

## Event bindings — `bind_event`

For `Button.OnClicked` and friends, **don't** use `find_nodes` / `add_node`. Use `bp:bind_event` — it auto-promotes the widget to a variable, finds the right delegate, and drops the event node into the EventGraph in one call.

```lua
bp:bind_event("PlayBtn", "OnClicked")                        -- default node name
bp:bind_event("QuitBtn", "OnClicked", "OnQuitClicked")       -- custom event name
bp:bind_event("Music",   "OnCheckStateChanged")
bp:bind_event("Volume",  "OnValueChanged")
```

### Discovering events

```lua
bp:list_events()              -- all events: 46+ entries on a typical widget BP
bp:list_events("PlayBtn")     -- filtered to one widget — preferred
```

Each entry has `name`, `kind`, `signature`, `target`, `source`, `bindable`. UserWidget overrides (`Construct`, `PreConstruct`, `Tick`, `OnFocusReceived`, `OnTouchStarted`, …) come back too. Bindable=false means it's an override slot, not a delegate.

### Custom events / dispatchers

Same shapes as `neostack-blueprint`:

```lua
bp:add_custom_event("OnWaveCleared", { inputs={{name="WaveIndex", type="int"}} })
bp:add_event_dispatcher("OnGameStarted",
  { inputs={ {name="Reason", type="string"} } })   -- keyed form
bp:add_event_dispatcher("OnHealed",
  { {name="Amount", type="float"} })                -- positional form (also works)
```

## Animations

```lua
local a = bp:add_animation("FadeIn")                 -- new (5s, 30fps MovieScene)
bp:configure_animation("FadeIn", {duration=2.5, display_name="Fade In"})
bp:rename_animation("FadeIn", "MainFadeIn")           -- full rename (var refs follow)
bp:get_animation("MainFadeIn")                        -- tracks/sections/bindings
bp:remove_animation("MainFadeIn")
bp:list_animations()
```

`configure_animation` `display_name` is just the label — for a real rename use `rename_animation` (it updates the MovieScene, the WidgetVariableNameToGuidMap, and graph-side `Get MyAnim` refs).

## Named slots

A NamedSlot is a UWidget that exposes a "fill me in" hole — useful for parent widget classes that let children inject content.

```lua
bp:add_named_slot("ContentArea", {parent="Root"})     -- create a slot widget
bp:set_named_slot_content("ContentArea", "MyChild")   -- parent MyChild under it
bp:set_named_slot_content("ContentArea", nil)         -- clear (destroys the previous content widget)
bp:list_named_slots()                                  -- local slots + content widget
bp:list_inherited_named_slots()                        -- slots exposed by the parent class
bp:remove_named_slot("ContentArea")
```

Setter rejects: self, root, and ancestor cycles. Clearing a slot **destroys** the previous content widget.

## Desired focus, thumbnail, validation

```lua
bp:set_desired_focus("PlayBtn")          -- startup keyboard focus widget
bp:set_desired_focus(nil)                 -- clear
bp:get_desired_focus()
bp:configure_thumbnail("/Game/UI/T_HUDThumb")
bp:validate_widget_tree()                 -- {ok=bool, offending_widget?, offending_type?}
```

## Export / import widgets

For copy-pasting a subtree between widget BPs, or for templates:

```lua
local txt = bp:export_widgets()                       -- whole tree
local txt = bp:export_widgets("PlayBtn")              -- one widget
local txt = bp:export_widgets({"PlayBtn","QuitBtn"})  -- many

bp2:import_widgets(txt, {parent="Root2"})             -- parent= required when text has a root
```

Import returns `[{name,type,is_root}, ...]` and registers each new widget in the compiler GUID map.

## Stale snapshots — re-open after structural changes

Like all enriched BP tables, `bp.variables` / `bp.graphs` / `bp.components` are **snapshots** taken when you opened the BP. They do NOT auto-refresh after `add_variable` / `add_function` / `add_event_graph`. The widget-tree methods (`list_widgets`, `get_widget`, `widget_info`) DO read live state and are safe to call repeatedly. If a member-variable list looks stale, just `bp = open_asset(path)` again.

## End-to-end pattern — health bar HUD

```lua
local path = "/Game/UI/WBP_HUD"
local bp = create_asset(path, "WidgetBlueprint")

-- Tree
bp:add_widget("CanvasPanel", {name="Root"})
bp:add_widget("VerticalBox", {name="Stack", parent="Root"})
bp:configure_widget("Stack", {
  slot = {
    LayoutData = "(Anchors=(Minimum=(X=0,Y=0),Maximum=(X=1,Y=0)),Offsets=(Left=20,Top=20,Right=20,Bottom=80),Alignment=(X=0,Y=0))",
  },
})

bp:add_widget("TextBlock",   {name="Title",  parent="Stack"})
bp:configure_widget("Title", {Text="Player HUD", Font="(Size=28)", Justification="ETextJustify::Center"})

bp:add_widget("ProgressBar", {name="Health", parent="Stack", is_variable=true})
bp:configure_widget("Health", {
  Percent=1.0,
  FillColorAndOpacity="(R=0.2,G=0.9,B=0.3,A=1)",
  slot = {Padding={left=0,top=8,right=0,bottom=0}, Size="(SizeRule=Automatic)"},
})

bp:add_widget("Button", {name="PauseBtn", parent="Stack", is_variable=true})
bp:add_widget("TextBlock", {name="PauseLabel", parent="PauseBtn"})
bp:configure_widget("PauseLabel", {Text="Pause"})

-- Variable + property binding
bp:add_variable("HealthPercent", "float", {default=1.0})
bp:add_binding({
  object_name="Health", property_name="Percent",
  source_property="HealthPercent", kind="Property",
})

-- Event binding (auto-promotes PauseBtn, drops node into EventGraph)
bp:bind_event("PauseBtn", "OnClicked")

-- Optional: animation
bp:add_animation("Intro")
bp:configure_animation("Intro", {duration=0.5})

-- Polish
bp:set_desired_focus("PauseBtn")
bp:configure_thumbnail("/Game/UI/T_HUDThumb")

bp:compile()
bp:save()

-- Verify a clean compile
local compile_log = read_log("compile", {Asset=path})
for _, line in ipairs(compile_log) do log(tostring(line.message or line.text or line)) end
```

## Visual verification

Use screenshot asset mode after meaningful layout changes. The default WidgetBlueprint capture is the clean rendered UMG preview and ignores the Designer viewport's current pan/zoom, rulers, and safe-zone chrome:

```lua
screenshot({mode="asset", asset="/Game/UI/WBP_HUD", max_dimension=1200})
```

Only opt into the Designer surface when debugging the editor view itself:

```lua
screenshot({
  mode = "asset",
  asset = "/Game/UI/WBP_HUD",
  widget_capture = "designer", -- includes editor overlays, rulers, safe-zone chrome, and current pan/zoom
})
```

## Failure modes you'll actually see

| Symptom | Cause / fix |
|---|---|
| `add_widget -> root widget 'X' already exists` | A `WidgetBlueprint` has exactly one root. Pass `parent=` or `remove_widget("X")` first. |
| `parent 'Y' not found or not a panel` | Y is a leaf widget (Image/TextBlock/ProgressBar/…) or doesn't exist. `bp:find_widgets({is_panel=true})` lists valid parents. |
| `parent 'Y' cannot accept more children` | Y is a single-child container (Border, NamedSlot, SizeBox, ScaleBox, Button, …). |
| `cannot parent widget to itself` / `cannot parent to own descendant` | The reparent would create a cycle. |
| `name 'X' is already in use` | Names are globally unique within a widget tree. Pick another or rename the existing widget first. |
| `configure_widget` returns true but value didn't change | Watch for `[WARN] property 'X' not found` or `[WARN] failed to parse value` in the trace. Verify with `bp:get_widget(name).props.X`. |
| Anchors not applying on a CanvasPanelSlot | You're setting `Anchors=` directly. Wrap in `LayoutData=...` instead. |
| `add_binding` says "property is not bindable" | Property has no binding delegate. Most cosmetic UProperties don't — only the ones marked `BlueprintReadWrite` + `BindWidget` do. Try a function binding instead, or change the value imperatively from a graph. |
| `bind_event -> event not found on Button` | Wrong delegate name. Run `bp:list_events("WidgetName")` to discover. |
| `connect -> Float is not compatible with X` | Type mismatch on a manual `connect`. Auto-connect via `add_node({from_handle, from_pin})` will warn-and-skip on the same condition. |
| `bp.variables` doesn't show what you just added | Stale snapshot. Re-`open_asset`. The widget-tree methods don't have this problem. |
| `bp:export_widgets()` returned a tiny string | Earlier versions only emitted the root. Pass an explicit `{name1, name2, ...}` array if a whole-tree export looks suspiciously small. |

## Discovery escape hatches

- `bp:help()` — full method list on the widget BP table.
- `bp:widget_info()` — counts + root + animation/binding/named-slot counts.
- `bp:get_widget(name)` — every editable UProperty + slot props for one widget. Use this to discover property names and current ImportText format.
- `bp:list_events("WidgetName")` — every bindable delegate + override on one widget.
- `class_properties("/Script/UMG.CanvasPanelSlot")` — Reflection lookup for any UClass / slot class.
- `help("WidgetBlueprint")` / `help("AddNode")` / `help("Connect")` — domain docs.

For graph node patterns (find_nodes / add_node / connect / set_pin / read_graph / pin defaults), see **`neostack-blueprint`** — the widget BP graph behaves identically.
