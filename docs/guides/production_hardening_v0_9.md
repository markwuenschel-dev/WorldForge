# Production Hardening v0.9 — Operator Runbook

> Make WorldForge **operable by a human** and **understandable after a failure**.

v0.9 is a *hardening* release. It adds no new content systems — it adds the
read-only health, audit, packaging, and lifecycle commands that let an operator
decide whether a generated world is safe to ship, and a shared status vocabulary
that makes every validator's output mean the same thing.

This runbook is the operator's entry point. The behavior it documents is governed
by two frozen contracts — quote them, do not contradict them:

- [`docs/contracts/v0_9_validation_contract.md`](../contracts/v0_9_validation_contract.md) — report shape, the five verdicts, strict semantics, UE-check wording.
- [`docs/contracts/v0_9_failure_taxonomy.md`](../contracts/v0_9_failure_taxonomy.md) — the `WFnnn` failure codes and how to clear each one.

---

## 1. What v0.9 hardens (and what it does NOT build)

**Hardens (new in v0.9):**

| Command | Purpose | Mutates? |
|---|---|---|
| `make worldforge-doctor` | Local factory health: Python, deps, repo layout, definition/pack/registry readability, report writability. | No (read-only) |
| `make audit-generated-content` | Repo-wide ownership / provenance / path audit across **every** generated surface. | No (read-only) |
| `make package-check PACK=…` | Per-world-pack ship-readiness gate: registry, provenance, forbidden-path, owned-asset, budget caps. | No (read-only) |
| `make repair-world-pack PACK=…` | Diagnose (and with `APPLY=1`, re-derive) a world pack's pure-Python artifacts + registry consistency. | Only with `APPLY=1` |
| `make destroy-world-pack PACK=…` | Lifecycle teardown of a world pack's registry-owned generated assets. | Only with `CONFIRM=1` |

It also threads a real **strict mode** (`STRICT=1`) through the existing validators
(`validate-generated-asset`, `validate-runtime-state`, `validate-world-pack`,
`validate-terrain`, `validate-poi`, `validate-slice-pack`) and migrates their
soft checks onto the shared six-verdict contract.

**Does NOT build (out of scope for v0.9):**

- No new biome, terrain recipe, POI recipe, placement preset, or state preset.
- No MeshForge / procedural-mesh framework, no new HDA authoring.
- No new UE-side materialization. v0.9 never writes `Content/**` on its own (see §4).

If you want new content, that is a forge release (v0.6 TerrainForge, v0.7 POIForge,
v0.8 Runtime StateForge / Houdini intake). v0.9 only makes what already exists
**trustworthy and shippable**.

---

## 2. Strict mode and the five-verdict vocabulary

Every v0.9 validator writes one JSON report and prints a console summary using the
**same** status vocabulary. There are exactly **five per-check verdicts** and four
overall statuses — no synonyms (contract §2, §7):

| Verdict | Meaning | Blocks normally | Blocks under `STRICT=1` |
|---|---|---|---|
| `PASS` | Evaluated and passed | no | no |
| `WARN` | Soft failure a hardened build should catch | no | **yes** |
| `WARN_ONLY` | Intentionally non-blocking forever (legacy / explicitly allowed) | no | no |
| `FAIL` | Blocking failure | **yes** | **yes** |
| `SKIP_NOT_APPLICABLE` | Spec genuinely lacks this surface (or an optional in-editor cross-check whose report is absent) | no | no |

Overall `status` is one of `ok` / `warn` / `fail` / `error`; `passed == (status in {ok, warn})`,
and the process exit code is `0` iff `passed`. `make` / CI gate on that exit code.

### How `STRICT=1` works

Pass `STRICT=1` to any v0.9 `make` target. The Makefile `export STRICT`s it so it
reaches subprocesses (including UE-side validators that resolve it via
`strict_from_env()`):

```bash
make validate-world-pack PACK=desert_production_seed DEEP=1 STRICT=1
```

**Strict only ever ADDS blocking — it never removes it.** Non-strict behavior is
byte-for-byte the legacy behavior. The only thing strict changes:

```
FAIL                 always blocking
WARN                 becomes blocking      <- the entire point of strict mode
WARN_ONLY            stays non-blocking          (explicitly allowed / legacy compat)
SKIP_NOT_APPLICABLE  stays non-blocking          (surface absent / optional cross-check not run)
```

**WARN vs FAIL, in operator terms:** a `FAIL` is a real, mode-independent defect —
fix the artifact. A `WARN` is a production-readiness gate: harmless to *build* with,
but you should not *ship* with it. `STRICT=1` is how you assert "this is the final
gate; surface every WARN as blocking." Do **not** relax a check to make strict pass —
if strict surfaces a real problem, fix the artifact, not the validator
(contract §4).

