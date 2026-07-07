#!/usr/bin/env python3
"""materialize_assets.py — WorldForge v1.5 Wave-3 HYBRID cover resolver (headless).

Decides WHICH asset realizes each cover family/biome need in a pack and writes a
resolution PLAN. This is the hybrid production rule made concrete:

    a validated third_party CATALOG mesh REPLACES the generated_owned baseline
    ONLY when it matches the family/biome AND passed validation;
    otherwise the guaranteed generated_owned baseline is used.

Every family/biome need ALWAYS resolves to *something* (never left uncovered),
because the owned baseline is the guaranteed floor. The plan also records which
UE assets still need import/build.

HEADLESS ONLY: this writes the plan; it does NOT spawn or import anything in UE.
The report carries ``live_materialized: False`` — a live UE run (separate driver)
flips it True. Claiming a live spawn here would be a lie the fail-closed
materialization validator is designed to catch.

Usage:
    python tools/pipeline/materialize_assets.py --pack encounter_loop_world --approved-only [--strict]
Report: wf.asset.ue_materialization.v1
Plan:   procedural/generated/realization/plan/materialization_plan_<pack>.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import encounter_contract as EC
import mesh_contract as MC
import provenance as PROV
import realized_cover_contract as RC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from v1_5_schema_gate import discover_records
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "materialize_assets"
REPORT_TYPE = "wf.asset.ue_materialization.v1"
GENERATOR_VERSION = "1.5.0"
PLAN_DIR = asset_paths.COVER_BINDINGS_DIR.parent / "plan"

# A catalog asset is treated as a validated cover replacement only when it passed
# validation (never "pending"/"rejected").
VALIDATION_PASSED = ("passed", "validated", "approved")

# Cover-intent tags a catalog asset must carry to count as a cover mesh.
COVER_INTENT_TAGS = ("cover", "encounter_cover", "encounter")


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


def load_owned_baselines():
    """sm_id -> baseline spec dict for every generated_owned cover baseline."""
    out = {}
    base = asset_paths.OWNED_COVER_DIR
    if base.is_dir():
        for p in sorted(base.glob("*.json")):
            try:
                spec = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if spec.get("sm_id"):
                out[spec["sm_id"]] = spec
    return out


def load_catalog_assets():
    """asset_id -> catalog record, merged from CATALOG_DIR + the aggregate ledger."""
    out = {}
    recs, _errs = discover_records(
        [asset_paths.CATALOG_DIR.relative_to(REPO_ROOT).as_posix()])
    for _name, rec in recs:
        if isinstance(rec, dict) and rec.get("asset_id"):
            out[rec["asset_id"]] = rec
    agg = asset_paths.ACQUISITION_CATALOG
    if agg.is_file():
        try:
            data = json.loads(agg.read_text(encoding="utf-8"))
            for aid, rec in (data.get("assets") or {}).items():
                out.setdefault(aid, rec)
        except Exception:  # noqa: BLE001
            pass
    return out


def _asset_tags(rec):
    tags = set()
    for key in ("usage_tags", "encounter_tags", "biome_tags", "terrain_tags",
                "mission_tags"):
        for t in rec.get(key) or []:
            tags.add(str(t).lower())
    return tags


def match_catalog_cover(family, biome, catalog, approved_only):
    """Return a catalog record that validly REPLACES this family/biome cover, else None.

    Requirements: third_party_owned, cover-intent tag present, biome match, and
    (when approved_only) validation passed + a real ue_asset_path. Deterministic:
    the lowest asset_id wins when several qualify.
    """
    candidates = []
    for aid in sorted(catalog):
        rec = catalog[aid]
        if MC.resolve_ownership_class(rec) != MC.OWNERSHIP_THIRD_PARTY:
            continue
        tags = _asset_tags(rec)
        if not (tags & set(COVER_INTENT_TAGS)):
            continue
        # For the canonical cover family the cover-intent tag is enough; other
        # cover-capable families (rock_outcrop / industrial_debris) must name the
        # family explicitly in the asset's intent tags.
        if family != "encounter_cover" and family not in tags:
            continue
        if biome not in tags:
            continue
        if approved_only:
            if str(rec.get("validation_status")).lower() not in VALIDATION_PASSED:
                continue
            if not MC.is_allowed_final_path(rec.get("ue_asset_path") or ""):
                continue
        candidates.append(rec)
    return candidates[0] if candidates else None


def _ue_materialization_complete(pack):
    """Ground live_materialized in REAL UE evidence, not a mutable flag.

    The plan is regenerated headlessly on every shield run; it must NOT clobber a
    live cube->mesh swap already performed in the editor. So we derive the live
    state from the live-swap driver's report: >0 proxies replaced AND 0 cubes
    remaining. No report (UE run not done) -> False (fail-closed, honest).
    """
    rep_dir = REPO_ROOT / "procedural" / "reports" / "realization" / "replace_cover_proxies_ue"
    try:
        reps = sorted(rep_dir.glob("*.json"))
        if not reps:
            return False
        d = json.loads(reps[0].read_text(encoding="utf-8"))
        return bool(d.get("replaced_total", 0) > 0 and d.get("remaining_cubes_total", 1) == 0)
    except Exception:  # noqa: BLE001
        return False


def resolve(pack, strict, approved_only):
    rep = ValidationReport("pack", pack, strict=strict)
    encounters = load_pack_encounters(pack)
    rep.check("pack_has_encounters", bool(encounters),
              "no encounters in pack '{}'".format(pack),
              code=FailureCode.ASSET_UE_MATERIALIZATION_FAILURE)

    owned = load_owned_baselines()
    rep.check("owned_baselines_present", bool(owned),
              "no generated_owned cover baselines — run generate_owned_cover_meshes first",
              code=FailureCode.COVER_BASELINE_MISSING)
    catalog = load_catalog_assets()

    # Collect the family/biome needs (union across the pack) + heights present.
    needs = {}  # (family, biome) -> set(height_class)
    for enc in encounters:
        biome = enc.get("biome_family")
        heights = {c.get("height_class") for c in enc.get("cover_anchors") or []
                   if c.get("height_class") in RC.HEIGHT_CLASSES}
        for family in EC.BIOME_COVER_FAMILIES.get(biome, ()):
            needs.setdefault((family, biome), set()).update(heights)

    resolutions = []
    needs_ue_import = {}  # ue_asset_path -> {asset_id, ownership, source}
    n_third_party = 0
    n_generated = 0

    for (family, biome) in sorted(needs):
        heights = sorted(needs[(family, biome)]) or [RC.HEIGHT_CLASSES[1]]
        cat = match_catalog_cover(family, biome, catalog, approved_only)
        if cat is not None:
            source = "third_party_catalog"
            ownership = MC.OWNERSHIP_THIRD_PARTY
            asset_id = cat["asset_id"]
            ue_path = cat.get("ue_asset_path") or ""
            per_height = {h: {"asset_id": asset_id, "ue_asset_path": ue_path}
                          for h in heights}
            live = str(cat.get("materialization_status")).lower() == "materialized"
            needs_ue_import[ue_path] = {
                "asset_id": asset_id, "ownership_class": ownership,
                "source": source, "live_materialized": live}
            n_third_party += 1
        else:
            source = "generated_owned_baseline"
            ownership = MC.OWNERSHIP_GENERATED
            asset_id = None
            per_height = {}
            for h in heights:
                sm_id = "SM_Owned_{}_{}".format(family, h)
                spec = owned.get(sm_id)
                ue_path = spec.get("final_asset_path") if spec else ""
                per_height[h] = {"asset_id": sm_id, "ue_asset_path": ue_path}
                needs_ue_import[ue_path] = {
                    "asset_id": sm_id, "ownership_class": ownership,
                    "source": source,
                    "live_materialized": bool(spec and spec.get("live_built"))}
            n_generated += 1

        # Every need must resolve to a real backed asset per height.
        for h in heights:
            entry = per_height.get(h) or {}
            rep.check(
                "resolved[{}:{}:{}]".format(family, biome, h),
                bool(entry.get("asset_id")) and bool(entry.get("ue_asset_path")),
                "cover need family={} biome={} height={} did not resolve to a "
                "backed asset".format(family, biome, h),
                code=FailureCode.COVER_REPLACEMENT_NOT_CATALOG_BACKED)

        resolutions.append({
            "family": family,
            "biome": biome,
            "source": source,
            "ownership_class": ownership,
            "catalog_asset_id": asset_id,
            "heights": heights,
            "per_height": per_height,
        })

    prov = PROV.build_provenance(
        REPO_ROOT, [Path(EC.__file__), Path(MC.__file__), Path(RC.__file__)],
        COMMAND, GENERATOR_VERSION)
    prov.pop("generated_at_utc", None)  # determinism: no wall-clock in the plan

    plan = {
        "schema_version": RC.SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "pack_id": pack,
        "approved_only": bool(approved_only),
        "live_materialized": _ue_materialization_complete(pack),  # derived from UE evidence
        "resolutions": resolutions,
        "needs_ue_import": [
            {"ue_asset_path": k, **v} for k, v in sorted(needs_ue_import.items())],
        "counts": {
            "family_biome_needs": len(needs),
            "resolved_third_party": n_third_party,
            "resolved_generated_baseline": n_generated,
            "ue_assets_needing_import": len(needs_ue_import),
        },
        "provenance": prov,
    }
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    plan_path = PLAN_DIR / "materialization_plan_{}.json".format(pack)
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")

    return rep, plan, plan_path


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.5 hybrid cover resolver (headless plan).")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--approved-only", action="store_true")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep, plan, plan_path = resolve(args.pack, strict, args.approved_only)
    rep.finalize()
    counts = plan["counts"]
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status,
        record_count=counts["family_biome_needs"],
        records_total=counts["family_biome_needs"],
        records_passed=counts["family_biome_needs"] if rep.passed else 0,
        records_failed=0 if rep.passed else counts["family_biome_needs"],
        extra={"live_materialized": plan.get("live_materialized"),
               "resolved_third_party": counts["resolved_third_party"],
               "resolved_generated_baseline": counts["resolved_generated_baseline"],
               "ue_assets_needing_import": counts["ue_assets_needing_import"],
               "plan_path": plan_path.relative_to(REPO_ROOT).as_posix()}))
    report_dir, filename = asset_paths.report_path("realization", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    sys.stdout.write(
        "[{}] plan -> {} | needs={} third_party={} generated_baseline={} "
        "(live_materialized=False)\n".format(
            COMMAND, plan_path.relative_to(REPO_ROOT).as_posix(),
            counts["family_biome_needs"], counts["resolved_third_party"],
            counts["resolved_generated_baseline"]))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
