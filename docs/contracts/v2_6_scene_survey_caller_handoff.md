# WorldForge v2.6 — SceneSurveyForge Caller Handoff

Status: **IN PROGRESS.** The v2.6 shield is **12/13**, with `validate-scene-survey-runtime`
the **only** red: it stays red until a caller-originated survey actually runs. That red now
resolves to one of three named conditions and you should read which — **§12**. And **no run
can reach `status: "pass"` today** — see §11.
Branch: `worldforge/v2.6-scene-survey`
Contract version: **`wf.scene_survey.contract.v2_6.1`**
(`tools/pipeline/scene_survey_contracts.py:195`, mirrored by all three schemas and
the manifest. This document previously said `v2_6.0`; that was stale.)
Contract surface: read `contract_surface_sha256` from
`specs/scene_survey/scene_survey_contract_manifest.json` — that field is machine-written by
`tools/pipeline/export_scene_survey_contracts.py:778-779, 799` and is the only authoritative
value. **Do not trust a hash transcribed into prose.** This document used to carry
`sha256:2bebaa59…c390b0`; a repo-wide search found that string in exactly one place — this line —
and it matches neither the committed manifest nor a fresh export. Nothing in the repo hashes,
reads, or gates on this markdown file, so a hand-copied hash here can rot silently and did.
Minimum WorldForge commit: **`99efe79a`**
Failure-code band: **WF1061–WF1130** (`SCENE_SURVEY_*`, **65** codes — verified by
enumeration 2026-07-30; WF1115–WF1119 are unallocated, so the band is a range, not a
census), plus WF1011/WF1026 from the bridge band

This document is the complete surface a caller needs to invoke a WorldForge scene
survey. It is written so the caller can generate a valid request **without reading
any WorldForge implementation code**.

**A note on the citations below.** The seven files on this path that were under active
edit (`run_scene_survey_probe.py`, `scene_survey_evidence.py`, `scene_survey_recompute.py`,
`validate_scene_survey_runtime.py`, `scene_survey_far_side.py`, and both halves of
`SceneSurvey.{h,cpp}`) are now **committed and clean at HEAD `89f97f8a`**. Claims about
them are still cited **by symbol** rather than by line number — that convention is kept
deliberately, because the lane may reopen and symbol citations survive it. Line citations
appear only for files that have been stable across the whole edit window. Verified
2026-07-30.

It is deliberately **not** a guide to choosing a subject. WorldForge owns
capability; the caller owns intent. Which level, which anchor, and which objective
a survey is *for* are decisions this document has no authority over and takes no
position on. What follows describes only how to *state* a subject you have already
resolved, and what WorldForge will prove back to you about it.

---

## 1. Contract artifacts

Generated from the Python spine, never hand-written:

```
specs/scene_survey/scene_survey_subject.schema.json      the caller-resolved subject
specs/scene_survey/scene_survey_request.schema.json      the request envelope
specs/scene_survey/scene_survey_report.schema.json       the survey result
specs/scene_survey/scene_survey_contract_manifest.json   version, vocabulary, hashes
examples/scene_survey/caller_resolved_actor_request.json      actor_object_path mode
examples/scene_survey/caller_resolved_transform_request.json  explicit_transform mode
```

Regenerate / verify (the second form writes nothing and is a shield gate):

```
PYTHONUTF8=1 python tools/pipeline/export_scene_survey_contracts.py
PYTHONUTF8=1 python tools/pipeline/export_scene_survey_contracts.py --check
```

**`--check` is GREEN as of 2026-07-30** — verified by running it: `PASS — 6 artifact(s)
match a fresh export; 111 schema/validator equivalence probes agreed`, exit 0. An earlier
revision of this document said it "is red on this working tree, and you should expect that",
citing committed pin `ea454a79…` against live pin `462b2bd3…`; **that is stale.** The
artifacts were regenerated and the drift is closed (live pin now `3fea6d29…`).

The underlying mechanic still holds and will bite again: the two
`examples/scene_survey/*.json` files embed an *observed* plugin-source pin of the local
`Plugins/WorldForge/Source/**`, so **any** edit to the plugin source re-drifts them and
cascades into the manifest. If you see this gate red, re-run the first form to regenerate.
That is a WorldForge-side housekeeping condition, never a defect in your request.

