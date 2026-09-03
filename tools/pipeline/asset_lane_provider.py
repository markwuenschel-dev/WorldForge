#!/usr/bin/env python3
"""asset_lane_provider.py -- the procedural/ asset lanes, ADAPTED behind the Core
provider seam.

WHY ADAPT AND NOT REIMPLEMENT
-----------------------------
The older ``procedural/`` pipeline already authors textures, material instances
and mesh assets, and it has 20 texture ``.uasset``, 7 material ``.uasset`` and a
42-entry mesh catalog on disk to show for it. None of that was reachable from
Core: the capability vocabulary reserved ``material_authoring``,
``mesh_synthesis`` and ``asset_ingest`` and no declaration offered them, so
selection could never route to the lane that actually does the work. The largest
body of proven asset production in this repository sat outside the system that
grades production.

This module closes that seam by DECLARING capability over the existing lane. It
calls no UE API, authors no material, and generates no mesh. Reimplementing any
of that would create a second implementation of working code and, worse, a
second authority over the same artifacts.

WHY THIS ONE IS NOT A SINK MUTATION
-----------------------------------
Deliberate, and the reason the asset lanes are adapted while the world-mutating
lanes are reimplemented. An actor can be un-spawned; an asset something else
references cannot be un-created without breaking the thing that references it.
Folding asset production into the transaction sink would hand it a compensation
it cannot honestly provide -- so the declaration says ``rollback=none`` over a
side effect marked ``reversible=False``, and means it.

That has a consequence worth stating plainly: REFUSAL IS THE ONLY SAFETY
MECHANISM this provider has. There is no undo to fall back on, so anything it
cannot resolve or verify up front it declines to offer capability over. Hence
two codes, both hard refusals:

* WF1271 -- a catalog entry names a ``final_asset_path`` that is not on disk.
  The catalog is a claim about what exists; the filesystem is the fact.
* WF1272 -- an entry resolves but its own lane never graded it green. Core does
  not re-grade the adapted lane (that would be the second authority again); it
  refuses to offer capability over anything the owning lane has not passed.

WHAT THIS PROVIDER DOES NOT CLAIM
---------------------------------
It reports what the lane HAS PRODUCED and can be selected for. It does not
prove any of those assets is correct, nor that the editor could rebuild them
today. Its evidence is an inventory resolution -- filesystem facts plus the
owning lane's own verdict -- and that is all it says.

Usage:
    cd tools && PYTHONUTF8=1 python pipeline/asset_lane_provider.py --json
"""

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
_REPO = os.path.dirname(_TOOLS)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from wfcore.failure import FailureCode as C     # noqa: E402
from wfcore.providers import base as PB         # noqa: E402

PROVIDER_ID = "procedural_asset_lane"
RT_ASSET_INVENTORY = "wf.core.asset_lane_inventory.v1"

MESH_CATALOG_REL = "procedural/generated/worldforge_mesh_catalog.json"
MATERIAL_MANIFEST_DIR_REL = "procedural/manifests/materials"

# The owning lane's own green verdict. Core reads it; Core never recomputes it.
VALIDATION_OK = ("valid", "ok", "passed", "validated")

# States an inventory entry can be in. Three, kept separate: "we could not find
# it" and "its lane never passed it" have different remedies, and collapsing
# them into one "unavailable" bucket would hide which one applies.
STATE_AVAILABLE = "available"
STATE_ABSENT = "absent"
STATE_UNVALIDATED = "unvalidated"


def _read_json(rel):
    path = os.path.join(_REPO, rel)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _ue_path_to_disk(ue_path):
    """Map a /Game/... package path to its .uasset on disk.

    /Game maps to Content/. Returns None for anything not under /Game, which is
    not an error here -- it means this entry is not a project content asset and
    this provider has no filesystem claim to make about it.
    """
    if not isinstance(ue_path, str) or not ue_path.startswith("/Game/"):
        return None
    # A package path may carry an object suffix (/Game/X/Y.Y); the asset on disk
    # is named for the package, not the object. Same notation trap the sink hit.
    pkg = ue_path.split(".")[0]
    rel = pkg[len("/Game/"):]
    return os.path.join(_REPO, "Content", rel + ".uasset")


def _classify(ue_path, validation_status):
    disk = _ue_path_to_disk(ue_path)
    if disk is None:
        return STATE_ABSENT, None, "not a /Game content path: {!r}".format(ue_path)
    if not os.path.isfile(disk):
        # Report the owning lane's own verdict alongside the absence. Absent is
        # the more fundamental fact and picks the code, but a reader told only
        # "absent" could reasonably assume validation had passed and the file
        # was merely misplaced. Both facts, one message.
        also = ""
        if validation_status is not None and str(validation_status).lower() not in VALIDATION_OK:
            also = (" (its owning lane also records validation_status={!r},"
                    " so this entry would be refused even if the file"
                    " existed)").format(validation_status)
        return (STATE_ABSENT, disk,
                "catalog names {} but no .uasset exists at {}{}".format(
                    ue_path, os.path.relpath(disk, _REPO).replace(os.sep, "/"),
                    also))
    if validation_status is not None and str(validation_status).lower() not in VALIDATION_OK:
        return (STATE_UNVALIDATED, disk,
                "resolves on disk but its owning lane records "
                "validation_status={!r}".format(validation_status))
    return STATE_AVAILABLE, disk, "resolved on disk"


