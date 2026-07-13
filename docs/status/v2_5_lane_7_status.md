# v2.5 Lane 7 (Hostile Validation, Integrity, Shield) — Handoff

Status: COMPLETE (uncommitted; commander commits). Worktree: `D:\Unreal Projects\WorldForge-UE58`.
Date: 2026-07-13. (Subagent authored gates 1–4; it died on an auth error before the umbrella /
known-bads / torture — those three were completed by the commander with full context, and all
four subagent gates were independently re-verified GREEN before building on them.)

## Files
Subagent-authored (verified):
- `tools/pipeline/transition_negatives.py` — `--hostile` negatives gate.
- `tools/pipeline/transition_fuzz.py` — deterministic fuzz gate.
- `tools/pipeline/transition_report_integrity.py` — report-integrity gate (reads a reports dir).
- `tools/pipeline/transition_hygiene.py` — hygiene gate (abs-path / 5.7-tree / stray-output).
Commander-completed:
- `tools/pipeline/run_transition_known_bads.py` — on-disk fixture harness.
- `tools/pipeline/run_transition_torture.py` — deterministic torture harness.
- `tools/pipeline/validate_transition_integrity.py` — umbrella running all six.
- `procedural/known_bads/v2_5/*.json` — 16 machine-generated hostile fixtures.

## WF1011–1033 coverage
`transition_negatives.py` proves the full band IN-CODE: every contract's registered known-bad
is rejected for its owning code, AND every WF1011–1033 code has ≥1 owning known-bad rejected
for exactly that code (23 fixtures; the two cross-artifact codes WF1026 BRIDGE_STALE_PLUGIN and
WF1030 BRIDGE_OPERATION_ID_MISMATCH use supplemental negative validators). `run_transition_known_bads.py`
additionally materializes 16 of the mission's named hostile scenarios as ON-DISK fixtures
under `procedural/known_bads/v2_5/`, each self-describing (`_contract`, `_expected_code`), and
asserts each is rejected for its expected code.

## Commands (all PYTHONUTF8=1 STRICT=1, all PASS)
| Gate | Result |
|------|--------|
| `transition_negatives.py --strict` | PASS |
| `transition_fuzz.py --strict` | PASS |
| `transition_report_integrity.py procedural/reports/ue5_8 --strict` | PASS (sweeps the whole 5.8 tree incl. plugin-build + all lane reports) |
| `transition_hygiene.py --strict` | PASS |
| `run_transition_known_bads.py --strict` | PASS (16 on-disk fixtures) |
| `run_transition_torture.py --strict` | PASS (94 constrained-field mutations, 0 leaks) |
| `validate_transition_integrity.py --strict` | **PASS — 6/6 sub-gates** |

## Torture-harness honesty note (a bug I fixed, not hid)
The first torture harness mutated EVERY field and asserted rejection — it flagged 76 "leaks"
that were false positives: corrupting advisory metadata (`created_by`, `created_at`,
`report_type`) and identity's NULLABLE breadcrumbs (`engine_build_id`, `project_commit`,
`plugin_commit`) is legitimately ACCEPTED, because those are not contract-constrained. The
contracts were correct; the harness was wrong. Fix: torture now mutates only genuinely-
constrained REQUIRED fields (drop + a universal violating sentinel), skipping identity's
nullable trio. This keeps every assertion honest — no false catches, and it still proves
breadth (94 mutations across 7 contracts, every one rejected). This is the intended behavior,
not a weakening: I did not relax any contract to make the gate pass.

## Report-integrity: meta-convention enforcement
`transition_report_integrity.py` enforces the commander meta convention over the whole
`procedural/reports/ue5_8` tree: it does NOT flag a runtime-free report that host-resolves
engine_minor=7 (uproject fallback) as contamination; it DOES flag runtime_execution_required
reports whose observed_runtime_engine != declared minor, evidence entries tagged non-target,
and paths under `procedural/reports/ue5_7`. It passed clean against every committed + lane
report, including the Lane 1 plugin-build report (which correctly declares observed=8 after a
real 5.8 boot).

## Limitations / integration
- The umbrella is a standalone rollup; the SHIELD's `--hostile` flag still invokes the four
  individual gate scripts directly (commander wiring). The umbrella is for one-shot Lane-7
  self-check and Wave-9.
- Live-filesystem stale-binary and interrupted-conversion torture are modeled at the
  record/contract level here; a live variant can be added once the serial UE conversion runs.
- git status: all files untracked (`??`) except pre-existing noise; nothing committed by Lane 7.
