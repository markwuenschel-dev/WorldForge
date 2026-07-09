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

Beyond the meta envelope, this gate enforces the contract §4 combat honesty burden
on COMPLETION evidence (``completion/cs_*.json``): every completion record MUST
carry a non-empty TOP-LEVEL ``damage_events`` list of real DamageEvents, and a
``combat_completed_runtime`` success MUST NOT be claimed with ``damage_events == []``
or ``player_min_health == player_max_health`` (no real damage / no health mutation
== fake combat evidence, rejected via COMBAT_FAKE_SUCCESS).

ANTI-FAKE-GREEN: this gate reads runtime evidence that does not exist until the UE
combat runtime runs. When no ``cs_*.json`` evidence exists yet, there is genuinely
nothing to violate, so the scan itself is a clean pass — BUT the gate still proves
its own logic by dogfooding in-memory evidence: one record WITHOUT meta (flagged)
and one WITH meta (passes); one REAL completion with a non-empty damage_events list
(passes) and two FAKE completions — empty damage_events and no health mutation —
that MUST be rejected. It never greens vacuously.

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


def completion_violations(doc):
    """The single source of truth for 'is this COMPLETION evidence record honest?'.
    Returns a list of problem strings (empty == clean). Real combat evidence lives
    in ``completion/cs_*.json`` (contract §4) and — beyond a v1.5 meta envelope —
    MUST carry a non-empty TOP-LEVEL ``damage_events`` list of real DamageEvents,
    and MUST NOT claim ``combat_completed_runtime`` success without real damage /
    health mutation. This is the anti-fake-combat-evidence surface: a completion
    that says success but shows ``damage_events == []`` or
    ``player_min_health == player_max_health`` is fake green and is rejected here.

    ``damage_events`` is an EVIDENCE extra, not a frozen combat_contracts completion
    field, so it is popped before the schema check to honor COMBAT_COMPLETION_ALLOWED
    and validated separately as a list of DamageEvents."""
    if not isinstance(doc, dict):
        return ["completion evidence is not a JSON object"]
    problems = []
    de = doc.get("damage_events")
    if not isinstance(de, list):
        problems.append("completion evidence missing top-level 'damage_events' list")
        de = []
    # Validate the completion body against the frozen contract (damage_events popped).
    body = {k: v for k, v in doc.items() if k != "damage_events"}
    for c in CC.validate_combat_completion_report(body, strict=True):
        if not c[1]:
            problems.append("{}: {}".format(c[0], c[2]))
    # Every top-level damage event must itself be a valid DamageEvent.
    for i, ev in enumerate(de):
        bad = [c for c in CC.validate_damage_event(ev, strict=True) if not c[1]]
        if bad:
            problems.append("damage_events[{}] {}: {}".format(i, bad[0][0], bad[0][2]))
    # Explicit anti-fake-green guard on the success class (contract §4).
    if doc.get("completion_class") == CC.SUCCESS_COMBAT_CLASS:
        if len(de) == 0:
            problems.append("combat_completed_runtime with empty damage_events "
                            "(fake combat evidence)")
        pmin, pmax = doc.get("player_min_health"), doc.get("player_max_health")
        if pmin is not None and pmax is not None and pmin == pmax:
            problems.append("combat_completed_runtime with "
                            "player_min_health==player_max_health (no health mutation)")
        # A success claiming N damage events must actually carry that evidence.
        seen = doc.get("damage_events_seen")
        if isinstance(seen, int) and seen > 0 and len(de) == 0:
            problems.append("damage_events_seen={} but top-level damage_events is "
                            "empty (evidence/tally mismatch)".format(seen))
    return problems


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


def _dogfood_completion(rep, pack, strict):
    """Prove the completion-evidence checker constrains real combat semantics on a
    synthetic record (runs regardless of real evidence, leaves no files behind):
      * a REAL completion carrying a non-empty top-level damage_events list + meta
        must pass;
      * a fake completion whose damage_events == [] must be rejected;
      * a fake completion whose player_min_health == player_max_health must be
        rejected."""
    meta = build_meta(command="combat-completion", pack=pack, strict=strict, status="ok",
                      record_count=1, records_total=1, records_passed=1,
                      report_type=CC.RT_COMBAT_COMPLETION)
    events = [CC._example_damage_event()]
    real = dict(CC._example_combat_completion(), damage_events=events, meta=meta)
    fake_empty = dict(CC._example_combat_completion(), damage_events=[], meta=meta)
    fake_no_mut = dict(CC._example_combat_completion(player_min_health=100.0),
                       damage_events=events, meta=meta)
    rep.check("dogfood::completion_real_passes", completion_violations(real) == [],
              "a real completion with non-empty damage_events must pass; got {}".format(
                  completion_violations(real)[:3]),
              code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
    rep.check("dogfood::completion_empty_damage_flagged", len(completion_violations(fake_empty)) > 0,
              "a combat_completed_runtime with empty damage_events must be rejected",
              code=F.COMBAT_NO_DAMAGE_EVENTS)
    rep.check("dogfood::completion_no_mutation_flagged", len(completion_violations(fake_no_mut)) > 0,
              "a combat_completed_runtime with no health mutation must be rejected",
              code=F.PLAYER_HEALTH_NO_MUTATION)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # ---- self-proof: the checker constrains even with zero real evidence ----
    _dogfood(rep, args.pack, strict)
    _dogfood_completion(rep, args.pack, strict)

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
        # Completion evidence (contract §4: completion/cs_*.json) carries the real
        # combat honesty burden — a non-empty top-level damage_events list and no
        # fake-green success. Scoped by the contract-pinned directory name.
        if path.parent.name == "completion":
            cprob = completion_violations(doc)
            rep.check("ri::{}::combat_honesty".format(rel), not cprob,
                      "combat completion evidence violations: {}".format(cprob[:4]),
                      code=F.COMBAT_FAKE_SUCCESS)
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
          "(dogfood: with/without-meta + real/fake completion damage_events)".format(n))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
