#!/usr/bin/env python3
"""fuzz_world_pack.py — WorldForge v1.0x fuzz gate (Agent 7).

Throws fuzzed configurations across many dimensions at the real validator cores
and proves that EVERY case either PASSES cleanly (a valid combination) or FAILS
cleanly with a classified failure code (an invalid combination) — and NEVER
crashes / throws an uncaught traceback.

Fuzz dimensions: terrain form, placement, material variant, environment class,
visual style, fog, lighting, POI density/placement, entity density, budget class,
ray tracing on/off, performance/cinematic rendering, scenario/time-of-day state.

Two validator surfaces are fuzzed and alternated per case:
  * the environment/visual compatibility matrix (profiles.incompatible + the
    field/class rules) — fed a synthetic resolved-environment;
  * the level-design + entity-anchor overlays (validate_pois / entity_anchors
    validator cores) — fed a base-valid in-memory overlay with random mutations.

Only a CRASH (uncaught exception) — or a case that neither cleanly passes nor
cleanly fails — is a ``FailureCode.FUZZ_FAILURE``. Clean rejections are expected
and counted, not failures. Fuzzing is seeded, so the whole run is reproducible.

Report: ``fuzz_world_pack_report.json`` with record_count == cases.

Usage:
    PYTHONUTF8=1 python tools/pipeline/fuzz_world_pack.py --pack desert_mvp_world --cases 25 --strict
"""

import argparse
import copy
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta  # noqa: E402
from world_pack_maps import enumerate_maps, report_dir_for, MapRecord  # noqa: E402
import profiles as P  # noqa: E402
import generate_level_design as LD  # noqa: E402
import generate_entity_anchors as EA  # noqa: E402
from validate_pois import check_overlay as pois_check  # noqa: E402
from validate_entity_anchors import check_map as ea_check  # noqa: E402

FUZZ = FailureCode.FUZZ_FAILURE

ENV_CLASSES = ("photoreal", "cinematic", "stylized", "low_visibility",
               "performance", "raytraced", "alien", "readable")
STYLE_CLASSES = ("photoreal", "cinematic", "stylized", "low_visibility",
                 "performance", "alien", "readable")
RENDER_MODES = ("standard", "cinematic", "performance")
RT_REQ = ("off", "optional", "required")
RT_MODES = ("off", "reflections", "full")
TOD_PHASES = ("day", "dusk", "night", "dawn")
BUDGET_TOKENS = ("light", "medium", "heavy", "core", "ambient", "optional", "bogus_class")


# =============================================================================
# environment/visual compatibility fuzz
# =============================================================================
def _fuzz_env(rng):
    """Build a synthetic resolved-environment across the fuzz dimensions."""
    env_class = rng.choice(ENV_CLASSES)
    style_class = rng.choice(STYLE_CLASSES)
    phase = rng.choice(TOD_PHASES)
    target_ev = rng.choice([-2.0, 0.0, 2.0, 8.0])
    exposure_ev = rng.choice([target_ev, target_ev + rng.choice([0.0, 0.5, 3.0])])
    rt_req = rng.choice(RT_REQ)
    rt_mode = rng.choice(RT_MODES)
    fog_density = rng.choice([0.0, 0.2, 0.5, 0.9])
    low_vis = rng.choice([True, False])
    render_mode = rng.choice(RENDER_MODES)
    resolved = {
        "environment": {"class": env_class, "low_visibility": low_vis},
        "children": {
            "visual_style": {"style_class": style_class},
            "rendering": {"ray_tracing": rt_req, "rendering_mode": render_mode},
            "ray_tracing": {"mode": rt_mode},
            "post_process": {"exposure_ev": exposure_ev},
            "time_of_day": {"phase": phase, "target_exposure_ev": target_ev},
            "fog": {"density": fog_density},
        },
    }
    return resolved


def _fuzz_case_env(rep, case_idx, rng):
    """Run one env-compat fuzz case. Return 'valid' | 'reject' | 'crash'."""
    try:
        resolved = _fuzz_env(rng)
        reasons = P.incompatible(resolved)
        ok = not reasons
        rep.check("case[{}]::env_compat".format(case_idx), True,
                  ("valid combo" if ok else "cleanly rejected: " + "; ".join(reasons[:2])),
                  code=FUZZ)
        return "valid" if ok else "reject"
    except Exception as exc:  # noqa: BLE001
        rep.check("case[{}]::env_compat".format(case_idx), False,
                  "FUZZ CRASH in env-compat: {}".format(exc), code=FUZZ)
        return "crash"


