#!/usr/bin/env python3
"""
render_with_sbsrender.py
Wrapper script to render Substance Designer graphs using sbsrender CLI.

Usage:
    python tools/substance/render_with_sbsrender.py --recipe terrain_rock_desert_01

It reads the YAML recipe, calls sbsrender with the parameters,
and outputs textures to:
    procedural/substance/exports/<recipe_id>/
"""

import argparse
import subprocess
import sys
import yaml
from pathlib import Path


def load_recipe(recipe_name: str) -> dict:
    recipes_dir = Path(__file__).parent.parent.parent / "procedural" / "substance" / "recipes"
    recipe_path = recipes_dir / f"{recipe_name}.yaml"

    if not recipe_path.exists():
        print(f"ERROR: Recipe not found: {recipe_path}")
        sys.exit(1)

    with open(recipe_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_sbsrender_command(recipe: dict, recipe_name: str, output_dir: Path) -> list:
    graph_name = recipe["graph"]
    parameters = recipe.get("parameters", {})

    graphs_dir = Path(__file__).parent.parent.parent / "procedural" / "substance" / "graphs"
    graph_path = graphs_dir / graph_name

    if not graph_path.exists():
        print(f"ERROR: Graph not found: {graph_path}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "sbsrender", "render",
        "--input", str(graph_path),
        "--output-path", str(output_dir),
        "--output-name", "{inputName}",
        "--output-format", "png",
    ]

    # Add parameters
    for param_name, value in parameters.items():
        cmd.extend(["--set-value", f"${param_name}={value}"])

    return cmd


def main():
    parser = argparse.ArgumentParser(description="Render Substance graph using sbsrender")
    parser.add_argument("--recipe", required=True, help="Recipe name without .yaml")
    args = parser.parse_args()

    recipe = load_recipe(args.recipe)
    recipe_name = args.recipe

    output_dir = Path(__file__).parent.parent.parent / "procedural" / "substance" / "exports" / recipe_name

    cmd = build_sbsrender_command(recipe, recipe_name, output_dir)

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("sbsrender failed:")
        print(result.stdout)
        print(result.stderr)
        sys.exit(result.returncode)

    print(f"Successfully rendered textures to: {output_dir}")


if __name__ == "__main__":
    main()