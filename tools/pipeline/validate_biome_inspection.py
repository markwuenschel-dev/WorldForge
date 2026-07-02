#!/usr/bin/env python3
"""validate_biome_inspection.py — WorldForge v1.1 BiomeForge inspection-completeness gate.

A lightweight completeness gate for the inspection-facing surface of every biome
family the world pack declares: each biome must carry a non-empty id / display_name
/ description, every compatibility-axis allow-list must be a non-empty list, and
every rule block must be a non-empty mapping. This overlaps validate_biome_contract
(which checks full structural shape); here we assert only that the biome is
*inspectable* — nothing an operator or the inspection metadata generator would read
is blank. One check per biome family. record_count == number of biome families.

Core is importable:
    validate_pack(pack, strict, biomes_root=None) -> ValidationReport
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta, hash_obj
from world_pack_maps import report_dir_for

import biomes as B
from validate_biome_contract import load_world_pack

CODE = FailureCode.BIOME_CONTRACT_FAILURE


def _inspection_gaps(bid, biome):
    """Return a list of human-readable completeness gaps (empty == complete)."""
    gaps = []
    for f in B.BIOME_SCALAR_FIELDS:
        v = biome.get(f)
        if not isinstance(v, str) or not v.strip():
            gaps.append("scalar '{}' blank/absent".format(f))
    for f in B.BIOME_LIST_FIELDS:
        v = biome.get(f)
        if not isinstance(v, list) or not v:
            gaps.append("axis list '{}' empty/absent".format(f))
    for f in B.BIOME_RULE_FIELDS:
        v = biome.get(f)
        if not isinstance(v, dict) or not v:
            gaps.append("rule block '{}' empty/absent".format(f))
    return gaps


def validate_pack(pack, strict, biomes_root=None):
    """Importable core. Returns a ValidationReport (call .finalize()/.write())."""
    world_pack_id, families = load_world_pack(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    if not families:
        rep.check("pack_declares_biome_families", False,
                  "world pack '{}' declares no biome_families".format(world_pack_id),
                  code=CODE)

    for bid in families:
        tag = "biome_inspection::{}".format(bid)
        try:
            biome = B.load_biome(bid, biomes_root)
        except B.BiomeError as exc:
            rep.check(tag, False, str(exc), code=CODE)
            continue
        gaps = _inspection_gaps(bid, biome)
        rep.check(
            tag, not gaps,
            "biome '{}' inspection metadata complete".format(bid) if not gaps else
            "biome '{}' has {} inspection gap(s): {}".format(bid, len(gaps), "; ".join(gaps)),
            code=CODE,
        )

    rep.set_meta(build_meta(
        command="validate-biome-inspection", pack=world_pack_id, strict=strict,
        status=None, record_count=len(families),
        input_spec_hash=hash_obj(sorted(families)),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate biome inspection-metadata completeness for a world pack.")
    parser.add_argument("--pack", default="biome_expansion_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--biomes-root", default=None,
                        help="override biomes root (for fixtures/tests)")
    parser.add_argument("--bindings-path", default=None,
                        help="unused; accepted for CLI uniformity")
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.biomes_root)
    _, families = load_world_pack(args.pack)
    rep.finalize()
    rep.write(report_dir_for(rep.entity_id), "validate_biome_inspection_report.json")
    rep.print_summary("validate-biome-inspection")
    print("[validate-biome-inspection] records={} (biome families in pack)".format(len(families)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
