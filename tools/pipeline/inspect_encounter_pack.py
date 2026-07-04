#!/usr/bin/env python3
"""inspect_encounter_pack.py — WorldForge v1.4 EncounterForge operator utility (Lane G).

Read-only. Shows what the generated encounter pack (or a single encounter)
actually IS, and — with --diagnose — classifies every problem into the v1.4
Encounter / PlaytestBeta / Balance failure buckets so an operator sees which
lane is red without opening 120 encounter.json files. Mirrors
inspect_mission_pack.py; it is NOT a generator and NOT part of the
create/validate contract. It joins four things:

    procedural/generated/worldforge_encounter_catalog.json        — the catalog ledger
    procedural/generated/encounters/<encounter_id>/encounter.json — per-encounter records
    procedural/reports/encounters/playtest_beta/<encounter_id>.json — beta evidence
    procedural/reports/encounters/balance/<encounter_id>.json      — balance evidence

Three modes:
    inspect-encounter-pack   default: human summary + JSON report, exit 0
    inspect-encounter        --encounter <id>: full dossier, exit 0 (2 if unknown)
    diagnose-encounter-pack  --diagnose: classify problems into buckets,
                             exit 0 if clean, 1 if any problem (usable as a gate)

    PYTHONUTF8=1 python tools/pipeline/inspect_encounter_pack.py --pack encounter_loop_world
    PYTHONUTF8=1 python tools/pipeline/inspect_encounter_pack.py --pack encounter_loop_world --encounter enc_lp_Alien_CrystalField_Debris_Perf_01
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/inspect_encounter_pack.py --pack encounter_loop_world --diagnose --strict
"""

import argparse
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC  # noqa: E402
import mission_contract as MC  # noqa: E402
import playtest_beta_contract as PB  # noqa: E402
from encounter_catalog import load_encounter_catalog, catalog_content_hash  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta, strict_from_env, hash_obj  # noqa: E402


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------
def _beta_report_path(eid):
    return REPO_ROOT / EC.PLAYTEST_BETA_REPORTS_REL / (eid + ".json")


def _balance_report_path(eid):
    return REPO_ROOT / EC.BALANCE_REPORTS_REL / (eid + ".json")


