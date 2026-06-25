#!/usr/bin/env python3
r"""
prepare_biome_slice.py -- authoring-side prep for one biome slice variant.

    make prepare-biome-slice BIOME=desert VARIANT=sandy

Reads procedural/slices/<BIOME>_<VARIANT>.yaml and, for every recipe in the
slice's `recipes:` list, runs the non-UE authoring steps:

    1. python tools/substance/validate_recipe.py --recipe <recipe>
    2. python tools/pipeline/generate_manifest.py --recipe <recipe>

This is the prep that biome_slice.py's run_authoring() does for recipes, pulled
out so it can be run on its own (no headless UE launch). It deliberately does
NOT run the UE-side import/create/validate steps -- those `import unreal` and
must run inside the editor's Python.

Runs in plain WSL Python; PyYAML is fine here (the no-YAML rule only applies to
scripts that `import unreal`). Exits non-zero on any failure.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SLICES_DIR = REPO / "procedural" / "slices"


def _run(cmd, label):
    """Run an authoring-side step, streaming output. Returns the return code."""
    print("\n[prepare-slice] $ {}".format(" ".join(str(c) for c in cmd)))
    proc = subprocess.run(cmd, cwd=str(REPO))
    if proc.returncode != 0:
        print("[prepare-slice] FAILED ({}) rc={}".format(label, proc.returncode))
    return proc.returncode


def prepare(biome, variant):
    slug = "{}_{}".format(biome, variant)
    cfg_path = SLICES_DIR / "{}.yaml".format(slug)
    if not cfg_path.is_file():
        print("[prepare-slice] no slice config: {}".format(cfg_path))
        return 2

    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    recipes = cfg.get("recipes", []) or []
    print("[prepare-slice] slice '{}' (biome={} variant={}) -- {} recipe(s)".format(
        slug, cfg.get("biome"), cfg.get("variant"), len(recipes)))

    if not recipes:
        print("[prepare-slice] WARNING: slice has no recipes; nothing to prepare.")

    py = sys.executable
    results = []  # (recipe, step, rc)
    failures = 0
    for recipe in recipes:
        rc = _run([py, "tools/substance/validate_recipe.py", "--recipe", recipe], "validate-recipe")
        results.append((recipe, "validate-recipe", rc))
        if rc != 0:
            failures += 1
            continue  # skip manifest if the recipe is invalid
        rc = _run([py, "tools/pipeline/generate_manifest.py", "--recipe", recipe], "generate-manifest")
        results.append((recipe, "generate-manifest", rc))
        if rc != 0:
            failures += 1

    print("\n[prepare-slice] ==== summary for {} ====".format(slug))
    for recipe, step, rc in results:
        print("[prepare-slice]   {:<8} {:<18} {}".format(
            "OK" if rc == 0 else "FAIL", step, recipe))
    if failures:
        print("[prepare-slice] {} step(s) FAILED".format(failures))
    else:
        print("[prepare-slice] authoring prep OK ({} recipe(s))".format(len(recipes)))
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser(description="Authoring-side prep for a biome slice variant.")
    ap.add_argument("--biome", required=True)
    ap.add_argument("--variant", required=True)
    args = ap.parse_args()
    raise SystemExit(prepare(args.biome, args.variant))


if __name__ == "__main__":
    main()
