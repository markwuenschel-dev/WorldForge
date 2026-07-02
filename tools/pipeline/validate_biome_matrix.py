#!/usr/bin/env python3
"""validate_biome_matrix.py — WorldForge v1.1 BiomeForge compatibility-matrix gate.

Proves the cross-axis compatibility contract is complete and self-consistent:

  * the compatibility_matrix.yaml parses and every forbidden-combination entry is
    well-formed (two axis:value bindings + a reason);
  * for EVERY declared biome × EVERY compatibility axis in ``biomes.AXES`` the
    biome declares a non-empty allow-list (a missing/empty allow-list means that
    axis is undefined for the biome — a BIOME_MATRIX_FAILURE);
  * no biome is FORCED into a globally-forbidden combination — i.e. a biome must
    never pin both axes of a forbidden pair to exactly the forbidden values as
    their only option (that would make every generated map illegal by
    construction). Individually allowing both values is fine; the per-map
    ``combination_allowed`` rule catches co-occurrence at bind time.

One check per (biome, axis), one per forbidden rule, one per (biome, forbidden
rule). record_count == number of declared biome families.

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

CODE = FailureCode.BIOME_MATRIX_FAILURE


def _pair_binding(side):
    """Return (axis, value) for one side of a forbidden pair, or (None, None)."""
    if not isinstance(side, dict):
        return None, None
    return side.get("axis"), side.get("value")


def validate_pack(pack, strict, biomes_root=None):
    """Importable core. Returns a ValidationReport (call .finalize()/.write())."""
    world_pack_id, families = load_world_pack(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    # ---- matrix parses -------------------------------------------------------
    try:
        matrix = B.load_compat_matrix(biomes_root)
    except B.BiomeError as exc:
        rep.check("compat_matrix_loads", False, str(exc), code=CODE)
        rep.set_meta(build_meta(command="validate-biome-matrix", pack=world_pack_id,
                                strict=strict, status=None, record_count=len(families)))
        return rep

    forbidden = B.forbidden_combinations(matrix)
    rep.check("compat_matrix_loads", True,
              "matrix parsed; {} forbidden pair(s)".format(len(forbidden)))

    # ---- forbidden pairs are well-formed -------------------------------------
    for i, entry in enumerate(forbidden):
        a_axis, a_val = _pair_binding(entry.get("a"))
        b_axis, b_val = _pair_binding(entry.get("b"))
        well_formed = bool(a_axis) and a_val is not None and bool(b_axis) and b_val is not None
        axes_known = a_axis in B.AXES and b_axis in B.AXES
        has_reason = bool(entry.get("reason"))
        ok = well_formed and axes_known and has_reason
        detail = ("well-formed: {}={} + {}={}".format(a_axis, a_val, b_axis, b_val)
                  if ok else
                  "malformed forbidden pair #{}: axes/values/reason incomplete or "
                  "unknown axis (a={}:{}, b={}:{}, reason={})".format(
                      i, a_axis, a_val, b_axis, b_val, has_reason))
        rep.check("forbidden_pair_well_formed::{}".format(i), ok, detail, code=CODE)

    if not families:
        rep.check("pack_declares_biome_families", False,
                  "world pack '{}' declares no biome_families".format(world_pack_id),
                  code=CODE)

    # ---- per biome × axis allow-list completeness + forced-combo safety ------
    for bid in families:
        try:
            biome = B.load_biome(bid, biomes_root)
        except B.BiomeError as exc:
            rep.check("biome_loads::{}".format(bid), False, str(exc), code=CODE)
            continue

        for axis in B.AXES:
            vals = B.allowed_values(biome, axis)
            rep.check(
                "matrix::{}::{}".format(bid, axis),
                bool(vals),
                "biome '{}' declares no allow-list for axis '{}'".format(bid, axis)
                if not vals else
                "axis '{}' allows {} value(s)".format(axis, len(vals)),
                code=CODE,
            )

        # A biome must not be FORCED into a globally-forbidden combination.
        for i, entry in enumerate(forbidden):
            a_axis, a_val = _pair_binding(entry.get("a"))
            b_axis, b_val = _pair_binding(entry.get("b"))
            if a_axis not in B.AXES or b_axis not in B.AXES:
                continue
            a_vals = B.allowed_values(biome, a_axis)
            b_vals = B.allowed_values(biome, b_axis)
            forced = (a_vals == [a_val]) and (b_vals == [b_val])
            rep.check(
                "forbidden_not_forced::{}::{}".format(bid, i),
                not forced,
                "biome '{}' is forced into forbidden combo {}={} + {}={} "
                "(both axes pinned to the forbidden value)".format(
                    bid, a_axis, a_val, b_axis, b_val)
                if forced else
                "biome '{}' retains a legal escape from forbidden pair #{}".format(bid, i),
                code=CODE,
            )

    rep.set_meta(build_meta(
        command="validate-biome-matrix", pack=world_pack_id, strict=strict,
        status=None, record_count=len(families),
        input_spec_hash=hash_obj({"families": sorted(families),
                                  "forbidden": len(forbidden)}),
    ))
    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate the biome compatibility matrix for a world pack.")
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
    rep.write(report_dir_for(rep.entity_id), "validate_biome_matrix_report.json")
    rep.print_summary("validate-biome-matrix")
    print("[validate-biome-matrix] records={} (biome families in pack)".format(len(families)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
