#!/usr/bin/env python3
"""run_v2_5_1_known_bads.py — v2.5.1 hostile fixture harness for the two weaknesses
v2.5 shipped: unearned conversion claims, and a DRY PROBE standing in for a live bridge.

Complements run_transition_known_bads.py (the v2.5 catalogue, which rides the frozen
``transition_contracts`` validators) by attacking the v2.5.1 evidence surfaces —
the canonical conversion manifest, the map-census reconciliation, the LIVE bridge
report, and report integrity itself.

WHAT MAKES A FIXTURE HONEST HERE
--------------------------------
Every fixture is driven through a REAL validator — the same function the shield's own
gate calls, imported and invoked, never a reimplementation. A fixture is only counted
as proven when it is:

    1. REJECTED at all                                (else: a fake green)
    2. rejected FOR ITS OWNING FAILURE CODE           (else: rejected by accident)
    3. rejected BY ITS OWNING CHECK, where named      (else: rejected by collateral noise)

(3) is the rail (1)+(2) alone cannot hold. A dishonest report typically trips many
checks; asserting only the code lets a fixture "pass" on a rejection that has nothing
to do with the vector it claims to cover. Naming the owning check pins each fixture to
the rail that is actually supposed to catch it.

POSITIVE CONTROLS. A rejecter that rejects everything proves nothing, so each driver
must also ACCEPT the honest artifact (``control::*`` checks below). Rejection is only
evidence when acceptance is possible.

FIXTURES ARE PURE ARTIFACTS. Unlike the v2.5 catalogue, no ``_expected_code``/``_contract``
keys are embedded in the fixture files. The LIVE bridge contract enforces
``live::no_unknown_fields``, so an embedded harness key would get the fixture rejected
for CARRYING HARNESS METADATA rather than for its vector — a rejection that proves
nothing while looking green. Each fixture file is therefore byte-for-byte what a
dishonest submitter would actually present, and the catalogue metadata lives beside it
in ``index.json``.

VECTORS (9) — all codes pre-existing, from the WF1011-1039 transition band; none added.

    synthetic audit report presented as real   -> WF1015  audit::real_manifest
    disjoint manifest keyspaces                -> WF1015  audit::common_keyspace
    map-count discrepancy w/o classifications  -> WF1021  present::no_unclassified_entries
    identical versions labelled as an upgrade  -> WF1021  audit::unclassified_packages_zero
    dry bridge probe satisfying the live gate  -> WF1034  (live contract)
    zero-exit bridge with no evidence          -> WF1028  (live contract)
    foreign-project evidence                   -> WF1024  real::evidence_belongs_to_target
    stale evidence reuse                       -> WF1026  (live contract)
    manually modified audit report             -> WF1034  manual_edit_ok_with_failures

GREEN when every fixture is rejected by its owning check for its owning code, and every
driver still accepts the honest artifact. RED (WF1035 TRANSITION_NEGATIVE_ACCEPTED)
otherwise.

This harness never writes to another lane's report path: the gate functions it calls are
pure (they take a ValidationReport and do not persist), and the only file this tool
writes is its own report.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/run_v2_5_1_known_bads.py --strict
Reports -> procedural/reports/ue5_8/hostile/run_v2_5_1_known_bads_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import audit_conversion_diff as ACD  # noqa: E402
import gloam_bridge_probe as GBP  # noqa: E402  (the v2.5 DRY probe — the headline bad)
import transition_report_integrity as TRI  # noqa: E402
import validate_conversion_audit as VCA  # noqa: E402  (Lane 3's REAL gate)
import validate_gloam_bridge_live as VGBL  # noqa: E402  (Lane 4's REAL gate)
import validate_map_census_reconciliation as VMCR  # noqa: E402  (Lane 2's REAL gate)
from bridge import live as LIVE  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from transition_identity import transition_identity  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "procedural" / "known_bads" / "v2_5_1"
INDEX_PATH = FIXTURE_DIR / "index.json"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "hostile"

# --------------------------------------------------------------------------- #
# Canonical-manifest fixture shapes.
#
# UE 5.7 and UE 5.8 ship the IDENTICAL package version (FileVersionUE5=1018), so
# _V57/_V58 differ only in the custom-version container and the engine stamp —
# the same shape the real corpus carries.
# --------------------------------------------------------------------------- #
_V57 = {"file_version_ue4": 522, "file_version_ue5": 1018, "legacy": -9, "licensee": 0,
        "custom_versions": {"86181d60844f64acded316aad6c7ea0d": 225},
        "saved_by_engine_branch": "5.7"}
_V58 = {"file_version_ue4": 522, "file_version_ue5": 1018, "legacy": -9, "licensee": 0,
        "custom_versions": {"86181d60844f64acded316aad6c7ea0d": 268},
        "saved_by_engine_branch": "5.8"}


def _pkg(path, **over):
    """A canonical-shaped, fully-evidenced package record (both sides populated)."""
    d = {"package_path": path, "asset_class": "map", "conversion_status": "present_both",
         "source_hash": "a" * 64, "converted_hash": "b" * 64,
         "source_engine": "5.7", "converted_engine": "5.8",
         "source_package_version": dict(_V57), "converted_package_version": dict(_V58),
         "actor_count": {"source": 3, "converted": 3},
         "actor_class_inventory": {"source": {"StaticMeshActor": 3},
                                   "converted": {"StaticMeshActor": 3}},
         "component_count": None, "critical_references": None, "classification": None}
    d.update(over)
    return d


def _manifest(pkgs, **over):
    """A canonical-shaped manifest wrapper."""
    d = {"schema_version": ACD.CANONICAL_SCHEMA, "report_type": ACD.CANONICAL_SCHEMA,
         "keyspace": ACD.CANONICAL_KEYSPACE, "package_count": len(pkgs),
         "source_engine": "5.7", "target_engine": "5.8", "packages": pkgs,
         "meta": {"git_sha": "c" * 40, "record_count": len(pkgs)}}
    d.update(over)
    return d


def _clean_gate_report(**over):
    """A well-formed, untampered ValidationReport-shaped artifact."""
    d = {"status": "ok", "failures": [],
         "checks": {"audit::no_actor_loss": {"verdict": "PASS", "detail": ""}},
         "meta": {"git_sha": "d" * 40, "timestamp": "2026-07-14T00:00:00+00:00",
                  "report_type": "wf.transition.conversion_audit_gate.v1",
                  "records_total": 1, "records_passed": 1, "records_failed": 0,
                  "records_skipped": 0, "declared_target_engine": "5.8",
                  "observed_runtime_engine": None,
                  "runtime_execution_required": False, "runtime_executed": False}}
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# The catalogue. (slug, driver, doc, expected_code, expected_check, vector)
# expected_check=None where the driver reports contract-level checks whose names
# are not a stable public surface; the owning CODE then carries the assertion.
# --------------------------------------------------------------------------- #
def _fixtures():
    ex = LIVE.example_live_report
    f = []

    # (1) A synthetic manifest dressed as the real canonical artifact: right schema,
    # right keyspace, real-looking records — but meta.git_sha is absent, so it was
    # never PRODUCED by the builder. Evidence you cannot trace to a commit is not
    # evidence, and a hand-rolled toy must never green the conversion gate.
    f.append((
        "synthetic_audit_presented_as_real", "conversion_audit_gate",
        _manifest([_pkg("/Game/Maps/Desert_Valley_01")],
                  meta={"git_sha": None, "record_count": 1}),
        C.CONVERSION_MANIFEST_INCOMPLETE, "audit::real_manifest",
        "a fabricated manifest presented as the real canonical conversion manifest"))

    # (2) THE v2.5 BUG ITSELF. The 5.7 side lists a package the 5.8 side has no record
    # for, so the two sides do not share a keyspace and the diff silently compares
    # nothing. v2.5 shipped exactly this: conversion_manifest held maps only, so 54
    # non-map assets had no post-conversion side at all.
    f.append((
        "disjoint_manifest_keyspaces", "conversion_audit_gate",
        _manifest([
            _pkg("/Game/Maps/Desert_Valley_01"),
            _pkg("/Game/Materials/Terrain/DA_Terrain_Sand_Desert_01",
                 asset_class="material", conversion_status="source_only",
                 converted_hash=None, converted_package_version=None,
                 actor_count={"source": None, "converted": None},
                 actor_class_inventory={"source": None, "converted": None})]),
        C.CONVERSION_MANIFEST_INCOMPLETE, "audit::common_keyspace",
        "5.7 and 5.8 inventories keyed disjointly — one side has no record"))

    # (3) The 131-vs-124 delta re-presented with the explanation removed. A map-count
    # discrepancy carrying no classification is an unexplained cross-engine diff, and
    # 'unclassified' must stay RED rather than be widened away.
    f.append((
        "map_count_discrepancy_unclassified", "census_reconcile_gate",
        {"counts": {"only_5_7": 7, "only_5_8": 0, "present_both": 124},
         "actor_accounting": {"total_actor_count_5_7": 2799,
                              "total_actor_count_5_8": 2799},
         "entries": [{"package_path": "/Game/Maps/_wf_test_lvl",
                      "membership": "only_5_7", "classification": "unclassified",
                      "evidence": {}, "rationale": ""}],
         "forced_unclassified": []},
        C.REGRESSION_UNCLASSIFIED_DIFF, "present::no_unclassified_entries",
        "a 5.7-only map left unexplained — the census delta is not accounted for"))

    # (4) THE OTHER v2.5 BUG. A package whose CORE and CUSTOM versions are IDENTICAL on
    # both sides and whose engine stamp never moved, declaring itself an
    # 'asset_version_upgrade' — the unearned claim v2.5 applied to all 124 maps.
    #
    # The declared `classification` field is inert (the audit derives its own labels
    # from evidence and reads that field nowhere), so the rejection does not come from
    # catching the label — it comes from the EVIDENCE REFUSING TO SUPPORT ONE. With no
    # version delta and no engine move, nothing explains the changed bytes, the
    # classifier declines to award any benign label, and the package lands in
    # `unclassified` -> RED. The claim cannot be made because it cannot be earned.
    f.append((
        "identical_versions_labelled_version_upgrade", "conversion_audit_gate",
        _manifest([_pkg("/Game/Maps/Desert_Valley_01",
                        classification="asset_version_upgrade",
                        source_package_version=dict(_V57),
                        converted_package_version=dict(_V57),
                        source_hash="a" * 64, converted_hash="b" * 64)]),
        C.REGRESSION_UNCLASSIFIED_DIFF, "audit::unclassified_packages_zero",
        "identical package versions on both sides, declared a version upgrade"))

    # (5) THE HEADLINE. The v2.5 DRY PROBE — the very artifact v2.5 shipped as its
    # "bridge gate" — submitted to the live gate. A dry probe asserts that NOTHING ran;
    # it is green precisely when no far side was touched. It must never satisfy a
    # positive claim. Built from the real dry probe, not a mock of one.
    f.append((
        "dry_probe_satisfies_live_gate", "live_bridge_contract",
        GBP.build_probe_report()[1],
        C.TRANSITION_REPORT_INTEGRITY_FAILED, None,
        "the v2.5 rejecting dry probe offered as proof of a live 5.8 run"))

    # (6) The process exited 0, so a naive gate calls it success — but nothing came
    # back. An exit code is not evidence; the artifact is.
    f.append((
        "zero_exit_bridge_no_evidence", "live_bridge_contract",
        ex(evidence_entries=[], evidence_hashes=[], evidence_count=0,
           process_exit_code=0),
        C.BRIDGE_EMPTY_EVIDENCE, None,
        "bridge process exits zero having produced no evidence at all"))

    # (7) Evidence lifted from a DIFFERENT project and counted as this operation's.
    # Note the path is RELATIVE, so it slips past the absolute-path-leak rail (WF1029)
    # entirely — only the project-membership rail catches it, which is why this fixture
    # is driven at GATE level and pinned to that check by name.
    f.append((
        "foreign_project_evidence", "live_bridge_gate",
        ex(evidence_entries=["../SomeOtherProject/Content/WFBridge/x.uasset"],
           evidence_hashes=["b" * 64], evidence_count=1),
        C.BRIDGE_WRONG_PROJECT, "real::evidence_belongs_to_target",
        "evidence rooted in another project passed off as the target's"))

    # (8) Evidence from an EARLIER operation replayed to green a new run. The artifact
    # is real and its hash checks out — it just isn't this operation's.
    f.append((
        "stale_evidence_reuse", "live_bridge_contract",
        ex(evidence_operation_id="op_example_0000"),
        C.BRIDGE_STALE_PLUGIN, None,
        "evidence from a previous operation replayed as this run's proof"))

    # (9) A real gate report hand-edited to say 'ok' while its own failure list still
    # names the failure. The tampering is visible in the artifact's own contradiction.
    f.append((
        "manually_modified_audit_report", "report_integrity",
        _clean_gate_report(
            status="ok",
            failures=["audit::no_actor_loss: 1 map(s) lost actors across conversion"]),
        C.TRANSITION_REPORT_INTEGRITY_FAILED, "manual_edit_ok_with_failures",
        "a conversion-audit report edited by hand to hide its own failure"))

    return f


# --------------------------------------------------------------------------- #
# Drivers — each invokes a REAL validator and returns [(check_name, code_str)]
# for everything that FAILED. Never a reimplementation of a rule.
# --------------------------------------------------------------------------- #
def _failed(rep):
    return [(n, str(c.get("code"))) for n, c in rep.checks.items()
            if c.get("verdict") == "FAIL" and c.get("code")]


def _drive_conversion_audit_gate(path):
    """Lane 3's REAL gate body, pointed at a fixture manifest."""
    rep = ValidationReport("gate", "kb_conversion_audit", strict=True)
    VCA.run(rep, str(path))
    return _failed(rep)


