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


def build_meta(command, pack=None, strict=False, deep=False, torture=False,
               seeds=None, input_spec_hash=None, output_manifest_hash=None,
               status=None, failure_count=0, warning_count=0, skipped_count=0,
               record_count=0, extra=None):
    """Build the canonical v1.0x report-metadata block.

    Any field left None is still emitted (as None) so consumers can rely on the
    key always being present — an absent key is itself a report-integrity smell.
    """
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
        "status": status,
        "failure_count": int(failure_count),
        "warning_count": int(warning_count),
        "skipped_count": int(skipped_count),
        "record_count": int(record_count),
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


if __name__ == "__main__":
    # Self-check / demonstration.
    m = build_meta("selfcheck", pack="desert_mvp_world", strict=True, status="ok",
                   record_count=25)
    json.dump(m, sys.stdout, indent=2)
    sys.stdout.write("\n")
    assert not missing_meta_keys(m), missing_meta_keys(m)
    assert stable_meta(m).get("timestamp") is None
    sys.stdout.write("report_meta self-check OK\n")
