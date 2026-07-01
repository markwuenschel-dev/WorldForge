#!/usr/bin/env python3
"""lifecycle_torture.py — WorldForge v1.0x lifecycle torture / regression gate (Agent 7).

Proves the world pack's lifecycle is HARDENED:

  1. For every corruption mode in ``corrupt_world_pack.MODES``:
       snapshot -> corrupt -> assert the appropriate detector
       (audit_generated_content / repair_world_pack dry-run / a core validator /
       an ownership cross-check) DETECTS and CLASSIFIES it; for repairable
       corruptions assert a deterministic regenerate/repair FIXES it; then restore.
     A corruption that goes UNDETECTED is a ``CORRUPTION_UNDETECTED`` FAIL.
     ``touch_human_owned_asset`` must leave the human-owned asset byte-identical
     (else ``REPAIR_TOUCHED_HUMAN_OWNED``).

  2. One full destroy(owned, scoped) -> rebuild(regenerate deterministically) ->
     revalidate cycle that must return green, with overlay content hashes proven
     stable across the cycle.

Everything runs against GENERATED-OWNED, deterministically-regenerable artifacts
or temp copies; the real UE maps/human assets are never mutated. A master snapshot
of the generated overlays/registry/specs is taken up front and restored in a
``finally`` so the working tree is left byte-identical to its pre-torture state.

Report: ``lifecycle_torture_report.json`` (parent-over-children, build_meta).

Usage:
    PYTHONUTF8=1 python tools/pipeline/lifecycle_torture.py --pack desert_mvp_world --strict
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = REPO_ROOT / "tools" / "pipeline"
sys.path.insert(0, str(PIPELINE))

from validation_report import ValidationReport, strict_from_env  # noqa: E402
from failure_codes import FailureCode  # noqa: E402
from report_meta import build_meta, hash_file  # noqa: E402
from world_pack_maps import enumerate_maps, report_dir_for  # noqa: E402

import corrupt_world_pack as C  # noqa: E402
import generate_level_design as LD  # noqa: E402
import generate_entity_anchors as EA  # noqa: E402
from registry import load_registry  # noqa: E402

PY = sys.executable
LIF = FailureCode.LIFECYCLE_FAILURE


# =============================================================================
# subprocess + snapshot helpers
# =============================================================================
def _run(script, extra):
    path = PIPELINE / script
    if not path.is_file():
        return None, "validator missing: {}".format(script)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run([PY, str(path)] + extra, cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True)
    tail = " | ".join((proc.stdout or "").strip().splitlines()[-1:])[:200]
    return proc.returncode, tail


def _snapshot_tree(paths, dest):
    """Copy a set of files/dirs into ``dest`` preserving relative structure."""
    import shutil
    dest = Path(dest)
    mapping = []
    for p in paths:
        p = Path(p)
        rel = p.relative_to(REPO_ROOT)
        target = dest / rel
        if p.is_dir():
            shutil.copytree(str(p), str(target), dirs_exist_ok=True)
        elif p.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(p), str(target))
        mapping.append((p, target, p.is_dir()))
    return mapping


def _restore_tree(mapping):
    """Restore live paths from a snapshot mapping, removing files added since."""
    import shutil
    for live, snap, is_dir in mapping:
        if is_dir:
            live_files = {q.relative_to(live) for q in live.rglob("*") if q.is_file()} if live.is_dir() else set()
            snap_files = {q.relative_to(snap) for q in snap.rglob("*") if q.is_file()} if snap.is_dir() else set()
            for extra in live_files - snap_files:
                try:
                    (live / extra).unlink()
                except OSError:
                    pass
            for rel in snap_files:
                dst = live / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(snap / rel), str(dst))
        else:
            if snap.is_file():
                live.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(snap), str(live))


def _master_snapshot_paths():
    return [
        C.LEVEL_DESIGN_DIR,
        C.ENTITY_ANCHORS_DIR,
        C.PLACEMENT_DIR,
        C.REGISTRY_PATH,
        REPO_ROOT / "procedural" / "slices" / "desert" / "generated",
    ]


# =============================================================================
# detectors — one per corruption class. Return (detected: bool, code, detail).
# =============================================================================
def _pois_detects(pack, strict):
    import validate_pois as VP
    rep = VP.validate_pack(pack, strict)
    rep.finalize()
    return (not rep.passed), FailureCode.POI_USABILITY_FAILURE, \
        "{} POI failure(s)".format(len(rep.failures))


def _anchors_detects(pack, strict):
    import validate_entity_anchors as VE
    rep = VE.validate_pack(pack, strict)
    rep.finalize()
    return (not rep.passed), FailureCode.ENTITY_ANCHOR_FAILURE, \
        "{} entity-anchor failure(s)".format(len(rep.failures))


def _env_detects(pack, strict, profiles_root, code):
    import validate_environment_contract as VC
    rep = VC.validate_pack(pack, strict, profiles_root=profiles_root)
    rep.finalize()
    return (not rep.passed), code, "{} environment failure(s)".format(len(rep.failures))


def _repair_dryrun_detects(pack):
    rc, tail = _run("repair_world_pack.py", ["--pack", pack])
    return (rc not in (0, None)), FailureCode.REGISTRY_MISSING_ENTRY, "repair rc={} {}".format(rc, tail)


def _audit_detects(code):
    rc, tail = _run("audit_generated_content.py", ["--quiet"])
    return (rc not in (0, None)), code, "audit rc={}".format(rc)


def detect_material_reference(target):
    """Cross-check: the spec's declared terrain.material_mi must appear in the
    registry entry's referenced_assets. Missing => broken material reference."""
    reg = load_registry(REPO_ROOT)
    entry = reg.get(target, {})
    sp = C._spec_path_for(target)
    spec = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else {}
    mat = (spec.get("terrain") or {}).get("material_mi")
    if not mat:
        return False, FailureCode.ASSET_REFERENCE_FAILURE, "no material_mi in spec"
    present = mat in (entry.get("referenced_assets", []) or [])
    return (not present), FailureCode.ASSET_REFERENCE_FAILURE, \
        "material {} {} in referenced_assets".format(mat, "present" if present else "MISSING")


