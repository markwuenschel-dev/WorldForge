#!/usr/bin/env python3
"""observation_intake -- read a caller's live evidence into the observed world.

THE GAP THIS FILLS
------------------
A consumer adapter declares ``runtime_state_access``: a channel the game OFFERS,
naming where it writes measurements of its own live world. ``consumers.adapter``
validates that the declaration is well-formed and then -- as its own field notes
admit -- reads nothing through it. It is "a channel, not a reader".

The consequence ran all the way to the end of the pipeline. Every field of the
observed world stayed ``not_observed``, ``reconcile`` refused for want of a
measured world, and acceptance folded to UNKNOWN. All of that was CORRECT
behaviour on unbacked input; none of it could ever change, because nothing was
ever going to back the input. This module is the reader.

WHY A MAPPING, AND WHY IT CANNOT LIE
------------------------------------
The caller emits its own artifact schema. WorldForge is forbidden by its own
hygiene gate from naming any game, so Core cannot learn that schema. The bridge
is a MAPPING the caller declares: which of its artifact fields answers which
observation key.

That immediately raises the obvious objection, and it is a serious one: if the
caller supplies both the measurement and the statement of what the measurement
means, the caller can assert anything, and we are back to self-attestation
wearing an evidence schema. Three structural rails answer it:

1. **A mapping SELECTS; it never COMPUTES.** ``value_shape`` picks one of a
   CLOSED set of readers implemented here. There is no expression language, no
   arithmetic, no default, no fallback literal. A mapping cannot produce a value
   that is not already sitting in the artifact -- not because it is discouraged,
   but because the vocabulary offers no way to say it.

2. **A mapping cannot declare provenance.** There is no provenance field in the
   mapping schema, and ``build_observed_world`` stamps ``measured`` only on a
   value it actually read out of a file it actually opened. A caller cannot mark
   its own guess as measured, because the word is not available to it.

3. **A required-but-unsatisfied artifact FAILS; it never vanishes.** An artifact
   whose ``require`` predicates do not hold produces ``observation_failed`` with
   the reason. It is not skipped. Skipping is how a witnessed negative turns
   silently into an absence, and an absence reads as "nothing to worry about".

What remains genuinely un-defended, stated plainly rather than papered over: a
caller that writes a false number into its own artifact will have that false
number read as measured. No reader on this side can detect that, and pretending
otherwise would be worse than naming it. What this module guarantees is narrower
and still worth having -- that the value in the model is the value in the file,
that the file existed and satisfied its stated preconditions, and that every
backed field can be traced to a locator a human can open.

House style: stdlib only; ``validate_X(...) -> List[Check]``.
"""

import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from wfcore.failure import FailureCode as C          # noqa: E402
from wfcore.models import observed_world as OW       # noqa: E402
from wfcore.models.desired_world import WORLD_IDENTITY_KEYS  # noqa: E402

RT_OBSERVATION_MAPPING = "wf.core.observation_mapping.v1"
COLLECTOR = "pipeline.observation_intake"
# From Core's closed evidence vocabulary. A caller telemetry file is a
# structured measurement record, not a log or a capture.
EVIDENCE_KIND = "record"

_P = "observation_intake."

# THE CLOSED READER SET. This tuple is the whole anti-fabrication argument: a
# mapping chooses one of these and supplies a path, and that is the entire
# expressive power available to it. Adding an entry is a visible contract change
# in one tuple; a mapping cannot add one by writing something clever.
SHAPE_XYZ_OBJECT = "xyz_object"      # {"x":..,"y":..,"z":..} -> [x,y,z]
SHAPE_XYZ_ARRAY = "xyz_array"        # [x,y,z]                -> [x,y,z]
SHAPE_NUMBER = "scalar_number"
SHAPE_STRING = "scalar_string"
SHAPE_BOOL = "scalar_bool"
VALUE_SHAPES = (SHAPE_XYZ_OBJECT, SHAPE_XYZ_ARRAY, SHAPE_NUMBER,
                SHAPE_STRING, SHAPE_BOOL)

MAPPING_ENTRY_REQUIRED = ("observation_key", "section", "entity_id", "field",
                          "select", "value_path", "value_shape")
MAPPING_ENTRY_ALLOWED = MAPPING_ENTRY_REQUIRED + ("require", "detail")
MAPPING_REQUIRED = ("mapping_id", "consumer_id", "artifact_root",
                    "artifact_glob", "entries", "schema_version")
