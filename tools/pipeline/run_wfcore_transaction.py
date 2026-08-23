#!/usr/bin/env python3
"""run_wfcore_transaction.py -- boot the editor, run ONE Core transaction, read it back.

WHAT THIS IS
------------
The near side of tools/unreal/wfcore_unreal_sink.py. It builds a transaction
request, launches ``UnrealEditor-Cmd`` headless with ``-ExecutePythonScript``, and
reads back the ONE deterministic JSON document the far side wrote. The transaction
itself runs FAR SIDE, inside the editor, using the committed
``wfcore.transaction.executor`` unchanged -- this process contributes the request,
the boot, and an INDEPENDENT re-derivation of what came back.

WHY THE VERDICT IS RE-DERIVED AND NOT COPIED
--------------------------------------------
The far side reports an outcome. That outcome was computed by the same code whose
correctness is in question, so this process does not take it as the answer: it
re-runs ``delta.validate_world_delta`` over the returned record and re-folds
``verification_status`` and ``rollback_completeness`` from the per-mutation
observations. A disagreement between the reported outcome and the re-derived folds
is real information and is reported as such, not smoothed over.

WHY exit(0) IS NARROW
---------------------
Exit 0 means: the editor exited cleanly, the far side wrote its document, the
document carries a delta, that delta re-validates, and its outcome is one the caller
declared it would accept (``--expect``, default ``committed``). Anything else exits
non-zero. In particular a ``partial_commit`` is never a success: the world is
neither committed nor rolled back, and an exit code that rounded that to either
would let a caller retry on top of a half-changed world.

THE ADDRESS SPACE AND THE ROUNDING -- DUPLICATED ON PURPOSE, AND MEASURED
------------------------------------------------------------------------
``parse_actor_address``, ``normalize_class_ref``, ``actor_payload`` and
``ROUND_DIGITS`` below are second copies of the far side's. They cannot be imported:
tools/unreal/wfcore_unreal_sink.py does ``import unreal`` at module scope, which
only exists inside the editor interpreter. The duplication is therefore structural
-- so it is MEASURED rather than trusted:
``tools/pipeline/test_wfcore_unreal_sink.py`` asserts the two implementations agree
over a table of cases and that the two ``ROUND_DIGITS`` are equal. If they ever
drift, the caller's declared postcondition and the sink's observation of it would be
written in different alphabets, and every correct mutation would read as a violated
postcondition and be rolled back.

USAGE
-----
    # bootless: build and print the request, the command and the environment
    python tools/pipeline/run_wfcore_transaction.py --demo-spawn StaticMeshActor \
        --map /Game/Maps/_wf_test_lvl --dry-run

    # live: boot the editor and run it
    python tools/pipeline/run_wfcore_transaction.py --demo-spawn StaticMeshActor \
        --map /Game/Maps/_wf_test_lvl

    # a real request authored elsewhere
    python tools/pipeline/run_wfcore_transaction.py --request my_delta_request.json \
        --map /Game/Maps/_wf_test_lvl
"""

import argparse
import json
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
FAR_SIDE = TOOLS_DIR / "unreal" / "wfcore_unreal_sink.py"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from wfcore.transaction import delta as D  # noqa: E402

NEAR_SIDE_SCHEMA = "wf.core.unreal_sink_run_report.v1"

PROVIDER_ID = "unreal_editor_mutation_sink"
ROLLBACK_MODE = "compensating"   # wfcore.providers.base.ROLLBACK_COMPENSATING

# MUST equal wfcore_unreal_sink.ROUND_DIGITS. Asserted by the test suite.
ROUND_DIGITS = 3

DEFAULT_EDITOR_ARGS = ("-unattended", "-nopause", "-nosplash", "-nullrhi", "-stdout")


