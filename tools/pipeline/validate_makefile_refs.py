#!/usr/bin/env python3
"""validate_makefile_refs.py — every Makefile pipeline reference must resolve.

Integrity fitness-check (audit candidate C3): a Makefile recipe that invokes
`$(PYTHON) tools/pipeline/X.py` for a script that does not exist is drift — the
documented command surface silently fails. This check parses every such reference
and asserts the target file is present, so a renamed/removed/never-built script is
caught the moment it lands (it would have caught the v2.0 `build_vertical_slice.py`
phantom target).

KNOWN_MISSING is a small, documented allowlist of PRE-EXISTING (pre-v2.0) missing
references, tracked as adjacent findings in the audit ledger — the check stays
green on them but FAILS on any NEW missing reference, and also fails if an
allowlisted script reappears (a stale allowlist entry). This keeps the check
honest without forcing an out-of-scope cleanup of older milestones.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/validate_makefile_refs.py --strict
Reports -> procedural/reports/integrity/validate_makefile_refs_report.json
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "integrity"
MAKEFILE = REPO_ROOT / "Makefile"
_REF_RE = re.compile(r"tools/pipeline/([A-Za-z0-9_]+\.py)")

# Pre-existing (pre-v2.0) missing references — tracked adjacent findings, NOT
# fixed by the v2.0 audit scope. See scratchpad/v2_0_integrity_audit.html.
KNOWN_MISSING = {
    "diff_world_pack.py",              # Makefile:643 (v0.x world-pack diff)
    "materialize_visual_environment_kits.py",  # Makefile:1035 (v1.5 visual kits)
}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Makefile pipeline-reference integrity check.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("repo", "makefile_refs", strict=strict)

    text = MAKEFILE.read_text(encoding="utf-8", errors="ignore")
    refs = sorted(set(_REF_RE.findall(text)))
    rep.check("refs_found", len(refs) > 0, "no pipeline refs parsed from Makefile",
              code=F.GENERATION_FAILURE)

    pipe = REPO_ROOT / "tools" / "pipeline"
    missing = [r for r in refs if not (pipe / r).is_file()]
    new_missing = [r for r in missing if r not in KNOWN_MISSING]
    rep.check("no_new_missing_refs", not new_missing,
              "Makefile references nonexistent script(s): {}".format(new_missing),
              code=F.GENERATION_FAILURE)

    # a KNOWN_MISSING that now exists is a stale allowlist entry — force cleanup.
    stale_allow = [r for r in KNOWN_MISSING if (pipe / r).is_file()]
    rep.check("allowlist_not_stale", not stale_allow,
              "KNOWN_MISSING entries now exist (remove from allowlist): {}".format(stale_allow),
              code=F.REGISTRY_INCONSISTENT)

    rep.finalize()
    rep.set_meta(build_meta(command="validate-makefile-refs", pack=None, strict=strict,
                            status=rep.status, record_count=len(refs), records_total=len(refs),
                            report_type="wf.integrity.makefile_refs.v1"))
    rep.write(REPORT_DIR, "validate_makefile_refs_report.json")
    rep.print_summary("validate-makefile-refs")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
