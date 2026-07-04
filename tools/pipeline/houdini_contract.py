#!/usr/bin/env python3
"""houdini_contract.py — WorldForge v1.2 addendum Houdini intake contract.

Houdini is a GENERATED backend (addendum §1/§5): the baked/imported StaticMesh
WorldForge produces is generated_owned, but the source HDA must NOT be assumed
generated-owned — it is project_owned or third_party_owned depending on origin.
A houdini_generated asset is a normal MeshForge mesh asset (it lives in the mesh
catalog, source_type=houdini_generated) that additionally carries a
``houdini_intake`` block plus cook/bake/import reports.

Live cook/bake requires Houdini Engine on the runner. When Houdini is not
available (HOUDINI=metadata_only), the intake validates the declared cook/bake/
import report metadata from a prior cook — the same skip-when-no-live-tool
convention the v0.8 Houdini sidecar and the ue_generated path already use. It is
NOT fake green: the reports must be present, well-formed, and status-ok, and the
final-path / ownership / registry / provenance guarantees stay hard.
"""

from pathlib import Path

import mesh_contract as MC

REPO_ROOT = Path(__file__).resolve().parents[2]

# The HDA source may be project- or third-party-owned — NEVER assumed generated.
HDA_OWNERSHIP_CLASSES = ("project_owned", "third_party_owned")

# Required keys of a descriptor's ``houdini_intake`` block (addendum §5).
HOUDINI_INTAKE_REQUIRED = (
    "hda_id", "hda_name", "hda_path", "hda_ownership_class", "hda_version",
    "houdini_version", "houdini_engine_version", "unreal_plugin_version",
    "parameter_set", "parameter_hash", "cook_report", "bake_report",
    "import_report", "source_hash", "output_asset_hash",
)

# Cook/bake/import report required keys + the statuses that count as success.
HOUDINI_REPORT_REQUIRED = ("status", "hda_id", "generated_at_utc")
HOUDINI_REPORT_OK_STATUSES = ("ok", "success", "cooked", "baked", "imported")
HOUDINI_REPORT_FAIL_STATUSES = ("fail", "failed", "error")

# Modes for the HOUDINI flag.
HOUDINI_MODE_LIVE = "live"            # cook/bake really ran this session
HOUDINI_MODE_METADATA_ONLY = "metadata_only"  # validate declared prior-cook reports


def is_houdini_asset(record):
    return (record or {}).get("source_type") == "houdini_generated"


def houdini_intake_block(record):
    return (record or {}).get("houdini_intake") or {}


def iter_houdini_assets(catalog):
    """Yield (asset_id, entry) for houdini_generated assets in the mesh catalog."""
    for aid, entry in sorted((catalog.get("assets") or {}).items()):
        if entry.get("source_type") == "houdini_generated":
            yield aid, entry


def report_ok(report):
    """True if a cook/bake/import report block is present and status-ok."""
    if not isinstance(report, dict):
        return False
    status = str(report.get("status", "")).lower()
    return status in HOUDINI_REPORT_OK_STATUSES


def report_failed(report):
    if not isinstance(report, dict):
        return False
    return str(report.get("status", "")).lower() in HOUDINI_REPORT_FAIL_STATUSES


def houdini_mode_from_env():
    """Resolve HOUDINI flag: '1'/'live' -> live; 'metadata_only' -> metadata-only;
    anything falsy -> None (disabled)."""
    import os
    val = (os.environ.get("HOUDINI") or "").strip().lower()
    if val in ("1", "true", "yes", "on", "live"):
        return HOUDINI_MODE_LIVE
    if val in ("metadata_only", "metadata", "meta"):
        return HOUDINI_MODE_METADATA_ONLY
    return None
