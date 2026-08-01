#!/usr/bin/env python3
r"""scene_survey_operation.py — operation identity, isolation and durability for v2.6.

WHAT THIS IS FOR
================
The v2.6 scene-survey rail currently has no way to say "this evidence was produced
FOR THIS operation". Four verified holes, each with a failure code already minted
for it and nothing raising that code:

1. THE GATE READS ONE FILENAME, FOREVER.
   ``tools/pipeline/validate_scene_survey_runtime.py:49-50`` binds
   ``RUNTIME_REPORT = REPORT_DIR / "scene_survey_report.json"`` — one hard-coded
   path. ``main()`` (:179-216) takes ``--pack`` (:181) and ``--strict`` (:182) and
   nothing else: there is no ``--report`` and no ``--operation-id``. The gate reads
   that single file at :190/:198 and validates it at :202-203. So ANY well-formed
   report satisfies ANY operation, indefinitely.
   -> WF1127 SCENE_SURVEY_OPERATION_MANIFEST_MISSING / WF1128 ..._ID_MISMATCH
      (``failure_codes.py:1233-1234``) exist for exactly this and are raised by
      nothing: the only references repo-wide are the constants themselves and two
      declarative spec files (``specs/scene_survey/scene_survey_contract_manifest.json:97-100``,
      ``specs/scene_survey/scene_survey_report.schema.json:244-248``).

2. EVERY RUN OVERWRITES THAT PATH, AND A REFUSED RUN LEAVES THE PRIOR ONE STANDING.
   ``run_scene_survey_probe.py:657`` sets ``out = REPORT_DIR / "scene_survey_report.json"``
   and :729 writes it. The stale-artifact unlink loop is at :660-662 — AFTER all
   eight early ``return 2`` guards (:600, :604, :607, :612, :617, :631, :639, :648).
   A run refused at any of those eight points never reaches the unlink, so the
   PREVIOUS operation's report stays on disk and the gate in (1) reads it and
   greens.

3. ``output_location`` REACHES ``mkdir(parents=True)`` WITH NO CONTAINMENT CHECK.
   ``run_scene_survey_probe.py:658`` — ``response_dir = REPO_ROOT / req.output_location``
   — and ``_emit_response`` does ``out_dir.mkdir(parents=True, exist_ok=True)``
   (:471) then ``dest.write_text(...)`` (:473). ``req.output_location`` is a plain
   caller-supplied ``str`` (``tools/bridge/schema.py:93``). On Windows
   ``Path(r"D:\repo") / "C:/evil"`` yields ``C:/evil``: an absolute or
   drive-qualified value REPLACES the root and the tool creates directories and
   writes files outside the repository.
   -> WF1130 SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE (``failure_codes.py:1236``),
      likewise raised by nothing.

4. NEITHER REPORT WRITE IS ATOMIC, AND NOTHING LOCKS.
   ``run_scene_survey_probe.py:729`` and :473 both use ``Path.write_text`` — a
   truncate-in-place. Combined with the unlink at :660-662, the window in which
   the report is ABSENT or half-written spans every editor boot: ``--repeat``
   defaults to 2 (:584) and ``--timeout`` to 900 (:586), so ~2 x 900 s of nothing
   on disk. Meanwhile 5 of 6 artifacts are fixed "latest" paths and there is ZERO
   locking anywhere in the tree — ``grep -rn "msvcrt|fcntl|flock|LockFile|O_EXCL"
   --include=*.py tools/`` returns no hits (verified at d5e3ca17).
   -> WF1129 SCENE_SURVEY_CONCURRENT_OPERATION (``failure_codes.py:1235``), also
      raised by nothing.

This module is the missing mechanism, as a self-contained library. It is NOT wired
in: no existing file is modified by this lane. A later integration step imports it.

WHAT IT PROVIDES
================
* ``confine_path``            — refuse any caller path that escapes the repo root.
* ``atomic_write_bytes``      — same-directory temp + fsync + ``os.replace``.
* ``hash_request``            — stable hash over ``BridgeRequest`` with a DOCUMENTED
                                included/excluded field split.
* ``acquire_operation_lock``  — single-writer guard with non-deadlocking stale
                                detection.
* ``build_operation_manifest``/``publish_operation_manifest``/``load_operation_manifest``
* ``verify_operation_evidence`` — is this evidence FOR this request, or a prior
                                artifact being re-presented?

CONTRACT: every public function FAILS CLOSED and RETURNS its failure as an
``OpResult``. Nothing raises past this module's boundary. Pure stdlib; no Unreal,
no network; importable and self-testable with no editor.

Self-test (no editor, no network, writes only to a temp dir):
    PYTHONUTF8=1 python tools/pipeline/scene_survey_operation.py
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import os
import socket
import sys
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# failure codes
# --------------------------------------------------------------------------- #
# Import the canonical codes when the tree is importable; otherwise fall back to
# the same literals so this module stays standalone-importable. CODES_SOURCE lets
# the self-test report which path it took, and the self-test asserts the literals
# agree whenever the real module IS importable — so a rename upstream is caught
# here rather than silently forked.
_REPO_ROOT_GUESS = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT_GUESS / "tools" / "pipeline") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_GUESS / "tools" / "pipeline"))

try:  # pragma: no cover - exercised both ways by the self-test's report line
    from failure_codes import FailureCode as C  # type: ignore

    CODES_SOURCE = "failure_codes"
except Exception:  # noqa: BLE001

    class C:  # type: ignore[no-redef]
        """Standalone fallback mirroring ``failure_codes.FailureCode``."""

        SCENE_SURVEY_REPORT_INVALID = "WF1062_SCENE_SURVEY_REPORT_INVALID"
        SCENE_SURVEY_CLEANUP_UNVERIFIED = "WF1092_SCENE_SURVEY_CLEANUP_UNVERIFIED"
        SCENE_SURVEY_EVIDENCE_MISSING = "WF1097_SCENE_SURVEY_EVIDENCE_MISSING"
        SCENE_SURVEY_REPORT_INTEGRITY_FAILED = "WF1100_SCENE_SURVEY_REPORT_INTEGRITY_FAILED"
        SCENE_SURVEY_EVIDENCE_RAW_MISSING = "WF1113_SCENE_SURVEY_EVIDENCE_RAW_MISSING"
        SCENE_SURVEY_OPERATION_MANIFEST_MISSING = "WF1127_SCENE_SURVEY_OPERATION_MANIFEST_MISSING"
        SCENE_SURVEY_OPERATION_ID_MISMATCH = "WF1128_SCENE_SURVEY_OPERATION_ID_MISMATCH"
        SCENE_SURVEY_CONCURRENT_OPERATION = "WF1129_SCENE_SURVEY_CONCURRENT_OPERATION"
        SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE = "WF1130_SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE"

    CODES_SOURCE = "fallback_literals"


# --------------------------------------------------------------------------- #
# result type — every public function returns one of these, and never raises
# --------------------------------------------------------------------------- #
@dataclasses.dataclass(frozen=True)
class OpResult:
    """The single return type of this module. ``ok`` False always carries a code.

    ``reason`` is a short machine-stable slug (e.g. ``"unc_or_device_path"``) so
    callers and tests can assert on WHICH rejection fired, not just that one did.
    """

    ok: bool
    code: Optional[str] = None
    detail: str = ""
    value: Any = None
    reason: str = ""

    def __bool__(self) -> bool:  # noqa: D105
        return self.ok

    def as_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "code": self.code, "reason": self.reason, "detail": self.detail}


def _ok(value: Any = None, detail: str = "") -> OpResult:
    return OpResult(True, None, detail, value, "")


def _fail(code: str, reason: str, detail: str) -> OpResult:
    return OpResult(False, code, detail, None, reason)


# --------------------------------------------------------------------------- #
# canonical serialization
# --------------------------------------------------------------------------- #
# TWO forms, deliberately distinct:
#
#   * CANONICAL (compact, sort_keys, no spaces) — the DIGEST preimage. Digests
#     bind CONTENT, so reformatting a manifest (indent, key order) does not
#     invalidate it; mutating a value does.
#   * PRETTY (sort_keys, indent=2, trailing "\n") — what lands on disk, encoded to
#     UTF-8 BYTES and written in binary. Writing bytes is stronger than
#     newline="\n": no text-layer translation can occur at all. This matters
#     because .gitattributes pins `*.json text eol=lf` (`.gitattributes:13`), so
#     the default Windows CRLF translation would manufacture whole-file diffs that
#     look like drift and are not.
CANONICAL_SEPARATORS = (",", ":")
MAX_JSON_DEPTH = 64


def _canonicalize(obj: Any, _depth: int = 0) -> Any:
    """Validate + normalize a JSON-able tree. Raises ValueError (caught by callers).

    Refuses what json.dumps would silently accept and make non-deterministic or
    non-standard: non-str dict keys (unorderable / coerced), and non-finite floats
    (NaN/Infinity are not JSON and do not survive a round trip through other
    parsers).
    """
    if _depth > MAX_JSON_DEPTH:
        raise ValueError("json nesting deeper than {}".format(MAX_JSON_DEPTH))
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            raise ValueError("non-finite float {!r} is not representable JSON".format(obj))
        return obj
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(v, _depth + 1) for v in obj]
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if not isinstance(k, str):
                raise ValueError("dict key {!r} is not a string".format(k))
            out[k] = _canonicalize(v, _depth + 1)
        return out
    raise ValueError("unserializable type {}".format(type(obj).__name__))


def canonical_json(obj: Any) -> OpResult:
    """Compact, key-sorted JSON text — the digest preimage. Never raises."""
    try:
        return _ok(json.dumps(_canonicalize(obj), sort_keys=True, ensure_ascii=False,
                              separators=CANONICAL_SEPARATORS))
    except (ValueError, TypeError, RecursionError) as exc:
        return _fail(C.SCENE_SURVEY_REPORT_INVALID, "not_canonicalizable",
                     "object is not canonically serializable: {}".format(exc))


def pretty_json_bytes(obj: Any) -> OpResult:
    """UTF-8 bytes for on-disk JSON: sort_keys, indent=2, LF only, trailing LF."""
    try:
        text = json.dumps(_canonicalize(obj), sort_keys=True, ensure_ascii=False, indent=2)
    except (ValueError, TypeError, RecursionError) as exc:
        return _fail(C.SCENE_SURVEY_REPORT_INVALID, "not_serializable",
                     "object is not serializable: {}".format(exc))
    # json.dumps emits only "\n"; assert it so a future indent/separator change
    # cannot smuggle a CR in.
    if "\r" in text:
        return _fail(C.SCENE_SURVEY_REPORT_INVALID, "carriage_return_in_payload",
                     "serialized JSON contains CR; the on-disk form must be LF-only")
    return _ok((text + "\n").encode("utf-8"))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_bytes(data: bytes) -> str:
    return "sha256:" + sha256_hex(data)


def digest_file(path: Path) -> OpResult:
    """Digest a file's bytes. Missing/unreadable is a RETURNED failure (WF1113)."""
    try:
        h = hashlib.sha256()
        size = 0
        with open(str(path), "rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                h.update(chunk)
    except FileNotFoundError:
        return _fail(C.SCENE_SURVEY_EVIDENCE_RAW_MISSING, "evidence_absent",
                     "evidence file does not exist: {}".format(path))
    except OSError as exc:
        return _fail(C.SCENE_SURVEY_EVIDENCE_RAW_MISSING, "evidence_unreadable",
                     "evidence file unreadable: {}: {}".format(path, exc))
    return _ok({"sha256": "sha256:" + h.hexdigest(), "bytes": size})


# --------------------------------------------------------------------------- #
# path confinement  (WF1130)
# --------------------------------------------------------------------------- #
# Rejection is SYNTACTIC FIRST, then resolution, then containment, then a symlink
# scan. Syntax first because `Path(repo) / candidate` already lost the game by the
# time you can resolve it: on Windows an absolute or drive-qualified right-hand
# operand REPLACES the left, so the escape is complete before any check runs.
_WIN_RESERVED_STEMS = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM{}".format(i) for i in range(1, 10)]
    + ["LPT{}".format(i) for i in range(1, 10)]
)
MAX_PATH_CHARS = 1024


