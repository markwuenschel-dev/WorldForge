# v2.5.1 Lane 5 — Shield hardening + hostile suite

Branch: `worldforge/v2.5.1-transition-integrity` · Worktree: `D:/Unreal Projects/WorldForge-v251`
Scope: DoD #8 (dry probe can no longer satisfy the positive gate) and #9 (shield fails on
synthetic/stale substitute evidence). Not committed.

**Verdict: RED — 20/22 gates.** The two v2.5 weaknesses are closed and cannot recur; the
shield is RED on **two pre-existing blockers that are outside this lane's ownership and
that I declined to soften**. Neither is caused by, nor fixable within, Lane 5.

## The shield after v2.5.1

```
                     v2_5_shield.py --strict … --regressions        22 gates
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ (always)      transition-contracts                                  PASS │
  │ --topology    transition-topology                                   PASS │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ --conversion  conversion-manifest                                   PASS │
  │             + root-coverage                              NEW v2.5.1 PASS │
  │             + conversion-audit                           NEW v2.5.1 PASS │
  │             + census-reconcile                           NEW v2.5.1 PASS │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ --plugin      plugin-build                                          FAIL │◄─ blocker 1
  │ --capability  capability-manifest                                   PASS │
  │ --regression  transition-regression                                 PASS │
  │ --baseline    transition-baseline                                   PASS │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ --bridge      gloam-bridge         (DRY  = NEGATIVE test)           PASS │
  │             + gloam-bridge-live    (LIVE = POSITIVE gate) NEW v2.5.1 PASS│
  ├──────────────────────────────────────────────────────────────────────────┤
  │ --hostile     transition-negatives · transition-fuzz                PASS │
  │               transition-report-integrity                           PASS │
  │               transition-hygiene                                    FAIL │◄─ blocker 2
  │               transition-known-bads · transition-torture            PASS │
  │             + v2.5.1-known-bads (9 vectors)              NEW v2.5.1 PASS │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ --regressions regress:v2.4 (10/10) · v2.3 (22/22) · v2.2 (22/22)    PASS │
  └──────────────────────────────────────────────────────────────────────────┘
                 19 gates without --regressions · 22 with
```

Exact command and result:

```bash
PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_5_shield.py --strict \
    --topology --conversion --plugin --capability --regression --baseline \
    --bridge --hostile --regressions
# v2.5 shield: RED — 20/22 gates passed
#   FAILED: ['plugin-build', 'transition-hygiene']
```

## The two v2.5 weaknesses, closed

### 1. A dry probe can no longer satisfy a positive claim

v2.5's `--bridge` was satisfied by `validate_gloam_bridge.py` **alone** — a gate over a
**rejecting dry probe**. A dry probe asserts that *nothing ran*; it is green precisely when
no far side was touched. That is a **negative** test, and a negative test can never satisfy
the positive claim *"the bridge works against a separate UE 5.8 project"*.

`--bridge` now requires **both** gates. Proven at **shield level**, by experiment:

| Experiment | `gloam-bridge` (dry) | `gloam-bridge-live` | Shield |
|---|---|---|---|
| live report **absent** | **PASS** | FAIL | **RED** 2/3 |
| **v2.5 dry probe substituted as the live report** | **PASS** | FAIL | **RED** 2/3 |
| real live report restored | PASS | PASS | GREEN 3/3 |

The middle row is the whole point: the dry probe **still passes its own gate** — it remains
a valid negative test, exactly as Lane 4 and the commander required — while the shield goes
**RED**, because the positive claim now demands positive evidence. Under v2.5 that same row
was GREEN. Row 1 proves the live gate fails **closed** rather than being skipped when its
evidence is missing.

### 2. Conversion claims must be earned

`--conversion` now carries `root-coverage`, `conversion-audit` and `census-reconcile`
alongside the original manifest gate. Verified at **shield level** (not merely at gate
level) by substituting each known-bad for the **real** evidence and re-running the shield:

| Real evidence replaced by | Shield |
|---|---|
| `synthetic_audit_presented_as_real` → canonical manifest | **RED** (`conversion-audit` + `root-coverage`) |
| `disjoint_manifest_keyspaces` → canonical manifest | **RED** (`conversion-audit` + `root-coverage`) |
| `identical_versions_labelled_version_upgrade` → canonical manifest | **RED** (`conversion-audit` + `root-coverage`) |
| `map_count_discrepancy_unclassified` → census payload | **RED** (`census-reconcile`) |

