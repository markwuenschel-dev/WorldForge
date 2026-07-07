#!/usr/bin/env python3
"""asset_source_adapters.py — WorldForge v1.5 Wave-2 concrete source adapters.

Each adapter binds ONE real source behind the fail-closed ``SourceAdapter``
interface. Ownership and license are decided at the source, not downstream, and
every acquired byte lands in a quarantine root FIRST.

Adapters:
  * LocalFabMegascansCacheAdapter — read-only scan of the LIVE Fab/Megascans
    cache (never delete/mutate/move a cache file); third_party_owned, fab license.
  * PolyHavenDirectDownloadAdapter — LIVE CC0 download via urllib against
    api.polyhaven.com; degrades honestly (no fabricated hash) when offline.
  * ManualFabAcquisitionAdapter — search only; refuses automated download.
  * QuarantineFolderAdapter — inspects hand-dropped files; fail-closed reject.
  * Houdini/Internal/ExistingProject stubs — policy-correct ownership only.

Stdlib + PyYAML pipeline only. Network via urllib (no requests).
"""

import shutil
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import asset_config
import mesh_contract as MC
import scan_external_asset_library as SEAL
from failure_codes import FailureCode
from source_adapter_base import (
    SourceAdapter,
    SourcePolicy,
    anchored_quarantine_path,
    assert_under_quarantine_root,
    build_candidate,
    build_quarantine_record,
    http_download,
    http_get_json,
    make_refusal,
    quarantine_data_root,
    sha256_file,
    validate_candidate,
    validate_quarantine_record,
)
from asset_paths import QUARANTINE_DATA_ROOTS, ensure, under_quarantine_root


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# SEAL asset_type bucket -> AssetNeed/candidate asset_type vocabulary.
_ASSET_TYPE_MAP = {
    "rock": "3d_mesh",
    "debris": "3d_mesh",
    "vegetation": "3d_mesh",
    "surface": "material",
    "decal": "decal",
}
# Usage intent -> which SEAL asset_type buckets satisfy it.
_USAGE_TYPES = {
    "cover": ("rock", "debris"),
    "dressing": ("debris", "vegetation", "decal", "surface"),
}


def _usage_of(seal_type):
    if seal_type in ("rock", "debris"):
        return "cover"
    return "dressing"


