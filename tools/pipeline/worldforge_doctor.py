#!/usr/bin/env python3
r"""worldforge_doctor.py — WorldForge v0.9 local factory health command.

ONE read-only command that reports whether the local factory is healthy enough
to *build and validate* WorldForge content. It is the superset companion to
``ue_doctor.py`` (which focuses on booting UE): worldforge-doctor checks the
whole authoring-side toolchain — Python, hard dependencies, repo layout,
definition/pack/registry readability, report writability — and surfaces the
UE/editor surface as a non-blocking environment warning plus the canonical
D7-gated Content-materialization note.

NON-MUTATING: it never writes into project ``Content/**`` or any registry. The
only thing it writes is its own report under
``procedural/reports/worldforge_doctor/``.

Usage:
    python tools/pipeline/worldforge_doctor.py            # health check
    python tools/pipeline/worldforge_doctor.py --strict   # strict: soft WARNs block
    python tools/pipeline/worldforge_doctor.py --quiet     # suppress per-check lines

Strict mode is also honored via the STRICT env var (STRICT=1), matching the
v0.9 validation contract. Strict only ever ADDS blocking: missing/optional UE
tooling stays non-blocking even under strict; a *malformed* definition / pack /
registry becomes blocking under strict.

Exit 0 when healthy (status ok|warn), 1 when a blocking check FAILs.
"""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

# This file lives in tools/pipeline/. Make sibling contract modules importable
# regardless of the caller's working directory.
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from validation_report import (  # noqa: E402  (sibling contract module)
    ValidationReport,
    strict_from_env,
    GATED_HUMAN_EDITOR_NOTE,
    PASS,
    WARN,
    WARN_ONLY,
    FAIL,
    GATED_HUMAN_EDITOR,
    SKIP_NOT_APPLICABLE,
)
from failure_codes import FailureCode  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

REPORT_DIR_REL = "procedural/reports/worldforge_doctor"
REPORT_FILENAME = "worldforge_doctor_report.json"

# Minimum Python the repo's tooling expects.
MIN_PY = (3, 8)

# Hard Python deps validators import at module load — missing => FAIL.
HARD_DEPS = (("numpy", "numpy"), ("pyyaml", "yaml"))
# Recommended deps — missing => WARN (only some validators need them).
RECOMMENDED_DEPS = (("Pillow", "PIL"),)

# Required directories for a usable factory checkout.
REQUIRED_DIRS = (
    "procedural/definitions",
    "procedural/generated",
    "procedural/reports",
    "tools/pipeline",
    "tools/unreal",
)

# Default UE editor locations (mirrors ue_doctor.py; intentionally duplicated so
# this file stays self-contained and does NOT import/modify ue_doctor.py).
DEFAULT_EDITOR_WSL = "/mnt/c/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-cmd.exe"
DEFAULT_EDITOR_WIN = r"C:\Program Files\Epic Games\UE_5.7\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"

# Houdini / generated-asset intake ledger (the registry Agent 6 hardens).
GENERATED_ASSET_REGISTRY_REL = "procedural/generated/worldforge_generated_asset_registry.json"


def _is_wsl():
    try:
        with open("/proc/version") as f:
            return "microsoft" in f.read().lower()
    except Exception:
        return False


def _default_editor():
    return DEFAULT_EDITOR_WSL if _is_wsl() else DEFAULT_EDITOR_WIN


def _has_module(import_name):
    try:
        return importlib.util.find_spec(import_name) is not None
    except Exception:
        return False


def _load_yaml():
    """Return the yaml module if importable, else None (dep check reports it)."""
    try:
        import yaml  # noqa: F401
        return yaml
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Individual checks. Each records exactly one contract check whose ``detail`` is
# the next action to fix the problem.
# ---------------------------------------------------------------------------

def check_python_version(rep):
    cur = sys.version_info
    ok = (cur.major, cur.minor) >= MIN_PY
    detail = (
        "Python {}.{}.{} OK (>= {}.{})".format(cur.major, cur.minor, cur.micro, *MIN_PY)
        if ok else
        "Python {}.{}.{} too old — install Python {}.{}+ and re-run".format(
            cur.major, cur.minor, cur.micro, *MIN_PY)
    )
    rep.check("python_version", ok, detail)


def check_hard_deps(rep):
    for dist, import_name in HARD_DEPS:
        present = _has_module(import_name)
        detail = (
            "{} importable".format(import_name) if present
            else "missing hard dep '{}' — run: pip install {}".format(import_name, dist)
        )
        rep.check("dep_" + import_name, present, detail)


