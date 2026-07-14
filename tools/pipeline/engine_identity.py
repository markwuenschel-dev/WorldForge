#!/usr/bin/env python3
"""engine_identity.py — WorldForge v2.5 engine-identity block (UE 5.7 -> 5.8).

The v2.5 transition runs the SAME procedural pipeline against two different
Unreal Engine installs (frozen 5.7 and active 5.8) out of two git worktrees.
For any report to be trustworthy across that transition it must record *which
engine actually ran it* and *which worktree/commit produced it* — not merely
what ``WorldForge.uproject`` claims (EngineAssociation is authoring intent, not
the engine that executed).

This module produces that identity block as a plain, JSON-able dict where every
key is ALWAYS present (an absent key is itself an integrity smell — the same
discipline ``report_meta.build_meta`` follows). Later lanes attach it via
``build_meta(..., extra=engine_identity())`` so the meta block gains the
engine_* / *_commit / project_path_identity fields with no change to
report_meta.py.

Design notes
------------
* Dependency-light: stdlib + ``report_meta.hash_text`` only (reused for the
  worktree fingerprint so hashing stays consistent repo-wide). No side effects
  beyond reading files and shelling out to ``git`` for commit SHAs.
* Reflects the engine that RAN: engine_* come from the resolved install's
  ``Engine/Build/Build.version``, never from the uproject.
* Robust: if nothing resolves, the dict still returns with engine_* = None and
  a ``_resolution`` note explaining why — it never raises.
* Windows UTF-8: run with PYTHONUTF8=1; no emoji in any emitted string.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# report_meta lives next to this file (tools/pipeline/). Import its hashing so
# the worktree fingerprint uses the exact same sha256 helper as everything else.
try:
    from report_meta import hash_text
except ImportError:  # pragma: no cover - allow running from other cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from report_meta import hash_text

# Worktree root = tools/pipeline/engine_identity.py -> parents[2].
WORKTREE_ROOT = Path(__file__).resolve().parents[2]

# The tail of a headless launcher path we strip to recover the install root,
# e.g. WF_UE_CMD=D:/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe.
_UE_CMD_TAIL = ("Engine", "Binaries", "Win64")

# EngineAssociation -> known install root fallback (last-resort resolution when
# neither an explicit arg nor WF_UE_CMD is available).
KNOWN_ENGINE_ROOTS = {
    "5.7": r"C:/Program Files/Epic Games/UE_5.7",
    "5.8": r"D:/UE_5.8",
}

# The seven identity keys this module contracts to emit — always present.
IDENTITY_KEYS = (
    "engine_major",
    "engine_minor",
    "engine_patch",
    "engine_build_id",
    "project_commit",
    "plugin_commit",
    "project_path_identity",
)


def _run_git(args):
    """Run a git command in the worktree root; return stripped stdout or None.

    Tolerates git being missing / not a repo — returns None instead of raising.
    """
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(WORKTREE_ROOT),
            capture_output=True,
            text=True,
        )
        if out.returncode == 0:
            val = out.stdout.strip()
            return val or None
    except Exception:
        pass
    return None


def _read_uproject_association():
    """Return the EngineAssociation string from WorldForge.uproject, or None."""
    up = WORKTREE_ROOT / "WorldForge.uproject"
    try:
        data = json.loads(up.read_text(encoding="utf-8"))
        assoc = data.get("EngineAssociation")
        if isinstance(assoc, str) and assoc.strip():
            return assoc.strip()
    except Exception:
        pass
    return None


def _install_root_from_ue_cmd(ue_cmd):
    """Derive an install root from a WF_UE_CMD launcher path.

    Strips the trailing Engine/Binaries/Win64/<exe> so
    ``D:/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe`` -> ``D:/UE_5.8``.
    Falls back to walking up until a directory containing ``Engine`` is found.
    """
    if not ue_cmd:
        return None
    try:
        p = Path(ue_cmd)
        # exe -> Win64 -> Binaries -> Engine -> <root>
        parts = [q.name for q in [p.parent, p.parent.parent, p.parent.parent.parent]]
        if [x for x in parts] == list(reversed(_UE_CMD_TAIL)):
            return p.parents[3]
        # Fallback: climb until we find a parent whose child 'Engine' exists.
        for anc in p.parents:
            if (anc / "Engine" / "Build" / "Build.version").is_file():
                return anc
    except Exception:
        pass
    return None


def resolve_engine_root(engine_root=None):
    """Resolve the UE install root and report how it was resolved.

    Precedence:
      1. explicit ``engine_root`` argument
      2. ``WF_UE_CMD`` env var (strip Engine/Binaries/Win64/<exe>)
      3. map ``WorldForge.uproject`` EngineAssociation to a KNOWN_ENGINE_ROOTS entry

    Returns ``(root_path_or_None, note_str)``. The path is returned even if it
    does not exist so the caller can record the attempted location; existence is
    (re)checked when reading Build.version.
    """
    if engine_root:
        return Path(engine_root), "explicit engine_root argument"

    ue_cmd = os.environ.get("WF_UE_CMD")
    if ue_cmd:
        root = _install_root_from_ue_cmd(ue_cmd)
        if root is not None:
            return root, "WF_UE_CMD env ({})".format(ue_cmd)
        return None, "WF_UE_CMD set but unparseable ({})".format(ue_cmd)

    assoc = _read_uproject_association()
    if assoc:
        mapped = KNOWN_ENGINE_ROOTS.get(assoc)
        if mapped:
            return Path(mapped), "uproject EngineAssociation {} -> known install".format(assoc)
        return None, "uproject EngineAssociation {} has no known install mapping".format(assoc)

    return None, "no engine_root arg, no WF_UE_CMD, no resolvable EngineAssociation"


def _read_build_version(engine_root):
    """Read Engine/Build/Build.version under engine_root; return (dict, note)."""
    if engine_root is None:
        return None, "engine root unresolved"
    bv = Path(engine_root) / "Engine" / "Build" / "Build.version"
    if not bv.is_file():
        return None, "Build.version not found at {}".format(bv)
    try:
        return json.loads(bv.read_text(encoding="utf-8")), "read {}".format(bv)
    except Exception as exc:  # pragma: no cover - malformed file
        return None, "Build.version unreadable at {} ({})".format(bv, exc)


def project_path_identity():
    """Stable identifier of which worktree produced a report.

    ``hash_text(<normalized abs worktree root>)[:12] + ':' + basename`` so the
    frozen-5.7 worktree and the active-5.8 worktree yield distinct, stable ids
    that a report can be tied back to.
    """
    root = WORKTREE_ROOT.resolve()
    normalized = root.as_posix().lower()
    return "{}:{}".format(hash_text(normalized)[:12], root.name)


def engine_identity(engine_root=None):
    """Return the v2.5 engine-identity dict (all seven keys always present).

    See module docstring for the contract. Never raises: on any failure the
    engine_* keys are None and a ``_resolution`` note explains why.
    """
    root, resolution_note = resolve_engine_root(engine_root)
    build, build_note = _read_build_version(root)

    if build:
        engine_major = build.get("MajorVersion")
        engine_minor = build.get("MinorVersion")
        engine_patch = build.get("PatchVersion")
        changelist = build.get("Changelist")
        branch = build.get("BranchName")
        # engine_build_id: authoritative changelist, tagged with branch when present.
        if changelist is not None and branch:
            engine_build_id = "{}@{}".format(changelist, branch)
        elif changelist is not None:
            engine_build_id = str(changelist)
        else:
            engine_build_id = None
    else:
        engine_major = engine_minor = engine_patch = None
        engine_build_id = None

    project_commit = _run_git(["rev-parse", "HEAD"])
    plugin_commit = _run_git(["log", "-1", "--format=%H", "--", "Plugins/WorldForge"])
    if not plugin_commit:
        plugin_commit = project_commit

    return {
        "engine_major": engine_major,
        "engine_minor": engine_minor,
        "engine_patch": engine_patch,
        "engine_build_id": engine_build_id,
        "project_commit": project_commit,
        "plugin_commit": plugin_commit,
        "project_path_identity": project_path_identity(),
        # Diagnostic breadcrumbs (additive; not part of the seven-key contract).
        "engine_root": str(root) if root is not None else None,
        "_resolution": "{}; {}".format(resolution_note, build_note),
    }


def report_root_for_engine(engine_minor):
    """Map an engine minor version to a report subtree name.

    minor==7 -> "ue5_7", minor==8 -> "ue5_8", else "ue5_<minor>". Used to route
    reports under procedural/reports/<subtree>/ so 5.7 and 5.8 runs never collide.
    """
    if engine_minor == 7:
        return "ue5_7"
    if engine_minor == 8:
        return "ue5_8"
    return "ue5_{}".format(engine_minor)


def reports_dir(base="procedural/reports", engine_minor=None):
    """Return the Path for reports of a given engine minor under ``base``.

    If ``engine_minor`` is None it resolves the current engine identity to pick
    the subtree; if that too is unresolved the base path is returned as-is.
    """
    if engine_minor is None:
        engine_minor = engine_identity().get("engine_minor")
    if engine_minor is None:
        return Path(base)
    return Path(base) / report_root_for_engine(engine_minor)


def _selfcheck():
    """Assert the identity contract holds. Returns the identity dict."""
    ident = engine_identity()
    for key in IDENTITY_KEYS:
        assert key in ident, "missing identity key: {}".format(key)
    minor = ident.get("engine_minor")
    if minor is not None:
        assert isinstance(minor, int), "engine_minor must be int when resolvable"
    # Routing helper contract.
    assert report_root_for_engine(7) == "ue5_7"
    assert report_root_for_engine(8) == "ue5_8"
    assert report_root_for_engine(9) == "ue5_9"
    # project_path_identity is stable across calls.
    assert project_path_identity() == project_path_identity()
    return ident


def _parse_args(argv):
    engine_root = None
    emit = False
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--emit":
            emit = True
        elif arg == "--engine-root":
            i += 1
            if i < len(argv):
                engine_root = argv[i]
        elif arg.startswith("--engine-root="):
            engine_root = arg.split("=", 1)[1]
        elif arg == "--selfcheck":
            emit = False
        i += 1
    return engine_root, emit


if __name__ == "__main__":
    _engine_root, _emit = _parse_args(sys.argv[1:])
    if "--selfcheck" in sys.argv[1:]:
        ident = _selfcheck()
        sys.stdout.write("engine_identity self-check OK\n")
        sys.exit(0)
    ident = engine_identity(_engine_root)
    json.dump(ident, sys.stdout, indent=2)
    sys.stdout.write("\n")
    sys.exit(0)