def confine_path(repo_root: Any, candidate: Any) -> OpResult:
    """Resolve a caller-supplied relative path, or REFUSE it with WF1130.

    Returns ``value = {"absolute": Path, "relative_posix": str}`` on success.

    Accepts ONLY a repo-relative path using ``/`` or ``\\`` separators. Everything
    else is refused, including cases that look harmless on POSIX and are not on
    Windows (``C:foo`` is drive-RELATIVE — it resolves against the current
    directory *of drive C*, which is not this repository).

    Note one deliberate over-rejection: any ``:`` anywhere is refused. That covers
    drive letters (``C:\\``, ``C:/``, ``C:foo``) and NTFS alternate data streams
    (``report.json:hidden``) in one rule. Colons are illegal in Windows filenames
    regardless, so nothing legitimate is lost.
    """
    try:
        root = Path(str(repo_root)).resolve()
    except (OSError, ValueError) as exc:
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "repo_root_unresolvable",
                     "repo root is not resolvable: {!r}: {}".format(repo_root, exc))

    if not isinstance(candidate, str):
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "not_a_string",
                     "output_location must be a string, got {}".format(type(candidate).__name__))
    raw = candidate
    if not raw.strip():
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "empty",
                     "output_location is empty or whitespace-only")
    if len(raw) > MAX_PATH_CHARS:
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "too_long",
                     "output_location exceeds {} characters".format(MAX_PATH_CHARS))
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "control_character",
                     "output_location contains a control character (NUL/CR/LF/...)")
    # \\?\C:\... , \\.\pipe\... , \\server\share , //server/share
    if raw.startswith(("\\\\", "//")):
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "unc_or_device_path",
                     "output_location is a UNC / extended-length / device path: {!r}".format(raw))
    if ":" in raw:
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "colon_drive_or_ads",
                     "output_location contains ':' (drive-qualified, drive-relative, or "
                     "NTFS alternate data stream): {!r}".format(raw))
    if raw[0] in "/\\":
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "root_relative",
                     "output_location is root-anchored, not repo-relative: {!r}".format(raw))
    if raw.startswith("~"):
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "home_expansion",
                     "output_location begins with '~' (home expansion): {!r}".format(raw))

    parts = [p for p in raw.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts:
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "no_components",
                     "output_location names no path component: {!r}".format(raw))
    for part in parts:
        if part == "..":
            return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "parent_traversal",
                         "output_location traverses upward ('..'): {!r}".format(raw))
        if part != part.strip() or part.endswith((" ", ".")):
            # Windows silently strips trailing spaces/dots, so "foo. " and "foo"
            # are the same file — a normalization difference an auditor cannot see.
            return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "trailing_space_or_dot",
                         "component {!r} has leading/trailing whitespace or a trailing "
                         "dot: {!r}".format(part, raw))
        if part.split(".")[0].upper() in _WIN_RESERVED_STEMS:
            return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "reserved_device_name",
                         "component {!r} is a reserved Windows device name: {!r}".format(part, raw))

    # Symlink / junction escape, checked BEFORE the whole-path containment test so
    # the failure NAMES the offending component. (Ordered this way deliberately:
    # Path.resolve() below follows links, so the containment check would catch the
    # same escape but could only say "resolved somewhere else", which is not
    # actionable. Containment remains the backstop for everything this misses.)
    probe = root
    for part in parts:
        probe = probe / part
        try:
            is_link = probe.is_symlink()
        except OSError:
            break
        if is_link:
            try:
                target = probe.resolve()
                tc = os.path.commonpath([str(root), str(target)])
            except (OSError, ValueError, RuntimeError):
                target, tc = probe, ""
            if os.path.normcase(tc) != os.path.normcase(str(root)):
                return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "symlink_escape",
                             "component {!r} is a link pointing outside the repo root "
                             "({} -> {})".format(part, probe, target))
        try:
            if not probe.exists():
                break
        except OSError:
            break

    try:
        resolved = (root / PurePosixPath(*parts)).resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "unresolvable",
                     "output_location is not resolvable: {!r}: {}".format(raw, exc))

    # Containment via commonpath, NOT str.startswith: "D:\\repo-evil" passes a
    # startswith("D:\\repo") test and is a different tree.
    try:
        common = os.path.commonpath([str(root), str(resolved)])
    except ValueError:
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "different_drive",
                     "output_location resolves onto a different drive than the repo root: "
                     "{} vs {}".format(resolved, root))
    if os.path.normcase(common) != os.path.normcase(str(root)):
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "escapes_repo_root",
                     "output_location resolves outside the repo root: {} not under {}".format(
                         resolved, root))

    rel = PurePosixPath(*parts).as_posix()
    return _ok({"absolute": resolved, "relative_posix": rel},
               "confined to {}".format(rel))


def relative_posix(repo_root: Any, path: Any) -> OpResult:
    """Repo-relative POSIX form of an in-repo absolute path (no machine paths).

    Mirrors the house rule stated at ``tools/bridge/schema.py:165`` — "All paths
    are project-relative — no machine paths."
    """
    try:
        root = Path(str(repo_root)).resolve()
        p = Path(str(path)).resolve()
        return _ok(p.relative_to(root).as_posix())
    except (ValueError, OSError) as exc:
        return _fail(C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, "not_under_root",
                     "{} is not under the repo root {}: {}".format(path, repo_root, exc))


# --------------------------------------------------------------------------- #
# atomic publish
# --------------------------------------------------------------------------- #
# SEQUENCE (and why each step is there):
#   1. confine the destination (if a repo root was supplied)          -> WF1130
#   2. mkdir the destination's parent
#   3. create a temp file in THAT SAME DIRECTORY, O_CREAT|O_EXCL      -> same volume,
#      because os.replace across volumes is not atomic and on Windows raises
#      outright; O_EXCL so two concurrent publishers cannot share a temp name
#   4. write all bytes, os.fsync(fd), close                           -> the bytes
#      are durable BEFORE anything points at them
#   5. os.replace(tmp, dest)                                          -> atomic
#      swap of the directory entry; a reader sees either the whole old file or
#      the whole new one, never a truncated one and never no file at all
#   6. best-effort directory fsync (POSIX only; opening a directory is not
#      permitted on Windows, so this is skipped and REPORTED as skipped)
#   7. on ANY failure, unlink the temp; the destination is left untouched
#
# This is the direct replacement for the truncate-in-place at
# run_scene_survey_probe.py:729 and :473.
_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF_S = 0.05


