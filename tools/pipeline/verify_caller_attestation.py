#!/usr/bin/env python3
"""verify_caller_attestation -- resolve a caller's provenance claim about itself.

WHAT THIS IS FOR
----------------
A consumer adapter authored by a real importing game can declare, in
``provenance``, the repository it lives in and the commit it was authored at.
Those two fields are the ONLY independently checkable facts in the whole
provenance record: everything else is the caller describing itself, and a
description cannot be wrong in a way a machine can notice.

Before this module existed, they were not checked. The repository URL and the
commit sha were interpolated into a prose sentence, the provenance rail asserted
the sentence was a non-empty string, and the flow runner did not carry either
value into the artifact it wrote. So the strongest evidence the caller offered
was discarded twice -- once by not being parsed, and once by not being persisted.

WHAT THIS DOES NOT DO, AND WHY IT MATTERS
-----------------------------------------
It does not decide whether the caller is real. That question belongs to
``consumers.adapter``: an adapter DECLARES its origination and Core refuses to
upgrade a run beyond what was declared (WF1288). This module answers a narrower
and more useful question -- *given that a caller named a repository and a
commit, do they exist and do they match?* -- and it answers it against a
repository on disk rather than against the caller's own say-so.

The distinction is load-bearing. WF1288 is WorldForge claiming a caller it does
not have. WF1291 (this module) is a named caller whose claim about itself did
not resolve. Rendering those with one code would make a real, cheap, mechanical
check indistinguishable from the deep architectural one, and the deep one would
absorb the blame for every stale sha.

THREE OUTCOMES, NEVER TWO
-------------------------
``resolved``     the commit exists in the named repository and the remote agrees
``unresolved``   attestation is well-formed, but no repository was supplied to
                 check it against -- UNKNOWN, and it blocks nothing on its own
``absent``       the adapter attested nothing; there is no promise to break

``absent`` never fails. An adapter written before these fields existed -- or one
in a repository WorldForge does not own and must never edit -- has not lied by
staying silent, and grading silence as a failure would punish precisely the
adapters that are behaving correctly. What it must never do is *look the same*
as ``resolved``, which is the entire reason this returns a state rather than a
boolean.

House style matches tools/pipeline/*_contract*.py: stdlib only, and
``validate_X(...) -> List[Check]`` where
``Check = (check_name, ok, detail, failure_code)``.
"""

import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from consumers import adapter as ADP          # noqa: E402
from wfcore import tri                        # noqa: E402
from wfcore.failure import FailureCode as C   # noqa: E402

RT_ATTESTATION_RESULT = "wf.core.caller_attestation_result.v1"

_P = "caller_attestation."

# Terminal resolution states, closed.
# A red must name WHICH red it is. "We could not check" and "we checked and it
# did not hold" are different facts about the world, they are repaired by
# different actions -- supply a repository vs. correct the claim -- and a fold
# that renders them identically produces a verdict carrying no information.
RESOLVED = "resolved"        # checked against a real repository, and it held
REFUTED = "refuted"          # checked, and the claim did NOT hold
UNRESOLVED = "unresolved"    # well-formed, but nothing was able to check it
ABSENT = "absent"            # nothing was claimed
MALFORMED = "malformed"      # claimed in a shape no resolver could ever look up
RESOLUTION_STATES = (RESOLVED, REFUTED, UNRESOLVED, ABSENT, MALFORMED)

# The checks that constitute an actual resolution attempt. If one of these
# failed, the claim was TESTED and lost -- that is REFUTED, not UNRESOLVED.
_SUBSTANTIVE_CHECKS = frozenset((
    "declared_commit_exists",
    "declared_repository_matches_origin",
))

_GIT_TIMEOUT_S = 20


