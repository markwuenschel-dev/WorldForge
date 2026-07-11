# WorldForge v2.4 AdvancedAIForge / TacticalBehaviorForge — Status

Branch: `worldforge/v2.4-tacticalbehaviorforge` (off `main` @ v2.3 merge `6a18bd2`)
Failure-code band: **WF931–WF1010** `TACTICAL_*` (WF931–974 defined, WF975–1010 reserved)

## Baseline (to verify before downstream waves)

* v2.3 shield GREEN 22/22 · v2.2 GREEN 22/22 · v2.1 GREEN 20/20 · v2.0 GREEN 20/20

## Wave status — ALL DONE

| Wave | Scope | State |
|------|-------|-------|
| 1 | Tactical contracts + fail-closed shield | ✅ **DONE** — 15 contracts + 51 negatives GREEN |
| 2 | Profiles / roles / affordance authoring | ✅ **DONE** — 3 roles / 2 profiles / 24 affordance maps |
| 3 | Tactical NPC / group bindings | ✅ **DONE** — 48 NPC bindings / 24 group states |
| 4 | Tactical runtime / decision proof (24 scenarios) | ✅ **DONE** — 24 runtime reports + 24 decision bundles |
| 5 | Tactical save/load + budgets | ✅ **DONE** — 24 save states + 24 budget reports |
| 6 | OperatorForge tactical views | ✅ **DONE** — 24 scenario + 48 NPC views + dashboard |
| R | Hostile closure + v2.4 shield green + regressions | ✅ **DONE** — shield GREEN 23/23 |

## Final result — v2.4 shield GREEN 23/23

```
python tools/pipeline/v2_4_shield.py --strict --tactical --advanced-ai   # GREEN 23/23
```

Runtime matrix: 24/24 GENUINE tactical evidence in `deterministic_tactical_simulation`
mode (labeled honestly; NOT live UE AI). Each scenario runs a 2-NPC coordinated squad
through a scripted decision loop over the REAL v2.3 region/route/cover + v2.2 quest/faction
evidence — every decision has an input, considered options, a selected VALID option, an
execution result, and a state delta; the matrix covers every required action class
(hold_position, advance/retreat_to_anchor, flank_via_route, use_cover, pressure_objective).
Tactical state round-trips save/load (content-derived hashes); budgets classify honestly.

### Regressions (shield-level) — all GREEN

```
v2.3 shield --streaming --worldscale  → GREEN 22/22
v2.2 shield --quests --factions       → GREEN 22/22
v2.1 shield --operator                → GREEN 20/20
v2.0 shield --package                 → GREEN 4/4
```

v1.9/v1.8/v1.7/v1.6z live-UE regressions were **not** re-run: they require `--require-live`
engine runtime and are unaffected by v2.4, which is purely additive authoring/simulation
over the v2.3 substrate (no v1.x combat/NPC/reward code touched).

### Delivered (7 commits)

* `failure_codes.py` — WF931–974 `TACTICAL_*` band (44 codes)
* `tactical_contracts.py` (15 contracts) · `tactical_spec.py` · `tactical_runtime.py`
* validators/generators: profiles, affordances, bindings, runtime, save-load, budgets
* operator: `build_tactical_index.py`, `build_tactical_dashboard.py`, `tactical_operator_smoke.py`
* hostile: negatives (51) · negative-validators · fuzz-300 · torture (24) · report-integrity
  (+ real TacticalEvidenceIndex) · hygiene
* `v2_4_shield.py` · Makefile v2.4 section · contract + status docs
* generated artifacts: 3 roles / 2 profiles / 24 affordances / 48 bindings / 24 groups;
  evidence: 24 runtime / 24 decisions / 24 save / 24 budget / 24 scenario + 48 NPC views

## Honest caveats (carried into the PR)

* v2.4 is a **bounded tactical behavior substrate**, not final game AI.
* Runtime matrix is intentionally **24 scenarios**, not 120.
* Runtime mode will be labeled honestly (`deterministic_tactical_simulation` or
  `live_tactical_runtime`); a simulation is never labeled live AI.
* NPC behavior stays bounded by existing routes, anchors, cover affordances, and
  streaming scopes. No native UE navmesh claim, no BT editor / GOAP / EQS / RL / LLM NPC.
* Combat = v1.8 substrate; streaming = v2.3 substrate; quest/faction = v2.2 substrate.