MAPPING_ALLOWED = MAPPING_REQUIRED + ("created_by", "detail", "report_type")

# Words a mapping must never contain. Their presence means the author expected
# to be able to state a value or a provenance, and an author who expected that
# has misunderstood the contract badly enough that failing loudly is kinder than
# ignoring the key.
FORBIDDEN_MAPPING_KEYS = ("value", "default", "provenance", "expression",
                          "compute", "fallback", "measured", "observed_by")


# --------------------------------------------------------------------------- #
# mapping validation
# --------------------------------------------------------------------------- #
def validate_observation_mapping(mapping, strict=False):
    code = C.CORE_OBSERVATION_MAPPING_INVALID
    out = []
    is_obj = isinstance(mapping, dict)
    out.append((_P + "mapping_is_object", is_obj,
                "mapping must be an object (got {})".format(
                    type(mapping).__name__), None if is_obj else code))
    if not is_obj:
        return out

    for f in MAPPING_REQUIRED:
        ok = f in mapping
        out.append((_P + "mapping_has_" + f, ok,
                    "mapping is missing required field {!r}".format(f),
                    None if ok else code))

    sv = mapping.get("schema_version")
    out.append((_P + "mapping_schema_version", sv == RT_OBSERVATION_MAPPING,
                "schema_version must be {!r} (got {!r})".format(
                    RT_OBSERVATION_MAPPING, sv),
                None if sv == RT_OBSERVATION_MAPPING else code))

    extra = sorted(set(mapping) - set(MAPPING_ALLOWED))
    out.append((_P + "mapping_no_unknown_keys", not extra,
                "unknown mapping keys {}; the vocabulary is closed so that a "
                "caller cannot smuggle a value in beside the selector".format(
                    extra), None if not extra else code))

    entries = mapping.get("entries")
    ok = isinstance(entries, list) and len(entries) >= 1
    out.append((_P + "mapping_has_entries", ok,
                "entries must be a non-empty list (got {!r})".format(
                    type(entries).__name__), None if ok else code))
    if not ok:
        return out

    seen, targets = set(), set()
    for i, e in enumerate(entries):
        pfx = _P + "entry[{}].".format(i)
        if not isinstance(e, dict):
            out.append((pfx + "is_object", False,
                        "entry must be an object (got {})".format(
                            type(e).__name__), code))
            continue
        for f in MAPPING_ENTRY_REQUIRED:
            has = f in e
            out.append((pfx + "has_" + f, has,
                        "entry missing required field {!r}".format(f),
                        None if has else code))

        bad = sorted(set(e) - set(MAPPING_ENTRY_ALLOWED))
        out.append((pfx + "no_unknown_keys", not bad,
                    "unknown entry keys {}".format(bad),
                    None if not bad else code))

        # RAIL 1: the vocabulary offers no way to state a value or a provenance.
        smuggled = sorted(k for k in e if k.lower() in FORBIDDEN_MAPPING_KEYS)
        out.append((pfx + "declares_no_value_or_provenance", not smuggled,
                    "entry carries {} -- a mapping SELECTS a value out of an "
                    "artifact and never supplies, defaults or computes one, and "
                    "it never states its own provenance. WorldForge stamps "
                    "'measured' only on a value it read from a file it "
                    "opened".format(smuggled),
                    None if not smuggled else C.CORE_OBSERVATION_VALUE_FABRICATED))

        shape = e.get("value_shape")
        ok_shape = shape in VALUE_SHAPES
        out.append((pfx + "value_shape_known", ok_shape,
                    "value_shape {!r} must be one of {} -- the reader set is "
                    "closed on purpose".format(shape, list(VALUE_SHAPES)),
                    None if ok_shape else code))

        vp = e.get("value_path")
        ok_vp = (isinstance(vp, list) and len(vp) >= 1
                 and all(isinstance(s, str) and s for s in vp))
        out.append((pfx + "value_path_is_field_path", ok_vp,
                    "value_path must be a non-empty list of field names (got "
                    "{!r}); it addresses a location, it is not an "
                    "expression".format(vp), None if ok_vp else code))

        sel = e.get("select")
        ok_sel = isinstance(sel, dict) and len(sel) >= 1
        out.append((pfx + "select_is_nonempty_object", ok_sel,
                    "select must be a non-empty object of field->value "
                    "equality tests (got {!r}). An empty selector would match "
                    "every artifact, which is not a measurement of "
                    "anything".format(sel), None if ok_sel else code))

        sec = e.get("section")
        ok_sec = sec in OW.OBSERVED_SECTIONS
        out.append((pfx + "section_known", ok_sec,
                    "section {!r} must be one of {}".format(
                        sec, list(OW.OBSERVED_SECTIONS)),
                    None if ok_sec else code))

        key = e.get("observation_key")
        dupe = key in seen
        seen.add(key)
        out.append((pfx + "observation_key_unique", not dupe,
                    "observation_key {!r} is mapped twice".format(key),
                    None if not dupe else code))

        # The one that actually matters, and the reason this rail is separate:
        # observation_key is a LABEL, but (section, entity_id, field) is the
        # ADDRESS. Two entries with different labels can name one address, and
        # then the last one written silently wins -- which was observed turning
        # a measured field into a failed one purely by ordering. Uniqueness must
        # be checked on the address, not on the label.
        target = (e.get("section"), e.get("entity_id"), e.get("field"))
        tdupe = target in targets
        targets.add(target)
        out.append((pfx + "target_field_unique", not tdupe,
                    "two entries write the same observed field {}; two sources "
                    "for one field is an ambiguity nobody can adjudicate, and "
                    "whichever lands last would silently win".format(target),
                    None if not tdupe else code))
    return out


