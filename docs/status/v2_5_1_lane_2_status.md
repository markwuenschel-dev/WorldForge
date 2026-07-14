# v2.5.1 Lane 2 — Map-Census Reconciliation Status

**Branch:** `worldforge/v2.5.1-transition-integrity`
**Verdict:** **GREEN** — 7/7 of the 5.7-only packages carry an evidence-backed
classification; `unclassified = 0`.

## The finding

The 131-vs-124 delta is **not a conversion loss**. It is **7 untracked editor scratch
maps** that existed in the primary worktree's working directory when the 5.7 census
ran, and did not exist in the tree where the 5.8 census and the pre-conversion
manifest ran.

```
5.7 census   131 maps   total_actor_count = 2799
5.8 census   124 maps   total_actor_count = 2799   <- identical
delta         7 maps    actors in those 7 =    0   <- actor-neutral
```

5.8 is a **strict subset** of 5.7 (`only_5_8 = 0`). No map was renamed, redirected,
or silently dropped.

## Root cause

`wf_map_actor_census.py` enumerates `/Game` through the **AssetRegistry**, which
walks the **working directory** — it does not care whether a package is tracked by
git. An untracked scratch `.umap` sitting in `Content/Maps` is therefore counted.
`build_conversion_manifest.py` `rglob()`s the same `CONTENT_ROOTS` and so agrees with
the census *for the tree it ran in* (`map_count = 124`, matching 5.8 exactly).

The delta is a property of **working-tree content**, not of the 5.7 → 5.8 transition.

## The 7 packages — all `generated_or_transient`

| Package | Classification |
| --- | --- |
| `/Game/Maps/_wf_lit_lit_mi_ash` | `generated_or_transient` |
| `/Game/Maps/_wf_lit_lit_mi_sand` | `generated_or_transient` |
| `/Game/Maps/_wf_test_lvl` | `generated_or_transient` |
| `/Game/Maps/_wf_test_lvl_ash` | `generated_or_transient` |
| `/Game/Maps/_wf_test_lvl_mi_ash` | `generated_or_transient` |
| `/Game/Maps/_wf_test_lvl_mi_sand` | `generated_or_transient` |
| `/Game/Maps/_wf_test_lvl_sand` | `generated_or_transient` |

### Evidence (identical for all 7)

1. **Empty in the 5.7 census** — `actor_count = 0`, empty `class_histogram`,
   `loaded = true`, `error = null`. They loaded fine; they simply contain nothing.
2. **Never committed** — absent at `HEAD`, absent at tag `worldforge-v2.4-ue5.7-final`,
   and `git log --diff-filter=D --all` shows no deletion. Never added ⇒ never deleted.
3. **Not gitignored** — `git check-ignore` returns nothing; they are genuinely
   untracked working-tree files, not an ignore-rule artifact.
4. **Absent from this worktree on disk** — untracked files do not propagate to a
   `git worktree`, which is exactly why the 5.8-side tree never saw them.
5. **Absent from `pre_conversion_manifest.json`** — whose `map_count` is 124, matching
   the 5.8 census exactly.
6. **UE's own record** (corroboration) — all 7 appear in the primary worktree's
   `Saved/SourceControl/UncontrolledChangelists.json`, i.e. the editor itself logged
   them as created outside source control.
7. **Single scratch session** — all 7 mtimes fall in a 7-minute window
   (2026-06-25 16:21–16:28), alongside `Content/Maps/_wf_test/M_wf_test_{ash,sand}.uasset`.
8. **Already known** — `docs/status/v1_7_pr_readiness.md:69` calls them out verbatim as
   "Untracked environment clutter (…`_wf_test` maps…)".

Naming corroborates: `_wf_test_lvl*` are scratch test levels, `_wf_lit_*` / `*_mi_*`
are lighting / material-instance probes across the ash/sand variants.

## Files

