# Runbook — `desert_mvp_world` (WorldForge v1.0 MVP)

Reproduce a small playable adaptive desert world pack from data, from a clean tree
to strict validation. Every command is a Makefile target; on Windows each is a thin
wrapper over `PYTHONUTF8=1 python tools/pipeline/<script>.py ...` (run the Python
form directly if `make` is not installed — `PYTHONUTF8=1` is required so validator
output does not crash under cp1252).

## 0. Health check (read-only)

```bash
make worldforge-doctor
```

Expect `PASS`. `dep_PIL` is a soft WARN (install Pillow for terrain preview
niceties). The `content_materialization` check reports the state of the in-editor
UE materialization the tooling drives — see Known Limitations.

## 1. Static spec pre-flight (no UE, no generation)

```bash
make validate-world-pack-spec PACK=desert_mvp_world STRICT=1
```

Proves every referenced surface resolves (variants, terrain recipes, placement
presets, POI templates, state presets), variant templates are complete, names are
unique, and the MVP coverage minimums are met (25 maps · 3 terrain · 8 variants ·
6 placement · 6 POI · 4 state · 3 scenario paths). Coverage report:
`procedural/reports/coverage/desert_mvp_world_coverage.json`.

## 2. Generate the world pack (headless UE)

```bash
make create-world-pack PACK=desert_mvp_world JOBS=6
```

Phase 1 (spec + prepare) runs in parallel; Phase 2 builds each `.umap` in a serial
headless-editor boot. Idempotent: a rerun skips up-to-date slices (hash match).
Report: `procedural/reports/world_packs/desert_mvp_world/create_world_pack_report.json`.

## 3. Per-slice in-editor validation → aggregate strict gate

The aggregate validator consumes cached per-slice UE reports (it never launches the
editor itself). Produce those reports first, then aggregate:

```bash
# produce cached validate_slice reports (one headless boot per map)
for n in $(python -c "import yaml;[print(s['name']) for s in yaml.safe_load(open('procedural/slice_packs/desert_mvp_world.yaml'))['slices']]" | tr -d '\r'); do
  python tools/pipeline/run_slice_ue.py --script validate_slice.py \
    --spec "procedural/slices/desert/generated/$n.json" --deep
done

# aggregate: deep + strict
make validate-world-pack PACK=desert_mvp_world DEEP=1 STRICT=1
```

Expect `25/25 PASS` (each map 34/34 checks: PlayerStart, nav bounds, POI actor/
type/bounds/anchors, terrain + placement masks). Note the `tr -d '\r'` — the name
list must be stripped of Windows carriage returns or the spec paths won't resolve.

## 4. Runtime scenario across compatible maps

```bash
make run-world-state-scenario PACK=desert_mvp_world SCENARIO=industrial_takeover STRICT=1
```

Selects every industrial-path map (matrix `scenarios:` tag + POI fallback), mutates
`industrial_pressure` 0.0→0.75, aggregates state, computes MPC/POI evidence, and
performs a save/load round-trip per map. Expect `13/13 compatible maps PASS`. The
post-scenario map validity is a real `ue_check` (`PASS`/`FAIL`); the in-editor MPC
read-back is `SKIP_NOT_APPLICABLE` (non-blocking) until its editor report is present.
Report: `procedural/reports/world_packs/desert_mvp_world/run_world_state_scenario_report.json`.

## 5. Playable inspection metadata

```bash
make inspect-world-pack   PACK=desert_mvp_world      # generate per-map records
make validate-inspection  PACK=desert_mvp_world STRICT=1
```

Writes one record per map under `procedural/generated/inspection/<name>.json`
(terrain form · material variant · placement · primary POI · state · scenario
compatibility · PlayerStart/nav/POI signals · validation status) plus a pack index
at `procedural/reports/inspection/desert_mvp_world_inspection.json`. A human reads
the index to identify any map's composition and primary POI and whether it passed.

## 6. Package + lifecycle

```bash
make package-check      PACK=desert_mvp_world                 # budgets + ownership (read-only)
make repair-world-pack  PACK=desert_mvp_world                 # diagnose; APPLY=1 [UE=1] to fix
make destroy-world-pack PACK=desert_mvp_world                 # DRY RUN (shows WOULD-DELETE)
make destroy-world-pack PACK=desert_mvp_world CONFIRM=1       # actually remove generated-owned outputs
```

`destroy` only removes generated-owned files (maps, specs, placement DAs, per-slice
reports). It never touches human-owned templates, PCG graphs, material masters, HDA
sources, or vendor libraries (dry-run reports `retained (unsafe): 0`).

## 7. Full lifecycle gate (definition of done)

```bash
make worldforge-doctor
make create-world-pack        PACK=desert_mvp_world JOBS=6
make validate-world-pack      PACK=desert_mvp_world DEEP=1 STRICT=1   # (after step-3 UE validate pass)
make run-world-state-scenario PACK=desert_mvp_world SCENARIO=industrial_takeover STRICT=1
make package-check            PACK=desert_mvp_world
make repair-world-pack        PACK=desert_mvp_world
make destroy-world-pack       PACK=desert_mvp_world CONFIRM=1
make create-world-pack        PACK=desert_mvp_world JOBS=6
make validate-world-pack      PACK=desert_mvp_world DEEP=1 STRICT=1   # (after step-3 UE validate pass)
```

## 8. Regression shield (previous milestones stay green)

```bash
make validate-world-pack PACK=desert_poi_lite_seed   DEEP=1 STRICT=1
make validate-world-pack PACK=desert_production_seed DEEP=1 STRICT=1
```
