# v2.6 — Support Grid Contract (language-independent)

**Status**: Active. Authority for support-grid sampling semantics in **every** implementation.
**Governs**: `USceneSurveyStatics::SampleSurveySupport` (C++, shipping), the canonical Python
authority `tools/pipeline/support_grid_canonical.py`, and any future native collector.
**Decision reference**: `docs/architecture/forge_design_decisions.md` D18.

The support mathematics is **language-independent**. Every value below is a **contract value** — it
must be named and referenced from a single declaration, never re-typed as an implementation-local
constant in a second language.

A collector emits **raw observations**. It does not emit verdicts, and it is never a second
authority for report truth. Classification is *derived* downstream by the assembler and
independently *re-derived* by the validator.

**Operator resolutions of 2026-07-30 are recorded in §1.1 (grid extent), §5.2 (edge classification
is diagnostic in the C++), and §10 (the split of authority).**

**Later on 2026-07-30 the two remaining declaration gaps were closed:** `τ_n` is now **declared by
derivation** (§5.2.1–5.2.2, `τ_n = θ_max = 44°`), and **canonical sample identity** is now specified
(§1.4). Both are implemented in the canonical Python authority and gated by the conformance harness.

One `[OPEN]` remains: §5.4, a native/canonical disagreement about a `blocked` neighbour, which needs
an operator ruling. One `[HANDOFF]` remains: §5.2.6, the shipping C++ does **not** implement `τ_n`
and cannot without new per-cell normal retention — native-collector work under §10.

---

## 1 — Grid geometry

The sample region is a **named shape**, not an implied one:

```
sample_region_shape : axis_aligned_square      (the only implemented mode)
radius_cm           : the square's HALF-EXTENT
```

For a grid centred at `a = (a_x, a_y)` with half-extent `R` and spacing `s`:

```
k    = floor(R / s)
i, j in [-k, k]
p_ij = ( a_x + i*s ,  a_y + j*s )
N    = (2k + 1)^2
```

`R < s` therefore produces **exactly one centre sample**, and no sample is ever placed outside the
half-extent the collector was handed.

`N` is the nominal sample count and the basis for the cost model in D18
(`T_grid = N * (T_trace + T_interop + T_record)`).

### 1.1 — Grid extent [RESOLVED 2026-07-30]

The shipping C++ previously computed `FMath::Max(1, (int32)(RadiusCm / StepCm))` — that is
`max(1, floor(R/s))`. The operator has ruled this **mathematically wrong** for a square region of
half-extent `R`: when `R < s` it sampled a 3×3 grid reaching `±s`, i.e. outside the requested
half-extent, instead of a single centre cell.

| Condition | Contract `k` | Old C++ `k` | Cells |
|---|---|---|---|
| `R >= s`  | `floor(R/s)` | `floor(R/s)` | agree |
| `R < s`   | `0`          | `1`          | 1 vs 9 |

**Resolution: the C++ changed to `floor(R/s)`.** `SceneSurvey.cpp:103` now reads
`const int32 K = FMath::FloorToInt(RadiusCm / StepCm);`, with the square-region semantics stated in
the comment block at `SceneSurvey.cpp:92-102` and echoed in the log line at `SceneSurvey.cpp:225`
(`shape=axis_aligned_square k=%d`). `RadiusCm <= 0` and `StepCm <= 0` remain rejected at
`SceneSurvey.cpp:84`, so the quotient is positive and `FloorToInt` is a true floor.

This changes the plugin source, and therefore the plugin source hash, which **forces a re-vendor in
any caller project that has vendored the plugin.**

### 1.2 — Radial regions are a separate declared mode

If a radial region is ever wanted it is a **separate, separately named mode**:

```
sample_region_shape : axis_aligned_disk
predicate           : i^2 + j^2 <= (R/s)^2
```

The two modes must remain distinguishable by name at every layer. Silently switching between square
and disk semantics is forbidden: `support_grid_canonical.py` names both
(`SAMPLE_REGION_SHAPES`) but implements only the square one
(`IMPLEMENTED_SAMPLE_REGION_SHAPES`), and asking for the disk mode raises rather than quietly
running the square one.

### 1.3 — Precision of `k` across languages [KNOWN DIVERGENCE]

The C++ divides two 32-bit `float`s; the Python authority divides two `float64`s. Where the two
quotients floor differently, the collectors disagree on the **sample count itself**, not merely on a
cell class. Concrete witnesses exist and are easy to hit: `R = 29.999999999999996, s = 10` gives
`k = 2` in float64 and `k = 3` in float32. Any `R` that accumulated from repeated addition and lands
just under a multiple of `s` is a candidate. Recorded as fixture `float32_quotient`.

### 1.4 — Canonical sample identity [DECLARED 2026-07-30]

Every sample carries an identity. It is constructed **only** from canonical grid coordinates and
declared contract names — never from process order, iteration order, wall-clock, PRNG, memory
address, or any floating-point quantity.

