#!/usr/bin/env python3
"""validate_map_census_reconciliation.py — v2.5.1 Lane 2 census-reconciliation gate.

Fail-closed gate over ``reconcile_map_census.py``. The bright line: ANY entry
classified ``unclassified`` => RED. A map-count delta is only "explained" when every
5.7-only package carries an evidence-backed reason; an unexplained package must stop
the wave, not get rounded down to a curiosity.

Two jobs:

1. DOGFOOD the classifier (reconcile_map_census.classify) against inline known-bads,
   so the reconciler cannot be fake-greened:
     * evidence with no explanatory probe            -> unclassified  (WF1021)
     * on-disk under CONTENT_ROOTS but not inventoried -> unclassified (WF1021)
       (build_conversion_manifest rglob()s those roots — a gap there is a real bug,
        not a classification)
     * a package tracked at the 5.7 tag but gone at HEAD must NOT be laundered into
       generated_or_transient — it is stale_or_invalid_5_7 (WF1037)
     * an actor-bearing 5.7-only map must NOT reach generated_or_transient (WF1014)
   Each known-bad MUST land on its owning outcome, else this gate is RED.

2. Validate the emitted reconciliation payload
   (procedural/reports/ue5_8/census/map_census_reconciliation.json):
     * absent/unparseable payload            -> fail-closed RED (WF1015)
     * any ``unclassified`` entry            -> RED (WF1021)
     * any classification outside the closed vocabulary -> RED (WF1034)
     * ``only_5_7`` used as a RESOLVED classification   -> RED (WF1037)
       (only_5_7 is a membership label; letting it pass would be a laundering hole)
     * a non-empty ``forced_unclassified``   -> RED (WF1037) — the proof hook must
       never be left on in a real run
     * set algebra + actor accounting must reconcile against the raw censuses
       (WF1034 / WF1014) — the gate recomputes them rather than trusting the payload

Failure codes are drawn from the EXISTING WF1011-1039 transition band; none invented.

Runtime-free gate.
Report -> procedural/reports/ue5_8/census/validate_map_census_reconciliation_report.json
Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_map_census_reconciliation.py --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reconcile_map_census as RMC  # noqa: E402
from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from transition_identity import transition_identity  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "census"
PAYLOAD_PATH = REPORT_DIR / RMC.REPORT_NAME


def _ev(**over):
    """A baseline evidence record (the real generated_or_transient shape), overridable."""
    base = {
        "package_path": "/Game/Maps/_fixture",
        "repo_relative_path": "Content/Maps/_fixture.umap",
        "actor_count_5_7": 0,
        "class_histogram_5_7_empty": True,
        "loaded_5_7": True,
        "error_5_7": None,
        "on_disk_in_worktree": False,
        "tracked_at_head": False,
        "tracked_at_5_7_tag": False,
        "deleted_in_history": False,
        "in_conversion_manifest": False,
        "under_content_roots": True,
        "plugin_or_engine_path": False,
        "redirector_referencing": [],
        "uncontrolled_changelist_listed": True,
    }
    base.update(over)
    return base


def _known_bads():
    """(name, evidence, must_classify_as, owning_code) — each proves one honesty rail."""
    return (
        # No probe explains it -> must fail closed, not fall into a soft bucket.
        ("no_probe_explains_absence",
         _ev(actor_count_5_7=12, class_histogram_5_7_empty=False, on_disk_in_worktree=False,
             tracked_at_head=True),
         "unclassified", C.REGRESSION_UNCLASSIFIED_DIFF),
        # On disk under CONTENT_ROOTS yet uninventoried -> impossible; must not be excused.
        ("on_disk_under_roots_but_uninventoried",
         _ev(on_disk_in_worktree=True, under_content_roots=True, in_conversion_manifest=False),
         "unclassified", C.REGRESSION_UNCLASSIFIED_DIFF),
        # Real committed 5.7 content that was retired -> stale, never "scratch".
        ("tracked_at_5_7_tag_then_deleted_is_not_scratch",
         _ev(tracked_at_5_7_tag=True, tracked_at_head=False, deleted_in_history=True),
         "stale_or_invalid_5_7", C.TRANSITION_HYGIENE_FAILED),
        # An actor-bearing map is never transient scratch — that would hide real loss.
        ("actor_bearing_map_is_not_transient",
         _ev(actor_count_5_7=87, class_histogram_5_7_empty=False),
         "unclassified", C.CONVERSION_ACTOR_LOSS),
    )


def dogfood(rep):
    """Prove the classifier lands each known-bad on its owning outcome."""
    # The valid example: the real scratch shape resolves to generated_or_transient.
    good_cls, _ = RMC.classify(_ev())
    rep.check("dogfood::valid_example_classifies",
              good_cls == "generated_or_transient",
              "baseline scratch evidence should classify generated_or_transient, got "
              "{!r}".format(good_cls),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    for name, ev, want, code in _known_bads():
        got, why = RMC.classify(ev)
        rep.check("dogfood::known_bad::{}".format(name), got == want,
                  "known-bad {!r} must classify {!r} (got {!r}: {})".format(
                      name, want, got, why[:120]),
                  code=code)

    # The vocabulary is genuinely closed.
    rep.check("dogfood::vocabulary_closed",
              set(RMC.RESOLVED_5_7_ONLY).issubset(set(RMC.CLASSIFICATIONS))
              and "unclassified" in RMC.CLASSIFICATIONS,
              "resolved reasons must be a subset of the closed vocabulary",
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    # only_5_7 must NOT be a resolved reason — else it is a pass-through hole.
    rep.check("dogfood::only_5_7_is_not_a_resolved_reason",
              "only_5_7" not in RMC.RESOLVED_5_7_ONLY,
              "only_5_7 is a membership label; accepting it as a resolved reason would "
              "let an unexplained package pass the gate",
              code=C.TRANSITION_HYGIENE_FAILED)


def validate_present_report(rep, strict):
    """Validate the emitted reconciliation payload; absent payload is fail-closed RED."""
    if not PAYLOAD_PATH.is_file():
        rep.check("present::report_exists", False,
                  "no reconciliation payload at {} — run reconcile_map_census.py first "
                  "(fail-closed RED)".format(PAYLOAD_PATH.relative_to(REPO_ROOT)),
                  code=C.CONVERSION_MANIFEST_INCOMPLETE)
        return
    rep.check("present::report_exists", True, str(PAYLOAD_PATH.relative_to(REPO_ROOT)),
              code=C.CONVERSION_MANIFEST_INCOMPLETE)
    try:
        payload = json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        rep.check("present::report_parseable", False,
                  "reconciliation payload unparseable: {}".format(exc),
                  code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
        return
    rep.check("present::report_parseable", True, "parsed",
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        rep.check("present::entries_present", False,
                  "payload has no entries — an empty reconciliation explains nothing",
                  code=C.CONVERSION_MANIFEST_INCOMPLETE)
        return
    rep.check("present::entries_present", True, "{} entries".format(len(entries)),
              code=C.CONVERSION_MANIFEST_INCOMPLETE)

    # --- vocabulary integrity ------------------------------------------------
    vocab = set(RMC.CLASSIFICATIONS)
    bad_vocab = sorted({e.get("classification") for e in entries} - vocab)
    rep.check("present::classification_vocabulary_closed", not bad_vocab,
              "classifications outside the closed vocabulary: {}".format(bad_vocab),
              code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    # --- THE BRIGHT LINE: any unclassified entry => RED -----------------------
    unresolved = [e["package_path"] for e in entries
                  if e.get("classification") == "unclassified"]
    rep.check("present::no_unclassified_entries", not unresolved,
              "{} entry(ies) remain unclassified — the census delta is NOT explained: "
              "{}".format(len(unresolved), unresolved[:8]),
              code=C.REGRESSION_UNCLASSIFIED_DIFF)

    # --- only_5_7 must never be a resolved classification ---------------------
    laundered = [e["package_path"] for e in entries
                 if e.get("membership") == "only_5_7" and e.get("classification") == "only_5_7"]
    rep.check("present::only_5_7_not_used_as_resolution", not laundered,
              "{} 5.7-only entry(ies) carry classification 'only_5_7', which is a "
              "membership label, not a reason: {}".format(len(laundered), laundered[:8]),
              code=C.TRANSITION_HYGIENE_FAILED)

    # --- every 5.7-only entry carries a resolved reason + evidence ------------
    for e in sorted((x for x in entries if x.get("membership") == "only_5_7"),
                    key=lambda x: x["package_path"]):
        gp = e["package_path"]
        rep.check("present::resolved::{}".format(gp),
                  e.get("classification") in RMC.RESOLVED_5_7_ONLY,
                  "5.7-only package {} has classification {!r}, not one of the resolved "
                  "reasons {}".format(gp, e.get("classification"), list(RMC.RESOLVED_5_7_ONLY)),
                  code=C.REGRESSION_UNCLASSIFIED_DIFF)
        rep.check("present::evidence_backed::{}".format(gp),
                  isinstance(e.get("evidence"), dict) and bool(e.get("rationale")),
                  "5.7-only package {} must carry an evidence record and a rationale — "
                  "a bare classification is an assertion, not proof".format(gp),
                  code=C.TRANSITION_REPORT_INTEGRITY_FAILED)

    # --- the proof hook must be off in a real run ----------------------------
    forced = payload.get("forced_unclassified") or []
    rep.check("present::force_hook_disabled", not forced,
              "payload was produced with --force-unclassified={} — the fail-closed "
              "proof hook must never be left on in a real run".format(forced),
              code=C.TRANSITION_HYGIENE_FAILED)

    # --- recompute set algebra from the RAW censuses (do not trust the payload) --
    try:
        _, m57 = RMC._load_census(RMC.CENSUS_5_7)
        _, m58 = RMC._load_census(RMC.CENSUS_5_8)
    except Exception as exc:
        rep.check("present::censuses_readable", False,
                  "cannot re-read source censuses: {}".format(exc),
                  code=C.CONVERSION_MANIFEST_INCOMPLETE)
        return
    rep.check("present::censuses_readable", True, "re-read both censuses",
              code=C.CONVERSION_MANIFEST_INCOMPLETE)

    s57, s58 = set(m57), set(m58)
    want = {"only_5_7": len(s57 - s58), "only_5_8": len(s58 - s57),
            "present_both": len(s57 & s58)}
    counts = payload.get("counts") or {}
    for k, v in want.items():
        rep.check("present::set_algebra::{}".format(k), counts.get(k) == v,
                  "payload counts.{}={} but recomputing from the raw censuses gives "
                  "{}".format(k, counts.get(k), v),
                  code=C.TRANSITION_REPORT_INTEGRITY_FAILED)
    rep.check("present::every_census_map_covered",
              len(entries) == len(s57 | s58),
              "payload has {} entries but the union of both censuses is {} maps — "
              "some map is unaccounted for".format(len(entries), len(s57 | s58)),
              code=C.CONVERSION_MANIFEST_INCOMPLETE)

    # --- actor accounting: the delta must be actor-neutral --------------------
    actors_lost = sum(m57[g].get("actor_count") or 0 for g in (s57 - s58))
    rep.check("present::only_5_7_maps_are_actor_free", actors_lost == 0,
              "5.7-only maps carry {} actor(s) — dropping them from the 5.8 census is "
              "real actor loss, not a classification".format(actors_lost),
              code=C.CONVERSION_ACTOR_LOSS)
    acc = payload.get("actor_accounting") or {}
    rep.check("present::actor_totals_match",
              acc.get("total_actor_count_5_7") == acc.get("total_actor_count_5_8"),
              "5.7 total_actor_count={} != 5.8 total_actor_count={} — the map delta is "
              "not actor-neutral".format(acc.get("total_actor_count_5_7"),
                                         acc.get("total_actor_count_5_8")),
              code=C.CONVERSION_ACTOR_LOSS)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5.1 map-census reconciliation gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("gate", "map_census_reconciliation", strict=strict)
    dogfood(rep)
    validate_present_report(rep, strict)
    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-map-census-reconciliation", pack=args.pack, strict=strict,
        status=rep.status, record_count=len(rep.checks), records_total=len(rep.checks),
        report_type="wf.transition.map_census_reconciliation_gate.v1",
        extra=transition_identity("5.8", runtime_required=False, runtime_executed=False,
                                  observed_runtime_engine=None)))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_map_census_reconciliation_report.json")
    rep.print_summary("map-census-reconciliation")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
