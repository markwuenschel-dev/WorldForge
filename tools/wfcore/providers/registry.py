#!/usr/bin/env python3
"""wfcore.providers.registry -- the capability registry Core does not have yet.

WHY THIS EXISTS
---------------
``docs/architecture/forge_design_decisions.md`` D19 (lines 316-321) states the
gap plainly: a real WorldForgeCore runtime capability registry -- "none exists
today"; the only ``Register*`` call in the whole plugin registers a console
command. Every capability today is reached by a hardcoded path from a caller who
already knew which tool to use. That is the thing this module replaces, on the
Python side, ahead of the native crossing: a place where capability is looked up
by WHAT IT DOES, so that adding a second provider of the same capability is a
registration rather than an edit to every call site.

WHAT A REGISTRY IS AND IS NOT
-----------------------------
It IS: an index from capability -> providers, an authority on provider identity
uniqueness, and a reporter of collisions.

It is NOT a selector. Looking up two providers for one capability is the normal,
healthy case -- it is exactly the situation a platform wants, and resolving it
needs the consumer's request, which the registry does not have. So the registry
returns ALL matches, in a deterministic order, and leaves the choice to
``selection``. A registry that quietly returned "the best one" would be making
the decision in the one place that has no information to make it with.

COLLISIONS ARE REPORTED, NOT REJECTED
-------------------------------------
A capability offered by several providers is a collision. It is not an error --
but it MUST be visible, because it is the precondition for an unexplained pick.
``collisions()`` surfaces them, and the snapshot validator rails on a snapshot
that under-reports them (WF1229): a registry claiming a capability has one
provider when it has two is how "which one ran?" stops being answerable.

REGISTRATION IS FAIL-CLOSED
---------------------------
An invalid declaration is NOT stored. Storing it and hoping selection filters it
later means a malformed provider is a live candidate for however long the process
runs, and its badness surfaces as a confusing selection result rather than as a
registration failure with a code.
"""

from typing import Any, Dict, List, Optional, Tuple

from ..failure import FailureCode as C
from .base import (
    CAPABILITIES,
    Check,
    validate_provider_declaration,
)

RT_CAPABILITY_REGISTRY = "wf.core.capability_registry.v1"

REGISTRY_SNAPSHOT_REQUIRED = (
    "registry_id", "providers", "capability_index", "collisions", "schema_version",
)
REGISTRY_SNAPSHOT_ALLOWED = REGISTRY_SNAPSHOT_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes",
)


