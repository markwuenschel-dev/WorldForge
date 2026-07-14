#!/usr/bin/env python3
"""audit_conversion_diff.py — v2.5 pre/post-conversion diff classifier (scaffolding).

Given a PRE-conversion inventory (build_conversion_manifest.py) and a POST-conversion
manifest (the commander's authoritative conversion output), classify every changed asset
so the conversion window cannot land silent damage. Each change lands in exactly one bin:

    expected_engine_conversion  content hash changed by an accounted engine upgrade /
                                expected resave — benign, the reason conversion exists
    redirector_cleanup          a redirector appeared/was fixed up — benign housekeeping
    unexpected_binary_churn     content changed with no accounted reason — RELEASE-BLOCKING
    actor_loss                  a map's post actor count fell below (before - accounted
                                deletions) — RELEASE-BLOCKING, the cardinal conversion sin
    broken_reference            an asset present pre-conversion vanished post-conversion,
                                dangling every reference to it — RELEASE-BLOCKING
    unexplained                 a change the classifier cannot account for — RELEASE-BLOCKING
                                by default (unknown is guilty until explained)

RELEASE-BLOCKING bins fail the audit; benign bins do not. This module is SCAFFOLDING:
it is dogfooded on two SYNTHETIC in-memory manifests (a clean case and an actor-loss case)
and is NOT run against real conversion output this wave (none exists — see
validate_conversion_manifest.py, which is intentionally RED).

Run:
    PYTHONUTF8=1 python tools/pipeline/audit_conversion_diff.py   # runs the dogfood
"""

import argparse
import sys

# Classification bins.
EXPECTED_ENGINE_CONVERSION = "expected_engine_conversion"
REDIRECTOR_CLEANUP = "redirector_cleanup"
UNEXPECTED_BINARY_CHURN = "unexpected_binary_churn"
ACTOR_LOSS = "actor_loss"
BROKEN_REFERENCE = "broken_reference"
UNEXPLAINED = "unexplained"

ALL_BINS = (EXPECTED_ENGINE_CONVERSION, REDIRECTOR_CLEANUP, UNEXPECTED_BINARY_CHURN,
            ACTOR_LOSS, BROKEN_REFERENCE, UNEXPLAINED)

# A change in any of these bins blocks the release.
RELEASE_BLOCKING_BINS = frozenset(
    {UNEXPECTED_BINARY_CHURN, ACTOR_LOSS, BROKEN_REFERENCE, UNEXPLAINED})

# Churn classes (from transition_contracts.CHURN_CLASSES) that account for a hash change.
_ACCOUNTED_CHURN = frozenset(
    {"asset_version_upgrade", "redirector_fixup", "expected_resave"})


def _index(manifest):
    """Return {path: entry} from a manifest carrying an 'assets' or 'maps' list."""
    out = {}
    for key in ("assets", "maps"):
        for e in (manifest.get(key) or []):
            path = e.get("path") or e.get("map_path")
            if path:
                out[path] = e
    return out


def _classify_change(pre, post):
    """Classify one changed/removed/added asset given its pre and post entries."""
    if post is None:
        # Present before, gone after -> dangling references.
        return BROKEN_REFERENCE
    if pre is None:
        # New asset. A redirector standing in for a moved asset is benign cleanup;
        # anything else appearing is unexplained.
        return REDIRECTOR_CLEANUP if post.get("type") == "redirector" else UNEXPLAINED

    # Map actor accounting takes precedence — a lost actor is the cardinal sin.
    before = post.get("actors_before", pre.get("actors_before"))
    after = post.get("actors_after")
    deletions = post.get("accounted_deletions", 0)
    if isinstance(before, int) and isinstance(after, int) and isinstance(deletions, int):
        if after < before - deletions:
            return ACTOR_LOSS

    # Content unchanged -> not a change at all (caller filters, but be safe).
    if pre.get("sha256") is not None and pre.get("sha256") == post.get("sha256"):
        return None

    churn = post.get("churn_class")
    if churn == "redirector_fixup" or post.get("type") == "redirector":
        return REDIRECTOR_CLEANUP
    if churn in _ACCOUNTED_CHURN:
        return EXPECTED_ENGINE_CONVERSION
    # A binary change with no accounted reason is churn we must not wave through.
    return UNEXPECTED_BINARY_CHURN


