#!/usr/bin/env python3
"""audit_conversion_diff.py — v2.5.1 conversion classifier over OBSERVED EVIDENCE.

WHAT CHANGED IN v2.5.1 (and why)
--------------------------------
The v2.5 classifier binned packages by the operation it ASSUMED had happened
(``expected_engine_conversion`` gated on a ``churn_class`` of
``asset_version_upgrade`` / ``redirector_fixup`` / ``expected_resave``). Those
labels were asserted by the producer, not derived from evidence. A label claiming
an operation nobody observed is a fake green.

v2.5.1 replaces the vocabulary with EVIDENCE-NAMED labels. Every label is a
statement about a comparison this module actually performed on fields really
present in the canonical manifest
(``procedural/manifests/ue5_8_conversion/canonical_conversion_manifest.json``,
schema ``wf.transition.canonical_conversion.v1``, keyed by ``package_path``).

THE EVIDENCE AVAILABLE (per record)
-----------------------------------
    source_hash / converted_hash                sha256 of the real package bytes
                                                (source side is the Git-LFS oid,
                                                which IS the content sha256)
    source_package_version /                    {file_version_ue4, file_version_ue5,
      converted_package_version                  legacy, licensee, custom_versions,
                                                 saved_by_engine_branch}
    actor_count.source / actor_count.converted  int for maps, null for assets
    package_kind / asset_class                  map|asset ; map|material|texture|…
    conversion_status                           present_both | source_only | converted_only
    component_count                             ALWAYS null (needs a loaded UWorld)
    critical_references                         ALWAYS null (needs a loaded UWorld)

NULL IS UNKNOWN, NEVER ZERO. A null discriminator is recorded in each result's
``unknown`` list, can never justify a benign label, and can never be read as
"no change".

VERSION EVIDENCE — core vs custom vs stamp are THREE DIFFERENT THINGS
---------------------------------------------------------------------
The version dicts hold three unrelated kinds of evidence. They must never be
compared wholesale (``src_dict != conv_dict`` would conflate all three and fire a
bogus version claim on every converted package):

  * CORE    file_version_ue4 / file_version_ue5 / legacy / licensee. UE 5.7 and
            5.8 share FileVersionUE5=1018 (same terminal ObjectVersion enum
            IMPORT_TYPE_HIERARCHIES), so CORE never moves across this transition.
  * CUSTOM  custom_versions {guid_hex: int}. These DO move across an engine
            resave (e.g. FFortniteMainBranchObjectVersion 225->268,
            FUE5MainStreamObjectVersion 121->123). null = UNPARSEABLE = UNKNOWN,
            never {} and never "no change".
  * STAMP   saved_by_engine_branch, "5.7"/"5.8" — WHICH ENGINE WROTE THE BYTES.
            NOT a version. It is the positive witness for engine_resave_only.

DECLARED vs OBSERVED: a record's ``converted_engine`` field is a DECLARED intent
("this is the 5.8 side"). ``saved_by_engine_branch`` is an OBSERVED fact. Where
they disagree the STAMP wins — that divergence is exactly how an unconverted
package is caught (declared 5.8, stamped 5.7).

LABELS ACTUALLY DECIDED (each with its exact evidence rule)
----------------------------------------------------------
``unchanged``
    both hashes non-null AND EQUAL. Byte-identical packages are TOTAL evidence:
    nothing inside can differ, so no unknown can undermine this label. In a
    CONVERSION audit it also means the package was NOT converted — surfaced via
    ``unconverted_packages`` when the stamp confirms it, never silently green.

``package_version_changed``
    CORE differs (any of file_version_ue4/file_version_ue5/legacy/licensee) — a
    package FORMAT change, which outranks the resave that carried it — OR
    custom_versions are KNOWN ON BOTH SIDES, differ, and NO engine-stamp move
    explains them. This is the ONLY label that may claim a version move, and only
    on a real version delta. Never fires on the stamp, and never on UNKNOWN
    custom versions.

``actor_graph_changed``
    The actor graph moved, by COUNT or by COMPOSITION:
      * actor_count both non-null AND differ — blocking iff converted < source
        (actor loss, WF1014);
      * actor_class_inventory both non-null AND a class present in source with
        count>0 is absent/zero after — blocking (WF1014). This is per-class actor
        loss and it fires EVEN AT AN UNCHANGED TOTAL COUNT: a class replacement
        ({HoudiniAssetActor:1, StaticMeshActor:1} -> {StaticMeshActor:2}) still
        totals 2 and is invisible to actor_count alone. That is the silent damage
        this audit exists to catch;
      * a class gained or a per-class count shift with nothing lost — reported,
        not blocked.
    Both loss rules are checked BEFORE any benign label, so a version move or a
    resave can never mask an actor loss.

``engine_resave_only``
    present_both AND hashes non-null AND DIFFER AND CORE known+equal AND custom
    versions do not contradict AND actor evidence does not contradict AND the
    STAMP is known on both sides and MOVED. See the honesty bound below.

``unclassified``
    anything else: contradictory evidence, null hash, unknown CORE, unknown or
    unmoved STAMP on a byte change, or not present_both. ALWAYS BLOCKING
    (WF1021). Unknown is guilty until explained. Forcing a label to clear this
    gate is the exact failure mode v2.5.1 exists to remove.

WHY THE STAMP IS THE EVIDENCE FOR engine_resave_only (not a separate label)
---------------------------------------------------------------------------
Before the stamp existed this bin meant "the bytes changed and nothing else we
can see moved" — a residual argued from ABSENCE. With the stamp it means "a
DIFFERENT ENGINE WROTE THESE BYTES": a positive observation of the very
operation the label names. Splitting the stamp into its own label would leave
engine_resave_only as the weak absence-argument again and scatter one event's
evidence across two bins. So the stamp is folded in as a REQUIREMENT.

The converse now bites: a hash change with NO stamp move is NOT an engine resave
— the same engine rewrote the package — and it falls to ``unclassified`` rather
than being waved through as benign. That rule has zero hits today; it exists so
the benign bin cannot absorb an anomaly.

CAUSE OUTRANKS EFFECT (why a custom-version bump does not win the bin)
---------------------------------------------------------------------
Bumping custom versions is WHAT AN ENGINE RESAVE DOES. When the stamp moved
5.7 -> 5.8 AND custom versions moved 225 -> 268, those are not two findings:
they are one event and its bookkeeping. Labelling by the effect
(``package_version_changed``) while the cause is directly observable would be
strictly less informative and would empty the ``engine_resave_only`` bin
entirely — measured: with custom versions populated, effect-first ordering
yields 176 package_version_changed / 0 engine_resave_only. So a moved stamp
CLAIMS the custom delta and records it as corroborating evidence.

CORE is the exception: a core/format move is not routine bookkeeping, so it
outranks the resave and keeps ``package_version_changed``. And a custom move
with NO stamp move keeps ``package_version_changed`` too — there the version
moved and nothing accounts for it, which is a finding in its own right.

HONESTY BOUND on ``engine_resave_only``
---------------------------------------
``_only`` is scoped to the OBSERVED evidence set, not to reality. It asserts "no
other difference is visible in this manifest", NOT "no other difference exists".
component_count and critical_references are null for all packages; actor_count is
null for every non-map asset; custom_versions is currently null for all packages
(a producer-side parse failure — see ``version_evidence_complete`` in
validate_conversion_audit.py, which BLOCKS on it rather than letting this bin
quietly absorb a real version change). Each result carries ``unknown`` so the
residual is auditable per record.

LABELS DELIBERATELY NOT USED (undecidable from real evidence — see _UNDECIDABLE)
-------------------------------------------------------------------------------
``serialized_content_changed``, ``metadata_only_changed``,
``reference_graph_changed``, ``plugin_class_restored``. Each is refused for a
specific reason recorded in ``_UNDECIDABLE`` and asserted unreachable by
``undecidable_label_leak()``. They are NOT emitted, not even as a fallback.

DELETIONS
---------
A record with conversion_status == source_only was present before conversion and
absent after: every reference to it dangles. The manifest carries no
accounted-deletion allowlist, so ANY such record is an UNACCOUNTED deletion —
blocking (WF1016) and additionally labelled ``unclassified``.

Run:
    PYTHONUTF8=1 python tools/pipeline/audit_conversion_diff.py            # real manifest
    PYTHONUTF8=1 python tools/pipeline/audit_conversion_diff.py --selftest # negative controls
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CANONICAL_MANIFEST = (REPO_ROOT / "procedural" / "manifests" / "ue5_8_conversion"
                      / "canonical_conversion_manifest.json")
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "ue5_8" / "audit"
REPORT_NAME = "conversion_diff_audit.json"

CANONICAL_SCHEMA = "wf.transition.canonical_conversion.v1"
CANONICAL_KEYSPACE = "package_path"

# The four CORE package-version fields. Everything else in the version dict is
# NOT a core version and must never be diffed as one.
CORE_VERSION_KEYS = ("file_version_ue4", "file_version_ue5", "legacy", "licensee")

# -- Evidence-named labels this module actually decides ----------------------- #
UNCHANGED = "unchanged"
PACKAGE_VERSION_CHANGED = "package_version_changed"
ACTOR_GRAPH_CHANGED = "actor_graph_changed"
ENGINE_RESAVE_ONLY = "engine_resave_only"
UNCLASSIFIED = "unclassified"

ALL_LABELS = (UNCHANGED, PACKAGE_VERSION_CHANGED, ACTOR_GRAPH_CHANGED,
              ENGINE_RESAVE_ONLY, UNCLASSIFIED)

# -- Labels refused because no real field can decide them --------------------- #
_UNDECIDABLE = {
    "serialized_content_changed":
        "only a whole-file sha256 is available; a hash delta cannot be localized to "
        "serialized object data as opposed to header/summary/metadata bytes. Deciding "
        "this needs per-export payload digests the manifest does not carry.",
    "metadata_only_changed":
        "the manifest carries no metadata surface at all (no package flags, no asset "
        "registry tags, no timestamps, no sizes) — there is nothing to compare, so "
        "'metadata only' can never be affirmed.",
    "reference_graph_changed":
        "critical_references is null for every package (needs a loaded UWorld). "
        "Null is UNKNOWN; emitting this label on null evidence would be a fabrication, "
        "and emitting its absence would be a fake green.",
    "plugin_class_restored":
        "REFUSAL SURVIVES actor_class_inventory being plumbed in. The named candidate "
        "/Game/WorldForge/Maps/Untitled reads {HoudiniAssetActor:1, StaticMeshActor:1} "
        "on BOTH sides, so source-vs-converted does not witness the reclaim at all: it "
        "was a historical event against an intermediate state, not a property of this "
        "diff. No field present can decide it, and the class inventory — the one thing "
        "that could have — positively shows there is nothing to see. Confirmed with "
        "Lane 1, who records that the refusal stands.",
}


import pathlib

def _repo_relative(p):
    """Repo-relative POSIX path for a manifest location.

    Recorded paths must be portable: an absolute Windows path leaks the author's
    machine into evidence and trips the hygiene rail (WF1037) — correctly. The
    manifest always lives inside the repo, so relativise it; fall back to the bare
    filename rather than emit an absolute path.
    """
    try:
        return pathlib.Path(p).resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return pathlib.Path(p).name


def undecidable_label_leak(results):
    """Return any refused label that leaked into results — must always be empty."""
    emitted = {r["label"] for r in results}
    return sorted(emitted & set(_UNDECIDABLE))


# --------------------------------------------------------------------------- #
# Evidence extraction — CORE, CUSTOM and STAMP are read separately on purpose.
# --------------------------------------------------------------------------- #
def _core_delta(src, conv):
    """Sorted CORE version keys that differ. None when UNKNOWN (dict missing)."""
    if not isinstance(src, dict) or not isinstance(conv, dict):
        return None
    return sorted(k for k in CORE_VERSION_KEYS if src.get(k) != conv.get(k))


def _custom_delta(src, conv):
    """Custom-version comparison. Returns None when UNKNOWN on either side.

    null custom_versions means the producer could not parse the
    FCustomVersionContainer. That is UNKNOWN — it is NOT an empty set and NOT
    evidence of "no custom version changed".
    """
    if not isinstance(src, dict) or not isinstance(conv, dict):
        return None
    s, c = src.get("custom_versions"), conv.get("custom_versions")
    if not isinstance(s, dict) or not isinstance(c, dict):
        return None
    return sorted(g for g in set(s) | set(c) if s.get(g) != c.get(g))


def _stamps(src, conv):
    """(source_branch, converted_branch); either may be None = UNKNOWN."""
    s = src.get("saved_by_engine_branch") if isinstance(src, dict) else None
    c = conv.get("saved_by_engine_branch") if isinstance(conv, dict) else None
    return s, c


def _actor_pair(rec):
    """(source, converted) actor counts; either may be None = UNKNOWN."""
    ac = rec.get("actor_count") or {}
    s, c = ac.get("source"), ac.get("converted")
    return (s if isinstance(s, int) else None, c if isinstance(c, int) else None)


def _class_inventory(rec):
    """(source, converted) {class_name: count}; either may be None = UNKNOWN.

    Populated for maps from the censuses' class_histogram. null for non-map
    packages, which have no actors at all — UNKNOWN, never an empty inventory.
    """
    inv = rec.get("actor_class_inventory") or {}
    s, c = inv.get("source"), inv.get("converted")
    return (s if isinstance(s, dict) else None, c if isinstance(c, dict) else None)


def _class_delta(src, conv):
    """(lost, gained, shifted) class names, or None when UNKNOWN.

    ``lost``    present in source with count>0, absent or zero after. This is
                per-class ACTOR LOSS and is blocking EVEN WHEN THE TOTAL ACTOR
                COUNT IS UNCHANGED — a class replacement (HoudiniAssetActor ->
                StaticMeshActor at 2 -> 2) is invisible to actor_count and is
                exactly the silent damage this audit exists to catch.
    ``gained``  absent or zero in source, present after.
    ``shifted`` present on both sides but the count moved.
    """
    if not isinstance(src, dict) or not isinstance(conv, dict):
        return None
    lost = sorted(k for k in src if src.get(k, 0) > 0 and conv.get(k, 0) == 0)
    gained = sorted(k for k in conv if conv.get(k, 0) > 0 and src.get(k, 0) == 0)
    shifted = sorted(k for k in set(src) | set(conv)
                     if src.get(k, 0) != conv.get(k, 0)
                     and k not in lost and k not in gained)
    return lost, gained, shifted


def classify(rec):
    """Classify ONE canonical-manifest record from its observed evidence.

    Returns {label, blocking, reason, evidence, unknown, unconverted}. ``evidence``
    lists comparisons actually made; ``unknown`` lists discriminators that were
    null and therefore justified nothing.
    """
    evidence, unknown = [], []

    if rec.get("component_count") is None:
        unknown.append("component_count=null(needs UWorld)")
    if rec.get("critical_references") is None:
        unknown.append("critical_references=null(needs UWorld)")

    status = rec.get("conversion_status")
    src_h, conv_h = rec.get("source_hash"), rec.get("converted_hash")
    sv, cv = rec.get("source_package_version"), rec.get("converted_package_version")
    core = _core_delta(sv, cv)
    custom = _custom_delta(sv, cv)
    s_stamp, c_stamp = _stamps(sv, cv)
    a_src, a_conv = _actor_pair(rec)

    if custom is None:
        unknown.append("custom_versions=null(unparseable by producer)")
    if s_stamp is None or c_stamp is None:
        unknown.append("saved_by_engine_branch=null(src={},conv={})".format(
            s_stamp, c_stamp))
    if a_src is None or a_conv is None:
        unknown.append("actor_count=null(kind={})".format(rec.get("package_kind")))
    else:
        evidence.append("actor_count {}->{}".format(a_src, a_conv))

    ci_src, ci_conv = _class_inventory(rec)
    cls = _class_delta(ci_src, ci_conv)
    if cls is None:
        unknown.append("actor_class_inventory=null(kind={})".format(
            rec.get("package_kind")))
    else:
        evidence.append("actor_class_inventory known ({} source class(es))".format(
            len(ci_src)))

    def out(label, blocking, reason, unconverted=False):
        return {"label": label, "blocking": blocking, "reason": reason,
                "evidence": evidence, "unknown": unknown, "unconverted": unconverted}

    # 1. Not present on both sides -> no defensible comparison exists.
    if status != "present_both":
        if status == "source_only":
            return out(UNCLASSIFIED, True,
                       "present pre-conversion, absent post-conversion: unaccounted "
                       "deletion, every reference to it dangles")
        return out(UNCLASSIFIED, True,
                   "conversion_status={!r}: no both-sides evidence to compare".format(status))

    # 2. A missing hash is UNKNOWN, not "same".
    if not src_h or not conv_h:
        return out(UNCLASSIFIED, True,
                   "hash missing (source={}, converted={}): change is UNKNOWN".format(
                       bool(src_h), bool(conv_h)))

    # 3. The record's own evidence must agree with itself. actor_class_inventory
    #    and actor_count are independently sourced, so a disagreement means one of
    #    them is wrong and NEITHER can be trusted for this package.
    for side, inv, cnt in (("source", ci_src, a_src), ("converted", ci_conv, a_conv)):
        if inv is not None and cnt is not None and sum(inv.values()) != cnt:
            return out(UNCLASSIFIED, True,
                       "contradictory evidence: {} actor_class_inventory totals {} but "
                       "actor_count says {}".format(side, sum(inv.values()), cnt))

    # 4. Byte-identical. TOTAL evidence — identical bytes cannot hide a difference,
    #    so no `unknown` can undermine this one.
    if src_h == conv_h:
        evidence.append("hash identical")
        if a_src is not None and a_conv is not None and a_src != a_conv:
            return out(UNCLASSIFIED, True,
                       "contradictory evidence: hashes identical but actor_count "
                       "{}->{}".format(a_src, a_conv))
        if cls is not None and (cls[0] or cls[1] or cls[2]):
            return out(UNCLASSIFIED, True,
                       "contradictory evidence: hashes identical but the actor class "
                       "inventory moved (lost={}, gained={}, shifted={})".format(
                           cls[0], cls[1], cls[2]))
        if s_stamp is not None and c_stamp is not None and s_stamp != c_stamp:
            return out(UNCLASSIFIED, True,
                       "contradictory evidence: hashes identical but engine stamp "
                       "{}->{}".format(s_stamp, c_stamp))
        # Identical bytes in a CONVERSION audit == this package was not converted.
        declared = rec.get("converted_engine")
        unconv = (c_stamp is not None and declared is not None
                  and str(c_stamp) != str(declared))
        if unconv:
            evidence.append("stamp {} != declared converted_engine {}".format(
                c_stamp, declared))
            return out(UNCHANGED, False,
                       "bytes identical on both sides and still stamped {} while the "
                       "record declares converted_engine={}: NOT CONVERTED".format(
                           c_stamp, declared),
                       unconverted=True)
        return out(UNCHANGED, False, "source and converted bytes are identical")
    evidence.append("hash differs")

    # 5. THE CARDINAL SIN FIRST. An actor loss must never be masked by a benign
    #    label that happens to match earlier in the rule order.
    if a_src is not None and a_conv is not None and a_conv < a_src:
        return out(ACTOR_GRAPH_CHANGED, True,
                   "actor LOSS {} -> {} ({} actor(s) gone) with no accounted "
                   "deletion".format(a_src, a_conv, a_src - a_conv))

    # 5b. CLASS LOSS is actor loss the total count cannot see. A class that was
    #     there and is now gone is silent damage even at an unchanged actor count
    #     (the class-replacement case: {HoudiniAssetActor:1, StaticMeshActor:1} ->
    #     {StaticMeshActor:2} still totals 2). Blocking, same as a count drop.
    if cls is not None and cls[0]:
        return out(ACTOR_GRAPH_CHANGED, True,
                   "actor CLASS LOSS: {} present in source, gone after{} — silent "
                   "damage the total actor count ({}) does not reveal".format(
                       ", ".join("{}x{}".format(ci_src.get(k), k) for k in cls[0]),
                       " (replaced by {})".format(", ".join(
                           "{}x{}".format(ci_conv.get(k), k) for k in cls[1]))
                       if cls[1] else "",
                       "{}->{}".format(a_src, a_conv)
                       if a_src is not None else "UNKNOWN"))

    # 6. CORE versions must be readable at all.
    if core is None:
        return out(UNCLASSIFIED, True,
                   "core package version UNKNOWN on one or both sides; cannot tell a "
                   "version move from unexplained churn")

    # 6. A CORE version move is a PACKAGE FORMAT change — the most significant
    #    version fact there is, and it outranks the resave that carried it.
    if core:
        evidence.append("CORE version differs on {}".format(",".join(core)))
        return out(PACKAGE_VERSION_CHANGED, False,
                   "core package version really moved: {}".format(", ".join(
                       "{}: {!r}->{!r}".format(k, (sv or {}).get(k), (cv or {}).get(k))
                       for k in core)))
    evidence.append("CORE version identical")

    # 8. Actor gain, or a class composition change with nothing lost (losses
    #    already returned at 5/5b). A structural change is more specific than the
    #    resave that carried it.
    if a_src is not None and a_conv is not None and a_src != a_conv:
        return out(ACTOR_GRAPH_CHANGED, False,
                   "actor gain {} -> {} (+{}); not a loss, reported not blocked".format(
                       a_src, a_conv, a_conv - a_src))
    if cls is not None and (cls[1] or cls[2]):
        return out(ACTOR_GRAPH_CHANGED, False,
                   "actor class composition changed with nothing lost (gained={}, "
                   "shifted={}); not a loss, reported not blocked".format(
                       cls[1], cls[2]))

    def _custom_detail():
        return ", ".join("{}: {!r}->{!r}".format(
            g[:8], (sv.get("custom_versions") or {}).get(g),
            (cv.get("custom_versions") or {}).get(g)) for g in (custom or [])[:4])

    # 8. The bytes were rewritten. Only a MOVED engine stamp positively witnesses
    #    that a DIFFERENT ENGINE did it — and a moved stamp EXPLAINS a custom
    #    version bump, because bumping custom versions is what an engine resave
    #    does. Cause outranks effect: the label names the engine resave and
    #    records the custom delta as corroborating evidence rather than splitting
    #    one event across two bins.
    if s_stamp is not None and c_stamp is not None and s_stamp != c_stamp:
        evidence.append("engine stamp MOVED {}->{}".format(s_stamp, c_stamp))
        if custom:
            evidence.append("custom_versions moved on {} guid(s) — consistent with, "
                            "and explained by, the engine change".format(len(custom)))
        elif custom == []:
            evidence.append("custom_versions identical")
        return out(ENGINE_RESAVE_ONLY, False,
                   "a different engine wrote the bytes ({}->{}); core version "
                   "identical; actor graph not contradicting{}".format(
                       s_stamp, c_stamp,
                       "; custom versions bumped as expected ({})".format(
                           _custom_detail()) if custom else ""))

    # 9. No engine change to explain the rewrite. A custom-version move is now a
    #    finding in its own right: the version moved and NOTHING accounts for it.
    if custom:
        evidence.append("custom_versions differ on {} guid(s) with NO engine "
                        "change".format(len(custom)))
        return out(PACKAGE_VERSION_CHANGED, False,
                   "custom versions really moved on {} guid(s) with no engine change "
                   "to explain it: {}".format(len(custom), _custom_detail()))
    if custom == []:
        evidence.append("custom_versions identical")

    # 10. Bytes changed, and nothing observed explains it.
    if s_stamp is None or c_stamp is None:
        return out(UNCLASSIFIED, True,
                   "bytes changed but the engine stamp is UNKNOWN (src={!r}, "
                   "conv={!r}): nothing witnesses an engine resave".format(
                       s_stamp, c_stamp))
    return out(UNCLASSIFIED, True,
               "bytes changed but the SAME engine ({}) wrote both sides: this is not "
               "an engine conversion and nothing explains the rewrite".format(s_stamp))


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
def audit(manifest):
    """Classify every package in a canonical conversion manifest."""
    packages = manifest.get("packages") or []
    results = []
    for rec in packages:
        r = classify(rec)
        r["package_path"] = rec.get("package_path")
        r["package_kind"] = rec.get("package_kind")
        r["asset_class"] = rec.get("asset_class")
        results.append(r)
    results.sort(key=lambda r: (r["package_path"] or ""))

    counts = {lbl: 0 for lbl in ALL_LABELS}
    for r in results:
        counts[r["label"]] = counts.get(r["label"], 0) + 1

    blocking = [r for r in results if r["blocking"]]
    unclassified = [r for r in results if r["label"] == UNCLASSIFIED]
    actor_loss = [r for r in results
                  if r["label"] == ACTOR_GRAPH_CHANGED and r["blocking"]]
    deletions = [p.get("package_path") for p in packages
                 if p.get("conversion_status") == "source_only"]

    return {
        "package_count": len(results),
        "counts_by_label": counts,
        "labels_refused_as_undecidable": dict(_UNDECIDABLE),
        "undecidable_label_leak": undecidable_label_leak(results),
        "unclassified_packages": [r["package_path"] for r in unclassified],
        "unaccounted_deletions": deletions,
        "actor_loss_packages": [r["package_path"] for r in actor_loss],
        "class_loss_packages": [r["package_path"] for r in actor_loss
                                if "CLASS LOSS" in r["reason"]],
        "class_inventory_known": sum(
            1 for p in packages if _class_delta(*_class_inventory(p)) is not None),
        "unconverted_packages": [r["package_path"] for r in results
                                 if r.get("unconverted")],
        "version_evidence": version_evidence(packages),
        "release_blocking": bool(blocking),
        "blocking_packages": blocking,
        "results": results,
    }


def version_evidence(packages):
    """Coverage of the version evidence itself — is the input worth classifying on?

    A field that is null for EVERY package is not "unknown for a few records"; it
    is a producer-side failure to read that evidence at all. Reported so the gate
    can refuse to certify a diff whose version evidence was never actually read.
    """
    n = len(packages)
    core_known = custom_known = stamp_known = 0
    for p in packages:
        sv, cv = p.get("source_package_version"), p.get("converted_package_version")
        if _core_delta(sv, cv) is not None:
            core_known += 1
        if _custom_delta(sv, cv) is not None:
            custom_known += 1
        s, c = _stamps(sv, cv)
        if s is not None and c is not None:
            stamp_known += 1
    return {
        "package_count": n,
        "core_version_known": core_known,
        "custom_versions_known": custom_known,
        "engine_stamp_known": stamp_known,
        "custom_versions_systematically_absent": n > 0 and custom_known == 0,
    }


def load_manifest(path):
    with Path(path).open(encoding="utf-8") as fh:
        return json.load(fh)


def is_real_canonical_manifest(manifest):
    """Return (ok, reasons) — is this the real canonical manifest, not a stub?"""
    reasons = []
    if manifest.get("schema_version") != CANONICAL_SCHEMA:
        reasons.append("schema_version={!r} != {!r}".format(
            manifest.get("schema_version"), CANONICAL_SCHEMA))
    if manifest.get("report_type") != CANONICAL_SCHEMA:
        reasons.append("report_type={!r} != {!r}".format(
            manifest.get("report_type"), CANONICAL_SCHEMA))
    if manifest.get("keyspace") != CANONICAL_KEYSPACE:
        reasons.append("keyspace={!r} != {!r}".format(
            manifest.get("keyspace"), CANONICAL_KEYSPACE))
    pkgs = manifest.get("packages") or []
    if manifest.get("package_count") != len(pkgs):
        reasons.append("package_count={!r} but {} package records".format(
            manifest.get("package_count"), len(pkgs)))
    if not pkgs:
        reasons.append("no package records")
    meta = manifest.get("meta") or {}
    if not meta.get("git_sha"):
        reasons.append("meta.git_sha absent — not a produced artifact")
    if meta.get("record_count") != len(pkgs):
        reasons.append("meta.record_count={!r} but {} package records".format(
            meta.get("record_count"), len(pkgs)))
    return (not reasons), reasons


def common_keyspace(manifest):
    """Return (ok, reasons) — does every record carry BOTH sides of the diff?"""
    reasons = []
    pkgs = manifest.get("packages") or []
    for p in pkgs:
        path = p.get("package_path")
        if not path:
            reasons.append("record without package_path")
            continue
        if p.get("conversion_status") != "present_both":
            reasons.append("{}: conversion_status={!r}".format(
                path, p.get("conversion_status")))
        if not p.get("source_hash"):
            reasons.append("{}: no source_hash".format(path))
        if not p.get("converted_hash"):
            reasons.append("{}: no converted_hash".format(path))
    paths = [p.get("package_path") for p in pkgs]
    if len(set(paths)) != len(paths):
        reasons.append("package_path is not unique — keyspace is not a key")
    return (not reasons), reasons[:10]


# --------------------------------------------------------------------------- #
# Self-test — negative controls on canonical-SHAPED synthetic records.
# Proves the blocking rules actually fire. Never used to green the real gate.
# --------------------------------------------------------------------------- #
_V57 = {"file_version_ue4": 522, "file_version_ue5": 1018, "legacy": -9, "licensee": 0,
        "custom_versions": {"aa": 225}, "saved_by_engine_branch": "5.7"}
_V58 = {"file_version_ue4": 522, "file_version_ue5": 1018, "legacy": -9, "licensee": 0,
        "custom_versions": {"aa": 268}, "saved_by_engine_branch": "5.8"}


def _rec(path, kind="map", src="a" * 8, conv="b" * 8, sv=None, cv=None,
         a_src=10, a_conv=10, status="present_both", declared="5.8",
         ci_src=None, ci_conv=None):
    if kind == "map" and ci_src is None and a_src is not None:
        ci_src = {"StaticMeshActor": a_src}
    if kind == "map" and ci_conv is None and a_conv is not None:
        ci_conv = {"StaticMeshActor": a_conv}
    return {"package_path": path, "package_kind": kind,
            "asset_class": "map" if kind == "map" else "material",
            "conversion_status": status, "source_hash": src, "converted_hash": conv,
            "source_engine": "5.7", "converted_engine": declared,
            "source_package_version": dict(_V57 if sv is None else sv),
            "converted_package_version": dict(_V58 if cv is None else cv),
            "actor_count": {"source": a_src, "converted": a_conv},
            "actor_class_inventory": {"source": ci_src, "converted": ci_conv},
            "component_count": None, "critical_references": None}


def _no_custom(v):
    d = dict(v)
    d["custom_versions"] = None
    return d


def _selftest():
    fails = []

    def expect(name, rec, label, blocking):
        r = classify(rec)
        if r["label"] != label:
            fails.append("{}: expected {!r}, got {!r} ({})".format(
                name, label, r["label"], r["reason"]))
        elif r["blocking"] is not blocking:
            fails.append("{}: expected blocking={}, got {} ({})".format(
                name, blocking, r["blocking"], r["reason"]))
        return r

    # CAUSE OUTRANKS EFFECT: stamp moved AND custom versions moved is ONE event
    # (an engine resave and its bookkeeping), so the engine resave claims the bin.
    r = expect("stamp_move_claims_custom_bump", _rec("/G/M/a"), ENGINE_RESAVE_ONLY, False)
    if not any("custom_versions moved" in e for e in r["evidence"]):
        fails.append("stamp_move_claims_custom_bump: the custom delta must still be "
                     "recorded as corroborating evidence, not discarded")
    # A custom move with NO engine change to explain it IS a version finding.
    expect("custom_move_same_engine",
           _rec("/G/M/a2", cv=dict(_V58, saved_by_engine_branch="5.7")),
           PACKAGE_VERSION_CHANGED, False)
    # Stamp moved, custom versions UNKNOWN -> the resave is witnessed by the stamp.
    expect("resave_custom_unknown",
           _rec("/G/M/b", sv=_no_custom(_V57), cv=_no_custom(_V58)),
           ENGINE_RESAVE_ONLY, False)
    # Stamp moved, custom versions known and EQUAL -> resave only.
    expect("resave_custom_equal",
           _rec("/G/M/c", sv=_V57, cv=dict(_V57, saved_by_engine_branch="5.8")),
           ENGINE_RESAVE_ONLY, False)
    expect("unchanged", _rec("/G/M/d", src="z" * 8, conv="z" * 8,
                             sv=_V57, cv=_V57, declared="5.7"), UNCHANGED, False)
    # Byte-identical but declared converted -> UNCHANGED and flagged unconverted.
    r = expect("unconverted", _rec("/G/M/e", src="z" * 8, conv="z" * 8,
                                   sv=_V57, cv=_V57, declared="5.8"), UNCHANGED, False)
    if not r.get("unconverted"):
        fails.append("unconverted: byte-identical package declared 5.8 but stamped 5.7 "
                     "must be flagged unconverted")
    expect("asset_resave_unknown_actors",
           _rec("/G/A/f", kind="asset", a_src=None, a_conv=None,
                sv=_no_custom(_V57), cv=_no_custom(_V58)),
           ENGINE_RESAVE_ONLY, False)

    # THE CARDINAL SIN must block, and must NOT be masked by a version move.
    expect("actor_loss", _rec("/G/M/g", a_src=214, a_conv=210), ACTOR_GRAPH_CHANGED, True)
    expect("actor_loss_with_version_move",
           _rec("/G/M/h", a_src=214, a_conv=210,
                cv=dict(_V58, file_version_ue5=1019)),
           ACTOR_GRAPH_CHANGED, True)
    expect("actor_gain", _rec("/G/M/i", a_src=210, a_conv=214,
                              sv=_no_custom(_V57), cv=_no_custom(_V58)),
           ACTOR_GRAPH_CHANGED, False)
    expect("core_version_changed",
           _rec("/G/M/j", cv=dict(_V58, file_version_ue5=1019)),
           PACKAGE_VERSION_CHANGED, False)

    # Unknown is guilty.
    expect("deleted", _rec("/G/M/k", status="source_only"), UNCLASSIFIED, True)
    expect("null_hash", _rec("/G/M/l", conv=None), UNCLASSIFIED, True)
    expect("contradiction", _rec("/G/M/m", src="q" * 8, conv="q" * 8, a_src=5, a_conv=4),
           UNCLASSIFIED, True)
    n = _rec("/G/M/n")
    n["converted_package_version"] = None
    expect("null_core_is_unknown", n, UNCLASSIFIED, True)
    # Bytes changed but the SAME engine wrote both -> not an engine resave.
    expect("same_engine_rewrite",
           _rec("/G/M/o", sv=_no_custom(_V57),
                cv=_no_custom(dict(_V57, saved_by_engine_branch="5.7"))),
           UNCLASSIFIED, True)
    # Bytes changed but the stamp is UNKNOWN -> nothing witnesses a resave.
    p = _rec("/G/M/p", sv=_no_custom(_V57), cv=_no_custom(_V58))
    p["converted_package_version"]["saved_by_engine_branch"] = None
    expect("stamp_unknown", p, UNCLASSIFIED, True)

    # The stamp must NEVER be diffed as a version.
    r = classify(_rec("/G/M/q", sv=_no_custom(_V57), cv=_no_custom(_V58)))
    if r["label"] == PACKAGE_VERSION_CHANGED:
        fails.append("engine stamp was diffed as a package version — bogus version claim")
    # A version claim requires a real version delta.
    r = classify(_rec("/G/M/r", sv=_V57, cv=dict(_V57, saved_by_engine_branch="5.8")))
    if r["label"] == PACKAGE_VERSION_CHANGED:
        fails.append("v2.5 bug regressed: version claim with identical versions")
    # UNKNOWN custom versions must never be read as "no custom change".
    r = classify(_rec("/G/M/s", sv=_no_custom(_V57), cv=_no_custom(_V58)))
    if not any("custom_versions=null" in u for u in r["unknown"]):
        fails.append("null custom_versions not recorded as UNKNOWN")

    # CLASS REPLACEMENT AT EQUAL ACTOR COUNT — the bin actor_count cannot see.
    # This is the Untitled shape: total holds at 2, but the Houdini class is gone.
    r = expect("class_replacement_equal_count",
               _rec("/G/M/swap", a_src=2, a_conv=2,
                    ci_src={"HoudiniAssetActor": 1, "StaticMeshActor": 1},
                    ci_conv={"StaticMeshActor": 2}),
               ACTOR_GRAPH_CHANGED, True)
    if "HoudiniAssetActor" not in r["reason"]:
        fails.append("class_replacement: the lost class must be named in the reason")
    # A class gained with nothing lost is reported, not blocked.
    expect("class_gained_only",
           _rec("/G/M/gain", a_src=2, a_conv=2,
                ci_src={"StaticMeshActor": 2},
                ci_conv={"StaticMeshActor": 1, "PointLight": 1}),
           ACTOR_GRAPH_CHANGED, False)
    # Class loss must not be masked by a simultaneous version move.
    expect("class_loss_with_version_move",
           _rec("/G/M/swap2", a_src=2, a_conv=2,
                cv=dict(_V58, file_version_ue5=1019),
                ci_src={"HoudiniAssetActor": 1, "StaticMeshActor": 1},
                ci_conv={"StaticMeshActor": 2}),
           ACTOR_GRAPH_CHANGED, True)
    # Untitled's real shape: identical inventories both sides -> NOT a class event.
    expect("untitled_shape_is_not_a_class_event",
           _rec("/G/M/untitled", a_src=2, a_conv=2,
                sv=_no_custom(_V57), cv=_no_custom(_V58),
                ci_src={"HoudiniAssetActor": 1, "StaticMeshActor": 1},
                ci_conv={"HoudiniAssetActor": 1, "StaticMeshActor": 1}),
           ENGINE_RESAVE_ONLY, False)
    # A null inventory is UNKNOWN and must never read as "no classes".
    r = classify(_rec("/G/A/noinv", kind="asset", a_src=None, a_conv=None,
                      sv=_no_custom(_V57), cv=_no_custom(_V58)))
    if not any("actor_class_inventory=null" in u for u in r["unknown"]):
        fails.append("null actor_class_inventory not recorded as UNKNOWN")
    # The record's evidence must agree with itself.
    expect("inventory_contradicts_actor_count",
           _rec("/G/M/bad", a_src=10, a_conv=10, ci_src={"StaticMeshActor": 9}),
           UNCLASSIFIED, True)

    if undecidable_label_leak([classify(_rec("/G/M/t"))]):
        fails.append("refused label leaked")

    a = audit({"packages": [_rec("/G/M/ok"), _rec("/G/M/lost", a_src=99, a_conv=90)]})
    if not a["release_blocking"]:
        fails.append("audit with actor loss NOT release-blocking (fake-green vector)")
    if a["actor_loss_packages"] != ["/G/M/lost"]:
        fails.append("actor_loss_packages wrong: {}".format(a["actor_loss_packages"]))
    # version_evidence must detect systematic absence.
    ve = audit({"packages": [_rec("/G/M/u", sv=_no_custom(_V57), cv=_no_custom(_V58))]})
    if not ve["version_evidence"]["custom_versions_systematically_absent"]:
        fails.append("systematic absence of custom_versions not detected")
    return fails


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="v2.5.1 evidence-based conversion classifier.")
    ap.add_argument("--manifest", default=str(CANONICAL_MANIFEST))
    ap.add_argument("--out", default=str(REPORT_DIR / REPORT_NAME))
    ap.add_argument("--selftest", action="store_true",
                    help="run negative controls on synthetic records and exit")
    args, _ = ap.parse_known_args(argv)

    if args.selftest:
        fails = _selftest()
        for f in fails:
            print("[conversion-audit]   - {}".format(f))
        print("[conversion-audit] SELFTEST {}".format("FAIL" if fails else "PASS"))
        return 1 if fails else 0

    manifest = load_manifest(args.manifest)
    result = audit(manifest)
    real_ok, real_reasons = is_real_canonical_manifest(manifest)
    key_ok, key_reasons = common_keyspace(manifest)
    result["manifest_path"] = _repo_relative(args.manifest)
    result["real_manifest"] = real_ok
    result["real_manifest_reasons"] = real_reasons
    result["common_keyspace"] = key_ok
    result["common_keyspace_reasons"] = key_reasons

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    ve = result["version_evidence"]
    print("[conversion-audit] manifest={}".format(args.manifest))
    print("[conversion-audit] packages={} real_manifest={} common_keyspace={}".format(
        result["package_count"], real_ok, key_ok))
    for lbl in ALL_LABELS:
        print("[conversion-audit]   {:<24} {}".format(lbl, result["counts_by_label"][lbl]))
    print("[conversion-audit] version evidence known: core={}/{} custom={}/{} "
          "stamp={}/{}".format(ve["core_version_known"], ve["package_count"],
                               ve["custom_versions_known"], ve["package_count"],
                               ve["engine_stamp_known"], ve["package_count"]))
    print("[conversion-audit] actor_class_inventory known: {}/{} ({} map(s))".format(
        result["class_inventory_known"], result["package_count"],
        sum(1 for r in result["results"] if r["package_kind"] == "map")))
    print("[conversion-audit] refused-as-undecidable: {}".format(
        ", ".join(sorted(_UNDECIDABLE))))
    print("[conversion-audit] unclassified={} unaccounted_deletions={} actor_loss={} "
          "unconverted={}".format(
              len(result["unclassified_packages"]), len(result["unaccounted_deletions"]),
              len(result["actor_loss_packages"]), len(result["unconverted_packages"])))
    print("[conversion-audit] release_blocking={}".format(result["release_blocking"]))
    print("[conversion-audit] report -> {}".format(out))
    return 1 if result["release_blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
