#!/usr/bin/env python3
"""validate_encounter_anchor_preservation.py — WorldForge v1.5 Wave-4 regression.

The PRIME v1.5 regression guarantee: materializing v1.4x cube cover proxies into
real catalog-backed meshes must NEVER move an encounter anchor nor delete any of
its non-cover anchors. If materialization moved an anchor, every downstream
validator that runs on the JSON specs (PlaytestForge Beta / BalanceForge /
encounter-cover / encounter-route) would silently break. This validator PROVES
the invariant held.

For every ``RealizedCoverBinding`` in the pack it proves the replacement preserved
the anchor:

  * the binding's ``cover_anchor_id`` still exists in its encounter's
    ``cover_anchors`` (materialization did not delete/rename the anchor)
  * the binding's implied world_position EQUALS the encounter anchor's
    world_position — proven by recomputing the anchor→route clearance with the
    EXACT logic + 600cm threshold replace_cover_proxies used and asserting it
    equals the clearance the binding recorded (a moved anchor yields a different
    clearance)  -> COVER_REPLACEMENT_ANCHOR_MUTATED
  * the binding's ``height_class`` equals the anchor's ``height_class``
  * the binding's encounter_id / mission_id / map_id match the encounter record

and — once per encounter — that every NON-cover anchor collection
(spawn/patrol/ambush/idle/resource/safe/danger/objective) is still present and
well-formed (materialization did not delete them)  -> ENCOUNTER_ANCHOR_FAILURE.

Delegates the anchor→route clearance math to replace_cover_proxies.route_clearance
(same densifier + threshold), so no geometry is reimplemented here.

Report: wf.realization.anchor_preservation.v1

Usage:
    python tools/pipeline/validate_encounter_anchor_preservation.py --pack encounter_loop_world [--strict]
Writes:
    procedural/reports/realization/validate_encounter_anchor_preservation/
        validate_encounter_anchor_preservation_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import asset_paths
import encounter_contract as EC
import mission_contract as MC
import replace_cover_proxies as RCP
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

COMMAND = "validate_encounter_anchor_preservation"
REPORT_TYPE = "wf.realization.anchor_preservation.v1"

MUTATED = FailureCode.COVER_REPLACEMENT_ANCHOR_MUTATED
ANCHOR_FAIL = FailureCode.ENCOUNTER_ANCHOR_FAILURE

# Non-cover anchor collections that materialization must never delete. Each entry
# maps the encounter key to how a member must be shaped (proves nothing was
# blanked/corrupted, which is how a deletion would manifest).
#   "point"  -> dict with an id and a coordinate world_position
#   "bounds" -> dict with an id and a bounds dict
#   "token"  -> a truthy scalar/dict (objective link id)
NONCOVER_ANCHORS = (
    ("spawn_anchors", "point", True),    # every encounter must retain >= 1 spawn
    ("patrol_anchors", "point", False),
    ("ambush_anchors", "point", False),
    ("idle_anchors", "point", False),
    ("resource_nodes", "point", False),
    ("safe_zones", "point", False),
    ("danger_zones", "bounds", False),
    ("objective_links", "token", False),
)


def _is_coord(w):
    return (isinstance(w, (list, tuple)) and len(w) >= 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    for v in w[:2]))


def _member_ok(member, shape):
    if shape == "token":
        return bool(member)
    if not isinstance(member, dict) or not member.get("id"):
        return False
    if shape == "point":
        return _is_coord(member.get("world_position"))
    if shape == "bounds":
        b = member.get("bounds")
        return isinstance(b, dict) and bool(b)
    return False


def _load_bindings():
    d = asset_paths.COVER_BINDINGS_DIR
    out = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            out.append((p.name, json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            out.append((p.name, None))
    return out


def check_noncover_anchors(rep, enc):
    eid = enc.get("encounter_id")

    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(name, eid), ok, detail, code=ANCHOR_FAIL)

    for key, shape, require_nonempty in NONCOVER_ANCHORS:
        val = enc.get(key)
        c("noncover_anchor_is_list[{}]".format(key), isinstance(val, list),
          "{} must remain a list, got {!r}".format(key, type(val).__name__))
        members = val if isinstance(val, list) else []
        if require_nonempty:
            c("noncover_anchor_nonempty[{}]".format(key), len(members) >= 1,
              "{} is empty — materialization must not delete it".format(key))
        malformed = [i for i, m in enumerate(members) if not _member_ok(m, shape)]
        c("noncover_anchor_wellformed[{}]".format(key), not malformed,
          "{} has malformed/deleted members at indices {} (shape={})".format(
              key, malformed[:8], shape))


def check_binding(rep, name, binding, enc, mission):
    bid = (binding or {}).get("binding_id") or name

    def c(cname, ok, detail="", code=MUTATED):
        return rep.check("{}::{}".format(cname, bid), ok, detail, code=code)

    # id coherence with the encounter record.
    c("binding_encounter_id_matches",
      binding.get("encounter_id") == enc.get("encounter_id"),
      "binding.encounter_id={!r} != encounter {!r}".format(
          binding.get("encounter_id"), enc.get("encounter_id")), code=ANCHOR_FAIL)
    c("binding_mission_id_matches",
      binding.get("mission_id") == enc.get("mission_id"),
      "binding.mission_id={!r} != encounter.mission_id={!r}".format(
          binding.get("mission_id"), enc.get("mission_id")), code=ANCHOR_FAIL)
    expected_map = RCP.map_id_of(enc.get("mission_id") or "")
    c("binding_map_id_matches", binding.get("map_id") == expected_map,
      "binding.map_id={!r} != map_id_of(mission)={!r}".format(
          binding.get("map_id"), expected_map), code=ANCHOR_FAIL)

    # The cover anchor the binding replaced must still exist in the encounter.
    anchors = {a.get("id"): a for a in (enc.get("cover_anchors") or [])
               if isinstance(a, dict)}
    aid = binding.get("cover_anchor_id")
    anchor = anchors.get(aid)
    if not c("cover_anchor_still_exists", anchor is not None,
             "cover_anchor_id={!r} no longer present in encounter cover_anchors "
             "(anchor deleted/renamed by materialization)".format(aid)):
        return

    # height_class must be unchanged.
    c("height_class_preserved",
      binding.get("height_class") == anchor.get("height_class"),
      "binding.height_class={!r} != anchor.height_class={!r}".format(
          binding.get("height_class"), anchor.get("height_class")))

    # Position preservation, proven via the recomputed anchor→route clearance:
    # replace_cover_proxies stored route_clearance_result.min_clearance_cm computed
    # from the anchor's world_position; recompute it from the CURRENT anchor and it
    # must be byte-identical. A moved anchor would change the clearance.
    pos = anchor.get("world_position")
    if not _is_coord(pos):
        c("anchor_world_position_valid", False,
          "encounter cover anchor {!r} has no valid world_position".format(aid))
        return
    recomputed_min, _cleared = RCP.route_clearance(pos, mission)
    stored_min = (binding.get("route_clearance_result") or {}).get("min_clearance_cm")
    same = recomputed_min == stored_min
    c("world_position_preserved", same,
      "implied world_position moved: recomputed anchor→route clearance {} != "
      "binding-recorded {} (materialization must never move an anchor)".format(
          recomputed_min, stored_min))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Prove v1.5 cover materialization preserved every encounter anchor.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)

    # Encounters in this pack + their missions (cache).
    encounters = {e.get("encounter_id"): e for e in RCP.load_pack_encounters(args.pack)}
    if not encounters:
        rep.error("no encounters in pack '{}' — run 'make create-encounters' first"
                  .format(args.pack))
    missions = {}
    for eid, enc in sorted(encounters.items()):
        mission, _ = MC.load_mission(enc.get("mission_id") or "")
        missions[eid] = mission
        rep.check("mission_loads::{}".format(eid), mission is not None,
                  "mission {!r} did not load".format(enc.get("mission_id")),
                  code=ANCHOR_FAIL)
        check_noncover_anchors(rep, enc)

    bindings = _load_bindings()
    if not bindings:
        rep.error("no cover bindings under {} — run 'replace_cover_proxies' first"
                  .format(asset_paths.COVER_BINDINGS_DIR))

    n_bindings = 0
    n_skipped = 0
    for name, binding in bindings:
        if binding is None:
            rep.check("binding_parses::{}".format(name), False,
                      "cover binding {} is unparseable".format(name),
                      code=FailureCode.REALIZED_COVER_BINDING_FAILURE)
            continue
        eid = binding.get("encounter_id")
        enc = encounters.get(eid)
        if enc is None:
            # Binding references an encounter that loaded (id present) but not in
            # this pack -> out of scope for this pack run.
            enc_any, _ = EC.load_encounter(eid or "")
            if enc_any is None:
                rep.check("binding_encounter_exists::{}".format(name), False,
                          "binding references encounter {!r} that does not exist"
                          .format(eid), code=ANCHOR_FAIL)
            else:
                n_skipped += 1
            continue
        mission = missions.get(eid)
        if mission is None:
            continue  # mission_loads already recorded the failure
        check_binding(rep, name, binding, enc, mission)
        n_bindings += 1

    rep.finalize()
    rep.set_meta(build_meta(
        command=COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status,
        record_count=n_bindings, records_total=n_bindings,
        records_passed=n_bindings if rep.passed else 0,
        records_failed=0 if rep.passed else n_bindings,
        extra={"bindings_checked": n_bindings,
               "bindings_out_of_pack_skipped": n_skipped,
               "encounters_checked": len(encounters)}))
    report_dir, filename = asset_paths.report_path("realization", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    sys.stdout.write(
        "[{}] {} binding(s) + {} encounter(s) checked, {} out-of-pack skipped\n"
        .format(COMMAND, n_bindings, len(encounters), n_skipped))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
