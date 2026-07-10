# Execution Contract: C7 — parse the real save_slot (make WF705 non-vacuous)

Status: **ready** (no blocking human decision — see §8 re-assessment)

## 1. Executive mission
The slice runtime producer hardcodes `save_slot = REWARD_SAVE_SLOT`, so the WF705
wrong-slot honesty invariant can never fire on a real produced report — it only
guards hand-authored/torture records. Parse the slot the engine actually emitted
(`WF_REWARD_SAVE slot=%s`) so a report that saved to the wrong slot is caught, and
prove it with a UE-free self-test.

## 2. Current baseline
- Branch `main` @ `59c7e8e` (C1–C10 except C7 merged), tree clean.
- Runs today: `ruff` (F,E9), `python tools/pipeline/*.py --strict`, `python tools/pipeline/v2_0_shield.py ... --require-live`. v2.0 shield GREEN 20/20.
- `run_slice_forge_alpha.build_report` (`tools/pipeline/run_slice_forge_alpha.py:145,150`): `ev = RB.evaluate(text)` is computed; `ev["save_slot"]` already parses `WF_REWARD_SAVE slot=(\S+)` (`run_reward_forge_alpha.py:80,314,362`); line 150 ignores it and hardcodes `SX.REWARD_SAVE_SLOT`.
- C++ marker is real: `Source/WorldForge/WFRuntime.cpp:842` emits `WF_REWARD_SAVE saved=%d slot=%s events=%d`.
- All 24 committed `slice_runtime_*.json` already carry `save_slot="WFReward_State"` — the value the fix would parse, so **no committed-evidence regeneration and no UE re-run are needed**.
- `build_report(scn, text)` is a **pure function** → unit-testable with synthetic stdout.
- No pytest suite; the repo's convention is in-tool self-tests/dogfoods (e.g. `run_reward_forge_alpha.py --selftest`).

## 3. Strategic meaning
An honesty invariant that can only fail on synthetic input is theater. Parsing the
real slot makes WF705 a live guard on produced evidence — closing the last v2.0
audit ledger candidate at the producer, where truth enters the system.

## 4. Scope
`save_slot` sourcing in `run_slice_forge_alpha.build_report`, plus a `--selftest`
that exercises `build_report` end-to-end against synthetic UE stdout (parsed slot
carried; a forbidden slot flows through to WF705 rejection; absent marker falls
back). One enforceable check, no engine dependency.

## 5. Non-goals
- Not broad cleanup of the producer or `run_reward_forge_alpha`.
- Not regenerating the 24 committed runtime reports (already correct) — no UE re-run.
- No schema change to `SliceRuntimeReport` (WF705 already lives in the schema).
- Not any other ledger candidate (C7 is the last one).

## 6. Blast-radius summary
Single producer function. `save_slot` sites: `run_slice_forge_alpha.py:150` (source, the fix), `:206` (written into the doc), `:324` (existing gate dogfood — unaffected). Consumers of the field: `validate_slice_runtime_report` WF705 check (`slice_contracts.py`, unchanged), `validate_slice_save_load` (`_facet`, unchanged). No committed artifact changes value.

## 7. Contracts / seams involved
- `SliceRuntimeReport.save_slot` + the WF705 `sr::completed_requires::v1_9_save_slot` invariant — `tools/pipeline/slice_contracts.py` (owner: v2.0 spine; **unchanged** by this mission).
- `run_reward_forge_alpha.evaluate` `save_slot` parse (`RE_SAVE`) — the marker source, reused as-is.

## 8. Human decisions required
**Re-assessed: none blocking.** The audit ledger tagged C7 `human_decision_risk=2`
on the assumption a UE re-run was required and that "is hardcoding acceptable?" was
open. Grounding shows neither holds: `build_report` is unit-testable and the
mission itself is the decision to fix. One minor implementation fork remains,
**decided** here (not a canonical human-decision category):

- **Fork (decided → A):** *A — report carries the parsed slot* (recommended): the
  report reflects whatever the engine emitted; a wrong slot then trips WF705
  downstream. vs *B — keep `REWARD_SAVE_SLOT` as the value but assert the marker
  agrees, failing production on mismatch.* A is chosen: it keeps the report a
  faithful record of the run and routes enforcement through the existing schema
  invariant rather than a second producer-side assertion. B recorded in §9.

## 9. Implementation strategy (decided shape: A)
`build_report` sources `save_slot` from `ev["save_slot"]` (the parsed marker),
falling back to `SX.REWARD_SAVE_SLOT` only when the marker is absent (no reward
fired — the report is non-completed anyway). WF705 in the schema then validates
the real value. Prove it with a `--selftest` that never launches UE.

*Rejected — B (assert-and-keep):* keeps a second source of truth (constant +
assertion) and makes production throw instead of producing an honest failed
report; more surface, less faithful evidence.

## 10. Task graph
T1 → T2 → T3 (strictly sequential).

## 11. Task-by-task plan

