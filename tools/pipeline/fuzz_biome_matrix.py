#!/usr/bin/env python3
"""fuzz_biome_matrix.py — WorldForge v1.1 BiomeForge combinatorial fuzz gate (Agent 7).

The BiomeForge sibling of ``fuzz_world_pack.py``. Where the v1.0x fuzzer throws
fuzzed *environment/overlay* configurations at the validator cores, this fuzzer
throws fuzzed *biome-axis binding combinations* at the frozen biome compatibility
contract (``biomes.py``: the per-biome allow-lists + the cross-axis
``compatibility_matrix.yaml``) and proves the matrix rules have TEETH:

  * every deliberately-VALID combination (all axis values drawn from the biome's
    own allow-lists and surviving ``combination_allowed``) is ACCEPTED;
  * every deliberately-INVALID combination (a cross-biome material, a matrix
    forbidden pair like ``performance_baked + full`` ray tracing, a POI outside
    the biome, or an unknown token) is cleanly REJECTED;
  * nothing crashes.

The synthesized combination spans the ten biome axes the brief enumerates:
biome_family × terrain_form × material_family × vegetation_profile ×
placement_profile × environment_profile × rendering_profile ×
raytracing_profile × POI class × entity anchor type.

A case that SHOULD be rejected but is ACCEPTED is a fake-green hole — the matrix
lets an illegal world through — and is tagged ``FailureCode.BIOME_FUZZ_FAILURE``.
An over-strict rejection of a genuinely-valid combination, and any uncaught crash,
are also ``BIOME_FUZZ_FAILURE``. Fuzzing is a pure function of the case index
(``random.Random(base_seed + i)`` — never time / os entropy), so the run is fully
reproducible.

Report: ``fuzz_biome_matrix_report.json`` with ``record_count == cases`` and a
``build_meta`` block, under
``procedural/reports/world_packs/<world_pack_id>/``.

Usage:
    PYTHONUTF8=1 python tools/pipeline/fuzz_biome_matrix.py \
        --pack biome_expansion_world --cases 200 --strict
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

import random  # noqa: E402

from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta  # noqa: E402
from world_pack_maps import report_dir_for, resolve_world_pack_path  # noqa: E402
from biomes import (  # noqa: E402
    BiomeError, list_biomes, load_biome, allowed_values, compatible,
    load_compat_matrix, combination_allowed,
)

BFUZZ = FailureCode.BIOME_FUZZ_FAILURE

# The nine non-biome axes the fuzzer binds per case (biome is chosen separately).
# Keys are biomes.AXES names, so compatible() and combination_allowed() apply
# directly. Ordered so the console/detail reads terrain -> ecology.
FUZZ_AXES = (
    "terrain_form",
    "material_family",
    "vegetation_profile",
    "placement_profile",
    "environment_profile",
    "rendering_profile",
    "raytracing_profile",
    "poi_class",
    "entity_anchor_type",
)

# The deliberately-invalid case kinds, rotated by case index so every kind gets
# even coverage regardless of --cases. "valid" is the accepted baseline.
CASE_KINDS = (
    "valid",
    "cross_biome_material",   # snow material in a volcanic biome, etc.
    "forbidden_pair",         # performance_baked + full ray tracing
    "poi_not_in_biome",       # industrial_yard in a forest, etc.
    "unknown_value",          # a synthetic token no biome allows
)

BASE_SEED = 90210  # fixed; per-case rng = Random(BASE_SEED + i)


# =============================================================================
# rules oracle — the code under test
# =============================================================================
def rules_accept(biome, bindings, matrix):
    """Return (accepted, reason) for a biome + axis-binding combination.

    A combination is ACCEPTED iff every axis value is in the biome's declared
    allow-list AND the bindings survive the cross-axis forbidden-pair matrix.
    This is the single source of truth the fuzzer's expectations are checked
    against; the negative-test harness injects a holed variant of this function
    to prove the fuzzer catches a fake-green acceptance.
    """
    for axis, value in bindings.items():
        if not compatible(biome, axis, value):
            return False, "{}={!r} not in biome allow-list".format(axis, value)
    reasons = combination_allowed(bindings, matrix)
    if reasons:
        return False, reasons[0]
    return True, "all axes allowed; no forbidden pair"


# =============================================================================
# combination synthesis (deterministic, per case index)
# =============================================================================
def _valid_binding(biome, rng):
    """Build an all-in-allow-list binding that is guaranteed matrix-legal.

    Ray tracing is pinned to ``off`` so none of the forbidden pairs (all of which
    require ``raytracing_profile == full`` or a cinematic tier we don't bind) can
    fire — the baseline is provably accepted.
    """
    b = {}
    for axis in FUZZ_AXES:
        vals = allowed_values(biome, axis)
        b[axis] = rng.choice(vals) if vals else None
    rt = allowed_values(biome, "raytracing_profile")
    if "off" in rt:
        b["raytracing_profile"] = "off"
    elif rt:
        b["raytracing_profile"] = rt[0]
    return b


def _invalid_from_pool(this_values, pool, fallback):
    """Return a value that is in ``pool`` but NOT in ``this_values`` (guaranteed
    invalid for this biome), or ``fallback`` if the pool offers no such value."""
    candidates = sorted(v for v in pool if v not in this_values)
    return candidates[0] if candidates else fallback


def synth_case(biome_id, biome, kind, rng, matrix, material_pool, poi_pool):
    """Synthesize one (bindings, expected_accept, note) tuple.

    ``expected_accept`` is derived from CONSTRUCTION INTENT (not from the code
    under test): "valid" -> True; every invalid kind injects a value/pair that is
    genuinely illegal for this biome -> False. The case runner then compares this
    intent against ``rules_accept``; a divergence is the fake-green signal.
    """
    b = _valid_binding(biome, rng)

    if kind == "valid":
        return b, True, "baseline valid combination"

    if kind == "cross_biome_material":
        this = set(allowed_values(biome, "material_family"))
        bad = _invalid_from_pool(this, material_pool, "__fuzz_no_such_material__")
        b["material_family"] = bad
        return b, False, "cross-biome material {!r} in {}".format(bad, biome_id)

    if kind == "forbidden_pair":
        rends = allowed_values(biome, "rendering_profile")
        rts = allowed_values(biome, "raytracing_profile")
        if "performance_baked" in rends and "full" in rts:
            # Both values are valid MEMBERSHIPS, so the ONLY reason to reject is
            # the matrix forbidden pair — this specifically exercises
            # combination_allowed(), not the allow-lists.
            b["rendering_profile"] = "performance_baked"
            b["raytracing_profile"] = "full"
            return b, False, "matrix forbidden pair performance_baked + full RT"
        # Fallback if this biome can't express the pair: corrupt a token instead.
        b["rendering_profile"] = "__fuzz_no_such_rendering__"
        return b, False, "unknown rendering token (forbidden-pair fallback)"

    if kind == "poi_not_in_biome":
        this = set(allowed_values(biome, "poi_class"))
        bad = _invalid_from_pool(this, poi_pool, "__fuzz_no_such_poi__")
        b["poi_class"] = bad
        return b, False, "POI {!r} not in {} allow-list".format(bad, biome_id)

    # kind == "unknown_value": garbage on a rotating axis.
    axis = rng.choice(FUZZ_AXES)
    b[axis] = "__fuzz_unknown_{}__".format(axis)
    return b, False, "unknown token on axis {}".format(axis)


# =============================================================================
# case runner
# =============================================================================
def run_cases(rep, biomes, matrix, material_pool, poi_pool, cases, accept_fn):
    """Run ``cases`` synthesized combinations; record one check each.

    Returns a tally dict {valid, cleanly_rejected, crashes, mismatches}.
    ``accept_fn`` is injectable so the negative-test harness can prove the
    detector catches a holed oracle.
    """
    tally = {"valid": 0, "cleanly_rejected": 0, "crashes": 0, "mismatches": 0}
    biome_ids = sorted(biomes)
    for i in range(cases):
        rng = random.Random(BASE_SEED + i)
        biome_id = biome_ids[i % len(biome_ids)]
        kind = CASE_KINDS[i % len(CASE_KINDS)]
        name = "case[{}]::{}::{}".format(i, kind, biome_id)
        try:
            biome = biomes[biome_id]
            bindings, expected_accept, note = synth_case(
                biome_id, biome, kind, rng, matrix, material_pool, poi_pool)
            accepted, reason = accept_fn(biome, bindings, matrix)
            ok = (accepted == expected_accept)
            if ok:
                if expected_accept:
                    tally["valid"] += 1
                    detail = "VALID accepted: {} ({})".format(note, reason)
                else:
                    tally["cleanly_rejected"] += 1
                    detail = "INVALID rejected: {} ({})".format(note, reason)
            else:
                tally["mismatches"] += 1
                if expected_accept:
                    detail = ("OVER-STRICT: valid combo rejected: {} ({})"
                              .format(note, reason))
                else:
                    detail = ("FAKE-GREEN: invalid combo ACCEPTED "
                              "(matrix hole): {}".format(note))
            rep.check(name, ok, detail, code=BFUZZ)
        except Exception as exc:  # noqa: BLE001
            tally["crashes"] += 1
            rep.check(name, False, "FUZZ CRASH: {}".format(exc), code=BFUZZ)
    return tally


# =============================================================================
# pack resolution + validation
# =============================================================================
def _pack_biome_ids(pack):
    """Resolve (world_pack_id, [biome_id,...]) from the world pack yaml.

    Prefers the pack's declared ``biome_families``; falls back to every biome
    family on disk so the fuzzer still exercises the contract for a pack that
    omits the list. Independent of whether any slice specs exist yet.
    """
    wp_path = resolve_world_pack_path(pack)
    world_pack_id = pack
    declared = []
    if wp_path.is_file():
        data = yaml.safe_load(wp_path.read_text(encoding="utf-8")) or {}
        world_pack_id = data.get("world_pack_id", wp_path.stem)
        declared = list(data.get("biome_families", []) or [])
    if not declared:
        declared = list_biomes()
    return world_pack_id, declared


def validate_pack(pack, cases, strict, accept_fn=rules_accept):
    world_pack_id, biome_ids = _pack_biome_ids(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    # Load every declared biome + the matrix once. A biome that fails to load is
    # a real contract defect (owned by the contract lane) but must not silently
    # shrink the fuzz surface — surface it as a blocking check.
    matrix = load_compat_matrix()
    biomes = {}
    for bid in biome_ids:
        try:
            biomes[bid] = load_biome(bid)
        except BiomeError as exc:
            rep.check("biome_loads::{}".format(bid), False,
                      "biome family failed to load: {}".format(exc), code=BFUZZ)

    if not biomes:
        rep.error("no biome families available to fuzz for pack {}".format(world_pack_id))
        return rep, world_pack_id, {"valid": 0, "cleanly_rejected": 0,
                                    "crashes": 0, "mismatches": 0}

    # Cross-biome pools for the "wrong biome" injections.
    material_pool, poi_pool = set(), set()
    for b in biomes.values():
        material_pool.update(allowed_values(b, "material_family"))
        poi_pool.update(allowed_values(b, "poi_class"))

    tally = run_cases(rep, biomes, matrix, material_pool, poi_pool, cases, accept_fn)

    print("[fuzz] cases={} valid={} cleanly_rejected={} crashes={}".format(
        cases, tally["valid"], tally["cleanly_rejected"], tally["crashes"]))
    if tally["mismatches"]:
        print("[fuzz] MISMATCHES={} (matrix accepted an invalid combo or rejected "
              "a valid one)".format(tally["mismatches"]))

    rep.set_meta(build_meta(
        command="fuzz-biome-matrix", pack=world_pack_id, strict=strict,
        torture=True, status=None, record_count=cases,
        extra={"valid": tally["valid"], "cleanly_rejected": tally["cleanly_rejected"],
               "crashes": tally["crashes"], "mismatches": tally["mismatches"],
               "base_seed": BASE_SEED, "biomes": sorted(biomes)}))
    return rep, world_pack_id, tally


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge BiomeForge combinatorial fuzz gate — "
                    "valid accepted, invalid rejected, never crash.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--cases", type=int, default=25)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, world_pack_id, _tally = validate_pack(args.pack, max(1, args.cases), strict)
    rep.finalize()
    rep.write(report_dir_for(world_pack_id), "fuzz_biome_matrix_report.json")
    rep.print_summary("fuzz-biome-matrix")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
