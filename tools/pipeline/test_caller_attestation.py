#!/usr/bin/env python3
"""test_caller_attestation -- prove the attestation rails can actually go red.

WHY THIS BUILDS ITS OWN REPOSITORY
----------------------------------
The obvious way to test a commit resolver is to point it at a checkout that
happens to be on this machine. That is not a test: it passes because of a fact
about somebody's disk, it cannot construct the negative cases at all, and the
day that checkout moves the suite reports a defect in code that did not change.

So every resolution case here builds a throwaway git repository in a temp
directory, commits into it, and reads back the sha git actually produced. The
positive case is then a real commit resolved out of a real repository, and the
negative cases are constructible rather than hypothetical.

WHAT IS ACTUALLY BEING PROVEN
-----------------------------
Not "the happy path returns true" -- that proves almost nothing. The load-bearing
assertions are the ones that separate states a weaker implementation would blur:

  * absent      is not resolved   -- silence must never read as verified
  * unresolved  is not refuted    -- "could not check" must never read as "false"
  * refuted     is not unresolved -- a tested-and-failed claim must not hide
  * a stale-but-real commit still resolves, and reachability alone never fails it
"""

import os
import subprocess
import sys
import tempfile
import shutil

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from consumers import adapter as ADP                      # noqa: E402
from pipeline import verify_caller_attestation as VA      # noqa: E402
from wfcore import tri                                    # noqa: E402

_FAILS = []
_PASSES = [0]


def check(name, ok, detail=""):
    if ok:
        _PASSES[0] += 1
    else:
        _FAILS.append("{}: {}".format(name, detail))


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
_REMOTE = "https://github.com/example-org/example-game.git"


def _adapter(repository=None, commit_sha=None, origination=None):
    """A minimal adapter carrying only what these rails read.

    Deliberately not built through ``ADP.build_adapter``: this suite is testing
    the attestation accessors and the resolver, and threading a full valid
    adapter through would couple these assertions to unrelated schema churn.
    """
    prov = {
        "origination": origination or ADP.ORIGINATION_CALLER,
        "authored_by": "an external caller",
        "statement": "this intent originates from an importing project",
    }
    if repository is not None:
        prov["repository"] = repository
    if commit_sha is not None:
        prov["commit_sha"] = commit_sha
    return {"provenance": prov}


def _git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args),
                          capture_output=True, text=True, timeout=30)


def _make_repo(tmp, remote=_REMOTE, commits=2):
    """A real git repository with real commits. Returns (path, [shas])."""
    path = os.path.join(tmp, "callerrepo")
    os.makedirs(path)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.invalid")
    _git(path, "config", "user.name", "T")
    _git(path, "config", "commit.gpgsign", "false")
    shas = []
    for i in range(commits):
        with open(os.path.join(path, "f{}.txt".format(i)), "w",
                  encoding="utf-8") as fh:
            fh.write("content {}\n".format(i))
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", "commit {}".format(i))
        shas.append(_git(path, "rev-parse", "HEAD").stdout.strip())
    if remote:
        _git(path, "remote", "add", "origin", remote)
    return path, shas


def _state(adapter, repo_path=None, strict=False):
    rec = VA.build_attestation_record(adapter, repo_path=repo_path,
                                      strict=strict)
    return rec["resolution_state"], rec["verdict"], rec


# --------------------------------------------------------------------------- #
# 1. shape / accessor layer -- no git involved
# --------------------------------------------------------------------------- #
def test_attestation_states():
    check("absent_when_neither_field",
          ADP.attestation_of(_adapter()) == ADP.ATTESTATION_ABSENT,
          ADP.attestation_of(_adapter()))

    a = _adapter(repository=_REMOTE, commit_sha="a" * 40)
    check("declared_when_both_wellformed",
          ADP.attestation_of(a) == ADP.ATTESTATION_DECLARED,
          ADP.attestation_of(a))

    # HALF an attestation is the dangerous case: it reads like evidence in a
    # report and resolves to nothing.
    for partial in (_adapter(repository=_REMOTE),
                    _adapter(commit_sha="a" * 40)):
        check("malformed_when_half_supplied",
              ADP.attestation_of(partial) == ADP.ATTESTATION_MALFORMED,
              ADP.attestation_of(partial))

    for bad in ("", "   ", "nothexadecimal!", "abc", "z" * 40, "A" * 200):
        m = _adapter(repository=_REMOTE, commit_sha=bad)
        check("malformed_sha_{!r}".format(bad[:12]),
              ADP.attestation_of(m) == ADP.ATTESTATION_MALFORMED,
              "sha {!r} -> {}".format(bad, ADP.attestation_of(m)))

    check("empty_repository_is_malformed",
          ADP.attestation_of(
              _adapter(repository="  ", commit_sha="a" * 40))
          == ADP.ATTESTATION_MALFORMED)

    # Short-but-legal git abbreviation must be accepted; git's own default is 7.
    check("seven_char_sha_is_wellformed",
          ADP.attestation_of(_adapter(repository=_REMOTE, commit_sha="abc1234"))
          == ADP.ATTESTATION_DECLARED)


