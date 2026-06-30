# v0.9 Failure Taxonomy

**Status:** Frozen for v0.9 Production Hardening (Agent 0).
**Companion to:** [`v0_9_validation_contract.md`](v0_9_validation_contract.md) and
[`tools/pipeline/failure_codes.py`](../../tools/pipeline/failure_codes.py).

Every non-`PASS` check should carry a stable `FailureCode`. This table is the
human-facing meaning of each code: what tripped it, its default severity, and how
to clear it. The free-text `detail` on the check carries the specifics; the code
is the stable bucket.

**Severity legend**
- `fail` — blocking in both normal and strict mode. Fix the artifact.
- `warn` — soft; non-blocking normally, **blocking under `STRICT=1`** unless the
  validator explicitly allows it (`WARN_ONLY`). Treat as a production-readiness gate.
- `gated` — `GATED_HUMAN_EDITOR`; never blocking. Clears when a human/editor runs
  the documented UE command (D7 — agents cannot materialize `Content/**`).

---

## 000–009 · Descriptor / parsing

| Code | Severity | Meaning | How to clear |
|---|---|---|---|
| `WF000_DESCRIPTOR_MISSING` | fail | Expected `descriptor.json` not found | Regenerate the artifact (`make create-*`); confirm path |
| `WF001_DESCRIPTOR_UNPARSEABLE` | fail | Descriptor exists but is not valid JSON | Inspect/repair the descriptor; regenerate |
| `WF002_RECIPE_MISSING` | fail | Referenced recipe/definition YAML absent | Restore the recipe under `procedural/definitions/...` |
| `WF003_SPEC_INVALID` | fail | Spec fails schema/shape requirements | Fix the spec inputs; re-run the generator |

## 010–019 · Registry / ownership

| Code | Severity | Meaning | How to clear |
|---|---|---|---|
| `WF010_REGISTRY_MISSING_ENTRY` | fail | Artifact not present in its registry | Re-run the registering generator (`make register-*` / `create-*`) |
| `WF011_REGISTRY_INCONSISTENT` | fail | Registry entry disagrees with on-disk descriptor | Re-register; investigate manual edits |
| `WF012_OWNER_UNRESOLVABLE` | fail | Cannot determine which forge owns the artifact | Add/repair ownership metadata in the registry |

## 020–029 · Provenance

| Code | Severity | Meaning | How to clear |
|---|---|---|---|
| `WF020_PROVENANCE_MISSING` | fail | No provenance block on the descriptor | Regenerate so provenance is stamped |
| `WF021_PROVENANCE_INCOMPLETE` | fail | Provenance present but missing required fields | Regenerate with current `provenance.py` |

## 030–039 · Generated artifacts

| Code | Severity | Meaning | How to clear |
|---|---|---|---|
| `WF030_ARTIFACT_MISSING` | fail | A declared output file is absent | Re-run the generator; verify output paths |
| `WF031_ARTIFACT_DEGENERATE` | fail | Output is degenerate (flat heightmap, all-black/white mask) | Re-check recipe params; regenerate |
| `WF032_DIMENSIONS_INVALID` | fail | Artifact dimensions disagree with descriptor | Regenerate at the declared dimensions |
| `WF033_MAP_INVALID` | fail | Post-operation map is no longer valid | Repair or rebuild the slice |

## 040–049 · Path policy

| Code | Severity | Meaning | How to clear |
|---|---|---|---|
| `WF040_FORBIDDEN_PATH` | fail | Final path is a forbidden Houdini Temp/Bake path | Relocate to the WorldForge-owned tree; re-register |
| `WF041_PATH_NOT_OWNED` | fail | Final path is outside the allowed owned root | Move under `/Game/WorldForge/Generated/...`; re-register |
| `WF042_CATALOG_MEMBERSHIP_MISSING` | fail | PCG-eligible asset not listed in its catalog | Add to the asset catalog category; re-validate |
| `WF043_TEMP_PATH_AS_FINAL` | fail | A temp/bake path is used as a final registered path | Use temp/bake only as provenance; set owned final path |

