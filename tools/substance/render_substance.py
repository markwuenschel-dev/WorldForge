#!/usr/bin/env python3
"""
render_substance.py
Renders Substance Designer graphs using a recipe.

This is a well-documented stub. In production you would:
- Use the Substance Automation Toolkit (pysbs) for full Python control, or
- Call the Substance CLI (sbsrender / sbsmutator)

For now it validates the recipe and prints the exact command you should run
(or the pysbs code you would write).

Usage:
    python tools/substance/render_substance.py --recipe terrain_rock_desert_01
"""

import argparse
import yaml
from pathlib import Path
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--output-dir", default="procedural/substance/exports")
    args = parser.parse_args()
    
    recipes_dir = Path(__file__).parent.parent.parent / "procedural" / "substance" / "recipes"
    recipe_path = recipes_dir / f"{args.recipe}.yaml"
    
    if not recipe_path.exists():
        print(f"Recipe not found: {recipe_path}")
        sys.exit(1)
    
    with open(recipe_path) as f:
        recipe = yaml.safe_load(f)
    
    graph_name = recipe["graph"]
    resolution = recipe["resolution"]
    params = recipe["parameters"]
    
    print(f"Would render: {graph_name}")
    print(f"Resolution: {resolution}")
    print(f"Parameters: {params}")
    print(f"Output directory: {args.output_dir}")
    print("\n--- Recommended approaches ---")
    print("1. Using Substance CLI (recommended for CI/agents):")
    print(f"   sbsrender render --input graphs/{graph_name} "
          f"--set-value {' '.join([f'{k}={v}' for k,v in params.items()])} "
          f"--output-name {args.recipe} --output-format png "
          f"--output-path {args.output_dir} --resolution {resolution},{resolution}")
    
    print("\n2. Using pysbs (full Python control):")
    print("   See Adobe Substance Automation Toolkit documentation for pysbs usage.")
    print("   You can load the .sbs, modify exposed inputs from the recipe, and render outputs programmatically.")
    
    print("\nAfter rendering, copy the generated textures into your UE5 Content/Textures folder")
    print("with the exact names defined in the recipe 'outputs' section.")

if __name__ == "__main__":
    main()