def check_recommended_deps(rep):
    for dist, import_name in RECOMMENDED_DEPS:
        present = _has_module(import_name)
        detail = (
            "{} importable".format(import_name) if present
            else "recommended dep '{}' absent (terrain/pack-score need it) — "
                 "run: pip install {}".format(import_name, dist)
        )
        rep.warn_only("dep_" + import_name, present, detail)


def check_required_dirs(rep):
    for rel in REQUIRED_DIRS:
        p = REPO_ROOT / rel
        ok = p.is_dir()
        detail = (
            str(p) if ok
            else "required directory missing: {} — restore it from the repo".format(rel)
        )
        rep.check("dir_" + rel.replace("/", "_"), ok, detail)


def check_editor(rep):
    editor = os.environ.get("UE_EDITOR_CMD", _default_editor())
    ok = os.path.isfile(editor)
    detail = (
        "UE editor found: {}".format(editor) if ok
        else "UE editor not found at {} — set UE_EDITOR_CMD (pure-Python build "
             "steps still work without it)".format(editor)
    )
    # Non-blocking in BOTH modes: a pure-Python build/validate run does not need
    # UE installed, so this must not fail even under --strict.
    rep.warn_only("unreal_editor_path", ok, detail)


def check_headless_runner(rep):
    unreal_dir = REPO_ROOT / "tools" / "unreal"
    runners = sorted((REPO_ROOT / "tools" / "pipeline").glob("run_*_ue.py")) + \
        sorted((REPO_ROOT / "tools" / "pipeline").glob("run_ue_*.py"))
    ok = unreal_dir.is_dir() and len(runners) > 0
    detail = (
        "headless UE runner present ({} runner script(s), tools/unreal present)".format(len(runners))
        if ok else
        "headless UE runner unavailable — expected tools/unreal + tools/pipeline/run_*_ue.py "
        "(pure-Python steps still work)"
    )
    rep.warn_only("ue_headless_runner", ok, detail)


def check_utf8(rep):
    enc = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
    pythonutf8 = os.environ.get("PYTHONUTF8", "0")
    ok = enc == "utf8" or pythonutf8 == "1"
    detail = (
        "UTF-8 output forced (PYTHONUTF8=1 or utf-8 stdout)" if ok
        else "set PYTHONUTF8=1 before running tools (Windows cp1252 crashes on emoji output)"
    )
    rep.warn_only("python_utf8", ok, detail)


def check_definitions_readable(rep, yaml_mod):
    def_root = REPO_ROOT / "procedural" / "definitions"
    if not def_root.is_dir():
        rep.skip("definitions_readable", "procedural/definitions absent (covered by dir check)")
        return
    yamls = sorted(def_root.rglob("*.yaml")) + sorted(def_root.rglob("*.yml"))
    if not yamls:
        rep.warn_only("definitions_readable", False,
                      "no definition YAMLs under procedural/definitions — author some first")
        return
    if yaml_mod is None:
        rep.skip("definitions_readable", "pyyaml missing (covered by dep check) — cannot parse")
        return
    sample = yamls[:3]
    bad = []
    for p in sample:
        try:
            yaml_mod.safe_load(p.read_text(encoding="utf-8"))
        except Exception as exc:
            bad.append("{} ({})".format(p.relative_to(REPO_ROOT), exc))
    ok = not bad
    detail = (
        "parsed {} sampled definition(s) of {} found".format(len(sample), len(yamls)) if ok
        else "unparseable definition(s): {} — fix the YAML".format("; ".join(bad))
    )
    rep.check("definitions_readable", ok, detail, warn_only=True,
              code=FailureCode.DESCRIPTOR_UNPARSEABLE)


def check_pack_definitions_readable(rep, yaml_mod):
    packs = sorted((REPO_ROOT / "procedural" / "world_packs").glob("*.yaml")) + \
        sorted((REPO_ROOT / "procedural" / "slice_packs").glob("*.yaml"))
    if not packs:
        rep.warn_only("pack_definitions_readable", False,
                      "no world_packs/*.yaml or slice_packs/*.yaml found — define a pack first")
        return
    if yaml_mod is None:
        rep.skip("pack_definitions_readable", "pyyaml missing (covered by dep check) — cannot parse")
        return
    bad = []
    for p in packs:
        try:
            yaml_mod.safe_load(p.read_text(encoding="utf-8"))
        except Exception as exc:
            bad.append("{} ({})".format(p.relative_to(REPO_ROOT), exc))
    ok = not bad
    detail = (
        "parsed {} pack definition(s)".format(len(packs)) if ok
        else "unparseable pack(s): {} — fix the YAML".format("; ".join(bad))
    )
    rep.check("pack_definitions_readable", ok, detail, warn_only=True,
              code=FailureCode.SPEC_INVALID)


