# Houdini provider status — what is and is not proven

**Status as of 2026-08-06: there is NO live Houdini production provider.**
This is a statement of absence, recorded deliberately, and enforced by a gate.

```
cd tools && PYTHONUTF8=1 python pipeline/validate_external_tool_providers.py
```

---

## The four things that get collapsed into "we have Houdini support"

Only the fourth is a production capability. The first three are all true here.

| # | Claim | True? | Evidence |
|---|---|---|---|
| 1 | the plugin **builds** | yes | `HoudiniEngine`, `HoudiniNiagara`, `HoudiniLiveLink` compiled against UE 5.8 |
| 2 | the plugin **mounts** | yes | live probe: `HoudiniEngine` enabled, `v3.0 - H21.0.753`, base dir under the project |
| 3 | a **fixture was generated** with it | yes | `procedural/fixtures/houdini/flat_plane_v1.json` carries a `generator` block naming `hython`, Houdini `21.0.729` |
| 4 | the **planner selected a provider that cooked and produced an output** | **no** | nothing. No declaration, no selection, no cook. |

The difficulty is that 1–3 produce artifacts that look exactly like 4's. A
deterministic fixture with a real Houdini version stamp reads as proof of a
working provider to anyone who does not already know it was authored by hand as
a test input. That is precisely why it must not count.

## What the D18 measurement does and does not say

D18 measured Python's cost for support-grid sampling and concluded the support
grid should **stay in Python**. That is a statement about one implementation
choice *inside* WorldForge.

It says nothing about whether an external tool can be driven end to end. Quoting
it toward "Houdini is proven" would be using a real measurement to answer a
question it never asked — and it would be persuasive, because the measurement
itself is sound.

## The rule, enforced rather than described

A provider declaring a capability backed by an external DCC tool
(`houdini`, `hython`, `hapi`, `substance`, `blender`, `maya`) must carry
**cook evidence**:

| field | why |
|---|---|
| `tool_name`, `tool_version` | which tool, which build |
| `session_id` | the cook is identifiable and re-findable |
| `input_digest` | what went in |
| `output_paths`, `output_digests` | what came out, and its content hash |
| `cook_seconds` | that it actually ran |
| `selected_by_plan` | **the plan step that selected this provider** |

Missing any field → `WF1289_CORE_PROVIDER_COOK_EVIDENCE_MISSING`.

Evidence whose `output_paths` live under `procedural/fixtures/`,
`procedural/known_bads/`, `tests/fixtures/` or `examples/` →
`WF1290_CORE_PROVIDER_EVIDENCE_IS_FIXTURE`.

`selected_by_plan` is the field that matters most. It is what separates "a human
ran hython once" from "the planner chose this provider for an operation it can
materially improve". Without it, a cook is a thing someone did, not a capability
the platform has.

**Mutation-tested:** a Houdini provider declaring `flat_plane_v1.json` as its
cook evidence trips both rails with those exact codes; removing it returns the
gate to green.

## When this document should change

When a Houdini provider is registered in the capability registry, selected by a
plan step for an operation it materially improves, and the cook produces an
output asset with a recorded digest. At that point this file records the
capability instead of its absence — and the gate starts grading the claim rather
than asserting there is none.

Until then: Houdini is a **mounted plugin and a fixture generator**. Nothing more
has been demonstrated, and nothing more should be reported.

---

## Addendum, 2026-09-03 — the second Houdini lane, and its self-authored evidence

Everything above is scoped to the **wfcore provider layer** and remains accurate.
It was, however, **silent about the older `procedural/` MeshForge lane** — and
that silence is load-bearing, because that lane reported **222 green checks over
six `houdini_generated` assets** while no Houdini process had ever run.

**The mechanism.** `tools/pipeline/create_mesh_assets.py` writes the
`cook_report.json` / `bake_report.json` / `import_report.json` files itself
(`_write_houdini_reports`), with `status` hardcoded to `"ok"` and exactly the
keys `houdini_contract.HOUDINI_REPORT_REQUIRED` demands. The four
`validate_houdini_*` gates then grade those files. Gate and subject share an
author, so the checks could not fail for any reason that matters. The intake
docstring said the reports "come from a prior cook" — an intent that was never
implemented, and plausible enough that the loop stayed invisible for the life of
the lane.

Two further tells, both now recorded: the declared
`hda_path` `/Game/WorldForge/HDAs/worldforge_rock_generator` names a directory
that does not exist, and the one project HDA
(`Content/WorldForge/Houdini/HDAs/rock_generator.hda`) is byte-identical to
SideFX's shipped `rock_generator.hda` sample.

**What changed.** The two questions were separated rather than merged:

| Question | Gate | State |
|---|---|---|
| is the declared report present, well-formed, status-ok? | `validate_houdini_{cook,bake}_reports.py` (WF233/234/235) | **unchanged, still green** — a real descriptor-integrity check that `test_negative_sources.py` and `source_lifecycle_torture.py` prove can go red |
| does that report constitute evidence Houdini ran? | `validate_houdini_cook_evidence.py` (**WF239**) | **RED by design** — 18 failures, 6 assets x 3 stages |

Conflating them is what hid the gap; separating them is the fix. The reports now
carry `producer: "worldforge.create_mesh_assets"`, so the self-authorship is a
fact **in the data** rather than an inference — a report that names its own
author cannot be mistaken for an independent measurement.

`validate_houdini_cook_evidence.py` imports `COOK_EVIDENCE_REQUIRED` verbatim
from `validate_external_tool_providers.py` rather than declaring its own: one
vocabulary across both lanes, so the two can never disagree about what a cook
is. `inspect_houdini_intake.py` imports the same classifier — its dossier
previously reported `total_problems: 0` over this evidence and now reports 18.

**Honest limit:** a caller that writes a false `cook_evidence` block has it read
as resolved. This closes the accidental lie, not the deliberate one.
