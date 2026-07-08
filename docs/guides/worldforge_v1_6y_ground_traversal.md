# WorldForge v1.6y — Ground Traversal (status)

**GroundTraversalForge + NavRuntimeForge + PlaytestForge Delta**
Branch: `worldforge/v1.6-runtime-playability` · Pack: `encounter_loop_world`

v1.6x proved runtime completion via continuous **flight**. v1.6y proves **grounded
traversal**: a gravity-on, capsule-collision pawn that walks on the generated
map's terrain to the objective — flight and teleport can never count as success.

## Headline

**120/120 genuine `grounded_completed_runtime`.** `make v1-6y-shield STRICT=1
REQUIRE_LIVE=1` → **GREEN 7/7, achieved P2 (120/120 grounded)**. The v1.6x flight
matrix remains green as a regression; the v1.6 shield (19/19) and desert
(30/33) regressions remain green.

## Wave 0 — the traversal-architecture decision (empirical, not guessed)

A C++ grounded pawn (`AWFGroundedRuntimePawn`: gravity ON, capsule
`QueryAndPhysics`, `MOVE_Walking`, auto-possess) was run headless and probed the
navmesh at BeginPlay. The data decided the architecture:

| Question | Result | Consequence |
|----------|--------|-------------|
| UE runtime navmesh available in `-game`? | **NO** — `WF_GNAV navmesh_present=1 path_exists=0` (nav system exists, zero path/tiles) | Strategy A dead headless. Classified `navmesh_result=path_missing`, **never** faked as `grounded_navmesh`. |
| Does the static-mesh terrain have collision? | **YES** — pawn spawns z=300, falls, **lands z≈90 and walks** (`WF_GROUND grounded=1 mode=Walking`) | Grounded traversal viable. |

**Decision: Strategy D (hybrid), success mode `grounded_manual_waypoint`** — a
single deterministic grounded waypoint (the objective) followed on the ground via
`CharacterMovement` floor-follow/step-up. This is exactly the spec's
navmesh-unusable contingency: *use the WorldForge grounded route substrate; do not
claim `grounded_navmesh`.*

## What is GREEN now

| Gate | Proof |
|------|-------|
| `contract:self-check` | `ground_completion_contract` — valid grounded passes; **flight/teleport success rejected** |
| `failure-codes` | WF516–WF563 `GROUND_*` band validates |
| `no-flight-detector:self-test` | injects a flight-as-grounded-success → **rejected (exit 1)** |
| `ground:completion` | 120/120 reports validate against the frozen contract |
| `ground:no-flight-success` | always-on detector: no report claims grounded success with flight/teleport |
| `ground:gate` | **120/120 grounded_completed_runtime, tier P2** |
| `regression:v1.6x-flight-matrix` | 120/120 flight completions still green |

Every grounded completion carries: spawn + possess, ≥1 on-ground sample, grounded
arrival, `ground.*` telemetry, interaction, state mutation, save, and reload
verification.

## No-fake-green enforcement

- `grounded_completed_runtime` requires `grounded_success=true`, `flight_used=false`,
  `teleport_used=false`, `actual_traversal_mode ∈ {grounded_navmesh,
  grounded_worldforge_route, grounded_manual_waypoint}`, telemetry, and
  `save_load_result=pass` — enforced by the contract and re-checked by the
  always-on detector.
- The detector's `--self-test` proves it rejects an injected flight success.

## Honest caveats / remaining v1.6y breadth

- **Mode is `grounded_manual_waypoint`** (straight-line grounded following), not the
  full multi-node `grounded_worldforge_route` with cover/hazard-avoidance zones.
  That, plus deep walkability **geometry** analysis (surface extraction; slope/step/
  capsule sampling from mesh), the full standalone schema spine (scenario / pawn-
  profile / walkability / navmesh-probe / route-graph / route-plan / telemetry
  schemas + taxonomy), the complete negative/fuzz(300)/torture/report-integrity
  suite, and the biome/mission regressions, are **not yet built** — the remaining
  v1.6y breadth (candidate for the parallel swarm now that the architecture is
  proven).
- **`grounded_navmesh` remains future fidelity**, blocked on headless UE navmesh,
  which Wave 0 proved unavailable.

## Make surface (built)

```
make ground-prepare PACK=encounter_loop_world            # place grounded pawn on 60 maps (1 boot)
make run-playtest-forge-delta PACK=... STRICT=1 SCENARIOS=120   # drive grounded matrix
make ground-gate STRICT=1                                # 120/120 grounded_completed_runtime
make validate-ground-completion PACK=... STRICT=1
make validate-no-flight-ground-success PACK=... STRICT=1
make ground-no-fake-green-selftest                       # proves the detector rejects flight success
make v1-6y-shield PACK=... STRICT=1 REQUIRE_LIVE=1        # GREEN 7/7 P2
```
