#!/usr/bin/env python3
"""index_reports.py — v2.1 OperatorForge report indexer + evidence graph (Wave 2).

Indexes the REAL WorldForge evidence stack (the v2.0 vertical-slice reports, which
cross-reference the v1.6z traversal / v1.7 NPC / v1.8 combat / v1.9 reward layers)
into two derived operator artifacts:

  procedural/reports/operator/index/operator_report_index.json  (OperatorReportIndex)
  procedural/reports/operator/index/evidence_graph.json         (list[EvidenceTrace])

OperatorForge INDEXES existing evidence; it does not make stale evidence true. So
this indexer resolves every claim to a REAL file on disk — a claim whose supporting
report is missing is recorded with verdict=blocked and an explicit missing_input,
never laundered to pass. The Wave-2 validator (validate_operator_index.py) then
proves the index against the OperatorReportIndex / EvidenceTrace contracts AND
re-checks referential integrity (every path exists, every code resolves).

Both artifacts are DERIVED — no source evidence is rewritten. Determinism: the
records are ordered by scenario id; only git_sha/created_at reflect run identity.

Acceptance:
    PYTHONUTF8=1 python tools/operator/index_reports.py --strict
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_contracts as OX  # noqa: E402
from failure_codes import all_codes  # noqa: E402

INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"

# Real evidence roots for the v2.0 vertical slice. Only roots that exist are
# recorded (a missing source root is an honest WF712 the validator surfaces).
SOURCE_ROOTS = (
    "procedural/reports/slice/runtime",
    "procedural/reports/slice/integrity",
    "procedural/reports/slice/package",
    "procedural/generated/slice",
)

MANIFEST = REPO_ROOT / "procedural/generated/slice/manifest.json"
PACKAGE_REPORT = REPO_ROOT / "procedural/reports/slice/package/slice_package_worldforge_vertical_slice.json"
EVIDENCE_INDEX = REPO_ROOT / "procedural/reports/slice/integrity/slice_evidence_index_worldforge_vertical_slice.json"
RUNTIME_DIR = REPO_ROOT / "procedural/reports/slice/runtime"
PACKAGE_REPORT_REL = "procedural/reports/slice/package/slice_package_worldforge_vertical_slice.json"

# claim -> source milestone (which substrate proves it).
CLAIM_MILESTONE = {
    "scenario completed": "v2.0",
    "grounded traversal succeeded": "v1.6z",
    "npc pressure occurred": "v1.7",
    "combat damage occurred": "v1.8",
    "reward granted": "v1.9",
    "save/load roundtrip passed": "v1.9",
    "package includes map": "v2.0",
}


def _git(*args, default=""):
    try:
        return subprocess.check_output(["git", *args], cwd=str(REPO_ROOT),
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        return default


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _exists(rel):
    return (REPO_ROOT / rel).is_file()


def _rel(p):
    return str(Path(p).as_posix())


def build_traces(manifest, package):
    """Build one EvidenceTrace per (scenario, claim), resolving to real files."""
    traces = []
    known = set(all_codes())
    maps_included = set(package.get("maps_included", []))
    pkg_exists = package.get("package_exists") is True

    for ssid in sorted(manifest.get("scenarios", [])):
        rrel = "procedural/reports/slice/runtime/slice_runtime_{}.json".format(ssid)
        rpath = REPO_ROOT / rrel
        runtime = _load(rpath) if rpath.is_file() else None
        tele = [t for t in (runtime.get("telemetry_paths", []) if runtime else [])]

        def _trace(claim, ok, supporting, missing,
                   telemetry=(), save_load=(), package_proofs=(), fail_code=None):
            verdict = "pass" if ok and not missing else ("blocked" if missing else "fail")
            fcs = [] if verdict == "pass" else ([fail_code] if fail_code else [])
            t = OX._example_evidence_trace(
                trace_id="trace_{}_{}".format(ssid, claim.replace(" ", "_").replace("/", "_")),
                scenario_id=ssid,
                claim=claim,
                claim_status=verdict,
                supporting_reports=list(supporting),
                supporting_telemetry=list(telemetry),
                supporting_save_load_proofs=list(save_load),
                supporting_package_proofs=list(package_proofs),
                source_milestones=[CLAIM_MILESTONE[claim]],
                stale_inputs=[],
                missing_inputs=list(missing),
                verdict=verdict,
                failure_codes=fcs,
            )
            return t

        if runtime is None:
            # No runtime report -> every claim for this scenario is blocked.
            for claim in CLAIM_MILESTONE:
                traces.append(_trace(claim, False, [], [rrel]))
            continue

        rlist = [rrel]
        missing_tele = [t for t in tele if not _exists(t)]
        # scenario completed
        traces.append(_trace(
            "scenario completed",
            runtime.get("slice_completed_runtime") is True
            and not runtime.get("failure_codes"),
            rlist, [], telemetry=tele, package_proofs=[PACKAGE_REPORT_REL],
            fail_code="WF702_SLICE_MISSION_INCOMPLETE"))
        # grounded traversal
        traces.append(_trace(
            "grounded traversal succeeded",
            runtime.get("traversal_completed") is True and not missing_tele,
            rlist, missing_tele, telemetry=tele,
            fail_code="WF679_SLICE_TRAVERSAL_MISSING"))
        # npc pressure
        traces.append(_trace(
            "npc pressure occurred", runtime.get("npc_behavior_seen") is True,
            rlist, [], fail_code="WF680_SLICE_NPC_EVIDENCE_MISSING"))
        # combat damage
        traces.append(_trace(
            "combat damage occurred", runtime.get("combat_damage_seen") is True,
            rlist, [], fail_code="WF703_SLICE_NPC_NO_DAMAGE"))
        # reward granted (must mutate state)
        traces.append(_trace(
            "reward granted",
            runtime.get("reward_granted") is True
            and (runtime.get("inventory_mutated") is True
                 or runtime.get("progression_mutated") is True),
            rlist, [], fail_code="WF704_SLICE_REWARD_WITHOUT_MUTATION"))
        # save/load roundtrip (proof carried inside the runtime report)
        traces.append(_trace(
            "save/load roundtrip passed",
            runtime.get("save_load_result") == "roundtrip_ok",
            rlist, [], save_load=rlist, fail_code="WF684_SLICE_SAVE_LOAD_FAILED"))
        # package includes map
        traces.append(_trace(
            "package includes map",
            pkg_exists and runtime.get("map_id") in maps_included,
            [PACKAGE_REPORT_REL], [], package_proofs=[PACKAGE_REPORT_REL],
            fail_code="WF725_OPERATOR_PACKAGE_PROOF_MISSING"))

    # sanity: any failure code we emitted must be a real registry code.
    for t in traces:
        for c in t.get("failure_codes", []):
            if c not in known:
                t.setdefault("notes", "unknown code {}".format(c))
    return traces


def build_index(manifest, package, traces):
    """Build the OperatorReportIndex over the real source roots."""
    roots = [r for r in SOURCE_ROOTS if (REPO_ROOT / r).is_dir()]
    report_count = sum(1 for r in roots for _ in (REPO_ROOT / r).rglob("*.json"))

    # coverage: a scenario is "seen" iff its runtime report exists and completed.
    scenarios = sorted(manifest.get("scenarios", []))
    missing = []
    for ssid in scenarios:
        rpath = RUNTIME_DIR / "slice_runtime_{}.json".format(ssid)
        if not rpath.is_file():
            missing.append("runtime:{}".format(ssid))
            continue
        r = _load(rpath)
        if r.get("slice_completed_runtime") is not True or r.get("failure_codes"):
            missing.append("incomplete:{}".format(ssid))

    # distinct failure codes observed across the evidence graph.
    codes_seen = sorted({c for t in traces for c in t.get("failure_codes", [])})
    stale = []  # referential staleness (missing referenced inputs) is folded into
    # each trace's missing_inputs; no report here references a vanished input.

    integrity = "pass" if not missing and not stale else "blocked"
    sha = _git("rev-parse", "HEAD", default="unknown")
    dirty = bool(_git("status", "--porcelain"))

    idx = OX._example_report_index(
        index_id="operator_report_index",
        created_at="live",
        git_sha=sha,
        repo_status="dirty" if dirty else "clean",
        source_roots=roots,
        report_count=report_count,
        scenario_count=len(scenarios),
        pack_count=1,
        map_count=len(manifest.get("maps", [])),
        failure_code_count=len(codes_seen),
        evidence_categories=["runtime", "traversal", "npc", "combat", "reward",
                             "save_load", "package"],
        missing_evidence=missing,
        stale_evidence=stale,
        integrity_result=integrity,
        source_milestones=["v2.0", "v1.9", "v1.8", "v1.7", "v1.6z"],
    )
    return idx


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator report indexer.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)

    if not MANIFEST.is_file():
        print("[operator-index-reports] FAIL — slice manifest not found: {}".format(MANIFEST))
        sys.exit(1)
    manifest = _load(MANIFEST)
    package = _load(PACKAGE_REPORT) if PACKAGE_REPORT.is_file() else {"maps_included": [],
                                                                        "package_exists": False}

    traces = build_traces(manifest, package)
    idx = build_index(manifest, package, traces)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    (INDEX_DIR / "operator_report_index.json").write_text(
        json.dumps(idx, indent=2, sort_keys=True), encoding="utf-8")
    graph = {
        "schema_version": "wf.operator.evidence_graph.v1",
        "index_id": idx["index_id"],
        "git_sha": idx["git_sha"],
        "trace_count": len(traces),
        "traces": traces,
    }
    (INDEX_DIR / "evidence_graph.json").write_text(
        json.dumps(graph, indent=2, sort_keys=True), encoding="utf-8")

    npass = sum(1 for t in traces if t["verdict"] == "pass")
    print("[operator-index-reports] wrote index ({} reports, {} scenarios, integrity={})"
          .format(idx["report_count"], idx["scenario_count"], idx["integrity_result"]))
    print("  evidence graph: {} traces ({} pass / {} not-pass)".format(
        len(traces), npass, len(traces) - npass))
    print("  -> {}".format((INDEX_DIR / "operator_report_index.json").as_posix()))
    print("  -> {}".format((INDEX_DIR / "evidence_graph.json").as_posix()))
    # honest non-zero exit if the index itself is not clean under --strict.
    if args.strict and idx["integrity_result"] != "pass":
        print("  integrity_result != pass under --strict -> RED")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
