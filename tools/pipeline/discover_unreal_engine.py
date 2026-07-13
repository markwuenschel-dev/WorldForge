#!/usr/bin/env python3
"""discover_unreal_engine.py — WorldForge v2.5 engine + gate discovery (Lane 5).

The v2.5 transition runs the SAME procedural pipeline against two Unreal installs
(frozen 5.7 and active 5.8). Build automation must resolve — deterministically and
WITHOUT guessing — *which* engine a gate should run against and *whether that gate
needs the engine at all* (schema gates need neither an install nor a runtime; a
plugin compile needs the install but not a running editor; an editor/commandlet
smoke needs a live runtime). Getting this wrong is how 5.7 evidence gets laundered
as a 5.8 baseline, or how a "GREEN" is claimed for a gate that never actually ran.

This tool answers three questions for CI:
    1. Given ``--version 5.7|5.8``  -> resolve the install: engine_root, the
       UnrealEditor-Cmd.exe launcher, the Build.bat path, and the build_id
       (changelist@branch) read from Engine/Build/Build.version.
    2. Given ``--gate <name>``      -> report (requires_engine, requires_runtime)
       for that gate so an orchestrator knows whether it may run it headless-free,
       must have an install, or must have a live runtime.
    3. Given ``--table``            -> print the full v2.5 gate matrix.

Resolution is DELEGATED to engine_identity (imported, not duplicated): a ``--version``
maps to engine_identity.KNOWN_ENGINE_ROOTS and is passed as an explicit engine_root
to engine_identity.resolve_engine_root / engine_identity(). The build_id therefore
reflects the engine that would actually run, never the uproject EngineAssociation.

Windows UTF-8: run with PYTHONUTF8=1. No emoji in any emitted string. Stdlib only.
"""

import argparse
import json
import sys
from pathlib import Path

# engine_identity lives next to this file (tools/pipeline/). Import its resolver so
# engine-root resolution is done in exactly ONE place, repo-wide.
try:
    from engine_identity import (
        KNOWN_ENGINE_ROOTS,
        engine_identity,
        resolve_engine_root,
    )
except ImportError:  # pragma: no cover - allow running from another cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from engine_identity import (
        KNOWN_ENGINE_ROOTS,
        engine_identity,
        resolve_engine_root,
    )

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
UPROJECT = WORKTREE_ROOT / "WorldForge.uproject"

# The two engine minors the transition spans.
SUPPORTED_VERSIONS = ("5.7", "5.8")

