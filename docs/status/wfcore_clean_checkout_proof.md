# Clean-checkout verification at the branch tip

Run in a **detached git worktree** at the tip, so nothing untracked or ignored from
the operator's working tree could contribute to the result. This is what separates
"the gates pass" from "the gates pass because of files only this machine has".

Reproduce:

```bash
cd "D:/Unreal Projects/WorldForge"
git worktree add --detach "$TMP/wfcore-clean-verify" $(git rev-parse HEAD)
cd "$TMP/wfcore-clean-verify/tools"
PYTHONUTF8=1 python core_boundary_proof.py capture --out ../proof-base.json
PYTHONUTF8=1 python wfcore_shield.py --baseline ../proof-base.json
PYTHONUTF8=1 python pipeline/test_consumer_flow.py
PYTHONUTF8=1 python pipeline/test_wfcore_unreal_sink.py
PYTHONUTF8=1 python pipeline/validate_failure_codes.py
PYTHONUTF8=1 python core_boundary_proof.py capture --out ../proof-after.json
cd "D:/Unreal Projects/WorldForge" && git worktree remove --force "$TMP/wfcore-clean-verify"
```

## Recorded result

| item | value |
|---|---|
| branch tip SHA | `ad8a57696f812db1a0646ba929dbf5a52c16fb39` |
| branch | `worldforge/wfcore-consumer-platform` |
| commits ahead of `main` | 15 |
| initial status in worktree | **0 entries — pristine** |
| baseline manifest | `proof-base.json`, sha256 `ac697eed8f9c8970…` |
| Core capture BEFORE | `sha256:1f91927f25eccf5b…091d6003`, 39 files |
| Core capture AFTER | `sha256:1f91927f25eccf5b…091d6003`, 39 files — **identical** |
| after-manifest file hash | `ac697eed8f9c8970…` — **byte-identical to the baseline** |

## Gate results in the clean checkout

| gate | exit | note |
|---|---|---|
| `pipeline/test_consumer_flow.py` | 0 | consumer proof, both demonstration consumers |
| `pipeline/test_wfcore_unreal_sink.py` | 0 | 189 checks, no editor required |
| `pipeline/validate_external_tool_providers.py` | 0 | absence asserted as absence |
| `pipeline/validate_failure_codes.py` | 0 | no orphaned codes |
| 8 Core suites + hygiene + boundary proof | 0 | inside the shield |
| `pipeline/validate_execution_environment.py` | **1** | **expected — see below** |
| `wfcore_shield.py` | **1** | inherits the above, correctly |

### Why the environment gate cannot pass in a clean checkout, and why that is right

The plugins it governs are **untracked local installs**. `Plugins/NeoStackAI/` and
`Plugins/UELLMToolkit/` exist in the operator's working tree and in no clean
checkout — a detached worktree has **5** tracked plugin descriptors where the
working tree has **10**, and **zero** `.uplugin.disabled` files.

So the gate is intrinsically about the operator's machine. That is a true property
of this project, not a defect in the gate: the whole reason the two disabled
descriptors need policing is that they are local, untracked, and invisible to git.

The clean-checkout run is what surfaced this, and it prompted a fix
(`ad8a5769`): absence of the local installs is now reported **distinctly from
drift**. Reporting it as a fingerprint mismatch was true but misleading — it reads
as "a plugin descriptor changed" and would send a future agent hunting a change
that never happened. Absence still **fails closed**; an unverifiable environment is
not a verified one.

**Operational rule:** run `validate_execution_environment.py` in the operator's
working tree. In CI or any clean checkout it will correctly refuse, naming the
reason.

## Tracked files mutated by the run

Three, all **gate report outputs** — the gates write their own reports:

```
M procedural/reports/core/environment/validate_execution_environment_report.json
M procedural/reports/core/environment/validate_external_tool_providers_report.json
M procedural/reports/failure_codes/validate_failure_codes_report.json
```

**None is under `tools/wfcore/`** — consistent with the Core digest being identical
before and after. Core was not touched by running the gates, which is the property
the boundary proof exists to establish.

## What this proof does and does not establish

**Establishes:** every gate except the machine-specific one passes from tracked
content alone. No result depended on an untracked or ignored local file. Core is
byte-identical before and after, and the two capture manifests are byte-identical
to each other.

**Does not establish:** anything about live Unreal execution — the clean-checkout
run is deliberately editor-free. Live proof lives in
`procedural/reports/core/transaction/` (authored + rolled back real content) and
`procedural/reports/scene_survey/fixture_smoke/` (21/21 probes), both taken in the
operator's working tree against a real 5.8 editor.
