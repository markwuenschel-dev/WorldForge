#!/usr/bin/env python3
"""validate_failure_codes.py — prove the failure-code registry is coherent.

v1.5 Agent-0D gate. Asserts, under STRICT, that:

  * every FailureCode constant is a well-formed ``WFnnn_SHORT_NAME`` string;
  * WF numbers are unique (no two codes share a band number);
  * every code has a severity ("fail"/"warn") — the v1.5 backfill guarantees a
    default, so a missing severity here means the backfill regressed;
  * every code appears in GATE_TAXONOMY so full-shield can roll it up by lane;
  * the v1.5 bands (350–436) are present — a spot guard that the new codes did
    not get dropped by a bad merge.

This is what stops a validator from emitting a generic failure when a
domain-specific code exists, and stops the taxonomy from silently losing a code.
Reports -> procedural/reports/failure_codes/validate_failure_codes_report.json
"""

import re
import sys
from pathlib import Path

from failure_codes import (FailureCode, SEVERITY, GATE_TAXONOMY, all_codes,
                           code_number)
from report_meta import build_meta
from validation_report import ValidationReport, strict_from_env

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "failure_codes"

_CODE_RE = re.compile(r"^WF\d{3}_[A-Z0-9_]+$")

# Spot-check anchors: at least one code from each v1.5 band must exist.
V1_5_ANCHORS = (
    FailureCode.ASSET_NEED_ANALYSIS_FAILURE,       # 350 AssetAcquisition
    FailureCode.COVER_PROXY_REPLACEMENT_FAILURE,   # 390 AssetRealization
    FailureCode.VISUAL_KIT_CONTRACT_FAILURE,       # 400 VisualEnvironment
    FailureCode.LIFECYCLE_THIRD_PARTY_DESTROY_ATTEMPT,  # 420 lifecycle/package
    FailureCode.V1_5_REPORT_INTEGRITY_FAILURE,     # 436 integrity
)


def validate():
    strict = strict_from_env()
    rep = ValidationReport("registry", "failure_codes", strict=strict)

    named = {k: v for k, v in vars(FailureCode).items()
             if not k.startswith("_") and isinstance(v, str)}

    # 1. well-formed
    malformed = [c for c in named.values() if not _CODE_RE.match(c)]
    rep.check("codes_well_formed", not malformed,
              "malformed: {}".format(malformed[:5]),
              code=FailureCode.V1_5_TAXONOMY_FAILURE)

    # 2. unique WF numbers
    seen = {}
    dupes = []
    for name, code in named.items():
        n = code_number(code)
        if n in seen:
            dupes.append("{}={} collides with {}".format(name, n, seen[n]))
        else:
            seen[n] = name
    rep.check("wf_numbers_unique", not dupes, "; ".join(dupes[:5]),
              code=FailureCode.V1_5_TAXONOMY_FAILURE)

    # 3. every code has a severity
    no_sev = [c for c in named.values() if c not in SEVERITY]
    rep.check("every_code_has_severity", not no_sev,
              "no severity: {}".format(no_sev[:5]),
              code=FailureCode.V1_5_TAXONOMY_FAILURE)
    bad_sev = [c for c in named.values()
               if SEVERITY.get(c) not in ("fail", "warn")]
    rep.check("severity_values_valid", not bad_sev,
              "bad severity: {}".format(bad_sev[:5]),
              code=FailureCode.V1_5_TAXONOMY_FAILURE)

    # 4. every code in the gate taxonomy
    tax_codes = set(GATE_TAXONOMY.values())
    missing_tax = [c for c in named.values() if c not in tax_codes]
    rep.check("every_code_in_gate_taxonomy", not missing_tax,
              "missing from taxonomy: {}".format(missing_tax[:5]),
              code=FailureCode.V1_5_TAXONOMY_FAILURE)

    # 5. v1.5 bands present
    all_set = set(named.values())
    missing_anchor = [c for c in V1_5_ANCHORS if c not in all_set]
    rep.check("v1_5_bands_present", not missing_anchor,
              "missing v1.5 anchor codes: {}".format(missing_anchor),
              code=FailureCode.V1_5_TAXONOMY_FAILURE)

    total = len(named)
    rep.set_meta(build_meta(
        "validate-failure-codes", pack=None, strict=strict,
        report_type="wf.v1_5.failure_codes.v1", status=None,
        record_count=total, records_total=total))
    rep.finalize()
    rep.write(REPORT_DIR, "validate_failure_codes_report.json")
    rep.print_summary("validate-failure-codes")
    return rep.exit_code


if __name__ == "__main__":
    sys.exit(validate())
