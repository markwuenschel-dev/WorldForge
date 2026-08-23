#!/usr/bin/env python3
"""wfcore.contracts.asset_catalog -- the CLOSED set of things Core may build with.

WHY CLOSED AND NOT OPEN
-----------------------
An open catalog -- "here are some assets you may use, plus anything else that
seems to fit" -- cannot be violated, so it authorises everything while reading as
an authorisation of something. Every asset Core places ends up in the consumer's
project, under the consumer's licence, in the consumer's art direction, and the
consumer is the only party who can say yes to that. So the catalog is a closed
world: an asset that is not listed is NOT usable, and its absence is a refusal
rather than a gap for Core to fill in.

That is enforced two ways, and both matter:

  * ``closed_world`` must be literally ``True``. The field exists so the closure
    is a statement the consumer made rather than a convention Core assumed, and a
    catalog that declares itself open is rejected outright (WF1207) instead of
    being quietly honoured -- an open catalog is not a weaker catalog, it is a
    different contract that this module cannot enforce.
  * :func:`authorization_of` returns ``tri.VIOLATED`` for an unlisted asset, not
    ``tri.UNKNOWN``. Absence from a closed set is a decided answer.

WHY ``unreviewed`` IS A REAL AUTHORIZATION VALUE
------------------------------------------------
Consumers onboard assets faster than they review them, and the alternative to
saying "unreviewed" is saying nothing -- which is indistinguishable from "not
mine" once the record is on disk. ``unreviewed`` evaluates to ``tri.UNKNOWN`` and
therefore blocks acceptance: the asset can be catalogued, planned around, and
discussed, but it cannot be shipped into an accepted world until a human says a
word about it. The same reasoning applies to ``approved_with_conditions``, whose
conditions nothing in Core has evaluated -- Core does not get to decide that a
condition it never checked was met.
"""

from typing import Any, Dict, List, Optional

from .. import tri
from ..failure import FailureCode as C
from . import (Check, check_bool, check_enum, check_is_object, check_no_unknown,
               check_required, check_schema_version, check_str, check_str_list,
               require_caller_owned)

RT_ASSET_CATALOG = "wf.core.asset_catalog.v1"
RT_ASSET_CATALOG_ENTRY = "wf.core.asset_catalog_entry.v1"

# --------------------------------------------------------------------------- #
# closed vocabularies. Roles describe what an asset IS STRUCTURALLY, never what
# it depicts: "surface_material" is a role, a named biome or a named prop is a
# consumer's vocabulary and has no business inside Core.
# --------------------------------------------------------------------------- #
ASSET_ROLES = (
    "surface_material",
    "terrain_layer",
    "static_geometry",
    "modular_geometry",
    "skeletal_actor",
    "foliage",
    "decal",
    "light_rig",
    "audio_emitter",
    "volume",
    "marker",
    "effect",
)

APPROVED = "approved"
APPROVED_WITH_CONDITIONS = "approved_with_conditions"
DENIED = "denied"
UNREVIEWED = "unreviewed"
AUTHORIZATIONS = (APPROVED, APPROVED_WITH_CONDITIONS, DENIED, UNREVIEWED)

ASSET_ENTRY_REQUIRED = ("asset_id", "asset_role", "authorization",
                        "source_reference")
ASSET_ENTRY_ALLOWED = ASSET_ENTRY_REQUIRED + (
    "style_tags", "conditions", "denial_reason", "variant_of", "notes",
)

ASSET_CATALOG_REQUIRED = (
    "catalog_id",
    "consumer_id",
    "closed_world",
    "entries",
    "style_families",
    "schema_version",
)
ASSET_CATALOG_ALLOWED = ASSET_CATALOG_REQUIRED + (
    "created_by", "created_at", "report_type", "meta", "notes",
)

# The catalog names the consumer's own content. Every one of these is a fact only
# the consumer can state; a Core default would be Core authorising itself.
CALLER_OWNED_FIELDS = ("catalog_id", "consumer_id", "entries")

