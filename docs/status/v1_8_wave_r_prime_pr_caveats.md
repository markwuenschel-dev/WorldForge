# WorldForge v1.8 Wave R Prime — CombatForge Alpha: PR caveats

Branch `worldforge/v1.8-combatforge`. Date 2026-07-09. Contract:
`docs/contracts/v1_8_wave_r_prime_contract.md` (LOCKED).

Wave R Prime layers **real runtime combat** onto the v1.7 NPC behavior runtime: NPC
pressure and hazards now deal actual damage, player health mutates at runtime, and
combat state persists through an independent save/load. This document states plainly
what the milestone proves, what it does NOT, and the honesty rules the gates enforce
so a reviewer never has to take a green check on faith.

## What Wave R Prime is designed to prove

When the one authorized 120-scenario UE matrix has run and committed its evidence, a
`combat_completed_runtime` scenario proves ALL of the following on real engine
runtime (headless `-game`, no editor, no navmesh, no teleport/flight — same spine as
v1.6z/v1.7):

- **Real damage** — ≥1 `WF_COMBAT_DAMAGE` event with `after < before`; the ordered
  set of those markers IS the completion report's top-level `damage_events` list.
- **Health mutation** — `player_min_health < player_max_health`; the player's health
  genuinely dropped at runtime, it was not a decorative counter.
- **Combat save/load** — combat state persists to the `WFCombat_State` slot,
  **distinct** from the mission (`WFRuntime_Complete`) and NPC (`WFNPC_State`) slots,
  and reload-verifies (`WF_COMBAT_VERIFY persisted_true`).
- **Winnability under baseline** — the player survives (`final_health > 0`) AND the
  mission still completes; combat pressure challenges the mission without making it
  unwinnable.
- **Unwinnable / no-damage detection** — a profile whose baseline damage ≥ max health,
  or that expects zero damage, is rejected at the contract layer
  (`COMBAT_UNWINNABLE_BASELINE` / `COMBAT_NO_DAMAGE_EVENTS`).
- **Hostile rejection** — every fake-combat vector is rejected for its owning code:
  zero-damage "events", success with `damage_events == []`, `min == max` health,
  mission-not-completed, save/load-fail, missing damage telemetry.

## Current state — the 120 matrix has NOT run (read this first)

**There is NO real combat evidence in this branch yet.** The C++ combat spine
(`WFRuntime.{h,cpp}`) is authored and compiling and emits the `WF_COMBAT_*` markers,
and the entire authoring + validation + hostile substrate is in place and green on
synthetic input — but `procedural/reports/combat/{completion,telemetry,save_load}/`
contains **zero `cs_*.json` evidence files**. Per the contract §6 hard gate, the
120-scenario matrix is launched only after a compile + 1-scenario smoke proves a
valid `cs_*.json` with a non-empty top-level `damage_events`.

Consequently, honestly:

- **P0/P1/P2 runtime combat is NOT claimed.** No "120/120 combat_completed_runtime"
  claim is made or implied until the matrix runs and commits evidence.
- The evidence-reading gates (`combat_report_integrity`, `combat_hygiene`) **PASS on
  the empty tree** because there is genuinely nothing to violate — but they do **not**
  green vacuously: each dogfoods its own logic in-memory (report_integrity flags a
  fake completion with `damage_events == []` / no mutation and passes a real one;
  hygiene flags an orphan `cs_*.json` + UE-transient junk on a throwaway temp fixture
  and passes a clean tree). Pointed at real, non-empty evidence they will fail-closed
  on any fake-green record.

## Hostile / hygiene lane status (Agent 7)

All green on synthetic input under `PYTHONUTF8=1 STRICT=1`:

```
combat_report_integrity --strict    PASS  (meta envelope + top-level damage_events +
                                           fake-completion rejection; dogfood real/fake)
combat_hygiene --strict             PASS  (orphan/stale cs_*.json + UE-transient/junk
                                           scan; dogfood clean/dirty temp fixture)
combat_negatives --strict           PASS  (26 negative fixtures, each rejected for its
                                           owning failure code)
combat_fuzz --cases 300 --seed 1337 PASS  (300 malformed mutants, 0 wrongly accepted,
                                           0 validator crashes)
combat_torture --strict             PASS  (corrupt-real-record + determinism +
                                           partial!=full, 5 contracts)
```

- `combat_report_integrity` now additionally enforces the contract §4 combat honesty
  burden on `completion/cs_*.json`: a non-empty **top-level `damage_events`** list of
  real `DamageEvent`s, and rejection of any `combat_completed_runtime` claimed with
  `damage_events == []` or `player_min_health == player_max_health`.
- `combat_hygiene` (new) asserts no orphan/stale/synthetic `cs_*.json` (every evidence
  id must be generatable from the 120 v1.7 behavior scenarios — `cs_<id>` from
  `bs_<id>`) and no UE transients / crash logs / local save-slot junk under the combat
  tree.
- `.gitignore` gained an append-only UE-transients stanza (`*.sav`, `*.dmp`, `*.mdmp`,
  `*-Crash.log`, `*.runtime-xml`, `Saved/Crashes/`) covering the local-runtime junk a
  combat playtest can drop that was not already ignored. Verified with `git check-ignore`;
  no previously-tracked file is newly ignored.

## Hard non-goals (deferred — NOT in Wave R Prime)

Combat here is **damage + health + persistence + winnability**, layered on the existing
pressure substrate. Explicitly OUT of scope and NOT implemented:

- **No weapons / abilities** — no weapon actors, ammo, cooldowns, or ability system.
  Damage comes only from NPC pressure and hazard zones.
- **No boss / elite / phase encounters.**
- **No tactical AI** — no combat decision-making, target selection, flanking, morale,
  or squad coordination beyond the v1.7 pressure model.
- **No cover system** — no cover queries, cover-seeking, or line-of-sight combat logic.
- **No navmesh dependency** — unchanged from v1.6z/v1.7; movement is grounded
  waypoint traversal, not navmesh pathfinding.

Any of these appearing "supported" in a report would be a defect; the contract taxonomy
reserves no success class for them.

## One-full-120-matrix policy

The 120-scenario UE combat matrix is **expensive and authorized to run ONCE** after the
compile + smoke gate passes (contract §5/§6). It is **never** rerun for
metadata-only, report-only, or documentation changes — those are proven on synthetic
fixtures by the hostile/hygiene gates above. If a change alters real combat semantics
(C++ damage/health/save-load), the smoke gate is re-proven before any rerun is
considered. Re-running the matrix to "refresh" green evidence is a fake-work smell and
is not permitted.
