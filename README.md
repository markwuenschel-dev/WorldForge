# WorldForge

**WorldForge is a tooling layer, not a game.** It is the factory that lets you build
adaptive games faster.

```
Unreal Engine
    ↓
WorldForge tooling layer   ← this project
    ↓
Your actual game           ← a separate project, built later
```

## What it provides

- **Procedural materials**
- **Manifest pipeline**
- **UE import automation**
- **Adaptive world-state contracts**
- **Agent-safe generation rules**

The game built on top could later be an open-world RPG, a base-builder survival
game, a colony sim, a faction-driven sandbox, or an adaptive fantasy world.
WorldForge stays general enough to support any of them.

## Why tooling is kept separate from the game

If one project is *both* the tooling framework *and* the actual game, the
architecture gets messy fast — material pipeline code, import scripts, Substance
recipes, and world-state rules end up tangled with specific lore, factions,
enemies, quests, and buildings. That makes it hard for both humans and agents to
reason about **what is reusable infrastructure versus game-specific content.**

WorldForge draws that line at the folder level.

## Architecture

```
WorldForge/                         thin C++ host shell (disposable)
├── WorldForge.uproject             UE 5.7
├── Source/WorldForge/              minimal primary game module
└── Plugins/WorldForge/             THE reusable factory — port this folder into any game
    └── Source/
        ├── WorldForgeCore/         Runtime: world-state contracts + generation-rule primitives
        │                           (game-agnostic; ships in packaged builds)
        └── WorldForgeEd/           Editor-only: procedural materials, manifest pipeline,
                                    import automation (never shipped)
```

The rule of thumb:

| Belongs in `Plugins/WorldForge/` | Does **not** belong here |
| --- | --- |
| Material/generation pipelines | Specific lore, factions, enemies |
| World-state contracts (schemas) | Specific quests, base buildings |
| Import/manifest automation | Hand-authored game content |
| Generation *rules* | Generation *results* |

When you start the real game, create a new project and drop
`Plugins/WorldForge/` into it. The host shell here stays behind.

## Getting started

1. Right-click `WorldForge.uproject` → **Generate Visual Studio project files**
   (or open it directly; the editor will offer to build the modules).
2. Open in Unreal Editor 5.7 and let it compile `WorldForge`, `WorldForgeCore`,
   and `WorldForgeEd`.

## Conventions for agents

- Treat `Plugins/WorldForge/` as reusable infrastructure. Do not add
  game-specific content, lore, or assets to it.
- Runtime-safe code goes in `WorldForgeCore`. Editor-only tooling goes in
  `WorldForgeEd`.
- World-state contracts describe *capabilities and parameters*, never specific
  game content — this is what keeps generation forward-compatible and agent-safe.
