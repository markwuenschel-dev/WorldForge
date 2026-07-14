# v2.5.1 Lane 3 — Conversion classification describes OBSERVED EVIDENCE

Branch: `worldforge/v2.5.1-transition-integrity` · Worktree: `D:/Unreal Projects/WorldForge-v251`
Status: **GREEN on real evidence.** 12/13 checks PASS, 1 WARN_ONLY (surfaced, not silenced),
0 FAIL. Every version field is now genuinely parsed (custom 178/178, was 0/178). Not committed.

## Mission

Make conversion classification describe **observed evidence**, not the assumed operation.
A label that names an operation nobody verified is a fake green.

## Files owned

| File | Role |
|---|---|
| `tools/pipeline/audit_conversion_diff.py` | The classifier — evidence-named labels |
| `tools/pipeline/validate_conversion_audit.py` | Fail-closed gate over the REAL canonical manifest |
| `procedural/reports/ue5_8/audit/conversion_diff_audit.json` | Per-package evidence + labels (178) |
| `procedural/reports/ue5_8/audit/validate_conversion_audit_report.json` | Gate report |
| `docs/status/v2_5_1_lane_3_status.md` | This file |

Not edited: `build_canonical_conversion_manifest.py` (Lane 1), any census, any other
manifest, `v2_5_shield.py`, `failure_codes.py`, Lane 2's files.

## Results — full tally over 178 packages

```
[conversion-audit] packages=178 real_manifest=True common_keyspace=True
  unchanged                2
  package_version_changed  0
  actor_graph_changed      0
  engine_resave_only     176
  unclassified             0
version evidence known:      core=178/178  custom=178/178  stamp=178/178
actor_class_inventory known: 124/178 (124 maps; null for the 54 assets = UNKNOWN)
unclassified=0  unaccounted_deletions=0  actor_loss=0  class_loss=0  unconverted=2
release_blocking=False
```

178 = 124 maps + 54 assets. `package_version_changed` and `actor_graph_changed` are **live
rules with zero hits** — both fire on real evidence (proven on synthetics and on a mutated
real record), they simply have no evidence to fire on in this conversion.

## Evidence-base defects found by this lane (all now fixed by Lane 1)

| # | Defect | How it would have shipped |
|---|---|---|
| 1 | stale `CONTENT_ROOTS` (2 of 3 roots) | 2 packages invisible to the audit entirely |
| 2 | version parser read only CORE | "zero version changes across 176" — an artifact |
| 3 | custom-version offset off by 24 bytes | `custom_versions` null 178/178, reported as "0 changed" |

Defect 3 was the one this lane blocked on. Lane 1's root cause from the engine source
(`PackageFileSummary.cpp:176-184`): when `FileVersionUE >= PACKAGE_SAVED_HASH` (1016; our
packages are 1018) the summary carries `SavedHash` (FIoHash, 20B) + `TotalHeaderSize` (4B)
before the custom-version container — so the array starts at **52**, not 24. My diagnosis had
the symptom and mechanism right but guessed the array at 32 and misread `@44=5984` as a stray
value; it is `TotalHeaderSize`. Two independent methods then produced identical numbers
(`FUE5MainStream 121→123`, `FUE5Release 61→68`, `FFortniteMain 225→268`), which is the real
confirmation. Lane 1's fix is version-conditional on `PACKAGE_SAVED_HASH` rather than a magic
constant.

**Why blocking was the right call rather than a footnote:** certifying *"176 engine_resave_only,
no version change observed"* on a manifest that could not read custom versions is the mirror
image of the v2.5 bug — v2.5 claimed an upgrade that never happened; greening there would have
denied one that did. Both are false descriptions of a conversion. The gate blocked the
**evidence base** (WF1015) and never touched a label to manufacture a colour. The blocker is
now resolved on real data (`custom_versions_systematically_absent: false`) and
`audit::version_evidence_complete` **PASSES**.

## Label vocabulary — evidence rules

Null is UNKNOWN, never zero. Rule order listed; earlier rules win.

| # | Label | Exact evidence rule | Blocking |
|---|---|---|---|
| 1 | `unclassified` | not `present_both` (a `source_only` record is an unaccounted deletion) | **yes** |
| 2 | `unclassified` | source or converted hash null | **yes** |
| 3 | `unclassified` | `actor_class_inventory` total disagrees with `actor_count` — independently sourced, so a disagreement means neither can be trusted | **yes** |
| 4 | `unchanged` | both hashes non-null AND **equal**. Total evidence — identical bytes cannot hide a difference, so no unknown undermines it. Contradictions (equal hash but moved actor count / stamp / class inventory) → `unclassified` | no |
| 5 | `actor_graph_changed` | actor counts known AND `converted < source` — **actor loss** | **yes** (WF1014) |
| 5b | `actor_graph_changed` | class inventories known AND a class with count>0 in source is absent/zero after — **class loss**, fires at unchanged total count | **yes** (WF1014) |
| 6 | `unclassified` | CORE version dict null on either side | **yes** |
| 7 | `package_version_changed` | CORE differs — a package FORMAT change, outranks the resave that carried it | no |
| 8 | `actor_graph_changed` | actor gain, or class gained/shifted with nothing lost | no |
| 9 | `engine_resave_only` | hashes differ AND CORE equal AND `saved_by_engine_branch` known both sides AND **MOVED** (5.7→5.8). Custom delta recorded as corroborating evidence | no |
| 10 | `package_version_changed` | custom_versions known both sides AND differ AND **no stamp move explains it** | no |
| 11 | `unclassified` | bytes changed but stamp UNKNOWN, or the SAME engine wrote both sides | **yes** (WF1021) |

