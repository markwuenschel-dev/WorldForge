#!/usr/bin/env python3
"""fuzz_mission_matrix.py — WorldForge v1.3 MissionForge mutation-fuzz gate (Agent 6).

The MissionForge sibling of fuzz_biome_matrix.py / fuzz_world_pack.py. Where those
throw fuzzed biome/environment combinations at the contract cores, this fuzzer
clones a REAL generated mission (which passes every validator) and applies exactly
ONE deterministic corruption — drop a required anchor, zero every state delta,
break the route's hazard claim, dangle a reward on a ghost completion, fake a mesh
dependency, drop the completion key from the persisted set, swap the biome, etc. —
then runs the validator that OWNS that corruption and proves the mutation is
REJECTED. It proves the mission gate has TEETH: no mutation slips through, and no
validator crashes on malformed input.

The fuzz is a pure function of the case index (``random.Random(BASE_SEED + i)`` —
never time / os entropy), so the run is fully reproducible: the same --cases N
always exercises the same N mutations. The validators are run IN-PROCESS against
the mutated mission dict (never the on-disk catalog), so the fuzzer can never
dirty the generated tree; a catalog byte-snapshot is still restored in a finally
as belt-and-suspenders insurance.

A mutation that SHOULD be rejected but is ACCEPTED is a fake-green hole
(``wrongly_accepted``); an uncaught validator exception is a ``crash``. Either is
a ``FailureCode.FUZZ_FAILURE``. Exit 0 iff 0 crashes AND 0 wrongly_accepted.

Report: procedural/reports/missions/fuzz_mission_matrix/fuzz_mission_matrix_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/fuzz_mission_matrix.py \
        --pack mission_loop_world --cases 200 --strict
"""

import argparse
import copy
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC  # noqa: E402
from mission_catalog import catalog_path, load_mission_catalog  # noqa: E402
from mesh_catalog import load_mesh_catalog  # noqa: E402
import external_asset_contract as EAC  # noqa: E402
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

# Validator cores (imported, never subprocessed — module main() is guarded).
import validate_mission_graph as vgraph  # noqa: E402
import validate_mission_objectives as vobj  # noqa: E402
import validate_mission_routes as vroutes  # noqa: E402
import validate_mission_state as vstate  # noqa: E402
import validate_mission_rewards as vrewards  # noqa: E402
import validate_mission_dependencies as vdeps  # noqa: E402
import validate_mission_save_load as vsave  # noqa: E402
import validate_mission_biome_compatibility as vbiome  # noqa: E402
import validate_mission_contract as vcontract  # noqa: E402

FUZZ = FailureCode.FUZZ_FAILURE
BASE_SEED = 1303013  # fixed; per-case rng = Random(BASE_SEED + i)


# =============================================================================
# corruptions — each mutates a clone in place and returns a short note. Each is
# owned by ONE validator core (the "run" key) that MUST reject the mutation.
# =============================================================================
def _mut_drop_start(m, rng):
    m.pop("start_anchor", None)
    return "dropped start_anchor"


def _mut_drop_objectives(m, rng):
    m["objective_anchors"] = []
    return "emptied objective_anchors"


def _mut_zero_state(m, rng):
    for s in m.get("state_keys") or []:
        s["delta"] = 0.0
        s["expected_final"] = float(s.get("initial", 0.0))  # keep arithmetic honest
    return "zeroed every state delta"


def _mut_break_route_avoids(m, rng):
    (m.setdefault("required_route", {}))["avoids_hazards"] = False
    return "required_route.avoids_hazards -> False"


def _mut_dangle_reward(m, rng):
    rewards = m.get("reward_outputs") or []
    if rewards:
        rewards[0]["fires_on"] = "ghost_{}".format(rng.randint(0, 1 << 30))
    else:
        m["reward_outputs"] = [{"reward_id": "r", "reward_type": "unlock",
                                "fires_on": "ghost_{}".format(rng.randint(0, 1 << 30))}]
    return "reward fires_on a ghost completion"


