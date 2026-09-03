---
name: neostack-umg-design
description: How to make UMG Widget Blueprints actually look good — typography, palette, atmosphere, brutalist/editorial/terminal aesthetics. Use when the user asks for a HUD, menu, settings panel, terminal, briefing screen, dashboard, or any UI where look-and-feel matters more than wiring. Layers on top of `neostack-widget` (mechanics) — read that first.
---

# Designing UMG Widget Blueprints

`neostack-widget` covers the binding — `add_widget`, `configure_widget`, slot props, events. This skill is about taste: committing to an aesthetic direction and executing it precisely with the tools UE actually gives you.

## The shape of a designed widget

```lua
local bp = create_asset("/Game/UI/WBP_X", "WidgetBlueprint")

-- 1. Tokens at the top of the script (commit to ONE accent)
local ACCENT = "(R=1.0,G=0.62,B=0.10,A=1)"      -- amber, ember, neon — your signal color
local FG     = "(R=0.92,G=0.90,B=0.85,A=1)"      -- bone / cream / off-white
local MUTED  = "(R=0.45,G=0.45,B=0.48,A=1)"
local VOID   = "(R=0.015,G=0.015,B=0.020,A=1)"   -- never pure 0,0,0

-- 2. Root is a CanvasPanel — only way to layer atmosphere over content
bp:add_widget("CanvasPanel", {name="Root"})

-- 3. Background void
bp:add_widget("Border", {name="VoidBG", parent="Root"})
bp:configure_widget("VoidBG", { BrushColor=VOID, slot={
  LayoutData = "(Anchors=(Minimum=(X=0,Y=0),Maximum=(X=1,Y=1)),Offsets=(Left=0,Top=0,Right=0,Bottom=0))",
  ZOrder = 0,
}})

-- 4. Content goes in a normal HBox/VBox anchored to fill — not directly on the canvas
bp:add_widget("HorizontalBox", {name="Grid", parent="Root"})
bp:configure_widget("Grid", { slot={
  LayoutData = "(Anchors=(Minimum=(X=0,Y=0),Maximum=(X=1,Y=1)),Offsets=(Left=80,Top=92,Right=80,Bottom=80))",
  ZOrder = 5,
}})

-- 5. Atmosphere LAST — accent rails, hairlines, corner ticks as siblings of Grid
```

## The five rules nothing else matters more than

1. **Commit to ONE aesthetic direction.** Terminal-brutalist. Editorial-magazine. Retro-arcade. Soft-organic. Luxury-refined. Pick one in plain language before writing any code. Half-committed designs read as generic.
2. **One accent color, full stop.** ACCENT does ALL the attention work. Adding a second accent is where AI-slop lives. If you need to differentiate, use opacity (`A=0.5`) or a dim variant of the SAME accent — don't reach for a new hue.
3. **No pure black, no centered everything.** `(0,0,0)` flattens optically — use `(0.01–0.04, 0.01–0.04, 0.01–0.04)` for "void." Asymmetric layouts are more memorable than centered ones; pick a fixed-width column on one side.
4. **Atmosphere is layers, not a solid color.** Hairlines, accent rails, corner ticks, faint glow bands — these are 2–4 thin Border widgets on the Root canvas with carefully chosen ZOrder. They cost almost nothing and transform the read.
5. **The hero typography is the single thing someone remembers.** One oversized element (timestamp, title, number) carries the design. Everything else is metadata around it.

## LayoutData semantics — read this before any CanvasPanel positioning

`LayoutData` is the single biggest source of "the code looks right but the render is wrong" problems. The two traps below cost half an hour of debugging if missed.

### Trap 1: `Right`/`Bottom` change meaning depending on anchors

`Offsets=(Left=,Top=,Right=,Bottom=)` looks like four edge positions, but it isn't:

| Anchor in that axis | Left / Top | Right / Bottom |
|---|---|---|
| Point (`min == max`) | position from anchor | **WIDTH / HEIGHT** |
| Stretch (`min != max`) | inset from left/top edge | inset from right/bottom edge |

So `Anchors=(0,0.5)-(0,0.5)` (point) with `Offsets=(Left=120,Top=0,Right=320,Bottom=620)` is a **320×620 box** positioned at `(anchor_x + 120, anchor_y + 0)`. NOT a quad with four edge coords.

### Trap 2: omitting `Alignment` silently centers your widget

