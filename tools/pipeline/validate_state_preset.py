#!/usr/bin/env python3
"""validate_state_preset.py

Validate a state preset YAML file.

Usage:
    python tools/pipeline/validate_state_preset.py --preset procedural/definitions/state/desert/industrialized.yaml

Exit 0: PASS
Exit 1: FAIL
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
    parser = argparse.ArgumentParser(description="Validate a state preset YAML.")
    parser.add_argument("--preset", required=True, help="path to state preset YAML")
    args = parser.parse_args(argv)

    preset_path = Path(args.preset)
    if not preset_path.is_absolute():
        preset_path = REPO_ROOT / preset_path

    errors = []

    if not preset_path.is_file():
        print(f"FAIL: file not found: {preset_path}")
        return 1

    try:
        with preset_path.open("r", encoding="utf-8") as fh:
            preset = yaml.safe_load(fh)
    except Exception as exc:
        print(f"FAIL: could not parse YAML: {exc}")
        return 1

    if not isinstance(preset, dict):
        print("FAIL: top-level must be a mapping")
        return 1

    for field in ("state_preset_id", "biome", "values"):
        if field not in preset:
            errors.append(f"missing required field: {field!r}")

    values = preset.get("values", {})
    if not isinstance(values, dict) or not values:
        errors.append("'values' must be a non-empty mapping")
    else:
        for key, entry in values.items():
            if not isinstance(entry, dict):
                errors.append(f"values.{key} must be a mapping")
                continue
            for subfield in ("before", "after"):
                if subfield not in entry:
                    errors.append(f"values.{key} missing '{subfield}'")
                else:
                    v = entry[subfield]
                    if not isinstance(v, (int, float)) or not (0.0 <= float(v) <= 1.0):
                        errors.append(f"values.{key}.{subfield}={v!r} must be float in [0.0, 1.0]")
            before = entry.get("before")
            after = entry.get("after")
            if before is not None and after is not None:
                if float(after) < float(before):
                    errors.append(f"values.{key}: after ({after}) < before ({before})")

    preset_id = preset.get("state_preset_id", preset_path.stem)
    if errors:
        print(f"FAIL: {preset_id}")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"PASS: {preset_id} ({len(values)} state key(s) valid)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