# --------------------------------------------------------------------------- #
# the closed reader set
# --------------------------------------------------------------------------- #
def _dig(doc, path):
    """(found, value). Literal traversal only -- no wildcards, no defaults."""
    cur = doc
    for seg in path:
        if not isinstance(cur, dict) or seg not in cur:
            return False, None
        cur = cur[seg]
    return True, cur


def _coerce(raw, shape):
    """(ok, value, reason). Shape-checks what was read; never invents."""
    if shape == SHAPE_XYZ_OBJECT:
        if not isinstance(raw, dict):
            return False, None, "expected an object with x/y/z, got {}".format(
                type(raw).__name__)
        for k in ("x", "y", "z"):
            if not isinstance(raw.get(k), (int, float)) or isinstance(
                    raw.get(k), bool):
                return False, None, "member {!r} is not a number: {!r}".format(
                    k, raw.get(k))
        return True, [float(raw["x"]), float(raw["y"]), float(raw["z"])], ""
    if shape == SHAPE_XYZ_ARRAY:
        if not (isinstance(raw, list) and len(raw) == 3
                and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        for v in raw)):
            return False, None, "expected a 3-number array, got {!r}".format(raw)
        return True, [float(v) for v in raw], ""
    if shape == SHAPE_NUMBER:
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            return False, None, "expected a number, got {!r}".format(raw)
        return True, float(raw), ""
    if shape == SHAPE_STRING:
        if not isinstance(raw, str):
            return False, None, "expected a string, got {!r}".format(raw)
        return True, raw, ""
    if shape == SHAPE_BOOL:
        if not isinstance(raw, bool):
            return False, None, "expected a bool, got {!r}".format(raw)
        return True, raw, ""
    return False, None, "unknown value_shape {!r}".format(shape)


# --------------------------------------------------------------------------- #
# artifact scanning
# --------------------------------------------------------------------------- #
def load_artifacts(root, pattern):
    """[(locator, doc_or_None, error_or_None)] -- unreadable files are KEPT.

    A file that could not be parsed is carried through as an error rather than
    dropped. Dropping it would make a corrupt artifact indistinguishable from an
    artifact that was never written, and those want different responses.
    """
    out = []
    if not root or not os.path.isdir(root):
        return out
    for path in sorted(glob.glob(os.path.join(root, pattern))):
        try:
            with open(path, encoding="utf-8") as fh:
                out.append((path, json.load(fh), None))
        except (OSError, ValueError) as exc:
            out.append((path, None, "{}: {}".format(type(exc).__name__, exc)))
    return out


def _matches(doc, select):
    return all(doc.get(k) == v for k, v in (select or {}).items())


def _pick(candidates):
    """Deterministic choice among matches: newest declared time, then locator.

    Uses the artifact's OWN declared timestamp, never file mtime -- mtime moves
    when a file is copied or re-saved and has been caught in this repository
    reporting a stale artifact as fresh.
    """
    return sorted(candidates,
                  key=lambda c: (str(c[1].get("created_at") or ""), c[0]))[-1]