_P = "cat::"


def validate_asset_catalog(obj: Any, strict: bool = False) -> List[Check]:
    """Validate a catalog and every entry in it."""
    code = C.CORE_ASSET_CATALOG_INVALID
    ch = check_is_object(obj, code, _P, "asset_catalog")
    if ch:
        return ch

    ch += check_required(obj, ASSET_CATALOG_REQUIRED, code, _P)
    ch += check_no_unknown(obj, ASSET_CATALOG_ALLOWED, code, _P, strict)
    ch += check_str(obj, "catalog_id", code, _P)
    ch += check_str(obj, "consumer_id", code, _P)
    ch += check_bool(obj, "closed_world", code, _P)
    ch += check_schema_version(obj, RT_ASSET_CATALOG, code, _P)

    # --- the closure itself ---------------------------------------------------
    closed = obj.get("closed_world")
    ok = closed is True
    ch.append((_P + "catalog_is_closed_world", ok,
               "closed_world={!r} must be exactly True; an open catalog cannot "
               "be violated, so it authorises everything while reading as an "
               "authorisation of something".format(closed),
               None if ok else code))

    entries = obj.get("entries")
    if not isinstance(entries, (list, tuple)):
        ch.append((_P + "entries_is_list", False,
                   "entries must be a list, got {}".format(type(entries).__name__),
                   code))
        return ch

    ok = len(entries) > 0
    ch.append((_P + "entries_non_empty", ok,
               "catalog carries {} entr(ies); an empty CLOSED catalog authorises "
               "nothing at all while still reading, in a report, as a catalog"
               .format(len(entries)), None if ok else code))

    for idx, entry in enumerate(entries):
        for (name, e_ok, detail, e_code) in validate_asset_entry(entry, strict=strict):
            ch.append(("{}entry[{}].{}".format(_P, idx, name), e_ok, detail, e_code))

    ids = [e.get("asset_id") for e in entries if isinstance(e, dict)]
    dupes = sorted({i for i in ids if i is not None and ids.count(i) > 1})
    ok = not dupes
    ch.append((_P + "asset_ids_unique", ok,
               "duplicate asset_id(s) {}; a duplicate makes an authorisation "
               "lookup ambiguous, and the shadowed record is invisible"
               .format(dupes) if dupes else "all asset_ids unique",
               None if ok else code))

    ch += _rail_style_families(obj, entries, code)
    ch += _rail_variant_targets_resolve(entries, code)
    return ch


def validate_asset_entry(entry: Any, strict: bool = False) -> List[Check]:
    """Validate ONE catalog entry.

    The conditional rails are where the honesty lives: a conditional approval
    with no conditions, and a denial with no reason, are both records that carry a
    verdict nobody can act on or appeal.
    """
    code = C.CORE_ASSET_CATALOG_INVALID
    ch = check_is_object(entry, code, "", "catalog entry")
    if ch:
        return ch

    ch += check_required(entry, ASSET_ENTRY_REQUIRED, code, "")
    ch += check_no_unknown(entry, ASSET_ENTRY_ALLOWED, code, "", strict)
    ch += check_str(entry, "asset_id", code, "")
    ch += check_str(entry, "source_reference", code, "")
    ch += check_enum(entry, "asset_role", ASSET_ROLES, code, "")
    ch += check_enum(entry, "authorization", AUTHORIZATIONS, code, "")

    if "style_tags" in entry:
        ch += check_str_list(entry, "style_tags", code, "", min_len=0)

    auth = entry.get("authorization")

    if auth == APPROVED_WITH_CONDITIONS:
        conditions = entry.get("conditions")
        ok = (isinstance(conditions, (list, tuple)) and len(conditions) > 0
              and all(isinstance(c, str) and c.strip() for c in conditions))
        ch.append(("conditional_approval_states_conditions", ok,
                   "authorization={!r} with conditions={!r}; a conditional "
                   "approval whose conditions are unstated is an unconditional "
                   "approval that reads as a careful one".format(auth, conditions),
                   None if ok else code))

    if auth == DENIED:
        reason = entry.get("denial_reason")
        ok = isinstance(reason, str) and bool(reason.strip())
        ch.append(("denial_states_reason", ok,
                   "authorization={!r} with denial_reason={!r}; a denial nobody "
                   "can read cannot be appealed or re-reviewed, so the asset is "
                   "excluded permanently by accident".format(auth, reason),
                   None if ok else code))

    return ch