Both loss rules sit **before every benign label**, so a version move or a resave can never
mask an actor or class loss.

### Three kinds of version evidence — never diffed wholesale

The version dicts hold three unrelated things. A naive `src_dict != conv_dict` conflates them
and would fire a bogus `package_version_changed` on **all 176** converted packages, because
`saved_by_engine_branch` lives in the same dict. Guarded by `audit::stamp_not_diffed_as_version`.

- **CORE** — `file_version_ue4/file_version_ue5/legacy/licensee`. 5.7 and 5.8 share
  FileVersionUE5=1018, so CORE never moves here. Known 178/178, changed 0/178.
- **CUSTOM** — `custom_versions {guid: int}`. Known 178/178, **changed 174/178**.
- **STAMP** — `saved_by_engine_branch`. Not a version. Which engine wrote the bytes.
  Known 178/178, moved 176/178.

### The stamp IS the evidence for `engine_resave_only` — now proven by the data

Before the stamp, that bin meant "bytes changed and nothing else we can see moved" — a
residual argued from **absence**. With the stamp it means "**a different engine wrote these
bytes**": a positive observation of the operation the label names.

**Cause outranks effect.** My first cut ordered the version rule before the resave rule; MUT5
showed that yields **176 `package_version_changed` / 0 `engine_resave_only`** — the version
rule swallows the bin. Bumping custom versions is *what an engine resave does*, so a moved
stamp **claims** the custom delta and records it as corroboration.

The data now proves this was right, via the 4 packages whose custom versions did **not** move:

```
/Game/Materials/Terrain/DA_Terrain_Rock_Desert_Ash_01   hash DIFFERS, stamp 5.7->5.8, custom UNCHANGED
/Game/Materials/Terrain/DA_Terrain_Sand_Desert_01       hash DIFFERS, stamp 5.7->5.8, custom UNCHANGED
  -> engine_resave_only
     evidence: ['hash differs', 'CORE version identical', 'engine stamp MOVED 5.7->5.8',
                'custom_versions identical']
```

Had `engine_resave_only` been keyed off custom versions, these two 5.8-written DataAssets
would have been misclassified. The converse still bites: bytes changed with **no** stamp move
is not an engine resave → `unclassified` (zero hits; it exists so the benign bin cannot absorb
an anomaly).

### Honesty bound on `engine_resave_only` — unchanged

`_only` is scoped to the **observed** evidence set, not reality. It asserts "no other
difference is visible in this manifest", **not** "no other difference exists". Every result
carries an `unknown` list so the residual is auditable per record:

```
/Game/Maps/Desert_Valley_01  (map)
  evidence: ['actor_count 234->234', 'actor_class_inventory known (7 source class(es))',
             'hash differs', 'CORE version identical', 'engine stamp MOVED 5.7->5.8',
             'custom_versions moved on 4 guid(s) — consistent with, and explained by,
              the engine change']
  unknown : ['component_count=null(needs UWorld)', 'critical_references=null(needs UWorld)']
```

`component_count` / `critical_references` remain UNKNOWN-and-unobtainable and are **not**
blocked — a physical limit, recorded per-record, never read as zero.

## Class inventory (Q5) — used as evidence, and it earns its place

`actor_class_inventory {source, converted}` is now consumed. It decides a bin `actor_count`
is structurally blind to: **class replacement at unchanged total count**. Zero hits on the
real corpus (0 class swaps across 124 maps) — a live rule with no evidence, like
`package_version_changed`.

Proven on a mutated **real** record (`Untitled`, inventory forced to `{StaticMeshActor: 2}`,
actor_count left at 2→2):

```
label : actor_graph_changed   blocking: True
reason: actor CLASS LOSS: 1xHoudiniAssetActor present in source, gone after
        — silent damage the total actor count (2->2) does not reveal
```

It also bought a free integrity check: inventory totals match `actor_count` on 124/124 maps,
and a disagreement now → `unclassified` (rule 3), since the two are independently sourced.

## Labels deliberately NOT used

Refused in code as `_UNDECIDABLE` (machine-readable reasons, asserted unreachable by
`undecidable_label_leak()`, gated WF1035):