# --------------------------------------------------------------------------- #
# remote-url comparison
# --------------------------------------------------------------------------- #
def normalize_remote(url):
    """Reduce a git remote to ``host/path`` for comparison. None stays None.

    The same repository is legitimately spelled several ways -- ``https://``,
    ``ssh://``, scp-style ``git@host:owner/repo``, with or without a ``.git``
    suffix or a trailing slash. Comparing raw strings would report a mismatch
    between two spellings of one repository, which is a false accusation and
    worse than not checking: it would teach a reader to ignore the rail.

    Credentials in the URL are dropped rather than compared. A remote that
    carries a token differs per-machine and says nothing about identity.
    """
    if not isinstance(url, str):
        return None
    u = url.strip()
    if not u:
        return None
    for scheme in ("https://", "http://", "ssh://", "git://"):
        if u.lower().startswith(scheme):
            u = u[len(scheme):]
            break
    else:
        # scp-style: git@host:owner/repo
        if "@" in u and ":" in u and not u.startswith("/"):
            u = u.split("@", 1)[1].replace(":", "/", 1)
    if "@" in u:                       # strip user[:token]@ credentials
        u = u.split("@", 1)[1]
    u = u.rstrip("/")
    if u.lower().endswith(".git"):
        u = u[:-4]
    return u.lower() or None