```
sample_id = version | shape | "k=" k | "i=" ±i | "j=" ±j

wf.support_grid.v2_6.r2|axis_aligned_square|k=1|i=-1|j=+0
```

Constructed by `support_grid_canonical.sample_id(k, i, j, shape)`; minted per grid by
`GridResult.sample_ids()` / `.sample_id_for(i, j)`.

#### 1.4.1 — Components, and why each is present

| Component | Form | Why it is in the identity |
|---|---|---|
| `version` | `wf.support_grid.v2_6.r<N>` | Semantics change without coordinates changing. `r1` refused `τ_n`; `r2` declares it (§5.2), which flips what `edge` and `resolved_class` a given cell resolves to. Two samples minted under different revisions are **different observations** and must not compare equal. |
| `shape` | full declared name | §1.2 forbids square and disk semantics from being silently substituted. The identity carries the **full name**, never an abbreviation, so the distinction survives here too. Constrained to `SAMPLE_REGION_SHAPES`. |
| `k` | `k=<non-negative int>` | The §5.1 perimeter asymmetry means a cell's evidence quality depends on the extent: `(1,0)` is a 3-neighbour perimeter cell at `k=1` and a 4-neighbour interior cell at `k=2`. Without `k`, two non-interchangeable observations would share an identity. |
| `i`, `j` | `i=<signed int>` | The cell itself, in canonical index space (§1, §6). |

The namespace follows the house convention `wf.<domain>.<thing>.v<N>`. The `.r<N>` **revision**
suffix is specific to this contract: bump it on a **semantic** change to what a sample means, never
on a prose edit. It is gated by `identity::version_is_carried`.

#### 1.4.2 — Normalization rules

All of these are load-bearing; each has a golden.

1. **Integers only.** A float index is a `ContractViolation`, never rounded. Floats are exactly what
   fails to round-trip across the language boundary (§1.3), so no float may enter an identity.
2. **Sign always explicit** on `i` and `j` (`+0`, `-1`, `+2`). Without it, `0` and `-0` could both
   exist and name the same cell.
3. **No zero padding**, no thousands separator, no locale-dependent formatting. `k` is unsigned and
   unpadded; `i`/`j` are signed and unpadded. The parser **rejects** a padded form rather than
   accepting it as equivalent.
4. **Separator `|`.** It cannot occur in any component: the version is `[a-z0-9._]`, shape names are
   `[a-z_]`, indices are `[-+0-9]`.
5. **Range-checked at construction.** `|i| > k` or `|j| > k` raises — an identity must never name a
   cell the grid does not contain.
6. **Strict inverse.** `parse_sample_id` accepts only what `sample_id` emits and rejects a wrong
   revision, a padded index, an unsigned index, an out-of-range cell, or a malformed field. A
   lenient parser would let a corrupted identity through as a plausible one. **Round-tripping is the
   determinism proof** (`identity::round_trips`).

#### 1.4.3 — Scope: operation-local, deliberately

The identity is unique **within one survey operation** and is **not globally unique**. Two
operations at different anchors — or at the same anchor with a different spacing `s` — legitimately
mint identical `sample_id`s.

This is a decision, not an oversight. The anchor and the spacing are **floats**, and admitting a
float would make the identity disagree across exactly the float32/float64 boundary §1.3 already
documents. So:

> **A `sample_id` names a cell within a grid, not a place in the world.** It is qualified by the
> operation — `(operation_id, sample_id)` — and is never a substitute for it.

This matches the existing split between identity-of-the-*asking* (`operation_id`) and
identity-of-the-*question* (`request_hash`) used elsewhere in the v2.6 chain. Asserted by
`identity::anchor_and_spacing_do_not_leak_in` and `identity::unique_within_an_operation`.

#### 1.4.4 — Relationship to canonical ordering

**A `sample_id` is an identity, not an ordering key.** Canonical order is `canonical_sort_key`
(§6), and only that.

Sorting the strings lexically gives the **wrong** answer: `'+'` is `0x2B` and `'-'` is `0x2D`, so
`"i=+0"` precedes `"i=-1"` lexically while canonically `-1 < 0`. `sort_key_from_sample_id` exists
for when an identity is all you have. Both facts are asserted —
`identity::lexical_sort_is_NOT_canonical_order` deliberately pins the *inequality*, so that nobody
comes to rely on a coincidence.

`GridResult.sample_ids()` returns identities in canonical order, positionally aligned with
`GridResult.cells`. Identity is attached at the **grid** level, not on `CellResult`: a cell does not
know `k`, and copying `k` into every cell is a second place for it to drift.

#### 1.4.5 — The other `sample_id` in this tree [NAMED EXEMPTION]

`tools/pipeline/run_v2_6_fixture_smoke.py:424-432` also defines a `sample_id`, minting
`sample_0002_0001` from **shifted non-negative** indices (`row = i + k`, `col = j + k`), zero-padded
so that **lexical order equals canonical order** — the exact opposite property to §1.4.4.

That is a **fixture-local ordering token**, not an evidence identity. Its purpose is to let that
harness prove ordering by sorting strings, feeding its `id_sequence_sha256` at `:2018-2020`. It is
exempt from this section and **must not be emitted as evidence**.