# =============================================================================
# overlay fuzz (level-design + entity-anchors)
# =============================================================================
def _mutate_ld(ld, rng):
    if not ld.get("pois"):
        return
    poi = rng.choice(ld["pois"])
    kind = rng.choice(["budget", "drop_approach", "teleport", "empty_style", "empty_inspection"])
    if kind == "budget":
        poi["budget_class"] = rng.choice(BUDGET_TOKENS)
    elif kind == "drop_approach":
        poi.pop("approach_vector", None)
    elif kind == "teleport":
        poi["world_position"] = [9.9e9, 9.9e9, 9.9e9]
        poi["bounds"] = {"min": [9.9e9, 9.9e9, 0], "max": [1e10, 1e10, 1]}
    elif kind == "empty_style":
        poi["style_compat"] = []
    elif kind == "empty_inspection":
        poi["inspection"] = {}


def _mutate_ea(ea, rng):
    anchors = ea.get("anchors") or []
    if not anchors:
        return
    a = rng.choice(anchors)
    kind = rng.choice(["budget", "faction", "capacity", "float", "drop_field"])
    if kind == "budget":
        a["budget_class"] = rng.choice(BUDGET_TOKENS)
    elif kind == "faction":
        a["faction_tag"] = "not_a_real_faction"
    elif kind == "capacity":
        a["capacity"] = 9999
        a["type"] = "enemy_spawn_zone"
    elif kind == "float":
        a["position"] = [a["position"][0], a["position"][1], a.get("ground_z", 0) + 100000]
    elif kind == "drop_field":
        a.pop("provenance", None)


def _fuzz_case_overlay(rep, case_idx, base_map, world_pack_id, rng, strict):
    """Run one overlay fuzz case. Return 'valid' | 'reject' | 'crash'."""
    try:
        spec = copy.deepcopy(base_map.spec)
        spec["seed"] = rng.randint(1, 2 ** 31 - 1)
        mr = MapRecord(dict(base_map)); mr["spec"] = spec
        ld = LD.build_overlay(mr, world_pack_id)
        ea = EA.build_overlay(mr, level_design=ld)
        mutated = rng.random() < 0.6
        if mutated:
            if rng.random() < 0.5:
                _mutate_ld(ld, rng)
            else:
                _mutate_ea(ea, rng)
        tmp = ValidationReport("x", "x", strict=strict)
        pois_check(tmp, base_map.slice_id, ld)
        ea_check(tmp, base_map.slice_id, ea, strict)
        tmp.finalize()
        ok = tmp.passed
        # A well-formed outcome is always classified (pass or coded-fail); the
        # fuzz check fails ONLY on a crash.
        rep.check("case[{}]::overlay".format(case_idx), True,
                  ("valid overlay (mutated={})".format(mutated) if ok
                   else "cleanly rejected (mutated={}): {}".format(
                       mutated, "; ".join(tmp.failures[:2]))),
                  code=FUZZ)
        return "valid" if ok else "reject"
    except Exception as exc:  # noqa: BLE001
        rep.check("case[{}]::overlay".format(case_idx), False,
                  "FUZZ CRASH in overlay: {}".format(exc), code=FUZZ)
        return "crash"


def validate_pack(pack, cases, strict, base_seed=1337):
    world_pack_id, maps = enumerate_maps(pack)
    present = [m for m in maps if m.spec_exists and m.slice_id]
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)
    if not present:
        rep.error("world pack enumerated zero overlay-eligible maps")
        return rep, world_pack_id, {"valid": 0, "reject": 0, "crash": 0}

    tally = {"valid": 0, "reject": 0, "crash": 0}
    for i in range(cases):
        rng = random.Random(base_seed + i)
        if i % 2 == 0:
            outcome = _fuzz_case_env(rep, i, rng)
        else:
            base_map = present[i % len(present)]
            outcome = _fuzz_case_overlay(rep, i, base_map, world_pack_id, rng, strict)
        tally[outcome] += 1

    print("[fuzz] cases={} valid={} cleanly_rejected={} crashes={}".format(
        cases, tally["valid"], tally["reject"], tally["crash"]))
    rep.set_meta(build_meta(command="fuzz-world-pack", pack=world_pack_id, strict=strict,
                            torture=True, status=None, record_count=cases,
                            extra={"valid": tally["valid"], "cleanly_rejected": tally["reject"],
                                   "crashes": tally["crash"], "base_seed": base_seed}))
    return rep, world_pack_id, tally


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge fuzz gate — clean pass/reject, never crash.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--cases", type=int, default=25)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep, world_pack_id, _tally = validate_pack(args.pack, max(1, args.cases), strict)
    rep.finalize()
    rep.write(report_dir_for(world_pack_id), "fuzz_world_pack_report.json")
    rep.print_summary("fuzz-world-pack")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
