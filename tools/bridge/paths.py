#!/usr/bin/env python3
"""tools/bridge/paths.py — parameterised path resolution for the live bridge.

DoD #17 requires the live run to need NO machine-specific hard-coded path. Every
path the bridge needs is therefore resolved through one ladder, and the rung that
answered is recorded so the report can show *how* each path was found:

    1. an explicit CLI argument      -> source "arg"
    2. an environment variable       -> source "env"
    3. discovery from repo state     -> source "discovered"
    4. (engine only) the shared engine_identity registry -> source "registry"

If no rung answers, resolution FAILS LOUDLY. It never falls back to a baked
constant, because a baked constant is precisely the thing that makes a green run
un-reproducible on another machine.

Nothing here is a literal machine path. ``D:/UE_5.8`` appears nowhere in this
module: the engine is discovered from WF_UE_CMD, from the shared engine_identity
registry (which the platform already owns), or from an explicit argument.

Self-contained: stdlib + the shared engine_identity registry.
"""

import os
import subprocess
import sys
from pathlib import Path

_PIPELINE = Path(__file__).resolve().parents[2] / "tools" / "pipeline"
if str(_PIPELINE) not in sys.path:
    sys.path.insert(0, str(_PIPELINE))

# Environment variable names — the documented, machine-independent knobs.
ENV_FIXTURE_ROOT = "WF_BRIDGE_FIXTURE_ROOT"
ENV_PLUGIN_SOURCE = "WF_BRIDGE_PLUGIN_SOURCE"
ENV_ENGINE_ROOT = "WF_BRIDGE_ENGINE_ROOT"
ENV_UE_CMD = "WF_UE_CMD"

_UE_CMD_REL = "Engine/Binaries/Win64/UnrealEditor-Cmd.exe"


class ResolutionError(RuntimeError):
    """Raised when a required path cannot be resolved from any rung."""


class Resolved(object):
    """A resolved path plus the rung of the ladder that produced it."""

    __slots__ = ("value", "source")

    def __init__(self, value, source):
        self.value = value
        self.source = source

    def __str__(self):
        return str(self.value)

    def as_dict(self):
        return {"value": str(self.value).replace("\\", "/"), "source": self.source}


def _engine_root_from_registry():
    """Ask the platform's own engine registry where 5.8 lives (never hard-coded here)."""
    try:
        from engine_identity import KNOWN_ENGINE_ROOTS
    except Exception:
        return None
    root = KNOWN_ENGINE_ROOTS.get("5.8")
    return Path(root) if root and Path(root).is_dir() else None


def resolve_engine_root(arg=None):
    """Resolve the UE 5.8 install root: arg -> env -> WF_UE_CMD -> registry."""
    if arg:
        return Resolved(Path(arg), "arg")
    env = os.environ.get(ENV_ENGINE_ROOT)
    if env:
        return Resolved(Path(env), "env")
    cmd = os.environ.get(ENV_UE_CMD)
    if cmd:
        # .../Engine/Binaries/Win64/UnrealEditor-Cmd.exe -> engine root
        p = Path(cmd).resolve()
        if len(p.parents) >= 4:
            return Resolved(p.parents[3], "env")
    reg = _engine_root_from_registry()
    if reg:
        return Resolved(reg, "registry")
    raise ResolutionError(
        "cannot resolve the UE 5.8 engine root. Pass --engine-root, or set {} or {}."
        .format(ENV_ENGINE_ROOT, ENV_UE_CMD))


def resolve_ue_cmd(engine_root=None, arg=None):
    """Resolve UnrealEditor-Cmd.exe: arg -> WF_UE_CMD -> <engine_root>/..."""
    if arg:
        return Resolved(Path(arg), "arg")
    env = os.environ.get(ENV_UE_CMD)
    if env:
        return Resolved(Path(env), "env")
    root = engine_root or resolve_engine_root().value
    cmd = Path(root) / _UE_CMD_REL
    if cmd.is_file():
        return Resolved(cmd, "discovered")
    raise ResolutionError(
        "cannot resolve UnrealEditor-Cmd.exe (looked at {}). Pass --ue-cmd or set {}."
        .format(cmd, ENV_UE_CMD))


def _build_id(modules_json):
    try:
        import json
        return json.loads(Path(modules_json).read_text(encoding="utf-8")).get("BuildId")
    except Exception:
        return None


def _worktree_with_matching_plugin_binaries(repo_root, engine_build_id):
    """Discover a git worktree of THIS repo carrying plugin binaries built for ``engine_build_id``.

    The plugin's compiled DLLs are build artifacts and are not committed, so they
    live in whichever worktree last built them — and different worktrees track
    different engines (the 5.7 track and the 5.8 track both exist here). Rather than
    hard-code a path, we ask git for the worktree list and pick the one whose plugin
    BuildId actually matches the engine we are about to run. Matching on BuildId
    rather than on a directory name is what stops a stale 5.7 binary being handed to
    a 5.8 editor (WF1019).
    """
    try:
        out = subprocess.check_output(
            ["git", "worktree", "list", "--porcelain"], cwd=str(repo_root),
            stderr=subprocess.DEVNULL).decode("utf-8", "replace")
    except Exception:
        return None
    candidates = [Path(line.split(" ", 1)[1].strip())
                  for line in out.splitlines() if line.startswith("worktree ")]
    candidates.sort(key=lambda p: 0 if str(p) == str(repo_root) else 1)
    fallback = None
    for wt in candidates:
        plugin = wt / "Plugins" / "WorldForge"
        modules = plugin / "Binaries" / "Win64" / "UnrealEditor.modules"
        if not modules.is_file():
            continue
        if engine_build_id and _build_id(modules) == engine_build_id:
            return plugin
        fallback = fallback or plugin
    # Return the mismatched one rather than None so create_fixture can raise the
    # precise stale-binary error instead of a vague "not found".
    return fallback


def resolve_plugin_source(repo_root, arg=None, engine_build_id=None):
    """Resolve the WorldForge plugin dir with 5.8 binaries: arg -> env -> discovery."""
    if arg:
        return Resolved(Path(arg), "arg")
    env = os.environ.get(ENV_PLUGIN_SOURCE)
    if env:
        return Resolved(Path(env), "env")
    found = _worktree_with_matching_plugin_binaries(repo_root, engine_build_id)
    if found:
        return Resolved(found, "discovered")
    raise ResolutionError(
        "cannot find a WorldForge plugin directory with 5.8-built binaries in any "
        "worktree of this repository. Build the plugin under UE 5.8, or pass "
        "--plugin-source / set {}.".format(ENV_PLUGIN_SOURCE))


def resolve_fixture_root(repo_root, arg=None):
    """Resolve where the fixture project lives: arg -> env -> sibling of the repo.

    The default is a SIBLING of the repository, never a child: the fixture must be
    outside this repo to be a separate repository at all.
    """
    if arg:
        return Resolved(Path(arg), "arg")
    env = os.environ.get(ENV_FIXTURE_ROOT)
    if env:
        return Resolved(Path(env), "env")
    return Resolved(Path(repo_root).resolve().parent / "WF-BridgeFixture58", "discovered")
