#!/usr/bin/env python3
"""build_manifest -- what was generated, who owns it, and what proves it.

THE GAP
-------
A build produced actors in a world and a pile of correct reports about the run,
and not one of them said, per artifact: which request caused this, who owns it,
what its content hashes to, or which checks vouch for it. The transaction journal
records what HAPPENED; it does not identify what now EXISTS. Asked "is this actor
yours, and can you prove it came from that request?", the platform had no answer
that survived the process exiting.

``procedural/`` already solves this for the pack pipeline -- owned-path prefixes,
``generated_owned`` flags, registries carrying ``input_hash``. The wfcore
transaction path had none of it, so this brings the same discipline to the
artifacts a bounded build creates.

TWO HASHES, NOT ONE, AND THE DIFFERENCE IS THE POINT
-----------------------------------------------------
``intent_hash``   the placement as PLANNED -- what was asked for
``observed_hash`` the payload the editor reported back -- what exists

A single hash would force a choice between describing the request and describing
the world, and the interesting question is precisely whether those two agree.
When they diverge the manifest says so per artifact rather than averaging it into
a summary nobody can act on.

OWNERSHIP IS DECLARED BY THE CALLER, NEVER INFERRED
----------------------------------------------------
An artifact is ``worldforge_generated`` only because this build created it. Any
path the caller declared protected is ``game_owned`` and must NEVER appear in the
generated list -- if it does, that is not a labelling mistake to be corrected in
the manifest, it means a build authored over content it was told not to touch,
and the validator refuses the whole document rather than describing the damage
tidily.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
_REPO = os.path.dirname(_TOOLS)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from wfcore.failure import FailureCode as C     # noqa: E402

RT_BUILD_MANIFEST = "wf.core.build_manifest.v1"

OWNER_WORLDFORGE = "worldforge_generated"
OWNER_GAME = "game_owned"
OWNERSHIPS = (OWNER_WORLDFORGE, OWNER_GAME)

_P = "build_manifest."

ARTIFACT_REQUIRED = ("artifact_id", "target_path", "ownership", "source",
                     "intent_hash", "observed_hash", "validation")
MANIFEST_REQUIRED = ("manifest_id", "request_id", "created_at", "git_sha",
                     "artifacts", "schema_version")


def canonical_hash(obj):
    """sha256 over canonical JSON. Stable across runs, machines and key order."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _git_sha(repo_root):
    try:
        proc = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=20)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    # Explicit unknown, never omitted: a reader must be able to tell "could not
    # read the revision" from "nobody recorded one".
    return "unknown"


def build_manifest(request_id, plan, observed_payloads, protected_identities,
                   created_at, target_paths=None, engine_build=None,
                   evidence_refs=None, validation=None, repo_root=_REPO):
    """One record per generated artifact, each independently checkable.

    ``target_paths`` is supplied ALONGSIDE the plan, aligned to its placements,
    rather than annotated onto them. Writing the address back into the plan
    would mutate the very document the rebuild-equivalence check compares --
    which is exactly what happened the first time this was wired, and the
    equivalence rail caught it. A manifest builder must not disturb its input.
    """
    protected = {str(p).strip() for p in (protected_identities or [])
                 if str(p).strip()}
    plan_hash = canonical_hash(plan.get("placements") or [])
    artifacts = []

    places = plan.get("placements") or []
    paths = list(target_paths or [])
    for idx, placement in enumerate(places):
        # Address comes from the transaction request that authored it, so the
        # manifest names exactly the thing that exists -- not a path this module
        # re-derived and could re-derive differently.
        target = paths[idx] if idx < len(paths) else placement.get("target_path")
        observed = (observed_payloads or {}).get(target)
        intent = {
            "location_cm": placement.get("location_cm"),
            "rotation_pyr": placement.get("rotation_pyr"),
            "scale": placement.get("scale"),
        }
        artifacts.append({
            "artifact_id": "art_{}_{:03d}".format(request_id,
                                                  placement.get("index", 0)),
            "target_path": target,
            "ownership": OWNER_WORLDFORGE,
            "source": {
                "request_id": request_id,
                "plan_hash": plan_hash,
                "placement_index": placement.get("index"),
                "anchor_ids": plan.get("anchor_ids"),
                "provider_id": plan.get("provider_id"),
            },
            "intent_hash": canonical_hash(intent),
            "observed_hash": canonical_hash(observed) if observed else None,
            "intent_matches_observed": (
                None if not observed else
                canonical_hash({
                    "location_cm": observed.get("location"),
                    "rotation_pyr": observed.get("rotation"),
                    "scale": observed.get("scale"),
                }) == canonical_hash(intent)),
            "schema_versions": {
                "plan": plan.get("schema_version"),
                "manifest": RT_BUILD_MANIFEST,
            },
            "validation": validation or {},
            "evidence_refs": list(evidence_refs or []),
        })

    return {
        "schema_version": RT_BUILD_MANIFEST,
        "report_type": RT_BUILD_MANIFEST,
        "manifest_id": "man_{}".format(request_id),
        "request_id": request_id,
        "created_at": created_at,
        "git_sha": _git_sha(repo_root),
        "engine_build": engine_build,
        "declared_game_owned": sorted(protected),
        "artifacts": artifacts,
        "counts": {
            "generated": len(artifacts),
            "observed": sum(1 for a in artifacts if a["observed_hash"]),
            "intent_matches_observed": sum(
                1 for a in artifacts if a["intent_matches_observed"] is True),
        },
    }


