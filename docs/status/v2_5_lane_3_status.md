# v2.5 UE58Transition — Lane 3: Conversion Manifest + Pre-Conversion Inventory

Status: **Inventory + validators DONE. Conversion gate intentionally RED (honest).**
Worktree: `D:\Unreal Projects\WorldForge-UE58` — branch `worldforge/v2.5-ue58-transition`.
Wave scope: INVENTORY + VALIDATORS ONLY. No editor opened, no asset resaved, no
`.uasset`/`.umap` written. Authoritative binary conversion is the commander's serial job.

## Objective

Prepare — read-only — for the authoritative UE 5.7 -> 5.8 asset/map conversion:

1. A deterministic **pre-conversion inventory** of every asset the conversion will touch
   (path, size, streamed sha256, path/extension/redirector classification). Actor counts
   are **not** extractable without a loaded editor, so they are recorded as
   `actors_before = null` / `actors_note = "unknown_without_editor"` — never fabricated.
2. A fail-closed **conversion gate** for the shield that dogfoods the `ConversionManifest`
   contract and refuses to green until the commander's authoritative manifest exists.
3. An **audit scaffold** that will diff pre- vs post-conversion manifests and classify
   every changed asset, blocking on actor loss / broken references / unexplained churn.

## Files created

| File | Role |
|------|------|
| `tools/pipeline/build_conversion_manifest.py` | Read-only walk of content roots -> deterministic pre-conversion inventory |
| `tools/pipeline/validate_conversion_manifest.py` | Shield `--conversion` gate: dogfoods contract, fails closed until authoritative manifest exists |
| `tools/pipeline/audit_conversion_diff.py` | Pre/post diff classifier (scaffolding, dogfooded on synthetic manifests) |
| `procedural/manifests/ue5_8_conversion/pre_conversion_manifest.json` | Generated inventory (machine-generated only — never hand-edit) |
| `docs/status/v2_5_lane_3_status.md` | This handoff |