**Schema validity is necessary, not sufficient.** Each schema carries an
`x-worldforge-rails` array naming the constraints JSON Schema cannot express —
cross-field arithmetic and request↔report binding. Those rails are enforced at
runtime regardless. Do not treat a schema-clean request as an accepted request.

---

## 2. Discovering the operation

The registry is the source of truth for what this door accepts. It needs no
pipeline import and provokes no failure:

```
cd tools && PYTHONUTF8=1 python -m bridge.capability_ops --list
```

```json
[ { "operation": "scene_survey",
    "summary": "read-only spatial survey of a caller-resolved subject in a target map",
    "far_side_script": "tools/bridge/scene_survey_far_side.py",
    "far_side_script_present": true,
    "payload_keys": ["subject", "captures"] } ]
```

An unregistered `requested_operation` is refused with
`WF1011_CAPABILITY_UNAVAILABLE`. There is no nearest-match and no default.

---

## 3. The supported command

```
PYTHONUTF8=1 python tools/pipeline/run_scene_survey_probe.py \
    --request <caller-produced-request.json> \
    --project <path-to-target>.uproject \
    --strict
```

`--request` is the **only** way to state a subject. `--map` and `--anchor` exist
solely to be refused — they are not defaulted, not overridden, and not honoured
(the refusal is the first preparation check in `run_scene_survey_probe._run_survey`).
A survey WorldForge chose the subject for would prove nothing about the subject you
cared about.

Useful optional flags: `--repeat N` (default 2; determinism needs ≥2),
`--capture gameplay,elevated_oblique,top_down` (opt-in; see §9),
`--engine-root`, `--ue-cmd`, `--timeout` (default 900s), `--smoke` (bootless
self-check).

---

## 4. Caller-owned fields

Every field below is yours. WorldForge fills in none of them, and a request
missing one is refused rather than completed on your behalf.

| Field | Required | Notes |
|---|---|---|
| `operation_id` | yes | opaque; identifies this invocation end to end |
| `source_repository` | yes | **your** repository name — this is the caller-origin claim |
| `source_commit` | yes | **your** commit — see §8 |
| `target_repository` | yes | repository containing the target project |
| `target_commit` | yes | commit of the target repository |
| `target_engine` | yes | `"5.8"` by convention. **Nothing on the scene-survey path checks the value** — the schema types it as a bare string, and the one `== BRIDGE_ENGINE` check lives in `tools/bridge/probe.py:142`, which this command never calls |
| `target_project` | yes | project name; the far side asserts the editor opened `<name>.uproject` |
| `target_map` | yes | UE **package** path (`/Game/Maps/Foo`), not a content-file path. Must equal `subject.map_asset_path` — **but the check is skipped when `target_map` is empty**, so an empty string silently disables it. Send a real path |
| `required_plugin` | yes | `"WorldForge"` by convention; **the value is unchecked** (bare string in the schema). The plugin *directory* `Plugins/WorldForge` is hard-coded in the probe and ignores this field |
| `required_plugin_version` | yes | `"0.1.0"` by convention; **the value is unchecked** |
| `requested_operation` | yes | `"scene_survey"` |
| `output_location` | yes | repo-relative directory for the response artifact |
| `required_plugin_source_hash` | **effectively yes** | see §7 — an unstated pin fails closed |
| `subject` | **effectively yes** | the `SceneSurveySubject`; optional on the dataclass because other operations take none, but `scene_survey` refuses a request without one |
| `timeout_seconds` | no | dataclass default 300 (`tools/bridge/schema.py:94`) — **but inert for this operation.** Nothing on the scene-survey path reads it; the editor deadline is the CLI `--timeout` (default 900). Both shipped examples set it to 900 for consistency. Do not rely on it to bound a run |

Unknown keys are refused outright (`run_scene_survey_probe._load_request`).

### The subject

| Field | Type | Notes |
|---|---|---|
| `subject_id` | non-empty string | opaque to WorldForge; echoed back so you can prove identity |
| `subject_kind` | `actor` \| `area` \| `point` | |
| `map_asset_path` | non-empty string | `/Game/...` package path |
| `anchor_mode` | `explicit_transform` \| `actor_object_path` | see §5 |
| `anchor_location` | `[x,y,z]` or `null` | key must be **present** either way |
| `anchor_rotation` | `[pitch,yaw,roll]` or `null` | key must be present; **never compared** during binding |
| `anchor_object_path` | string or `null` | key must be present either way |
| `resolved_by` | `"caller"` | the only legal value |
| `schema_version` | `wf.scene_survey.survey_subject.v1` | |

