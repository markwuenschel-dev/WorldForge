# Execution Contract: closed request vocabulary for the first carrier (T4)

Status: ready for re-review (revision 3)

**Revision note (revision 1).** The first rewrite of the original T4 contract
responded to five verified defects in the original design: (1) the original
layering — declaring `wf.core.carrier_vocabulary.v1` on an object also
validated by v1's `world_request` strict validator while adding new
top-level fields — cannot pass `check_no_unknown` in strict mode
(`tools/wfcore/contracts/world_request.py:106-135`, verified that session);
(2) the save/reload requirement referenced a `constraint_id` field that did
not exist anywhere in the schema; (3) an excluded term would dual-fail
(generic v1 code + `WF1296`) instead of failing once; (4) `bounded_region`
had no coordinate frame, units, Z-extent policy, or map binding; (5)
`revision_policy` was referenced by the exclusion rail but never passed to
any validator. All five were fixed by restructuring around an explicit
**carrier envelope** that nests unmodified v1 documents rather than
overloading one of them.

**Revision note (revision 2, this pass).** An independent user re-review of
revision 1 found three further P1 (blocking) defects, verified directly
against the live document before this pass was dispatched — see
`.project-intelligence/decisions/terrain/worldforge-walkaway-mission/tickets/T4.md`,
"Re-review (2026-08-21)": (1) the envelope claimed to be a closed vocabulary
while deliberately leaving `bounded_region`/`interaction_objective` (plus two
other nesting points this revision also closes) open to unknown fields —
backwards, because v1's own permissive nested-object convention exists for
v1's *own* long-standing fields and does not obligate a brand-new
carrier-specific boundary to inherit it; (2) `bounded_region`'s four
offset/extent fields could be `UNKNOWN` with no resolution workflow anywhere
downstream, making an "executable" request that no adapter could actually
execute; (3) the save/reload "proof" bound nothing — `operation_id` and all
three hashes were unconstrained opaque strings, the hash algorithm and
canonical scope were undecided with no named owner, and a no-op (`pre ==
post`, nothing happened) satisfied the same check as a real completion. This
pass fixes all three, plus a fourth, closely related gap the re-review named
explicitly: the same no-op tolerance also meant a canonical first-proof run
could pass without ever having produced a real incomplete→complete
transition. `WF1296_CORE_REQUEST_DOMAIN_NOT_SUPPORTED` is unchanged and
remains the only new failure code this contract claims.

**Revision note (revision 3, this pass — "Fix pass 3", 2026-08-21).** A
second independent user re-review of revision 2 found it materially better
but still not approvable: two further P1 (blocking) defects, plus one
required handoff clarification, all verified directly against live source
before this pass was dispatched.

1. **Runtime evidence lived inside the caller-owned, supposedly-"unmodified"
   `acceptance_criteria` document — wrong, fixed by moving it out entirely.**
   `operation_id`, the three state hashes, `reload_verified_at`,
   `pre_completion_state`/`post_completion_state`, and `proof_kind` all lived
   inside the `evidence` sub-object of the targeted
   `evaluation_requirements[]` entry — itself inside the nested
   `acceptance_criteria` document that §1/§4/§5/§9.0/§14 all, in the same
   breath, called "unmodified." That is backwards: a declared acceptance
   contract that only acquires real values for eight of its fields *after*
   execution is not unmodified, it is mutated post-hoc, and every "closed to
   unknown fields" claim made about a document that still contained those
   fields was self-contradicting. Confirmed against live source this pass
   that this codebase already has a real, working precedent for keeping the
   two apart: `tools/wfcore/acceptance/evaluate.py`'s
   `evaluate_acceptance(criteria, delta, evidence, ...)`
   (`evaluate.py:444-446`) takes the caller-owned `acceptance_criteria`
   record and a **separately supplied** `evidence` argument — raw rows with
   their own schema, `EVIDENCE_REQUIRED = ("evidence_id", "constraint_id",
   "operation_id", "observed_at", "observation_kind", "reload_backed",
   "supports", "evidence_refs", "detail")` (`evaluate.py:155-157`) — as two
   distinct objects; `acceptance_criteria.py` itself never embeds a proof
   payload, only an `evidence_kind` *label* naming how a constraint will
   eventually be evaluated (`EVALUATION_REQUIREMENT_ALLOWED`,
   `acceptance_criteria.py:69-71`, confirmed by reading the file in full).
   Fixed this pass by removing every evidence field from both nested
   documents and the envelope itself, and spinning the evidence payload out
   into a separate runtime-evidence/receipt record that a later validator
   (owned by the new prerequisite ticket `EVD-1`, referenced but not
   implemented here) binds against the envelope as two distinct objects —
   see the rewritten §9.5 and the interface note in §9.10.
2. **`world_request.subject` was used as a target-map pointer throughout
   this document but never validated as one — fixed with a new carrier-only
   grammar rail.** §7 and §9.2 both treat `subject` as the one thing every
   spatial field in `bounded_region` is defined relative to, but
   `world_request.py` validates it only as a required, non-empty string
   (`world_request.py:136-137`, via the generic `check_str` at
   `contracts/__init__.py:162-167`) — confirmed by reading both this pass.
   Searched this codebase for a reusable Unreal map/package-path grammar
   before inventing one, per this pass's mandate; the closest real precedent
   found is `is_ue_package_path` (`tools/pipeline/transition_hygiene.py:70-
   78`), a narrow grammar validator built for an unrelated v2.5 report-
   hygiene gate. Fixed with a new carrier-only rail,
   `subject_is_target_map_path` (new §9.11), that restates (rather than
   imports — see §9.11 for why) that precedent's shape rule, narrowed to the
   `/Game/` mount only, plus an explicit requirement — stated as a binding
   note on `T1`'s own future implementation, since T4 cannot enforce this
   structurally before execution exists — that `T1`'s live evidence must
   bind the map identity it actually loads/mutates back to this same
   `subject` value. No second target-map field is added.
3. **Required handoff clarification (not a third P1, but must be explicit):
   `T1` is forbidden from claiming spatial boundedness it has not proven.**
   Verified this pass, directly against the live mutation-bound enforcement
   code: `classify_target` (`tools/wfcore/transaction/delta.py:325-371`),
   the single place membership is decided, called from both the preflight
   check and the post-apply check (`delta.py:328-330`), decides bound
   membership with exact string-list containment —
   `if path in allowed: return TARGET_IN_BOUND` (`delta.py:363-366`) against
   `allowed_packages`/`allowed_actors` — never a coordinate or transform
   comparison; the module's own docstring states this in so many words,
   "Membership is EXACT, never prefix or glob" (`delta.py:28-31`). This
   machinery proves which *addresses* (package/actor paths) a mutation
   touched. It proves nothing about whether those addresses' *transforms*
   fall inside `bounded_region`'s planar extent — no XY-region, bounding-
   box, or coordinate check exists anywhere in it, confirmed by reading
   `delta.py`'s `classify_target`/`bound_from_step`/`validate_world_delta`
   and `tools/wfcore/transaction/executor.py`'s `_check_actual_touches`
   (`executor.py:525-568`) in full this pass. New §9.12 states, as a hard,
   explicit, unimplemented-today requirement on `T1`'s own future
   contract — not something this document's own validators check — that
   `T1` must not claim a mutation stayed inside `bounded_region` unless it
   independently proves the actual mutated transforms lie within the
   resolved planar region; path-bound enforcement alone does not establish
   that claim.

This pass also records an explicit user decision correcting `EVD-1`'s
scope, updated everywhere `EVD-1` is referenced in this document (§9.10 is
the primary update): `EVD-1` is a separate, fourth ticket that blocks `T5`'s
canonical live proof run and `T2`'s LIVE-EVIDENCE implementation
specifically. It does **not** block `T4`'s own schema implementation, and it
does **not** block `T2` drafting its own entry-point contract — `T2` may
reference the envelope/receipt split conceptually before `EVD-1`'s schema
exists; `T2` only cannot *implement* live evidence handling until `EVD-1`
lands. `T4` no longer needs to hedge about whether `EVD-1` blocks its own
implementation, because it never did and does not now.

`WF1296_CORE_REQUEST_DOMAIN_NOT_SUPPORTED` remains the only new failure
code this contract claims; this pass adds no new code. This revision does
not mark itself approved — the Status line above records a third re-review
request, not adoption.

**Revision note (revision 4, “Fix pass 4”, 2026-08-21) — propagation, not
re-argument.** A third independent user re-review accepted fix pass 3's
*reasoning* on all three fixes — each was re-verified against live source by
independent lanes before this pass — but found the pass **half-applied**, and
refused it on that ground:

1. **§9.11 and §9.12 were promised, referenced eleven times between them, and
   never written.** §9 ended at §9.10 and §10 began immediately after.
   §9.7's validator docstring named a rail (`_rail_subject_is_target_map_path`)
   whose shape rule lived only in a section that did not exist, and §9.10's
   target-identity binding forwarded to “§9.11's parallel requirement on
   `T1`” — a dangling pointer. Both sections are written out in full this
   pass. No new argument: they state what fix pass 3 already established.
2. **The execution half (§10–§16) still specified revision 2's deleted
   design.** §9.5/§9.0 removed the `evidence` sub-object, the eight-field
   completeness check, the hash round-trip check, the completion-transition
   check, the `operation_id`-binding rail, and both
   `CARRIER_EVALUATION_REQUIREMENT_ALLOWED` and `EVALUATION_EVIDENCE_ALLOWED`
   — but §11's T4.4 still ordered every one of them built, §11's T4.6 still
   listed their fixtures, §14 still gated on them, §15 still coded them, and
   §16 still counted them. The sharpest instance was a direct
   self-contradiction: §9.7 said `validate_carrier_acceptance_pairing` keeps
   “the save/reload evidence CARDINALITY rail ONLY … narrowed from revision
   2's five rails to one”, while §11 told the implementer to build six.
   §10–§16 are rewritten this pass to match the settled §9 design exactly;
   §17 and §20 are corrected in the same sweep for the same reason.
3. **Two citation defects corrected while touching the document.**
   `_check_actual_touches` spans `executor.py:525-568`, not `525-564` as
   revision 3 cited it in three places (its returned `stray` record dict runs
   to line 567). And revision 3 called `is_ue_package_path` “the one real
   grammar validator found anywhere in the codebase” — an overstated absence
   claim: it is the only *derived-mount, multi-rule shape* validator, but at
   least nine other sites enforce real, weaker `/Game/`-prefix rules that
   reject and emit errors. The wording is corrected in §2 and §9.11.

**Ownership boundary, restated because §10–§16 now depend on it being
unambiguous:** `T4` owns the `subject` grammar rail (§9.11) plus the
pre-execution envelope and cardinality rails. `EVD-1` owns **all**
receipt/hash/operation-id/completion validation (§9.5, §9.10). No task in
§10–§16 may reference the deleted receipt sub-object.

**Dependency language, unchanged and re-confirmed this pass:** `EVD-1` does
**not** block `T4`, and does **not** block `T2` drafting its entry-point
contract. It blocks `T2`'s live-evidence *implementation* and `T5`'s
canonical live run.

Revision 4 does **not** mark itself approved, and authorizes no source
change: it records a fourth re-review request against a document-only pass.

**Documentation-honesty note (revisions 2-3).** `tools/wfcore/contracts/
carrier_vocabulary.py` and its test module do not exist. Nothing in this
document has been implemented or run. Everywhere this document describes what
a rail, pipeline, or fixture "produces," "proves," or "confirms," that
language names **specified, not observed** behavior — it is what T4.4/T4.6
are required to make true, not a report of a test that has already passed.
Language in revision 1 that read as though the pipeline's behavior had been
demonstrated rather than designed has been softened below. This pass's own
new rails and interface notes (§9.5, §9.11, §9.12) are held to the same
discipline: nothing in them has run either.

For the implementer who picks up `T4` from
`.project-intelligence/decisions/terrain/worldforge-walkaway-mission/tickets/T4.md`.
This document is the binding plan. **No source change is authorized by this
document itself** — the map's standing constraint
(`.project-intelligence/decisions/terrain/worldforge-walkaway-mission/map.md:78-83`)
still applies; T4 remains a backlog item until a future work cycle explicitly
authorizes execution of the tasks below.

---

## 1. Executive mission

Extend wfcore's existing `world_request` / `acceptance_criteria` contract pair
with a new, additive, versioned **envelope** — the **carrier vocabulary** —
that:

1. names the exact closed field set the first live carrier (T2) may accept:
   target map (now a validated map-path shape, fix pass 3), bounded region,
   biome/landform, placement/POI intent, one interaction objective, a
   structural requirement that save/reload evidence will exist — carried as
   an envelope object that *nests* a genuinely, fully unmodified
   `wf.core.world_request.v1` document and a genuinely, fully unmodified
   `wf.core.acceptance_criteria.v1` document, rather than adding fields
   directly onto either. **Fix pass 3:** the runtime-evidence *payload*
   itself (`operation_id`, state hashes, completion states, `proof_kind`) is
   no longer part of either nested document or the envelope — it lives in a
   separate runtime-evidence/receipt record that a later validator binds
   against the envelope, so "nests an unmodified document" is now true
   without qualification (§9.5, §9.10);
2. rejects quest/combat/reward/faction/tactical-behavior/streaming terms with
   one new, real, domain-naming failure code — never a silent drop, and never
   a second failure alongside the generic one for the same cause;
3. keeps every existing `world_request`/`acceptance_criteria` v1 document
   valid forever, because the new rules live in a new sibling envelope
   module, not an edit to v1's required-field set, and because nothing new is
   ever added *directly onto* a v1 document's own top level.

## 2. Current baseline

- Branch `worldforge/wfcore-consumer-platform` (per
  `docs/contracts/wfcore_caller_mission_brief.md:85`).
- `tools/wfcore/contracts/world_request.py` defines `wf.core.world_request.v1`
  — required fields `request_id, consumer_id, catalog_id, request_kind,
  subject, constraints, semantic_landmarks, gameplay_affordances, population,
  environment, schema_version`
  (`tools/wfcore/contracts/world_request.py:93-105`). `subject` is already the
  caller-owned "target map" field, with no default
  (`tools/wfcore/contracts/world_request.py:117-123`).
- **The strict-mode blocker (verified this session).**
  `validate_world_request(obj, strict=False)` calls `check_no_unknown(obj,
  WORLD_REQUEST_ALLOWED, code, _P, strict)`
  (`tools/wfcore/contracts/world_request.py:135`), and in strict mode this
  rejects any top-level field not in `WORLD_REQUEST_ALLOWED`
  (`world_request.py:106-115`). A document cannot simultaneously declare
  `wf.core.carrier_vocabulary.v1`, satisfy `wf.core.world_request.v1`'s own
  `schema_version` check, and carry new top-level fields
  (`bounded_region`, `interaction_objective`) — that is a structural
  contradiction, not a style preference. This is why §9 below restructures
  around a nesting **envelope** instead.