If you don't specify `Alignment`, UE auto-derives it as `(anchor.min + anchor.max) / 2`. So `Anchors=(0,0.5)-(0,0.5)` becomes `Alignment=(0, 0.5)` automatically — meaning the widget's *vertical center* lands at `anchor_y + Top`, not its top edge. Half the widget renders above the offset.

**Always specify `Alignment` explicitly.** Pick from these three intents:

```lua
-- Top-left corner of bounding box at the offset (most common for panels)
"(Anchors=(...),Offsets=(...),Alignment=(X=0,Y=0))"

-- Center of bounding box at the offset (equipment slots, dots, badges)
"(Anchors=(...),Offsets=(...),Alignment=(X=0.5,Y=0.5))"

-- Right edge or bottom edge anchored (corner stamps, footer badges)
"(Anchors=(1,1)-(1,1),Offsets=(...),Alignment=(X=1,Y=1))"
```

### Pick the anchor strategy that matches the panel's role

- **Responsive edge rail** (left/right column that fills any canvas height): `Anchors=(0,0)-(0,1)`, `Alignment=(0,0)`, `Offsets=(Left=120,Top=80,Right=320,Bottom=80)` → width 320 (Right is WIDTH because anchor X is point), top inset 80, bottom inset 80.
- **Centered card with fixed size** (HUD card that floats at vertical middle): `Anchors=(0,0.5)-(0,0.5)`, `Alignment=(0,0.5)`, `Offsets=(Left=120,Top=0,Right=320,Bottom=620)` → 320×620 centered on canvas vertical middle.
- **Corner-anchored badge** (top-right stamp): `Anchors=(1,0)-(1,0)`, `Alignment=(1,0)`, `Offsets=(Left=-72,Top=22,Right=200,Bottom=14)` → grows back-and-down from the top-right corner.

When in doubt, prefer stretch anchors with insets — they're responsive across canvas sizes. Point anchors with explicit Alignment are simpler arithmetic but rebreak if the canvas size changes.

## Engine font reality

Only these ship in `/Engine/EngineFonts/` — there is **no** RobotoMono, no display font, no serif. If you want anything else, the project has to import a Font asset into `/Game/Fonts/`.

| Path | Typefaces | Use for |
|---|---|---|
| `/Engine/EngineFonts/Roboto.Roboto` | `Regular`, `Bold`, `Light`, `Italic`, `Bold Italic` | body, sans display |
| `/Engine/EngineFonts/DroidSansMono.DroidSansMono` | `Regular` only | mono headings, terminal vibe, numerics |
| `/Engine/EngineFonts/SmallFont.SmallFont`, `TinyFont.TinyFont`, `RobotoTiny.RobotoTiny` | one face | niche; rarely the right call |

DroidSansMono has only one weight — fake bold/light by varying **Size** and **ColorAndOpacity**, not by setting `TypefaceFontName`.

**FontObject MUST use the class-prefixed ImportText form** (or the equivalent table form). Bare paths get rejected:

```lua
-- ImportText (preferred for verbose Font literals)
Font = "(FontObject=Font'/Engine/EngineFonts/Roboto.Roboto',TypefaceFontName=\"Light\",Size=18,LetterSpacing=0)"

-- Table form (cleaner when you have only a few fields)
Font = { FontObject="/Engine/EngineFonts/DroidSansMono.DroidSansMono", Size=11, LetterSpacing=320 }
```

`LetterSpacing` is the secret weapon — large positive values (200–400) on small uppercase mono labels do the heavy lifting that all-caps + tracking does in Figma. Slight negative (-20 to -40) on hero monospace numerics tightens them so they read as one shape.

## Typography hierarchy (a working scale)

| Role | Font | Size | LetterSpacing | Color |
|---|---|---|---|---|
| Eyebrow / metadata label | mono | 9–11 | +280–400 (uppercase) | accent or muted |
| Hero numeric / title | mono | 60–80 | -20 to -40 | foreground |
| Sub-hero coordinates | mono | 16–20 | +40–80 | muted |
| Section header | mono | 10–12 | +240–320 | accent |
| Body callout | sans Light | 16–18 | 0 | foreground |
| Status / footer | mono | 9–12 | +280–400 | accent |

`ColorAndOpacity` on TextBlock needs the wrapper:
```lua
ColorAndOpacity = "(SpecifiedColor=" .. ACCENT .. ")"
```

## Atmosphere — decorative CanvasPanel layers