Optional metadata keys, never type-checked: `meta`, `report_type`, `created_by`,
`created_at`, `notes`, `display_key`.

---

## 5. Anchor modes

There are exactly two, and they are **storage shapes, not choices WorldForge is
allowed to make**:

```
explicit_transform  ->  anchor_location = [x,y,z]   AND  anchor_object_path = null
actor_object_path   ->  anchor_object_path = "..."  AND  anchor_location    = null
```

Exclusivity is enforced as an XOR on null-ness. Zero populated channels means you
never resolved the subject; two populated channels means WorldForge would have to
pick one — both are `WF1106_SCENE_SURVEY_SUBJECT_UNRESOLVED`.

`anchor_rotation` is outside the XOR and may be present or `null` in either mode.

**They are equal for *binding*. They are NOT equal for *acceptance*.** An
`explicit_transform` survey can pass every binding rail in §6 and still be
permanently ineligible for the acceptance gate, because under that mode the anchor
coordinates the far side reports were **copied from your own request** — the
observation is a value compared against a copy of itself, so it cannot distinguish
a correct subject from arbitrary coordinates. Only `actor_object_path` has the far
side independently *resolve* an actor and *read* its transform. If your run has to
satisfy acceptance, you must use `actor_object_path`. See §8.

---

## 6. Request ↔ report binding

This is what makes a survey falsifiable. After the run, **seven** rails compare your
request to the returned report (`scene_survey_contracts.validate_subject_binding`,
`scene_survey_contracts.py:1085-1175`); **all seven must pass**, and a failure of any
one of them is a hard `fail`, never a `blocked`. Earlier revisions of this document
said "five"; the two acceptance rails below were omitted.

| Rail | Requirement | Code on failure |
|---|---|---|
| `sb::subject_id_match` | report `subject_id` equals request `subject_id`, exactly | WF1107 |
| `sb::map_match` | report `map_asset_path` equals request `map_asset_path` | WF1107 |
| `sb::transform_within_tolerance` | `explicit_transform` only: Euclidean L2 distance between requested `anchor_location` and observed `observed_anchor_location` **≤ 1.0 cm, inclusive** | WF1107 |
| `sb::object_path_match` | `actor_object_path` only: `observed_anchor_object_path` equals requested `anchor_object_path`, exact string | WF1107 |
| `sb::resolver_not_worldforge` | request `resolved_by` **and** report `subject_resolved_by` both `"caller"` | WF1108 |
| `sb::acceptance_not_overclaimed` | a report claiming `acceptance_eligible: true` must survive re-derivation from the pair (§8) | WF1111 |
| `sb::acceptance_reason_matches_evidence` | a report claiming ineligibility must state the reason the evidence actually gives | WF1112 |

The last two are **directional on purpose**: only the over-claim is rejected.
Under-claiming cannot cause a false accept, so it fails safe
(`scene_survey_contracts.py:1144-1153`).

Notes that bite:

* The tolerance is **Euclidean, not per-axis.** 0.6 cm of drift on each of x/y/z
  is an L2 of ≈1.039 cm and **fails**, even though no single axis exceeded 1 cm.
* **Rotation and scale are never compared.** Do not infer that a passing bind
  proves orientation.
* An executed run must carry a vec3 `observed_anchor_location` in **either**
  mode, not only `explicit_transform`. Note this one is enforced by the *report*
  contract (`sr::observed_anchor_present`, WF1106), not by the binding table above —
  it is mode-independent, and the far side supplies the location in
  `actor_object_path` mode by reading it off the resolved actor.

---

## 7. Plugin source pin

WorldForge refuses to survey through a plugin whose source it cannot identify.

`required_plugin_source_hash` is the sha256 of the target's
`Plugins/WorldForge/Source/**`, computed with: every file under `Source/`
recursively, sorted by POSIX-relative path, CRLF and lone CR normalized to LF,
each record framed as `<relpath>\0<bytelen>\0<bytes>`. No file is skipped.

Compute it against your own tree:

```
python -c "import sys;sys.path.insert(0,'tools');from bridge import paths as P;\
print(P.hash_plugin_source(r'<target>/Plugins/WorldForge'))"
```