def validate_build_manifest(man, strict=False):
    code = C.CORE_PLACEMENT_PLAN_INVALID
    out = []
    is_obj = isinstance(man, dict)
    out.append((_P + "is_object", is_obj,
                "manifest must be an object", None if is_obj else code))
    if not is_obj:
        return out

    for f in MANIFEST_REQUIRED:
        ok = f in man
        out.append((_P + "has_" + f, ok,
                    "missing required field {!r}".format(f),
                    None if ok else code))

    sv = man.get("schema_version")
    out.append((_P + "schema_version", sv == RT_BUILD_MANIFEST,
                "schema_version must be {!r} (got {!r})".format(
                    RT_BUILD_MANIFEST, sv),
                None if sv == RT_BUILD_MANIFEST else code))

    # Stamped, or its freshness can never be graded.
    stamped = bool(man.get("created_at")) and bool(man.get("git_sha"))
    out.append((_P + "is_stamped", stamped,
                "a manifest must carry created_at and git_sha (got {!r}/{!r}); "
                "an unstamped manifest certifies content of unknown age "
                "forever".format(man.get("created_at"), man.get("git_sha")),
                None if stamped else code))

    protected = set(man.get("declared_game_owned") or [])
    arts = man.get("artifacts")
    if not isinstance(arts, list):
        out.append((_P + "artifacts_is_list", False, "artifacts must be a list",
                    code))
        return out

    seen = set()
    for i, a in enumerate(arts):
        pfx = _P + "artifact[{}].".format(i)
        if not isinstance(a, dict):
            out.append((pfx + "is_object", False, "artifact must be an object",
                        code))
            continue
        for f in ARTIFACT_REQUIRED:
            ok = f in a
            out.append((pfx + "has_" + f, ok,
                        "missing {!r}".format(f), None if ok else code))

        own = a.get("ownership")
        out.append((pfx + "ownership_known", own in OWNERSHIPS,
                    "ownership {!r} must be one of {}".format(own, OWNERSHIPS),
                    None if own in OWNERSHIPS else code))

        # THE RAIL THAT MATTERS. A generated artifact standing on a path the
        # caller declared game-owned is not a mislabelling to be tidied up in
        # the manifest -- it means the build authored over content it was told
        # not to touch, and the document must refuse rather than describe it.
        tp = a.get("target_path")
        collides = tp in protected
        out.append((pfx + "does_not_claim_game_owned_content", not collides,
                    "artifact {!r} is listed as {} but the caller declared that "
                    "path game-owned. This is not a labelling error: it means "
                    "generated content was authored onto protected "
                    "content".format(tp, own),
                    None if not collides else code))

        dupe = tp in seen
        seen.add(tp)
        out.append((pfx + "target_path_unique", not dupe,
                    "two artifacts claim {!r}; identity must be 1:1 or no hash "
                    "can be attributed".format(tp), None if not dupe else code))

        for h in ("intent_hash",):
            v = a.get(h)
            ok = isinstance(v, str) and v.startswith("sha256:") and len(v) == 71
            out.append((pfx + h + "_wellformed", ok,
                        "{} must be a sha256:<64hex> digest (got {!r})".format(
                            h, v), None if ok else code))

        # An unobserved artifact is honest; a MATCH claimed without an
        # observation is not.
        m = a.get("intent_matches_observed")
        if a.get("observed_hash") is None:
            out.append((pfx + "no_match_claimed_without_observation", m is None,
                        "artifact has no observed_hash, so intent_matches_observed "
                        "must be null (got {!r}) -- a match asserted against "
                        "nothing is the shape of a fabricated verification".format(m),
                        None if m is None else code))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", required=True, help="manifest to validate")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    try:
        with open(args.manifest, encoding="utf-8") as fh:
            man = json.load(fh)
    except (OSError, ValueError) as exc:
        print("manifest unreadable: {}".format(exc)); return 2
    checks = validate_build_manifest(man, strict=args.strict)
    bad = [c for c in checks if not c[1]]
    print("build-manifest: {} check(s), {} failure(s)".format(len(checks),
                                                              len(bad)))
    for name, _ok, detail, _c in bad:
        print("  FAIL {}: {}".format(name, detail[:160]))
    if not bad:
        print("  {} artifact(s), all identified, owned, hashed and "
              "stamped".format(len(man.get("artifacts") or [])))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
