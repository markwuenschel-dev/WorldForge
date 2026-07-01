# WorldForge v1.0 — Status: COMPLETE

`desert_mvp_world` is built, strictly validated, scenario-proven, packaged, and
proven through a full destroy → rebuild → re-validate lifecycle. All results below
were produced by the pipeline (not asserted by hand).

## Verified gate results

| Gate | Command | Result |
|---|---|---|
| Health | `worldforge-doctor` | PASS (16 OK, 1 soft WARN dep_PIL, 1 GATED D7) |
| Spec pre-flight | `validate-world-pack-spec STRICT=1` | PASS — 25 maps, coverage minimums met, variant templates complete |
| Generate | `create-world-pack JOBS=6` | 25/25 built, 0 failed |
| Strict deep validate | `validate-world-pack DEEP=1 STRICT=1` | **25/25 PASS** (34 checks/map: PlayerStart, nav, POI actor/type/bounds/anchors, masks) |
| Runtime scenario | `run-world-state-scenario SCENARIO=industrial_takeover STRICT=1` | **13/13 compatible maps PASS** (state 0→0.75, save/load round-trip, POI evidence) |
| Inspection | `inspect-world-pack` / `validate-inspection STRICT=1` | PASS — 25/25 records complete, 25 playable |
| Package | `package-check` | PASS — 511 checks, all 12 budget categories within caps (1.9 MB, 0 forbidden refs) |
| Repair | `repair-world-pack` | PASS — 0 to repair (clean) |
| Destroy | `destroy-world-pack CONFIRM=1` | PASS — 100 generated-owned files removed, 0 retained-unsafe |
| Rebuild from data | `create-world-pack JOBS=6` | 25/25 built, 0 failed |
| Re-validate (post-rebuild) | `validate-world-pack DEEP=1 STRICT=1` | **25/25 PASS** |
| Regression: poi_lite_seed | `validate-world-pack DEEP=1 STRICT=1` | 6/6 PASS |
| Regression: production_seed | `validate-world-pack DEEP=1 STRICT=1` | 30/30 PASS |

## Coverage (`reports/coverage/desert_mvp_world_coverage.json`)

25 maps · 3 terrain forms · 8 material variants · 6 placement presets · 6 POI types ·
4 state presets · 3 runtime-scenario paths — every MVP minimum met or exceeded.

## What v1.0 added (smallest gap-fill only)

- Terrain forms: `cracked_ridge`, `sandy_basin` (materialized + validated).
- Placement preset: `reclaimed_scrub` (desert).
- Scenario: `industrial_takeover` (pack-level, reuses v0.8 mechanics).
- Tooling: `validate-world-pack-spec`, `run-world-state-scenario`, `inspect-world-pack`,
  `validate-inspection`.
- Fixes: completed two incomplete variant templates (`desert_light_industrial`,
  `desert_ruined_industrial` — missing `preview_base_color`); hardened the spec
  validator to catch variant-template incompleteness at spec time.

## Definition of done — met

Builds from data · 25 maps · all load · PlayerStart/nav/POI valid · masks validate ·
placement respects masks · runtime scenario + save/load pass · budgets pass ·
registry/provenance pass · package-check passes · repair/destroy/rebuild work ·
idempotent rebuild · strict validation passes · docs reproduce the flow · previous
milestones green.

## Intentionally NOT done

Expansion toward 50 maps (25 is the MVP floor; the brief scopes v1.0 to minimum
coverage). See `docs/status/v1_0_known_limitations.md` for the honest edges.

## Notes on how this build was run

UE materialization (map build, per-slice validation, terrain heightmap) is normally a
D7 human/editor step; it was executed here under explicit user authorization, so the
otherwise-GATED checks cleared to PASS. `make` was not on the tool-environment PATH, so
targets were exercised via their `tools/pipeline/*.py` entrypoints (identical behavior).
