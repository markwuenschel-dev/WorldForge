# WorldForge v2.1 — OperatorForge — Status

**Branch:** `worldforge/v2.1-operatorforge`
**Milestone:** operator control plane for WorldForge's evidence stack.
**Shield:** `v2-1-shield --operator` **GREEN — 20/20**.

OperatorForge is **not player-facing UI**. It is the internal control plane that
turns the v1.6z–v2.0 report/evidence universe into something a human can inspect
and trust: a report index + evidence graph, a static pack/scenario/failure/asset/
route dashboard, and a safe, bounded, allowlisted command launcher with run diffs.
It **indexes existing evidence; it does not make stale evidence true.**

## What shipped (by wave)

### Wave 1 — Contracts + fail-closed shield (`a3ed4bc`)
- Failure-code band **WF711–WF740** `OPERATOR_*` (§8), backfill auto-registers
  SEVERITY + GATE_TAXONOMY (registry 533 → 563 codes).
- `tools/operator/operator_contracts.py` — **11 strict contracts** (§7.1–7.11)
  with `X_REQUIRED`/`validate_X`/`_example_X` + `CONTRACTS` registry +
  `KNOWN_BAD_OWNING_CODE`, mirroring `slice_contracts.py`. Command allowlist
  policy is single-sourced here.
- `validate_operator_contracts.py` (dogfood gate) + `operator_negatives.py`
  (34 hostile fixtures, each rejected for its owning code).
- `tools/pipeline/v2_1_shield.py` — fail-closed; unbuilt gates are honestly RED.

### Wave 2 — Report index + evidence graph (`2463349`)
- `index_reports.py` — indexes the **real** v2.0 slice evidence: 85 reports over
  4 source roots → `operator_report_index.json` (integrity=pass, 24/24 covered)
  and `evidence_graph.json` (**168 EvidenceTrace** records = 7 claims × 24
  scenarios), every claim resolved to a real file on disk.
- `validate_operator_index.py` — fail-closed gate enforcing schema **and**
  referential integrity (paths exist, codes resolve, sha real, coverage complete).
  Adversarially spot-checked: a trace pointed at a missing file turns it RED.

### Wave 3 — Static dashboard (`488051e`)
- `operator_view.py` (shared theme-aware inlined-CSS HTML helpers).
- `build_dashboard.py` — validated `pack_cards.json` + `scenario_cards.json` and
  `index.html` + pack page + **24 scenario detail pages**; facet statuses derived
  from the graph (a card shows `pass` only where the trace verdict is pass).
- `validate_operator_evidence.py` — card facets must equal graph verdicts (no
  over-claim); runtime-pass cards' paths must exist.
- `operator_smoke.py` — pages present/non-empty/marked, **zero broken links**,
  not stale vs index sha.
- `build_failure_index.py` — FailureCodeIndex explorer over WF671–740.
- `build_asset_ownership.py` — AssetOwnershipView over the **real** mesh
  (generated_owned) + Megascans (third_party_owned) catalogs; 4 classes kept
  distinct; third-party never `regenerate` (contract-enforced).
- `build_route_view.py` — RouteWalkabilityView per scenario from **real** v1.6z
  walkability; `grounded_worldforge_route` proved, navmesh an explicit honest
  headless limit (never claimed proved).

### Wave 4 — Command launcher + diff (this commit)
- `operator_command.py` — allowlisted, bounded launcher; `plan_request()` is the
  single §9 decision point (unallowlisted→WF726, destructive→WF729, full-matrix
  no reason→WF728, write-run no dry-run/reason→WF727). Dry-run plans without
  executing; read-only commands may run with captured stdout/stderr +
  OperatorCommandResult.
- `diff_operator_runs.py` — contract-valid OperatorDiffReport (default: honest
  genesis→current transition; `--left/--right` for real run snapshots).
- `operator_command_negatives.py` — attacks the real launcher decision logic.

### Wave R — Hostile suite (this commit)
- `operator_fuzz.py` (300 deterministic mutations, zero invalid accepted),
  `operator_torture.py` (11 fake-green modes + launcher refusals),
  `operator_report_integrity.py` (report-meta integrity, non-vacuous floor),
  `operator_hygiene.py` (no drift: manifest = cards = pages; artifacts under the
  operator tree; runnable gates carry an Acceptance line).

## Regressions
- **v2.0** contracts shield: GREEN 3/3 (from existing evidence; shared
  `failure_codes.py` change is additive, registry gate GREEN).
- v1.9/v1.8/v1.7/v1.6z: not re-run live this milestone (operator work is additive
  and does not touch their runtime); validate via their own `--require-live`
  shields when runtime semantics change.

## Honest caveats
- Operator/control-plane milestone, **not player-facing UI**.
- Dashboard is **local/static** (self-contained HTML, no server).
- "Repair" = safe diagnostic/rerun guidance, **not** automatic world repair.
- Command launching is **allowlisted and bounded**; full-matrix reruns stay gated
  by explicit reason; destructive commands are blocked.
- OperatorForge **indexes existing evidence; it does not make stale evidence true.**
- No new gameplay systems, no QuestForge/FactionState/Streaming/tactical-AI, and
  **no native navmesh claim** (headless navmesh remains an honest path_missing limit).

## Not run
- Full 120/24 scenario matrix (not needed — runtime/recorder/save-load semantics
  unchanged this milestone).