# --------------------------------------------------------------------------- #
# git probes -- each degrades to (None, reason), never raises
# --------------------------------------------------------------------------- #
def _git(repo_path, *args):
    """(stdout, error). ``None`` stdout means NOT OBSERVED, never 'false'."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_path)] + [str(a) for a in args],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_S)
    except FileNotFoundError:
        return None, "git executable not found on PATH"
    except subprocess.TimeoutExpired:
        return None, "git timed out after {}s".format(_GIT_TIMEOUT_S)
    except OSError as exc:
        return None, "git could not run: {}".format(exc)
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout or "").strip() or \
            "git exited {}".format(proc.returncode)
    return proc.stdout.strip(), None


def probe_repository(repo_path, commit_sha, declared_repository):
    """Everything git can tell us, as data. Decides nothing."""
    out = {
        "repo_path": str(repo_path),
        "is_git_repo": None,
        "object_type": None,
        "resolved_sha": None,
        "reachable_from_head": None,
        "origin_url": None,
        "origin_normalized": None,
        "declared_normalized": normalize_remote(declared_repository),
        "errors": [],
    }

    top, err = _git(repo_path, "rev-parse", "--show-toplevel")
    out["is_git_repo"] = top is not None
    if err:
        out["errors"].append("rev-parse --show-toplevel: {}".format(err))
    if not out["is_git_repo"]:
        return out

    otype, err = _git(repo_path, "cat-file", "-t", commit_sha)
    out["object_type"] = otype
    if err:
        out["errors"].append("cat-file -t: {}".format(err))

    if otype == "commit":
        full, err = _git(repo_path, "rev-parse", "--verify",
                         "{}^{{commit}}".format(commit_sha))
        out["resolved_sha"] = full
        if err:
            out["errors"].append("rev-parse --verify: {}".format(err))

        # Reachability is recorded, never blocking. A caller may legitimately
        # attest a commit on a branch that HEAD has not merged; that is a real
        # commit in a real repository and refusing it would be wrong.
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_path), "merge-base",
                 "--is-ancestor", commit_sha, "HEAD"],
                capture_output=True, text=True, timeout=_GIT_TIMEOUT_S)
            out["reachable_from_head"] = (proc.returncode == 0)
        except (OSError, subprocess.SubprocessError) as exc:
            out["errors"].append("merge-base --is-ancestor: {}".format(exc))

    origin, err = _git(repo_path, "remote", "get-url", "origin")
    out["origin_url"] = origin
    out["origin_normalized"] = normalize_remote(origin)
    if err:
        out["errors"].append("remote get-url origin: {}".format(err))

    return out


# --------------------------------------------------------------------------- #
# the rails
# --------------------------------------------------------------------------- #
def validate_caller_attestation(adapter, repo_path=None, strict=False):
    """``List[Check]`` for one adapter's structured attestation.

    ``repo_path`` is the caller's own checkout. Omitting it is normal: not every
    invocation has the caller's repository available, and the honest answer then
    is UNRESOLVED rather than a guess in either direction.
    """
    code = C.CORE_CALLER_ATTESTATION_UNRESOLVED
    out = []
    state = ADP.attestation_of(adapter)
    got = ADP.attestation_fields(adapter)

    if state == ADP.ATTESTATION_ABSENT:
        # Recorded, never failed. The check exists so a reader can see that the
        # question was asked and answered "nothing was promised" -- an omitted
        # check and a passed check are indistinguishable in a report, and that
        # ambiguity is what lets an unchecked claim read as a verified one.
        out.append((_P + "attestation_supplied", True,
                    "adapter supplies no structured attestation "
                    "({}); nothing was promised, so nothing is unresolved. "
                    "This is not a pass -- it is an absence, and the run record "
                    "carries it as such".format(
                        list(ADP.PROVENANCE_ATTESTATION_FIELDS)), None))
        return out

    if state == ADP.ATTESTATION_MALFORMED:
        out.append((_P + "attestation_well_formed", False,
                    "structured attestation is present but not resolvable as "
                    "given: repository={!r} commit_sha={!r}. A half-written "
                    "attestation reads like evidence and resolves to "
                    "nothing".format(got["repository"], got["commit_sha"]),
                    code))
        return out

    out.append((_P + "attestation_well_formed", True,
                "repository and commit_sha are present and well-formed", None))

    if repo_path is None:
        out.append((_P + "repository_supplied_for_resolution", not strict,
                    "attestation is well-formed but no caller repository was "
                    "supplied to resolve it against, so it is UNRESOLVED. This "
                    "is not evidence that the claim is false, and it is not "
                    "evidence that it is true. Pass --caller-repo to decide it",
                    None if not strict else code))
        return out

    if not os.path.isdir(repo_path):
        out.append((_P + "caller_repo_exists", False,
                    "caller repository path does not exist: {}".format(repo_path),
                    code))
        return out
    out.append((_P + "caller_repo_exists", True,
                "caller repository present at {}".format(repo_path), None))

    probe = probe_repository(repo_path, got["commit_sha"], got["repository"])

    out.append((_P + "caller_repo_is_git", bool(probe["is_git_repo"]),
                "{} must be a git repository to resolve a commit against "
                "(errors: {})".format(repo_path, probe["errors"]),
                None if probe["is_git_repo"] else code))
    if not probe["is_git_repo"]:
        return out

    is_commit = probe["object_type"] == "commit"
    out.append((_P + "declared_commit_exists", is_commit,
                "declared commit_sha {!r} must name a commit in {} (git says "
                "object type {!r}; errors: {}). A sha that resolves to nothing "
                "is the one part of a provenance claim that can be checked, and "
                "it did not check out".format(
                    got["commit_sha"], repo_path, probe["object_type"],
                    probe["errors"]),
                None if is_commit else code))

    # Recorded, deliberately not blocking -- see probe_repository.
    out.append((_P + "declared_commit_reachable_from_head", True,
                "reachable_from_head={!r} (recorded, not graded: a commit on an "
                "unmerged branch is still a real commit)".format(
                    probe["reachable_from_head"]), None))

    dn, on = probe["declared_normalized"], probe["origin_normalized"]
    if on is None:
        out.append((_P + "declared_repository_matches_origin", False,
                    "the caller repository has no resolvable 'origin' remote, so "
                    "the declared repository {!r} cannot be corroborated "
                    "(errors: {})".format(got["repository"], probe["errors"]),
                    code))
    else:
        match = dn == on
        out.append((_P + "declared_repository_matches_origin", match,
                    "declared repository {!r} normalises to {!r}; the checkout's "
                    "origin {!r} normalises to {!r}. They must name the same "
                    "repository, or the commit was resolved against something "
                    "other than what the caller claimed".format(
                        got["repository"], dn, probe["origin_url"], on),
                    None if match else code))
    return out


def resolution_state(checks, adapter):
    """Fold a check list into exactly one of ``RESOLUTION_STATES``."""
    state = ADP.attestation_of(adapter)
    if state == ADP.ATTESTATION_ABSENT:
        return ABSENT
    if state == ADP.ATTESTATION_MALFORMED:
        return MALFORMED
    failed = {n for (n, ok, _d, _c) in checks if not ok}
    if _P + "attestation_well_formed" in failed:
        return MALFORMED
    # A substantive check that FAILED means the claim was put to the test and
    # did not survive. That is a stronger and more actionable statement than
    # "unresolved", and collapsing it into unresolved would let a demonstrably
    # false attestation wear the same label as an unchecked one.
    if any(_P + c in failed for c in _SUBSTANTIVE_CHECKS):
        return REFUTED
    if failed:
        return UNRESOLVED
    ran_resolution = any(n == _P + "declared_commit_exists"
                         for (n, _ok, _d, _c) in checks)
    return RESOLVED if ran_resolution else UNRESOLVED


def attestation_verdict(state):
    """Tri-verdict. UNRESOLVED and ABSENT are both UNKNOWN, never SATISFIED.

    Only a claim that was actually tested can be VIOLATED. Not being able to
    check something is never evidence against it -- that coercion of unknown to
    false is the mirror image of the fake-green this codebase keeps finding, and
    it is just as wrong.
    """
    if state == RESOLVED:
        return tri.SATISFIED
    if state in (MALFORMED, REFUTED):
        return tri.VIOLATED
    return tri.UNKNOWN


def build_attestation_record(adapter, repo_path=None, strict=False):
    """The persistable record. This is what the flow runner should carry."""
    checks = validate_caller_attestation(adapter, repo_path=repo_path,
                                         strict=strict)
    state = resolution_state(checks, adapter)
    got = ADP.attestation_fields(adapter)
    return {
        "schema_version": RT_ATTESTATION_RESULT,
        "report_type": RT_ATTESTATION_RESULT,
        "declared_repository": got["repository"],
        "declared_commit_sha": got["commit_sha"],
        "attestation_state": ADP.attestation_of(adapter),
        "resolution_state": state,
        "verdict": attestation_verdict(state),
        "resolved_against": str(repo_path) if repo_path else None,
        "checks": [{"check": n, "ok": ok, "detail": d, "failure_code": c}
                   for (n, ok, d, c) in checks],
        "failure_codes": sorted({c for (_n, ok, _d, c) in checks
                                 if not ok and c}),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Resolve a consumer adapter's structured provenance "
                    "attestation against a real repository.")
    ap.add_argument("--consumer", required=True,
                    help="consumer id; a dotted module path for a caller that "
                         "lives in its own repository")
    ap.add_argument("--consumer-path", action="append", default=[],
                    help="directory to prepend to sys.path; repeatable")
    ap.add_argument("--caller-repo",
                    help="the caller's own checkout, to resolve the commit "
                         "against. Omitting it yields UNRESOLVED, not a pass")
    ap.add_argument("--strict", action="store_true",
                    help="treat an unresolvable-because-unsupplied attestation "
                         "as a failure rather than an honest unknown")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="write the record here")
    args = ap.parse_args(argv)

    for d in args.consumer_path:
        if not os.path.isdir(d):
            print("consumer-path does not exist: {}".format(d))
            return 2
        if d not in sys.path:
            sys.path.insert(0, d)

    import importlib
    name = args.consumer if "." in args.consumer \
        else "consumers." + args.consumer
    try:
        mod = importlib.import_module(name)
    except ImportError as exc:
        print("could not import consumer {!r}: {}".format(name, exc))
        return 2

    record = build_attestation_record(mod.adapter(),
                                      repo_path=args.caller_repo,
                                      strict=args.strict)

    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, sort_keys=True)

    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print("caller attestation -- {}".format(args.consumer))
        print("  declared repository : {}".format(record["declared_repository"]))
        print("  declared commit     : {}".format(record["declared_commit_sha"]))
        print("  attestation         : {}".format(record["attestation_state"]))
        print("  resolution          : {}".format(record["resolution_state"]))
        print("  verdict             : {}".format(record["verdict"]))
        print("")
        for c in record["checks"]:
            print("  [{}] {}".format("OK  " if c["ok"] else "FAIL", c["check"]))
            if not c["ok"]:
                print("        {}".format(c["detail"][:160]))

    return 0 if not record["failure_codes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
