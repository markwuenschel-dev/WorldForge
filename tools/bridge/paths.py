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

import hashlib
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


# ---------------------------------------------------------------------------
# Plugin SOURCE identity (the source half of the problem the BuildId match above
# solves for binaries).
#
# _worktree_with_matching_plugin_binaries guards WF1019 by refusing to hand a
# 5.7-built DLL to a 5.8 editor. That guards the COMPILED artifact. It says nothing
# about whether the far side's plugin *source* is the same source this repo pinned:
# two checkouts can carry byte-different SceneSurvey.cpp and still produce binaries
# whose BuildId matches, because BuildId identifies the ENGINE, not the plugin code.
# A source hash closes that gap — the caller pins the source it expects, the near
# side hashes what is actually on disk before booting, and a mismatch is WF1026
# (stale plugin) instead of a silently different survey.
# ---------------------------------------------------------------------------

_PLUGIN_SOURCE_SUBDIR = "Source"


def _worktree_with_plugin_source(repo_root):
    """Discover a worktree of THIS repo carrying a plugin ``Source/`` tree.

    Deliberately NOT ``_worktree_with_matching_plugin_binaries``: that one requires
    compiled binaries, and source identity is answerable from a checkout that was
    never built. Reusing it would make the source hash unavailable exactly where it
    is most useful — on a machine that has the code but not the build.

    ``repo_root`` is ALWAYS tried first, and both sides are ``resolve()``d before
    comparison. That is not a stylistic detail: plugin *source* is committed, so the
    answer is normally repo_root's own tree, and a sibling worktree on another branch
    is a different revision of the same plugin. Comparing unresolved strings (a
    relative ``repo_root`` against git's absolute output) silently demotes repo_root
    and hashes whichever worktree git happens to list first — observed here handing
    back the parked v2.4 checkout instead of this one.
    """
    root = Path(repo_root).resolve()
    candidates = [root]
    try:
        out = subprocess.check_output(
            ["git", "worktree", "list", "--porcelain"], cwd=str(root),
            stderr=subprocess.DEVNULL).decode("utf-8", "replace")
    except Exception:
        pass
    else:
        others = sorted(Path(line.split(" ", 1)[1].strip()).resolve()
                        for line in out.splitlines() if line.startswith("worktree "))
        candidates += [p for p in others if p != root]
    for wt in candidates:
        plugin = wt / "Plugins" / "WorldForge"
        if (plugin / _PLUGIN_SOURCE_SUBDIR).is_dir():
            return plugin
    return None


def hash_plugin_source(plugin_dir):
    """Return the sha256 hex digest of a plugin's ``Source/**`` tree.

    Determinism rules, each one load-bearing:

    * **Sorted by relative POSIX path.** Directory iteration order is a filesystem
      detail; sorting makes the digest independent of it.
    * **No absolute paths in the digest.** Only paths relative to ``Source/`` are
      hashed, so the same tree on two machines (or two worktrees) hashes equal.
    * **Line endings normalised** (CRLF and lone CR -> LF) before hashing, so a
      checkout under a different ``core.autocrlf`` is not reported as different
      code. NOTE: the two live copies of this plugin were verified to be pure-LF
      already, so this normalisation is defensive, not the thing that makes them
      agree — do not cite it as evidence they match.
    * **Length-framed entries.** Each record is ``<relpath>\\0<bytelen>\\0<bytes>``,
      so no combination of names and contents can be re-partitioned into a
      different tree with the same digest.
    * **No filtering.** Every file under ``Source/`` is hashed verbatim. A skip-list
      is a place for a difference to hide, and this function exists to find
      differences.

    Raises ResolutionError if there is no ``Source/`` dir or it holds no files: an
    empty digest would be a hash that matches nothing and alarms about nothing.
    """
    root = Path(plugin_dir) / _PLUGIN_SOURCE_SUBDIR
    if not root.is_dir():
        raise ResolutionError(
            "plugin source tree not found: {} has no {}/ directory".format(
                plugin_dir, _PLUGIN_SOURCE_SUBDIR))
    files = sorted((p for p in root.rglob("*") if p.is_file()),
                   key=lambda p: p.relative_to(root).as_posix())
    if not files:
        raise ResolutionError(
            "plugin source tree {} contains no files — refusing to emit a digest "
            "that would match nothing".format(root))
    h = hashlib.sha256()
    for p in files:
        rel = p.relative_to(root).as_posix()
        data = p.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(str(len(data)).encode("ascii"))
        h.update(b"\0")
        h.update(data)
    return h.hexdigest()


def resolve_plugin_source_hash(repo_root=None, arg=None, plugin_dir=None):
    """Resolve a plugin dir, then hash its ``Source/`` tree.

    Returns ``Resolved(<sha256 hex>, source)`` where ``source`` is the rung that
    answered — the same ladder discipline as every other resolver here:

        1. ``plugin_dir`` / ``arg`` (an explicit plugin directory) -> "arg"
        2. ``$WF_BRIDGE_PLUGIN_SOURCE``                            -> "env"
        3. a worktree of ``repo_root`` carrying Plugins/WorldForge/Source -> "discovered"

    There is no registry rung: the shared registry knows about engines, not plugins
    (same as ``resolve_plugin_source``). If no rung answers this raises
    ResolutionError — it never falls back to a baked constant, because a baked
    constant here would be a hash that silently claims agreement it never checked.

    ``plugin_dir`` is the rung Lane C wants: hand it the TARGET project's
    ``<project>/Plugins/WorldForge`` and compare the result to
    ``BridgeRequest.required_plugin_source_hash`` before booting the editor.
    """
    explicit = plugin_dir or arg
    if explicit:
        return Resolved(hash_plugin_source(explicit), "arg")
    env = os.environ.get(ENV_PLUGIN_SOURCE)
    if env:
        return Resolved(hash_plugin_source(env), "env")
    if repo_root:
        found = _worktree_with_plugin_source(repo_root)
        if found:
            return Resolved(hash_plugin_source(found), "discovered")
    raise ResolutionError(
        "cannot resolve a WorldForge plugin source tree to hash. Pass plugin_dir=, "
        "or set {}, or call with repo_root= so a worktree can be discovered."
        .format(ENV_PLUGIN_SOURCE))


def plugin_source_hash_matches(required, observed):
    """Compare a caller's pinned source hash against the observed one.

    Returns ``(ok, detail)``. ``ok`` is True only on an exact match of two non-empty
    digests. An unstated pin (``required`` is None/empty) returns **False** with a
    detail saying so: "nobody pinned it" is an unverified claim, not a passing one,
    and the caller must decide whether an unpinned run is acceptable rather than
    having this function decide by returning True.

    The caller maps a False result to WF1026_BRIDGE_STALE_PLUGIN.
    """
    if not required:
        return False, ("no required_plugin_source_hash was stated — plugin source "
                       "identity is unverified (observed {})".format(
                           (observed or "?")[:12]))
    if not observed:
        return False, ("no plugin source hash could be observed on disk to compare "
                       "against required {}".format(required[:12]))
    if required == observed:
        return True, "plugin source hash matches ({})".format(required[:12])
    return False, ("plugin source hash mismatch: required {} != observed {} — the "
                   "far side is running different plugin source".format(
                       required[:12], observed[:12]))


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
