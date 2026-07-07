#!/usr/bin/env python3
"""report_meta.py — WorldForge v1.0x shared report-metadata block.

The v1.0x brief requires every major command to emit a structured report whose
metadata is machine-comparable across runs and rich enough to prove a report is
not stale, empty, or fabricated. This helper produces that metadata block so the
shape is identical everywhere, and provides deterministic hashing of inputs and
outputs so report-integrity and determinism checks have stable anchors.

It is deliberately dependency-free (stdlib only) and additive: validators call
``build_meta(...)`` and attach the returned dict under the ``meta`` key of their
report (ValidationReport.set_meta does this), or embed it directly.

Required metadata fields (brief §"Reports Are Artifacts"):
    command, pack, strict, deep, torture, seeds, git_sha, timestamp,
    input_spec_hash, output_manifest_hash, validator_version, status,
    failure_count, warning_count, skipped_count, record_count

`timestamp` and `git_sha` are RUNTIME metadata: determinism checks must exclude
them (see stable_meta()).
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Bump when the shared v1.0x report shape changes in a breaking way.
VALIDATOR_VERSION = "v1.0x"

# WorldForge milestone version, emitted as a separate additive field so existing
# reports keyed on validator_version are undisturbed. v1.5 introduces the richer
# report identity (report_id/report_type/records_*) as backward-compatible extras.
WORLDFORGE_VERSION = "v1.5"

# Fields that are inherently per-run and MUST be excluded from determinism
# comparison. Everything else in the meta block is expected to be stable for a
# fixed (spec, seed, flags) tuple.
RUNTIME_META_FIELDS = ("timestamp", "git_sha", "duration_s", "host")


def git_sha(short=False):
    """Return the current git SHA, or 'unknown' if git is unavailable."""
    try:
        args = ["git", "rev-parse", "--short", "HEAD"] if short else ["git", "rev-parse", "HEAD"]
        out = subprocess.run(args, cwd=str(REPO_ROOT), capture_output=True, text=True)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def utc_now_iso():
    """Return a timezone-aware UTC ISO-8601 timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def hash_bytes(data):
    """Return a short sha256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()


def hash_text(text):
    """Return a short sha256 hex digest of a string (utf-8)."""
    return hash_bytes(text.encode("utf-8"))


def hash_file(path):
    """Return sha256 of a file's bytes, or None if it does not exist."""
    path = Path(path)
    if not path.is_file():
        return None
    return hash_bytes(path.read_bytes())