---

## 3. Reading a report

The shared helper writes both a JSON report (under `procedural/reports/...`) and a
console summary. Console tags map to verdicts: `[OK   ]`→PASS, `[WARN ]`→WARN/WARN_ONLY,
`[FAIL ]`→FAIL, `[SKIP ]`→SKIP_NOT_APPLICABLE. A `(blocks)` suffix marks a check that
blocks in the current mode.

Each non-`PASS` check carries a stable `WFnnn` `code` from the
[failure taxonomy](../contracts/v0_9_failure_taxonomy.md); the free-text `detail`
carries the specifics, and the code is the stable bucket for triage.

---

## 4. UE checks

Some checks assert a UE-side artifact under `Content/**` (`.uasset` / `.umap`) that
the tooling materializes by driving the editor. These use `ue_check(...)`, a
**normal blocking check**: artifact present and valid → `PASS`, missing → `FAIL`.
There is no deferred verdict — the UE work is run, not postponed. Human-authored
master assets stay owner-owned and are protected from repair/destroy by the
ownership/provenance model.

The commands that materialize these artifacts (so their `ue_check` reports `PASS`):

| Editor command | Materializes | Failure code if missing |
|---|---|---|
| `make relocate-houdini-asset ASSET=…` | `asset_exists_in_ue_as_static_mesh` (generated-asset intake) | `WF080` / `WF081` |
| `make apply-state-scenario NAME=… SCENARIO=…` | native-authority availability for `ue_state_applied`; a native owner must materialize runtime state | `WF082` |
| `make import-terrain NAME=…` | terrain UE-import presence | `WF080` |

These run inside UE editor Python (`UE_PYTHON`), with the relevant slice map open
where required. Where a UE cross-check is **optional**, the validator asserts it with
`ue_check(...)` when its editor report is present and records `skip(...)` →
`SKIP_NOT_APPLICABLE` (non-blocking) otherwise, so the pure-Python data layer
validates cleanly — even under `STRICT=1` — without an editor.

---

## 5. The clean-state → full v0.9 validation sequence (final integration gate)

Run this in order from a clean checkout. The first two are environment/repo-wide;
the rest assert specific artifacts and packs under strict mode. Every command is
read-only.

```bash
make worldforge-doctor
make audit-generated-content
make validate-generated-asset ASSET=rock_generator_desert_01 STRICT=1
make validate-runtime-state NAME=Desert_Ash_IndustrialYard_01 SCENARIO=activate_industrial_forge STRICT=1
make validate-world-pack PACK=desert_poi_lite_seed DEEP=1 STRICT=1
make validate-world-pack PACK=desert_production_seed DEEP=1 STRICT=1
make package-check PACK=desert_poi_lite_seed
make package-check PACK=desert_production_seed STRICT=1
```

A green run means: the toolchain is healthy, nothing in the tree has slipped its
ownership/provenance/path guarantees, the canonical intake asset and runtime
scenario pass strict (optional UE cross-checks aside), both seed world packs validate
deeply under strict, and both packs are package/ship-ready (the production seed under
strict). The only non-blocking residue you should see is `SKIP_NOT_APPLICABLE` lines
for optional UE cross-checks whose editor reports are not yet present (§4) — those
become real `PASS`/`FAIL` `ue_check`s once the tooling runs the documented commands
in-editor.

> On Windows, prefix the underlying Python invocations with `PYTHONUTF8=1` (or set
> it in the environment) so emoji/Unicode in tool output does not crash cp1252.

### World-pack repair / destroy / rebuild lifecycle

The lifecycle commands are **safe by default**: `repair-world-pack` only diagnoses
and `destroy-world-pack` only dry-runs unless you explicitly opt in.

```bash
# REPAIR — diagnose only (mutates nothing)
make repair-world-pack PACK=desert_poi_lite_seed

# REPAIR — re-derive missing pure-Python artifacts (placement DataAssets)
make repair-world-pack PACK=desert_poi_lite_seed APPLY=1

# REPAIR — additionally run per-slice UE repair for UE-materialization map gaps (needs editor)
make repair-world-pack PACK=desert_poi_lite_seed APPLY=1 UE=1

# DESTROY — dry-run: lists what WOULD be removed, deletes nothing, registry untouched
make destroy-world-pack PACK=desert_poi_lite_seed

# DESTROY — actually delete registry-owned generated assets + update the registry
make destroy-world-pack PACK=desert_poi_lite_seed CONFIRM=1

# REBUILD — destroy then recreate the pack from its definition
make destroy-world-pack PACK=desert_poi_lite_seed CONFIRM=1
make create-world-pack  PACK=desert_poi_lite_seed JOBS=4
```

**Gating, explicitly:**