No shared files touched (`failure_codes.py`, `engine_identity.py`, `transition_contracts.py`,
the shield, other lanes' files all untouched). No existing `Content/` asset modified or deleted.

## Contract dogfooded

`transition_contracts.ConversionManifest` (`validate_conversion_manifest` /
`_example_conversion_manifest`). The gate proves the canonical valid example passes with
zero failures AND the registered known-bad (a map losing an actor with no accounted
deletion) is **rejected for its owning code `WF1014_CONVERSION_ACTOR_LOSS`**. A validator
that greened actor loss would be a fake-green vector; this gate would turn RED if so.

## Exact commands + real output

```
$ PYTHONUTF8=1 python tools/pipeline/build_conversion_manifest.py
[pre-conversion-inventory] 179 assets, 124 maps, 15850284 bytes -> procedural\manifests\ue5_8_conversion\pre_conversion_manifest.json
[pre-conversion-inventory] counts_by_type: {"blueprint": 0, "data_asset": 8, "map": 124, "material": 15, "other": 17, "redirector": 0, "texture": 15}
[pre-conversion-inventory] conversion_status = pre_conversion_inventory (actor counts deferred: unknown_without_editor)
```
Determinism verified: two consecutive runs produce identical
`meta.output_manifest_hash = 0a9b698709a98946757362c392cdc577908b27a791a1efe72379c2bada1f0d63`
(git_sha/timestamp are runtime-only per `report_meta`).

```
$ PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_conversion_manifest.py --strict
[conversion-gate] FAIL — worldforge_vertical_slice (1 failure(s), 0 warning(s), strict=on)
[conversion-gate]   FAIL: conversion::authoritative_manifest_present: authoritative conversion not yet performed: expected procedural/manifests/ue5_8_conversion/conversion_manifest.json ...
[conversion-gate] EXPECTED RED: the authoritative UE 5.7 -> 5.8 conversion has not been performed. This is the honest pre-conversion state, not a defect.
EXIT=1
```
The three contract-dogfood checks PASS; the single failure is the deliberate
authoritative-manifest-present gate.

```
$ PYTHONUTF8=1 python tools/pipeline/audit_conversion_diff.py
[conversion-audit] clean-case release_blocking=False bins={'expected_engine_conversion': 1, 'redirector_cleanup': 1, ...}
[conversion-audit] actor-loss-case release_blocking=True bins={..., 'actor_loss': 1, ...}
[conversion-audit] DOGFOOD PASS: clean benign, actor-loss release-blocking. (scaffolding only — not run on real conversion output; none exists)
EXIT=0
```

## Pre-conversion inventory stats

| Type | Count |
|------|-------|
| map (`.umap`) | 124 |
| material (`M_`/`MI_`) | 15 |
| texture (`T_`) | 15 |
| data_asset (`DA_`) | 8 |
| other (`SM_`/`PCG_`/`.hda`/`.gitkeep`) | 17 |
| blueprint | 0 |
| redirector | 0 |
| **total assets** | **179** |
| **total bytes** | **15,850,284 (~15.12 MB)** |

Roots walked (read-only): `Content/` (178 files) and `Plugins/WorldForge/Content/`
(1 `.gitkeep`). Classification is path/extension based, with a cheap read-only byte scan
for the `ObjectRedirector` class marker (none found — 0 redirectors in-tree pre-conversion).

## Why the conversion gate is honestly RED

The authoritative UE 5.7 -> 5.8 conversion has **not been performed**. Proving no silent
actor loss requires **real** per-map actor counts from a loaded 5.8 UWorld — which only the
commander's serial editor pass can produce. The pre-conversion inventory carries
`actors_before = null` by design and is explicitly **rejected as a substitute**: greening
off it would launder an unperformed conversion into a pass. RED here is the correct,
honest state for this wave (code `WF1015_CONVERSION_MANIFEST_INCOMPLETE`).

## Commander authorization — prerequisites for the conversion window

1. **Serial, not parallel.** The authoritative conversion resaves shared binary assets; it
   must be the commander's single-threaded job while no other lane writes `Content/`.
2. **Engine truth.** Run under real UE 5.8 (`D:\UE_5.8`) out of this worktree so
   `engine_identity()` resolves `engine_minor = 8` from `Build.version` (not the uproject).
3. **Real actor accounting.** For every map, record `actors_before` (from the 5.7 baseline)
   and `actors_after` (from the loaded 5.8 world) plus any `accounted_deletions` — never
   `null`, never inferred.
4. **Explain all churn.** Every changed asset must carry an accounted `churn_class`
   (`asset_version_upgrade` / `redirector_fixup` / `expected_resave`); unaccounted churn
   fails the contract (`WF1016`).

## To flip the gate GREEN (single source of truth)

Write the authoritative manifest to the canonical path:

```
procedural/manifests/ue5_8_conversion/conversion_manifest.json
```

It must:
- carry top-level completeness flag **`"conversion_status": "complete"`**, AND
- pass `transition_contracts.validate_conversion_manifest(..., strict=True)` with zero
  failures (source_engine `5.7`, target_engine `5.8`, `expected_map_count == len(maps)`,
  no `WF1014` actor loss, no `WF1016` unaccounted churn).

Then `validate_conversion_manifest.py` greens. After conversion, run
`audit_conversion_diff.py` with the pre-conversion inventory + the authoritative manifest
to confirm no release-blocking change (actor_loss / broken_reference / unexpected_binary_churn
/ unexplained) slipped through.

## Limitations

- Actor counts are absent by design (no editor). The inventory proves file identity, not
  world contents.
- Classification is heuristic (path/extension + redirector byte scan); a `.uasset` whose
  class disagrees with its naming prefix would be mis-binned. This affects reporting
  granularity only — the conversion contract's actor/churn honesty checks are independent.
- The audit tool is scaffolding, dogfooded on synthetic manifests only. It has NOT been run
  against real conversion output because none exists yet (by design this wave).

## Meta convention

All emitted reports attach `build_meta(extra=...)` with `declared_target_engine="5.8"`,
`observed_runtime_engine=None`, `runtime_execution_required=False`, `runtime_executed=False`
— this lane is read-only / runtime-free and makes no UE-observation claim.

## Git status (lane files, all untracked — NOT committed per swarm policy)

```
?? procedural/manifests/ue5_8_conversion/
?? procedural/reports/ue5_8/validate_conversion_manifest_report.json
?? tools/pipeline/audit_conversion_diff.py
?? tools/pipeline/build_conversion_manifest.py
?? tools/pipeline/validate_conversion_manifest.py
?? docs/status/v2_5_lane_3_status.md
```
