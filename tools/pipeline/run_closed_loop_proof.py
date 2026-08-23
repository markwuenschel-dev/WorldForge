#!/usr/bin/env python3
"""run_closed_loop_proof -- drive the whole loop and say honestly how far it got.

    observations -> anchors -> placements -> transaction request
      -> LIVE Unreal materialisation -> post-observation -> comparison
      -> destroy -> rebuild -> equivalence

WHAT THIS IS AND IS NOT
-----------------------
It is the one runnable thing that exercises every seam in order against a real
editor, so that "the loop is closed" stops being an argument assembled out of
green unit suites and becomes a command with an exit code.

It is NOT an acceptance run for any particular game. The proof it produces is
about the MECHANISM. Two things separate the two, and this module refuses to let
them blur:

* ``--caller-artifacts`` decides whose measurements drive it. Pointed at a
  fixture, the report is stamped ``proof_kind: mechanism_proof``. Only artifacts
  from a real external caller earn ``externally_proven``, and this script cannot
  award that to itself -- the stamp is derived from whether a caller-originated
  adapter was supplied, never from a flag.
* materialisation targets whatever ``--project`` says. Pointing it at a game's
  project writes into that game's content, which is a decision the game makes,
  not one a proof script may take because it would make a nicer report.

EVERY PHASE CAN FAIL, AND A FAILED PHASE STOPS THE RUN
------------------------------------------------------
There is no "continue anyway". A comparison against a world that did not
materialise, or a rebuild-equivalence claim over content that was never
destroyed, is worse than no claim: it is a green square with nothing behind it.
The report records which phase stopped it and why.
"""

import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)
_REPO = os.path.dirname(_TOOLS)
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from pipeline import observation_intake as OI          # noqa: E402
from pipeline import route_placement_provider as RP    # noqa: E402
from wfcore.models import observed_world as OW         # noqa: E402

RT_LOOP_PROOF = "wf.core.closed_loop_proof.v1"

# The evidence ladder from the mission statement, as a closed ordered set. A
# phase may claim a rung only if it actually did the thing that rung names.
PROOF_MECHANISM = "mechanism_proof"          # ran, on WorldForge's own fixture
PROOF_EXTERNAL = "externally_proven"         # ran, driven by a real caller
PROOF_KINDS = (PROOF_MECHANISM, PROOF_EXTERNAL)

# Two mechanical violation classes, deliberately different in KIND:
#
#   displacement  content still exists but is in the wrong place. Detected from
#                 an observed transform; repaired by a bounded modify.
#   deletion      content that should exist is GONE. Detected from an absence,
#                 which is the harder direction -- nothing reports itself
#                 missing -- and repaired by re-creating from the source plan.
#
# Exercising only displacement left the create-repair path unproven and, worse,
# left "detect a thing that is not there" untested. An absence is exactly the
# signal a comparison built on iterating observations will silently miss.
VIOLATION_DISPLACEMENT = "displacement"
VIOLATION_DELETION = "deletion"
VIOLATION_CLASSES = (VIOLATION_DISPLACEMENT, VIOLATION_DELETION)

PHASES = ("intake", "anchors", "plan", "request", "ownership",
          "materialise", "post_observe", "compare", "perturb",
          "detect", "repair", "resurvey", "destroy", "rebuild",
          "manifest", "equivalence", "cleanup")