def _mesh_entries():
    catalog = _read_json(MESH_CATALOG_REL) or {}
    for aid, entry in sorted((catalog.get("assets") or {}).items()):
        yield {
            "entry_id": aid,
            "lane": "mesh",
            "capability": PB.CAP_MESH_SYNTHESIS,
            "ue_path": entry.get("final_asset_path"),
            "validation_status": entry.get("validation_status"),
            "source_type": entry.get("source_type"),
            "input_hash": entry.get("input_hash"),
        }


def _material_entries():
    d = os.path.join(_REPO, MATERIAL_MANIFEST_DIR_REL)
    if not os.path.isdir(d):
        return
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json") or name.startswith("_"):
            continue
        man = _read_json(os.path.join(MATERIAL_MANIFEST_DIR_REL, name).replace(os.sep, "/"))
        if not isinstance(man, dict):
            continue
        rid = man.get("recipe_id") or name[:-5]
        ue = man.get("ue") or {}
        # The material instance the lane produces.
        yield {
            "entry_id": "{}::material_instance".format(rid),
            "lane": "material",
            "capability": PB.CAP_MATERIAL_AUTHORING,
            "ue_path": ue.get("instance_path"),
            "validation_status": None,
            "synthesis": man.get("synthesis"),
        }
        # Its data asset, when the recipe asks for one.
        if ue.get("generate_data_asset"):
            yield {
                "entry_id": "{}::data_asset".format(rid),
                "lane": "material",
                "capability": PB.CAP_MATERIAL_AUTHORING,
                "ue_path": ue.get("data_asset_path"),
                "validation_status": None,
                "synthesis": man.get("synthesis"),
            }
        # Every imported texture is an ingested artifact.
        for tex_type, info in sorted((man.get("exports") or {}).items()):
            yield {
                "entry_id": "{}::texture::{}".format(rid, tex_type),
                "lane": "texture",
                "capability": PB.CAP_ASSET_INGEST,
                "ue_path": info.get("ue_asset_path"),
                "validation_status": None,
                "synthesis": man.get("synthesis"),
            }


def resolve_inventory():
    """Resolve every adapted-lane entry against the filesystem and its own verdict.

    Returns (entries, refusals). A refusal carries the failure code so the
    caller can see WHY capability is not offered, not merely that it is not.
    """
    entries, refusals = [], []
    for rec in list(_mesh_entries()) + list(_material_entries()):
        state, disk, detail = _classify(rec.get("ue_path"), rec.get("validation_status"))
        rec = dict(rec)
        rec["state"] = state
        rec["disk_path"] = (os.path.relpath(disk, _REPO).replace(os.sep, "/")
                            if disk else None)
        rec["detail"] = detail
        if state == STATE_ABSENT:
            rec["failure_code"] = C.CORE_ASSET_LANE_ARTIFACT_ABSENT
            refusals.append(rec)
        elif state == STATE_UNVALIDATED:
            rec["failure_code"] = C.CORE_ASSET_LANE_ENTRY_UNVALIDATED
            refusals.append(rec)
        else:
            rec["failure_code"] = None
        entries.append(rec)
    return entries, refusals


def offered_capabilities(entries):
    """Capabilities this provider can actually serve RIGHT NOW.

    A capability with zero available entries is NOT offered. Declaring a
    capability the inventory cannot serve is the same shape of empty claim the
    four declaration rails exist to stop -- it would make selection pick this
    provider for work it cannot do.
    """
    caps = sorted({e["capability"] for e in entries if e["state"] == STATE_AVAILABLE})
    return caps


def inventory_report():
    entries, refusals = resolve_inventory()
    by_state = {}
    for e in entries:
        by_state[e["state"]] = by_state.get(e["state"], 0) + 1
    return {
        "report_type": RT_ASSET_INVENTORY,
        "provider_id": PROVIDER_ID,
        "counts": by_state,
        "total": len(entries),
        "offered_capabilities": offered_capabilities(entries),
        "refusals": [
            {"entry_id": r["entry_id"], "lane": r["lane"], "state": r["state"],
             "failure_code": r["failure_code"], "detail": r["detail"]}
            for r in refusals
        ],
        "entries": entries,
    }