# ===========================================================================
# 1. Local Fab/Megascans cache (LIVE, read-only)
# ===========================================================================
class LocalFabMegascansCacheAdapter(SourceAdapter):
    """Scan the live Fab/Megascans VaultCache. READ-ONLY: never delete, mutate,
    or move a cache file. Quarantine COPIES a representative file — the original
    is never relocated."""

    POLICY = SourcePolicy(
        adapter_name="local_fab_megascans_cache",
        ownership_class=MC.OWNERSHIP_THIRD_PARTY,
        free_ok=True,
        paid_ok=False,
        download_automation_allowed=False,   # local reference; nothing is downloaded
        manual_only=False,                    # scanning a local cache is automatic
        may_delete_source=False,              # LOAD-BEARING: cache is never deleted
        may_mutate_source=False,
        network=False,
        license_families=("fab_standard",),
        default_license_family="fab_standard",
        default_price_class="free",
        notes="Read-only third-party cache scan; quarantine copies, never moves.",
    )

    def __init__(self, lib_id="megascans"):
        self.lib_id = lib_id
        self.lib_block = asset_config.external_library(lib_id)
        self.root = asset_config.library_root(lib_id)

    # -- discovery -----------------------------------------------------------
    def _iter_asset_dirs(self):
        if self.root is None:
            return
        for d in sorted(p for p in self.root.iterdir() if p.is_dir()):
            yield d

    def _candidate_for(self, asset_dir, need_id=None, status="found"):
        record = SEAL.build_external_record(asset_dir, self.lib_block, self.root)
        seal_type = record["asset_type"]
        content_hash = SEAL.content_sha256(asset_dir) or ""
        usage = _usage_of(seal_type)
        rel_path = asset_dir.name
        cid = self._candidate_id(record["external_asset_id"], content_hash)
        biomes = record.get("biome_compatibility") or []
        cand = build_candidate(
            candidate_id=cid,
            asset_need_id=need_id or "need_local_cache_{}".format(usage),
            source_adapter=self.name,
            source_type="megascans_library",
            source_url="",
            source_path=rel_path,
            display_name=record["asset_name"],
            publisher="Quixel Megascans (Fab)",
            author="Quixel",
            license_family="fab_standard",
            license_url="https://www.fab.com/eula",
            license_text_snapshot_path="",
            price_class="free",           # already in cache; no purchase to use it
            eula_required=False,          # EULA already accepted to hold the cache
            manual_acquisition_required=False,
            download_automation_allowed=False,
            hash_expected=content_hash,
            file_type="gltf",
            asset_type=_ASSET_TYPE_MAP.get(seal_type, "3d_mesh"),
            quality_score=0.85,
            fit_score=0.7,
            risk_score=0.1,
            candidate_status=status,
            rejection_reason="",
            tags=list(biomes) + [seal_type, usage],
            provenance={
                "library_root_alias": asset_config.library_root_alias(self.lib_id),
                "source_path_hash": record["source_path_hash"],
                "source_content_hash": content_hash,
                "external_asset_id": record["external_asset_id"],
            },
        )
        return cand

    def scan_local(self):
        out = []
        for d in self._iter_asset_dirs():
            out.append(self._candidate_for(d, status="found"))
        return out

    def detect_new(self, since=None):
        """Return candidates for assets modified after ``since`` (epoch secs)."""
        out = []
        for d in self._iter_asset_dirs():
            try:
                mtime = d.stat().st_mtime
            except OSError:
                continue
            if since is None or mtime > float(since):
                out.append(self._candidate_for(d, status="found"))
        return out

    def search(self, needs):
        """Rank cache candidates against needs (cover/dressing intent)."""
        needs = needs or []
        cands = []
        for d in self._iter_asset_dirs():
            base = self._candidate_for(d, status="ranked")
            cands.append((d, base))
        if not needs:
            return [c for _, c in cands]
        results = []
        for need in needs:
            usages = set(_norm_usages(need))
            want_types = set()
            for u in usages:
                want_types |= set(_USAGE_TYPES.get(u, ()))
            for _, c in cands:
                ctags = set(c.get("tags") or [])
                if not want_types or (want_types & ctags):
                    ranked = dict(c)
                    ranked["asset_need_id"] = need.get("asset_need_id", c["asset_need_id"])
                    results.append(ranked)
        return results or [c for _, c in cands]

    # -- acquisition (COPY-only quarantine) ----------------------------------
    def quarantine(self, path_or_url, candidate):
        root = self.root
        src = Path(path_or_url)
        if not src.is_absolute() and root is not None:
            src = root / path_or_url
        if not src.is_dir():
            return make_refusal(self.name, FailureCode.ASSET_QUARANTINE_FAILURE,
                                "source asset dir not found: {}".format(src), candidate)
        rep = SEAL.representative_source_file(src)
        content_hash = SEAL.content_sha256(src)
        if rep is None or not content_hash:
            return make_refusal(self.name, FailureCode.ASSET_HASH_MISSING,
                                "no hashable source file under {}".format(src), candidate)
        cid = candidate.get("candidate_id", "unknown")
        dest_dir = quarantine_data_root() / "megascans" / cid
        assert_under_quarantine_root(dest_dir)
        ensure(dest_dir)
        dest_file = dest_dir / rep.name
        # COPY (never move) — the live cache file is left exactly where it is.
        shutil.copy2(str(rep), str(dest_file))
        copy_hash = sha256_file(dest_file)
        qrec = build_quarantine_record(
            quarantine_id=self._quarantine_id(cid, content_hash),
            candidate_id=cid,
            source_adapter=self.name,
            source_url_or_path=src.name,
            local_quarantine_path=anchored_quarantine_path(dest_dir),
            file_manifest=[rep.name],
            hashes={"content_sha256": content_hash, "quarantined_copy_sha256": copy_hash},
            license_family="fab_standard",
            ownership_class=MC.OWNERSHIP_THIRD_PARTY,
            external_licensed=True,
            generated_owned=False,
            third_party_owned=True,
            human_owned=False,
            project_owned=False,
            publisher="Quixel Megascans (Fab)",
            author="Quixel",
            import_intent=candidate.get("asset_need_id", "encounter_cover"),
            ue_import_target="/Game/WorldForge/ThirdParty/Meshes/",
            validation_status="pending",
            validation_errors=[],
            notes="Representative file COPIED (not moved) from live cache; original untouched.",
        )
        return qrec

    def classify(self, raw):
        return {
            "ownership_class": MC.OWNERSHIP_THIRD_PARTY,
            "third_party_owned": True,
            "generated_owned": False,
            "human_owned": False,
            "project_owned": False,
            "external_licensed": True,
            "license_family": "fab_standard",
            "decision": "accept_reference",
            "reason": "resolved third-party Fab/Megascans cache asset (read-only)",
        }


