#!/usr/bin/env python3
"""validate_biome_contract.py — WorldForge v1.1 BiomeForge biome-contract gate.

Proves that EVERY biome family a world pack declares under ``biome_families:``
loads and satisfies the structural biome_family contract (biomes.py): id matches
the file stem, every required scalar / axis allow-list / rule block is present and
correctly shaped, and no unknown top-level fields have crept in. This is the data
substrate every downstream BiomeForge lane depends on, so a structural violation
here is a hard, blocking BIOME_CONTRACT_FAILURE.

Follows the v1.0x shared build contract: one ValidationReport per pack, one check
per biome family, meta attached, canonical report path, record_count == number of
declared biome families.

Core is importable:
    validate_pack(pack, strict, biomes_root=None) -> ValidationReport
The negative harness injects a broken biome tree through ``biomes_root``.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: PyYAML required (pip install pyyaml).\n")
    raise

from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta, hash_obj
from world_pack_maps import resolve_world_pack_path, report_dir_for

import biomes as B


def load_world_pack(pack):
    """Return (world_pack_id, [declared biome_family ids]) for a world pack yaml."""
    path = resolve_world_pack_path(pack)
    if not path.is_file():
        raise FileNotFoundError("world pack not found: {}".format(path))
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    world_pack_id = data.get("world_pack_id", path.stem)
    families = list(data.get("biome_families", []) or [])
    return world_pack_id, families


def validate_pack(pack, strict, biomes_root=None):
    """Importable core. Returns a ValidationReport (call .finalize()/.write())."""
    world_pack_id, families = load_world_pack(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    if not families:
        rep.check("pack_declares_biome_families", False,
                  "world pack '{}' declares no biome_families".format(world_pack_id),
                  code=FailureCode.BIOME_CONTRACT_FAILURE)

    for bid in families:
        tag = "biome_contract::{}".format(bid)
        try:
            biome = B.load_biome(bid, biomes_root)
        except B.BiomeError as exc:
            rep.check(tag, False, str(exc), code=FailureCode.BIOME_CONTRACT_FAILURE)
            continue

        problems = B.validate_biome_fields(bid, biome, biomes_root)
        if problems:
            detail = "{} contract problem(s): {}".format(
                len(problems), "; ".join("[{}] {}".format(c, d) for c, d in problems))
            rep.check(tag, False, detail, code=FailureCode.BIOME_CONTRACT_FAILURE)
        else:
            rep.check(tag, True, "biome '{}' satisfies the biome_family contract "
                      "({} required fields present)".format(bid, len(B.BIOME_REQUIRED_FIELDS)))

    rep.set_meta(build_meta(
        command="validate-biome-contract", pack=world_pack_id, strict=strict,
        status=None, record_count=len(families),
        input_spec_hash=hash_obj(sorted(families)),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate the biome_family contract for a world pack.")
    parser.add_argument("--pack", default="biome_expansion_world",
                        help="world pack id (default: biome_expansion_world)")
    parser.add_argument("--strict", action="store_true", help="hostile / strict mode")
    parser.add_argument("--biomes-root", default=None,
                        help="override biomes root (for fixtures/tests)")
    parser.add_argument("--bindings-path", default=None,
                        help="unused; accepted for CLI uniformity")
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.biomes_root)
    _, families = load_world_pack(args.pack)
    rep.finalize()
    rep.write(report_dir_for(rep.entity_id), "validate_biome_contract_report.json")
    rep.print_summary("validate-biome-contract")
    print("[validate-biome-contract] records={} (biome families in pack)".format(len(families)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