def test_remote_normalisation():
    forms = [
        "https://github.com/example-org/example-game.git",
        "https://github.com/example-org/example-game",
        "git@github.com:example-org/example-game.git",
        "ssh://git@github.com/example-org/example-game.git",
        "https://github.com/example-org/example-game/",
        "https://TOKEN@github.com/example-org/example-game.git",
    ]
    norm = {VA.normalize_remote(f) for f in forms}
    check("all_spellings_normalise_alike", len(norm) == 1,
          "got {}".format(norm))
    check("different_repos_stay_different",
          VA.normalize_remote("https://github.com/a/b")
          != VA.normalize_remote("https://github.com/a/c"))
    check("none_stays_none", VA.normalize_remote(None) is None)
    check("empty_stays_none", VA.normalize_remote("   ") is None)


# --------------------------------------------------------------------------- #
# 2. the state separations -- the assertions that actually matter
# --------------------------------------------------------------------------- #
def test_absent_is_never_resolved(tmp):
    repo, _shas = _make_repo(tmp)
    st, verdict, rec = _state(_adapter(), repo_path=repo)
    check("absent_stays_absent_even_with_a_repo", st == VA.ABSENT, st)
    check("absent_verdict_is_unknown", verdict == tri.UNKNOWN, verdict)
    check("absent_raises_no_code", rec["failure_codes"] == [],
          rec["failure_codes"])


def test_unresolved_is_not_refuted():
    a = _adapter(repository=_REMOTE, commit_sha="a" * 40)
    st, verdict, rec = _state(a, repo_path=None)
    check("no_repo_is_unresolved", st == VA.UNRESOLVED, st)
    check("unresolved_is_unknown_not_violated", verdict == tri.UNKNOWN, verdict)
    check("unresolved_raises_no_code_by_default", rec["failure_codes"] == [],
          rec["failure_codes"])
    # ...but strict mode is allowed to demand a decision.
    st2, _v2, rec2 = _state(a, repo_path=None, strict=True)
    check("strict_makes_unsupplied_a_failure", bool(rec2["failure_codes"]),
          rec2["failure_codes"])


def test_resolved_positive(tmp):
    repo, shas = _make_repo(tmp)
    a = _adapter(repository=_REMOTE, commit_sha=shas[-1])
    st, verdict, rec = _state(a, repo_path=repo)
    check("real_commit_real_remote_resolves", st == VA.RESOLVED,
          "{} / {}".format(st, rec["failure_codes"]))
    check("resolved_is_satisfied", verdict == tri.SATISFIED, verdict)

    # A STALE but real commit is still real. This is the exact shape of the
    # live caller's claim -- authored at an older commit, still a true ancestor
    # -- and refusing it would be wrong.
    older = _adapter(repository=_REMOTE, commit_sha=shas[0])
    st2, v2, _r2 = _state(older, repo_path=repo)
    check("stale_but_real_commit_still_resolves", st2 == VA.RESOLVED, st2)
    check("stale_commit_is_satisfied", v2 == tri.SATISFIED, v2)

    # Abbreviated sha of a real commit must resolve too.
    ab = _adapter(repository=_REMOTE, commit_sha=shas[-1][:10])
    st3, _v3, _r3 = _state(ab, repo_path=repo)
    check("abbreviated_real_sha_resolves", st3 == VA.RESOLVED, st3)


def test_refuted_missing_commit(tmp):
    repo, _shas = _make_repo(tmp)
    # Well-formed hex that names nothing in this repository.
    a = _adapter(repository=_REMOTE, commit_sha="0123456789abcdef" * 2 + "01234567")
    st, verdict, rec = _state(a, repo_path=repo)
    check("nonexistent_commit_is_refuted", st == VA.REFUTED, st)
    check("refuted_is_violated_not_unknown", verdict == tri.VIOLATED, verdict)
    check("refuted_raises_wf1291",
          "WF1291_CORE_CALLER_ATTESTATION_UNRESOLVED" in rec["failure_codes"],
          rec["failure_codes"])


