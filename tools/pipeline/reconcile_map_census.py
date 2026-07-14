#!/usr/bin/env python3
"""reconcile_map_census.py — v2.5.1 Lane 2 map-census reconciler.

Explains the 131-vs-124 map discrepancy between the UE 5.7 and UE 5.8 censuses as
CLASSIFICATIONS BACKED BY EVIDENCE, not as a count delta. "The count changed" is not
an explanation; every 5.7-only package must earn a reason from probes that can be
re-run, or it stays ``unclassified`` and the gate goes RED.

Inputs (read-only):
  procedural/evidence/ue5_7/census_ue57_authoritative.json      (131 maps)
  procedural/evidence/ue5_8/census_ue58_postresave_houdini.json (124 maps)
  procedural/manifests/ue5_8_conversion/pre_conversion_manifest.json

Why the two censuses can legitimately disagree
----------------------------------------------
``wf_map_actor_census.py`` enumerates /Game through the AssetRegistry, which walks
the WORKING DIRECTORY on disk — it does not care whether a package is tracked by
git. So an untracked scratch .umap sitting in the editor's Content/Maps is counted.
``build_conversion_manifest.py`` rglob()s the same CONTENT_ROOTS, so it agrees with
the census *for the tree it ran in*. The 5.7 census ran in the primary worktree
(scratch present); the 5.8 census and the manifest ran in a tree without those
untracked files. The delta is therefore a property of WORKING-TREE CONTENT, not of
the 5.7 -> 5.8 conversion.

Evidence probes (deterministic, in-repo, no Unreal, no network)
--------------------------------------------------------------
  actor_count_5_7          from the 5.7 census entry
  loaded_5_7 / error_5_7   from the 5.7 census entry
  on_disk_in_worktree      Content/<rel>.umap present in THIS worktree
  tracked_at_head          git ls-files
  tracked_at_5_7_tag       git ls-tree -r <TAG_5_7>
  deleted_in_history       git log --diff-filter=D --all
  in_conversion_manifest   pre_conversion_manifest.json asset paths
  redirector_targets       manifest entries typed "redirector"
  under_content_roots      path falls beneath build_conversion_manifest CONTENT_ROOTS
  plugin_or_engine_path    path is a plugin/engine/vendor sample tree
  uncontrolled_changelist  OPTIONAL corroboration: UE's own record of packages
                           created outside source control (Saved/ is not tracked,
                           so this probe is best-effort and never load-bearing)

Classification vocabulary is CLOSED (see CLASSIFICATIONS). ``only_5_7`` is a
MEMBERSHIP label, never a resolved reason: a 5.7-only package that reaches the end
of the rule chain without earning a reason is emitted ``unclassified`` so the gate
fails closed.

Runtime-free. Report -> procedural/reports/ue5_8/census/map_census_reconciliation.json
Acceptance: PYTHONUTF8=1 STRICT=1 python tools/pipeline/reconcile_map_census.py
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from report_meta import build_meta  # noqa: E402
from transition_identity import transition_identity  # noqa: E402

CENSUS_5_7 = REPO_ROOT / "procedural" / "evidence" / "ue5_7" / "census_ue57_authoritative.json"
CENSUS_5_8 = REPO_ROOT / "procedural" / "evidence" / "ue5_8" / "census_ue58_postresave_houdini.json"
MANIFEST = REPO_ROOT / "procedural" / "manifests" / "ue5_8_conversion" / "pre_conversion_manifest.json"
UCL_PATH = REPO_ROOT / "Saved" / "SourceControl" / "UncontrolledChangelists.json"

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "census"
REPORT_NAME = "map_census_reconciliation.json"

TAG_5_7 = "worldforge-v2.4-ue5.7-final"

# Mirrors build_conversion_manifest.CONTENT_ROOTS. Duplicated deliberately: Lane 2
# does not import that module (it is not ours to perturb) and a drift between the
# two lists is itself a finding the gate surfaces.
CONTENT_ROOTS = ("Content", "Plugins/WorldForge/Content", "Plugins/CoreTerrainMaterials/Content")

# Path fragments that mark an engine/plugin/vendor sample rather than project content.
_SAMPLE_MARKERS = ("/Engine/", "/EngineData/", "/HoudiniEngine/", "/Houdini/Examples/",
                   "/Plugins/", "/Samples/", "/StarterContent/", "/Vendor/")

# CLOSED classification vocabulary.
CLASSIFICATIONS = (
    "only_5_7",                  # membership label only — never a resolved reason
    "only_5_8",
    "present_both",
    "renamed_or_redirected",
    "excluded_by_inventory_rule",
    "plugin_or_engine_sample",
    "generated_or_transient",
    "stale_or_invalid_5_7",
    "unclassified",
)

# Reasons that count as RESOLVED for a 5.7-only package.
RESOLVED_5_7_ONLY = ("renamed_or_redirected", "excluded_by_inventory_rule",
                     "plugin_or_engine_sample", "generated_or_transient",
                     "stale_or_invalid_5_7")


def _git(*args):
    """Run a read-only git command in REPO_ROOT -> stdout str ('' on failure)."""
    try:
        out = subprocess.run(("git",) + args, cwd=str(REPO_ROOT), capture_output=True,
                             text=True, timeout=60)
    except Exception:
        return ""
    return out.stdout if out.returncode == 0 else ""


def _game_to_rel(game_path):
    """/Game/Maps/Foo -> Content/Maps/Foo.umap (the repo-relative package path)."""
    assert game_path.startswith("/Game/"), game_path
    return "Content/" + game_path[len("/Game/"):] + ".umap"


def _load_census(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    return d, {m["map"]: m for m in d["maps"]}


def _load_manifest():
    if not MANIFEST.is_file():
        return None, set(), []
    d = json.loads(MANIFEST.read_text(encoding="utf-8"))
    paths = {a["path"] for a in d.get("assets", [])}
    redirs = [a["path"] for a in d.get("assets", []) if a.get("type") == "redirector"]
    return d, paths, redirs


def _load_uncontrolled():
    """OPTIONAL: UE's record of packages created outside source control.

    Saved/ is not tracked, so this is corroboration only — absence is not evidence
    of anything and never changes a classification.
    """
    if not UCL_PATH.is_file():
        return None
    try:
        blob = json.dumps(json.loads(UCL_PATH.read_text(encoding="utf-8", errors="replace")))
    except Exception:
        return None
    return blob


def probe(game_path, entry_5_7, tracked_head, tracked_tag, deleted_paths,
          manifest_paths, redirs, ucl_blob):
    """Gather the evidence record for one 5.7-only package. No verdict here."""
    rel = _game_to_rel(game_path)
    ev = {
        "package_path": game_path,
        "repo_relative_path": rel,
        "actor_count_5_7": entry_5_7.get("actor_count"),
        "class_histogram_5_7_empty": not entry_5_7.get("class_histogram"),
        "loaded_5_7": entry_5_7.get("loaded"),
        "error_5_7": entry_5_7.get("error"),
        "on_disk_in_worktree": (REPO_ROOT / rel).is_file(),
        "tracked_at_head": rel in tracked_head,
        "tracked_at_5_7_tag": rel in tracked_tag,
        "deleted_in_history": rel in deleted_paths,
        "in_conversion_manifest": rel in manifest_paths,
        "under_content_roots": any(rel == r or rel.startswith(r + "/") for r in CONTENT_ROOTS),
        "plugin_or_engine_path": any(m.lower() in ("/" + rel + "/").lower()
                                     for m in _SAMPLE_MARKERS),
        "redirector_referencing": sorted(p for p in redirs if Path(rel).stem in p),
    }
    ev["uncontrolled_changelist_listed"] = (
        None if ucl_blob is None else (rel.rsplit("/", 1)[-1] in ucl_blob))
    return ev


def classify(ev):
    """Evidence -> (classification, rationale). Deterministic, first match wins.

    Ordered most-specific first. Every branch cites the probes it stands on; the
    terminal branch is ``unclassified`` so an unexplained package fails closed
    rather than silently landing in a permissive bucket.
    """
    # 1. A redirector proves the package moved rather than vanished.
    if ev["redirector_referencing"]:
        return "renamed_or_redirected", (
            "an ObjectRedirector in the pre-conversion manifest still references this "
            "package name ({}), i.e. the asset was renamed/moved, not lost".format(
                ev["redirector_referencing"][:3]))

    # 2. Engine/plugin/vendor sample content — not project content, not our loss.
    if ev["plugin_or_engine_path"]:
        return "plugin_or_engine_sample", (
            "package lives under an engine/plugin/vendor sample tree; it is not "
            "project content inventoried for conversion")

    # 3. Was real, committed 5.7 content, and is provably gone from the tree.
    if ev["tracked_at_5_7_tag"] and not ev["tracked_at_head"]:
        return "stale_or_invalid_5_7", (
            "package was tracked at {} but is absent at HEAD (deleted_in_history={}) "
            "— it was retired between the 5.7 tag and now, so the 5.7 census counted "
            "content that no longer exists".format(TAG_5_7, ev["deleted_in_history"]))

    # 4. Untracked working-tree scratch: never in git, not on disk here, not in the
    #    inventory, and carrying no actors. The 5.7 census saw it only because the
    #    AssetRegistry walks the editor's working directory.
    if (not ev["tracked_at_head"] and not ev["tracked_at_5_7_tag"]
            and not ev["deleted_in_history"] and not ev["on_disk_in_worktree"]
            and not ev["in_conversion_manifest"] and ev["actor_count_5_7"] == 0
            and ev["class_histogram_5_7_empty"]):
        return "generated_or_transient", (
            "never tracked in git (absent at HEAD and at {}, never deleted -> never "
            "committed), absent from this worktree on disk, absent from the "
            "pre-conversion manifest, and empty in the 5.7 census (actor_count=0, "
            "empty class_histogram). This is editor scratch that the 5.7 AssetRegistry "
            "walk picked up from the primary worktree's working directory; it carries "
            "no actors, so nothing was lost".format(TAG_5_7))

    # 5. Present on disk and under CONTENT_ROOTS but the inventory still skipped it.
    if ev["on_disk_in_worktree"] and not ev["in_conversion_manifest"]:
        if not ev["under_content_roots"]:
            return "excluded_by_inventory_rule", (
                "package exists on disk but falls outside CONTENT_ROOTS {} so "
                "build_conversion_manifest never inventories it".format(list(CONTENT_ROOTS)))
        return "unclassified", (
            "package is on disk UNDER CONTENT_ROOTS yet missing from the manifest — "
            "build_conversion_manifest rglob()s every file under those roots, so this "
            "should be impossible. Refusing to guess")

    # 6. Terminal: no probe explains it. Fail closed.
    return "unclassified", (
        "no evidence probe explains this package's absence from the 5.8 census "
        "(evidence: {}). Refusing to invent a reason".format(
            {k: v for k, v in ev.items() if k not in ("package_path", "repo_relative_path")}))


def reconcile(force_unclassified=()):
    """Build the reconciliation payload.

    ``force_unclassified`` is a FAIL-CLOSED PROOF HOOK ONLY: it forces the named
    package(s) to ``unclassified`` so the gate can be shown going RED on demand. It
    is recorded in the payload (``forced_unclassified``) so a forced run can never
    be mistaken for a real one.
    """
    d57, m57 = _load_census(CENSUS_5_7)
    d58, m58 = _load_census(CENSUS_5_8)
    manifest, manifest_paths, redirs = _load_manifest()
    ucl_blob = _load_uncontrolled()

    tracked_head = set(_git("ls-files").splitlines())
    tracked_tag = set(_git("ls-tree", "-r", "--name-only", TAG_5_7).splitlines())
    deleted_paths = set(_git("log", "--all", "--diff-filter=D", "--name-only",
                             "--pretty=format:").splitlines()) - {""}

    s57, s58 = set(m57), set(m58)
    only_5_7, only_5_8, both = sorted(s57 - s58), sorted(s58 - s57), sorted(s57 & s58)

    entries = []
    for gp in both:
        entries.append({"package_path": gp, "membership": "present_both",
                        "classification": "present_both",
                        "rationale": "present in both the 5.7 and 5.8 censuses",
                        "actor_count_5_7": m57[gp].get("actor_count"),
                        "actor_count_5_8": m58[gp].get("actor_count"),
                        "evidence": None})
    for gp in only_5_8:
        entries.append({"package_path": gp, "membership": "only_5_8",
                        "classification": "only_5_8",
                        "rationale": "present in the 5.8 census only (added after the "
                                     "5.7 census was taken)",
                        "actor_count_5_7": None,
                        "actor_count_5_8": m58[gp].get("actor_count"),
                        "evidence": None})
    for gp in only_5_7:
        ev = probe(gp, m57[gp], tracked_head, tracked_tag, deleted_paths,
                   manifest_paths, redirs, ucl_blob)
        cls, why = classify(ev)
        if gp in force_unclassified:
            cls, why = "unclassified", "FORCED unclassified via --force-unclassified " \
                                       "(fail-closed proof hook; not a real finding)"
        entries.append({"package_path": gp, "membership": "only_5_7",
                        "classification": cls, "rationale": why,
                        "actor_count_5_7": m57[gp].get("actor_count"),
                        "actor_count_5_8": None, "evidence": ev})

    entries.sort(key=lambda e: e["package_path"])

    counts = {c: 0 for c in CLASSIFICATIONS}
    for e in entries:
        counts[e["classification"]] = counts.get(e["classification"], 0) + 1

    actors_only_5_7 = sum(m57[g].get("actor_count") or 0 for g in only_5_7)

    return {
        "reconciliation_status": "map_census_reconciliation",
        "generated_by": "tools/pipeline/reconcile_map_census.py",
        "source_engine": "5.7",
        "target_engine": "5.8",
        "classification_vocabulary": list(CLASSIFICATIONS),
        "inputs": {
            "census_5_7": {"path": str(CENSUS_5_7.relative_to(REPO_ROOT)).replace("\\", "/"),
                           "tag": d57.get("tag"), "engine_version": d57.get("engine_version"),
                           "map_count": d57.get("map_count"),
                           "total_actor_count": d57.get("total_actor_count")},
            "census_5_8": {"path": str(CENSUS_5_8.relative_to(REPO_ROOT)).replace("\\", "/"),
                           "tag": d58.get("tag"), "engine_version": d58.get("engine_version"),
                           "map_count": d58.get("map_count"),
                           "total_actor_count": d58.get("total_actor_count")},
            "conversion_manifest": {
                "path": str(MANIFEST.relative_to(REPO_ROOT)).replace("\\", "/"),
                "present": manifest is not None,
                "map_count": (manifest or {}).get("map_count")},
            "uncontrolled_changelist_probe_available": ucl_blob is not None,
        },
        "counts": {
            "census_5_7_maps": len(s57),
            "census_5_8_maps": len(s58),
            "only_5_7": len(only_5_7),
            "only_5_8": len(only_5_8),
            "present_both": len(both),
            "by_classification": counts,
        },
        "actor_accounting": {
            "total_actor_count_5_7": d57.get("total_actor_count"),
            "total_actor_count_5_8": d58.get("total_actor_count"),
            "actors_in_only_5_7_maps": actors_only_5_7,
            "actor_delta": (d57.get("total_actor_count") or 0) - (d58.get("total_actor_count") or 0),
            "note": "the map-count delta is actor-neutral iff actors_in_only_5_7_maps == 0 "
                    "and actor_delta == 0",
        },
        "forced_unclassified": sorted(force_unclassified),
        "entries": entries,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5.1 Lane 2 map-census reconciler.")
    ap.add_argument("--out", default=str(REPORT_DIR / REPORT_NAME))
    ap.add_argument("--pack", default="worldforge_vertical_slice")
    ap.add_argument("--force-unclassified", default="",
                    help="comma-separated /Game package paths to force to "
                         "unclassified (fail-closed proof hook only)")
    args, _ = ap.parse_known_args(argv)

    forced = tuple(p for p in (s.strip() for s in args.force_unclassified.split(",")) if p)
    payload = reconcile(force_unclassified=forced)

    payload_hash = hashlib.sha256(
        json.dumps(payload["entries"], sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()

    n = len(payload["entries"])
    unresolved = payload["counts"]["by_classification"].get("unclassified", 0)
    payload["meta"] = build_meta(
        command="reconcile-map-census", pack=args.pack, status="ok" if not unresolved else "fail",
        record_count=n, records_total=n, records_passed=n - unresolved, records_failed=unresolved,
        output_manifest_hash=payload_hash,
        report_type="wf.transition.map_census_reconciliation.v1",
        extra=transition_identity("5.8", runtime_required=False, runtime_executed=False,
                                  observed_runtime_engine=None))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    c = payload["counts"]
    print("[reconcile-map-census] 5.7={} 5.8={} | only_5_7={} only_5_8={} both={}".format(
        c["census_5_7_maps"], c["census_5_8_maps"], c["only_5_7"], c["only_5_8"],
        c["present_both"]))
    for e in payload["entries"]:
        if e["membership"] == "only_5_7":
            print("  {:<40s} -> {}".format(e["package_path"], e["classification"]))
    print("[reconcile-map-census] unclassified={} -> {}".format(
        unresolved, out_path.relative_to(REPO_ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
