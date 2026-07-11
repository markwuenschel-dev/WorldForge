#!/usr/bin/env python3
"""streaming_hygiene.py — v2.3 artifact-hygiene gate (Wave R).

Proves the streaming surface is internally consistent and free of drift/orphans:
  * every streaming GATE script (pipeline + operator) carries an 'Acceptance:'
    docstring line (libraries excluded)
  * no forbidden transient leaked under the streaming/operator roots
  * the counts line up with no silent desync: 2 regions, 6 tiles, >=24 anchors,
    >=4 routes, 24 mission + 24 npc bindings, 24 runtime reports, 48 lifecycle
    reports, 24 save states, 24 budget reports, 2 region views, 6 tile views
  * core index artifacts exist and are non-empty

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/streaming_hygiene.py --strict
Reports -> procedural/reports/streaming/streaming_hygiene_report.json
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
GEN = REPO_ROOT / "procedural" / "generated"
SREP = REPO_ROOT / "procedural" / "reports" / "streaming"
OP_REP = REPO_ROOT / "procedural" / "reports" / "operator"
LIBS = {"streaming_contracts.py", "streaming_spec.py"}
FORBIDDEN = ("Saved", "Intermediate", "DerivedDataCache", "Build", ".sav", "crash")


def _gate_scripts():
    s = [p for p in PIPELINE.glob("*.py")
         if ("streaming" in p.name or p.name in ("generate_cross_tile_anchors.py",
             "generate_cross_tile_routes.py", "generate_streamed_bindings.py",
             "run_streaming_forge_alpha.py", "v2_3_shield.py")) and p.name not in LIBS]
    s += [p for p in OPERATOR.glob("*.py") if "streaming" in p.name]
    return sorted(set(s))


def _count(root, pat):
    return len(list(root.glob(pat))) if root.is_dir() else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.3 streaming hygiene gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "streaming_hygiene", strict=strict)

    scripts = _gate_scripts()
    rep.check("hygiene::scripts_present", len(scripts) >= 15,
              "expected the streaming gate scripts (got {})".format(len(scripts)),
              code=F.STREAMING_HYGIENE_FAILED)
    for p in scripts:
        rep.check("hygiene::{}::acceptance_doc".format(p.name),
                  "Acceptance:" in p.read_text(encoding="utf-8", errors="replace"),
                  "gate script must carry an 'Acceptance:' docstring line",
                  code=F.STREAMING_HYGIENE_FAILED)

    for root in (GEN / "regions", GEN / "tiles", GEN / "anchors", GEN / "routes",
                 GEN / "streaming", SREP, OP_REP / "regions", OP_REP / "tiles"):
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and any(tok.lower() in p.as_posix().lower() for tok in FORBIDDEN):
                rep.check("hygiene::no_transient::{}".format(p.name), False,
                          "forbidden transient under {}: {}".format(root.name, p.name),
                          code=F.STREAMING_HYGIENE_FAILED)

    runtime_runs = len([d for d in (SREP / "runtime").iterdir()
                        if (SREP / "runtime").is_dir() and d.is_dir()
                        and (d / "report.json").is_file()]) if (SREP / "runtime").is_dir() else 0
    counts = {
        "regions": (_count(GEN / "regions", "*.json"), 2),
        "tiles": (_count(GEN / "tiles", "*.json"), 6),
        "mission_bindings": (_count(GEN / "streaming" / "mission_bindings", "*.json"), 24),
        "npc_bindings": (_count(GEN / "streaming" / "npc_bindings", "*.json"), 24),
        "runtime_reports": (runtime_runs, 24),
        "lifecycle_reports": (_count(SREP / "lifecycle", "*.json"), 48),
        "save_states": (_count(SREP / "save_load", "strun_*.json"), 24),
        "budget_reports": (_count(SREP / "budgets", "strun_*.json"), 24),
    }
    for name, (got, exp) in counts.items():
        rep.check("hygiene::count_{}".format(name), got == exp,
                  "expected {} {} (got {})".format(exp, name, got), code=F.STREAMING_HYGIENE_FAILED)
    rep.check("hygiene::anchors_min", _count(GEN / "anchors", "*.json") >= 24,
              "expected >= 24 anchors", code=F.STREAMING_HYGIENE_FAILED)
    rep.check("hygiene::routes_min", _count(GEN / "routes", "*.json") >= 4,
              "expected >= 4 routes", code=F.STREAMING_HYGIENE_FAILED)

    for label, path, exp in (
        ("region_views", OP_REP / "index" / "region_views.json", 2),
        ("tile_views", OP_REP / "index" / "tile_views.json", 6)):
        ok = path.is_file() and path.stat().st_size > 2
        rep.check("hygiene::core::{}".format(label), ok,
                  "core artifact missing/empty: {}".format(path.name), code=F.STREAMING_HYGIENE_FAILED)
        if ok:
            rep.check("hygiene::count_{}".format(label),
                      len(json.loads(path.read_text(encoding="utf-8"))) == exp,
                      "expected {} {}".format(exp, label), code=F.STREAMING_HYGIENE_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="streaming-hygiene", pack=None, strict=strict, status=rep.status,
        record_count=len(scripts), records_total=len(scripts), report_type="wf.streaming.hygiene.v1"))
    SREP.mkdir(parents=True, exist_ok=True)
    rep.write(SREP, "streaming_hygiene_report.json")
    rep.print_summary("streaming-hygiene")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