def test_refuted_wrong_remote(tmp):
    repo, shas = _make_repo(tmp, remote="https://github.com/someone/else.git")
    a = _adapter(repository=_REMOTE, commit_sha=shas[-1])
    st, verdict, rec = _state(a, repo_path=repo)
    check("commit_resolved_in_the_wrong_repo_is_refuted", st == VA.REFUTED, st)
    check("wrong_remote_is_violated", verdict == tri.VIOLATED, verdict)
    check("wrong_remote_raises_wf1291",
          "WF1291_CORE_CALLER_ATTESTATION_UNRESOLVED" in rec["failure_codes"],
          rec["failure_codes"])


def test_unresolvable_environment(tmp):
    # A directory that exists but is not a repository: we could not check.
    plain = os.path.join(tmp, "notarepo")
    os.makedirs(plain)
    a = _adapter(repository=_REMOTE, commit_sha="a" * 40)
    st, verdict, _rec = _state(a, repo_path=plain)
    check("non_git_directory_is_unresolved", st == VA.UNRESOLVED, st)
    check("non_git_directory_is_unknown_not_violated",
          verdict == tri.UNKNOWN, verdict)

    missing = os.path.join(tmp, "does", "not", "exist")
    st2, v2, _r2 = _state(a, repo_path=missing)
    check("missing_path_is_unresolved", st2 == VA.UNRESOLVED, st2)
    check("missing_path_is_unknown", v2 == tri.UNKNOWN, v2)


def test_no_origin_remote(tmp):
    repo, shas = _make_repo(tmp, remote=None)
    a = _adapter(repository=_REMOTE, commit_sha=shas[-1])
    st, verdict, _rec = _state(a, repo_path=repo)
    check("no_origin_cannot_corroborate", st in (VA.REFUTED, VA.UNRESOLVED), st)
    check("no_origin_is_not_satisfied", verdict != tri.SATISFIED, verdict)


def test_malformed_never_touches_git(tmp):
    repo, _shas = _make_repo(tmp)
    a = _adapter(repository=_REMOTE, commit_sha="not-a-sha")
    st, verdict, rec = _state(a, repo_path=repo)
    check("malformed_short_circuits", st == VA.MALFORMED, st)
    check("malformed_is_violated", verdict == tri.VIOLATED, verdict)
    check("malformed_raises_wf1291",
          "WF1291_CORE_CALLER_ATTESTATION_UNRESOLVED" in rec["failure_codes"],
          rec["failure_codes"])


def test_states_are_mutually_exclusive(tmp):
    """Every fixture lands in exactly one declared state, and the set is closed."""
    repo, shas = _make_repo(tmp)
    cases = [
        (_adapter(), repo),
        (_adapter(repository=_REMOTE, commit_sha=shas[-1]), repo),
        (_adapter(repository=_REMOTE, commit_sha="b" * 40), repo),
        (_adapter(repository=_REMOTE, commit_sha="a" * 40), None),
        (_adapter(repository=_REMOTE, commit_sha="nope"), repo),
    ]
    seen = []
    for adapter, rp in cases:
        st, _v, _r = _state(adapter, repo_path=rp)
        check("state_in_closed_set", st in VA.RESOLUTION_STATES, st)
        seen.append(st)
    check("fixtures_cover_distinct_states", len(set(seen)) >= 4,
          "states seen: {}".format(seen))


# --------------------------------------------------------------------------- #
def main():
    have_git = shutil.which("git") is not None
    if not have_git:
        # Refuse to report green on a machine that could not run the resolution
        # half at all. A suite that silently skips its own substance is the
        # fake-green this file exists to prevent.
        print("test_caller_attestation: FAIL -- git is not on PATH, so every "
              "resolution case would be skipped; that cannot be reported green")
        return 2

    test_attestation_states()
    test_remote_normalisation()
    test_unresolved_is_not_refuted()

    tmp = tempfile.mkdtemp(prefix="wf_attest_")
    try:
        for fn in (test_absent_is_never_resolved, test_resolved_positive,
                   test_refuted_missing_commit, test_refuted_wrong_remote,
                   test_unresolvable_environment, test_no_origin_remote,
                   test_malformed_never_touches_git,
                   test_states_are_mutually_exclusive):
            sub = tempfile.mkdtemp(prefix="case_", dir=tmp)
            fn(sub)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if _FAILS:
        print("test_caller_attestation: {} passed, {} FAILED".format(
            _PASSES[0], len(_FAILS)))
        for f in _FAILS:
            print("  - {}".format(f))
        return 1
    print("test_caller_attestation: {} assertion(s) passed, 0 failed".format(
        _PASSES[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
