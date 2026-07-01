#!/usr/bin/env python3
"""seed_matrix.py — WorldForge v1.0x seed-sweep gate (Agent 7).

Sweeps a matrix of seeds and proves that, for EVERY seed, the seed-varied
authoring artifacts a world pack would generate are (a) internally VALID (the
level-design + entity-anchor overlays pass their own validators) and (b)
DETERMINISTIC on repeat (identical content_hash when rebuilt).

Seeds are a pure function of the sweep index, so the matrix is reproducible.
Overlays are built IN-MEMORY with the seed overridden; nothing is written to the
real tree, so the working tree is untouched.

Seed tiers (by --seeds N):
    smoke <=5 | standard <=25 | regression <=50 | torture <=100

If a bound is applied to cap heavy work (e.g. maps-per-seed for the torture
tier) it is printed — never silently truncated.

Failure taxonomy:
    a seed producing INVALID output -> FailureCode.REGRESSION_FAILURE
    a seed that is NON-deterministic -> FailureCode.DETERMINISM_FAILURE

Report: ``seed_matrix_report.json`` with record_count == seeds run.

Usage:
    PYTHONUTF8=1 python tools/pipeline/seed_matrix.py --pack desert_mvp_world --seeds 25 --strict
"""

import argparse
import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta, hash_obj  # noqa: E402
from world_pack_maps import enumerate_maps, report_dir_for, MapRecord  # noqa: E402
import generate_level_design as LD  # noqa: E402
import generate_entity_anchors as EA  # noqa: E402
from validate_pois import check_overlay as pois_check  # noqa: E402
from validate_entity_anchors import check_map as ea_check  # noqa: E402

REG = FailureCode.REGRESSION_FAILURE
DET = FailureCode.DETERMINISM_FAILURE

TORTURE_MAP_CAP = 8  # maps-per-seed cap for the heavy torture tier (>50 seeds)


def _tier(n):
    if n <= 5:
        return "smoke"
    if n <= 25:
        return "standard"
    if n <= 50:
        return "regression"
    return "torture"


def _seed_for(i):
    """Deterministic, well-spread seed for sweep index i."""
    return (i * 2654435761 + 1013904223) % (2 ** 31)


def _build_overlays(map_record, world_pack_id, seed):
    """Build LD + EA overlays in memory with the seed overridden. Pure."""
    spec = copy.deepcopy(map_record.spec)
    spec["seed"] = seed
    mr = MapRecord(dict(map_record))
    mr["spec"] = spec
    ld = LD.build_overlay(mr, world_pack_id)
    ea = EA.build_overlay(mr, level_design=ld)
    return ld, ea


def _overlays_valid(sid, ld, ea, strict):
    """Run the real overlay validators against in-memory overlays. Return (ok, detail)."""
    tmp = ValidationReport("x", "x", strict=strict)
    pois_check(tmp, sid, ld)
    ea_check(tmp, sid, ea, strict)
    tmp.finalize()
    return tmp.passed, "; ".join(tmp.failures[:3])


def validate_pack(pack, seeds, strict):
    world_pack_id, maps = enumerate_maps(pack)
    present = [m for m in maps if m.spec_exists and m.slice_id]
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    if not present:
        rep.error("world pack enumerated zero overlay-eligible maps")
        return rep, world_pack_id, 0

    tier = _tier(seeds)
    maps_per_seed = len(present)
    capped = False
    if seeds > 50 and len(present) > TORTURE_MAP_CAP:
        maps_per_seed = TORTURE_MAP_CAP
        capped = True
    print("[seed-matrix] pack={} tier={} seeds={} maps={} maps_per_seed={}".format(
        world_pack_id, tier, seeds, len(present), maps_per_seed))
    if capped:
        print("[seed-matrix] CAP APPLIED: maps_per_seed={} of {} (tier={}); "
              "no silent truncation".format(maps_per_seed, len(present), tier))

    for i in range(seeds):
        seed = _seed_for(i)
        sample = present[:maps_per_seed]
        invalid, nondet = [], []
        for m in sample:
            try:
                ld, ea = _build_overlays(m, world_pack_id, seed)
                ok, detail = _overlays_valid(m.slice_id, ld, ea, strict)
                if not ok:
                    invalid.append("{}({})".format(m.slice_id, detail))
                # determinism: rebuild and compare content hashes
                ld2, ea2 = _build_overlays(m, world_pack_id, seed)
                if hash_obj(LD.content_for_hash(ld)) != hash_obj(LD.content_for_hash(ld2)) or \
                        ea.get("content_hash") != ea2.get("content_hash"):
                    nondet.append(m.slice_id)
            except Exception as exc:  # noqa: BLE001
                invalid.append("{}(raised {})".format(m.slice_id, exc))
        rep.check("seed[{}]::seed_{}::valid".format(i, seed), not invalid,
                  "invalid overlays: {}".format(", ".join(invalid[:4])) if invalid
                  else "{} map(s) internally valid".format(len(sample)), code=REG)
        rep.check("seed[{}]::seed_{}::deterministic".format(i, seed), not nondet,
                  "nondeterministic: {}".format(", ".join(nondet[:4])) if nondet
                  else "content hashes stable on repeat", code=DET)

    rep.set_meta(build_meta(command="seed-matrix", pack=world_pack_id, strict=strict,
                            seeds=seeds, torture=(tier == "torture"), status=None,
                            record_count=seeds,
                            extra={"tier": tier, "maps_per_seed": maps_per_seed,
                                   "capped": capped}))
    return rep, world_pack_id, seeds


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge seed-sweep validity + determinism gate.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--seeds", type=int, default=25, help="number of seeds to sweep")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, world_pack_id, n = validate_pack(args.pack, max(1, args.seeds), strict)
    rep.finalize()
    rep.write(report_dir_for(world_pack_id), "seed_matrix_report.json")
    rep.print_summary("seed-matrix")
    print("[seed-matrix] seeds_run={} record_count={}".format(n, n))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