def _mut_fake_mesh(m, rng):
    md = m.setdefault("mesh_dependencies", {})
    md["resolved_mesh_assets"] = ["mesh_fuzz_{}".format(rng.randint(0, 1 << 30))]
    return "resolved_mesh_assets -> fabricated id"


def _mut_undeclared_completion_key(m, rng):
    comps = m.get("completion_conditions") or []
    if comps:
        comps[0]["state_key"] = "fuzz_key_{}".format(rng.randint(0, 1 << 30))
    return "completion references an undeclared state key"


def _mut_empty_rewards(m, rng):
    m["reward_outputs"] = []
    return "emptied reward_outputs"


def _mut_bad_operator(m, rng):
    comps = m.get("completion_conditions") or []
    if comps:
        comps[0]["operator"] = rng.choice(["!!", "=>", "approx", ""])
    return "completion operator not in the allowed set"


def _mut_corrupt_route_length(m, rng):
    route = m.setdefault("required_route", {})
    base = float(route.get("length_cm") or 1000.0)
    route["length_cm"] = base * 3.0 + 12345.0 + rng.randint(1, 999)  # far off geometry
    return "route length_cm fabricated (>1% off geometry)"


def _mut_persist_drops_completion(m, rng):
    keys = m.setdefault("state_keys", [])
    aux = "aux_{}".format(rng.randint(0, 1 << 20))
    keys.append({"key": aux, "initial": 0.0, "delta": 0.0, "expected_final": 0.0})
    (m.setdefault("save_load_contract", {}))["persist_keys"] = [aux]  # drops completion key
    return "persist_keys omits the completion state key"


def _mut_wrong_biome(m, rng):
    cur = m.get("biome_family")
    others = [b for b in MC.BIOME_FAMILIES if b != cur]
    m["biome_family"] = rng.choice(others) if others else cur
    return "biome_family swapped away from the source map's biome"


# Each entry: (mutate_fn, run_fn). run_fn(rep, mid, m, ctx) drives the owning core.
def _run_graph(rep, mid, m, ctx):
    vgraph.check_graph(rep, mid, m)


def _run_obj(rep, mid, m, ctx):
    vobj.check_objectives(rep, mid, m, ctx["archetypes"])


def _run_routes(rep, mid, m, ctx):
    vroutes.check_route(rep, mid, m)


def _run_state(rep, mid, m, ctx):
    vstate.check_mission(rep, mid, m)


def _run_rewards(rep, mid, m, ctx):
    vrewards.check_mission(rep, mid, m)


def _run_deps(rep, mid, m, ctx):
    vdeps.check_mission(rep, mid, m, ctx["mesh_assets"], ctx["ext_assets"])


def _run_save(rep, mid, m, ctx):
    vsave.check_mission(rep, mid, m)


def _run_biome(rep, mid, m, ctx):
    vbiome.check_biome(rep, mid, m, ctx["mesh_assets"], ctx["ext_assets"])


def _run_contract(rep, mid, m, ctx):
    vcontract.check_mission(rep, mid, m, ctx["strict"])


CORRUPTIONS = (
    ("drop_start_anchor", _mut_drop_start, _run_graph),
    ("drop_objectives", _mut_drop_objectives, _run_obj),
    ("zero_state_deltas", _mut_zero_state, _run_state),
    ("break_route_avoids", _mut_break_route_avoids, _run_routes),
    ("dangle_reward", _mut_dangle_reward, _run_rewards),
    ("fake_mesh_dep", _mut_fake_mesh, _run_deps),
    ("undeclared_completion_key", _mut_undeclared_completion_key, _run_state),
    ("empty_rewards", _mut_empty_rewards, _run_rewards),
    ("bad_completion_operator", _mut_bad_operator, _run_contract),
    ("corrupt_route_length", _mut_corrupt_route_length, _run_routes),
    ("persist_drops_completion", _mut_persist_drops_completion, _run_save),
    ("wrong_biome", _mut_wrong_biome, _run_biome),
)