## 050–059 · Ownership integrity

| Code | Severity | Meaning | How to clear |
|---|---|---|---|
| `WF050_HUMAN_TEMPLATE_MARKED_GENERATED` | fail | A human-owned template is flagged generated-owned | Correct ownership flags; never auto-destroy templates |
| `WF051_GENERATED_FLAG_MISSING` | fail | Generated asset lacks explicit `generated_owned: true` | Set the flag in the descriptor; re-register |
| `WF052_DESTROYABLE_HUMAN_OWNED` | fail | A human-owned asset is marked destroyable | Remove destroyable flag from protected assets |

## 060–069 · Budget

| Code | Severity | Meaning | How to clear |
|---|---|---|---|
| `WF060_BUDGET_EXCEEDED` | fail | A budget category exceeds its cap | Reduce counts/dimensions or justify a budget change |
| `WF061_BUDGET_PROFILE_MISSING` | warn | No budget profile resolved for the pack | Add a budget profile; strict mode will require one |

## 070–079 · Runtime state / scenarios

| Code | Severity | Meaning | How to clear |
|---|---|---|---|
| `WF070_SCENARIO_UNPARSEABLE` | fail | Scenario recipe cannot be parsed | Fix the scenario YAML |
| `WF071_TARGET_MAP_UNRESOLVED` | fail | Scenario target map does not resolve | Point the scenario at an existing map |
| `WF072_STATE_DELTA_UNBOUNDED` | fail | A state delta falls outside its allowed bound | Clamp/correct the delta in the scenario |
| `WF073_MPC_VALUE_MISMATCH` | fail | Aggregated MPC value ≠ expected | Reconcile scenario expectation vs. simulation |
| `WF074_POI_EVIDENCE_MISSING` | fail | Expected POI evidence not produced | Verify POI wiring; re-run the sim |
| `WF075_SAVE_LOAD_ROUNDTRIP_FAILED` | fail | Save/load state did not round-trip | Fix persist keys; re-run the round-trip |

## 080–089 · UE materialization (D7-gated)

| Code | Severity | Meaning | How to clear |
|---|---|---|---|
| `WF080_UE_MATERIALIZATION_PENDING` | gated | UE asset/map not yet materialized by editor | Human/editor runs the documented UE command, then re-validate |
| `WF081_UE_ASSET_NOT_STATIC_MESH` | gated | Materialized UE asset is not a StaticMesh | Re-run relocate; confirm the bake produced a StaticMesh |
| `WF082_UE_STATE_NOT_APPLIED` | gated | Scenario MPC state not yet applied in UE | Human/editor runs `make apply-state-scenario`, then re-validate |

## 090–099 · Packaging

| Code | Severity | Meaning | How to clear |
|---|---|---|---|
| `WF090_PACKAGE_FORBIDDEN_DEPENDENCY` | fail | Final dependency on a forbidden path (e.g. HoudiniEngine/Temp,Bake) | Relocate the dependency into the owned tree |
| `WF091_PACKAGE_UNRESOLVED_REFERENCE` | fail | A referenced asset cannot be resolved | Restore/re-import the missing asset |
| `WF092_PACKAGE_MISSING_OWNED_ASSET` | fail | A registry-owned asset is missing from the package set | Re-materialize or re-register the owned asset |

---

## Triage flow

1. **`status: error`** → inputs missing/unparseable. Fix `WF00x` first; nothing
   else ran.
2. **Any `fail`** → blocking. Resolve every `failures[]` entry. These are real and
   mode-independent.
3. **`gated` only** → the artifact-side work is done; what remains is a D7 human/
   editor UE step. Run the documented command; re-validate with `STRICT=1`.
4. **`warn` under non-strict** → not blocking today, but `STRICT=1` will fail on it.
   Resolve before declaring production-ready, or consciously downgrade to
   `WARN_ONLY` with a recorded justification.
