#!/usr/bin/env python3
"""tools/bridge/fixture.py — the far-side UE 5.8 FIXTURE project (a separate repo).

DoD #17 requires the bridge to be proven against a SEPARATE UE 5.8 project. This
module creates that far side: a minimal, self-contained UE 5.8 project living
OUTSIDE the WorldForge repository, in its own git repository, that references the
WorldForge plugin.

Why a fixture rather than Gloamstead: Gloamstead is not present on this machine.
The honest move is a project that is genuinely separate — its own directory, its
own .uproject, its own git history, its own plugin copy — and to SAY it is a
stand-in (the live report carries fixture_standin=True / is_gloamstead_target=False)
rather than dress it up as Gloamstead. What it proves is the bridge mechanism; what
it does not prove is Gloamstead compatibility, and neither this module nor the live
report claims otherwise.

The fixture is deliberately minimal — no Source, no maps, no content beyond what the
operation authors. It is a *binary* plugin host: the plugin's 5.8 DLLs are copied in
and the project has no C++ module of its own, so the editor loads the plugin from
its precompiled binaries and never needs to invoke a compiler.

Everything is parameterised: the fixture root, the plugin source, and the engine all
arrive by argument or environment (see paths.py). Nothing here is a baked constant
tied to one machine.

Self-contained: stdlib only.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

# The fixture's project name. Note it does NOT contain "gloam": the far side is
# honestly a fixture, and naming it Gloam* to satisfy a substring check elsewhere
# would be exactly the laundering this lane exists to prevent.
FIXTURE_PROJECT_NAME = "WFBridgeFixture58"

# Top-level directories the fixture project legitimately owns. Evidence rooted
# anywhere else belongs to another project (WF1024).
FIXTURE_ROOT_DIRS = frozenset({"Content", "Saved", "Config", "Plugins"})

_UPROJECT = {
    "FileVersion": 3,
    "EngineAssociation": "5.8",
    "Category": "BridgeFixture",
    "Description": ("Separate UE 5.8 fixture project: the far side of the WorldForge "
                    "cross-repository bridge. Not Gloamstead; a stand-in that proves "
                    "the bridge mechanism against a genuinely separate project."),
    "Plugins": [
        {"Name": "WorldForge", "Enabled": True},
        {"Name": "PythonScriptPlugin", "Enabled": True},
        {"Name": "EditorScriptingUtilities", "Enabled": True},
    ],
}

_DEFAULT_ENGINE_INI = """[/Script/EngineSettings.GameMapsSettings]
GameDefaultMap=/Engine/Maps/Templates/OpenWorld
EditorStartupMap=/Engine/Maps/Templates/OpenWorld
"""

_GITIGNORE = """Saved/
Intermediate/
DerivedDataCache/
"""

_PLUGIN_BINARIES = (
    "UnrealEditor-WorldForgeCore.dll",
    "UnrealEditor-WorldForgeEd.dll",
    "UnrealEditor.modules",
)


def _git(args, cwd, check=True):
    return subprocess.run(["git"] + args, cwd=str(cwd), check=check,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def uproject_path(fixture_root):
    return Path(fixture_root) / "{}.uproject".format(FIXTURE_PROJECT_NAME)


def plugin_build_id(plugin_binaries_dir):
    """The BuildId the plugin DLLs were compiled against, or None."""
    mod = Path(plugin_binaries_dir) / "UnrealEditor.modules"
    if not mod.is_file():
        return None
    try:
        return json.loads(mod.read_text(encoding="utf-8")).get("BuildId")
    except (ValueError, OSError):
        return None


def engine_build_id(engine_root):
    """The engine's own BuildId, or None."""
    mod = Path(engine_root) / "Engine/Binaries/Win64/UnrealEditor.modules"
    if not mod.is_file():
        return None
    try:
        return json.loads(mod.read_text(encoding="utf-8")).get("BuildId")
    except (ValueError, OSError):
        return None