- **Where v1 has no closed-field gate (verified this session, load-bearing
  for §9's placement decisions).** `_rail_environment`
  (`world_request.py:331-360`) validates the `environment` object with
  `check_required` + `check_measure` + `check_enum` calls only — it never
  calls `check_no_unknown` on `env`. The same is true of
  `_rail_evaluation_requirements` in `acceptance_criteria.py:122-177` for
  each `evaluation_requirements[]` entry — `EVALUATION_REQUIREMENT_ALLOWED`
  is *defined* (`acceptance_criteria.py:69-71`) but never passed to
  `check_no_unknown` anywhere in the file, confirmed by reading the file in
  full this session. Both nested objects are therefore *not* closed
  surfaces: an extra key inside `environment` does not fail v1 strict
  validation. This is the concrete reason `environment.biome_class` (§9.1)
  can be added *inside* v1's own nested object without editing v1 at all,
  while `bounded_region` and `interaction_objective` — genuinely new
  *top-level* fields — cannot, and must live on the envelope instead.
  **Fix pass 3 correction:** revision 2 also cited this same
  no-closed-field-gate fact to justify adding a per-evaluation `evidence`
  sub-object inside the nested `acceptance_criteria`'s `evaluation_
  requirements[]` entries. That placement is removed this pass (see below
  and §9.5) — the fact that v1 *permits* an extra field there was never a
  reason it should *carry* runtime evidence; the fix pass 3 re-review named
  this as the deeper problem with that placement, independent of whether v1
  would have rejected it.
- **Fix pass 3 — the declared-criteria/evidence split already has a real
  precedent in this codebase, and it is not `acceptance_criteria.py`
  carrying evidence itself (verified this pass).**
  `tools/wfcore/acceptance/evaluate.py`'s entry point,
  `evaluate_acceptance(criteria, delta, evidence, applied_at=None,
  result_id=None)` (`evaluate.py:444-446`), takes the caller-owned
  `acceptance_criteria` record and a **separate** `evidence` argument — raw
  rows with their own schema, `EVIDENCE_REQUIRED = ("evidence_id",
  "constraint_id", "operation_id", "observed_at", "observation_kind",
  "reload_backed", "supports", "evidence_refs", "detail")`
  (`evaluate.py:155-157`) — as two distinct objects, never one document
  carrying both. `acceptance_criteria.py` itself (`EVALUATION_REQUIREMENT_
  ALLOWED`, `acceptance_criteria.py:69-71`; `EVIDENCE_KINDS`,
  `acceptance_criteria.py:55-61`) never defines a field for a proof
  payload — `evidence_kind` is a *label* naming how a constraint will
  eventually be evaluated, not a container for the evaluation itself; the
  module docstring frames acceptance as a fold over *declared* constraints
  plus *separately supplied* evaluations
  (`acceptance_verdict(criteria, evaluations_by_id)`, `acceptance_
  criteria.py:216-241`, whose second argument is already a reduced
  `constraint_id -> tri value` mapping, not raw evidence). This is the
  concrete precedent fix pass 3's §9.5 rewrite follows: evidence is a
  separate record, never embedded in the caller-owned declaration it
  proves.
- **Fix pass 3 — `world_request.subject` has no map-path grammar, verified
  this pass, and no reusable one exists anywhere in this codebase to
  import.** `subject` is validated only by the generic `check_str` loop at
  `world_request.py:136-137` (`check_str` itself,
  `contracts/__init__.py:162-167`, asserts only `isinstance(v, str) and
  bool(v.strip())` — reused identically for `request_id`/`consumer_id`/
  `catalog_id`). Searched `tools/wfcore/contracts/` in full (no `/Game/`,
  `.umap`, `PackageName`, or `ObjectPath` vocabulary anywhere),
  `tools/bridge/scene_survey_far_side.py` in full (its only map-path logic,
  `_norm_package` at `scene_survey_far_side.py:474-488`, is an
  identity-comparison *normalizer* with no grammar enforcement — it accepts
  any string), and `tools/pipeline/asset_paths.py` in full (a repo-
  filesystem-layout module with no UE package-path concept — its own
  self-test at `asset_paths.py:82` asserts a `/Game/...` string does *not*
  match its own quarantine-root check, confirming it has no package-path
  awareness). The only *shape-grammar* validator — one that rules on
  separators, leading slash, segment structure, and mount membership rather
  than merely testing a prefix — is `is_ue_package_path`
  (`tools/pipeline/transition_hygiene.py:70-78`), built for an unrelated
  v2.5 report-hygiene gate. **Corrected in fix pass 4:** revision 3 called
  this "the one real grammar validator found anywhere in the codebase,"
  which overstates the absence — at least nine other sites enforce real,
  weaker `/Game/`-prefix rules that do reject and emit errors (enumerated in
  §9.11). None of them is a substitute for a shape grammar, but the honest
  claim is the narrower one. See §9.11 for the full rule and for why this
  pass restates its shape instead of importing it.
- **Fix pass 3 — the mutation-bound enforcement machinery is path-based,
  not region-based, verified this pass, load-bearing for §9.12.**
  `classify_target(bound, target_kind, target_path)`
  (`tools/wfcore/transaction/delta.py:325-371`) is, by the module's own
  docstring, "the single place membership is decided" (`delta.py:26`) — the
  function's own docstring calls it "The single membership rule in the
  package" (`delta.py:326-337`) — used by both the preflight check and the
  post-apply check (`delta.py:328-330`); its decision is exact
  string-list containment — `if path in allowed: return TARGET_IN_BOUND`
  (`delta.py:363-366`) against `allowed_packages`/`allowed_actors` — and
  the module docstring states plainly "Membership is EXACT, never prefix or
  glob" (`delta.py:28-31`). `tools/wfcore/transaction/executor.py`'s
  `_check_actual_touches` (`executor.py:525-568`) is the concrete
  post-apply enforcement point and calls the same `classify_target`. No
  coordinate, transform, or XY-region comparison exists anywhere in this
  call chain, in `delta.py`, or in `executor.py` — confirmed by reading
  both files in full this pass. This machinery proves *which addresses*
  (package/actor paths) a mutation touched; it proves nothing about whether
  those addresses' *transforms* fall inside a spatial region. See §9.12.
- `tools/wfcore/contracts/acceptance_criteria.py` defines
  `wf.core.acceptance_criteria.v1`, with a closed `EVIDENCE_KINDS` = `(
  "static_analysis", "authoring_time_check", "runtime_observation",
  "human_review", "external_measurement")` naming *how a constraint is
  evaluated* (`acceptance_criteria.py:55-61`).
  `tools/wfcore/models/observed_world.py:143-150` defines a **separate,
  unrelated** `EVIDENCE_KINDS` naming *what kind of artifact backs a
  measurement*. Both real, both called `EVIDENCE_KINDS`, different modules —
  verified by reading both files in full. Anyone extending "evidence"
  vocabulary for T4 must extend `acceptance_criteria.EVIDENCE_KINDS`, not
  `observed_world.EVIDENCE_KINDS`.
- `tools/wfcore/contracts/revision_policy.py` defines
  `wf.core.revision_policy.v1`, whose `MUTATION_KINDS` closed vocabulary is
  `(add_geometry, remove_geometry, move_geometry, replace_surface_material,
  adjust_terrain_height, adjust_lighting, add_population, remove_population,
  move_population, adjust_navigation, adjust_volumes, adjust_audio,
  retag_metadata)` (`revision_policy.py:50-64`, read in full this session).
  **None of these strings overlaps any `EXCLUDED_DOMAIN_TERMS` entry** — see
  §9's resolution of item 5.
- `tools/wfcore/constraints.py:304-311` already enforces
  `constraint_ids_unique` on every constraint set that goes through
  `validate_constraint_set` — including `acceptance_criteria.constraints`,
  which folds through it (`acceptance_criteria.py:109-110`). This is
  load-bearing for §9's "resolves uniquely" definition: uniqueness does not
  need to be re-derived by the carrier module, only existence does.
- `tools/bridge/scene_survey_far_side.py:2594-2631` (`_verify_anchor`) is the
  only place in this codebase that already resolves and verifies a spatial
  anchor against a live UE level: `anchor_mode == "explicit_transform"`
  requires a finite `[x, y, z]` `anchor_location`, and `anchor_mode ==
  "actor_object_path"` resolves a named actor **among "the placed actors of
  this level"** (`scene_survey_far_side.py:2618-2620`) and reads its live
  location. There is no third "bare world origin, no anchor" mode anywhere
  in this codebase — verified by reading the function in full. §9's
  `bounded_region` design reuses exactly these two modes and deliberately
  does **not** invent a third.
- `tools/wfcore/contracts/consumer_profile.py:107-114` is the house
  convention for linear/positional distance units: `capsule_height_cm`,
  `capsule_radius_cm`, `eye_height_cm`, `max_step_height_cm`,
  `max_jump_height_cm` — all `_cm`, matching UE's native unit (1 Unreal Unit
  = 1 cm). `tools/wfcore/models/observed_world.py` confirms the same
  convention throughout its own measured fields (`distance_to_anchor_cm`,
  `ground_delta_z_cm`, `footprint_sample_radius_cm`, `bounds_origin`/
  `bounds_extent` in UE-native units). `world_request.environment.extent_m2`
  is the one existing exception, and it names an *area*, not a linear
  distance — not a counter-precedent for `bounded_region`'s origin/extent
  fields, which are linear. §9 standardizes `bounded_region` entirely in
  `_cm`, correcting the original draft's own inconsistency (it had mixed
  `origin_x_cm` with `extent_x_m`).
- `tools/wfcore/contracts/consumer_profile.py:88-101`: the `LOCOMOTION_MODES`
  "jump" story — a closed vocabulary grown *after* a real caller exposed a
  gap, documented in-line at the point it was added. This is the precedent
  `BIOME_CLASSES` (§9) and `VERTICAL_SCOPES` (§9) both follow: ship a minimal
  honest starter set now, grow it later with a real caller's evidence.
- Six files import `world_request` today and would be affected by nothing
  changing in v1 itself: `tools/pipeline/run_consumer_flow.py:123,240`,
  `tools/consumers/demoarena/__init__.py:50,177`,
  `tools/consumers/demoexpanse/__init__.py`, `tools/consumers/adapter.py:84`
  (imports `AFFORDANCE_KINDS`/`LANDMARK_ROLES` directly for its own
  reachability rail), `tools/wfcore/contracts/test_contracts.py`.
- `tools/wfcore/failure.py` is a shim onto the single failure-code authority
  `tools/pipeline/failure_codes.py`; Core owns band **WF1200–1299**
  (`tools/wfcore/failure.py:1-59`). The last defined Core code is
  `WF1290_CORE_PROVIDER_EVIDENCE_IS_FIXTURE` (`failure_codes.py:1408`),
  inside a section explicitly commented `-- external-tool provider evidence
  (1289-1295) --` (`failure_codes.py:1398`). **WF1296–1299 are the only
  genuinely free numbers** in the Core band. This contract claims exactly
  one of them, `WF1296`; confirmed non-colliding with the sibling T3
  contract's WF1297-1299 allocation, which is out of scope for this
  document.
- `tools/pipeline/validate_failure_codes.py:1-19` is the runnable gate that
  proves the band stays coherent. Confirmed command form:
  `PYTHONUTF8=1 python pipeline/validate_failure_codes.py --strict` (run
  from `tools/`).
- `tools/wfcore/contracts/test_contracts.py:1-114` is the existing
  negatives-first suite pattern: canonical example asserted valid under
  `strict=True`, then ≥3 known-bads spawned via `**over` from that example,
  each asserted to fail a **named check** with a **named code**
  (`expect_failure`, `test_contracts.py:63-82`).
- `tools/wfcore/models/desired_world.py` and `observed_world.py` carry no
  bounded-region, biome, or save/reload-evidence concept today; nothing
  there needs to change for T4.

## 3. Strategic meaning

Q4 (`.../decisions.md:108-138`) rejected "accept a generic `objective` string
and route to the closest script" because an interface that is broader than
the backend's evidence contract manufactures false positives. This contract
is the concrete schema-level enforcement of that rejection: it makes the
narrow scope a thing the validator refuses to cross, not a thing a docstring
asks callers to respect. It directly unblocks `T1` and `T2`, both of which
depend on `T4` (`.../map.md:52-53`).

## 4. Scope

- One new sibling contracts module, `wf.core.carrier_vocabulary.v1`, defining
  a **carrier envelope** object that nests one unmodified
  `wf.core.world_request.v1` document and one unmodified
  `wf.core.acceptance_criteria.v1` document, plus envelope-level fields
  (`envelope_id`, `bounded_region`, `interaction_objective`).
  `wf.core.revision_policy.v1` is **not** nested — see §9's resolution of
  item 5; the module does not import `revision_policy.py` at all.
- One new required `bounded_region` concept (envelope-level, UE-anchored,
  **closed** field set, and — since revision 2 — its four offset/extent
  fields required to be resolved, non-`UNKNOWN`, on every request this
  envelope represents), one new required `interaction_objective` concept
  (envelope-level, carrying a `constraint_id` binding, **closed** field
  set), one new required `environment.biome_class` concept (nested *inside*
  the v1 `world_request`, legal to add because that nesting level has no
  closed-field gate of its own — §2 — but now carrier-closed at the carrier
  layer, on top of v1's own permissive default — see §9.0), and — fix pass
  3, replacing revision 2's in-document evidence fields — a structural rail
  requiring exactly one `evaluation_requirements[]` entry to exist naming
  this carrier's `interaction_objective.constraint_id` with
  `evidence_kind == "runtime_save_reload_observation"`; the evidence
  *content itself* (state hashes, completion states, `proof_kind`,
  `operation_id`) is validated later, against a separate receipt record, by
  a validator this document does not implement (§9.5, §9.10).
- One new required carrier-only rail, **`subject_is_target_map_path`** (fix
  pass 3, new §9.11): `world_request.subject` must be a `/Game/...` UE
  package path, not merely a non-empty string. No new field — this rail
  tightens the existing `subject` field's meaning; the target-map pointer
  stays singular.
- **This revision — carrier-level closed-field rails.** `bounded_region`,
  `interaction_objective`, and `world_request.environment` each gain a
  carrier-owned `check_no_unknown`-equivalent rail, reusing
  `C.CORE_WORLD_REQUEST_INVALID` (WF1208) — see §9.0. **Fix pass 3:** the
  fourth nesting point revision 2 closed — the targeted
  `evaluation_requirements[]` entry's `evidence` sub-object — no longer
  exists to close; see §9.5.
- One new coordinate-measure helper (existing `check_measure` rejects
  non-positive numbers, which is wrong for a region origin that can
  legitimately be zero or negative — see §9). `check_measure`/
  `check_coordinate` themselves stay general-purpose and untouched; the
  carrier's own rail on top of them is what refuses `UNKNOWN` for this
  specific envelope (§9.2).
- One new `acceptance_criteria.EVIDENCE_KINDS` member.
- One new failure code, its raise site, and its negative test.
- **Fix pass 3 — the evidence payload's interface, not its schema, is
  defined here; ownership is explicitly `EVD-1`'s.** The runtime-evidence
  receipt's field names and what they bind to (`envelope_id`,
  `constraint_id`, an immutable-input hash, target identity, `operation_
  id`, the state hashes, completion states, `proof_kind`) are named in
  §9.5/§9.10 so `T4`'s side of the interface is stated; the hash algorithm,
  canonical scope, and the live operation-receipt binding remain
  `EVD-1`'s to design in full, not decided here. **Scope correction, this
  pass:** `EVD-1` blocks `T5`'s canonical live run and `T2`'s
  LIVE-EVIDENCE implementation specifically — it does not block `T4`'s own
  schema implementation (unchanged from revision 2) and, this pass makes
  explicit, does not block `T2` drafting its own entry-point contract
  either (§9.10).
- Negatives-first test coverage for every new rail, in the established
  pattern, including the pre-scan/reconcile domain-exclusion pipeline's
  no-dual-fail guarantee.

## 5. Non-goals

- **No wiring into `T1`'s adapter or `T2`'s entry point.** T4 has no
  dependencies and feeds both (`T4.md:38-41`); consuming the new vocabulary
  in `run_consumer_flow.py` or a live adapter is `T1`/`T2`'s own contract.
- **No editing `wf.core.world_request.v1` or `wf.core.acceptance_criteria.v1`
  required-field sets, or their top-level `*_ALLOWED` tuples.** Both stay
  byte-for-byte immutable per Q4's versioning requirement
  (`.../decisions.md:135-137`) — and, after this revision, this is now
  *structurally guaranteed* rather than merely intended, because the new
  top-level fields live on the envelope, never on either v1 document.
- **No scanning free-text fields** (`notes`, `detail`, `significance`) for
  excluded-domain keywords — see §8 Fork 2.
- **No adding quest/combat/reward/faction/tactical-behavior/streaming as
  legal values anywhere.** Recognized only so they can be refused with the
  new code, never accepted.
- **No wiring a live human-resolution workflow for `biome_class`/
  `relief_class == "unknown"`.** §9 makes this an outright refusal for the
  first carrier because nothing downstream can act on a "resolve me later"
  promise yet (§5's own first bullet). A future carrier that has such a
  workflow may relax this — that is new scope, not this contract's.
- **No preview/draft envelope shape, this revision.** §9.2 concludes —
  rather than leaves ambiguous — that the first carrier has no preview mode
  of its own yet; the existing `run_consumer_flow.py --preview` flow already
  covers the pre-envelope layer (see §9.2's grounding). Inventing an unused
  preview envelope shape now would be exactly the kind of ungrounded
  abstraction §9.2's anchor-mode reasoning already refuses elsewhere in this
  document.
- **No implementing `EVD-1`/the evidence-digest sub-contract here.** §9.10
  names it as a new prerequisite and states what it must own; drafting or
  implementing it is that contract's own future work, not this pass's.
  **Fix pass 3:** `EVD-1` gates `T5`'s canonical live run and `T2`'s
  LIVE-EVIDENCE implementation, not `T4`'s own implementation and not `T2`
  drafting its entry-point contract — see §9.10.
- **No implementing or enforcing `T1`'s spatial-boundedness proof here**
  (fix pass 3, new §9.12). This document states, as an explicit,
  unimplemented-today requirement on `T1`'s own future contract, that `T1`
  must not claim a mutation stayed inside `bounded_region` without
  independently proving the mutated transforms lie within the resolved
  planar region — but T4 validates only the request, before any mutation
  has happened, and has no access to a post-mutation transform to check.
  Designing or implementing that proof is `T1`'s own future work.
- **No implementation.** This document is the contract; execution requires
  its own authorization per the map's standing constraint.

## 6. Blast-radius summary

New module, purely additive — narrower than the original draft, because
`revision_policy.py` is no longer touched or even imported:

- `tools/wfcore/contracts/__init__.py` — add one helper (`check_coordinate`)
  and one name to `__all__` (`contracts/__init__.py:60-82`).
- `tools/wfcore/contracts/acceptance_criteria.py` — add one member to
  `EVIDENCE_KINDS` (`acceptance_criteria.py:55-61`). Adding an enum
  **member** is non-breaking: `check_enum` tests membership, not
  exhaustiveness, so no existing valid `acceptance_criteria` document stops
  validating.
- `tools/pipeline/failure_codes.py` — add one constant in a new
  `-- closed carrier request vocabulary (1296-1299) --` section, mirroring
  the existing per-topic section-comment convention.
- **No existing file's required-field set, `*_ALLOWED` tuple, or
  `schema_version` changes.** `world_request.py`, `acceptance_criteria.py`
  (beyond the one `EVIDENCE_KINDS` append), and `revision_policy.py` are all
  byte-for-byte untouched. `AFFORDANCE_KINDS` and `LANDMARK_ROLES`
  (`world_request.py:50-74`), read live by `tools/consumers/adapter.py:84`,
  stay untouched; the carrier vocabulary's narrower subsets live in the new
  module.
- New files only: the carrier-vocabulary envelope module and its test
  module (§10 task graph). Revision 2's fixes (closed-field rails,
  region-resolved rail) and fix pass 3's fixes (evidence moved out of both
  nested documents, `subject_is_target_map_path`) all land inside these
  same two new files — no additional file is touched.
- `docs/contracts/wfcore_evidence_digest_contract.md` / `EVD-1` (§9.10) is
  **not** created or touched by this pass — it is named as a prerequisite
  for `T1`/`T2`'s future implementation of live evidence handling, and for
  `T5`'s canonical live run (fix pass 3 scope correction, §9.10), not part
  of this document's own blast radius.

No generated artifact, fixture, golden file, or cross-language seam is
touched. `tools/pipeline/validate_failure_codes.py` is the only existing gate
this mission must keep green.

## 7. Contracts / seams involved

| Concept | Owner today | What T4 adds |
|---|---|---|
| target map | `world_request.subject` (nested, caller-owned, no default, validated only as a non-empty string — `world_request.py:136-137`) | reused as-is, plus (fix pass 3) a new carrier-only `subject_is_target_map_path` rail requiring a `/Game/...` UE map-package-path shape, not merely a non-empty string — §9.11. Still exactly one target-map pointer in the whole envelope; every spatial field below stays defined relative to it. `T1` is required, not this document's own validators, to prove the map it actually loads/mutates at runtime matches this value — §9.11 |
| bounded region | *nothing today* | new required **envelope-level** object, anchored to a live UE actor or explicit transform exactly as `scene_survey_far_side._verify_anchor` already does, **closed** to unknown fields, and — since revision 2 — required to be fully resolved (no `UNKNOWN` offsets/extent) on this executable envelope — see §9.2 |
| biome | *nothing today* | new required `environment.biome_class`, closed vocab, nested **inside** the v1 `world_request.environment` object (legal to add — that nesting level has no `check_no_unknown` gate at v1, §2 — but carrier-closed at the carrier layer, §9.0) |
| landform | `world_request.environment.relief_class` (`RELIEF_CLASSES`) | reused as-is, plus a carrier-only rail forbidding `UNKNOWN` (§9) |
| placement/POI intent | `world_request.semantic_landmarks` + `LANDMARK_ROLES` | reused as-is, no new roles needed |
| one interaction objective | *nothing today* | new required **envelope-level** `interaction_objective`, naming exactly one affordance **and** a `constraint_id` binding into the nested `acceptance_criteria`, **closed** to unknown fields (§9.3) |
| runtime/save-reload evidence | `acceptance_criteria.EVIDENCE_KINDS` | new `runtime_save_reload_observation` member, plus a structural cardinality rail (exactly one matching `evaluation_requirements[]` entry, §9.5). **Fix pass 3:** the evidence *content* (hashes, completion states, `proof_kind`, `operation_id`) is removed from both nested documents and the envelope — it lives in a separate runtime-evidence/receipt record, validated later by a validator this document names the interface for but does not implement, owned by a new prerequisite, `EVD-1` (§9.5, §9.10) |
| spatial boundedness of a mutation | *nothing today; path-based mutation-bound enforcement only (`transaction/delta.py:325-371`)* | *nothing T4 implements* — fix pass 3 adds a required, unimplemented-today note (§9.12) that `T1`'s future contract must independently prove mutated transforms lie inside `bounded_region`'s resolved planar extent before claiming spatial boundedness; existing path-based mutation-bound enforcement does not establish this |
| excluded domains | *nothing today* | new recognized-but-refused term lists + `WF1296`, via a pre-scan/reconcile pipeline that never dual-fails |
| revision policy | `wf.core.revision_policy.v1`, standalone | **not part of the envelope** — see §9's resolution of item 5 |

## 8. Human decisions required

**Fork 1 of 2 — where the carrier vocabulary lives.**

- **Option A (recommended, now the only structurally valid choice): a new
  sibling contract module**, `tools/wfcore/contracts/carrier_vocabulary.py`,
  defining `RT_CARRIER_VOCABULARY = "wf.core.carrier_vocabulary.v1"` and an
  **envelope** object that *nests* one unmodified `wf.core.world_request.v1`
  document and one unmodified `wf.core.acceptance_criteria.v1` document,
  validating each via its own unmodified v1 validator
  (`world_request.validate_world_request`,
  `acceptance_criteria.validate_acceptance_criteria`), then layers the new
  envelope-level fields and rails on top. This revision demonstrates why
  Option A is not merely preferred but *required*: §2's strict-mode analysis
  shows the alternative (folding new top-level fields directly onto
  `world_request` while it still declares `wf.core.world_request.v1`) cannot
  pass `check_no_unknown` in strict mode. There is no longer a live fork
  here in practice, but the reasoning is kept for the record.
- **Option B: bump `world_request`'s `schema_version` handling to accept a
  second value** — rejected for the same immutability reason as before, and
  now additionally for the structural reason above: even Option B would need
  an envelope-shaped nesting the moment `interaction_objective` needed to
  cross-reference `acceptance_criteria`'s constraint set, so it does not
  actually avoid the restructuring this revision requires.

**Lean: Option A**, now load-bearing rather than merely preferred.

**Fork 2 of 2 — how domain exclusion is detected.**

- **Option A (recommended, decided): structural recognition only**, via a
  **pre-scan/reconcile pipeline** (§9) that classifies excluded terms
  *before* delegating to the v1 validators, so a term that is *also*
  out-of-vocabulary at v1 (e.g. `quest_giver`, which is not in
  `LANDMARK_ROLES` at all) fails **once**, with `WF1296`, never twice. This
  revision replaces the original draft's simple "check after validating"
  sketch — which would have dual-failed — with a concrete three-step
  pipeline; see §9.
- **Option B: keyword-scan free text too** — still declined, same
  reasoning as before (§5).

**Lean: Option A**, already written into §9/§10 below as the decided shape.
The tension that `patrol_route`/`flanking_route`/`chokepoint`/`spawn_area`
are simultaneously legal at `world_request.v1` and excluded at the carrier
layer for the *same literal string* is intentional and not a bug: v1 serves
consumers outside the first carrier who may have legitimate non-tactical
uses for those kind names. The carrier vocabulary narrows what the first
live carrier will accept; it does not narrow what `world_request` means
everywhere. **This tension is exactly why the pre-scan/reconcile pipeline in
§9 must not assume a domain hit always coincides with a v1 failure** —
sometimes it does (`quest_giver`), sometimes it doesn't
(`patrol_route`), and the pipeline must produce exactly one `WF1296` failure
in both cases, never zero and never two.

## 9. Implementation strategy

### 9.0 The envelope, at a glance

```
wf.core.carrier_vocabulary.v1  (envelope — THIS module, new)
│
├─ envelope_id            (str, caller-owned)
├─ bounded_region          (object, caller-owned, NEW — §9.2)
├─ interaction_objective   (object, caller-owned, NEW — §9.3)
│
├─ world_request  ─────────────────────────────────────────────┐
│    UNMODIFIED wf.core.world_request.v1 document               │
│    validated by world_request.validate_world_request()        │
│    verbatim (only pre-scanned/reconciled per §9.4, never       │
│    edited) — includes environment.biome_class as a NEW         │
│    sub-field (§9.1), legal because `environment` has no        │
│    check_no_unknown gate (§2). `subject` is carrier-tightened   │
│    by a rail, not a new field (§9.11, fix pass 3)              │
└──────────────────────────────────────────────────────────────┘
│
└─ acceptance_criteria ─────────────────────────────────────────┐
     GENUINELY, FULLY UNMODIFIED wf.core.acceptance_criteria.v1  │
     document — fix pass 3 removes the per-evaluation `evidence` │
     sub-object revision 2 had added here; nothing about this    │
     document's shape differs from a plain v1 consumer's own,    │
     validated by acceptance_criteria.validate_acceptance_       │
     criteria() verbatim, no exceptions (§9.5)                   │
     ─────────────────────────────────────────────────────────┘
```

Both nested documents keep declaring their own `schema_version`
(`wf.core.world_request.v1` / `wf.core.acceptance_criteria.v1`) and keep
passing their own unmodified strict validators when handed to them directly
— that is the whole point of nesting rather than folding. `revision_policy`
is deliberately absent from this diagram; see §9.6.

**Field list (concrete, typed):**

```
envelope_id: str                                  # caller-owned, envelope's own identity
schema_version: "wf.core.carrier_vocabulary.v1"    # envelope's own identity, distinct from
                                                    # the two nested documents' own schema_version
world_request: <full wf.core.world_request.v1 document, caller-owned>
acceptance_criteria: <full wf.core.acceptance_criteria.v1 document, caller-owned>
bounded_region: <object, caller-owned, NEW>
interaction_objective: <object, caller-owned, NEW>
```

```python
CARRIER_ENVELOPE_REQUIRED = (
    "envelope_id", "world_request", "acceptance_criteria",
    "bounded_region", "interaction_objective", "schema_version",
)
CARRIER_ENVELOPE_ALLOWED = CARRIER_ENVELOPE_REQUIRED + (
    "created_by", "created_at", "report_type", "meta", "notes",
)
CARRIER_ENVELOPE_CALLER_OWNED_FIELDS = (
    "envelope_id", "world_request", "acceptance_criteria",
    "bounded_region", "interaction_objective",
)
```

`check_no_unknown` **is** applied at this top envelope level (mirroring
every existing top-level document — `WORLD_REQUEST_ALLOWED`,
`ACCEPTANCE_CRITERIA_ALLOWED`, `REVISION_POLICY_ALLOWED` are all gated the
same way).

**Reversed this revision — the new nested objects are also closed.**
Revision 1 left `bounded_region`/`interaction_objective` open to unknown
fields, reasoning that this "mirrors" the house convention that nested
objects like `landmark`/`affordance`/`population`/`environment`/`rollback`
use `check_required` + typed field checks only, never a closed-field gate
(true, and still true of those v1 fields — verified across
`world_request.py`, `acceptance_criteria.py`, `revision_policy.py`, none of
their nested-object rails call `check_no_unknown`). The re-review correctly
identified that reasoning as backwards: that convention exists because those
are v1's own *long-standing* fields, evolved under v1's own versioning
discipline — it is not a general rule that "nested" implies "open," and it
does not obligate a **brand-new, carrier-specific** boundary to inherit the
same permissiveness. Left as revision 1 specified it, `interaction_objective.
quest_id` (or any other unsupported field) would be silently accepted and
ignored — directly contradicting this contract's own closed-vocabulary
premise (Q4: "Unsupported/unrecognized request terms get a domain-specific
failure code — never a silently dropped field"). A carrier whose own new
surface is not closed is not actually closed.

**Three** nesting points gain a carrier-owned closed-field rail
(`bounded_region`, `interaction_objective`, `world_request.environment`),
each reusing `C.CORE_WORLD_REQUEST_INVALID` (WF1208) — the same code the
biome/relief-unknown rail (§9.1) already reuses for a carrier-only
restriction layered on top of a permissive v1 default. **Fix pass 3
correction:** revision 2 counted a fourth nesting point here — the targeted
`evaluation_requirements[]` entry and its `evidence` sub-object, housed
inside `validate_carrier_acceptance_pairing` (§9.5). That fourth point is
removed this pass, not merely re-homed: the `evidence` sub-object it
existed to close no longer lives inside `acceptance_criteria` at all (§9.5),
and the targeted `evaluation_requirements[]` entry itself carries no new
carrier-owned field any more — it is exactly as v1 already shaped it, so
per this document's own corrected standard (below, unchanged since revision
2) it stays exactly as open as v1 made it. There is nothing new on that
entry for a carrier-owned rail to close:

```python
BOUNDED_REGION_ALLOWED = BOUNDED_REGION_REQUIRED  # no optional fields (§9.2)
INTERACTION_OBJECTIVE_ALLOWED = INTERACTION_OBJECTIVE_REQUIRED  # no optional fields (§9.3)
CARRIER_ENVIRONMENT_ALLOWED = (
    "extent_m2", "relief_class", "lighting_condition", "resolution_owner",
    "biome_class",
)  # the four v1 fields actually read by world_request._rail_environment
   # (world_request.py:91,340-359) plus the carrier's own biome_class (§9.1)
```

**Fix pass 3 removed** `CARRIER_EVALUATION_REQUIREMENT_ALLOWED` and
`EVALUATION_EVIDENCE_ALLOWED`, which revision 2 defined here to close the
now-removed `evidence` sub-object. Neither construct has a reason to exist
in `carrier_vocabulary.py` any more; the fields they used to name moved to
the receipt interface described in §9.5/§9.10, which this module references
but does not itself validate.

Note what is deliberately **not** reversed: `environment`'s *v1-owned*
fields (`extent_m2`, `relief_class`, `lighting_condition`,
`resolution_owner`) stay exactly as permissive as v1 already made them —
`CARRIER_ENVIRONMENT_ALLOWED` is a superset that adds only the carrier's
own new `biome_class` sub-field, never narrowing what v1 itself already
permits. Closing v1's own nested objects outright would be the same
"obligation inherited from a different owner" mistake in the other
direction, and would break `world_request.validate_world_request` called
directly on the nested document (§14's strict-nesting proof) the moment a
caller used a v1-legal `environment` field the carrier rail didn't know
about yet. The same reasoning is why `evaluation_requirements[]` entries
get no carrier-owned closed-field rail at all this pass: with no new field
of the carrier's own to protect, adding one would be exactly this same
mistake.

### 9.1 `environment.biome_class` (nested inside `world_request`, unchanged from original draft)

```
environment.biome_class (existing environment object, new sub-field):
    closed vocab BIOME_CLASSES = (
        "temperate_forest", "grassland", "desert", "wetland", "coastal",
        UNKNOWN,
    )
    Starter set, expected to grow the way LOCOMOTION_MODES grew "jump"
    (consumer_profile.py:88-101) once a real caller's biome has no honest
    member — not pre-guessed now.
```

**New carrier-only rail — `biome_class`/`relief_class` may never be
`UNKNOWN` on an executable first-carrier request (fix for item 4's second
half).** `RELIEF_CLASSES` already includes `UNKNOWN` at v1
(`world_request.py:81`), and v1's own `_rail_environment` already *permits*
an `UNKNOWN` environment field as long as `resolution_owner` names who
resolves it (`world_request.py:347-359`). That permission is correct for
`world_request.v1` in general — it serves every consumer, including ones
with a real resolution workflow. It is **wrong for this carrier specifically
**, because (§5) nothing downstream of the first carrier's live execution
path is wired to act on a "resolve me later" promise yet — `resolution_owner`
would be a name with nowhere to send it. The carrier module therefore adds
its own rail, `_rail_environment_known`, layered *on top of* v1's own
(unmodified) permission:

```python
def _rail_environment_known(world_request_obj, code):
    env = world_request_obj.get("environment") if isinstance(world_request_obj, dict) else {}
    out = []
    out += check_required(env, ("biome_class",), code, "cv::world_request.environment.")
    out += check_enum(env, "biome_class", BIOME_CLASSES, code, "cv::world_request.environment.")
    # Closed-field rail (fix for defect 1) -- v1's own environment object has
    # no check_no_unknown gate (§2), so the carrier adds its own, superset of
    # v1's permitted fields plus biome_class (§9.0).
    out += check_no_unknown(env, CARRIER_ENVIRONMENT_ALLOWED, code,
                            "cv::world_request.environment.")
    unknown_fields = sorted(f for f in ("biome_class", "relief_class") if env.get(f) == UNKNOWN)
    ok = not unknown_fields
    out.append(("cv::environment.biome_and_relief_known_for_executable_carrier", ok,
                "environment field(s) {} are declared unknown; v1 permits this with a "
                "resolution_owner, but this carrier has no live resolution path wired to "
                "act on that promise yet (§5), so an unknown here is refused outright "
                "rather than silently treated as 'no constraint'".format(unknown_fields),
                None if ok else code))
    return out
```

**Failure code:** `C.CORE_WORLD_REQUEST_INVALID` (existing, WF1208) — reused
as the envelope's own generic code (§9.7). This rail does not fire a new
code; the value being `UNKNOWN` on an executable carrier request is, at
this layer, simply an invalid request.

### 9.2 `bounded_region` (envelope-level, new — fix for item 4)

Grounded entirely in code that already exists and already resolves/verifies
a spatial anchor against a live UE level: `scene_survey_far_side.py:2594-
2631`'s `_verify_anchor`. **No third "bare world origin, no anchor" mode is
invented** — nothing in this codebase already resolves what "the map's
origin" means as a concept, and inventing one here would be exactly the kind
of unverified abstraction item 4 was raised to eliminate. Every
`bounded_region` must anchor to something UE can independently verify.

```
bounded_region (object, required, envelope-level, new):
    anchor_mode: enum ANCHOR_MODES = ("explicit_transform", "actor_object_path")
        # identical vocabulary to scene_survey_far_side._verify_anchor's
        # own anchor_mode (scene_survey_far_side.py:2600-2631) — reused,
        # not reinvented.
    anchor_location_cm: [x, y, z]     # REQUIRED iff anchor_mode == "explicit_transform".
        # Three finite int/float components -- NOT UNKNOWN-able component-wise:
        # an anchor a caller chooses to declare explicitly is, by definition,
        # known. Mirrors _finite_vec3's rejection of non-finite values
        # (scene_survey_far_side.py:2603).
    anchor_object_path: str            # REQUIRED iff anchor_mode == "actor_object_path";
        # non-empty. Resolved among the placed actors of world_request.subject's
        # OWN level -- never a different level than the one the request targets
        # (scene_survey_far_side.py:2618-2620's own resolution scope). This is
        # how "binding to the specific target map" is satisfied WITHOUT a
        # second target-map field: there is exactly one, world_request.subject,
        # and every anchor/offset in bounded_region is defined relative to it.
    origin_x_cm: coordinate    # OFFSET from the resolved anchor, in cm.
    origin_y_cm: coordinate    # check_coordinate: any real number, or UNKNOWN
                                # at the HELPER level (§9.8's helper stays
                                # general-purpose) -- but see the carrier-only
                                # "must be resolved" rail immediately below:
                                # THIS carrier refuses UNKNOWN outright.
    extent_x_cm: measure       # check_measure: positive cm, or UNKNOWN at the
    extent_y_cm: measure       # helper level. Zero is rejected for the same
                                # reason check_measure rejects it everywhere
                                # else (contracts/__init__.py:218-237) -- and,
                                # per the same carrier-only rail, UNKNOWN is
                                # ALSO refused for this carrier specifically.
    vertical_scope: enum VERTICAL_SCOPES = ("planar_only",)
        # REQUIRED, single legal value in v1. States OUT LOUD, not by omission,
        # that bounded_region bounds X/Y only and makes no claim about Z:
        # whether WorldForge respects an existing floor/ceiling, or may build
        # vertically unbounded structures, is undecided policy -- pretending
        # to bound Z with a field nobody has designed the semantics for would
        # be worse than the honest single-value enum. Same growth pattern as
        # BIOME_CLASSES/LOCOMOTION_MODES: a future carrier that supports real
        # vertical bounding adds a second legal value, not a v2 bump.
```

```python
BOUNDED_REGION_REQUIRED = (
    "anchor_mode", "origin_x_cm", "origin_y_cm",
    "extent_x_cm", "extent_y_cm", "vertical_scope",
)
BOUNDED_REGION_ALLOWED = BOUNDED_REGION_REQUIRED + (
    "anchor_location_cm", "anchor_object_path",
)  # the two conditionally-required anchor fields (below) are allowed but not
   # always required -- BOUNDED_REGION_REQUIRED alone would wrongly reject
   # whichever half the conditional rail needs present
```

Conditional rail (`_rail_bounded_region_anchor`), mirroring
`world_request._rail_revision_shape`'s existing conditional-requirement
pattern (`world_request.py:154-188`) exactly:

- `check_no_unknown(region, BOUNDED_REGION_ALLOWED, code, "cv::bounded_region.")`
  runs first — the closed-field rail (fix for defect 1). §9.0.
- `anchor_mode == "explicit_transform"` → `anchor_location_cm` REQUIRED, a
  3-element list/tuple of finite int/float; `anchor_object_path` must be
  absent (the two halves disagreeing — an explicit transform that *also*
  names an actor path — is the same class of contradiction
  `_rail_revision_shape` already polices for `request_kind`/
  `revision_target`).
- `anchor_mode == "actor_object_path"` → `anchor_object_path` REQUIRED,
  non-empty string; `anchor_location_cm` must be absent.

**New this revision — `_rail_bounded_region_resolved`, fix for defect 2.**
`check_coordinate`/`check_measure` (§9.8, unchanged, general-purpose) both
permit `UNKNOWN` at the helper level, because for other consumers of those
helpers an unresolved measure is a legitimately sayable thing. It is
**wrong for this carrier specifically**: nothing downstream of the first
carrier resolves a `bounded_region` offset or extent that arrives as
`UNKNOWN` — there is no resolution workflow anywhere in this codebase for
it, and `T1`'s adapter cannot derive a legal mutation bound from an
unresolved region (an "executable" request with an unknown extent is not
actually executable). This is the exact same shape of carrier-only
tightening as §9.1's `biome_class`/`relief_class` refusal — a rail layered
*on top of* a permissive general-purpose helper, not a change to the
helper:

```python
def _rail_bounded_region_resolved(region, code):
    unresolved = sorted(f for f in
        ("origin_x_cm", "origin_y_cm", "extent_x_cm", "extent_y_cm")
        if region.get(f) == UNKNOWN)
    ok = not unresolved
    return [("cv::bounded_region.offsets_and_extent_resolved", ok,
             "bounded_region field(s) {} are declared unknown; this carrier "
             "represents an EXECUTABLE request and has no resolution "
             "workflow that could ever clear an unknown offset or extent, "
             "so an unresolved region is refused outright rather than "
             "silently accepted as a placeholder".format(unresolved),
             None if ok else code)]
```

**Why this carrier has no preview/draft envelope, this revision (also fix
for defect 2).** The original draft left `origin_x_cm`/`origin_y_cm`/
`extent_x_cm`/`extent_y_cm` as "or `UNKNOWN`" apparently to leave room for a
preview/draft use case, but named no resolution owner and no downstream
consumer that could ever clear it — an ambiguity, not a design. Investigated
this revision: `tools/pipeline/run_consumer_flow.py`'s existing `--preview`
flow (`docs/contracts/wfcore_caller_mission_brief.md`, landed `a511aafb`)
already covers the pre-envelope layer — it builds and validates a plain
`wf.core.world_request.v1`/`wf.core.acceptance_criteria.v1` pair directly
(`run_consumer_flow.py:931-1057`, `run_preview`), reports through its own
distinct `wf.core.consumer_preview_report.v1` report type
(`run_consumer_flow.py:134`), performs no observation pass at all
(`PREVIEW_NOT_OBSERVED`, `run_consumer_flow.py:521-522`), and hard-refuses a
`satisfied` preview acceptance verdict with a non-zero exit
(`run_consumer_flow.py:1235-1236`) — verified by reading the module this
session. **The carrier envelope (`bounded_region`/`interaction_objective`)
does not exist anywhere in that code path**, and per §5's own non-goal ("No
wiring into `T1`'s adapter or `T2`'s entry point"), it is not wired in by
this contract either. There is therefore no live caller today that needs a
`bounded_region` with an unresolved offset/extent — the preview need this
was hedging against is already served, one layer down, by a flow that never
touches this envelope at all. Conclusion, not left open: **the first
carrier has no preview mode of its own yet.** Inventing a distinct,
separately-versioned preview envelope shape now, with nothing that would
ever submit one, would be exactly the kind of unverified, unused
abstraction §9.2's anchor-mode design already refuses elsewhere in this
document (no invented "bare world origin" mode). If a future carrier
revision wires the envelope itself into a preview flow, that flow gets its
own explicitly `executable: false`-discriminated envelope shape at that
point, grounded in a real caller that needs it — new scope, not guessed
here.

**Failure code:** `C.CORE_WORLD_REQUEST_INVALID` (existing, WF1208) — the
envelope's reused generic code (§9.7), for both the closed-field rail and
the resolved-offsets rail.

### 9.3 `interaction_objective` (envelope-level, new — fix for item 2)

```
interaction_objective (object, required, envelope-level, new):
    affordance_id: str
        # must resolve to exactly one entry in the nested world_request's
        # gameplay_affordances with required == True and
        # affordance_kind == "interaction_surface"
    constraint_id: str
        # NEW this revision -- the field the save/reload rail was missing.
        # Must "resolve uniquely" against the nested acceptance_criteria,
        # defined concretely as:
        #   (a) EXISTS: exactly one entry in acceptance_criteria.constraints
        #       carries constraint_id equal to this value. Uniqueness itself
        #       is NOT re-derived here -- constraints.validate_constraint_set
        #       already guarantees constraint_ids_unique across the whole set
        #       (constraints.py:304-311, verified this session), and
        #       acceptance_criteria's own validator already folds that check
        #       in (acceptance_criteria.py:109-110). So this half of the rail
        #       is an EXISTENCE check only.
        #   (b) BLOCKS: this same constraint_id appears verbatim in
        #       acceptance_criteria.must_block_ids.
    detail: str
```

```python
INTERACTION_OBJECTIVE_REQUIRED = ("affordance_id", "constraint_id", "detail")
INTERACTION_OBJECTIVE_ALLOWED = INTERACTION_OBJECTIVE_REQUIRED  # no optional
   # fields; closed outright (fix for defect 1, §9.0)
```

Rail `_rail_interaction_objective(envelope_obj, code)`, granular per-cause
checks (matching the house style of separately-named checks over one
combined boolean, e.g. `revision_names_target`/`revision_names_policy`):

- `interaction_objective.no_unknown_fields` — `check_no_unknown(io,
  INTERACTION_OBJECTIVE_ALLOWED, code, "cv::interaction_objective.")`. New
  this revision, runs first — the closed-field rail (fix for defect 1).
- `interaction_objective.affordance_id_resolves_exactly_once` — exactly one
  `gameplay_affordances[]` entry carries this `affordance_id`.
- `interaction_objective.resolved_affordance_is_required` — that entry's
  `required == True`.
- `interaction_objective.resolved_affordance_is_interaction_surface` — that
  entry's `affordance_kind == "interaction_surface"`.
- `interaction_objective.constraint_id_exists_in_acceptance_criteria` —
  §9.3(a) above.
- `interaction_objective.constraint_id_is_must_block` — §9.3(b) above.

This rail runs inside `validate_carrier_world_request` (§9.7), not the joint
pairing function, because everything it checks is *structural* — ID
existence and cardinality, resolvable the moment the envelope is submitted,
before any generation has happened. The envelope's nesting (§9.0) is what
makes this possible in one function: `interaction_objective` cross-references
into `acceptance_criteria`, and the envelope carries both.

**Failure code:** `C.CORE_WORLD_REQUEST_INVALID` (existing, WF1208), same
reused envelope code — `interaction_objective` is an envelope-owned concept
even though one of its checks reaches into the nested `acceptance_criteria`.

### 9.4 Excluded-domain rejection: the pre-scan/reconcile pipeline (fix for item 3)

`EXCLUDED_DOMAIN_TERMS` is unchanged from the original draft, **except** the
`revision_policy.permitted_mutations`/`prohibited_mutations` surface is
removed — see §9.6:

```python
EXCLUDED_DOMAIN_TERMS = {
    "quest":             ("quest_marker", "quest_giver", "quest_objective",
                           "quest_trigger"),
    "combat":            ("enemy_encounter", "combat_area", "damage_volume",
                           "hostile_spawn"),
    "reward":            ("loot_drop", "reward_cache", "loot_spawn"),
    "faction":           ("faction_territory", "faction_marker",
                           "reputation_zone"),
    "tactical_behavior": ("patrol_route", "flanking_route", "chokepoint",
                           "spawn_area"),
    "streaming":         ("level_stream_volume", "sublevel_stream",
                           "world_partition_cell", "streaming_source"),
}
```

checked against exactly two structural surfaces of the **nested**
`world_request`: `semantic_landmarks[].role` and
`gameplay_affordances[].affordance_kind`.

**The problem this revision fixes:** `quest_giver` is not a legal
`LANDMARK_ROLES` member at v1 at all (`world_request.py:50-60`), so v1's own
`check_enum` would *already* fail it with the generic code
(`CORE_WORLD_REQUEST_INVALID`). Naively also appending a `WF1296` check for
the same entry produces two failures for one cause — exactly the dual-fail
§8 Fork 2 and the contract's own stated intent forbid. Conversely,
`patrol_route` **is** a legal `AFFORDANCE_KINDS` member at v1
(`world_request.py:63-74`), so v1's own check would *pass* it — here the
fix is the opposite problem: nothing about v1 will ever produce a failure to
fold in, so `WF1296` must fire entirely on its own. Both cases must resolve
to **exactly one** failing check.

**Concrete pipeline, run inside `validate_carrier_world_request`, positioned
immediately after `check_is_object` gates the envelope's own shape and
before the nested `world_request`'s checks are folded into the envelope's
check list:**

1. **CLASSIFY.** Walk the nested `world_request`'s `semantic_landmarks[]`
   and `gameplay_affordances[]` *before* calling the v1 delegate. For each
   entry, look up its `role` (landmarks) or `affordance_kind` (affordances)
   against `EXCLUDED_DOMAIN_TERMS`. Record every hit as a tuple
   `(list_name, index, field, domain, value)`.
2. **DELEGATE.** Call `world_request.validate_world_request(nested_wr,
   strict=strict)` **unchanged** — the full, unmodified v1 authority, on the
   untouched nested object. This call is identical to what a plain v1
   consumer would get; nothing about it is aware of exclusion.
3. **RECONCILE.** `check_enum`'s check-name format is
   `"{prefix}{field}_in_vocabulary"` (`contracts/__init__.py:189-194`,
   verified), so for `semantic_landmarks[idx]` the delegate's check is named
   `wr::landmark[idx].role_in_vocabulary`, and for `gameplay_affordances[idx]`
   it is `wr::affordance[idx].affordance_kind_in_vocabulary`. For every
   classified hit from step 1, drop the matching check **if and only if
   it is present and failing** in the delegate's returned list — its cause
   is now covered by step 4. Every other check the delegate produced,
   *including other checks on that same list entry* (e.g.
   `wr::landmark[idx].must_be_reachable_bool`), is kept verbatim. When the
   delegate's check for that entry *passed* (the `patrol_route` case —
   legal at v1), there is nothing to drop; step 4 is the only new failure.
4. **EMIT.** For every classified hit from step 1, append one new check
   named `cv::{list_name}[idx].{field}_excluded_domain`, `ok=False`, failure
   code `C.CORE_REQUEST_DOMAIN_NOT_SUPPORTED` (`WF1296`), whose detail names
   the domain and the offending value verbatim (e.g. `"role='quest_giver'
   belongs to the excluded 'quest' domain — not silently dropped, refused by
   name"`).

**Specified, not yet observed** (see the revision-2 documentation-honesty
note at the top of this document): this pipeline is *designed* to produce
exactly one failing check per excluded term, in both the
"also-illegal-at-v1" case and the "legal-at-v1-but-carrier-excluded" case,
and to leave every unrelated check on the same entry untouched. Nothing has
run it yet — `T4.6`'s `quest_giver`/`patrol_route` fixtures (§10/§11) are
what turns this from a design claim into a checked one, and until they run
and pass, this pipeline's no-dual-fail behavior remains a specification.

### 9.5 Runtime/save-reload evidence — a structural requirement only; content lives elsewhere (fix pass 3, P1 defect 1)

**The problem, verified this pass.** Revision 2 put `operation_id`, three
state hashes, `reload_verified_at`, the completion-state pair, and
`proof_kind` inside a new `evidence` sub-object of the targeted
`evaluation_requirements[]` entry, itself inside the nested
`acceptance_criteria` document. Reachable through the same
no-`check_no_unknown`-at-v1 loophole `environment.biome_class` legitimately
uses (§2, §9.1) — but that loophole justifies adding a carrier-only
*declaration* field to a v1-permissive object, not smuggling *post-hoc
evidence* into a document this contract, in the same breath, calls
"unmodified" everywhere else (§1, §4, §5, §9.0, §14). Eight of that
document's fields would have no real value until *after* the interaction
objective was executed and saved/reloaded — a declared acceptance
criteria document that mutates after execution is not a declaration any
more. This codebase already has a working precedent for keeping the two
apart, confirmed this pass by reading it in full:
`tools/wfcore/acceptance/evaluate.py`'s `evaluate_acceptance(criteria,
delta, evidence, applied_at=None, result_id=None)` (`evaluate.py:444-446`)
takes the caller-owned `acceptance_criteria` record and a **separately
supplied** `evidence` argument, with its own schema — `EVIDENCE_REQUIRED =
("evidence_id", "constraint_id", "operation_id", "observed_at",
"observation_kind", "reload_backed", "supports", "evidence_refs",
"detail")` (`evaluate.py:155-157`) — as two distinct objects. Notably, that
existing schema already has a `reload_backed`/`observation_kind` concept
(`OBS_RELOADED = "reload_backed_observation"`, `evaluate.py:116`) covering
exactly the same "was this a save/reload-backed observation" question this
carrier's evidence exists to answer — independent confirmation that a
save/reload-backed evidence *record*, kept separate from the criteria it
proves, is an established shape in this codebase, not a new idea.

**The fix.** Every evidence-content field is removed from both nested
documents and from the envelope. `acceptance_criteria` is now genuinely,
fully unmodified — every `evaluation_requirements[]` entry stays exactly
v1's own shape:

```
evaluation_requirements[] entry (existing, v1, genuinely unmodified — no new fields):
    constraint_id: <matches interaction_objective.constraint_id for the targeted entry>
    evidence_kind: "runtime_save_reload_observation"   # new EVIDENCE_KINDS member (§4)
    evaluator: str     # optional, v1-owned, unchanged
    detail: str        # optional, v1-owned, unchanged
    notes: str          # optional, v1-owned, unchanged