All evidence was restored **byte-identical to HEAD** afterwards (`git diff --quiet HEAD`
clean on both the manifest and the census payload). `root-coverage` independently rejects
every bad manifest as well — defence in depth that was not designed for, but is real.

The required conditions (`real_manifest`, `common_keyspace`, `unclassified_packages=0`,
`unaccounted_deletions=0`, plus Lane 2's `missing_maps_unclassified=0`) are therefore
enforced *by the shield*, not merely available in a gate nobody runs.

### Fail-closed, verified rather than assumed

Every new gate turns the shield RED when its **evidence** is absent *and* when its
**script** is absent:

| Removed | Result |
|---|---|
| `canonical_conversion_manifest.json` | `conversion-audit` FAIL, `root-coverage` FAIL |
| `map_census_reconciliation.json` | `census-reconcile` FAIL |
| `gloam_bridge_live_report.json` | `gloam-bridge-live` FAIL |
| `validate_conversion_audit.py` (the script) | `conversion-audit` FAIL *(gate not yet implemented)* |

## Why the new gates carry no new flags

They ride the **existing** flags whose claims they prove. `--conversion` already claims
"the conversion is sound"; `--bridge` already claims "the bridge is ready". The v2.5.1
gates are what make those claims true. Behind a new opt-in flag they would be optional —
and *an anti-fake-green gate you can forget to pass is not a gate*. The documented v2.5
acceptance command is unchanged and now gets the v2.5.1 hardening automatically. `--help`
stays honest because the flag surface did not change.

## Known-bads — 9 vectors, `procedural/known_bads/v2_5_1/`

Runner: `tools/pipeline/run_v2_5_1_known_bads.py` (**new**; the v2.5 runner
`run_transition_known_bads.py` was left untouched — it rides the frozen
`transition_contracts` validators and none of the v2.5.1 evidence surfaces exist there).
28 checks, all PASS.

| # | Vector / fixture | Driver (a **real** validator) | Owning check | Code | Origin |
|---|---|---|---|---|---|
| 1 | `synthetic_audit_presented_as_real` | Lane 3 gate `VCA.run` | `audit::real_manifest` | **WF1015** | authored |
| 2 | `disjoint_manifest_keyspaces` | Lane 3 gate `VCA.run` | `audit::common_keyspace` | **WF1015** | authored |
| 3 | `map_count_discrepancy_unclassified` | Lane 2 gate `VMCR.validate_present_report` | `present::no_unclassified_entries` | **WF1021** | authored |
| 4 | `identical_versions_labelled_version_upgrade` | Lane 3 gate `VCA.run` | `audit::unclassified_packages_zero` | **WF1021** | authored |
| 5 | `dry_probe_satisfies_live_gate` | Lane 4 `LIVE.validate_live_bridge_report` | *(contract)* | **WF1034** | **reused** — built from Lane 4's real `GBP.build_probe_report()` |
| 6 | `zero_exit_bridge_no_evidence` | Lane 4 contract | *(contract)* | **WF1028** | **reused** — Lane 4's `example_live_report` builder |
| 7 | `foreign_project_evidence` | Lane 4 **gate** `VGBL.validate_real_live_report` | `real::evidence_belongs_to_target` | **WF1024** | **reused** — Lane 4 gate + `evidence_belongs_to` |
| 8 | `stale_evidence_reuse` | Lane 4 contract | *(contract)* | **WF1026** | **reused** — Lane 4's builder |
| 9 | `manually_modified_audit_report` | `TRI.report_integrity_findings` | `manual_edit_ok_with_failures` | **WF1034** | **reused** — the shield's own report-integrity detector |

**Reused 5, authored 4.** All codes pre-existing, all inside WF1011–1039. **None added.**
Every driver is an imported, invoked **real validator** — never a reimplementation of a
rule. The gate functions called are pure (they take a `ValidationReport` and do not
persist), so the harness cannot clobber another lane's report; the only file it writes is
its own.

### Three design decisions worth the ink

**Fixtures are PURE artifacts; metadata lives in `index.json`.** The v2.5 catalogue embeds
`_expected_code`/`_contract` inside each fixture. That idiom is unsafe here: Lane 4's live
contract enforces `live::no_unknown_fields`, so an embedded harness key would get the
fixture rejected **for carrying harness metadata** rather than for its vector — a rejection
that proves nothing while looking green. Each fixture is therefore byte-for-byte what a
dishonest submitter would actually present.

**Rejection must come from the OWNING CHECK, not just the owning code.** A dishonest report
trips many rails at once — the dry probe alone trips ten codes. Asserting only the code lets
a fixture "pass" on a rejection unrelated to its vector. Vector 7 is the proof of need: its
foreign path is *relative* (`../SomeOtherProject/...`), so it slips past the absolute-path
rail (WF1029) entirely and **the live contract accepts it outright** — only the gate-level
project-membership rail catches it. Pinning it to `real::evidence_belongs_to_target` is what
makes that fixture mean what it says.

**Positive controls.** A rejecter that rejects everything proves nothing, so each driver
must also *accept* the honest artifact (`control::conversion_audit_accepts_real_manifest`,
`control::live_contract_accepts_valid_report`,
`control::report_integrity_accepts_clean_report`). Rejection is only evidence when
acceptance is possible.

**The harness is itself load-bearing** — verified, not assumed: replacing a known-bad with a
valid artifact turns it RED (`kb::zero_exit_bridge_no_evidence::rejected: known-bad was
ACCEPTED`), and a driver that *crashes* on hostile input is scored a **failure**, not a
rejection — a validator that explodes has not judged the input.

### Vector 4 — what actually rejects it, and what does not

`identical_versions_labelled_version_upgrade` is the v2.5 bug (`asset_version_upgrade` on
all 124 maps, with UE 5.7 and 5.8 sharing `FileVersionUE5=1018`). The fixture declares
`classification: "asset_version_upgrade"` on a package whose CORE **and** CUSTOM versions
are identical on both sides and whose engine stamp never moved.

It is rejected — but **not** by catching the label. The declared `classification` field is
**consumed by nothing** (confirmed: zero reads in `audit_conversion_diff.py` and
`validate_conversion_audit.py`); the audit derives its own labels from evidence. The
rejection comes from **the evidence refusing to support a claim**: with no version delta and
no engine move, nothing explains the changed bytes, the classifier declines every benign
label, and the package lands in `unclassified` → **WF1021** → RED. The claim cannot be made
because it cannot be earned. That is the stronger property, and it is the one that holds.

## What I could not honestly gate

**`audit::version_claims_are_earned` (WF1034) is structurally unfireable from a manifest
fixture.** It re-derives the version delta from the same record the classifier read, and the
classifier emits `package_version_changed` only when `_core_delta` or `_custom_delta` is
non-empty — so the two always agree. It is a **classifier-regression tripwire**, not a
manifest-tampering gate. It is worth keeping (it would fire if the classifier regressed),
but no known-bad can exercise it and I did not fabricate one that appears to. Vector 4 is
gated on WF1021 instead, which is real and fires.

**The declared `classification` field is unvalidated.** Nothing reads it, so nothing can
reject a manifest that declares a dishonest label. Today this is latent rather than
exploitable — no downstream claim is built on the field — but it is an unguarded surface a
future consumer could start trusting. Flagged for Lane 0; adding a rail would mean editing
Lane 3's validator, which I do not own.

## The two blockers (RED) — pre-existing, not mine, not softened

### Blocker 1 — `plugin-build` (WF1019 + `overall_ok`)

**This integration worktree has never been built.** All three plugin DLLs are **missing**:

```
newest C++ source : 2026-07-14 15:24:31  Source/WorldForgeEditor.Target.cs
WorldForgeCore    : MISSING  Plugins/WorldForge/Binaries/Win64/UnrealEditor-WorldForgeCore.dll
WorldForgeEd      : MISSING  Plugins/WorldForge/Binaries/Win64/UnrealEditor-WorldForgeEd.dll
WorldForge        : MISSING  Binaries/Win64/UnrealEditor-WorldForge.dll
```

With no binaries, `binary_mtime` falls back to `0.0`, so `not_stale`
(`binary_mtime >= newest_source_mtime`) fails and `overall_ok` fails. The message says
*"binaries must not predate newest C++ source (stale)"*, which reads misleadingly for the
**missing** case — but the RED is **correct**: no binaries means no proof the plugin builds
or loads.

Pre-existing and independent of Lane 5: the gate rebuilds its evidence from live disk state
each run, and depends only on worktree build state, which I did not change. The committed
report says `ok` because it was produced in a tree that *had* binaries — the same mechanism
Lane 2 documented for the untracked scratch maps: **build artifacts do not propagate to a
`git worktree`.**

*Fix (not Lane 5's):* build the WorldForge plugin against UE 5.8 in this worktree. That
requires running the UE toolchain, which this lane's brief forbids, and
`validate_plugin_build.py` is not a file I own. **Not fakeable, and not faked.**

### Blocker 2 — `transition-hygiene` (WF1037) — mixed: 179 false positives + 2 real findings

Three files are flagged, all committed at HEAD and **unmodified by me** — Lane 3's
`conversion_diff_audit.json`, Lane 2's `map_census_reconciliation.json`, Lane 4's
`gloam_bridge_live_report.json`. My own report produces **zero** hygiene findings.

**179 of 181 findings are FALSE POSITIVES.** `transition_hygiene.py:39` uses
`_ABS_PATH_RE = ^([A-Za-z]:[\\/]|[\\/])`, so **any** leading `/` reads as an absolute
filesystem path — but `/Game/Maps/Desert_Valley_01` and `/CoreTerrainMaterials/...` are UE
**package paths**: machine-independent logical paths. They reach the rail because
`_is_path_key` treats any key ending `_path` as a path, and Lane 1's canonical keyspace is
literally `package_path`. The rail predates the keyspace: v2.5 carried repo-relative **file**
paths (`Content/Maps/x.umap`), which have no leading slash. **The commander-mandated
keyspace and the v2.5 hygiene rail are in direct conflict.**

**2 findings are GENUINE and should be fixed:**

1. **A real machine-path leak** — `conversion_diff_audit.json` carries
   `manifest_path = "D:\Unreal Projects\WorldForge-v251\procedural\manifests\…"`. Should be
   repo-relative. (Lane 3's producer; `ACD.CANONICAL_MANIFEST` is an absolute `Path` and is
   `str()`-ed straight into the payload.)
2. **A transient-path reference** — `gloam_bridge_live_report.json` `evidence_entries[1]` is
   `Saved/WorldForgeBridge/op_v2_5_1_gloam_bridge_live_0001/far_side_response.json`.
   Hygiene forbids `Saved/` (`FORBIDDEN_DIRS`); Lane 4's `FIXTURE_ROOT_DIRS` explicitly
   **allows** `Saved` as a legitimate evidence root. A genuine policy disagreement about
   whether a far-side response written to a transient directory is durable evidence.

I did not fix any of it: `transition_hygiene.py` is a v2.5 validator and the three payloads
belong to Lanes 2/3/4 — none are mine. Widening the rail to make my lane green is precisely
the laundering this lane exists to prevent, and the 2 genuine findings are exactly what
would have been laundered away with it.

*Recommended for Lane 0 (in priority order):*
1. Teach the `_ABS_PATH_RE` consumers that a UE package path is not a machine path (e.g.
   exempt `^/(Game|<PluginName>)/`, or key on `package_path` semantics). Note the same regex
   is duplicated in `tools/bridge/live.py:58` — fix both or neither.
2. Lane 3: emit `manifest_path` repo-relative.
3. Adjudicate Lane 4's `Saved/` evidence entry against the hygiene policy.

Until (1) lands, `--hostile` cannot go green on the v2.5.1 evidence set. That is an honest
RED, and I am leaving it RED.

## DoD

| # | Item | State |
|---|------|-------|
| 8 | dry probe can no longer satisfy the positive gate | ✅ proven at shield level, by experiment |
| 9 | shield fails on synthetic/stale substitute evidence | ✅ proven at shield level, by experiment |

## Files owned / touched

| File | Change |
|---|---|
| `tools/pipeline/v2_5_shield.py` | **extended** — 4 new gates + 1 hostile gate; existing 14 gates and `--regressions` unchanged and still passing |
| `tools/pipeline/run_v2_5_1_known_bads.py` | **new** — 9-vector hostile harness |
| `procedural/known_bads/v2_5_1/**` | **new** — 9 pure fixtures + `index.json` |
| `docs/status/v2_5_1_lane_5_status.md` | **new** — this file |

Not edited: any other lane's validator, the canonical manifest, any census,
`failure_codes.py`, `transition_contracts.py`, `transition_hygiene.py`,
`run_transition_known_bads.py`, `gloam_bridge_probe.py`, `validate_gloam_bridge.py`.

Runtime-free lane: Unreal was never run. The live bridge report was **validated**, not
regenerated (`gloam_bridge_live_report.json` restored byte-identical to HEAD after the
substitution experiments).

## Commands

```bash
cd "D:/Unreal Projects/WorldForge-v251"

# hostile catalogue
PYTHONUTF8=1 STRICT=1 python tools/pipeline/run_v2_5_1_known_bads.py --strict
PYTHONUTF8=1 STRICT=1 python tools/pipeline/run_v2_5_1_known_bads.py --strict --no-regen

# full shield (--regressions takes several minutes)
PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_5_shield.py --strict \
    --topology --conversion --plugin --capability --regression --baseline \
    --bridge --hostile --regressions
```
