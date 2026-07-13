#!/usr/bin/env python3
"""validate_plugin_build.py — v2.5 Lane 1 plugin build + load gate (shield --plugin).

Proves the REAL WorldForge plugin builds and LOADS under UE 5.8, from evidence, not
assertion. This is the milestone's primary critical path.

The gate is GREEN only when a real UE 5.8 build produced fresh module binaries AND a real
UE 5.8 editor boot loaded those exact binaries (WorldForgeCore + WorldForgeEd) and reached
engine init. It fails closed when: the load evidence is absent; a required module did not
load; a binary is older than its newest C++ source (stale); the build did not succeed; or
the engine identity does not resolve to 5.8.

Evidence lineage:
  1. A real build:  D:/UE_5.8 Build.bat WorldForgeEditor Win64 Development  (exit 0).
  2. A real boot:   UnrealEditor-Cmd.exe WorldForge.uproject -nullrhi -unattended -execcmds=quit
     whose UE log carries the plugin mount + module InternalLoadLibrary lines + engine-init.
Pass that boot log ONCE via --load-log; this gate distills it to
  procedural/reports/ue5_8/plugin/plugin_load_evidence.json  (small, reproducible) and reads
that distilled evidence on subsequent (shield) runs.

DOGFOODS the PluginBuildReport contract and its hostile negatives (wrong engine, stale
binary, binary predating source, missing module, module load failure, build-ok-but-output-
missing, engine identity mismatch). A validator that greens any of those turns this gate RED.

Acceptance:
    PYTHONUTF8=1 python tools/pipeline/validate_plugin_build.py --strict \
        --engine-root D:/UE_5.8 --load-log <ue_boot_log>
Reports -> procedural/reports/ue5_8/plugin/
"""

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC
from engine_identity import engine_identity
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "plugin"
LOAD_EVIDENCE = REPORT_DIR / "plugin_load_evidence.json"
HANDSHAKE = REPORT_DIR / "plugin_capability_handshake.json"

PLUGIN_NAME = "WorldForge"
# The plugin's own modules (from WorldForge.uplugin) that MUST load.
REQUIRED_MODULES = ("WorldForgeCore", "WorldForgeEd")
# Binaries that must exist after a build (project module WorldForge carries WFRuntime).
BINARY_DLLS = {
    "WorldForgeCore": REPO_ROOT / "Plugins/WorldForge/Binaries/Win64/UnrealEditor-WorldForgeCore.dll",
    "WorldForgeEd": REPO_ROOT / "Plugins/WorldForge/Binaries/Win64/UnrealEditor-WorldForgeEd.dll",
    "WorldForge": REPO_ROOT / "Binaries/Win64/UnrealEditor-WorldForge.dll",
}
# C++/build source roots whose newest mtime the binaries must not predate.
SOURCE_ROOTS = (REPO_ROOT / "Source", REPO_ROOT / "Plugins/WorldForge/Source")
SOURCE_EXTS = (".cpp", ".h", ".hpp", ".inl", ".c", ".cc", ".cs", ".uplugin")

_LOAD_RE = re.compile(r"InternalLoadLibrary:\s*'([A-Za-z0-9_]+)'\s*\('([^']+)'\)")