```

`validate_carrier_acceptance_pairing(envelope_obj)` keeps exactly **one**
rail, down from revision 2's five:

1. **Cardinality.** Exactly one `evaluation_requirements[]` entry has
   `constraint_id == interaction_objective.constraint_id` **and**
   `evidence_kind == "runtime_save_reload_observation"`. (Not "at least
   one" — see §20's open-question note on this lean, unchanged.) This is a
   *structural* check on the declared criteria alone — it needs no
   evidence to exist yet, which is exactly why it is the one rail that
   still belongs to `T4` and can run at submission time. **Failure code:**
   `C.CORE_ACCEPTANCE_CRITERIA_INVALID` (WF1210), unchanged from revision 2.

**Fix pass 3 removed, not relocated within this function:** the
closed-field rail on the `evidence` sub-object (there is no more `evidence`
sub-object to close — §9.0), the eight-required-fields check, the
`reload_state_hash == post_state_hash` round-trip check, the
`proof_kind`/completion-state consistency check, and the
`_rail_operation_id_bound_to_envelope` structural binding. None of these
checks can run inside `validate_carrier_acceptance_pairing` any more: the
data they inspected no longer lives on the envelope or either nested
document at submission time. They are not deleted from the contract's
scope — they become requirements on a **later validator**, described
below and named in full in §9.10, that this document specifies the
interface for but does not implement.

**Where the evidence payload lives now: a separate runtime-evidence
receipt, not part of `carrier_vocabulary.v1`.** After the interaction
objective has actually been completed and saved/reloaded in a live
session, a separate record — tentatively `wf.core.runtime_evidence_
receipt.v1`, owned in full by the new prerequisite ticket `EVD-1` (§9.10) —
carries the fields revision 2 had put inside `acceptance_criteria`:

```
runtime evidence receipt (SEPARATE record — NOT part of the carrier_vocabulary.v1
envelope, NOT part of either nested v1 document; full schema owned by EVD-1):
    operation_id: str
    pre_state_hash: str
    post_state_hash: str
    reload_state_hash: str
    reload_verified_at: str
    pre_completion_state: enum ("incomplete", "complete")
    post_completion_state: enum ("incomplete", "complete")
    proof_kind: enum ("first_completion", "idempotent_retry")
