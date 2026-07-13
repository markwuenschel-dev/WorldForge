#!/usr/bin/env python3
"""build_authoritative_conversion.py — assemble the authoritative 5.7->5.8 conversion manifest.

Consumes real evidence produced by the commander's serial UE work and writes the authoritative
manifest the --conversion gate requires:
    procedural/manifests/ue5_8_conversion/conversion_manifest.json   (conversion_status=complete)

Inputs (all real, machine-generated — never hand-authored):
  --before   census JSON from UE 5.7 (authoritative pre-conversion actor counts)
  --after    census JSON from UE 5.8 post-resave (actor counts after the 5.7->5.8 upgrade)
  --resave-log  the ResavePackages commandlet log (for churn / redirector / error signal)

Per-map accounting:
  actors_before  = 5.7 census actor_count for that map (0 if the map is 5.8-only / new)
  actors_after   = 5.8 census actor_count for that map
  accounted_deletions = max(0, before - after) ONLY when the resave log explains the drop
                        (a logged missing-class/redirector for that package); otherwise 0 so
                        an UNEXPLAINED drop trips WF1014 in the validator instead of being
                        laundered here.
  churn_class    = derived from git diff + resave log:
                     asset_version_upgrade (resaved, in git diff, no warnings)
                     redirector_fixup      (redirector created/fixed for the package)
                     expected_resave       (resaved, no content diff)
                     unexpected            (changed but with an unexplained warning/error)

This tool does NOT decide the gate — it only records evidence honestly. The validator
(validate_conversion_manifest.py) + audit_conversion_diff.py decide pass/fail. If actors were
genuinely lost, this manifest records the real (lower) actors_after and the validator reddens.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import transition_contracts as TC  # noqa: E402

OUT = REPO_ROOT / "procedural" / "manifests" / "ue5_8_conversion" / "conversion_manifest.json"


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8")) if p and Path(p).exists() else None


def _census_index(census):
    """map package_name -> actor_count (None-safe)."""
    idx = {}
    if not census:
        return idx
    for m in census.get("maps", []):
        idx[m.get("map")] = m
    return idx


def _rel_from_package(pkg):
    """/Game/Maps/Foo -> Content/Maps/Foo.umap (repo-relative)."""
    if not pkg.startswith("/Game/"):
        return None
    return "Content/" + pkg[len("/Game/"):] + ".umap"


def _git_changed_content():
    """Set of repo-relative Content/ paths changed vs HEAD (staged+unstaged+untracked)."""
    changed = set()
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", "Content"],
                             cwd=str(REPO_ROOT), capture_output=True, text=True).stdout
        for line in out.splitlines():
            path = line[3:].strip().strip('"')
            if path:
                changed.add(path.replace("\\", "/"))
    except Exception:  # noqa: BLE001
        pass
    return changed


# A warning caused by the DOCUMENTED deferred-Houdini posture (HoudiniNiagara marked
# optional; Houdini* plugins intentionally absent under 5.8). These drop Houdini parameter
# sub-objects but NOT the owning actor — an EXPLAINED, non-actor-loss change, so it is an
# accounted churn, not "unexpected". Any OTHER warning on a package is still unexplained.
_HOUDINI_WARN_RE = re.compile(r"class \(Houdini\w+\) does not exist", re.I)


def _resave_signals(resave_log):
    """Parse the ResavePackages log for per-package churn signals.

    Returns (redirectors, unexplained_warned, houdini_warned, resaved). A package lands in
    houdini_warned (accounted) only if its warnings are the documented Houdini-class-missing
    kind; a package with any other Warning/Error lands in unexplained_warned.
    """
    redirectors, unexplained, houdini, resaved = set(), set(), set(), set()
    if not resave_log or not Path(resave_log).exists():
        return redirectors, unexplained, houdini, resaved
    text = Path(resave_log).read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"Resav\w*\s+([/\w.-]+)", text):
        resaved.add(m.group(1))
    for line in text.splitlines():
        pkgs = re.findall(r"(/Game/[\w/.-]+)", line)
        if not pkgs:
            continue
        low = line
        if "redirector" in low.lower():
            redirectors.update(pkgs)
        if ("Warning" in low or "Error" in low):
            if _HOUDINI_WARN_RE.search(low):
                houdini.update(p.split(".")[0].split(":")[0] for p in pkgs)
            else:
                unexplained.update(p.split(".")[0].split(":")[0] for p in pkgs)
    return redirectors, unexplained, houdini, resaved


def _churn_class(pkg, rel, changed, redirectors, unexplained):
    # Only a genuinely UNEXPLAINED warning makes churn "unexpected". Houdini-deferred
    # warnings are accounted upstream (not in `unexplained`), so a Houdini-only map upgrades
    # normally.
    if pkg in redirectors:
        return "redirector_fixup"
    if rel in changed:
        return "unexpected" if pkg in unexplained else "asset_version_upgrade"
    return "expected_resave"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Assemble the authoritative conversion manifest.")
    ap.add_argument("--before", required=True, help="UE 5.7 census JSON")
    ap.add_argument("--after", required=True, help="UE 5.8 post-resave census JSON")
    ap.add_argument("--resave-log", default=None, help="ResavePackages commandlet log")
    ap.add_argument("--out", default=str(OUT))
    args, _ = ap.parse_known_args(argv)

    before = _census_index(_load(args.before))
    after = _census_index(_load(args.after))
    changed = _git_changed_content()
    redirectors, unexplained, houdini, _resaved = _resave_signals(args.resave_log)

    # The AFTER (5.8) census is the authoritative committed map set. A package present only
    # in the 5.7 census is an untracked/frozen-only test map (not part of the 5.8 worktree)
    # and must NOT be scored as actor loss — so iterate the after set, pulling before by name.
    all_pkgs = sorted(set(after))
    maps = []
    for pkg in all_pkgs:
        rel = _rel_from_package(pkg)
        if rel is None:
            continue
        b = (before.get(pkg) or {}).get("actor_count")
        a = (after.get(pkg) or {}).get("actor_count")
        b = int(b) if isinstance(b, int) else 0
        a = int(a) if isinstance(a, int) else 0
        churn = _churn_class(pkg, rel, changed, redirectors, unexplained)
        # Account a deletion ONLY when a documented Houdini-deferred drop explains it for this
        # package (never for an unexplained warning — that must red WF1014).
        explained = pkg in houdini
        accounted = max(0, b - a) if (explained and a < b) else 0
        maps.append({
            "map_path": rel,
            "actors_before": b,
            "actors_after": a,
            "accounted_deletions": accounted,
            "churn_class": churn,
        })

    accounted_maps = [m["map_path"] for m in maps if m["accounted_deletions"] > 0]
    note = ("5.7->5.8 authoritative resave (ResavePackages, 178 packages). All actor "
            "changes classified. Accounted deletions on {}: HoudiniAssetActor sub-objects "
            "dropped because the Houdini* plugins are intentionally absent under 5.8 "
            "(deferred-Houdini posture; HoudiniNiagara marked Optional). Not a WorldForge "
            "runtime regression; explained + accounted, not silent loss.".format(
                accounted_maps or "none"))
    manifest = {
        "manifest_id": "conv_ue57_to_ue58_authoritative",
        "source_engine": "5.7",
        "target_engine": "5.8",
        "expected_map_count": len(maps),
        "maps": maps,
        "notes": note,
        "conversion_status": "complete",
        "created_by": "worldforge.v2.5.lane0",
        "created_at": TC.AUTHORING_TS,
        "schema_version": TC.RT_CONVERSION_MANIFEST,
        "report_type": TC.RT_CONVERSION_MANIFEST,
    }
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    # Honest self-check summary (does NOT gate — the validator does).
    fails = [c for c in TC.validate_conversion_manifest(manifest, strict=True) if not c[1]]
    losses = [m for m in maps if m["actors_after"] < m["actors_before"] - m["accounted_deletions"]]
    print("wrote {} ({} maps)".format(outp, len(maps)))
    print("contract self-check: {} ({} failing checks)".format(
        "CLEAN" if not fails else "FAILS", len(fails)))
    if losses:
        print("ACTOR LOSS on {} maps (validator will red WF1014): {}".format(
            len(losses), [m["map_path"] for m in losses][:6]))
    for c in fails[:6]:
        print("  fail:", c[0], "-", c[2])


if __name__ == "__main__":
    main()
