#!/usr/bin/env python3
"""_wf_stamp -- bind an editor-produced report to a revision and a moment.

WHY
---
``tools/pipeline/validate_runtime_state.py`` learned this the hard way: the only
in-editor bridge report on disk was two months old and carried nothing saying
which build produced it, so there was no way to tell whether the measurement
still described the code. The fix there was to require ``timestamp`` and
``git_sha`` on the report, and the same gap exists across the material lane --
``import_result.json``, ``material_result.json`` and ``asset_validation_result.json``
all record what the editor did and none of them says WHEN, or against WHAT.

An unstamped report cannot serve as runtime evidence. Not because it is
untrustworthy, but because nothing binds it to a revision: it is a measurement
with no subject. ``evidence_ladder`` refuses to promote a capability on one, and
it is right to.

File mtime is NOT a substitute. It moves when a file is copied and says nothing
about when the editor ran -- that argument is already written down in
``validate_runtime_state``.

This module is deliberately stdlib-only and imports no ``unreal``, so it works
on both sides of the editor boundary and cannot fail an import inside a headless
run.
"""

import datetime
import os
import subprocess


def git_sha(repo_root):
    """HEAD sha, or 'unknown'. Never raises -- a stamp that crashes a headless
    editor run would cost the whole run to record a provenance field."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_root),
                             capture_output=True, text=True, check=True)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 - environment, not logic
        return "unknown"


def engine_version():
    """Engine version as the editor itself reports it, when we are inside one."""
    try:
        import unreal  # noqa: PLC0415 - only available in-editor, by design
        return str(unreal.SystemLibrary.get_engine_version())
    except Exception:  # noqa: BLE001
        return None


def stamp(report, repo_root, produced_by):
    """Add freshness + provenance fields to an editor report, in place.

    Returns the same dict so callers can write it directly. Existing keys are
    never overwritten: a caller that already recorded a more precise value keeps
    it, and this only fills what is missing.
    """
    if not isinstance(report, dict):
        return report
    report.setdefault(
        "timestamp",
        datetime.datetime.now(datetime.timezone.utc).isoformat())
    report.setdefault("git_sha", git_sha(repo_root))
    report.setdefault("produced_by", produced_by)
    ev = engine_version()
    if ev:
        report.setdefault("engine_version", ev)
    report.setdefault("ran_in_editor", ev is not None)
    return report