Two identifier schemes with contradictory ordering semantics may coexist only if they can never be
confused, so that is gated rather than assumed:
`identity::fixture_token_is_rejected_by_the_canonical_parser` proves `parse_sample_id` **refuses**
the fixture form, and `identity::fixture_token_is_not_a_canonical_identity` proves the two token
spaces are disjoint.

(A third key-like construct exists natively — `GridKey` at `SceneSurvey.cpp:26-30`, which biases
indices by `+2000` for `TMap` lookup. It is function-local, never serialized, and destroyed on
return, so it is not an identity at all. The C++ emits **no per-sample identifier of any kind**.)

---

## 2 — Raw observation record

Each sample preserves the raw trace result and nothing derived. A cell carries **two** raw
observations — the ground trace and, when it was issued, the head-clearance trace:

```
e_ij = ( trace_start, trace_end, hit, impact_point, normal,
         actor_path, component_path, failure )
```

Rules:
- `hit` is **tri-state**. `True` = ran and hit. `False` = ran and cleanly missed. `None` = **the
  trace did not run**, and `failure` says why. A cell whose trace did not run records `failure`
  with `hit = None` — **never** `hit = False`. "Missed" and "never attempted" are different
  observations (mirrors the tri-state `collection_ok` rule at
  `tools/pipeline/scene_survey_evidence.py:398-408`, and its `not_requested`/`failed` constructors
  at `:444-453`).
- `impact_point` and `normal` are `None` on a clean miss, never a zero vector, and are absent
  entirely when the trace did not run.
- The head trace being **absent** means it was never issued. Absent must never read as "clear".
- No verdict field. No support class. Classification is not the collector's output.

### 2.1 — Trace parameters (verified against `SceneSurvey.cpp` at 2026-07-30)

| Parameter | Value | Source |
|---|---|---|
| Channel | `ECC_Visibility` | `SceneSurvey.cpp:119` |
| Complex trace | `true` | `SceneSurvey.cpp:105` |
| Ground trace start Z | `a_z + 1000` | `SceneSurvey.cpp:117` |
| Ground trace end Z | `a_z - 3000` | `SceneSurvey.cpp:117` |
| Head-clearance start Z | `p_impact.z + MaxStepH + 5` | `SceneSurvey.cpp:147` |
| Head-clearance end Z | `p_impact.z + 176` | `SceneSurvey.cpp:148` |

**Note the ground trace is anchored to the grid centre's Z, not to each cell.** Every column is
swept over the same absolute `[a_z - 3000, a_z + 1000]` window. Terrain outside that window is not
observable by this collector at this anchor — a real limit, and a `failure` cause, not a miss.

---

## 3 — Tolerances (contract values)

| Symbol | Name | Value | Source |
|---|---|---|---|
| `θ_max` | max standable slope | **44°** | `MaxSlope`, `SceneSurvey.cpp:90` |
| `h_step` | max step height | **45 cm** | `MaxStepH`, `SceneSurvey.cpp:90` |
| `τ_h` | edge height discontinuity | **90 cm** (`2 * h_step`) | `SceneSurvey.cpp:195` |
| `head_lo` | head clearance window low | `h_step + 5` = **50 cm** | `SceneSurvey.cpp:147` |
| `head_hi` | head clearance window high | **176 cm** | `SceneSurvey.cpp:148` |
| `τ_n` | edge normal discontinuity | **44°** (`= 1.0 × θ_max`) | derived — see §5.2.2; **not in the C++**, §5.2.6 |

`176 cm` and `45 cm` are character-capsule-shaped numbers with no named source in the C++. They are
contract values here by adoption, not by derivation; if the caller's character metrics differ, this
table is what changes.

`τ_h` and `τ_n` are the two **derived** rows: `τ_h = 2 × h_step` and `τ_n = 1.0 × θ_max`. The
multipliers differ because the domains are bounded differently — see §5.2.2, which also records why
the symmetric-looking `2 × θ_max` is provably vacuous. Neither derived value may be re-typed as a
literal in any language.

### 3.1 — Where the single declaration lives

The Python declaration is `SupportTolerances` / `CONTRACT_TOLERANCES` in
`tools/pipeline/support_grid_canonical.py`. `τ_h`, `head_lo` and `τ_n` are all **derived** there,
never re-typed — so the `2 *`, the `+ 5` and the `1.0 *` each exist once. `τ_n` comes from
`derive_tau_n_deg(θ_max)`, and the conformance harness gates the **derivation** rather than the
number (`edge::tau_n_is_derived_not_typed`), because an implementation that receives `44.0` and
stores it as its own literal has re-opened exactly the D18 drift this rule exists to close.