def atomic_write_bytes(dest: Any, data: bytes, *, repo_root: Any = None) -> OpResult:
    """Publish ``data`` to ``dest`` atomically. Never truncates in place."""
    if not isinstance(data, (bytes, bytearray)):
        return _fail(C.SCENE_SURVEY_REPORT_INVALID, "not_bytes",
                     "atomic_write_bytes requires bytes, got {}".format(type(data).__name__))
    dest_path = Path(str(dest))
    if repo_root is not None:
        rel = relative_posix(repo_root, dest_path.parent) if dest_path.is_absolute() else None
        if rel is not None and not rel.ok:
            return rel
        if not dest_path.is_absolute():
            conf = confine_path(repo_root, str(dest))
            if not conf.ok:
                return conf
            dest_path = conf.value["absolute"]

    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _fail(C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED, "mkdir_failed",
                     "cannot create destination directory {}: {}".format(dest_path.parent, exc))

    tmp = dest_path.with_name("{}.tmp-{}-{}".format(dest_path.name, os.getpid(), uuid.uuid4().hex))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = None
    try:
        fd = os.open(str(tmp), flags, 0o644)
        os.write(fd, bytes(data))
        os.fsync(fd)
    except OSError as exc:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        _quiet_unlink(tmp)
        return _fail(C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED, "temp_write_failed",
                     "could not write temp file {}: {}".format(tmp, exc))
    try:
        os.close(fd)
    except OSError as exc:
        _quiet_unlink(tmp)
        return _fail(C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED, "temp_close_failed",
                     "could not close temp file {}: {}".format(tmp, exc))

    last: Optional[OSError] = None
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(str(tmp), str(dest_path))
            last = None
            break
        except PermissionError as exc:
            # Windows: a scanner or a reader without FILE_SHARE_DELETE can hold the
            # destination briefly. Bounded retry, then give up with the temp removed.
            last = exc
            time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))
        except OSError as exc:
            last = exc
            break
    if last is not None:
        _quiet_unlink(tmp)
        return _fail(C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED, "replace_failed",
                     "could not atomically replace {}: {}".format(dest_path, last))

    dir_fsynced = False
    if hasattr(os, "O_DIRECTORY"):  # POSIX only; opening a directory fails on Windows
        try:
            dfd = os.open(str(dest_path.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dfd)
                dir_fsynced = True
            finally:
                os.close(dfd)
        except OSError:
            dir_fsynced = False

    return _ok({"path": dest_path, "bytes": len(data), "sha256": digest_bytes(bytes(data)),
                "dir_fsynced": dir_fsynced},
               "published {} bytes atomically".format(len(data)))


def atomic_write_json(dest: Any, obj: Any, *, repo_root: Any = None) -> OpResult:
    """Serialize (sorted keys, indent 2, LF-only) and publish atomically."""
    blob = pretty_json_bytes(obj)
    if not blob.ok:
        return blob
    return atomic_write_bytes(dest, blob.value, repo_root=repo_root)


def _quiet_unlink(path: Path) -> None:
    try:
        os.unlink(str(path))
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# request hashing
# --------------------------------------------------------------------------- #
# THE SPLIT, AND WHY.
#
# The request hash answers exactly one question: "is this the same QUESTION that
# was asked?" It must NOT answer "is this the same ASKING?" — that is
# operation_id's job, and collapsing the two into one scalar destroys the ability
# to report WF1128 (a manifest bound to a different operation) separately from a
# genuine change of subject.
#
# INCLUDED (12) — everything that determines what the survey is ABOUT:
#   source_repository, source_commit          the asking side's identity
#   target_repository, target_commit          the surveyed tree's identity
#   target_engine, target_project, target_map the surveyed world
#   required_plugin, required_plugin_version,
#   required_plugin_source_hash               the far-side CODE that observes it
#                                             (a different plugin build is a
#                                             different question — see the
#                                             WF1026 preflight at
#                                             run_scene_survey_probe.py:642-648)
#   requested_operation                       which capability was asked for
#   subject                                   the caller-resolved SceneSurveySubject
#                                             (schema.py:100), hashed in full and
#                                             recursively — it IS the question
#
# EXCLUDED (3) — each is recorded verbatim in the manifest, so "excluded from the
# hash" never means "unaudited":
#   operation_id     Excluded ON PURPOSE. It identifies the ASKING, not the
#                    question. If it were hashed, two runs of an identical survey
#                    would produce different hashes and the hash could never
#                    detect a prior artifact re-presented under a new id — which
#                    is precisely the replay this module exists to catch. Bound
#                    SEPARATELY as manifest["operation_id"] and checked
#                    independently, so replay (new id, same question) surfaces as
#                    WF1128 while a changed question surfaces as a hash mismatch.
#   output_location  Where the answer is DELIVERED, not what was asked. Two
#                    identical surveys written to two directories are the same
#                    evidence; hashing it would mean a caller who reorganized its
#                    output tree could no longer detect stale evidence for an
#                    identical subject. It is confined separately by confine_path
#                    (WF1130) and stored verbatim under manifest["delivery"].
#   timeout_seconds  A runner knob (default 300 at schema.py:94; the probe's own
#                    default is 900 at run_scene_survey_probe.py:586). A survey of
#                    the same subject with a longer patience is the same survey.
#                    Stored at manifest["timeout_seconds"].
#
# ANTI-DRIFT: hash_request refuses any request carrying a field in neither set.
# A future field added to BridgeRequest therefore FAILS CLOSED instead of being
# silently omitted from the hash — which would be a silent replay hole.
REQUEST_HASH_ALGORITHM = "sha256"
REQUEST_HASH_FIELD_SET_VERSION = 1
REQUEST_HASH_INCLUDED: Tuple[str, ...] = (
    "required_plugin",
    "required_plugin_source_hash",
    "required_plugin_version",
    "requested_operation",
    "source_commit",
    "source_repository",
    "subject",
    "target_commit",
    "target_engine",
    "target_map",
    "target_project",
    "target_repository",
)
REQUEST_HASH_EXCLUDED: Tuple[str, ...] = (
    "operation_id",
    "output_location",
    "timeout_seconds",
)
REQUEST_HASH_KNOWN = frozenset(REQUEST_HASH_INCLUDED) | frozenset(REQUEST_HASH_EXCLUDED)


def request_as_dict(request: Any) -> OpResult:
    """Normalize a BridgeRequest dataclass / mapping / to_dict()-able into a dict."""
    if dataclasses.is_dataclass(request) and not isinstance(request, type):
        try:
            return _ok(dataclasses.asdict(request))
        except (TypeError, ValueError) as exc:
            return _fail(C.SCENE_SURVEY_REPORT_INVALID, "request_not_convertible",
                         "cannot convert request dataclass: {}".format(exc))
    if isinstance(request, dict):
        return _ok(dict(request))
    to_dict = getattr(request, "to_dict", None)
    if callable(to_dict):
        try:
            out = to_dict()
        except Exception as exc:  # noqa: BLE001
            return _fail(C.SCENE_SURVEY_REPORT_INVALID, "request_to_dict_failed",
                         "request.to_dict() failed: {}".format(exc))
        if isinstance(out, dict):
            return _ok(dict(out))
    return _fail(C.SCENE_SURVEY_REPORT_INVALID, "request_not_a_mapping",
                 "request is not a dataclass, mapping, or to_dict()-able: {}".format(
                     type(request).__name__))


def hash_request(request: Any) -> OpResult:
    """Stable hash over the documented BridgeRequest field set.

    ``value = {"request_hash": "sha256:...", "preimage": "<canonical json>",
               "field_set_version": int, "included": [...], "excluded": [...]}``
    """
    asdict_res = request_as_dict(request)
    if not asdict_res.ok:
        return asdict_res
    data = asdict_res.value

    unknown = sorted(set(data) - REQUEST_HASH_KNOWN)
    if unknown:
        return _fail(C.SCENE_SURVEY_OPERATION_ID_MISMATCH, "unknown_request_fields",
                     "request carries field(s) {} that are in neither the hashed nor the "
                     "documented-exclusion set. Refusing rather than hashing a partial "
                     "request: an undocumented exclusion is a replay hole. Update "
                     "REQUEST_HASH_INCLUDED/REQUEST_HASH_EXCLUDED and bump "
                     "REQUEST_HASH_FIELD_SET_VERSION.".format(unknown))
    missing = sorted(f for f in REQUEST_HASH_INCLUDED if f not in data)
    if missing:
        return _fail(C.SCENE_SURVEY_OPERATION_ID_MISMATCH, "missing_hashed_fields",
                     "request is missing hashed field(s) {} — cannot bind evidence to a "
                     "request that does not state what it asked for".format(missing))

    fields = {name: data[name] for name in REQUEST_HASH_INCLUDED}
    # The field-set version and the field NAMES are part of the preimage, so
    # changing the covered set changes every hash. A hash can never be silently
    # reinterpreted under a new set.
    preimage = canonical_json({
        "algorithm": REQUEST_HASH_ALGORITHM,
        "field_set_version": REQUEST_HASH_FIELD_SET_VERSION,
        "fields": fields,
        "field_names": list(REQUEST_HASH_INCLUDED),
    })
    if not preimage.ok:
        return preimage
    return _ok({
        "request_hash": "sha256:" + sha256_hex(preimage.value.encode("utf-8")),
        "preimage": preimage.value,
        "field_set_version": REQUEST_HASH_FIELD_SET_VERSION,
        "included": list(REQUEST_HASH_INCLUDED),
        "excluded": list(REQUEST_HASH_EXCLUDED),
    })


# --------------------------------------------------------------------------- #
# process liveness (for stale-lock detection)
# --------------------------------------------------------------------------- #
# NEVER use os.kill(pid, 0) on Windows: CPython implements os.kill there as
# OpenProcess + TerminateProcess(handle, sig), so signal 0 would KILL the target
# with exit code 0 rather than probe it.
def _pid_alive(pid: int) -> Optional[bool]:
    """True / False / None(=cannot determine). None must be treated as ALIVE."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                err = ctypes.get_last_error()
                if err == 87:  # ERROR_INVALID_PARAMETER -> no such process
                    return False
                return None  # ERROR_ACCESS_DENIED etc: exists but unqueryable
            try:
                code = wintypes.DWORD()
                if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                    return None
                return code.value == STILL_ACTIVE
            finally:
                k32.CloseHandle(h)
        except Exception:  # noqa: BLE001
            return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def _pid_start_token(pid: int) -> Optional[str]:
    """A cheap process-identity token, so a REUSED pid is not mistaken for alive.

    Windows: the process creation time from GetProcessTimes.
    Linux:   field 22 (starttime) of /proc/<pid>/stat.
    Else:    None — reuse detection is then unavailable and is reported as such.
    """
    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return None
            try:
                creation = wintypes.FILETIME()
                exit_t = wintypes.FILETIME()
                kernel_t = wintypes.FILETIME()
                user_t = wintypes.FILETIME()
                if not k32.GetProcessTimes(h, ctypes.byref(creation), ctypes.byref(exit_t),
                                           ctypes.byref(kernel_t), ctypes.byref(user_t)):
                    return None
                return "win:{}".format((creation.dwHighDateTime << 32) | creation.dwLowDateTime)
            finally:
                k32.CloseHandle(h)
        except Exception:  # noqa: BLE001
            return None
    try:
        with open("/proc/{}/stat".format(pid), "r", encoding="utf-8") as fh:
            raw = fh.read()
        tail = raw[raw.rfind(")") + 1:].split()
        return "linux:{}".format(tail[19])  # field 22 overall, index 19 after comm
    except (OSError, IndexError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# single-writer lock  (WF1129)
# --------------------------------------------------------------------------- #
LOCK_REL = "procedural/reports/scene_survey/runtime/.scene_survey_operation.lock"
DEFAULT_LOCK_TTL_SECONDS = 3600  # > --repeat 2 x --timeout 900 (probe:584,:586) + boot slack


@dataclasses.dataclass(frozen=True)
class LockHandle:
    path: Path
    operation_id: str
    nonce: str
    pid: int
    host: str
    created_at_utc: str
    body: Dict[str, Any]


def _read_lock_body(path: Path) -> Optional[Dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _lock_staleness(body: Optional[Dict[str, Any]], path: Path, now: float,
                    ttl_seconds: int) -> Tuple[bool, str]:
    """Decide staleness. Returns (is_stale, human reason).

    STALE means, precisely, BOTH of:
      (a) AGE  — the lock's ``created_at_utc`` (or, if the body is unreadable, the
                 file's mtime) is more than ``ttl_seconds`` in the past; AND
      (b) DEAD — the holder recorded THIS host, and the recorded pid is not alive,
                 or is alive but its process-start token differs from the recorded
                 one (i.e. the pid was recycled and belongs to something else).

    The conjunction is what makes clock skew non-fatal. A clock that jumps
    BACKWARD makes a lock look younger — never stale — which is fail-closed. A
    clock that jumps FORWARD makes a live lock look aged, but (b) still sees the
    live process and refuses to break it.

    A holder on a DIFFERENT host cannot be probed, so (b) is unsatisfiable and the
    lock is NEVER declared stale automatically. That is deliberate: this is a
    single-host guard, and silently breaking a remote holder's lock would be the
    exact cross-binding it exists to prevent.
    """
    if body is None:
        try:
            age = now - os.path.getmtime(str(path))
        except OSError:
            return False, "lock body unreadable and mtime unavailable"
        if age <= ttl_seconds:
            return False, "lock body unparseable but only {:.0f}s old".format(age)
        return True, ("lock body unparseable and mtime is {:.0f}s old (> ttl {}s); no pid "
                      "to probe".format(age, ttl_seconds))

    created = _parse_iso(body.get("created_at_utc"))
    if created is None:
        return False, "lock has no parseable created_at_utc; refusing to break it"
    age = now - created
    if age <= ttl_seconds:
        return False, "holder is {:.0f}s old, within ttl {}s".format(age, ttl_seconds)

    host = body.get("host")
    if host != socket.gethostname():
        return False, ("holder is on host {!r}, not {!r}; liveness cannot be probed so the "
                       "lock is never auto-broken".format(host, socket.gethostname()))

    pid = body.get("pid")
    alive = _pid_alive(pid if isinstance(pid, int) else -1)
    if alive is None:
        return False, "pid {} liveness could not be determined; treating as alive".format(pid)
    if alive:
        recorded_token = body.get("pid_start_token")
        current_token = _pid_start_token(pid)
        if recorded_token and current_token and recorded_token != current_token:
            return True, ("pid {} is alive but its start token changed ({} -> {}): the pid was "
                          "recycled, the holder is gone, and the lock is {:.0f}s old".format(
                              pid, recorded_token, current_token, age))
        return False, "pid {} is still alive; lock is held, not stale".format(pid)
    return True, "pid {} is not alive and the lock is {:.0f}s old (> ttl {}s)".format(
        pid, age, ttl_seconds)


def acquire_operation_lock(repo_root: Any, operation_id: str, *,
                           lock_rel: str = LOCK_REL,
                           ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
                           attempts: int = 3,
                           now: Optional[float] = None) -> OpResult:
    """Take the single-writer lock, or REFUSE with WF1129. ``value = LockHandle``."""
    if not isinstance(operation_id, str) or not operation_id.strip():
        return _fail(C.SCENE_SURVEY_OPERATION_ID_MISMATCH, "no_operation_id",
                     "an operation lock requires a non-empty operation_id")
    conf = confine_path(repo_root, lock_rel)
    if not conf.ok:
        return conf
    lock_path = conf.value["absolute"]
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _fail(C.SCENE_SURVEY_CONCURRENT_OPERATION, "lock_dir_unavailable",
                     "cannot create lock directory {}: {}".format(lock_path.parent, exc))

    last_detail = ""
    for attempt in range(max(1, attempts)):
        clock = time.time() if now is None else now
        pid = os.getpid()
        body = {
            "schema_version": LOCK_SCHEMA_VERSION,
            "operation_id": operation_id,
            "nonce": uuid.uuid4().hex,
            "pid": pid,
            "pid_start_token": _pid_start_token(pid),
            "host": socket.gethostname(),
            "created_at_utc": _iso(clock),
            "ttl_seconds": int(ttl_seconds),
        }
        blob = pretty_json_bytes(body)
        if not blob.ok:
            return blob
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(str(lock_path), flags, 0o644)
        except FileExistsError:
            held = _read_lock_body(lock_path)
            stale, why = _lock_staleness(held, lock_path, clock, ttl_seconds)
            if not stale:
                return _fail(
                    C.SCENE_SURVEY_CONCURRENT_OPERATION, "lock_held",
                    "another operation holds {}: operation_id={!r} pid={} host={!r} "
                    "created_at_utc={!r} — {}".format(
                        conf.value["relative_posix"],
                        (held or {}).get("operation_id"), (held or {}).get("pid"),
                        (held or {}).get("host"), (held or {}).get("created_at_utc"), why))
            # STEAL BY RENAME, never by unlink-then-create: renaming a stale lock
            # aside to a unique name succeeds for exactly ONE racer; every other
            # racer gets FileNotFoundError and loops. Unlink-then-create would let
            # two breakers both "win".
            aside = lock_path.with_name(lock_path.name + ".stale-" + uuid.uuid4().hex)
            try:
                os.replace(str(lock_path), str(aside))
            except FileNotFoundError:
                last_detail = "lost the steal race for a stale lock; retrying"
                continue
            except OSError as exc:
                return _fail(C.SCENE_SURVEY_CONCURRENT_OPERATION, "stale_lock_unbreakable",
                             "stale lock {} could not be moved aside: {}".format(lock_path, exc))
            _quiet_unlink(aside)
            last_detail = "broke a stale lock: {}".format(why)
            continue
        except OSError as exc:
            return _fail(C.SCENE_SURVEY_CONCURRENT_OPERATION, "lock_unopenable",
                         "cannot create lock {}: {}".format(lock_path, exc))

        try:
            os.write(fd, blob.value)
            os.fsync(fd)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
        return _ok(LockHandle(path=lock_path, operation_id=operation_id, nonce=body["nonce"],
                              pid=pid, host=body["host"], created_at_utc=body["created_at_utc"],
                              body=body),
                   "acquired {}{}".format(conf.value["relative_posix"],
                                          " (" + last_detail + ")" if last_detail else ""))
    return _fail(C.SCENE_SURVEY_CONCURRENT_OPERATION, "lock_contended",
                 "could not acquire {} in {} attempts: {}".format(lock_path, attempts,
                                                                  last_detail or "contended"))


def release_operation_lock(handle: Any) -> OpResult:
    """Release a lock we hold. Refuses to delete a lock that is no longer ours.

    The nonce check matters: if our lock was declared stale and stolen while we
    were paused, the file on disk now belongs to somebody else and deleting it
    would hand a third process a second concurrent writer slot.
    """
    if not isinstance(handle, LockHandle):
        return _fail(C.SCENE_SURVEY_CONCURRENT_OPERATION, "not_a_lock_handle",
                     "release_operation_lock requires a LockHandle, got {}".format(
                         type(handle).__name__))
    body = _read_lock_body(handle.path)
    if body is None:
        return _fail(C.SCENE_SURVEY_CONCURRENT_OPERATION, "lock_vanished",
                     "lock {} is gone or unreadable; it was taken from us, not released "
                     "by us".format(handle.path))
    if body.get("nonce") != handle.nonce or body.get("operation_id") != handle.operation_id:
        return _fail(C.SCENE_SURVEY_CONCURRENT_OPERATION, "lock_not_ours",
                     "lock {} now holds operation_id={!r} nonce={!r}, not ours ({!r}/{!r}) — "
                     "refusing to delete another operation's lock".format(
                         handle.path, body.get("operation_id"), body.get("nonce"),
                         handle.operation_id, handle.nonce))
    try:
        os.unlink(str(handle.path))
    except OSError as exc:
        return _fail(C.SCENE_SURVEY_CONCURRENT_OPERATION, "lock_unlink_failed",
                     "could not release lock {}: {}".format(handle.path, exc))
    return _ok(True, "released {}".format(handle.path.name))


# --------------------------------------------------------------------------- #
# operation manifest
# --------------------------------------------------------------------------- #
MANIFEST_SCHEMA_VERSION = "wf.scene_survey.operation_manifest.v1"
LOCK_SCHEMA_VERSION = "wf.scene_survey.operation_lock.v1"
MANIFEST_DIR_REL = "procedural/reports/scene_survey/runtime/operations"
DIGEST_EXCLUDED_KEYS = ("manifest_digest",)

# EVIDENCE ROLES. Roles are closed so an integration cannot invent a category that
# no gate looks at.
EVIDENCE_ROLES = ("far_side_run", "stdout_markers", "request", "response", "other")
CAPTURE_ROLE = "capture"


def manifest_path_for(repo_root: Any, operation_id: str) -> OpResult:
    """Per-operation manifest path. Per-operation, NOT a shared 'latest' name.

    This is the shape that fixes hole (1): the gate must be handed an
    operation-scoped path, so a prior operation's artifact is not merely stale but
    is not even at the address being read.
    """
    slug = _slug(operation_id)
    if not slug:
        return _fail(C.SCENE_SURVEY_OPERATION_ID_MISMATCH, "unusable_operation_id",
                     "operation_id {!r} has no filesystem-safe form".format(operation_id))
    return confine_path(repo_root, "{}/{}/operation_manifest.json".format(MANIFEST_DIR_REL, slug))


def report_path_for(repo_root: Any, operation_id: str) -> OpResult:
    """Per-operation derived-report path (the companion to manifest_path_for)."""
    slug = _slug(operation_id)
    if not slug:
        return _fail(C.SCENE_SURVEY_OPERATION_ID_MISMATCH, "unusable_operation_id",
                     "operation_id {!r} has no filesystem-safe form".format(operation_id))
    return confine_path(repo_root, "{}/{}/scene_survey_report.json".format(MANIFEST_DIR_REL, slug))


def _slug(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    keep = [ch if (ch.isalnum() or ch in "._-") else "_" for ch in value.strip()]
    slug = "".join(keep).strip("._-")
    return slug[:120]


def _iso(epoch: Optional[float] = None) -> str:
    ts = time.time() if epoch is None else epoch
    return (datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
            .replace(microsecond=0).isoformat().replace("+00:00", "Z"))


def _parse_iso(text: Any) -> Optional[float]:
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        raw = text.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def compute_manifest_digest(manifest: Dict[str, Any]) -> OpResult:
    """Digest over the manifest with the digest field itself removed.

    Over the CANONICAL (compact, key-sorted) form, so the digest binds content and
    survives a reformat of the on-disk file. A value change does not survive it.
    """
    if not isinstance(manifest, dict):
        return _fail(C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING, "manifest_not_a_mapping",
                     "manifest is not a mapping: {}".format(type(manifest).__name__))
    body = {k: v for k, v in manifest.items() if k not in DIGEST_EXCLUDED_KEYS}
    canon = canonical_json(body)
    if not canon.ok:
        return canon
    return _ok("sha256:" + sha256_hex(canon.value.encode("utf-8")))


def _evidence_records(repo_root: Any, entries: Iterable[Any], *,
                      default_role: str) -> OpResult:
    """Digest a list of evidence paths into sorted, repo-relative records."""
    records: List[Dict[str, Any]] = []
    for entry in entries or ():
        if isinstance(entry, dict):
            raw_path = entry.get("path")
            role = entry.get("role", default_role)
            extra = {k: v for k, v in entry.items() if k not in ("path", "role")}
        else:
            raw_path, role, extra = entry, default_role, {}
        if default_role == CAPTURE_ROLE:
            allowed = (CAPTURE_ROLE,) + EVIDENCE_ROLES
        else:
            allowed = EVIDENCE_ROLES
        if role not in allowed:
            return _fail(C.SCENE_SURVEY_REPORT_INVALID, "unknown_evidence_role",
                         "evidence role {!r} is not one of {}".format(role, allowed))
        conf = confine_path(repo_root, raw_path if isinstance(raw_path, str) else "")
        if not conf.ok:
            return conf
        dig = digest_file(conf.value["absolute"])
        if not dig.ok:
            return dig
        rec = {"path": conf.value["relative_posix"], "role": role,
               "sha256": dig.value["sha256"], "bytes": dig.value["bytes"]}
        rec.update({k: v for k, v in extra.items() if k not in rec})
        records.append(rec)
    records.sort(key=lambda r: (r["role"], r["path"]))
    return _ok(records)


def build_operation_manifest(repo_root: Any, request: Any, *,
                             raw_evidence: Sequence[Any] = (),
                             derived_report: Any = None,
                             captures: Sequence[Any] = (),
                             cleanup: Optional[Dict[str, Any]] = None,
                             created_at_utc: Optional[str] = None) -> OpResult:
    """Build the immutable operation manifest. Returns ``value = manifest dict``.

    SCHEMA, and why each block is in it:

      schema_version / manifest_version   what this document IS
      operation_id                        the ASKING — the anti-replay discriminator
      request_hash (+ algorithm, field-set
        version, included, excluded)      the QUESTION, plus the covered field set
                                          recorded IN the manifest so a reader can
                                          check what the hash did and did not cover
                                          without reading this source file
      created_at_utc                      when the binding was made
      source / target / plugin            WHO asked, WHAT was surveyed (repo,
                                          commit, engine, project, map) and with
                                          WHICH far-side code — the target identity
      target.subject_*                    the caller-resolved subject's identity
                                          plus a digest of the whole subject, so a
                                          mutated subject is visible without
                                          re-deriving the request hash
      delivery                            output_location verbatim + its confined
                                          form: excluded from the hash, never
                                          unaudited
      timeout_seconds                     likewise excluded, likewise recorded
      raw_evidence[]                      the INPUTS the report was derived from,
                                          each with a digest — so "the report says
                                          X" can be re-derived rather than trusted
      derived_report                      the report path + digest: the one artifact
                                          the runtime gate actually reads
      captures[]                          capture files + digests (opt-in; an empty
                                          list is a legal clean pass, per
                                          run_scene_survey_probe.py:510-516)
      cleanup                             the cleanup claim + its report digest
      manifest_digest                     seals every field above

    Immutability is by digest, not by file permission: any edit to any field
    invalidates ``manifest_digest``, which ``verify_operation_evidence`` recomputes.
    """
    req_res = request_as_dict(request)
    if not req_res.ok:
        return req_res
    req = req_res.value

    hashed = hash_request(req)
    if not hashed.ok:
        return hashed

    operation_id = req.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id.strip():
        return _fail(C.SCENE_SURVEY_OPERATION_ID_MISMATCH, "no_operation_id",
                     "request has no non-empty operation_id; evidence with no operation "
                     "identity is unfalsifiable")

    # output_location is CONFINED here even though it is excluded from the hash.
    # This is the check missing at run_scene_survey_probe.py:658 / :471.
    delivery: Dict[str, Any] = {"output_location": req.get("output_location")}
    conf = confine_path(repo_root, req.get("output_location"))
    if not conf.ok:
        return conf
    delivery["output_location_relative_posix"] = conf.value["relative_posix"]
    delivery["output_location_confined"] = True

    raw_res = _evidence_records(repo_root, raw_evidence, default_role="far_side_run")
    if not raw_res.ok:
        return raw_res
    cap_res = _evidence_records(repo_root, captures, default_role=CAPTURE_ROLE)
    if not cap_res.ok:
        return cap_res

    if derived_report is None:
        return _fail(C.SCENE_SURVEY_EVIDENCE_MISSING, "no_derived_report",
                     "a manifest must bind the derived report the runtime gate reads")
    dr_res = _evidence_records(repo_root, [
        derived_report if isinstance(derived_report, dict)
        else {"path": derived_report, "role": "other"}], default_role="other")
    if not dr_res.ok:
        return dr_res
    derived = dict(dr_res.value[0])
    derived.pop("role", None)

    subject = req.get("subject")
    subject_digest = None
    if subject is not None:
        sc = canonical_json(subject)
        if not sc.ok:
            return sc
        subject_digest = "sha256:" + sha256_hex(sc.value.encode("utf-8"))

    cleanup_block: Dict[str, Any] = {
        "cleanup_verified": False,
        "temporary_placements": 0,
        "residual_actor_paths": [],
        "report_path": None,
        "report_sha256": None,
    }
    if cleanup is not None:
        if not isinstance(cleanup, dict):
            return _fail(C.SCENE_SURVEY_CLEANUP_UNVERIFIED, "cleanup_not_a_mapping",
                         "cleanup must be a mapping, got {}".format(type(cleanup).__name__))
        unknown = sorted(set(cleanup) - set(cleanup_block))
        if unknown:
            return _fail(C.SCENE_SURVEY_CLEANUP_UNVERIFIED, "unknown_cleanup_fields",
                         "cleanup carries unknown field(s) {}".format(unknown))
        cleanup_block.update(cleanup)
        if cleanup_block.get("report_path"):
            cconf = confine_path(repo_root, cleanup_block["report_path"])
            if not cconf.ok:
                return cconf
            cdig = digest_file(cconf.value["absolute"])
            if not cdig.ok:
                return cdig
            cleanup_block["report_path"] = cconf.value["relative_posix"]
            cleanup_block["report_sha256"] = cdig.value["sha256"]

    manifest: Dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_version": 1,
        "operation_id": operation_id,
        "created_at_utc": created_at_utc or _iso(),
        "request_hash": hashed.value["request_hash"],
        "request_hash_algorithm": REQUEST_HASH_ALGORITHM,
        "request_hash_field_set_version": hashed.value["field_set_version"],
        "request_hash_included_fields": hashed.value["included"],
        "request_hash_excluded_fields": hashed.value["excluded"],
        "source": {
            "repository": req.get("source_repository"),
            "commit": req.get("source_commit"),
        },
        "target": {
            "repository": req.get("target_repository"),
            "commit": req.get("target_commit"),
            "engine": req.get("target_engine"),
            "project": req.get("target_project"),
            "map": req.get("target_map"),
            "subject_id": (subject or {}).get("subject_id") if isinstance(subject, dict) else None,
            "subject_map_asset_path": ((subject or {}).get("map_asset_path")
                                       if isinstance(subject, dict) else None),
            "subject_kind": (subject or {}).get("kind") if isinstance(subject, dict) else None,
            "subject_digest": subject_digest,
        },
        "plugin": {
            "name": req.get("required_plugin"),
            "version": req.get("required_plugin_version"),
            "source_hash": req.get("required_plugin_source_hash"),
        },
        "requested_operation": req.get("requested_operation"),
        "delivery": delivery,
        "timeout_seconds": req.get("timeout_seconds"),
        "raw_evidence": raw_res.value,
        "derived_report": derived,
        "captures": cap_res.value,
        "cleanup": cleanup_block,
    }
    dig = compute_manifest_digest(manifest)
    if not dig.ok:
        return dig
    manifest["manifest_digest"] = dig.value
    return _ok(manifest, "manifest for operation {}".format(operation_id))


def publish_operation_manifest(repo_root: Any, manifest: Dict[str, Any],
                               dest: Any = None) -> OpResult:
    """Atomically publish a manifest. ``dest`` defaults to manifest_path_for()."""
    if not isinstance(manifest, dict):
        return _fail(C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING, "manifest_not_a_mapping",
                     "manifest is not a mapping")
    check = verify_manifest_digest(manifest)
    if not check.ok:
        return check
    if dest is None:
        dres = manifest_path_for(repo_root, manifest.get("operation_id"))
        if not dres.ok:
            return dres
        dest_path = dres.value["absolute"]
    else:
        dest_path = Path(str(dest))
    return atomic_write_json(dest_path, manifest, repo_root=repo_root)


def load_operation_manifest(path: Any) -> OpResult:
    """Load + digest-verify a manifest. Absent/unusable is WF1127."""
    p = Path(str(path))
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        return _fail(C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING, "manifest_absent",
                     "no operation manifest at {} — evidence with no manifest cannot be "
                     "bound to an operation".format(p))
    except OSError as exc:
        return _fail(C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING, "manifest_unreadable",
                     "operation manifest unreadable at {}: {}".format(p, exc))
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return _fail(C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING, "manifest_unparseable",
                     "operation manifest at {} is not valid UTF-8 JSON: {}".format(p, exc))
    if not isinstance(obj, dict):
        return _fail(C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING, "manifest_not_a_mapping",
                     "operation manifest at {} is not a JSON object".format(p))
    check = verify_manifest_digest(obj)
    if not check.ok:
        return check
    return _ok(obj)


def verify_manifest_digest(manifest: Dict[str, Any]) -> OpResult:
    """The manifest must seal itself. A tampered manifest is treated as absent."""
    if not isinstance(manifest, dict):
        return _fail(C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING, "manifest_not_a_mapping",
                     "manifest is not a mapping")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return _fail(C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING, "wrong_schema_version",
                     "manifest schema_version is {!r}, expected {!r}".format(
                         manifest.get("schema_version"), MANIFEST_SCHEMA_VERSION))
    stated = manifest.get("manifest_digest")
    if not isinstance(stated, str) or not stated:
        return _fail(C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING, "no_manifest_digest",
                     "manifest carries no manifest_digest; it seals nothing")
    recomputed = compute_manifest_digest(manifest)
    if not recomputed.ok:
        return recomputed
    if recomputed.value != stated:
        return _fail(C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING, "manifest_digest_mismatch",
                     "manifest_digest {} does not match the manifest's contents ({}) — the "
                     "manifest was edited after it was sealed".format(stated, recomputed.value))
    return _ok(True)


# --------------------------------------------------------------------------- #
# replay / staleness
# --------------------------------------------------------------------------- #
def verify_operation_evidence(repo_root: Any, manifest: Any, request: Any, *,
                              max_age_seconds: Optional[int] = None,
                              now: Optional[float] = None,
                              check_files: bool = True) -> OpResult:
    """Was this evidence produced FOR THIS request, or is it a prior artifact?

    Order, and the code each step owns:

      1. manifest present, right schema, self-sealed          -> WF1127
      2. manifest.operation_id == request.operation_id        -> WF1128
         This is THE anti-replay discriminator. A prior artifact re-presented for
         a new asking has the old id and fails here, even though the question —
         and therefore the request hash — is byte-identical. That separability is
         exactly why operation_id is excluded from the hash.
      3. manifest.request_hash == hash_request(request)       -> WF1128
         A different question with the same id.
      4. field-set version agrees                             -> WF1128
         A manifest hashed under a different covered field set cannot be compared.
      5. every raw evidence file exists and digests match     -> WF1113
      6. the derived report exists and digests match          -> WF1100
      7. optional max_age                                     -> WF1128

    NOT CHECKED HERE (out of scope, and stated so rather than implied): whether
    the report's CONTENTS are valid — that is
    ``scene_survey_contracts.validate_scene_survey_report`` and the subject
    binding at ``validate_scene_survey_runtime.py:72-99``. This function answers
    only "does this evidence belong to this request".
    """
    clock = time.time() if now is None else now

    if isinstance(manifest, (str, Path)):
        loaded = load_operation_manifest(manifest)
        if not loaded.ok:
            return loaded
        manifest = loaded.value
    seal = verify_manifest_digest(manifest)
    if not seal.ok:
        return seal

    req_res = request_as_dict(request)
    if not req_res.ok:
        return req_res
    req = req_res.value

    if manifest.get("operation_id") != req.get("operation_id"):
        return _fail(C.SCENE_SURVEY_OPERATION_ID_MISMATCH, "operation_id_mismatch",
                     "manifest binds operation_id {!r} but the request is {!r} — this "
                     "evidence was produced for a different operation and is being "
                     "re-presented".format(manifest.get("operation_id"), req.get("operation_id")))

    if manifest.get("request_hash_field_set_version") != REQUEST_HASH_FIELD_SET_VERSION:
        return _fail(C.SCENE_SURVEY_OPERATION_ID_MISMATCH, "field_set_version_mismatch",
                     "manifest was hashed under request field-set version {!r}; this build "
                     "uses {} — the two hashes are not comparable".format(
                         manifest.get("request_hash_field_set_version"),
                         REQUEST_HASH_FIELD_SET_VERSION))

    hashed = hash_request(req)
    if not hashed.ok:
        return hashed
    if manifest.get("request_hash") != hashed.value["request_hash"]:
        return _fail(C.SCENE_SURVEY_OPERATION_ID_MISMATCH, "request_hash_mismatch",
                     "manifest binds request_hash {} but this request hashes to {} — the "
                     "evidence answers a different question (target, subject, plugin or "
                     "commit changed)".format(manifest.get("request_hash"),
                                              hashed.value["request_hash"]))

    if check_files:
        for rec in manifest.get("raw_evidence") or []:
            res = _reverify_record(repo_root, rec, C.SCENE_SURVEY_EVIDENCE_RAW_MISSING,
                                   "raw evidence")
            if not res.ok:
                return res
        for rec in manifest.get("captures") or []:
            res = _reverify_record(repo_root, rec, C.SCENE_SURVEY_EVIDENCE_RAW_MISSING,
                                   "capture")
            if not res.ok:
                return res
        derived = manifest.get("derived_report") or {}
        res = _reverify_record(repo_root, derived, C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED,
                               "derived report")
        if not res.ok:
            return res

    if max_age_seconds is not None:
        created = _parse_iso(manifest.get("created_at_utc"))
        if created is None:
            return _fail(C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING, "no_created_at",
                         "manifest has no parseable created_at_utc; its age is unknowable")
        age = clock - created
        if age > max_age_seconds:
            return _fail(C.SCENE_SURVEY_OPERATION_ID_MISMATCH, "manifest_too_old",
                         "manifest binds this request but was sealed {:.0f}s ago, beyond the "
                         "caller's max_age of {}s".format(age, max_age_seconds))

    return _ok({"operation_id": manifest.get("operation_id"),
                "request_hash": manifest.get("request_hash")},
               "evidence is bound to operation {}".format(manifest.get("operation_id")))


def _reverify_record(repo_root: Any, rec: Any, missing_code: str, label: str) -> OpResult:
    if not isinstance(rec, dict) or not isinstance(rec.get("path"), str):
        return _fail(missing_code, "malformed_evidence_record",
                     "{} record is malformed: {!r}".format(label, rec))
    conf = confine_path(repo_root, rec["path"])
    if not conf.ok:
        return conf
    dig = digest_file(conf.value["absolute"])
    if not dig.ok:
        return OpResult(False, missing_code, dig.detail, None, dig.reason)
    if dig.value["sha256"] != rec.get("sha256"):
        return _fail(missing_code, "evidence_digest_mismatch",
                     "{} {} digests {} but the manifest sealed {} — the file on disk is not "
                     "the artifact this operation produced".format(
                         label, rec["path"], dig.value["sha256"], rec.get("sha256")))
    return _ok(True)


# =========================================================================== #
# SELF-DOGFOOD
# =========================================================================== #
# Every control is proven BOTH ways: it must ACCEPT a legitimate case and REJECT a
# hostile one. The harness tracks accepts and rejects per control and FAILS a
# control that produced no accepts — so an all-reject implementation (the cheapest
# way to fake a green suite) cannot pass.
# =========================================================================== #
class _Suite:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, bool, str]] = []

    def accept(self, control: str, name: str, res: Any, detail: str = "") -> None:
        ok = bool(res.ok) if isinstance(res, OpResult) else bool(res)
        got = res.code if isinstance(res, OpResult) and res.code else ""
        self.rows.append((control, "ACCEPT " + name, ok,
                          detail or (("unexpected refusal: [{}] {}".format(
                              got, res.detail) if isinstance(res, OpResult) else "") if not ok
                              else "accepted")))

    def reject(self, control: str, name: str, res: Any, *, code: Optional[str] = None,
               reason: Optional[str] = None) -> None:
        if not isinstance(res, OpResult):
            self.rows.append((control, "REJECT " + name, False, "not an OpResult"))
            return
        ok = (not res.ok)
        why = "refused [{}] reason={}".format(res.code, res.reason)
        if ok and code is not None and res.code != code:
            ok, why = False, "refused with {}, expected {}".format(res.code, code)
        if ok and reason is not None and res.reason != reason:
            ok, why = False, "reason {!r}, expected {!r}".format(res.reason, reason)
        if not ok and res.ok:
            why = "ACCEPTED a hostile case (should have refused)"
        self.rows.append((control, "REJECT " + name, ok, why))

    def report(self) -> int:
        controls: Dict[str, Dict[str, int]] = {}
        for control, name, ok, _why in self.rows:
            c = controls.setdefault(control, {"accept": 0, "reject": 0, "pass": 0, "fail": 0})
            c["accept" if name.startswith("ACCEPT") else "reject"] += 1
            c["pass" if ok else "fail"] += 1
        width = max(len(n) for _c, n, _o, _w in self.rows) + 2
        current = None
        for control, name, ok, why in self.rows:
            if control != current:
                print("\n-- {} {}".format(control, "-" * max(0, 66 - len(control))))
                current = control
            print("   [{}] {:<{}} {}".format("PASS" if ok else "FAIL", name, width, why))
        print("\n" + "=" * 78)
        bad = 0
        for control in sorted(controls):
            c = controls[control]
            starved = c["accept"] == 0 or c["reject"] == 0
            status = "OK"
            if c["fail"]:
                status, bad = "FAILED", bad + 1
            elif starved:
                status, bad = "ONE-SIDED", bad + 1
            print("  {:<34} accept={} reject={} pass={} fail={}  {}".format(
                control, c["accept"], c["reject"], c["pass"], c["fail"], status))
        print("=" * 78)
        return bad


def _fake_request(**over: Any) -> Dict[str, Any]:
    """A BridgeRequest-shaped dict. Uses the real dataclass when importable."""
    base = {
        "operation_id": "op_v2_6_scene_survey_0001",
        "source_repository": "WorldForge",
        "source_commit": "d5e3ca17ab16770a3237e001f7b88ff0639a55fa",
        # A FIXTURE caller, deliberately anonymous. Naming a real target game here
        # would put the caller's vocabulary inside the WorldForge surface, which the
        # hygiene gate forbids for the same reason the ownership boundary does:
        # WorldForge owns capability, the caller owns its own names.
        "target_repository": "FixtureCaller",
        "target_commit": "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f",
        "target_engine": "5.8",
        "target_project": "FixtureCaller.uproject",
        "target_map": "/Game/Fixture/Lvl_Fixture",
        "required_plugin": "WorldForge",
        "required_plugin_version": "0.1.0",
        "requested_operation": "scene_survey",
        "output_location": "procedural/reports/scene_survey/responses",
        "timeout_seconds": 900,
        "subject": {
            "subject_id": "subject_fixture_alpha",
            "kind": "point",
            "map_asset_path": "/Game/Fixture/Lvl_Fixture",
            "anchor_location": [1200.0, -450.0, 96.0],
            "resolved_by": "caller",
        },
        "required_plugin_source_hash": "sha256:" + "ab" * 32,
    }
    base.update(over)
    return base


def _main() -> int:  # noqa: C901
    import shutil
    import tempfile

    s = _Suite()
    print("=" * 78)
    print("scene_survey_operation.py — SELF-DOGFOOD  (no editor, no network)")
    print("  python      : {}".format(sys.version.split()[0]))
    print("  os.name     : {}   host: {}".format(os.name, socket.gethostname()))
    print("  codes source: {}".format(CODES_SOURCE))
    print("=" * 78)

    root = Path(tempfile.mkdtemp(prefix="wf_scene_survey_op_"))
    outside = Path(tempfile.mkdtemp(prefix="wf_outside_"))
    try:
        # ---------------------------------------------------------------- #
        # CONTROL 0 — the codes we cite are the codes that exist
        # ---------------------------------------------------------------- #
        ctl = "0-failure-codes"
        expected = {
            "SCENE_SURVEY_OPERATION_MANIFEST_MISSING": "WF1127_SCENE_SURVEY_OPERATION_MANIFEST_MISSING",
            "SCENE_SURVEY_OPERATION_ID_MISMATCH": "WF1128_SCENE_SURVEY_OPERATION_ID_MISMATCH",
            "SCENE_SURVEY_CONCURRENT_OPERATION": "WF1129_SCENE_SURVEY_CONCURRENT_OPERATION",
            "SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE": "WF1130_SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE",
        }
        for attr, literal in expected.items():
            s.accept(ctl, "{} == {}".format(attr, literal),
                     _ok() if getattr(C, attr, None) == literal
                     else _fail("x", "x", "got {!r}".format(getattr(C, attr, None))))
        s.reject(ctl, "a code this module never uses is absent",
                 _fail(C.SCENE_SURVEY_OPERATION_ID_MISMATCH, "sentinel",
                       "sentinel: the harness itself distinguishes ok from not-ok"))

        # ---------------------------------------------------------------- #
        # CONTROL 1 — path confinement (WF1130)
        # ---------------------------------------------------------------- #
        ctl = "1-path-confinement"
        for good in ("procedural/reports/scene_survey/responses",
                     "procedural\\reports\\scene_survey\\responses",
                     "procedural/./reports//scene_survey",
                     "procedural/generated/scene_survey/requests/op_0001.json"):
            s.accept(ctl, "legit {!r}".format(good), confine_path(root, good))

        hostile: List[Tuple[str, Any, str]] = [
            ("absolute drive (win)", "C:/Windows/Temp/evil", "colon_drive_or_ads"),
            ("absolute drive backslash", "C:\\Windows\\Temp\\evil", "colon_drive_or_ads"),
            ("DRIVE-RELATIVE C:foo", "C:foo", "colon_drive_or_ads"),
            ("NTFS alt data stream", "procedural/report.json:hidden", "colon_drive_or_ads"),
            ("extended-length \\\\?\\", "\\\\?\\C:\\Windows\\Temp\\evil", "unc_or_device_path"),
            ("device \\\\.\\pipe", "\\\\.\\pipe\\wf", "unc_or_device_path"),
            ("UNC \\\\server\\share", "\\\\server\\share\\evil", "unc_or_device_path"),
            ("UNC //server/share", "//server/share/evil", "unc_or_device_path"),
            ("posix absolute /etc", "/etc/passwd", "root_relative"),
            ("backslash root \\Windows", "\\Windows\\Temp", "root_relative"),
            ("dotdot escape", "../../../Windows/Temp", "parent_traversal"),
            ("dotdot mid-path", "procedural/../../outside", "parent_traversal"),
            ("dotdot backslash mix", "procedural\\..\\..\\outside", "parent_traversal"),
            ("home expansion ~", "~/evil", "home_expansion"),
            ("reserved device NUL", "procedural/NUL", "reserved_device_name"),
            ("reserved device CON.json", "procedural/CON.json", "reserved_device_name"),
            ("reserved device COM1", "procedural/COM1/out", "reserved_device_name"),
            ("trailing dot component", "procedural/reports./x", "trailing_space_or_dot"),
            ("trailing space component", "procedural/reports /x", "trailing_space_or_dot"),
            ("NUL byte", "procedural/\x00evil", "control_character"),
            ("newline injection", "procedural/a\nb", "control_character"),
            ("empty string", "", "empty"),
            ("whitespace only", "   ", "empty"),
            ("not a string", 17, "not_a_string"),
            ("None", None, "not_a_string"),
            ("only dots", "./.", "no_components"),
            ("over-long", "a/" * 700, "too_long"),
        ]
        for name, value, reason in hostile:
            s.reject(ctl, name, confine_path(root, value),
                     code=C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, reason=reason)

        # sibling-prefix: "<root>-evil" must NOT count as inside "<root>"
        sibling = Path(str(root) + "-evil")
        sibling.mkdir(exist_ok=True)
        s.reject(ctl, "sibling prefix dir (startswith trap)",
                 confine_path(root, "../{}-evil/x".format(root.name)),
                 code=C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, reason="parent_traversal")

        # symlink escape — needs privilege on Windows; skipped honestly if refused.
        link = root / "linked_out"
        made_link = False
        try:
            link.symlink_to(outside, target_is_directory=True)
            made_link = True
        except (OSError, NotImplementedError):
            pass
        if made_link:
            s.reject(ctl, "symlink to outside the repo", confine_path(root, "linked_out/evil"),
                     code=C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE, reason="symlink_escape")
            # ...and a link that stays INSIDE must still be accepted, or the rail is
            # just "reject every link" wearing a specific reason string.
            (root / "procedural").mkdir(parents=True, exist_ok=True)
            inner = root / "linked_in"
            try:
                inner.symlink_to(root / "procedural", target_is_directory=True)
                s.accept(ctl, "symlink that stays inside the repo is allowed",
                         confine_path(root, "linked_in/reports"))
            except (OSError, NotImplementedError):
                print("   [SKIP] ACCEPT symlink that stays inside the repo -- link creation "
                      "failed on the second attempt")
        else:
            print("   [SKIP] REJECT symlink to outside the repo -- symlink creation not "
                  "permitted on this host (needs Developer Mode / admin); the containment "
                  "check itself is still exercised by the dotdot cases")

        # ---------------------------------------------------------------- #
        # CONTROL 2 — atomic publish
        # ---------------------------------------------------------------- #
        ctl = "2-atomic-publish"
        target = root / "procedural" / "reports" / "scene_survey" / "runtime" / "probe.json"
        r1 = atomic_write_json(target, {"b": 2, "a": 1}, repo_root=root)
        s.accept(ctl, "publishes into a fresh directory", r1)
        on_disk = target.read_bytes()
        s.accept(ctl, "on-disk bytes are LF-only (no CRLF translation)",
                 _ok() if b"\r" not in on_disk else _fail("x", "crlf", repr(on_disk[:60])))
        s.accept(ctl, "on-disk keys are sorted",
                 _ok() if on_disk.index(b'"a"') < on_disk.index(b'"b"')
                 else _fail("x", "unsorted", "sort_keys not applied"))
        s.accept(ctl, "trailing newline present",
                 _ok() if on_disk.endswith(b"\n") else _fail("x", "no_eol", ""))
        r2 = atomic_write_json(target, {"a": 9}, repo_root=root)
        s.accept(ctl, "overwrite is a replace, not a truncate", r2)
        s.accept(ctl, "no temp files left behind",
                 _ok() if not list(target.parent.glob("*.tmp-*"))
                 else _fail("x", "temp_leak", str(list(target.parent.glob("*.tmp-*")))))
        s.accept(ctl, "destination never absent after overwrite",
                 _ok() if target.is_file() else _fail("x", "vanished", ""))
        s.accept(ctl, "byte-identical republish is deterministic",
                 _ok() if atomic_write_json(target, {"a": 9}, repo_root=root).value["sha256"]
                 == r2.value["sha256"] else _fail("x", "nondeterministic", ""))
        s.reject(ctl, "publish outside the repo root",
                 atomic_write_json(str(outside / "evil.json"), {"x": 1}, repo_root=root),
                 code=C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE)
        s.reject(ctl, "non-finite float refused", atomic_write_json(
            root / "nan.json", {"x": float("nan")}, repo_root=root))
        s.reject(ctl, "non-string dict key refused", atomic_write_json(
            root / "k.json", {1: "x"}, repo_root=root))
        s.reject(ctl, "raw bytes required by atomic_write_bytes",
                 atomic_write_bytes(root / "b.json", "not bytes"))

        # ---------------------------------------------------------------- #
        # CONTROL 3 — request hashing
        # ---------------------------------------------------------------- #
        ctl = "3-request-hash"
        base_req = _fake_request()
        h0 = hash_request(base_req)
        s.accept(ctl, "hashes a well-formed request", h0)
        s.accept(ctl, "stable across repeated calls",
                 _ok() if hash_request(_fake_request()).value["request_hash"]
                 == h0.value["request_hash"] else _fail("x", "unstable", ""))
        s.accept(ctl, "key order in the subject dict is irrelevant",
                 _ok() if hash_request(_fake_request(subject={
                     "resolved_by": "caller", "anchor_location": [1200.0, -450.0, 96.0],
                     "map_asset_path": "/Game/Fixture/Lvl_Fixture", "kind": "point",
                     "subject_id": "subject_fixture_alpha"})).value["request_hash"]
                 == h0.value["request_hash"] else _fail("x", "order_sensitive", ""))
        for excluded, newval in (("operation_id", "op_TOTALLY_DIFFERENT"),
                                 ("output_location", "procedural/elsewhere"),
                                 ("timeout_seconds", 1800)):
            same = hash_request(_fake_request(**{excluded: newval})).value["request_hash"]
            s.accept(ctl, "EXCLUDED {} does not change the hash".format(excluded),
                     _ok() if same == h0.value["request_hash"]
                     else _fail("x", "excluded_leaked", "hash changed"))
        # "the hash MUST change" is a rejection of the sameness claim, so it is
        # recorded on the reject side: _differs() returns a failing OpResult when
        # the hash changed (the desired outcome) and a passing one when it did not.
        def _differs(req_over: Dict[str, Any]) -> OpResult:
            got = hash_request(_fake_request(**req_over))
            if not got.ok:
                return _ok(None, "hash_request itself refused: {}".format(got.detail))
            if got.value["request_hash"] == h0.value["request_hash"]:
                return _ok(None, "hash did NOT change — this field is silently unhashed")
            return _fail("SENTINEL", "hash_changed", "hash differs, as required")

        for included, newval in (("target_commit", "1" * 40),
                                 ("target_map", "/Game/Other/Lvl"),
                                 ("target_engine", "5.7"),
                                 ("target_project", "Other.uproject"),
                                 ("target_repository", "SomewhereElse"),
                                 ("required_plugin", "NotWorldForge"),
                                 ("required_plugin_version", "9.9.9"),
                                 ("required_plugin_source_hash", "sha256:" + "cd" * 32),
                                 ("requested_operation", "something_else"),
                                 ("source_repository", "NotWorldForge"),
                                 ("source_commit", "2" * 40)):
            s.reject(ctl, "INCLUDED {} changes the hash".format(included),
                     _differs({included: newval}), reason="hash_changed")
        s.reject(ctl, "INCLUDED subject changes the hash",
                 _differs({"subject": dict(base_req["subject"],
                                           subject_id="subject_fixture_beta")}),
                 reason="hash_changed")
        s.reject(ctl, "undocumented extra field refuses (anti-drift)",
                 hash_request(_fake_request(brand_new_field="x")),
                 code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH, reason="unknown_request_fields")
        missing = _fake_request()
        del missing["target_map"]
        s.reject(ctl, "missing hashed field refuses", hash_request(missing),
                 code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH, reason="missing_hashed_fields")
        s.reject(ctl, "non-request object refuses", hash_request(42))

        # field-set completeness against the REAL BridgeRequest, when importable.
        try:
            sys.path.insert(0, str(_REPO_ROOT_GUESS / "tools"))
            from bridge.schema import BridgeRequest as _BR  # type: ignore

            real = {f.name for f in dataclasses.fields(_BR)}
            s.accept(ctl, "field sets exactly cover BridgeRequest ({} fields)".format(len(real)),
                     _ok() if real == REQUEST_HASH_KNOWN
                     else _fail("x", "field_set_drift",
                                "unclassified={} phantom={}".format(
                                    sorted(real - REQUEST_HASH_KNOWN),
                                    sorted(REQUEST_HASH_KNOWN - real))))
        except Exception as exc:  # noqa: BLE001
            print("   [SKIP] ACCEPT field sets cover BridgeRequest -- import failed: "
                  "{}: {}".format(type(exc).__name__, exc))

        # ---------------------------------------------------------------- #
        # CONTROL 4 — single-writer lock (WF1129)
        # ---------------------------------------------------------------- #
        ctl = "4-single-writer-lock"
        l1 = acquire_operation_lock(root, "op_A")
        s.accept(ctl, "first operation takes the lock", l1)
        s.reject(ctl, "second operation is refused while held",
                 acquire_operation_lock(root, "op_B"),
                 code=C.SCENE_SURVEY_CONCURRENT_OPERATION, reason="lock_held")
        s.accept(ctl, "holder can release its own lock", release_operation_lock(l1.value))
        l2 = acquire_operation_lock(root, "op_B")
        s.accept(ctl, "lock is reusable after release", l2)
        s.reject(ctl, "release refuses a foreign lock (nonce guard)",
                 release_operation_lock(dataclasses.replace(l2.value, nonce="not-ours")),
                 code=C.SCENE_SURVEY_CONCURRENT_OPERATION, reason="lock_not_ours")
        s.accept(ctl, "real release still works", release_operation_lock(l2.value))
        s.reject(ctl, "release of an already-released lock refuses",
                 release_operation_lock(l2.value),
                 code=C.SCENE_SURVEY_CONCURRENT_OPERATION, reason="lock_vanished")
        s.reject(ctl, "empty operation_id refuses", acquire_operation_lock(root, "  "),
                 code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH)
        s.reject(ctl, "lock path outside the repo refuses",
                 acquire_operation_lock(root, "op_C", lock_rel="../evil.lock"),
                 code=C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE)
        s.reject(ctl, "release requires a LockHandle", release_operation_lock({"nonce": "x"}))

        # stale detection: a DEAD pid + aged lock is breakable...
        lock_file = (root / LOCK_REL)
        dead_pid = 999_999_999  # never a live pid; probes as not-alive
        lock_file.write_bytes(json.dumps({
            "schema_version": LOCK_SCHEMA_VERSION, "operation_id": "op_CRASHED",
            "nonce": "n", "pid": dead_pid, "pid_start_token": None,
            "host": socket.gethostname(), "created_at_utc": _iso(time.time() - 7200),
            "ttl_seconds": DEFAULT_LOCK_TTL_SECONDS}).encode("utf-8"))
        l3 = acquire_operation_lock(root, "op_RECOVER")
        s.accept(ctl, "aged lock held by a DEAD pid is broken (no deadlock)", l3)
        if l3.ok:
            release_operation_lock(l3.value)
        # ...but an aged lock held by a LIVE pid is NOT breakable.
        lock_file.write_bytes(json.dumps({
            "schema_version": LOCK_SCHEMA_VERSION, "operation_id": "op_LIVE",
            "nonce": "n", "pid": os.getpid(), "pid_start_token": _pid_start_token(os.getpid()),
            "host": socket.gethostname(), "created_at_utc": _iso(time.time() - 7200),
            "ttl_seconds": DEFAULT_LOCK_TTL_SECONDS}).encode("utf-8"))
        s.reject(ctl, "aged lock held by a LIVE pid is NOT broken",
                 acquire_operation_lock(root, "op_GREEDY"),
                 code=C.SCENE_SURVEY_CONCURRENT_OPERATION, reason="lock_held")
        # ...and a YOUNG lock with a dead pid is NOT breakable (TTL is required too).
        lock_file.write_bytes(json.dumps({
            "schema_version": LOCK_SCHEMA_VERSION, "operation_id": "op_YOUNG",
            "nonce": "n", "pid": dead_pid, "pid_start_token": None,
            "host": socket.gethostname(), "created_at_utc": _iso(),
            "ttl_seconds": DEFAULT_LOCK_TTL_SECONDS}).encode("utf-8"))
        s.reject(ctl, "young lock with a dead pid is NOT broken (TTL required)",
                 acquire_operation_lock(root, "op_IMPATIENT"),
                 code=C.SCENE_SURVEY_CONCURRENT_OPERATION, reason="lock_held")
        # ...and an aged lock owned by ANOTHER HOST is never auto-broken.
        lock_file.write_bytes(json.dumps({
            "schema_version": LOCK_SCHEMA_VERSION, "operation_id": "op_REMOTE",
            "nonce": "n", "pid": dead_pid, "pid_start_token": None,
            "host": "some-other-build-agent", "created_at_utc": _iso(time.time() - 999999),
            "ttl_seconds": DEFAULT_LOCK_TTL_SECONDS}).encode("utf-8"))
        s.reject(ctl, "aged lock owned by ANOTHER HOST is never auto-broken",
                 acquire_operation_lock(root, "op_CROSSHOST"),
                 code=C.SCENE_SURVEY_CONCURRENT_OPERATION, reason="lock_held")
        _quiet_unlink(lock_file)

        # ---------------------------------------------------------------- #
        # CONTROL 5 — manifest build / publish / seal
        # ---------------------------------------------------------------- #
        ctl = "5-operation-manifest"
        ev_dir = root / "procedural" / "reports" / "scene_survey" / "runtime"
        ev_dir.mkdir(parents=True, exist_ok=True)
        (ev_dir / "far_side_run1.json").write_bytes(b'{"run":1}\n')
        (ev_dir / "far_side_run2.json").write_bytes(b'{"run":2}\n')
        (ev_dir / "scene_survey_report.json").write_bytes(b'{"status":"ok"}\n')
        (ev_dir / "cleanup.json").write_bytes(b'{"residual":0}\n')
        rel = "procedural/reports/scene_survey/runtime"

        m = build_operation_manifest(
            root, base_req,
            raw_evidence=[{"path": rel + "/far_side_run1.json", "role": "far_side_run"},
                          {"path": rel + "/far_side_run2.json", "role": "far_side_run"}],
            derived_report={"path": rel + "/scene_survey_report.json"},
            captures=[],
            cleanup={"cleanup_verified": True, "temporary_placements": 3,
                     "residual_actor_paths": [], "report_path": rel + "/cleanup.json"})
        s.accept(ctl, "builds from a legitimate request + real evidence", m)
        s.accept(ctl, "seals itself (digest verifies)", verify_manifest_digest(m.value))
        s.accept(ctl, "binds request_hash",
                 _ok() if m.value["request_hash"] == h0.value["request_hash"]
                 else _fail("x", "hash_drift", ""))
        s.accept(ctl, "records the EXCLUDED fields verbatim",
                 _ok() if (m.value["delivery"]["output_location"] == base_req["output_location"]
                           and m.value["timeout_seconds"] == base_req["timeout_seconds"])
                 else _fail("x", "exclusion_unaudited", ""))
        s.accept(ctl, "stores only repo-relative POSIX paths",
                 _ok() if all("\\" not in r["path"] and ":" not in r["path"]
                              for r in m.value["raw_evidence"])
                 else _fail("x", "machine_path", str(m.value["raw_evidence"])))
        mp = manifest_path_for(root, base_req["operation_id"])
        s.accept(ctl, "per-operation manifest path is confined", mp)
        s.accept(ctl, "publishes atomically",
                 publish_operation_manifest(root, m.value, mp.value["absolute"]))
        s.accept(ctl, "round-trips off disk", load_operation_manifest(mp.value["absolute"]))
        s.accept(ctl, "reformatting the file does NOT break the seal",
                 (lambda: (mp.value["absolute"].write_bytes(
                     (json.dumps(json.loads(mp.value["absolute"].read_text("utf-8")),
                                 indent=8, sort_keys=False) + "\n").encode("utf-8")),
                     load_operation_manifest(mp.value["absolute"]))[1])())
        s.reject(ctl, "tampered manifest fails the seal",
                 (lambda: (mp.value["absolute"].write_bytes(
                     json.dumps(dict(json.loads(mp.value["absolute"].read_text("utf-8")),
                                     operation_id="op_SWAPPED")).encode("utf-8")),
                     load_operation_manifest(mp.value["absolute"]))[1])(),
                 code=C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING,
                 reason="manifest_digest_mismatch")
        s.reject(ctl, "absent manifest is WF1127",
                 load_operation_manifest(root / "nope" / "operation_manifest.json"),
                 code=C.SCENE_SURVEY_OPERATION_MANIFEST_MISSING, reason="manifest_absent")
        s.reject(ctl, "unsafe output_location refuses the whole build",
                 build_operation_manifest(
                     root, _fake_request(output_location="C:/evil"),
                     raw_evidence=[], derived_report={"path": rel + "/scene_survey_report.json"}),
                 code=C.SCENE_SURVEY_OUTPUT_LOCATION_UNSAFE)
        s.reject(ctl, "missing evidence file refuses the build",
                 build_operation_manifest(
                     root, base_req, raw_evidence=[{"path": rel + "/never_written.json"}],
                     derived_report={"path": rel + "/scene_survey_report.json"}),
                 code=C.SCENE_SURVEY_EVIDENCE_RAW_MISSING, reason="evidence_absent")
        s.reject(ctl, "no derived report refuses the build",
                 build_operation_manifest(root, base_req, raw_evidence=[], derived_report=None),
                 code=C.SCENE_SURVEY_EVIDENCE_MISSING, reason="no_derived_report")
        s.reject(ctl, "unknown evidence role refuses",
                 build_operation_manifest(
                     root, base_req,
                     raw_evidence=[{"path": rel + "/far_side_run1.json", "role": "made_up"}],
                     derived_report={"path": rel + "/scene_survey_report.json"}),
                 reason="unknown_evidence_role")
        s.reject(ctl, "request with no operation_id refuses the build",
                 build_operation_manifest(
                     root, _fake_request(operation_id=""), raw_evidence=[],
                     derived_report={"path": rel + "/scene_survey_report.json"}),
                 code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH, reason="no_operation_id")

        # ---------------------------------------------------------------- #
        # CONTROL 6 — replay / staleness
        # ---------------------------------------------------------------- #
        ctl = "6-replay-detection"
        s.accept(ctl, "the operation's own request verifies",
                 verify_operation_evidence(root, m.value, base_req))
        s.accept(ctl, "still verifies within max_age",
                 verify_operation_evidence(root, m.value, base_req, max_age_seconds=3600))
        s.reject(ctl, "SAME question, NEW operation id -> replay caught",
                 verify_operation_evidence(root, m.value,
                                           _fake_request(operation_id="op_v2_6_scene_survey_0002")),
                 code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH, reason="operation_id_mismatch")
        s.reject(ctl, "SAME id, DIFFERENT map -> stale evidence caught",
                 verify_operation_evidence(root, m.value,
                                           _fake_request(target_map="/Game/Other/Lvl")),
                 code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH, reason="request_hash_mismatch")
        s.reject(ctl, "SAME id, DIFFERENT target commit -> stale evidence caught",
                 verify_operation_evidence(root, m.value, _fake_request(target_commit="9" * 40)),
                 code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH, reason="request_hash_mismatch")
        s.reject(ctl, "SAME id, DIFFERENT subject -> stale evidence caught",
                 verify_operation_evidence(root, m.value, _fake_request(subject=dict(
                     base_req["subject"], subject_id="subject_fixture_beta"))),
                 code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH, reason="request_hash_mismatch")
        s.reject(ctl, "SAME id, DIFFERENT plugin source hash -> stale evidence caught",
                 verify_operation_evidence(root, m.value, _fake_request(
                     required_plugin_source_hash="sha256:" + "ef" * 32)),
                 code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH, reason="request_hash_mismatch")
        s.accept(ctl, "EXCLUDED output_location change still verifies (by design)",
                 verify_operation_evidence(root, m.value,
                                           _fake_request(output_location="procedural/elsewhere")))
        s.reject(ctl, "raw evidence mutated on disk -> caught",
                 (lambda: ((ev_dir / "far_side_run2.json").write_bytes(b'{"run":"TAMPERED"}\n'),
                           verify_operation_evidence(root, m.value, base_req))[1])(),
                 code=C.SCENE_SURVEY_EVIDENCE_RAW_MISSING, reason="evidence_digest_mismatch")
        (ev_dir / "far_side_run2.json").write_bytes(b'{"run":2}\n')
        s.reject(ctl, "raw evidence deleted -> caught",
                 (lambda: (os.unlink(str(ev_dir / "far_side_run1.json")),
                           verify_operation_evidence(root, m.value, base_req))[1])(),
                 code=C.SCENE_SURVEY_EVIDENCE_RAW_MISSING, reason="evidence_absent")
        (ev_dir / "far_side_run1.json").write_bytes(b'{"run":1}\n')
        s.reject(ctl, "derived report swapped -> caught",
                 (lambda: ((ev_dir / "scene_survey_report.json").write_bytes(
                     b'{"status":"ok","faked":true}\n'),
                     verify_operation_evidence(root, m.value, base_req))[1])(),
                 code=C.SCENE_SURVEY_REPORT_INTEGRITY_FAILED, reason="evidence_digest_mismatch")
        (ev_dir / "scene_survey_report.json").write_bytes(b'{"status":"ok"}\n')
        s.reject(ctl, "manifest older than max_age -> caught",
                 verify_operation_evidence(root, dict(
                     m.value, created_at_utc=_iso(time.time() - 99999),
                     manifest_digest=compute_manifest_digest(dict(
                         m.value, created_at_utc=_iso(time.time() - 99999))).value),
                     base_req, max_age_seconds=60),
                 code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH, reason="manifest_too_old")
        s.reject(ctl, "manifest hashed under a different field-set version -> caught",
                 verify_operation_evidence(root, (lambda mm: dict(
                     mm, manifest_digest=compute_manifest_digest(mm).value))(
                     dict(m.value, request_hash_field_set_version=999)), base_req),
                 code=C.SCENE_SURVEY_OPERATION_ID_MISMATCH, reason="field_set_version_mismatch")
        s.accept(ctl, "final state re-verifies clean (not stuck failing)",
                 verify_operation_evidence(root, m.value, base_req))

        bad = s.report()
        if bad:
            print("\nRESULT: FAIL — {} control(s) failed or were one-sided.".format(bad))
            return 1
        print("\nRESULT: PASS — every control accepted a legitimate case AND refused a "
              "hostile one.")
        print("NOTE: this proves the LIBRARY. Nothing is wired into the probe or the "
              "runtime gate by this lane.")
        return 0
    finally:
        for d in (root, outside, Path(str(root) + "-evil")):
            shutil.rmtree(str(d), ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(_main())
    except Exception as exc:  # noqa: BLE001 - the self-test itself must fail closed
        import traceback

        traceback.print_exc()
        print("RESULT: FAIL — self-test raised {}: {}".format(type(exc).__name__, exc))
        sys.exit(1)
