#!/usr/bin/env python3
"""validate_determinism.py — WorldForge v1.0x determinism gate (Agent 7).

Proves the authoring pipeline is deterministic for a fixed (spec, seed) tuple:

  * same seed => same slice-spec semantic hash (regenerated twice, fresh procs);
  * same seed => same level-design + entity-anchor overlay ``content_hash``
    (regenerated twice in fresh processes — the ONLY per-run field is the
    provenance timestamp, which content_hash excludes);
  * same seed => same ownership/audit result (audit run twice is identical);
  * same seed => same validation report modulo ``stable_meta`` (runtime fields
    stripped);
  * a DIFFERENT seed must produce an allowed difference (the hashes change).

All regeneration happens in-memory or into throwaway temp names; the working tree
is left byte-identical. Nondeterminism is tagged ``FailureCode.DETERMINISM_FAILURE``.

Report: ``validate_determinism_report.json``.

Usage:
    PYTHONUTF8=1 python tools/pipeline/validate_determinism.py --pack desert_mvp_world --strict
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
from report_meta import build_meta, stable_meta, hash_obj  # noqa: E402
from world_pack_maps import enumerate_maps, report_dir_for, generated_spec_path  # noqa: E402
from registry import load_registry  # noqa: E402
import corrupt_world_pack as C  # noqa: E402
import generate_level_design as LD  # noqa: E402
import generate_entity_anchors as EA  # noqa: E402

DET = FailureCode.DETERMINISM_FAILURE
PY = sys.executable

_NAME_DEP = {"slice_id", "region_id", "map", "output_dir"}
_UNSTABLE = {"provenance", "generated_at_utc"}


def _run_py(code):
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run([PY, "-c", code], cwd=str(REPO_ROOT), env=env,
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _overlay_hash_emitter(pack, kind):
    if kind == "ld":
        body = (
            "import generate_level_design as L\n"
            "from world_pack_maps import enumerate_maps\n"
            "from report_meta import hash_obj\n"
            "wid,maps=enumerate_maps(%r)\n"
            "out={}\n"
            "for m in maps:\n"
            "    if not m.spec_exists: continue\n"
            "    o=L.build_overlay(m,wid)\n"
            "    out[m.slice_id]=hash_obj(L.content_for_hash(o))\n"
            "print(json.dumps(out))\n" % pack
        )
    else:
        body = (
            "import generate_entity_anchors as E\n"
            "wid,overlays,missing=E.generate_pack(%r,write=False)\n"
            "out={o['slice_id']:o['content_hash'] for o in overlays}\n"
            "print(json.dumps(out))\n" % pack
        )
    return ("import sys,json\nsys.path.insert(0,r%r)\n" % str(PIPELINE)) + body


def _fresh_overlay_hashes(pack, kind):
    rc, out, err = _run_py(_overlay_hash_emitter(pack, kind))
    if rc != 0:
        return None, err.strip()[:200]
    try:
        return json.loads(out.strip().splitlines()[-1]), None
    except Exception as exc:  # noqa: BLE001
        return None, "unparseable emitter output: {}".format(exc)


def _semantic_spec_hash(spec):
    cleaned = {k: v for k, v in spec.items() if k not in _NAME_DEP and k not in _UNSTABLE}
    return hash_obj(cleaned)


def _regen_spec_hash(entry, spec, name, seed):
    """Regenerate a throwaway slice spec via create_slice_spec.py; return semantic
    hash then delete the temp spec. Returns (hash_or_None, err)."""
    biome = entry.get("biome", "desert")
    cmd = [PY, str(PIPELINE / "create_slice_spec.py"),
           "--biome", biome, "--variant", entry.get("variant", ""),
           "--name", name, "--seed", str(seed)]
    if entry.get("placement_preset_id"):
        cmd += ["--placement", entry["placement_preset_id"]]
    if entry.get("state_preset_id"):
        cmd += ["--state-preset", entry["state_preset_id"]]
    if (spec.get("terrain_forge") or {}).get("recipe_id"):
        cmd += ["--terrain", spec["terrain_forge"]["recipe_id"]]
    if (spec.get("poi_forge") or {}).get("poi_type"):
        cmd += ["--poi", spec["poi_forge"]["poi_type"]]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
    tmp_spec = generated_spec_path(biome, name)
    try:
        if proc.returncode != 0 or not tmp_spec.is_file():
            return None, (proc.stderr or proc.stdout).strip()[:200]
        h = _semantic_spec_hash(json.loads(tmp_spec.read_text(encoding="utf-8")))
        return h, None
    finally:
        if tmp_spec.is_file():
            tmp_spec.unlink()


def validate_pack(pack, strict):
    world_pack_id, maps = enumerate_maps(pack)
    rep = ValidationReport("world_pack_id", world_pack_id, strict=strict)
    target = C.default_target(pack)
    reg = load_registry(REPO_ROOT)
    entry = reg.get(target, {})
    spec_path = generated_spec_path(entry.get("biome", "desert"), target)
    spec = json.loads(spec_path.read_text(encoding="utf-8")) if spec_path.is_file() else {}
    seed = spec.get("seed", 12345)

    # --- 1. spec determinism (same seed, two fresh regenerations) --------------
    # Snapshot registry so create_slice_spec side effects can't leak.
    # Reuse ONE throwaway name so only the seed varies (a different name would
    # change name-dependent fields like state.context_id and mask determinism).
    reg_before = C.REGISTRY_PATH.read_bytes() if C.REGISTRY_PATH.is_file() else None
    tmp_name = target + "_det_tmp"
    h1, e1 = _regen_spec_hash(entry, spec, tmp_name, seed)
    h2, e2 = _regen_spec_hash(entry, spec, tmp_name, seed)
    rep.check("spec::same_seed_same_hash", h1 is not None and h1 == h2,
              "regen1={} regen2={} ({}{})".format(
                  (h1 or "ERR")[:20], (h2 or "ERR")[:20], e1 or "", e2 or ""),
              code=DET)
    # different seed must change the hash
    h3, e3 = _regen_spec_hash(entry, spec, tmp_name, int(seed) + 777)
    rep.check("spec::diff_seed_diff_hash", h3 is not None and h1 is not None and h3 != h1,
              "seed {} hash != seed {} hash ({})".format(int(seed) + 777, seed, e3 or "ok"),
              code=DET)
    if reg_before is not None:
        C.REGISTRY_PATH.write_bytes(reg_before)

    # --- 2. overlay content_hash determinism (fresh processes) -----------------
    for kind, label in (("ld", "level_design"), ("ea", "entity_anchors")):
        a, ea1 = _fresh_overlay_hashes(pack, kind)
        b, ea2 = _fresh_overlay_hashes(pack, kind)
        ok = a is not None and b is not None and a == b and len(a) == len(maps)
        rep.check("overlay::{}::content_hash_stable".format(label), ok,
                  "two fresh regenerations {} ({} maps hashed)".format(
                      "MATCH" if (a == b) else "DIFFER", len(a or {})) + (
                      "; err={}".format(ea1 or ea2) if not ok else ""),
                  code=DET)

    # different seed changes overlay hashes (in-memory build with seed bump)
    import copy as _copy
    from world_pack_maps import MapRecord
    m0 = next((m for m in maps if m.slice_id == target and m.spec_exists), None)
    if m0 is not None:
        base = LD.build_overlay(m0, world_pack_id)
        bumped_spec = _copy.deepcopy(m0.spec)
        bumped_spec["seed"] = int(bumped_spec.get("seed", 0)) + 991
        m1 = MapRecord(dict(m0)); m1["spec"] = bumped_spec
        bumped = LD.build_overlay(m1, world_pack_id)
        rep.check("overlay::diff_seed_diff_hash",
                  hash_obj(LD.content_for_hash(base)) != hash_obj(LD.content_for_hash(bumped)),
                  "seed bump changes level-design overlay content_hash", code=DET)

    # --- 3. ownership/audit result determinism ---------------------------------
    def _audit_report():
        env = os.environ.copy(); env["PYTHONUTF8"] = "1"
        subprocess.run([PY, str(PIPELINE / "audit_generated_content.py"), "--quiet"],
                       cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
        p = REPO_ROOT / "procedural" / "reports" / "audit" / "audit_generated_content_report.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        return {"status": d.get("status"), "counts": d.get("counts"),
                "checks": {k: v.get("verdict") for k, v in d.get("checks", {}).items()}}
    a1 = _audit_report(); a2 = _audit_report()
    rep.check("ownership::audit_result_stable", a1 == a2,
              "two audit runs {} (status={})".format(
                  "identical" if a1 == a2 else "DIFFER", a1.get("status")),
              code=DET)

    # --- 4. validation report determinism modulo stable_meta -------------------
    def _pois_report():
        env = os.environ.copy(); env["PYTHONUTF8"] = "1"
        args = ["--pack", pack] + (["--strict"] if strict else [])
        subprocess.run([PY, str(PIPELINE / "validate_pois.py")] + args,
                       cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
        p = report_dir_for(world_pack_id) / "validate_pois_report.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        return {"status": d.get("status"),
                "checks": {k: v.get("verdict") for k, v in d.get("checks", {}).items()},
                "stable_meta": stable_meta(d.get("meta"))}
    r1 = _pois_report(); r2 = _pois_report()
    rep.check("report::validate_pois_stable_modulo_meta", r1 == r2,
              "two validate-pois runs {} (runtime meta stripped)".format(
                  "identical" if r1 == r2 else "DIFFER"),
              code=DET)

    rep.set_meta(build_meta(command="validate-determinism", pack=world_pack_id, strict=strict,
                            seeds=[seed], status=None, record_count=len(rep.checks) or 1,
                            input_spec_hash=hash_obj(spec)))
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Prove the WorldForge authoring pipeline is deterministic.")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = validate_pack(args.pack, strict)
    rep.finalize()
    rep.write(report_dir_for(rep.entity_id), "validate_determinism_report.json")
    rep.print_summary("validate-determinism")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
