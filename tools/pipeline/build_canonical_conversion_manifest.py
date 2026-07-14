#!/usr/bin/env python3
"""build_canonical_conversion_manifest.py — v2.5.1 canonical 5.7->5.8 conversion manifest.

WHY THIS EXISTS
---------------
v2.5 shipped two manifests that could not be diffed against each other:

    pre_conversion_manifest : 179 assets (124 map + 55 non-map), keyed by repo path
    conversion_manifest     : 124 maps only, keyed by repo path

The map paths overlap perfectly, so the keyspaces were never "disjoint" — but the 55
NON-MAP assets had no post-conversion record at all. Running audit_conversion_diff on
the real pair therefore classified all 55 as ``broken_reference`` (release-blocking),
including ``Content/.gitkeep``. Nothing was broken; the post side simply never recorded
them. That is why the audit was never wired into the shield: on real data it was noise.

This module emits ONE record per package with BOTH sides populated, so a single
canonical keyspace exists and the audit can run for real.

THE CANONICAL KEY is ``package_path`` — the UE /Game path (``/Game/WorldForge/Maps/X``),
derived from the repo path. ``repo_path`` is retained for provenance. Content roots map:

    Content/<x>                        -> /Game/<x>
    Plugins/<Name>/Content/<x>         -> /<Name>/<x>       (UE plugin mount point)

EVIDENCE, NOT ASSUMPTION
------------------------
* source_hash / converted_hash — sha256 of the real bytes. Source bytes come from the
  frozen 5.7 tag (``worldforge-v2.4-ue5.7-final``), LFS-smudged; converted bytes come
  from the working tree.
* source_package_version / converted_package_version — parsed from the real .uasset
  package file summary (legacy / FileVersionUE4 / FileVersionUE5). This is what makes
  the v2.5.1 classifier honest: UE 5.7 and UE 5.8 share FileVersionUE5=1018, so a
  package resaved by 5.8 does NOT get a version bump, and calling it an
  "asset_version_upgrade" was never earned.
* actor_count — from the real UE censuses (maps only). Non-maps get None, not 0.
* component_count / critical_references — NOT extractable without a loaded UWorld.
  Emitted as None with an explicit note rather than faked. A consumer that needs them
  must run the editor; a None here must never read as "zero".

Run:
    PYTHONUTF8=1 python tools/pipeline/build_canonical_conversion_manifest.py
"""

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from build_conversion_manifest import CONTENT_ROOTS, classify as _classify  # noqa: E402
from report_meta import build_meta  # noqa: E402

SOURCE_TAG = "worldforge-v2.4-ue5.7-final"
SOURCE_ENGINE = "5.7"
TARGET_ENGINE = "5.8"

PRE_MANIFEST = REPO_ROOT / "procedural/manifests/ue5_8_conversion/pre_conversion_manifest.json"
CENSUS_57 = REPO_ROOT / "procedural/evidence/ue5_7/census_ue57_authoritative.json"
CENSUS_58 = REPO_ROOT / "procedural/evidence/ue5_8/census_ue58_postresave_houdini.json"

OUT = REPO_ROOT / "procedural/manifests/ue5_8_conversion/canonical_conversion_manifest.json"

_UASSET_MAGIC = 0x9E2A83C1


def package_path_for(repo_path):
    """Repo-relative path -> UE package path, or None for non-package files."""
    if not repo_path.endswith((".uasset", ".umap")):
        return None
    stem = repo_path.rsplit(".", 1)[0]
    if stem.startswith("Content/"):
        return "/Game/" + stem[len("Content/"):]
    parts = stem.split("/")
    if len(parts) > 3 and parts[0] == "Plugins" and parts[2] == "Content":
        return "/" + parts[1] + "/" + "/".join(parts[3:])
    return None


_ENGINE_BRANCH_RE = re.compile(rb"\+\+UE5\+Release-(\d+)\.(\d+)")


