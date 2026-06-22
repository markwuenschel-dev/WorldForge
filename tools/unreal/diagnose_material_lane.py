#!/usr/bin/env python3
r"""
diagnose_material_lane.py
Diagnostic helper for UE5.
"""

import argparse
import json
from pathlib import Path


def run_diagnostics(recipe_id: str, project_root: str = "."):
    root = Path(project_root).resolve()
    manifest_path = root / "procedural/manifests/materials" / f"{recipe_id}.json"

    if not manifest_path.exists():
        result = {"status": "failed", "recipe_id": recipe_id, "errors": [{"category": "manifest_mismatch", "message": str(manifest_path)}]}
    else:
        result = {"status": "ok", "recipe_id": recipe_id, "errors": [], "message": "Basic diagnostics passed (run full validate-assets for details)"}

    report_dir = root / "procedural/reports/materials" / recipe_id
    report_dir.mkdir(parents=True, exist_ok=True)
    with open(report_dir / "diagnostics_result.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    run_diagnostics(args.recipe, args.project_root)