def _load_json(path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _encounter_ids(catalog):
    """The authoritative id set: catalog records ∪ any encounter dir on disk."""
    ids = set((catalog.get("encounters") or {}).keys())
    root = REPO_ROOT / EC.ENCOUNTER_GENERATED_REL
    if root.is_dir():
        for sub in root.iterdir():
            if sub.is_dir() and (sub / "encounter.json").is_file():
                ids.add(sub.name)
    return sorted(ids)


def _load_encounters(catalog):
    """encounter_id -> encounter dict. Missing/unparseable -> None."""
    out = OrderedDict()
    for eid in _encounter_ids(catalog):
        enc, _err = EC.load_encounter(eid)
        out[eid] = enc
    return out


_MISSION_CACHE = {}


def _mission_for(enc):
    mid = (enc or {}).get("mission_id")
    if not mid:
        return None
    if mid not in _MISSION_CACHE:
        _MISSION_CACHE[mid] = MC.load_mission(mid)[0]
    return _MISSION_CACHE[mid]


def _pressure_total(enc, mission):
    try:
        return EC.total_pressure(EC.pressure_components(enc or {}, mission or {}))
    except Exception:  # noqa: BLE001
        return None


def _stats(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return {"min": None, "mean": None, "max": None, "n": 0}
    return {"min": round(min(vals), 3),
            "mean": round(sum(vals) / len(vals), 3),
            "max": round(max(vals), 3), "n": len(vals)}


# ---------------------------------------------------------------------------
# inspect-encounter-pack
# ---------------------------------------------------------------------------
def _summary_data(catalog, encounters):
    entries = catalog.get("encounters") or {}

    biome = Counter()
    m_arch = Counter()
    e_arch = Counter()
    profile = Counter()
    band = Counter()

    missions = set()
    pressures = []
    first_pressures = []
    beta_completed = 0
    beta_missing = 0
    balance_classified = 0
    balance_missing = 0
    invalid = 0

    for eid, enc in encounters.items():
        if enc is None:
            invalid += 1
            continue
        if EC.missing_required_fields(enc):
            invalid += 1
        biome[enc.get("biome_family") or "(unset)"] += 1
        m_arch[enc.get("mission_archetype") or "(unset)"] += 1
        e_arch[enc.get("encounter_archetype") or "(unset)"] += 1
        profile[enc.get("encounter_profile") or "(unset)"] += 1
        band[enc.get("difficulty_band") or "(unset)"] += 1
        if enc.get("mission_id"):
            missions.add(enc["mission_id"])

        mission = _mission_for(enc)
        pressures.append(_pressure_total(enc, mission))
        try:
            pm = EC.pacing_metrics(enc, mission or {})
            first_pressures.append(pm.get("distance_from_spawn_to_first_pressure"))
        except Exception:  # noqa: BLE001
            first_pressures.append(None)

        beta = _load_json(_beta_report_path(eid))
        if beta is None:
            beta_missing += 1
        elif beta.get("completed") is True:
            beta_completed += 1

        bal = _load_json(_balance_report_path(eid))
        if bal is None:
            balance_missing += 1
        elif (entries.get(eid) or {}).get("balance_status") == "classified":
            balance_classified += 1

    def _ordered(counter, taxonomy):
        out = OrderedDict()
        for key in taxonomy:
            out[key] = counter.get(key, 0)
        for key in sorted(counter):
            if key not in out:
                out[key] = counter[key]
        return out

    return {
        "total_encounters": len(encounters),
        "total_missions_covered": len(missions),
        "by_biome_family": _ordered(biome, MC.BIOME_FAMILIES),
        "by_mission_archetype": _ordered(m_arch, MC.MISSION_ARCHETYPES),
        "by_encounter_archetype": _ordered(e_arch, EC.ENCOUNTER_ARCHETYPES),
        "by_encounter_profile": _ordered(profile, EC.ENCOUNTER_PROFILES),
        "by_difficulty_band": _ordered(band, EC.DIFFICULTY_BANDS),
        "pressure_score": _stats(pressures),
        "first_pressure_cm": _stats(first_pressures),
        "playtest_beta_completed": beta_completed,
        "playtest_beta_report_missing": beta_missing,
        "balance_classified": balance_classified,
        "balance_report_missing": balance_missing,
        "invalid_encounters": invalid,
    }


def _print_counter(title, mapping, indent="    "):
    print("  %s" % title)
    if not mapping:
        print("%s(none)" % indent)
        return
    for key, n in mapping.items():
        print("%s%-30s %d" % (indent, key, n))


def cmd_inspect_pack(pack, catalog, encounters, strict):
    data = _summary_data(catalog, encounters)

    print("=" * 72)
    print("INSPECT-ENCOUNTER-PACK  pack=%s  (%d encounter(s) over %d mission(s))" % (
        pack, data["total_encounters"], data["total_missions_covered"]))
    print("=" * 72)
    _print_counter("Encounters per biome_family:", data["by_biome_family"])
    _print_counter("Encounters per mission_archetype:", data["by_mission_archetype"])
    _print_counter("Encounters per encounter_archetype:", data["by_encounter_archetype"])
    _print_counter("Encounters per profile:", data["by_encounter_profile"])
    _print_counter("Encounters per difficulty band:", data["by_difficulty_band"])
    ps, fp = data["pressure_score"], data["first_pressure_cm"]
    print("  Pressure score:")
    print("    min/mean/max                        %s / %s / %s (n=%d)" % (
        ps["min"], ps["mean"], ps["max"], ps["n"]))
    print("  Pacing first pressure (cm):")
    print("    min/mean                            %s / %s (n=%d)" % (
        fp["min"], fp["mean"], fp["n"]))
    print("  Evidence:")
    print("    playtest beta completed             %d" % data["playtest_beta_completed"])
    print("    playtest beta report missing        %d" % data["playtest_beta_report_missing"])
    print("    balance classified                  %d" % data["balance_classified"])
    print("    balance report missing              %d" % data["balance_report_missing"])
    print("    invalid encounters                  %d" % data["invalid_encounters"])

    meta = build_meta(
        command="inspect-encounter-pack", pack=pack, strict=strict,
        status="ok", record_count=data["total_encounters"],
        input_spec_hash=catalog_content_hash(catalog),
        output_manifest_hash=hash_obj(data),
        extra={"summary": data},
    )
    report = {"pack": pack, "summary": data, "meta": meta}
    _write_report("inspect_encounter_pack", "inspect_encounter_pack_report.json", report)
    return 0


# ---------------------------------------------------------------------------
# inspect-encounter (single-encounter dossier)
# ---------------------------------------------------------------------------
def cmd_inspect_encounter(pack, catalog, encounter_id, strict):
    enc, err = EC.load_encounter(encounter_id)
    entry = (catalog.get("encounters") or {}).get(encounter_id)
    if enc is None and entry is None:
        sys.stderr.write("encounter not found in catalog or on disk: %s (%s)\n"
                         % (encounter_id, err))
        return 2

    e = enc or {}
    beta = _load_json(_beta_report_path(encounter_id))
    balance = _load_json(_balance_report_path(encounter_id))

    print("=" * 72)
    print("INSPECT-ENCOUNTER  %s  (pack=%s)" % (encounter_id, pack))
    print("=" * 72)
    if enc is None:
        print("  WARNING: encounter.json missing/unparseable — catalog record only")

    for label, key in (("mission_id", "mission_id"),
                       ("biome_family", "biome_family"),
                       ("mission_archetype", "mission_archetype"),
                       ("encounter_archetype", "encounter_archetype"),
                       ("encounter_profile", "encounter_profile"),
                       ("difficulty_band", "difficulty_band"),
                       ("pressure_budget", "pressure_budget"),
                       ("seed", "seed")):
        print("  %-22s %s" % (label, e.get(key)))

    print("  %-22s %d group(s)" % ("spawn_groups", len(e.get("spawn_groups") or [])))
    for g in e.get("spawn_groups") or []:
        print("      %-40s count=[%s,%s] policy=%s pressure=%s roles=%s" % (
            g.get("spawn_group_id"), g.get("count_min"), g.get("count_max"),
            g.get("spawn_policy"), g.get("pressure_value"), g.get("role_tags")))
    print("  %-22s spawn=%d cover=%d patrol=%d ambush=%d" % (
        "anchors", len(e.get("spawn_anchors") or []), len(e.get("cover_anchors") or []),
        len(e.get("patrol_anchors") or []), len(e.get("ambush_anchors") or [])))
    print("  %-22s safe=%d danger=%d hazard=%d resource=%d" % (
        "zones", len(e.get("safe_zones") or []), len(e.get("danger_zones") or []),
        len(e.get("hazard_zones") or []), len(e.get("resource_nodes") or [])))
    print("  %-22s approach=%d escape=%d" % (
        "routes", len(e.get("approach_routes") or []), len(e.get("escape_routes") or [])))
    print("  %-22s %s" % ("pacing_target", e.get("pacing_target")))

    mission = _mission_for(e)
    total = _pressure_total(e, mission)
    print("  %-22s total=%s recomputed_band=%s" % (
        "pressure(recomputed)", total,
        EC.classify_band(total) if total is not None else None))

    if beta is None:
        print("  %-22s (no beta report)" % "playtest_beta")
    else:
        print("  %-22s completed=%s band=%s" % (
            "playtest_beta", beta.get("completed"),
            (beta.get("pressure") or {}).get("band")))
    if balance is None:
        print("  %-22s (no balance report)" % "balance")
    else:
        print("  %-22s band=%s pressure=%s pacing=%s confidence=%s invalid_reason=%s" % (
            "balance", balance.get("difficulty_band"), balance.get("pressure_score"),
            balance.get("pacing_score"), balance.get("completion_confidence"),
            balance.get("invalid_reason")))

    dossier = {
        "encounter_id": encounter_id,
        "encounter": e,
        "catalog_entry": entry,
        "playtest_beta_report": beta,
        "balance_report": balance,
    }
    meta = build_meta(
        command="inspect-encounter", pack=pack, strict=strict,
        status="ok", record_count=1,
        input_spec_hash=hash_obj(e),
        extra={"encounter_id": encounter_id},
    )
    out = {"pack": pack, "encounter": dossier, "meta": meta}
    _write_report("inspect_encounter_pack",
                  "inspect_encounter_%s_report.json" % encounter_id, out)
    return 0


# ---------------------------------------------------------------------------
# diagnose-encounter-pack
# ---------------------------------------------------------------------------
# Ordered buckets: (label, FailureCode). Every problem lands in one or more
# buckets via _classify_encounter below. A clean pack yields zero problems.
DIAGNOSE_BUCKETS = (
    ("missing-encounter", FailureCode.ENCOUNTER_CONTRACT_FAILURE),
    ("missing-field", FailureCode.ENCOUNTER_CONTRACT_FAILURE),
    ("band-invalid", FailureCode.ENCOUNTER_PRESSURE_FAILURE),
    ("over-budget", FailureCode.ENCOUNTER_PRESSURE_FAILURE),
    ("route-blocked", FailureCode.ENCOUNTER_ROUTE_FAILURE),
    ("playtest-beta-report-missing", FailureCode.PLAYTEST_BETA_REPORT_FAILURE),
    ("playtest-beta-not-completed", FailureCode.PLAYTEST_BETA_COMPLETION_FAILURE),
    ("balance-report-missing", FailureCode.BALANCE_REPORT_FAILURE),
    ("balance-unclassified", FailureCode.BALANCE_REPORT_FAILURE),
)


def _classify_encounter(eid, enc, entry):
    """Re-check one encounter cheaply. Return list of (bucket, detail)."""
    problems = []

    if enc is None:
        problems.append(("missing-encounter", "encounter.json missing or unparseable"))
        return problems  # nothing else is trustworthy without an encounter

    missing = EC.missing_required_fields(enc)
    if missing:
        problems.append(("missing-field",
                         "missing required field(s): %s" % ", ".join(missing)))

    band = enc.get("difficulty_band")
    if band not in EC.DIFFICULTY_BANDS or band == "invalid":
        problems.append(("band-invalid", "difficulty_band=%r" % band))

    mission = _mission_for(enc)
    total = _pressure_total(enc, mission)
    budget = EC.PROFILE_PRESSURE_BUDGETS.get(enc.get("encounter_profile"))
    if total is None or budget is None or total > budget:
        problems.append(("over-budget",
                         "recomputed pressure %s vs budget %s (profile=%r)" % (
                             total, budget, enc.get("encounter_profile"))))

    blockage = PB.route_blockage_ratio(enc, mission)
    max_block = (enc.get("pacing_target") or {}).get("max_route_blockage_ratio")
    if blockage is None:
        problems.append(("route-blocked", "no usable mission required_route to check"))
    elif blockage >= 1.0 or not isinstance(max_block, (int, float)) \
            or blockage > max_block:
        problems.append(("route-blocked",
                         "route_blockage_ratio=%s (max=%s)" % (blockage, max_block)))

    beta = _load_json(_beta_report_path(eid))
    if beta is None:
        problems.append(("playtest-beta-report-missing",
                         "no beta report at %s" % _beta_report_path(eid)))
    elif beta.get("completed") is not True:
        problems.append(("playtest-beta-not-completed",
                         "beta report completed=%r" % beta.get("completed")))

    balance = _load_json(_balance_report_path(eid))
    if balance is None:
        problems.append(("balance-report-missing",
                         "no balance report at %s" % _balance_report_path(eid)))
    else:
        bal_band = balance.get("difficulty_band")
        unclassified = (bal_band not in EC.DIFFICULTY_BANDS or bal_band == "invalid"
                        or balance.get("invalid_reason") is not None
                        or (entry or {}).get("balance_status") != "classified")
        if unclassified:
            problems.append(("balance-unclassified",
                             "balance band=%r invalid_reason=%r catalog_status=%r" % (
                                 bal_band, balance.get("invalid_reason"),
                                 (entry or {}).get("balance_status"))))

    return problems


def cmd_diagnose(pack, catalog, encounters, strict):
    entries = catalog.get("encounters") or {}
    found = {label: [] for label, _ in DIAGNOSE_BUCKETS}

    for eid, enc in encounters.items():
        for bucket, detail in _classify_encounter(eid, enc, entries.get(eid)):
            found[bucket].append((eid, detail))

    total_problems = sum(len(v) for v in found.values())

    print("=" * 72)
    print("DIAGNOSE-ENCOUNTER-PACK  pack=%s  (%d encounter(s), %d problem(s))" % (
        pack, len(encounters), total_problems))
    print("=" * 72)
    for label, code in DIAGNOSE_BUCKETS:
        items = found[label]
        if not items:
            print("  [%-28s] (%s)  none" % (label, code))
            continue
        print("  [%-28s] (%s)  %d" % (label, code, len(items)))
        for eid, detail in items:
            print("      %-52s %s" % (eid, detail))

    if total_problems == 0:
        print("\n  No problems found. GREEN.")

    status = "ok" if total_problems == 0 else "fail"
    buckets_report = {
        label: {"code": code, "count": len(found[label]),
                "encounters": [eid for eid, _ in found[label]],
                "details": ["%s: %s" % (eid, det) for eid, det in found[label]]}
        for label, code in DIAGNOSE_BUCKETS
    }
    meta = build_meta(
        command="diagnose-encounter-pack", pack=pack, strict=strict,
        status=status, failure_count=total_problems,
        record_count=len(encounters),
        input_spec_hash=catalog_content_hash(catalog),
        extra={"total_problems": total_problems, "buckets": buckets_report},
    )
    report = {"pack": pack, "total_problems": total_problems,
              "buckets": buckets_report, "meta": meta}
    _write_report("diagnose_encounter_pack", "diagnose_encounter_pack_report.json", report)

    return 0 if total_problems == 0 else 1


# ---------------------------------------------------------------------------
# report writer
# ---------------------------------------------------------------------------
def _write_report(command_dir, filename, report):
    out_dir = REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / command_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    with path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    try:
        shown = path.relative_to(Path.cwd())
    except ValueError:
        shown = path
    print("\n[report] -> %s" % shown)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Inspect / diagnose the WorldForge generated encounter pack.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--encounter", default=None, help="Inspect a single encounter by id")
    ap.add_argument("--diagnose", action="store_true",
                    help="Classify encounter problems into EncounterForge buckets")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    catalog = load_encounter_catalog(REPO_ROOT)

    if args.encounter:
        return cmd_inspect_encounter(args.pack, catalog, args.encounter, strict)

    encounters = _load_encounters(catalog)
    if args.diagnose:
        return cmd_diagnose(args.pack, catalog, encounters, strict)
    return cmd_inspect_pack(args.pack, catalog, encounters, strict)


if __name__ == "__main__":
    sys.exit(main())
