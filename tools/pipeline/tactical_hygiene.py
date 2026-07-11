#!/usr/bin/env python3
"""tactical_hygiene.py — v2.4 artifact-hygiene gate (Wave R).

Proves the tactical surface is internally consistent and free of drift/orphans:
  * every tactical GATE script (pipeline + operator) carries an 'Acceptance:' docstring
    line (libraries excluded)
  * no forbidden transient leaked under the tactical/operator roots
  * the counts line up with no silent desync: 3 roles, 2 profiles, 24 affordance maps,
    48 NPC bindings, 24 group states, 24 runtime reports, 24 decision bundles, 24 save
    states, 24 budget reports, 24 scenario views, 48 NPC views
  * core index artifacts exist and are non-empty

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/tactical_hygiene.py --strict
Reports -> procedural/reports/tactical/tactical_hygiene_report.json
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

PIPELINE = REPO_ROOT / "tools" / "pipeline"
OPERATOR = REPO_ROOT / "tools" / "operator"
GEN = REPO_ROOT / "procedural" / "generated" / "tactical"
TREP = REPO_ROOT / "procedural" / "reports" / "tactical"
OP_REP = REPO_ROOT / "procedural" / "reports" / "operator" / "tactical"
LIBS = {"tactical_contracts.py", "tactical_spec.py", "tactical_runtime.py"}
# Match forbidden UE transients as PATH SEGMENTS / suffixes, not arbitrary substrings —
# a legitimately named report like build_tactical_index_report.json must not trip "Build".
FORBIDDEN_DIRS = ("Saved", "Intermediate", "DerivedDataCache", "Build")
FORBIDDEN_SUFFIX = (".sav",)


def _is_transient(root, p):
    rel_parts = p.relative_to(root).parts
    if any(seg in FORBIDDEN_DIRS for seg in rel_parts):
        return True
    if p.suffix.lower() in FORBIDDEN_SUFFIX:
        return True
    return "crash" in p.name.lower()


def _gate_scripts():
    s = [p for p in PIPELINE.glob("*.py")
         if ("tactical" in p.name or p.name == "v2_4_shield.py") and p.name not in LIBS]
    s += [p for p in OPERATOR.glob("*.py") if "tactical" in p.name]
    return sorted(set(s))


def _count(root, pat):
    return len(list(root.glob(pat))) if root.is_dir() else 0


def _view_count(path):
    if not (path.is_file() and path.stat().st_size > 2):
        return -1
    return len(json.loads(path.read_text(encoding="utf-8")))


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.4 tactical hygiene gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "tactical_hygiene", strict=strict)

    scripts = _gate_scripts()
    rep.check("hygiene::scripts_present", len(scripts) >= 18,
              "expected the tactical gate scripts (got {})".format(len(scripts)),
              code=F.TACTICAL_HYGIENE_FAILED)
    for p in scripts:
        rep.check("hygiene::{}::acceptance_doc".format(p.name),
                  "Acceptance:" in p.read_text(encoding="utf-8", errors="replace"),
                  "gate script must carry an 'Acceptance:' docstring line",
                  code=F.TACTICAL_HYGIENE_FAILED)

    for root in (GEN, TREP, OP_REP):
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and _is_transient(root, p):
                rep.check("hygiene::no_transient::{}".format(p.name), False,
                          "forbidden transient under {}: {}".format(root.name, p.name),
                          code=F.TACTICAL_HYGIENE_FAILED)

    counts = {
        "roles": (_count(GEN / "roles", "*.json"), 3),
        "profiles": (_count(GEN / "profiles", "*.json"), 2),
        "affordances": (_count(GEN / "affordances", "*.json"), 24),
        "bindings": (_count(GEN / "bindings", "*.json"), 48),
        "groups": (_count(GEN / "groups", "*.json"), 24),
        "runtime_reports": (_count(TREP / "runtime", "tac_*.json"), 24),
        "decision_bundles": (_count(TREP / "decisions", "tac_*.json"), 24),
        "save_states": (_count(TREP / "save_load", "tss_*.json"), 24),
        "budget_reports": (_count(TREP / "budgets", "tbr_*.json"), 24),
    }
    for name, (got, exp) in counts.items():
        rep.check("hygiene::count_{}".format(name), got == exp,
                  "expected {} {} (got {})".format(exp, name, got), code=F.TACTICAL_HYGIENE_FAILED)

    for label, path, exp in (
        ("scenario_views", OP_REP / "scenario_views.json", 24),
        ("npc_views", OP_REP / "npc_views.json", 48)):
        got = _view_count(path)
        rep.check("hygiene::core::{}".format(label), got == exp,
                  "core artifact missing/miscounted: {} (got {}, want {})".format(
                      path.name, got, exp), code=F.TACTICAL_HYGIENE_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="tactical-hygiene", pack=None, strict=strict, status=rep.status,
        record_count=len(scripts), records_total=len(scripts), report_type="wf.tactical.hygiene.v1"))
    TREP.mkdir(parents=True, exist_ok=True)
    rep.write(TREP, "tactical_hygiene_report.json")
    rep.print_summary("tactical-hygiene")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