def read_package_versions(raw):
    """Parse the .uasset package file summary. Returns dict or None if not a package.

    IMPORTANT — why this reads more than the core versions:

    An earlier revision of this parser read only legacy/UE4/UE5/licensee and concluded
    "zero package-version changes across all 176 packages". That was an artifact of
    looking at too few fields. UE 5.7 and 5.8 genuinely share FileVersionUE5=1018
    (same last ObjectVersion enum), so the CORE versions never move across this
    transition — but the CUSTOM version block and the engine stamp do:

        MPC_WorldState : ++UE5+Release-5.7 -> ++UE5+Release-5.8
        M_Terrain_Master: FortniteMain 225->268, UE5-Main 121->123, UE5-Release 61->68

    Classifying on the core versions alone therefore cannot distinguish "no observable
    difference" from "written by a different engine". Both are read here so the
    classifier can tell them apart on evidence.
    """
    if raw is None or len(raw) < 24:
        return None
    tag = struct.unpack_from("<I", raw, 0)[0]
    if tag != _UASSET_MAGIC:
        return None
    legacy = struct.unpack_from("<i", raw, 4)[0]
    off = 8
    if legacy != -4:
        off += 4  # legacy UE3 version field
    try:
        ue4 = struct.unpack_from("<i", raw, off)[0]
        ue5 = struct.unpack_from("<i", raw, off + 4)[0]
        licensee = struct.unpack_from("<i", raw, off + 8)[0]
        off += 12
        # FCustomVersionContainer: int32 count, then count x {FGuid(16), int32 version}
        custom = {}
        count = struct.unpack_from("<i", raw, off)[0]
        off += 4
        if 0 <= count <= 512:  # sanity bound; a real package has tens, not thousands
            for _ in range(count):
                guid = raw[off:off + 16].hex()
                ver = struct.unpack_from("<i", raw, off + 16)[0]
                custom[guid] = ver
                off += 20
        else:
            custom = None  # unparseable -> UNKNOWN, never silently {}
    except struct.error:
        return None

    # SavedByEngineVersion's branch string sits later in the summary. Extracted by a
    # bounded search of the header region rather than a full summary walk: documented
    # heuristic, and None when not found (never guessed).
    m = _ENGINE_BRANCH_RE.search(raw[:8192])
    stamp = "{}.{}".format(m.group(1).decode(), m.group(2).decode()) if m else None

    return {"legacy": legacy, "file_version_ue4": ue4,
            "file_version_ue5": ue5, "licensee": licensee,
            "custom_versions": custom,
            "saved_by_engine_branch": stamp}


def _git_show_smudged(ref, repo_path):
    """Real bytes of repo_path at ref, LFS pointers resolved. None if absent."""
    p = subprocess.run(["git", "show", "{}:{}".format(ref, repo_path)],
                       cwd=str(REPO_ROOT), capture_output=True)
    if p.returncode != 0:
        return None
    blob = p.stdout
    if blob[:40].startswith(b"version https://git-lfs"):
        s = subprocess.run(["git", "lfs", "smudge"], cwd=str(REPO_ROOT),
                           input=blob, capture_output=True)
        if s.returncode != 0:
            return None
        blob = s.stdout
    return blob


def _sha(b):
    return hashlib.sha256(b).hexdigest() if b is not None else None


def _census_actor_counts(path):
    out = {}
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    for m in d.get("maps", []):
        out[m.get("map")] = m.get("actor_count")
    return out


def _asset_class(repo_path):
    """Asset taxonomy for a repo path, reusing build_conversion_manifest.classify()."""
    return _classify(repo_path, b"")


def _enumerate_repo_paths():
    """Union of package files at the 5.7 tag and in the working tree, under CONTENT_ROOTS.

    Deliberately does NOT read pre_conversion_manifest.json. That manifest is a stale
    artifact: commit e1b65e3c widened CONTENT_ROOTS to include
    Plugins/CoreTerrainMaterials/Content but never regenerated the output, so the
    committed file still records only 2 roots (meta.git_sha fa922a37) and omits every
    CoreTerrainMaterials package. Sourcing the package list from it silently inherited
    that hole — which is exactly how the two CoreTerrainMaterials resaves went unseen.

    Enumerating the UNION of both sides (rather than either alone) is what lets a
    deletion (source-only) or an addition (converted-only) be observed at all.
    """
    out = set()
    ls = subprocess.run(["git", "ls-tree", "-r", "--name-only", SOURCE_TAG],
                        cwd=str(REPO_ROOT), capture_output=True, text=True)
    tag_files = ls.stdout.splitlines() if ls.returncode == 0 else []
    for root in CONTENT_ROOTS:
        for f in tag_files:
            if f.startswith(root + "/"):
                out.add(f)
        live = REPO_ROOT / root
        if live.is_dir():
            for p in live.rglob("*"):
                if p.is_file():
                    out.add(p.relative_to(REPO_ROOT).as_posix())
    return sorted(out)