def _drive_census_reconcile_gate(path):
    """Lane 2's REAL gate body. Its payload path is a module global, so it is
    redirected for the call and restored — the validator itself is not modified."""
    old = VMCR.PAYLOAD_PATH
    VMCR.PAYLOAD_PATH = Path(path)
    try:
        rep = ValidationReport("gate", "kb_census", strict=True)
        VMCR.validate_present_report(rep, True)
        return _failed(rep)
    finally:
        VMCR.PAYLOAD_PATH = old


def _drive_live_bridge_contract(path):
    """Lane 4's REAL live-bridge contract validator."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(c[0], str(c[3]))
            for c in LIVE.validate_live_bridge_report(doc, strict=True) if not c[1]]


def _drive_live_bridge_gate(path):
    """Lane 4's REAL gate body (contract + disk re-verification), pointed at a
    fixture report. Same redirect-and-restore discipline as the census driver."""
    old = VGBL.LIVE_REPORT
    VGBL.LIVE_REPORT = Path(path)
    try:
        rep = ValidationReport("gate", "kb_live_bridge", strict=True)
        VGBL.validate_real_live_report(rep)
        return _failed(rep)
    finally:
        VGBL.LIVE_REPORT = old


def _drive_report_integrity(path):
    """The REAL report-integrity detector the shield's own gate scans with."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(label, str(code)) for label, code in TRI.report_integrity_findings(doc)]