def detect_poi_reference(target):
    """The generated spec must carry a poi_forge block whose descriptor resolves."""
    sp = C._spec_path_for(target)
    spec = json.loads(sp.read_text(encoding="utf-8")) if sp.is_file() else {}
    pf = spec.get("poi_forge")
    if not isinstance(pf, dict) or not pf:
        return True, FailureCode.ASSET_REFERENCE_FAILURE, "poi_forge reference absent from spec"
    dpath = pf.get("descriptor_path")
    resolves = bool(dpath) and (REPO_ROOT / dpath).is_file()
    return (not resolves), FailureCode.ASSET_REFERENCE_FAILURE, \
        "poi descriptor {}".format("resolves" if resolves else "MISSING")


def detect_duplicate_record(pack):
    """Registry integrity: no two slice records may claim the same map_path or the
    same owned .umap. A duplicate/rogue record collides and is flagged."""
    reg = load_registry(REPO_ROOT)
    seen = {}
    collisions = []
    for sid, entry in reg.items():
        keys = [entry.get("map_path")]
        keys += list(entry.get("owned_assets", []) or [])
        for k in keys:
            if not k:
                continue
            if k in seen and seen[k] != sid:
                collisions.append((k, seen[k], sid))
            else:
                seen.setdefault(k, sid)
    return (bool(collisions), FailureCode.REGISTRY_INCONSISTENT,
            "{} registry map_path/owned collision(s)".format(len(collisions)))