def hash_obj(obj):
    """Stable hash of a JSON-serialisable object (sorted keys, no whitespace)."""
    return hash_text(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def strict_from_env(default=False):
    """Mirror validation_report.strict_from_env so callers can import from one place."""
    val = os.environ.get("STRICT")
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def flag_from_env(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def derive_report_id(report_type=None, command=None, pack=None, suffix=None):
    """Deterministically derive a report_id from stable inputs.

    Deliberately excludes timestamp/git_sha so the id is stable across runs of a
    fixed (report_type, command, pack, suffix) tuple — determinism gates compare
    stable_meta() which retains report_id. For per-record reports (one file per
    encounter/asset) pass a distinct ``suffix`` (e.g. the record id) so ids do
    not collide.
    """
    label = report_type or command or "report"
    basis = "|".join([str(label), str(pack or ""), str(suffix or "")])
    return "{}:{}".format(label, hash_text(basis)[:12])


def build_meta(command, pack=None, strict=False, deep=False, torture=False,
               seeds=None, input_spec_hash=None, output_manifest_hash=None,
               status=None, failure_count=0, warning_count=0, skipped_count=0,
               record_count=0, report_type=None, report_id=None,
               records_total=None, records_passed=None, records_failed=None,
               records_skipped=None, report_id_suffix=None, extra=None):
    """Build the canonical WorldForge report-metadata block.

    Any field left None is still emitted (as None) so consumers can rely on the
    key always being present — an absent key is itself a report-integrity smell.

    v1.5 additive fields (backward compatible — pre-v1.5 reports simply lack them
    until regenerated): worldforge_version, report_type, report_id, and the
    records_{total,passed,failed,skipped} tally. The records_* fields mirror the
    legacy *_count fields when not passed explicitly, so callers that only set the
    old counts still get a coherent tally.
    """
    rec_total = int(records_total) if records_total is not None else int(record_count)
    rec_failed = int(records_failed) if records_failed is not None else int(failure_count)
    rec_skipped = int(records_skipped) if records_skipped is not None else int(skipped_count)
    if records_passed is not None:
        rec_passed = int(records_passed)
    else:
        rec_passed = max(0, rec_total - rec_failed - rec_skipped)
    meta = {
        "command": command,
        "pack": pack,
        "strict": bool(strict),
        "deep": bool(deep),
        "torture": bool(torture),
        "seeds": seeds,
        "git_sha": git_sha(),
        "timestamp": utc_now_iso(),
        "input_spec_hash": input_spec_hash,
        "output_manifest_hash": output_manifest_hash,
        "validator_version": VALIDATOR_VERSION,
        "worldforge_version": WORLDFORGE_VERSION,
        "report_type": report_type,
        "report_id": report_id if report_id is not None else derive_report_id(
            report_type, command, pack, report_id_suffix),
        "status": status,
        "failure_count": int(failure_count),
        "warning_count": int(warning_count),
        "skipped_count": int(skipped_count),
        "record_count": int(record_count),
        "records_total": rec_total,
        "records_passed": rec_passed,
        "records_failed": rec_failed,
        "records_skipped": rec_skipped,
    }
    if extra:
        meta.update(extra)
    return meta


def stable_meta(meta):
    """Return a copy of a meta block with runtime-only fields stripped.

    Used by determinism checks: two runs of the same (spec, seed, flags) tuple
    must produce identical stable_meta() output.
    """
    return {k: v for k, v in (meta or {}).items() if k not in RUNTIME_META_FIELDS}


# The canonical set of metadata keys every v1.0x report's meta block must carry.
# report-integrity uses this to flag reports missing required metadata.
REQUIRED_META_KEYS = (
    "command", "pack", "strict", "git_sha", "timestamp",
    "validator_version", "status", "failure_count", "warning_count",
    "skipped_count", "record_count",
)


def missing_meta_keys(meta):
    """Return the required meta keys absent from a report's meta block."""
    if not isinstance(meta, dict):
        return list(REQUIRED_META_KEYS)
    return [k for k in REQUIRED_META_KEYS if k not in meta]


# The richer identity standard v1.5 report types must satisfy. Kept separate from
# REQUIRED_META_KEYS so the global report-integrity gate over pre-v1.5 reports is
# undisturbed; v1.5 validators and the v1.5 report-integrity pass enforce these.
V1_5_REQUIRED_META_KEYS = REQUIRED_META_KEYS + (
    "worldforge_version", "report_type", "report_id",
    "records_total", "records_passed", "records_failed", "records_skipped",
)


def missing_v1_5_meta_keys(meta):
    """Return the v1.5-required meta keys absent from a report's meta block.

    A v1.5 report additionally must carry a non-empty report_type and report_id
    (present-but-None is still a smell for the new report standard).
    """
    if not isinstance(meta, dict):
        return list(V1_5_REQUIRED_META_KEYS)
    missing = [k for k in V1_5_REQUIRED_META_KEYS if k not in meta]
    for k in ("report_type", "report_id"):
        if k not in missing and not meta.get(k):
            missing.append(k)
    return missing


if __name__ == "__main__":
    # Self-check / demonstration.
    m = build_meta("selfcheck", pack="desert_mvp_world", strict=True, status="ok",
                   record_count=25, report_type="wf.asset.gap_report.v1",
                   records_passed=24, records_failed=1)
    json.dump(m, sys.stdout, indent=2)
    sys.stdout.write("\n")
    assert not missing_meta_keys(m), missing_meta_keys(m)
    assert not missing_v1_5_meta_keys(m), missing_v1_5_meta_keys(m)
    assert m["records_total"] == 25 and m["records_passed"] == 24 and m["records_failed"] == 1
    # report_id must be deterministic (no timestamp leakage) and survive stable_meta.
    assert stable_meta(m).get("timestamp") is None
    assert derive_report_id("wf.asset.gap_report.v1", pack="desert_mvp_world") == \
        derive_report_id("wf.asset.gap_report.v1", pack="desert_mvp_world")
    sys.stdout.write("report_meta self-check OK\n")