### T1 — parse `save_slot` from the marker
- **Purpose:** stop hardcoding; use the slot the engine emitted.
- **Files:** `tools/pipeline/run_slice_forge_alpha.py`.
- **Action:** replace line 150 with `slot = ev.get("save_slot"); save_slot = slot if isinstance(slot, str) and slot else SX.REWARD_SAVE_SLOT` (+ update the comment).
- **Check:** covered by the T2 self-test.
- **Verify:** `PYTHONUTF8=1 python -c "..."` builds a report from a synthetic text containing `WF_REWARD_SAVE saved=1 slot=WFReward_State events=3` and asserts `doc['save_slot']=='WFReward_State'` from the PARSE path (not the constant) — proven by a second text with `slot=WFCombat_State` yielding `doc['save_slot']=='WFCombat_State'`.
- **Risk/rollback:** if `ev['save_slot']` is unexpectedly None on a real reward, the fallback preserves today's behavior; revert = restore the constant.

### T2 (depends: T1) — add `--selftest` to `run_slice_forge_alpha`
- **Purpose:** the enforceable, UE-free check that WF705 is now live on produced reports.
- **Files:** `tools/pipeline/run_slice_forge_alpha.py` (new `do_selftest`, `--selftest` arg).
- **Action:** feed `build_report(scenarios[0], text)` three synthetic stdouts — (a) full success with `slot=WFReward_State` → `save_slot==WFReward_State` and `validate_slice_runtime_report(doc)` clean; (b) same but `slot=WFCombat_State` → `validate_slice_runtime_report(doc)` fails with `WF705`; (c) no `WF_REWARD_SAVE` → `save_slot==REWARD_SAVE_SLOT`. Exit non-zero on any mismatch. Leaves no evidence files (build a doc in memory; skip the telemetry sidecar write, or write to a temp path).
- **Check:** `do_selftest` itself.
- **Verify:** `PYTHONUTF8=1 python tools/pipeline/run_slice_forge_alpha.py --selftest` → exit 0 with a printed PASS line.
- **Risk/rollback:** self-test writes a telemetry sidecar as a side effect — guard `build_report` or use a temp dir so the selftest leaves zero real files (mirror `run_reward_forge_alpha --selftest`). Revert = drop the mode.

### T3 (depends: T2) — regression gate + no-churn confirmation
- **Purpose:** prove nothing regressed and no committed evidence changed.
- **Files:** none (verification only).
- **Action:** run the shield; confirm the 24 committed reports are byte-unchanged (value already `WFReward_State`).
- **Check:** the shield.
- **Verify:** `PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_0_shield.py --pack encounter_loop_world --strict --slices --require-live --package --torture` → GREEN 20/20; `git status --short procedural/reports/slice/runtime/` shows no modified `slice_runtime_*.json` (after reverting any meta-churn).
- **Risk/rollback:** shield red → inspect gate; revert = `git checkout -- .`.

## 12. Execution mode
**Sequential.** One producer function + a self-test; no schema, no committed
artifact, no cross-language change. Connected-impact-sweep is not warranted — the
output value is unchanged and no consumer contract moves.

## 13. Required commands
```
ruff check tools/pipeline/run_slice_forge_alpha.py --select F,E9 --no-cache
PYTHONUTF8=1 python tools/pipeline/run_slice_forge_alpha.py --selftest
PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_0_shield.py --pack encounter_loop_world --strict --slices --require-live --package --torture
git status --short procedural/reports/slice/runtime/
```

## 14. Verification gates
- After T1: the two-text parse assertion passes (WFReward_State and WFCombat_State each carried through).
- After T2: `--selftest` exit 0; the forbidden-slot case shows `WF705` and leaves zero evidence files.
- After T3: shield GREEN 20/20; no `slice_runtime_*.json` modified; ruff clean.

## 15. Failure codes
Executor reports against: `WF705 SLICE_SAVE_LOAD_WRONG_SLOT` (the invariant now
exercised). Plus contract codes: `FAIL-SCOPE-CREEP`, `FAIL-PHANTOM-TARGET`,
`FAIL-UNVERIFIED-TASK`, `FAIL-FAKE-GREEN` (e.g. a self-test that never feeds a
forbidden slot), `FAIL-BURIED-DECISION`.

## 16. Negative fixtures
- `--selftest` case (b): a produced-style report with `slot=WFCombat_State` MUST be
  rejected by `validate_slice_runtime_report` for `WF705` — the proof the invariant
  is no longer vacuous. This is the fixture that would fail before T1 (the producer
  could never emit a forbidden slot).

## 17. Review plan
- **Spec:** the report's `save_slot` equals the parsed marker slot; a forbidden
  slot trips WF705; absent marker falls back safely.
- **Quality:** single-line source change + a self-test that leaves no artifacts; no
  schema/interface change; the 24 committed reports unchanged; ruff clean.

## 18. Merge gate
Open the PR when: `--selftest` exit 0; shield GREEN 20/20; no committed
`slice_runtime_*.json` modified; ruff clean; tree clean. Then `/ship`.

## 19. Definition of done
Running §13 answers done with no judgment call: `--selftest` PASS (incl. the
forbidden-slot WF705 case), shield GREEN 20/20, zero committed runtime reports
modified, ruff clean.

## 20. Follow-ups
- None open in the v2.0 audit ledger after C7 — C1–C10 all resolved.
- 2 pre-existing Makefile-ref gaps remain tracked in `validate_makefile_refs.KNOWN_MISSING` (out of every v2.0 scope).