The C++ literals cannot be imported from Python, so single-sourcing across the language boundary is
enforced by a **gate instead of an import**: `tools/pipeline/support_grid_conformance.py` parses
`SceneSurvey.cpp` and asserts every value in the table above still matches
(`tolerance::cpp_agrees::*`), and separately asserts agreement with the third existing declaration,
`scene_survey_evidence.py:281-300` (`GROUND_MAX_SLOPE_DEG`, `GROUND_DZ_TOLERANCE_CM`,
`GROUND_MAX_SLOPE_COS`).

A gate was chosen over an import deliberately. An import would make the canonical module silently
absorb a change made to `scene_survey_evidence` for another lane's reasons — `GROUND_DZ_TOLERANCE_CM`
is *named* for a Δz tolerance even though its provenance is `MaxStepH`. A gate turns any such change
RED and visible. The counter-argument is that three declarations still exist and the gate is the only
thing holding them together; that is accepted, and the gate is blocking.

---

## 4 — Support predicate

```
S_ij  =  hit_ij
      ∧  finite(p_impact_ij)
      ∧  finite(n_hat_ij)
      ∧  n_hat_ij · z_hat  >=  cos(θ_max)
      ∧  head_clear_ij
```

`S_ij` is **tri-state**: `True`, `False`, or `None` (unknown). Fail-closed — `None` is never
support.

`head_clear_ij` is true when the upward trace over `[p_impact.z + head_lo, p_impact.z + head_hi]`
ran and did **not** hit. The shipping C++ requires it (`SceneSurvey.cpp:147-152`); a head-blocked
cell is classified `blocked`, not `valid`.

The C++ tests slope as `degrees(acos(clamp(n.Z, -1, 1))) > 44` (`SceneSurvey.cpp:138-141`). For a
unit normal `n.Z ≡ n̂·ẑ`, so that is equivalent to `n̂·ẑ >= cos θ_max` up to floating-point
representation. **An implementation must compare against `cos(θ_max)` directly** rather than
round-tripping through `acos`/`degrees`, which is where two languages will disagree in the last
bits. The same applies to the `τ_n` comparison (§5.2): compare the dot product against `cos(τ_n)`,
never `arccos` the dot product.

Note that the C++ compares the **raw** `ImpactNormal.Z` while the contract writes `n̂`, a unit
normal. These agree exactly for a unit normal and invert for a shortened one — recorded as fixture
`non_unit_normal`.

### 4.1 — Class vocabulary

`valid_support` · `unsupported` · `edge` · `blocked` · `trace_error` · `unknown`
(`scene_survey_contracts.py:62-64`). `unknown` is the fail-closed default before classification.

**`trace_error` is now reachable in the C++.** `SceneSurvey.cpp:125-134` assigns it when a blocking
hit carries a NaN impact point, a NaN normal, or a degenerate (near-zero) normal — a *failed
measurement*, which is not the same observation as "there is no floor here". Before this change the
class was structurally unreachable and every downstream rail of the form
`valid excludes trace_error` reduced to `valid <= total`, i.e. was vacuous.

**`unknown` remains structurally unreachable in the C++.** It is a real fail-closed initialiser
(`SceneSurvey.cpp:120`) but every branch overwrites it, and `SceneSurvey.cpp:155` writes a class for
every index in the loop, so the counter is always `0`. **A validator must therefore not cite
"valid excludes unknown" as a gate against the native counter** — it is vacuous. The canonical
Python authority *can* produce `unknown` (a cell inside the region with no observation recorded, and
— only when `τ_n` is absent, §5.2.3 — any cell whose edge status is indeterminate), so the rail is
meaningful there and only there. Recorded as fixture `unknown_class_unreachable`.

Note that with `τ_n` declared (§5.2.1) the *indeterminate* source of `unknown` no longer arises for
`CONTRACT_TOLERANCES`: a supported cell now resolves to `valid_support` or `edge`, never `unknown`.
The remaining canonical source of `unknown` is an unobserved cell.

---

## 5 — Edge detection

An edge is a **neighbourhood discontinuity**, not an appearance. The authoritative predicate is:

```
E_ij = S_ij ∧ ∃ q ∈ 𝒩(i,j) :
           ¬S_q
         ∨ |z_ij - z_q| > τ_h
         ∨ arccos(clamp(n̂_ij · n̂_q, -1, 1)) > τ_n
```

`E_ij` is a re-classification of **supported cells only**. A cell that is not supported keeps its
own class; it is never `edge`.

`¬S_q` is satisfied by `S_q = False` **and** by `S_q = None`. That is the declared fail-closed rule
of §4.1 applied consistently — an unknown neighbour is not known support, so a supported cell beside
it sits on a known boundary of knowledge. (The Kleene-logic alternative, `¬None = None`, was
considered and rejected: it would make an unknown neighbour weaken the edge result rather than
strengthen it, which is the unsafe direction.)

### 5.1 — Neighbourhood and boundary handling

`𝒩(i,j)` is **4-connected (von Neumann)**: `(±1, 0), (0, ±1)` — `SceneSurvey.cpp:174-175`.

**An off-grid neighbour is NOT evidence of an edge.** `SceneSurvey.cpp:188` skips a neighbour with
no entry rather than treating absence as invalid. This is deliberate and must be preserved: the
opposite convention marks the entire grid perimeter as edge, which is a shape artifact of the
sampling window rather than an observation about the world.

