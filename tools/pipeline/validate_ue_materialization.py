#!/usr/bin/env python3
"""validate_ue_materialization.py — WorldForge v1.5 Wave-3 UE materialization gate.

Validates the headless materialization PLAN + every UE asset it needs:

  * every planned UE asset is backed by a real record — a catalog AssetCatalogRecord
    (third_party) OR a generated_owned cover baseline spec   (ASSET_UE_MATERIALIZATION_FAILURE)
  * its ue_asset_path is under an approved /Game owned root   (ASSET_UE_PATH_INVALID)

FAIL-CLOSED: while the plan's ``live_materialized`` is False (no UE import/build
run yet), every planned asset is a BLOCKING ASSET_UE_MATERIALIZATION_FAILURE. That
is honest — the plan exists, the UE assets do not, so the gate is correctly RED
until the UE driver imports/builds them and flips live_materialized True.

Usage:
    python tools/pipeline/validate_ue_materialization.py --pack encounter_loop_world [--strict]
Report: wf.realization.ue_materialization_validation.v1
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import mesh_contract as MC
from failure_codes import FailureCode
from report_meta import build_meta, strict_from_env
from v1_5_schema_gate import discover_records
from validation_report import ValidationReport

REPO_ROOT = asset_paths.REPO_ROOT
COMMAND = "validate_ue_materialization"
REPORT_TYPE = "wf.realization.ue_materialization_validation.v1"
PLAN_DIR = asset_paths.COVER_BINDINGS_DIR.parent / "plan"


def load_plan(pack):
    p = PLAN_DIR / "materialization_plan_{}.json".format(pack)
    if not p.is_file():
        return None, "materialization plan missing: {} (run materialize_assets first)".format(p)
    try:
        return json.loads(p.read_text(encoding="utf-8")), None
    except Exception as exc:  # noqa: BLE001
        return None, "plan unparseable: {}".format(exc)


def owned_backed():
    """set of sm_ids + final_asset_paths declared by owned-cover baselines."""
    out = set()
    base = asset_paths.OWNED_COVER_DIR
    if base.is_dir():
        for p in sorted(base.glob("*.json")):
            try:
                s = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for k in ("sm_id", "final_asset_path"):
                if s.get(k):
                    out.add(s[k])
    return out


def catalog_backed():
    """asset_id -> record for every catalog asset."""
    out = {}
    recs, _e = discover_records(
        [asset_paths.CATALOG_DIR.relative_to(REPO_ROOT).as_posix()])
    for _n, r in recs:
        if isinstance(r, dict) and r.get("asset_id"):
            out[r["asset_id"]] = r
    agg = asset_paths.ACQUISITION_CATALOG
    if agg.is_file():
        try:
            data = json.loads(agg.read_text(encoding="utf-8"))
            for aid, r in (data.get("assets") or {}).items():
                out.setdefault(aid, r)
        except Exception:  # noqa: BLE001
            pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.5 UE materialization gate.")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"
    strict = strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    plan, perr = load_plan(args.pack)
    rep.check("materialization_plan_present", plan is not None,
              perr or "plan loaded",
              code=FailureCode.ASSET_UE_MATERIALIZATION_FAILURE)
    if plan is None:
        rep.finalize()
        rep.set_meta(build_meta(COMMAND.replace("_", "-"), pack=args.pack,
                                strict=strict, report_type=REPORT_TYPE,
                                status=rep.status, record_count=0))
        report_dir, filename = asset_paths.report_path("realization", COMMAND)
        rep.write(report_dir, filename)
        rep.print_summary(COMMAND.replace("_", "-"))
        return rep.exit_code

    owned = owned_backed()
    catalog = catalog_backed()
    needs = plan.get("needs_ue_import") or []
    live_materialized = bool(plan.get("live_materialized"))

    n_ok = 0
    for need in needs:
        ue_path = need.get("ue_asset_path")
        aid = need.get("asset_id")
        backed = (aid in owned) or (ue_path in owned) or (aid in catalog)
        rep.check("asset_backed[{}]".format(aid), backed,
                  "planned UE asset '{}' ({}) is backed by neither a catalog "
                  "record nor an owned-cover baseline".format(aid, ue_path),
                  code=FailureCode.ASSET_UE_MATERIALIZATION_FAILURE)
        rep.check("ue_path_approved_root[{}]".format(aid),
                  MC.is_allowed_final_path(ue_path or ""),
                  "ue_asset_path '{}' is not under an approved /Game owned "
                  "root".format(ue_path),
                  code=FailureCode.ASSET_UE_PATH_INVALID)
        if backed and MC.is_allowed_final_path(ue_path or ""):
            n_ok += 1

    # FAIL-CLOSED: the plan is valid but nothing is live in UE yet.
    rep.check("live_materialized", live_materialized,
              "plan live_materialized=False: {} UE asset(s) still need import/build "
              "in the editor — run the UE materialization driver".format(len(needs)),
              code=FailureCode.ASSET_UE_MATERIALIZATION_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(
        COMMAND.replace("_", "-"), pack=args.pack, strict=strict,
        report_type=REPORT_TYPE, status=rep.status,
        record_count=len(needs), records_total=len(needs),
        records_passed=n_ok if live_materialized else 0,
        records_failed=len(needs) if not live_materialized else len(needs) - n_ok,
        extra={"planned_ue_assets": len(needs), "schema_backed": n_ok,
               "live_materialized": live_materialized}))
    report_dir, filename = asset_paths.report_path("realization", COMMAND)
    rep.write(report_dir, filename)
    rep.print_summary(COMMAND.replace("_", "-"))
    sys.stdout.write(
        "[{}] planned_ue_assets={} schema_backed={} live_materialized={}\n".format(
            COMMAND, len(needs), n_ok, live_materialized))
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(main())
