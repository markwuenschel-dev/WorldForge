# WorldForge v1.0x — Shared Build Contract (read before writing any validator)

This is a build-coordination artifact for the v1.0x hardening lanes, NOT user docs.
Every v1.0x validator MUST follow this contract so the full-shield gate can trust
and aggregate it. Deviations break integration.

## Toolchain
- `make` is NOT installed here. Verify by running the Python entrypoint directly:
  `PYTHONUTF8=1 python tools/pipeline/<validator>.py --pack desert_mvp_world --strict`
- Always run Python with `PYTHONUTF8=1` (Windows cp1252 crashes on non-ascii).
- Python 3.14. Stdlib + PyYAML only. No new third-party deps.

## Mandatory imports (every validator starts like this)
```python
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta, hash_file, hash_obj, flag_from_env
from world_pack_maps import enumerate_maps, report_dir_for
```

## Map enumeration — the ONLY way to iterate a pack
```python
world_pack_id, maps = enumerate_maps(pack)   # pack = "desert_mvp_world"
for m in maps:
    if not m.spec_exists:
        # coverage shortfall — FAIL, do not silently skip
        ...
    spec = m.spec            # the loaded per-map generated JSON
    slice_id = m.slice_id
```
Never re-derive the map list yourself. "Every map" == every record from enumerate_maps.

## Report shape (parent-over-children)
- Build ONE `ValidationReport("world_pack_id", world_pack_id, strict=strict)` as the
  parent gate report. Add one check per map (or per sub-entity), tagged with a
  `code=FailureCode.<LANE>_FAILURE`.
- Attach metadata: `rep.set_meta(build_meta(command="validate-<x>", pack=world_pack_id,
  strict=strict, status=None, record_count=len(maps)))`. Counts auto-refresh on write.
- Write to the canonical dir:
```python
report_dir = report_dir_for(world_pack_id)
rep.finalize()
rep.write(report_dir, "validate_<x>_report.json")
rep.print_summary("validate-<x>")
sys.exit(rep.exit_code)
```
- record_count MUST equal the number of maps validated. A zero-record report is a FAIL.

## Strict mode = hostile mode
- `strict = args.strict or strict_from_env()`.
- In strict, WARN becomes blocking (ValidationReport handles this). Do NOT emit
  `warn_only`/`allow_in_strict` for genuine contract violations — those are FAIL.
- Missing/empty/zero-record/skipped inputs are FAIL in strict, never silent.
- No implicit fallback defaults: if a required field is absent, FAIL — do not
  substitute a default and pass.

## Profiles & bindings (Agents 2/3/6 substrate)
- Profile data files: `procedural/definitions/profiles/<kind>/<name>.yaml`
  kinds: environment, visual_style, sky, lighting, fog, atmosphere, post_process,
  time_of_day, weather, rendering, scalability, ray_tracing
- An `environment` profile references child profiles by name (sky:, lighting:, fog:,
  atmosphere:, rendering:, scalability:, ray_tracing:, visual_style:, post_process:,
  time_of_day:, weather:).
- Map→profile binding overlay (does NOT modify generated specs, preserves green
  baseline): `procedural/definitions/profiles/bindings/<world_pack_id>.yaml`
  ```yaml
  world_pack_id: desert_mvp_world
  default_environment_profile: photoreal_desert_day   # explicit, declared, validated
  bindings:
    Desert_AshFlats_IndustrialYard_Heavy_01: cinematic_desert_high_contrast
    # ... every slice_id gets an explicit binding (no silent default in strict)
  ```
- Shared loader lives at `tools/pipeline/profiles.py` (Agent 2 creates it; Agents
  3/6 import `resolve_environment, load_profile, PROFILE_KINDS` from it).

## Negative fixtures (mandatory per lane)
- Each validator ships a sibling `test_negative_<lane>.py` that:
  - constructs at least one KNOWN-BAD input (broken profile/binding/spec) in a
    temp dir or `procedural/fixtures/negative/<lane>/`,
  - invokes the validator's importable core function on it,
  - asserts it FAILS with the correct FailureCode,
  - prints `NEGATIVE OK: <n> fixtures failed as expected` and exits 0 when all
    known-bad inputs correctly failed (exit 1 if any bad input passed).
- Structure validators so the core logic is an importable function
  (e.g. `validate_pack(pack, strict) -> ValidationReport`) callable by the test.

## Makefile — DO NOT EDIT
Agent 0 owns the Makefile. In your final report, list the exact target block(s) to
add (target name, recipe line). Do not touch the Makefile yourself.

## Ownership / no-collision
Only create the files assigned to your lane. Never edit another lane's files,
`failure_codes.py`, `validation_report.py`, `report_meta.py`, `world_pack_maps.py`,
or the Makefile. Report integration notes back to Agent 0 (the caller).