Fail-closed semantics: **an unstated pin is a failure, not a waiver.** All three
of unstated / unobservable / mismatched produce `WF1026_BRIDGE_STALE_PLUGIN`, and
this is checked **before the editor boots** — the failure message says so
explicitly.

This description was re-verified against `tools/bridge/paths.py:244-264` on
2026-07-30 and is exact, including "no file is skipped" — there is no filter and no
skip-list. An absent or empty `Source/` **raises** rather than emitting a digest,
which is why "unobservable" is a distinct fail-closed case above and not a hash that
matches nothing.

The hash covers `Source/**` only. It does **not** prove the binary was rebuilt
from that source; a stale DLL against fresh source is outside what this pin can
detect.

---

## 8. Provenance, and why it matters

You supply provenance through `source_repository` and `source_commit`. These are
the fields that make a run *caller-originated*.

**This is load-bearing for acceptance.** A request authored inside WorldForge may
be used for contract tests, and the two files under `examples/scene_survey/` are
exactly that — but a WorldForge-authored request can never satisfy the final
acceptance gate. The gate exists to prove the caller resolved a real subject,
invoked the generic capability, and received evidence proving that exact subject
was surveyed. A request WorldForge wrote to itself proves none of that.

### Acceptance eligibility is a report field, and you should read it

Every report carries two required fields this document previously did not mention:
`acceptance_eligible` (bool) and `acceptance_ineligibility_reason` (a closed enum,
or `null`). They are derived by one shared predicate that the independent validator
re-runs, never re-implements (`scene_survey_evidence.derive_acceptance_eligibility`,
reached via `scene_survey_contracts.evaluate_acceptance_eligibility`).

Eligibility is a conjunction of five components, evaluated **in this order** — the
first one to fail names the reason:

| # | Component | Reason emitted when it is the first to fail |
|---|---|---|
| 1 | `anchor_mode_observable` — `anchor_mode == "actor_object_path"` | `independent_subject_anchor_not_observable` |
| 2 | `observed_world_identity_valid` — the editor opened the world you named | `observed_world_identity_unverified` |
| 3 | `observed_actor_identity_valid` — it resolved the exact actor you named | `observed_actor_identity_unverified` |
| 4 | `observed_actor_transform_valid` — it reported a finite vec3 for that actor | `observed_actor_transform_unobserved` |
| 5 | `survey_bound_to_observed_actor` — a run happened and `subject_id` / `resolved_by` are continuous across both sides | `survey_not_bound_to_observed_actor` |

Consequences worth stating flatly:

* **`explicit_transform` fails component 1 and is therefore never
  acceptance-eligible**, no matter how clean the rest of the survey is. This is a
  locked invariant expressed as ordinary conjunction, so there is no special case to
  waive. `examples/scene_survey/caller_resolved_transform_request.json` is a valid
  contract-test request that is, by construction, acceptance-ineligible.
* Component 5 is honestly the weakest of the five: it proves the report belongs to
  this request, not that each spatial sample was taken relative to the observed
  actor. No per-sample anchor provenance exists in the report contract yet.
* `acceptance_eligible` is independent of `status`. A `blocked` run can be
  acceptance-eligible, and a survey with no failure codes can be ineligible.

---

## 9. Output paths

Artifacts are **operation-scoped**. Write `OPDIR` for
`procedural/reports/scene_survey/runtime/operations/<slug>/`
(`scene_survey_operation.py:972`; `manifest_path_for` at `:981`, `report_path_for` at `:995`).

`<slug>` is **not** your raw `operation_id`: every character that is not
alphanumeric, `.`, `_` or `-` becomes `_`, leading/trailing `._-` are stripped, and
the result is truncated to 120 characters (`scene_survey_operation._slug`, `:1004`).
An `operation_id` that slugs to the empty string is refused with
`WF1128_SCENE_SURVEY_OPERATION_ID_MISMATCH`. Keep `operation_id` filesystem-safe and
under 120 characters and `<slug>` will equal it.

| Artifact | Path | Authority |
|---|---|---|
| Survey report | `OPDIR/scene_survey_report.json` | **AUTHORITATIVE** — the evidence of record |
| Survey report (shared copy) | `procedural/reports/scene_survey/runtime/scene_survey_report.json` | **mirror only** — the process prints it as "not the evidence of record" |
| Per-run far-side evidence | `OPDIR/far_side_run{i}.json`, i = 1..`--repeat` | raw |
| Operation manifest (the seal) | `OPDIR/operation_manifest.json` | published **last**, after every artifact it names is durable |
| Bridge response | `<output_location>/scene_survey_response_<operation_id>.json` | — |

