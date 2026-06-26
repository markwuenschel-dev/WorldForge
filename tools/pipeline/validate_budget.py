#!/usr/bin/env python3
"""validate_budget.py

Validate a WorldForge budget YAML definition.

Usage:
    python tools/pipeline/validate_budget.py --budget procedural/definitions/budgets/desert_default.yaml

Exit code:
    0  PASS
    1  FAIL
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

REQUIRED_TOP = {"budget_id", "biome", "limits"}
REQUIRED_LIMITS = {"max_total_instances"}


def fail(msg):
    print("FAIL:", msg)
    sys.exit(1)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate a WorldForge budget YAML.")
    ap.add_argument("--budget", required=True, help="Path to budget YAML")
    args = ap.parse_args(argv)

    budget_path = Path(args.budget)
    if not budget_path.is_absolute():
        budget_path = REPO_ROOT / budget_path

    if not budget_path.is_file():
        fail("budget file not found: {}".format(budget_path))

    try:
        with budget_path.open("r", encoding="utf-8") as f:
            budget = yaml.safe_load(f)
    except Exception as exc:
        fail("could not parse budget YAML: {}".format(exc))

    if not isinstance(budget, dict):
        fail("budget YAML must be a mapping")

    missing_top = REQUIRED_TOP - set(budget.keys())
    if missing_top:
        fail("missing required fields: {}".format(", ".join(sorted(missing_top))))

    limits = budget["limits"]
    if not isinstance(limits, dict):
        fail("'limits' must be a mapping")

    missing_limits = REQUIRED_LIMITS - set(limits.keys())
    if missing_limits:
        fail("limits missing required fields: {}".format(", ".join(sorted(missing_limits))))

    if not isinstance(limits["max_total_instances"], (int, float)) or limits["max_total_instances"] <= 0:
        fail("limits.max_total_instances must be a positive number")

    per_cat = limits.get("per_category", {})
    if per_cat:
        if not isinstance(per_cat, dict):
            fail("limits.per_category must be a mapping")
        for cat, limit in per_cat.items():
            if not isinstance(limit, (int, float)) or limit <= 0:
                fail("limits.per_category.{} must be a positive number (got {!r})".format(cat, limit))

    budget_id = budget.get("budget_id", "<unknown>")
    biome = budget.get("biome", "<unknown>")
    print("PASS: budget '{}' (biome={}) — max_total={}, categories={}".format(
        budget_id, biome, limits["max_total_instances"], len(per_cat)
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
