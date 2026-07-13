#!/usr/bin/env python3
"""validate_gloam_bridge.py — v2.5 Gloamstead bridge gate (shield --bridge lane).

Proves the cross-repository bridge FOUNDATION is honest OFFLINE:

  1. DOGFOODS the GloamBridgeProbe contract (transition_contracts): the valid
     example passes with zero failures; the known-bad is rejected for its owning
     code BRIDGE_ABSENT_PLUGIN (WF1025).
  2. DOGFOODS the tools.bridge package: a valid request -> dry_probe report passes
     the GloamBridgeProbe contract, and the request<->response invariants hold.
  3. Validates the REAL probe report produced by gloam_bridge_probe.py, including
     the binding meta convention (declared_target_engine=5.8, runtime_executed=False)
     and project-relative evidence.
  4. NEGATIVES (inline fixtures) — each MUST be rejected for a specific WF code:
        wrong engine          -> WF1023 BRIDGE_WRONG_ENGINE
        wrong project         -> WF1024 BRIDGE_WRONG_PROJECT
        plugin absent (ready) -> WF1025 BRIDGE_ABSENT_PLUGIN
        stale evidence reused -> WF1026 BRIDGE_STALE_PLUGIN
        map missing (ready)   -> WF1027 BRIDGE_MAP_MISSING
        empty evidence        -> WF1028 BRIDGE_EMPTY_EVIDENCE
        absolute path leak    -> WF1029 BRIDGE_ABSOLUTE_PATH_LEAK
        operation_id mismatch -> WF1030 BRIDGE_OPERATION_ID_MISMATCH

GREEN iff the real dry probe passes AND every negative is rejected for its code.
v2.5 SCOPE BOUNDARY: dry probe only; the live Gloamstead fixture is a later gate.

Acceptance:
    PYTHONUTF8=1 python tools/pipeline/validate_gloam_bridge.py --strict
Report -> procedural/reports/ue5_8/gloam/validate_gloam_bridge_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import transition_contracts as TC  # noqa: E402
import bridge  # noqa: E402  (tools/bridge package)
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402
import gloam_bridge_probe as GBP  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "gloam"

_VALIDATE = TC.validate_gloam_bridge_probe
_EXAMPLE = TC._example_gloam_bridge_probe


def _fails(obj):
    """Return (failing_checks, failing_codes) for the GloamBridgeProbe contract."""
    fails = [c for c in _VALIDATE(obj, strict=True) if not c[1]]
    return fails, {c[3] for c in fails}


def _reject_for(rep, name, obj, expected_code):
    """Assert a GloamBridgeProbe fixture is rejected for expected_code."""
    fails, codes = _fails(obj)
    rep.check("negative::{}::rejected".format(name), len(fails) > 0,
              "fixture must be rejected", code=C.TRANSITION_NEGATIVE_ACCEPTED)
    rep.check("negative::{}::code".format(name), expected_code in codes,
              "must reject for {} (got {})".format(
                  expected_code, sorted(str(c) for c in codes)[:5]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)


def _reject_pair_for(rep, name, checks, expected_code):
    """Assert a request<->response invariant set rejects for expected_code."""
    fails = [c for c in checks if not c[1]]
    codes = {c[3] for c in fails}
    rep.check("negative::{}::rejected".format(name), len(fails) > 0,
              "response pair must be rejected", code=C.TRANSITION_NEGATIVE_ACCEPTED)
    rep.check("negative::{}::code".format(name), expected_code in codes,
              "must reject for {} (got {})".format(
                  expected_code, sorted(str(c) for c in codes)[:5]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)


def dogfood_contract(rep):
    """(1) The GloamBridgeProbe contract greens its valid example, rejects its bad."""
    gfails, _ = _fails(_EXAMPLE())
    rep.check("dogfood::valid_example_passes", len(gfails) == 0,
              "valid GloamBridgeProbe example rejected: {}".format(
                  [c[0] for c in gfails][:5]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    _, bad_codes = _fails(TC.CONTRACTS["GloamBridgeProbe"][2]())
    rep.check("dogfood::known_bad_rejected_owning_code",
              C.BRIDGE_ABSENT_PLUGIN in bad_codes,
              "known-bad must reject for BRIDGE_ABSENT_PLUGIN (got {})".format(
                  sorted(str(c) for c in bad_codes)[:5]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)
    # schema literal must match the contract's RT_GLOAM_BRIDGE (no drift).
    rep.check("dogfood::schema_version_matches_contract",
              bridge.BRIDGE_SCHEMA_VERSION == TC.RT_GLOAM_BRIDGE,
              "bridge schema {!r} != contract {!r}".format(
                  bridge.BRIDGE_SCHEMA_VERSION, TC.RT_GLOAM_BRIDGE),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)


def dogfood_bridge_package(rep):
    """(2) A valid request -> dry_probe report passes; the pair invariants hold."""
    req = bridge.build_request()
    report = bridge.dry_probe(req)
    gfails, _ = _fails(report)
    rep.check("bridge::dry_probe_passes_contract", len(gfails) == 0,
              "dry_probe report rejected by contract: {}".format(
                  [c[0] for c in gfails][:5]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    rep.check("bridge::dry_probe_rejected_result",
              report["probe_result"] == bridge.PROBE_RESULT_REJECTED,
              "dry probe must report rejected_dry_probe",
              code=C.BRIDGE_ABSENT_PLUGIN)
    rep.check("bridge::dry_probe_no_plugin_no_map",
              report["plugin_present"] is False and report["map_present"] is False,
              "dry probe must not claim plugin/map presence",
              code=C.BRIDGE_ABSENT_PLUGIN)
    rep.check("bridge::dry_probe_preserves_operation_id",
              report["operation_id"] == req.operation_id,
              "dry probe must preserve request operation_id",
              code=C.BRIDGE_OPERATION_ID_MISMATCH)
    resp = bridge.dry_probe_response(req)
    pair_fails = [c for c in bridge.validate_bridge_response(req, resp) if not c[1]]
    rep.check("bridge::valid_pair_invariants_hold", len(pair_fails) == 0,
              "valid request/response rejected: {}".format(
                  [c[0] for c in pair_fails][:5]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)


def validate_real_report(rep):
    """(3) The on-disk probe report passes the contract + carries the meta convention."""
    _, report = GBP.build_probe_report()
    out = GBP.REPORT_DIR / GBP.REPORT_NAME
    rep.check("real::report_written", out.is_file(),
              "run gloam_bridge_probe.py first (missing {})".format(out),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    if out.is_file():
        try:
            report = json.loads(out.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover
            rep.check("real::report_parses", False, "unparseable report: {}".format(exc),
                      code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
            return
    gfails, _ = _fails(report)
    rep.check("real::passes_contract", len(gfails) == 0,
              "on-disk probe report rejected: {}".format([c[0] for c in gfails][:5]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    meta = report.get("meta") or {}
    rep.check("real::meta_declared_engine",
              meta.get("declared_target_engine") == "5.8",
              "meta.declared_target_engine must be '5.8' (got {!r})".format(
                  meta.get("declared_target_engine")),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    rep.check("real::meta_observed_runtime_none",
              "observed_runtime_engine" in meta and meta.get("observed_runtime_engine") is None,
              "meta.observed_runtime_engine must be present and None",
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    rep.check("real::meta_runtime_not_required",
              meta.get("runtime_execution_required") is False,
              "meta.runtime_execution_required must be False (dry probe)",
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    rep.check("real::meta_runtime_not_executed",
              meta.get("runtime_executed") is False,
              "meta.runtime_executed must be False (dry probe)",
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    # every evidence path project-relative (no machine-specific leak).
    entries = report.get("evidence_entries") or []
    leaks = [e for e in entries if not (isinstance(e, str) and not bridge.probe._ABS_PATH_RE.match(e.strip()))]
    rep.check("real::evidence_project_relative", not leaks and bool(entries),
              "evidence must be non-empty and project-relative (leaks: {})".format(leaks[:2]),
              code=C.BRIDGE_ABSOLUTE_PATH_LEAK)


def run_negatives(rep):
    """(4) Every dishonest fixture is rejected for its specific WF code."""
    # -- single-object GloamBridgeProbe contract negatives --------------------
    _reject_for(rep, "wrong_engine",
                _EXAMPLE(target_engine="5.7"), C.BRIDGE_WRONG_ENGINE)
    _reject_for(rep, "wrong_project",
                _EXAMPLE(target_project="WorldForge"), C.BRIDGE_WRONG_PROJECT)
    _reject_for(rep, "plugin_absent_while_ready",
                _EXAMPLE(probe_result="ready", plugin_present=False, map_present=True),
                C.BRIDGE_ABSENT_PLUGIN)
    _reject_for(rep, "map_missing_while_ready",
                _EXAMPLE(probe_result="ready", plugin_present=True, map_present=False),
                C.BRIDGE_MAP_MISSING)
    _reject_for(rep, "exit_zero_but_evidence_missing",
                _EXAMPLE(evidence_entries=[]), C.BRIDGE_EMPTY_EVIDENCE)
    _reject_for(rep, "absolute_path_leak",
                _EXAMPLE(evidence_entries=["D:/Unreal Projects/leak/foreign_report.json"]),
                C.BRIDGE_ABSOLUTE_PATH_LEAK)

    # -- request<->response pair invariant negatives --------------------------
    req = bridge.build_request()
    # operation_id mismatch: a response minted for a different operation (WF1030).
    resp_mismatch = bridge.build_response(req, operation_id="op_v2_5_gloam_bridge_9999")
    _reject_pair_for(rep, "operation_id_mismatch",
                     bridge.validate_bridge_response(req, resp_mismatch),
                     C.BRIDGE_OPERATION_ID_MISMATCH)
    # stale evidence reused: evidence carried over from a prior operation (WF1026).
    resp_stale = bridge.build_response(
        req, evidence_paths=["procedural/reports/ue5_8/gloam/old_probe.json"],
        evidence_operation_id="op_v2_5_gloam_bridge_0000")
    _reject_pair_for(rep, "stale_evidence_reused",
                     bridge.validate_bridge_response(req, resp_stale),
                     C.BRIDGE_STALE_PLUGIN)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 Gloamstead bridge gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    # Ensure the real probe report exists (offline; no UE) before we validate it.
    GBP.main([])

    rep = ValidationReport("pack", args.pack, strict=strict)
    dogfood_contract(rep)
    dogfood_bridge_package(rep)
    validate_real_report(rep)
    run_negatives(rep)
    rep.finalize()

    rep.set_meta(build_meta(
        command="gloam-bridge", pack=args.pack, strict=strict,
        status=rep.status, record_count=len(rep.checks), records_total=len(rep.checks),
        report_type="wf.transition.gloam_bridge_gate.v1",
        extra={
            "declared_target_engine": bridge.BRIDGE_ENGINE,
            "observed_runtime_engine": None,
            "runtime_execution_required": False,
            "runtime_executed": False,
        }))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_gloam_bridge_report.json")
    rep.print_summary("gloam-bridge")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