Consequence: cells at `|i| = k` or `|j| = k` are evaluated against fewer than four neighbours —
corners against 2, other perimeter cells against 3, interior cells against 4 — and are
systematically *less* likely to be classified `edge`. That asymmetry is a known property of the
contract, and downstream evidence must not present perimeter cells as equally-supported evidence.

### 5.2 — The C++ edge flag is DIAGNOSTIC [RESOLVED 2026-07-30]; `τ_n` is now DECLARED

The normal-discontinuity term **does not exist in the shipping C++**. Pass 2
(`SceneSurvey.cpp:184-200`) tests only neighbour invalidity and `|Δz| > τ_h`; no neighbour normal is
compared. It therefore systematically *under*-reports: a ridge crest with a sharp normal change but
no height step stays `valid` on both sides.

**Operator resolution: the C++ edge flag MAY REMAIN, as a temporary DIAGNOSTIC. It MUST NOT satisfy
the authoritative edge result.** This is now stated in three places so it cannot be mistaken:
the pass-2 comment block at `SceneSurvey.cpp:159-173`; the header doc for `SampleSurveySupport`
(`SceneSurvey.h:41-60`); and the log line itself, which carries `edge_authority=diagnostic`
(`SceneSurvey.cpp:225`). The authoritative edge result is derived by the WorldForge evidence layer
from raw observations — see §10.

#### 5.2.1 — `τ_n` declaration

| Field | Value |
|---|---|
| Contract name | `τ_n` — edge normal-discontinuity tolerance |
| Field name (Python) | `SupportTolerances.tau_n_deg` |
| **Units** | **degrees**, plane angle between two unit surface normals |
| **Declared value** | **`τ_n = θ_max` = 44.0°** — *derived*, see 5.2.2 |
| Derivation | `derive_tau_n_deg(θ_max) = TAU_N_MULTIPLIER * θ_max`, `TAU_N_MULTIPLIER = 1.0` |
| **Valid range** | `0 < τ_n < 2·θ_max`. Open at both ends — see 5.2.2 for why each end is excluded |
| **Comparison** | `dot(n̂_ij, n̂_q) < cos(τ_n)` — **strictly less than** |
| **Default policy** | **No default.** `tau_n_deg = None` is REFUSED, never defaulted |
| **Behaviour when absent** | Reading `cos(τ_n)` raises `UndeclaredToleranceError`; `E_ij` becomes tri-state (see 5.2.3) |
| Float tolerance | **None — exact comparison.** See 5.2.4 |
| Serialization | degrees as a JSON number; the *derivation*, not the number, is what crosses (5.2.5) |

The comparison is on the **dot product against `cos(τ_n)`**, never `arccos` of the dot product
(§4). Because `arccos` is strictly decreasing on `[-1, 1]`,
`arccos(clamp(n̂_ij · n̂_q, -1, 1)) > τ_n ⟺ n̂_ij · n̂_q < cos(τ_n)`, and the second form avoids the
`acos`/`degrees` round-trip that is exactly where two languages disagree in the last bits. Both
normals are unit-normalised first (§4, `_unit_normal`), so the dot product *is* the cosine of the
separation angle; a non-unit normal is a failed measurement (`trace_error`), never a scaled one.

#### 5.2.2 — Why 44°, and why the range is open at both ends

This is a **declaration with a stated derivation**, not a measurement. It is not an
implementation-local constant, and it introduces no new number: `44.0` is typed once, at
`SceneSurvey.cpp:90`, and `τ_n` is computed from it — the same rule `τ_h = 2·h_step` already obeys.

**Upper end — a hard bound, and it is why `2·θ_max` is *not* the answer.** The normal term is only
ever evaluated between two cells that are **both supported**
(`support_grid_canonical.py`, `derive_edges`: the cell is supported by construction and the
neighbour is gated on `q.supported is True` before the normal comparison is reached). Both unit
normals therefore satisfy `n̂ · ẑ >= cos(θ_max)` — each lies within `θ_max` of world up — so their
separation is at most `2·θ_max = 88°`. **Any `τ_n >= 2·θ_max` is vacuous: it can never fire.** This
is not asserted, it is proved by golden case `edge::tau_n_at_ceiling_is_provably_vacuous`, which
builds the sharpest crest two supported cells can form (two faces at exactly `θ_max` in opposing
directions) and shows a `τ_n` of 88° still does not fire. `SupportTolerances.tau_n_ceiling_deg`
names the bound and `tau_n_is_vacuous` tests it.

**Lower end — a soft bound that cannot be derived, only bounded away from zero.** `τ_n` must exceed
the normal variation produced by merely *sampling a smooth standable surface*, or every curved slope
becomes an `edge`. Fixing that lower bound properly needs a curvature budget or a measured
character-controller tolerance. **Neither exists in this repo** — the search that established this
is recorded below. So the lower end is open, not quantified.