def _norm_usages(need):
    tags = []
    for k in ("usage_tags", "encounter_tags", "terrain_tags"):
        v = need.get(k)
        if isinstance(v, list):
            tags += [str(t).lower() for t in v]
    usages = set()
    for t in tags:
        if "cover" in t:
            usages.add("cover")
        if "dress" in t or "scatter" in t or "debris" in t or "veg" in t:
            usages.add("dressing")
    return usages or {"cover", "dressing"}


# ===========================================================================
# 2. Poly Haven direct CC0 download (LIVE network)
# ===========================================================================
class PolyHavenDirectDownloadAdapter(SourceAdapter):
    """LIVE CC0 downloads from api.polyhaven.com. Only CC0 is ever eligible; any
    non-CC0 / missing-license / missing-hash fails closed. Degrades honestly to
    ``requires_manual_acquisition`` (live_download=False) when the network is
    unavailable — never fabricates a hash or a phantom download."""

    POLICY = SourcePolicy(
        adapter_name="polyhaven_direct_download",
        ownership_class=MC.OWNERSHIP_THIRD_PARTY,
        free_ok=True,
        paid_ok=False,
        download_automation_allowed=True,     # CC0 only, opted in
        manual_only=False,
        may_delete_source=False,
        may_mutate_source=False,
        network=True,
        license_families=("cc0",),
        default_license_family="cc0",
        default_price_class="free",
        notes="CC0-only automated download; quarantine-first; honest offline degrade.",
    )

    # Map types worth grabbing, cheapest/most-useful first.
    _MAP_PREFERENCE = ("Diffuse", "Rough", "AO", "arm", "nor_gl", "nor_dx", "Displacement")
    # Keywords used to bias selection toward desert/arid cover+dressing needs.
    _DEFAULT_KEYWORDS = ("desert", "sand", "rock", "gravel", "ground", "cliff", "arid", "dune")

    def __init__(self):
        self.cfg = asset_config.polyhaven_config()
        self.api = self.cfg.get("api_base", "https://api.polyhaven.com")
        self.network_ok = None
        self.last_error = None

    # -- discovery -----------------------------------------------------------
    def search(self, needs, asset_kind="textures"):
        """Fetch a small CC0 candidate set. Sets self.network_ok honestly."""
        limit = int(self.cfg.get("max_assets_per_run", 3))
        keywords = self._keywords_from(needs)
        try:
            assets = http_get_json("{}/assets?t={}".format(self.api, asset_kind))
            self.network_ok = True
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.network_ok = False
            self.last_error = "{}: {}".format(type(exc).__name__, exc)
            return []

        ids = self._pick_ids(assets, keywords, limit)
        cands = []
        for aid in ids:
            meta = assets.get(aid, {})
            name = meta.get("name") or aid
            authors = meta.get("authors") or {}
            author = ", ".join(authors.keys()) if isinstance(authors, dict) else str(authors)
            cats = meta.get("categories") or []
            cand = build_candidate(
                candidate_id=self._candidate_id(aid),
                asset_need_id=self._need_for(needs, aid),
                source_adapter=self.name,
                source_type="polyhaven",
                source_url="https://polyhaven.com/a/{}".format(aid),
                source_path="",
                display_name=name,
                publisher=self.cfg.get("publisher", "Poly Haven"),
                author=author or "Poly Haven",
                license_family="cc0",
                license_url=self.cfg.get("license_url", "https://polyhaven.com/license"),
                license_text_snapshot_path="",
                price_class="free",
                eula_required=False,
                manual_acquisition_required=False,
                download_automation_allowed=True,
                hash_expected="",                 # filled only after real download
                file_type="",
                asset_type="material" if asset_kind == "textures" else "3d_mesh",
                quality_score=0.8,
                fit_score=0.75,
                risk_score=0.05,
                candidate_status="ranked",
                rejection_reason="",
                tags=[str(c) for c in cats] + ["cc0", "polyhaven"],
            )
            cands.append(cand)
        return cands

    def _keywords_from(self, needs):
        kws = set()
        for need in needs or []:
            for k in ("biome_tags", "terrain_tags", "usage_tags", "encounter_tags"):
                for t in (need.get(k) or []):
                    kws.add(str(t).lower())
        return kws or set(self._DEFAULT_KEYWORDS)

    def _pick_ids(self, assets, keywords, limit):
        scored = []
        for aid, meta in assets.items():
            hay = " ".join([aid, str(meta.get("name", ""))]
                           + [str(c) for c in (meta.get("categories") or [])]
                           + [str(t) for t in (meta.get("tags") or [])]).lower()
            score = sum(1 for k in keywords if k in hay)
            scored.append((score, aid))
        # deterministic: highest keyword score, then alphabetical id
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [aid for _, aid in scored[:max(0, limit)]]

    def _need_for(self, needs, aid):
        if needs:
            return (needs[0] or {}).get("asset_need_id", "need_polyhaven_free")
        return "need_polyhaven_free"

    # -- acquisition ---------------------------------------------------------
    def download_if_allowed(self, candidate):
        # Fail closed on license.
        lf = (candidate.get("license_family") or "").lower()
        if not lf:
            return make_refusal(self.name, FailureCode.ASSET_LICENSE_MISSING,
                                "candidate has no license_family", candidate)
        if lf != "cc0":
            return make_refusal(self.name, FailureCode.ASSET_LICENSE_UNSUPPORTED,
                                "PolyHaven adapter only downloads CC0; got {!r}".format(lf), candidate)

        aid = self._id_from_url(candidate.get("source_url", ""))
        if not aid:
            return make_refusal(self.name, FailureCode.ASSET_SOURCE_URL_MISSING,
                                "cannot resolve polyhaven id from source_url", candidate)

        try:
            files = http_get_json("{}/files/{}".format(self.api, aid))
            self.network_ok = True
            pick = self._pick_file(files)
            if pick is None:
                self.network_ok = True
                return self._degrade(candidate, "no downloadable map found in files listing")
            map_type, res, fmt, leaf = pick
            url = leaf["url"]
            fname = "{}_{}_{}.{}".format(aid, map_type, res, fmt)
            dest_dir = quarantine_data_root() / "polyhaven" / aid
            assert_under_quarantine_root(dest_dir)
            ensure(dest_dir)
            dest = dest_dir / fname
            written, sha = http_download(url, dest, timeout=90)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.network_ok = False
            self.last_error = "{}: {}".format(type(exc).__name__, exc)
            return self._degrade(candidate, "network unavailable: {}".format(self.last_error))

        # License snapshot (CC0) — real file, real path under quarantine.
        lic_path = dest_dir / "LICENSE.txt"
        lic_text = (
            "Poly Haven asset '{}'\n"
            "License: CC0 1.0 Universal (Public Domain Dedication)\n"
            "License URL: {}\n"
            "Author(s): {}\n"
            "Source: {}\n"
            "Downloaded (quarantine-first) at: {}\n"
        ).format(aid, candidate.get("license_url", "https://polyhaven.com/license"),
                 candidate.get("author", "Poly Haven"), candidate.get("source_url", ""), _now_iso())
        lic_path.write_text(lic_text, encoding="utf-8")

        qrec = build_quarantine_record(
            quarantine_id=self._quarantine_id(aid, sha),
            candidate_id=candidate.get("candidate_id", "unknown"),
            source_adapter=self.name,
            source_url_or_path=candidate.get("source_url", ""),
            local_quarantine_path=anchored_quarantine_path(dest_dir),
            file_manifest=[fname, "LICENSE.txt"],
            hashes={"content_sha256": sha, "license_snapshot_sha256": sha256_file(lic_path)},
            license_family="cc0",
            ownership_class=MC.OWNERSHIP_THIRD_PARTY,
            external_licensed=True,
            generated_owned=False,
            third_party_owned=True,
            human_owned=False,
            project_owned=False,
            publisher=candidate.get("publisher", "Poly Haven"),
            author=candidate.get("author", "Poly Haven"),
            import_intent=candidate.get("asset_need_id", "material"),
            ue_import_target="/Game/WorldForge/ThirdParty/Materials/",
            validation_status="pending",
            validation_errors=[],
            notes="CC0 download landed in quarantine first; hash computed from real bytes.",
        )
        updated = dict(candidate)
        updated["candidate_status"] = "downloaded_to_quarantine"
        updated["hash_expected"] = sha
        updated["file_type"] = fmt
        updated["source_path"] = anchored_quarantine_path(dest)
        updated["license_text_snapshot_path"] = anchored_quarantine_path(lic_path)
        return {
            "refused": False,
            "live_download": True,
            "bytes": written,
            "candidate": updated,
            "quarantine_record": qrec,
            "note": "downloaded {} ({} {} {}) — {} bytes".format(aid, map_type, res, fmt, written),
        }

    def _degrade(self, candidate, why):
        """Honest offline degrade: mark requires_manual_acquisition, NO fake hash."""
        updated = dict(candidate)
        updated["candidate_status"] = "requires_manual_acquisition"
        updated["manual_acquisition_required"] = True
        updated["download_automation_allowed"] = False
        updated["hash_expected"] = ""
        updated["notes"] = "live download unavailable — manual acquisition required. {}".format(why)
        return {
            "refused": False,
            "live_download": False,
            "bytes": 0,
            "candidate": updated,
            "quarantine_record": None,
            "note": why,
        }

    def _id_from_url(self, url):
        url = (url or "").rstrip("/")
        if "/a/" in url:
            return url.rsplit("/a/", 1)[-1]
        return ""

    def _pick_file(self, files):
        prefs_res = list(self.cfg.get("preferred_resolutions", ["1k", "2k"]))
        prefs_fmt = list(self.cfg.get("preferred_formats", ["jpg", "png"]))
        for map_type in self._MAP_PREFERENCE:
            node = files.get(map_type)
            if not isinstance(node, dict):
                continue
            res_keys = [r for r in prefs_res if r in node] or sorted(node.keys())
            for res in res_keys:
                fmt_node = node.get(res)
                if not isinstance(fmt_node, dict):
                    continue
                fmt_keys = [f for f in prefs_fmt if f in fmt_node] or list(fmt_node.keys())
                for fmt in fmt_keys:
                    leaf = fmt_node.get(fmt)
                    if isinstance(leaf, dict) and leaf.get("url"):
                        return map_type, res, fmt, leaf
        return None

    def classify(self, raw):
        return {
            "ownership_class": MC.OWNERSHIP_THIRD_PARTY,
            "third_party_owned": True,
            "generated_owned": False,
            "human_owned": False,
            "project_owned": False,
            "external_licensed": True,
            "license_family": "cc0",
            "decision": "accept_cc0",
            "reason": "Poly Haven CC0 public-domain-dedicated asset",
        }


