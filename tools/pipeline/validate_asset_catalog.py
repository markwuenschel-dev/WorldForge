#!/usr/bin/env python3
"""validate_asset_catalog.py

Validate a WorldForge asset catalog YAML.

Usage:
    python tools/pipeline/validate_asset_catalog.py --catalog procedural/definitions/assets/desert_asset_catalog.yaml

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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate a WorldForge asset catalog YAML.")
    ap.add_argument("--catalog", required=True, help="Path to catalog YAML")
    args = ap.parse_args(argv)

    catalog_path = Path(args.catalog)
    if not catalog_path.is_absolute():
        catalog_path = REPO_ROOT / catalog_path

    failures = []

    if not catalog_path.is_file():
        print("ERROR: catalog not found: {}".format(catalog_path))
        return 1

    try:
        with catalog_path.open("r", encoding="utf-8") as fh:
            catalog = yaml.safe_load(fh)
    except Exception as exc:
        print("ERROR: failed to parse YAML: {}".format(exc))
        return 1

    if not isinstance(catalog, dict):
        print("ERROR: catalog did not parse to a mapping")
        return 1

    catalog_id = catalog.get("catalog_id", "<missing>")
    biome = catalog.get("biome")
    categories = catalog.get("categories", {})

    print("CATALOG: {}".format(catalog_id))

    total_assets = sum(
        len(v.get("assets", [])) for v in categories.values() if isinstance(v, dict)
    )
    print("  categories: {}".format(len(categories)))
    print("  total assets: {}".format(total_assets))

    checks = []

    # 1. catalog_id present
    ok = bool(catalog.get("catalog_id"))
    checks.append(("catalog_id present", ok))
    if not ok:
        failures.append("missing catalog_id")

    # 2. biome present
    ok = bool(biome)
    checks.append(("biome present", ok))
    if not ok:
        failures.append("missing biome")

    # 3. categories non-empty
    empty_cats = [k for k, v in categories.items() if isinstance(v, dict) and not v.get("assets")]
    ok = not empty_cats
    checks.append(("all categories non-empty", ok))
    if not ok:
        failures.append("empty categories: {}".format(empty_cats))

    # 4. no duplicate assets across categories
    seen = {}
    for cat_name, cat_data in categories.items():
        if not isinstance(cat_data, dict):
            continue
        for asset in cat_data.get("assets", []):
            if asset in seen:
                failures.append("duplicate asset {} in {} and {}".format(asset, seen[asset], cat_name))
            seen[asset] = cat_name
    ok = not any("duplicate asset" in f for f in failures)
    checks.append(("no duplicate assets", ok))

    # 5. all paths /Game/ prefixed
    bad_paths = [a for a in seen if not a.startswith("/Game/")]
    ok = not bad_paths
    checks.append(("all paths /Game/ prefixed", ok))
    if not ok:
        failures.append("bad asset paths: {}".format(bad_paths))

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
