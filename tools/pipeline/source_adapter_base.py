#!/usr/bin/env python3
"""source_adapter_base.py — WorldForge v1.5 Wave-2 asset source-adapter base.

An AssetAcquisitionForge *source adapter* is the ONLY thing allowed to reach a
concrete asset source (a local third-party cache, a CC0 download API, a manual
marketplace, a hand-dropped quarantine folder). Every adapter answers the same
seven questions the acquisition pipeline asks — search / download / scan / detect
/ quarantine / classify / policy — behind one abstract interface so the driver
scripts (scan_local_asset_cache, acquire_free_assets) and the policy gate
(validate_source_adapters) never special-case a source.

The load-bearing safety rule of this layer is FAIL CLOSED. The base class:

  * refuses downloads by default (an adapter must *opt in* to automation),
  * never deletes/mutates/moves a source (``may_delete_source`` defaults False),
  * classifies unknown provenance as ``rejected`` (never as owned/free),
  * lands every acquired byte in a quarantine root FIRST and asserts it,
  * emits only AssetCandidate records that pass
    ``asset_candidate_contract.validate_record(strict=True)``.

Stdlib only. No adapter here may import ``requests`` — network adapters use
``urllib`` (see ``http_get_json`` / ``http_download``).
"""

import hashlib
import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import asset_candidate_contract as CAND
import mesh_contract as MC
import quarantine_contract as QC
from asset_paths import (
    CANDIDATES_DIR,
    QUARANTINE_DATA_ROOTS,
    QUARANTINE_RECORDS_DIR,
    QUARANTINE_ROOT_ANCHORS,
    ensure,
    under_quarantine_root,
)
from failure_codes import FailureCode

REPO_ROOT = Path(__file__).resolve().parents[2]

ADAPTER_BASE_VERSION = "1.5.0"
_HTTP_UA = "WorldForge-AssetAcquisitionForge/1.5 (+stdlib-urllib)"


# ---------------------------------------------------------------------------
# Policy — one immutable record per adapter, fail-closed by construction.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SourcePolicy:
    """The enforceable policy envelope of a single source adapter.

    Defaults are the SAFE defaults: nothing free, nothing paid, no automated
    download, manual-only, source is never deletable, ownership is third-party
    (the most protected class). An adapter must explicitly relax each flag.
    """

    adapter_name: str
    ownership_class: str = MC.OWNERSHIP_THIRD_PARTY
    free_ok: bool = False
    paid_ok: bool = False
    download_automation_allowed: bool = False
    manual_only: bool = True
    may_delete_source: bool = False           # NEVER True for external/human sources
    may_mutate_source: bool = False
    network: bool = False
    license_families: tuple = ()
    default_license_family: str = "unknown"
    default_price_class: str = "unknown"
    notes: str = ""

    def to_dict(self):
        d = asdict(self)
        d["license_families"] = list(self.license_families)
        return d


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Quarantine path helpers — every acquired byte lands here FIRST.
# ---------------------------------------------------------------------------
def quarantine_data_root(prefer_project=False):
    """Return an absolute quarantine data root (external drive, or project tree)."""
    return QUARANTINE_DATA_ROOTS[1] if prefer_project else QUARANTINE_DATA_ROOTS[0]


def anchored_quarantine_path(abs_path):
    """Return a machine-independent, anchor-relative string for a quarantine path.

    Stores ``WorldForgeAssetCache/_Quarantine/...`` rather than an absolute
    ``D:/...`` path so the record never leaks an absolute/cache path and still
    proves it sits under a quarantine root.
    """
    s = str(abs_path).replace("\\", "/")
    for anchor in QUARANTINE_ROOT_ANCHORS:
        i = s.find(anchor)
        if i >= 0:
            return s[i:]
    return s


def assert_under_quarantine_root(path):
    """Raise unless ``path`` sits under a declared quarantine root. Fail closed."""
    if not under_quarantine_root(path):
        raise ValueError(
            "path {!r} is not under a quarantine root {}".format(path, QUARANTINE_ROOT_ANCHORS))
    return path