# ===========================================================================
# 3. Manual Fab acquisition (search-only; refuses automated download)
# ===========================================================================
class ManualFabAcquisitionAdapter(SourceAdapter):
    """Surfaces Fab marketplace candidates that a human must acquire. Never logs
    in, purchases, or accepts an EULA. download_if_allowed always refuses."""

    POLICY = SourcePolicy(
        adapter_name="manual_fab_acquisition",
        ownership_class=MC.OWNERSHIP_THIRD_PARTY,
        free_ok=True,
        paid_ok=True,
        download_automation_allowed=False,    # LOAD-BEARING: never automate Fab
        manual_only=True,
        may_delete_source=False,
        may_mutate_source=False,
        network=False,
        license_families=("fab_standard", "fab_professional"),
        default_license_family="fab_standard",
        default_price_class="unknown",
        notes="Search-only; manual acquisition + EULA gate; no login/purchase.",
    )

    def search(self, needs):
        cands = []
        for need in (needs or [{}]):
            nid = need.get("asset_need_id", "need_manual_fab")
            usage = "-".join(sorted(_norm_usages(need)))
            cid = self._candidate_id(nid, usage)
            cands.append(build_candidate(
                candidate_id=cid,
                asset_need_id=nid,
                source_adapter=self.name,
                source_type="fab_marketplace",
                source_url="https://www.fab.com/search?q={}".format(usage or "asset"),
                source_path="",
                display_name="Fab marketplace candidate ({})".format(usage or "asset"),
                publisher="Fab",
                author="Various",
                license_family="fab_standard",
                license_url="https://www.fab.com/eula",
                license_text_snapshot_path="",
                price_class="unknown",
                eula_required=True,                    # forces manual gate
                manual_acquisition_required=True,
                download_automation_allowed=False,
                hash_expected="",
                file_type="",
                asset_type=need.get("asset_type", "3d_mesh"),
                quality_score=0.7,
                fit_score=0.6,
                risk_score=0.3,
                candidate_status="requires_manual_acquisition",
                rejection_reason="",
                tags=["fab", "manual", usage] if usage else ["fab", "manual"],
                notes="Requires manual purchase/download + EULA acceptance by a human.",
            ))
        return cands

    def download_if_allowed(self, candidate):
        return make_refusal(
            self.name, FailureCode.ASSET_DOWNLOAD_NOT_ALLOWED,
            "manual Fab acquisition can never be automated (no login/purchase/EULA)",
            candidate)

    def classify(self, raw):
        return {
            "ownership_class": MC.OWNERSHIP_THIRD_PARTY,
            "third_party_owned": True,
            "generated_owned": False,
            "human_owned": False,
            "project_owned": False,
            "external_licensed": True,
            "license_family": (raw or {}).get("license_family", "fab_standard"),
            "decision": "manual_acquisition_required",
            "reason": "Fab marketplace asset — human must acquire",
        }