def detect_stale_report(pack):
    rpt = C.REPORTS_DIR / pack / "validate_pois_report.json"
    if not rpt.is_file():
        return True, FailureCode.REPORT_STALE, "report missing"
    data = json.loads(rpt.read_text(encoding="utf-8"))
    meta = data.get("meta") or {}
    stale = (meta.get("record_count", -1) == 0 and data.get("passed") is True) or \
            str(meta.get("timestamp", "")).startswith("2000-")
    # If Agent 1's report-integrity validator exists, corroborate with it.
    integ = PIPELINE / "validate_report_integrity.py"
    corroborated = None
    if integ.is_file():
        rc, _ = _run("validate_report_integrity.py", ["--pack", pack])
        corroborated = rc not in (0, None)
    detail = "stale-detected={} report_integrity_present={} corroborated={}".format(
        stale, integ.is_file(), corroborated)
    return (stale or bool(corroborated)), FailureCode.REPORT_STALE, detail


def detect_human_untouched(manifest):
    """touch_human_owned_asset guard: the human-owned asset must be byte-identical
    (hash unchanged). Returns (guard_held, code, detail)."""
    human = manifest.get("human_owned")
    marker = manifest.get("marker")
    pre = None
    if marker and Path(marker).is_file():
        pre = json.loads(Path(marker).read_text(encoding="utf-8")).get("pre_hash")
    cur = hash_file(REPO_ROOT / human) if human else None
    untouched = (pre == cur)
    return untouched, FailureCode.REPAIR_TOUCHED_HUMAN_OWNED, \
        "human_owned={} untouched={} (pre==cur)".format(human, untouched)


def classify_corruption(mode, detected, detector_code):
    """Map a detection outcome to the stable failure code the gate records.

    An UNDETECTED corruption is always ``CORRUPTION_UNDETECTED``. For the
    human-touch guard, a held guard is clean (None); a broken guard is
    ``REPAIR_TOUCHED_HUMAN_OWNED``.
    """
    if mode == "touch_human_owned_asset":
        return None if detected else FailureCode.REPAIR_TOUCHED_HUMAN_OWNED
    return detector_code if detected else FailureCode.CORRUPTION_UNDETECTED


def run_detector(mode, pack, target, manifest, strict):
    """Route a corruption mode to its detector. Returns (detected, code, detail).

    For ``touch_human_owned_asset`` ``detected`` means the guard HELD (human
    untouched); a False there is the REPAIR_TOUCHED_HUMAN_OWNED violation.
    """
    if mode in ("delete_generated_asset", "move_generated_asset", "partial_destroy"):
        return _pois_detects(pack, strict)
    if mode in ("remove_entity_anchor", "partial_repair"):
        return _anchors_detects(pack, strict)
    if mode in ("delete_generated_manifest", "truncate_manifest", "orphan_generated_asset"):
        return _repair_dryrun_detects(pack)
    if mode == "duplicate_manifest_record":
        return detect_duplicate_record(pack)
    if mode == "bad_generated_path":
        return _audit_detects(FailureCode.PATH_NOT_OWNED)
    if mode == "remove_material_reference":
        return detect_material_reference(target)
    if mode == "remove_poi_reference":
        return detect_poi_reference(target)
    if mode == "remove_environment_profile":
        return _env_detects(pack, strict, manifest.get("profiles_root"),
                            FailureCode.ENVIRONMENT_PROFILE_FAILURE)
    if mode == "remove_lighting_profile":
        return _env_detects(pack, strict, manifest.get("profiles_root"),
                            FailureCode.LIGHTING_PROFILE_FAILURE)
    if mode == "touch_human_owned_asset":
        return detect_human_untouched(manifest)
    if mode == "stale_report":
        return detect_stale_report(pack)
    raise ValueError("no detector for mode {}".format(mode))


# =============================================================================
# repair — deterministic regeneration for the repairable modes.
# =============================================================================
def repair_mode(mode, pack, target):
    if mode in ("delete_generated_asset", "move_generated_asset", "partial_destroy"):
        LD.generate_pack(pack)
        if mode == "partial_destroy":
            _run("repair_world_pack.py", ["--pack", pack, "--apply"])
        return True
    if mode in ("remove_entity_anchor", "partial_repair"):
        EA.generate_pack(pack, write=True)
        return True
    return False