**The choice.** Inside `(0°, 88°)`, `θ_max` is the midpoint: the maximum-margin point between the
two failure modes above — vacuity at the top, curvature false-positives at the bottom. It is also
the **only angle this contract already declares**, and it carries the right meaning: `θ_max` is the
declared boundary between an orientation a character can stand on and one it cannot. Setting
`τ_n = θ_max` states:

> Two adjacent supported cells are on the same walkable surface only if their orientations differ by
> **less than the entire standable range**. A larger turn across one sample step is a crease between
> two faces, not a slope.

**The counter-argument, recorded.** `τ_h` is `2 × h_step`, so the symmetric-looking choice would be
`τ_n = 2 × θ_max`. That analogy **fails**, and the failure is itself the argument: the height domain
is unbounded (a neighbour can be any `Δz` away), whereas the angular domain is *already* capped at
`2·θ_max` by the supported-cell precondition. Copying the `2×` multiplier into the angular term
lands exactly on the vacuous ceiling. The two tolerances have different multipliers because they
live in differently-bounded domains.

**What would change this.** A real character-controller step/lip angular tolerance, a locomotion
authoring rule, or a measured value from the target — none of which exists here (searched: no `τ_n`,
normal-discontinuity, or neighbour-normal angular tolerance anywhere in `tools/` or in the plugin;
the only angle constants in the C++ are `MaxSlope` at `SceneSurvey.cpp:90` and the `acos` clamp
bounds at `:139`). When one appears, `derive_tau_n_deg`, this table, and the C++ change **together**.

#### 5.2.3 — Behaviour when `τ_n` is absent (the refusal path, still live)

`CONTRACT_TOLERANCES` now carries a derived `τ_n`. The refusal machinery is **not** removed, because
a tolerance set that genuinely has no `τ_n` must never quietly acquire one — and a guard nothing can
reach is a guard that rots. `TOLERANCES_TAU_N_REFUSED` exists so the path stays exercised:

- Reading `cos(τ_n)` raises `UndeclaredToleranceError`. There is no fallback and no opt-out;
  `refuse_undeclared_tau_n=False` without a declared value also raises.
- With the term refused, an edge can still be **proved** (a declared disjunct fires) but a non-edge
  can **never** be proved. So for a supported cell with at least one on-grid neighbour,
  `E_ij ∈ {True, None}` — it is **never `False`**.
- Only a cell with no evaluable neighbours at all (`k = 0`) can be proved `E_ij = False`.
- Fail-closed, an indeterminate `E_ij` resolves to class `unknown`, not `valid_support`.

**What declaring `τ_n` bought.** Under the refusal a uniform flat grid reported as entirely
`unknown` — honest, but useless as evidence. With `τ_n` declared, the same grid resolves to
`valid_support` throughout (`edge::declared_tau_n_resolves_a_flat_grid`). That is the whole return on
the declaration, and it is asserted rather than described.

A Python collector that silently picks a `τ_n` still produces results that cannot be compared to the
C++ — which is why the value is *derived from a shared declared constant* rather than chosen.

#### 5.2.4 — Floating-point tolerance: there is none, deliberately

The comparison `dot < cos(τ_n)` is **exact**. No epsilon is added on either side.

Adding a tolerance `ε` to a threshold comparison does not remove the boundary, it moves it to
`cos(τ_n) ± ε` and makes the new boundary undeclared. The declared boundary must be the only one.
Consequences, all asserted as goldens:

- **Strictly greater-than.** A separation of *exactly* `τ_n` is **not** an edge. This matches `τ_h`,
  which is `> `, not `>=`, at `SceneSurvey.cpp:195`.
- **Reproducibility at the boundary is by construction, not by luck.** `cos(τ_n)` is computed once,
  as `math.cos(math.radians(tau_n_deg))`. A normal pair separated by exactly `τ_n` produces a dot
  product bit-identical to that value, so `dot < cos_tau_n` is deterministically `False`.
  `golden::tau_n_at_threshold_is_not_an_edge` builds precisely that pair.
- **Unit-normalisation happens first**, with its own declared tolerance
  (`unit_normal_tol = 1e-3`): a normal whose length deviates by more than that is a **failed
  measurement** (`trace_error`), not a rescaled observation. That is the only tolerance in this path,
  and it guards *measurement validity*, not the angular comparison.

Goldens `golden::tau_n_{below,at,above}_threshold_*` pin all three sides: 43° does not fire, exactly
44° does not fire, 46° (split ±23° so both faces stay standable) fires and names
`normal_discontinuity` as the term.

#### 5.2.5 — Cross-language serialization

- **Unit: degrees.** Never radians, never a cosine. `cos(τ_n)` is a computed comparison value, not a
  serialized one — shipping the cosine would bake one language's `cos` rounding into the contract.
- **On the wire: a JSON number** in degrees, alongside the `theta_max` it derives from.
- **What must actually cross is the derivation, not the number.** An implementation that receives
  `44.0` and stores it as its own literal has re-typed the constant and re-opened D18 drift. It must
  compute `τ_n` from its own `θ_max` using `TAU_N_MULTIPLIER`. The conformance harness gates the
  derivation, not the value: `edge::tau_n_is_derived_not_typed`.
