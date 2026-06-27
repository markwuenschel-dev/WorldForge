#!/usr/bin/env python3
r"""
prepare_recipe_material.py (UE5 Python) -- WorldForge recipe material prep.

Reads a staged manifest from the fixed pointer file (no spaces in path, safe
for -ExecutePythonScript):
    procedural/reports/recipes/_active_manifest.json

Written by run_ue_recipe.py before launching this script.

Runs each pipeline step by calling the script's main() with the staged manifest
path, so we avoid re-implementing any logic:
  1. import_textures
  2. create_material_instances
  3. create_data_asset
  4. validate_assets

Writes: procedural/reports/recipes/<recipe_id>/prepare_recipe_report.json
"""

import json
import os
import sys
import traceback

import unreal

ROOT = os.path.normpath(unreal.Paths.project_dir())
STAGING = os.path.join(ROOT, "procedural", "reports", "recipes", "_active_manifest.json")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


def log(m):
    unreal.log("[prepare-recipe] {}".format(m))


def _call_main(module_name, staged_path):
    """Import module_name and call its main() with --manifest and --project-root args."""
    import importlib
    mod = importlib.import_module(module_name)
    saved = sys.argv[:]
    sys.argv = [module_name + ".py", "--manifest", staged_path, "--project-root", ROOT]
    try:
        mod.main()
        return True
    except SystemExit as e:
        return (e.code == 0 or e.code is None)
    except Exception as exc:
        log("{} raised: {}".format(module_name, exc))
        unreal.log_error(traceback.format_exc())
        return False
    finally:
        sys.argv = saved


def main():
    log("reading staged manifest: {}".format(STAGING))
    if not os.path.isfile(STAGING):
        raise SystemExit("[prepare-recipe] staged manifest not found: {}".format(STAGING))

    with open(STAGING, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    recipe_id = manifest.get("recipe_id", "unknown")
    log("recipe: {}".format(recipe_id))

    out_dir = os.path.join(ROOT, "procedural", "reports", "recipes", recipe_id)
    os.makedirs(out_dir, exist_ok=True)

    steps = [
        ("import_textures", "import_textures"),
        ("create_material_instances", "create_material_instances"),
        ("create_data_asset", "create_data_asset"),
        ("validate_assets", "validate_assets"),
    ]

    report = {"recipe_id": recipe_id, "steps": {}}
    for label, module in steps:
        log("--- {} ---".format(label))
        ok = _call_main(module, STAGING)
        report["steps"][label] = ok
        log("{}: {}".format(label, "OK" if ok else "FAIL"))

    all_ok = all(report["steps"].values())
    report["passed"] = all_ok
    report["status"] = "ok" if all_ok else "error"

    report_path = os.path.join(out_dir, "prepare_recipe_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    verdict = "PASS" if all_ok else "FAIL"
    log("prepare_recipe_material: {} -- report at {}".format(verdict, report_path))


if __name__ == "__main__":
    main()
