# WorldForge v2.5.1 — Transition Integrity Closure (Lane 0 ledger)

Commander: Lane 0. Integration worktree: `D:\Unreal Projects\WorldForge-v251` (CLEAN).
Branch: `worldforge/v2.5.1-transition-integrity`, off the real merged `main` @ `87977097`
(PR #35 merge commit, verified via `gh pr view 35`).
UE 5.8: `D:/UE_5.8` (5.8.0-55116800). Last updated: 2026-07-14.

v2.5.1 adds **no new product capability**. It closes proof debt in two capabilities v2.5
already claims: conversion integrity and bridge readiness.

## Commander decisions (binding)

1. **Fresh worktree is the release surface.** Neither dirty worktree is used for
   integration. Both are preserved as forensic sources — inventoried with hashes at
   `procedural/reports/v2_5_1/forensics/` before any lane ran. Nothing deleted.
2. **Disjoint file ownership** (below). Lanes do not commit; Lane 0 commits.
3. **Lane 1 owns the canonical manifest format** and merged FIRST — every downstream
   lane reads its schema.
4. `failure_codes.py` is **read-only to all lanes**. No new codes; v2.5.1 must be
   expressible in the existing WF1011–1039 band or the finding is wrong.
5. **The dry probe survives as a NEGATIVE test.** It may never satisfy a positive gate.

## Ownership manifest (disjoint)

| Lane | Scope | Owned paths |
|------|-------|-------------|
| 0 | commander | this ledger; all commits; `procedural/reports/v2_5_1/forensics/`; final clean-checkout gate |
| 1 | canonical manifest | `build_canonical_conversion_manifest.py`, `canonical_conversion_manifest.json` |
| 2 | census reconciliation | `reconcile_map_census.py`, `validate_map_census_reconciliation.py`, `procedural/reports/ue5_8/census/`, lane-2 status |
| 3 | classification semantics | `audit_conversion_diff.py`, `validate_conversion_audit.py`, `procedural/reports/ue5_8/audit/`, lane-3 status |
| 4 | live bridge | `tools/bridge/**`, `gloam_bridge_live.py`, `validate_gloam_bridge_live.py`, `procedural/reports/ue5_8/gloam/live/`, fixture project (outside repo), lane-4 status |
| 5 | shield + hostile | `v2_5_shield.py`, `procedural/known_bads/v2_5_1/**`, hostile runners, lane-5 status |
| 6 | provenance closure | investigation only; recommendations to Lane 0 |

## Lane status

| Lane | Status | Latest | Blockers |
|------|--------|--------|----------|
| 0 | ACTIVE | clean worktree @ `87977097`; forensics captured; Lane 1 merged `4b99b6ae` | — |
| 1 | **MERGED** `4b99b6ae` | canonical manifest: 176 packages, one keyspace, both sides populated | — |
| 2 | ACTIVE | 131-vs-124 census reconciliation | — |
| 3 | ACTIVE | evidence-named classification vocabulary | needs Lane 1 schema (landed) |
| 4 | ACTIVE | live 5.8 fixture bridge proof | — |
| 5 | NOT_STARTED | shield hardening + hostile | needs Lanes 3 + 4 |
| 6 | ACTIVE | provenance / DoD #22 | — |

## Findings so far (Lane 1, verified)

**Correction to the v2.5 PR body and to my own earlier claim.** I reported the manifests
had "disjoint keyspaces (179 assets/0 maps vs 0 assets/124 maps)". That was wrong — I
compared top-level list lengths. The 124 map paths overlap **perfectly** (pre ∩ post =
124, zero either side).

The real defect was narrower: `conversion_manifest` recorded **maps only**, so the 55
non-map assets in `pre_conversion_manifest` had no post-conversion side. Running
`audit_conversion_diff` on the real pair therefore produced:

```
release_blocking: True
  124 -> expected_engine_conversion   (maps, correctly paired)
   55 -> broken_reference             FALSE — no post record, not a deletion
  first "broken reference": Content/.gitkeep
```

That is why the audit was never a shield gate: on real data it was noise.

Canonical manifest result — **176 packages, all `present_both`, zero broken references**;
3 non-package files (2× `.gitkeep`, `rock_generator.hda`) recorded as skipped.

**All 176 packages changed. ZERO have a package-version change.** UE 5.7 and UE 5.8 both
carry `FileVersionUE5=1018` / `FileVersionUE4=522` / `legacy=-9` — same last
`ObjectVersion` enum entry (`IMPORT_TYPE_HIERARCHIES`) in both engines' headers. So
`asset_version_upgrade`, currently applied to all 124 maps, is **unearned for every
package** — not merely suspect. Lane 3 owns the correction.

## Definition of done (11 items, from the closure brief)

| # | Item | State |
|---|------|-------|
| 1 | real 5.7/5.8 inventories share a canonical keyspace | ✅ Lane 1 |
| 2 | `audit_conversion_diff` runs against real manifests | ⏳ Lane 3 |
| 3 | all packages classified | ⏳ Lane 3 |
| 4 | all 7 map-count differences explained | ⏳ Lane 2 |
| 5 | `asset_version_upgrade` used only when earned | ⏳ Lane 3 (evidence: never earned) |
| 6 | CoreTerrainMaterials recorded+classified or reverted | ⏳ Lane 6 |
| 7 | live bridge run against a separate 5.8 project | ⏳ Lane 4 |
| 8 | dry probe can no longer satisfy the positive gate | ⏳ Lane 5 |
| 9 | shield fails on synthetic/stale substitute evidence | ⏳ Lane 5 |
| 10 | integration worktree clean | ⏳ Lane 0 final |
| 11 | v2.4/v2.3/v2.2 regressions green | ⏳ Lane 0 final |
