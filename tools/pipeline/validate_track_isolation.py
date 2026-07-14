#!/usr/bin/env python3
"""validate_track_isolation.py — v2.5 shield ``--track-isolation`` gate (Lane 2).

Proves the frozen 5.7 track and the active 5.8 track cannot silently write over
each other. This is a REAL filesystem gate, not a schema fixture:

  * the two worktrees (5.7 = ``D:/Unreal Projects/WorldForge``, 5.8 =
    ``D:/Unreal Projects/WorldForge-UE58``) resolve to DIFFERENT absolute
    Saved / Intermediate / Binaries / DerivedDataCache paths — no shared writable
    build/output dir that a 5.8 build could clobber in the 5.7 tree or vice versa;
  * the report subtrees ``procedural/reports/ue5_7`` and ``.../ue5_8`` are
    disjoint (neither contains the other);
  * the preservation refs exist so the 5.7 line is recoverable — branch
    ``release/ue5.7-v2.4-lts`` and tag ``worldforge-v2.4-ue5.7-final``. If either
    is ABSENT it is reported as a NON-BLOCKING known-gap for the commander to
    create (this lane never creates refs).

Negatives (inline, must be rejected): a shared writable Saved/Intermediate/binary
path across the two tracks; a report fingerprinted to the wrong worktree.

Runtime-free gate. Report -> procedural/reports/ue5_8/validate_track_isolation_report.json
Acceptance: PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_track_isolation.py --strict
"""

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode as C  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from transition_identity import transition_identity, worktree_identifier  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8"

# The two tracks, by their worktree roots (absolute, real on this machine).
TRACK_5_7_ROOT = Path("D:/Unreal Projects/WorldForge")
TRACK_5_8_ROOT = Path("D:/Unreal Projects/WorldForge-UE58")

# Per-worktree writable dirs that MUST NOT be shared between tracks.
ISOLATED_DIRS = ("Saved", "Intermediate", "Binaries", "DerivedDataCache")

# Preservation refs the 5.7 line must be recoverable from.
PRESERVATION_BRANCH = "release/ue5.7-v2.4-lts"
PRESERVATION_TAG = "worldforge-v2.4-ue5.7-final"


def _norm(p):
    return Path(p).resolve().as_posix().rstrip("/").lower()


def _within(child, parent):
    """True iff child == parent or parent is an ancestor of child (shared writable)."""
    c, pr = Path(child).resolve(), Path(parent).resolve()
    return c == pr or pr in c.parents


def isolation_checks(a_root, b_root, label):
    """Per-dir isolation checks between two track roots.

    A dir is isolated iff the two tracks' copies are neither equal nor nested —
    a nested pair (one inside the other) is a shared-writable hazard.
    """
    ch = []
    ch.append(("iso::{}::roots_distinct".format(label),
               _norm(a_root) != _norm(b_root),
               "the two tracks share a worktree root: {}".format(_norm(a_root)),
               C.TRANSITION_HYGIENE_FAILED))
    for d in ISOLATED_DIRS:
        pa, pb = Path(a_root) / d, Path(b_root) / d
        isolated = (_norm(pa) != _norm(pb)
                    and not _within(pa, pb) and not _within(pb, pa))
        ch.append(("iso::{}::{}_isolated".format(label, d), isolated,
                   "tracks share writable {} dir: {} vs {}".format(d, _norm(pa), _norm(pb)),
                   C.TRANSITION_HYGIENE_FAILED))
    return ch


def report_subtree_checks(root):
    a = Path(root) / "procedural" / "reports" / "ue5_7"
    b = Path(root) / "procedural" / "reports" / "ue5_8"
    disjoint = (_norm(a) != _norm(b)
                and not _within(a, b) and not _within(b, a))
    return [("iso::report_subtrees_disjoint", disjoint,
             "ue5_7 and ue5_8 report subtrees overlap: {} vs {}".format(_norm(a), _norm(b)),
             C.TRANSITION_HYGIENE_FAILED)]


def worktree_match_check(meta, expected):
    wt = meta.get("worktree_identifier")
    return [("iso::report_worktree_matches", wt == expected,
             "report worktree_identifier {!r} != this worktree {!r}".format(wt, expected),
             C.TRANSITION_REPORT_INTEGRITY_FAILED)]