# =============================================================================
# destroy -> rebuild -> revalidate cycle
# =============================================================================
def _overlay_hashes(pack):
    """Content hashes (runtime-stripped) for LD + EA overlays, keyed slice_id."""
    world_pack_id, maps = enumerate_maps(pack)
    out = {}
    for m in maps:
        sid = m.slice_id
        ld_p = C.LEVEL_DESIGN_DIR / (sid + ".json")
        ea_p = C.ENTITY_ANCHORS_DIR / (sid + ".json")
        h = {}
        if ld_p.is_file():
            from report_meta import hash_obj
            o = json.loads(ld_p.read_text(encoding="utf-8"))
            h["ld"] = hash_obj(LD.content_for_hash(o))
        if ea_p.is_file():
            o = json.loads(ea_p.read_text(encoding="utf-8"))
            h["ea"] = o.get("content_hash") or EA.content_hash(o)
        out[sid] = h
    return out


def destroy_rebuild_revalidate(rep, pack, strict):
    """Run one scoped-owned destroy -> deterministic rebuild -> revalidate cycle."""
    pre = _overlay_hashes(pack)

    # (a) prove the real UE-scoped destroy tool works in DRY-RUN (never --confirm).
    rc, tail = _run("destroy_world_pack.py", ["--pack", pack])
    rep.check("cycle::destroy_dryrun_safe", rc == 0,
              "destroy_world_pack dry-run rc={} ({})".format(rc, tail), code=LIF)

    # (b) scoped-owned destroy of regenerable overlays (generated-owned only).
    removed = 0
    for d in (C.LEVEL_DESIGN_DIR, C.ENTITY_ANCHORS_DIR):
        for f in sorted(d.glob("*.json")):
            f.unlink()
            removed += 1
    rep.check("cycle::owned_overlays_destroyed", removed > 0,
              "removed {} generated-owned overlay file(s)".format(removed), code=LIF)

    # (c) deterministic rebuild.
    _wid, ld_res = LD.generate_pack(pack)
    _wid2, ea_overlays, ea_missing = EA.generate_pack(pack, write=True)
    ld_ok = all(s == "OK" for _sid, s, _d in ld_res)
    rep.check("cycle::rebuild_level_design", ld_ok,
              "regenerated {} level-design overlays".format(sum(1 for _s, st, _d in ld_res if st == "OK")),
              code=LIF)
    rep.check("cycle::rebuild_entity_anchors", not ea_missing,
              "regenerated {} entity-anchor overlays (missing={})".format(len(ea_overlays), len(ea_missing)),
              code=LIF)

    # (d) revalidate: core gates must all be green again.
    yaml_arg = "procedural/world_packs/{}.yaml".format(pack)
    common = ["--strict"] if strict else []
    gates = [
        ("validate-world-pack-spec", "validate_world_pack_spec.py", ["--pack", yaml_arg] + common),
        ("validate-world-pack", "validate_world_pack.py", ["--pack", yaml_arg] + common),
        ("validate-environment-contract", "validate_environment_contract.py", ["--pack", pack] + common),
        ("validate-pois", "validate_pois.py", ["--pack", pack] + common),
        ("validate-entity-anchors", "validate_entity_anchors.py", ["--pack", pack] + common),
    ]
    for gid, script, gargs in gates:
        rc, tail = _run(script, gargs)
        rep.check("cycle::revalidate::{}".format(gid), rc == 0,
                  "{} rc={} ({})".format(gid, rc, tail), code=LIF)

    # (d') report-integrity is a concurrent Agent-1 landing; corroborate if present,
    # but the cycle's PASS never hinges on it (known concurrent-landing gap).
    integ = PIPELINE / "validate_report_integrity.py"
    if integ.is_file():
        rc, tail = _run("validate_report_integrity.py", ["--pack", pack] + common)
        rep.warn_only("cycle::revalidate::report_integrity_present", rc == 0,
                      "report-integrity rc={} ({})".format(rc, tail),
                      code=FailureCode.REPORT_INTEGRITY_FAILURE)
    else:
        rep.warn_only("cycle::revalidate::report_integrity_present", True,
                      "validate_report_integrity.py absent — known concurrent Agent-1 gap; "
                      "core gates carry the PASS criteria",
                      code=FailureCode.VALIDATOR_SKIPPED)

    # (e) determinism through the cycle: rebuilt overlay hashes == pre-destroy.
    post = _overlay_hashes(pack)
    drift = [sid for sid in pre if pre.get(sid) != post.get(sid)]
    rep.check("cycle::overlay_hashes_stable", not drift,
              "overlay content hashes stable across destroy->rebuild ({} drifted)".format(len(drift)),
              code=FailureCode.DETERMINISM_FAILURE)


