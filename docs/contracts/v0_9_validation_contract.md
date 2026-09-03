# v0.9 Validation Contract

**Status:** Frozen for v0.9 Production Hardening (Agent 0 — Integration Captain).
**Audience:** every validator, audit, doctor, package-check, and runtime tool.
**Rule:** all v0.9 work conforms to this document. If a tool needs to deviate,
change this contract first — do not fork the semantics.

This contract formalizes the report/status pattern WorldForge validators *already*
use and adds the one thing v0.9 needs: a real strict mode. It does **not** invent
a parallel scheme. The shared helper lives at
[`tools/pipeline/validation_report.py`](../../tools/pipeline/validation_report.py);
failure codes at [`tools/pipeline/failure_codes.py`](../../tools/pipeline/failure_codes.py).

---

## 1. Canonical report shape

Every validator writes one JSON report. The shape is a **superset** of the legacy
shape — all legacy keys remain so existing consumers (e.g. `validate_slice_pack.py`
reading `rep["passed"]` and `checks[*].ok`) keep working unchanged.

```jsonc
{
  "<entity_key>": "<entity_id>",      // e.g. "terrain_name": "Terrain_AshFlats_01"
  "schema_version": "v0.9",
  "strict": false,                     // whether STRICT mode was active
  "checks": {
    "<check_name>": {
      "ok": true,                      // LEGACY — true iff verdict == PASS
      "detail": "human-readable why",  // LEGACY — specifics live here
      "warn_only": false,              // LEGACY — non-blocking-in-normal-mode hint
      "verdict": "PASS",               // NEW — see vocabulary below
      "code": null,                    // NEW — stable FailureCode when not PASS
      "blocking": false                // NEW — whether this check blocks in the report's mode
    }
  },
  "failures": [ "name: detail" ],      // LEGACY — BLOCKING failures only
  "warnings": [ "name: detail" ],      // LEGACY — non-blocking soft warnings (present only if any)
  "counts": { "PASS": 5, "WARN": 0, "WARN_ONLY": 0, "FAIL": 0,
              "SKIP_NOT_APPLICABLE": 1 },
  "passed": true,                      // LEGACY — true iff no blocking failure
  "status": "ok"                       // LEGACY — ok | warn | fail | error
}
```

Reports are written with `ValidationReport.write(report_dir, filename)` under
`procedural/reports/...` (unchanged paths). Exit code is `0` when `passed`, else `1`.

---

## 2. Per-check verdict vocabulary

| Verdict | Meaning | Blocks (normal) | Blocks (strict) |
|---|---|---|---|
| `PASS` | Evaluated and passed | no | no |
| `WARN` | Soft failure a hardened build should catch | no | **yes** (unless allowed) |
| `WARN_ONLY` | Intentionally non-blocking (legacy / explicitly allowed) | no | no |
| `FAIL` | Blocking failure | **yes** | **yes** |
| `SKIP_NOT_APPLICABLE` | Spec genuinely lacks this surface (or an optional in-editor cross-check whose report is absent) | no | no |

These five names are the **only** allowed per-check verdicts. Do not introduce
synonyms.

### How a verdict is chosen (API)

```python
from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode

rep = ValidationReport("terrain_name", name, strict=strict_from_env())

rep.check("descriptor_exists", path.is_file(), str(path),
          code=FailureCode.DESCRIPTOR_MISSING)          # -> PASS or FAIL
rep.check("terrain_imported_in_ue", imported, "...",
          warn_only=True)                                # -> PASS or WARN
rep.ue_check("asset_exists_in_ue_as_static_mesh", ue_ok, detail,
             code=FailureCode.UE_ARTIFACT_MISSING)       # -> PASS or FAIL
rep.warn_only("legacy_thing", ok, "...")                 # -> PASS or WARN_ONLY (never blocks)
rep.skip("water_table", "spec has no water surface")     # -> SKIP_NOT_APPLICABLE
# optional in-editor cross-check: ue_check when its editor report is present, else skip()
rep.finalize()
rep.write(report_dir, "validate_terrain_report.json")
rep.print_summary("validate-terrain")
sys.exit(rep.exit_code)
```

- `check(..., warn_only=False)` → `PASS` / `FAIL`. **Identical to the legacy closure.**
- `check(..., warn_only=True)` → `PASS` / `WARN`. Non-blocking normally, **blocking under strict**.
- `check(..., warn_only=True, allow_in_strict=True)` (or `warn_only(...)`) → `WARN_ONLY`. Never blocks.
- `ue_check(...)` → `PASS` / `FAIL`. A **normal blocking check** for a UE artifact the tooling materializes by driving the editor: present+valid → PASS, missing → FAIL. There is no deferred state. Optional in-editor cross-checks use `ue_check(...)` when their editor report is present and `skip(...)` otherwise.
- `skip(...)` → `SKIP_NOT_APPLICABLE`. Never blocks.
- `error(detail)` → forces `status="error"`, `passed=False` (inputs missing/unparseable).

---

## 3. Overall report status

| `status` | When | `passed` |
|---|---|---|
| `ok` | No blocking failures, no unresolved warnings | `true` |
| `warn` | No blocking failures, but `WARN`/`WARN_ONLY` present | `true` |
| `fail` | One or more blocking failures | `false` |
| `error` | Validation could not run (missing/unparseable inputs) | `false` |