def _git(args):
    try:
        out = subprocess.run(["git", *args], cwd=str(REPO_ROOT),
                             capture_output=True, text=True)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def run(rep):
    this_wt = worktree_identifier()

    # 1. REAL isolation between the two live worktrees.
    for name, ok, detail, code in isolation_checks(TRACK_5_7_ROOT, TRACK_5_8_ROOT, "real"):
        rep.check(name, ok, detail, code=code)
    for name, ok, detail, code in report_subtree_checks(TRACK_5_8_ROOT):
        rep.check(name, ok, detail, code=code)

    # 2. Both worktree roots really exist on disk (isolation is only meaningful
    #    if the frozen 5.7 tree is actually present alongside the 5.8 tree).
    rep.check("iso::track_5_7_worktree_present", TRACK_5_7_ROOT.is_dir(),
              "frozen 5.7 worktree missing at {}".format(TRACK_5_7_ROOT),
              code=C.TRANSITION_HYGIENE_FAILED)
    rep.check("iso::track_5_8_worktree_present", TRACK_5_8_ROOT.is_dir(),
              "active 5.8 worktree missing at {}".format(TRACK_5_8_ROOT),
              code=C.TRANSITION_HYGIENE_FAILED)

    # 3. Preservation refs — present => PASS; absent => NON-BLOCKING known-gap.
    branch_present = bool(_git(["branch", "--list", PRESERVATION_BRANCH]))
    tag_present = bool(_git(["tag", "--list", PRESERVATION_TAG]))
    if branch_present:
        rep.check("preservation::branch_present", True,
                  "preservation branch {} exists".format(PRESERVATION_BRANCH))
    else:
        rep.warn_only("preservation::branch_present", False,
                      "KNOWN-GAP: commander must create branch {}".format(PRESERVATION_BRANCH),
                      code=C.TRANSITION_HYGIENE_FAILED)
    if tag_present:
        rep.check("preservation::tag_present", True,
                  "preservation tag {} exists".format(PRESERVATION_TAG))
    else:
        rep.warn_only("preservation::tag_present", False,
                      "KNOWN-GAP: commander must create tag {}".format(PRESERVATION_TAG),
                      code=C.TRANSITION_HYGIENE_FAILED)

    # 4. Negatives — each MUST be rejected.
    #    a) two tracks pointing at the SAME root share every writable dir.
    shared = [c for c in isolation_checks(TRACK_5_8_ROOT, TRACK_5_8_ROOT, "neg") if not c[1]]
    scodes = {c[3] for c in shared}
    rep.check("negative::shared_writable_dirs_rejected", len(shared) > 0,
              "a shared writable Saved/Intermediate/Binaries path must be rejected",
              code=C.TRANSITION_NEGATIVE_ACCEPTED)
    rep.check("negative::shared_writable_owning_code",
              C.TRANSITION_HYGIENE_FAILED in scodes,
              "shared-writable negative must be rejected for {} (got {})".format(
                  C.TRANSITION_HYGIENE_FAILED, sorted(str(c) for c in scodes)[:4]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)
    #    b) a report fingerprinted to the wrong worktree.
    wrong_meta = {"worktree_identifier": "deadbeefcafe:SomeOtherTree"}
    wrong = [c for c in worktree_match_check(wrong_meta, this_wt) if not c[1]]
    wcodes = {c[3] for c in wrong}
    rep.check("negative::wrong_worktree_report_rejected", len(wrong) > 0,
              "a report from the wrong worktree must be rejected",
              code=C.TRANSITION_NEGATIVE_ACCEPTED)
    rep.check("negative::wrong_worktree_owning_code",
              C.TRANSITION_REPORT_INTEGRITY_FAILED in wcodes,
              "wrong-worktree negative must be rejected for {} (got {})".format(
                  C.TRANSITION_REPORT_INTEGRITY_FAILED, sorted(str(c) for c in wcodes)[:4]),
              code=C.TRANSITION_NEGATIVE_ACCEPTED)


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 dual-track isolation gate.")
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("gate", "track_isolation", strict=strict)
    run(rep)
    rep.finalize()
    rep.set_meta(build_meta(
        command="validate-track-isolation", pack=args.pack, strict=strict,
        status=rep.status, record_count=len(rep.checks), records_total=len(rep.checks),
        report_type="wf.transition.track_isolation_gate.v1",
        extra=transition_identity("5.8", runtime_required=False,
                                  runtime_executed=False, observed_runtime_engine=None)))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "validate_track_isolation_report.json")
    rep.print_summary("track-isolation")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