- **Non-finite is refused, never encoded** — consistent with the numeric-hygiene rule the evidence
  layer already applies.
- **The C++ carries no `τ_n` at all** (§5.2.6), so today nothing crosses. This section fixes the
  form so the native-collector promotion has a target.

#### 5.2.6 — The C++ does NOT implement `τ_n` [HANDOFF]

Stated plainly because it is the difference between the contract and the shipping engine:

**`τ_n` is declared for the AUTHORITATIVE derivation — the canonical Python authority. The shipping
C++ diagnostic pass does not implement it, and cannot be made to without new data retention.**

`SceneSurvey.cpp` pass 1 stores only `H.ImpactPoint.Z` into `GridZ` (`SceneSurvey.cpp:140`); the
impact normal is consumed by the slope test at `:138-141` and **discarded within the loop
iteration**. Pass 2 (`:184-200`) therefore reads only `Cls` and `GridZ` and has **no per-cell normal
to compare**. Adding `τ_n` natively is not "add a comparison" — it requires a per-cell normal map
alongside `GridZ`, which is native-collector work under §10 and out of scope for the lane that wrote
this section (which may not edit C++).

Gated in both directions so the asymmetry cannot rot:
`tolerance::cpp_pass2_still_has_no_normal_term`, `tolerance::cpp_retains_no_per_cell_normal`, and
`tolerance::cpp_has_no_tau_n_literal` go **RED** the moment the C++ gains the term — which is when
this section, the ledger row, and the golden must all be updated together. The numeric consequence
is pinned by `golden::XFAIL::cpp_cannot_reproduce_tau_n_edges`: on the ridge-crest fixture the
canonical authority proves **6** edges and the native pass finds **0**.

### 5.3 — Ordering dependence

Edge reclassification reads `S_q` from **pass 1** classifications only. It must not observe edges
written by pass 2, or the result becomes iteration-order dependent. The C++ is safe here because it
only ever *writes* `CLS_EDGE` and only ever *reads* `CLS_UNSUPPORTED`/`CLS_TRACE_ERROR`/
`CLS_UNKNOWN` (`SceneSurvey.cpp:189`) — a value pass 2 never produces. The canonical Python
implementation preserves the separation explicitly: pass 1 produces an immutable
`Pass1Result` array and pass 2 writes a second array. Fusing the passes is a correctness bug, not an
optimisation.

### 5.4 — A `blocked` neighbour: native and canonical disagree [OPEN, found 2026-07-30]

`SceneSurvey.cpp:189` tests `CLS_UNSUPPORTED || CLS_TRACE_ERROR || CLS_UNKNOWN` — **`CLS_BLOCKED` is
omitted from the invalid set.** Under the authoritative predicate a blocked cell has `S_q = False`,
so `¬S_q` holds and its supported neighbour **is** an edge.

Concretely: a cell standing on the lip above a 70° face reads as ordinary open floor natively, and
as an edge canonically. The native answer is the unsafe one. Recorded as fixture
`blocked_neighbour_not_edge`; needs an operator ruling on whether the C++ diagnostic should be
brought into line or left as-is with the divergence documented.

---

## 6 — Canonical ordering

Raw records are emitted in **row-major ascending index order**: `i` from `-k` to `+k` (outer),
`j` from `-k` to `+k` (inner). Formally, `(i,j) < (i',j')` iff `i < i'` or (`i == i'` and `j < j'`).
This matches the C++ traversal at `SceneSurvey.cpp:111-113` and `:176-178`.

Ordering is part of the contract because raw records feed a determinism hash. Note that the C++
*tally* loop iterates a `TMap` (`SceneSurvey.cpp:206`) whose order is unspecified — acceptable for
counts, and **not** acceptable for any future raw emission. Native raw emission must iterate the
index range, never the map.

**Ordering is carried by the coordinates, never by the sample identity.** Sorting `sample_id`
strings lexically does **not** reproduce this order — see §1.4.4, which pins the inequality on
purpose so no consumer comes to rely on a coincidence.

---

## 7 — Projection convention

`ẑ` is world up, `+Z`. Slope is measured against world up, not against the anchor's local frame or
a surface-fitted plane. Sample coordinates are placed in the **world XY plane at fixed spacing**;
the grid is axis-aligned to world X/Y and is **not** rotated to the subject's yaw. Two surveys of
the same subject at different yaws therefore sample the same world cells — intentional, and the
reason the grid is centred on an observed anchor location rather than an actor transform.

---

## 8 — Known non-observations

Do not treat these as measurements:

- **`navmesh=0`** is a literal inside the log format string (`SceneSurvey.cpp:224`). It is not a
  navmesh query and must never be reported as one.