def check_registry_roots_readable(rep):
    gen = REPO_ROOT / "procedural" / "generated"
    registries = sorted(gen.glob("worldforge_*registry*.json")) if gen.is_dir() else []
    if not registries:
        rep.warn_only("registry_roots_readable", False,
                      "no worldforge_*registry*.json yet — nothing built/tracked")
        return
    bad = []
    total_entries = 0
    for p in registries:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                total_entries += len(data)
        except Exception as exc:
            bad.append("{} ({})".format(p.name, exc))
    ok = not bad
    detail = (
        "parsed {} registry root(s), {} total entries".format(len(registries), total_entries) if ok
        else "unparseable registry root(s): {} — fix or regenerate".format("; ".join(bad))
    )
    rep.check("registry_roots_readable", ok, detail, warn_only=True,
              code=FailureCode.REGISTRY_INCONSISTENT)


def check_houdini_registry_readable(rep):
    p = REPO_ROOT / GENERATED_ASSET_REGISTRY_REL
    if not p.is_file():
        rep.warn_only("houdini_generated_asset_registry", False,
                      "no generated-asset registry yet ({}) — register an intake asset "
                      "to create it".format(GENERATED_ASSET_REGISTRY_REL))
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        n = len(data) if isinstance(data, dict) else 0
        rep.check("houdini_generated_asset_registry", True,
                  "generated-asset registry readable — {} asset(s) tracked".format(n))
    except Exception as exc:
        rep.check("houdini_generated_asset_registry", False,
                  "generated-asset registry unparseable: {} — fix the JSON".format(exc),
                  warn_only=True, code=FailureCode.REGISTRY_INCONSISTENT)


def check_report_writable(rep, report_dir):
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        probe = report_dir / ".worldforge_doctor_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        rep.check("report_dir_writable", True, str(report_dir))
    except Exception as exc:
        rep.check("report_dir_writable", False,
                  "cannot write report dir {}: {} — check permissions".format(report_dir, exc))


def add_d7_materialization_note(rep):
    """Informational, always-present, never-blocking D7 line (canonical wording)."""
    rep.gated("content_materialization_d7", False, GATED_HUMAN_EDITOR_NOTE,
              code=FailureCode.UE_MATERIALIZATION_PENDING)


# ---------------------------------------------------------------------------
# Console rendering
# ---------------------------------------------------------------------------

_TAG = {
    PASS: "[OK   ]",
    WARN: "[WARN ]",
    WARN_ONLY: "[WARN ]",
    FAIL: "[FAIL ]",
    GATED_HUMAN_EDITOR: "[GATED]",
    SKIP_NOT_APPLICABLE: "[SKIP ]",
}


def print_checks(rep):
    for name, c in rep.checks.items():
        verdict = c.get("verdict", PASS)
        tag = _TAG.get(verdict, "[????]")
        block = " (blocks)" if c.get("blocking") else ""
        print("  {} {}{} — {}".format(tag, name, block, c.get("detail", "")))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge local factory health command (read-only).")
    ap.add_argument("--strict", action="store_true",
                    help="strict mode: soft WARNs (malformed inputs) become blocking")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress the per-check listing (summary only)")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    report_dir = REPO_ROOT / REPORT_DIR_REL

    yaml_mod = _load_yaml()

    rep = ValidationReport("doctor", "worldforge_local_factory", strict=strict)

    # Hard environment / toolchain.
    check_python_version(rep)
    check_hard_deps(rep)
    check_recommended_deps(rep)
    check_required_dirs(rep)

    # UE / editor surface (non-blocking — pure-Python steps still work).
    check_editor(rep)
    check_headless_runner(rep)
    check_utf8(rep)

    # Readability of the things validators consume.
    check_definitions_readable(rep, yaml_mod)
    check_pack_definitions_readable(rep, yaml_mod)
    check_registry_roots_readable(rep)
    check_houdini_registry_readable(rep)

    # Doctor's own output surface.
    check_report_writable(rep, report_dir)

    # D7-gated Content materialization (informational, canonical wording).
    add_d7_materialization_note(rep)

    rep.finalize()

    print("WORLDFORGE DOCTOR — local factory health (strict={})".format("on" if strict else "off"))
    if not args.quiet:
        print_checks(rep)

    counts = rep.to_dict()["counts"]
    print("COUNTS: " + ", ".join("{}={}".format(k, v) for k, v in counts.items() if v))

    rep.write(report_dir, REPORT_FILENAME)
    rep.print_summary("worldforge-doctor")

    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