```

This document does **not** design that schema in full — per the scope note
in §9.10, that is `EVD-1`'s own work. What T4 owns is its *side of the
interface*: the **later validator** (owned by `EVD-1`/`T1`/`T2`, referenced
here, not implemented here) takes **the envelope and the receipt as two
separate objects** — `validate_runtime_evidence(envelope, receipt)`, name
tentative — and must bind:

- **`envelope_id`** — the receipt names which envelope's interaction it is
  evidence for (the direct descendant of revision 2's `operation_id`-
  prefix idea, generalized: the binding is now envelope-to-receipt at the
  object level, not string-prefix at the field level).
- **`constraint_id`**, taken from `interaction_objective.constraint_id` —
  which declared acceptance criterion this receipt is evidence toward,
  so the receipt cannot silently drift to prove a different objective than
  the one the envelope declared.
- **An immutable-input hash** — a hash of the envelope plus its two nested
  documents, taken *as submitted, pre-execution* — so the receipt is bound
  to the exact request that was approved for execution, not merely to an
  `envelope_id` string a caller could reuse against a since-edited request.
- **Target identity** — the resolved map/subject the mutation actually ran
  against, bound back to `world_request.subject` (§9.11's own binding
  requirement on `T1` is the live half of this same tie).
- **Operation ID** — the specific mutation/transaction operation the
  receipt's hashes and completion states describe, carrying forward
  revision 2's original intent (one real execution, not a class of
  executions) now expressed as a binding the later validator checks
  directly against a real operation record, instead of a string-prefix
  convention T4 alone could invent.

The round-trip check (`reload_state_hash == post_state_hash`), the
completion-transition check (`proof_kind`/completion-state consistency —
revision 2's fix for its own defect 4, preserved here as a *requirement on
the later validator*, not dropped), and the eight-field completeness check
all move to that same later validator, unchanged in substance from
revision 2's design — only their home changes. **Failure code(s)** for
that later validator are explicitly undecided here — not this contract's
number to spend, per the same reasoning §9.10 already applies to the hash
algorithm itself.

**Failure codes, this section, after the move.** `C.CORE_ACCEPTANCE_
CRITERIA_INVALID` (WF1210) covers only the one cardinality rail T4 still
owns. `CORE_SINK_RELOAD_MISMATCH` (WF1281) is still deliberately **not**
reused for the future round-trip check: it names a different owner/layer
(the engine-backed mutation sink's own live reload verification,
`failure_codes.py:1385`), and this schema-only contract does not implement
or claim to be that layer, unchanged reasoning from revision 2.

**What this pass leaves open, honestly.** T4 itself specifies nothing
about the receipt's actual content shape or algorithm beyond naming the
four/five bindings above — that is deliberate, per the scope note in
§9.10, and is not a gap this pass silently worked around.

### 9.6 `revision_policy`: resolved, not included (fix for item 5)

The original draft's exclusion logic named
`revision_policy.permitted_mutations`/`prohibited_mutations` as a third
surface to scan, but no function signature anywhere took `revision_policy`
as an argument — a referenced-but-unreachable field. This revision resolves
it by **removing the reference**, not by threading the field through:
`revision_policy.MUTATION_KINDS` (`revision_policy.py:50-64`, quoted in
full in §2) is a closed, structural-verb vocabulary — `add_geometry`,
`remove_geometry`, `move_geometry`, `replace_surface_material`,
`adjust_terrain_height`, `adjust_lighting`, `add_population`,
`remove_population`, `move_population`, `adjust_navigation`,
`adjust_volumes`, `adjust_audio`, `retag_metadata` — and **none of these
thirteen strings appears in any `EXCLUDED_DOMAIN_TERMS` entry**, verified by
reading both lists side by side this session. A rail that checked
`revision_policy.permitted_mutations`/`prohibited_mutations` against
`EXCLUDED_DOMAIN_TERMS` could never fire — it would be dead code dressed as
enforcement, exactly the kind of thing this map exists to catch. Since
`revision_policy` is not one of T4.md's six named vocabulary items either
(target map, bounded region, biome/landform, POI intent, one interaction
objective, runtime/save-reload evidence), it is not nested into the
envelope at all, and `carrier_vocabulary.py` does not import
`revision_policy.py`.

### 9.7 The two validator functions

```python
def validate_carrier_world_request(envelope_obj, strict=True) -> List[Check]:
    """Full structural validity of the envelope EXCEPT runtime evidence.

    code = C.CORE_WORLD_REQUEST_INVALID -- the envelope's own reused generic
    code, for every envelope-level rail (bounded_region -- including its own
    closed-field and offsets-resolved rails -- interaction_objective's
    structural and closed-field checks, the biome/relief-known rail and its
    carrier-environment closed-field check, and -- fix pass 3 defect 2,
    written out in fix pass 4 -- _rail_subject_is_target_map_path, §9.11) as well as the top-level
    check_is_object / check_required / check_no_unknown / schema_version
    gates. Runnable at request-submission time, before any generation has
    happened -- nothing it checks depends on evidence that does not exist
    yet.
    """

