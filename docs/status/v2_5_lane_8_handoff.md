# v2.5 Lane 8 (HostileValidationForge) — Wave 0 Handoff

## File created
- `tools/pipeline/v2_5_shield.py` — the v2.5 UE 5.7->5.8 Transition shield skeleton.
  Mirrors `tools/pipeline/v2_4_shield.py` exactly: identical `REPO_ROOT` (`parents[2]`),
  `PY = sys.executable`, `run(label, relpath, *a)` helper (missing script → FAIL
  "(gate not yet implemented)"; else `subprocess.run([PY, script, *args], cwd=REPO_ROOT)`
  → PASS on rc==0), flag-gated lanes appended to a `results` list, and the final verdict
  block (`failed = [lbl for lbl,ok in results if not ok]`, GREEN/RED line, `sys.exit`).
  Uses `argparse` + `parse_known_args`. Threads a global `--strict` to gate scripts that
  accept it. Does NOT compute git_sha itself (that comes from each gate's report meta).

## Flag → gate-script mapping
| Flag | Gate label | Script invoked | Args threaded |
|------|-----------|----------------|---------------|
| (always) | `transition-contracts` | `tools/pipeline/validate_transition_contracts.py` | `--strict` (hard-wired) |
| `--topology` | `transition-topology` | `tools/pipeline/validate_transition_topology.py` | `--strict` if global set |
| `--conversion` | `conversion-manifest` | `tools/pipeline/validate_conversion_manifest.py` | `--strict` if global set |
| `--plugin` | `plugin-build` | `tools/pipeline/validate_plugin_build.py` | `--strict` if global set |
| `--capability` | `capability-manifest` | `tools/pipeline/validate_capability_manifest.py` | `--strict` if global set |
| `--regression` | `transition-regression` | `tools/pipeline/transition_regression.py` | `--strict` (hard-wired) |
| `--baseline` | `transition-baseline` | `tools/pipeline/validate_transition_baseline.py` | `--strict` (hard-wired) |
| `--bridge` | `gloam-bridge` | `tools/pipeline/validate_gloam_bridge.py` | `--strict` (hard-wired) |
| `--hostile` | `transition-negatives` | `tools/pipeline/transition_negatives.py` | `--strict` if global set |
| `--hostile` | `transition-fuzz` | `tools/pipeline/transition_fuzz.py` | `--strict` (hard-wired) |
| `--hostile` | `transition-report-integrity` | `tools/pipeline/transition_report_integrity.py` | `procedural/reports/ue5_8 --strict` (hard-wired) |
| `--hostile` | `transition-hygiene` | `tools/pipeline/transition_hygiene.py` | `--strict` if global set |
| `--regressions` | `regress:v2.4` | `tools/pipeline/v2_4_shield.py` | `--pack ... [--strict] --tactical` |
| `--regressions` | `regress:v2.3` | `tools/pipeline/v2_3_shield.py` | `--pack ... [--strict] --streaming --worldscale` |
| `--regressions` | `regress:v2.2` | `tools/pipeline/v2_2_shield.py` | `--pack ... [--strict] --quests --factions` |

The three `--regressions` targets EXIST and are Python-only / engine-agnostic; they may pass.

## Proof — Run 1 (no flags)
```
========================================================================
WorldForge v2.5 UE 5.7->5.8 Transition — pack=worldforge_vertical_slice
========================================================================
  [FAIL] transition-contracts  (gate not yet implemented: tools/pipeline/validate_transition_contracts.py)
========================================================================
v2.5 shield: RED — 0/1 gates passed
  FAILED (fail-closed — awaiting v2.5 transition waves): ['transition-contracts']
EXIT=1
```

## Proof — Run 2 (all lanes)
```
========================================================================
WorldForge v2.5 UE 5.7->5.8 Transition — pack=worldforge_vertical_slice
========================================================================
  [FAIL] transition-contracts  (gate not yet implemented: tools/pipeline/validate_transition_contracts.py)
  [FAIL] transition-topology  (gate not yet implemented: tools/pipeline/validate_transition_topology.py)
  [FAIL] conversion-manifest  (gate not yet implemented: tools/pipeline/validate_conversion_manifest.py)
  [FAIL] plugin-build  (gate not yet implemented: tools/pipeline/validate_plugin_build.py)
  [FAIL] capability-manifest  (gate not yet implemented: tools/pipeline/validate_capability_manifest.py)
  [FAIL] transition-regression  (gate not yet implemented: tools/pipeline/transition_regression.py)
  [FAIL] transition-baseline  (gate not yet implemented: tools/pipeline/validate_transition_baseline.py)
  [FAIL] gloam-bridge  (gate not yet implemented: tools/pipeline/validate_gloam_bridge.py)
  [FAIL] transition-negatives  (gate not yet implemented: tools/pipeline/transition_negatives.py)
  [FAIL] transition-fuzz  (gate not yet implemented: tools/pipeline/transition_fuzz.py)
  [FAIL] transition-report-integrity  (gate not yet implemented: tools/pipeline/transition_report_integrity.py)
  [FAIL] transition-hygiene  (gate not yet implemented: tools/pipeline/transition_hygiene.py)
========================================================================
v2.5 shield: RED — 0/12 gates passed
  FAILED (fail-closed — awaiting v2.5 transition waves): [ ...all 12 labels... ]
EXIT=1
```

## Contract spine status
The always-on `transition-contracts` gate is wired to `validate_transition_contracts.py --strict`.
At the moment of this Wave-0 build, Lane 4's `validate_transition_contracts.py` had **not yet
landed in this worktree** (Lanes run in parallel; my worktree is isolated), so it currently
reports fail-closed like every other gate. The wiring is verified correct: `REPO_ROOT` resolves
to the worktree root, present-file detection works, and `run()` is a byte-for-byte mirror of
`v2_4_shield.py`'s helper — so the gate flips to **PASS** the instant Lane 4's script is present
and returns rc==0. No further shield change is required for that flip.

All unbuilt gates fail-closed with "(gate not yet implemented)". Nothing is stubbed green.

## Gate scripts later waves must create to turn each lane green
Under `tools/pipeline/`:
1. `validate_transition_contracts.py` (Lane 4 — makes the always-on spine PASS)
2. `validate_transition_topology.py`   (--topology)
3. `validate_conversion_manifest.py`   (--conversion)
4. `validate_plugin_build.py`          (--plugin)
5. `validate_capability_manifest.py`   (--capability)
6. `transition_regression.py`          (--regression)
7. `validate_transition_baseline.py`   (--baseline)
8. `validate_gloam_bridge.py`          (--bridge)
9. `transition_negatives.py`           (--hostile)
10. `transition_fuzz.py`               (--hostile)
11. `transition_report_integrity.py`   (--hostile; reads `procedural/reports/ue5_8`)
12. `transition_hygiene.py`            (--hostile)

## Known limitations
- Wave 0 is FAIL-CLOSED by design: with no flags the shield is RED (0/1) and with all
  transition flags it is RED (0/12). This is the intended honest state, not a defect.
- `--regressions` (opt-in) is wired to the existing v2.4/v2.3/v2.2 shields but was not
  exercised in the two required proof runs; those shields exist and are engine-agnostic.
- The shield does not compute git_sha — that comes from each gate's report meta (same as
  v2_4_shield.py). MEMORY note: v2.4 shield must run under Git Bash (git not on PS child
  PATH); the same caveat will apply once git-sha-bearing gate reports exist for v2.5.
- Lane 8 built ONLY the shield skeleton; no gate scripts were implemented.
