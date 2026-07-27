# WorldForge v2.6 — SceneSurveyForge Caller Handoff

Status: **IN PROGRESS — v2.6 shield RED 10/11; the single red is `validate-scene-survey-runtime`, which is red until a caller-originated survey runs**
Branch: `worldforge/v2.6-scene-survey`
Contract version: **`wf.scene_survey.contract.v2_6.0`**
Contract surface: `sha256:2bebaa594adb5de98e2140a6ae6517be77bf579e52047bc07ca1afcf83c390b0`
Minimum WorldForge commit: **`99efe79a`**
Failure-code band: **WF1061–WF1130** (`SCENE_SURVEY_*`, 65 codes), plus WF1011/WF1026 from the bridge band

This document is the complete surface a caller needs to invoke a WorldForge scene
survey. It is written so the caller can generate a valid request **without reading
any WorldForge implementation code**.

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
(`run_scene_survey_probe.py:518-525`). A survey WorldForge chose the subject for
would prove nothing about the subject you cared about.

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
| `target_engine` | yes | `"5.8"` |
| `target_project` | yes | project name; the far side asserts the editor opened `<name>.uproject` |
| `target_map` | yes | UE **package** path (`/Game/Maps/Foo`), not a content-file path. Must equal `subject.map_asset_path` |
| `required_plugin` | yes | `"WorldForge"` |
| `required_plugin_version` | yes | `"0.1.0"` |
| `requested_operation` | yes | `"scene_survey"` |
| `output_location` | yes | repo-relative directory for the response artifact |
| `required_plugin_source_hash` | **effectively yes** | see §7 — an unstated pin fails closed |
| `subject` | **effectively yes** | the `SceneSurveySubject`; optional on the dataclass because other operations take none, but `scene_survey` refuses a request without one |
| `timeout_seconds` | no | default 300 |

Unknown keys are refused outright (`_load_request`, `run_scene_survey_probe.py:351-354`).

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

---

## 6. Request ↔ report binding

This is what makes a survey falsifiable. After the run, five rails compare your
request to the returned report; all five must pass.

| Rail | Requirement | Code on failure |
|---|---|---|
| `sb::subject_id_match` | report `subject_id` equals request `subject_id`, exactly | WF1107 |
| `sb::map_match` | report `map_asset_path` equals request `map_asset_path` | WF1107 |
| `sb::transform_within_tolerance` | `explicit_transform` only: Euclidean L2 distance between requested `anchor_location` and observed `observed_anchor_location` **≤ 1.0 cm, inclusive** | WF1107 |
| `sb::object_path_match` | `actor_object_path` only: `observed_anchor_object_path` equals requested `anchor_object_path`, exact string | WF1107 |
| `sb::resolver_not_worldforge` | request `resolved_by` **and** report `subject_resolved_by` both `"caller"` | WF1108 |

Notes that bite:

* The tolerance is **Euclidean, not per-axis.** 0.6 cm of drift on each of x/y/z
  is an L2 of ≈1.039 cm and **fails**, even though no single axis exceeded 1 cm.
* **Rotation and scale are never compared.** Do not infer that a passing bind
  proves orientation.
* An executed run must carry a vec3 `observed_anchor_location` in **either**
  mode, not only `explicit_transform`.

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

---

## 9. Output paths

| Artifact | Path |
|---|---|
| Survey report (the one the gate reads) | `procedural/reports/scene_survey/runtime/scene_survey_report.json` |
| Per-run far-side evidence | `procedural/reports/scene_survey/runtime/far_side_run{i}.json`, i = 1..`--repeat` |
| Bridge response | `<output_location>/scene_survey_response_<operation_id>.json` |

All are written under the **WorldForge** repo, never into the target project. The
report is a wrapper: the domain record is at `.survey`, and your submitted subject
is echoed at `.subject` — that top-level `subject` key is what makes the report
bindable.

Stale artifacts from a previous run are deleted before the editor boots, so a
report on disk always belongs to the most recent invocation.

---

## 10. Preparation failure vs runtime failure

This distinction is carried by the **exit code**, and it is unambiguous:

```
exit 2  PREPARATION failure. The editor was NEVER launched. No report is written.
        The reason is printed to stdout with its WF code.
exit 1  RUNTIME failure. The editor ran. A report IS written; read its
        failure_codes and status.
exit 0  Pass.
```

If you see exit 2, do not look for a report file — there is none by design, and an
old one would be stale. Preparation failures, in the order they are checked:

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

Runtime failure codes, written into the report's `failure_codes`:

| Code | Meaning |
|---|---|
| `WF1095_SCENE_SURVEY_RUNTIME_SIMULATED_OVERCLAIM` | the run did not actually execute |
| `WF1094_SCENE_SURVEY_DETERMINISM_MISMATCH` | repeat runs disagreed |
| `WF1062_SCENE_SURVEY_REPORT_INVALID` | far side reported an error, or the report violates its contract |
| `WF1106_SCENE_SURVEY_SUBJECT_UNRESOLVED` | the anchor was not verified on the far side |
| `WF1109_SCENE_SURVEY_CHANNEL_DISAGREEMENT` | the stdout marker channel and the JSON channel disagreed |
| `WF1107_SCENE_SURVEY_SUBJECT_MISMATCH` | binding failed (§6) |
| `WF1108_SCENE_SURVEY_SUBJECT_INFERRED` | a resolver other than `caller` appeared on either side |
| `WF1068_SCENE_SURVEY_CAMERA_CAPTURE_MISSING` | captures were requested but none were produced |
| `WF1097_SCENE_SURVEY_EVIDENCE_MISSING` | a clean status without the evidence to back it |

`status` is `pass`, `blocked`, or `fail`. **`blocked` is an honest outcome**, not
a bug: it means the survey ran and bound correctly but a requested product (today,
camera capture) could not be produced. Only `fail` indicates the survey itself is
untrustworthy.

---

## 11. Cleanup guarantees — and their current limits

What is guaranteed today:

* The survey is **read-only with respect to persistent content**. The far side
  loads the level, verifies the anchor, enumerates, samples, and probes. It never
  saves the map and never spawns a permanent actor.
* Temporary markers are **trace-probed, not spawned** — `probe_temp_marker` tests
  a candidate placement without instantiating anything, so there is no marker to
  leave behind.
* Stale artifacts are purged before each boot.

What is **not yet proven**, stated plainly because a caller must not read more
assurance into this than exists:

* `cleanup_verified` in the report is currently a **hard-coded `true`**, justified
  by the trace-probe design above rather than by an observation. It is not yet an
  independent measurement.
* The report does **not yet carry** `package_dirty_before` / `package_dirty_after`
  or the temporary-actor counts. Package immutability is therefore argued from
  design, not demonstrated from evidence.
* `proxy_owners` and `proxies_disabled` are hard-coded `0` / `false`; proxy
  enumeration needs a `-game` pass.
* Camera capture cannot succeed in the current `-nullrhi` pass and is reported
  honestly as not captured. Requesting captures will produce `blocked`, not a
  false positive.

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
