#!/usr/bin/env python3
"""fuzz_encounter_matrix.py — WorldForge v1.4 EncounterForge mutation-fuzz gate (Lane G).

The EncounterForge sibling of fuzz_mission_matrix.py. It clones a REAL generated
encounter (which passes every validator) and applies exactly ONE deterministic
corruption — drop the spawn/start clearance, zero every state delta, dangle a
reward off resolution, fabricate a mesh id, char-explode the megascans list (a
regression guard for a real bug: a scalar string iterated into characters), lie
about the difficulty band, overrun the pressure budget, explode route blockage,
swap a hazard to a biome-foreign type, drop persistence, corrupt the spawn
policy/waves, remove the escape, displace cover, drift the seed, doctor the
beta/balance evidence — then runs ONLY the validator core that OWNS that
corruption and proves the mutation is REJECTED. Every importable v1.4 core is
exercised at least once.

The fuzz is a pure function of the case index (``random.Random(BASE_SEED + i)``)
so the run is fully reproducible. Cores run IN-PROCESS against mutated deep
copies (never the on-disk catalog); a catalog byte-snapshot is still restored in
a finally as belt-and-suspenders insurance.

A mutation ACCEPTED is a fake-green hole (``wrongly_accepted``); an uncaught
exception is a ``crash``. Exit 0 iff 0 crashes AND 0 wrongly_accepted.

Report: procedural/reports/encounters/fuzz_encounter_matrix/fuzz_encounter_matrix_report.json

Usage:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/fuzz_encounter_matrix.py \
        --pack encounter_loop_world --cases 300 --strict
"""

import argparse
import copy
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC  # noqa: E402
import mission_contract as MC  # noqa: E402
import playtest_beta_contract as PB  # noqa: E402
from encounter_catalog import catalog_path, load_encounter_catalog  # noqa: E402
from mesh_catalog import load_mesh_catalog  # noqa: E402
import external_asset_contract as EAC  # noqa: E402
from report_meta import build_meta  # noqa: E402
from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

# Validator cores (imported, never subprocessed — module main() is guarded).
import validate_encounter_contract as vcontract  # noqa: E402
import validate_encounter_archetypes as varch  # noqa: E402
import validate_spawn_groups as vspawn  # noqa: E402
import validate_encounter_anchors as vanchors  # noqa: E402
import validate_encounter_routes as vroutes  # noqa: E402
import validate_encounter_biome_compatibility as vbiome  # noqa: E402
import validate_encounter_mission_compatibility as vmcompat  # noqa: E402
import validate_encounter_state as vstate  # noqa: E402
import validate_encounter_save_load as vsave  # noqa: E402
import validate_encounter_rewards as vrewards  # noqa: E402
import validate_encounter_mesh_dependencies as vmesh  # noqa: E402
import validate_encounter_cover as vcover  # noqa: E402
import validate_encounter_hazards as vhazards  # noqa: E402
import validate_encounter_resources as vresources  # noqa: E402
import validate_encounter_pressure as vpressure  # noqa: E402
import validate_encounter_pacing as vpacing  # noqa: E402
import validate_playtest_beta_contract as vbetacon  # noqa: E402
import validate_playtest_beta_reports as vbetarep  # noqa: E402
import validate_balance_reports as vbalance  # noqa: E402

FUZZ = FailureCode.FUZZ_FAILURE
BASE_SEED = 1404014  # fixed; per-case rng = Random(BASE_SEED + i)


# =============================================================================
# corruptions — each mutates a clone in place (and/or doctors aux evidence) and
# returns a short note. Each is owned by ONE core (the run fn) that MUST reject.
# =============================================================================
def _mission_of(enc, ctx):
    return ctx["missions"].get(enc.get("mission_id"))


def _mut_drop_start_clearance(enc, rng, ctx, aux):
    mission = _mission_of(enc, ctx) or {}
    start = (mission.get("start_anchor") or {}).get("world_position") or [0.0, 0.0, 0.0]
    for a in enc.get("spawn_anchors") or []:
        a["world_position"] = list(start)
    return "every spawn anchor moved onto the mission start (clearance dropped)"


def _mut_drop_required_field(enc, rng, ctx, aux):
    enc.pop("budget_class", None)
    return "dropped required field budget_class"


def _mut_spawn_policy(enc, rng, ctx, aux):
    for g in enc.get("spawn_groups") or []:
        others = [p for p in EC.SPAWN_POLICIES if p != g.get("spawn_policy")]
        g["spawn_policy"] = rng.choice(others)
    return "spawn policy swapped away from the archetype spec (wave corruption)"


