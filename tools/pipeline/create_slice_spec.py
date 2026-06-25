#!/usr/bin/env python3
"""create_slice_spec.py

Turn a named preset request (biome + variant + name) into a concrete,
fully-resolved slice spec JSON, so a new named UE slice can be built without
hand-wiring.

This is a plain-python generator (PyYAML only); it is NOT a UE script.

Usage:
    python tools/pipeline/create_slice_spec.py \
        --biome desert --variant sandy --name Desert_Test_Sandy_01 \
        [--seed N] [--region <id>]

Reads the variant template:
    procedural/slices/<biome>_<variant>.yaml
Emits:
    procedural/slices/<biome>/generated/<NAME>.json
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "ERROR: PyYAML is required (pip install pyyaml).\n"
    )
    sys.exit(2)


# Repo root = two levels up from this file (tools/pipeline/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SEED = 12345
PCG_GRAPH = "/Game/Procedural/PCG/PCG_FoliageScatter"
GENERATOR_NAME = "create_slice_spec"
GENERATOR_VERSION = "1.0.0"


def fail(msg: str) -> "NoReturn":
    sys.stderr.write(f"ERROR: {msg}\n")
    sys.exit(1)


def require_nonempty_list(value, field: str, template_path: Path):
    if not isinstance(value, list) or len(value) == 0:
        fail(
            f"template {template_path} field '{field}' must be a non-empty "
            f"list (got: {value!r})"
        )
    return value


def get_required(d: dict, key: str, template_path: Path):
    if not isinstance(d, dict) or key not in d:
        fail(f"template {template_path} is missing required field '{key}'")
    return d[key]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a fully-resolved slice spec JSON from a variant "
        "template."
    )
    parser.add_argument("--biome", required=True, help="biome, e.g. desert")
    parser.add_argument(
        "--variant", required=True, help="variant, e.g. sandy / ash / heavy_industrial"
    )
    parser.add_argument(
        "--name", required=True, help="slice name, e.g. Desert_Test_Sandy_01"
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="override seed (default: template seed or 12345)"
    )
    parser.add_argument(
        "--region", default=None, help="region/context id (default: NAME)"
    )
    args = parser.parse_args(argv)

    biome = args.biome
    variant = args.variant
    name = args.name

    template_rel = f"procedural/slices/{biome}_{variant}.yaml"
    template_path = REPO_ROOT / template_rel
    if not template_path.is_file():
        fail(
            f"template not found: {template_path} "
            f"(expected procedural/slices/<biome>_<variant>.yaml)"
        )

    with template_path.open("r", encoding="utf-8") as fh:
        template = yaml.safe_load(fh)

    if not isinstance(template, dict):
        fail(f"template {template_path} did not parse to a mapping")

    # --- Resolve required template fields ---
    recipes = require_nonempty_list(
        template.get("recipes"), "recipes", template_path
    )
    placement_definitions = require_nonempty_list(
        template.get("placement_definitions"),
        "placement_definitions",
        template_path,
    )

    state = get_required(template, "state", template_path)
    render = get_required(template, "render", template_path)

    # region_id and context_id must be identical (runtime state address ContextId).
    region_id = args.region if args.region is not None else name
    context_id = region_id

    # seed: CLI override -> template render.seed -> default.
    if args.seed is not None:
        seed = args.seed
    else:
        seed = render.get("seed", DEFAULT_SEED)

    # preview_base_color stays LINEAR (do NOT convert to 0-255).
    preview_base_color = get_required(
        render, "preview_base_color", template_path
    )

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    spec = {
        "slice_id": name,
        "biome": biome,
        "variant": variant,
        "region_id": region_id,
        "seed": seed,
        "map": f"/Game/WorldForge/Maps/{name}",
        "terrain": {
            "material_recipe": recipes[0],
            "material_mi": get_required(render, "terrain_mi", template_path),
            "preview_base_color": preview_base_color,
        },
        "state": {
            "scope": get_required(state, "scope", template_path),
            "context_id": context_id,
            "key": get_required(state, "key", template_path),
            "before": get_required(state, "before", template_path),
            "after": get_required(state, "after", template_path),
        },
        "placement": {
            "definition": placement_definitions[0],
            "data_asset": get_required(
                render, "placement_data_asset", template_path
            ),
            "pcg_graph": PCG_GRAPH,
        },
        "output_dir": f"procedural/reports/slices/{biome}/{name}",
        "source_template": template_rel,
        "provenance": {
            "generated_at_utc": now_iso,
            "generator": GENERATOR_NAME,
            "generator_version": GENERATOR_VERSION,
        },
    }

    out_dir = REPO_ROOT / "procedural" / "slices" / biome / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.json"

    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    rel_out = out_path.relative_to(REPO_ROOT).as_posix()
    print(rel_out)
    print(
        f"Wrote slice spec '{name}' (biome={biome} variant={variant} "
        f"seed={seed} region_id={region_id})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