def sha256_file(path):
    """Return ``sha256:<hex>`` of a file's real bytes (chunked), or None."""
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def sha256_bytes(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# HTTP helpers (urllib only — no third-party network libraries permitted).
# ---------------------------------------------------------------------------
def _ssl_context():
    try:
        return ssl.create_default_context()
    except Exception:
        return None


def http_get_json(url, timeout=20):
    """GET a URL and parse JSON. Raises urllib.error.URLError on network failure."""
    req = urllib.request.Request(url, headers={"User-Agent": _HTTP_UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_download(url, dest_path, timeout=60, max_bytes=None):
    """Download ``url`` to ``dest_path`` (must be under a quarantine root).

    Returns (bytes_written, ``sha256:<hex>``). Raises on network error or if the
    destination is not under a quarantine root (fail closed — no byte lands
    outside quarantine).
    """
    assert_under_quarantine_root(dest_path)
    ensure(Path(dest_path))
    req = urllib.request.Request(url, headers={"User-Agent": _HTTP_UA})
    h = hashlib.sha256()
    written = 0
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp, \
            open(dest_path, "wb") as out:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            if max_bytes is not None and written + len(chunk) > max_bytes:
                chunk = chunk[: max_bytes - written]
                out.write(chunk)
                h.update(chunk)
                written += len(chunk)
                break
            out.write(chunk)
            h.update(chunk)
            written += len(chunk)
    return written, "sha256:" + h.hexdigest()


# ---------------------------------------------------------------------------
# Record builders — the ONLY sanctioned way to mint candidate / quarantine dicts
# so every record is schema-clean (exactly the allowed fields) by construction.
# ---------------------------------------------------------------------------
_CANDIDATE_DEFAULTS = {
    "candidate_id": "",
    "asset_need_id": "",
    "source_adapter": "",
    "source_type": "",
    "source_url": "",
    "source_path": "",
    "display_name": "",
    "publisher": "",
    "author": "",
    "license_family": "unknown",
    "license_url": "",
    "license_text_snapshot_path": "",
    "price_class": "unknown",
    "eula_required": False,
    "manual_acquisition_required": False,
    "download_automation_allowed": False,
    "hash_expected": "",
    "file_type": "",
    "asset_type": "3d_mesh",
    "quality_score": 0.0,
    "fit_score": 0.0,
    "risk_score": 0.0,
    "candidate_status": "found",
    "rejection_reason": "",
}


def build_candidate(**kw):
    """Build a schema-clean AssetCandidate dict (only allowed fields present).

    Required fields are defaulted; optional fields appear only when supplied.
    Callers should still run ``validate_candidate`` before persisting.
    """
    rec = dict(_CANDIDATE_DEFAULTS)
    for k, v in kw.items():
        if k in CAND.ALLOWED_FIELDS:
            rec[k] = v
        else:
            raise KeyError("build_candidate: field {!r} is not in the candidate schema".format(k))
    return rec


def validate_candidate(record, strict=True):
    """Return (ok, [failing (check, detail, code)]) for an AssetCandidate."""
    failing = []
    for cname, ok, detail, code in CAND.validate_record(record, strict=strict):
        if not ok:
            failing.append((cname, detail, code))
    return (not failing), failing


_QREC_DEFAULTS = {
    "quarantine_id": "",
    "candidate_id": "",
    "source_adapter": "",
    "source_url_or_path": "",
    "local_quarantine_path": "",
    "file_manifest": [],
    "hashes": {},
    "license_family": "unknown",
    "ownership_class": MC.OWNERSHIP_THIRD_PARTY,
    "external_licensed": False,
    "generated_owned": False,
    "third_party_owned": False,
    "human_owned": False,
    "project_owned": False,
    "publisher": "",
    "author": "",
    "import_intent": "",
    "ue_import_target": "",
    "validation_status": "pending",
    "validation_errors": [],
    "created_at": "",
}


def build_quarantine_record(**kw):
    """Build a schema-clean QuarantineAssetRecord dict (only allowed fields)."""
    rec = dict(_QREC_DEFAULTS)
    rec["created_at"] = _now_iso()
    for k, v in kw.items():
        if k in QC.ALLOWED_FIELDS:
            rec[k] = v
        else:
            raise KeyError("build_quarantine_record: field {!r} not in quarantine schema".format(k))
    return rec


def validate_quarantine_record(record, strict=True):
    failing = []
    for cname, ok, detail, code in QC.validate_record(record, strict=strict):
        if not ok:
            failing.append((cname, detail, code))
    return (not failing), failing


def persist_candidate(record):
    """Write an AssetCandidate to CANDIDATES_DIR/<candidate_id>.json; return path."""
    cid = record.get("candidate_id") or "candidate"
    path = CANDIDATES_DIR / "{}.json".format(cid)
    ensure(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


def persist_quarantine(record):
    """Write a QuarantineAssetRecord to QUARANTINE_RECORDS_DIR/<id>.json; return path."""
    qid = record.get("quarantine_id") or "quarantine"
    path = QUARANTINE_RECORDS_DIR / "{}.json".format(qid)
    ensure(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


def make_refusal(adapter_name, code, detail, candidate=None):
    """Structured refusal returned by download_if_allowed when policy forbids it."""
    return {
        "refused": True,
        "adapter": adapter_name,
        "failure_code": code,
        "detail": detail,
        "candidate_id": (candidate or {}).get("candidate_id") if isinstance(candidate, dict) else None,
        "at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------
class SourceAdapter:
    """Abstract base. Subclasses set ``POLICY`` and override what they support.

    The base implementations are the FAIL-CLOSED defaults:
      * search / scan_local / detect_new -> [] (nothing found)
      * download_if_allowed -> refusal (no automation unless opted in)
      * quarantine -> refusal (nothing quarantined by an adapter that has no source)
      * classify -> rejected/unknown (never owned/free)
    """

    POLICY = SourcePolicy(adapter_name="abstract_source_adapter")

    # -- identity ------------------------------------------------------------
    @property
    def name(self):
        return self.POLICY.adapter_name

    def emit_policy(self):
        """Machine-readable policy block for reports and the policy gate."""
        d = self.POLICY.to_dict()
        d["adapter_base_version"] = ADAPTER_BASE_VERSION
        return d

    # -- discovery -----------------------------------------------------------
    def search(self, needs):
        return []

    def scan_local(self):
        return []

    def detect_new(self, since=None):
        return []

    # -- acquisition ---------------------------------------------------------
    def download_if_allowed(self, candidate):
        return make_refusal(
            self.name, FailureCode.ASSET_DOWNLOAD_NOT_ALLOWED,
            "adapter {!r} does not permit automated download (fail closed)".format(self.name),
            candidate)

    def quarantine(self, path_or_url, candidate):
        return make_refusal(
            self.name, FailureCode.ASSET_QUARANTINE_FAILURE,
            "adapter {!r} cannot quarantine (no source binding)".format(self.name),
            candidate)

    # -- classification (fail closed) ---------------------------------------
    def classify(self, raw):
        """Default: unknown source -> rejected. Subclasses assert real ownership."""
        return {
            "ownership_class": None,
            "third_party_owned": False,
            "generated_owned": False,
            "human_owned": False,
            "project_owned": False,
            "external_licensed": False,
            "license_family": "unknown",
            "decision": "reject",
            "reason": "unknown source/license — fail closed",
        }

    # -- shared helpers ------------------------------------------------------
    def _candidate_id(self, *parts):
        basis = "|".join(str(p) for p in parts if p is not None)
        return "cand_{}_{}".format(self.name, hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12])

    def _quarantine_id(self, *parts):
        basis = "|".join(str(p) for p in parts if p is not None)
        return "q_{}_{}".format(self.name, hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12])


if __name__ == "__main__":
    import sys

    p = SourcePolicy(adapter_name="selfcheck", ownership_class=MC.OWNERSHIP_GENERATED)
    assert p.may_delete_source is False and p.manual_only is True
    a = SourceAdapter()
    assert a.search([]) == [] and a.scan_local() == []
    ref = a.download_if_allowed({"candidate_id": "x"})
    assert ref["refused"] and ref["failure_code"] == FailureCode.ASSET_DOWNLOAD_NOT_ALLOWED
    assert a.classify({})["decision"] == "reject"
    cand = build_candidate(
        candidate_id="cand_x", asset_need_id="need_x", source_adapter="selfcheck",
        source_type="test", source_path="WorldForgeAssetCache/_Quarantine/x",
        display_name="X", license_family="cc0", price_class="free",
        candidate_status="found")
    ok, failing = validate_candidate(cand, strict=True)
    assert ok, failing
    qp = quarantine_data_root() / "selfcheck" / "x.bin"
    assert under_quarantine_root(qp), qp
    assert anchored_quarantine_path(qp).startswith("WorldForgeAssetCache/_Quarantine")
    sys.stdout.write("source_adapter_base self-check OK\n")
