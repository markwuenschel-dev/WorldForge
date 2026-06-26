#!/usr/bin/env python3
"""validate_placement_preset.py

Validate a WorldForge placement preset YAML against its asset catalog.

Usage:
    python tools/pipeline/validate_placement_preset.py \
        --preset procedural/definitions/placement/desert/industrial_debris.yaml \
        [--catalog-dir procedural/definitions/assets/]

Exit 0 on PASS, 1 on FAIL.
"""

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_DIR = REPO_ROOT / "procedural" / "definitions" / "assets"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate a WorldForge placement preset YAML.")
    ap.add_argument("--preset", required=True, help="Path to placement preset YAML")
    ap.add_argument(
        "--catalog-dir",
        default=str(DEFAULT_CATALOG_DIR),
        help="Directory containing asset catalog YAMLs (default: procedural/definitions/assets/)",
    )
    args = ap.parse_args(argv)

    preset_path = Path(args.preset)
    if not preset_path.is_absolute():
        preset_path = REPO_ROOT / preset_path

    failures = []

    if not preset_path.is_file():
        print("ERROR: preset not found: {}".format(preset_path))
        return 1

    try:
        with preset_path.open("r", encoding="utf-8") as fh:
            preset = yaml.safe_load(fh)
    except Exception as exc:
        print("ERROR: failed to parse YAML: {}".format(exc))
        return 1

    if not isinstance(preset, dict):
        print("ERROR: preset did not parse to a mapping")
        return 1

    placement_id = preset.get("placement_id", "<missing>")
    print("PLACEMENT PRESET: {}".format(placement_id))

    checks = []

    # 1. Required fields
    for field in ("placement_id", "biome", "asset_catalog", "state_key", "categories"):
        ok = field in preset and bool(preset[field])
        checks.append(("field '{}' present".format(field), ok))
        if not ok:
            failures.append("missing required field: {}".format(field))

    if failures:
        for label, ok in checks:
            print("  [{}] {}".format("OK" if ok else "FAIL", label))
        print("RESULT: FAIL")
        for f in failures:
            print("  - {}".format(f))
        return 1

    catalog_id = preset["asset_catalog"]
    preset_categories = preset.get("categories", {})

    # 2. Catalog exists
    catalog_dir = Path(args.catalog_dir)
    if not catalog_dir.is_absolute():
        catalog_dir = REPO_ROOT / catalog_dir
    catalog_path = catalog_dir / (catalog_id + ".yaml")
    catalog_ok = catalog_path.is_file()
    checks.append(("catalog '{}' exists".format(catalog_id), catalog_ok))
    if not catalog_ok:
        failures.append("catalog not found: {}".format(catalog_path))

    catalog_categories = set()
    if catalog_ok:
        try:
            with catalog_path.open("r", encoding="utf-8") as fh:
                catalog = yaml.safe_load(fh)
            catalog_categories = set(catalog.get("categories", {}).keys())
        except Exception as exc:
            failures.append("could not read catalog: {}".format(exc))
            catalog_ok = False

    # 3. All preset categories exist in catalog
    if catalog_ok:
        unknown = [c for c in preset_categories if c not in catalog_categories]
        ok = not unknown
        checks.append(("all categories in catalog", ok))
        if not ok:
            failures.append("categories not in catalog: {}".format(unknown))

    # 4. All densities in [0.0, 1.0]
    bad_densities = []
    for cat, data in preset_categories.items():
        if not isinstance(data, dict):
            bad_densities.append("{}: not a mapping".format(cat))
            continue
        for key in ("density_at_0", "density_at_1"):
            val = data.get(key)
            if val is None:
                bad_densities.append("{}.{}: missing".format(cat, key))
            elif not (0.0 <= float(val) <= 1.0):
                bad_densities.append("{}.{}: {} out of [0,1]".format(cat, key, val))
    ok = not bad_densities
    checks.append(("all densities in [0.0, 1.0]", ok))
    if not ok:
        failures.extend(bad_densities)

    # 5. At least one category active (density > 0)
    any_active = any(
        float(data.get("density_at_0", 0)) > 0 or float(data.get("density_at_1", 0)) > 0
        for data in preset_categories.values()
        if isinstance(data, dict)
    )
    ok = any_active
    checks.append(("at least one category active", ok))
    if not ok:
        failures.append("no category has density > 0 at either state endpoint")

    for label, ok in checks:
        print("  [{}] {}".format("OK" if ok else "FAIL", label))

    if failures:
        print("RESULT: FAIL")
        for f in failures:
            print("  - {}".format(f))
        return 1

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
