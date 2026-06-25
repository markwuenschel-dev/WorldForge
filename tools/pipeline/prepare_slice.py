#!/usr/bin/env python3
"""prepare_slice.py

Lane B of the WorldForge "slice factory": given a generated slice spec JSON,
prepare/verify the *authoring-side* and *on-disk* assets it references, so the
UE map build can rely on them.

This is plain python (NO `import unreal`). It only does authoring-side recipe /
placement prep (validate + manifest) and verifies that the UE assets the spec
points at already exist on disk. CREATING missing UE assets needs the editor and
is explicitly OUT of scope -- this lane validates and prints an actionable hint.

Spec shape (produced by tools/pipeline/create_slice_spec.py):
    {
      "slice_id": "...", "biome": "...", "variant": "...",
      "terrain":   {"material_recipe": "...", "material_mi": "/Game/..."},
      "placement": {"definition": "...", "data_asset": "/Game/...",
                    "pcg_graph": "/Game/..."},
      ...
    }

Usage:
    python tools/pipeline/prepare_slice.py --spec <path-to-generated-json>

Exit code:
    0  -> all authoring steps passed AND material_mi + data_asset exist on disk
    1  -> any authoring step failed, or a required asset is missing on disk
          (pcg_graph missing is a WARNING, not fatal)
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# tools/pipeline/ -> repo root is two levels up.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Authoring-side scripts (repo-relative). Run with the same interpreter.
VALIDATE_RECIPE = "tools/substance/validate_recipe.py"
GENERATE_MANIFEST = "tools/pipeline/generate_manifest.py"
VALIDATE_PLACEMENT = "tools/pipeline/validate_placement.py"
GENERATE_PLACEMENT_MANIFEST = "tools/pipeline/generate_placement_manifest.py"


def fail(msg: str) -> "NoReturn":
    sys.stderr.write(f"ERROR: {msg}\n")
    sys.exit(2)


def get_nested(spec: dict, *keys: str):
    """Walk nested dict keys, returning None if any level is missing."""
    cur = spec
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def run_step(label: str, script_rel: str, arg_flag: str, arg_value: str) -> bool:
    """Run an authoring script as a subprocess, streaming its output.

    Returns True on exit code 0, False otherwise. Output is inherited (streamed)
    so the user sees the underlying validator/manifest messages live.
    """
    script_path = REPO_ROOT / script_rel
    print(f"\n=== {label} ===")
    if not script_path.is_file():
        print(f"  ! script not found: {script_rel}")
        return False
    argv = [sys.executable, str(script_path), arg_flag, str(arg_value)]
    print(f"  $ {Path(sys.executable).name} {script_rel} {arg_flag} {arg_value}")
    sys.stdout.flush()  # keep our header ahead of the child's inherited stdout
    try:
        result = subprocess.run(argv, cwd=str(REPO_ROOT))
    except OSError as exc:  # pragma: no cover - defensive
        print(f"  ! failed to launch: {exc}")
        return False
    ok = result.returncode == 0
    print(f"  -> {'OK' if ok else 'FAIL'} (exit {result.returncode})")
    return ok


def game_path_to_disk(game_path: str):
    """Convert a UE object path to a repo-relative Content/*.uasset disk path.

    /Game/Foo/Bar              -> Content/Foo/Bar.uasset
    /SomePlugin/Foo/Bar        -> Plugins/SomePlugin/Content/Foo/Bar.uasset  (best-effort)

    Returns a Path (absolute, under REPO_ROOT) or None if the root is unknown.
    A trailing ".SomeObject" (UE package.object suffix) is stripped first.
    """
    if not isinstance(game_path, str) or not game_path.startswith("/"):
        return None

    # Strip a UE package.object suffix if present (e.g. /Game/X/MI.MI -> /Game/X/MI).
    path = game_path
    last = path.rsplit("/", 1)[-1]
    if "." in last:
        pkg, _, _obj = last.rpartition(".")
        path = path[: -len(last)] + pkg

    parts = [p for p in path.split("/") if p]
    if not parts:
        return None

    root = parts[0]
    rest = parts[1:]
    if not rest:
        return None

    if root == "Game":
        disk = REPO_ROOT / "Content" / Path(*rest)
    else:
        # Best-effort plugin mount: /<Plugin>/... -> Plugins/<Plugin>/Content/...
        disk = REPO_ROOT / "Plugins" / root / "Content" / Path(*rest)

    return disk.with_suffix(".uasset")


def check_asset(label: str, game_path):
    """Resolve a /Game/ path to disk and check existence.

    Returns (present: bool, disk_path: Path|None, resolvable: bool).
    """
    if not game_path:
        print(f"  - {label:14s} MISSING (no path in spec)")
        return (False, None, False)
    disk = game_path_to_disk(game_path)
    if disk is None:
        print(f"  - {label:14s} UNRESOLVED ({game_path} -> unknown mount root)")
        return (False, None, False)
    present = disk.is_file()
    rel = disk.relative_to(REPO_ROOT).as_posix() if disk.is_relative_to(REPO_ROOT) else str(disk)
    status = "PRESENT" if present else "MISSING"
    print(f"  - {label:14s} {status}  {game_path} -> {rel}")
    return (present, disk, True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare/verify authoring-side + on-disk assets for a slice spec."
    )
    parser.add_argument("--spec", required=True, help="path to a generated slice spec JSON")
    args = parser.parse_args(argv)

    # Line-buffer our stdout so our headers stay interleaved correctly with the
    # inherited stdout of the authoring subprocesses (matters when piped, e.g.
    # through WSL where the default is block buffering).
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):  # pragma: no cover - older/odd streams
        pass

    spec_path = Path(args.spec)
    if not spec_path.is_file():
        fail(f"spec not found: {spec_path}")

    try:
        with spec_path.open("r", encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"could not read spec JSON {spec_path}: {exc}")

    if not isinstance(spec, dict):
        fail(f"spec {spec_path} did not parse to a JSON object")

    slice_id = spec.get("slice_id", "<unknown>")
    material_recipe = get_nested(spec, "terrain", "material_recipe")
    material_mi = get_nested(spec, "terrain", "material_mi")
    placement_def = get_nested(spec, "placement", "definition")
    data_asset = get_nested(spec, "placement", "data_asset")
    pcg_graph = get_nested(spec, "placement", "pcg_graph")

    print("=" * 64)
    print(f"PREPARE SLICE: {slice_id}")
    print(f"  spec:             {spec_path}")
    print(f"  material_recipe:  {material_recipe}")
    print(f"  placement_def:    {placement_def}")
    print("=" * 64)

    # --- Authoring steps ---------------------------------------------------
    steps = []  # (label, ok)

    if material_recipe:
        steps.append(("validate-recipe",
                      run_step("validate recipe", VALIDATE_RECIPE, "--recipe", material_recipe)))
        steps.append(("generate-manifest",
                      run_step("generate material manifest", GENERATE_MANIFEST, "--recipe", material_recipe)))
    else:
        print("\n! spec.terrain.material_recipe missing -- cannot run material authoring steps")
        steps.append(("validate-recipe", False))
        steps.append(("generate-manifest", False))

    if placement_def:
        steps.append(("validate-placement",
                      run_step("validate placement", VALIDATE_PLACEMENT, "--definition", placement_def)))
        steps.append(("generate-placement-manifest",
                      run_step("generate placement manifest", GENERATE_PLACEMENT_MANIFEST, "--definition", placement_def)))
    else:
        print("\n! spec.placement.definition missing -- cannot run placement authoring steps")
        steps.append(("validate-placement", False))
        steps.append(("generate-placement-manifest", False))

    # --- On-disk asset verification ---------------------------------------
    print("\n=== verify on-disk UE assets ===")
    mi_present, _, _ = check_asset("material_mi", material_mi)
    da_present, _, _ = check_asset("data_asset", data_asset)
    pcg_present, _, pcg_resolvable = check_asset("pcg_graph", pcg_graph)

    # --- Summary -----------------------------------------------------------
    print("\n" + "=" * 64)
    print("PREPARE SUMMARY")
    print("=" * 64)
    print(f"  slice: {slice_id}")
    print("  authoring steps:")
    all_steps_ok = True
    for label, ok in steps:
        print(f"    [{'OK  ' if ok else 'FAIL'}] {label}")
        all_steps_ok = all_steps_ok and ok
    print("  on-disk assets:")
    print(f"    [{'PRESENT' if mi_present else 'MISSING'}] material_mi   {material_mi}")
    print(f"    [{'PRESENT' if da_present else 'MISSING'}] data_asset    {data_asset}")
    pcg_status = "PRESENT" if pcg_present else ("MISSING" if pcg_resolvable or pcg_graph else "MISSING")
    print(f"    [{pcg_status}] pcg_graph     {pcg_graph}  (non-fatal)")

    # --- Actionable hints + exit decision ----------------------------------
    hints = []
    if not mi_present:
        hints.append(
            "  material_mi missing; run inside the editor:\n"
            f"    make prepare-material RECIPE={material_recipe or '<recipe>'}"
        )
    if not da_present:
        hints.append(
            "  data_asset missing; run inside the editor:\n"
            f"    make create-placement-data-asset DEF={placement_def or '<def>'}"
        )
    if not pcg_present:
        # pcg_graph is human-owned and missing is non-fatal: warn only.
        print(f"\nWARNING: pcg_graph not found on disk ({pcg_graph}); "
              "this is human-owned and non-fatal, but the map build needs it eventually.")

    ok = all_steps_ok and mi_present and da_present

    print()
    if ok:
        print("RESULT: OK -- authoring steps passed and required assets present.")
    else:
        print("RESULT: FAIL -- see hints below.")
        if not all_steps_ok:
            print("  one or more authoring steps failed (see logs above).")
        for h in hints:
            print(h)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