# ===========================================================================
# 4. Quarantine folder (hand-dropped files; fail-closed classify)
# ===========================================================================
class QuarantineFolderAdapter(SourceAdapter):
    """Inspects manually-dropped files under a quarantine root. Fail-closed: a
    drop with no trustworthy provenance/license sidecar is REJECTED."""

    POLICY = SourcePolicy(
        adapter_name="quarantine_folder",
        ownership_class=MC.OWNERSHIP_THIRD_PARTY,
        free_ok=False,
        paid_ok=False,
        download_automation_allowed=False,
        manual_only=True,
        may_delete_source=False,
        may_mutate_source=False,
        network=False,
        license_families=(),
        default_license_family="unknown",
        default_price_class="unknown",
        notes="Fail-closed: unknown source/license is rejected, never accepted.",
    )

    _KNOWN_LICENSES = ("cc0", "fab_standard", "fab_professional")

    def __init__(self, roots=None):
        self.roots = [Path(r) for r in (roots or QUARANTINE_DATA_ROOTS)]

    def scan_local(self):
        cands = []
        for root in self.roots:
            if not root.is_dir():
                continue
            for entry in sorted(p for p in root.iterdir() if p.is_dir() or p.is_file()):
                cands.append(self._candidate_for(entry))
        return cands

    def _sidecar_license(self, entry):
        d = entry if entry.is_dir() else entry.parent
        for name in ("provenance.json", "PROVENANCE.json", "license.json", "LICENSE.json"):
            p = d / name
            if p.is_file():
                try:
                    import json
                    data = json.loads(p.read_text(encoding="utf-8"))
                    return str((data or {}).get("license_family", "")).lower()
                except Exception:
                    return ""
        return ""

    def _candidate_for(self, entry):
        decision = self.classify({"path": entry, "license_family": self._sidecar_license(entry)})
        rel = anchored_quarantine_path(entry)
        rejected = decision["decision"] == "reject"
        return build_candidate(
            candidate_id=self._candidate_id(rel),
            asset_need_id="need_quarantine_dropped",
            source_adapter=self.name,
            source_type="quarantine_drop",
            source_url="",
            source_path=rel if under_quarantine_root(entry) else str(entry).replace("\\", "/"),
            display_name=entry.name,
            publisher="",
            author="",
            license_family=decision.get("license_family", "unknown") or "unknown",
            license_url="",
            license_text_snapshot_path="",
            price_class="unknown",
            eula_required=False,
            manual_acquisition_required=True,     # never auto-trust a drop
            download_automation_allowed=False,
            hash_expected="",
            file_type=entry.suffix.lstrip(".") if entry.is_file() else "",
            asset_type="3d_mesh",
            quality_score=0.0 if rejected else 0.5,
            fit_score=0.0 if rejected else 0.5,
            risk_score=1.0 if rejected else 0.4,
            candidate_status="rejected" if rejected else "found",
            rejection_reason=decision["reason"] if rejected else "",
            tags=["quarantine_drop"],
        )

    def classify(self, raw):
        lf = str((raw or {}).get("license_family", "")).lower()
        if lf in self._KNOWN_LICENSES:
            return {
                "ownership_class": MC.OWNERSHIP_THIRD_PARTY,
                "third_party_owned": True,
                "generated_owned": False,
                "human_owned": False,
                "project_owned": False,
                "external_licensed": True,
                "license_family": lf,
                "decision": "accept_pending_review",
                "reason": "drop carries a known license sidecar ({})".format(lf),
            }
        return {
            "ownership_class": None,
            "third_party_owned": False,
            "generated_owned": False,
            "human_owned": False,
            "project_owned": False,
            "external_licensed": False,
            "license_family": "unknown",
            "decision": "reject",
            "reason": "unknown source/license on manual drop — fail closed",
        }


