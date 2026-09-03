# Execution Contract: T3 — Versioned acceptance policy (three criterion classes)

Status: ready (revised — failure-code allocation and four design gaps closed;
see §2, §9, §11, §15, §20)

Source ticket: `.project-intelligence/decisions/terrain/worldforge-walkaway-mission/tickets/T3.md`.
Resolved decision: `.project-intelligence/decisions/terrain/worldforge-walkaway-mission/decisions.md` Q3.
This document is the binding plan. It authorizes nothing by itself — implementation
starts only when this contract is handed to `production-flywheel` / the normal
implementation flow under its own authorization, per
`.project-intelligence/decisions/terrain/worldforge-walkaway-mission/map.md:69-74`
("No source change is authorized by Cycle 1"). This revision is itself a
contract-document-only change — no source file is touched by this pass either.

## 1. Executive mission

Build `tools/wfcore/policy/`, a new wfcore package that defines the versioned
acceptance-policy artifact Q3 requires: a closed three-class taxonomy of
acceptance criteria (machine-required invariants, measurable runtime/performance
budgets, human-required design evidence), a content-hashed immutable policy
registry, and the two honestly-different claims —
`accepted_by_declared_policy` and `production_quality` — as named,
mechanically-derived tri-valued verdicts. No existing wfcore file is modified
except `tools/pipeline/failure_codes.py` (new WF12xx constants, additive only).

## 2. Current baseline

- Branch: `worldforge/wfcore-consumer-platform` [verified — `git branch --show-current`].
- Working tree carries pre-existing, unrelated modifications (`procedural/reports/**`,
  `.neostack/skills-manifest.json`) [verified — `git status --porcelain`]. None of
  it is `tools/wfcore/` or `tools/pipeline/failure_codes.py`; this mission does
  not need to touch or clean any of it (that is `CLEANUP-1`, out of scope here).
- `tools/wfcore/` today has no `policy/` package
  [verified — `ls tools/wfcore` shows `acceptance/ analysis/ constraints.py
  contracts/ failure.py hygiene.py models/ planning/ providers/ repair/
  transaction/ tri.py` and no `policy/`].
- `tools/wfcore_shield.py:47-61` discovers every `tools/wfcore/**/test_*.py` by
  walking the tree — a new `tools/wfcore/policy/test_policy.py` is picked up
  automatically; no shield wiring is needed.
