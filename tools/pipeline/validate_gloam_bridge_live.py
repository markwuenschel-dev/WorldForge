#!/usr/bin/env python3
"""validate_gloam_bridge_live.py — v2.5.1 LIVE bridge POSITIVE gate (DoD #17).

The v2.5 bridge gate (validate_gloam_bridge.py) proves the bridge contract offline
against a rejecting DRY probe. That is a NEGATIVE gate: it is GREEN precisely when
nothing ran. It cannot satisfy DoD #17, which requires a real run against a
SEPARATE UE 5.8 project. This is the POSITIVE gate that can only go GREEN when the
far side genuinely executed. The dry probe and its gate are untouched.

GREEN requires ALL of:
    execution_mode          == "live"
    runtime_executed        is True
    observed_runtime_engine  is UE 5.8, as reported by the RUNNING editor
    plugin_loaded           is True
    operation_completed     is True
    evidence_count          > 0
plus the full LiveBridgeReport contract (tools.bridge.live): target repository and
commit resolved, correct .uproject opened, capability handshake green, operation_id
preserved end to end, evidence project-relative and hash-paired.

It does not stop at reading the report. The gate INDEPENDENTLY RE-VERIFIES the
evidence: it re-hashes every artifact from the bytes on disk in the target project
and compares against the hashes the report carries. A report whose hashes do not
reproduce is rejected — evidence you cannot re-derive is not evidence.

FAIL-CLOSED PROOFS (each must be rejected for its owning code):
    dry probe submitted to the live gate -> WF1034 TRANSITION_REPORT_INTEGRITY_FAILED
    runtime never executed               -> WF1034 TRANSITION_REPORT_INTEGRITY_FAILED
    exit zero but evidence missing       -> WF1028 BRIDGE_EMPTY_EVIDENCE
    wrong engine observed                -> WF1023 BRIDGE_WRONG_ENGINE
    plugin absent                        -> WF1025 BRIDGE_ABSENT_PLUGIN
    plugin present but never loaded      -> WF1018 PLUGIN_LOAD_FAILED
    operation_id mismatch (end to end)   -> WF1030 BRIDGE_OPERATION_ID_MISMATCH
    evidence from another project        -> WF1024 BRIDGE_WRONG_PROJECT
    stale/reused evidence                -> WF1026 BRIDGE_STALE_PLUGIN
    absolute path leak                   -> WF1029 BRIDGE_ABSOLUTE_PATH_LEAK
    capability handshake failed          -> WF1011 CAPABILITY_UNAVAILABLE
    operation did not complete           -> WF1034 TRANSITION_REPORT_INTEGRITY_FAILED

Only existing codes from the WF1011-WF1039 transition band are used; no code is added.

Runtime-REQUIRED gate: it validates the artifact of a real run. Run the live runner
first (gloam_bridge_live.py); this gate never launches an editor itself and never
manufactures a report.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_gloam_bridge_live.py --strict
Report -> procedural/reports/ue5_8/gloam/live/validate_gloam_bridge_live_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import bridge  # noqa: E402
from bridge import fixture as FX  # noqa: E402
from bridge import live as LIVE  # noqa: E402
from bridge import paths as P  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, hash_file, strict_from_env  # noqa: E402
from transition_identity import transition_identity  # noqa: E402
from validation_report import ValidationReport  # noqa: E402
import gloam_bridge_probe as GBP  # noqa: E402  (the DRY probe — used as a NEGATIVE)

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "gloam" / "live"
LIVE_REPORT = REPORT_DIR / "gloam_bridge_live_report.json"


def _fails(obj):
    fails = [c for c in LIVE.validate_live_bridge_report(obj, strict=True) if not c[1]]
    return fails, {c[3] for c in fails}


def _reject_for(rep, name, obj, expected_code):
    """Assert a dishonest live report is rejected FOR ITS OWNING CODE."""
    fails, codes = _fails(obj)
    rep.check("negative::{}::rejected".format(name), len(fails) > 0,
              "fixture must be rejected by the live gate",
              code=C.TRANSITION_NEGATIVE_ACCEPTED)
    rep.check("negative::{}::code".format(name), expected_code in codes,
              "must reject for {} (got {})".format(
                  expected_code, sorted(str(c) for c in codes)[:6]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)


def dogfood_contract(rep):
    """The live contract greens its own valid example and is distinct from the dry one."""
    gfails, _ = _fails(LIVE.example_live_report())
    rep.check("dogfood::valid_example_passes", len(gfails) == 0,
              "valid live example rejected: {}".format([(c[0], c[2]) for c in gfails][:4]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    # The live schema MUST NOT collide with the dry one, or a dry report could be
    # relabelled as live by editing one string.
    rep.check("dogfood::live_schema_distinct_from_dry",
              LIVE.LIVE_SCHEMA_VERSION != bridge.BRIDGE_SCHEMA_VERSION,
              "live schema must differ from the dry-probe schema",
              code=C.TRANSITION_HYGIENE_FAILED)


def validate_real_live_report(rep):
    """The POSITIVE gate: the on-disk live report must prove a real run happened."""
    rep.check("live::report_written", LIVE_REPORT.is_file(),
              "run tools/pipeline/gloam_bridge_live.py first (missing {})".format(
                  LIVE_REPORT.name),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    if not LIVE_REPORT.is_file():
        return None
    try:
        report = json.loads(LIVE_REPORT.read_text(encoding="utf-8"))
    except ValueError as exc:
        rep.check("live::report_parses", False, "unparseable live report: {}".format(exc),
                  code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
        return None

    # 1. the full live contract
    for name, ok, detail, code in LIVE.validate_live_bridge_report(report, strict=True):
        rep.check("real::{}".format(name), ok, detail, code=code)

    # 2. the six DoD #17 headline conditions, asserted explicitly and by name
    rep.check("dod17::execution_mode_live",
              report.get("execution_mode") == LIVE.MODE_LIVE,
              "execution_mode must be live", code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    rep.check("dod17::runtime_executed",
              report.get("runtime_executed") is True,
              "runtime_executed must be true", code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    rep.check("dod17::observed_runtime_engine_5_8",
              LIVE.engine_minor(report.get("observed_runtime_engine")) == 8,
              "observed_runtime_engine must be 5.8 (got {!r})".format(
                  report.get("observed_runtime_engine")),
              code=C.BRIDGE_WRONG_ENGINE)
    rep.check("dod17::plugin_loaded", report.get("plugin_loaded") is True,
              "plugin_loaded must be true", code=C.PLUGIN_LOAD_FAILED)
    rep.check("dod17::operation_completed", report.get("operation_completed") is True,
              "operation_completed must be true",
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    rep.check("dod17::evidence_count_positive",
              isinstance(report.get("evidence_count"), int)
              and report.get("evidence_count", 0) > 0,
              "evidence_count must be > 0", code=C.BRIDGE_EMPTY_EVIDENCE)

    # 3. meta convention: a live bridge REQUIRES a runtime and must have had one.
    meta = report.get("meta") or {}
    rep.check("real::meta_declared_engine",
              meta.get("declared_target_engine") == "5.8",
              "meta.declared_target_engine must be '5.8'",
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    rep.check("real::meta_runtime_required",
              meta.get("runtime_execution_required") is True,
              "meta.runtime_execution_required must be True for a LIVE bridge",
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    rep.check("real::meta_runtime_executed",
              meta.get("runtime_executed") is True,
              "meta.runtime_executed must be True", code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    rep.check("real::meta_observed_runtime_engine",
              meta.get("observed_runtime_engine") == 8,
              "meta.observed_runtime_engine must be 8 (got {!r})".format(
                  meta.get("observed_runtime_engine")),
              code=C.EVIDENCE_ENGINE_MISMATCH)

    # 4. the far side really is a SEPARATE repository, outside this one
    fixture_root = P.resolve_fixture_root(REPO_ROOT).value
    rep.check("real::fixture_outside_repo",
              FX.is_outside(fixture_root, REPO_ROOT),
              "the far-side project must live outside the WorldForge repo to be a "
              "separate repository (got {})".format(fixture_root),
              code=C.TRANSITION_HYGIENE_FAILED)
    fixture_head = FX.fixture_git_head(fixture_root)
    rep.check("real::fixture_is_own_repo", bool(fixture_head),
              "the far-side project must be its own git repository",
              code=C.TRANSITION_HYGIENE_FAILED)
    # The commit the far side resolved must be the far side's ACTUAL HEAD — this is
    # what makes "target commit resolved" a resolution rather than an assertion.
    rep.check("real::resolved_commit_is_fixture_head",
              report.get("resolved_target_commit") == fixture_head,
              "resolved_target_commit {!r} != the fixture repo's real HEAD {!r}".format(
                  report.get("resolved_target_commit"), fixture_head),
              code=C.BRIDGE_WRONG_PROJECT)
    rep.check("real::target_repo_is_not_worldforge",
              (report.get("resolved_target_repository") or "").lower()
              not in ("worldforge", REPO_ROOT.name.lower()),
              "the bridge must target a SEPARATE repository, not WorldForge itself",
              code=C.BRIDGE_WRONG_PROJECT)

    # 5. INDEPENDENT re-verification: re-hash the evidence from the bytes on disk.
    entries = report.get("evidence_entries") or []
    hashes = report.get("evidence_hashes") or []
    missing, mismatched = [], []
    for rel, claimed in zip(entries, hashes):
        p = Path(fixture_root) / rel
        if not p.is_file():
            missing.append(rel)
            continue
        if hash_file(p) != claimed:
            mismatched.append(rel)
    rep.check("real::evidence_exists_on_disk", not missing and bool(entries),
              "evidence claimed but not present in the target project: {}".format(
                  missing[:3]),
              code=C.BRIDGE_EMPTY_EVIDENCE)
    rep.check("real::evidence_hashes_reproduce", not mismatched,
              "evidence hash does not reproduce from the bytes on disk (tampered or "
              "stale): {}".format(mismatched[:3]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    # Evidence must belong to the TARGET project, not some other project.
    foreign = LIVE.evidence_belongs_to(entries, FX.FIXTURE_ROOT_DIRS)
    rep.check("real::evidence_belongs_to_target", not foreign,
              "evidence rooted outside the target project: {}".format(foreign[:3]),
              code=C.BRIDGE_WRONG_PROJECT)

    # 6. no machine-specific path is REQUIRED: every path came off the resolution
    #    ladder (arg/env/discovered/registry), never a baked constant.
    sources = report.get("resolution_sources") or {}
    rep.check("real::resolution_sources_recorded",
              set(sources) >= {"engine_root", "ue_cmd", "plugin_source", "fixture_root"},
              "the report must record how every path was resolved (got {})".format(
                  sorted(sources)),
              code=C.TRANSITION_HYGIENE_FAILED)
    bad_src = {k: v.get("source") for k, v in sources.items()
               if isinstance(v, dict)
               and v.get("source") not in ("arg", "env", "discovered", "registry")}
    rep.check("real::paths_parameterised", not bad_src,
              "every path must resolve from arg/env/discovery, not a baked constant "
              "(offenders: {})".format(bad_src),
              code=C.TRANSITION_HYGIENE_FAILED)
    # The report body itself must not leak a machine path into evidence.
    leaks = [e for e in entries if not LIVE._is_rel(e)]
    rep.check("real::no_machine_path_in_evidence", not leaks,
              "evidence leaks an absolute path: {}".format(leaks[:2]),
              code=C.BRIDGE_ABSOLUTE_PATH_LEAK)
    return report


def run_negatives(rep):
    """FAIL-CLOSED: every dishonest live report is rejected for its owning code."""
    ex = LIVE.example_live_report

    # (1) THE headline negative: the v2.5 DRY PROBE — the very report v2.5 shipped as
    # its "bridge gate" — submitted to the live gate. It must go RED. If this ever
    # passes, a dry probe has been laundered into a live proof.
    _, dry = GBP.build_probe_report()
    _reject_for(rep, "dry_probe_submitted_to_live_gate", dry,
                C.TRANSITION_REPORT_INTEGRITY_FAILED)
    # ...and the same dry probe with its schema_version rewritten to the live one:
    # relabelling must not be enough to pass.
    relabelled = dict(dry)
    relabelled["schema_version"] = LIVE.LIVE_SCHEMA_VERSION
    relabelled["report_type"] = LIVE.LIVE_SCHEMA_VERSION
    _reject_for(rep, "dry_probe_relabelled_as_live", relabelled,
                C.TRANSITION_REPORT_INTEGRITY_FAILED)

    # (2) process exits zero but no evidence came back.
    _reject_for(rep, "exit_zero_but_evidence_missing",
                ex(evidence_entries=[], evidence_hashes=[], evidence_count=0),
                C.BRIDGE_EMPTY_EVIDENCE)
    # ...and the subtler form: evidence_count lies about a truly empty list.
    _reject_for(rep, "evidence_count_lies",
                ex(evidence_entries=[], evidence_hashes=[], evidence_count=3),
                C.BRIDGE_EMPTY_EVIDENCE)

    # (3) wrong engine actually observed.
    _reject_for(rep, "wrong_engine_observed",
                ex(observed_runtime_engine="5.7.2-12345+++UE5+Release-5.7"),
                C.BRIDGE_WRONG_ENGINE)
    _reject_for(rep, "engine_not_observed_at_all",
                ex(observed_runtime_engine=None), C.BRIDGE_WRONG_ENGINE)

    # (4) plugin absent / present-but-not-loaded.
    _reject_for(rep, "plugin_absent",
                ex(plugin_present=False, plugin_loaded=False),
                C.BRIDGE_ABSENT_PLUGIN)
    _reject_for(rep, "plugin_present_but_not_loaded",
                ex(plugin_present=True, plugin_loaded=False),
                C.PLUGIN_LOAD_FAILED)

    # (5) operation_id mismatch end to end: the far side echoed a different id.
    _reject_for(rep, "operation_id_mismatch",
                ex(far_side_evidence={"operation_id": "op_someone_elses_9999"}),
                C.BRIDGE_OPERATION_ID_MISMATCH)

    # (6) evidence belonging to another project / leaking a machine path.
    _reject_for(rep, "evidence_absolute_path_leak",
                ex(evidence_entries=["D:/Unreal Projects/OtherProject/Content/x.uasset"],
                   evidence_hashes=["b" * 64], evidence_count=1),
                C.BRIDGE_ABSOLUTE_PATH_LEAK)

    # (7) stale evidence reused from a previous operation.
    _reject_for(rep, "stale_evidence_reused",
                ex(evidence_operation_id="op_example_0000"), C.BRIDGE_STALE_PLUGIN)

    # (8) the run never happened / never completed.
    _reject_for(rep, "runtime_not_executed", ex(runtime_executed=False),
                C.TRANSITION_REPORT_INTEGRITY_FAILED)
    _reject_for(rep, "operation_not_completed", ex(operation_completed=False),
                C.TRANSITION_REPORT_INTEGRITY_FAILED)
    _reject_for(rep, "execution_mode_dry", ex(execution_mode=LIVE.MODE_DRY),
                C.TRANSITION_REPORT_INTEGRITY_FAILED)

    # (9) capability handshake failed / empty.
    _reject_for(rep, "capability_unavailable",
                ex(plugin_capability_manifest=[
                    {"capability_id": "WorldForgeCore.MaterialRecipeDataAsset",
                     "available": False, "evidence": "ABSENT"}]),
                C.CAPABILITY_UNAVAILABLE)
    _reject_for(rep, "capability_handshake_empty",
                ex(plugin_capability_manifest=[], capability_handshake_ok=False),
                C.CAPABILITY_UNAVAILABLE)

    # (10) wrong project / unresolved commit.
    _reject_for(rep, "wrong_project_opened",
                ex(resolved_uproject="SomeOtherGame.uproject"), C.BRIDGE_WRONG_PROJECT)
    _reject_for(rep, "commit_not_resolved",
                ex(resolved_target_commit="HEAD"), C.BRIDGE_ABSENT_PLUGIN)

    # (11) the honesty breadcrumb itself: a live report may not claim Gloamstead.
    _reject_for(rep, "false_gloamstead_claim",
                ex(is_gloamstead_target=True), C.TRANSITION_HYGIENE_FAILED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5.1 LIVE bridge POSITIVE gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("gate", "gloam_bridge_live", strict=strict)
    dogfood_contract(rep)
    report = validate_real_live_report(rep)
    run_negatives(rep)
    rep.finalize()

    # This gate's own meta must mirror the run it validates: a live bridge REQUIRES a
    # runtime, and observed_runtime_engine is taken from the validated report — never
    # asserted here.
    observed = LIVE.engine_minor((report or {}).get("observed_runtime_engine"))
    rep.set_meta(build_meta(
        command="gloam-bridge-live", pack=args.pack, strict=strict,
        status=rep.status, record_count=len(rep.checks), records_total=len(rep.checks),
        report_type="wf.transition.gloam_bridge_live_gate.v1",
        extra=transition_identity(
            bridge.BRIDGE_ENGINE,
            runtime_required=True,
            runtime_executed=bool((report or {}).get("runtime_executed")),
            observed_runtime_engine=observed)))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_gloam_bridge_live_report.json")
    rep.print_summary("gloam-bridge-live")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