DRIVERS = {
    "conversion_audit_gate": _drive_conversion_audit_gate,
    "census_reconcile_gate": _drive_census_reconcile_gate,
    "live_bridge_contract": _drive_live_bridge_contract,
    "live_bridge_gate": _drive_live_bridge_gate,
    "report_integrity": _drive_report_integrity,
}


# --------------------------------------------------------------------------- #
# Positive controls — a rejecter that rejects everything proves nothing.
# --------------------------------------------------------------------------- #
def positive_controls(rep):
    # The REAL canonical manifest must still pass Lane 3's gate body. If this fails,
    # the conversion driver rejects everything and its known-bads mean nothing.
    sub = ValidationReport("gate", "control_conversion_audit", strict=True)
    try:
        VCA.run(sub, str(ACD.CANONICAL_MANIFEST))
        conv_fails = _failed(sub)
    except Exception as exc:  # noqa: BLE001 — a crashing control is a failed control
        conv_fails = [("control_raised", str(exc))]
    rep.check("control::conversion_audit_accepts_real_manifest", not conv_fails,
              "the REAL canonical manifest must pass the conversion-audit gate, or "
              "this driver rejects everything and its known-bads prove nothing: "
              "{}".format(conv_fails[:3]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)

    # The live contract must accept an honest live report.
    live_fails = [c[0] for c in
                  LIVE.validate_live_bridge_report(LIVE.example_live_report(), strict=True)
                  if not c[1]]
    rep.check("control::live_contract_accepts_valid_report", not live_fails,
              "a valid live report must be accepted, or the live driver rejects "
              "everything: {}".format(live_fails[:3]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)

    # The report-integrity detector must accept an untampered report.
    ri = TRI.report_integrity_findings(_clean_gate_report())
    rep.check("control::report_integrity_accepts_clean_report", not ri,
              "an untampered report must be accepted: {}".format(ri),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)


# --------------------------------------------------------------------------- #
def materialize(fixtures):
    """Write each fixture as a PURE artifact + a sidecar catalogue index."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    index = {}
    for slug, driver, doc, code, check, vector in fixtures:
        (FIXTURE_DIR / (slug + ".json")).write_text(
            json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
        index[slug] = {"driver": driver, "expected_code": str(code),
                       "expected_check": check, "vector": vector,
                       "fixture": slug + ".json"}
    INDEX_PATH.write_text(json.dumps(
        {"schema_version": "wf.transition.known_bads_index.v1",
         "note": "Fixtures are PURE artifacts: catalogue metadata lives here, never "
                 "inside a fixture, because the live bridge contract rejects unknown "
                 "fields and a fixture rejected for carrying harness metadata would "
                 "prove nothing.",
         "fixtures": index}, indent=2, sort_keys=True), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="v2.5.1 hostile known-bad fixture harness (conversion + bridge).")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--no-regen", action="store_true",
                    help="validate the fixtures already on disk; do not regenerate")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    fixtures = _fixtures()
    if not args.no_regen:
        materialize(fixtures)

    rep = ValidationReport("suite", "v2_5_1_known_bads", strict=strict)

    if not INDEX_PATH.is_file():
        rep.check("kb::index_present", False,
                  "no fixture index at {} — run without --no-regen".format(INDEX_PATH),
                  code=C.TRANSITION_NEGATIVE_ACCEPTED)
        rep.finalize()
        rep.print_summary("v2.5.1-known-bads")
        sys.exit(rep.exit_code)

    index = (json.loads(INDEX_PATH.read_text(encoding="utf-8"))).get("fixtures") or {}
    n = 0
    for slug in sorted(index):
        entry = index[slug]
        path = FIXTURE_DIR / entry["fixture"]
        driver = DRIVERS.get(entry.get("driver"))
        n += 1
        if not path.is_file():
            rep.check("kb::{}::fixture_present".format(slug), False,
                      "fixture file missing: {}".format(path),
                      code=C.TRANSITION_NEGATIVE_ACCEPTED)
            continue
        if driver is None:
            rep.check("kb::{}::known_driver".format(slug), False,
                      "unknown driver {!r}".format(entry.get("driver")),
                      code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
            continue
        try:
            fails = driver(path)
        except Exception as exc:  # noqa: BLE001
            # A crash is NOT a rejection. A validator that explodes on hostile input
            # has not judged it, and we must not score that as a pass.
            rep.check("kb::{}::rejected_not_crashed".format(slug), False,
                      "driver raised {} instead of rejecting the fixture: {}".format(
                          type(exc).__name__, exc),
                      code=C.TRANSITION_NEGATIVE_ACCEPTED)
            continue

        names = {f[0] for f in fails}
        codes = {f[1] for f in fails}
        rep.check("kb::{}::rejected".format(slug), len(fails) > 0,
                  "known-bad was ACCEPTED — {}".format(entry["vector"]),
                  code=C.TRANSITION_NEGATIVE_ACCEPTED)
        rep.check("kb::{}::owning_code".format(slug),
                  entry["expected_code"] in codes,
                  "must be rejected for {} (got {})".format(
                      entry["expected_code"], sorted(codes)[:5]),
                  code=C.TRANSITION_NEGATIVE_ACCEPTED)
        if entry.get("expected_check"):
            rep.check("kb::{}::owning_check".format(slug),
                      entry["expected_check"] in names,
                      "must be rejected BY {} — rejection by any other rail is "
                      "collateral, not proof of this vector (failed: {})".format(
                          entry["expected_check"], sorted(names)[:5]),
                      code=C.TRANSITION_NEGATIVE_ACCEPTED)

    positive_controls(rep)

    rep.check("kb::catalogue_complete", n >= 9,
              "the v2.5.1 catalogue must carry >= 9 fixtures, one per mission vector "
              "(got {})".format(n),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="v2-5-1-known-bads", pack=None, strict=strict, status=rep.status,
        record_count=n, records_total=n,
        report_type="wf.transition.known_bads_v2_5_1.v1",
        extra=transition_identity("5.8", runtime_required=False, runtime_executed=False,
                                  observed_runtime_engine=None)))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "run_v2_5_1_known_bads_report.json")
    rep.print_summary("v2.5.1-known-bads")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