class CapabilityRegistry(object):
    """Capability -> providers, with identity uniqueness and collision reporting.

    Ordering is deterministic everywhere (sorted by ``provider_id``). Insertion
    order must never be observable in a result: it is a property of how the
    process happened to boot, and letting it leak into selection makes a build
    reproducible only by accident.
    """

    def __init__(self) -> None:
        self._by_id: Dict[str, Dict[str, Any]] = {}

    # -- registration ------------------------------------------------------- #
    def register(self, declaration: Any, strict: bool = False) -> List[Check]:
        """Validate and store ONE declaration. Returns house-shape checks.

        Fail-closed: if any check fails, nothing is stored. The caller can tell
        by re-reading the checks -- and by ``provider_id not in registry``.
        """
        checks: List[Check] = list(validate_provider_declaration(declaration, strict=strict))

        provider_id = declaration.get("provider_id") if isinstance(declaration, dict) else None
        if isinstance(provider_id, str) and provider_id:
            fresh = provider_id not in self._by_id
            checks.append(("registry_provider_id_unique", fresh,
                           "provider_id {!r} is already registered; a duplicate identity "
                           "makes every selection result ambiguous about which "
                           "declaration it ranked".format(provider_id) if not fresh
                           else "provider_id {!r} is unique in this registry".format(provider_id),
                           None if fresh else C.CORE_PROVIDER_DECLARATION_INVALID))

        if all(ok for (_n, ok, _d, _c) in checks):
            self._by_id[provider_id] = dict(declaration)
        return checks

    def register_all(self, declarations: Any, strict: bool = False) -> List[Check]:
        """Register many; check names are prefixed by index so failures locate."""
        out: List[Check] = []
        for idx, decl in enumerate(declarations or []):
            for (name, ok, detail, code) in self.register(decl, strict=strict):
                out.append(("provider[{}].{}".format(idx, name), ok, detail, code))
        return out

    # -- lookup ------------------------------------------------------------- #
    def __contains__(self, provider_id: str) -> bool:
        return provider_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, provider_id: str) -> Optional[Dict[str, Any]]:
        return self._by_id.get(provider_id)

    def registered(self) -> Tuple[Dict[str, Any], ...]:
        """All declarations, sorted by provider_id."""
        return tuple(self._by_id[k] for k in sorted(self._by_id))

    def provider_ids(self) -> Tuple[str, ...]:
        return tuple(sorted(self._by_id))

    def providers_for(self, capability: str) -> Tuple[Dict[str, Any], ...]:
        """EVERY provider offering this capability, sorted by provider_id.

        Returns all matches, never a preferred one -- see the module docstring.
        An unknown capability returns empty; ``check_capability`` is what
        distinguishes "nobody offers it" from "that is not a capability".
        """
        out = [self._by_id[k] for k in sorted(self._by_id)
               if capability in (self._by_id[k].get("capabilities") or ())]
        return tuple(out)

    def capability_index(self) -> Dict[str, Tuple[str, ...]]:
        """capability -> provider ids, both levels deterministically ordered."""
        index: Dict[str, List[str]] = {}
        for pid in sorted(self._by_id):
            for cap in self._by_id[pid].get("capabilities") or ():
                index.setdefault(cap, []).append(pid)
        return {cap: tuple(index[cap]) for cap in sorted(index)}

    def collisions(self) -> Dict[str, Tuple[str, ...]]:
        """Capabilities offered by more than one provider.

        Not an error. But a collision is the precondition for an unexplained
        pick, so it is surfaced rather than left to be discovered by whoever
        wonders why two builds differed.
        """
        return {cap: ids for cap, ids in self.capability_index().items() if len(ids) > 1}

    def uncovered(self, required: Any) -> Tuple[str, ...]:
        """Which of ``required`` capabilities have zero registered providers."""
        index = self.capability_index()
        return tuple(sorted({c for c in (required or ()) if not index.get(c)}))

    # -- checks ------------------------------------------------------------- #
    def check_capability(self, capability: Any) -> List[Check]:
        """Is this a capability at all, and does anything offer it?

        Two distinct failures with two distinct codes on purpose. "That word is
        not a capability" (WF1227) is an authoring mistake in the request; "no
        provider offers it" (WF1228) is a real gap in the platform. Collapsing
        them sends the reader to fix the wrong thing.
        """
        checks: List[Check] = []
        known = capability in CAPABILITIES
        checks.append(("registry_capability_known", known,
                       "capability {!r} is not in the Core vocabulary {}".format(
                           capability, CAPABILITIES) if not known
                       else "capability {!r} is in the Core vocabulary".format(capability),
                       None if known else C.CORE_PROVIDER_CAPABILITY_UNKNOWN))
        if known:
            matches = self.providers_for(capability)
            ok = len(matches) > 0
            checks.append(("registry_capability_has_provider", ok,
                           "{} provider(s) offer {!r}".format(len(matches), capability)
                           if ok else
                           "no registered provider offers {!r}".format(capability),
                           None if ok else C.CORE_NO_PROVIDER_FOR_CAPABILITY))
        return checks

    def check_coverage(self, required: Any) -> List[Check]:
        """Every capability in ``required`` must be offered by something."""
        checks: List[Check] = []
        for cap in list(required or ()):
            for (name, ok, detail, code) in self.check_capability(cap):
                checks.append(("{}::{}".format(cap, name), ok, detail, code))
        return checks

    # -- evidence ----------------------------------------------------------- #
    def snapshot(self, registry_id: str = "wfcore_capability_registry") -> Dict[str, Any]:
        """A deterministic, JSON-safe record of what this registry contains.

        This is the evidence artifact a selection result points back at: without
        it, "provider X was chosen" cannot be re-checked later, because the set
        it was chosen FROM is gone.
        """
        index = self.capability_index()
        return {
            "registry_id": registry_id,
            "providers": list(self.provider_ids()),
            "capability_index": {cap: list(ids) for cap, ids in index.items()},
            "collisions": {cap: list(ids) for cap, ids in self.collisions().items()},
            "schema_version": RT_CAPABILITY_REGISTRY,
            "report_type": RT_CAPABILITY_REGISTRY,
        }


