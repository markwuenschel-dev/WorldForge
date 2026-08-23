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