| File | Role |
| --- | --- |
| `tools/pipeline/reconcile_map_census.py` | Reconciler — 11 evidence probes → closed-vocabulary classification |
| `tools/pipeline/validate_map_census_reconciliation.py` | Fail-closed gate — any `unclassified` ⇒ RED |
| `procedural/reports/ue5_8/census/map_census_reconciliation.json` | Reconciliation payload (131 entries) |
| `procedural/reports/ue5_8/census/validate_map_census_reconciliation_report.json` | Gate report (35 checks, all PASS) |

## Failure codes used (all from the existing WF1011–1039 band; none invented)

| Code | Where | Why |
| --- | --- | --- |
| `WF1021_REGRESSION_UNCLASSIFIED_DIFF` | the bright line | An unexplained cross-engine map diff is exactly an unclassified diff. Fires on any `unclassified` entry and on any 5.7-only entry lacking a resolved reason. |
| `WF1014_CONVERSION_ACTOR_LOSS` | actor rails | If a 5.7-only map carried actors, dropping it *is* silent actor loss — not a classification. Also guards the 2799 == 2799 identity. |
| `WF1015_CONVERSION_MANIFEST_INCOMPLETE` | input rails | Absent/unparseable/empty payload or unreadable censuses = an incomplete inventory; fail closed. |
| `WF1034_TRANSITION_REPORT_INTEGRITY_FAILED` | integrity rails | Vocabulary escapes, unparseable payload, set-algebra mismatch, missing evidence records. |
| `WF1037_TRANSITION_HYGIENE_FAILED` | hygiene rails | `only_5_7` laundered into a resolved classification; `--force-unclassified` left enabled; a retired 5.7 asset mislabelled as scratch. |

## Anti-fake-green design

- **`only_5_7` is a membership label, never a resolved reason.** Since the gate only
  fails on `unclassified`, allowing `only_5_7` as a terminal classification would be a
  silent pass-through hole. The rule chain therefore emits `unclassified` — never
  `only_5_7` — for an unresolved 5.7-only package, and a dedicated rail enforces it.
- **The gate recomputes set algebra and actor totals from the raw censuses** rather
  than trusting the payload's own `counts`.
- **4 inline known-bads** prove the classifier cannot be fooled: an actor-bearing map
  cannot reach `generated_or_transient`; a package tracked at the 5.7 tag but gone at
  HEAD cannot be laundered into scratch; an on-disk-but-uninventoried package under
  `CONTENT_ROOTS` is `unclassified` (that combination is impossible given `rglob`, so
  it is a real bug, not a reason); unexplained evidence terminates in `unclassified`.
- **`--force-unclassified` is recorded in the payload** (`forced_unclassified`) and a
  gate rail fails on it, so a forced proof run can never be mistaken for a real green.

## Commands

```bash
PYTHONUTF8=1 STRICT=1 python tools/pipeline/reconcile_map_census.py
PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_map_census_reconciliation.py --strict
```

Fail-closed proof (note `MSYS_NO_PATHCONV=1` — Git Bash otherwise rewrites `/Game/...`
into a Windows path and the force silently no-ops):

```bash
MSYS_NO_PATHCONV=1 PYTHONUTF8=1 STRICT=1 python tools/pipeline/reconcile_map_census.py \
    --force-unclassified=/Game/Maps/_wf_test_lvl
PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_map_census_reconciliation.py --strict  # exit 1
PYTHONUTF8=1 STRICT=1 python tools/pipeline/reconcile_map_census.py                         # restore
```

## Caveats

- The 7 scratch maps still sit untracked in the primary worktree
  (`D:\Unreal Projects\WorldForge`). Any future 5.7-side census run from that tree will
  count 131 again. Deleting them is out of Lane 2's scope — flagged for the operator.
- The `UncontrolledChangelists.json` probe reads `Saved/`, which is not tracked and is
  absent from this worktree. It is recorded as **corroboration only**
  (`uncontrolled_changelist_probe_available: false` here) and never changes a
  classification — the load-bearing probes are git, disk, manifest, and census.
- Runtime-free by construction: `observed_runtime_engine=None`,
  `runtime_execution_required=false`, `runtime_executed=false`. Unreal was not run.