def _mut_safe_zone_smother(enc, rng, ctx, aux):
    spawns = [a.get("world_position") for a in enc.get("spawn_anchors") or []
              if a.get("world_position")]
    if not spawns:
        return "no spawns (mutation vacuous)"
    for i, z in enumerate(enc.get("safe_zones") or []):
        s = spawns[i % len(spawns)]
        off = rng.uniform(100.0, 800.0)
        z["world_position"] = [s[0] + off, s[1] + off, 0.0]
    return "every safe zone moved inside the spawn pressure bubble"


def _mut_escape_removal(enc, rng, ctx, aux):
    enc["escape_routes"] = []
    return "emptied escape_routes"


def _mut_blockage_explosion(enc, rng, ctx, aux):
    mission = _mission_of(enc, ctx) or {}
    corridor = EC.densify_route(
        (mission.get("required_route") or {}).get("waypoints"))
    enc["spawn_anchors"] = [
        {"id": "fuzz_block_{}".format(i), "kind": "spawn",
         "world_position": list(wp), "valid_spawn": True}
        for i, wp in enumerate(corridor)]
    return "spawn anchors placed on every densified route waypoint (blockage -> 1.0)"


def _mut_hazard_type_swap(enc, rng, ctx, aux):
    biome = enc.get("biome_family")
    allowed = set(EC.BIOME_HAZARD_TYPES.get(biome, ()))
    foreign = [h for h in EC.HAZARD_TYPES if h not in allowed]
    bad = foreign[0] if foreign else "heat"
    zones = enc.get("hazard_zones") or []
    if zones:
        for hz in zones:
            hz["hazard_type"] = bad
            hz["visual_marker"] = "hazard_marker_{}".format(bad)
    else:
        zid = "fuzz_hazard_{}".format(rng.randint(0, 1 << 20))
        enc["hazard_zones"] = [{
            "id": zid, "hazard_type": bad,
            "bounds": {"min": [0.0, 0.0, 0.0], "max": [1000.0, 1000.0, 1200.0]},
            "visual_marker": "hazard_marker_{}".format(bad)}]
        enc.setdefault("visual_marker_requirements", []).append(
            {"target_id": zid, "marker_class": "hazard_marker_{}".format(bad)})
    return "hazard type swapped to biome-foreign {!r} for {}".format(bad, biome)


def _mut_seed_drift(enc, rng, ctx, aux):
    enc["seed"] = (enc.get("seed") or 0) + 1 + rng.randint(0, 5)
    return "encounter seed drifted away from the mission seed"


def _mut_zero_state_deltas(enc, rng, ctx, aux):
    for s in enc.get("state_keys") or []:
        if isinstance(s, dict):
            s["delta"] = 0
            s["expected_final"] = s.get("initial")  # keep arithmetic honest
    return "zeroed every state delta (encounter never resolves)"


def _mut_persist_drop(enc, rng, ctx, aux):
    (enc.setdefault("save_load_contract", {}))["persist_keys"] = []
    return "persist_keys emptied (completion state not saved)"


def _mut_dangle_reward(enc, rng, ctx, aux):
    ghost = "fuzz_ghost_{}".format(rng.randint(0, 1 << 30))
    for h in enc.get("reward_hooks") or []:
        h["fires_on"] = ghost
    return "reward hooks fire on {!r} instead of encounter_resolved".format(ghost)


def _mut_fake_mesh_id(enc, rng, ctx, aux):
    md = enc.setdefault("mesh_dependencies", {})
    res = md.get("resolved_mesh_assets")
    res = list(res) if isinstance(res, list) else []
    res.append("mesh_fuzz_{}".format(rng.randint(0, 1 << 30)))
    md["resolved_mesh_assets"] = res
    return "resolved_mesh_assets gained a fabricated id"


def _mut_char_explode_megascans(enc, rng, ctx, aux):
    # Regression guard: a scalar string must never be iterated into characters
    # and each character silently accepted.
    enc["megascans_dependencies"] = "megascans_ghost_asset"
    return "megascans_dependencies set to a scalar string (char-explode guard)"


def _mut_cover_displacement(enc, rng, ctx, aux):
    covers = enc.get("cover_anchors") or []
    if covers:
        for cov in covers:
            pos = cov.get("world_position") or [0.0, 0.0, 0.0]
            cov["world_position"] = [pos[0] + 100000.0, pos[1] + 100000.0, 0.0]
        return "every cover anchor displaced 100000cm from its spawn cluster"
    spawns = [a.get("world_position") for a in enc.get("spawn_anchors") or []
              if a.get("world_position")]
    base = spawns[0] if spawns else [0.0, 0.0, 0.0]
    enc["cover_anchors"] = [{
        "id": "fuzz_cover_orphan", "kind": "cover",
        "world_position": [base[0] + 100000.0, base[1] + 100000.0, 0.0],
        "height_class": "half_height", "collision": True}]
    return "orphan cover anchor injected 100000cm from every spawn"