def _iso_now():
    """UTC stamp for artifacts this process creates."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0).isoformat()


def _phase(name, ok, detail, **extra):
    d = {"phase": name, "ok": bool(ok), "detail": detail}
    d.update(extra)
    return d


def _run_tx(request_path, map_pkg, operation_id, project, out_path,
            save_map, timeout, expect="committed"):
    """Boot the editor once. Returns (ok, near_side_report, detail)."""
    cmd = [sys.executable, os.path.join(_HERE, "run_wfcore_transaction.py"),
           "--request", request_path, "--map", map_pkg,
           "--operation-id", operation_id, "--out", out_path,
           "--expect", expect, "--timeout", str(timeout)]
    if project:
        cmd += ["--project", project]
    if save_map:
        cmd.append("--save-map")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_TOOLS)
    report = None
    if os.path.isfile(out_path):
        try:
            with open(out_path, encoding="utf-8") as fh:
                report = json.load(fh)
        except (OSError, ValueError) as exc:
            return False, None, "near-side report unreadable: {}".format(exc)
    tail = (proc.stdout or "")[-600:] + (proc.stderr or "")[-400:]
    return proc.returncode == 0, report, tail.strip()


def _outcome_of(near):
    """The delta outcome, read from where the near side actually records it.

    ``near_side_findings.outcome`` is the near side's OWN re-derivation, not the
    far side's self-report -- which is the point: the two are computed
    independently and a mismatch is itself a finding.
    """
    return ((near or {}).get("near_side_findings") or {}).get("outcome")


def _far_side(near):
    """The far-side document the near side points at, loaded. None if absent."""
    path = (near or {}).get("far_side_document")
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _observed_actor_labels(near):
    """Labels the editor says it ACTUALLY wrote, from its post-observation.

    Reads the FAR side's observation of the world after apply -- never the
    request. The declared target and the observed result are separate documents
    on purpose, and a comparison that reads the request back to itself proves
    only that a dict round-trips.
    """
    far = _far_side(near)
    out = set()
    for m in ((far or {}).get("delta") or {}).get("mutations", []) or []:
        if m.get("status") == "applied":
            obs = m.get("observed_after_apply") or {}
            if obs.get("state_kind") == "present":
                out.add(m.get("target_path"))
    return out


def _observed_payloads(near):
    """target_path -> observed payload, for comparing transforms not just names."""
    far = _far_side(near)
    out = {}
    for m in ((far or {}).get("delta") or {}).get("mutations", []) or []:
        if m.get("status") == "applied":
            out[m.get("target_path")] = (
                (m.get("observed_after_apply") or {}).get("payload"))
    return out


def _destroy_request(apply_req, observed_payloads, operation_id):
    """A delete request whose declared before-state is the OBSERVED one.

    ``executor`` compares the declared before-state against what it measures at
    apply time and aborts with WF1250 when they differ -- another writer moved
    the target between planning and now. That rail is the reason a delete cannot
    be authored blind: a hand-built ``present_state`` stand-in disagrees with the
    real payload and the transaction correctly refuses. So the restore point in
    this request is the payload the editor itself reported after the apply.
    """
    from wfcore.transaction import delta as TD
    step_id = "step_closed_loop_destroy"
    muts = []
    for m in apply_req["mutations"]:
        payload = observed_payloads.get(m["target_path"])
        if payload is None:
            continue
        muts.append({
            "mutation_id": m["mutation_id"] + "_del",
            "step_id": step_id, "provider_id": m["provider_id"],
            "target_kind": TD.TARGET_ACTOR, "target_path": m["target_path"],
            "operation": TD.OP_DELETE,
            "before_state": TD.present_state(payload),
            "status": TD.MUT_PLANNED,
            "rollback_mode": m["rollback_mode"],
            "schema_version": TD.RT_MUTATION,
            "expected_after_state": TD.absent_state(),
        })
    bounds = [dict(b, step_id=step_id) for b in apply_req["bounds"]]
    return {"operation_id": operation_id, "bounds": bounds,
            "evidence_refs": ["route_placement_plan", "observed_world"],
            "mutations": muts}


def _transform_request(operation_id, step_id, targets, observed_payloads,
                       new_locations, provider_id="unreal_editor_mutation_sink"):
    """A modify request over EXACTLY ``targets`` and nothing else.

    The bound is built from the target list rather than inherited from the
    original apply. That is the boundedness claim made structurally: a repair
    whose bound still admits every actor the first pass could reach is not a
    bounded repair, it is an unbounded one that happened to touch less.
    """
    from wfcore.transaction import delta as TD
    muts = []
    for i, tp in enumerate(sorted(targets)):
        before = observed_payloads.get(tp)
        if before is None:
            continue
        after = dict(before)
        after["location"] = list(new_locations[tp])
        muts.append({
            "mutation_id": "mut_{}_{:03d}".format(step_id, i),
            "step_id": step_id, "provider_id": provider_id,
            "target_kind": TD.TARGET_ACTOR, "target_path": tp,
            "operation": TD.OP_MODIFY,
            "before_state": TD.present_state(before),
            "status": TD.MUT_PLANNED,
            "rollback_mode": "compensating",
            "schema_version": TD.RT_MUTATION,
            "expected_after_state": TD.present_state(after),
        })
    bound = {"step_id": step_id,
             "allowed_packages": sorted({tp.split(":", 1)[0] for tp in targets}),
             "allowed_actors": sorted(targets),
             "schema_version": TD.RT_MUTATION_BOUND}
    return {"operation_id": operation_id, "bounds": [bound],
            "evidence_refs": ["route_placement_plan", "observed_world"],
            "mutations": muts}


def _deleted_targets(near):
    """Targets the editor reported as ACTUALLY removed, from its own record.

    Read from the applied delete mutations rather than inferred from a shrinking
    observation set: "absent from what we happened to look at" and "we watched it
    be removed" are different claims, and only the second is a measurement.
    """
    far = _far_side(near)
    out = set()
    for m in ((far or {}).get("delta") or {}).get("mutations", []) or []:
        if m.get("status") == "applied" and m.get("operation") == "delete":
            out.add(m.get("target_path"))
    return out


def _containment_blockers(observed_payloads, bound):
    """Blocker ids for placements whose OBSERVED location left the extent.

    Computed from the transform the editor reported, not from the plan. A
    detector that reads the plan would report the world it asked for.
    """
    out = []
    for tp, payload in sorted((observed_payloads or {}).items()):
        loc = (payload or {}).get("location")
        if not (isinstance(loc, list) and len(loc) == 3):
            out.append("unreadable::" + str(tp))
            continue
        inside, _detail = RP.within_planar_bound(loc, bound)
        if not inside:
            out.append("out_of_bounds::" + str(tp))
    return out


def _ownership_refusal(targets, protected):
    """Paths a repair must never touch. Escalation, not repair.

    Ownership is not a mechanical property, so a violation involving one is not
    a candidate for automatic repair at any bound. It leaves the loop.
    """
    prot = {p.strip() for p in (protected or []) if str(p).strip()}
    hits = sorted(t for t in targets
                  if t in prot or any(t.startswith(pp + ":") or
                                      t.split(":", 1)[0] == pp for pp in prot))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--caller-artifacts", required=True,
                    help="directory of caller-emitted observation artifacts")
    ap.add_argument("--caller-adapter",
                    help="dotted module of a REAL caller adapter. Supplying one "
                         "that declares caller origination is the only way this "
                         "run can be stamped externally_proven")
    ap.add_argument("--consumer-path", action="append", default=[])
    ap.add_argument("--subject-start", required=True,
                    help="subject id of the route's first anchor")
    ap.add_argument("--subject-end", required=True,
                    help="subject id of the route's second anchor")
    ap.add_argument("--map", required=True, help="/Game/... map to author into")
    ap.add_argument("--project", help="path to the .uproject to boot")
    ap.add_argument("--operation-id", default="op_closed_loop_proof_0001")
    ap.add_argument("--actor-class", required=True,
                    help="reflected actor class to place. REQUIRED and never "
                         "defaulted: what goes into a world is the caller's "
                         "decision, taken from its approved catalog")
    ap.add_argument("--protected", action="append", default=[],
                    help="a game-owned path a repair may never touch. "
                         "Repeatable. An ownership-involved violation escalates "
                         "instead of being repaired, at any bound")
    ap.add_argument("--violation-class", default=VIOLATION_DISPLACEMENT,
                    choices=list(VIOLATION_CLASSES),
                    help="which mechanical violation to inject and repair. "
                         "'displacement' moves a placement out of bounds; "
                         "'deletion' removes one entirely, which is detected "
                         "from an absence and repaired by re-creating it")
    ap.add_argument("--static-mesh",
                    help="mesh asset to give each placement. Caller-supplied "
                         "like --actor-class; without it the spawned actors have "
                         "zero-extent bounds and the survey correctly refuses "
                         "them as geometry")
    ap.add_argument("--material",
                    help="material to apply to each placement. Caller-supplied "
                         "like --actor-class and --static-mesh: WorldForge "
                         "decides where, the game decides what it looks like")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--extent-cm", type=float, default=20000.0)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--no-live", action="store_true",
                    help="stop before booting the editor (plumbing check only)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    for d in args.consumer_path:
        if d not in sys.path:
            sys.path.insert(0, d)

    scratch = os.path.dirname(os.path.abspath(args.out))
    if scratch and not os.path.isdir(scratch):
        os.makedirs(scratch)

    # -- proof kind, derived and not asserted ------------------------------- #
    proof_kind, origination = PROOF_MECHANISM, None
    if args.caller_adapter:
        try:
            import importlib
            from consumers import adapter as ADP
            mod = importlib.import_module(args.caller_adapter)
            origination = ADP.origination_of(mod.adapter())
            if origination == ADP.ORIGINATION_CALLER:
                proof_kind = PROOF_EXTERNAL
        except Exception as exc:            # noqa: BLE001
            origination = "adapter_unreadable: {}".format(exc)

    report = {
        "schema_version": RT_LOOP_PROOF, "report_type": RT_LOOP_PROOF,
        "operation_id": args.operation_id,
        "proof_kind": proof_kind,
        "caller_origination": origination,
        "subject_map": args.map,
        "project": args.project,
        "phases": [], "stopped_at": None, "green": False,
    }

    def stop(ph):
        report["phases"].append(ph)
        if not ph["ok"]:
            report["stopped_at"] = ph["phase"]
        return ph["ok"]

    def finish(code):
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        print("\nclosed-loop proof -- {}".format(report["proof_kind"]))
        for p in report["phases"]:
            print("  [{}] {:14} {}".format("OK  " if p["ok"] else "FAIL",
                                           p["phase"], p["detail"][:110]))
        print("\n  {}".format("LOOP GREEN" if report["green"]
                              else "STOPPED AT: {}".format(report["stopped_at"])))
        print("  report -> {}".format(args.out))
        return code

    # -- 1. intake ----------------------------------------------------------- #
    def _entry(key, subject):
        return {"observation_key": key, "section": "semantic_landmarks",
                "entity_id": subject, "field": "location_cm",
                "select": {"subject_id": subject},
                "require": {"status": "resolved",
                            "anchor_mode": "actor_object_path"},
                "value_path": ["transform", "location"],
                "value_shape": OI.SHAPE_XYZ_OBJECT}

    mapping = {"mapping_id": "map_closed_loop_proof",
               "consumer_id": "closed_loop_proof",
               "artifact_root": args.caller_artifacts,
               "artifact_glob": "*.json",
               "schema_version": OI.RT_OBSERVATION_MAPPING,
               "entries": [_entry("start", args.subject_start),
                           _entry("end", args.subject_end)]}
    mbad = [c for c in OI.validate_observation_mapping(mapping) if not c[1]]
    if not stop(_phase("intake", not mbad, "mapping invalid: {}".format(mbad)
                       if mbad else "mapping valid")):
        return finish(1)

    model, results = OI.build_observed_world(
        mapping, args.operation_id,
        world_identity={"world_id": args.map,
                        "request_id": args.operation_id, "revision": 0},
        artifact_root=args.caller_artifacts)
    census = OI.intake_census(results)
    obad = [c[0] for c in OW.validate_observed_world(model, strict=True)
            if not c[1]]
    report["intake_census"] = census
    if not stop(_phase("intake", not obad,
                       "observed world invalid: {}".format(obad) if obad
                       else "observed world valid; {}".format(json.dumps(census)),
                       census=census)):
        return finish(1)

    # -- 2. anchors ---------------------------------------------------------- #
    anchors = OI.anchors_from_observed(
        model, "semantic_landmarks", [args.subject_start, args.subject_end])
    unbacked = [a for a in anchors if a["location_cm"] is None]
    if not stop(_phase("anchors", not unbacked,
                       "unbacked anchor(s): {}".format(
                           [(a["anchor_id"], a["provenance"]) for a in unbacked])
                       if unbacked else "both anchors measured: {}".format(
                           [a["location_cm"] for a in anchors]),
                       anchors=anchors)):
        return finish(1)

    # -- 3. plan ------------------------------------------------------------- #
    bound = {"origin_x_cm": 0.0, "origin_y_cm": 0.0,
             "extent_x_cm": args.extent_cm, "extent_y_cm": args.extent_cm}
    plan = RP.plan_route_placements(anchors, args.count, bound)
    pbad = [c[0] for c in RP.validate_placement_plan(plan, strict=True)
            if not c[1]]
    ok = (not plan["refused"]) and not pbad
    report["placement_plan"] = plan
    if not stop(_phase("plan", ok,
                       plan.get("refusal_reason") or "validator: {}".format(pbad)
                       if not ok else "{} placement(s), containment proved by "
                       "coordinates".format(len(plan["placements"])))):
        return finish(1)

    # -- 4. request ---------------------------------------------------------- #
    req, errs = RP.build_transaction_request(
        plan, args.operation_id, "step_closed_loop_place", args.map,
        "wfmarker", actor_class=args.actor_class,
        static_mesh=args.static_mesh, material=args.material,
        evidence_refs=["route_placement_plan", "observed_world"])
    from pipeline import run_wfcore_transaction as TX
    verrs, _w = TX.validate_request(req) if req else (["no request"], [])
    ok = req is not None and not errs and not verrs
    req_path = os.path.join(scratch, "loop_request.json")
    if req:
        with open(req_path, "w", encoding="utf-8") as fh:
            json.dump(req, fh, indent=2, sort_keys=True)
    if not stop(_phase("request", ok,
                       "errors={} sink_validation={}".format(errs, verrs)
                       if not ok else "{} mutation(s); the sink's own validator "
                       "accepts it".format(len(req["mutations"])))):
        return finish(1)

    # -- 4b. ownership, BEFORE the editor is ever booted ---------------------- #
    # Ordering is the whole guarantee. This originally ran after materialisation
    # and passed its own negative control -- while the colliding actors were
    # already written to disk. "Game-owned assets are never silently modified"
    # cannot be established by a check that runs after the write; the only
    # version of it worth having refuses before anything is authored.
    owned_hits = _ownership_refusal(
        sorted(m["target_path"] for m in req["mutations"]), args.protected)
    stop(_phase("ownership", not owned_hits,
                "generated targets collide with declared game-owned paths {} -- "
                "escalating instead of proceeding".format(owned_hits)
                if owned_hits else
                "no generated target touches any of the {} declared game-owned "
                "path(s); everything this loop may repair is WorldForge's "
                "own".format(len(args.protected)),
                protected=list(args.protected), collisions=owned_hits))
    if owned_hits:
        return finish(1)


    if args.no_live:
        # A plumbing check is gateable without an editor, and it must NEVER be
        # mistakable for the real thing. So it exits 0 when everything before
        # materialisation held -- but `green` stays False and the verdict says
        # plumbing_only, because nothing was materialised and therefore nothing
        # downstream may be claimed. A gate reading the exit code learns "the
        # wiring is intact"; anyone reading the report learns exactly that and
        # no more.
        pre_ok = all(ph["ok"] for ph in report["phases"])
        report["verdict"] = "plumbing_only"
        report["green"] = False
        stop(_phase("materialise", False,
                    "--no-live: stopped before booting the editor. The {} phase(s) "
                    "before materialisation {}. Nothing was materialised, so "
                    "nothing downstream may be claimed and this run is NOT a "
                    "closed-loop proof".format(
                        len(report["phases"]),
                        "all held" if pre_ok else "did NOT all hold")))
        return finish(0 if pre_ok else 1)

    # -- 5. materialise (LIVE) ----------------------------------------------- #
    tx_out = os.path.join(scratch, "loop_tx_apply.json")
    ok, near, detail = _run_tx(req_path, args.map, args.operation_id,
                               args.project, tx_out, True, args.timeout)
    outcome = _outcome_of(near)
    ok = ok and outcome == "committed"
    if not stop(_phase("materialise", ok,
                       "outcome={} :: {}".format(outcome, detail),
                       outcome=outcome)):
        return finish(1)

    # -- 6/7. post-observation and comparison -------------------------------- #
    written = _observed_actor_labels(near)
    wanted = {m["target_path"] for m in req["mutations"]}
    missing, extra = sorted(wanted - written), sorted(written - wanted)
    stop(_phase("post_observe", bool(written),
                "sink post-observed {} actor(s) present".format(len(written)),
                observed=sorted(written)))
    ok = not missing and not extra
    if not stop(_phase("compare", ok,
                       "missing={} unexpected={}".format(missing, extra) if not ok
                       else "every planned placement is present in the world, "
                            "and nothing else was written",
                       missing=missing, unexpected=extra)):
        return finish(1)

    # -- 7c. the build manifest: identity, ownership, hashes, provenance ------ #
    # Emitted from the PLAN plus what the editor observed, so every generated
    # artifact can be traced to the request that caused it and checked against
    # what actually exists. Without this the run leaves correct reports about
    # events and nothing that identifies the things now in the world.
    from pipeline import build_manifest as BM
    _obs_now = _observed_payloads(near)
    manifest = BM.build_manifest(
        request_id=args.operation_id, plan=plan,
        target_paths=[m["target_path"] for m in req["mutations"]],
        observed_payloads=_obs_now,
        protected_identities=args.protected,
        created_at=(near or {}).get("meta", {}).get("timestamp")
        or _iso_now(),
        engine_build=(near or {}).get("environment", {}).get("WF_TX_OPERATION_ID")
        and None,
        evidence_refs=["route_placement_plan", "observed_world",
                       (near or {}).get("far_side_document")],
        validation={"compare": "every planned placement present, nothing else",
                    "containment": "coordinate_comparison"})
    man_path = os.path.join(scratch, "build_manifest.json")
    with open(man_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
    mbad = [c[0] for c in BM.validate_build_manifest(manifest, strict=True)
            if not c[1]]
    report["build_manifest"] = man_path
    if not stop(_phase("manifest", not mbad,
                       "manifest invalid: {}".format(mbad) if mbad else
                       "{} artifact(s) identified, owned, hashed and stamped; "
                       "{} match their intent".format(
                           manifest["counts"]["generated"],
                           manifest["counts"]["intent_matches_observed"]),
                       manifest_path=man_path,
                       counts=manifest["counts"])):
        return finish(1)

    planned_locations = {m["target_path"]:
                         (m["expected_after_state"]["payload"]["location"])
                         for m in req["mutations"]}
    observed_now = _observed_payloads(near)

    # -- 8. perturb: inject a REAL mechanical violation into the live world ---- #
    # Not a simulated one. The marker is actually moved, in the editor, to a
    # location outside the declared planar extent -- so the detector downstream
    # has to find it the same way it would find a genuine drift.
    victim = sorted(wanted)[len(sorted(wanted)) // 2]
    if args.violation_class == VIOLATION_DELETION:
        pert_req = _destroy_request(
            {"mutations": [m for m in req["mutations"]
                           if m["target_path"] == victim],
             "bounds": req["bounds"]},
            observed_now, args.operation_id + "_perturb")
        _what = "deleted {}".format(victim)
    else:
        far_off = [args.extent_cm * 4.0, args.extent_cm * 4.0,
                   planned_locations[victim][2]]
        pert_req = _transform_request(
            args.operation_id + "_perturb", "step_perturb", [victim],
            observed_now, {victim: far_off})
        _what = "moved {} to {}".format(victim, far_off)
    pert_path = os.path.join(scratch, "loop_request_perturb.json")
    with open(pert_path, "w", encoding="utf-8") as fh:
        json.dump(pert_req, fh, indent=2, sort_keys=True)
    ptx = os.path.join(scratch, "loop_tx_perturb.json")
    ok, pnear, detail = _run_tx(pert_path, args.map,
                                args.operation_id + "_perturb", args.project,
                                ptx, True, args.timeout)
    poutcome = _outcome_of(pnear)
    ok = ok and poutcome == "committed"
    if not stop(_phase("perturb", ok,
                       "outcome={} :: {} :: {}".format(
                           poutcome, _what, detail),
                       victim=victim, violation_class=args.violation_class)):
        return finish(1)

    # -- 9. detect: re-survey and find it from the OBSERVED transform --------- #
    after_perturb = dict(observed_now)
    after_perturb.update(_observed_payloads(pnear))
    if args.violation_class == VIOLATION_DELETION:
        # An absence cannot be found by iterating what IS there. It is found by
        # asking the world for each thing that SHOULD be there -- which is why
        # this is derived from the expected set, not from the observation.
        gone = _deleted_targets(pnear)
        for tp in gone:
            after_perturb.pop(tp, None)
        blockers_before = ["missing::" + tp for tp in sorted(gone)]
    else:
        blockers_before = _containment_blockers(after_perturb, bound)
    ok = bool(blockers_before)
    if not stop(_phase("detect", ok,
                       "the injected violation was NOT detected, so the detector "
                       "proves nothing" if not ok else
                       "{} contract violation(s) detected {}: {}".format(
                           len(blockers_before),
                           "from an ABSENCE -- each expected placement was asked "
                           "for by name, because nothing reports itself missing"
                           if args.violation_class == VIOLATION_DELETION
                           else "from observed transforms",
                           blockers_before),
                       blockers=blockers_before)):
        return finish(1)

    # -- 10. repair: bounded, and only what is WorldForge's ------------------- #
    violating = sorted(b.split("::", 1)[1] for b in blockers_before
                       if "::" in b)
    escalate = _ownership_refusal(violating, args.protected)
    if escalate:
        stop(_phase("repair", False,
                    "violation involves game-owned path(s) {} -- ESCALATED, not "
                    "repaired. Ownership is not a mechanical property".format(
                        escalate)))
        return finish(1)

    if args.violation_class == VIOLATION_DELETION:
        # Re-create from the SOURCE PLAN, not from a remembered observation.
        # Rebuilding from what we last saw would reproduce the world as it
        # drifted; rebuilding from the plan reproduces what was asked for.
        by_path = {m["target_path"]: m for m in req["mutations"]}
        rep_req = {
            "operation_id": args.operation_id + "_repair",
            "bounds": [dict(b, step_id="step_repair") for b in req["bounds"]],
            "evidence_refs": ["route_placement_plan", "observed_world"],
            "mutations": [dict(by_path[v], step_id="step_repair",
                               mutation_id=by_path[v]["mutation_id"] + "_re")
                          for v in violating if v in by_path],
        }
        rep_req["bounds"][0]["allowed_actors"] = sorted(violating)
    else:
        rep_req = _transform_request(
            args.operation_id + "_repair", "step_repair", violating,
            after_perturb, {v: planned_locations[v] for v in violating})
    rep_path = os.path.join(scratch, "loop_request_repair.json")
    with open(rep_path, "w", encoding="utf-8") as fh:
        json.dump(rep_req, fh, indent=2, sort_keys=True)
    rptx = os.path.join(scratch, "loop_tx_repair.json")
    ok, rpnear, detail = _run_tx(rep_path, args.map,
                                 args.operation_id + "_repair", args.project,
                                 rptx, True, args.timeout)
    rpoutcome = _outcome_of(rpnear)
    bound_actors = set(rep_req["bounds"][0]["allowed_actors"])
    bounded = bound_actors == set(violating)
    ok = ok and rpoutcome == "committed" and bounded
    if not stop(_phase("repair", ok,
                       "outcome={} bounded_to={} (violating={}) :: {}".format(
                           rpoutcome, sorted(bound_actors), violating, detail),
                       repaired=violating, bound_actors=sorted(bound_actors))):
        return finish(1)

    # -- 11. re-survey: converged, and nothing else moved --------------------- #
    after_repair = dict(after_perturb)
    after_repair.update(_observed_payloads(rpnear))
    if args.violation_class == VIOLATION_DELETION:
        still_gone = [tp for tp in violating if tp not in after_repair]
        blockers_after = ["missing::" + tp for tp in sorted(still_gone)]
    else:
        blockers_after = _containment_blockers(after_repair, bound)
    from wfcore.repair import loop as RL
    converging = RL.is_converging(blockers_before, blockers_after)
    resolved = not blockers_after
    # Untouched actors must be byte-identical to their pre-perturbation state.
    # A repair that "fixed" the violation by nudging everything else is not a
    # bounded repair, and only comparing the bystanders can tell.
    bystanders = sorted(set(observed_now) - set(violating))
    unchanged = all(after_repair.get(b) == observed_now.get(b)
                    for b in bystanders)
    ok = resolved and unchanged
    if not stop(_phase("resurvey", ok,
                       "blockers {} -> {} (converging={}), bystanders "
                       "unchanged={} ({} checked)".format(
                           blockers_before, blockers_after, converging,
                           unchanged, len(bystanders)),
                       blockers_before=blockers_before,
                       blockers_after=blockers_after,
                       converging=converging,
                       bystanders_unchanged=unchanged)):
        return finish(1)

    # NOTE: `written` and `near` are deliberately NOT reassigned here. A bounded
    # repair post-observes only its own bounded targets -- one actor, not three --
    # so adopting its observation as "the world" would shrink the world to the
    # part that was repaired, and the rebuild comparison below would then be
    # comparing three actors against one. The full post-repair state is
    # `after_repair`, which merges the repair's observations over the apply's.

    # -- 8. destroy ----------------------------------------------------------- #
    from wfcore.transaction import delta as TD
    del_req = _destroy_request(req, after_repair,
                               args.operation_id + "_destroy")
    del_path = os.path.join(scratch, "loop_request_destroy.json")
    with open(del_path, "w", encoding="utf-8") as fh:
        json.dump(del_req, fh, indent=2, sort_keys=True)
    dtx = os.path.join(scratch, "loop_tx_destroy.json")
    ok, dnear, detail = _run_tx(del_path, args.map,
                                args.operation_id + "_destroy", args.project,
                                dtx, True, args.timeout)
    doutcome = _outcome_of(dnear)
    ok = ok and doutcome == "committed"
    if not stop(_phase("destroy", ok,
                       "outcome={} :: {}".format(doutcome, detail))):
        return finish(1)

    # -- 9. rebuild from the SAME source specification ------------------------ #
    plan2 = RP.plan_route_placements(anchors, args.count, bound)
    req2, errs2 = RP.build_transaction_request(
        plan2, args.operation_id + "_rebuild", "step_closed_loop_place",
        args.map, "wfmarker", actor_class=args.actor_class,
        static_mesh=args.static_mesh, material=args.material,
        evidence_refs=["route_placement_plan", "observed_world"])
    req2_path = os.path.join(scratch, "loop_request_rebuild.json")
    with open(req2_path, "w", encoding="utf-8") as fh:
        json.dump(req2, fh, indent=2, sort_keys=True)
    rtx = os.path.join(scratch, "loop_tx_rebuild.json")
    ok, rnear, detail = _run_tx(req2_path, args.map,
                                args.operation_id + "_rebuild", args.project,
                                rtx, True, args.timeout)
    routcome = _outcome_of(rnear)
    ok = ok and routcome == "committed" and not errs2
    if not stop(_phase("rebuild", ok,
                       "outcome={} :: {}".format(routcome, detail))):
        return finish(1)

    # -- 10. equivalence ------------------------------------------------------ #
    # Compared on the PLAN (the intended world) and on what the world reported
    # back, not on one of them twice.
    plan_same = RP.canonical(plan) == RP.canonical(plan2)
    rebuilt = _observed_actor_labels(rnear)
    world_same = rebuilt == written
    # Names matching is not equivalence. Two runs can spawn identically-labelled
    # actors in different places, and a check that stopped at labels would call
    # that a rebuild.
    first_payloads = after_repair
    rebuilt_payloads = _observed_payloads(rnear)
    transforms_same = first_payloads == rebuilt_payloads
    ok = plan_same and world_same and transforms_same
    stop(_phase("equivalence", ok,
                "intended-world identical={} observed-labels identical={} "
                "observed-transforms identical={} (first={} rebuilt={})".format(
                    plan_same, world_same, transforms_same,
                    sorted(written), sorted(rebuilt)),
                plan_identical=plan_same, world_identical=world_same,
                transforms_identical=transforms_same,
                observed_first=first_payloads,
                observed_rebuilt=rebuilt_payloads))

    # -- 11. leave the world as we found it ----------------------------------- #
    # Without this the proof is single-shot: the rebuilt actors persist, and the
    # next run's create finds them present and correctly refuses. A lifecycle
    # proof that cannot be run twice has not proved lifecycle.
    final_req = _destroy_request(req2, _observed_payloads(rnear),
                                 args.operation_id + "_final_cleanup")
    fpath = os.path.join(scratch, "loop_request_final_cleanup.json")
    with open(fpath, "w", encoding="utf-8") as fh:
        json.dump(final_req, fh, indent=2, sort_keys=True)
    ftx = os.path.join(scratch, "loop_tx_final_cleanup.json")
    ok, fnear, detail = _run_tx(fpath, args.map,
                                args.operation_id + "_final_cleanup",
                                args.project, ftx, True, args.timeout)
    foutcome = _outcome_of(fnear)
    left = _observed_actor_labels(fnear)
    ok = ok and foutcome == "committed"
    stop(_phase("cleanup", ok,
                "outcome={} :: the map is returned to its pre-proof state, so "
                "this proof is repeatable :: {}".format(foutcome, detail),
                outcome=foutcome, still_present=sorted(left)))

    report["green"] = all(p["ok"] for p in report["phases"])
    return finish(0 if report["green"] else 1)


if __name__ == "__main__":
    raise SystemExit(main())
