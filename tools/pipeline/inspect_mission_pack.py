#!/usr/bin/env python3
"""inspect_mission_pack.py — WorldForge v1.3 MissionForge operator utility.

Read-only. Shows what the generated mission pack (or a single mission) actually
IS, and — with --diagnose — classifies every problem into the brief's Mission /
Playtest failure buckets so an operator sees which lane is red without opening 60
mission.json files. Mirrors the console/JSON-report habit of the existing
inspect_mesh_catalog.py / inspect_world_pack.py operator tools; it is NOT a
generator and NOT part of the create/validate contract. It joins three things:

    procedural/generated/worldforge_mission_catalog.json         — the catalog ledger
    procedural/generated/missions/<mission_id>/mission.json      — per-mission records
    procedural/reports/missions/playtest/<mission_id>.json       — playtest evidence

Three modes (brief §Agent 7 / operator):
    inspect-mission-pack   default: human summary + JSON report, exit 0
    inspect-mission        --mission <id>: full per-mission dossier, exit 0 (2 if unknown)
    diagnose-mission-pack  --diagnose: classify problems into MISSION_*/PLAYTEST_*
                           buckets, exit 0 if clean, 1 if any problem (usable as a gate)

    PYTHONUTF8=1 python tools/pipeline/inspect_mission_pack.py --pack mission_loop_world
    PYTHONUTF8=1 python tools/pipeline/inspect_mission_pack.py --pack mission_loop_world --mission mission_Alien_CrystalField_Debris_Perf_01
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/inspect_mission_pack.py --pack mission_loop_world --diagnose --strict
"""

import argparse
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import mission_contract as MC  # noqa: E402
from mission_catalog import load_mission_catalog, catalog_content_hash  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta, strict_from_env, hash_obj  # noqa: E402


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------
def _playtest_report_path(mission_id):
    return REPO_ROOT / MC.MISSION_REPORTS_REL / "playtest" / (mission_id + ".json")


