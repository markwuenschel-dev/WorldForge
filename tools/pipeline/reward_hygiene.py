#!/usr/bin/env python3
"""reward_hygiene.py — WorldForge v1.9 Reward/Progression artifact-hygiene gate.

The reward/progression evidence + generated trees (``procedural/reports/rewards/``,
``procedural/reports/progression/``, ``procedural/generated/rewards/``,
``procedural/generated/progression/``) must stay clean: every per-scenario evidence
file must map to a REAL scenario that has GENERATED STATE, no file may leak an
absolute filesystem path or a forbidden runtime save slot into content, and the
tree must never accumulate UE transients / crash logs / local ``*.sav`` junk. This
is the hygiene twin of [[reward_report_integrity]] (which polices whether evidence
is HONEST); this one polices whether the evidence tree is CLEAN. Mirrors
[[combat_hygiene]].

Three invariants:

  (a) No orphan / stray evidence — every scenario-scoped evidence file (one that
      carries a ``scenario_id``) must reference a scenario id that HAS generated
      state (the committed ``procedural/generated/progression/inventory/*.json``
      stems are the single source of truth for "has generated state"). An evidence
      file whose scenario has no generated state is orphaned/stray and rejected.

  (b) No path / save-slot leak — no evidence file may embed an ABSOLUTE filesystem
      path (a Windows drive like ``D:\\`` or a unix ``/home`` / ``/Users`` /
      ``/mnt`` root) or a FORBIDDEN runtime save slot (WFRuntime_Complete /
      WFNPC_State / WFCombat_State) — reward/progression state uses only its own
      dedicated slots.

  (c) No version-controllable junk — no UE transients (``Saved/`` / ``Intermediate/``
      / ``DerivedDataCache/`` / ``Binaries/``), crash logs, ``*.log``, or local
      save-slot files (``*.sav``) anywhere under the reward/progression trees.

ANTI-FAKE-GREEN: it dogfoods its own logic on a throwaway temp fixture (orphan +
absolute-path leak + save-slot leak + junk all get flagged; a clean tree passes),
leaving ZERO files behind, and asserts the real generatable set is non-empty so it
can never validate orphans vacuously.

Acceptance: PYTHONUTF8=1 STRICT=1 python tools/pipeline/reward_hygiene.py --strict
Exit 0 iff the reward/progression trees are clean.
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import reward_contracts as RX
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode as F

# The generated-state root whose stems ground "this scenario has generated state".
GENERATED_STATE_DIR = REPO_ROOT / "procedural" / "generated" / "progression" / "inventory"

# Trees scanned for orphan evidence (scenario-scoped) + leaks + junk.
SCAN_ROOTS = (
    REPO_ROOT / "procedural" / "reports" / "rewards",
    REPO_ROOT / "procedural" / "reports" / "progression",
    REPO_ROOT / "procedural" / "generated" / "rewards",
    REPO_ROOT / "procedural" / "generated" / "progression",
)

# Junk that must never live under the reward/progression trees.
JUNK_SUFFIXES = {".log", ".sav", ".tmp", ".bak", ".dmp", ".crash", ".pdb", ".obj"}
JUNK_NAME_SUBSTRINGS = ("crash",)
JUNK_PATH_PARTS = {"Saved", "Intermediate", "DerivedDataCache", "Binaries", "Build"}

# Absolute-path leak signatures: a Windows drive root or a unix home/system root.
_ABS_PATH_RE = re.compile(r"[A-Za-z]:[\\/]|/(?:home|Users|mnt|root)/")


def _is_validator_output(path):
    """Validator-output reports (validate_*.json / *_report.json) are not evidence;
    they carry ValidationReport meta (incl. a git_sha) and are policed by their own
    gates, so they are excluded from the evidence/leak/orphan scans."""
    n = path.name
    return n.startswith("validate_") or n.endswith("_report.json")


def generatable_scenarios(state_dir=GENERATED_STATE_DIR):
    """The set of scenario ids that HAVE generated state — the committed inventory
    state file stems. Single source of truth for the orphan check, grounded in the
    actual generated state so it can never drift from what is generatable."""
    d = Path(state_dir)
    if not d.is_dir():
        return set()
    return {p.stem for p in d.glob("*.json") if not _is_validator_output(p)}


RUNTIME_SL_DIR = REPO_ROOT / "procedural" / "reports" / "rewards" / "save_load"


def runtime_backed_scenarios(sl_dir=RUNTIME_SL_DIR):
    """Scenario ids backed by a genuine RUNTIME save/load proof (roundtrip_ok=true).

    A runtime ``reward_granted_runtime`` completion writes no ``generated/`` state —
    its durable state lives in the engine save slots (WFReward/Inventory/
    Progression_State), attested by the in-engine reload-verify these proofs record.
    So a runtime proof grounds a scenario exactly as generated state grounds an
    authoring scenario; both count as "not orphan". An actual orphan (a completion
    with neither generated state nor a runtime proof) is still rejected."""
    d = Path(sl_dir)
    if not d.is_dir():
        return set()
    out = set()
    for p in d.glob("inventory_save_load_*.json"):
        if _is_validator_output(p):
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(doc, dict) and doc.get("roundtrip_ok") is True and isinstance(doc.get("scenario_id"), str):
            out.add(doc["scenario_id"])
    return out


def _iter_evidence(root):
    """Yield (path, doc) for every scenario-scoped JSON evidence file under root
    (one that carries a ``scenario_id``). Robust to unparseable files (doc=None)."""
    root = Path(root)
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*.json")):
        if _is_validator_output(p):
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            doc = None
        yield p, doc


def orphan_evidence(roots, generatable):
    """Scenario-scoped evidence files whose scenario_id has no generated state.
    Returns a list of (relpath, scenario_id) tuples (empty == clean)."""
    orphans = []
    for root in roots:
        for p, doc in _iter_evidence(root):
            sid = doc.get("scenario_id") if isinstance(doc, dict) else None
            if not isinstance(sid, str):
                continue  # not scenario-scoped (catalog/table/unlock record) — skip
            if sid not in generatable:
                try:
                    rel = p.relative_to(REPO_ROOT).as_posix()
                except ValueError:
                    rel = p.name
                orphans.append((rel, sid))
    return orphans


def leak_violations(roots):
    """Evidence files that embed an absolute path or a forbidden save slot. Returns
    a list of (relpath, reason) tuples (empty == clean)."""
    hits = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.json")):
            if _is_validator_output(p):
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                continue
            rel = p.relative_to(REPO_ROOT).as_posix() if REPO_ROOT in p.parents else p.name
            if _ABS_PATH_RE.search(text):
                hits.append((rel, "absolute filesystem path leaked into evidence"))
            for slot in RX.FORBIDDEN_SAVE_SLOTS:
                if slot in text:
                    hits.append((rel, "forbidden save slot {!r} leaked into evidence".format(slot)))
    return hits


def _is_junk(path):
    if path.suffix.lower() in JUNK_SUFFIXES:
        return True
    low = path.name.lower()
    if any(s in low for s in JUNK_NAME_SUBSTRINGS):
        return True
    return any(part in JUNK_PATH_PARTS for part in path.parts)


def junk_paths(roots):
    """Any UE-transient / crash-log / save-slot junk under the trees. Returns a list
    of relpath strings (empty == clean)."""
    hits = []
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and _is_junk(p):
                base = REPO_ROOT if REPO_ROOT in p.parents else root
                try:
                    hits.append(p.relative_to(base).as_posix())
                except ValueError:
                    hits.append(p.name)
    return hits


def _dogfood(rep):
    """Prove the hygiene checkers constrain, on a THROWAWAY temp fixture that leaves
    nothing under the real trees. A clean tree passes; an orphan evidence file, an
    absolute-path leak, a forbidden save-slot leak, and junk files are flagged."""
    generatable = {"rs_auth_00_rwt_disable_site_baseline"}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        comp = root / "rewards" / "completion"
        comp.mkdir(parents=True)
        # --- clean: one generatable evidence file, no leak, no junk ---
        (comp / "reward_completion_rs_auth_00_rwt_disable_site_baseline.json").write_text(
            json.dumps({"scenario_id": "rs_auth_00_rwt_disable_site_baseline",
                        "save_load_key": "WFReward_State"}), encoding="utf-8")
        roots = [root]
        rep.check("dogfood::clean_no_orphans", orphan_evidence(roots, generatable) == [],
                  "a generatable evidence file must not be flagged as orphan",
                  code=F.REWARD_REPORT_INTEGRITY_FAILED)
        rep.check("dogfood::clean_no_leaks", leak_violations(roots) == [],
                  "a clean evidence file must report no leaks", code=F.REWARD_REPORT_INTEGRITY_FAILED)
        rep.check("dogfood::clean_no_junk", junk_paths(roots) == [],
                  "a clean tree must report no junk", code=F.REWARD_REPORT_INTEGRITY_FAILED)
        # --- dirty: orphan evidence + abs-path leak + save-slot leak + junk ---
        (comp / "reward_completion_rs_totally_orphan.json").write_text(
            json.dumps({"scenario_id": "rs_totally_orphan"}), encoding="utf-8")
        (comp / "reward_completion_rs_leak_abs.json").write_text(
            json.dumps({"scenario_id": "rs_auth_00_rwt_disable_site_baseline",
                        "path": "D:\\Unreal Projects\\WorldForge\\leak.json"}), encoding="utf-8")
        (comp / "reward_completion_rs_leak_slot.json").write_text(
            json.dumps({"scenario_id": "rs_auth_00_rwt_disable_site_baseline",
                        "save_load_key": "WFCombat_State"}), encoding="utf-8")
        (comp / "WFReward.log").write_text("x", encoding="utf-8")
        (comp / "WFReward_State.sav").write_text("x", encoding="utf-8")
        (root / "rewards" / "Saved").mkdir(parents=True)
        (root / "rewards" / "Saved" / "autosave.json").write_text("{}", encoding="utf-8")
        orphans = orphan_evidence(roots, generatable)
        leaks = leak_violations(roots)
        junk = junk_paths(roots)
        rep.check("dogfood::orphan_flagged",
                  any(sid == "rs_totally_orphan" for _, sid in orphans),
                  "a scenario with no generated state must be flagged as orphan (got {})".format(
                      orphans), code=F.REWARD_REPORT_INTEGRITY_FAILED)
        rep.check("dogfood::abs_path_leak_flagged",
                  any("absolute" in reason for _, reason in leaks),
                  "an absolute filesystem path must be flagged (got {})".format(leaks),
                  code=F.REWARD_REPORT_INTEGRITY_FAILED)
        rep.check("dogfood::save_slot_leak_flagged",
                  any("WFCombat_State" in reason for _, reason in leaks),
                  "a forbidden save slot must be flagged (got {})".format(leaks),
                  code=F.REWARD_REPORT_INTEGRITY_FAILED)
        rep.check("dogfood::junk_flagged",
                  any(j.endswith("WFReward.log") for j in junk)
                  and any(j.endswith("WFReward_State.sav") for j in junk)
                  and any("Saved/" in j for j in junk),
                  "UE transients / crash logs / save slots must be flagged (got {})".format(junk),
                  code=F.REWARD_REPORT_INTEGRITY_FAILED)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # ---- self-proof: the checkers constrain regardless of the real tree ----
    _dogfood(rep)

    # ---- scan the real reward/progression trees ----
    generatable = generatable_scenarios() | runtime_backed_scenarios()
    rep.check("hygiene::generatable_known", len(generatable) > 0,
              "no generatable scenario ids resolved from {} — cannot validate orphans".format(
                  GENERATED_STATE_DIR.relative_to(REPO_ROOT).as_posix()),
              code=F.REWARD_REPORT_INTEGRITY_FAILED)

    orphans = orphan_evidence(SCAN_ROOTS, generatable)
    rep.check("hygiene::no_orphan_evidence", not orphans,
              "orphan/stray reward evidence (scenario has no generated state): {}".format(
                  orphans[:8]), code=F.REWARD_REPORT_INTEGRITY_FAILED)

    leaks = leak_violations(SCAN_ROOTS)
    rep.check("hygiene::no_path_or_save_slot_leak", not leaks,
              "absolute-path / forbidden-save-slot leak in reward evidence: {}".format(
                  leaks[:8]), code=F.REWARD_REPORT_INTEGRITY_FAILED)

    junk = junk_paths(SCAN_ROOTS)
    rep.check("hygiene::no_ue_transients_or_junk", not junk,
              "UE transients / crash logs / save-slot junk under the reward trees: {}".format(
                  junk[:8]), code=F.REWARD_REPORT_INTEGRITY_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(command="reward-hygiene", pack=args.pack, strict=strict,
                            status=rep.status, record_count=len(generatable),
                            report_type="wf.reward.hygiene.v1", records_total=len(generatable)))
    rep.write(REPO_ROOT / "procedural/reports/rewards/hygiene", "reward_hygiene_report.json")
    rep.print_summary("reward-hygiene")
    print("[reward-hygiene] {} generatable scenario(s), {} orphan(s), {} leak(s), {} junk file(s) "
          "(dogfood: clean/dirty temp fixture)".format(
              len(generatable), len(orphans), len(leaks), len(junk)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