def validate_carrier_acceptance_pairing(envelope_obj) -> List[Check]:
    """The save/reload evidence CARDINALITY rail ONLY (§9.5, fix pass 3 --
    narrowed from revision 2's five rails to one).

    code = C.CORE_ACCEPTANCE_CRITERIA_INVALID. Deliberately kept as a SEPARATE
    function from validate_carrier_world_request, even though the envelope
    restructuring (revision 2) means both take the SAME single envelope
    argument rather than two separate top-level documents as the original
    draft's two-argument signature assumed. The split remains meaningful even
    though this function's scope shrank this pass: it is still the one place
    that reasons about the PAIRING between interaction_objective and the
    nested acceptance_criteria's evaluation_requirements[], as distinct from
    each document's own internal shape. Fix pass 3 removed every rail that
    depended on evidence CONTENT (operation_id, the three hashes, the reload
    timestamp, the completion-state pair, proof_kind) because that content no
    longer lives inside the envelope or either nested document at
    submission time -- see §9.5. What remains is purely structural (does a
    matching evaluation_requirements[] entry exist, exactly once) and can
    still run at submission time, before any generation has happened. The
    evidence-content checks are now requirements on a LATER validator this
    document names the interface for but does not implement (§9.5, §9.10).
    """
```

Both are named the same as the original draft; only the argument shape
changed (one envelope instead of two documents), a direct and disclosed
consequence of the envelope restructuring in §9.0. **Fix pass 3:**
`validate_carrier_acceptance_pairing`'s scope shrank to one rail; it is kept
as a separate function anyway, per the reasoning in its own docstring above,
rather than folded into `validate_carrier_world_request` — the pairing
concern is conceptually distinct even when it is currently one check.

### 9.8 New helper (`contracts/__init__.py`) — unchanged from original draft

```python
def check_coordinate(obj, field, code, prefix):
    """A real-valued coordinate: any int/float, or the literal UNKNOWN.

    Unlike check_measure, zero and negative values are legal -- a bounded
    region's offset from its anchor is not a physical magnitude, it is a
    position, and an offset that sits at (0, 0) or south/west of the anchor
    is not a fabrication.
    """