# --------------------------------------------------------------------------- #
# pure helpers -- mirrors of the far side's, checked for parity by the tests
# --------------------------------------------------------------------------- #
def normalize_class_ref(value):
    """Mirror of wfcore_unreal_sink.normalize_class_ref."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text or None


def parse_actor_address(path):
    """Mirror of wfcore_unreal_sink.parse_actor_address."""
    if not isinstance(path, str) or not path.strip():
        return None, None, "actor address must be a non-empty string, got {!r}".format(path)
    text = path.strip()
    if text.count(":") != 1:
        return None, None, (
            "actor address {!r} must be exactly '<map_package>:<actor_label>' with "
            "one colon (found {})".format(path, text.count(":")))
    map_pkg, label = text.split(":", 1)
    map_pkg, label = map_pkg.strip().rstrip("/"), label.strip()
    if not map_pkg or not label:
        return None, None, (
            "actor address {!r} has an empty map package or label; an address that "
            "names no actor cannot be observed and must not be applied".format(path))
    return map_pkg, label, None


def _round(value):
    """Mirror of wfcore_unreal_sink._round."""
    try:
        f = float(value)
    except Exception:  # noqa: BLE001
        return None
    if not math.isfinite(f):
        return None
    return round(f, ROUND_DIGITS) + 0.0


def _round_triple(values):
    try:
        items = list(values)
    except Exception:  # noqa: BLE001
        return None
    if len(items) != 3:
        return None
    out = [_round(v) for v in items]
    return None if any(v is None for v in out) else out


def actor_payload(actor_class, location, rotation, scale):
    """Mirror of wfcore_unreal_sink.actor_payload."""
    cls = normalize_class_ref(actor_class)
    loc, rot, scl = _round_triple(location), _round_triple(rotation), _round_triple(scale)
    if not cls or loc is None or rot is None or scl is None:
        return None
    return {"actor_class": cls, "location": loc, "rotation": rot, "scale": scl}


def actor_address(map_package, label):
    return "{}:{}".format(str(map_package).strip().rstrip("/"), str(label).strip())


# --------------------------------------------------------------------------- #
# request construction
# --------------------------------------------------------------------------- #
def build_mutation(mutation_id, step_id, address, operation, payload):
    """One mutation record, in the shape delta.validate_mutation accepts.

    ``before_state`` is the DECLARED one and is deliberately the weakest possible
    claim: the executor observes the real before-state and keeps this only as
    ``before_state_declared``, so writing anything more confident here would be a
    claim about a world this process cannot see.
    """
    before = D.absent_state() if operation == D.OP_CREATE else D.unmeasured_state(
        "the near side does not observe the world; the executor captures the real "
        "before-state by observation before it applies anything")
    record = {
        "mutation_id": mutation_id,
        "step_id": step_id,
        "provider_id": PROVIDER_ID,
        "target_kind": D.TARGET_ACTOR,
        "target_path": address,
        "operation": operation,
        "before_state": before,
        "expected_after_state": D.present_state(payload),
        "status": D.MUT_PLANNED,
        "rollback_mode": ROLLBACK_MODE,
        "schema_version": D.RT_MUTATION,
    }
    return record


def build_bound(step_id, addresses, packages=()):
    """The step's mutation bound. EXACT addresses only -- never a prefix, never a glob.

    ``packages`` is non-empty only when the run will SAVE the map: an unsaved
    editor-world mutation writes no package, and a bound widened to authorise a
    write that never happens also authorises one that does.
    """
    return {
        "step_id": step_id,
        "allowed_packages": [str(p) for p in packages],
        "allowed_actors": [str(a) for a in addresses],
        "protected_paths": [],
        "schema_version": D.RT_MUTATION_BOUND,
    }


def build_demo_spawn_request(map_package, actor_class, label, location, rotation,
                             scale, operation_id, save_map=False):
    """A one-step, one-mutation SPAWN request. (request, error)."""
    payload = actor_payload(actor_class, location, rotation, scale)
    if payload is None:
        return None, (
            "cannot build a spawn request: actor_class={!r} location={!r} "
            "rotation={!r} scale={!r} is not a complete actor payload".format(
                actor_class, location, rotation, scale))
    address = actor_address(map_package, label)
    _pkg, _label, err = parse_actor_address(address)
    if err:
        return None, err
    step_id = "step_wfcore_unreal_sink_demo"
    return {
        "operation_id": operation_id,
        "bounds": [build_bound(step_id, [address],
                               packages=[map_package] if save_map else ())],
        "mutations": [build_mutation("mut_demo_spawn_0", step_id, address,
                                     D.OP_CREATE, payload)],
        "evidence_refs": ["far_side_transaction_document"],
    }, None


def validate_request(request):
    """(errors, warnings). Refuses a request whose shape the executor would refuse
    anyway -- cheaper here, and it never costs an editor boot to find out."""
    errors, warnings = [], []
    if not isinstance(request, dict):
        return ["request must be an object, got {}".format(type(request).__name__)], []
    bounds = request.get("bounds") or []
    mutations = request.get("mutations") or []
    if not mutations:
        errors.append("request declares no mutations; there is nothing to run")
    for idx, b in enumerate(bounds):
        for (name, ok, detail, _code) in D.validate_mutation_bound(b, strict=True):
            if not ok:
                errors.append("bounds[{}].{}: {}".format(idx, name, detail))
    for idx, m in enumerate(mutations):
        for (name, ok, detail, _code) in D.validate_mutation(m, strict=False):
            if not ok:
                errors.append("mutations[{}].{}: {}".format(idx, name, detail))
        if isinstance(m, dict) and m.get("target_kind") == D.TARGET_ACTOR:
            _pkg, _label, err = parse_actor_address(m.get("target_path"))
            if err:
                errors.append("mutations[{}].target_path: {}".format(idx, err))
    if not (request.get("evidence_refs") or []):
        warnings.append(
            "evidence_refs is empty; delta.validate_world_delta requires at least "
            "one for any delta that touched the world, so a commit would fail its "
            "own coherence rail")
    return errors, warnings


# --------------------------------------------------------------------------- #
# boot construction -- pure, so the tests can check it without an editor
# --------------------------------------------------------------------------- #
def build_far_side_env(out_path, request_path, map_package, repo_root, operation_id,
                       save_map=False, observe_after=True, tools_dir=None):
    """The EXACT environment contract tools/unreal/wfcore_unreal_sink.py reads.

    Every value is a string: a subprocess environment cannot carry anything else,
    and a bool leaking through here would reach the far side as ``"True"``, which
    its flag parser accepts -- but ``"False"`` would too, and it would read as true
    under a naive parser. Both sides speak "1"/"0" only.
    """
    return {
        "WF_TX_OUT": str(out_path),
        "WF_TX_REQUEST": str(request_path),
        "WF_TX_MAP": str(map_package or ""),
        "WF_TX_REPO_ROOT": str(repo_root),
        "WF_TX_OPERATION_ID": str(operation_id),
        "WF_TX_SAVE_MAP": "1" if save_map else "0",
        "WF_TX_OBSERVE_AFTER": "1" if observe_after else "0",
        "WF_TX_TOOLS": str(tools_dir or TOOLS_DIR),
        "PYTHONUTF8": "1",
    }


def build_editor_command(ue_cmd, uproject, script, extra_args=DEFAULT_EDITOR_ARGS):
    """The argv for the headless boot. Forward slashes throughout: UE's own command
    line parser treats a trailing backslash before a quote as an escape."""
    return [
        str(ue_cmd),
        str(uproject).replace("\\", "/"),
        "-ExecutePythonScript={}".format(str(script).replace("\\", "/")),
    ] + list(extra_args)


def resolve_paths(args):
    """(ue_cmd, uproject, error). Uses the committed bridge ladder, never a
    hard-coded engine path."""
    try:
        from bridge import paths as P
    except Exception as exc:  # noqa: BLE001
        return None, None, "could not import tools/bridge/paths.py: {}: {}".format(
            type(exc).__name__, exc)
    try:
        engine_root = P.resolve_engine_root(args.engine_root)
        ue_cmd = P.resolve_ue_cmd(engine_root.value, args.ue_cmd)
    except Exception as exc:  # noqa: BLE001
        return None, None, "{}: {}".format(type(exc).__name__, exc)
    uproject = Path(args.project) if args.project else (REPO_ROOT / "WorldForge.uproject")
    if not uproject.is_file():
        return None, None, "uproject {} does not exist".format(uproject)
    return ue_cmd.value, uproject, None


def run_editor(cmd, env_extra, timeout):
    """(exit_code_or_None, stdout, seconds). None means the boot timed out."""
    env = dict(os.environ)
    env.update(env_extra)
    started = time.time()
    try:
        proc = subprocess.run(cmd, env=env, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return (proc.returncode,
                proc.stdout.decode("utf-8", "replace"),
                round(time.time() - started, 2))
    except subprocess.TimeoutExpired as exc:
        return (None,
                (exc.stdout or b"").decode("utf-8", "replace"),
                round(time.time() - started, 2))


# --------------------------------------------------------------------------- #
# reading the far side back -- an independent re-derivation, never an echo
# --------------------------------------------------------------------------- #
def rederive(far_doc):
    """Re-check what came back. Returns a dict of near-side findings.

    Nothing here reads the far side's own opinion of itself except to COMPARE
    against it. ``outcome_agrees`` is the interesting field: the far side's outcome
    was computed by the executor, and this recomputes the same folds from the
    per-mutation observations the executor recorded.
    """
    out = {
        "delta_present": False,
        "outcome": None,
        "validation_failures": [],
        "rederived_verification": None,
        "rederived_rollback_completeness": None,
        "reported_verification": None,
        "reported_rollback_completeness": None,
        "verification_agrees": None,
        "rollback_agrees": None,
        "mutation_statuses": {},
        "failure_codes": [],
    }
    if not isinstance(far_doc, dict):
        return out
    record = far_doc.get("delta")
    if not isinstance(record, dict):
        return out
    out["delta_present"] = True
    out["outcome"] = record.get("outcome")
    out["failure_codes"] = list(record.get("failure_codes") or [])
    for (name, ok, detail, code) in D.validate_world_delta(record, strict=False):
        if not ok:
            out["validation_failures"].append(
                {"check": name, "detail": detail, "failure_code": code})
    out["rederived_verification"] = D.verification_status(record)
    out["rederived_rollback_completeness"] = D.rollback_completeness(record)
    out["reported_verification"] = record.get("verification")
    out["reported_rollback_completeness"] = record.get("rollback_completeness")

    # BOTH folds are VACUOUSLY SATISFIED over an empty set -- ``tri.conj([])`` is
    # ``satisfied`` -- while the executor initialises both fields to UNKNOWN
    # (executor.py:290-292) and writes them only on the path that computed them
    # (:515, :594, :644). So on a committed delta the reported rollback_completeness
    # is UNKNOWN and the re-fold is SATISFIED, and comparing them would report a
    # disagreement on every successful run: an alarm that fires on the healthy case
    # is an alarm nobody reads. The comparison is therefore made only where a fold
    # actually ranged over something, and is ``None`` -- NOT CHECKED, which is not
    # agreement -- elsewhere.
    statuses = {}
    kinds = []
    for m in (record.get("mutations") or []):
        if isinstance(m, dict):
            statuses[str(m.get("mutation_id"))] = m.get("status")
            kinds.append(m.get("status"))
    applied_any = any(s in (D.MUT_APPLIED, D.MUT_ROLLED_BACK, D.MUT_ROLLBACK_FAILED,
                            D.MUT_ROLLBACK_UNVERIFIED) for s in kinds)
    rollback_attempted = any(s in (D.MUT_ROLLED_BACK, D.MUT_ROLLBACK_FAILED,
                                   D.MUT_ROLLBACK_UNVERIFIED, D.MUT_UNRECOVERABLE)
                             for s in kinds)
    out["verification_fold_ranged_over_something"] = applied_any
    out["rollback_fold_ranged_over_something"] = rollback_attempted
    out["verification_agrees"] = (
        (out["rederived_verification"] == out["reported_verification"])
        if applied_any else None)
    out["rollback_agrees"] = (
        (out["rederived_rollback_completeness"]
         == out["reported_rollback_completeness"])
        if rollback_attempted else None)
    out["mutation_statuses"] = statuses
    return out


def build_report(*, operation_id, request, far_doc, findings, exit_code, stdout_tail,
                 seconds, expected_outcomes, command, env_extra, far_out_path,
                 boot_error=None):
    """The near-side report. States its inputs; asserts nothing it did not check."""
    accepted = (findings.get("outcome") in expected_outcomes
                and findings.get("delta_present")
                and not findings.get("validation_failures")
                # `is not False` on purpose: None means the fold ranged over
                # nothing and was NOT CHECKED, which must not read as agreement
                # and must not be treated as a disagreement either.
                and findings.get("verification_agrees") is not False
                and findings.get("rollback_agrees") is not False
                and exit_code == 0
                and not boot_error)
    reasons = []
    if boot_error:
        reasons.append(boot_error)
    if exit_code is None:
        reasons.append("the editor boot timed out; no exit code was observed")
    elif exit_code != 0:
        reasons.append("the editor exited {}".format(exit_code))
    if far_doc is None:
        reasons.append(
            "the far side wrote no document at {}; that is indistinguishable from a "
            "far side that never started, so it is not read as a failure of the "
            "transaction -- it is a failure to observe one".format(far_out_path))
    elif not findings.get("delta_present"):
        reasons.append("the far-side document carries no delta: {}".format(
            far_doc.get("error")))
    else:
        if findings.get("outcome") not in expected_outcomes:
            reasons.append("outcome {!r} is not in the accepted set {}".format(
                findings.get("outcome"), sorted(expected_outcomes)))
        if findings.get("validation_failures"):
            reasons.append("the returned delta failed {} coherence check(s)".format(
                len(findings["validation_failures"])))
        if findings.get("verification_agrees") is False:
            reasons.append(
                "the delta REPORTS verification {!r} but re-folding the recorded "
                "per-mutation observations gives {!r}".format(
                    findings.get("reported_verification"),
                    findings.get("rederived_verification")))
        if findings.get("rollback_agrees") is False:
            reasons.append(
                "the delta REPORTS rollback_completeness {!r} but re-folding gives "
                "{!r}".format(findings.get("reported_rollback_completeness"),
                              findings.get("rederived_rollback_completeness")))
    return {
        "report_type": NEAR_SIDE_SCHEMA,
        "schema_version": NEAR_SIDE_SCHEMA,
        "operation_id": operation_id,
        "accepted": bool(accepted),
        "not_accepted_because": reasons,
        "expected_outcomes": sorted(expected_outcomes),
        "editor_exit_code": exit_code,
        "editor_seconds": seconds,
        "far_side_document": far_out_path,
        "far_side_error": (far_doc or {}).get("error"),
        "far_side_traceback": (far_doc or {}).get("traceback"),
        "far_side_failure_codes": list((far_doc or {}).get("failure_codes") or []),
        "sink_refusals": list((far_doc or {}).get("sink_refusals") or []),
        "sink_notes": list((far_doc or {}).get("sink_notes") or []),
        "map_requested": (far_doc or {}).get("map_requested"),
        "map_loaded": (far_doc or {}).get("map_loaded"),
        "world_package_observed": (far_doc or {}).get("world_package_observed"),
        "journal_path": ((far_doc or {}).get("delta") or {}).get("journal_path"),
        "lock": ((far_doc or {}).get("delta") or {}).get("lock"),
        "near_side_findings": findings,
        "request": request,
        "command": [str(c) for c in command],
        "environment": dict(env_extra),
        "stdout_tail": stdout_tail,
    }


def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False,
                               default=str), encoding="utf-8")
    return path


def _parse_triple(text, default):
    if text is None or not str(text).strip():
        return list(default), None
    parts = [p for p in str(text).replace(";", ",").split(",") if p.strip()]
    if len(parts) != 3:
        return list(default), "{!r} is not three comma-separated numbers".format(text)
    out = []
    for p in parts:
        try:
            value = float(p.strip())
        except ValueError:
            return list(default), "{!r} contains a non-numeric component".format(text)
        if not math.isfinite(value):
            return list(default), "{!r} contains a non-finite component".format(text)
        out.append(value)
    return out, None


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def build_arg_parser():
    ap = argparse.ArgumentParser(
        prog="run_wfcore_transaction.py",
        description="Run ONE wfcore transaction against a real Unreal project.")
    ap.add_argument("--request", default=None,
                    help="path to a transaction request JSON "
                         "{operation_id, bounds, mutations, evidence_refs}")
    ap.add_argument("--demo-spawn", default=None, metavar="CLASS",
                    help="synthesize a one-mutation spawn request for this short "
                         "reflected actor class (e.g. StaticMeshActor)")
    ap.add_argument("--label", default=None,
                    help="actor label for --demo-spawn (default: a unique WF_TX_* label)")
    ap.add_argument("--location", default="0,0,200", help="x,y,z for --demo-spawn")
    ap.add_argument("--rotation", default="0,0,0", help="pitch,yaw,roll for --demo-spawn")
    ap.add_argument("--scale", default="1,1,1", help="x,y,z for --demo-spawn")
    ap.add_argument("--map", default=None,
                    help="/Game/... level to load before mutating (required for any "
                         "actor mutation)")
    ap.add_argument("--save-map", action="store_true",
                    help="save the map after each mutation. OFF by default: an "
                         "unsaved editor-world mutation writes nothing to disk. With "
                         "this on, the map package must be inside the step's bound.")
    ap.add_argument("--no-observe-after", action="store_true",
                    help="skip post-observation. Core then reports "
                         "committed_unverified and NEVER a plain commit.")
    ap.add_argument("--expect", default=D.DELTA_COMMITTED,
                    help="comma-separated delta outcomes this run accepts "
                         "(default: committed). partial_commit is never a success.")
    ap.add_argument("--operation-id", default=None)
    ap.add_argument("--out", default=None, help="path for the near-side report JSON")
    ap.add_argument("--far-out", default=None, help="path for the far-side document")
    ap.add_argument("--project", default=None, help="path to the .uproject")
    ap.add_argument("--engine-root", default=None)
    ap.add_argument("--ue-cmd", default=None)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--dry-run", action="store_true",
                    help="build the request, command and environment and print them; "
                         "never launches the editor")
    return ap


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    operation_id = args.operation_id or "op_wfcore_tx_" + uuid.uuid4().hex[:12]
    expected = {t.strip() for t in str(args.expect).split(",") if t.strip()}
    unknown = sorted(expected - set(D.DELTA_OUTCOMES))
    if unknown:
        print("ERROR: --expect names unknown outcome(s) {}; known outcomes are {}".format(
            unknown, list(D.DELTA_OUTCOMES)))
        return 2

    # --- the request -------------------------------------------------------- #
    if args.request and args.demo_spawn:
        print("ERROR: --request and --demo-spawn are two channels for one question; "
              "pass exactly one")
        return 2
    if args.request:
        try:
            request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print("ERROR: could not read --request {}: {}: {}".format(
                args.request, type(exc).__name__, exc))
            return 2
        if isinstance(request, dict) and not request.get("operation_id"):
            request["operation_id"] = operation_id
        operation_id = (request.get("operation_id") if isinstance(request, dict)
                        else operation_id) or operation_id
    elif args.demo_spawn:
        if not args.map:
            print("ERROR: --demo-spawn needs --map: an actor address is "
                  "'<map_package>:<label>' and there is no default map")
            return 2
        loc, loc_err = _parse_triple(args.location, [0.0, 0.0, 200.0])
        rot, rot_err = _parse_triple(args.rotation, [0.0, 0.0, 0.0])
        scl, scl_err = _parse_triple(args.scale, [1.0, 1.0, 1.0])
        for err in (loc_err, rot_err, scl_err):
            if err:
                print("ERROR: {}".format(err))
                return 2
        label = args.label or "WF_TX_{}".format(uuid.uuid4().hex[:8])
        request, err = build_demo_spawn_request(
            args.map, args.demo_spawn, label, loc, rot, scl, operation_id,
            save_map=args.save_map)
        if request is None:
            print("ERROR: {}".format(err))
            return 2
    else:
        print("ERROR: pass --request PATH or --demo-spawn CLASS")
        return 2

    errors, warnings = validate_request(request)
    for w in warnings:
        print("WARNING: {}".format(w))
    if errors:
        print("ERROR: the request would be refused by the executor before it took "
              "the lock; refusing here instead of paying an editor boot to find out:")
        for e in errors:
            print("  - {}".format(e))
        return 2

    # --- paths -------------------------------------------------------------- #
    report_dir = REPO_ROOT / "procedural" / "reports" / "core" / "transaction" / operation_id
    far_out = Path(args.far_out) if args.far_out else (report_dir / "far_side.json")
    near_out = Path(args.out) if args.out else (report_dir / "run_report.json")
    request_path = report_dir / "request.json"
    _write_json(request_path, request)

    env_extra = build_far_side_env(
        far_out, request_path, args.map, REPO_ROOT, operation_id,
        save_map=args.save_map, observe_after=not args.no_observe_after)

    if args.dry_run:
        print(json.dumps({
            "mode": "dry-run (no editor was launched)",
            "operation_id": operation_id,
            "request_path": str(request_path),
            "request": request,
            "environment": env_extra,
            "command": build_editor_command("<ue_cmd>", "<uproject>", FAR_SIDE),
        }, indent=2, sort_keys=True))
        return 0

    ue_cmd, uproject, err = resolve_paths(args)
    if err:
        print("ERROR: {}".format(err))
        return 2
    if not FAR_SIDE.is_file():
        print("ERROR: far side {} does not exist".format(FAR_SIDE))
        return 2

    # A stale document from a previous run would be read back as this run's result.
    try:
        if far_out.exists():
            far_out.unlink()
    except OSError as exc:
        print("ERROR: could not remove the previous far-side document {}: {}".format(
            far_out, exc))
        return 2

    command = build_editor_command(ue_cmd, uproject, FAR_SIDE)
    print("booting: {}".format(" ".join(str(c) for c in command)))
    exit_code, stdout, seconds = run_editor(command, env_extra, args.timeout)
    print("editor exited {} after {}s".format(exit_code, seconds))

    far_doc, boot_error = None, None
    if far_out.is_file():
        try:
            far_doc = json.loads(far_out.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            boot_error = "the far-side document at {} is not readable JSON: {}: {}".format(
                far_out, type(exc).__name__, exc)
    findings = rederive(far_doc)
    report = build_report(
        operation_id=operation_id, request=request, far_doc=far_doc,
        findings=findings, exit_code=exit_code,
        stdout_tail=(stdout or "")[-8000:], seconds=seconds,
        expected_outcomes=expected, command=command, env_extra=env_extra,
        far_out_path=str(far_out), boot_error=boot_error)
    _write_json(near_out, report)

    print("near-side report -> {}".format(near_out))
    print("far-side document -> {}".format(far_out))
    print("outcome={} verification={} rollback={} codes={}".format(
        findings.get("outcome"), findings.get("reported_verification"),
        findings.get("reported_rollback_completeness"),
        findings.get("failure_codes")))
    if report["accepted"]:
        print("ACCEPTED")
        return 0
    print("NOT ACCEPTED:")
    for reason in report["not_accepted_because"]:
        print("  - {}".format(reason))
    print("Far-side output does NOT reach stdout. Read {} and "
          "Saved/Logs/WorldForge.log to diagnose.".format(far_out))
    return 1


if __name__ == "__main__":
    sys.exit(main())