# ===========================================================================
# 5. Policy-correct stubs (ownership + policy only)
# ===========================================================================
class HoudiniGeneratedAssetAdapter(SourceAdapter):
    """Stub: Houdini is a GENERATED backend. The baked output is generated_owned,
    but the source HDA is NOT assumed owned/deletable."""

    POLICY = SourcePolicy(
        adapter_name="houdini_generated_asset",
        ownership_class=MC.OWNERSHIP_GENERATED,
        free_ok=True, paid_ok=False,
        download_automation_allowed=False, manual_only=False,
        may_delete_source=False, may_mutate_source=False, network=False,
        default_license_family="generated_internal", default_price_class="free",
        notes="Generated output is owned; source HDA is not deletable by lifecycle.",
    )

    def classify(self, raw):
        return _generated_classify(MC.OWNERSHIP_GENERATED, "houdini baked output")


class InternalGeneratedAssetAdapter(SourceAdapter):
    """Stub: WorldForge internal recipe output — generated_owned."""

    POLICY = SourcePolicy(
        adapter_name="internal_generated_asset",
        ownership_class=MC.OWNERSHIP_GENERATED,
        free_ok=True, paid_ok=False,
        download_automation_allowed=False, manual_only=False,
        may_delete_source=False, may_mutate_source=False, network=False,
        default_license_family="generated_internal", default_price_class="free",
        notes="Internal generator output; owned, no external acquisition.",
    )

    def classify(self, raw):
        return _generated_classify(MC.OWNERSHIP_GENERATED, "internal recipe output")