def build():
    a57 = _census_actor_counts(CENSUS_57)
    a58 = _census_actor_counts(CENSUS_58)

    packages, skipped = [], []
    for repo_path in _enumerate_repo_paths():
        pkg = package_path_for(repo_path)
        if pkg is None:
            # Non-package files (.gitkeep, .hda, ...) are recorded as skipped rather
            # than silently dropped OR mis-audited as broken references.
            skipped.append({"repo_path": repo_path, "reason": "not_a_ue_package"})
            continue

        src = _git_show_smudged(SOURCE_TAG, repo_path)
        dst_file = REPO_ROOT / repo_path
        dst = dst_file.read_bytes() if dst_file.is_file() else None

        sv = read_package_versions(src)
        dv = read_package_versions(dst)
        is_map = repo_path.endswith(".umap")

        packages.append({
            "package_path": pkg,
            "repo_path": repo_path,
            "asset_class": _asset_class(repo_path),
            "package_kind": "map" if is_map else "asset",
            "source_hash": _sha(src),
            "converted_hash": _sha(dst),
            "source_engine": SOURCE_ENGINE,
            "converted_engine": TARGET_ENGINE,
            "source_package_version": sv,
            "converted_package_version": dv,
            "actor_count": {"source": a57.get(pkg), "converted": a58.get(pkg)}
                           if is_map else {"source": None, "converted": None},
            # Honest nulls: no loaded UWorld here. None != zero.
            "component_count": None,
            "critical_references": None,
            "conversion_status": ("present_both" if src is not None and dst is not None
                                  else "source_only" if src is not None
                                  else "converted_only"),
            "classification": None,  # Lane 3 classifier owns this.
        })

    packages.sort(key=lambda p: p["package_path"])
    return {
        "manifest_id": "canonical_conversion_ue57_to_ue58",
        "schema_version": "wf.transition.canonical_conversion.v1",
        "report_type": "wf.transition.canonical_conversion.v1",
        "source_engine": SOURCE_ENGINE,
        "target_engine": TARGET_ENGINE,
        "source_ref": SOURCE_TAG,
        "keyspace": "package_path",
        # Root coverage is RECORDED so drift is detectable. pre_conversion_manifest.json
        # declared 2 roots while the script declared 3 (e1b65e3c widened the script but
        # never regenerated the output) and no gate noticed — which is precisely how the
        # CoreTerrainMaterials packages stayed invisible. validate_inventory_root_coverage
        # now fails closed on that mismatch.
        "content_roots": list(CONTENT_ROOTS),
        "packages_per_root": {
            root: sum(1 for p in packages if p["repo_path"].startswith(root + "/"))
            for root in CONTENT_ROOTS
        },
        "package_count": len(packages),
        "map_count": sum(1 for p in packages if p["package_kind"] == "map"),
        "asset_count": sum(1 for p in packages if p["package_kind"] == "asset"),
        "skipped_non_packages": skipped,
        "packages": packages,
        "notes": ("One record per package, both sides populated, keyed by package_path. "
                  "component_count/critical_references are null (need a loaded UWorld) — "
                  "null means UNKNOWN, never zero."),
        "meta": build_meta(
            command="build-canonical-conversion-manifest",
            pack="worldforge_vertical_slice", strict=True, status="ok",
            record_count=len(packages), records_total=len(packages),
            report_type="wf.transition.canonical_conversion.v1"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5.1 canonical conversion manifest.")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    m = build()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print("wrote {} ({} packages: {} maps + {} assets; {} non-package files skipped)".format(
        args.out, m["package_count"], m["map_count"], m["asset_count"],
        len(m["skipped_non_packages"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
