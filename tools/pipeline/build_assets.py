#!/usr/bin/env python3
"""
build_assets.py
Main orchestrator for the procedural content pipeline.

This is the recommended entrypoint for both humans and agents.

Current capabilities (MVP):
- Validates a recipe
- (Future) Triggers Substance rendering
- Prints clear next steps for UE5-side execution

Usage:
    python tools/pipeline/build_assets.py --recipe terrain_rock_desert_01
    python tools/pipeline/build_assets.py --all
"""

import argparse
import subprocess
import sys
from pathlib import Path

def run_command(cmd: list[str], description: str):
    print(f"\n▶ {description}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    print(result.stdout)
    return result

def build_recipe(recipe_name: str):
    root = Path(__file__).parent.parent.parent
    validate_script = root / "tools" / "substance" / "validate_recipe.py"
    
    print(f"\n{'='*60}")
    print(f"Building asset pipeline for recipe: {recipe_name}")
    print(f"{'='*60}")
    
    # Step 1: Validate recipe
    run_command(
        [sys.executable, str(validate_script), "--recipe", recipe_name],
        "Validating recipe"
    )
    
    print("\n✅ Recipe validation passed.")
    print("\nNext manual / UE5 steps:")
    print("  1. Render textures from Substance (use render_substance.py or Designer)")
    print("  2. Inside UE5 Python: run create_material_instances.py --recipe", recipe_name)
    print("  3. Run validate_assets.py")
    print("  4. Generate previews")
    print("\nOr use the Makefile targets after setting up your environment.")

def main():
    parser = argparse.ArgumentParser(description="Procedural asset pipeline orchestrator")
    parser.add_argument("--recipe", help="Single recipe to build")
    parser.add_argument("--all", action="store_true", help="Build all recipes")
    args = parser.parse_args()
    
    if args.recipe:
        build_recipe(args.recipe)
    elif args.all:
        recipes_dir = Path(__file__).parent.parent.parent / "procedural" / "substance" / "recipes"
        for recipe_file in recipes_dir.glob("*.yaml"):
            build_recipe(recipe_file.stem)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()