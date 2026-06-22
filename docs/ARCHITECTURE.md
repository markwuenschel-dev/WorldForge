# WorldForge Architecture

## Core principle

WorldForge is the **factory**, not the **product**. The single most important
invariant in this repo:

> Reusable infrastructure and game-specific content never live in the same place.

Everything reusable lives under `Plugins/WorldForge/`. Everything else (the
`.uproject`, `Source/WorldForge/`, `Content/`) is a disposable host shell that
exists only so the tooling can be developed, compiled, and tested in isolation.

## Module boundaries

### `WorldForgeCore` (Runtime)
Game-agnostic primitives the *running game* consumes:
- Adaptive world-state **contracts** (stable schemas, versioned).
- Generation-**rule** primitives (the rules, not the generated results).

Constraints: minimal dependencies (`Core`, `CoreUObject`, `Engine`); must compile
into a packaged, non-editor build; no editor-only headers.

### `WorldForgeEd` (Editor)
Authoring tooling that *produces* content but never ships:
- Procedural material authoring.
- The manifest pipeline.
- UE import automation.

Constraints: may depend on `UnrealEd`, `AssetTools`, Slate, etc. Never referenced
by runtime code. Excluded from packaged builds automatically (module `Type: Editor`).

### `WorldForge` (host game module)
Intentionally near-empty. Exists so the project has a Game/Editor target to
compile and run. Depends only on `WorldForgeCore` to demonstrate the consumer
side of a contract. Not part of the reusable layer.

## Contracts

A contract (`FWorldForgeStateContract`) is the stable interface between tooling
output and a consuming game. Contracts describe **capabilities and parameters**
(e.g. `biome.temperature`), are **versioned**, and are deliberately free of lore,
factions, or quests. This is what makes generated data forward-compatible and
safe for agents to produce and consume without coupling to a specific game.

## Porting into a real game

1. Create the game project (separate `.uproject`).
2. Copy `Plugins/WorldForge/` into the game's `Plugins/`.
3. Enable the `WorldForge` plugin in the game's `.uproject`.
4. The game consumes `WorldForgeCore` contracts; the editor tooling
   (`WorldForgeEd`) is available while authoring and dropped at package time.

The host shell in this repo does not travel with the plugin.
