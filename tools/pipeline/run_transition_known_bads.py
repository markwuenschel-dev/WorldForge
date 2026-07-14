#!/usr/bin/env python3
"""run_transition_known_bads.py — v2.5 on-disk known-bad fixture harness.

Complements transition_negatives.py (which proves the band in-code) by materializing the
mission's hostile scenario list as ON-DISK JSON fixtures under procedural/known_bads/v2_5/,
then running the correct contract validator against each and asserting it is REJECTED for the
fixture's declared expected code. On-disk fixtures make the hostile catalogue auditable and
reusable by the torture harness and future waves.

Fixtures are MACHINE-GENERATED (deterministic) by this tool — they are known-BADS, not
proof-of-pass, so generating them here is legitimate. Each fixture file carries its own
`_expected_code` and `_contract` so the harness is self-describing.

GREEN when every fixture is rejected for its expected code. RED (TRANSITION_NEGATIVE_ACCEPTED)
if any fixture is accepted or rejected for the wrong code.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/run_transition_known_bads.py --strict
Reports -> procedural/reports/ue5_8/hostile/run_transition_known_bads_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "procedural" / "known_bads" / "v2_5"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "hostile"

# contract name -> validator, for fixtures that ride a real contract validator.
VALIDATORS = {
    "EngineIdentity": TC.validate_engine_identity,
    "CapabilityManifest": TC.validate_capability_manifest,
    "ConversionManifest": TC.validate_conversion_manifest,
    "PluginBuildReport": TC.validate_plugin_build_report,
    "TransitionRegressionReport": TC.validate_transition_regression_report,
    "GloamBridgeProbe": TC.validate_gloam_bridge_probe,
    "TransitionBaseline": TC.validate_transition_baseline,
}


def _fixtures():
    """The mission hostile catalogue as (slug, contract, record, expected_code)."""
    e = TC
    f = []
    # runtime-free report mislabeled as observed UE 5.8 — a baseline entry that claims 5.8 but
    # is sourced from the frozen 5.7 tree (evidence copied from old engine).
    f.append(("runtime_free_mislabeled_as_5_8", "TransitionBaseline",
              e._example_transition_baseline(entry_count=1, entries=[
                  {"report_path": "procedural/reports/ue5_7/spine.json", "engine_minor": 8,
                   "report_type": e.RT_ENGINE_IDENTITY}]), C.EVIDENCE_COPIED_FROM_OLD_ENGINE))
    # UE 5.7 report copied into a UE 5.8 baseline (5.7 contamination).
    f.append(("ue57_report_in_ue58_baseline", "TransitionBaseline",
              e._example_transition_baseline(entry_count=1, entries=[
                  {"report_path": "procedural/reports/ue5_8/x.json", "engine_minor": 7,
                   "report_type": e.RT_PLUGIN_BUILD}]), C.EVIDENCE_5_7_CONTAMINATION))
    # stale plugin DLL: overall_ok claimed but binary older than source.
    f.append(("stale_plugin_dll", "PluginBuildReport",
              e._example_plugin_build_report(overall_ok=True, binary_mtime=100,
                                             newest_source_mtime=200), C.STALE_PLUGIN_BINARY))
    # plugin DLL newer than report but older than source — same stale code path.
    f.append(("plugin_dll_predates_source", "PluginBuildReport",
              e._example_plugin_build_report(overall_ok=True, binary_mtime=150,
                                             newest_source_mtime=175), C.STALE_PLUGIN_BINARY))
    # wrong project opened by the bridge (not Gloamstead).
    f.append(("wrong_project_opened", "GloamBridgeProbe",
              e._example_gloam_bridge_probe(target_project="SomeOtherProject"),
              C.BRIDGE_WRONG_PROJECT))
    # wrong map: bridge claims ready but map not present.
    f.append(("wrong_map_opened", "GloamBridgeProbe",
              e._example_gloam_bridge_probe(probe_result="ready", plugin_present=True,
                                            map_present=False), C.BRIDGE_MAP_MISSING))
    # missing conversion asset: manifest incomplete (fewer maps than expected).
    f.append(("missing_conversion_asset", "ConversionManifest",
              e._example_conversion_manifest(expected_map_count=9),
              C.CONVERSION_MANIFEST_INCOMPLETE))
    # actor count silently decreases with no accounted deletion.
    f.append(("actor_count_silent_decrease", "ConversionManifest",
              e._example_conversion_manifest(expected_map_count=1, maps=[
                  {"map_path": "Content/Maps/encounter_loop_world.umap", "actors_before": 214,
                   "actors_after": 213, "accounted_deletions": 0,
                   "churn_class": "expected_resave"}]), C.CONVERSION_ACTOR_LOSS))
    # successful exit with missing evidence — bridge with empty evidence list.
    f.append(("success_exit_missing_evidence", "GloamBridgeProbe",
              e._example_gloam_bridge_probe(evidence_entries=[]), C.BRIDGE_EMPTY_EVIDENCE))
    # baseline references a report drawn from the frozen 5.7 tree (stale/old-engine).
    f.append(("baseline_references_stale_report", "TransitionBaseline",
              e._example_transition_baseline(entry_count=1, entries=[
                  {"report_path": "procedural/reports/ue5_7/regression/old.json",
                   "engine_minor": 8, "report_type": e.RT_REGRESSION}]),
              C.EVIDENCE_COPIED_FROM_OLD_ENGINE))
    # bridge returns foreign evidence via an absolute machine path leak.
    f.append(("bridge_foreign_evidence_abs_path", "GloamBridgeProbe",
              e._example_gloam_bridge_probe(evidence_entries=["C:/Other/Machine/ev.json"]),
              C.BRIDGE_ABSOLUTE_PATH_LEAK))
    # absolute path leak in a conversion map path.
    f.append(("absolute_path_leak_conversion", "ConversionManifest",
              e._example_conversion_manifest(expected_map_count=1, maps=[
                  {"map_path": "D:/Unreal Projects/WorldForge/Content/Maps/x.umap",
                   "actors_before": 10, "actors_after": 10, "accounted_deletions": 0,
                   "churn_class": "none"}]), C.CONVERSION_MANIFEST_INCOMPLETE))
    # unknown regression classification.
    f.append(("unknown_regression_classification", "TransitionRegressionReport",
              e._example_transition_regression_report(regression_free=True, diffs=[
                  {"map_path": "Content/Maps/x.umap", "classification": "unclassified"}]),
              C.REGRESSION_UNCLASSIFIED_DIFF))
    # binary churn not present in the conversion manifest — unexpected churn class.
    f.append(("binary_churn_not_in_manifest", "ConversionManifest",
              e._example_conversion_manifest(expected_map_count=1, maps=[
                  {"map_path": "Content/Maps/encounter_loop_world.umap", "actors_before": 214,
                   "actors_after": 214, "accounted_deletions": 0, "churn_class": "unexpected"}]),
              C.CONVERSION_UNEXPECTED_CHURN))
    # wrong engine for the whole transition edge.
    f.append(("wrong_engine_identity", "EngineIdentity",
              e._example_engine_identity(engine_minor=6), C.ENGINE_VERSION_MISMATCH))
    # required capability unavailable.
    f.append(("required_capability_unavailable", "CapabilityManifest",
              e._example_capability_manifest(capabilities=[
                  {"capability_id": "WorldForgeRuntime", "kind": "plugin_module",
                   "required": True, "available": False, "required_version": "2.5.0",
                   "actual_version": None}]), C.CAPABILITY_UNAVAILABLE))
    return f


def materialize(f):
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for slug, contract, record, code in f:
        doc = dict(record)
        doc["_contract"] = contract
        doc["_expected_code"] = str(code)
        doc["_slug"] = slug
        (FIXTURE_DIR / (slug + ".json")).write_text(json.dumps(doc, indent=2), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 on-disk known-bad fixture harness.")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--no-regen", action="store_true", help="validate existing fixtures only")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    f = _fixtures()
    if not args.no_regen:
        materialize(f)

    rep = ValidationReport("suite", "transition_known_bads", strict=strict)
    n = 0
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        contract = doc.get("_contract")
        expected = doc.get("_expected_code")
        validate = VALIDATORS.get(contract)
        n += 1
        if validate is None:
            rep.check("kb::{}::known_contract".format(path.stem), False,
                      "fixture names unknown contract {!r}".format(contract),
                      code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
            continue
        record = {k: v for k, v in doc.items() if not k.startswith("_")}
        fails = [ck for ck in validate(record, strict=True) if not ck[1]]
        codes = {str(ck[3]) for ck in fails}
        rep.check("kb::{}::rejected".format(path.stem), len(fails) > 0,
                  "on-disk known-bad was ACCEPTED (fake green)",
                  code=C.TRANSITION_NEGATIVE_ACCEPTED)
        rep.check("kb::{}::owning_code".format(path.stem), expected in codes,
                  "must be rejected for {} (got {})".format(expected, sorted(codes)[:4]),
                  code=C.TRANSITION_NEGATIVE_ACCEPTED)

    rep.check("kb::catalogue_nonempty", n >= 16,
              "known-bad catalogue must carry >= 16 fixtures (got {})".format(n),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="transition-known-bads", pack=None, strict=strict, status=rep.status,
        record_count=n, records_total=n, report_type="wf.transition.known_bads.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "run_transition_known_bads_report.json")
    rep.print_summary("transition-known-bads")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
