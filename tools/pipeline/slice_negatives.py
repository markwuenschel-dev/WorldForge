#!/usr/bin/env python3
"""slice_negatives.py — v2.0 Agent-7 hostile negative-fixture suite.

Proves the slice schema spine REJECTS known-bad records — and rejects each one
for its OWNING failure code, because a validator that fails for the wrong reason
is not real coverage. Fixtures are generated in-code (no stored files): each is a
canonical slice_contracts._example_* with a single targeted override that
violates exactly one honesty invariant.

Two assertions per fixture: (1) the record IS rejected, and (2) it is rejected
for its owning WF6xx code. Plus a reverse dogfood (every valid example still
passes — guards against a "reject everything" fake) and a vacuous-suite guard.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/slice_negatives.py --strict
Reports -> procedural/reports/slice/negatives/slice_negatives_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import slice_contracts as SX
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "slice" / "negatives"

VSC = SX.validate_vertical_slice_contract
SCN = SX.validate_slice_scenario
MAN = SX.validate_slice_manifest
RUN = SX.validate_slice_runtime_report
PKG = SX.validate_slice_package_report
IDX = SX.validate_slice_evidence_index


def cases():
    """Return [(label, validate_fn, known_bad_record, owning_failure_code), ...]."""
    c = []
    e_vsc = SX._example_vertical_slice_contract
    e_scn = SX._example_slice_scenario
    e_man = SX._example_slice_manifest
    e_run = SX._example_slice_runtime_report
    e_pkg = SX._example_slice_package_report
    e_idx = SX._example_slice_evidence_index

    # --- VerticalSliceContract ---
    c.append(("vsc:count_not_matrix_product", VSC, e_vsc(scenario_count=99),
              F.SLICE_SCENARIO_SET_INVALID))
    c.append(("vsc:duplicate_biome", VSC, e_vsc(biomes=["desert", "desert"], scenario_count=24),
              F.SLICE_CONTRACT_INVALID))
    c.append(("vsc:requires_flag_not_bool", VSC, e_vsc(requires_combat="yes"),
              F.SLICE_CONTRACT_INVALID))
    c.append(("vsc:empty_biomes", VSC, e_vsc(biomes=[], scenario_count=0),
              F.SLICE_CONTRACT_INVALID))
    c.append(("vsc:wrong_schema_version", VSC, e_vsc(schema_version="wf.slice.bogus.v9"),
              F.SLICE_CONTRACT_INVALID))

    # --- SliceScenario ---
    c.append(("scn:missing_route_binding", SCN, e_scn(expected_route_id=None),
              F.SLICE_ROUTE_BINDING_INVALID))
    c.append(("scn:missing_reward_binding", SCN, e_scn(expected_reward_table_id=None),
              F.SLICE_REWARD_TABLE_BINDING_INVALID))
    c.append(("scn:missing_map_id", SCN, e_scn(map_id=None),
              F.SLICE_SCENARIO_INVALID))

    # --- SliceManifest ---
    c.append(("man:duplicate_scenarios", MAN, e_man(
        scenarios=["vs_a", "vs_a"]), F.SLICE_DUPLICATE_SCENARIO_REPORT))
    c.append(("man:count_mismatch", MAN, e_man(scenario_count=5),
              F.SLICE_MANIFEST_INVALID))

    # --- SliceRuntimeReport (the honesty spine) ---
    c.append(("run:completed_no_state_mutation", RUN,
              e_run(inventory_mutated=False, progression_mutated=False),
              F.SLICE_REWARD_WITHOUT_MUTATION))
    c.append(("run:completed_forbidden_save_slot", RUN,
              e_run(save_slot="WFCombat_State"), F.SLICE_SAVE_LOAD_WRONG_SLOT))
    c.append(("run:completed_save_load_failed", RUN,
              e_run(save_load_result="failed"), F.SLICE_SAVE_LOAD_FAILED))
    c.append(("run:completed_mission_incomplete", RUN,
              e_run(mission_completed=False), F.SLICE_MISSION_INCOMPLETE))
    c.append(("run:completed_no_combat_damage", RUN,
              e_run(combat_damage_seen=False), F.SLICE_NPC_NO_DAMAGE))
    c.append(("run:completed_no_traversal", RUN,
              e_run(traversal_completed=False), F.SLICE_TRAVERSAL_MISSING))
    c.append(("run:completed_no_npc", RUN,
              e_run(npc_behavior_seen=False), F.SLICE_NPC_EVIDENCE_MISSING))
    c.append(("run:completed_not_launched", RUN,
              e_run(launched=False), F.SLICE_LAUNCH_FAILED))
    c.append(("run:completed_with_failure_codes", RUN,
              e_run(failure_codes=["WF677_SLICE_LAUNCH_FAILED"]), F.SLICE_PARTIAL_MATRIX))
    c.append(("run:completed_no_telemetry", RUN,
              e_run(telemetry_paths=[]), F.SLICE_TRAVERSAL_MISSING))
    c.append(("run:incomplete_but_no_failure_codes", RUN,
              e_run(slice_completed_runtime=False, failure_codes=[]),
              F.SLICE_RUNTIME_REPORT_MISSING))

    # --- SlicePackageReport ---
    c.append(("pkg:pass_but_no_package", PKG,
              e_pkg(package_exists=False, package_size_bytes=0),
              F.SLICE_PACKAGE_MISSING))
    c.append(("pkg:exists_but_zero_size", PKG,
              e_pkg(package_exists=True, package_size_bytes=0),
              F.SLICE_PACKAGE_MISSING))
    c.append(("pkg:live_without_real_sha", PKG,
              e_pkg(git_sha="unknown"), F.SLICE_STALE_EVIDENCE))
    c.append(("pkg:no_maps_included", PKG,
              e_pkg(maps_included=[]), F.SLICE_BUILD_MANIFEST_INVALID))

    # --- SliceEvidenceIndex ---
    c.append(("idx:partial_matrix", IDX, e_idx(scenario_count_expected=2),
              F.SLICE_PARTIAL_MATRIX))
    c.append(("idx:stale_evidence_present", IDX,
              e_idx(stale_evidence=["vs_desert_reach_objective_baseline_s1"]),
              F.SLICE_STALE_EVIDENCE))
    c.append(("idx:missing_evidence_present", IDX,
              e_idx(missing_evidence=["vs_desert_reach_objective_baseline_s1"]),
              F.SLICE_PARTIAL_MATRIX))
    # coverage by DUPLICATE ids is not coverage: seen==expected but the category
    # lists are the same id repeated, so distinct count < expected (the C1 hole).
    c.append(("idx:duplicate_ids_not_coverage", IDX,
              e_idx(scenario_count_expected=2, scenario_count_seen=2,
                    runtime_reports=["s", "s"], traversal_reports=["s", "s"],
                    npc_reports=["s", "s"], combat_reports=["s", "s"],
                    reward_reports=["s", "s"], save_load_reports=["s", "s"]),
              F.SLICE_PARTIAL_MATRIX))
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.0 slice hostile negative fixtures.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "slice_negatives", strict=strict)
    cs = cases()
    rep.check("neg::case_count_nonzero", len(cs) > 0,
              "negative suite must not be vacuous", code=F.SLICE_NEGATIVE_ACCEPTED)

    for label, fn, bad, code in cs:
        fails = [c for c in fn(bad, strict=True) if not c[1]]
        codes = {c[3] for c in fails}
        rep.check("neg::{}::rejected".format(label), len(fails) > 0,
                  "known-bad '{}' must be rejected".format(label),
                  code=F.SLICE_NEGATIVE_ACCEPTED)
        rep.check("neg::{}::owning_code".format(label), code in codes,
                  "'{}' must be rejected for owning code {} (got {})".format(
                      label, code, sorted(str(x) for x in codes)[:5]),
                  code=F.SLICE_NEGATIVE_ACCEPTED)

    # reverse dogfood: every valid example still passes (no reject-everything fake).
    for name, (validate, good, _bad) in SX.CONTRACTS.items():
        gfails = [c for c in validate(good(), strict=True) if not c[1]]
        rep.check("pos::{}::valid_example_passes".format(name), len(gfails) == 0,
                  "valid example rejected: {}".format([c[0] for c in gfails][:4]),
                  code=F.SLICE_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="slice-negative-validators", pack=None, strict=strict,
        status=rep.status, record_count=len(cs), records_total=len(cs),
        report_type="wf.slice.negatives.v1"))
    rep.write(REPORT_DIR, "slice_negatives_report.json")
    rep.print_summary("slice-negative-validators")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