Earlier revisions of this document placed the report and the per-run evidence
directly under `runtime/`. That is no longer where they live, and the flat
`runtime/scene_survey_report.json` is now a convenience mirror, not the artifact to
grade. **Read `OPDIR`.**

All are written under the **WorldForge** repo, never into the target project. The
report is a wrapper: the domain record is at `.survey`, and your submitted subject
is echoed at `.subject` — that top-level `subject` key is what makes the report
bindable. Note the wrapper carries its own `ok`/`fail` house vocabulary, which is
**not** the survey `status` of §10.

**On staleness — read this carefully, it is weaker than it used to read.** Only
`far_side_run*.json` inside *this operation's own* `OPDIR` are purged before the
boot. The shared mirror is deliberately **not** unlinked ahead of a run that might
refuse; it is republished atomically at the end, or left exactly as it was. So a
refused or crashed run leaves the **previous** invocation's
`runtime/scene_survey_report.json` in place, and it will look current. This is
another reason to read `OPDIR`, which is unique per `operation_id`.

`operation_id` is **not reusable**: a re-run with an `operation_id` whose manifest
already exists is refused outright with `WF1128`.

---

## 10. Preparation failure vs runtime failure

This distinction is *mostly* carried by the **exit code**, but it is **not
unambiguous**, and an earlier revision of this document said it was. Corrected:

```
exit 2  Refusal. USUALLY a preparation failure with the editor never launched and
        no report written — but see the warning below: four exit-2 paths fire AFTER
        the run, and three of those after the report is already durable on disk.
exit 1  The editor ran and the survey did not pass. This covers BOTH status "fail"
        and status "blocked". A report IS written; read its failure_codes.
exit 0  status == "pass" — which no run can reach today (§11).
```

> **Do not treat exit 2 as "no report exists".** The publication tail returns 2 when
> it cannot publish the derived report, cannot publish the response, cannot build
> the operation manifest, or cannot publish the manifest. In the last three cases
> the report has already been written and fsynced. The reliable "was this run
> sealed?" test is the presence of `OPDIR/operation_manifest.json`, which is
> published last precisely so that a manifest is never visible before the evidence
> it names.

Note also that exit 1 does **not** imply the survey is untrustworthy — `blocked`
exits 1 too, and `blocked` is the normal outcome today.

Preparation failures, in the order they are checked:

| Order | Refusal | Code |
|---|---|---|
| 1 | `--map` / `--anchor` supplied | *(refused by message; no code)* |
| 2 | `--request` missing | *(refused by message)* |
| 3 | `--project` missing | *(refused by message)* |
| 4 | request unreadable / not JSON / not an object / unknown key / fails `BridgeRequest` | *(refused by message)* |
| 5 | `requested_operation` != `scene_survey` | WF1011 |
| 6 | payload/subject invalid | WF1106 / WF1108 / WF1065 |
| 7 | `target_map` != `subject.map_asset_path` | WF1107 |
| 8 | plugin source hash unstated / unobservable / mismatched | WF1026 |

Six further preparation refusals follow #8 and were previously undocumented. All
exit 2, all before the boot:

| Order | Refusal | Code |
|---|---|---|
| 9 | the request's `operation_id` disagrees with the resolved operation identity | WF1128 |
| 10 | the request hash could not be computed | *(refused by message)* |
| 11 | `output_location` escapes its permitted root | **WF1130** |
| 12 | artifact paths could not be resolved | *(refused by message)* |
| 13 | **a manifest already exists for this `operation_id`** — re-runs are refused, not overwritten | WF1128 |
| 14 | the operation directory could not be created | *(refused by message)* |

Runtime failure codes, written into the report's `failure_codes`:

| Code | Meaning |
|---|---|
| `WF1095_SCENE_SURVEY_RUNTIME_SIMULATED_OVERCLAIM` | the run did not actually execute |
| `WF1094_SCENE_SURVEY_DETERMINISM_MISMATCH` | repeat runs disagreed |
| `WF1062_SCENE_SURVEY_REPORT_INVALID` | the far side reported an error. **Only that arm exists** — an earlier revision also claimed "or the report violates its contract", but a report that fails its own validator produces a printed WARNING and a house check, not a WF1062 in `failure_codes` |
| `WF1106_SCENE_SURVEY_SUBJECT_UNRESOLVED` | the anchor was not verified on the far side |
| `WF1109_SCENE_SURVEY_CHANNEL_DISAGREEMENT` | the stdout marker channel and the JSON channel disagreed |
| `WF1107_SCENE_SURVEY_SUBJECT_MISMATCH` | binding failed (§6) |
| `WF1108_SCENE_SURVEY_SUBJECT_INFERRED` | a resolver other than `caller` appeared on either side |
| `WF1068_SCENE_SURVEY_CAMERA_CAPTURE_MISSING` | captures were requested but none were produced |
| `WF1097_SCENE_SURVEY_EVIDENCE_MISSING` | a clean status without the evidence to back it |
| `WF1121_SCENE_SURVEY_MAP_LOAD_FAILED` | the level never opened |
| `WF1122_SCENE_SURVEY_WORLD_IDENTITY_UNVERIFIED` | a level opened, but not confirmably the one you named |
| `WF1113_SCENE_SURVEY_EVIDENCE_RAW_MISSING` | one or more fields nothing observed; they are named in `meta.evidence_unknown_fields` |
| `WF1110_SCENE_SURVEY_EVIDENCE_CLASSIFICATION_INVALID` | an evidence record is internally malformed — a defect in the assembler, not in your request |
| `WF1092_SCENE_SURVEY_CLEANUP_UNVERIFIED` | `cleanup_verified` is not `true` (see §11) |
| `WF1091_SCENE_SURVEY_PROXY_DISABLE_UNVERIFIED` | `proxy_owners` or `proxies_disabled` is `null` (see §11) |
| `WF1111_SCENE_SURVEY_EVIDENCE_UNSUPPORTED_CLAIM` | the report over-claimed `acceptance_eligible` (§6, §8) |
| `WF1112_SCENE_SURVEY_EVIDENCE_REDERIVATION_MISMATCH` | the report's ineligibility reason is not the one the evidence gives (§6, §8) |

`status` is `pass`, `blocked`, or `fail`, and the split is mechanical
(`run_scene_survey_probe._build_report`): `fail` iff the run did not execute, was
non-deterministic, the far side errored, the subject was unresolved, the two
channels disagreed, a §6 binding rail failed, or world identity was unverified.
Anything else with a non-empty `failure_codes` is `blocked`; only an empty
`failure_codes` is `pass`.

**`blocked` is an honest outcome**, not a bug: the survey ran and bound correctly
but something could not be produced or observed. Note that this is broader than
"a requested product is missing" — an unobservable *capability* blocks too, which
is why no run reaches `pass` today (§11).

---

## 11. Cleanup guarantees — and their current limits

What is guaranteed today:

* The survey is **read-only with respect to persistent content**. The far side
  loads the level, verifies the anchor, enumerates, samples, and probes. It never
  saves the map — `tools/bridge/scene_survey_far_side.py` contains no save call at
  all; its only use of `EditorLoadingAndSavingUtils` is *reading* the dirty-package
  sets. The one spawn path in the file, `_SpawnLedger.spawn_transient`, has **no
  callers**, and would hard-code `transient=True` if it had any.
* Temporary markers are **trace-probed, not spawned** — `USceneSurveyStatics::ProbeTempMarker`
  (`Plugins/WorldForge/Source/WorldForgeCore/Private/SceneSurvey.cpp`) runs a ground
  trace, four corner traces and two blocking-overlap tests and returns a bool. It
  never spawns, so there is no marker to leave behind.
* **`cleanup_verified` is now derived from measurement, not asserted.** It is no
  longer the hard-coded `true` earlier revisions of this document described. The
  far side takes a **pre** inventory at anchor-bind and a **post** inventory at
  cleanup (`scene_survey_far_side.py`, `_inventory`), and the assembler derives the
  verdict from the pair (`run_scene_survey_probe._build_evidence` →
  `scene_survey_evidence.derive_cleanup_verified`) as an **equality** — not
  containment — on three sets plus the level actor set:

  ```
  cleanup_verified = (D_post == D_pre) AND (T_post == T_pre) AND (M_post == M_pre)
                     AND (actor_paths unchanged)

  D = dirty packages     T = operation-owned actors     M = map/package identity
  ```

  Equality in both directions matters: a package that *stops* being dirty was
  written to disk, and a survey that saves a map has mutated the project just as
  surely as one that dirties it.