def _mut_malformed_hazard_bounds(enc, rng, ctx, aux):
    zones = enc.get("hazard_zones") or []
    if zones:
        for hz in zones:
            b = hz.get("bounds") or {}
            mn, mx = b.get("min"), b.get("max")
            if mn and mx:
                hz["bounds"] = {"min": list(mx), "max": list(mn)}  # min > max
            else:
                hz["bounds"] = {"min": [1000.0, 1000.0, 0.0],
                                "max": [-1000.0, -1000.0, 1200.0]}
        return "hazard bounds inverted (min > max)"
    biome = enc.get("biome_family")
    htype = (EC.BIOME_HAZARD_TYPES.get(biome) or ("heat",))[0]
    zid = "fuzz_hazard_bounds_{}".format(rng.randint(0, 1 << 20))
    enc["hazard_zones"] = [{
        "id": zid, "hazard_type": htype,
        "bounds": {"min": [1000.0, 1000.0, 0.0], "max": [-1000.0, -1000.0, 1200.0]},
        "visual_marker": "hazard_marker_{}".format(htype)}]
    enc.setdefault("visual_marker_requirements", []).append(
        {"target_id": zid, "marker_class": "hazard_marker_{}".format(htype)})
    return "hazard zone injected with inverted bounds (min > max)"


def _mut_resource_link_corruption(enc, rng, ctx, aux):
    node_ids = [n.get("id") for n in enc.get("resource_nodes") or []
                if isinstance(n, dict) and n.get("id")]
    if node_ids:
        enc["objective_links"] = [l for l in enc.get("objective_links") or []
                                  if l not in node_ids]
        return "resource node ids removed from objective_links (unreachable resource)"
    enc.setdefault("reward_hooks", []).append(
        {"reward_id": "fuzz_rg_{}".format(rng.randint(0, 1 << 20)),
         "reward_type": "resource_grant", "fires_on": "encounter_resolved"})
    return "phantom resource_grant hook injected with zero resource nodes"


def _mut_band_lie(enc, rng, ctx, aux):
    cur = enc.get("difficulty_band")
    others = [b for b in EC.DIFFICULTY_BANDS if b not in ("invalid", cur)]
    enc["difficulty_band"] = rng.choice(others)
    return "difficulty_band lied: {!r} -> {!r}".format(cur, enc["difficulty_band"])


def _mut_budget_overrun(enc, rng, ctx, aux):
    for g in enc.get("spawn_groups") or []:
        g["difficulty_value"] = round(40.0 + rng.random(), 3)
    return "spawn difficulty exploded (pressure far over budget)"


def _mut_first_pressure_at_start(enc, rng, ctx, aux):
    mission = _mission_of(enc, ctx) or {}
    start = (mission.get("start_anchor") or {}).get("world_position") or [0.0, 0.0, 0.0]
    for a in enc.get("spawn_anchors") or []:
        a["world_position"] = list(start)
    return "all pressure stacked on the player start (pacing floor violated)"


def _mut_beta_modes_stripped(enc, rng, ctx, aux):
    pt = enc.setdefault("playtest_contract", {})
    pt["modes"] = [m for m in (pt.get("modes") or [])
                   if not str(m).startswith("encounter_")]
    return "playtest contract stripped of every encounter_* beta mode"


def _mut_beta_report_doctored(enc, rng, ctx, aux):
    report = ctx["beta_report"](enc["encounter_id"])
    if report is not None:
        report = copy.deepcopy(report)
        report["completed"] = True
        modes = report.get("modes") or {}
        if modes:
            first = sorted(modes)[0]
            modes[first] = dict(modes.get(first) or {})
            modes[first]["passed"] = False
        report["modes"] = modes
    aux["report"] = report
    return "beta report doctored: completed=True while a declared mode failed"


def _mut_balance_band_doctored(enc, rng, ctx, aux):
    report = ctx["balance_report"](enc["encounter_id"])
    if report is not None:
        report = copy.deepcopy(report)
        cur = report.get("difficulty_band")
        others = [b for b in EC.DIFFICULTY_BANDS if b not in ("invalid", cur)]
        report["difficulty_band"] = rng.choice(others)
    aux["report"] = report
    return "balance report band doctored away from the classified band"


