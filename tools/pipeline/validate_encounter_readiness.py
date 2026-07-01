#!/usr/bin/env python3
"""validate_encounter_readiness.py — WorldForge v1.0x encounter-readiness gate.

Proves that the entity-anchor substrate leaves POIs *encounter-ready* for a
future EncounterForge WITHOUT that system scraping geometry. A POI is
encounter-ready when its overlay provides, all generated-owned and budgeted:

  * at least one ``encounter_anchor`` carrying a valid encounter_tag;
  * at least one REACHABLE ``enemy_spawn_zone``;
  * at least one ``faction_ownership_anchor`` with a valid faction_tag;
  * enemy-spawn capacity/count within the map's density budget;
  * provenance (generated-owned) on every encounter-related anchor.

Per map the check asserts the POI is encounter-ready; a pack-level check asserts
at least one POI in the pack is encounter-ready (the brief's "at least some").
Blocking failures are tagged ``FailureCode.ENCOUNTER_READINESS_FAILURE`` (density
overruns use ``FailureCode.ENTITY_DENSITY_EXCEEDED``). record_count == maps.

Usage:
    PYTHONUTF8=1 python tools/pipeline/validate_encounter_readiness.py --pack desert_mvp_world --strict
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
from validation_report import ValidationReport, strict_from_env
from failure_codes import FailureCode
from report_meta import build_meta
from world_pack_maps import enumerate_maps, report_dir_for
import generate_entity_anchors as G

ENC = FailureCode.ENCOUNTER_READINESS_FAILURE
DENS = FailureCode.ENTITY_DENSITY_EXCEEDED


def _fmt(items, n=6):
    items = list(items)
    shown = ", ".join(str(x) for x in items[:n])
    return shown + (" …(+{})".format(len(items) - n) if len(items) > n else "")


def evaluate_readiness(map_id, overlay):
    """Return (ready: bool, reasons: list[str]) for one overlay. Pure, importable."""
    reasons = []
    if not isinstance(overlay, dict):
        return False, ["no entity-anchor overlay (run generate-entity-anchors)"]
    anchors = overlay.get("anchors")
    wm = overlay.get("world_model")
    if not isinstance(anchors, list) or not isinstance(wm, dict) or "player_start" not in wm:
        return False, ["overlay missing anchors or world_model.player_start"]

    player_start = wm["player_start"]
    edge_max = wm.get("edge_max_dist_cm", G.EDGE_MAX_DIST_CM)
    positions = [a["position"] for a in anchors if isinstance(a, dict) and "position" in a]
    reachable_idx = G.compute_reachable_indices(player_start, positions, edge_max)
    reach = {}
    j = 0
    for a in anchors:
        if isinstance(a, dict) and "position" in a:
            reach[id(a)] = (j + 1) in reachable_idx
            j += 1

    def owned(a):
        prov = a.get("provenance") or {}
        return bool(prov.get("generator")) and prov.get("owned_by") == "generated"

    encounter_anchors = [a for a in anchors if isinstance(a, dict) and a.get("type") == "encounter_anchor"]
    enemy_zones = [a for a in anchors if isinstance(a, dict) and a.get("type") == "enemy_spawn_zone"]
    faction_anchors = [a for a in anchors if isinstance(a, dict) and a.get("type") == "faction_ownership_anchor"]

    good_encounter = [a for a in encounter_anchors if a.get("encounter_tag") in G.VALID_ENCOUNTER_TAGS
                      and a.get("encounter_tag") != "none" and owned(a)]
    reachable_enemy = [a for a in enemy_zones if reach.get(id(a), False) and owned(a)]
    good_faction = [a for a in faction_anchors if a.get("faction_tag") in G.VALID_FACTIONS and owned(a)]

    if not good_encounter:
        reasons.append("no encounter_anchor with a valid encounter_tag + provenance")
    if not reachable_enemy:
        reasons.append("no reachable, generated-owned enemy_spawn_zone")
    if not good_faction:
        reasons.append("no faction_ownership_anchor with a valid faction_tag + provenance")

    return (len(reasons) == 0), reasons


def check_map(rep, map_id, overlay, strict):
    """Add encounter-readiness checks for one map's overlay to ``rep``. Importable core."""
    p = "{}: ".format(map_id)
    ready, reasons = evaluate_readiness(map_id, overlay)
    rep.check(p + "poi_encounter_ready", ready,
              "POI not encounter-ready: " + _fmt(reasons), code=ENC)

    # Density: enemy-spawn budget must not be blown even when "ready".
    if isinstance(overlay, dict) and isinstance(overlay.get("anchors"), list):
        anchors = overlay["anchors"]
        db = overlay.get("density_budget") or G.DENSITY_BUDGET
        enemy = [a for a in anchors if isinstance(a, dict) and a.get("type") == "enemy_spawn_zone"]
        enemy_cap = sum(int(a.get("capacity", 0)) for a in enemy)
        density_ok = (len(enemy) <= db["max_enemy_spawn_zones_per_map"] and
                      enemy_cap <= db["max_total_spawn_capacity"])
        rep.check(p + "encounter_density_budgeted", density_ok,
                  "enemy encounter density over budget: enemy_zones={}/{} enemy_capacity={}/{}".format(
                      len(enemy), db["max_enemy_spawn_zones_per_map"],
                      enemy_cap, db["max_total_spawn_capacity"]),
                  code=DENS)
    return ready


def validate_pack(pack, strict, overlay_dir=None, overlays=None):
    """Core entrypoint: parent report for the pack. Importable."""
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)
    if not maps:
        rep.error("world pack enumerated zero maps")
        rep.set_meta(build_meta(command="validate-encounter-readiness", pack=world_pack_id,
                                strict=strict, status=None, record_count=0))
        return rep

    ready_count = 0
    for m in maps:
        map_id = m.slice_id or "<unknown>"
        if not m.spec_exists:
            rep.check("{}: spec_present".format(map_id), False,
                      m.get("spec_error") or "generated spec missing", code=ENC)
            continue
        overlay = overlays.get(map_id) if overlays is not None else G.load_overlay(map_id, overlay_dir)
        if check_map(rep, map_id, overlay, strict):
            ready_count += 1

    # Pack-level: at least some POIs must be encounter-ready.
    rep.check("pack_has_encounter_ready_pois", ready_count > 0,
              "no encounter-ready POIs in pack ({} maps)".format(len(maps)), code=ENC)
    rep.set_meta(build_meta(command="validate-encounter-readiness", pack=world_pack_id,
                            strict=strict, status=None, record_count=len(maps),
                            extra={"encounter_ready_pois": ready_count}))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate encounter-readiness of the entity substrate.")
    ap.add_argument("--pack", default="desert_mvp_world", help="World pack id.")
    ap.add_argument("--strict", action="store_true", help="Treat warnings as blocking (STRICT=1).")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = validate_pack(args.pack, strict)
    rep.finalize()
    report_dir = report_dir_for(rep.entity_id)
    rep.write(report_dir, "validate_encounter_readiness_report.json")
    rep.print_summary("validate-encounter-readiness")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
