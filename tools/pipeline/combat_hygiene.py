#!/usr/bin/env python3
"""combat_hygiene.py — WorldForge v1.8 CombatForge artifact-hygiene gate.

The combat evidence tree (``procedural/reports/combat/``) must stay clean: it may
only ever contain combat evidence that maps to a REAL, generatable combat scenario,
and it must never accumulate UE transients, crash logs, or local save-slot junk.
This gate is the hygiene half of Agent 7's hostile lane — the twin of
[[combat_report_integrity]] (which polices whether evidence is HONEST); this one
polices whether the evidence tree is CLEAN.

Three invariants (contract §4/§5 + repo hygiene policy):

  (a) No orphan / stale evidence — every combat evidence file (``cs_<id>.json`` under
      ``completion/`` / ``telemetry/`` / ``save_load/``) must map to a combat
      scenario id that is genuinely GENERATABLE from the 120 v1.7 behavior
      scenarios (``cs_<id>`` derives from ``bs_<id>``). A ``cs_*.json`` whose id is
      not in that set is orphaned/stale/synthetic and is rejected. This same
      invariant catches leftover synthetic fixtures (invariant (c)) — a hand-made
      fixture id is not generatable.

  (b) No version-controllable junk — no UE transients (``Saved/`` / ``Intermediate/``
      / ``DerivedDataCache/`` / ``Binaries/``), crash logs, ``*.log``, or local
      save-slot files (``*.sav``) anywhere under the combat tree.

  (c) No leftover synthetic evidence — folded into (a): the ONLY legitimate
      ``cs_*.json`` files are ones a real matrix run produced for a generatable id.

ANTI-FAKE-GREEN: on the current EMPTY evidence tree (the 120 UE matrix has NOT run)
there are zero ``cs_*.json`` files, so orphan/junk scans are honestly clean and the
gate PASSes — but it still dogfoods its own logic on a throwaway temp fixture
(orphan + junk get flagged, a clean tree passes) so it never greens vacuously. It
leaves ZERO files behind under ``procedural/reports/combat/``.

Acceptance: PYTHONUTF8=1 STRICT=1 python tools/pipeline/combat_hygiene.py --strict
Exit 0 iff the combat evidence tree is clean.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode as F

COMBAT_REPORTS_ROOT = REPO_ROOT / "procedural" / "reports" / "combat"
BEHAVIOR_SCENARIOS_DIR = REPO_ROOT / "procedural" / "generated" / "npc" / "behavior_scenarios"

# The contract-pinned evidence subdirs whose cs_<id>.json files are per-scenario
# evidence (completion / telemetry / save_load). Files under other combat report
# dirs (validator outputs like *_report.json) are not cs_-evidence and are ignored.
EVIDENCE_SUBDIRS = ("completion", "telemetry", "save_load")

# Junk that must never live under the combat evidence tree.
JUNK_SUFFIXES = {".log", ".sav", ".tmp", ".bak", ".dmp", ".crash", ".pdb", ".obj"}
JUNK_NAME_SUBSTRINGS = ("crash",)  # crash logs / crash dumps under any name
JUNK_PATH_PARTS = {"Saved", "Intermediate", "DerivedDataCache", "Binaries", "Build"}


def generatable_combat_ids(behavior_dir=BEHAVIOR_SCENARIOS_DIR):
    """The set of combat scenario ids a real matrix run could legitimately produce:
    each of the 120 v1.7 behavior scenarios with its ``bs_`` prefix rewritten to
    ``cs_`` (contract §5: ``cs_<id>`` derives from ``bs_<id>``). Single source of
    truth for the orphan check, grounded in the actual generated behavior
    scenarios so it can never drift from what is generatable."""
    ids = set()
    d = Path(behavior_dir)
    if not d.is_dir():
        return ids
    for f in sorted(d.glob("bs_*.json")):
        bsid = f.stem
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            bsid = doc.get("behavior_scenario_id", bsid)
        except Exception:  # noqa: BLE001 — filename stem is a safe fallback
            pass
        if isinstance(bsid, str) and bsid.startswith("bs_"):
            ids.add("cs_" + bsid[len("bs_"):])
    return ids


def evidence_cs_files(root=COMBAT_REPORTS_ROOT):
    """Every combat evidence file (``cs_*.json``) under an EVIDENCE_SUBDIR of the
    combat reports tree. Returns a list of Paths (possibly empty)."""
    root = Path(root)
    out = []
    for sub in EVIDENCE_SUBDIRS:
        d = root / sub
        if d.is_dir():
            out.extend(sorted(d.rglob("cs_*.json")))
    return out


def orphan_evidence(root, generatable):
    """cs_*.json evidence files whose scenario id is NOT generatable. Returns a
    list of (relpath, cs_id) tuples (empty == clean)."""
    root = Path(root)
    orphans = []
    for p in evidence_cs_files(root):
        cs_id = p.stem
        if cs_id not in generatable:
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                rel = p.name
            orphans.append((rel, cs_id))
    return orphans


def _is_junk(path):
    if path.suffix.lower() in JUNK_SUFFIXES:
        return True
    low = path.name.lower()
    if any(s in low for s in JUNK_NAME_SUBSTRINGS):
        return True
    return any(part in JUNK_PATH_PARTS for part in path.parts)


def junk_paths(root=COMBAT_REPORTS_ROOT):
    """Any UE-transient / crash-log / save-slot junk under the combat tree. Returns
    a list of relpath strings (empty == clean)."""
    root = Path(root)
    if not root.is_dir():
        return []
    hits = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and _is_junk(p):
            try:
                hits.append(p.relative_to(root).as_posix())
            except ValueError:
                hits.append(p.name)
    return hits


def _dogfood(rep):
    """Prove the hygiene checkers constrain, on a THROWAWAY temp fixture that leaves
    nothing under procedural/reports/combat/. A clean tree passes; an orphan
    cs_*.json and junk files are flagged."""
    generatable = {"cs_enc_lp_Example_Good_01__light_pressure"}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # --- clean tree: one legitimate, generatable evidence file, no junk ---
        (root / "completion").mkdir(parents=True)
        (root / "completion" / "cs_enc_lp_Example_Good_01__light_pressure.json").write_text(
            "{}", encoding="utf-8")
        rep.check("dogfood::clean_no_orphans", orphan_evidence(root, generatable) == [],
                  "a generatable cs_*.json must not be flagged as orphan",
                  code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
        rep.check("dogfood::clean_no_junk", junk_paths(root) == [],
                  "a clean tree must report no junk", code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
        # --- dirty tree: orphan evidence + UE transients / crash log / save slot ---
        (root / "completion" / "cs_totally_synthetic_orphan.json").write_text(
            "{}", encoding="utf-8")
        (root / "telemetry").mkdir(parents=True)
        (root / "telemetry" / "WFCombat.log").write_text("x", encoding="utf-8")
        (root / "telemetry" / "WFCombat_State.sav").write_text("x", encoding="utf-8")
        (root / "telemetry" / "UECrash_2026.txt").write_text("x", encoding="utf-8")
        (root / "Saved").mkdir(parents=True)
        (root / "Saved" / "autosave.json").write_text("{}", encoding="utf-8")
        orphans = orphan_evidence(root, generatable)
        junk = junk_paths(root)
        rep.check("dogfood::orphan_flagged", any(o[1] == "cs_totally_synthetic_orphan"
                                                 for o in orphans),
                  "a non-generatable cs_*.json must be flagged as orphan (got {})".format(orphans),
                  code=F.COMBAT_REPORT_INTEGRITY_FAILURE)
        rep.check("dogfood::junk_flagged",
                  any(j.endswith("WFCombat.log") for j in junk)
                  and any(j.endswith("WFCombat_State.sav") for j in junk)
                  and any("Saved/" in j for j in junk)
                  and any("UECrash" in j for j in junk),
                  "UE transients / crash logs / save slots must be flagged (got {})".format(junk),
                  code=F.COMBAT_REPORT_INTEGRITY_FAILURE)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("pack", args.pack, strict=strict)

    # ---- self-proof: the checkers constrain even on an empty real tree ----
    _dogfood(rep)

    # ---- scan the real combat evidence tree ----
    generatable = generatable_combat_ids()
    rep.check("hygiene::generatable_known", len(generatable) > 0,
              "no generatable combat scenario ids resolved from {} — cannot validate "
              "orphans (behavior scenarios missing?)".format(
                  BEHAVIOR_SCENARIOS_DIR.relative_to(REPO_ROOT).as_posix()),
              warn_only=True, code=F.COMBAT_REPORT_INTEGRITY_FAILURE)

    orphans = orphan_evidence(COMBAT_REPORTS_ROOT, generatable)
    rep.check("hygiene::no_orphan_evidence", not orphans,
              "orphan/stale/synthetic combat evidence (id not generatable): {}".format(
                  orphans[:8]), code=F.COMBAT_REPORT_INTEGRITY_FAILURE)

    junk = junk_paths(COMBAT_REPORTS_ROOT)
    rep.check("hygiene::no_ue_transients_or_junk", not junk,
              "UE transients / crash logs / save-slot junk under the combat tree: {}".format(
                  junk[:8]), code=F.COMBAT_REPORT_INTEGRITY_FAILURE)

    n_ev = len(evidence_cs_files(COMBAT_REPORTS_ROOT))
    rep.check("hygiene::scan_ran", True,
              "scanned {} combat evidence file(s), {} generatable id(s) "
              "(0 evidence is a clean pass)".format(n_ev, len(generatable)),
              code=F.COMBAT_REPORT_INTEGRITY_FAILURE)

    rep.finalize()
    rep.set_meta(build_meta(command="combat-hygiene", pack=args.pack, strict=strict,
                            status=rep.status, record_count=n_ev,
                            report_type="wf.combat.hygiene.v1", records_total=n_ev))
    rep.write(REPO_ROOT / "procedural/reports/combat/hygiene", "combat_hygiene_report.json")
    rep.print_summary("combat-hygiene")
    print("[combat-hygiene] {} evidence file(s), {} orphan(s), {} junk file(s) "
          "(dogfood: clean/dirty temp fixture)".format(n_ev, len(orphans), len(junk)))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