- **Failure-code band is hard, not conventional.** `tools/wfcore/failure.py:13`
  states plainly that Core owns band **WF1200–1299** — not "usually stays
  inside", a stated boundary. `tools/pipeline/failure_codes.py` WF1200–1299
  band: 66 numbers in use today, highest is `WF1290_CORE_PROVIDER_EVIDENCE_IS_FIXTURE`
  [verified — enumerated via `code_number()` over every `FailureCode` constant].
  The section comment at `tools/pipeline/failure_codes.py:1398` reserves
  1291–1295 for "external-tool provider evidence" — only 1289/1290 are
  currently allocated inside that reservation, and `failure_codes.py`'s own
  precedent at its WF666–670 comment ("Do NOT reuse/renumber an earlier band...
  leave them") makes clear those five numbers are not available to a new,
  unrelated topic even though unused. **`WF1296` is independently claimed by
  the sibling T4 contract** (`docs/contracts/wfcore_request_vocabulary_contract.md:404`,
  `CORE_REQUEST_DOMAIN_NOT_SUPPORTED`), which states outright
  (`wfcore_request_vocabulary_contract.md:69`) that "WF1296–1299 are the only
  genuinely free numbers" in the Core band. Neither T3 nor T4 has landed any
  code yet [verified — `grep -n "WF1296\|WF129[7-9]\|WF130[0-4]"
  tools/pipeline/failure_codes.py` returns nothing]; T4's contract reserves
  WF1296 first. **T3's genuinely available allocation is therefore exactly
  three numbers: WF1297, WF1298, WF1299** — not the nine (WF1296–1304)
  originally proposed in this document. §15 replaces the original nine-code
  table with a three-code table; each surviving code consolidates several of
  the original failure modes into one code with a `detail`-string-named cause,
  the same pattern T4 itself uses for `WF1296` (one code, six excluded
  domains) and the pattern already established at `WF1201_CORE_CONSTRAINT_UNKNOWN_CLASS`
  / `WF1203_CORE_NO_LOAD_BEARING_CONSTRAINT` (`tools/pipeline/failure_codes.py:1260,1268`).
- `tools/pipeline/validate_failure_codes.py:22-70` is the gate that fails the
  build if two codes collide on a WF number, and `failure.py:31-36` documents
  that `SEVERITY`/`GATE_TAXONOMY` are auto-backfilled for any new constant — a
  new code needs no manual registry edit beyond the constant itself.
- No `hashlib` usage exists anywhere under `tools/wfcore/` today
  [verified — `grep -rln hashlib tools/wfcore/` returned nothing]. Policy-hash
  computation is new machinery, not an extension of an existing helper.
- `tools/wfcore/transaction/executor.py:93` establishes the
  `procedural/reports/core/<lane>/` convention for on-disk runtime artifacts
  (`CORE_TRANSACTION_JOURNAL_DIR = "procedural/reports/core/transaction"`).
- `tools/wfcore/tri.py:135-149` — `tri.conj(values)` sets `saw_unknown` only
  from values it actually iterates; `tri.conj([])` never enters the loop and
  falls through to `return SATISFIED`
  [verified — read `tri.py:135-149` directly]. Any fold over a criterion set
  that can be silently incomplete (a declared criterion simply not supplied to
  the fold) inherits this: an empty or partial evaluation set reads as
  vacuously satisfied, not as "nothing was checked." §9/§11 close this with a
  completeness gate that runs *before* the fold, so `tri.conj` is only ever
  called over a set the caller has already proven equals the policy's own
  declared criterion set.
- No signing, key-management, or reviewer-identity infrastructure exists
  anywhere in this repository today [verified — `grep -rniE
  "gpg|hmac|reviewer|signing_key|pubkey|attestation" tools/wfcore
  tools/pipeline --include=*.py` returns nothing under either directory].
  §9/§11's human-review attestation design (§9, Fix 3) is therefore built from
  what the repository already has — git itself, and `hashlib` — rather than
  assuming a key-management system that does not exist; the part that
  genuinely requires new infrastructure (a registry of which signer
  fingerprints are authorized reviewers) is named and deferred, not silently
  assumed away (§20).

## 3. Strategic meaning

Q3 rejected "declared gates passed ⇒ production quality" as a lie of omission
and rejected fabricating subjective quality as a number as a lie of fabrication.
This mission is the one artifact that makes both honest: it is the only place
in the platform allowed to say `production_quality`, and it can only say it when
a real, attributable human signed a real review of a real build. `T1` and `T2`
cannot honestly evaluate what they produced without this policy shape to judge
against — `T3.md:39-42` states T3 "feeds the evidence schema `T1` and `T2` both
need."

The same "no lie of omission" standard this mission exists to enforce on `T1`/
`T2` applies reflexively to the fold that computes the two claims (§9, Fix 1):
a policy that silently accepts an incomplete evaluation set would be exactly
the fake-green this mission was chartered to prevent, just moved one layer
down.

## 4. Scope

- A new `tools/wfcore/policy/` package: `acceptance_policy.py` (schema,
  validators, hashing, immutability, fold) and `test_policy.py` (negative-first
  suite).
- New WF1297–WF1299 failure-code constants in `tools/pipeline/failure_codes.py`,
  additive only.
- The on-disk policy registry convention (`procedural/reports/core/policy/`)
  and the `publish_policy()` write path that enforces immutability via atomic
  exclusive file creation (§9, Fix 2) — never a read-compare-write sequence.
- The two claim evaluators (`accepted_by_declared_policy`,
  `production_quality`) as pure functions over a policy record + a *complete*
  set of criterion evaluations (§9, Fix 1), returning one
  `wf.core.policy_evaluation.v1` result record.
- A concrete, verifiable human-review attestation schema (§9, Fix 3) and a
  concrete runtime-measurement evidence schema (§9, Fix 4) — both new record
  shapes this contract fully specifies, in place of the free-text
  `reviewer_identity` string and opaque `environment_profile_id` the original
  draft under-specified.
- Documentation of the exact interface `T1`/`T2` must adopt to fold a
  `policy_hash` into their own operation identity (specified here; **not**
  wired into `transaction/executor.py`, `acceptance/evaluate.py`, or
  `pipeline/run_wfcore_transaction.py` by this mission — see Non-goals).

## 5. Non-goals

- **No modification to `tools/wfcore/acceptance/evaluate.py`,
  `tools/wfcore/transaction/delta.py`, `tools/wfcore/transaction/executor.py`,
  or `tools/pipeline/run_wfcore_transaction.py`.** T3 has no ticket
  dependencies and must not become a hidden prerequisite edit to files three
  other tickets (`T1`, `T2`, `T5`) also touch. The policy's machine-invariant
  criterion class *cites* an existing `wf.core.acceptance_result.v1` /
  `wf.core.acceptance_finding.v1` record by id; it does not change how those
  records are produced.
- **No wiring into `T1`'s adapter or `T2`'s entry point.** Those are separate,
  currently-blocked tickets (`map.md:52-53`). This contract specifies the
  interface they must consume (§7, §9); actually consuming it is their
  contract, not this one's task list.
- **Not a repair/retry mechanism.** A policy version never changes a
  threshold in place; the only lifecycle action this mission implements is
  "publish a new immutable version" and "detect an attempt to mutate an
  existing one." Rerunning an operation under a new policy version is an
  operational procedure this contract documents (§9) but does not automate.
- **Not `CLEANUP-1` or `DOC-1`.** The dirty working tree and the D19/run-state
  reconciliation are separate, already-scoped tickets; this mission's tasks
  touch only the files named in §11.
- **No LLM integration code.** The advisory-evidence record shape is defined
  (§7) so a future caller can populate it, but no LLM-calling code, prompt, or
  client is written here.
- **No `REVIEWER_REGISTRY` (the fingerprint-to-reviewer mapping) is built,
  populated, or wired here.** §9 Fix 3 specifies the human-review attestation
  *schema* and the *verification contract* against such a registry, and
  specifies that its absence must fold to `UNKNOWN` — never to a silent
  `True`. Designing the registry's own schema, provisioning process, and
  key-rotation policy is out of scope for T3 and is flagged as a real,
  load-bearing follow-up (§20), not solved by assumption.
- **No environment-profile registry (id → expected `profile_digest`) is
  built here.** §9 Fix 4 requires every runtime measurement to carry its own
  `profile_digest` as evidence of what was actually measured, but pinning
  that digest against a *declared expected* digest for a named profile is not
  implemented — this was already flagged as a gap in the original contract's
  §20 and remains genuinely open (§20).
- **No general-purpose cross-process locking utility is introduced.** §9 Fix 2
  uses one OS primitive (`O_CREAT | O_EXCL`) local to `publish_policy`; this
  mission does not build a reusable lock-file manager for other lanes to
  adopt.

## 6. Blast-radius summary

Additive-only mission; no `connected-impact-sweep` is required.

- **New files** (§11): zero existing consumers to break.
- **`tools/pipeline/failure_codes.py`**: shared, load-bearing, single source of
  truth (`failure.py:9-17`). The collision risk that mattered — T4 also
  claiming numbers in this band — is now resolved by direct verification
  (§2): T4's own contract claims `WF1296` and states `WF1297–1299` are the
  numbers left; this contract claims exactly those three, so T3 and T4 no
  longer have an unresolved race over the same numbers. `T3.0` remains a
  live-file re-check immediately before writing (§11), because a *third*
  sibling ticket (`T1`, `T2`, `DOC-1`) landing first and claiming one of
  1297–1299 is still a real, if smaller, residual risk this discovery step
  exists to catch — if that happens, T3.0 stops and this contract's number
  allocation is revisited rather than silently shifted.
- **`docs/contracts/`**: this file is revised in place; no other contract doc
  is edited.
- **`tools/wfcore_shield.py`**: unmodified; its discovery walk (`:47-61`)
  picks up the new suite automatically. Verify this claim as part of T3.4
  rather than assuming it (§11).

## 7. Contracts / seams involved

| Seam | Owner | What T3 does with it |
|---|---|---|
| `wfcore.tri` (`tools/wfcore/tri.py`) | tri-value authority | Reused verbatim: `tri.conj`, `tri.accepts`, `tri.UNKNOWN`, `tri.from_bool`. No re-derivation. `tri.conj`'s empty-iterable identity (`conj([]) == SATISFIED`, `tri.py:135-149`) is treated as a documented property of the primitive, never called directly on an unvalidated set (§9 Fix 1). |
| `wfcore.constraints` (`tools/wfcore/constraints.py`) | constraint-class authority | Reused for **pattern**, not values: T3's 3 `criterion_class` values are a *new, parallel* closed taxonomy at the policy layer, not a re-slicing of the 8 constraint classes. `constraints.ACCEPTANCE_LOAD_BEARING`-style "closed set that may block a claim" is the template for `POLICY_ACCEPTED_CLASSES` (§9), and `constraints.py:108-109`'s `SCORING_CLASSES` structural-exclusion pattern is the template for keeping `advisory_evidence` out of the human-review fold. |
| `wfcore.contracts.acceptance_criteria` (`tools/wfcore/contracts/acceptance_criteria.py`) | consumer acceptance-criteria authority | Cited by reference (`criteria_id`/`request_id`), never re-implemented. |
| `wfcore.acceptance.evaluate` (`tools/wfcore/acceptance/evaluate.py`) | acceptance-verdict authority | A `machine_invariant` policy criterion's evidence *is* a `wf.core.acceptance_finding.v1` record this module already produces (`evaluate.py:166-169`). T3 reads its `constraint_id`/`evaluation`/`schema_version` fields; it does not call `evaluate_acceptance()` and does not modify the module. `evaluate.py`'s `EVIDENCE_REQUIRED` shape (`evaluate.py:159-160`, in particular `evidence_refs`) is the direct template for T3's new runtime-measurement schema (§9 Fix 4) — a derived number must carry pointers to the raw evidence that produced it, the same rule `evaluate.py` already enforces for acceptance evidence. |
| `wfcore.failure` (`tools/wfcore/failure.py`) | the one failure-code authority | Exactly three new WF12xx constants added there — `WF1297`, `WF1298`, `WF1299` — per `failure.py:29-36`'s rule: a constant needs a real raise site and a negative test, or it is dead weight. Each of the three now covers several failure *causes*, distinguished in the raising code's `detail` string, never by a separate constant per cause (§15). |
| `wfcore_shield.py` (`tools/wfcore_shield.py`) | Core's single gate | Auto-discovers `tools/wfcore/policy/test_policy.py`; no edit needed, verified not assumed (T3.4). |
| `procedural/reports/core/<lane>/` convention | `transaction/executor.py:93` | Extended by one new lane: `procedural/reports/core/policy/`. |
| Git, as the reviewer-attestation substrate | this repository itself | New in this revision (§9 Fix 3): a `human_review` record's attestation binds to a signed git commit hash, verified by re-deriving the signer and the commit's actual diff — never a stored, unverifiable claim. The one piece this seam does *not* yet provide — a registry mapping signer fingerprint → authorized reviewer identity — is named as a deferred dependency, not invented here (§5, §20). |

## 8. Human decisions required

None block this contract. Two naming/spelling calls were made rather than
asked, because the cost of being wrong is a rename, not a redesign:

- `criterion_class` values are spelled `machine_invariant` / `runtime_budget` /
  `human_review` — short paraphrases of `T3.md:18-26`'s own three class names,
  chosen because `T1`/`T2` will hardcode these strings and shorter names
  reduce the chance of a typo'd enum member going unnoticed. If a different
  spelling is preferred, it is a find-and-replace across
  `tools/wfcore/policy/*.py` before those constants are consumed elsewhere —
  flagged here so nobody discovers it after `T1` has already copied the
  strings.
- **New in this revision**: the failure-code consolidation names —
  `CORE_POLICY_INVALID` (shape), `CORE_POLICY_REGISTRY_VIOLATION` (write-path
  integrity), `CORE_POLICY_VERDICT_UNTRUSTWORTHY` (evaluation-time
  trustworthiness) — are a three-way split by *pipeline phase* (authoring-time
  validation / registry write / evaluation-time fold), not by criterion class
  or by original failure mode. This is a deliberate axis choice: it keeps
  each code's raise sites textually close together in the module (one
  function family per code) rather than scattered. If a reviewer prefers a
  split by criterion class instead, that is a `detail`-string and
  documentation change only — no record shape or evaluator logic depends on
  which of the three codes a given `detail` is filed under.