* **An unmeasured set is never read as an empty one.** A sufficiency gate
  (`scene_survey_evidence.sufficiency_cleanup`) refuses to answer unless both
  inventories exist, both report `collection_ok`, the post snapshot is strictly
  *after* the pre one and at or after the cleanup stage, and `actor_paths`,
  `dirty_packages` and `operation_owned_actor_paths` are all present **as lists** on
  both sides. When it refuses, `cleanup_verified` is reported as `null`, never
  `true` or `false` (`run_scene_survey_probe._reported`), and
  `WF1092_SCENE_SURVEY_CLEANUP_UNVERIFIED` is raised.
* **A second, independent implementation re-derives the same verdict** from the raw
  atoms and must agree — `scene_survey_recompute.cleanup_verified`, enforced by
  `validate_scene_survey_runtime.py` (`recompute::*::cleanup_from_inventories`).
* **Package immutability is therefore demonstrated from evidence, not argued from
  design.** It is the `D_post == D_pre` conjunct above.

What is **not yet proven**, stated plainly because a caller must not read more
assurance into this than exists:

* **Two snapshots cannot see an object that was created *and* destroyed between
  them.** Inventory equality is a statement about endpoints, not about the interval.
  A per-object mutation ledger that closes this gap is **in flight and has not
  landed**; until it does, `cleanup_verified: true` means "the world at cleanup is
  set-identical to the world at anchor-bind", which is weaker than "nothing was ever
  mutated". Do not read the stronger sentence into it.
* The **report body** carries no `package_dirty_before` / `package_dirty_after`
  field and no temporary-actor count — the report schema has no such properties. The
  underlying sets are not hidden, but you must read them from
  `meta.evidence.cleanup_verified.inputs`, which carries `newly_dirty_packages`,
  `no_longer_dirty_packages`, `temporary_objects_leaked`,
  `temporary_objects_released`, `actors_pre`, `actors_post` and the map identities —
  or from the `far_side_run*.json` artifacts.
* Dirtiness is observable only as **membership of the engine's dirty-package sets**;
  `UPackage.is_dirty()` is not exposed to Python.
* `proxy_owners` and `proxies_disabled` are **`null`, not `0` / `false`** — earlier
  revisions of this document said hard-coded `0`/`false`, and that is no longer
  true. MeshForge runtime proxies spawn at game `BeginPlay` and a `-nullrhi` editor
  pass never reaches it, so neither their presence nor their disablement is
  observable here; the code files that as `unsupported` / `not_requested` rather
  than inventing a measurement (`run_scene_survey_probe._proxy_owner_record`,
  `._proxies_disabled_record`). Both `null` values raise
  `WF1091_SCENE_SURVEY_PROXY_DISABLE_UNVERIFIED`. Proxy enumeration needs a `-game`
  pass. **A `null` here is the honest answer; a `0` would have been a claim.**
* Camera capture cannot succeed in the current `-nullrhi` pass and is reported
  honestly as not captured — nothing in the far side ever sets `camera_capture_ran`
  to `True`. Requesting captures produces `blocked` with `WF1068`, not a false
  positive.

### The one thing to plan around: `status: "pass"` is currently unreachable

Do not build acceptance on `status == "pass"` yet. Independently of what you
request, three evidence fields are **unconditionally** classified `unsupported`
today — `support_samples_valid`, `unsupported_regions`, `edge_regions`
(`run_scene_survey_probe._build_evidence`) — because the far side returns only an
aggregate support total and no per-sample breakdown. That makes
`meta.evidence_unknown_fields` non-empty, which raises
`WF1113_SCENE_SURVEY_EVIDENCE_RAW_MISSING`, and `proxy_owners` / `proxies_disabled`
add `WF1091`. Neither code is in the `hard` set, so the verdict is `"blocked"` — an
**honest incomplete**, not a failure. A perfectly clean, correctly bound,
capture-free survey therefore returns `blocked`, and exits **1**, today. Read
`failure_codes` and §6 binding, not `status`, to decide whether the survey answered
your question.

These are the open items on the WorldForge side. They do not affect subject
binding, which is fully enforced today.

---

## 12. Acceptance (canonical surface; `make` not installed — run python directly)

