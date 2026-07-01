#!/usr/bin/env python3
"""full_shield.py — WorldForge v1.0x final integration gate (Agent 0).

Runs every registered v1.0x gate in order against a world pack and rolls the
results into ONE structured report plus a concise human summary. The parent
FAILS if any required child gate fails. This is the canonical
``make full-shield`` entrypoint:

    make full-shield PACK=desert_mvp_world JOBS=8 STRICT=1 DEEP=1 TORTURE=1 SEEDS=100

Design principles (brief §"No fake green"):
  * A gate whose validator SCRIPT DOES NOT EXIST is a blocking failure
    (status=missing) — never silently skipped.
  * A gate that exits non-zero is a blocking failure.
  * A gate that should have written a report but did not is a failure.
  * Torture-only / destructive gates run only under TORTURE=1.
  * The final report carries git SHA, pack, flags, seed set, timestamp and the
    per-gate status list; determinism consumers strip runtime-only meta.

The gate registry is data-driven so gates can be added/tuned in one place. Each
gate declares the exact argv (validators added by other v1.0x lanes all share
the contract CLI: ``--pack <id|yaml> [--strict] [--deep]``, exit 0/1, and write
a report under procedural/reports/...).
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "tools" / "pipeline"
sys.path.insert(0, str(PIPELINE))

from report_meta import build_meta, flag_from_env, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402

PY = sys.executable
WORLD_PACK_YAML = "procedural/world_packs/{pack}.yaml"

# Phases group gates for the human summary.
PHASES = [
    "spec", "generate", "environment", "sky-lighting-fog", "rendering",
    "poi", "entity", "scenario-package", "determinism-fuzz", "lifecycle",
    "regression", "final",
]


def _s(strict):
    return ["--strict"] if strict else []


def _d(deep):
    return ["--deep"] if deep else []


def gate(gid, label, phase, code, script, args_fn, report=None,
         torture_only=False, required=True):
    """Declare one gate. args_fn(ctx)->list[str] builds argv tail after the script."""
    return {
        "id": gid, "label": label, "phase": phase, "code": code,
        "script": script, "args_fn": args_fn, "report": report,
        "torture_only": torture_only, "required": required,
    }


def build_registry():
    """The ordered 33-gate v1.0x contract. Some gates are owned by lanes that
    land incrementally; until their script exists they register as blocking
    failures (status=missing)."""
    yaml_arg = lambda c: WORLD_PACK_YAML.format(pack=c["pack_id"])
    id_arg = lambda c: c["pack_id"]

    reports = "procedural/reports/world_packs/{pack}"

    def r(name):
        return lambda c: reports.format(pack=c["world_pack_id"]) + "/" + name

    G = []
    # 1 — static spec pre-flight
    G.append(gate("validate-world-pack-spec", "Validate world-pack spec", "spec",
                  FailureCode.CONTRACT_FAILURE, "validate_world_pack_spec.py",
                  lambda c: ["--pack", yaml_arg(c)] + _s(c["strict"])))
    # 2 — environment contract
    G.append(gate("validate-environment-contract", "Validate environment contract", "environment",
                  FailureCode.ENVIRONMENT_PROFILE_FAILURE, "validate_environment_contract.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  report=r("validate_environment_contract_report.json")))
    # 3 — build the pack (generation). Heavy; gated so a validation-only shield
    # can skip rebuild via BUILD=0.
    G.append(gate("create-world-pack", "Create world pack", "generate",
                  FailureCode.GENERATION_FAILURE, "create_world_pack.py",
                  lambda c: ["--pack", yaml_arg(c), "--jobs", str(c["jobs"])],
                  required=True))
    # 4 — deep world-pack validation
    G.append(gate("validate-world-pack", "Validate world pack (deep)", "generate",
                  FailureCode.CONTRACT_FAILURE, "validate_world_pack.py",
                  lambda c: ["--pack", yaml_arg(c)] + _d(c["deep"]) + _s(c["strict"])))
    # 5 — report integrity (Agent 1)
    G.append(gate("validate-report-integrity", "Validate report integrity", "generate",
                  FailureCode.REPORT_INTEGRITY_FAILURE, "validate_report_integrity.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"])))
    # 6 — inspection metadata
    G.append(gate("validate-inspection", "Validate inspection metadata", "generate",
                  FailureCode.CONTRACT_FAILURE, "generate_inspection_metadata.py",
                  lambda c: ["--pack", yaml_arg(c), "--validate"] + _s(c["strict"])))
    # 7 — runtime scenario
    G.append(gate("run-world-state-scenario", "Run world-state scenario", "scenario-package",
                  FailureCode.SCENARIO_FAILURE, "run_world_state_scenario.py",
                  lambda c: ["--pack", yaml_arg(c), "--scenario", c["scenario"]] + _s(c["strict"])))
    # 8-11 — sky/lighting/fog/atmosphere (Agent 3)
    for name, code in (("sky", FailureCode.SKY_PROFILE_FAILURE),
                       ("lighting", FailureCode.LIGHTING_PROFILE_FAILURE),
                       ("fog", FailureCode.FOG_PROFILE_FAILURE),
                       ("atmosphere", FailureCode.ATMOSPHERE_PROFILE_FAILURE)):
        G.append(gate("validate-%s" % name, "Validate %s" % name, "sky-lighting-fog",
                      code, "validate_%s.py" % name,
                      lambda c, n=name: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=r("validate_%s_report.json" % name)))
    # 12-15 — rendering/scalability/raytracing/budgets (Agent 6)
    for name, code in (("rendering-profiles", FailureCode.RENDERING_PROFILE_FAILURE),
                       ("scalability", FailureCode.SCALABILITY_FAILURE),
                       ("raytracing", FailureCode.RAYTRACING_FAILURE),
                       ("performance-budgets", FailureCode.BUDGET_FAILURE)):
        script = "validate_%s.py" % name.replace("-", "_")
        G.append(gate("validate-%s" % name, "Validate %s" % name, "rendering",
                      code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=r(script.replace(".py", "_report.json"))))
    # 16-pre — generate level-design overlays (Agent 4) before validating them
    G.append(gate("generate-level-design", "Generate level-design overlays", "poi",
                  FailureCode.GENERATION_FAILURE, "generate_level_design.py",
                  lambda c: ["--pack", id_arg(c)]))
    # 16-19 — POI/level-design/reachability/poi-graph (Agent 4)
    for name, code in (("pois", FailureCode.POI_USABILITY_FAILURE),
                       ("level-design", FailureCode.LEVEL_DESIGN_FAILURE),
                       ("reachability", FailureCode.REACHABILITY_FAILURE),
                       ("poi-graph", FailureCode.POI_GRAPH_FAILURE)):
        script = "validate_%s.py" % name.replace("-", "_")
        G.append(gate("validate-%s" % name, "Validate %s" % name, "poi",
                      code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=r(script.replace(".py", "_report.json"))))
    # 20-pre — generate entity-anchor overlays (Agent 5) before validating them
    G.append(gate("generate-entity-anchors", "Generate entity-anchor overlays", "entity",
                  FailureCode.GENERATION_FAILURE, "generate_entity_anchors.py",
                  lambda c: ["--pack", id_arg(c)]))
    # 20-22 — entity anchors/npc spawns/encounter readiness (Agent 5)
    for name, code in (("entity-anchors", FailureCode.ENTITY_ANCHOR_FAILURE),
                       ("npc-spawns", FailureCode.NPC_SPAWN_FAILURE),
                       ("encounter-readiness", FailureCode.ENCOUNTER_READINESS_FAILURE)):
        script = "validate_%s.py" % name.replace("-", "_")
        G.append(gate("validate-%s" % name, "Validate %s" % name, "entity",
                      code, script,
                      lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                      report=r(script.replace(".py", "_report.json"))))
    # 23 — package check
    G.append(gate("package-check", "Package check", "scenario-package",
                  FailureCode.PACKAGE_FAILURE, "package_check.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"])))
    # 24 — determinism (Agent 7)
    G.append(gate("validate-determinism", "Validate determinism", "determinism-fuzz",
                  FailureCode.DETERMINISM_FAILURE, "validate_determinism.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"])))
    # 25 — seed matrix (Agent 7)
    G.append(gate("seed-matrix", "Seed matrix", "determinism-fuzz",
                  FailureCode.DETERMINISM_FAILURE, "seed_matrix.py",
                  lambda c: ["--pack", id_arg(c), "--seeds", str(c["seeds"])] + _s(c["strict"])))
    # 26 — fuzz (Agent 7)
    G.append(gate("fuzz-world-pack", "Fuzz world pack", "determinism-fuzz",
                  FailureCode.FUZZ_FAILURE, "fuzz_world_pack.py",
                  lambda c: ["--pack", id_arg(c), "--cases", str(c["cases"])] + _s(c["strict"])))
    # 27 — lifecycle torture (Agent 7) — TORTURE only
    G.append(gate("lifecycle-torture", "Lifecycle torture", "lifecycle",
                  FailureCode.LIFECYCLE_FAILURE, "lifecycle_torture.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  torture_only=True))
    # 28 — repair (existing)
    G.append(gate("repair-world-pack", "Repair world pack", "lifecycle",
                  FailureCode.LIFECYCLE_FAILURE, "repair_world_pack.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  torture_only=True))
    # 29-31 destroy/rebuild/revalidate are performed inside lifecycle-torture on
    # an owned scope (safe, provenance-guarded). Represented by gate 27 above +
    # revalidate below.
    # 31 — revalidate (Agent 0)
    G.append(gate("revalidate-world-pack", "Revalidate world pack", "lifecycle",
                  FailureCode.LIFECYCLE_FAILURE, "revalidate_world_pack.py",
                  lambda c: ["--pack", id_arg(c)] + _s(c["strict"]),
                  torture_only=True))
    # 32 — regression matrix (Agent 7)
    G.append(gate("validate-regression-matrix", "Validate regression matrix", "regression",
                  FailureCode.REGRESSION_FAILURE, "validate_regression_matrix.py",
                  lambda c: _s(c["strict"])))
    # 33 — final report integrity (Agent 1) — re-run after everything
    G.append(gate("final-report-integrity", "Final report integrity check", "final",
                  FailureCode.REPORT_INTEGRITY_FAILURE, "validate_report_integrity.py",
                  lambda c: ["--pack", id_arg(c), "--final"] + _s(c["strict"])))
    return G


def run_gate(g, ctx):
    """Run one gate; return a result row."""
    script_path = PIPELINE / g["script"]
    row = {"id": g["id"], "label": g["label"], "phase": g["phase"],
           "code": g["code"], "status": None, "rc": None, "detail": ""}

    if g["torture_only"] and not ctx["torture"]:
        row["status"] = "skipped_no_torture"
        row["detail"] = "torture-only gate; TORTURE not set"
        return row

    if not script_path.is_file():
        row["status"] = "missing"
        row["detail"] = "validator not implemented yet: tools/pipeline/%s" % g["script"]
        return row

    argv = [PY, str(script_path)] + g["args_fn"](ctx)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    if ctx["strict"]:
        env["STRICT"] = "1"
    if ctx["deep"]:
        env["DEEP"] = "1"
    try:
        proc = subprocess.run(argv, cwd=str(REPO_ROOT), env=env,
                              capture_output=True, text=True, timeout=ctx["timeout"])
    except subprocess.TimeoutExpired:
        row["status"] = "fail"
        row["detail"] = "timeout after %ss" % ctx["timeout"]
        return row
    row["rc"] = proc.returncode
    tail = (proc.stdout or "").strip().splitlines()[-3:]
    row["detail"] = " | ".join(tail)[:400]

    # Cross-check the gate's report if it declares one.
    if g["report"]:
        rpt_path = REPO_ROOT / g["report"](ctx)
        if not rpt_path.is_file():
            row["status"] = "fail"
            row["detail"] = "gate exited %s but wrote no report: %s" % (proc.returncode, g["report"](ctx))
            return row
        try:
            rpt = json.loads(rpt_path.read_text(encoding="utf-8"))
            row["report_status"] = rpt.get("status")
            rc_meta = rpt.get("meta") or {}
            row["record_count"] = rc_meta.get("record_count", rpt.get("counts", {}).get("PASS"))
        except Exception as exc:
            row["status"] = "fail"
            row["detail"] = "report unparseable: %s" % exc
            return row

    row["status"] = "pass" if proc.returncode == 0 else "fail"
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.0x full-shield integration gate.")
    ap.add_argument("--pack", default="desert_mvp_world")
    ap.add_argument("--jobs", type=int, default=int(os.environ.get("JOBS", "1")))
    ap.add_argument("--seeds", type=int, default=int(os.environ.get("SEEDS", "5")))
    ap.add_argument("--cases", type=int, default=int(os.environ.get("CASES", "25")))
    ap.add_argument("--scenario", default="industrial_takeover")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--deep", action="store_true")
    ap.add_argument("--torture", action="store_true")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--no-build", action="store_true",
                    help="Skip the heavy create-world-pack rebuild gate (validation-only run).")
    ap.add_argument("--only", default=None, help="Run only gates whose id contains this substring")
    args = ap.parse_args(argv)

    strict = args.strict or strict_from_env()
    deep = args.deep or flag_from_env("DEEP")
    torture = args.torture or flag_from_env("TORTURE")

    # Resolve world_pack_id from the pack yaml.
    from world_pack_maps import enumerate_maps
    try:
        world_pack_id, maps = enumerate_maps(args.pack)
    except Exception as exc:
        sys.stderr.write("ERROR: cannot enumerate pack %s: %s\n" % (args.pack, exc))
        sys.exit(2)

    ctx = {"pack_id": args.pack, "world_pack_id": world_pack_id,
           "strict": strict, "deep": deep, "torture": torture,
           "jobs": args.jobs, "seeds": args.seeds, "cases": args.cases,
           "scenario": args.scenario, "timeout": args.timeout}

    print("=" * 70)
    print("WorldForge v1.0x FULL-SHIELD — pack=%s strict=%s deep=%s torture=%s seeds=%s" % (
        world_pack_id, strict, deep, torture, args.seeds))
    print("=" * 70)

    registry = build_registry()
    if args.no_build or flag_from_env("NO_BUILD"):
        registry = [g for g in registry if g["id"] != "create-world-pack"]
    if args.only:
        registry = [g for g in registry if args.only in g["id"]]

    rows = []
    for i, g in enumerate(registry, 1):
        print("\n[%2d/%d] %s (%s)" % (i, len(registry), g["label"], g["id"]))
        row = run_gate(g, ctx)
        rows.append(row)
        mark = {"pass": "PASS", "fail": "FAIL", "missing": "MISSING",
                "skipped_no_torture": "SKIP"}.get(row["status"], row["status"].upper())
        print("       -> %s  %s" % (mark, row["detail"]))

    # Roll up.
    def is_blocking(row, g):
        if row["status"] in ("fail", "missing"):
            return True
        return False

    gate_by_id = {g["id"]: g for g in registry}
    blocking = [r for r in rows if is_blocking(r, gate_by_id[r["id"]])]
    n_pass = sum(1 for r in rows if r["status"] == "pass")
    n_fail = sum(1 for r in rows if r["status"] == "fail")
    n_missing = sum(1 for r in rows if r["status"] == "missing")
    n_skip = sum(1 for r in rows if r["status"] == "skipped_no_torture")
    passed = len(blocking) == 0

    # Failure taxonomy rollup.
    taxonomy = {}
    for r in blocking:
        taxonomy.setdefault(r["code"], []).append(r["id"])

    meta = build_meta(command="full-shield", pack=world_pack_id, strict=strict,
                      deep=deep, torture=torture, seeds=args.seeds,
                      status="ok" if passed else "fail",
                      failure_count=len(blocking), record_count=len(rows))

    report = {
        "world_pack_id": world_pack_id, "meta": meta,
        "passed": passed, "status": "ok" if passed else "fail",
        "totals": {"gates": len(rows), "pass": n_pass, "fail": n_fail,
                   "missing": n_missing, "skipped": n_skip},
        "blocking_gates": [r["id"] for r in blocking],
        "failure_taxonomy": taxonomy,
        "gates": rows,
        "map_count": len(maps),
    }
    report_dir = REPO_ROOT / "procedural" / "reports" / "world_packs" / world_pack_id
    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / "full_shield_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\n" + "=" * 70)
    print("FULL-SHIELD %s — %d/%d gates pass (%d fail, %d missing, %d skipped)" % (
        "PASS" if passed else "FAIL", n_pass, len(rows), n_fail, n_missing, n_skip))
    if blocking:
        print("Blocking gates:")
        for r in blocking:
            print("  [%s] %s (%s)" % (r["status"].upper(), r["id"], r["code"]))
    if taxonomy:
        print("Failure taxonomy:")
        for code, ids in sorted(taxonomy.items()):
            print("  %s: %s" % (code, ", ".join(ids)))
    print("Report: procedural/reports/world_packs/%s/full_shield_report.json" % world_pack_id)
    print("=" * 70)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