```

Reused three times for `bounded_region.origin_x_cm`/`origin_y_cm` (may be
`UNKNOWN` **at the helper level**) and is explicitly **not** used for
`anchor_location_cm`'s three components, which must be finite (§9.2) — an
anchor a caller chooses to declare explicitly is known by construction.
**Unchanged this revision, deliberately:** this helper and `check_measure`
both stay general-purpose and keep permitting `UNKNOWN` — it is the new
carrier-only `_rail_bounded_region_resolved` (§9.2), layered on top, that
refuses `UNKNOWN` for *this* carrier's four offset/extent fields. A future
carrier with a genuine resolution workflow can reuse these same helpers
without this contract's stricter rail ever needing to change.

### 9.9 Versioning scheme

`wf.core.carrier_vocabulary.v1` is a distinct schema identity from
`wf.core.world_request.v1`/`wf.core.acceptance_criteria.v1`. A document
validates against the carrier vocabulary only when its envelope declares
that identity; nothing about either nested document's own `schema_version`
check changes, so a v1-only consumer's documents are untouched — and, after
this revision, this is enforced by the envelope's own structural boundary,
not merely by convention. When a second objective family (e.g. quest) later
earns its own evidence contract, it ships as `wf.core.carrier_vocabulary.v2`
— a new sibling validator or a new branch in this module — never as an edit
to v1's required set, exactly as `T4.md:33-36` requires.

### 9.10 Evidence-digest ownership: spun out to `EVD-1`, not decided here (fix for defect 3)

**The problem.** Revision 1 left the exact scope and algorithm of
`pre_state_hash`/`post_state_hash`/`reload_state_hash` — and the live
binding of `operation_id` to a real operation receipt — as an "open,
flagged not resolved" item deferred to "`T1`/`T2`'s own execution
contracts." The re-review correctly named this as more than an open
question: it leaves a **shared acceptance seam ownerless**. `T1` (the
adapter) and `T2` (the entry point) both consume these same evidence
fields; if each independently invents its own answer for what gets hashed
and how `operation_id` is verified, they can produce two incompatible
notions of "proven" for the same evidence shape, and nothing would catch
the disagreement until a real run hit it.

**The choice: path (b), a new prerequisite contract, not path (a) (T4 fully
owning the digest/receipt sub-contract itself).** Both were offered;
path (b) is the coherent one given everything else already verified in
this document:

- **Why not path (a).** Fully specifying "a binding from `operation_id` to
  a real operation receipt/journal entry" requires a real operation
  receipt/journal schema to bind against. `T2` owns "persists an operation
  journal before external work starts" (`decisions.md` Q2) and `T1` owns
  "bind every mutation to one target map + one operation ID" (`T1.md`) —
  but as of this revision **neither has a drafted execution contract at
  all** (`map.md`'s Frontier section: only `T3`/`T4` have contracts
  drafted; `T1`/`T2` are "open, blocked"). For T4 to fully specify the
  receipt binding now, it would have to invent T2's not-yet-designed
  operation-journal schema on T2's behalf. That is precisely the
  "referenced-but-unreachable field" failure this same document already
  had to clean up once, in Fix 5 (§9.6): a rail that names a surface no
  function signature can actually reach yet is dead specification dressed
  as enforcement. Repeating that mistake for the evidence-digest rail
  would be worse, not better, than naming the dependency honestly.
- **Why path (b) is coherent.** `T4` is explicitly scoped as request
  vocabulary / schema shape only, with "no wiring into `T1`'s adapter or
  `T2`'s entry point" as a standing non-goal (§5) and Q1's ownership split
  already assigns "operation lifecycle" and "evidence collation" to
  wfcore's adapter/entry-point layer, not the vocabulary layer. A
  dedicated evidence-digest contract that both `T1` and `T2` implement
  against keeps that boundary intact, gives the shared seam exactly one
  owner, and can pin the canonical hash scope concretely against
  `tools/wfcore/models/observed_world.py`'s real identity/measurement
  conventions (which already exist and can be read today) without needing
  `T1`/`T2`'s own contracts to exist first.

**What `EVD-1` (tentative ID) / `docs/contracts/wfcore_evidence_digest_contract.md`
must own, once it exists — expanded this pass with the interface T4's own
side supplies (fix pass 3, P1 defect 1):**

1. **The runtime-evidence receipt's full schema** — the concrete shape
   named informally in §9.5 (`operation_id`, `pre_state_hash`,
   `post_state_hash`, `reload_state_hash`, `reload_verified_at`,
   `pre_completion_state`, `post_completion_state`, `proof_kind`) becomes a
   real, versioned document (`wf.core.runtime_evidence_receipt.v1`,
   tentative) with its own required/allowed tuples, `build_*`/`_example_*`
   pair, and negatives-first tests, per this codebase's own convention
   (§17's Standards axis). **Not designed in full here** — T4 names the
   field list and what each field binds to (below); the schema itself,
   including any additional fields a receipt needs, is `EVD-1`'s own work.
2. **The (envelope, receipt) binding a later validator checks** — this is
   T4's side of the interface, stated concretely so `EVD-1` has something
   to implement against rather than a vague "bind it somehow": a validator
   taking the envelope and the receipt as two separate objects must bind
   **`envelope_id`** (which envelope this receipt is evidence for),
   **`constraint_id`** (from `interaction_objective.constraint_id` — which
   declared criterion the receipt proves), **an immutable-input hash** (a
   hash of the envelope plus its two nested documents, taken as submitted,
   pre-execution — so the receipt is bound to the exact request approved
   for execution, not merely to a reusable `envelope_id` string), **target
   identity** (the resolved map/subject the mutation actually ran against,
   tying back to `world_request.subject` — see §9.11's parallel
   requirement on `T1`), and **operation ID** (the specific
   mutation/transaction operation the receipt's hashes and completion
   states describe).
3. **Canonical state scope** — concretely, what gets hashed: the
   interaction objective's own local state vs. the whole observed-world
   document. Must be decided against `observed_world.py`'s real fields, not
   guessed.
4. **A fixed algorithm** — e.g. SHA-256 over a canonically-serialized form
   — with the canonicalization rule specified precisely enough that two
   independent implementations of `T1`/`T2` produce byte-identical hashes
   for the same observed state.
5. **A real binding from `operation_id` to an operation receipt/journal
   entry** — once `T2`'s operation journal has a concrete schema, this
   contract defines how `operation_id` is looked up against it and what
   makes the lookup authentic (not just string-matching).
6. **Validation logic that recomputes, not trusts** — checks the submitted
   hashes against independently-recomputable values derived from the
   actual observed state and the actual journal entry, rather than
   accepting the caller's claim that two opaque strings are equal.

**What this contract (`T4`) still owns and does not defer, after fix pass
3's move (narrower than revision 2's list):** the `evaluation_
requirements[]` targeting/cardinality rail (§9.5 rail 1, unchanged
structural check), and — new this pass — `subject_is_target_map_path`
(§9.11). **No longer T4's, moved out this pass:** the (former) `evidence`
sub-object's field shape and closed-field rail (that sub-object no longer
exists — §9.0/§9.5), the save/reload round-trip check, and the
completion-transition check (§9.5's old rails 3-5) — these are now
requirements *on the later validator* named above, not on `T4`'s own
`carrier_vocabulary.py`. None of what `T4` still owns requires `EVD-1` to
exist, and `T4`'s own merge gate (§18) does not depend on it.

**Scope correction, this pass — recorded as an explicit user decision.**
Revision 2 hedged `EVD-1` as a blocker on "`T1`/`T2`'s future
implementation" without saying which part of `T2`. That hedge is resolved
now: `EVD-1` is a separate, fourth ticket. It blocks **`T5`'s canonical
live proof run** and **`T2`'s LIVE-EVIDENCE implementation**
specifically — the parts of those tickets that must implement live
hash-recomputation or operation-receipt verification against these
evidence fields; doing so before `EVD-1` exists and is approved would let
each independently guess the canonical scope/algorithm, exactly the
outcome this section exists to prevent. `EVD-1` does **not** block `T4`'s
own schema implementation — unchanged from revision 2, and now stated
without the earlier hedge — and, made explicit this pass, does **not**
block `T2` drafting its own entry-point contract: `T2` may reference the
envelope/receipt split conceptually, describe how its entry point will
call the later validator, and get its own contract reviewed, before
`EVD-1`'s schema exists. `T2` only cannot *implement* live evidence
handling — the code that actually recomputes a hash or looks up an
operation journal entry — until `EVD-1` lands. This document does not
create the `EVD-1` ticket/contract file itself — registering it in the
decision terrain map (`.project-intelligence/decisions/terrain/worldforge-walkaway-mission/`)
is that map's owner's own follow-up action, named here so the dependency is
explicit rather than silently missing.

### 9.11 `subject_is_target_map_path` — the target-map pointer gets a grammar (fix pass 3, P1 defect 2; written out in fix pass 4)

**The problem, verified.** §7 and §9.2 both treat `world_request.subject` as
the single thing every spatial field in `bounded_region` is defined relative
to. v1 validates it only as a required, non-empty string: it is checked by
the same generic `check_str` loop as `request_id`/`consumer_id`/`catalog_id`
(`world_request.py:136-137`), and `check_str` itself asserts nothing beyond
`isinstance(v, str) and bool(v.strip())` (`contracts/__init__.py:162-167`).
At validation time those four fields are literally indistinguishable — same
function, same arguments. A caller could submit `"the desert level"`, a
Windows path, or `"   x   "` and every rail in this document that reasons
"relative to the target map" would still pass. Verified this pass by reading
both call sites and every other occurrence of `subject` in `world_request.py`
(`:98, 117-122, 136, 267-283, 367, 387, 395, 401-416` — the rest are the
ALLOWED tuple, `CALLER_OWNED_FIELDS`, docstrings, and *constraint* subjects,
which are a different field on a different object).

**The rail.** One new carrier-only rail, `_rail_subject_is_target_map_path`,
enforced by `validate_carrier_world_request` (§9.7) and coded
`C.CORE_WORLD_REQUEST_INVALID` (WF1208) — the envelope's own generic code, no
new code claimed. It requires `world_request.subject` to be a **canonical
`/Game/` UE long package name naming exactly one target map identity**.

The grammar, stated as nine rules against the raw submitted value (not a
stripped or normalized copy — "canonical" means the caller submits it already
canonical, so the rail never silently repairs a value the rest of the
envelope is defined relative to):

| # | Rule | Rejects |
|---|------|---------|
| 1 | contains no backslash and no `:` | `D:\Maps\Foo` — a drive letter or Windows separator is never a package path |
| 2 | starts with `/` | `Game/Maps/Foo` |
| 3 | does not end with `/` | `/Game/Maps/Foo/` |
| 4 | equals its own `.strip()` | `" /Game/Maps/Foo"` — leading/trailing whitespace |
| 5 | splits (on `/`, after the single leading `/`) into **at least two** segments | `/Game` |
| 6 | first segment is exactly `Game` | `/Engine/Maps/Foo`, `/MyPlugin/Maps/Foo`, `/game/Maps/Foo` |
| 7 | no segment is empty, `.`, or `..` | `/Game//Foo`, `/Game/./Foo`, `/Game/../Foo` |
| 8 | no segment contains `.` | `/Game/Maps/Foo.Foo` — that is an *object path*, not a long package name |
| 9 | no segment contains any character in the target engine's `INVALID_LONGPACKAGE_CHARACTERS` | `/Game/Maps/Foo?`, `/Game/Maps/Bad Name`, `/Game/Maps/A&B`, `/Game/Maps/x@y` — see the character set and its authority below |

Rules 5-9 together are what make this a **single target identity** rather
than merely a well-formed string: exactly one map, named the one canonical
way, with no object-suffix variant able to name the same asset differently,
and no name the engine itself would refuse to mount.

**Rule 9 — the engine's own invalid-character set (added in fix pass 5, P1).**
Rules 1-8 constrain separators and structure but say nothing about the
*characters inside a segment*, so revision 4's grammar accepted names Unreal
itself rejects — `/Game/Maps/Foo?` and `/Game/Maps/Bad Name` both passed all
eight rules. Calling such a value a "canonical UE long package name" was
therefore false. The authority is the engine's own constant,
`INVALID_LONGPACKAGE_CHARACTERS`, read this pass from the installed engine
header at `Engine/Source/Runtime/Core/Public/UObject/NameTypes.h:185`:

```
#define INVALID_LONGPACKAGE_CHARACTERS  TEXT("\\:*?\"<>|' ,.&!~\n\r\t@#")
```

Decoded, that is these twenty characters — no segment of `subject` may
contain any of them:

```
\   :   *   ?   "   <   >   |   '   (space)   ,   .   &   !   ~   \n   \r   \t   @   #
```

