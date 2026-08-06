# Caller mission brief — the first external acceptance run

For the agent operating **in the Gloamstead repository**, not in WorldForge.

WorldForge is at the service boundary. Every capability below exists, is gated, and
has been proven against WorldForge-authored demonstration consumers. The one
load-bearing missing proof is a **real importing game defining its own intent and
grading the world it gets back**. That proof cannot be produced from this side:
WorldForge authoring the request would be `WF1288_CORE_CALLER_PROVENANCE_FABRICATED`,
and every artifact would look perfect while answering a question nobody asked.

## The shape of the work

```
define intent → resolve semantics → call WorldForge → grade the returned world
```

Gloamstead is not helping build WorldForge. It is doing what every future importing
game does.

## What Gloamstead owns and must author itself

Resolve every game-specific identity from the **real** Gloamstead project — its git
state, Unreal project, maps, gameplay systems, assets, and existing in-flight work.
Inspect before writing.

- game product profile
- art and asset catalog
- world request
- protected-content and revision policy
- acceptance contract
- semantic landmark bindings
- player and camera metrics
- experience graph
- environmental-state requirements

Provenance must originate from Gloamstead's repository and current commit. Do not
ask WorldForge to invent any of it, and do not copy the request into a
WorldForge-authored fixture — that would convert a real caller into another
demonstration.

## Keep the adapter thin

An adapter **may** expose: project state, maps, semantic identities, gameplay
anchors, approved resources, runtime queries, protected bindings, acceptance hooks.

It **may not** implement: composition, provider selection, asset selection,
placement, lighting, generation, transaction, validation, or repair. Those belong to
WorldForge and must stay generic, or the next consumer cannot reuse them.

`tools/consumers/adapter.py` enforces this in two layers — the record
(`GENERATION_LOGIC_FIELDS`) and the **source** (`GENERATION_DEF_PREFIXES`,
`FORBIDDEN_CORE_IMPORTS`) — because a record-only check is evaded by an adapter that
declares nothing and does the work in code. Violations are `WF1287`.

## What to require back before permitting any persistent mutation

- caller-provenance validation
- normalized desired state
- observed-world evidence
- constraint and conflict analysis
- typed generation or revision plan
- provider-selection explanation
- bounded mutation preview
- expected package and actor changes
- compensating rollback actions
- required acceptance evidence

Do not permit persistent mutation until those artifacts are valid.

## Then execute, and grade

Allow WorldForge to execute the approved bounded transaction against the real
Gloamstead project. Prove: save, unload/close, reload, protected-binding
preservation, PIE completion, required visual and gameplay state transitions,
spatial and collision validity, cleanup, performance, evidence integrity.

Expose at least one **meaningful detected defect** and require repair through the
same generic planning, transaction, and validation path. Do not repair it by hand in
the adapter — `WF1267_CORE_REPAIR_BYPASSED_PLANNING` exists for exactly that, and a
hand-repair proves nothing about the platform.

## The WorldForge side you are calling

Branch `worldforge/wfcore-consumer-platform` at `D:/Unreal Projects/WorldForge`.
Package root is `tools/`.

| surface | path |
|---|---|
| consumer contracts | `tools/wfcore/contracts/{consumer_profile,asset_catalog,world_request,revision_policy,acceptance_criteria}.py` |
| adapter contract | `tools/consumers/adapter.py` |
| worked examples | `tools/consumers/demoarena/`, `tools/consumers/demoexpanse/` — *demonstrations, not templates for provenance* |
| reconciliation | `tools/wfcore/analysis/reconcile.py` |
| planning + selection | `tools/wfcore/planning/synth.py`, `tools/wfcore/providers/selection.py` |
| bounded transaction | `tools/wfcore/transaction/executor.py` |
| live Unreal path | `tools/pipeline/run_wfcore_transaction.py` + `tools/unreal/wfcore_unreal_sink.py` |
| acceptance + repair | `tools/wfcore/acceptance/evaluate.py`, `tools/wfcore/repair/loop.py` |

**Known gap on the WorldForge side:** `tools/pipeline/run_consumer_flow.py` stops at
contract validation — it does not yet chain reconcile → plan → delta → acceptance,
and has no `--live` flag. Each layer is proven by its own suite and the sink has live
proof, but the chaining is unwritten. Expect to drive the layers directly, or to ask
for that wiring.

## Constraints

Preserve all unrelated in-flight work. Do not reset, clean, overwrite, bulk-commit,
push, merge, or rewrite history. Continue while executable caller-side work remains;
stop only for a genuinely external dependency or an irreversible product-identity
decision.