def audit(pre_manifest, post_manifest):
    """Diff two manifests -> a structured audit result.

    Returns a dict with per-change classifications, per-bin counts, the
    release-blocking change list, and an overall ``release_blocking`` boolean.
    """
    pre_idx = _index(pre_manifest)
    post_idx = _index(post_manifest)
    all_paths = sorted(set(pre_idx) | set(post_idx))

    changes = []
    for path in all_paths:
        pre, post = pre_idx.get(path), post_idx.get(path)
        # Unchanged assets present on both sides with equal hashes are not changes.
        if pre and post and pre.get("sha256") is not None \
                and pre.get("sha256") == post.get("sha256") \
                and post.get("actors_after") is None:
            continue
        classification = _classify_change(pre, post)
        if classification is None:
            continue
        changes.append({
            "path": path,
            "classification": classification,
            "blocking": classification in RELEASE_BLOCKING_BINS,
        })

    counts = {b: 0 for b in ALL_BINS}
    for c in changes:
        counts[c["classification"]] += 1
    blocking = [c for c in changes if c["blocking"]]

    return {
        "changed_count": len(changes),
        "counts_by_bin": counts,
        "release_blocking": bool(blocking),
        "blocking_changes": blocking,
        "changes": changes,
    }


# --------------------------------------------------------------------------- #
# Dogfood — two SYNTHETIC in-memory manifests. No real conversion output exists.
# --------------------------------------------------------------------------- #
def _synthetic_pre():
    return {"assets": [
        {"path": "Content/Maps/encounter_loop_world.umap", "type": "map",
         "sha256": "aaa", "actors_before": 214},
        {"path": "Content/Maps/alpine_snow.umap", "type": "map",
         "sha256": "bbb", "actors_before": 188},
        {"path": "Content/Textures/Terrain/T_Sand_BC.uasset", "type": "texture",
         "sha256": "ccc"},
    ]}


def _synthetic_post_clean():
    # Every map resaved (hash churns) with full actor retention; texture untouched.
    return {"assets": [
        {"path": "Content/Maps/encounter_loop_world.umap", "type": "map",
         "sha256": "aaa2", "actors_before": 214, "actors_after": 214,
         "accounted_deletions": 0, "churn_class": "asset_version_upgrade"},
        {"path": "Content/Maps/alpine_snow.umap", "type": "map",
         "sha256": "bbb2", "actors_before": 188, "actors_after": 187,
         "accounted_deletions": 1, "churn_class": "redirector_fixup"},
        {"path": "Content/Textures/Terrain/T_Sand_BC.uasset", "type": "texture",
         "sha256": "ccc"},
    ]}


def _synthetic_post_actor_loss():
    # encounter map silently drops 4 actors with no accounted deletion.
    return {"assets": [
        {"path": "Content/Maps/encounter_loop_world.umap", "type": "map",
         "sha256": "aaa3", "actors_before": 214, "actors_after": 210,
         "accounted_deletions": 0, "churn_class": "expected_resave"},
        {"path": "Content/Maps/alpine_snow.umap", "type": "map",
         "sha256": "bbb2", "actors_before": 188, "actors_after": 188,
         "accounted_deletions": 0, "churn_class": "asset_version_upgrade"},
        {"path": "Content/Textures/Terrain/T_Sand_BC.uasset", "type": "texture",
         "sha256": "ccc"},
    ]}


def _dogfood():
    failures = []

    clean = audit(_synthetic_pre(), _synthetic_post_clean())
    if clean["release_blocking"]:
        failures.append("clean case wrongly flagged release-blocking: {}".format(
            clean["blocking_changes"]))
    if clean["counts_by_bin"][EXPECTED_ENGINE_CONVERSION] != 1:
        failures.append("clean case: expected 1 expected_engine_conversion, got {}".format(
            clean["counts_by_bin"]))
    if clean["counts_by_bin"][REDIRECTOR_CLEANUP] != 1:
        failures.append("clean case: expected 1 redirector_cleanup, got {}".format(
            clean["counts_by_bin"]))

    loss = audit(_synthetic_pre(), _synthetic_post_actor_loss())
    if not loss["release_blocking"]:
        failures.append("actor-loss case NOT flagged release-blocking (fake-green vector)")
    if loss["counts_by_bin"][ACTOR_LOSS] != 1:
        failures.append("actor-loss case: expected 1 actor_loss, got {}".format(
            loss["counts_by_bin"]))
    if not any(c["classification"] == ACTOR_LOSS and c["blocking"]
               for c in loss["blocking_changes"]):
        failures.append("actor_loss change not present in blocking_changes")

    return failures, clean, loss


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.5 conversion diff classifier (dogfood).")
    ap.add_argument("--dogfood", action="store_true", default=True)
    ap.parse_known_args(argv)

    failures, clean, loss = _dogfood()
    print("[conversion-audit] clean-case release_blocking={} bins={}".format(
        clean["release_blocking"], clean["counts_by_bin"]))
    print("[conversion-audit] actor-loss-case release_blocking={} bins={}".format(
        loss["release_blocking"], loss["counts_by_bin"]))
    if failures:
        print("[conversion-audit] DOGFOOD FAILED:")
        for f in failures:
            print("[conversion-audit]   - {}".format(f))
        return 1
    print("[conversion-audit] DOGFOOD PASS: clean benign, actor-loss release-blocking. "
          "(scaffolding only — not run on real conversion output; none exists)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