The pattern: content lives in normal HBox/VBox containers anchored to fill the screen. **Decoration lives on the Root CanvasPanel as siblings of the content**, positioned via `LayoutData` and stacked via `ZOrder`.

ZOrder discipline (use the same scale every time):
- `0` — void background
- `1` — faint atmospherics (glow bands, dim hairlines)
- `2` — accent rails
- `3` — corner stamps, page locators
- `4` — corner ticks, foreground decorations
- `5` — main content grid
- `6+` — modal overlays

### Hairline rule (any direction)

A 1px Border wrapped in a SizeBox forces a true hairline — Borders alone size to their content:

```lua
bp:add_widget("SizeBox", {name="Rule", parent="Main"})
bp:configure_widget("Rule", {
  HeightOverride=1, bOverride_HeightOverride=true,
  slot = { Padding={top=20,bottom=20}, HorizontalAlignment="HAlign_Fill" },
})
bp:add_widget("Border", {name="RuleFill", parent="Rule"})
bp:configure_widget("RuleFill", { BrushColor = "(R=0.18,G=0.18,B=0.20,A=1)" })
```

### Edge accent rail (full-height vertical line)

```lua
bp:add_widget("Border", {name="LeftRailLine", parent="Root"})
bp:configure_widget("LeftRailLine", {
  BrushColor = ACCENT,
  slot = {
    -- Anchored to left edge, stretching full height; Right=2 means 2px wide
    LayoutData = "(Anchors=(Minimum=(X=0,Y=0),Maximum=(X=0,Y=1)),Offsets=(Left=24,Top=64,Right=2,Bottom=64))",
    ZOrder = 2,
  },
})
```

### Corner-tick L-bracket (the brutalist signature)

Two thin Borders anchored to the same corner with one short and one tall — produces an L. Repeat per corner:

```lua
-- Top-right horizontal arm
bp:add_widget("Border", {name="TickTR_H", parent="Root"})
bp:configure_widget("TickTR_H", { BrushColor=ACCENT, slot={
  LayoutData = "(Anchors=(Minimum=(X=1,Y=0),Maximum=(X=1,Y=0)),Offsets=(Left=-72,Top=56,Right=12,Bottom=2),Alignment=(X=1,Y=0))",
  ZOrder = 4,
}})
-- Top-right vertical arm — same anchor, swap dimensions
bp:add_widget("Border", {name="TickTR_V", parent="Root"})
bp:configure_widget("TickTR_V", { BrushColor=ACCENT, slot={
  LayoutData = "(Anchors=(Minimum=(X=1,Y=0),Maximum=(X=1,Y=0)),Offsets=(Left=-72,Top=56,Right=2,Bottom=12),Alignment=(X=1,Y=0))",
  ZOrder = 4,
}})
```

### Numbered chip / key tag (`[1]` `[2]` `[3]`)

Tactical UIs and game HUDs use `[1] [2] [3]` numbered chips in front of weapon names or hotkey labels. Build them as an **Overlay containing a Border (background) + a TextBlock (number)**, wrapped in a SizeBox for fixed dimensions:

```lua
bp:add_widget("SizeBox", {name="ChipBox", parent="Header"})
bp:configure_widget("ChipBox", {
  WidthOverride=28, bOverride_WidthOverride=true,
  HeightOverride=28, bOverride_HeightOverride=true,
  slot = { Padding={right=12}, VerticalAlignment="VAlign_Center" },
})
bp:add_widget("Overlay", {name="ChipOL", parent="ChipBox"})

bp:add_widget("Border", {name="ChipBG", parent="ChipOL"})
bp:configure_widget("ChipBG", { BrushColor = "(R=0.20,G=0.22,B=0.26,A=1)" })

bp:add_widget("TextBlock", {name="ChipN", parent="ChipOL"})
bp:configure_widget("ChipN", {
  Text = "1",
  Font = { FontObject="/Engine/EngineFonts/Roboto.Roboto", TypefaceFontName="Bold", Size=13 },
  ColorAndOpacity = "(SpecifiedColor="..FG..")",
  Justification = "ETextJustify::Center",
  slot = { HorizontalAlignment="HAlign_Center", VerticalAlignment="VAlign_Center" },
})
```

**The chip BG must be visibly lighter than its parent panel.** If they're within `(0.05, 0.05, 0.05)` luminance of each other the chip vanishes and the number floats unreadable. Either bump the BG `(0.10+, 0.10+, 0.10+)` brighter than the panel, OR give the chip a 1px outline via a WidgetStyle.