# =============================================================================
# case runner
# =============================================================================
def _load_real_missions():
    catalog = load_mission_catalog(REPO_ROOT)
    mids = sorted((catalog.get("missions") or {}).keys())
    missions = {}
    for mid in mids:
        m, err = MC.load_mission(mid)
        if m is not None:
            missions[mid] = m
    return missions


def run_cases(rep, missions, ctx, cases, strict):
    tally = {"valid_rejected": 0, "wrongly_accepted": 0, "crashes": 0}
    mids = sorted(missions)
    if not mids:
        rep.error("no real missions to clone/mutate")
        return tally
    for i in range(cases):
        rng = random.Random(BASE_SEED + i)
        base_mid = mids[i % len(mids)]
        name, mutate, run = CORRUPTIONS[i % len(CORRUPTIONS)]
        case = "case[{}]::{}::{}".format(i, name, base_mid)
        try:
            mutated = copy.deepcopy(missions[base_mid])
            note = mutate(mutated, rng)
            sub = ValidationReport("mission", "fuzz_{}".format(i), strict=strict)
            run(sub, base_mid, mutated, ctx)
            sub.finalize()
            rejected = not sub.passed
            if rejected:
                tally["valid_rejected"] += 1
                rep.check(case, True, "mutation REJECTED: {}".format(note), code=FUZZ)
            else:
                tally["wrongly_accepted"] += 1
                rep.check(case, False,
                          "FAKE-GREEN: mutation ACCEPTED (validator hole): {}".format(note),
                          code=FUZZ)
        except Exception as exc:  # noqa: BLE001
            tally["crashes"] += 1
            rep.check(case, False, "FUZZ CRASH: {}: {}".format(type(exc).__name__, exc), code=FUZZ)
    return tally


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.3 MissionForge mutation-fuzz gate — "
                    "every one-defect mutation of a real mission must be rejected, never crash.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--cases", type=int, default=200)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    cases = max(1, args.cases)

    rep = ValidationReport("pack", args.pack, strict=strict)

    # Belt-and-suspenders: snapshot the catalog bytes so even an unexpected code
    # path can never leave the ledger changed (the fuzz is in-process/read-only).
    cat_file = catalog_path(REPO_ROOT)
    cat_backup = cat_file.read_bytes() if cat_file.is_file() else None
    try:
        missions = _load_real_missions()
        ctx = {
            "archetypes": MC.load_all_archetypes(),
            "mesh_assets": (load_mesh_catalog(REPO_ROOT) or {}).get("assets") or {},
            "ext_assets": (EAC.load_external_catalog(REPO_ROOT) or {}).get("assets") or {},
            "strict": strict,
        }
        tally = run_cases(rep, missions, ctx, cases, strict)
    finally:
        if cat_backup is not None:
            cat_file.write_bytes(cat_backup)

    print("[fuzz] cases={} valid_rejected={} wrongly_accepted={} crashes={}".format(
        cases, tally["valid_rejected"], tally["wrongly_accepted"], tally["crashes"]))

    rep.finalize()
    rep.set_meta(build_meta(
        command="fuzz-mission-matrix", pack=args.pack, strict=strict, torture=True,
        status=rep.status, record_count=cases,
        extra={"valid_rejected": tally["valid_rejected"],
               "wrongly_accepted": tally["wrongly_accepted"],
               "crashes": tally["crashes"], "base_seed": BASE_SEED,
               "corruptions": [c[0] for c in CORRUPTIONS]}))
    rep.write(REPO_ROOT / MC.MISSION_REPORTS_REL / "fuzz_mission_matrix",
              "fuzz_mission_matrix_report.json")
    rep.print_summary("fuzz-mission-matrix")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
