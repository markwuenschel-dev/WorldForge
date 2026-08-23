#!/usr/bin/env python3
"""wfcore.hygiene -- mechanically enforce that Core knows no consumer's vocabulary.

WHAT THIS GATE DEFENDS
----------------------
The platform claim is: a substantially different importing game drives the same
flow with an EMPTY ``git diff -- tools/wfcore/``. That claim is only meaningful
if Core is incapable of knowing any particular game. The moment a consumer's
proper noun, map path, faction, biome, or asset name appears inside Core, the
second-consumer proof degrades into "the two consumers happened to be similar",
and nobody notices because everything still passes.

So game-agnosticism is not a review convention here. It is a gate.

WHY THE FORBIDDEN SET IS DERIVED, NOT LISTED
--------------------------------------------
The existing scene-survey hygiene gate hardcodes its deny-list
(``tools/pipeline/scene_survey_hygiene.py``: ``FORBIDDEN_VOCAB = ("VeilHeart",
"Gloamstead")``). That was right for one lane with one known caller, but as a
platform rule it FAILS OPEN in the worst possible way: onboard a third consumer,
let its name leak into Core, and the gate stays green because nobody remembered
to extend a tuple in a different directory.

This gate instead DERIVES the forbidden set from the consumers that actually
exist on disk, under ``tools/consumers/<consumer_id>/``. Registering a consumer
automatically bans its vocabulary from Core. The gate therefore gets stricter as
the platform grows, which is the only direction a safety gate may drift.

The hardcoded names are kept as a FLOOR, not as the definition -- they cover
consumers that have been discussed or partially integrated but do not yet have a
directory, and they must never be the only source. Floor plus derivation, never
derivation alone: a consumer directory that is deleted or renamed must not
silently unban its vocabulary from Core.

WHY THIS IS A DENY-LIST AND NOT AN ALLOW-LIST
---------------------------------------------
An allow-list of "words Core may contain" fails open for every word added later
and would need editing on every legitimate Core change -- so it would be widened
reflexively until it meant nothing. A deny-list of consumer-owned vocabulary
fails CLOSED: the failure mode is a false positive on an innocent word, which is
loud, immediate, and fixed by renaming an identifier. Prefer the gate that
breaks the build over the gate that quietly stops checking.

SCOPE
-----
Every ``*.py`` under ``tools/wfcore/``, this file exempted (it must be able to
name the words it forbids -- the same self-exemption the scene-survey gate uses,
and for the same reason). Comments and docstrings are scanned too: a comment
naming a consumer's map is documentation of a coupling that should not exist.
"""

import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from .failure import FailureCode as C

RT_CORE_HYGIENE_REPORT = "wf.core.hygiene_report.v1"

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.normpath(os.path.join(_HERE, os.pardir))
CORE_ROOT = _HERE
CONSUMERS_ROOT = os.path.join(_TOOLS, "consumers")

# Files inside Core that are allowed to contain the forbidden words. ONLY this
# module: it defines them. Keep this list at length one -- every entry added is
# a hole, and a hole in a hygiene gate is invisible by construction.
SELF_EXEMPT = ("hygiene.py",)

# The floor. Consumers that exist, or have existed, in this repository's orbit.
# NOT the definition of the forbidden set -- see the module docstring. Removing a
# name here does not make it legal in Core; it only stops it being caught when no
# consumer directory declares it.
FORBIDDEN_VOCAB_FLOOR = (
    "Gloamstead",
    "VeilHeart",
)

Check = Tuple[str, bool, str, Optional[str]]


def discover_consumer_vocabulary(consumers_root: str = CONSUMERS_ROOT) -> List[str]:
    """Return consumer identifiers found on disk, to be banned from Core.

    A missing consumers directory is NOT an error -- Core is expected to exist
    and be verifiable before any consumer is integrated. It simply contributes
    nothing beyond the floor.
    """
    if not os.path.isdir(consumers_root):
        return []
    out: List[str] = []
    for name in sorted(os.listdir(consumers_root)):
        if name.startswith(("_", ".")):
            continue
        if os.path.isdir(os.path.join(consumers_root, name)):
            out.append(name)
    return out