### Corner stamp (mission-briefing feel)

Tiny mono uppercase text in a corner — `TX 0042 // DEEP-FIELD // REV 7` reads as instrumentation:

```lua
bp:add_widget("TextBlock", {name="CornerStamp", parent="Root"})
bp:configure_widget("CornerStamp", {
  Text = "TX 0042  //  REV 7",
  Font = { FontObject="/Engine/EngineFonts/DroidSansMono.DroidSansMono", Size=9, LetterSpacing=400 },
  ColorAndOpacity = "(SpecifiedColor="..MUTED..")",
  slot = {
    LayoutData = "(Anchors=(Minimum=(X=1,Y=0),Maximum=(X=1,Y=0)),Offsets=(Left=-72,Top=22,Right=420,Bottom=14),Alignment=(X=1,Y=0))",
    ZOrder = 3,
  },
})
```

## Buttons — never use the default

Default UE button = generic AAA placeholder. Always override `WidgetStyle`. Set `DrawAs=Box` and use `RoundingType=FixedRadius` (NOT `HalfHeightRadius` — that one forces rounded corners regardless of `CornerRadii=0`).

You **must override all four states** (Normal / Hovered / Pressed / Disabled). Skipping any state causes it to fall back to engine default, which looks wildly different from the others mid-interaction.

```lua
bp:configure_widget("BtnPrimary", {
  WidgetStyle =
    "(Normal=(DrawAs=Box,TintColor=(SpecifiedColor=(R=0.04,G=0.04,B=0.06,A=1)),"
    .. "OutlineSettings=(Color=(SpecifiedColor=(R=1.0,G=0.62,B=0.10,A=1)),"
    .. "CornerRadii=(X=0,Y=0,Z=0,W=0),Width=2,RoundingType=FixedRadius)),"
    .. "Hovered=(DrawAs=Box,TintColor=(SpecifiedColor=(R=0.16,G=0.10,B=0.04,A=1)),"
    .. "OutlineSettings=(Color=(SpecifiedColor=(R=1.0,G=0.62,B=0.10,A=1)),"
    .. "CornerRadii=(X=0,Y=0,Z=0,W=0),Width=2,RoundingType=FixedRadius)),"
    .. "Pressed=(DrawAs=Box,TintColor=(SpecifiedColor=(R=0.22,G=0.14,B=0.04,A=1)),"
    .. "OutlineSettings=(Color=(SpecifiedColor=(R=1.0,G=0.62,B=0.10,A=1)),"
    .. "CornerRadii=(X=0,Y=0,Z=0,W=0),Width=2,RoundingType=FixedRadius)),"
    .. "Disabled=(DrawAs=Box,TintColor=(SpecifiedColor=(R=0.04,G=0.04,B=0.06,A=1)),"
    .. "OutlineSettings=(Color=(SpecifiedColor=(R=0.18,G=0.18,B=0.20,A=1)),"
    .. "CornerRadii=(X=0,Y=0,Z=0,W=0),Width=2,RoundingType=FixedRadius)),"
    .. "NormalPadding=(Left=18,Top=14,Right=18,Bottom=14),"
    .. "PressedPadding=(Left=18,Top=15,Right=18,Bottom=13))",
})
```

Inside the button: a `HorizontalBox` containing label + an index/tag (`// 01`, `// 02`) — gives the mission-briefing feel and keeps vertical alignment honest via `VerticalAlignment="VAlign_Center"`.

## Layout patterns that work every time

**Asymmetric three-column grid** (used in the DEEP-FIELD build):

```
[ FIXED 320 ][ SPACER 48 ][ FILL ][ SPACER 48 ][ FIXED 280 ]
   left rail               main column            actions
```

```lua
bp:add_widget("HorizontalBox", {name="Grid", parent="Root"})  -- anchored to fill
bp:add_widget("SizeBox",       {name="LeftBox",  parent="Grid"})  -- WidthOverride=320, bOverride_WidthOverride=true
bp:add_widget("Spacer",        {name="GutterL",  parent="Grid"})  -- Size="(X=48,Y=0)"
bp:add_widget("VerticalBox",   {name="Main",     parent="Grid"})  -- slot.Size="(SizeRule=Fill,Value=1.0)"
bp:add_widget("Spacer",        {name="GutterR",  parent="Grid"})  -- Size="(X=48,Y=0)"
bp:add_widget("SizeBox",       {name="RightBox", parent="Grid"})  -- WidthOverride=280
```

