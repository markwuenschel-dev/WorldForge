v2.1 OperatorForge adds a local operator surface for WorldForge's evidence stack. It indexes reports across the generated slice, traversal, NPC, combat, reward, save/load, asset, and package proof layers; generates operator-readable pack/scenario/failure/asset/route views; provides safe dry-run command launching and run diffs; and hardens the control plane with negative validators, fuzz, torture, report integrity, and command-safety gates.

## Waves

- **Wave 1 — Contracts + fail-closed shield** (`a3ed4bc`): WF711–740 `OPERATOR_*` band; 11 strict contracts (`operator_contracts.py`) mirroring `slice_contracts.py`; dogfood gate + 34 negatives; fail-closed `v2_1_shield.py`.
- **Wave 2 — Report index + evidence graph** (`2463349`): `index_reports.py` indexes the real v2.0 slice evidence (85 reports, 4 source roots) → `operator_report_index.json` (integrity=pass, 24/24) + `evidence_graph.json` (168 EvidenceTrace = 7 claims × 24 scenarios); `validate_operator_index.py` enforces schema **and** referential integrity.
- **Wave 3 — Static dashboard** (`488051e`): validated pack/scenario cards + `index.html` + pack + 24 scenario pages + failure/asset/route explorers; evidence-view gate; smoke + broken-link + staleness gate.
- **Wave 4 + R — Command launcher, diffs, hostile suite** (`3874738`): allowlisted bounded launcher (`plan_request` = single §9 decision point); genesis→current diff; command negatives; fuzz-300; 11-mode torture; report-integrity; hygiene.

## Validation

```
operator contracts GREEN
operator index GREEN
operator dashboard GREEN
operator smoke GREEN
operator evidence view GREEN
operator failure index GREEN
operator asset ownership GREEN
operator route view GREEN
operator command dry-run GREEN
operator command negatives GREEN
operator diff GREEN
operator negatives GREEN
operator fuzz-300 GREEN
operator torture GREEN
operator report integrity GREEN
operator hygiene GREEN
v2.1 shield GREEN (20/20)
v2.0 regression GREEN (contracts shield 3/3; failure_codes change is additive)
v1.9 regression validated from existing evidence (operator work is additive; not re-run live)
v1.8 regression validated from existing evidence (operator work is additive; not re-run live)
v1.7 regression validated from existing evidence (operator work is additive; not re-run live)
v1.6z regression validated from existing evidence (operator work is additive; not re-run live)
```

## Honest caveats

- v2.1 is an operator/control-plane milestone, **not** player-facing UI.
- The dashboard is local/static (self-contained HTML; no server).
- "Repair" means safe diagnostic/rerun guidance, **not** automatic destructive world repair.
- Command launching is allowlisted and bounded; full-matrix reruns remain gated by explicit invalidation or user authorization.
- OperatorForge indexes existing evidence; it does **not** make stale evidence true.
- No new gameplay systems are added. No QuestForge / FactionStateForge / StreamingForge / tactical-AI work is included.
- No native navmesh claim is introduced — headless UE navmesh remains an honest `path_missing` limit; proved traversal uses `grounded_worldforge_route`.
- No full 120/24 runtime matrix was rerun (runtime/recorder/save-load semantics unchanged this milestone).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
