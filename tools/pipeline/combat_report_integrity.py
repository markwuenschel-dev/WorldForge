#!/usr/bin/env python3
"""combat_report_integrity.py — WorldForge v1.8 CombatForge report-integrity gate.

Mirror of [[npc_report_integrity]] for the v1.8 combat evidence stream. Every
combat *evidence* record the runtime layer emits — scenario / telemetry /
completion ``cs_*.json`` files under ``procedural/reports/combat/`` — must carry a
coherent v1.5-shaped ``meta`` envelope (as produced by report_meta.build_meta)
and cannot claim success while empty, stale-typed, or tally-inconsistent.

Scoping (matches the v1.7 analog exactly, adapted for concurrent lanes): this gate
asserts ONLY on combat EVIDENCE files (``cs_*.json``). Sibling validator-output
reports (``*_report.json`` written by other lanes' gates) are intentionally NOT
required to carry a v1.5 meta here — those get their meta from ValidationReport
and are policed by their own gates. The scan is robust to concurrency: a file that
does not parse as JSON is skipped, not asserted on.

ANTI-FAKE-GREEN: this gate reads runtime evidence that does not exist until the UE
combat runtime runs. When no ``cs_*.json`` evidence exists yet, there is genuinely
nothing to violate, so the scan itself is a clean pass — BUT the gate still proves
its own logic by dogfooding one in-memory evidence record WITHOUT meta (must be
flagged) and one WITH meta (must pass). It never greens vacuously.

Acceptance: PYTHONUTF8=1 STRICT=1 python tools/pipeline/combat_report_integrity.py --strict
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import combat_contracts as CC
from report_meta import build_meta, strict_from_env, missing_v1_5_meta_keys
from validation_report import ValidationReport
from failure_codes import FailureCode as F

COMBAT_REPORTS_ROOT = REPO_ROOT / "procedural" / "reports" / "combat"
KNOWN_STATUS = {"ok", "warn", "fail", "error"}

# Combat evidence report types whose 'ok'/'warn' status implies a non-zero record
# set. Evidence records are per-scenario, so an ok evidence file must have
# records_total > 0 and records_failed == 0.
NONZERO_EVIDENCE_TYPES = {
    CC.RT_COMBAT_TELEMETRY, CC.RT_COMBAT_COMPLETION, CC.RT_DAMAGE_EVENT,
    CC.RT_PLAYER_COMBAT_STATE,
}


def iter_combat_evidence():
    """Yield (path, parsed_doc_or_None) for every combat EVIDENCE file (cs_*.json)
    under the combat reports tree. Robust to concurrent lanes: files that do not
    parse as JSON yield None (skipped by the caller), never crash the scan."""
    if not COMBAT_REPORTS_ROOT.is_dir():
        return
    for p in sorted(COMBAT_REPORTS_ROOT.rglob("cs_*.json")):
        try:
            yield p, json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — unparseable is a finding, not a crash
            yield p, None


def evidence_meta_violations(doc):
    """The single source of truth for 'is this evidence record's meta envelope
    v1.5-complete?'. Returns the list of missing v1.5 meta keys (empty == clean).
    Dogfooded below on a with-meta and a without-meta record so the checker's own
    logic is proven even when zero real evidence exists."""
    meta = doc.get("meta") if isinstance(doc, dict) else None
    return missing_v1_5_meta_keys(meta)


def _dogfood(rep, pack, strict):
    """Prove the meta checker constrains: a WITHOUT-meta evidence record must be
    flagged; a WITH-meta record must pass. Runs regardless of real evidence."""
    without_meta = CC._example_combat_completion()  # no 'meta' key
    with_meta = dict(
        CC._example_combat_completion(),
        meta=build_meta(command="combat-completion", pack=pack, strict=strict,
                        status="ok", record_count=1, records_total=1, records_passed=1,
                        report_type=CC.RT_COMBAT_COMPLETION),
    )
    rep.check("dogfood::without_meta_flagged", len(evidence_meta_violations(without_meta)) > 0,
              "evidence record lacking a v1.5 meta envelope must be flagged",
              code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
    rep.check("dogfood::with_meta_passes", evidence_meta_violations(with_meta) == [],
              "evidence record with a complete v1.5 meta envelope must pass; missing={}".format(
                  evidence_meta_violations(with_meta)),
              code=F.COMBAT_REPORT_INTEGRITY_FAILURE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # ---- self-proof: the checker constrains even with zero real evidence ----
    _dogfood(rep, args.pack, strict)

    # ---- scan real combat evidence (cs_*.json only) ----
    n = 0
    for path, doc in iter_combat_evidence():
        rel = path.relative_to(REPO_ROOT).as_posix()
        n += 1
        if doc is None:
            rep.check("ri::{}::parseable".format(rel), False, "combat evidence not parseable",
                      code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
            continue
        miss = evidence_meta_violations(doc)
        rep.check("ri::{}::meta_complete".format(rel), not miss,
                  "missing v1.5 meta keys: {}".format(miss), code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
        meta = doc.get("meta")
        if not isinstance(meta, dict):
            continue
        status = meta.get("status")
        rep.check("ri::{}::status_known".format(rel), status in KNOWN_STATUS,
                  "unknown status {!r}".format(status), code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
        fc = meta.get("failure_count", 0)
        if status == "ok":
            rep.check("ri::{}::ok_no_failures".format(rel), fc == 0,
                      "status=ok but failure_count={}".format(fc), code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
        tot = meta.get("records_total", 0)
        passed = meta.get("records_passed", 0)
        failed = meta.get("records_failed", 0)
        skipped = meta.get("records_skipped", 0)
        rep.check("ri::{}::records_tally".format(rel), tot == passed + failed + skipped,
                  "records_total {} != passed+failed+skipped".format(tot),
                  code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
        if meta.get("report_type") in NONZERO_EVIDENCE_TYPES and status in ("ok", "warn"):
            rep.check("ri::{}::nonzero_success".format(rel), tot > 0 and failed == 0,
                      "ok {} evidence with records_total={} failed={}".format(
                          meta.get("report_type"), tot, failed),
                      code=F.COMBAT_REPORT_INTEGRITY_FAILURE)

    # Zero real evidence is a clean pass (nothing to violate) — the dogfood above
    # is what keeps this honest, so we do NOT fail on n == 0.
    rep.check("integrity::scan_ran", True,
              "scanned {} combat evidence file(s) (0 is a clean pass)".format(n),
              code=F.COMBAT_REPORT_INTEGRITY_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="combat-report-integrity", pack=args.pack, strict=strict,
                            status=rep.status, record_count=n,
                            report_type="wf.combat.report_integrity.v1", records_total=n))
    rep.write(REPO_ROOT / "procedural/reports/combat/report_integrity",
              "combat_report_integrity_report.json")
    rep.print_summary("combat-report-integrity")
    print("[combat-report-integrity] {} combat evidence file(s) checked "
          "(dogfood: with/without-meta)".format(n))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