# --------------------------------------------------------------------------- #
# The v2.5 CI gate matrix — one source of truth for (requires_engine,
# requires_runtime) per gate. This is what lets an orchestrator decide, without
# guessing, which gates it may run in a no-UE CI lane vs. which are GATED behind
# a real install / a live runtime.
#
#   requires_engine  = the gate needs a resolvable UE install on disk
#   requires_runtime = the gate needs a LIVE engine process (editor / commandlet /
#                      runtime smoke). A plugin *compile* needs the install
#                      (Build.bat) but NOT a running editor, so it is
#                      engine=True, runtime=False.
#
# Keys are the shield/CI gate names; aliases (below) map the mission's CI-matrix
# row labels onto these canonical keys.
# --------------------------------------------------------------------------- #
GATE_MATRIX = {
    # --- Python-only gates: no install, no runtime (always runnable in CI) ----
    "transition-contracts": {
        "requires_engine": False, "requires_runtime": False, "kind": "python",
        "script": "tools/pipeline/validate_transition_contracts.py",
        "desc": "transition contract-spine schema gate (always-on)"},
    "transition-topology": {
        "requires_engine": False, "requires_runtime": False, "kind": "python",
        "script": "tools/pipeline/validate_transition_topology.py",
        "desc": "transition topology / registry schema gate"},
    "capability-manifest": {
        "requires_engine": False, "requires_runtime": False, "kind": "python",
        "script": "tools/pipeline/validate_capability_manifest.py",
        "desc": "capability manifest SHAPE gate (availability handshake is a UE gate)"},
    "gloam-bridge": {
        "requires_engine": False, "requires_runtime": False, "kind": "python",
        "script": "tools/pipeline/validate_gloam_bridge.py",
        "desc": "Gloamstead rejecting-dry-probe contract gate"},
    "transition-negatives": {
        "requires_engine": False, "requires_runtime": False, "kind": "python",
        "script": "tools/pipeline/transition_negatives.py",
        "desc": "hostile: known-bad negatives must be rejected"},
    "transition-fuzz": {
        "requires_engine": False, "requires_runtime": False, "kind": "python",
        "script": "tools/pipeline/transition_fuzz.py",
        "desc": "hostile: fuzz corpus must not fake-green"},
    "transition-report-integrity": {
        "requires_engine": False, "requires_runtime": False, "kind": "python",
        "script": "tools/pipeline/transition_report_integrity.py",
        "desc": "hostile: emitted reports carry honest meta/engine identity"},
    "transition-hygiene": {
        "requires_engine": False, "requires_runtime": False, "kind": "python",
        "script": "tools/pipeline/transition_hygiene.py",
        "desc": "hostile: no absolute-path / cross-engine leaks"},

    # --- Install required, but NO live runtime: a compile only ----------------
    "plugin-compile": {
        "requires_engine": True, "requires_runtime": False, "kind": "ue_build",
        "script": "tools/pipeline/validate_plugin_build.py",
        "desc": "compile WorldForge plugin (Build.bat WorldForgeEditor) — no editor launch"},

    # --- Live runtime required: editor / commandlet / runtime smokes ----------
    "editor-smoke": {
        "requires_engine": True, "requires_runtime": True, "kind": "ue_runtime",
        "script": None,
        "desc": "launch UnrealEditor-Cmd, load the slice map, prove it opens"},
    "commandlet-smoke": {
        "requires_engine": True, "requires_runtime": True, "kind": "ue_runtime",
        "script": None,
        "desc": "run a commandlet headless (e.g. resave/audit) and prove it exits 0"},
    "conversion-manifest": {
        "requires_engine": True, "requires_runtime": True, "kind": "ue_runtime",
        "script": "tools/pipeline/validate_conversion_manifest.py",
        "desc": "5.7->5.8 asset/map conversion (resave commandlet) + actor accounting"},
    "transition-regression": {
        "requires_engine": True, "requires_runtime": True, "kind": "ue_runtime",
        "script": "tools/pipeline/transition_regression.py",
        "desc": "re-run v2.4/2.3/2.2 runtime smokes under 5.8"},
    "new-features": {
        "requires_engine": True, "requires_runtime": True, "kind": "ue_runtime",
        "script": None,
        "desc": "prove v2.5 net-new runtime behaviour on the target engine"},
    "full-baseline": {
        "requires_engine": True, "requires_runtime": True, "kind": "ue_runtime",
        "script": "tools/pipeline/validate_transition_baseline.py",
        "desc": "one-time authorized 5.8 baseline evidence index (real runtime evidence)"},
    "final-shield": {
        "requires_engine": True, "requires_runtime": True, "kind": "aggregate",
        "script": "tools/pipeline/v2_5_shield.py",
        "desc": "aggregate v2.5 shield (folds every gate above; runtime lanes gated)"},
}

# Mission CI-matrix row labels -> canonical gate keys (so --gate accepts either).
GATE_ALIASES = {
    "python-contracts": "transition-contracts",
    "python": "transition-contracts",
    "contracts": "transition-contracts",
    "plugin-build": "plugin-compile",
    "plugin": "plugin-compile",
    "editor": "editor-smoke",
    "commandlet": "commandlet-smoke",
    "conversion": "conversion-manifest",
    "regression": "transition-regression",
    "baseline": "full-baseline",
    "features": "new-features",
    "shield": "final-shield",
}


def canonical_gate(name):
    """Resolve a gate label (canonical key or alias) to its canonical key."""
    if name in GATE_MATRIX:
        return name
    return GATE_ALIASES.get(name)


def _launcher_paths(engine_root):
    """Return (engine_exe, build_bat) Paths under an engine root (existence unchecked)."""
    root = Path(engine_root)
    engine_exe = root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
    build_bat = root / "Engine" / "Build" / "BatchFiles" / "Build.bat"
    return engine_exe, build_bat