def _rail_style_families(obj: Dict[str, Any], entries: List[Any],
                         code: str) -> List[Check]:
    """A style family may only gather assets this catalog actually authorises.

    Two failure modes, both invisible without this rail: a family naming an asset
    that is not in the catalog (Core would select a style and then have nothing
    legal to place), and a family containing a DENIED asset (Core would select a
    style whose members it must refuse -- the denial and the family disagree, and
    whichever is read last wins).
    """
    out: List[Check] = []
    families = obj.get("style_families")
    if not isinstance(families, (list, tuple)):
        return [(_P + "style_families_is_list", False,
                 "style_families must be a list (use [] to state that this "
                 "catalog groups nothing), got {}".format(type(families).__name__),
                 code)]

    by_id = {e.get("asset_id"): e for e in entries if isinstance(e, dict)}
    family_ids: List[Any] = []
    dangling: List[str] = []
    denied_members: List[str] = []
    malformed = 0

    for fam in families:
        if not isinstance(fam, dict):
            malformed += 1
            continue
        family_ids.append(fam.get("style_id"))
        members = fam.get("member_asset_ids")
        if not isinstance(members, (list, tuple)) or not members:
            malformed += 1
            continue
        for m in members:
            if m not in by_id:
                dangling.append("{}:{}".format(fam.get("style_id"), m))
            elif by_id[m].get("authorization") == DENIED:
                denied_members.append("{}:{}".format(fam.get("style_id"), m))

    ok = malformed == 0
    out.append((_P + "style_families_well_formed", ok,
                "{} style family/families are not objects with a non-empty "
                "member_asset_ids list".format(malformed) if malformed
                else "every style family is an object with members",
                None if ok else code))

    dupes = sorted({i for i in family_ids
                    if i is not None and family_ids.count(i) > 1})
    ok = not dupes
    out.append((_P + "style_family_ids_unique", ok,
                "duplicate style_id(s) {}".format(dupes) if dupes
                else "all style_ids unique", None if ok else code))

    ok = not dangling
    out.append((_P + "style_family_members_resolve", ok,
                "style family member(s) {} name no entry in this catalog; a "
                "style Core can select but cannot populate is a dead end it "
                "discovers only at placement time".format(dangling) if dangling
                else "every style family member resolves to an entry",
                None if ok else code))

    ok = not denied_members
    out.append((_P + "style_family_excludes_denied", ok,
                "style family member(s) {} are DENIED entries; the family and "
                "the denial contradict each other, and whichever is read last "
                "wins".format(denied_members) if denied_members
                else "no style family gathers a denied asset",
                None if ok else code))
    return out


def _rail_variant_targets_resolve(entries: List[Any], code: str) -> List[Check]:
    """``variant_of`` must name an asset in this same catalog."""
    ids = {e.get("asset_id") for e in entries if isinstance(e, dict)}
    dangling = sorted({
        e.get("variant_of") for e in entries
        if isinstance(e, dict) and e.get("variant_of") is not None
        and e.get("variant_of") not in ids})
    ok = not dangling
    return [(_P + "variant_targets_resolve", ok,
             "variant_of {} names no entry in this catalog; the variant inherits "
             "authorisation from a record that is not here".format(dangling)
             if dangling else "every variant_of resolves within this catalog",
             None if ok else code)]