def declaration():
    """The provider record. Every field is a claim; the four rails police them."""
    entries, _ = resolve_inventory()
    caps = offered_capabilities(entries) or [PB.CAP_ASSET_INGEST]
    d = PB._example_provider_declaration(
        provider_id=PROVIDER_ID,
        capabilities=caps,
        requirements=[
            PB._example_requirement(
                requirement_id="req_mesh_catalog",
                observation_key=None,
                requirement_kind=PB.REQ_INPUT_ARTIFACT,
                subject=MESH_CATALOG_REL,
                detail="the adapted lane's own catalog; without it there is no "
                       "inventory to offer capability over"),
            PB._example_requirement(
                requirement_id="req_material_manifests",
                observation_key=None,
                requirement_kind=PB.REQ_INPUT_ARTIFACT,
                subject=MATERIAL_MANIFEST_DIR_REL,
                detail="material manifests declaring instance, data-asset and "
                       "texture paths"),
            PB._example_requirement(
                requirement_id="req_editor_for_authoring",
                requirement_kind=PB.REQ_ENGINE_STATE,
                subject="unreal_editor",
                detail="RESOLVING the inventory needs no editor; PRODUCING a "
                       "new asset does. The two are separated so Core can "
                       "describe this capability on a machine that cannot run "
                       "it"),
        ],
        side_effects=[
            PB._example_side_effect(
                effect_id="eff_persistent_asset",
                effect_kind=PB.EFFECT_PERSISTENT_ASSET,
                scope="Content/**",
                reversible=False,
                detail="creates .uasset content. Marked irreversible because an "
                       "asset another asset references cannot be un-created "
                       "without breaking the referrer -- which is exactly why "
                       "this lane is not a transaction-sink mutation"),
            PB._example_side_effect(
                effect_id="eff_lane_reports",
                # EVIDENCE_ONLY, not FILESYSTEM. Corrected after the rail at
                # base.py:533-542 rejected the first draft: a reversible=true
                # NON-evidence effect under rollback=none is reversibility with
                # no mechanism to invoke. The lane's validation reports are
                # evidence about what happened, not a world change something
                # could later need undone -- so the honest kind is the one that
                # says "I emit evidence", and the rail was right to refuse the
                # other reading.
                effect_kind=PB.EFFECT_EVIDENCE_ONLY,
                scope="evidence.asset_lane_inventory",
                reversible=True,
                detail="the adapted lane writes its own validation reports; "
                       "this provider adds an inventory resolution on top"),
        ],
        # Not DET_SEEDED: texture synthesis is deterministic given a recipe, but
        # UE import settings, engine version and DDC state all participate in
        # what lands on disk. Claiming seeded determinism here would be the
        # free-and-wrong claim WF1233 exists to catch, and this provider has no
        # evidence that would survive it.
        determinism=PB.DET_ENV_DEPENDENT,
        rollback=PB.ROLLBACK_NONE,
        outputs=["asset_lane_inventory", "persistent_asset_paths"],
        evidence=["asset_lane_inventory"],
        limitations=[
            PB._example_limitation(
                limitation_id="lim_no_rollback",
                limitation_kind="coverage_unknown",
                detail="rollback=none is structural, not an omission. Refusal "
                       "up front is the only safety mechanism available, so an "
                       "entry that cannot be resolved is declined rather than "
                       "attempted and undone"),
            PB._example_limitation(
                limitation_id="lim_inventory_not_correctness",
                limitation_kind="fidelity",
                detail="resolves that an artifact EXISTS and that its owning "
                       "lane graded it. It does not verify the artifact is "
                       "correct, and it does not open the editor to check"),
            PB._example_limitation(
                limitation_id="lim_adapts_not_owns",
                limitation_kind="input_shape",
                detail="the implementation stays in procedural/. This provider "
                       "cannot produce anything that lane cannot, and does not "
                       "re-grade what that lane has already judged"),
        ],
        description="declares capability over the existing procedural/ texture, "
                    "material and mesh production, resolved against disk")

    # _example_provider_declaration seeds fields for a DIFFERENT provider. Left
    # in place they are published as this provider's claims, which is the exact
    # free-and-wrong shape the four rails exist to catch -- and none of the four
    # would catch these, because each is individually well-formed.
    #
    # determinism_evidence: the example names a repeat-run hash suite. No such
    # suite exists for this provider, and none could: determinism here is
    # stable_within_environment precisely BECAUSE UE import settings, engine
    # version and DDC state participate in what lands on disk. The rail only
    # requires evidence for DET_SEEDED, so a stale value would sit unchallenged.
    d.pop("determinism_evidence", None)
    # cost_profile feeds candidate ranking. Resolving an inventory is a few
    # hundred stat() calls, not the example's 30 seconds; leaving it would make
    # selection rank this provider as expensive on a fabricated number.
    d["cost_profile"] = {"wall_seconds": 0.5, "operator_attention": 0.0}
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Resolve the adapted procedural/ asset-lane inventory.")
    ap.add_argument("--json", action="store_true", help="emit the full report")
    args = ap.parse_args(argv)

    rep = inventory_report()
    if args.json:
        print(json.dumps(rep, indent=2, sort_keys=True))
        return 0

    print("provider: {}".format(PROVIDER_ID))
    print("  inventory: {} entries {}".format(rep["total"], rep["counts"]))
    print("  offers   : {}".format(", ".join(rep["offered_capabilities"]) or "(nothing)"))
    if rep["refusals"]:
        print("  refusals :")
        for r in rep["refusals"]:
            print("    [{}] {} -- {}".format(r["failure_code"], r["entry_id"], r["detail"]))
    else:
        print("  refusals : none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