def discover_engine(version, gate=None):
    """Resolve the install for a version; fold in a gate's runtime requirement.

    ``version`` in {"5.7","5.8"}. Resolution is delegated to engine_identity:
    the version maps to KNOWN_ENGINE_ROOTS and is passed as an explicit
    engine_root so the returned build_id reflects the resolved install's
    Build.version, never the uproject EngineAssociation.
    """
    known = KNOWN_ENGINE_ROOTS.get(version)
    root, resolution = resolve_engine_root(known)
    ident = engine_identity(engine_root=str(root) if root is not None else None)
    engine_exe, build_bat = (None, None)
    if root is not None:
        engine_exe, build_bat = _launcher_paths(root)

    out = {
        "requested_version": version,
        "engine_root": str(root) if root is not None else None,
        "engine_root_exists": bool(root is not None and Path(root).is_dir()),
        "engine_exe": str(engine_exe) if engine_exe is not None else None,
        "engine_exe_exists": bool(engine_exe is not None and engine_exe.is_file()),
        "build_bat": str(build_bat) if build_bat is not None else None,
        "build_bat_exists": bool(build_bat is not None and build_bat.is_file()),
        "engine_major": ident.get("engine_major"),
        "engine_minor": ident.get("engine_minor"),
        "engine_patch": ident.get("engine_patch"),
        "build_id": ident.get("engine_build_id"),
        "project_commit": ident.get("project_commit"),
        "plugin_commit": ident.get("plugin_commit"),
        "project_path_identity": ident.get("project_path_identity"),
        "uproject": str(UPROJECT),
        "resolution": resolution,
    }
    if gate is not None:
        key = canonical_gate(gate)
        if key is None:
            out["gate"] = gate
            out["gate_error"] = "unknown gate {!r}; known: {}".format(
                gate, sorted(list(GATE_MATRIX.keys()) + list(GATE_ALIASES.keys())))
        else:
            spec = GATE_MATRIX[key]
            out["gate"] = key
            out["gate_alias_of"] = None if key == gate else gate
            out["requires_engine"] = spec["requires_engine"]
            out["requires_runtime"] = spec["requires_runtime"]
            out["gate_kind"] = spec["kind"]
            out["gate_script"] = spec["script"]
            out["gate_desc"] = spec["desc"]
    return out


def gate_table():
    """Return the full gate matrix as an ordered list of row dicts."""
    rows = []
    for name, spec in GATE_MATRIX.items():
        rows.append({
            "gate": name,
            "requires_engine": spec["requires_engine"],
            "requires_runtime": spec["requires_runtime"],
            "kind": spec["kind"],
            "script": spec["script"],
            "desc": spec["desc"],
        })
    return rows


def _print_table():
    rows = gate_table()
    w = max(len(r["gate"]) for r in rows)
    print("v2.5 gate matrix (engine_required / runtime_required):")
    print("  {:<{w}}  engine  runtime  kind".format("gate", w=w))
    print("  {}".format("-" * (w + 26)))
    for r in rows:
        print("  {:<{w}}  {:<6}  {:<7}  {}".format(
            r["gate"], "yes" if r["requires_engine"] else "no",
            "yes" if r["requires_runtime"] else "no", r["kind"], w=w))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Resolve a UE install for a version and/or report a gate's "
                    "engine/runtime requirement (v2.5 transition).")
    ap.add_argument("--version", choices=SUPPORTED_VERSIONS,
                    help="engine minor to resolve (5.7 frozen, 5.8 active)")
    ap.add_argument("--gate", help="gate name (or CI-matrix alias) to report requirements for")
    ap.add_argument("--table", action="store_true", help="print the full gate matrix and exit")
    args = ap.parse_args(argv)

    if args.table and not (args.version or args.gate):
        _print_table()
        return 0

    if not args.version:
        # A gate-only query still needs a version to resolve an install; default
        # to the active target engine so --gate alone is answerable.
        version = "5.8"
    else:
        version = args.version

    result = discover_engine(version, gate=args.gate)
    if args.table:
        result["gate_matrix"] = gate_table()
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    # Non-zero only when a resolution genuinely failed (root unresolved) or an
    # unknown gate was named — CI can trust the exit code.
    if result.get("engine_root") is None or result.get("gate_error"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