# --------------------------------------------------------------------------- #
# intake
# --------------------------------------------------------------------------- #
def read_observations(mapping, operation_id, artifact_root=None):
    """Resolve every mapping entry against artifacts on disk.

    Returns ``(results, operations, evidence)``. A result is always produced for
    every entry -- backed, failed, or unobserved -- because a missing result and
    a negative result are different facts and only one of them is alarming.
    """
    root = artifact_root or mapping.get("artifact_root")
    pattern = mapping.get("artifact_glob") or "*.json"
    artifacts = load_artifacts(root, pattern)

    unreadable = [(loc, err) for (loc, doc, err) in artifacts if err]
    readable = [(loc, doc) for (loc, doc, err) in artifacts if err is None]

    results, operations, evidence = [], [], {}
    operations.append(OW.operation(
        operation_id=operation_id,
        operation_kind=OW.OP_STATE_READ,
        collector=COLLECTOR,
        ok=bool(readable),
        detail="scanned {} for {}: {} readable, {} unreadable ({})".format(
            root, pattern, len(readable), len(unreadable),
            [u[0] for u in unreadable][:3])))

    for entry in mapping.get("entries", []):
        key = entry.get("observation_key")
        sel = entry.get("select") or {}
        req = entry.get("require") or {}
        cands = [(loc, doc) for (loc, doc) in readable
                 if isinstance(doc, dict) and _matches(doc, sel)]

        if not cands:
            results.append({
                "entry": entry, "state": "not_observed", "locator": None,
                "field": OW.not_observed(
                    "no artifact under {} matched selector {} -- the caller has "
                    "not measured this yet".format(root, sel)),
            })
            continue

        # Artifacts matched but FAILED their preconditions. This is the branch
        # that must never collapse into 'not_observed': something was measured
        # and it did not hold, which is information.
        satisfying = [(loc, doc) for (loc, doc) in cands if _matches(doc, req)]
        if req and not satisfying:
            loc, doc = _pick(cands)
            unmet = {k: (v, doc.get(k)) for k, v in req.items()
                     if doc.get(k) != v}
            results.append({
                "entry": entry, "state": "observation_failed", "locator": loc,
                "field": OW.observation_failed(
                    "{} artifact(s) matched {} but none satisfied {}. Nearest: "
                    "{} with unmet {} (wanted, got). A measurement that did not "
                    "hold is not an absence".format(
                        len(cands), sel, req, loc, unmet),
                    operation_id=operation_id, observed_by=COLLECTOR),
            })
            evidence[loc] = OW.evidence_entry(
                EVIDENCE_KIND, loc, operation_id,
                "matched selector, failed require")
            continue

        loc, doc = _pick(satisfying or cands)
        found, raw = _dig(doc, entry.get("value_path") or [])
        if not found:
            results.append({
                "entry": entry, "state": "observation_failed", "locator": loc,
                "field": OW.observation_failed(
                    "artifact {} satisfied its preconditions but carries no "
                    "value at {}. The mapping addresses a location that is not "
                    "there; nothing is substituted for it".format(
                        loc, entry.get("value_path")),
                    operation_id=operation_id, observed_by=COLLECTOR),
            })
            evidence[loc] = OW.evidence_entry(
                EVIDENCE_KIND, loc, operation_id,
                "value_path absent")
            continue

        ok, value, why = _coerce(raw, entry.get("value_shape"))
        if not ok:
            results.append({
                "entry": entry, "state": "observation_failed", "locator": loc,
                "field": OW.observation_failed(
                    "value at {} in {} does not fit declared shape {!r}: "
                    "{}".format(entry.get("value_path"), loc,
                                entry.get("value_shape"), why),
                    operation_id=operation_id, observed_by=COLLECTOR),
            })
            evidence[loc] = OW.evidence_entry(
                EVIDENCE_KIND, loc, operation_id, "shape mismatch")
            continue

        # The only path that produces MEASURED, and it required opening a file
        # and finding the value literally present in it.
        results.append({
            "entry": entry, "state": "measured", "locator": loc,
            "field": OW.measured(
                value=value, operation_id=operation_id, observed_by=COLLECTOR,
                evidence_refs=(loc,),
                detail="read from {} at {} as {}".format(
                    loc, entry.get("value_path"), entry.get("value_shape"))),
        })
        evidence[loc] = OW.evidence_entry(
            EVIDENCE_KIND, loc, operation_id,
            "backs observation_key {}".format(key))

    return results, operations, evidence