**Spacer-as-gutter beats slot Padding for column gaps** — content stays flush to its own column edges and the script reads as a layout, not a series of nudges.

**Headroom Spacer at the top of every VBox column.** UE clips text cap-heights when text is the very first item. A 4–8px Spacer at index 0 fixes it:

```lua
bp:add_widget("Spacer", {name="Headroom", parent="LeftRail"})
bp:configure_widget("Headroom", { Size="(X=0,Y=4)" })
bp:reorder_widget("Headroom", 0)
```

## Use Lua helpers for repeated structures

When a UI has 12 inventory rows or 3 weapon cards with the same shape, **don't** copy-paste the configure_widget block per item. Write a single helper and call it per row — names of children must stay unique across the whole tree, so always parameterize them with the row's id:

```lua
local function inv_row(id, label, count)
  local row = "Row_" .. id
  bp:add_widget("HorizontalBox", {name=row, parent="LeftList"})
  bp:configure_widget(row, { slot={ Padding={top=2, bottom=2} } })

  bp:add_widget("SizeBox", {name="Icon_"..id, parent=row})
  bp:configure_widget("Icon_"..id, {
    WidthOverride=44, bOverride_WidthOverride=true,
    HeightOverride=44, bOverride_HeightOverride=true,
    slot = { Padding={right=12}, VerticalAlignment="VAlign_Center" },
  })
  bp:add_widget("Border", {name="IconBG_"..id, parent="Icon_"..id})
  bp:configure_widget("IconBG_"..id, { BrushColor=SLOT })

  bp:add_widget("TextBlock", {name="Name_"..id, parent=row})
  bp:configure_widget("Name_"..id, {
    Text=label, Font=font_sans("Regular", 14, 0),
    ColorAndOpacity = "(SpecifiedColor="..FG..")",
    slot = { Size="(SizeRule=Fill,Value=1.0)", VerticalAlignment="VAlign_Center" },
  })

  bp:add_widget("TextBlock", {name="Count_"..id, parent=row})
  bp:configure_widget("Count_"..id, {
    Text=count or "", Font=font_sans("Regular", 14, 0),
    ColorAndOpacity = "(SpecifiedColor="..MUTED..")",
    Justification = "ETextJustify::Right",
    slot = { VerticalAlignment="VAlign_Center" },
  })
end

inv_row("Painkiller", "Painkiller", "1")
inv_row("Bandage",    "Bandage",    "5")
-- … 10 more
```

12 inventory rows in 12 lines instead of 70+ widget calls. Same pattern for weapon cards (header chip + name + ammo info + image area + 4 attachment slots), equipment slots, settings rows — anything that repeats.

## Anti-patterns (the AI-slop checklist)

| Don't | Do |
|---|---|
| `BrushColor=(0,0,0)` | `(0.015, 0.015, 0.02)` — never pure black |
| Inter, Space Grotesk, generic sans defaults | Roboto Light + DroidSansMono, separated by intent |
| Two or more accent colors | One accent, varied by opacity |
| Centered everything | Asymmetric grid with one fixed-width side |
| Default UE button | Custom WidgetStyle with all 4 states |
| Rounded corners as a shortcut to "modern" | Sharp edges + better typography |
| Slot Padding for column gutters | Spacer widgets between columns |
| Reading the Designer screenshot expecting clean output | `screenshot({mode="asset", asset=...})` captures preview render; the dashed boxes are designer guides and disappear in PIE |

## Aesthetic directions to reach for

Pick ONE before writing any code. Each carries its own palette + type + composition logic:

- **Tactical / inventory dashboard** — three-band layout (left items list / center loadout / right weapons), Roboto Regular for labels, dark charcoal-blue void with subtle top/bottom haze, slot squares with hairline borders, numbered `[N]` chips on hotkey actions, count tags right-aligned in list rows. *PUBG-style; WBP_TacticalInventory ships this.*
- **Terminal / Brutalist** — DroidSansMono, void + single signal color, asymmetric grid, corner ticks, hairlines, no rounded corners. *DEEP-FIELD ships this.*
- **Editorial / Magazine** — Roboto Light + a hero serif (project-imported), generous whitespace, single full-bleed image, drop-cap, single accent rule.
- **Retro-arcade** — chunky pixel-feel via DroidSansMono + huge sizes, primary palette (red/yellow/cyan), 4-8px hard pixel borders, no anti-alias-feel typography.
- **Luxury / Refined** — thin imported serif, gold/copper accent on near-black, asymmetric whitespace as the primary tool, 1px decorations only.
- **Soft / Organic** — pastel palette (`(0.9, 0.85, 0.8)` warm bg), rounded corners (`CornerRadii=(X=12,...)`), gentle gradients via two stacked translucent Borders.