def _load_playtest_report(mission_id):
    p = _playtest_report_path(mission_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _mission_ids(catalog):
    """The authoritative mission id set: catalog records ∪ any dir on disk."""
    ids = set((catalog.get("missions") or {}).keys())
    root = REPO_ROOT / MC.MISSION_GENERATED_REL
    if root.is_dir():
        for sub in root.iterdir():
            if sub.is_dir() and (sub / "mission.json").is_file():
                ids.add(sub.name)
    return sorted(ids)


def _load_missions(catalog):
    """mission_id -> mission dict (from mission.json). Missing/unparseable -> None."""
    out = OrderedDict()
    for mid in _mission_ids(catalog):
        mission, _ = MC.load_mission(mid, REPO_ROOT)
        out[mid] = mission
    return out


def _mesh_dep_families(mission):
    md = (mission or {}).get("mesh_dependencies") or {}
    return list(md.get("required_families") or [])


def _megascans_dressing(mission):
    md = (mission or {}).get("mesh_dependencies") or {}
    dr = md.get("megascans_dressing")
    if not dr:
        return None
    return dr if isinstance(dr, str) else json.dumps(dr, sort_keys=True, ensure_ascii=False)


def _has_state_change(mission):
    """True if any state_key declares a non-zero delta (a real state transition)."""
    for sk in (mission or {}).get("state_keys") or []:
        if isinstance(sk, dict):
            try:
                if abs(float(sk.get("delta") or 0.0)) > 0.0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


# ---------------------------------------------------------------------------
# inspect-mission-pack
# ---------------------------------------------------------------------------
def _summary_data(catalog, missions):
    entries = catalog.get("missions") or {}

    archetype = Counter()
    biome = Counter()
    playtest_status = Counter()
    validation_status = Counter()

    with_rewards = 0
    with_save_load = 0
    with_mesh_deps = 0
    mesh_families = set()
    megascans = set()
    playtest_present = 0
    playtest_missing = 0

    for mid, mission in missions.items():
        m = mission or {}
        archetype[m.get("mission_archetype") or "(unset)"] += 1
        biome[m.get("biome_family") or "(unset)"] += 1

        ce = entries.get(mid) or {}
        playtest_status[ce.get("playtest_status") or "(unset)"] += 1
        validation_status[ce.get("validation_status") or "(unset)"] += 1

        if m.get("reward_outputs"):
            with_rewards += 1
        sl = m.get("save_load_contract") or {}
        if sl.get("persist_keys"):
            with_save_load += 1
        fams = _mesh_dep_families(m)
        if fams:
            with_mesh_deps += 1
        for f in fams:
            mesh_families.add(f)
        dr = _megascans_dressing(m)
        if dr:
            megascans.add(dr)

        if _playtest_report_path(mid).is_file():
            playtest_present += 1
        else:
            playtest_missing += 1

    def _ordered(counter, taxonomy):
        out = OrderedDict()
        for key in taxonomy:
            out[key] = counter.get(key, 0)
        for key in sorted(counter):
            if key not in out:
                out[key] = counter[key]
        return out

    return {
        "total_missions": len(missions),
        "by_archetype": _ordered(archetype, MC.MISSION_ARCHETYPES),
        "by_biome_family": _ordered(biome, MC.BIOME_FAMILIES),
        "by_playtest_status": OrderedDict(sorted(playtest_status.items())),
        "by_validation_status": OrderedDict(sorted(validation_status.items())),
        "missions_with_rewards": with_rewards,
        "missions_with_save_load": with_save_load,
        "missions_with_mesh_dependencies": with_mesh_deps,
        "distinct_mesh_families": sorted(mesh_families),
        "distinct_mesh_family_count": len(mesh_families),
        "distinct_megascans_dressing": sorted(megascans),
        "distinct_megascans_dressing_count": len(megascans),
        "playtest_report_present": playtest_present,
        "playtest_report_missing": playtest_missing,
    }


def _print_counter(title, mapping, indent="    "):
    print("  %s" % title)
    if not mapping:
        print("%s(none)" % indent)
        return
    for key, n in mapping.items():
        print("%s%-30s %d" % (indent, key, n))


def cmd_inspect_pack(pack, catalog, missions, strict):
    data = _summary_data(catalog, missions)

    print("=" * 72)
    print("INSPECT-MISSION-PACK  pack=%s  (%d mission(s))" % (pack, data["total_missions"]))
    print("=" * 72)
    _print_counter("Missions per archetype:", data["by_archetype"])
    _print_counter("Missions per biome_family:", data["by_biome_family"])
    _print_counter("Playtest status:", data["by_playtest_status"])
    _print_counter("Validation status:", data["by_validation_status"])
    print("  Composition:")
    print("    missions with rewards               %d" % data["missions_with_rewards"])
    print("    missions with save-load contract    %d" % data["missions_with_save_load"])
    print("    missions with mesh dependencies     %d" % data["missions_with_mesh_dependencies"])
    print("    distinct mesh families consumed     %d" % data["distinct_mesh_family_count"])
    if data["distinct_mesh_families"]:
        print("      %s" % ", ".join(data["distinct_mesh_families"]))
    print("    distinct Megascans dressing         %d" % data["distinct_megascans_dressing_count"])
    if data["distinct_megascans_dressing"]:
        print("      %s" % ", ".join(data["distinct_megascans_dressing"]))
    print("  Playtest evidence:")
    print("    playtest report present             %d" % data["playtest_report_present"])
    print("    playtest report missing             %d" % data["playtest_report_missing"])

    meta = build_meta(
        command="inspect-mission-pack", pack=pack, strict=strict,
        status="ok", record_count=data["total_missions"],
        input_spec_hash=catalog_content_hash(catalog),
        output_manifest_hash=hash_obj(data),
        extra={"summary": data},
    )
    report = {"pack": pack, "summary": data, "meta": meta}
    _write_report("inspect_mission_pack", "inspect_mission_pack_report.json", report)
    return 0


# ---------------------------------------------------------------------------
# inspect-mission (single-mission dossier)
# ---------------------------------------------------------------------------
def cmd_inspect_mission(pack, catalog, mission_id, strict):
    mission, err = MC.load_mission(mission_id, REPO_ROOT)
    entry = (catalog.get("missions") or {}).get(mission_id)
    if mission is None and entry is None:
        sys.stderr.write("mission not found in catalog or on disk: %s (%s)\n" % (mission_id, err))
        return 2

    m = mission or {}
    print("=" * 72)
    print("INSPECT-MISSION  %s  (pack=%s)" % (mission_id, pack))
    print("=" * 72)
    if mission is None:
        print("  WARNING: mission.json missing/unparseable — showing catalog record only")

    print("  %-22s %s" % ("archetype", m.get("mission_archetype")))
    print("  %-22s %s" % ("biome_family", m.get("biome_family")))

    src = m.get("source_map")
    if isinstance(src, dict):
        print("  %-22s slice=%s map=%s pack=%s" % (
            "source_map", src.get("slice_id"), src.get("world_pack_map"), src.get("world_pack_id")))
    else:
        print("  %-22s %s" % ("source_map", src))

    start = m.get("start_anchor") or {}
    print("  %-22s id=%s pos=%s valid_spawn=%s" % (
        "start_anchor", start.get("id"), start.get("world_position"), start.get("valid_spawn")))
    poi = m.get("primary_poi") or {}
    print("  %-22s id=%s class=%s anchor=%s" % (
        "primary_poi", poi.get("id"), poi.get("poi_class"), poi.get("gameplay_anchor")))

    route = m.get("required_route") or {}
    print("  %-22s length_cm=%s avoids_hazards=%s (%d waypoint(s))" % (
        "required_route", route.get("length_cm"), route.get("avoids_hazards"),
        len(route.get("waypoints") or [])))

    print("  %-22s" % "state_keys")
    for sk in m.get("state_keys") or []:
        if isinstance(sk, dict):
            print("      %-16s initial=%s delta=%s expected_final=%s" % (
                sk.get("key"), sk.get("initial"), sk.get("delta"), sk.get("expected_final")))
        else:
            print("      %s" % sk)

    print("  %-22s" % "completion_conditions")
    for cc in m.get("completion_conditions") or []:
        if isinstance(cc, dict):
            print("      %-14s %s %s %s @ %s" % (
                cc.get("condition_id"), cc.get("state_key"), cc.get("operator"),
                cc.get("threshold"), cc.get("at_node")))
        else:
            print("      %s" % cc)

    print("  %-22s" % "reward_outputs")
    for r in m.get("reward_outputs") or []:
        if isinstance(r, dict):
            print("      %-14s type=%s fires_on=%s" % (
                r.get("reward_id"), r.get("reward_type"), r.get("fires_on")))
        else:
            print("      %s" % r)

    sl = m.get("save_load_contract") or {}
    print("  %-22s persist_keys=%s expect_roundtrip=%s" % (
        "save_load_contract", sl.get("persist_keys"), sl.get("expect_roundtrip")))

    pc = m.get("playtest_contract") or {}
    report = _load_playtest_report(mission_id)
    if report is None:
        report_status = "(no playtest report)"
    else:
        report_status = "completed=%s expected=%s" % (
            report.get("completed"), report.get("expected_completion"))
    print("  %-22s modes=%s expected_completion=%s max_route_cm=%s" % (
        "playtest_contract", pc.get("modes"), pc.get("expected_completion"),
        pc.get("max_route_length_cm")))
    print("  %-22s %s" % ("playtest_report", report_status))

    md = m.get("mesh_dependencies") or {}
    print("  %-22s required_families=%s" % ("mesh_dependencies", md.get("required_families")))
    print("  %-22s resolved_mesh_assets=%s" % ("", md.get("resolved_mesh_assets")))
    print("  %-22s megascans_dressing=%s" % ("", md.get("megascans_dressing")))

    dossier = {
        "mission_id": mission_id,
        "mission": m,
        "catalog_entry": entry,
        "playtest_report": report,
    }
    meta = build_meta(
        command="inspect-mission", pack=pack, strict=strict,
        status="ok", record_count=1,
        input_spec_hash=hash_obj(m),
        extra={"mission_id": mission_id},
    )
    out = {"pack": pack, "mission": dossier, "meta": meta}
    _write_report("inspect_mission_pack",
                  "inspect_mission_%s_report.json" % mission_id, out)
    return 0


# ---------------------------------------------------------------------------
# diagnose-mission-pack
# ---------------------------------------------------------------------------
# Ordered buckets: (label, FailureCode). Every mission problem lands in one or
# more buckets via _classify_mission below. A clean pack yields zero problems.
DIAGNOSE_BUCKETS = (
    ("missing-mission", FailureCode.MISSION_CONTRACT_FAILURE),
    ("missing-field", FailureCode.MISSION_CONTRACT_FAILURE),
    ("unreachable-route", FailureCode.MISSION_ROUTE_FAILURE),
    ("no-reward", FailureCode.MISSION_REWARD_FAILURE),
    ("no-state-change", FailureCode.MISSION_STATE_FAILURE),
    ("missing-mesh-dependency", FailureCode.MISSION_MESH_DEPENDENCY_FAILURE),
    ("playtest-report-missing", FailureCode.PLAYTEST_REPORT_FAILURE),
    ("playtest-not-completed", FailureCode.PLAYTEST_COMPLETION_FAILURE),
)


def _classify_mission(mission_id, mission):
    """Re-check one mission cheaply. Return list of (bucket, detail).

    A valid mission returns []. mission is the parsed mission.json (or None if
    missing/unparseable).
    """
    problems = []

    # contract: mission.json must exist and parse.
    if mission is None:
        problems.append(("missing-mission", "mission.json missing or unparseable"))
        return problems  # nothing else is trustworthy without a mission

    missing = MC.missing_required_fields(mission)
    if missing:
        problems.append(("missing-field", "missing required field(s): %s" % ", ".join(missing)))

    # route: an explicit avoids_hazards=False is an unreachable / hazard-blocked route.
    route = mission.get("required_route") or {}
    if route.get("avoids_hazards") is False:
        problems.append(("unreachable-route", "required_route.avoids_hazards is False"))

    # reward: at least one reward output.
    if not mission.get("reward_outputs"):
        problems.append(("no-reward", "no reward_outputs declared"))

    # state: at least one non-zero state delta (a real transition).
    if not _has_state_change(mission):
        problems.append(("no-state-change", "no state_key declares a non-zero delta"))

    # mesh dependency: at least one required mesh family.
    if not _mesh_dep_families(mission):
        problems.append(("missing-mesh-dependency", "no mesh_dependencies.required_families declared"))

    # playtest evidence: report present, and completed.
    report = _load_playtest_report(mission_id)
    if report is None:
        problems.append(("playtest-report-missing", "no playtest report at %s"
                         % _playtest_report_path(mission_id)))
    elif report.get("completed") is not True:
        problems.append(("playtest-not-completed",
                         "playtest report completed=%r" % report.get("completed")))

    return problems


def cmd_diagnose(pack, catalog, missions, strict):
    # bucket -> list of (mission_id, detail)
    found = {label: [] for label, _ in DIAGNOSE_BUCKETS}

    for mid, mission in missions.items():
        for bucket, detail in _classify_mission(mid, mission):
            found[bucket].append((mid, detail))

    total_problems = sum(len(v) for v in found.values())

    print("=" * 72)
    print("DIAGNOSE-MISSION-PACK  pack=%s  (%d mission(s), %d problem(s))" % (
        pack, len(missions), total_problems))
    print("=" * 72)
    for label, code in DIAGNOSE_BUCKETS:
        items = found[label]
        if not items:
            print("  [%-24s] (%s)  none" % (label, code))
            continue
        print("  [%-24s] (%s)  %d" % (label, code, len(items)))
        for mid, detail in items:
            print("      %-48s %s" % (mid, detail))

    if total_problems == 0:
        print("\n  No problems found. GREEN.")

    status = "ok" if total_problems == 0 else "fail"
    buckets_report = {
        label: {"code": code, "count": len(found[label]),
                "missions": [mid for mid, _ in found[label]],
                "details": ["%s: %s" % (mid, det) for mid, det in found[label]]}
        for label, code in DIAGNOSE_BUCKETS
    }
    meta = build_meta(
        command="diagnose-mission-pack", pack=pack, strict=strict,
        status=status, failure_count=total_problems,
        record_count=len(missions),
        input_spec_hash=catalog_content_hash(catalog),
        extra={"total_problems": total_problems, "buckets": buckets_report},
    )
    report = {"pack": pack, "total_problems": total_problems,
              "buckets": buckets_report, "meta": meta}
    _write_report("diagnose_mission_pack", "diagnose_mission_pack_report.json", report)

    return 0 if total_problems == 0 else 1


# ---------------------------------------------------------------------------
# report writer
# ---------------------------------------------------------------------------
def _write_report(command_dir, filename, report):
    out_dir = REPO_ROOT / MC.MISSION_REPORTS_REL / command_dir
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
        description="Inspect / diagnose the WorldForge generated mission pack.")
    ap.add_argument("--pack", default="mission_loop_world")
    ap.add_argument("--mission", default=None, help="Inspect a single mission by id")
    ap.add_argument("--diagnose", action="store_true",
                    help="Classify mission problems into MissionForge/PlaytestForge buckets")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    catalog = load_mission_catalog(REPO_ROOT)

    if args.mission:
        return cmd_inspect_mission(args.pack, catalog, args.mission, strict)

    missions = _load_missions(catalog)
    if args.diagnose:
        return cmd_diagnose(args.pack, catalog, missions, strict)
    return cmd_inspect_pack(args.pack, catalog, missions, strict)


if __name__ == "__main__":
    sys.exit(main())