def _mut_pacing_target_impossible(enc, rng, ctx, aux):
    (enc.setdefault("pacing_target", {}))["min_first_pressure_cm"] = 9e8
    return "pacing target made unsatisfiable (min_first_pressure_cm=9e8)"


# =============================================================================
# owning-core runners — run(rep, eid, enc, ctx, aux)
# =============================================================================
def _run_contract(rep, eid, enc, ctx, aux):
    vcontract.check_encounter(rep, eid, enc, ctx["strict"], pack=ctx["pack"])


def _run_archetypes(rep, eid, enc, ctx, aux):
    varch.check_archetype(rep, eid, enc, ctx["archetypes"])


def _run_spawn_groups(rep, eid, enc, ctx, aux):
    vspawn.check_spawn_groups(rep, eid, enc, _mission_of(enc, ctx))


def _run_anchors(rep, eid, enc, ctx, aux):
    vanchors.check_anchors(rep, eid, enc, _mission_of(enc, ctx))


def _run_routes(rep, eid, enc, ctx, aux):
    vroutes.check_routes(rep, eid, enc, _mission_of(enc, ctx))


def _run_biome(rep, eid, enc, ctx, aux):
    vbiome.check_biome(rep, eid, enc)


def _run_mission_compat(rep, eid, enc, ctx, aux):
    vmcompat.check_mission_compat(rep, eid, enc, _mission_of(enc, ctx))


def _run_state(rep, eid, enc, ctx, aux):
    vstate.check_state(rep, eid, enc, _mission_of(enc, ctx))


def _run_save(rep, eid, enc, ctx, aux):
    vsave.check_save_load(rep, eid, enc, _mission_of(enc, ctx))


def _run_rewards(rep, eid, enc, ctx, aux):
    vrewards.check_rewards(rep, eid, enc)


def _run_mesh(rep, eid, enc, ctx, aux):
    vmesh.check_mesh_deps(rep, eid, enc, ctx["mesh_assets"], ctx["ext_assets"])


def _run_cover(rep, eid, enc, ctx, aux):
    vcover.check_cover(rep, eid, enc, _mission_of(enc, ctx), ctx["mesh_assets"])


def _run_hazards(rep, eid, enc, ctx, aux):
    vhazards.check_hazards(rep, eid, enc, _mission_of(enc, ctx))


def _run_resources(rep, eid, enc, ctx, aux):
    vresources.check_resources(rep, eid, enc, _mission_of(enc, ctx))


def _run_pressure(rep, eid, enc, ctx, aux):
    vpressure.check_pressure(rep, eid, enc, _mission_of(enc, ctx))


def _run_pacing(rep, eid, enc, ctx, aux):
    vpacing.check_pacing(rep, eid, enc, _mission_of(enc, ctx))


def _run_beta_contract(rep, eid, enc, ctx, aux):
    vbetacon.check_beta_contract(rep, eid, enc)


def _run_beta_report(rep, eid, enc, ctx, aux):
    vbetarep.check_beta_report(rep, eid, enc, aux.get("report"))


def _run_balance_report(rep, eid, enc, ctx, aux):
    vbalance.check_balance_report(rep, eid, enc, aux.get("report"),
                                  entry=ctx["entries"].get(eid))


def _run_beta_modes(rep, eid, enc, ctx, aux):
    results, completed = PB.run_beta_modes(enc, _mission_of(enc, ctx))
    failed = sorted(m for m, r in results.items() if not r.get("passed"))
    rep.check("beta_modes_complete::{}".format(eid), completed is True,
              "run_beta_modes completed={} failed_modes={}".format(completed, failed),
              code=FUZZ)


CORRUPTIONS = (
    ("drop_start_clearance", _mut_drop_start_clearance, _run_spawn_groups),
    ("drop_required_field", _mut_drop_required_field, _run_contract),
    ("spawn_policy_corruption", _mut_spawn_policy, _run_archetypes),
    ("safe_zone_smother", _mut_safe_zone_smother, _run_anchors),
    ("escape_removal", _mut_escape_removal, _run_routes),
    ("blockage_explosion", _mut_blockage_explosion, _run_routes),
    ("hazard_type_swap_wrong_biome", _mut_hazard_type_swap, _run_biome),
    ("seed_drift", _mut_seed_drift, _run_mission_compat),
    ("zero_state_deltas", _mut_zero_state_deltas, _run_state),
    ("persist_drop", _mut_persist_drop, _run_save),
    ("dangle_reward", _mut_dangle_reward, _run_rewards),
    ("fake_mesh_id", _mut_fake_mesh_id, _run_mesh),
    ("char_explode_megascans", _mut_char_explode_megascans, _run_mesh),
    ("cover_displacement", _mut_cover_displacement, _run_cover),
    ("malformed_hazard_bounds", _mut_malformed_hazard_bounds, _run_hazards),
    ("resource_link_corruption", _mut_resource_link_corruption, _run_resources),
    ("band_lie", _mut_band_lie, _run_pressure),
    ("budget_overrun", _mut_budget_overrun, _run_pressure),
    ("first_pressure_at_start", _mut_first_pressure_at_start, _run_pacing),
    ("beta_modes_stripped", _mut_beta_modes_stripped, _run_beta_contract),
    ("beta_report_doctored", _mut_beta_report_doctored, _run_beta_report),
    ("balance_band_doctored", _mut_balance_band_doctored, _run_balance_report),
    ("pacing_target_impossible", _mut_pacing_target_impossible, _run_beta_modes),
)


