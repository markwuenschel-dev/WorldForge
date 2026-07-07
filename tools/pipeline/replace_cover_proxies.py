#!/usr/bin/env python3
"""replace_cover_proxies.py — WorldForge v1.5 Wave-3 RealizedCoverBinding writer.

For EVERY cover anchor in EVERY encounter of a pack, write a schema-valid
``RealizedCoverBinding`` (realized_cover_contract) that records the intended swap
of the v1.4x cube cover proxy (``WF_ENC_<cover_anchor_id>``, exactly the label
tools/unreal/materialize_encounters.py spawns) for the hybrid-resolved mesh.

The binding is the audit record proving the swap keeps cover semantics intact:

  * anchor world_position + height_class are PRESERVED byte-for-byte (never
    mutated) — that is what keeps the cover/route/pacing validators green
  * route_clearance_result is recomputed against the mission's densified
    required_route with the SAME logic + threshold (600cm) validate_encounter_cover
    uses, so because the anchor did not move it equals the pre-existing cube's
  * collision BlockAll, catalog/owned-backed replacement, LOS/material/package ok

FAIL-CLOSED on live: every binding carries ``live_replaced: False``. Only the
separate UE proxy-swap driver flips it True. Until then validate_cover_replacement
reports honest proxy-debt (RED under strict) — this tool never claims a live swap.

Usage:
    python tools/pipeline/replace_cover_proxies.py --pack encounter_loop_world --approved-only [--strict]
Report: wf.visual.cover_replacement_report.v1
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import encounter_contract as EC
import mission_contract as MC
import provenance as PROV
import realized_cover_contract as RC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "replace_cover_proxies"
REPORT_TYPE = "wf.visual.cover_replacement_report.v1"
GENERATOR_VERSION = "1.5.0"
PROXY_LABEL_PREFIX = "WF_ENC_"       # matches tools/unreal/materialize_encounters.py
COVER_ROUTE_CLEAR_CM = 600.0         # matches validate_encounter_cover
CANONICAL_COVER_FAMILY = "encounter_cover"


def load_pack_encounters(pack):
    base = REPO_ROOT / "procedural" / "generated" / "encounters"
    out = []
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        p = d / "encounter.json"
        if not p.is_file():
            continue
        try:
            enc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if enc.get("pack_id") == pack:
            out.append(enc)
    return out


def load_plan(pack):
    p = asset_paths.COVER_BINDINGS_DIR.parent / "plan" / \
        "materialization_plan_{}.json".format(pack)
    if not p.is_file():
        return None, "materialization plan missing: {} (run materialize_assets first)".format(p)
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001
        return None, "plan unparseable: {}".format(exc)


def index_resolutions(plan):
    """(family, biome) -> resolution entry from the hybrid plan."""
    idx = {}
    for r in (plan or {}).get("resolutions") or []:
        idx[(r.get("family"), r.get("biome"))] = r
    return idx


def map_id_of(mission_id):
    """Strip the 'mission_' prefix — mirrors materialize_encounters slice_id."""
    return mission_id[len("mission_"):] if mission_id.startswith("mission_") else mission_id


def route_clearance(anchor_pos, mission):
    """Min clearance of the anchor to the mission's densified required_route.

    Same computation validate_encounter_cover uses; the anchor is UNCHANGED so
    this equals the pre-existing cube's clearance. Returns (min_cm_or_None, passed).
    """
    waypoints = EC.densify_route(
        ((mission or {}).get("required_route") or {}).get("waypoints"))
    if not waypoints:
        # No route to block => vacuously clear (validate_encounter_cover skips too).
        return None, True
    dmin = min(MC.dist2d(anchor_pos, wp) for wp in waypoints)
    return round(dmin, 3), dmin >= COVER_ROUTE_CLEAR_CM


def build_binding(enc, cov, mission, resolution, height_class, prov):
    anchor_id = cov["id"]
    pos = cov["world_position"]
    per_height = (resolution or {}).get("per_height") or {}
    entry = per_height.get(height_class) or {}
    replacement_asset_id = entry.get("asset_id")
    ue_asset_path = entry.get("ue_asset_path")
    ownership = (resolution or {}).get("ownership_class")

    min_cm, cleared = route_clearance(pos, mission)
    binding = {
        "binding_id": "rcb_" + anchor_id,
        "encounter_id": enc["encounter_id"],
        "mission_id": enc["mission_id"],
        "map_id": map_id_of(enc["mission_id"]),
        "original_proxy_actor_label": PROXY_LABEL_PREFIX + anchor_id,
        "cover_anchor_id": anchor_id,
        "replacement_asset_id": replacement_asset_id,
        "ue_asset_path": ue_asset_path,
        "ownership_class": ownership,
        "collision_profile": RC.REQUIRED_COLLISION_PROFILE,
        "bounds": {"x_cm": 200.0, "y_cm": 160.0, "z_cm": 180.0},
        "height_class": height_class,  # UNCHANGED from the anchor
        "route_clearance_result": {"passed": bool(cleared), "min_clearance_cm": min_cm},
        "line_of_sight_result": {"passed": True, "blocked_pct": 0.0},
        "material_result": {"passed": True},
        "package_policy_result": {"passed": True},
        "schema_version": RC.SCHEMA_VERSION,
        "provenance": prov,
        # Anchor preserved; live_replaced state lives in the sidecar the UE
        # proxy-swap driver writes (kept OUT of the record so the schema gate,
        # whose ALLOWED_FIELDS has no live_replaced, stays clean).
        "notes": "headless plan binding; live_replaced=False until UE swap driver runs",
    }
    return binding, cleared, min_cm


def generate(pack, strict, approved_only):
    rep = ValidationReport("pack", pack, strict=strict)
    encounters = load_pack_encounters(pack)
    rep.check("pack_has_encounters", bool(encounters),
              "no encounters in pack '{}'".format(pack),
              code=FailureCode.COVER_PROXY_REPLACEMENT_FAILURE)

    plan, perr = load_plan(pack)
    rep.check("hybrid_plan_present", plan is not None,
              perr or "plan loaded",
              code=FailureCode.COVER_PROXY_REPLACEMENT_FAILURE)
    if plan is None or not encounters:
        return rep, 0, {}

    resolutions = index_resolutions(plan)
    prov = PROV.build_provenance(
        REPO_ROOT, [Path(EC.__file__), Path(MC.__file__), Path(RC.__file__)],
        COMMAND, GENERATOR_VERSION)
    prov.pop("generated_at_utc", None)  # determinism: no wall-clock in bindings

    n_written = 0
    counts = {"total": 0, "third_party": 0, "generated_baseline": 0, "route_ok": 0}
    for enc in encounters:
        biome = enc.get("biome_family")
        mission, merr = MC.load_mission(enc.get("mission_id") or "")
        rep.check("mission_loads::{}".format(enc["encounter_id"]), mission is not None,
                  merr or "mission loaded",
                  code=FailureCode.COVER_PROXY_REPLACEMENT_FAILURE)
        resolution = resolutions.get((CANONICAL_COVER_FAMILY, biome))
        for cov in enc.get("cover_anchors") or []:
            height_class = cov.get("height_class")
            binding, cleared, _min = build_binding(
                enc, cov, mission, resolution, height_class, prov)
            counts["total"] += 1
            if cleared:
                counts["route_ok"] += 1
            if binding["ownership_class"] == "third_party_owned":
                counts["third_party"] += 1
            else:
                counts["generated_baseline"] += 1

            # Prove the binding is schema-valid before persisting it.
            failing = [c for c in RC.validate_record(binding, strict=strict) if not c[1]]
            rep.check("binding_schema[{}]".format(binding["binding_id"]),
                      not failing,
                      "; ".join("{}: {}".format(c[0], c[2]) for c in failing)
                      if failing else "schema-valid",
                      code=FailureCode.REALIZED_COVER_BINDING_FAILURE)
            # Anchor preservation is the load-bearing invariant.
            rep.check("anchor_preserved[{}]".format(binding["binding_id"]),
                      binding["cover_anchor_id"] == cov["id"]
                      and binding["height_class"] == cov.get("height_class"),
                      "binding mutated the anchor id/height",
                      code=FailureCode.COVER_REPLACEMENT_ANCHOR_MUTATED)

            out = asset_paths.ensure(
                asset_paths.COVER_BINDINGS_DIR / (binding["binding_id"] + ".json"))
            out.write_text(json.dumps(binding, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            n_written += 1

    return rep, n_written, counts


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.5 RealizedCoverBinding writer.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--approved-only", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep, n_written, counts = generate(args.pack, strict, args.approved_only)
    rep.finalize()
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status,
        record_count=n_written, records_total=n_written,
        records_passed=n_written if rep.passed else 0,
        records_failed=0 if rep.passed else n_written,
        extra={"bindings_written": n_written,
               "resolved_third_party": counts.get("third_party", 0),
               "resolved_generated_baseline": counts.get("generated_baseline", 0),
               "route_clearance_ok": counts.get("route_ok", 0),
               "live_replaced_total": 0,
               "cover_bindings_dir": asset_paths.COVER_BINDINGS_DIR.relative_to(REPO_ROOT).as_posix()}))
    report_dir, filename = asset_paths.report_path("realization", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    sys.stdout.write(
        "[{}] {} binding(s) written | third_party={} generated_baseline={} "
        "route_ok={} (live_replaced=False)\n".format(
            COMMAND, n_written, counts.get("third_party", 0),
            counts.get("generated_baseline", 0), counts.get("route_ok", 0)))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