- Two genuinely open questions are deferred rather than decided here, because
  deciding them would mean designing infrastructure this contract's scope
  does not cover (§5, §20): the `REVIEWER_REGISTRY` shape/provisioning, and
  the environment-profile registry for pinned `profile_digest` verification.

## 9. Implementation strategy

**Decided shape**, and why the alternative was rejected:

- **Compose with the existing acceptance pipeline for class 1, do not
  duplicate it.** `evaluate.py:1-95`'s own docstring states the house rule
  explicitly: a second implementation of the same authority "would drift the
  first time the taxonomy grows a class... silently." A `machine_invariant`
  policy criterion therefore carries a `source_finding_ref` pointing at an
  existing `wf.core.acceptance_finding.v1` record's `(result_id,
  constraint_id)`, and its tri-valued verdict *is* that finding's
  `evaluation` field, re-read at fold time — never re-computed. Rejected
  alternative: give the policy its own independent hard-invariant evaluator
  duplicating `constraints.fold_acceptance`. Rejected because it is exactly
  the "second authority" pattern `failure.py` and `evaluate.py` both name as
  the recurring mistake this repository is built against.
- **One shared criterion envelope, three polymorphic `decision` shapes.**
  Every criterion — regardless of class — carries the same five things the
  ticket names (`T3.md:28-30`): `evaluator`, `source_evidence`,
  `decision` (threshold *or* reviewer decision, shaped per class),
  `freshness_window_s`, `verdict`. This mirrors `constraints.py`'s own
  per-class field polymorphism (`validate_constraint`'s `if klass == BUDGET`
  / `if klass == TOLERANCE` branches) rather than inventing three unrelated
  record types.
  - `machine_invariant.decision` = `{"source_finding_ref": {"result_id":
    str, "constraint_id": str}}`.
  - `runtime_budget.decision` = `{"subject": str, "limit": number, "unit":
    str, "comparison": "at_most"|"at_least", "environment_profile_id": str}`.
    The criterion still declares an `environment_profile_id` *label* (not a
    digest) — a criterion is authored before any measurement exists, so it
    cannot pre-declare the digest of a future measured environment without a
    profile registry this mission does not build (§5, §20). What changes in
    this revision is the *measurement side* (Fix 4, below): the measurement
    a criterion is judged against must now carry its own `profile_digest`,
    closing the "opaque id" half of the gap even though the "pin the id to
    an expected digest" half stays open.
  - `human_review.decision` = the human-review record (Fix 3, below).
- **Freshness is a generalization of `evaluate.py`'s staleness rail, not a
  new idea.** `evaluate.py:257-275`'s `evidence_staleness()` already compares
  an evidence row's ordinal against the operation under judgement and returns
  a named stale reason rather than silently dropping the row. T3's
  `criterion_evidence_staleness(criterion, evidence_row, judged_at)` is the
  same shape, generalized to a *declared window* (`freshness_window_s`)
  instead of a hardcoded "must not predate the delta" rule, because policy
  criteria (especially `runtime_budget` and `human_review`) tolerate evidence
  measured some bounded time before the operation, not only evidence from the
  exact operation.
- **The two claims are one fold function, over a set the caller has already
  proven complete.** This is where the original draft had a real bug
  (§2, verified via `tri.py:135-149`): `tri.conj([])` returns `SATISFIED`,
  so a fold that simply iterates whatever `criterion_evaluations` a caller
  happened to pass in would let an omitted criterion — including a violated
  one, including *every* declared criterion — silently disappear from the
  result instead of blocking it. The fix is a hard completeness gate that
  runs **before** the fold and can only ever produce a rejection, never a
  verdict:

  ```
  def check_criterion_evaluation_completeness(policy, criterion_evaluations):
      """List[Check]. Empty list == the evaluation set is safe to fold.

      Not a fold input filter -- a gate. `evaluate_policy_claims` refuses to
      run tri.conj at all while this returns anything, because tri.conj has
      no way to distinguish "I looked at everything and it's fine" from
      "I was handed an empty or partial set." That distinction has to be
      established before the fold, by something whose only job is looking at
      set membership, not at verdicts.
      """
      declared_ids = {c["criterion_id"] for c in policy["criteria"]}
      supplied_ids = [c["criterion_id"] for (c, v) in criterion_evaluations]

      checks = []
      missing = declared_ids - set(supplied_ids)
      if missing:
          checks.append(_fail(F.CORE_POLICY_VERDICT_UNTRUSTWORTHY,
              "missing_criterion_evaluation: policy {!r} declares {} but "
              "evaluation set omits {}".format(policy["policy_id"],
              sorted(declared_ids), sorted(missing))))

      dupes = sorted({cid for cid in supplied_ids
                      if supplied_ids.count(cid) > 1})
      if dupes:
          checks.append(_fail(F.CORE_POLICY_VERDICT_UNTRUSTWORTHY,
              "duplicate_criterion_evaluation: {} supplied more than once"
              .format(dupes)))

      foreign = sorted(set(supplied_ids) - declared_ids)
      if foreign:
          checks.append(_fail(F.CORE_POLICY_VERDICT_UNTRUSTWORTHY,
              "foreign_criterion_evaluation: {} not declared by policy {!r}"
              .format(foreign, policy["policy_id"])))
      return checks


  def evaluate_policy_claims(policy, criterion_evaluations):
      """(Optional[dict], List[Check]).

      `(None, checks)` with checks non-empty means: no verdict was computed,
      because the caller did not supply an evaluation for exactly the
      policy's own declared criterion set. `(record, [])` means the record
      below was computed by folding a verified-complete set. There is no
      third shape where a record exists but is flagged invalid -- an
      incomplete set never reaches the fold, so it can never produce a
      verdict for a caller to misread.
      """
      completeness = check_criterion_evaluation_completeness(
          policy, criterion_evaluations)
      if completeness:
          return None, completeness

      declared_verdict = tri.conj(v for (c, v) in criterion_evaluations
                                   if c["criterion_class"] in
                                   (MACHINE_INVARIANT, RUNTIME_BUDGET))
      accepted_by_declared_policy = tri.accepts(declared_verdict)

      human_verdicts = [v for (c, v) in criterion_evaluations
                         if c["criterion_class"] == HUMAN_REVIEW]
      # A policy with ZERO human_review criteria can NEVER claim
      # production_quality -- explicit UNKNOWN, not vacuous SATISFIED.
      quality_verdict = (tri.conj([declared_verdict] + human_verdicts)
                         if human_verdicts else tri.UNKNOWN)
      production_quality = tri.accepts(quality_verdict)

      return {
          "policy_id": policy["policy_id"],
          "policy_version": policy["policy_version"],
          "policy_hash": policy["policy_hash"],
          "judged_operation_id": ...,
          "criterion_evaluations": criterion_evaluations,
          "declared_verdict": declared_verdict,
          "accepted_by_declared_policy": accepted_by_declared_policy,
          "quality_verdict": quality_verdict,
          "production_quality": production_quality,
          "schema_version": RT_POLICY_EVALUATION,
      }, []
  ```

  Two guards now compose instead of one: completeness (new, this revision)
  guarantees `tri.conj` is only ever called over the exact set the policy
  declared, and the `if human_verdicts else tri.UNKNOWN` line (unchanged
  from the original draft) guarantees `production_quality` cannot silently
  equal `accepted_by_declared_policy` merely because nobody declared a
  review criterion. Neither guard substitutes for the other: completeness
  closes the "criterion silently dropped" hole; the human-verdicts guard
  closes the "no review criterion ever existed" hole. Once completeness
  holds, the fold's `UNKNOWN`-unless-fully-measured behavior falls out of
  `tri.conj`'s own semantics for free — every per-class evaluator below
  already returns `tri.UNKNOWN` for anything it cannot actually measure
  (`evaluate_machine_invariant` on no matching finding, `evaluate_runtime_budget`
  on a mismatched or absent measurement, `evaluate_human_review` on an absent
  or unverifiable review), so an unmeasured criterion cannot be dropped
  (completeness gate) and cannot be counted as passing (each evaluator's own
  UNKNOWN default) — there is no path left for silence to read as success.
  Mirrors `constraints.py:313-323`'s `constraint_set_has_load_bearing_member`
  rail, generalized from "constraint set" to "policy", now applied at both
  the membership layer (completeness) and the class layer (human-verdicts
  guard).
- **Advisory evidence is structurally excluded from the fold, not
  filtered.** The human-review verdict is computed as a pure function of
  `(reviewer_decision, reviewer_attestation, reviewed_build_hash,
  reviewed_map_hash)` matched against the judged operation. `advisory_evidence`
  is a sibling field on the same record, never read by the verdict function —
  the same structural-exclusion pattern `constraints.SCORING_CLASSES` uses to
  keep soft preferences out of `fold_acceptance` (`constraints.py:108-109`):
  it cannot leak into the verdict because the fold function's source never
  names the field, not because a runtime check happens to catch it.
- **Fix 3 — a verifiable reviewer attestation, built from what this repo
  already has.** A non-empty `reviewer_identity` string proves nothing: it is
  typed by whoever calls the function, including the code under review. The
  original draft's `evaluate_human_review` required exactly this — fixed
  here by replacing the free-text field with a re-derivable fact, following
  this repository's own house rule (`evaluate.py`'s "never trust a stored
  judgement, recompute it" discipline, e.g. `_recompute_from_record`).
  `RT_HUMAN_REVIEW` now requires:
  `policy_hash`, `judged_operation_id`, `reviewed_build_hash`,
  `reviewed_map_hash`, `reviewer_decision` (∈ `HUMAN_REVIEW_DECISIONS`),
  `reviewed_at`, and a new nested `reviewer_attestation` object:
  `{"identity_source": "signed_git_commit", "commit_hash": <40-hex str>,
  "commit_signer_key_fingerprint": <str, read from git, never typed by the
  caller>, "schema_version": RT_REVIEWER_ATTESTATION}`.
  `ATTESTATION_SOURCES = ("signed_git_commit",)` — a closed, single-member
  vocabulary today, deliberately extensible later, mirroring
  `ADVISORY_SOURCE_KINDS`'s own "closed, extend visibly later" convention.
  `verify_human_review_attestation(review, repo_root)` shells out to git
  (`git log --show-signature -1 <commit_hash>`, `git show <commit_hash>`) to
  re-derive, never trust: (a) that `commit_hash` names a real, signed commit
  and extract its actual signer key fingerprint; (b) that the commit's own
  diff contains this exact `human_review` record's canonical bytes (so a
  valid old signed commit hash cannot be pasted onto a different review —
  the replay case); (c) whether the signer's fingerprint appears in
  `REVIEWER_REGISTRY` as an authorized reviewer. Because (c) depends on a
  registry this mission does not build (§5), the function returns
  `tri.UNKNOWN` — not `tri.SATISFIED` — for the whole attestation whenever
  `REVIEWER_REGISTRY` is absent or the fingerprint is not found there, and
  `tri.VIOLATED` when the signature or the content-binding check in (a)/(b)
  fails outright. **A `human_review` criterion can therefore never reach
  `SATISFIED` until a real `REVIEWER_REGISTRY` exists** — this is the same
  "absence is UNKNOWN, never quietly accepted" discipline `evaluate.py` and
  `tri.py` already apply everywhere else in this codebase, extended one
  layer deeper: declaring a review with no way to verify *who* reviewed is
  its own species of vacuous claim. `evaluate_human_review(criterion, review,
  judged_build_hash, judged_map_hash, judged_at) -> str` folds all of the
  above: `UNKNOWN` if `review` is `None`, if `reviewer_decision` is not in
  `HUMAN_REVIEW_DECISIONS`, if the attestation check above returns anything
  but `SATISFIED`, or if stale per `freshness_window_s`; `UNKNOWN` (reason
  `review_hash_mismatch`) if `reviewed_build_hash`/`reviewed_map_hash`
  disagree with the judged operation's actual hashes; else `SATISFIED` iff
  `reviewer_decision == "approve"`, else `VIOLATED`. `advisory_evidence` is
  never read by this function.
- **Fix 4 — runtime measurement is evidence, not a single trusted number.**
  The original draft passed `evaluate_runtime_budget` an untyped
  `measurement: dict` with no defined shape beyond an `environment_profile_id`
  string compared for equality — exactly the "opaque id, not a real schema"
  gap named in this revision's brief. New record type
  `RT_RUNTIME_MEASUREMENT = "wf.core.policy_runtime_measurement.v1"`,
  required fields: `subject` (str, what was measured — must match
  `criterion["decision"]["subject"]`), `unit` (str, must match), `value`
  (number), `environment_profile_id` (str, the declared-profile label,
  compared as before), `profile_digest` (str, sha256 hex of the canonical
  serialization of the actual measured environment envelope — hardware
  descriptor, engine build id, declared measurement conditions — computed by
  the measuring tool from what it actually ran on, never typed by hand;
  **required**, so a measurement record with no digest fails shape
  validation before it can be judged against anything), `judged_operation_id`,
  `build_hash`, `map_hash` (binding to the operation under judgement, mirroring
  `reviewed_build_hash`/`reviewed_map_hash` on the human-review record),
  `measured_at` (ordinal, same convention as `evidence_staleness`),
  `evidence_refs` (list of str — pointers to the raw evidence backing the
  number, mirroring `evaluate.py`'s own `EVIDENCE_REQUIRED.evidence_refs`;
  a derived value with no evidence pointer is exactly what `evaluate.py`
  already refuses to accept for acceptance evidence, and this schema holds
  runtime measurements to the same bar), `schema_version`.
  `evaluate_runtime_budget(criterion, measurement, judged_at) -> str` — `UNKNOWN`
  if `measurement` fails `validate_runtime_measurement` shape checks (missing
  `profile_digest` included); `UNKNOWN` (reason
  `measured_outside_declared_environment`) if
  `measurement["environment_profile_id"] !=
  criterion["decision"]["environment_profile_id"]`; `UNKNOWN` if stale per
  `criterion_evidence_staleness`; else `tri.from_bool` against `limit` +
  `comparison`. **What this does not yet do, named rather than assumed away**:
  it does not pin `profile_digest` against a pre-declared *expected* digest
  for the profile id — that requires an environment-profile registry this
  mission does not build (§5, carried forward from the original contract's
  own §20 gap). What changes today is that the digest is now captured as
  required evidence on every measurement, closing the "we can't even tell
  what was actually measured" half of the problem, while the "pin it to a
  known-good hardware fingerprint" half stays an open follow-up.
- **Immutability is enforced by an atomic write primitive, not a
  read-compare-write sequence.** The original draft specified `publish_policy`
  as read-existing → compare hash → write, which is a TOCTOU race between two
  concurrent publishers of the same `(policy_id, policy_version)`, and it
  treated an identical-hash republish as a permitted no-op — a hash-based
  dedup shortcut that is itself a silent-overwrite risk if the comparison
  logic is ever wrong. Both are fixed by changing the write mechanism, not by
  adding a lock manager:
  1. `validate_acceptance_policy(policy, strict=True)` runs first, including
     the new grammar rail on `policy_id`/`policy_version` (below). Any
     failing check aborts before any file activity.
  2. `compute_policy_hash(policy)` as before: `hashlib.sha256` over
     `json.dumps({k: v for k, v in policy.items() if k != "policy_hash"},
     sort_keys=True, separators=(",", ":"))`, hex digest.
  3. `os.makedirs(os.path.join(repo_root, registry_dir, policy_id),
     exist_ok=True)` — directory creation is idempotent and safe under
     concurrent callers by construction; no lock needed for it.
  4. The write itself: `fd = os.open(target_path, os.O_CREAT | os.O_EXCL |
     os.O_WRONLY)`. `O_EXCL` makes existence-check-and-create one atomic
     syscall — there is no window between "check if it exists" and "create
     it" for a second writer to land in, which is exactly what a
     read-compare-write sequence cannot guarantee. On success: write the
     canonical bytes, `os.fsync(fd)`, then `os.close(fd)` — the write is not
     considered durable until `fsync` returns without error, and
     `publish_policy` must not report success before that point.
  5. On `FileExistsError`: `(policy_id, policy_version)` is already
     published. **Rejected unconditionally, whether the incoming content is
     byte-identical or different** — this reverses the original draft's
     "identical hash may proceed as a no-op" behavior on purpose: immutable
     means immutable, not "immutable unless you happen to submit the same
     bytes twice." The failing check names which case it was (identical vs.
     different content, read back from the existing file for the `detail`
     string only — never used to decide whether to write) under
     `CORE_POLICY_REGISTRY_VIOLATION`.
  This local platform primitive is sufficient for this mission's actual
  concurrency model — independent CLI/agent processes writing to a shared
  local checkout, per §6's own "sibling tickets could race on shared state"
  framing — and needs no cross-process lock file or lock manager (§5).
  `verify_policy_hash(policy) -> bool` is unchanged: re-derives the hash from
  the record's own fields and compares to the stored `policy_hash` — the
  `CORE_POLICY_REGISTRY_VIOLATION` raise site for on-disk tampering/corruption
  detection, distinct from the write-time raise site above but sharing the
  same code (§15).
- **A safe, concrete grammar for `policy_id`/`policy_version`, used as path
  components.** Both are validated against
  `^[a-z0-9][a-z0-9_-]{0,63}$` — lowercase alphanumeric plus `_`/`-`, 1–64
  characters, must start with an alphanumeric. The deliberate choice here is
  excluding `.` from the charset **entirely**, rather than allowing dots and
  special-casing `..`: a grammar that cannot spell `.` cannot spell `..`
  either, so path traversal via either component is structurally
  unrepresentable instead of defended against by a second check that could
  itself have a bug. The cost is that a version string like `v1.2.3` must be
  spelled `v1-2-3` under this grammar — a one-time, cheap constraint, since
  `T1`/`T2` mint these strings programmatically rather than accepting free
  user text (§8's `criterion_class` note makes the same trade for the same
  reason). `/`, `\`, and any character outside the charset are rejected by
  construction, not enumerated as a blocklist. This check lives in
  `validate_acceptance_policy` (`CORE_POLICY_INVALID`, §15) — it is a shape
  rail on two already-required fields, not new registry-write logic.

## 10. Task graph

```
T3.0 (discovery, no deps)
  └─> T3.1 (package skeleton + schema + grammar) ──> T3.2 (hashing + atomic registry write)
                                                   ──> T3.3 (criterion evaluation + completeness gate + fold + claims)
        T3.2, T3.3 ──> T3.4 (negative-first suite + shield discovery proof)
        T3.4 ──> T3.5 (failure-code registration + validate_failure_codes proof)
        T3.5 ──> T3.6 (docstring/house-style pass + final full-suite proof)