`passed == (status in {"ok","warn"})`. CI / `make` gates key off the exit code,
which is `0` iff `passed`.

---

## 4. Strict mode (`STRICT=1`)

Strict mode is opt-in via the `STRICT` env var (the Makefile forwards `STRICT=1`).
`ValidationReport(strict=strict_from_env())` resolves it. Strict **only ever adds
blocking — never removes it**, so non-strict behavior is byte-for-byte the legacy
behavior.

```
FAIL                 always blocking
WARN                 becomes blocking            (this is the point of strict mode)
WARN_ONLY            stays non-blocking          (explicitly allowed / legacy compat)
SKIP_NOT_APPLICABLE  stays non-blocking          (surface absent / optional cross-check not run)
```

**Migration rule for validator owners (Agents 1/6/7):** when you adopt the shared
helper, every existing `warn_only=True` check must be *consciously classified*:

- Is it a **UE/Content artifact** the tooling materializes by driving the editor? → use `ue_check(...)` (a real `PASS`/`FAIL` check). If it is an *optional* in-editor cross-check, use `ue_check(...)` when its editor report is present and `skip(...)` otherwise.
- Is it a **genuine soft warning** a production build should not ship with? → keep
  `check(..., warn_only=True)` so strict catches it (`WARN`).
- Is it **intentionally non-blocking forever** (legacy compatibility)? → use
  `warn_only(...)` / `allow_in_strict=True` (`WARN_ONLY`) and say why in `detail`.

**Do not relax a check to make strict pass.** If strict surfaces a real problem,
fix the artifact, not the validator.

---

## 5. UE checks

Some checks assert a UE-side artifact under `Content/**` (`.uasset`/`.umap`) that
the tooling materializes by driving the editor. These use `ue_check(name, ok,
detail, code=...)`, a **normal blocking check**: the artifact present and valid →
`PASS`; missing → `FAIL`. There is no deferred verdict — the UE work is run, not
postponed. The tooling drives the editor to produce the artifact (e.g.
`make relocate-houdini-asset ...`, `make import-terrain ...`), then re-validation
reports `PASS`. Runtime state is
different: a matching native owner must materialize it through a state-write lease;
the editor-Python `make apply-state-scenario` helper reports unavailability rather
than mutating it. Human-authored master assets stay owner-owned and are protected
from repair/destroy by the ownership/provenance model.

Some UE cross-checks are **optional** (e.g. the runtime-state MPC bridge readback,
a terrain heightmap import, a generated-asset StaticMesh relocate). These are
verified with `ue_check(...)` **when their editor report is present**, and otherwise
recorded with `skip(...)` → `SKIP_NOT_APPLICABLE` — non-blocking and neutral, so the
authoring-side data layer validates cleanly (even under `STRICT=1`) without an
editor, and the UE cross-check lights up once its report appears.

---

## 6. Failure codes

Every non-`PASS` check *should* carry a stable `code` from
[`failure_codes.py`](../../tools/pipeline/failure_codes.py) (`FailureCode.*`). The
`detail` string carries specifics; the `code` is the stable bucket for triage,
audit grouping, and the runbook. Full table with remediation:
[`v0_9_failure_taxonomy.md`](v0_9_failure_taxonomy.md).

---

## 7. Shared-status names (use these literals everywhere)

```
verdicts : PASS  WARN  WARN_ONLY  FAIL  SKIP_NOT_APPLICABLE
status   : ok  warn  fail  error
```

Console summaries use `print_summary(tag)` and render `PASS`/`FAIL` headline plus
per-line `FAIL:` / `WARN:` / `WARN_ONLY:` prefixes.

---

## 8. Merge order (v0.9)

Contract first; independent health checks early; sidecar/runtime hardening before
audit/package; audits before destructive lifecycle; docs last.

```
1. Agent 0 — contract / status / failure taxonomy   (this document + shared helpers)
2. Agent 4 — worldforge-doctor
3. Agent 6 — Houdini generated-asset strict validation
4. Agent 7 — runtime strict validation
5. Agent 2 — audit-generated-content
6. Agent 5 — package-check / budgets
7. Agent 1 — strict world-pack validator migration
8. Agent 3 — repair / destroy / orphan lifecycle
9. Agent 8 — docs / runbook finalization
```

---

## 9. File ownership (no casual cross-edits)

| Agent | Owns |
|---|---|
| 0 | shared report/failure contract (this doc, taxonomy, `validation_report.py`, `failure_codes.py`) |
| 1 | validator migration to strict |
| 2 | audit / ownership (`audit-generated-content`) |
| 3 | repair / destroy / orphans (world-pack lifecycle) |
| 4 | `worldforge-doctor` |
| 5 | `package-check` / budgets |
| 6 | Houdini generated-asset hardening |
| 7 | runtime-state strict hardening |
| 8 | docs / runbook / Makefile help |

Shared `Makefile` targets: append a clearly-commented target block; Agent 0 / final
integrator resolves ordering and duplicates. Shared schema changes: one direct
canonical migration — no wrappers, no duplicate schema variants.
