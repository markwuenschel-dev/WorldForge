#!/usr/bin/env python3
"""reward_report_integrity.py — WorldForge v1.9 Reward/Progression report-integrity gate.

Mirror of [[combat_report_integrity]] for the v1.9 reward/progression evidence
stream. Scans the committed reward COMPLETION / TELEMETRY / SAVE-LOAD evidence and
asserts it is honest: non-empty, never zero-record, and every
``reward_granted_runtime`` success is backed by REAL durable consequence
(inventory or progression mutation, >0 reward events, and a telemetry file that
exists on disk and passes the completion-strength telemetry validator).

Unlike the combat analog (whose runtime evidence does not exist until UE runs),
the v1.9 authoring evidence IS committed and STABLE, so this gate is NON-vacuous:
it requires > 0 completion + telemetry records and fails if the tree is empty.

Completion-report shape note: reward completion reports are built by
``reward_forge.build_reward_completion`` and DO NOT carry a v1.5 ``meta`` block —
they carry the report's own honesty fields. So this gate gates on the REAL fields
present (``report_id``, ``status``, ``completion_class``, ``telemetry_path``,
``git_commit``, ``created_at``) rather than a meta envelope. Save/load proofs DO
carry a meta block and are checked for a coherent pass status.

Anti-fake-green honesty burden enforced on completion evidence:
  * a ``reward_granted_runtime`` success MUST show inventory_mutated OR
    progression_mutated, reward_events_seen > 0, and a telemetry_path FILE that
    exists and passes validate_reward_telemetry(require_completion=True);
  * NO completion may claim success with reward_events_seen == 0 (zero-record
    success == REWARD_REPORT_INTEGRITY_FAILED);
  * staleness — authoring evidence carries git_commit="unknown" (allowed), but a
    report claiming created_at="live" MUST carry a real git sha (guards the future
    runtime lane, STALE_REWARD_EVIDENCE).

It never greens vacuously: it dogfoods its own logic in-memory (a real completion
passes; a zero-events success, an unmutated success, and a live-without-sha report
are each rejected) AND it asserts a non-zero real scan.

Acceptance: PYTHONUTF8=1 STRICT=1 python tools/pipeline/reward_report_integrity.py --strict
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode as F

COMPLETION_DIR = REPO_ROOT / RX.REWARD_COMPLETION_REPORTS_REL
TELEMETRY_DIR = REPO_ROOT / RX.REWARD_TELEMETRY_REPORTS_REL
SAVE_LOAD_DIR = REPO_ROOT / RX.REWARD_SAVE_LOAD_REPORTS_REL
PROGRESSION_SAVE_LOAD_DIR = REPO_ROOT / RX.PROGRESSION_REPORTS_REL / "save_load"

# The real (non-meta) fields a reward completion report must carry to be honest.
COMPLETION_REQUIRED_INTEGRITY_FIELDS = (
    "report_id", "status", "completion_class", "telemetry_path", "git_commit", "created_at",
)


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — unparseable is a finding, not a crash
        return None


def completion_integrity_violations(doc, repo_root=REPO_ROOT):
    """The single source of truth for 'is this reward COMPLETION evidence honest?'.
    Returns a list of problem strings (empty == clean). Dogfooded below so its own
    logic is proven even independent of the real committed evidence."""
    if not isinstance(doc, dict):
        return ["completion evidence is not a JSON object"]
    problems = []
    for f in COMPLETION_REQUIRED_INTEGRITY_FIELDS:
        if f not in doc:
            problems.append("missing required field {!r}".format(f))
    if doc.get("status") not in RX.RESULT_STATUS:
        problems.append("unknown status {!r}".format(doc.get("status")))
    if doc.get("completion_class") not in RX.REWARD_COMPLETION_CLASSES:
        problems.append("unknown completion_class {!r}".format(doc.get("completion_class")))

    cls = doc.get("completion_class")
    cnt = doc.get("reward_events_seen")
    inv_mut = doc.get("inventory_mutated")
    prog_mut = doc.get("progression_mutated")

    if cls == RX.SUCCESS_REWARD_CLASS:
        # Zero-record success is the headline fake-green vector.
        if not (isinstance(cnt, int) and cnt > 0):
            problems.append("reward_granted_runtime with reward_events_seen={} "
                            "(zero-record success)".format(cnt))
        if not (inv_mut is True or prog_mut is True):
            problems.append("reward_granted_runtime with no inventory/progression mutation")
        if doc.get("status") != "pass":
            problems.append("reward_granted_runtime with status={!r}".format(doc.get("status")))
        # Telemetry path must exist on disk and pass the completion-strength validator.
        tpath = doc.get("telemetry_path")
        if not (isinstance(tpath, str) and tpath):
            problems.append("reward_granted_runtime missing telemetry_path")
        else:
            tfile = Path(repo_root) / tpath
            if not tfile.is_file():
                problems.append("telemetry_path file does not exist on disk: {}".format(tpath))
            else:
                tdoc = _load(tfile)
                tfails = [c for c in RX.validate_reward_telemetry(
                    tdoc, strict=True, require_completion=True) if not c[1]]
                if tfails:
                    problems.append("telemetry {} fails completion-strength validation: {}".format(
                        tpath, tfails[0][2]))

    # Staleness: authoring evidence uses git_commit="unknown"; a 'live' report must
    # carry a real sha.
    if doc.get("created_at") == "live":
        sha = doc.get("git_commit")
        if not (isinstance(sha, str) and sha and sha != "unknown"):
            problems.append("created_at='live' but git_commit is not a real sha ({!r})".format(sha))
    return problems


def _dogfood(rep):
    """Prove the completion-integrity checker constrains, on synthetic records that
    leave no files behind. A real completion passes; a zero-events success, an
    unmutated success, and a live-without-sha report are each rejected."""
    # A real, contract-shaped authoring completion whose telemetry_path points at a
    # committed telemetry file (so the on-disk + completion-strength check is
    # exercised for real). Authoring evidence carries created_at="authoring".
    real = RX._example_reward_completion(created_at="authoring", git_commit="unknown")
    # Point it at an actual committed telemetry file if one exists, else the example path.
    committed_tel = sorted(TELEMETRY_DIR.glob("reward_telemetry_*.json"))
    if committed_tel:
        rel = committed_tel[0].relative_to(REPO_ROOT).as_posix()
        real = RX._example_reward_completion(created_at="authoring", git_commit="unknown",
                                             telemetry_path=rel, evidence_paths=[rel])
    rep.check("dogfood::real_completion_passes", completion_integrity_violations(real) == [],
              "a real reward completion with a valid telemetry file must pass; got {}".format(
                  completion_integrity_violations(real)[:3]),
              code=F.REWARD_REPORT_INTEGRITY_FAILED)
    # Zero-record success MUST be rejected.
    zero = RX._example_reward_completion(reward_events_seen=0)
    rep.check("dogfood::zero_events_success_flagged",
              len(completion_integrity_violations(zero)) > 0,
              "a reward_granted_runtime with reward_events_seen=0 must be rejected",
              code=F.REWARD_REPORT_INTEGRITY_FAILED)
    # Success with no state mutation MUST be rejected.
    no_mut = RX._example_reward_completion(inventory_mutated=False, progression_mutated=False)
    rep.check("dogfood::unmutated_success_flagged",
              len(completion_integrity_violations(no_mut)) > 0,
              "a reward_granted_runtime with no state mutation must be rejected",
              code=F.REWARD_REPORT_INTEGRITY_FAILED)
    # created_at='live' with git_commit='unknown' MUST be rejected (stale evidence).
    live_stale = RX._example_reward_completion(created_at="live", git_commit="unknown")
    rep.check("dogfood::live_without_sha_flagged",
              any("git_commit" in p for p in completion_integrity_violations(live_stale)),
              "a created_at='live' report without a real git sha must be rejected",
              code=F.STALE_REWARD_EVIDENCE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # ---- self-proof: the checker constrains regardless of real evidence ----
    _dogfood(rep)

    # ---- scan real reward completion evidence ----
    n_completion = 0
    for path in sorted(COMPLETION_DIR.glob("reward_completion_*.json")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        n_completion += 1
        doc = _load(path)
        if doc is None:
            rep.check("ri::{}::parseable".format(rel), False, "completion evidence not parseable",
                      code=F.REWARD_REPORT_INTEGRITY_FAILED)
            continue
        prob = completion_integrity_violations(doc)
        rep.check("ri::{}::honest".format(rel), not prob,
                  "reward completion evidence violations: {}".format(prob[:4]),
                  code=F.REWARD_REPORT_INTEGRITY_FAILED)

    # ---- scan real reward telemetry evidence ----
    n_telemetry = 0
    for path in sorted(TELEMETRY_DIR.glob("reward_telemetry_*.json")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        n_telemetry += 1
        doc = _load(path)
        if doc is None:
            rep.check("ri::{}::parseable".format(rel), False, "telemetry evidence not parseable",
                      code=F.REWARD_TELEMETRY_MISSING)
            continue
        tfails = [c for c in RX.validate_reward_telemetry(doc, strict=True) if not c[1]]
        rep.check("ri::{}::valid_events".format(rel), not tfails,
                  "reward telemetry must carry a non-empty valid events list: {}".format(
                      tfails[:2]), code=F.REWARD_TELEMETRY_MISSING)

    # ---- scan save/load proofs (inventory + progression) — must be pass ----
    n_save_load = 0
    for d in (SAVE_LOAD_DIR, PROGRESSION_SAVE_LOAD_DIR):
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*save_load_*.json")):
            # Per-scenario proofs only — skip sibling validator-output reports
            # (validate_*_report.json), which get their meta from ValidationReport.
            if path.name.startswith("validate_") or path.name.endswith("_report.json"):
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            n_save_load += 1
            doc = _load(path)
            if doc is None:
                rep.check("ri::{}::parseable".format(rel), False, "save/load proof not parseable",
                          code=F.REWARD_SAVE_LOAD_FAILED)
                continue
            rep.check("ri::{}::roundtrip_ok".format(rel), doc.get("roundtrip_ok") is True,
                      "save/load proof must show roundtrip_ok=true", code=F.REWARD_SAVE_LOAD_FAILED)
            meta = doc.get("meta")
            if isinstance(meta, dict):
                rep.check("ri::{}::meta_status_ok".format(rel),
                          meta.get("status") in ("ok", "pass"),
                          "save/load proof meta status must be ok/pass (got {!r})".format(
                              meta.get("status")),
                          code=F.REWARD_REPORT_INTEGRITY_FAILED)

    # ---- non-vacuous: the committed authoring evidence MUST be present ----
    rep.check("integrity::completion_nonempty", n_completion > 0,
              "reward completion evidence tree is empty ({}) — nothing to prove".format(
                  COMPLETION_DIR.relative_to(REPO_ROOT).as_posix()),
              code=F.REWARD_REPORT_INTEGRITY_FAILED)
    rep.check("integrity::telemetry_nonempty", n_telemetry > 0,
              "reward telemetry evidence tree is empty ({})".format(
                  TELEMETRY_DIR.relative_to(REPO_ROOT).as_posix()),
              code=F.REWARD_TELEMETRY_MISSING)

    rep.finalize()
    n = n_completion + n_telemetry + n_save_load
    rep.set_meta(build_meta(command="reward-report-integrity", pack=args.pack, strict=strict,
                            status=rep.status, record_count=n,
                            report_type="wf.reward.report_integrity.v1", records_total=n))
    rep.write(REPO_ROOT / "procedural/reports/rewards/report_integrity",
              "reward_report_integrity_report.json")
    rep.print_summary("reward-report-integrity")
    print("[reward-report-integrity] {} completion + {} telemetry + {} save/load evidence file(s) "
          "(dogfood: real / zero-events / unmutated / live-without-sha)".format(
              n_completion, n_telemetry, n_save_load))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