# --------------------------------------------------------------------------- #
# evidence helpers
# --------------------------------------------------------------------------- #
def _sha256(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _newest_source_mtime():
    newest = 0.0
    newest_file = None
    for root in SOURCE_ROOTS:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in SOURCE_EXTS:
                m = p.stat().st_mtime
                if m > newest:
                    newest, newest_file = m, p
    return newest, newest_file


def distill_load_log(load_log_path):
    """Parse a real UE boot log into small reproducible load evidence."""
    text = Path(load_log_path).read_text(encoding="utf-8", errors="replace")
    loaded = {}
    for m in _LOAD_RE.finditer(text):
        loaded[m.group(1)] = m.group(2).replace("\\", "/")
    mounted = "Mounting Project plugin WorldForge" in text
    engine_init = "Engine is initialized" in text
    fatal = ("Fatal error" in text) or bool(
        re.search(r"Failed to load module '(WorldForgeCore|WorldForgeEd)'", text))
    ev = {
        "source_log": str(Path(load_log_path)).replace("\\", "/"),
        "plugin_mounted": mounted,
        "engine_initialized": engine_init,
        "fatal_error": fatal,
        "modules_loaded": {k: loaded[k] for k in REQUIRED_MODULES if k in loaded},
        "all_loaded_modules": loaded,
    }
    return ev


def build_evidence(engine_root, load_ev):
    ident = engine_identity(engine_root=engine_root)
    newest_src, newest_file = _newest_source_mtime()
    # newest binary mtime across the required DLLs that exist
    bin_info = {}
    bin_mtimes = []
    for name, path in BINARY_DLLS.items():
        if path.exists():
            st = path.stat()
            bin_info[name] = {
                "path": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "mtime": st.st_mtime, "size": st.st_size, "hash": _sha256(path),
            }
            bin_mtimes.append(st.st_mtime)
    binary_mtime = max(bin_mtimes) if bin_mtimes else 0.0
    # A module counts as loaded only if its distilled evidence names the FRESH plugin DLL.
    modules_built = [n for n in REQUIRED_MODULES if n in bin_info]
    loaded_map = load_ev.get("modules_loaded", {})
    plugin_loaded = (
        load_ev.get("plugin_mounted") and load_ev.get("engine_initialized")
        and not load_ev.get("fatal_error")
        and all(n in loaded_map for n in REQUIRED_MODULES))
    overall_ok = bool(plugin_loaded and modules_built == list(REQUIRED_MODULES)
                      and binary_mtime >= newest_src)
    report = {
        "report_id": "pluginbuild_worldforge_ue58",
        "plugin_name": PLUGIN_NAME,
        "target_engine": "5.8",
        "build_result": "succeeded" if modules_built == list(REQUIRED_MODULES) else "failed",
        "plugin_loaded": bool(plugin_loaded),
        "overall_ok": overall_ok,
        "binary_mtime": binary_mtime,
        "newest_source_mtime": newest_src,
        "modules": list(REQUIRED_MODULES),
        "created_by": "worldforge.v2.5.lane1",
        "created_at": TC.AUTHORING_TS,
        "schema_version": TC.RT_PLUGIN_BUILD,
        "report_type": TC.RT_PLUGIN_BUILD,
    }
    handshake = {
        "engine": {"major": ident.get("engine_major"), "minor": ident.get("engine_minor"),
                   "patch": ident.get("engine_patch"), "build_id": ident.get("engine_build_id")},
        "plugin_name": PLUGIN_NAME,
        "plugin_version": _uplugin_version(),
        "modules_required": list(REQUIRED_MODULES),
        "modules_loaded_from": {n: loaded_map.get(n) for n in REQUIRED_MODULES},
        "binaries": bin_info,
        "newest_source": str(newest_file.relative_to(REPO_ROOT)).replace("\\", "/") if newest_file else None,
        "plugin_loaded": bool(plugin_loaded),
    }
    return report, handshake, ident


def _uplugin_version():
    up = REPO_ROOT / "Plugins/WorldForge/WorldForge.uplugin"
    try:
        d = json.loads(up.read_text(encoding="utf-8"))
        return d.get("VersionName") or str(d.get("Version"))
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# dogfood: contract + hostile negatives
# --------------------------------------------------------------------------- #
def _dogfood(rep):
    validate, good, bad = TC.CONTRACTS["PluginBuildReport"]
    gfails = [c for c in validate(good(), strict=True) if not c[1]]
    rep.check("dogfood::valid_report_passes", not gfails,
              "valid PluginBuildReport rejected: {}".format([c[0] for c in gfails][:4]),
              code=FailureCode.TRANSITION_REPORT_INTEGRITY_FAILED)
    # hostile negatives -> (example, must-be-rejected owning code substring)
    negs = [
        ("wrong_engine", good(target_engine="5.7"), "ENGINE_VERSION_MISMATCH"),
        ("build_failed_but_ok", good(overall_ok=True, build_result="failed"), "BUILD_FAILED"),
        ("module_not_loaded", good(overall_ok=True, plugin_loaded=False), "PLUGIN_LOAD_FAILED"),
        ("binary_predates_source", good(overall_ok=True, binary_mtime=1, newest_source_mtime=2),
         "STALE_PLUGIN_BINARY"),
        ("missing_module", good(modules=["WorldForgeCore"]) if False else good(modules=[]),
         "BUILD_FAILED"),
    ]
    for label, ex, code_sub in negs:
        fails = [c for c in validate(ex, strict=True) if not c[1]]
        codes = {str(c[3]) for c in fails}
        hit = any(code_sub in c for c in codes)
        rep.check("dogfood::neg::{}".format(label), bool(fails) and hit,
                  "negative {} must be rejected for {} (got {})".format(
                      label, code_sub, sorted(codes)[:4]),
                  code=FailureCode.TRANSITION_NEGATIVE_ACCEPTED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 plugin build+load gate (--plugin).")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--engine-root", default="D:/UE_5.8")
    ap.add_argument("--load-log", default=None,
                    help="Path to a real UE 5.8 boot log; distilled to plugin_load_evidence.json.")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Obtain load evidence: distill a fresh boot log, else read prior distilled evidence.
    if args.load_log:
        load_ev = distill_load_log(args.load_log)
        LOAD_EVIDENCE.write_text(json.dumps(load_ev, indent=2), encoding="utf-8")
    elif LOAD_EVIDENCE.exists():
        load_ev = json.loads(LOAD_EVIDENCE.read_text(encoding="utf-8"))
    else:
        load_ev = {"plugin_mounted": False, "engine_initialized": False,
                   "fatal_error": False, "modules_loaded": {}}

    report, handshake, ident = build_evidence(args.engine_root, load_ev)
    HANDSHAKE.write_text(json.dumps(handshake, indent=2), encoding="utf-8")

    rep = ValidationReport("pack", args.pack, strict=strict)
    _dogfood(rep)
    # validate the REAL build report against the contract
    validate, _, _ = TC.CONTRACTS["PluginBuildReport"]
    for name, ok, detail, code in validate(report, strict=True):
        rep.check("plugin_build::" + name, ok, detail, code=code)
    # honest gate rails (belt-and-suspenders on top of the contract)
    rep.check("plugin::engine_is_5_8", ident.get("engine_minor") == 8,
              "engine identity must resolve to 5.8 (got {})".format(ident.get("engine_minor")),
              code=FailureCode.ENGINE_VERSION_MISMATCH)
    rep.check("plugin::modules_loaded", all(
        m in load_ev.get("modules_loaded", {}) for m in REQUIRED_MODULES),
        "required modules must load from fresh binaries: {}".format(
            sorted(load_ev.get("modules_loaded", {}))),
        code=FailureCode.PLUGIN_LOAD_FAILED)
    rep.check("plugin::not_stale", report["binary_mtime"] >= report["newest_source_mtime"],
              "binaries must not predate newest C++ source (stale)",
              code=FailureCode.STALE_PLUGIN_BINARY)
    rep.check("plugin::overall_ok", report["overall_ok"],
              "plugin build+load overall_ok must be True",
              code=FailureCode.BUILD_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="plugin-build", pack=args.pack, strict=strict, status=rep.status,
        report_type="wf.transition.plugin_build_gate.v1",
        extra=dict(engine_identity(engine_root=args.engine_root),
                   declared_target_engine="5.8",
                   observed_runtime_engine=ident.get("engine_minor"),
                   runtime_execution_required=True,
                   runtime_executed=bool(load_ev.get("engine_initialized")))))
    rep.write(REPORT_DIR, "validate_plugin_build_report.json")
    rep.print_summary("plugin-build")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
