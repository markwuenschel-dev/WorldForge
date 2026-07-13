#!/usr/bin/env python3
"""transition_negatives.py — v2.5 UE58TransitionForge hostile negative-fixture gate.

The shield ``--hostile`` ``transition-negatives`` lane. Proves the UE 5.7 -> 5.8
transition schema spine REJECTS known-bad records — each for its OWNING failure code,
because a validator that fails for the wrong reason is not real coverage.

Two obligations:
  1. For EVERY contract in transition_contracts.CONTRACTS, its registered known-bad is
     rejected for its owning code (KNOWN_BAD_OWNING_CODE).
  2. EVERY failure code in the WF1011-1033 band has at least one OWNING known-bad that is
     rejected for exactly that code. Most are produced by the contract validators; the two
     cross-artifact codes the schema validators cannot emit on their own — WF1026
     (BRIDGE_STALE_PLUGIN) and WF1030 (BRIDGE_OPERATION_ID_MISMATCH) — get minimal
     supplemental negative validators here.

GREEN when every known-bad is rejected for its owning code AND every valid example still
passes (a validator that greens its known-bad or reddens its valid example is a fake-green
vector). RED (TRANSITION_NEGATIVE_ACCEPTED) if any known-bad is ACCEPTED.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/transition_negatives.py --strict
Reports -> procedural/reports/ue5_8/hostile/transition_negatives_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "hostile"

# Short aliases for the seven contract validators.
ID = TC.validate_engine_identity
CAP = TC.validate_capability_manifest
CV = TC.validate_conversion_manifest
PB = TC.validate_plugin_build_report
RG = TC.validate_transition_regression_report
BR = TC.validate_gloam_bridge_probe
BL = TC.validate_transition_baseline


# --------------------------------------------------------------------------- #
# Supplemental negative validators — codes the schema-only contract validators
# cannot emit because they need a cross-artifact fact (plugin binary age vs a
# bridge readiness claim; the operation-id a probe was issued under). Each is a
# minimal honesty check in the exact (name, ok, detail, code) shape.
# --------------------------------------------------------------------------- #
def _neg_bridge_stale_plugin(rec, strict=False):
    """A bridge that claims 'ready' with a plugin binary older than its source (WF1026)."""
    result = rec.get("probe_result")
    bmt, smt = rec.get("plugin_binary_mtime"), rec.get("plugin_source_mtime")
    stale = (result == "ready"
             and isinstance(bmt, (int, float)) and not isinstance(bmt, bool)
             and isinstance(smt, (int, float)) and not isinstance(smt, bool)
             and bmt < smt)
    return [("br::ready_plugin_not_stale", not stale,
             "bridge claims ready with a stale plugin binary (mtime {} < source {})".format(bmt, smt),
             C.BRIDGE_STALE_PLUGIN)]


def _neg_bridge_operation_id(rec, strict=False):
    """A bridge probe whose operation_id != the operation it was issued for (WF1030)."""
    op, exp = rec.get("operation_id"), rec.get("expected_operation_id")
    ok = isinstance(op, str) and isinstance(exp, str) and bool(op) and op == exp
    return [("br::operation_id_matches", ok,
             "bridge operation_id {!r} does not match issued operation {!r}".format(op, exp),
             C.BRIDGE_OPERATION_ID_MISMATCH)]


def _ex_bridge(**over):
    """A minimal bridge-adjacent record for the supplemental validators."""
    d = {"probe_result": "rejected_dry_probe", "plugin_binary_mtime": 200,
         "plugin_source_mtime": 100, "operation_id": "op_v2_5_gloam_bridge_0001",
         "expected_operation_id": "op_v2_5_gloam_bridge_0001"}
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# The owning known-bad per failure code (WF1011-1033). Each entry:
#   (code_label, validator, bad_record, owning_code)
# --------------------------------------------------------------------------- #
def cases():
    e = TC
    c = []
    # -- capability (1011-1012) --
    c.append(("WF1011_capability_unavailable", CAP, e._example_capability_manifest(capabilities=[
        {"capability_id": "WorldForgeRuntime", "kind": "plugin_module", "required": True,
         "available": False, "required_version": "2.5.0", "actual_version": None}]),
        C.CAPABILITY_UNAVAILABLE))
    c.append(("WF1012_capability_version_mismatch", CAP, e._example_capability_manifest(capabilities=[
        {"capability_id": "WorldForgeRuntime", "kind": "plugin_module", "required": True,
         "available": True, "required_version": "2.5.0", "actual_version": "2.4.0"}]),
        C.CAPABILITY_VERSION_MISMATCH))
    # -- engine (1013) --
    c.append(("WF1013_engine_version_mismatch", ID, e._example_engine_identity(engine_major=4),
              C.ENGINE_VERSION_MISMATCH))
    # -- conversion (1014-1016) --
    c.append(("WF1014_conversion_actor_loss", CV, e._example_conversion_manifest(
        expected_map_count=1, maps=[{"map_path": "Content/Maps/encounter_loop_world.umap",
        "actors_before": 214, "actors_after": 210, "accounted_deletions": 0,
        "churn_class": "expected_resave"}]), C.CONVERSION_ACTOR_LOSS))
    c.append(("WF1015_conversion_manifest_incomplete", CV,
              e._example_conversion_manifest(expected_map_count=5), C.CONVERSION_MANIFEST_INCOMPLETE))
    c.append(("WF1016_conversion_unexpected_churn", CV, e._example_conversion_manifest(
        expected_map_count=1, maps=[{"map_path": "Content/Maps/encounter_loop_world.umap",
        "actors_before": 214, "actors_after": 214, "accounted_deletions": 0,
        "churn_class": "unexpected"}]), C.CONVERSION_UNEXPECTED_CHURN))
    # -- plugin build (1017-1019) --
    c.append(("WF1017_build_failed", PB, e._example_plugin_build_report(
        overall_ok=True, build_result="failed"), C.BUILD_FAILED))
    c.append(("WF1018_plugin_load_failed", PB, e._example_plugin_build_report(
        overall_ok=True, plugin_loaded=False, build_result="succeeded"), C.PLUGIN_LOAD_FAILED))
    c.append(("WF1019_stale_plugin_binary", PB, e._example_plugin_build_report(
        overall_ok=True, binary_mtime=100, newest_source_mtime=200), C.STALE_PLUGIN_BINARY))
    # -- regression (1020-1022) --
    c.append(("WF1020_map_load_failed", RG, e._example_transition_regression_report(
        regression_free=True, maps_loaded=20, maps_checked=24), C.MAP_LOAD_FAILED))
    c.append(("WF1021_regression_unclassified_diff", RG, e._example_transition_regression_report(
        regression_free=True, diffs=[{"map_path": "Content/Maps/x.umap",
        "classification": "unclassified"}]), C.REGRESSION_UNCLASSIFIED_DIFF))
    c.append(("WF1022_regression_worldforge_regression", RG, e._example_transition_regression_report(
        regression_free=True, diffs=[{"map_path": "Content/Maps/x.umap",
        "classification": "worldforge_regression"}]), C.REGRESSION_WORLDFORGE_REGRESSION))
    # -- bridge (1023-1030) --
    c.append(("WF1023_bridge_wrong_engine", BR, e._example_gloam_bridge_probe(target_engine="5.7"),
              C.BRIDGE_WRONG_ENGINE))
    c.append(("WF1024_bridge_wrong_project", BR, e._example_gloam_bridge_probe(
        target_project="WorldForge"), C.BRIDGE_WRONG_PROJECT))
    c.append(("WF1025_bridge_absent_plugin", BR, e._example_gloam_bridge_probe(
        probe_result="ready", plugin_present=False, map_present=True), C.BRIDGE_ABSENT_PLUGIN))
    c.append(("WF1026_bridge_stale_plugin", _neg_bridge_stale_plugin, _ex_bridge(
        probe_result="ready", plugin_binary_mtime=100, plugin_source_mtime=200),
        C.BRIDGE_STALE_PLUGIN))
    c.append(("WF1027_bridge_map_missing", BR, e._example_gloam_bridge_probe(
        probe_result="ready", plugin_present=True, map_present=False), C.BRIDGE_MAP_MISSING))
    c.append(("WF1028_bridge_empty_evidence", BR, e._example_gloam_bridge_probe(evidence_entries=[]),
              C.BRIDGE_EMPTY_EVIDENCE))
    c.append(("WF1029_bridge_absolute_path_leak", BR, e._example_gloam_bridge_probe(
        evidence_entries=["D:/UnrealProjects/leak.json"]), C.BRIDGE_ABSOLUTE_PATH_LEAK))
    c.append(("WF1030_bridge_operation_id_mismatch", _neg_bridge_operation_id, _ex_bridge(
        operation_id="op_wrong", expected_operation_id="op_v2_5_gloam_bridge_0001"),
        C.BRIDGE_OPERATION_ID_MISMATCH))
    # -- evidence / baseline (1031-1033) --
    c.append(("WF1031_evidence_engine_mismatch", BL, e._example_transition_baseline(
        entry_count=1, entries=[{"report_path": "procedural/reports/ue5_8/x.json",
        "engine_minor": 6, "report_type": e.RT_PLUGIN_BUILD}]), C.EVIDENCE_ENGINE_MISMATCH))
    c.append(("WF1032_evidence_5_7_contamination", BL, e._example_transition_baseline(
        entry_count=1, entries=[{"report_path": "procedural/reports/ue5_8/x.json",
        "engine_minor": 7, "report_type": e.RT_PLUGIN_BUILD}]), C.EVIDENCE_5_7_CONTAMINATION))
    c.append(("WF1033_evidence_copied_from_old_engine", BL, e._example_transition_baseline(
        entry_count=1, entries=[{"report_path": "procedural/reports/ue5_7/x.json",
        "engine_minor": 8, "report_type": e.RT_PLUGIN_BUILD}]), C.EVIDENCE_COPIED_FROM_OLD_ENGINE))
    return c


# The WF1011-1033 band this gate must fully cover with owning known-bads.
def _band_codes():
    band = []
    for v in vars(C).values():
        if isinstance(v, str) and v.startswith("WF10"):
            try:
                n = int(v[2:6])
            except ValueError:
                continue
            if 1011 <= n <= 1033:
                band.append(v)
    return sorted(set(band))


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 transition negative-fixture gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "transition_negatives", strict=strict)
    cs = cases()

    # 1. Every contract's registered known-bad is rejected for its owning code.
    for name, (validate, good, bad) in TC.CONTRACTS.items():
        fails = [ck for ck in validate(bad(), strict=True) if not ck[1]]
        codes = {ck[3] for ck in fails}
        owning = TC.KNOWN_BAD_OWNING_CODE.get(name)
        rep.check("contract::{}::known_bad_rejected".format(name), len(fails) > 0,
                  "contract known-bad was ACCEPTED (fake green)", code=C.TRANSITION_NEGATIVE_ACCEPTED)
        rep.check("contract::{}::owning_code".format(name), owning in codes,
                  "must be rejected for {} (got {})".format(owning, sorted(str(x) for x in codes)[:4]),
                  code=C.TRANSITION_NEGATIVE_ACCEPTED)
        # ...and its valid example still passes (reverse dogfood).
        gfails = [ck for ck in validate(good(), strict=True) if not ck[1]]
        rep.check("contract::{}::valid_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([ck[0] for ck in gfails][:4]),
                  code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    # 2. Every WF1011-1033 code has an owning known-bad rejected for exactly that code.
    covered = set()
    for label, validate, bad, owning in cs:
        fails = [ck for ck in validate(bad, strict=True) if not ck[1]]
        codes = {ck[3] for ck in fails}
        rep.check("neg::{}::rejected".format(label), len(fails) > 0,
                  "known-bad fixture was ACCEPTED (fake green)", code=C.TRANSITION_NEGATIVE_ACCEPTED)
        rep.check("neg::{}::owning_code".format(label), owning in codes,
                  "must be rejected for {} (got {})".format(owning, sorted(str(x) for x in codes)[:4]),
                  code=C.TRANSITION_NEGATIVE_ACCEPTED)
        if owning in codes:
            covered.add(owning)

    band = _band_codes()
    missing = [c for c in band if c not in covered]
    rep.check("neg::band_coverage_complete", not missing,
              "WF1011-1033 codes with no owning known-bad: {}".format(missing),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)
    rep.check("neg::suite_nonempty", len(cs) >= 23,
              "negative suite must carry >= 23 owning fixtures (got {})".format(len(cs)),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="transition-negatives", pack=None, strict=strict, status=rep.status,
        record_count=len(cs), records_total=len(cs), report_type="wf.transition.negatives.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "transition_negatives_report.json")
    rep.print_summary("transition-negatives")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