def validate_registry_snapshot(snapshot: Any, strict: bool = False) -> List[Check]:
    """Validate a registry snapshot record, including the under-reporting rail."""
    checks: List[Check] = []
    code = C.CORE_PROVIDER_DECLARATION_INVALID

    if not isinstance(snapshot, dict):
        return [("registry_snapshot_is_object", False,
                 "snapshot must be an object, got {}".format(type(snapshot).__name__),
                 code)]

    for fld in REGISTRY_SNAPSHOT_REQUIRED:
        present = fld in snapshot and snapshot.get(fld) is not None
        checks.append(("registry_has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else code))

    if strict:
        extra = sorted(set(snapshot) - set(REGISTRY_SNAPSHOT_ALLOWED))
        checks.append(("registry_no_unknown_fields", not extra,
                       "unexpected field(s) {}".format(extra) if extra
                       else "no unexpected fields", None if not extra else code))

    providers = snapshot.get("providers")
    ok = isinstance(providers, (list, tuple)) and all(
        isinstance(p, str) and p for p in providers)
    checks.append(("registry_providers_str_list", ok,
                   "providers must be a list of non-empty provider ids", None if ok else code))
    if isinstance(providers, (list, tuple)):
        dupes = sorted({p for p in providers if providers.count(p) > 1})
        checks.append(("registry_providers_unique", not dupes,
                       "duplicate provider id(s) {}".format(dupes) if dupes
                       else "provider ids unique", None if not dupes else code))

    index = snapshot.get("capability_index")
    ok = isinstance(index, dict)
    checks.append(("registry_capability_index_is_object", ok,
                   "capability_index must be an object mapping capability -> provider ids",
                   None if ok else code))

    if isinstance(index, dict):
        unknown = sorted({c for c in index if c not in CAPABILITIES})
        checks.append(("registry_index_capabilities_known", not unknown,
                       "capability_index names {} which is not in the Core "
                       "vocabulary {}".format(unknown, CAPABILITIES) if unknown
                       else "every indexed capability is in the Core vocabulary",
                       None if not unknown else C.CORE_PROVIDER_CAPABILITY_UNKNOWN))

        empty = sorted({c for c, ids in index.items()
                        if not isinstance(ids, (list, tuple)) or len(ids) == 0})
        checks.append(("registry_index_entries_nonempty", not empty,
                       "capability_index entr{} {} name no provider; an index entry "
                       "with no provider claims coverage that does not exist"
                       .format("ies" if len(empty) != 1 else "y", empty) if empty
                       else "every capability_index entry names >=1 provider",
                       None if not empty else C.CORE_NO_PROVIDER_FOR_CAPABILITY))

        known_ids = set(providers) if isinstance(providers, (list, tuple)) else set()
        dangling = sorted({p for ids in index.values()
                           if isinstance(ids, (list, tuple))
                           for p in ids if p not in known_ids})
        checks.append(("registry_index_ids_resolve", not dangling,
                       "capability_index references provider(s) {} absent from "
                       "providers".format(dangling) if dangling
                       else "every indexed provider id resolves",
                       None if not dangling else code))

        # --- rail: a snapshot must not under-report collisions ---------------
        declared = snapshot.get("collisions")
        if isinstance(declared, dict):
            actual = {c: sorted(ids) for c, ids in index.items()
                      if isinstance(ids, (list, tuple)) and len(ids) > 1}
            got = {c: sorted(ids) for c, ids in declared.items()
                   if isinstance(ids, (list, tuple))}
            ok = got == actual
            checks.append(("registry_collisions_fully_reported", ok,
                           "collisions {} does not match the {} multi-provider "
                           "capabilit(ies) in capability_index {}; a snapshot that "
                           "under-reports a collision presents a contested capability "
                           "as settled, which is how 'which provider ran?' stops being "
                           "answerable after the fact".format(got, len(actual), actual)
                           if not ok else
                           "collisions exactly match the multi-provider capabilities",
                           None if ok else C.CORE_PROVIDER_SELECTION_AMBIGUOUS))
        else:
            checks.append(("registry_collisions_is_object", False,
                           "collisions must be an object (possibly empty); absent, a "
                           "reader cannot tell 'no collisions' from 'not computed'",
                           code))

    sv = snapshot.get("schema_version")
    ok = sv == RT_CAPABILITY_REGISTRY
    checks.append(("registry_schema_version", ok,
                   "schema_version must be {!r} (got {!r})".format(
                       RT_CAPABILITY_REGISTRY, sv), None if ok else code))
    return checks


def _example_registry_snapshot(**over: Any) -> Dict[str, Any]:
    """Canonical-valid snapshot: two providers, one honestly-reported collision."""
    d: Dict[str, Any] = {
        "registry_id": "wfcore_capability_registry",
        "providers": ["editor_authoring_bridge", "runtime_authoring_bridge"],
        "capability_index": {
            "editor_authoring": ["editor_authoring_bridge"],
            "material_authoring": ["editor_authoring_bridge", "runtime_authoring_bridge"],
            "runtime_authoring": ["runtime_authoring_bridge"],
        },
        "collisions": {
            "material_authoring": ["editor_authoring_bridge", "runtime_authoring_bridge"],
        },
        "created_by": "worldforge.core",
        "schema_version": RT_CAPABILITY_REGISTRY,
        "report_type": RT_CAPABILITY_REGISTRY,
    }
    d.update(over)
    return d
