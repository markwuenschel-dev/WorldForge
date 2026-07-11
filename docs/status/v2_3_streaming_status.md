# WorldForge v2.3 StreamingForge / WorldScaleForge — Status

Branch: `worldforge/v2.3-streamingforge` (off `main` @ v2.2 merge `6f95773`)
Failure-code band: **WF851–WF930** `STREAMING_*`

## Baseline (verified before build)

* v2.2 shield GREEN 22/22 · v2.1 shield GREEN 20/20 · v2.0 shield GREEN

## Wave status

| Wave | Scope | State |
|------|-------|-------|
| 1 | Contracts + fail-closed shield | ✅ **DONE** — spine GREEN, downstream honestly RED |
| 2 | Region/tile/anchor/route/binding authoring | ⏳ pending |
| 3 | Streaming runtime + tile lifecycle | ⏳ pending |
| 4 | Cross-tile save/load + budgets | ⏳ pending |
| 5 | OperatorForge region/tile views | ⏳ pending |
| R | Hostile closure + v2.3 shield green | ⏳ pending |

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