- **`SampleSurveySupport` returns only `Total`** (`SceneSurvey.cpp:227`) — the per-cell `TMap` grid
  and heightfield it builds are discarded at function exit. The class counts survive only as text
  in a log line, which `run_scene_survey_probe.py:132-137` parses as a **diagnostic** channel that
  may not supply a reported value. This is the structural reason the support lane is weaker evidence
  than the rest of the chain, and the thing a promoted native collector would fix (§10).
- **The `edge` count in that log line** is the diagnostic flag of §5.2, not an edge result.

---

## 9 — Conformance

Any implementation claiming this contract must:

1. Reference §3 tolerances from a single declaration; no re-typed literals.
2. Emit raw per §2 with `None` distinguishing miss from failure, in both the ground and head traces.
3. Compute `k = floor(R/s)` and place no sample outside the half-extent (§1).
4. Name its `sample_region_shape` and refuse a shape it does not implement (§1.2).
5. Reproduce §5.1 boundary handling exactly, including the off-grid skip.
6. Preserve the §5.3 two-pass separation.
7. Derive `τ_n` from `θ_max` (§5.2.2) rather than re-typing `44.0`; compare
   `dot < cos(τ_n)` exactly, with no epsilon (§5.2.4). If a tolerance set has **no** `τ_n`, refuse
   the term rather than defaulting it, and represent the resulting indeterminacy as `None` rather
   than `False` (§5.2.3).
8. Emit in §6 canonical order.
9. Mint sample identities per §1.4 — coordinate-derived, float-free, operation-local, and never used
   as an ordering key.
10. Emit **no** verdict boolean, and no support class the assembler could consume as truth.

Two implementations conform when, given the same world and `(a, R, s)`, they produce
**identical raw records in identical order**. Matching aggregate counts is not conformance —
a count can match while individual cells disagree in compensating directions.

### 9.1 — Where conformance is proved

| Artifact | Path |
|---|---|
| Canonical authority | `tools/pipeline/support_grid_canonical.py` |
| Divergence fixtures | `tools/pipeline/support_grid_discrepancies.py` |
| Conformance harness | `tools/pipeline/support_grid_conformance.py` |
| Shield discovery shim | `tools/pipeline/test_negative_support_grid.py` |
| Report | `procedural/reports/scene_survey/support_grid_conformance_report.json` |

Run: `PYTHONUTF8=1 STRICT=1 python tools/pipeline/support_grid_conformance.py --strict`

Every check is blocking. A conformance harness with warn-only checks can go green while the contract
is broken.

---

## 10 — The split of authority [RESOLVED 2026-07-30]

**Python and C++ must not each own separate support mathematics.** Two copies agree by duplicated
convention, not by proof, and the first time they drift the drift is unattributable.

```
  engine-side layer                     WorldForge evidence layer
  (SceneSurvey.cpp)                     (support_grid_canonical.py)
  ─────────────────────────             ──────────────────────────────
  RAW TRACE OBSERVATIONS ONLY    ──▶    support S_ij
    trace_start, trace_end              height discontinuities
    hit (tri-state)                     edges E_ij
    impact_point, normal                aggregate safety
    actor_path, component_path
    failure
```

The engine side observes. The evidence layer decides. Anything the engine side classifies is a
**diagnostic**, never a result — which is why the `edge` flag was demoted rather than extended
(§5.2) and why the log line now says so out loud.

The shipping C++ has **not** yet been converted to raw emission — it still returns only `Total` and
logs its diagnostic counts (§8). That conversion is the D18 native-collector promotion and is out of
scope here; this section fixes the target so the promotion has something to build against, and so
nobody adds a *second* classifier in the meantime.

---

## 11 — Divergence ledger

Cases where the native path and the canonical authority give different answers for the same world.
Each is asserted by `divergence::<id>::still_holds` in the conformance harness, so if the C++ is
changed without updating this table the harness goes RED.

| Fixture | Status | Native | Canonical | C++ |
|---|---|---|---|---|
| `extent_r_lt_s` | resolved (§1.1) | *was* `k=1, N=9`, reach ±s | `k=0, N=1` | `:103` |
| `float32_quotient` | accepted (§1.3) | `floor(float32(R)/float32(s))` | `floor(float64(R/s))` | `:103` |
| `tau_n_ridge_crest` | **handoff** (§5.2.6) | `valid` both sides, **0** edges | **6** edges, `normal_discontinuity` | `:184-200`, `:140` |
| `blocked_neighbour_not_edge` | **open** (§5.4) | `valid` — blocked neighbour ignored | `edge` — `¬S_q` holds | `:189` |
| `unknown_class_unreachable` | accepted (§4.1) | never emitted; counter always 0 | emitted for an unobserved cell | `:120,155` |
| `head_trace_not_attempted` | accepted (§2) | `valid` — not-run reads as clear | `trace_error`, `S=None` | `:150-152` |
| `non_unit_normal` | accepted (§4) | `blocked` (raw `ImpactNormal.Z`) | `valid_support` (normalised `n̂`) | `:138-139` |

These are documented on purpose. A divergence that is written down, cited, and asserted by a test is
a known limit; a divergence discovered later inside a report is an unattributable bug.