class ExistingProjectAssetAdapter(SourceAdapter):
    """Stub: assets already committed in the project — project_owned, protected."""

    POLICY = SourcePolicy(
        adapter_name="existing_project_asset",
        ownership_class=MC.OWNERSHIP_PROJECT,
        free_ok=True, paid_ok=False,
        download_automation_allowed=False, manual_only=False,
        may_delete_source=False, may_mutate_source=False, network=False,
        default_license_family="project_internal", default_price_class="free",
        notes="Committed project asset; lifecycle-protected, no acquisition.",
    )

    def classify(self, raw):
        return _generated_classify(MC.OWNERSHIP_PROJECT, "committed project asset")


def _generated_classify(ownership_class, reason):
    return {
        "ownership_class": ownership_class,
        "third_party_owned": False,
        "generated_owned": ownership_class == MC.OWNERSHIP_GENERATED,
        "human_owned": False,
        "project_owned": ownership_class == MC.OWNERSHIP_PROJECT,
        "external_licensed": False,
        "license_family": "internal",
        "decision": "accept_owned",
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
ADAPTER_CLASSES = (
    LocalFabMegascansCacheAdapter,
    PolyHavenDirectDownloadAdapter,
    ManualFabAcquisitionAdapter,
    QuarantineFolderAdapter,
    HoudiniGeneratedAssetAdapter,
    InternalGeneratedAssetAdapter,
    ExistingProjectAssetAdapter,
)

ADAPTER_BY_NAME = {cls.POLICY.adapter_name: cls for cls in ADAPTER_CLASSES}
# Human-facing source ids used by the driver CLIs.
SOURCE_ALIASES = {
    "megascans": LocalFabMegascansCacheAdapter,
    "local_fab_megascans_cache": LocalFabMegascansCacheAdapter,
    "polyhaven": PolyHavenDirectDownloadAdapter,
    "polyhaven_direct_download": PolyHavenDirectDownloadAdapter,
    "manual_fab": ManualFabAcquisitionAdapter,
    "manual_fab_acquisition": ManualFabAcquisitionAdapter,
    "quarantine_folder": QuarantineFolderAdapter,
}


def get_adapter(source_id):
    cls = SOURCE_ALIASES.get(source_id) or ADAPTER_BY_NAME.get(source_id)
    if cls is None:
        raise KeyError("unknown source adapter: {!r}".format(source_id))
    return cls()


if __name__ == "__main__":
    import sys

    # Policy sanity: every adapter that touches an external/human source must
    # never permit source deletion; download automation is opt-in and CC0/local.
    for cls in ADAPTER_CLASSES:
        pol = cls.POLICY
        assert pol.may_delete_source is False, pol.adapter_name
        assert pol.may_mutate_source is False, pol.adapter_name
    # PolyHaven refuses non-CC0.
    ph = PolyHavenDirectDownloadAdapter()
    ref = ph.download_if_allowed({"candidate_id": "x", "license_family": "royalty_free",
                                  "source_url": "https://polyhaven.com/a/x"})
    assert ref.get("refused") and ref["failure_code"] == FailureCode.ASSET_LICENSE_UNSUPPORTED
    # ManualFab refuses automation.
    mf = ManualFabAcquisitionAdapter()
    r2 = mf.download_if_allowed({"candidate_id": "y"})
    assert r2.get("refused") and r2["failure_code"] == FailureCode.ASSET_DOWNLOAD_NOT_ALLOWED
    # QuarantineFolder fail-closed on unknown.
    qf = QuarantineFolderAdapter()
    assert qf.classify({"license_family": "mystery"})["decision"] == "reject"
    # Every search candidate is schema-clean.
    for cand in mf.search([{}]):
        ok, failing = validate_candidate(cand, strict=True)
        assert ok, failing
    sys.stdout.write("asset_source_adapters self-check OK ({} adapters)\n".format(len(ADAPTER_CLASSES)))