def forbidden_vocabulary(consumers_root: str = CONSUMERS_ROOT) -> List[str]:
    """The effective deny-list: the floor UNION whatever consumers exist."""
    vocab = {v.lower() for v in FORBIDDEN_VOCAB_FLOOR}
    for consumer_id in discover_consumer_vocabulary(consumers_root):
        # A consumer directory may be "gloamstead5_8"; ban the alphabetic stem
        # too so a version suffix cannot smuggle the name past a literal match.
        vocab.add(consumer_id.lower())
        stem = re.split(r"[^A-Za-z]", consumer_id, 1)[0]
        if len(stem) >= 4:
            vocab.add(stem.lower())
    return sorted(vocab)


def _core_python_files(core_root: str = CORE_ROOT) -> List[str]:
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(core_root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__",) and not d.startswith(".")]
        for fn in sorted(filenames):
            if fn.endswith(".py") and fn not in SELF_EXEMPT:
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def scan_core(core_root: str = CORE_ROOT,
              consumers_root: str = CONSUMERS_ROOT) -> Dict[str, Any]:
    """Scan Core for consumer vocabulary. Returns a report dict.

    Reports the offending file, line number, and the matched word so the fix is
    obvious. Line-level reporting matters: "Core mentions a consumer somewhere"
    is not actionable, and an unactionable gate gets suppressed.
    """
    vocab = forbidden_vocabulary(consumers_root)
    files = _core_python_files(core_root)
    violations: List[Dict[str, Any]] = []

    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError as exc:  # unreadable file is itself a finding
            violations.append({
                "file": os.path.relpath(path, _TOOLS).replace("\\", "/"),
                "line": 0,
                "matched": None,
                "detail": "could not read file: {}".format(exc),
            })
            continue
        for lineno, line in enumerate(lines, start=1):
            low = line.lower()
            for word in vocab:
                if word in low:
                    violations.append({
                        "file": os.path.relpath(path, _TOOLS).replace("\\", "/"),
                        "line": lineno,
                        "matched": word,
                        "detail": line.strip()[:160],
                    })

    return {
        "report_type": RT_CORE_HYGIENE_REPORT,
        "core_root": os.path.relpath(core_root, _TOOLS).replace("\\", "/"),
        "files_scanned": len(files),
        "forbidden_vocabulary": vocab,
        "consumers_discovered": discover_consumer_vocabulary(consumers_root),
        "violations": violations,
        "clean": not violations,
    }


def validate_core_hygiene(report: Dict[str, Any]) -> List[Check]:
    """Turn a scan report into house-shape checks."""
    checks: List[Check] = []

    scanned = report.get("files_scanned", 0)
    # A gate that scanned nothing must never report clean. This is the single
    # most common way a hygiene check dies silently: a path changes, zero files
    # match, and "no violations found" reads exactly like success.
    ok = isinstance(scanned, int) and scanned > 0
    checks.append(("hygiene_scanned_files", ok,
                   "scanned {} Core file(s); a scan that examined nothing "
                   "cannot report clean".format(scanned),
                   None if ok else C.CORE_CONSUMER_VOCABULARY_LEAK))

    violations = report.get("violations") or []
    ok = not violations
    if ok:
        detail = "no consumer vocabulary in Core across {} file(s)".format(scanned)
    else:
        head = "; ".join("{}:{} matched {!r}".format(
            v["file"], v["line"], v["matched"]) for v in violations[:5])
        detail = "{} violation(s): {}{}".format(
            len(violations), head, " ..." if len(violations) > 5 else "")
    checks.append(("hygiene_no_consumer_vocabulary", ok, detail,
                   None if ok else C.CORE_CONSUMER_VOCABULARY_LEAK))

    return checks


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    report = scan_core()
    checks = validate_core_hygiene(report)

    print("WorldForge Core hygiene -- consumer vocabulary must not appear in Core")
    print("  core_root            : {}".format(report["core_root"]))
    print("  files scanned        : {}".format(report["files_scanned"]))
    print("  consumers discovered : {}".format(
        report["consumers_discovered"] or "(none yet)"))
    print("  forbidden vocabulary : {}".format(report["forbidden_vocabulary"]))
    print("")
    failed = 0
    for (name, ok, detail, code) in checks:
        print("  [{}] {} -- {}{}".format(
            "PASS" if ok else "FAIL", name, detail,
            "" if ok else "  ({})".format(code)))
        if not ok:
            failed += 1

    if "--json" in argv:
        import json
        print(json.dumps(report, indent=2, sort_keys=True))

    print("")
    print("  GATE {}".format("GREEN" if failed == 0 else "RED"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
