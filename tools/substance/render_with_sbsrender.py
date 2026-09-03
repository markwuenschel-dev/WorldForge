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
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Mirrors tools/substance/make_placeholder_exports.py. Both producers write the
# SAME sidecar name into the SAME directory, and the only field that separates
# them is is_stopgap -- which is the entire point: the exports themselves are
# byte-indistinguishable, so the record has to carry the difference.
PRODUCER_NAME = "substance_sbsrender"
PRODUCER_VERSION = "1.0.0"
SIDECAR_NAME = "_synthesis.json"


def write_render_sidecar(output_dir, graph_path, cook_seconds, returncode):
    """Record that a REAL sbsrender process produced these files.

    Carries the process facts a stopgap cannot fabricate honestly: the graph
    digest that went in, the exit code, how long it ran, and a hash per output
    file as it landed on disk.
    """
    outputs = {}
    for png in sorted(output_dir.glob("*.png")):
        data = png.read_bytes()
        outputs[png.stem] = {
            "file": png.name,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    sidecar = {
        "schema_version": "1.0",
        "producer": PRODUCER_NAME,
        "producer_version": PRODUCER_VERSION,
        "mode": "sbsrender",
        "is_stopgap": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_digest": hashlib.sha256(graph_path.read_bytes()).hexdigest(),
        "input_path": graph_path.name,
        "process_exit_code": returncode,
        "cook_seconds": round(cook_seconds, 3),
        "outputs": outputs,
    }
    out = output_dir / SIDECAR_NAME
    out.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False) + chr(10),
                   encoding="utf-8")
    return out


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

    # A present-but-EMPTY graph is not something to render, it is something to
    # refuse. Rendering it would either fail deep inside sbsrender or, worse,
    # emit files that then wear a real render's provenance. See WF022 and
    # tools/pipeline/validate_generative_sources.py.
    if graph_path.stat().st_size == 0:
        print(f"ERROR: Graph is empty (0 bytes): {graph_path}")
        print("       Its digest is the digest of nothing. Author the .sbs "
              "before rendering from it.")
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
    started = time.monotonic()
    result = subprocess.run(cmd, capture_output=True, text=True)
    cook_seconds = time.monotonic() - started

    if result.returncode != 0:
        print("sbsrender failed:")
        print(result.stdout)
        print(result.stderr)
        sys.exit(result.returncode)

    graph_path = (Path(__file__).parent.parent.parent / "procedural" /
                  "substance" / "graphs" / recipe["graph"])
    sidecar = write_render_sidecar(output_dir, graph_path, cook_seconds,
                                   result.returncode)
    print(f"Successfully rendered textures to: {output_dir}")
    print(f"producer recorded -> {sidecar}")


if __name__ == "__main__":
    main()