def authorization_of(catalog: Dict[str, Any], asset_id: str) -> str:
    """Tri-verdict for "may Core use this asset?". Assumes a VALIDATED catalog.

    ==============================  ==================================================
    catalog state                   verdict
    ==============================  ==================================================
    ``approved``                    SATISFIED -- the consumer said yes
    ``approved_with_conditions``    UNKNOWN -- conditions exist and Core evaluated none
    ``denied``                      VIOLATED -- the consumer said no
    ``unreviewed``                  UNKNOWN -- nobody has said anything yet
    not present                     VIOLATED -- absence from a CLOSED set is a refusal
    ==============================  ==================================================

    The two UNKNOWN rows are the point. Neither may be rounded up to SATISFIED
    for convenience: doing so would let Core ship an asset on the strength of a
    condition it never checked, or on no review at all, and the resulting world
    would pass acceptance while carrying content nobody approved.
    """
    entry = find_entry(catalog, asset_id)
    if entry is None:
        return tri.VIOLATED
    auth = entry.get("authorization")
    if auth == APPROVED:
        return tri.SATISFIED
    if auth == DENIED:
        return tri.VIOLATED
    return tri.UNKNOWN


def find_entry(catalog: Dict[str, Any], asset_id: str) -> Optional[Dict[str, Any]]:
    for entry in (catalog.get("entries") or []):
        if isinstance(entry, dict) and entry.get("asset_id") == asset_id:
            return entry
    return None


def build_asset_catalog(**over: Any) -> Dict[str, Any]:
    """Build a catalog. ``CALLER_OWNED_FIELDS`` are REQUIRED -- no defaults.

    ``closed_world`` defaults to ``True`` because that is Core's rule rather than
    the consumer's choice: this module can only enforce a closed catalog, so it
    builds one. A consumer that wants an open catalog is asking for a different
    contract, and it will be rejected at validation with the reason spelled out.
    """
    require_caller_owned(over, CALLER_OWNED_FIELDS, "asset_catalog")
    d: Dict[str, Any] = dict(
        closed_world=True,
        style_families=[],
        schema_version=RT_ASSET_CATALOG,
        report_type=RT_ASSET_CATALOG,
    )
    d.update(over)
    return d


def _example_asset_entry(**over: Any) -> Dict[str, Any]:
    """Canonical-valid entry. Ids are neutral placeholders by construction."""
    d: Dict[str, Any] = {
        "asset_id": "asset_placeholder_surface_01",
        "asset_role": "surface_material",
        "authorization": APPROVED,
        "source_reference": "consumer://catalog/surface/placeholder_01",
        "style_tags": ["style_tag_a"],
    }
    d.update(over)
    return d


def _example_asset_catalog(**over: Any) -> Dict[str, Any]:
    """Canonical-valid catalog. ``**over`` spawns the known-bads."""
    d: Dict[str, Any] = dict(
        catalog_id="catalog_placeholder",
        consumer_id="consumer_placeholder",
        entries=[
            _example_asset_entry(),
            _example_asset_entry(
                asset_id="asset_placeholder_geometry_01",
                asset_role="static_geometry",
                source_reference="consumer://catalog/geometry/placeholder_01",
                style_tags=["style_tag_a"]),
            _example_asset_entry(
                asset_id="asset_placeholder_foliage_01",
                asset_role="foliage",
                authorization=UNREVIEWED,
                source_reference="consumer://catalog/foliage/placeholder_01",
                style_tags=["style_tag_b"]),
            _example_asset_entry(
                asset_id="asset_placeholder_effect_01",
                asset_role="effect",
                authorization=DENIED,
                denial_reason="withdrawn by the consumer pending licence review",
                source_reference="consumer://catalog/effect/placeholder_01"),
        ],
        style_families=[
            {
                "style_id": "style_family_a",
                "member_asset_ids": [
                    "asset_placeholder_surface_01",
                    "asset_placeholder_geometry_01",
                ],
            },
        ],
    )
    d.update(over)
    return build_asset_catalog(**d)
