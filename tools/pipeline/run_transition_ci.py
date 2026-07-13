#!/usr/bin/env python3
"""run_transition_ci.py — WorldForge v2.5 UE 5.7->5.8 CI matrix orchestrator (Lane 5).

CI for the transition must do two things HONESTLY at once:
  1. Run the gates that need no engine (the schema / contract / hostile tier) for
     REAL, on hosted no-UE runners, and report their true pass/fail.
  2. For gates that need an install or a live runtime, print the EXACT command it
     WOULD run against the explicitly-resolved engine and mark them GATED — never
     fabricate a UE result, never let a no-UE runner claim a runtime GREEN.

This orchestrator does exactly that. It discovers the python-only gates by
PRESENCE (a sibling gate script that a later wave has not yet built is marked
SKIPPED/pending, not a hard failure), runs the ones that exist, and for every UE
gate emits the would-run command with the engine paths from
discover_unreal_engine baked in. It then writes a CI summary report whose
build_meta records — unforgeably — that no runtime engine was observed and no
runtime was executed on this invocation.

Cache-key isolation: a helper derives an engine-specific cache key from
(version, build_id, plugin_commit, project_commit) and the orchestrator ASSERTS
the 5.7 and 5.8 keys differ, so a 5.7 build cache can never be reused for a 5.8
job (that is precisely how stale 5.7 artifacts get laundered as a 5.8 baseline).

Usage (canonical — `make` is optional; run directly):
    PYTHONUTF8=1 python tools/pipeline/run_transition_ci.py --engine 5.8 --python-only

Windows UTF-8: run with PYTHONUTF8=1. No emoji. Stdlib only.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import discover_unreal_engine as DUE  # noqa: E402
from report_meta import build_meta  # noqa: E402
from engine_identity import engine_identity  # noqa: E402

PY = sys.executable
UPROJECT = REPO_ROOT / "WorldForge.uproject"

# CI summary reports route under the 5.8 evidence subtree's ci/ folder (5.7 is the
# frozen tree; the transition's forward-looking CI evidence belongs to 5.8).
CI_REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "ci"

# The gate execution ORDER for the matrix (canonical keys from DUE.GATE_MATRIX).
GATE_ORDER = (
    "transition-contracts",
    "transition-topology",
    "capability-manifest",
    "gloam-bridge",
    "transition-negatives",
    "transition-fuzz",
    "transition-report-integrity",
    "transition-hygiene",
    "plugin-compile",
    "editor-smoke",
    "commandlet-smoke",
    "conversion-manifest",
    "transition-regression",
    "new-features",
    "full-baseline",
    "final-shield",
)

# Extra argv for python gates that accept a --strict flag.
PYTHON_GATE_ARGS = {
    "transition-contracts": ["--strict"],
    "transition-topology": ["--strict"],
    "capability-manifest": ["--strict"],
    "gloam-bridge": ["--strict"],
    "transition-fuzz": ["--strict"],
    "transition-report-integrity": ["procedural/reports/ue5_8", "--strict"],
    "transition-hygiene": ["--strict"],
    "transition-negatives": [],
}


def would_run_command(gate, disc):
    """Return the exact command string a UE gate WOULD run with the resolved engine.

    ``disc`` is a discover_unreal_engine.discover_engine() result carrying the
    concrete engine_exe / build_bat / uproject for the requested version. These
    are representative of the runtime lanes' invocations, with the EXPLICIT engine
    substituted so no ambiguity about which install would execute.
    """
    exe = disc.get("engine_exe")
    bat = disc.get("build_bat")
    up = disc.get("uproject")
    if gate == "plugin-compile":
        return '"{}" WorldForgeEditor Win64 Development -Project="{}" -waitmutex'.format(bat, up)
    if gate == "editor-smoke":
        return ('"{}" "{}" /Game/Maps/encounter_loop_world '
                '-unattended -nullrhi -nosplash -nosound -stdout -log').format(exe, up)
    if gate == "commandlet-smoke":
        return ('"{}" "{}" -run=WorldForgeRuntimeSmoke '
                '-unattended -nullrhi -stdout -log').format(exe, up)
    if gate == "conversion-manifest":
        return ('"{}" "{}" -run=ResavePackages -unattended -nullrhi -stdout   '
                '# then: {} python tools/pipeline/validate_conversion_manifest.py --strict').format(
                    exe, up, "PYTHONUTF8=1")
    if gate == "transition-regression":
        return ('"{}" "{}" -run=WorldForgeRuntimeSmoke -unattended -nullrhi -stdout   '
                '# then: {} python tools/pipeline/transition_regression.py --strict').format(
                    exe, up, "PYTHONUTF8=1")
    if gate == "new-features":
        return ('"{}" "{}" -run=WorldForgeRuntimeSmoke -unattended -nullrhi -stdout   '
                '# v2.5 net-new runtime feature proof on {}').format(exe, up, disc.get("build_id"))
    if gate == "full-baseline":
        return ('"{}" "{}" -unattended -nullrhi -stdout   '
                '# then: {} python tools/pipeline/build_transition_baseline.py --strict '
                '&& validate_transition_baseline.py --strict').format(exe, up, "PYTHONUTF8=1")
    if gate == "final-shield":
        return ('{} python tools/pipeline/v2_5_shield.py --strict '
                '--topology --conversion --plugin --capability --regression '
                '--baseline --bridge --hostile --regressions').format("PYTHONUTF8=1")
    return "(no command template for gate {!r})".format(gate)


def run_python_gate(gate, spec):
    """Run a present python gate for real; discover-by-presence handles absence."""
    script = spec.get("script")
    script_path = REPO_ROOT / script if script else None
    if not script or script_path is None or not script_path.is_file():
        return {
            "gate": gate, "kind": spec["kind"], "status": "SKIPPED",
            "detail": "sibling script not yet built ({}) — pending a later wave".format(script),
            "returncode": None, "command": None,
        }
    argv = PYTHON_GATE_ARGS.get(gate, [])
    cmd = [PY, str(script_path), *argv]
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    ok = proc.returncode == 0
    return {
        "gate": gate, "kind": spec["kind"],
        "status": "PASS" if ok else "FAIL",
        "detail": (proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "")[:200],
        "returncode": proc.returncode,
        "command": "python {} {}".format(script, " ".join(argv)).strip(),
    }


def gate_engine_cache_key(version):
    """Build an engine-specific cache key from (version, build_id, plugin, project).

    Two engines that share a worktree (same project/plugin commit) MUST still
    yield different keys, because their build artifacts are incompatible. The
    engine build_id is what guarantees that separation.
    """
    disc = DUE.discover_engine(version)
    parts = [
        "wf-transition",
        "ue" + str(version),
        "build=" + str(disc.get("build_id")),
        "plugin=" + str(disc.get("plugin_commit")),
        "project=" + str(disc.get("project_commit")),
    ]
    return "|".join(parts)


def assert_cache_isolation():
    """Prove 5.7 and 5.8 cache keys can never collide. Returns the proof dict."""
    k57 = gate_engine_cache_key("5.7")
    k58 = gate_engine_cache_key("5.8")
    assert k57 != k58, "CACHE ISOLATION VIOLATION: 5.7 and 5.8 cache keys are identical!"
    return {"key_5_7": k57, "key_5_8": k58, "isolated": k57 != k58}


def run_matrix(engine, python_only):
    """Run the CI matrix for one declared target engine. Returns (results, disc)."""
    disc = DUE.discover_engine(engine)
    results = []
    for gate in GATE_ORDER:
        spec = DUE.GATE_MATRIX[gate]
        if not spec["requires_engine"] and not spec["requires_runtime"]:
            # Python-only tier — run for real (or SKIP if not yet built).
            results.append(run_python_gate(gate, spec))
        else:
            # Install / runtime tier — NEVER executed here; print the would-run cmd.
            results.append({
                "gate": gate, "kind": spec["kind"], "status": "GATED",
                "detail": "requires UE run ({}); command printed, not executed".format(
                    "runtime" if spec["requires_runtime"] else "install/compile"),
                "returncode": None,
                "command": would_run_command(gate, disc),
                "requires_engine": spec["requires_engine"],
                "requires_runtime": spec["requires_runtime"],
            })
    return results, disc


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 UE 5.7->5.8 CI matrix orchestrator.")
    ap.add_argument("--engine", choices=DUE.SUPPORTED_VERSIONS, default="5.8",
                    help="declared target engine for this CI run (default 5.8)")
    ap.add_argument("--python-only", action="store_true",
                    help="run the no-UE gate tier only; mark UE gates GATED (default behaviour "
                         "still never executes UE, but records runtime_execution_required=True)")
    args = ap.parse_args(argv)

    print("=" * 72)
    print("WorldForge v2.5 transition CI — declared target engine {}  (python_only={})".format(
        args.engine, bool(args.python_only)))
    print("=" * 72)

    # Cache isolation is proven BEFORE anything else — a violation is fatal.
    cache = assert_cache_isolation()
    print("cache isolation: 5.7 key != 5.8 key -> {}".format(cache["isolated"]))
    print("  5.7 -> {}".format(cache["key_5_7"]))
    print("  5.8 -> {}".format(cache["key_5_8"]))
    print("-" * 72)

    results, disc = run_matrix(args.engine, args.python_only)

    for r in results:
        line = "  [{:<7}] {:<28} {}".format(r["status"], r["gate"], r.get("detail", ""))
        print(line)
        if r["status"] == "GATED" and r.get("command"):
            print("            would run: {}".format(r["command"]))

    ran = [r for r in results if r["status"] in ("PASS", "FAIL")]
    failed = [r for r in ran if r["status"] == "FAIL"]
    skipped = [r for r in results if r["status"] == "SKIPPED"]
    gated = [r for r in results if r["status"] == "GATED"]

    print("-" * 72)
    print("python gates: {} ran, {} passed, {} failed | {} skipped(pending) | {} GATED(UE)".format(
        len(ran), len(ran) - len(failed), len(failed), len(skipped), len(gated)))

    # --- CI summary report with an unforgeable runtime-provenance block --------
    build_meta_block = {
        "declared_target_engine": args.engine,
        "observed_runtime_engine": None,
        "runtime_execution_required": (not args.python_only),
        "runtime_executed": False,
        "engine_discovery": {
            "engine_root": disc.get("engine_root"),
            "engine_exe": disc.get("engine_exe"),
            "build_bat": disc.get("build_bat"),
            "build_id": disc.get("build_id"),
        },
        "cache_isolation": cache,
    }
    status = "ok" if not failed else "fail"
    meta = build_meta(
        command="run-transition-ci", pack="worldforge_vertical_slice",
        strict=True, status=status,
        record_count=len(results), records_total=len(results),
        records_passed=len([r for r in results if r["status"] == "PASS"]),
        records_failed=len(failed),
        records_skipped=len(skipped) + len(gated),
        report_type="wf.transition.ci_summary.v1",
        extra={**engine_identity(), **{"build_meta": build_meta_block}})
    report = {
        "report_type": "wf.transition.ci_summary.v1",
        "declared_target_engine": args.engine,
        "python_only": bool(args.python_only),
        "build_meta": build_meta_block,
        "gate_results": results,
        "summary": {
            "python_ran": len(ran), "python_passed": len(ran) - len(failed),
            "python_failed": len(failed), "skipped_pending": len(skipped),
            "ue_gated": len(gated),
        },
        "status": status,
        "meta": meta,
    }
    CI_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    fname = "transition_ci_summary_ue{}.json".format(args.engine.replace(".", "_"))
    out_path = CI_REPORT_DIR / fname
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        shown = out_path.relative_to(REPO_ROOT)
    except ValueError:
        shown = out_path
    print("CI summary -> {}".format(shown))

    # Exit code tracks REAL failures of executed python gates only. SKIPPED
    # (pending) and GATED (UE) are honest not-yet-run states, not failures — the
    # v2.5 shield is the fail-closed authority over those. A no-UE CI run is
    # GREEN iff every python gate that exists passed.
    verdict = "GREEN" if not failed else "RED"
    print("transition CI ({}): {}".format(args.engine, verdict))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