**Overlap, stated honestly rather than counted twice.** Rule 9 *subsumes*
parts of three earlier rules: `\` and `:` (rule 1), interior whitespace
(which rule 4's `.strip()` equality catches only at the ends), and `.`
(rule 8). Rules 1, 4, and 8 are deliberately **kept** rather than folded into
rule 9, because each names a specific, common authoring mistake and should
fail with its own diagnostic — a caller who pasted a Windows path deserves a
better message than "contains an invalid character." The implementer should
treat rule 9 as the authoritative backstop and rules 1/4/8 as
better-diagnosed special cases of it; a value failing both may report either,
and the fixtures below do not assert which.

**Engine-version authority, and a live discrepancy worth recording.** The
constant above was read from **UE 5.7**, the only engine installed on the
machine this pass ran on (`C:/Program Files/Epic Games/UE_5.7/...`). This
project's `WorldForge.uproject` declares `"EngineAssociation": "5.8"`, whose
headers are **not present here** and were therefore **not** read. The set is
long-standing and unlikely to have changed, but this document does not claim
that: it is `[verified]` for 5.7 and `[assumed]` for 5.8. The rail restates
the set as a literal in `carrier_vocabulary.py` — for the same four reasons
§9.11 already restates rather than imports `is_ue_package_path`, plus the
plain fact that Python contract code cannot import a C++ macro — so
**`T4`'s implementer must re-read the target engine's own
`NameTypes.h:185` and confirm the literal matches before landing the rail**,
and any future engine upgrade must re-confirm it. A stale copy of this set is
a silent correctness bug, not a cosmetic one.

**Why this restates `is_ue_package_path` rather than importing it.** Fix pass
3 searched for a reusable grammar before inventing one and found exactly one
real shape validator, `is_ue_package_path`
(`tools/pipeline/transition_hygiene.py:70-78`). It is restated here, not
imported, for four reasons, each verified this pass:

- **Import layer.** `tools/wfcore/contracts/` imports only stdlib and
  relative wfcore modules — verified by enumerating every import in all seven
  files in that directory; there is **zero** import of `tools/pipeline` from
  anywhere under `tools/wfcore/`. `tools/pipeline` is a flat script
  directory, not a package, so a plain `from pipeline import ...` cannot work
  at all; the one `sys.path` insert that makes it importable is deliberately
  confined to `tools/wfcore/failure.py`, which documents in so many words
  that it is "confined to this module so no other Core file needs to know the
  layout" (`failure.py:12-28`). Importing a pipeline helper into
  `carrier_vocabulary.py` would widen precisely the escape hatch that module
  was written to contain.
- **Mount scope mismatch.** `is_ue_package_path` accepts **any known mount**,
  not `/Game` alone: its mount set is derived at runtime by `_ue_mounts()`
  (`transition_hygiene.py:61-67`) as `{"Game"}` plus `{"Engine", "Script",
  "Temp"}` plus one mount per `Plugins/<Name>/Content` entry in the imported
  `CONTENT_ROOTS` (`transition_hygiene.py:31`). `/Engine/Maps/X` and every
  plugin mount pass it. This rail needs one mount, fixed.
- **Rule mismatch.** It enforces four rules — no backslash or `:`, leading
  `/`, at least two segments, mount membership — and does **not** reject
  empty segments, `.`/`..` segments, trailing slashes, or object suffixes:
  five of the nine things this rail must reject (rules 3, 4, 7, 8, 9 above)
  — notably it applies no character-set rule at all, so it too accepts
  `/Game/Maps/Bad Name`.
- **Ownership.** It was built for an unrelated v2.5 report-hygiene gate and
  has exactly one consumer (`transition_hygiene.py:93`). Binding a carrier
  request contract's grammar to it would couple this contract to that gate's
  future changes, in the opposite direction from every other seam in this
  document.

**Wording correction (fix pass 4).** Revision 3 called `is_ue_package_path`
"the one real grammar validator found anywhere in the codebase." That
overstates the absence. It is the only *derived-mount, multi-rule shape*
validator, but at least nine other sites enforce real, weaker `/Game/`-prefix
rules that genuinely reject and emit errors — among them
`validate_placement.py:90-91,155-156,175-176`,
`validate_asset_catalog.py:49,141-143`,
`substance/validate_recipe.py:149-155`,
`relocate_houdini_asset.py:73-74`, `audit_generated_content.py:140-148`, and
`mesh_contract.py:189-217` (allow/deny root lists). None checks segment
structure, rejects backslashes or drive letters, or derives its mount set, so
none is a substitute for the rule above — but the correct claim is "the only
shape-grammar validator," not "the only validator that rejects a bad UE
path." (Sweep was Python-only; C++ `Source/**` and `.lua` surfaces were not
searched and are not claimed either way.)

**What this rail does not prove — and `T1`'s binding requirement.** This is a
*shape* check on a string submitted before anything runs. It cannot prove the
named map exists, and it cannot prove that the map WorldForge actually loads
and mutates at runtime is that map. Therefore, as a binding requirement on
`T1`'s own future contract — not enforced by any validator in this document:

> `T1` must prove that the map it actually loads and mutates resolves to
> **exactly** the identity named by `world_request.subject`, and must bind
> that resolved identity back to this same value in its live evidence. `T1`
> must not report a mutation as having occurred "in the target map" on the
> strength of this rail alone, which only proves the caller spelled a map
> identity correctly.

§9.10's "target identity" binding is the receipt-side half of this same tie:
the receipt names the map the mutation ran against, this rail fixes the form
of the value it must match, and `T1` supplies the live proof that joins them.

### 9.12 `T1` may not claim spatial boundedness it has not proven (fix pass 3 handoff clarification; written out in fix pass 4)

**Status: a requirement on `T1`'s own future contract. Nothing in this
document implements or enforces it, and — verified this pass — nothing
anywhere in `tools/wfcore/` implements it today.**

**What the mutation-bound machinery actually does.** `classify_target(bound,
target_kind, target_path)` (`tools/wfcore/transaction/delta.py:325-371`) is
the single place bound membership is decided; the module docstring states it
as "the single place membership is decided, so the matching rule cannot drift
between the preflight check and the post-apply check" (`delta.py:26`), and
the function's own docstring repeats it as "The single membership rule in the
package" (`delta.py:326-337`). It has three real call sites: the preflight
check (`executor.py:363`), the post-apply actual-touch check
(`executor.py:548`, inside `_check_actual_touches`, `executor.py:525-568`,
called at `executor.py:502`), and a validator rail (`delta.py:744`).

Its decision is exact string-list containment — `if path in allowed: return
TARGET_IN_BOUND` (`delta.py:363-366`) — against `allowed_packages` /
`allowed_actors`, built at `delta.py:353-356` by passing each declared entry
through `normalize_target_path` (`delta.py:272-282`), which only strips
whitespace, converts backslashes to `/`, and drops one trailing `/`. The
module docstring is explicit about the design: "Membership is EXACT, never
prefix or glob. A bound that matches by prefix is a bound the author cannot
enumerate, and one that accepts `*` is not a bound at all" (`delta.py:28-31`).

**What that proves, and what it does not.** It proves which *addresses*
(package and actor paths) a mutation touched. It proves nothing whatever
about where those addresses' *transforms* are in space. No coordinate,
transform, XY-region, or bounding-box comparison exists anywhere in
`delta.py` or `executor.py` — established this pass by reading both files end
to end (917 and 702 lines), not by grep, and by inspecting `classify_target`,
`bound_from_step` (`delta.py:285-308`, which reads only the declared
`expected_changed_packages`/`expected_changed_actors` lists) and
`validate_world_delta` (`delta.py:664-861`, whose only comparison operators
are a `len(evidence) > 0` check and duplicate-id `.count()` tests). The
nearest thing to a state comparison is `states_equal` (`delta.py:254-266`),
which compares two state records by sorted-JSON string equality over the
whole opaque payload (`canonical`, `delta.py:217-224`) — a transform inside
a payload would be tested for byte-exact equality against a declared expected
state, never for membership in a region.

Nor does anything else in the package supply it. A sweep of all 39 `.py`
files under `tools/wfcore/` surfaced five candidates, none of them a spatial
containment check on mutated transforms: `consumer_profile.py:252-262`
(numeric coherence on an authored capsule spec — real geometry, but no world
target and no mutation), `observed_world.py:695-708`
(`entities_within_measured_extent`, where the "extent" is a list of entity
ids, not a spatial extent), `planning/plan.py:196-201` (`plan_mutation_bound`
— a union of declared address strings; "blast radius" is a metaphor in its
docstring), `planning/plan.py:208-227` (`_touches_protected` — deliberate
address-namespace *prefix* containment against protected content,
pre-mutation), and `providers/selection.py:278-281` (string set
intersection). `world_request.extent_m2` (`world_request.py:91,341`) is a
single scalar validated as a positive number or the literal `unknown`, and no
reader derives geometry from it. No `geom*`, `spatial*`, `region*`, or
`transform*` module exists under `tools/wfcore/` at all.

**The requirement.**

> `T1` must not claim, report, or let a caller infer that a mutation stayed
> inside `bounded_region` unless `T1` independently proves that the **actual
> mutated transforms** lie within the **resolved planar extent** of that
> region. Existing path-touch enforcement is not that proof and must not be
> presented as it, cited as it, or relied on as it. If `T1` cannot prove it,
> `T1` must say so plainly rather than claim boundedness by association with
> the mutation-bound machinery.

**Why this is not `T4`'s to enforce.** `T4` validates a request *before* any
mutation has happened and has no post-mutation transform to check (§5). It
can require that `bounded_region` be fully resolved (§9.2) — it cannot
require that anything ended up inside it. Designing and implementing that
proof is `T1`'s own future work; this section exists so that work cannot be
quietly skipped on the assumption that `allowed_packages` already covered it.

## 10. Task graph

```
T4.1 (helper)  ->  T4.2 (evidence-kind add)  ->  T4.4 (envelope module)  ->  T4.6 (tests)
T4.3 (failure code + raise-site stub target)  ------------------------------^
T4.5 (contracts/__init__ export)  -------------------------------------------^
T4.7 (gate run)  depends on T4.3, T4.6
```

Unchanged shape from revision 1. T4.4 still does not touch or import
`revision_policy.py` (§9.6). **Fix pass 4 — what this graph does and does not
still cover.** The carrier-owned work this document still specifies — the
three closed-field rails (§9.0), the region-resolved rail (§9.2), the
cardinality rail (§9.5), and the new `subject` grammar rail (§9.11) — all
lands inside T4.4/T4.6's existing scope: no new task node, no new dependency
edge, graph shape unchanged. The evidence work revision 2 had placed in
T4.4/T4.6 — the eight-field completeness check, the hash round-trip check,
the completion-transition check, the `operation_id`-binding rail, and the
closed-field rails on the `evidence` sub-object and its parent
`evaluation_requirements[]` entry — is **no longer in this task graph at
all**. It did not move to another node here; it left `T4`'s scope entirely
in fix pass 3 (§9.5, §9.0) and belongs to `EVD-1`'s later validator
(§9.10). `EVD-1` is a separate contract this task graph neither includes nor
depends on: it gates `T2`'s live-evidence *implementation* and `T5`'s
canonical live run — not `T4`'s own tasks, and not `T2` drafting its
entry-point contract.

T4.1, T4.2, T4.3 are independent and parallelizable. T4.4 depends on all
three. T4.5 can run alongside T4.4. T4.6 depends on T4.4+T4.5. T4.7 is last.

## 11. Task-by-task plan

**T4.1 — add `check_coordinate` helper** — unchanged from original draft.
*Files:* `tools/wfcore/contracts/__init__.py`.
*Action:* add `check_coordinate(obj, field, code, prefix)` beside
`check_measure` (`__init__.py:218-237`); add `"check_coordinate"` to
`__all__` (`__init__.py:60-82`).
*Verify:* `cd tools && PYTHONUTF8=1 python -c "from wfcore.contracts import check_coordinate; print(check_coordinate({'x': -5}, 'x', 'CODE', 'p::'))"`
prints one passing check tuple.
*Risk/rollback:* additive function; delete to revert.

**T4.2 — add `runtime_save_reload_observation` to `acceptance_criteria.EVIDENCE_KINDS`** —
unchanged from original draft.
*Files:* `tools/wfcore/contracts/acceptance_criteria.py`.
*Action:* append the new string to the `EVIDENCE_KINDS` tuple only.
*Verify:* `cd tools && PYTHONUTF8=1 python -m wfcore.contracts.test_contracts`
— every prior `acceptance_criteria` assertion still passes.
*Risk/rollback:* one-line tuple append; revert by removing the string.

**T4.3 (depends: none) — add `WF1296_CORE_REQUEST_DOMAIN_NOT_SUPPORTED`** —
unchanged from original draft.
*Files:* `tools/pipeline/failure_codes.py`.
*Action:* insert
`CORE_REQUEST_DOMAIN_NOT_SUPPORTED = "WF1296_CORE_REQUEST_DOMAIN_NOT_SUPPORTED"`
under a new `# -- closed carrier request vocabulary (1296-1299) --` comment,
after the existing `WF1290` line.
*Verify:* `cd tools && PYTHONUTF8=1 python pipeline/validate_failure_codes.py --strict`
exits 0 and the new code appears in
`procedural/reports/failure_codes/validate_failure_codes_report.json`.
*Risk/rollback:* one constant; delete the line to revert.

**T4.4 (depends: T4.1, T4.2, T4.3) — the carrier envelope module** (revised
again this pass)
*Purpose:* the contract itself.
*Files:* `tools/wfcore/contracts/carrier_vocabulary.py` (**NEW**).
*Action:* implement `RT_CARRIER_VOCABULARY = "wf.core.carrier_vocabulary.v1"`,
`CARRIER_ENVELOPE_REQUIRED`/`CARRIER_ENVELOPE_ALLOWED`/
`CARRIER_ENVELOPE_CALLER_OWNED_FIELDS` (§9.0), `BIOME_CLASSES` (§9.1),
`ANCHOR_MODES`/`VERTICAL_SCOPES`/`BOUNDED_REGION_REQUIRED`/
`BOUNDED_REGION_ALLOWED` (§9.2), `INTERACTION_OBJECTIVE_REQUIRED`/
`INTERACTION_OBJECTIVE_ALLOWED` (§9.3), `CARRIER_ENVIRONMENT_ALLOWED` (§9.0),
`EXCLUDED_DOMAIN_TERMS` (§9.4, two-surface not three),
`validate_carrier_world_request(envelope_obj, strict=True)` (folds
`world_request.validate_world_request` and
`acceptance_criteria.validate_acceptance_criteria` via `prefixed()` after
the classify/delegate/reconcile pipeline of §9.4, then layers
`_rail_bounded_region_anchor` + `_rail_bounded_region_resolved`,
`_rail_interaction_objective` (now including its own closed-field check),
`_rail_environment_known` (now including its own closed-field check), and
`_rail_subject_is_target_map_path` (§9.11, fix pass 4, extended in fix pass
5 — the nine-rule
canonical `/Game/` long-package-name grammar on `world_request.subject`,
coded `WF1208` like every other envelope-level rail; implement it as a
module-private helper in `carrier_vocabulary.py`, **not** by importing
`tools/pipeline/transition_hygiene.py`, per §9.11's four stated reasons) on
top — the real `WF1296` raise site lives in step 4 of §9.4's pipeline),
`validate_carrier_acceptance_pairing(envelope_obj)` (§9.5's **single**
rail — cardinality only, narrowed from revision 2's five in fix pass 3;
single-argument per §9.7's disclosed signature change. It is kept as a
separate function even at one rail, per §9.7's own reasoning, and it still
mirrors `models.observed_world.validate_model_pair`'s joint-rail *pattern*.
Do **not** implement a closed-field, required-fields, hash-round-trip,
completion-transition, or `operation_id`-binding check here: none of that
data exists on the envelope or either nested document at submission time —
§9.5), `build_carrier_envelope(**over)` (does **not** internally call
`world_request.build_world_request`/`acceptance_criteria.build_acceptance_criteria`
on the caller's behalf — the caller builds each nested document itself with
the existing `build_world_request`/`build_acceptance_criteria` and passes the
finished dicts in as `over["world_request"]`/`over["acceptance_criteria"]`;
`build_carrier_envelope` itself only enforces
`CARRIER_ENVELOPE_CALLER_OWNED_FIELDS` via `require_caller_owned` and
defaults `schema_version`/`report_type`), and `_example_carrier_envelope()`
canonical-valid fixture (built from `world_request._example_world_request()`
and `acceptance_criteria._example_acceptance_criteria()`, with `detail`
strings and `constraint_id`s aligned per §9.3, `bounded_region`'s four
offset/extent fields fully resolved per §9.2, `world_request.subject` set to
a canonical `/Game/` long package name that satisfies all nine rules of
§9.11, and exactly one matching `evaluation_requirements[]` entry — in
**plain v1 shape**, carrying `constraint_id` and `evidence_kind ==
"runtime_save_reload_observation"` and nothing else new (§9.5). **Fix pass 4:**
the fixture carries no `evidence` sub-object, no state hashes, no completion
states, no `proof_kind`, and no `operation_id`; those fields belong to the
separate runtime-evidence receipt owned by `EVD-1` (§9.5, §9.10), which this
example deliberately does not construct.)
*Verify:* `cd tools && PYTHONUTF8=1 python -c "from wfcore.contracts import carrier_vocabulary as CV; env = CV._example_carrier_envelope(); assert not [c for c in CV.validate_carrier_world_request(env, strict=True) if not c[1]]; assert not [c for c in CV.validate_carrier_acceptance_pairing(env) if not c[1]]"`
exits 0.
*Risk/rollback:* new file only; delete it to revert. Does not import
`revision_policy.py` (§9.6).

**T4.5 (depends: none, parallel with T4.4) — export the new module** —
unchanged from original draft.

**T4.6 (depends: T4.4, T4.5) — negatives-first test suite** (revised fixture
list, this pass)
*Purpose:* prove every new rail fires, named check + named code. Until this
task is implemented and run, every "produces X" claim elsewhere in this
document about `carrier_vocabulary.py`'s actual behavior is a specification,
not an observation (see the revision-2 documentation-honesty note).
*Files:* `tools/wfcore/contracts/test_carrier_vocabulary.py` (**NEW**).
*Action:* canonical example asserted valid under `strict=True`; then, at
minimum, one known-bad per new rail:
  - missing `bounded_region` → `CORE_WORLD_REQUEST_INVALID` (envelope's
    reused generic code)
  - `bounded_region.anchor_mode == "explicit_transform"` with negative
    `origin_x_cm` accepted (proves `check_coordinate`, not a failure case)
  - `bounded_region.anchor_mode == "explicit_transform"` with `anchor_location_cm`
    also carrying `anchor_object_path` → rejected (the two-halves-disagree rail)
  - `bounded_region.extent_x_cm == 0` → rejected (proves reuse of
    `check_measure`'s zero-rejection)
  - `bounded_region` missing `vertical_scope` → rejected
  - nested `environment` missing `biome_class` → rejected
  - `biome_class` outside `BIOME_CLASSES` → rejected
  - nested `environment.biome_class == UNKNOWN` (otherwise-valid `resolution_owner`
    stated) → **still rejected** — the load-bearing fixture proving the carrier
    rail is strictly tighter than v1's own unknown-with-owner allowance (§9.1)
  - `interaction_objective.affordance_id` naming an affordance that is not
    `required=True` → rejected
  - `interaction_objective.affordance_id` naming an affordance whose
    `affordance_kind != "interaction_surface"` → rejected
  - `interaction_objective.constraint_id` naming a constraint absent from
    the nested `acceptance_criteria.constraints` → rejected
  - `interaction_objective.constraint_id` present in `acceptance_criteria.constraints`
    but absent from `must_block_ids` → rejected
  - `gameplay_affordances[].affordance_kind == "patrol_route"` → **`WF1296`
    alone**, domain `"tactical_behavior"` named — the fixture proving the
    v1-legal/carrier-illegal case produces exactly one failure, not zero
  - `semantic_landmarks[].role == "quest_giver"` (out-of-band at v1 too) →
    **`WF1296` alone**, domain `"quest"` named, and the generic
    `role_in_vocabulary` failure that v1 would otherwise also produce is
    confirmed **absent** — the load-bearing no-dual-fail fixture (§9.4 step 3)
  - a value outside every vocabulary and every `EXCLUDED_DOMAIN_TERMS` entry
    (e.g. `affordance_kind == "made_up_kind"`) → the **generic** v1 code
    (`CORE_WORLD_REQUEST_INVALID`) alone, proving the domain code does not
    over-fire on ordinary malformed input
  - `build_carrier_envelope()` called without `bounded_region` →
    `ContractAuthorityError`
  - a pairing where two `evaluation_requirements[]` entries both cite the
    target `constraint_id` with `runtime_save_reload_observation` → rejected
    (cardinality rail, §9.5 rail 1)
  - **revision 2, fix for defect 1 — closed-field rails (three survive fix pass 4):**
    `bounded_region` carrying an unrecognized extra field (e.g. `quest_id`)
    → rejected, `WF1208`; `interaction_objective` carrying an unrecognized
    extra field → rejected, `WF1208`; nested `world_request.environment`
    carrying an unrecognized extra field alongside a valid `biome_class` →
    rejected, `WF1208` (proves the carrier's own closure, not v1's —
    `world_request.validate_world_request` called directly on the same
    `environment` object must still pass, since v1 itself has no gate here).
    **Fix pass 4 — two of revision 2's five closed-field fixtures are
    removed**: the one on the targeted `evaluation_requirements[]` entry and
    the one on its `evidence` sub-object. Neither rail exists any more — the
    sub-object is gone and the entry carries no carrier-owned field to close,
    so per §9.0 it stays exactly as open as v1 made it. Three closed-field
    fixtures remain, on `bounded_region`, `interaction_objective`, and
    `environment`.
  - **revision 2, fix for defect 2 — region must be resolved:**
    `bounded_region.origin_x_cm == UNKNOWN` (otherwise-valid region) →
    rejected, `WF1208`; `bounded_region.extent_y_cm == UNKNOWN`
    (otherwise-valid region) → rejected, `WF1208` — both prove
    `_rail_bounded_region_resolved` fires even though `check_coordinate`/
    `check_measure` alone would have accepted `UNKNOWN` at the helper level.
  - **new in fix pass 4 — `subject` grammar (§9.11): nine known-bads
    covering rules 1-8 — rule 7 carries two values, for the empty- and
    dot-segment cases; rule 9 is covered by its own parametric fixture below
    — each failing the check named
    `cv::world_request.subject_is_target_map_path` with `WF1208`:**
    a Windows path carrying backslashes and a drive-letter colon (rule 1);
    `"Game/Maps/Foo"`, no leading `/` (rule 2);
    `"/Game/Maps/Foo/"`, trailing slash (rule 3);
    `"  /Game/Maps/Foo"`, not equal to its own `.strip()` (rule 4);
    `"/Game"`, a single segment naming no map (rule 5);
    `"/Engine/Maps/Foo"`, a real and well-formed UE package path on the wrong
    mount — the load-bearing fixture proving this rail is strictly narrower
    than `is_ue_package_path`, which *accepts* this value
    (`transition_hygiene.py:61-67`) (rule 6);
    `"/Game//Foo"` and `"/Game/../Foo"`, empty and dot segments (rule 7);
    `"/Game/Maps/Foo.Foo"`, an object path rather than a long package name
    (rule 8).
  - **new in fix pass 5 — rule 9, the engine invalid-character set,
    tested parametrically:** one fixture parametrized over **every** character
    in `INVALID_LONGPACKAGE_CHARACTERS` (§9.11), asserting that
    `/Game/Maps/Foo<c>` is rejected with `WF1208` for each. It must explicitly
    cover `?` and an **interior space** (`"/Game/Maps/Bad Name"`) as named
    cases, since those are the two the eight-rule revision-4 grammar
    demonstrably let through. Characters that also trip an earlier rule
    (`\`, `:`, `.`) are included in the parametrization but the fixture
    asserts only *that* the value is rejected, not which rule rejected it —
    see §9.11's overlap note.
  - **new in fix pass 4 — the carrier-ownership proof for §9.11:** for at
    least one of the values rejected above, `world_request.
    validate_world_request(envelope["world_request"], strict=True)` called
    **directly** on the same nested document must return **zero** failing
    checks — v1 accepts every one of these strings through the generic
    `check_str` loop (`world_request.py:136-137`). This is the mechanical
    proof that the grammar is carrier-owned and layered on top of v1 rather
    than inherited from it, exactly parallel to the `environment`-closure
    fixture above, and the proof that fix pass 3's P1 defect 2 is actually
    closed rather than assumed.
*Verify:* `cd tools && PYTHONUTF8=1 python -m wfcore.contracts.test_carrier_vocabulary`
exits 0, every `[PASS]` line listed above with no `[FAIL]`.
*Risk/rollback:* new test file only; delete to revert.

**T4.7 (depends: T4.3, T4.6) — full-suite regression + failure-code gate** —
unchanged from original draft:
```
cd tools && PYTHONUTF8=1 python -m wfcore.contracts.test_contracts
cd tools && PYTHONUTF8=1 python -m wfcore.contracts.test_carrier_vocabulary
cd tools && PYTHONUTF8=1 python -m wfcore.models.test_models
cd tools && PYTHONUTF8=1 python pipeline/validate_failure_codes.py --strict
```

## 12. Execution mode

**Sequential.** Unchanged reasoning from the original draft; the envelope
restructuring makes T4.4 slightly larger but does not add independent
parallel lanes — most tasks still gate on T4.4.

## 13. Required commands

```
cd tools && PYTHONUTF8=1 python -m wfcore.contracts.test_contracts
cd tools && PYTHONUTF8=1 python -m wfcore.contracts.test_carrier_vocabulary
cd tools && PYTHONUTF8=1 python -m wfcore.models.test_models
cd tools && PYTHONUTF8=1 python pipeline/validate_failure_codes.py --strict
```

## 14. Verification gates

- **Red before green:** T4.6's `WF1296` fixtures, the no-dual-fail fixture
  (§9.4), the biome/relief-unknown-refused fixture (§9.1), the three
  surviving closed-field fixtures (§9.0), the region-must-be-resolved
  fixtures (§9.2), all ten `subject`-grammar fixtures from fix pass 4, and
  — new in fix pass 5 — the parametric invalid-character fixture (§9.11
  rule 9) must each be shown failing against the pre-T4.4 state,
  then shown passing after. **Fix pass 4 removed** the `operation_id`-binding
  and completion-transition gates revision 2 listed here: those rails are no
  longer T4's (§9.5), so there is nothing in T4.6 for them to gate.
- **Non-regression:** T4.7's four commands must all be green at completion,
  with `test_contracts.py` showing the same pass count it had before T4.2's
  `EVIDENCE_KINDS` append.
- **Strict-nesting proof (revision 1, still required):** T4.6 must include an
  assertion that `world_request.validate_world_request(envelope["world_request"],
  strict=True)` — called **directly**, bypassing the envelope entirely —
  returns zero failing checks on the canonical example. This is the
  mechanical proof that the nested document really is a fully-valid,
  independent `wf.core.world_request.v1` document and not merely something
  that happens to pass when folded through the envelope's own delegation.
  The same direct-call assertion applies to the nested `acceptance_criteria`.
  **New this pass:** this same fixture must also prove the carrier's own
  `environment`-closure rail rejects an extra field that the direct v1 call
  on the identical `environment` object does **not** reject — the concrete
  demonstration that the closure is carrier-owned, not inherited from v1
  (§9.0).
- **New in fix pass 4 — carrier-ownership proof for the `subject` grammar:**
  T4.6 must assert that a `subject` value this contract rejects under §9.11
  is nonetheless accepted by `world_request.validate_world_request(...,
  strict=True)` called directly on the same nested document — the mechanical
  demonstration that the grammar is layered on top of v1, not inherited from
  it, and that `subject` is no longer merely `check_str`-validated at the
  carrier boundary. **Fix pass 4 removed** revision 2's `proof_kind`
  distinct-outcome gate: both `proof_kind` and the completion-state pair left
  this contract's scope in fix pass 3 (§9.5), so T4.6 has no such fixture to
  assert over. Preserving that distinction is now a stated requirement on
  `EVD-1`'s later validator (§9.5, §9.10), not a T4 gate.

## 15. Failure codes

- `WF1296_CORE_REQUEST_DOMAIN_NOT_SUPPORTED` (new, §9.4) — a request named a
  structural term recognized as belonging to an excluded domain (quest,
  combat, reward, faction, tactical_behavior, streaming). The only new code
  this contract claims.
- `CORE_WORLD_REQUEST_INVALID` (existing, WF1208) — reused as the **carrier
  envelope's own generic code**: the envelope's top-level shape gates
  (`check_is_object`/`check_required`/`check_no_unknown`/`schema_version`),
  `bounded_region`'s structural, closed-field, and — new this revision —
  offsets/extent-resolved rails (§9.2), `interaction_objective`'s structural
  and — new this revision — closed-field checks (§9.3), the biome/relief
  -unknown-refusal rail and the carrier-environment closed-field check
  (§9.1), and — new in fix pass 4 — the `subject_is_target_map_path`
  grammar rail (§9.11) all use it. **Fix pass 4 removed** the closed-field
  checks revision 2 coded here on the targeted `evaluation_requirements[]`
  entry and its `evidence` sub-object: neither rail exists any more (§9.0,
  §9.5). It remains, unchanged, the nested `world_request` document's own
  code too when validated directly.
- `CORE_ACCEPTANCE_CRITERIA_INVALID` (existing, WF1210) — the joint
  save/reload pairing rail's failure code (§9.5), now covering **exactly one
  rail: cardinality**. **Fix pass 4 removed** the required-fields/enum
  -membership, hash-round-trip, completion-transition, and `operation_id`
  -binding uses revision 2 listed here; fix pass 3 moved all four out of this
  contract to `EVD-1`'s later validator (§9.5, §9.10), whose own failure
  code(s) are explicitly not decided here. Remains, unchanged, the nested
  `acceptance_criteria` document's own code too when validated directly.
- `ContractAuthorityError` (existing, `contracts/__init__.py:90-98`) —
  raised, not returned as a check, when `build_carrier_envelope()` is
  called without a `CARRIER_ENVELOPE_CALLER_OWNED_FIELDS` member.
- `CORE_SINK_RELOAD_MISMATCH` (WF1281) — **not reused** by this contract;
  named here only to record that it was considered and rejected for the
  hash-equality check revision 2 once carried, because it belongs to a
  different owner/layer (the live engine-backed mutation sink) and this
  contract is schema-only. Since fix pass 3 that check is not this
  contract's at all (§9.5); the reasoning is kept so `EVD-1` inherits it
  rather than rediscovering it.
- **No new failure code is added by fix pass 4 either.** The three
  surviving closed-field rails, the region-resolved rail, the cardinality
  rail, and the new `subject`-grammar rail (§9.11) all reuse
  `WF1208`/`WF1210` as noted above. A future `EVD-1` contract (§9.10) may
  claim its own code(s) for live hash-recomputation/receipt-verification
  failures when it exists — not decided here, and not this contract's number
  to spend. `WF1296` remains the single new code this document claims.

## 16. Negative fixtures

Enumerated in full in T4.6 above. **Recounted in fix pass 5: thirty-three
named cases** — seventeen surviving from revision 1, five surviving from
revision 2, ten new in fix pass 4, and one new in fix pass 5.

The revision-2 survivors are three closed-field fixtures
(`bounded_region`, `interaction_objective`, `environment`) and two
region-must-be-resolved fixtures. Fix pass 4's ten cases are nine `subject`
-grammar known-bads covering rules 1-8 of §9.11 (rule 7 carries two values,
for empty and dot segments), plus the carrier-ownership proof that v1 accepts
a value this contract rejects. Fix pass 5 adds one: the parametric fixture for
rule 9's engine invalid-character set, which explicitly covers `?` and an
interior space.

**Removed in fix pass 4 — eight of revision 2's thirty**, because the rails
they exercised are no longer this contract's (§9.5, §9.0): the two pairing
fixtures on the `evidence` sub-object (missing sub-object; hash round trip),
the two closed-field fixtures on the targeted `evaluation_requirements[]`
entry and that sub-object, the `operation_id`-binding fixture, and the three
completion-transition fixtures including the positive idempotent-retry one.
Revision 2's "thirty named cases" count is superseded. It also described
itself as a negative-fixture list while silently including two *positive*
cases: the negative-coordinate-accepted fixture and the idempotent-retry
fixture. Fix pass 4 removed the latter along with the rest of the
completion-transition work. The current thirty-three contain two positives —
the surviving negative-coordinate fixture and the new carrier-ownership proof
(§9.11) — and this section no longer describes the list as negatives-only. Each negative fixture is
a known-bad spawned from the canonical `_example_carrier_envelope()` via
`**over`, per the existing suite's discipline — a failure is attributable to
exactly the one field changed.

## 17. Review plan

- **Spec axis:** does every field in §9 trace to one of T4.md's six named
  vocabulary items, does the excluded-domain list cover exactly the six
  named exclusions (no more, no fewer), does the nested `world_request`/
  `acceptance_criteria` each independently pass their own unmodified strict
  v1 validator when extracted and called directly (§14's strict-nesting
  proof), is every carrier-owned nested object
  (`bounded_region`, `interaction_objective`, and the carrier's addition to
  `environment` — **three**, since fix pass 3 removed the fourth and fifth,
  §9.0) actually closed to unknown fields with a fixture proving it (§9.0,
  §14), and — new in fix pass 4 — does `world_request.subject` carry the
  §9.11 grammar with a fixture per rule and the carrier-ownership proof
  (§14)? A reviewer should also confirm the negative: that **no** task in
  §10–§16 references the deleted `evidence` sub-object, `EVALUATION_EVIDENCE_
  REQUIRED`/`_ALLOWED`, `CARRIER_EVALUATION_REQUIREMENT_ALLOWED`,
  `COMPLETION_STATES`, `PROOF_KINDS`, or an `operation_id` rail — the
  specific drift fix pass 4 existed to remove.
- **Standards axis:** does the new module match the five existing
  contracts' shape (`Check` tuples, `_P` prefix constant, `RT_*` schema
  identity, `*_REQUIRED`/`*_ALLOWED` tuples, `build_*`/`_example_*` pair,
  `require_caller_owned` for anything caller-owned)? **Corrected this
  pass:** revision 1 stated the house convention as "no `check_no_unknown`
  at nested-object depth" and treated that as binding on the carrier's own
  new objects too — that was defect 1, and it is no longer this document's
  standard. The corrected standard: v1's *own* nested objects
  (`landmark`/`affordance`/`population`/environment's v1-owned fields/
  `rollback`) stay open, exactly as v1 already made them; any **new,
  carrier-owned** nested object or sub-object is closed, with its own
  `*_ALLOWED` tuple, by default — see §9.0. Any deviation from *that*
  standard should be justified in review, not silent.

## 18. Merge gate

All four §13 commands green, plus a manual confirmation that
`git diff -- tools/wfcore/contracts/world_request.py`,
`git diff -- tools/wfcore/contracts/revision_policy.py` show **zero** lines
changed, and `git diff -- tools/wfcore/contracts/acceptance_criteria.py`
shows **exactly one line added** (the `EVIDENCE_KINDS` append) — the
immutability requirement from Q4 is a diff a reviewer can check by eye, and
this revision adds `revision_policy.py` to the zero-diff set since the
module no longer references it at all (§9.6).

## 19. Definition of done

Done when all four §13 commands exit 0, the `git diff` check in §18 holds,
§14's strict-nesting and distinct-outcome proofs pass, and
`tools/pipeline/validate_failure_codes.py --strict`'s report lists
`WF1296_CORE_REQUEST_DOMAIN_NOT_SUPPORTED` with no orphan/uniqueness
complaint. Any reader can answer done/not-done from those outputs without a
judgment call. **`EVD-1` (§9.10) existing is explicitly not part of this
definition of done** — `T4` is complete on its own terms without it; only
`T1`/`T2`'s later implementation against these evidence fields waits on it.

## 20. Follow-ups

- **Wiring into `T1`/`T2`.** Unchanged — this contract deliberately stops at
  the schema layer.
- **`BIOME_CLASSES` and `VERTICAL_SCOPES`' exact membership** are
  placeholder starter sets. Expect both to grow the way `LOCOMOTION_MODES`
  grew `jump` — once a real caller's biome (or a real vertical-bounding use
  case) has no honest member, not by pre-guessing now.
- **Prose keyword-scanning** (§8 Fork 2, Option B) was considered and
  declined; new scope if a future reviewer wants it.
- **`observed_world.EVIDENCE_KINDS` / `acceptance_criteria.EVIDENCE_KINDS`
  naming collision** — pre-existing, unrelated to T4, flagged not fixed.
- **Superseded this pass — evidence hash semantics.** Revision 1 left the
  hash scope/algorithm as an open item deferred to "`T1`/`T2`'s own
  execution contracts, independently." The re-review correctly named that
  as an ownerless shared seam, not merely an open question. §9.10 resolves
  it: a new prerequisite contract, `EVD-1`, owns the canonical hash scope,
  algorithm, and live operation-receipt binding; `T1`/`T2` must not
  implement against these evidence fields until it exists. This bullet is
  kept only to record that the old framing ("deferred to T1/T2") is
  superseded, not still live.
- **Open, not silently resolved — evaluation-requirement cardinality
  (§9.5).** This contract requires *exactly one* `runtime_save_reload_
  observation` evaluation requirement per interaction objective. A consumer
  wanting two independent evidence collectors for the same constraint
  (redundant verification) is a legitimate future want this contract does
  not support; relaxing "exactly one" to "at least one, with an explicit
  reconciliation rule for disagreement between them" is new scope, not
  silently assumed here.
- **Open, not silently resolved — `biome_class`/`relief_class` refusal is a
  hard block with no relief path.** §9.1 refuses `UNKNOWN` outright because
  nothing downstream can act on `resolution_owner` yet. Once a real
  resolution workflow exists for the first carrier, this may deserve
  softening back toward v1's own allowance — but doing that now, ahead of
  any such workflow existing, would reopen exactly the loophole item 4 was
  raised to close.
- **New this pass, open — the first carrier has no preview mode of its
  own.** §9.2 concludes that the existing `--preview` flow already serves
  the pre-envelope layer and that inventing an unused preview envelope shape
  now would be ungrounded. If a future revision wires `bounded_region`/
  `interaction_objective` into a real preview flow, that flow needs its own
  explicitly non-executable envelope shape (e.g. a distinct
  `schema_version` or a required `executable: false` discriminant checked
  before any other rail) at that point — not designed here because no real
  caller needs it yet.
- **New this pass, open — `EVD-1` is named, not created.** This document
  states what a new evidence-digest/operation-receipt contract must own
  (§9.10) and that `T4` now depends on it existing before `T1`/`T2` can
  implement against `T4`'s evidence fields — but does not create the ticket
  or contract file itself, since only `docs/contracts/
  wfcore_request_vocabulary_contract.md` is in scope for this pass.
  Registering `EVD-1` in the decision terrain map is a follow-up action for
  that map's owner.
- **Superseded in fix pass 3, recorded here in fix pass 4 —
  `operation_id`'s `envelope_id`-prefix rule is no longer this contract's.**
  Revision 2 carried a structural rail requiring `evidence.operation_id` to
  be prefixed by the envelope's own `envelope_id`, and this list flagged it
  as knowingly partial: it proved a caller *declared* which envelope an
  operation belonged to, never that a real operation ran or that submitted
  hashes were recomputed rather than asserted. Fix pass 3 removed the rail
  along with the rest of the evidence payload (§9.5); the binding it
  gestured at is now stated properly as one of the five bindings `EVD-1`'s
  later validator must check against a real operation record (§9.10). This
  bullet is kept only so the old framing is recorded as superseded, not
  still live.
- **New in fix pass 4, open — `§9.11`'s grammar is `/Game`-only by
  deliberate choice.** A future carrier whose target map legitimately lives
  on a plugin mount would fail rule 6. That is intended for the first
  carrier — one mount, one identity shape — but it is a real constraint,
  not an oversight, and relaxing it later means widening the rule and its
  nine fixtures together, the same way `LOCOMOTION_MODES` grew `jump`: once
  a real caller has an honest need, not by pre-guessing now.
