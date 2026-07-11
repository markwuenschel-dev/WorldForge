# WorldForge v2.3 StreamingForge / WorldScaleForge — Status

Branch: `worldforge/v2.3-streamingforge` (off `main` @ v2.2 merge `6f95773`)
Failure-code band: **WF851–WF930** `STREAMING_*`

## Baseline (verified before build)

* v2.2 shield GREEN 22/22 · v2.1 shield GREEN 20/20 · v2.0 shield GREEN

## Wave status

| Wave | Scope | State |
|------|-------|-------|
| 1 | Contracts + fail-closed shield | ✅ **DONE** |
| 2 | Region/tile/anchor/route/binding authoring | ✅ **DONE** — 2 regions / 6 tiles / 26 anchors / 4 routes / 48 bindings |
| 3 | Streaming runtime + tile lifecycle | ✅ **DONE** — 24 runs, 48 lifecycle |
| 4 | Cross-tile save/load + budgets | ✅ **DONE** — 24 save states + 24 budgets |
| 5 | OperatorForge region/tile views | ✅ **DONE** — 2 region + 6 tile views |
| R | Hostile closure + v2.3 shield green | ✅ **DONE** — shield GREEN 22/22 |

## Final result — v2.3 shield GREEN 22/22 (25/25 with regressions)

```
python tools/pipeline/v2_3_shield.py --strict --streaming --worldscale               # GREEN 22/22
python tools/pipeline/v2_3_shield.py --strict --streaming --worldscale --regressions  # GREEN 25/25
```

Runtime matrix: 24/24. Each scenario crosses ≥1 tile boundary with ≥1 stream
transition, completes its cross-tile route + mission, preserves tile state across
unload/reload, round-trips cross-tile save/load (tile+actor+mission+quest+faction
hashes), and stays inside budget. Runtime mode = `simulated_streaming_lifecycle`
(honest). Regressions: v2.2 22/22, v2.1 20/20, v2.0 green. v1.9/1.8/1.7/1.6z NOT
rerun (v2.3 changed none of their semantics — handoff §14).

## Wave 1 — delivered

* Failure band **WF851–WF894** registered (`failure_codes.py`, auto-backfilled).
* **`streaming_contracts.py`** — 13 strict schema-only contracts + navmesh/UE-mode
  truth guards + valid/known-bad factories + CONTRACTS/GROUPS/OWNING registries.
* **`validate_streaming_contracts.py`** — dogfood gate (GREEN, runtime-free).
* **`streaming_negatives.py`** — 41 known-bad fixtures, each rejected for its owning
  WF85x–88x code + reverse-dogfood + vacuous guard (GREEN).
* **`v2_3_shield.py`** — fail-closed. Spine-only GREEN 4/4; full
  (`--streaming --worldscale`) honestly RED.
* Makefile v2.3 section (contract/negative/shield targets); contract + status docs.

## Honest caveats

* Streamed generated-region substrate, not a full open world.
* Runtime matrix intentionally 24 scenarios, not 120; region size bounded (3 tiles).
* World Partition perfection / native UE navmesh streaming NOT claimed.
* Alpha runtime mode labeled honestly (simulated / process-isolated), never
  full_ue_streaming.
* NPCs stay v1.7/v1.8 sentry/pressure; combat v1.8; rewards v1.9; quest/faction v2.2.
* OperatorForge views are local/static; no player-facing map UI; no new asset
  acquisition / Houdini cook / multiplayer streaming.
