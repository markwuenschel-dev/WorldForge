#!/usr/bin/env python3
r"""
biome_slice.py -- one-command biome slice orchestrator (Phase 2).

    make biome-slice BIOME=desert VARIANT=industrialized

Chains the whole slice pipeline so the current proof can be rebuilt without
manual editor clicking:

    1. read procedural/slices/<BIOME>_<VARIANT>.yaml
    2. authoring-side: validate + manifest each recipe and placement definition
    3. emit the resolved JSON spec the UE render script consumes
       (procedural/reports/slices/_active_slice.json -- JSON, never YAML in UE)
    4. launch the headless editor to (re)build + render the before/after proof
    5. score render_report.json against the slice's `acceptance` block
    6. write <output_dir>/biome_slice_result.json

This module runs in plain WSL Python (PyYAML is fine here -- the no-YAML rule
only applies to scripts that `import unreal`). The UE step is launched as a
Windows process via WSL interop.

Env overrides (defaults target this machine's UE 5.7 install):
    UE_EDITOR_CMD   path to UnrealEditor-cmd.exe (WSL /mnt/... form)
    WF_UPROJECT     path to the .uproject (WSL form; default: repo/WorldForge.uproject)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SLICES_DIR = REPO / "procedural" / "slices"
ACTIVE_SLICE = REPO / "procedural" / "reports" / "slices" / "_active_slice.json"
RENDER_SCRIPT = REPO / "tools" / "unreal" / "build_and_render_desert_valley.py"

DEFAULT_EDITOR = "/mnt/c/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-cmd.exe"


def _run(cmd, label):
    """Run an authoring-side step, streaming output; raise on failure."""
    print("\n[biome-slice] $ {}".format(" ".join(str(c) for c in cmd)))
    proc = subprocess.run(cmd, cwd=str(REPO))
    if proc.returncode != 0:
        raise SystemExit("[biome-slice] FAILED ({}): {}".format(label, " ".join(map(str, cmd))))


def run_authoring(cfg):
    """Validate + manifest every recipe and placement definition in the slice."""
    py = sys.executable
    for recipe in cfg.get("recipes", []):
        _run([py, "tools/substance/validate_recipe.py", "--recipe", recipe], "validate-recipe")
        _run([py, "tools/pipeline/generate_manifest.py", "--recipe", recipe], "generate-manifest")
    for definition in cfg.get("placement_definitions", []):
        _run([py, "tools/pipeline/validate_placement.py", "--definition", definition], "validate-placement")
        _run([py, "tools/pipeline/generate_placement_manifest.py", "--definition", definition],
             "generate-placement-manifest")


def write_active_slice(cfg, slug):
    """Resolve the slice YAML into the flat JSON spec the UE render script reads."""
    st = cfg["state"]
    render = cfg.get("render", {})
    spec = {
        "slug": slug,
        "map": cfg["map"],
        "terrain_mi": render["terrain_mi"],
        "placement_data_asset": render["placement_data_asset"],
        "state": {"scope": st["scope"], "context_id": st["context_id"], "key": st["key"]},
        "states": [st["before"], st["after"]],
        "resolution": render.get("resolution", [1600, 900]),
        "seed": render.get("seed", 424242),
    }
    # Render-proof terrain look: an explicit per-variant base color (linear RGB)
    # that the UE render script lerps toward soot via MPC. This bypasses the
    # headless MIC texture-override bug so variants are visibly distinct. Optional
    # -- absent => render script keeps its old MI-driven path.
    if render.get("preview_base_color") is not None:
        spec["preview_base_color"] = render["preview_base_color"]
    ACTIVE_SLICE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_SLICE.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    # Keep a copy alongside the proof for provenance.
    out_dir = REPO / cfg["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "_slice_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print("[biome-slice] active slice spec -> {}".format(ACTIVE_SLICE))
    return spec


def _to_win(path):
    """WSL path -> Windows path with forward slashes (UE accepts forward slashes)."""
    win = subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()
    return win.replace("\\", "/")


def launch_render(editor, uproject):
    """Boot the headless editor to run the render script. Needs a REAL RHI (no -NullRHI)."""
    if not os.path.isfile(editor):
        raise SystemExit("[biome-slice] editor not found: {} (set UE_EDITOR_CMD)".format(editor))
    cmd = [
        editor,
        _to_win(uproject),
        "-ExecutePythonScript={}".format(_to_win(RENDER_SCRIPT)),
        "-unattended", "-nopause", "-nosplash", "-nosound", "-stdout",
    ]
    print("\n[biome-slice] launching headless render (this boots UE, ~minutes)...")
    print("[biome-slice] $ {}".format(" ".join(cmd)))
    started = time.time()
    proc = subprocess.run(cmd)
    print("[biome-slice] editor exited rc={} after {:.0f}s".format(proc.returncode, time.time() - started))
    return " ".join(cmd), proc.returncode


def _map_name(cfg):
    """Basename of the slice map, e.g. '/Game/Maps/Desert_Valley_01' -> 'Desert_Valley_01'."""
    return cfg["map"].rstrip("/").rsplit("/", 1)[-1]


def score(cfg, render_report_path, editor_rc=0):
    """Compare render_report.json against the acceptance block, accumulating HARD
    failure reasons. `passed` is true only when `failures` is empty."""
    acc = cfg.get("acceptance", {})
    result = {"mpc_updates": False, "foliage_increases": {}, "foliage_decreases": {},
              "screenshots_saved": False, "passed": False, "failures": []}
    fail = result["failures"].append

    if editor_rc != 0:
        fail("editor exited non-zero (rc={})".format(editor_rc))

    if not render_report_path.is_file():
        fail("render_report.json missing at {} -- editor did not produce a report".format(render_report_path))
        return result
    try:
        report = json.loads(render_report_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        fail("render_report.json is not valid JSON: {}".format(e))
        return result

    result["render_status"] = report.get("status")
    if report.get("status") != "ok":
        fail("render status={!r}; errors={}".format(report.get("status"), report.get("errors")))

    # Regression guard: the render must run in the slice's actual map, not a
    # transient 'Untitled' world (the new_level-on-existing-map bug).
    expected_world = _map_name(cfg)
    result["editor_world"] = report.get("editor_world")
    if report.get("editor_world") != expected_world:
        fail("editor_world={!r}, expected {!r} (map failed to load/save?)".format(
            report.get("editor_world"), expected_world))

    steps = report.get("steps", [])
    if len(steps) < 2:
        fail("expected 2 render steps, got {}".format(len(steps)))
        return result
    before, after = steps[0], steps[-1]

    result["mpc_updates"] = bool(before.get("mpc_matches_set")) and bool(after.get("mpc_matches_set"))
    if not result["mpc_updates"]:
        fail("MPC did not mirror state at both steps (mpc_matches_set false)")

    def count(step, species):
        return step.get("foliage", {}).get(species, {}).get("instances")

    for sp in acc.get("foliage_increases", []):
        b, a = count(before, sp), count(after, sp)
        ok = b is not None and a is not None and a > b
        result["foliage_increases"][sp] = {"before": b, "after": a, "ok": ok}
        if not ok:
            fail("foliage '{}' expected to INCREASE: before={} after={}".format(sp, b, a))
    for sp in acc.get("foliage_decreases", []):
        b, a = count(before, sp), count(after, sp)
        ok = b is not None and a is not None and a < b
        result["foliage_decreases"][sp] = {"before": b, "after": a, "ok": ok}
        if not ok:
            fail("foliage '{}' expected to DECREASE: before={} after={}".format(sp, b, a))

    # The UE script runs on Windows, so report paths may use backslash separators;
    # normalize before resolving against the (POSIX) repo root. Require non-empty files.
    shots = [REPO / s["screenshot"].replace("\\", "/") for s in steps if s.get("screenshot")]
    missing = [str(p) for p in shots if not (p.is_file() and p.stat().st_size > 0)]
    result["screenshots_saved"] = len(shots) >= 2 and not missing
    if not result["screenshots_saved"]:
        fail("screenshots missing/empty: {}".format(missing or "fewer than 2 captured"))

    result["passed"] = not result["failures"]
    return result


def main():
    ap = argparse.ArgumentParser(description="Build + prove a biome slice end to end.")
    ap.add_argument("--biome", required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--no-render", action="store_true",
                    help="Run authoring + emit spec, but skip the headless UE launch.")
    ap.add_argument("--editor", default=os.environ.get("UE_EDITOR_CMD", DEFAULT_EDITOR))
    ap.add_argument("--uproject", default=os.environ.get("WF_UPROJECT", str(REPO / "WorldForge.uproject")))
    args = ap.parse_args()

    slug = "{}_{}".format(args.biome, args.variant)
    cfg_path = SLICES_DIR / "{}.yaml".format(slug)
    if not cfg_path.is_file():
        raise SystemExit("[biome-slice] no slice config: {}".format(cfg_path))
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    print("[biome-slice] slice '{}' (biome={} variant={})".format(slug, cfg.get("biome"), cfg.get("variant")))

    out_dir = REPO / cfg["output_dir"]
    report_path = out_dir / "render_report.json"
    ue_cmd = None
    editor_rc = 0

    run_authoring(cfg)
    write_active_slice(cfg, slug)

    if args.no_render:
        print("[biome-slice] --no-render: skipping headless UE launch.")
    else:
        # Remove stale render outputs so a missing report after the run is an
        # unambiguous failure rather than a previous run's data scoring as pass.
        if report_path.is_file():
            report_path.unlink()
        for png in (out_dir / "screenshots").glob("*.png"):
            png.unlink()
        ue_cmd, editor_rc = launch_render(args.editor, args.uproject)

    acceptance = score(cfg, report_path, editor_rc) if not args.no_render else None

    result = {
        "biome": args.biome,
        "variant": args.variant,
        "slug": slug,
        "authoring": "ok",
        "rendered": not args.no_render,
        "acceptance": acceptance,
        "ue_command": ue_cmd,
        "outputs": {
            "slice_spec": str((out_dir / "_slice_spec.json").relative_to(REPO)),
            "render_report": str((out_dir / "render_report.json").relative_to(REPO)),
            "screenshots_dir": str((out_dir / "screenshots").relative_to(REPO)),
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "biome_slice_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\n[biome-slice] result -> {}".format(out_dir / "biome_slice_result.json"))

    if acceptance is not None:
        verdict = "PASS" if acceptance["passed"] else "FAIL"
        print("[biome-slice] acceptance: {}".format(verdict))
        if not acceptance["passed"]:
            for reason in acceptance["failures"]:
                print("[biome-slice]   - {}".format(reason))
            raise SystemExit("[biome-slice] slice FAILED ({} check(s) failed)".format(
                len(acceptance["failures"])))
    else:
        print("[biome-slice] authoring + spec ready; run without --no-render to render the proof.")


if __name__ == "__main__":
    main()