| Label | Why refused |
|---|---|
| `serialized_content_changed` | whole-file sha256 can't localize a delta to serialized data vs header/metadata bytes. Needs per-export payload digests. |
| `metadata_only_changed` | no metadata surface in the manifest at all. Nothing to compare ⇒ can never be affirmed. |
| `reference_graph_changed` | `critical_references` null 178/178 (needs a UWorld). Null is UNKNOWN. |
| `plugin_class_restored` | **Refusal SURVIVES the class inventory being plumbed in** — and is now positively confirmed rather than merely undecided. `Untitled` reads `{HoudiniAssetActor:1, StaticMeshActor:1}` on **both** sides: the one field that could have decided it shows there is nothing to see. The reclaim was a historical event against an intermediate state, not a property of this diff. Lane 1 concurs and has recorded that it stands. |

## `unconverted` — surfaced, not blocked

The 2 CoreTerrainMaterials are byte-identical while their record declares
`converted_engine=5.8` and their observed stamp says `5.7`. **Declared vs observed**: the
stamp wins, and that divergence is how an unconverted package is caught. `unchanged` in a
*conversion* audit means "was not converted" — reported as `unconverted_packages` and raised
as WARN_ONLY (`audit::no_unconverted_packages`, WF1037) rather than silently green. Not
blocking: Lane 1 corroborated these two were outside `CONTENT_ROOTS` at conversion time and
their 5.8 resave exists only as uncommitted collateral in another worktree. Blocking would
invent a failure condition outside this lane's mandate for a state the commander verified.

## Fail-closed proof

Mutations applied to **copies in scratchpad**. Real manifest sha256
`69f8b64a33fdcb3642a17059bbdefa5a3624f93b6a7334334fad5c07dd05727d` before and after
(identical); `git status procedural/manifests/` clean.

| Vector | Gate | Codes |
|---|---|---|
| force one package `unclassified` (null converted_hash) | **FAIL** exit=1 | WF1021, WF1015 |
| actor loss on a real map (234 → 230) | **FAIL** exit=1 | WF1014 |
| deletion (`conversion_status=source_only`) | **FAIL** exit=1 | WF1016, WF1021, WF1015 |
| stub manifest (wrong schema/keyspace, no records) | **FAIL** exit=1 | WF1015 |
| **class replacement at equal actor count** (real `Untitled`, 2→2) | **FAIL** exit=1 | WF1014 ×2 (`no_actor_loss`, `no_actor_class_loss`) |
| real manifest | **PASS** exit=0 (status=warn) | — |

Classifier negative controls (`--selftest`, 26 synthetic canonical-shaped cases) PASS and are
re-run inside the gate. They include: actor loss; actor loss masked by a simultaneous version
move; **class replacement at equal count**; **class loss masked by a version move**; class
gain-only (non-blocking); the real `Untitled` shape (identical inventories → NOT a class
event); inventory/actor_count contradiction; deletion; null hash; null CORE; null custom
versions as UNKNOWN; null inventory as UNKNOWN; same-engine rewrite; unknown stamp;
stamp-not-diffed-as-a-version; unconverted detection; cause-outranks-effect precedence.

## Failure codes used

All pre-existing, all in WF1011–1039. **None added.**

| Code | Where |
|---|---|
| `WF1014_CONVERSION_ACTOR_LOSS` | `audit::no_actor_loss`, `audit::no_actor_class_loss` |
| `WF1015_CONVERSION_MANIFEST_INCOMPLETE` | `audit::real_manifest`, `audit::common_keyspace`, `audit::version_evidence_complete`, `audit::every_package_labelled` |
| `WF1016_CONVERSION_UNEXPECTED_CHURN` | `audit::unaccounted_deletions_zero` |
| `WF1021_REGRESSION_UNCLASSIFIED_DIFF` | `audit::unclassified_packages_zero` |
| `WF1034_TRANSITION_REPORT_INTEGRITY_FAILED` | `audit::version_claims_are_earned`, `audit::stamp_not_diffed_as_version` |
| `WF1035_TRANSITION_NEGATIVE_ACCEPTED` | `audit::no_undecidable_label_leak`, `audit::classifier_negative_controls` |
| `WF1037_TRANSITION_HYGIENE_FAILED` | `audit::no_unconverted_packages` (WARN_ONLY) |

## Still undecidable without an editor

1. **Reference graph integrity** — `critical_references` null 178/178. "Zero broken references"
   is UNKNOWN here, not proven. The largest remaining hole.
2. **Component graph** — `component_count` null 178/178. Actor count and class inventory both
   hold at the actor level; a gutted actor still counts as 1 of its class.
3. **Content vs metadata localization** — needs per-export payload digests.
4. **Non-map assets have no structural observable** — for the 54 assets only CORE + CUSTOM +
   stamp are comparable, so `engine_resave_only` rests on the thinnest evidence there.
   Recorded per-record in `unknown`.

## Commands

```bash
cd "D:/Unreal Projects/WorldForge-v251"
PYTHONUTF8=1 python tools/pipeline/audit_conversion_diff.py --selftest   # negative controls
PYTHONUTF8=1 python tools/pipeline/audit_conversion_diff.py              # real manifest
PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_conversion_audit.py --strict
```

Runtime-free: `observed_runtime_engine=None`, `runtime_execution_required=False`,
`runtime_executed=False`. Unreal was never run.
