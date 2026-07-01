# UE5 Procedural World & Content Architecture v1.1

**Status**: Target Architecture (Full Vision)  
**Date**: 2026-06-21  
**Philosophy**: Human designs the factories and contracts. Agents operate the contracts at scale. Every vertical slice must be compatible with the final architecture.

## 1. Core Distinction

This is **not** an MVP document.  
This is the target end-state architecture. All implementation happens through vertical slices that harden toward this shape from day one. No throwaway scaffolding that teaches agents the wrong boundaries.

## 2. System Spine (The Flow)

```
Human-authored Templates
├── Substance Designer master graphs (.sbs)
├── UE5 master materials (Material Layers + MPC)
├── PCG graph templates
├── MassEntity processors & fragments
├── Niagara system templates
└── Core gameplay subsystems (C++ / Blueprints)

        ↓

Agent-Editable Contracts (Textual, Git-friendly, Validated)
├── MaterialRecipe.yaml
├── BiomeDefinition.yaml
├── TerraformStageDefinition.yaml
├── FoliageSpawnRules.yaml
├── EnemyDefinition.yaml
├── WeaponDefinition.yaml
├── ProjectileDefinition.yaml
├── WaveDefinition.yaml
└── ValidationRules.yaml

        ↓

Build-time Automation (Editor-only)
├── Recipe / definition validation
├── Substance rendering (pysbs / CLI)
├── Texture import + compression rules
├── Material Instance creation / update
├── DataAsset / DataTable generation from YAML
├── UE Data Validation (correctness + performance budgets)
├── Preview thumbnail + comparison renders
└── Provenance manifest emission

        ↓

Generated UE-Native Runtime Assets
├── Textures
├── Material Instances
├── Data Assets / Data Tables / Primary Data Assets
├── PCG parameter tables
├── Preview assets + reports
└── Build provenance manifests

        ↓

Runtime Systems (Never Python)
├── WorldStateSubsystem
├── TerraformSubsystem (three-tier health model)
├── BiomeSubsystem
├── PCG-driven population (reads Data Assets)
├── Material Parameter Collections + Runtime Virtual Textures
├── MassEntity processors (selective)
├── Niagara VFX
├── Audio state system
└── Post-process volume control
```

**Critical Rule**: YAML and Python exist only in the authoring and build pipeline. Runtime gameplay systems consume generated UE-native assets (Data Assets, Data Tables, etc.).

## 3. Human vs Agent Boundaries

**Human owns**:
- All master templates (Substance graphs, master materials, PCG graph structure, Mass processors, Niagara systems, core subsystems)
- Architecture decisions and contracts
- Final visual and gameplay quality bar
- Performance budget definitions

**Agents operate** (within contracts):
- Creating and varying material recipes
- Populating and tuning biome / terraform stage definitions
- Filling enemy, weapon, projectile, and wave definitions
- Maintaining validation rules and build scripts
- Running the full build pipeline and reporting

**Owner-owned authoring surfaces** (protected by the ownership/provenance model — agents drive the editor but do not overwrite these):
- Master Substance graphs and PCG graph structure
- Hand-authored master `.uasset` files and Blueprints
- Final visual or balance decisions without data

## 4. Provenance Model

Every generated asset must carry traceable provenance:
- Source recipe/definition file + git commit
- Parameters used
- Build timestamp
- Validation status + performance budget check results

This is emitted as sidecar manifests or embedded metadata during the build automation step. Critical for debugging "where did this asset come from?" at scale.

## 5. Build-time vs Runtime Boundary (Non-negotiable)

**Build-time / Editor only**:
- UE Python (import, material instance creation, batch operations)
- Commandlets
- Substance Automation Toolkit
- Custom Python orchestration scripts
- Data Validation runs
- Preview rendering

**Runtime (gameplay)**:
- C++
- Blueprints
- Subsystems
- Data Assets / Data Tables
- MassEntity
- PCG (runtime evaluation)
- Niagara
- Material Parameter Collections
- Runtime Virtual Textures

Never route gameplay logic through Python. UE Python is a content production tool, not a runtime scripting layer.

## 6. Technology Choices & Justifications

| Area                    | Chosen Technology              | Reason |
|-------------------------|--------------------------------|--------|
| Material authoring      | Substance Designer + UE Material Layers | Best procedural control + runtime blending flexibility |
| Material variation      | YAML recipes → generated Material Instances | Safe for agents, reproducible |
| World state             | Three-tier health model (Global / Biome / Local) | Enables local + systemic healing fantasy |
| Foliage / population    | PCG graphs + Data Asset rules | Powerful + performant; agents tune data, not graphs |
| High-count simulation   | MassEntity (selective)         | Data-oriented when it fits; avoid over-use |
| Projectiles             | Context-dependent (hitscan + pooled VFX, pooled actors, Niagara, or Mass) | Semantics matter more than one-size-fits-all |
| Validation              | UE Data Validation + custom rules + performance budgets | Catches both correctness and silent performance rot |
| Automation              | Python (editor) + Makefile/CLI | Agent-friendly, reproducible builds |

## 7. Implementation Approach

Implement via **vertical slices** that each deliver one complete, hardened lane while respecting the full architecture:

1. Material Factory lane (Substance recipe → generated MI + Data Asset)
2. World Healing lane (three-tier model + Material Layers + MPC)
3. Biome + Foliage lane (BiomeDefinition → PCG rules + spawn data)
4. Enemy Swarm lane (EnemyDefinition → MassEntity + spawn rules)
5. etc.

Each slice must include validation, provenance, and performance budget checks from the beginning.

---

This document is the single source of truth for the target architecture. All other design docs must align with it.