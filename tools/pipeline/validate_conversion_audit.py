#!/usr/bin/env python3
"""validate_conversion_audit.py — v2.5.1 fail-closed gate over the REAL canonical
conversion manifest (Lane 3).

Runs ``audit_conversion_diff`` against
``procedural/manifests/ue5_8_conversion/canonical_conversion_manifest.json`` — the
REAL artifact, never a fixture — and gates on evidence, not on assertions.

Required to pass (all four are hard failures, none is warn-only):

    real_manifest=true         the input really is the canonical manifest: right
                               schema_version/report_type/keyspace, a produced
                               meta.git_sha, and a declared package_count that
                               matches the records actually present. A stub or a
                               hand-edited toy cannot green this gate.  (WF1015)
    common_keyspace=true       every record carries BOTH sides — present_both with
                               a real source_hash AND a real converted_hash, and
                               package_path is genuinely unique. This is the v2.5
                               bug's tripwire: non-map assets once had no
                               post-conversion record at all.  (WF1015)
    unclassified_packages=0    every package is explained by an evidence rule.
                               An unexplained package keeps this gate RED, and
                               that is the CORRECT outcome — the fix is to earn a
                               label with real evidence, never to widen a rule
                               until the red goes away.  (WF1021)
    unaccounted_deletions=0    nothing present pre-conversion vanished post-
                               conversion. The manifest carries no accounted-
                               deletion allowlist, so any deletion is unaccounted
                               and dangles references.  (WF1016)

Plus the two honesty invariants the classifier exists to hold:

    actor loss blocks                       (WF1014) — the cardinal conversion sin
    no refused label leaks into output      (WF1035) — a label that cannot be
                                            decided from real fields must never be
                                            emitted, not even as a fallback
    classifier negative controls fire       (WF1035) — actor loss / deletion /
                                            null-evidence must classify BLOCKING
                                            on synthetic canonical-shaped records
    no version claim without a version diff (WF1034) — the v2.5 regression guard:
                                            UE 5.7 and 5.8 ship the identical
                                            package version, so ZERO packages may
                                            carry a version-upgrade claim

Runtime-free gate — this reads hashes and counts off disk; it never drives Unreal.
Report -> procedural/reports/ue5_8/audit/validate_conversion_audit_report.json
Acceptance: PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_conversion_audit.py --strict
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import audit_conversion_diff as ACD  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from transition_identity import transition_identity  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "audit"


def run(rep, manifest_path):
    # 0. The manifest must exist at all. Absent input => ERROR, never a green.
    path = Path(manifest_path)
    if not path.is_file():
        rep.error("canonical conversion manifest missing at {}".format(path))
        return None

    manifest = ACD.load_manifest(path)

    # 1. real_manifest — the input is the produced canonical artifact, not a stub.
    real_ok, real_reasons = ACD.is_real_canonical_manifest(manifest)
    rep.check("audit::real_manifest", real_ok,
              "not the real canonical manifest: {}".format("; ".join(real_reasons[:4])),
              code=C.CONVERSION_MANIFEST_INCOMPLETE)

    # 2. common_keyspace — both sides populated for every package_path.
    key_ok, key_reasons = ACD.common_keyspace(manifest)
    rep.check("audit::common_keyspace", key_ok,
              "keyspace is not common across both sides: {}".format(
                  "; ".join(key_reasons[:4])),
              code=C.CONVERSION_MANIFEST_INCOMPLETE)

    result = ACD.audit(manifest)

    # 3. unclassified_packages == 0. Unknown is guilty until explained.
    unclassified = result["unclassified_packages"]
    rep.check("audit::unclassified_packages_zero", len(unclassified) == 0,
              "{} package(s) unexplained by any evidence rule: {}".format(
                  len(unclassified), unclassified[:5]),
              code=C.REGRESSION_UNCLASSIFIED_DIFF)

    # 4. unaccounted_deletions == 0. A vanished package dangles every reference.
    deletions = result["unaccounted_deletions"]
    rep.check("audit::unaccounted_deletions_zero", len(deletions) == 0,
              "{} package(s) present pre-conversion and absent post: {}".format(
                  len(deletions), deletions[:5]),
              code=C.CONVERSION_UNEXPECTED_CHURN)

    # 5. The cardinal sin: no map may lose actors — by count OR by class.
    losses = result["actor_loss_packages"]
    rep.check("audit::no_actor_loss", len(losses) == 0,
              "{} map(s) lost actors across conversion: {}".format(
                  len(losses), losses[:5]),
              code=C.CONVERSION_ACTOR_LOSS)

    # 5b. Class loss is actor loss at an unchanged TOTAL count — asserted on its own
    #     axis because actor_count alone is blind to a class replacement.
    class_losses = result["class_loss_packages"]
    rep.check("audit::no_actor_class_loss", len(class_losses) == 0,
              "{} map(s) lost an actor CLASS across conversion (silent damage the "
              "total actor count does not reveal): {}".format(
                  len(class_losses), class_losses[:5]),
              code=C.CONVERSION_ACTOR_LOSS)

    # 6. No refused label leaked. A label that cannot be decided from real fields
    #    must never appear in output — not as a guess, not as a fallback.
    leak = result["undecidable_label_leak"]
    rep.check("audit::no_undecidable_label_leak", len(leak) == 0,
              "classifier emitted label(s) it cannot decide from real evidence: {}".format(
                  leak),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)

    # 7. Negative controls: the blocking rules must actually fire. A classifier
    #    that greens everything is worthless; prove it can go red on synthetics.
    selftest_fails = ACD._selftest()
    rep.check("audit::classifier_negative_controls", len(selftest_fails) == 0,
              "classifier negative controls failed: {}".format(selftest_fails[:4]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)

    # 8. THE v2.5 REGRESSION GUARD. Every package_version_changed claim must be
    #    backed by a REAL version delta in the record itself — CORE or CUSTOM,
    #    never the engine stamp. Re-derived here independently of the classifier,
    #    so the two must agree or the gate goes red. UE 5.7 and 5.8 share
    #    FileVersionUE5=1018, so a CORE claim can never be earned on this
    #    transition; only a custom-version delta could earn one.
    by_path = {p.get("package_path"): p for p in (manifest.get("packages") or [])}
    unearned = []
    for r in result["results"]:
        if r["label"] != ACD.PACKAGE_VERSION_CHANGED:
            continue
        rec = by_path.get(r["package_path"]) or {}
        sv, cv = rec.get("source_package_version"), rec.get("converted_package_version")
        core = ACD._core_delta(sv, cv)
        custom = ACD._custom_delta(sv, cv)
        if not core and not custom:
            unearned.append(r["package_path"])
    rep.check("audit::version_claims_are_earned", len(unearned) == 0,
              "{} package(s) claim a version change with no real CORE or CUSTOM "
              "version delta (the v2.5 asset_version_upgrade bug): {}".format(
                  len(unearned), unearned[:5]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    # 9. THE ENGINE STAMP IS NOT A VERSION. It sits inside the version dicts, so a
    #    naive whole-dict diff would fire a bogus version claim on every converted
    #    package. Proven here on the real data: no package may be labelled
    #    package_version_changed on stamp evidence alone.
    stamp_only = []
    for r in result["results"]:
        if r["label"] != ACD.PACKAGE_VERSION_CHANGED:
            continue
        rec = by_path.get(r["package_path"]) or {}
        sv, cv = rec.get("source_package_version"), rec.get("converted_package_version")
        s_stamp, c_stamp = ACD._stamps(sv, cv)
        if s_stamp != c_stamp and not ACD._core_delta(sv, cv) \
                and not ACD._custom_delta(sv, cv):
            stamp_only.append(r["package_path"])
    rep.check("audit::stamp_not_diffed_as_version", len(stamp_only) == 0,
              "{} package(s) claim a version change on engine-stamp evidence alone: "
              "{}".format(len(stamp_only), stamp_only[:5]),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    # 10. THE EVIDENCE BASE MUST ACTUALLY HAVE BEEN READ.
    #     custom_versions is null for EVERY package. That is not "unknown for a few
    #     records" — it is a producer-side failure to read the field at all, and it
    #     is load-bearing: custom versions are precisely what moves across an engine
    #     resave. Verified by hand against the real bytes (5.7 blob LFS-smudged vs
    #     the 5.8 worktree file, MI_WF_TerrainProof):
    #         FFortniteMainBranchObjectVersion 225 -> 268
    #         FUE5MainStreamObjectVersion      121 -> 123
    #         FUE5ReleaseStreamObjectVersion    61 ->  68
    #     — matching build_canonical_conversion_manifest.read_package_versions()'s
    #     own docstring examples. So a real version move IS happening and this
    #     manifest cannot see it. Certifying "engine_resave_only, no version change
    #     observed" on that input is the MIRROR IMAGE of the v2.5 bug: v2.5 claimed
    #     a version upgrade that never happened; greening here would deny one that
    #     did. Blocking, and NOT worked around by relabelling — the fix belongs to
    #     the producer, which this lane does not own.
    ve = result["version_evidence"]
    rep.check("audit::version_evidence_complete",
              not ve["custom_versions_systematically_absent"],
              "custom_versions is null for ALL {} packages — the producer never "
              "successfully parsed the FCustomVersionContainer, so 'no version change' "
              "is UNKNOWN, not observed. Root cause: read_package_versions() reads the "
              "array count at header offset 24; the array really begins at offset 32, "
              "so the count parses as 0x5C149824 and trips the 0<=count<=512 bound -> "
              "custom=None for every package.".format(ve["package_count"]),
              code=C.CONVERSION_MANIFEST_INCOMPLETE)

    # 11. Non-blocking but never silent: byte-identical packages in a CONVERSION
    #     audit were NOT converted (declared converted_engine vs observed stamp).
    unconv = result["unconverted_packages"]
    rep.warn_only("audit::no_unconverted_packages", len(unconv) == 0,
                  "{} package(s) are byte-identical and still carry the 5.7 engine "
                  "stamp while declaring converted_engine=5.8 — present in the tree "
                  "but never converted: {}".format(len(unconv), unconv[:5]),
                  code=C.TRANSITION_HYGIENE_FAILED)

    # 12. Tally completeness — every package landed in exactly one label.
    tallied = sum(result["counts_by_label"].values())
    rep.check("audit::every_package_labelled", tallied == result["package_count"],
              "tally {} != {} packages — a package fell through the rules".format(
                  tallied, result["package_count"]),
              code=C.CONVERSION_MANIFEST_INCOMPLETE)

    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5.1 conversion-audit gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--manifest", default=str(ACD.CANONICAL_MANIFEST))
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("gate", "conversion_audit", strict=strict)
    result = run(rep, args.manifest)
    rep.finalize()

    # The gate's verdict is the checks; the tally rides in meta so a reader of the
    # report alone can see WHAT was concluded about all 176 packages, not just that
    # the gate went green. Full per-package evidence lives in the audit report.
    extra = transition_identity("5.8", runtime_required=False,
                                runtime_executed=False, observed_runtime_engine=None)
    extra["manifest_path"] = str(Path(args.manifest))
    if result is not None:
        extra["package_count"] = result["package_count"]
        extra["counts_by_label"] = result["counts_by_label"]
        extra["unclassified_packages"] = result["unclassified_packages"]
        extra["unaccounted_deletions"] = result["unaccounted_deletions"]
        extra["actor_loss_packages"] = result["actor_loss_packages"]
        extra["labels_refused_as_undecidable"] = sorted(
            result["labels_refused_as_undecidable"])
    rep.set_meta(build_meta(
        command="validate-conversion-audit", pack=args.pack, strict=strict,
        status=rep.status, record_count=len(rep.checks), records_total=len(rep.checks),
        report_type="wf.transition.conversion_audit_gate.v1", extra=extra))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_conversion_audit_report.json")
    rep.print_summary("conversion-audit")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
