#!/usr/bin/env python3
"""core_boundary_proof.py -- prove a consumer run did not modify WorldForge Core.

THE CLAIM THIS EXISTS TO FALSIFY
--------------------------------
"A substantially different consumer profile works without modifying WorldForge
Core." That sentence is either the platform's central property or an empty
boast, and the difference is whether anything can catch it being false.

Prose cannot. A reviewer reading a diff will not notice that one of eighty Core
files gained a special case for the consumer being onboarded, and the test suite
will not notice either, because the special case is what makes the tests pass.
So the claim is discharged mechanically: capture Core's content before the
consumer run, capture it after, and require the two to be identical.

WHY A CONTENT DIGEST AND NOT ``git status``
-------------------------------------------
``git status`` answers "is the working tree dirty relative to the index", which
is a different question and gives the wrong answer twice:

* a Core edit that is staged, committed, or stashed mid-run shows as clean, and
  the proof would pass over exactly the edit it exists to catch
* an unrelated pre-existing dirty file in Core would fail a run that changed
  nothing

This script therefore hashes file CONTENT directly. It is indifferent to git
state, which also means it works in a checkout with unrelated in-flight work --
the normal condition of this repository.

WHAT COUNTS AS CORE
-------------------
Every ``*.py`` under ``tools/wfcore/``. Not the consumers, not the pipeline, not
the reports. If Core grows a non-Python asset that behaviour depends on, extend
``_core_files`` -- and note that forgetting to is a silent hole, which is why the
manifest records the file COUNT alongside the digest: a run that suddenly covers
fewer files is itself reported, rather than quietly proving less.

USAGE
-----
    cd tools
    python core_boundary_proof.py capture --out <baseline.json>
    ... run the consumer flow ...
    python core_boundary_proof.py verify --baseline <baseline.json>

``verify`` exits non-zero when Core changed, and names every file that differs
with its before/after digest so the offending edit is immediately locatable.
"""

import argparse
import hashlib
import json
import os
import sys
from typing import Any, Dict, List

_HERE = os.path.dirname(os.path.abspath(__file__))
CORE_ROOT = os.path.join(_HERE, "wfcore")

MANIFEST_SCHEMA = "wf.core.boundary_manifest.v1"


def _core_files(core_root: str = CORE_ROOT) -> List[str]:
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(core_root):
        dirnames[:] = [d for d in dirnames
                       if d != "__pycache__" and not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def _digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def capture(core_root: str = CORE_ROOT) -> Dict[str, Any]:
    """Digest every Core file. Newlines are normalised so a checkout-mode change
    (CRLF vs LF) is not mistaken for a semantic edit -- this repository is on
    Windows with git autocrlf in play, and a false positive here would train the
    operator to ignore the gate, which is worse than not having it."""
    files: Dict[str, str] = {}
    for path in _core_files(core_root):
        with open(path, "rb") as fh:
            raw = fh.read()
        normalised = raw.replace(b"\r\n", b"\n")
        rel = os.path.relpath(path, core_root).replace("\\", "/")
        files[rel] = _digest_bytes(normalised)

    combined = hashlib.sha256()
    for rel in sorted(files):
        combined.update(rel.encode("utf-8"))
        combined.update(b"\0")
        combined.update(files[rel].encode("utf-8"))
        combined.update(b"\n")

    return {
        "manifest_schema": MANIFEST_SCHEMA,
        "core_root": "tools/wfcore",
        "file_count": len(files),
        "files": files,
        "core_digest": "sha256:" + combined.hexdigest(),
    }


def compare(baseline: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """Diff two manifests into added / removed / modified.

    All three are violations. An ADDED Core file is just as much a Core
    modification as an edited one -- onboarding a consumer by dropping a new
    module into Core is the most natural way to break the boundary while every
    existing file's digest stays intact.
    """
    before = baseline.get("files") or {}
    after = current.get("files") or {}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    modified = sorted(p for p in (set(before) & set(after))
                      if before[p] != after[p])
    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged": baseline.get("core_digest") == current.get("core_digest"),
        "baseline_digest": baseline.get("core_digest"),
        "current_digest": current.get("core_digest"),
        "baseline_file_count": baseline.get("file_count"),
        "current_file_count": current.get("file_count"),
    }


def _cmd_capture(args: argparse.Namespace) -> int:
    manifest = capture()
    if manifest["file_count"] == 0:
        # A capture over zero files would make every later verify trivially
        # pass. Refuse to write a baseline that can only ever prove nothing.
        print("REFUSED: captured 0 Core files from {}. A baseline over nothing "
              "would make verify vacuous.".format(CORE_ROOT), file=sys.stderr)
        return 2
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    print("captured {} Core file(s) -> {}".format(manifest["file_count"], args.out))
    print("core_digest {}".format(manifest["core_digest"]))
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    with open(args.baseline, "r", encoding="utf-8") as fh:
        baseline = json.load(fh)
    current = capture()
    result = compare(baseline, current)

    print("WorldForge Core boundary proof")
    print("  baseline : {}  ({} files)".format(
        result["baseline_digest"], result["baseline_file_count"]))
    print("  current  : {}  ({} files)".format(
        result["current_digest"], result["current_file_count"]))

    if result["unchanged"]:
        print("")
        print("  PROOF HOLDS -- Core is byte-identical; the consumer ran "
              "without modifying it.")
        return 0

    print("")
    for label in ("modified", "added", "removed"):
        for rel in result[label]:
            print("  [{}] {}".format(label.upper(), rel))
    print("")
    print("  PROOF FAILED -- Core changed across the consumer run. Whatever the "
          "consumer needed belongs in the consumer's adapter, or it is a "
          "GENERIC capability that must be implemented generically and "
          "exercised through the consumer -- never a special case in Core.")
    return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("capture", help="write a Core baseline manifest")
    c.add_argument("--out", required=True)
    c.set_defaults(fn=_cmd_capture)

    v = sub.add_parser("verify", help="compare Core against a baseline manifest")
    v.add_argument("--baseline", required=True)
    v.set_defaults(fn=_cmd_verify)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