# =============================================================================
# case runner
# =============================================================================
def _load_real_encounters():
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted((catalog.get("encounters") or {}).keys())
    encounters = {}
    for eid in eids:
        enc, _err = EC.load_encounter(eid)
        if enc is not None:
            encounters[eid] = enc
    return encounters, (catalog.get("encounters") or {})


def _report_loader(rel_dir):
    cache = {}

    def load(eid):
        if eid not in cache:
            p = REPO_ROOT / rel_dir / "{}.json".format(eid)
            try:
                cache[eid] = json.loads(p.read_text(encoding="utf-8")) \
                    if p.is_file() else None
            except Exception:  # noqa: BLE001
                cache[eid] = None
        return cache[eid]
    return load


def run_cases(rep, encounters, ctx, cases):
    tally = {"valid_rejected": 0, "wrongly_accepted": 0, "crashes": 0}
    eids = sorted(encounters)
    if not eids:
        rep.error("no real encounters to clone/mutate")
        return tally
    for i in range(cases):
        rng = random.Random(BASE_SEED + i)
        base_eid = eids[i % len(eids)]
        name, mutate, run = CORRUPTIONS[i % len(CORRUPTIONS)]
        case = "case[{}]::{}::{}".format(i, name, base_eid)
        try:
            mutated = copy.deepcopy(encounters[base_eid])
            aux = {}
            note = mutate(mutated, rng, ctx, aux)
            sub = ValidationReport("encounter", "fuzz_{}".format(i),
                                   strict=ctx["strict"])
            run(sub, base_eid, mutated, ctx, aux)
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
            rep.check(case, False, "FUZZ CRASH: {}: {}".format(type(exc).__name__, exc),
                      code=FUZZ)
    return tally


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="WorldForge v1.4 EncounterForge mutation-fuzz gate — every "
                    "one-defect mutation of a real encounter must be rejected, never crash.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--cases", type=int, default=25)
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
        encounters, entries = _load_real_encounters()
        missions = {}
        for enc in encounters.values():
            mid = enc.get("mission_id")
            if mid and mid not in missions:
                missions[mid] = MC.load_mission(mid)[0]
        ctx = {
            "pack": args.pack,
            "strict": strict,
            "missions": missions,
            "entries": entries,
            "archetypes": EC.load_all_archetypes(),
            "mesh_assets": (load_mesh_catalog(REPO_ROOT) or {}).get("assets") or {},
            "ext_assets": (EAC.load_external_catalog(REPO_ROOT) or {}).get("assets") or {},
            "beta_report": _report_loader(EC.PLAYTEST_BETA_REPORTS_REL),
            "balance_report": _report_loader(EC.BALANCE_REPORTS_REL),
        }
        tally = run_cases(rep, encounters, ctx, cases)
    finally:
        if cat_backup is not None:
            cat_file.write_bytes(cat_backup)

    print("[fuzz] cases={} valid_rejected={} wrongly_accepted={} crashes={}".format(
        cases, tally["valid_rejected"], tally["wrongly_accepted"], tally["crashes"]))

    rep.finalize()
    rep.set_meta(build_meta(
        command="fuzz-encounter-matrix", pack=args.pack, strict=strict, torture=True,
        status=rep.status, record_count=cases,
        extra={"valid_rejected": tally["valid_rejected"],
               "wrongly_accepted": tally["wrongly_accepted"],
               "crashes": tally["crashes"], "base_seed": BASE_SEED,
               "corruptions": [c[0] for c in CORRUPTIONS]}))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "fuzz_encounter_matrix",
              "fuzz_encounter_matrix_report.json")
    rep.print_summary("fuzz-encounter-matrix")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
