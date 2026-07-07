#!/usr/bin/env python3
"""quarantine.py — WorldForge v1.5 first-class quarantine gate (library + CLI).

Quarantine is the MANDATORY waystation: incoming acquired bytes land in a
quarantine data root and earn a validated ``QuarantineAssetRecord`` BEFORE any
asset is ever allowed near a final/owned path. Nothing may skip this stage.

``quarantine_asset(source, candidate, adapter)`` copies the incoming bytes into a
``QUARANTINE_DATA_ROOTS`` location, asserts the result is genuinely under a
quarantine root (else ASSET_QUARANTINE_BYPASS), computes a content sha256 plus a
per-file manifest, resolves the ownership class via ``mesh_contract`` (never
reimplemented here), and writes a ``QuarantineAssetRecord`` validated against
``quarantine_contract`` before it touches disk.

Fail-closed by construction: an unknown source / license / ownership, or a
destination that is not under a quarantine root, refuses the operation and writes
NO record.

Run ``python quarantine.py`` for an isolated self-check (exit 0).
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import asset_paths
import mesh_contract as MC
import quarantine_contract as QC
from failure_codes import FailureCode
from provenance import build_provenance

REPO_ROOT = asset_paths.REPO_ROOT

# License family -> ownership class mapping used when a candidate does not carry
# explicit ownership flags. Owned families resolve to an owned class; external
# licensed families resolve to third_party_owned. Unknown -> refuse (fail-closed).
_OWNED_LICENSE_FAMILIES = {
    "generated_owned": MC.OWNERSHIP_GENERATED,
    "project_owned": MC.OWNERSHIP_PROJECT,
    "internal_project_license": MC.OWNERSHIP_PROJECT,
}
_THIRD_PARTY_LICENSE_FAMILIES = {
    "cc0", "fab_standard", "fab_professional",
    "fab_standard_license", "fab_professional_license",
}


class QuarantineError(RuntimeError):
    """Raised when an asset cannot be safely quarantined. Carries a failure code."""

    def __init__(self, code, detail):
        super().__init__("{}: {}".format(code, detail))
        self.code = code
        self.detail = detail


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _anchor_relative(path):
    """Return ``path`` sliced from the first quarantine anchor onward (posix)."""
    s = str(path).replace("\\", "/")
    for anchor in asset_paths.QUARANTINE_ROOT_ANCHORS:
        idx = s.find(anchor)
        if idx != -1:
            return s[idx:]
    return s


def _resolve_ownership(candidate):
    """Resolve ownership for a candidate. Prefers explicit flags/class (delegated
    to mesh_contract), else derives from license_family. None => ambiguous."""
    resolved = MC.resolve_ownership_class(candidate)
    if resolved is not None:
        return resolved
    lf = (candidate or {}).get("license_family")
    if lf in _OWNED_LICENSE_FAMILIES:
        return _OWNED_LICENSE_FAMILIES[lf]
    if lf in _THIRD_PARTY_LICENSE_FAMILIES:
        return MC.OWNERSHIP_THIRD_PARTY
    return None


def _pick_quarantine_root(quarantine_root):
    if quarantine_root is not None:
        return Path(quarantine_root)
    # Prefer the in-repo Content quarantine root (portable, always creatable).
    return asset_paths.QUARANTINE_DATA_ROOTS[1]


def quarantine_asset(source_path_or_url, candidate, adapter, *,
                     quarantine_root=None, records_dir=None, strict=True):
    """Move/copy incoming bytes into quarantine and write a validated record.

    Returns the written ``QuarantineAssetRecord`` dict. Raises ``QuarantineError``
    (fail-closed, no record written) on any unsafe condition.
    """
    candidate = candidate or {}
    candidate_id = candidate.get("candidate_id")
    if not candidate_id:
        raise QuarantineError(FailureCode.ASSET_QUARANTINE_FAILURE,
                              "candidate has no candidate_id")
    if not adapter:
        raise QuarantineError(FailureCode.ASSET_SOURCE_ADAPTER_FAILURE,
                              "no source adapter supplied")

    # -- resolve incoming local bytes (fail-closed: we must actually have them) --
    src = None
    if source_path_or_url:
        p = Path(str(source_path_or_url))
        if p.exists():
            src = p
    if src is None:
        # A bare URL we cannot fetch offline is not quarantinable bytes.
        raise QuarantineError(
            FailureCode.ASSET_QUARANTINE_FAILURE,
            "no local incoming bytes for source {!r} (a URL must be fetched to a "
            "local cache before quarantine)".format(source_path_or_url))

    # -- resolve ownership BEFORE copying (refuse unknown ownership) -------------
    ownership = _resolve_ownership(candidate)
    if ownership is None:
        raise QuarantineError(
            FailureCode.ASSET_OWNERSHIP_FAILURE,
            "ownership unresolvable for candidate {} (license_family={!r})".format(
                candidate_id, candidate.get("license_family")))
    if not candidate.get("license_family"):
        raise QuarantineError(FailureCode.ASSET_LICENSE_MISSING,
                              "candidate {} has no license_family".format(candidate_id))

    # -- copy bytes into a quarantine destination --------------------------------
    root = _pick_quarantine_root(quarantine_root)
    dest = root / candidate_id
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
    if src.is_dir():
        shutil.copytree(src, dest)
    else:
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / src.name)

    # -- MANDATORY: the destination must be under a quarantine root --------------
    if not asset_paths.under_quarantine_root(dest) or \
            not QC.is_under_quarantine_root(_anchor_relative(dest)):
        shutil.rmtree(dest, ignore_errors=True)
        raise QuarantineError(
            FailureCode.ASSET_QUARANTINE_BYPASS,
            "quarantine destination {} is not under a quarantine root".format(dest))
    if MC.is_allowed_final_path(_anchor_relative(dest)):
        shutil.rmtree(dest, ignore_errors=True)
        raise QuarantineError(
            FailureCode.ASSET_QUARANTINE_BYPASS,
            "quarantine destination resolved to a final owned path — bypass")

    # -- content hash + per-file manifest ----------------------------------------
    manifest = {}
    hasher = hashlib.sha256()
    for f in sorted(dest.rglob("*")):
        if f.is_file():
            rel = f.relative_to(dest).as_posix()
            digest = _sha256_file(f)
            manifest[rel] = digest
            hasher.update(rel.encode("utf-8"))
            hasher.update(digest.encode("utf-8"))
    if not manifest:
        shutil.rmtree(dest, ignore_errors=True)
        raise QuarantineError(FailureCode.ASSET_HASH_MISSING,
                              "no files quarantined (empty manifest)")
    content_sha256 = hasher.hexdigest()

    now = datetime.now(timezone.utc).isoformat()
    local_path = _anchor_relative(dest)
    record = {
        "quarantine_id": "q_" + candidate_id,
        "candidate_id": candidate_id,
        "source_adapter": adapter,
        "source_url_or_path": candidate.get("source_url") or candidate.get(
            "source_path") or str(source_path_or_url),
        "local_quarantine_path": local_path,
        "file_manifest": manifest,
        "hashes": {"content_sha256": content_sha256,
                   "source_hash": candidate.get("hash_expected") or ""},
        "license_family": candidate.get("license_family"),
        "ownership_class": ownership,
        "external_licensed": ownership == MC.OWNERSHIP_THIRD_PARTY,
        "generated_owned": ownership == MC.OWNERSHIP_GENERATED,
        "third_party_owned": ownership == MC.OWNERSHIP_THIRD_PARTY,
        "human_owned": ownership == MC.OWNERSHIP_HUMAN,
        "project_owned": ownership == MC.OWNERSHIP_PROJECT,
        "publisher": candidate.get("publisher") or "",
        "author": candidate.get("author") or "",
        "import_intent": candidate.get("asset_type") or "unspecified",
        "ue_import_target": "",
        "validation_status": "pending",
        "validation_errors": [],
        "created_at": now,
        "quarantined_at": now,
        "schema_version": QC.SCHEMA_VERSION,
        "provenance": build_provenance(
            REPO_ROOT, [f for f in dest.rglob("*") if f.is_file()],
            "quarantine.py", "v1.5") if str(dest).startswith(str(REPO_ROOT)) else {
                "generator_name": "quarantine.py", "generator_version": "v1.5",
                "generated_at_utc": now},
    }

    # -- validate BEFORE writing; refuse (and clean up) on any failure -----------
    failing = [c for c in QC.validate_record(record, strict=strict) if not c[1]]
    if failing:
        shutil.rmtree(dest, ignore_errors=True)
        name, _ok, detail, code = failing[0]
        raise QuarantineError(code, "record invalid ({}): {}".format(name, detail))

    rec_dir = Path(records_dir) if records_dir else asset_paths.QUARANTINE_RECORDS_DIR
    rec_dir.mkdir(parents=True, exist_ok=True)
    out = rec_dir / (record["quarantine_id"] + ".json")
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return record


def _self_check():
    """Isolated positive + negative self-check that never pollutes the repo."""
    tmp = Path(tempfile.mkdtemp(prefix="wf_quarantine_selftest_"))
    try:
        # Fabricate incoming bytes.
        src = tmp / "incoming"
        src.mkdir()
        (src / "rock_01.fbx").write_bytes(b"FBX-BYTES-selftest")
        (src / "rock_01_bc.png").write_bytes(b"PNG-BYTES-selftest")
        # A synthetic quarantine root whose path carries the anchor substring so
        # under_quarantine_root() is genuinely satisfied without touching the repo.
        qroot = tmp / "WorldForgeAssetCache" / "_Quarantine"
        qroot.mkdir(parents=True)
        recs = tmp / "records"

        candidate = {
            "candidate_id": "cand_selftest_rock",
            "source_url": "https://fab.com/listings/selftest",
            "license_family": "fab_standard",
            "publisher": "SelftestVendor",
            "author": "SelftestVendor",
            "asset_type": "3d_mesh",
            "hash_expected": "sha256:feedface",
        }
        rec = quarantine_asset(str(src), candidate, "manual_fab_acquisition",
                               quarantine_root=qroot, records_dir=recs, strict=True)
        assert rec["ownership_class"] == MC.OWNERSHIP_THIRD_PARTY, rec["ownership_class"]
        assert rec["hashes"]["content_sha256"], "missing content hash"
        assert len(rec["file_manifest"]) == 2, rec["file_manifest"]
        assert QC.is_under_quarantine_root(rec["local_quarantine_path"])
        failing = [c for c in QC.validate_record(rec, strict=True) if not c[1]]
        assert not failing, failing

        # Negative: unknown license -> ownership unresolvable -> refuse, no record.
        bad = dict(candidate, candidate_id="cand_selftest_bad", license_family="mystery")
        try:
            quarantine_asset(str(src), bad, "manual_fab_acquisition",
                             quarantine_root=qroot, records_dir=recs, strict=True)
            raise AssertionError("expected refusal for unknown license/ownership")
        except QuarantineError as exc:
            assert exc.code in (FailureCode.ASSET_OWNERSHIP_FAILURE,
                                FailureCode.ASSET_LICENSE_MISSING), exc.code

        # Negative: destination not under a quarantine root -> bypass refusal.
        try:
            quarantine_asset(str(src), dict(candidate, candidate_id="cand_selftest_bypass"),
                             "manual_fab_acquisition",
                             quarantine_root=(tmp / "NotQuarantine"),
                             records_dir=recs, strict=True)
            raise AssertionError("expected ASSET_QUARANTINE_BYPASS for non-quarantine root")
        except QuarantineError as exc:
            assert exc.code == FailureCode.ASSET_QUARANTINE_BYPASS, exc.code

        print("OK quarantine self-check: positive record valid; unknown-license and "
              "quarantine-bypass both refused (fail-closed).")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge v1.5 quarantine gate.")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--source", help="local path to incoming bytes")
    ap.add_argument("--candidate-json", help="path to a candidate record JSON")
    ap.add_argument("--adapter", default="manual_acquisition")
    args = ap.parse_args(argv)
    if args.strict:
        os.environ["STRICT"] = "1"

    if not args.source or not args.candidate_json:
        # Default invocation is the isolated self-check.
        return _self_check()

    candidate = json.loads(Path(args.candidate_json).read_text(encoding="utf-8"))
    try:
        rec = quarantine_asset(args.source, candidate, args.adapter, strict=True)
    except QuarantineError as exc:
        sys.stderr.write("REFUSED {}\n".format(exc))
        return 1
    print("quarantined -> {} ({})".format(rec["quarantine_id"],
                                           rec["local_quarantine_path"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
