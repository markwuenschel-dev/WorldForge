#!/usr/bin/env python3
"""validate_biome_poi_compatibility.py — WorldForge v1.1 BiomeForge POI gate.

Proves that EVERY map in a world pack binds a POI class its biome family
actually permits. A biome_family declares an authoritative ``poi_compatibility``
allow-list; a map that requests a POI class outside that list is a
BIOME_POI_COMPATIBILITY_FAILURE — implicit compatibility is never granted.

For each enumerated map we read the map's biome and the POI class its slice-pack
row requests (``row['poi']``). When the generated spec exists we ALSO cross-check
any POI class the spec carries, so a spec that drifts from the row can't sneak an
illegal POI past the gate. A map whose slice pack is missing (no biome / no
slice) is an honest coverage-shortfall failure — we do not fake it green.

Follows the v1.0x shared build contract (mirrors validate_sky.py): iterate via
enumerate_maps, one ValidationReport per pack, one check per map, meta attached,
record_count == number of maps, canonical report path.

Importable core:
    validate_pack(pack, strict, biomes_root=None) -> ValidationReport
The negative harness injects a broken biomes tree through ``biomes_root``.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta, hash_obj
from world_pack_maps import enumerate_maps, report_dir_for

import biomes as B

CODE = FailureCode.BIOME_POI_COMPATIBILITY_FAILURE

# Keys under a generated spec that may carry an explicit POI class, so a spec
# that drifts from its slice-pack row cannot smuggle an illegal POI past us.
_SPEC_POI_KEYS = ("poi", "poi_class")


def _spec_pois(spec):
    """Return POI class strings declared directly in a generated spec (defensive)."""
    out = []
    if not isinstance(spec, dict):
        return out
    for key in _SPEC_POI_KEYS:
        v = spec.get(key)
        if isinstance(v, str) and v.strip():
            out.append(v)
        elif isinstance(v, list):
            out.extend(x for x in v if isinstance(x, str) and x.strip())
    return out


def validate_pack(pack, strict, biomes_root=None):
    """Importable core. Returns a ValidationReport (call .finalize()/.write())."""
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    if not maps:
        rep.check("pack_has_maps", False, "world pack enumerated zero maps", code=CODE)

    hash_rows = []
    for i, m in enumerate(maps):
        tag = "biome_poi::{:02d}::{}".format(i, m.slice_id or m.get("pack_id") or "<unknown>")
        biome_id = m.get("biome")
        row_poi = m.get("row", {}).get("poi") if isinstance(m.get("row"), dict) else None

        # Coverage shortfall: a missing slice pack surfaces as a placeholder
        # record with no slice_id / no biome. Fail honestly, do not fake green.
        if not m.slice_id or not biome_id:
            rep.check(tag, False,
                      "coverage shortfall: {}".format(m.get("spec_error") or "no slice_id/biome"),
                      code=CODE)
            continue

        try:
            biome = B.load_biome(biome_id, biomes_root)
        except B.BiomeError as exc:
            rep.check(tag, False, "biome '{}' does not load: {}".format(biome_id, exc), code=CODE)
            continue

        pois = []
        if isinstance(row_poi, str) and row_poi.strip():
            pois.append(row_poi)
        if m.spec_exists:
            pois.extend(_spec_pois(m.spec))
        # de-dup, preserve order
        seen = set()
        pois = [p for p in pois if not (p in seen or seen.add(p))]

        if not pois:
            rep.check(tag, False,
                      "map declares no POI class (row.poi missing and no spec POI)",
                      code=CODE)
            continue

        allowed = B.allowed_values(biome, "poi_class")
        bad = [p for p in pois if not B.compatible(biome, "poi_class", p)]
        hash_rows.append((m.slice_id, tuple(sorted(pois))))
        rep.check(
            tag, not bad,
            "biome '{}' rejects POI class(es) {} (allowed: {})".format(biome_id, bad, allowed)
            if bad else "POI {} permitted by biome '{}'".format(pois, biome_id),
            code=CODE,
        )

    rep.set_meta(build_meta(
        command="validate-biome-poi-compatibility", pack=world_pack_id, strict=strict,
        status=None, record_count=len(maps),
        input_spec_hash=hash_obj(sorted(hash_rows)),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate biome POI compatibility for a world pack.")
    parser.add_argument("--pack", default="biome_expansion_world")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--biomes-root", default=None)
    args = parser.parse_args(argv)

    strict = args.strict or strict_from_env()
    rep = validate_pack(args.pack, strict, args.biomes_root)
    report_dir = report_dir_for(rep.entity_id)
    rep.finalize()
    rep.write(report_dir, "validate_biome_poi_compatibility_report.json")
    rep.print_summary("validate-biome-poi-compatibility")
    _, maps = enumerate_maps(args.pack)
    print("[validate-biome-poi-compatibility] records={} (maps in pack)".format(len(maps)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