- `repair-world-pack` default = **diagnose** (report only). `APPLY=1` re-derives any
  *missing* placement DataAsset via `generate_placement_da.py` (pure Python, no UE).
  `APPLY=1 UE=1` additionally runs `run_ue_repair.py` per registered slice — that
  needs an editor and materializes the UE map so its `ue_check` reports `PASS`.
  `STRICT=1` escalates soft gaps (e.g. a stale registry `input_hash`).
- `destroy-world-pack` default = **dry-run**. `CONFIRM=1` performs deletion and
  writes the registry. `STRICT=1` only affects reporting.

---

## 6. Interpreting audit / package-check failures

Both commands print a per-surface (audit) / per-category (package-check) roll-up
plus a `COUNTS:` line, and write a JSON report. To triage, follow the failure
taxonomy's flow ([`v0_9_failure_taxonomy.md` §Triage flow](../contracts/v0_9_failure_taxonomy.md)):

1. **`status: error`** → inputs missing/unparseable (`WF000`–`WF003`). Nothing else
   ran; fix the descriptor/spec/pack first.
2. **Any `FAIL`** → blocking and mode-independent. Resolve every `failures[]` entry.
   Use the `WFnnn` code to find the remediation in the taxonomy (e.g. `WF040`
   forbidden path → relocate into the owned tree; `WF060` budget exceeded → reduce
   counts/dimensions or justify a budget change; `WF090` forbidden dependency →
   relocate the dependency).
3. **UE `FAIL` (`WF080`–`WF082`)** → the UE artifact was absent when its `ue_check`
   ran. Have the tooling drive the editor to materialize it (§4), then re-validate
   with `STRICT=1`. (An optional UE cross-check whose report is not yet present is
   `SKIP_NOT_APPLICABLE`, not a failure.)
4. **`WARN` under non-strict** → not blocking today, but `STRICT=1` will fail on it.
   Resolve before declaring production-ready, or consciously downgrade to
   `WARN_ONLY` with a recorded justification (contract §4 migration rule).

`audit-generated-content` answers "has *anything* across the whole tree slipped its
ownership/provenance/path guarantees, including registry/disk orphans?"
`package-check` answers the narrower ship-time question "is *this* world pack safe
to cook/package?" and additionally resolves a per-pack budget profile to enforce
performance caps the audit does not.

---

## 7. How to repair / destroy safely

The lifecycle tools are deliberately conservative — they only ever touch the
**generated, registry-owned, destroyable** set:

- **`CONFIRM=1` is required to delete anything.** Without it, `destroy-world-pack`
  is a dry-run.
- Only slices **currently in the registry** are destroyed (registration is what
  marks a slice factory-owned). Slices named in the pack but absent from the
  registry are reported and never touched — use `make clean-orphans` for stray
  artifacts.
- The destroyable target set per slice is exactly: `owned_assets`, the generated
  slice spec, the placement DataAsset, and the per-slice report dir. Every target is
  additionally run through the shared `clean_orphans` ownership gate; anything that
  is not positively generated-owned is **RETAINED** and reported, never deleted.
- **Never touched:** `referenced_assets` (shared materials, PCG graphs, shared
  DataAssets), human-owned templates, HDAs, and asset catalogs. The audit enforces
  this in the other direction — a human-owned template flagged `generated_owned` or
  `destroyable` is a hard `FAIL` (`WF050` / `WF052`).

---

## 8. Known limitations (be honest)

- **Unregistered orphan `Content/WorldForge/Maps/*.umap`.** This checkout
  carries **3** unregistered, tracked orphan maps that `make list-orphans` flags:
  `Desert_Test_Ash_01.umap`, `Desert_Test_HeavyIndustrial_01.umap`,
  `Desert_Test_Sandy_01.umap`. They are not removed automatically because they are
  unregistered — outside any pack's owned set, so the lifecycle tools leave them
  alone. To remove them, the tooling drives the editor via
  `make clean-orphans CONFIRM=1`, or run from the repo root:

  ```bash
  git rm Content/WorldForge/Maps/Desert_Test_Ash_01.umap \
         Content/WorldForge/Maps/Desert_Test_HeavyIndustrial_01.umap \
         Content/WorldForge/Maps/Desert_Test_Sandy_01.umap
  # or, in-editor: make clean-orphans CONFIRM=1
  ```

- **UE checks need the editor.** UE artifacts (generated-asset StaticMesh presence,
  runtime `ue_state_applied`, terrain UE-import, world-pack owned-`.umap` /
  human-`/Game` dependency presence) are real `ue_check`s: present+valid → `PASS`,
  missing → `FAIL`. Where the cross-check is optional, it is `SKIP_NOT_APPLICABLE`
  (non-blocking) until its editor report is present, then a real `PASS`/`FAIL`. The
  tooling drives the editor to materialize the artifact (§4). The full data layer
  validates green *without* an editor; the UE surface lights up afterward.