```

T3.2 and T3.3 are independent of each other (both depend only on T3.1) and may
be worked in parallel by two agents; everything else is strictly sequential
because each later task's verify step depends on the previous task's code
existing.

## 11. Task-by-task plan

**T3.0 — Confirm WF1297–WF1299 remain free against the live file (depends: none)**

- Purpose: this revision fixes the exact three numbers this mission uses
  (§2) — WF1297, WF1298, WF1299 — rather than proposing a range to discover.
  T3.0's job is to re-verify that fact at implementation time, not to pick
  numbers.
- Files: `tools/pipeline/failure_codes.py` (read-only in this task).
- Action: run the enumeration this contract used (`code_number()` over every
  `FailureCode` constant, filtered to 1200–1299); confirm the current max is
  still `1290`, or if higher, confirm the increase is `WF1296` (T4 landing
  first is expected and harmless — it does not touch T3's allocation).
  Confirm none of `WF1297`, `WF1298`, `WF1299` individually exist yet. If any
  of the three has been claimed by a different ticket since this contract was
  written, **stop** — this contract's allocation must be revised, not
  silently reassigned to the next free numbers, because §15's three-code
  design is deliberately built around exactly these three numbers appearing
  together in one section comment.
- Check: none (discovery only).
- Verify:
  1. `cd tools && PYTHONUTF8=1 python -c "import sys; sys.path.insert(0,'pipeline'); from failure_codes import FailureCode, code_number; nums=sorted(code_number(v) for k,v in vars(FailureCode).items() if not k.startswith('_') and isinstance(v,str)); print(max(n for n in nums if 1200<=n<=1299))"` — expected `1290` or `1296`.
  2. `cd tools/pipeline && grep -n "WF1297\|WF1298\|WF1299" failure_codes.py` — must print nothing.
- Risk/rollback: none — read-only.

**T3.1 — Package skeleton + policy/criterion/measurement schema (depends: T3.0)**

- Purpose: establish `tools/wfcore/policy/` and the record shapes for the
  policy artifact, its three criterion kinds, the human-review attestation,
  and the runtime-measurement evidence record, with shape validators only
  (no hashing, no fold, no atomic write, no attestation verification yet).
- Files:
  - `tools/wfcore/policy/__init__.py` (NEW) — house-style module docstring
    (mirrors `tools/wfcore/acceptance/__init__.py:1-51`'s "WHAT THIS LAYER IS
    FOR" / "HOUSE STYLE" shape), `__all__` naming the public entry points.
  - `tools/wfcore/policy/acceptance_policy.py` (NEW) — the schema:
    `RT_ACCEPTANCE_POLICY = "wf.core.acceptance_policy.v1"`,
    `RT_POLICY_CRITERION = "wf.core.policy_criterion.v1"`,
    `RT_HUMAN_REVIEW = "wf.core.policy_human_review.v1"`,
    `RT_REVIEWER_ATTESTATION = "wf.core.policy_reviewer_attestation.v1"`,
    `RT_RUNTIME_MEASUREMENT = "wf.core.policy_runtime_measurement.v1"`,
    `RT_ADVISORY_EVIDENCE = "wf.core.policy_advisory_evidence.v1"`,
    `RT_POLICY_EVALUATION = "wf.core.policy_evaluation.v1"`.
    `CRITERION_CLASSES = (MACHINE_INVARIANT, RUNTIME_BUDGET, HUMAN_REVIEW)`
    (§8 spelling). `POLICY_ACCEPTED_CLASSES = (MACHINE_INVARIANT,
    RUNTIME_BUDGET)` — the closed set folded into
    `accepted_by_declared_policy`, mirroring
    `constraints.ACCEPTANCE_LOAD_BEARING`'s "one visible tuple" pattern
    (`constraints.py:93-106`).
    `POLICY_CRITERION_REQUIRED = ("criterion_id", "criterion_class",
    "evaluator", "source_evidence", "decision", "freshness_window_s",
    "verdict", "schema_version")`.
    `POLICY_REQUIRED = ("policy_id", "policy_version", "policy_hash",
    "criteria", "schema_version")`.
    `POLICY_ID_GRAMMAR = POLICY_VERSION_GRAMMAR =
    re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")` (§9 Fix 2).
    `HUMAN_REVIEW_REQUIRED = ("policy_hash", "judged_operation_id",
    "reviewed_build_hash", "reviewed_map_hash", "reviewer_decision",
    "reviewed_at", "reviewer_attestation", "schema_version")`.
    `ATTESTATION_SOURCES = ("signed_git_commit",)` (§9 Fix 3, closed, extend
    visibly later). `REVIEWER_ATTESTATION_REQUIRED = ("identity_source",
    "commit_hash", "commit_signer_key_fingerprint", "schema_version")`.
    `RUNTIME_MEASUREMENT_REQUIRED = ("subject", "unit", "value",
    "environment_profile_id", "profile_digest", "judged_operation_id",
    "build_hash", "map_hash", "measured_at", "evidence_refs",
    "schema_version")` (§9 Fix 4).
    `ADVISORY_SOURCE_KINDS = ("llm_advisory",)` (closed, extend visibly
    later).
    `BUDGET_COMPARISONS = ("at_most", "at_least")`.
    `HUMAN_REVIEW_DECISIONS = ("approve", "reject")` — no third silent
    "pending" value; absence of the field, not a stored sentinel, means
    not-yet-reviewed.
    `validate_policy_criterion(obj, strict=False) -> List[Check]`,
    `validate_acceptance_policy(obj, strict=False) -> List[Check]` (includes
    the `POLICY_ID_GRAMMAR`/`POLICY_VERSION_GRAMMAR` rail),
    `validate_human_review(obj, strict=False) -> List[Check]`,
    `validate_runtime_measurement(obj, strict=False) -> List[Check]` (NEW,
    §9 Fix 4).
    `_example_acceptance_policy(**over)`, `_example_human_review(**over)`,
    `_example_runtime_measurement(**over)` factories (domain-neutral, per
    `hygiene.py:1-24`'s game-agnosticism gate — no consumer vocabulary in any
    example, matching `constraints._example_constraint`'s "generic
    measurable" convention at `constraints.py:341-354`).
  - `tools/wfcore/policy/test_policy.py` (NEW) — empty harness scaffold only
    in this task; real tests land in T3.4.
- Action: implement the shapes and shape-only validators above, including the
  grammar rail. No hashing, no fold, no atomic write, no git-based attestation
  verification yet — those are T3.2/T3.3.
- Check: `validate_acceptance_policy(_example_acceptance_policy())`,
  `validate_human_review(_example_human_review())`, and
  `validate_runtime_measurement(_example_runtime_measurement())` each return
  zero failing checks; a policy built with `policy_id="Bad.Id"` (uppercase and
  a dot) fails the grammar rail.
- Verify: `cd tools && PYTHONUTF8=1 python -c "from wfcore.policy import acceptance_policy as P; ex = P._example_acceptance_policy(); bad = [c for c in P.validate_acceptance_policy(ex) if not c[1]]; print('OK' if not bad else 'FAIL', bad)"` must print `OK []`.
- Risk/rollback: new files only; delete the `policy/` directory to roll back.

**T3.2 — Content hash + atomic immutable registry write (depends: T3.1)**

- Purpose: implement `compute_policy_hash()` and `publish_policy()` using the
  atomic-exclusive-create mechanism specified in §9 Fix 2 — no
  read-compare-write sequence anywhere in this task.
- Files: `tools/wfcore/policy/acceptance_policy.py` (extend).
- Action:
  - `compute_policy_hash(policy: dict) -> str` — unchanged from the original
    draft: `hashlib.sha256` over `json.dumps({k: v for k, v in policy.items()
    if k != "policy_hash"}, sort_keys=True, separators=(",", ":"))`, hex
    digest.
  - `REGISTRY_DIR = "procedural/reports/core/policy"` (extends the
    `executor.py:93` convention).
  - `publish_policy(policy, repo_root, registry_dir=REGISTRY_DIR) ->
    Tuple[Optional[dict], List[Check]]` — implements the five-step sequence
    in §9 Fix 2 exactly: validate (strict, including grammar) → compute hash
    → `os.makedirs(..., exist_ok=True)` → `os.open(path, O_CREAT|O_EXCL|
    O_WRONLY)` → write + `fsync` + close on success, or a failing
    `CORE_POLICY_REGISTRY_VIOLATION` check (content read back only for the
    `detail` string) on `FileExistsError`, **with no branch that allows a
    write to proceed against an existing path under any condition**.
  - `verify_policy_hash(policy) -> bool` — re-derives the hash from the
    record's own fields and compares to the stored `policy_hash`; the
    `CORE_POLICY_REGISTRY_VIOLATION` raise site for on-disk tampering.
- Check: `validate_acceptance_policy` extended with the hash-presence/format
  rail; `verify_policy_hash` re-derivation rail added.
- Verify:
  1. `cd tools && PYTHONUTF8=1 python -c "from wfcore.policy import acceptance_policy as P; a=P._example_acceptance_policy(); h1=P.compute_policy_hash(a); a2=dict(a); a2['policy_hash']=h1; print(P.verify_policy_hash(a2))"` must print `True`.
  2. In a temp `registry_dir` (use the scratchpad): publish v1 → succeeds.
     Republish v1 with a **changed** threshold → fails with
     `CORE_POLICY_REGISTRY_VIOLATION`, no file overwritten (byte-compare the
     file before/after). Republish v1 with **byte-identical** content → also
     fails with `CORE_POLICY_REGISTRY_VIOLATION` (this is the fixture that
     proves the old "identical hash is a no-op" behavior is actually gone,
     not just redocumented).
  3. Two publishers racing the same `(policy_id, policy_version)` in
     parallel processes (a scripted verify, not a unit-test requirement):
     exactly one succeeds, the other observes `FileExistsError` inside
     `publish_policy` and returns the failing check — never a corrupted or
     partially-written file.
- Risk/rollback: new functions only in a new module; no existing writer
  touched.

**T3.3 — Criterion evaluation, completeness gate, attestation, and the two
claims (depends: T3.1)**

- Purpose: implement `criterion_evidence_staleness()`, the completeness gate,
  per-class evidence evaluation (including the updated runtime-measurement
  and human-review evaluators), and `evaluate_policy_claims()` exactly as
  specified in §9.
- Files: `tools/wfcore/policy/acceptance_policy.py` (extend).
- Action:
  - `check_criterion_evaluation_completeness(policy, criterion_evaluations)
    -> List[Check]` — exactly the §9 Fix 1 pseudocode: missing / duplicate /
    foreign criterion IDs, each its own failing check under
    `CORE_POLICY_VERDICT_UNTRUSTWORTHY`.
  - `evaluate_machine_invariant(criterion, finding: dict) -> str` — reads
    `finding["evaluation"]` from a supplied `wf.core.acceptance_finding.v1`
    record matching `criterion["decision"]["source_finding_ref"]`; returns
    `tri.UNKNOWN` if no matching finding is supplied (never dropped from the
    fold — mirrors `evaluate.py:345-370`'s `_recompute_from_record`).
  - `evaluate_runtime_budget(criterion, measurement: dict, judged_at) -> str`
    — per §9 Fix 4: `UNKNOWN` on a `measurement` that fails
    `validate_runtime_measurement` (including a missing `profile_digest`);
    `UNKNOWN` (reason `measured_outside_declared_environment`) on an
    `environment_profile_id` mismatch; `UNKNOWN` if stale per
    `criterion_evidence_staleness`; else `tri.from_bool` against `limit` +
    `comparison`.
  - `verify_human_review_attestation(review: dict, repo_root) -> str` (NEW,
    §9 Fix 3) — shells to git to re-derive the commit's signer fingerprint
    and confirm the commit's diff contains this exact record's canonical
    bytes; `VIOLATED` on an invalid signature or a content/commit mismatch;
    `UNKNOWN` if `REVIEWER_REGISTRY` is absent or the fingerprint is not
    found in it; `SATISFIED` only when the signature is valid, the content
    binding holds, and the fingerprint is found as an authorized reviewer.
  - `evaluate_human_review(criterion, review: dict, judged_build_hash,
    judged_map_hash, judged_at, repo_root) -> str` — `UNKNOWN` if `review` is
    `None` or `reviewer_decision` not in `HUMAN_REVIEW_DECISIONS`; `UNKNOWN`
    if `verify_human_review_attestation` does not return `SATISFIED`;
    `UNKNOWN` (reason `review_hash_mismatch`) if `reviewed_build_hash`/
    `reviewed_map_hash` disagree with the judged operation's actual hashes;
    `UNKNOWN` if stale per `freshness_window_s`; else `SATISFIED` iff
    `reviewer_decision == "approve"`, else `VIOLATED`. `advisory_evidence` is
    never read by this function (§9).
  - `evaluate_policy_claims(policy, criterion_evaluations: List[Tuple[dict,
    str]]) -> Tuple[Optional[dict], List[Check]]` — the completeness-gated
    fold in §9 Fix 1, returning `(None, failing_checks)` on an incomplete
    evaluation set or `(record, [])` on success, where `record` is a
    `wf.core.policy_evaluation.v1`: `{policy_id, policy_version, policy_hash,
    judged_operation_id, criterion_evaluations, declared_verdict,
    accepted_by_declared_policy, quality_verdict, production_quality,
    schema_version}`.
- Check: two guards are each a named test, not incidental coverage — the
  completeness gate (§9 Fix 1: a criterion silently omitted must reject, not
  fold) and the human-verdicts guard from the original draft
  (`production_quality` false/`UNKNOWN` when no `human_review` criterion
  exists).
- Verify:
  1. `cd tools && PYTHONUTF8=1 python -c "..."` — build a policy with only
     `machine_invariant`+`runtime_budget` criteria all `SATISFIED`, call
     `evaluate_policy_claims` with a *complete* evaluation set, assert
     `accepted_by_declared_policy is True and production_quality is False
     and quality_verdict == 'unknown'`.
  2. `cd tools && PYTHONUTF8=1 python -c "..."` — same policy, but omit one
     declared criterion's evaluation from the set passed to
     `evaluate_policy_claims`; assert the return is `(None, checks)` with
     `checks` non-empty and every check's code equal to
     `FailureCode.CORE_POLICY_VERDICT_UNTRUSTWORTHY` — never a record, and
     never a silent `SATISFIED`.
- Risk/rollback: new functions only.

**T3.4 — Negative-first suite + shield-discovery proof (depends: T3.2, T3.3)**

- Purpose: the real test suite, run via the module runner, plus one test
  proving `wfcore_shield.py` actually discovers it (§6's claim, verified not
  assumed).
- Files: `tools/wfcore/policy/test_policy.py` (rewrite from T3.1 scaffold).
- Action: negative-first suite mirroring `acceptance/test_acceptance.py:1-30`'s
  own stated discipline — every expected verdict re-derived from raw fields,
  never from the function under test's own helpers; a harness
  negative-control test proving the `expect_*` functions can fail. At least
  one test per sub-cause named in §15 under each of the three codes (17
  sub-causes total across `CORE_POLICY_INVALID` / `CORE_POLICY_REGISTRY_VIOLATION`
  / `CORE_POLICY_VERDICT_UNTRUSTWORTHY` — see §15/§16), plus:
  - `test_two_valued_spelling_would_have_wrongly_accepted` — the same
    headline-fake-green pattern `test_acceptance.py` names explicitly:
    assert `verdict != tri.VIOLATED` would have returned `True` on a case
    where `tri.accepts(verdict)` correctly returns `False`.
  - `test_shield_discovers_this_suite` — imports `wfcore_shield.discover_suites`
    and asserts `"wfcore.policy.test_policy"` is a member of the returned
    list.
  - `test_republish_with_identical_content_is_still_rejected` — the fixture
    named in T3.2's verify step 2, promoted to a permanent regression test:
    proves the immutability rule is "no write against an existing version,
    period," not a hash-based dedup optimization that happens to look the
    same in the common case.
  - `test_human_review_never_satisfies_without_reviewer_registry` — the §9
    Fix 3 guard: a syntactically-valid, signed-commit-referencing review with
    no `REVIEWER_REGISTRY` present must fold `UNKNOWN`, never `SATISFIED`.
- Check: the suite itself; run count must be `> 0` (mirrors
  `wfcore_shield.py:24-28`'s "discovering zero is a failure" discipline —
  the suite must assert it ran something, not just that nothing failed).
- Verify: `cd tools && PYTHONUTF8=1 python -m wfcore.policy.test_policy` must
  exit 0 and print a nonzero test count.
- Risk/rollback: test-only file; safe to delete and retry.

**T3.5 — Register the failure codes (depends: T3.4)**

- Purpose: add the 3 WF1297–WF1299 constants to
  `tools/pipeline/failure_codes.py`, each next to a comment naming the
  sub-causes it covers (matching the existing style at
  `failure_codes.py:1385-1408`), and prove the shared-registry gate stays
  green.
- Files: `tools/pipeline/failure_codes.py` (extend, additive only — insert
  after `CORE_PROVIDER_EVIDENCE_IS_FIXTURE` at line 1408, under a new
  section comment `# -- versioned acceptance policy (T3, WF1297-1299;
  WF1296 is T4's) --`).
- Action: add exactly the 3 constants named in §15, using the numbers T3.0
  confirmed.
- Check: `validate_failure_codes.py`'s uniqueness/severity/taxonomy checks.
- Verify: `cd tools/pipeline && PYTHONUTF8=1 python validate_failure_codes.py`
  must exit 0.
- Risk/rollback: revert the one hunk in `failure_codes.py` if a collision is
  discovered; nothing else depends on the exact numbers except T3.4's tests,
  which use `FailureCode.<NAME>` symbols, never literal numbers, so a
  renumber here does not require touching T3.4's file.

**T3.6 — House-style pass + full-suite proof (depends: T3.5)**

- Purpose: bring the new module up to the documented house style
  (`acceptance/__init__.py:38-45`'s "HOUSE STYLE" block: stdlib only, `RT_X`
  naming, `X_REQUIRED`/`X_ALLOWED`, `validate_X(obj, strict=False) ->
  List[Check]`, `_example_X(**over)` factories) and run the whole-Core gate
  once, clean.
- Files: `tools/wfcore/policy/acceptance_policy.py`,
  `tools/wfcore/policy/__init__.py`, `tools/wfcore/policy/test_policy.py`
  (polish only — no new behavior).
- Action: docstring pass explaining *why* each rail exists (matching the
  density of `constraints.py`/`evaluate.py`'s module docstrings, not a
  restatement of the code); confirm zero forbidden-vocabulary hits via
  `wfcore.hygiene`.
- Check: `wfcore.hygiene`'s scan; `wfcore_shield.py`'s full run.
- Verify: `cd tools && PYTHONUTF8=1 python wfcore_shield.py` must exit 0 and
  its printed suite count must be one higher than it was before T3.1 (proves
  the new suite actually ran inside the real gate, not just standalone).
- Risk/rollback: docstring-only changes on top of already-tested code; low
  risk. Roll back by reverting this task's commit alone.

## 12. Execution mode

**Sequential**, with T3.2/T3.3 as an optional 2-way parallel pair inside the
graph (§10). Reason: the mission is additive-only (§6) — it changes no
existing contract, schema, public API, artifact path, fixture, or cross-
language seam, so `connected-impact-sweep` is not warranted. It also has no
independent multi-surface work broad enough to justify handing off to
`human-directed-swarm-planner`; the one real parallel opportunity (T3.2 vs
T3.3) is small enough for two sequential agents or one, at the implementer's
discretion.

## 13. Required commands

Run from `tools/` unless noted:

```
PYTHONUTF8=1 python -m wfcore.policy.test_policy
PYTHONUTF8=1 python wfcore_shield.py
```
```
cd tools/pipeline && PYTHONUTF8=1 python validate_failure_codes.py
```

All three are runnable in this environment today — `python` resolves on PATH
and both `wfcore_shield.py` and `validate_failure_codes.py` are existing,
currently-passing scripts (their own suites are unrelated to this mission, so
their current pass/fail state should be captured once before T3.1 starts, as a
pre-existing-failure baseline per contract §2's convention).

## 14. Verification gates

| Phase | Expectation |
|---|---|
| Before T3.1 | `wfcore_shield.py` and `validate_failure_codes.py` baseline run, output captured (establishes pre-existing state; this mission must not be blamed for failures that predate it). |
| After T3.1 | New shape validators pass on the canonical examples (policy, human review, runtime measurement); the `policy_id`/`policy_version` grammar rail rejects a dotted/uppercase id; nothing else changes color. |
| After T3.2 | Hash round-trips; the immutability guard is demonstrated **red** before it is implemented (a negative fixture proves the check can fail), then green once implemented — including the identical-content-still-rejected case, shown as its own before/after, not folded silently into the differing-content case. |
| After T3.3 | Two guards are each shown red-then-green independently: the completeness gate (an omitted declared criterion must reject, not fold to a verdict) and the human-verdicts guard (`production_quality` cannot equal `accepted_by_declared_policy` with zero `human_review` criteria declared) — per `test_acceptance.py`'s "harness negative control" discipline, both, not just the final green. |
| After T3.4 | `python -m wfcore.policy.test_policy` green; `discover_suites()` includes it; every sub-cause in §15 has an asserting negative test. |
| After T3.5 | `validate_failure_codes.py` green with exactly the 3 new constants (`WF1297`, `WF1298`, `WF1299`) present. |
| After T3.6 | `wfcore_shield.py` green, suite count incremented by exactly 1. |

## 15. Failure codes

Exactly three numbers are available to T3 — `WF1297`, `WF1298`, `WF1299` —
verified this session against `tools/wfcore/failure.py:13`'s hard
`WF1200–1299` band, the `WF1291–1295` reservation at
`tools/pipeline/failure_codes.py:1398` (unavailable per the file's own
`WF666–670` "do not reuse an earlier band" precedent), and the sibling `T4`
contract's independent claim on `WF1296` (§2). Each of the three consolidates
several of the original nine proposed failure modes into one code, following
the exact pattern `T4` itself uses for `WF1296` (one code, six excluded
domains) and the pattern already live at `WF1201_CORE_CONSTRAINT_UNKNOWN_CLASS`:
the specific bad value or field goes in the raising check's `detail` string,
never in a second constant.

### `WF1297_CORE_POLICY_INVALID` — a `wf.core.policy_*` record fails shape validation

Raise sites: `validate_acceptance_policy`, `validate_policy_criterion`,
`validate_human_review`, `validate_runtime_measurement`. Authoring-time only —
nothing has been folded or written to disk yet when this fires.

| `detail` names | Negative fixture |
|---|---|
| malformed top-level policy shape (not an object; missing `criteria`) | malformed policy dict |
| `criterion_class` not in `CRITERION_CLASSES` | criterion with `criterion_class="soft_preference"` (borrowed from the wrong taxonomy on purpose, to prove the two taxonomies don't silently merge) |
| zero `machine_invariant`/`runtime_budget` criteria present | policy with only a `human_review` criterion |
| criterion not evaluable at authoring time | criterion with `source_evidence=[]` and `evaluator=""` |
| `policy_id`/`policy_version` fails the safe-grammar rail | `policy_id="Bad.Id"` (uppercase and a dot) |
| `runtime_measurement` record missing a required field | measurement dict missing `profile_digest` |
| `human_review` record missing a required binding field | review dict missing `reviewer_attestation` |

### `WF1298_CORE_POLICY_REGISTRY_VIOLATION` — the immutable on-disk registry was contradicted

Raise sites: `publish_policy` (write path), `verify_policy_hash` (read-back
integrity). Fires only after `WF1297`-class validation has already passed.

| `detail` names | Negative fixture |
|---|---|
| write attempt against an existing `(policy_id, policy_version)` with **different** content | publish v1 with `limit=900`, republish v1 with `limit=600` |
| write attempt against an existing `(policy_id, policy_version)` with **identical** content | publish v1, republish v1 unchanged — must still be rejected, no silent dedup |
| recomputed hash disagrees with the stored `policy_hash` | mutate a threshold in a policy dict without recomputing `policy_hash`, call `verify_policy_hash` |

### `WF1299_CORE_POLICY_VERDICT_UNTRUSTWORTHY` — an evaluation-time claim does not honestly follow from what was supplied or measured

Raise sites: `check_criterion_evaluation_completeness` /
`evaluate_policy_claims`, `evaluate_human_review`,
`verify_human_review_attestation`, `criterion_evidence_staleness`,
`validate_policy_evaluation` (re-derivation rail, mirrors `evaluate.py`'s
`accepted_is_tri_accepts_not_not_violated`).

| `detail` names | Negative fixture |
|---|---|
| a declared criterion has no supplied evaluation | 3-criterion policy, 2 evaluations supplied — must return `(None, checks)`, never a record |
| a criterion ID was supplied more than once | same criterion ID appears twice in the evaluation set |
| an evaluation names a criterion ID the policy never declared | evaluation set includes an ID absent from `policy["criteria"]` |
| a `human_review` verdict reads `SATISFIED` from advisory evidence alone | advisory evidence rows all say "looks good", `reviewer_decision` absent |
| `production_quality=True` claimed with zero `human_review` criteria declared, or a recomputed `quality_verdict` that is not `SATISFIED` | both cases, as two negative-test cases |
| evidence cited for a criterion is older than its `freshness_window_s` | evidence timestamped older than the declared window against a fixed `judged_at` |
| a reviewer attestation cannot be verified (bad/missing signature, commit does not contain this record, or no `REVIEWER_REGISTRY` entry for the signer) | a syntactically valid `reviewer_attestation` pointing at an unsigned or content-mismatched commit; separately, a validly signed commit with no matching `REVIEWER_REGISTRY` entry |

Every row above is a task-graph item inside T3.4, not an aspiration —
`failure.py:29-36`'s rule ("defining a code proves nothing... a real raise
site and a negative test") is the acceptance bar for T3.5, checked by T3.6's
full suite run. A single code covering many raise sites does not relax this
bar: every row still needs its own raise site and its own passing negative
test, exactly as if it had its own constant — the code is what's shared, not
the test coverage.

## 16. Negative fixtures

Seventeen total: seven under `CORE_POLICY_INVALID`, three under
`CORE_POLICY_REGISTRY_VIOLATION`, seven under `CORE_POLICY_VERDICT_UNTRUSTWORTHY`
(§15), plus the two named cross-cutting tests in T3.4's action list
(two-valued-spelling trap, shield-discovery proof) that are not tied to a
specific failure code. Every fixture is built with
`_example_acceptance_policy(**over)` / `_example_human_review(**over)` /
`_example_runtime_measurement(**over)`-style overrides (known-bad spawned from
the canonical-valid example), matching `constraints._example_constraint`'s
convention (`constraints.py:341-354`) — never a hand-typed second copy of the
schema that could drift from the real one.

## 17. Review plan

- **Spec compliance**: does the fold in `evaluate_policy_claims` run
  `check_criterion_evaluation_completeness` before touching `tri.conj`, and
  refuse to return a record (`(None, checks)`) on any completeness failure?
  Does it match §9's pseudocode exactly, including the
  `if human_verdicts else tri.UNKNOWN` guard? Does `evaluate_human_review`
  structurally exclude `advisory_evidence` from the verdict (grep the
  function body — the field name must not appear inside it)? Does
  `publish_policy` ever write to a path that `os.open(..., O_EXCL)` already
  rejected (grep for any fallback write path — there must be none)? Do all
  17 §15/§16 sub-causes have both a raise site and a passing negative test
  (grep `FailureCode.CORE_POLICY_` across `acceptance_policy.py` and
  `test_policy.py`, confirm every `detail` string named in §15 also appears
  asserted in the tests)?
- **Code quality**: house-style conformance per T3.6 (`RT_X`/`X_REQUIRED`/
  `X_ALLOWED`/`validate_X`/`_example_X` naming); no consumer vocabulary
  (`wfcore.hygiene` must stay green); docstrings explain *why*, not *what*,
  matching the density of the modules this contract cites.

## 18. Merge gate

All of §13's three commands green, run in this order, output captured:

```
cd tools && PYTHONUTF8=1 python -m wfcore.policy.test_policy
cd tools && PYTHONUTF8=1 python wfcore_shield.py
cd tools/pipeline && PYTHONUTF8=1 python validate_failure_codes.py
```

Plus: `git diff --stat` for the change must show only `tools/wfcore/policy/**`
(new) and one hunk in `tools/pipeline/failure_codes.py` — any other file in
the diff is scope creep (`FAIL-SCOPE-CREEP`) and blocks the merge until
justified or reverted. In particular: no `REVIEWER_REGISTRY` file and no
environment-profile registry file may appear in the diff — both are
out-of-scope infrastructure this contract deliberately defers (§5, §20), and
their absence is exactly why a `human_review` criterion cannot yet reach
`SATISFIED` (§9 Fix 3) — that is expected, not a defect to work around.

## 19. Definition of done

A reader can answer done/not-done with no judgment call by running the three
commands in §18 and checking `git diff --stat`. Done means: all three exit 0,
the diff touches only the two named surfaces, exactly three new failure-code
constants (`WF1297`, `WF1298`, `WF1299`) exist, and `wfcore_shield.py`'s
printed suite count is exactly one greater than the pre-T3.1 baseline captured
in §14's first row.

## 20. Follow-ups

- **Wiring `policy_hash` into `T1`/`T2`'s operation identity** — this
  contract specifies the interface (§9's `wf.core.policy_evaluation.v1`
  record carries `policy_id`/`policy_version`/`policy_hash`/
  `judged_operation_id` together) but does not implement the fold into
  `transaction/executor.py`'s delta record or `pipeline/run_wfcore_transaction.py`'s
  operation_id. That is `T1`/`T2`'s task when they start, per §5.
- **`REVIEWER_REGISTRY` — genuinely new infrastructure, not designed here
  (revised gap).** §9 Fix 3 fully specifies the human-review attestation
  *schema* and its *verification contract* (a signed git commit, content-bound
  to the exact review record, signer fingerprint checked against a registry),
  and specifies that the registry's absence must fold to `UNKNOWN` rather than
  a silent `SATISFIED`. What is not designed: the registry's own file
  format, who is authorized to add or revoke a fingerprint, and how key
  rotation is handled. Until it exists, **no `human_review` criterion in any
  policy can honestly reach `production_quality=True`** — this is a real,
  load-bearing consequence of this contract, not an incidental limitation,
  and it should be its own follow-up ticket before any consumer expects a
  real `production_quality` claim out of this system.
- **Environment-profile registry (id → expected `profile_digest`) — carried
  forward, partially narrowed.** §9 Fix 4 now requires every runtime
  measurement to carry a `profile_digest` computed from what was actually
  measured, closing "we can't tell what was actually measured." What remains
  open, unchanged from the original contract's own flagged gap: pinning that
  digest against a *declared expected* digest for a named
  `environment_profile_id`, so "measured under a different named profile" and
  "measured under drifted hardware sharing the same name" are both caught.
  Worth its own follow-up ticket once a real `runtime_budget` criterion is
  authored against it.
- **`CLEANUP-1` / `DOC-1`** — unrelated, already scoped, out of this
  mission's file set entirely (§5, §6).
- **FOG-2** (`map.md:63-67`, `decisions.md:185-190`) — whether `T5`'s "close
  v2.6" claim spans D19 or only wfcore's own caller-provenance item. T3 does
  not touch this; noted only so a future reader does not assume this
  contract resolved it.