# =============================================================================
# per-mode torture
# =============================================================================
def torture_mode(rep, pack, target, strict):
    """Snapshot->corrupt->detect->[repair]->restore for every corruption mode."""
    import tempfile
    for mode in sorted(C.MODES.keys()):
        spec = C.MODES[mode]
        snap_dir = tempfile.mkdtemp(prefix="wf_torture_{}_".format(mode))
        manifest = None
        try:
            manifest = C.apply_corruption(mode, pack, target, snap_dir=snap_dir)

            detected, code, detail = run_detector(mode, pack, target, manifest, strict)

            if mode == "touch_human_owned_asset":
                # 'detected' == guard held (human untouched). A violation is fatal.
                rep.check("mode::{}::human_untouched".format(mode), detected,
                          detail, code=FailureCode.REPAIR_TOUCHED_HUMAN_OWNED)
            else:
                rep.check("mode::{}::detected".format(mode), detected,
                          "corruption {}: {}".format(
                              "DETECTED" if detected else "UNDETECTED", detail),
                          code=classify_corruption(mode, detected, code))

            # Repairable corruptions must be fixable by deterministic regeneration.
            if spec["repairable"]:
                repaired = repair_mode(mode, pack, target)
                still, _c, rdetail = run_detector(mode, pack, target, manifest, strict)
                rep.check("mode::{}::repaired".format(mode), repaired and not still,
                          "repair {} (post-repair detector clear={})".format(
                              "applied" if repaired else "FAILED", not still),
                          code=LIF)
        except Exception as exc:  # noqa: BLE001
            rep.check("mode::{}::ran".format(mode), False,
                      "torture harness raised: {}".format(exc), code=LIF)
        finally:
            if manifest is not None:
                C.restore(manifest)


# =============================================================================
# main
# =============================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="WorldForge lifecycle torture / regression gate.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--target", default=None)
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    world_pack_id, maps = enumerate_maps(args.pack)
    target = args.target or C.default_target(args.pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)

    if not target:
        rep.error("no overlay-complete target slice found for pack {}".format(args.pack))
        rep.write(report_dir_for(world_pack_id), "lifecycle_torture_report.json")
        rep.print_summary("lifecycle-torture")
        sys.exit(rep.exit_code)

    # Master snapshot so the tree is left byte-identical regardless of outcome.
    import tempfile
    master_dir = tempfile.mkdtemp(prefix="wf_torture_master_")
    mapping = _snapshot_tree(_master_snapshot_paths(), master_dir)
    try:
        torture_mode(rep, args.pack, target, strict)
        destroy_rebuild_revalidate(rep, args.pack, strict)
    finally:
        _restore_tree(mapping)
        import shutil
        shutil.rmtree(master_dir, ignore_errors=True)

    n_modes = len(C.MODES)
    rep.set_meta(build_meta(command="lifecycle-torture", pack=world_pack_id, strict=strict,
                            torture=True, status=None, record_count=n_modes,
                            extra={"target": target, "modes": sorted(C.MODES.keys())}))
    rep.finalize()
    rep.write(report_dir_for(world_pack_id), "lifecycle_torture_report.json")
    rep.print_summary("lifecycle-torture")
    print("[lifecycle-torture] target={} modes={} destroy->rebuild->revalidate cycle run".format(
        target, n_modes))
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