- **Headless MIC texture-override bug (TICKET-001).** Headless `SceneCapture` does
  not apply Material Instance texture-parameter overrides, so headless renders of a
  master-material-driven terrain can come back grey. This is worked around elsewhere
  (vector `PreviewBaseColor` proof terrain) and is unrelated to v0.9 validation
  verdicts, but if you are visually verifying a slice headlessly and the terrain is
  flat grey, that is TICKET-001, not a hardening failure.

---

## 9. Real operator reports (what success looks like)

Captured on this checkout (Windows, `PYTHONUTF8=1`), lightly trimmed.

### `make worldforge-doctor`

```text
WORLDFORGE DOCTOR — local factory health (strict=off)
  [OK   ] python_version — Python 3.14.6 OK (>= 3.8)
  [OK   ] dep_numpy — numpy importable
  [OK   ] dep_yaml — yaml importable
  [WARN ] dep_PIL — recommended dep 'PIL' absent (terrain/pack-score need it) — run: pip install Pillow
  [OK   ] dir_procedural_definitions — .../procedural/definitions
  [OK   ] dir_procedural_generated — .../procedural/generated
  [OK   ] dir_procedural_reports — .../procedural/reports
  [OK   ] dir_tools_pipeline — .../tools/pipeline
  [OK   ] dir_tools_unreal — .../tools/unreal
  [OK   ] unreal_editor_path — UE editor found: .../UnrealEditor-Cmd.exe
  [OK   ] ue_headless_runner — headless UE runner present (5 runner script(s), tools/unreal present)
  [OK   ] python_utf8 — UTF-8 output forced (PYTHONUTF8=1 or utf-8 stdout)
  [OK   ] definitions_readable — parsed 3 sampled definition(s) of 22 found
  [OK   ] pack_definitions_readable — parsed 5 pack definition(s)
  [OK   ] registry_roots_readable — parsed 5 registry root(s), 45 total entries
  [OK   ] houdini_generated_asset_registry — generated-asset registry readable — 1 asset(s) tracked
  [OK   ] report_dir_writable — .../procedural/reports/worldforge_doctor
COUNTS: PASS=16, WARN_ONLY=1
[worldforge-doctor] PASS — worldforge_local_factory (0 failure(s), 1 warning(s), strict=off)
```

The `dep_PIL` line is `WARN_ONLY` (Pillow is needed only by terrain/pack-score), so
it does **not** block even under `STRICT=1`. `unreal_editor_path` is also non-blocking
in both modes — pure-Python build/validate works without an editor.

### `make audit-generated-content`

```text
WORLDFORGE AUDIT — generated content ownership/provenance/path (strict=off)
  [PASS] registries       PASS=10 WARN=0 FAIL=0 SKIP=5
  [PASS] generated_assets PASS=11 WARN=0 FAIL=0 SKIP=1
  [PASS] terrain          PASS=14 WARN=0 FAIL=0 SKIP=1
  [PASS] poi              PASS=36 WARN=0 FAIL=0 SKIP=6
  [PASS] slices           PASS=360 WARN=0 FAIL=0 SKIP=0
  [PASS] placement        PASS=216 WARN=0 FAIL=0 SKIP=0
  [PASS] scenarios        PASS=10 WARN=0 FAIL=0 SKIP=0
  [PASS] catalogs         PASS=2 WARN=0 FAIL=0 SKIP=0

AUDITED 87 item(s) across 8 surface(s)
COUNTS: PASS=659, SKIP_NOT_APPLICABLE=13
[audit-generated-content] PASS — generated_content (0 failure(s), 13 warning(s), strict=off)
```

Every surface rolls up `PASS`; the 13 `SKIP_NOT_APPLICABLE` are surfaces a given
item genuinely lacks (e.g. a registry root's `entry_count` line, or a non-template
item's `human_template_integrity` check). A clean audit here is the precondition for
running the per-pack `package-check`.

---

## 10. See also

- [`docs/guides/houdini_asset_intake.md`](houdini_asset_intake.md) — generated-asset intake; v0.9 strict + UE StaticMesh `ue_check`.
- [`docs/guides/runtime_stateforge_v0_8.md`](runtime_stateforge_v0_8.md) — runtime scenarios; v0.9 strict + `ue_state_applied` `ue_check`.
- [`docs/contracts/v0_9_validation_contract.md`](../contracts/v0_9_validation_contract.md) · [`docs/contracts/v0_9_failure_taxonomy.md`](../contracts/v0_9_failure_taxonomy.md).
</content>
</invoke>