def build_observed_world(mapping, operation_id, world_identity=None,
                         artifact_root=None, created_by=COLLECTOR):
    """A valid ``wf.core.observed_world.v1`` backed by the caller's artifacts."""
    results, operations, evidence = read_observations(
        mapping, operation_id, artifact_root=artifact_root)

    unmapped = ("no mapping entry addresses this field, so nothing measured it")

    # world_identity is the load-bearing one. Core requires every key of
    # WORLD_IDENTITY_KEYS on a BACKED identity, because a partial identity
    # compares equal on whichever keys it happens to carry -- which is how two
    # different worlds reconcile cleanly. A caller that did not fully identify
    # the world it measured leaves this not_observed, and reconcile then refuses
    # rather than comparing against a world nobody bound.
    ident_ok = (isinstance(world_identity, dict)
                and all(world_identity.get(k) not in (None, "")
                        for k in WORLD_IDENTITY_KEYS))
    backing = tuple(r["locator"] for r in results
                    if r["state"] == "measured" and r["locator"])[:1]
    if ident_ok and backing:
        identity_field = OW.measured(
            value={k: world_identity[k] for k in WORLD_IDENTITY_KEYS},
            operation_id=operation_id, observed_by=COLLECTOR,
            evidence_refs=backing,
            detail="the world these measurements came from, carried from the "
                   "caller's artifacts and cited to one of them")
    else:
        identity_field = OW.not_observed(
            "world identity is {} and backing evidence is {} -- an identity "
            "with no artifact behind it would let reconcile proceed against a "
            "world nobody bound".format(
                "complete" if ident_ok else "incomplete/absent",
                "present" if backing else "absent"))

    model = {
        "world_identity": identity_field,
        "observation_operations": operations,
        "evidence_index": dict(evidence),
        "created_by": created_by,
        "schema_version": OW.RT_OBSERVED_WORLD,
        "report_type": OW.RT_OBSERVED_WORLD,
    }
    for section in OW.OBSERVED_SECTIONS:
        model[section] = {OW.ENUMERATION_KEY: OW.not_observed(unmapped),
                          OW.ENTITIES_KEY: {}}

    for r in results:
        e = r["entry"]
        sec = model.get(e.get("section"))
        if not isinstance(sec, dict):
            continue
        ent = sec[OW.ENTITIES_KEY].setdefault(e.get("entity_id"), {})
        fld = e.get("field")
        if fld in ent:
            # Belt and braces behind the validator rail above. If two entries do
            # reach here for one address, the field becomes an explicit conflict
            # rather than whichever result happened to be processed last.
            ent[fld] = OW.observation_failed(
                "two mapping entries write {}.{}.{}; the model refuses to pick "
                "one. Fix the mapping -- this is not resolvable by "
                "precedence".format(e.get("section"), e.get("entity_id"), fld),
                operation_id=operation_id, observed_by=COLLECTOR)
            continue
        ent[fld] = r["field"]

    return model, results


def intake_census(results):
    """What was actually backed. Reported, never asserted in a comment."""
    by = {}
    for r in results:
        by[r["state"]] = by.get(r["state"], 0) + 1
    return {
        "entries": len(results),
        "measured": by.get("measured", 0),
        "observation_failed": by.get("observation_failed", 0),
        "not_observed": by.get("not_observed", 0),
        "backed_keys": sorted(r["entry"].get("observation_key")
                              for r in results if r["state"] == "measured"),
        "failed_keys": sorted(r["entry"].get("observation_key")
                              for r in results
                              if r["state"] == "observation_failed"),
    }


# --------------------------------------------------------------------------- #
# the bridge into generation
# --------------------------------------------------------------------------- #
def anchors_from_observed(model, section, entity_ids, field="location_cm"):
    """Observed fields -> the anchor list the placement planner consumes.

    An UNBACKED field yields ``location_cm: None``, which the planner refuses
    on. That pairing is the whole point of the bridge: the refusal happens in
    one place, for one reason, with the anchor named -- rather than each
    consumer inventing its own idea of what a missing measurement means.

    A field whose observation FAILED is carried through as None too, but the
    reason is preserved on the anchor so the refusal can say which of the two
    happened. "Nobody measured it" and "it was measured and did not hold" send a
    reader to different places.
    """
    fields = OW.field_map(model)
    out = []
    for eid in entity_ids:
        path = "{}.{}.{}.{}".format(section, OW.ENTITIES_KEY, eid, field)
        f = fields.get(path) or {}
        backed = f.get("provenance") in OW.BACKED_PROVENANCE
        out.append({
            "anchor_id": eid,
            "location_cm": f.get("value") if backed else None,
            "provenance": f.get("provenance") or "absent_from_model",
            "detail": f.get("detail"),
        })
    return out