```
PYTHONUTF8=1 python tools/pipeline/export_scene_survey_contracts.py --check
cd tools && PYTHONUTF8=1 python -m bridge.capability_ops --list
PYTHONUTF8=1 python tools/pipeline/run_scene_survey_probe.py --smoke --strict
PYTHONUTF8=1 STRICT=1 python tools/pipeline/v2_6_shield.py --strict --scene-survey
```

**What the shield actually runs.** The last command executes **13 gates** — five
always-on (`failure-codes`, `makefile-refs`, `scene-survey-contracts`,
`scene-survey-negative-fixtures`, `scene-survey-contract-export`, enumerated at
`tools/pipeline/v2_6_shield.py:79-86`) and eight in the survey lane
(`scene-survey-fuzz`, `-torture`, `-known-bads`, `-assembler-probes`,
`-report-integrity`, `-hygiene`, `run-scene-survey-smoke`,
`validate-scene-survey-runtime`, at `:90-111`). An earlier revision of this document
said the shield was 11 gates with a single red; both numbers were wrong.

**Current state: 12 of 13 pass. `validate-scene-survey-runtime` is the ONLY red.**
An earlier revision said to expect *two* reds; that is stale.
`scene-survey-contract-export` is now green (§1, verified by running `--check`).

* `validate-scene-survey-runtime` — red until a caller-originated survey writes a
  runtime report. This is the gate your survey is meant to turn green, and **nothing
  else turns it green.** It is not a caveat and not expected noise.

### The runtime red is one of three distinct conditions — read which one you have

Before 2026-07-30 this gate rendered three unrelated situations as the same red, so
its colour told you nothing. They are now separated, and the code tells you which
situation you are in. **Do not read the first as the third.**

| Rail | Code | What it means | How it is fixed |
|---|---|---|---|
| `input::operation_id_resolved` | `WF1128_SCENE_SURVEY_OPERATION_ID_MISMATCH` | **WIRING DEFECT.** No source produced an operation id at all — the gate cannot name what it is grading. **This was a real WorldForge-side bug**: the shield used to invoke the validator without `--operation-id`, so a missing argument masqueraded as absent caller evidence. **FIXED** — the shield now passes an explicit id (`RUNTIME_OPERATION_ID = "op_v2_6_scene_survey_0001"`, `v2_6_shield.py:45`, passed at `:110-111`). | Editing a command line. |
| `input::operation_id_unambiguous` | `WF1129_SCENE_SURVEY_CONCURRENT_OPERATION` | **AMBIGUITY.** More than one candidate operation was offered. The gate refuses to choose — picking one silently is how a run grades the wrong operation and nobody finds out. | Naming exactly one operation. |
| `input::caller_evidence_present` | `WF1097_SCENE_SURVEY_EVIDENCE_MISSING` | **ABSENT CALLER EVIDENCE.** The gate knows exactly which operation it would grade, and no runtime artifact for that operation exists yet. **This is the intentional red, and the one standing today.** | Booting an editor and running a caller-originated survey — **not** by editing a command line. |

Exactly one of the three can block on any given run: the evidence rail is *skipped*
when no id resolved, and the two resolution rails are mutually exclusive by
construction (`validate_scene_survey_runtime.py:37-53`, `resolve_operation_id`).

> `WF1129` carries a **second, unrelated meaning on the probe side**: operation-lock
> contention (`scene_survey_operation.py:865-954` — `lock_held`, `lock_contended`,
> `stale_lock_unbreakable`, and siblings). Read the reason string, not just the code:
> in the table above it means *the validator was offered several operations*; from the
> probe it means *another run holds this operation's lock*.

**`--operation-id` is now required, not optional.** Input selection is operation-scoped:
the gate reads one named operation's artifacts, the artifact must be newer than the code
that produces it, must be inside the declared max age, and — when the operation manifest
and originating request are both available — must match the request hash. Every one of
those is fail-closed. Before this, the file read one hard-coded path with no way to say
*which* operation was being graded, so any well-formed report satisfied any operation
forever; the gate was observed grading an eight-day-old artifact without noticing.

Keep your `operation_id` filesystem-safe and under 120 characters (§9) — it is what the
gate is told to grade.

The red is not caused by anything you send. What is on *you* is §6 binding and, if
your run must satisfy acceptance, the `actor_object_path` requirement in §5 and §8.
