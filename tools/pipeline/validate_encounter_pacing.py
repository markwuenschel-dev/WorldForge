#!/usr/bin/env python3
"""validate_encounter_pacing.py — WorldForge v1.4 encounter pacing validator (Lane F).

Proves every encounter PACES honestly against its own pacing_target using the
canonical §11 metrics from encounter_contract (never reimplemented): pressure
must not sit on the player start, the required route must stay traversable,
pressure points must carry cover, a safe recovery must exist after pressure,
peaks must be present but bounded, and pressure must not all be stacked on the
objective (archetype-aware floor). Violations fail ENCOUNTER_PACING_FAILURE.

The per-check evaluation is exposed as ``pacing_check_results(enc, mission)``
so BalanceForge computes its pacing_score from the SAME thresholds.

Usage:
    python tools/pipeline/validate_encounter_pacing.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_pacing/validate_encounter_pacing_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from encounter_catalog import load_encounter_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

# Pacing bounds shared by validator and BalanceForge (brief §11/§15).
MAX_PRESSURE_PEAKS = 6
MIN_PRESSURE_PEAKS = 1
OBJECTIVE_PRESSURE_FLOOR_CM = 2000.0          # non-holdout archetypes
OBJECTIVE_PRESSURE_FLOOR_HOLDOUT_CM = 400.0   # defensive_holdout / extraction_pressure
HOLDOUT_ARCHETYPES = ("defensive_holdout", "extraction_pressure")
MAX_HAZARD_OVERLAP_RATIO = 0.5


def _num(x):
    """Return float(x) for real numerics (bool excluded), else None."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def pacing_check_results(enc, mission):
    """Evaluate every pacing check for one encounter.

    Returns a list of (name, ok, detail) tuples. Pure — this is the single
    threshold set shared by check_pacing() and run_balance_forge's pacing_score.
    """
    m = EC.pacing_metrics(enc, mission)
    pt = enc.get("pacing_target") or {}
    results = []

    def add(name, ok, detail):
        results.append((name, bool(ok), detail))

    # First pressure must exist and keep clear of the player start.
    fp = _num(m.get("distance_from_spawn_to_first_pressure"))
    min_fp = _num(pt.get("min_first_pressure_cm"))
    add("first_pressure_far_enough",
        fp is not None and min_fp is not None and fp >= min_fp,
        "first pressure at {} cm < min_first_pressure_cm {} (pressure at player start)".format(fp, min_fp))

    # Required route must stay traversable.
    blockage = _num(m.get("route_blockage_ratio"))
    max_blockage = _num(pt.get("max_route_blockage_ratio"))
    add("route_blockage_within_target",
        blockage is not None and max_blockage is not None and blockage <= max_blockage,
        "route_blockage_ratio {} > max_route_blockage_ratio {}".format(blockage, max_blockage))
    add("route_not_fully_blocked",
        blockage is not None and blockage < 1.0,
        "route_blockage_ratio {} — required route fully inside pressure".format(blockage))

    # Pressure points must carry cover.
    cover = _num(m.get("cover_density_near_pressure"))
    min_cover = _num(pt.get("min_cover_per_pressure_point"))
    add("cover_density_meets_target",
        cover is not None and min_cover is not None and cover >= min_cover,
        "cover_density_near_pressure {} < min_cover_per_pressure_point {}".format(cover, min_cover))

    # A safe recovery must exist after pressure.
    safe = _num(m.get("safe_zone_distance_after_pressure"))
    add("safe_recovery_exists", safe is not None,
        "no safe zone reachable after pressure (safe_zone_distance_after_pressure is None)")

    # Peaks: present but bounded.
    peaks = m.get("pressure_peak_count") or 0
    add("pressure_peaks_at_least_one", peaks >= MIN_PRESSURE_PEAKS,
        "pressure_peak_count {} < {} — encounter has no pressure".format(peaks, MIN_PRESSURE_PEAKS))
    add("pressure_peaks_bounded", peaks <= MAX_PRESSURE_PEAKS,
        "pressure_peak_count {} > {} — too many peaks".format(peaks, MAX_PRESSURE_PEAKS))
    add("standard_profile_has_pressure",
        enc.get("encounter_profile") != "standard_pressure" or peaks >= MIN_PRESSURE_PEAKS,
        "standard_pressure encounter has pressure_peak_count {} — no pressure in a standard mission".format(peaks))

    # Objective pressure distance: present, and not all stacked on the objective.
    opd = _num(m.get("objective_pressure_distance"))
    archetype = enc.get("encounter_archetype")
    floor = (OBJECTIVE_PRESSURE_FLOOR_HOLDOUT_CM if archetype in HOLDOUT_ARCHETYPES
             else OBJECTIVE_PRESSURE_FLOOR_CM)
    add("objective_pressure_present", opd is not None,
        "objective_pressure_distance is None — no objective/pressure relation")
    add("objective_pressure_distance_ok", opd is not None and opd >= floor,
        "objective_pressure_distance {} < {} cm floor for archetype {!r} "
        "(pressure stacked at objective)".format(opd, floor, archetype))

    # Hazards must not smother the route.
    hazard = _num(m.get("hazard_overlap_ratio"))
    add("hazard_overlap_bounded", hazard is not None and hazard <= MAX_HAZARD_OVERLAP_RATIO,
        "hazard_overlap_ratio {} > {}".format(hazard, MAX_HAZARD_OVERLAP_RATIO))

    return results


def check_pacing(rep, eid, enc, mission):
    """Add all pacing checks for one encounter to ``rep``."""
    code = FailureCode.ENCOUNTER_PACING_FAILURE
    for name, ok, detail in pacing_check_results(enc, mission):
        rep.check("{}::{}".format(eid, name), ok, detail, code=code)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate v1.4 encounter pacing.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted((catalog.get("encounters") or {}).keys())
    if not eids:
        rep.error("no encounters — run 'make create-encounters' first")
    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("{}::loads".format(eid), False, err,
                      code=FailureCode.ENCOUNTER_PACING_FAILURE)
            continue
        mission, merr = MC.load_mission(enc.get("mission_id"))
        if mission is None:
            rep.check("{}::mission_loads".format(eid), False, merr,
                      code=FailureCode.ENCOUNTER_PACING_FAILURE)
            continue
        check_pacing(rep, eid, enc, mission)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-pacing", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_pacing",
              "validate_encounter_pacing_report.json")
    rep.print_summary("validate-encounter-pacing")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
