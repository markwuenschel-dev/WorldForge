#!/usr/bin/env python3
"""transition_identity.py — WorldForge v2.5 transition report-meta identity block.

Lane 2 (Repository / Engine Identity / Dual-Track Isolation) helper. Builds on
``engine_identity`` (imported, never modified) and adds the four commander
meta-identity convention keys that every v2.5 transition report MUST carry so
Lane 7 (evidence integrity) can tell an honest report from a laundered one:

    declared_target_engine      str   the engine this run TARGETS (e.g. "5.8")
    observed_runtime_engine     int   the UE minor a runtime run OBSERVED, or None
                                      when nothing actually executed a UE runtime
    runtime_execution_required  bool  does this gate need a real UE runtime to be
                                      meaningful?
    runtime_executed            bool  did a real UE runtime actually run?

Plus two fingerprints so a report is tied to its repository AND its worktree:

    repository_identifier   stable 12-hex over the shared git common dir — SAME
                            for the 5.7 and 5.8 worktrees (they are one repo)
    worktree_identifier     engine_identity.project_path_identity() — DIFFERENT
                            per worktree (this is the dual-track isolation anchor)

CRITICAL honesty separation (commander convention, implemented verbatim):
    The ``engine_major/minor/patch`` produced by engine_identity() describe the
    PYTHON INTERPRETER HOST (resolved from WF_UE_CMD / uproject EngineAssociation),
    NOT the observed UE runtime. In the v2.5 UE58 worktree the uproject still reads
    EngineAssociation "5.7", so a runtime-FREE report legitimately host-resolves to
    engine_minor=7. That is the documented uproject fallback and is NEVER, on its
    own, contamination. Contamination is a property of ``observed_runtime_engine``
    vs ``declared_target_engine`` under ``runtime_execution_required=True`` — see
    ``contamination_reason`` below. Stdlib only; run with PYTHONUTF8=1.
"""

import json
import subprocess
import sys
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKTREE_ROOT / "tools" / "pipeline"))

from engine_identity import engine_identity, project_path_identity  # noqa: E402
from report_meta import hash_text  # noqa: E402

# The four convention keys, exported so validators can iterate them.
CONVENTION_KEYS = (
    "declared_target_engine",
    "observed_runtime_engine",
    "runtime_execution_required",
    "runtime_executed",
)
# The two fingerprint keys this lane adds on top of engine_identity().
FINGERPRINT_KEYS = ("repository_identifier", "worktree_identifier")


def declared_minor(declared_target_engine):
    """Map a declared engine string like "5.8" to its integer minor (8), or None."""
    if not isinstance(declared_target_engine, str):
        return None
    parts = declared_target_engine.strip().split(".")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[1])
    return None


def _git_common_dir():
    """Absolute path of the shared git common dir (main repo .git), or None.

    Linked worktrees share ONE common dir, so both the 5.7 and 5.8 worktrees
    hash to the same repository_identifier while keeping distinct worktree ids.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(WORKTREE_ROOT), capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            p = Path(out.stdout.strip())
            if not p.is_absolute():
                p = (WORKTREE_ROOT / p)
            return p.resolve()
    except Exception:
        pass
    return None


def repository_identifier():
    """Stable 12-hex fingerprint of the repository (shared git common dir).

    Falls back to the worktree parent when git is unavailable so the key is
    always present (an absent key is itself an integrity smell).
    """
    common = _git_common_dir()
    basis = common.as_posix().lower() if common is not None \
        else WORKTREE_ROOT.parent.as_posix().lower()
    return hash_text(basis)[:12]


def worktree_identifier():
    """This worktree's identity — reuses engine_identity.project_path_identity()."""
    return project_path_identity()


def transition_identity(declared_target_engine, runtime_required=False,
                        runtime_executed=False, observed_runtime_engine=None,
                        engine_root=None):
    """Return the engine_identity() block merged with the v2.5 convention block.

    Pass the result straight to ``build_meta(..., extra=transition_identity(...))``
    so a report's meta gains BOTH the seven engine_identity keys and the four
    convention keys + two fingerprints in one shot.
    """
    out = dict(engine_identity(engine_root))
    out["declared_target_engine"] = str(declared_target_engine)
    out["observed_runtime_engine"] = observed_runtime_engine
    out["runtime_execution_required"] = bool(runtime_required)
    out["runtime_executed"] = bool(runtime_executed)
    out["repository_identifier"] = repository_identifier()
    out["worktree_identifier"] = worktree_identifier()
    return out


def contamination_reason(meta):
    """Return a string reason iff ``meta`` is CONTAMINATED, else None.

    Implements the commander rule verbatim: a report is contaminated ONLY when a
    runtime run was required yet observed the wrong engine. A runtime-free report
    that host-resolves to engine_minor=7 (uproject fallback) is NOT contaminated.
    """
    if not isinstance(meta, dict):
        return "meta is not a mapping"
    if meta.get("runtime_execution_required") is True:
        obs = meta.get("observed_runtime_engine")
        want = declared_minor(meta.get("declared_target_engine"))
        if obs is None:
            return "runtime_execution_required but observed_runtime_engine is None"
        if want is not None and obs != want:
            return "observed_runtime_engine {!r} != declared minor {!r}".format(obs, want)
    return None


def _selfcheck():
    """Assert the convention + fingerprint contract holds. Returns the block."""
    ti = transition_identity("5.8", runtime_required=False,
                             runtime_executed=False, observed_runtime_engine=None)
    for key in CONVENTION_KEYS + FINGERPRINT_KEYS:
        assert key in ti, "missing convention key: {}".format(key)
    assert ti["declared_target_engine"] == "5.8"
    assert ti["runtime_execution_required"] is False
    assert ti["runtime_executed"] is False
    assert ti["observed_runtime_engine"] is None
    # A runtime-free block is never contaminated, even if host minor is 7.
    assert contamination_reason(ti) is None, contamination_reason(ti)
    # A required-runtime block that observed the wrong engine IS contaminated.
    bad = transition_identity("5.8", runtime_required=True,
                              runtime_executed=True, observed_runtime_engine=7)
    assert contamination_reason(bad) is not None
    # declared_minor helper.
    assert declared_minor("5.8") == 8 and declared_minor("5.7") == 7
    assert declared_minor("garbage") is None
    # repository_identifier is stable; worktree_identifier matches engine_identity.
    assert repository_identifier() == repository_identifier()
    assert worktree_identifier() == project_path_identity()
    return ti


if __name__ == "__main__":
    if "--selfcheck" in sys.argv[1:]:
        block = _selfcheck()
        json.dump(block, sys.stdout, indent=2)
        sys.stdout.write("\ntransition_identity self-check OK\n")
        sys.exit(0)
    dt = "5.8"
    for i, a in enumerate(sys.argv[1:]):
        if a == "--declared" and i + 2 <= len(sys.argv[1:]):
            dt = sys.argv[1:][i + 1]
    json.dump(transition_identity(dt), sys.stdout, indent=2)
    sys.stdout.write("\n")
    sys.exit(0)
