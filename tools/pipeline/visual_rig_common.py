#!/usr/bin/env python3
"""visual_rig_common.py — WorldForge v1.3.5 environment-rig validator shared helpers (Agent 3).

Small, dependency-light helper so the seven environment-rig / atmosphere
validators enumerate the 60 materialized rigs the same way and share the
component-lookup + numeric-guard primitives. It reads the resolved rig SPEC +
its materialization_report from disk (there is NO live UE editor on this runner —
the load-bearing rule, brief §5, is that a fully-RESOLVED rig passes and a rig
that is only a JSON name with no bound component/params fails).

Enumeration source of truth: the visual catalog (60 maps). Each catalog entry
carries the rig_path; we read that rig JSON. Nothing here is UE-live.
"""

import json
from pathlib import Path

import visual_contract as VC
from visual_catalog import load_visual_catalog


def iter_rigs(repo_root):
    """Yield (slice_id, rig_or_None, error) for each rig, catalog-ordered.

    Enumerates the 60 maps from the visual catalog; for each, reads the rig JSON
    named by its ``rig_path`` (falling back to <ENV_RIGS_REL>/<slice_id>.json).
    A missing/unparseable rig yields (slice_id, None, error) so the caller can
    record a blocking failure rather than silently skipping.
    """
    repo_root = Path(repo_root)
    catalog = load_visual_catalog(repo_root)
    maps = catalog.get("maps") or {}
    for sid in sorted(maps):
        entry = maps.get(sid) or {}
        rel = entry.get("rig_path") or "{}/{}.json".format(VC.ENV_RIGS_REL, sid)
        path = repo_root / rel
        if not path.is_file():
            yield sid, None, "rig file missing: {}".format(rel)
            continue
        try:
            rig = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            yield sid, None, "rig unparseable ({}): {}".format(rel, exc)
            continue
        if not isinstance(rig, dict):
            yield sid, None, "rig is not an object: {}".format(rel)
            continue
        yield sid, rig, None


def components_by_type(rig):
    """Return {component_type: component_dict} for a rig's declared components."""
    out = {}
    for comp in (rig.get("components") or []):
        if isinstance(comp, dict) and comp.get("component"):
            out[comp["component"]] = comp
    return out


def is_number(value):
    """True for a real int/float (bool is NOT a number here)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)