def create_fixture(fixture_root, plugin_source, engine_root, force=False):
    """Create (or refresh) the fixture project + its own git repo. Returns a dict.

    ``plugin_source`` is the directory holding WorldForge.uplugin AND 5.8-built
    Binaries/Win64. The BuildId of those binaries is checked against the engine's:
    a mismatch means the plugin would silently fail to load (WF1019), so we refuse
    up front rather than produce a confusing red later.
    """
    fixture_root = Path(fixture_root)
    plugin_source = Path(plugin_source)
    src_bin = plugin_source / "Binaries" / "Win64"

    uplugin = plugin_source / "WorldForge.uplugin"
    if not uplugin.is_file():
        raise FileNotFoundError("no WorldForge.uplugin at {}".format(uplugin))

    p_build = plugin_build_id(src_bin)
    e_build = engine_build_id(engine_root)
    if p_build is None:
        raise FileNotFoundError(
            "no built plugin binaries at {} — the fixture needs 5.8-built DLLs "
            "(BuildId {}). Build the plugin under UE 5.8 first.".format(src_bin, e_build))
    if p_build != e_build:
        raise RuntimeError(
            "plugin BuildId {!r} != engine BuildId {!r}: these binaries were built "
            "against a different engine and would not load (WF1019 stale plugin "
            "binary). Rebuild the plugin under {}.".format(p_build, e_build, engine_root))

    if force and fixture_root.exists():
        shutil.rmtree(fixture_root)

    (fixture_root / "Content").mkdir(parents=True, exist_ok=True)
    (fixture_root / "Config").mkdir(parents=True, exist_ok=True)
    dst_plugin = fixture_root / "Plugins" / "WorldForge"
    dst_bin = dst_plugin / "Binaries" / "Win64"
    dst_bin.mkdir(parents=True, exist_ok=True)

    shutil.copy2(uplugin, dst_plugin / "WorldForge.uplugin")
    for name in _PLUGIN_BINARIES:
        src = src_bin / name
        if not src.is_file():
            raise FileNotFoundError("missing plugin binary {}".format(src))
        shutil.copy2(src, dst_bin / name)

    up = uproject_path(fixture_root)
    up.write_text(json.dumps(_UPROJECT, indent=4) + "\n", encoding="utf-8")
    (fixture_root / "Config" / "DefaultEngine.ini").write_text(
        _DEFAULT_ENGINE_INI, encoding="utf-8")
    (fixture_root / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")

    # Its own git repository — this is what makes "target_commit resolved" a real
    # resolution across a repository boundary rather than an echo of our own SHA.
    if not (fixture_root / ".git").exists():
        _git(["init", "-q"], fixture_root)
    _git(["add", "-A", "-f"], fixture_root)
    status = _git(["status", "--porcelain"], fixture_root).stdout.decode()
    head = _git(["rev-parse", "HEAD"], fixture_root, check=False)
    if status.strip() or head.returncode != 0:
        _git(["-c", "user.name=WorldForge Bridge Fixture",
              "-c", "user.email=bridge@worldforge.local",
              "commit", "-q", "-m",
              "WFBridgeFixture58: minimal separate UE 5.8 project referencing the "
              "WorldForge plugin"], fixture_root)

    commit = _git(["rev-parse", "HEAD"], fixture_root).stdout.decode().strip()
    return {
        "fixture_root": str(fixture_root).replace("\\", "/"),
        "project_name": FIXTURE_PROJECT_NAME,
        "uproject": str(up).replace("\\", "/"),
        "repository": fixture_root.name,
        "commit": commit,
        "plugin_build_id": p_build,
        "engine_build_id": e_build,
        "plugin_source": str(plugin_source).replace("\\", "/"),
    }


def fixture_git_head(fixture_root):
    """HEAD of the fixture's own repo, or None when it is not a repo."""
    r = _git(["rev-parse", "HEAD"], fixture_root, check=False)
    return r.stdout.decode().strip() if r.returncode == 0 else None


def is_outside(fixture_root, repo_root):
    """True iff the fixture really lives outside the WorldForge repository."""
    try:
        Path(fixture_root).resolve().relative_to(Path(repo_root).resolve())
        return False
    except ValueError:
        return True