## Quick-build template

A minimum brutalist HUD card — copy and reskin per direction:

```lua
local bp = create_asset("/Game/UI/WBP_HUDCard", "WidgetBlueprint")
local ACCENT = "(R=1.0,G=0.62,B=0.10,A=1)"
local FG     = "(R=0.92,G=0.90,B=0.85,A=1)"
local MUTED  = "(R=0.45,G=0.45,B=0.48,A=1)"
local VOID   = "(R=0.015,G=0.015,B=0.02,A=1)"
local MONO   = "/Engine/EngineFonts/DroidSansMono.DroidSansMono"

bp:add_widget("CanvasPanel", {name="Root"})

-- Card background
bp:add_widget("Border", {name="Card", parent="Root"})
bp:configure_widget("Card", { BrushColor=VOID, slot={
  LayoutData = "(Anchors=(Minimum=(X=0,Y=1),Maximum=(X=0,Y=1)),Offsets=(Left=40,Top=-180,Right=320,Bottom=120),Alignment=(X=0,Y=1))",
  ZOrder = 0,
}})

-- Accent rule along the top of the card
bp:add_widget("Border", {name="CardRule", parent="Root"})
bp:configure_widget("CardRule", { BrushColor=ACCENT, slot={
  LayoutData = "(Anchors=(Minimum=(X=0,Y=1),Maximum=(X=0,Y=1)),Offsets=(Left=40,Top=-180,Right=320,Bottom=2),Alignment=(X=0,Y=1))",
  ZOrder = 1,
}})

-- Content column
bp:add_widget("VerticalBox", {name="Col", parent="Root"})
bp:configure_widget("Col", { slot={
  LayoutData = "(Anchors=(Minimum=(X=0,Y=1),Maximum=(X=0,Y=1)),Offsets=(Left=64,Top=-160,Right=280,Bottom=100),Alignment=(X=0,Y=1))",
  ZOrder = 5,
}})

bp:add_widget("TextBlock", {name="Eyebrow", parent="Col"})
bp:configure_widget("Eyebrow", {
  Text = "OBJECTIVE  //  ACTIVE",
  Font = { FontObject=MONO, Size=10, LetterSpacing=320 },
  ColorAndOpacity = "(SpecifiedColor="..ACCENT..")",
  slot = { Padding={top=8, bottom=10} },
})

bp:add_widget("TextBlock", {name="Title", parent="Col"})
bp:configure_widget("Title", {
  Text = "RECOVER BLACK BOX",
  Font = { FontObject=MONO, Size=24, LetterSpacing=-10 },
  ColorAndOpacity = "(SpecifiedColor="..FG..")",
  slot = { Padding={bottom=14} },
})

bp:add_widget("TextBlock", {name="Hint", parent="Col"})
bp:configure_widget("Hint", {
  Text = "Sector 7-K  //  2.4 km NE",
  Font = { FontObject=MONO, Size=11, LetterSpacing=120 },
  ColorAndOpacity = "(SpecifiedColor="..MUTED..")",
})

bp:compile()
bp:save()
```

## Verifying the result

1. `screenshot({mode="asset", asset=path})` — preview render, accurate.
2. The Designer's dashed safe-zone outlines and panel boundaries **are designer-only overlays** — they vanish in PIE. Don't iterate on them.
3. After every visual change: re-screenshot, look at the *whole* composition, not the change. Most issues come from the change being right but the surrounding rhythm wrong.
4. For final-final verification: spawn the widget in PIE via `Add to Viewport` — only way to see exactly what shipping users see.

## What to fall back to

- `bp:get_widget(name).props` — see the actual ImportText for any property; copy-paste for the next widget instead of guessing syntax.
- `bp:widget_info()` — counts and root, fastest sanity check.
- `class_properties("/Script/UMG.Button")` — every editable UProperty on a class. Use when a configure_widget call doesn't seem to land.
- `help("WidgetBlueprint")` — full method list.

For binding mechanics (events, animations, named slots, property bindings, export/import), see **`neostack-widget`**. This skill stops where mechanics begin.
