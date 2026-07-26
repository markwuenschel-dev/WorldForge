#!/usr/bin/env python3
"""scene_survey_hygiene.py — v2.6 artifact-hygiene gate (SceneSurveyForge).

Ports the tactical_hygiene.py house pattern onto the v2.6 scene_survey surface:
proves the module is internally consistent and free of drift/orphans.

  * every scene_survey GATE script (pipeline + operator) carries an 'Acceptance:'
    docstring line (the documented command surface stays real; libraries excluded)
  * no forbidden UE transient (Saved/, Intermediate/, DerivedDataCache/, Build/,
    *.sav, crash logs) leaked under the scene_survey generated + report roots
  * the contract spine's dotted namespaces have not drifted: every RT_* report_type
    is a 'wf.scene_survey.<type>.v1' triple (report_type prefix + schema_version
    convention), the shared AUTHORING_TS is a deterministic midnight stamp (NOT
    wall-clock), and the declared report/profile roots match the on-disk tree
  * the core report artifacts exist, are non-empty, parse, and carry a
    scene_survey-namespaced report_type

The tactical/streaming/quest_faction hygiene gates additionally assert fixed
generated-artifact counts (24 affordances, 48 bindings, ...) and operator view
counts. v2.6 scene_survey is contract-only — no generated artifact matrix or
operator view tree exists yet — so those count-coherence rails have no surface to
bind to and are honestly omitted rather than asserted over zero artifacts. See the
REPORT-BACK finding.

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/pipeline/scene_survey_hygiene.py --strict
Reports -> procedural/reports/scene_survey/scene_survey_hygiene_report.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import scene_survey_contracts as SSC  # noqa: E402
from failure_codes import FailureCode as F  # noqa: E402
from report_meta import build_meta, strict_from_env  # noqa: E402
from validation_report import ValidationReport  # noqa: E402

PIPELINE = REPO_ROOT / "tools" / "pipeline"
OPERATOR = REPO_ROOT / "tools" / "operator"
GEN = REPO_ROOT / "procedural" / "generated" / "scene_survey"
SREP = REPO_ROOT / "procedural" / "reports" / "scene_survey"
OP_REP = REPO_ROOT / "procedural" / "reports" / "operator" / "scene_survey"

# Library modules (schema-only, no CLI gate) — exempt from the Acceptance rule.
LIBS = {"scene_survey_contracts.py", "scene_survey_spec.py", "scene_survey_runtime.py"}
# Match forbidden UE transients as PATH SEGMENTS / suffixes, not arbitrary
# substrings — a legitimately named report must not trip a bare "Build".
FORBIDDEN_DIRS = ("Saved", "Intermediate", "DerivedDataCache", "Build")
FORBIDDEN_SUFFIX = (".sav",)
# Deterministic authoring stamp: a fixed midnight-UTC ISO instant, never wall-clock.
_AUTHORING_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00:00\+00:00$")
_RT_NS_RE = re.compile(r"^wf\.scene_survey\.[a-z0-9_]+\.v1$")


def _is_transient(root, p):
    rel_parts = p.relative_to(root).parts
    if any(seg in FORBIDDEN_DIRS for seg in rel_parts):
        return True
    if p.suffix.lower() in FORBIDDEN_SUFFIX:
        return True
    return "crash" in p.name.lower()


def _gate_scripts():
    s = [p for p in PIPELINE.glob("*.py")
         if "scene_survey" in p.name and p.name not in LIBS]
    s += [p for p in OPERATOR.glob("*.py") if "scene_survey" in p.name]
    return sorted(set(s))


def _rt_namespaces():
    return {k: v for k, v in vars(SSC).items()
            if k.startswith("RT_") and isinstance(v, str)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.6 scene_survey hygiene gate.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()
    rep = ValidationReport("suite", "scene_survey_hygiene", strict=strict)

    # 1. Acceptance docstring on every gate script (libraries excluded).
    scripts = _gate_scripts()
    rep.check("hygiene::scripts_present", len(scripts) >= 2,
              "expected the scene_survey gate scripts (got {})".format(len(scripts)),
              code=F.SCENE_SURVEY_HYGIENE_FAILED)
    for p in scripts:
        rep.check("hygiene::{}::acceptance_doc".format(p.name),
                  "Acceptance:" in p.read_text(encoding="utf-8", errors="replace"),
                  "gate script must carry an 'Acceptance:' docstring line",
                  code=F.SCENE_SURVEY_HYGIENE_FAILED)

    # 2. No forbidden transient under the scene_survey generated + report roots.
    for root in (GEN, SREP, OP_REP):
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and _is_transient(root, p):
                rep.check("hygiene::no_transient::{}".format(p.name), False,
                          "forbidden transient under {}: {}".format(root.name, p.name),
                          code=F.SCENE_SURVEY_HYGIENE_FAILED)

    # 3. Contract-spine namespace / determinism hygiene (no silent drift).
    namespaces = _rt_namespaces()
    rep.check("hygiene::rt_namespaces_present", len(namespaces) >= 1,
              "scene_survey_contracts must expose RT_* report_type namespaces",
              code=F.SCENE_SURVEY_HYGIENE_FAILED)
    for name, val in sorted(namespaces.items()):
        rep.check("hygiene::namespace::{}".format(name),
                  bool(_RT_NS_RE.match(val)),
                  "{} must be a 'wf.scene_survey.<type>.v1' triple (got {!r})".format(name, val),
                  code=F.SCENE_SURVEY_HYGIENE_FAILED)
    rep.check("hygiene::authoring_ts_deterministic",
              isinstance(SSC.AUTHORING_TS, str) and bool(_AUTHORING_TS_RE.match(SSC.AUTHORING_TS)),
              "AUTHORING_TS must be a deterministic midnight-UTC stamp, not wall-clock "
              "(got {!r})".format(getattr(SSC, "AUTHORING_TS", None)),
              code=F.SCENE_SURVEY_HYGIENE_FAILED)
    rep.check("hygiene::report_root_declared",
              SSC.SURVEY_REPORTS_REL == "procedural/reports/scene_survey",
              "SURVEY_REPORTS_REL must name the scene_survey report tree (got {!r})".format(
                  getattr(SSC, "SURVEY_REPORTS_REL", None)),
              code=F.SCENE_SURVEY_HYGIENE_FAILED)
    rep.check("hygiene::profile_root_declared",
              isinstance(SSC.SURVEY_PROFILES_REL, str)
              and SSC.SURVEY_PROFILES_REL.startswith("procedural/generated/scene_survey"),
              "SURVEY_PROFILES_REL must live under the scene_survey generated tree "
              "(got {!r})".format(getattr(SSC, "SURVEY_PROFILES_REL", None)),
              code=F.SCENE_SURVEY_HYGIENE_FAILED)

    # 4. Core report artifacts exist, are non-empty, parse, and are scene_survey-namespaced.
    core_reports = (
        ("contract_spine", SREP / "validate_scene_survey_contracts_report.json"),
        ("fuzz_negatives", SREP / "negatives" / "scene_survey_fuzz_report.json"),
    )
    for label, path in core_reports:
        exists = path.is_file() and path.stat().st_size > 2
        rep.check("hygiene::core::{}".format(label), exists,
                  "core artifact missing/empty: {}".format(path.name),
                  code=F.SCENE_SURVEY_HYGIENE_FAILED)
        if not exists:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rep.check("hygiene::core::{}::parses".format(label), False,
                      "core artifact unparseable: {}".format(e),
                      code=F.SCENE_SURVEY_HYGIENE_FAILED)
            continue
        rt = (doc.get("meta") or {}).get("report_type")
        rep.check("hygiene::core::{}::namespaced".format(label),
                  isinstance(rt, str) and rt.startswith("wf.scene_survey."),
                  "core report_type must be scene_survey-namespaced (got {!r})".format(rt),
                  code=F.SCENE_SURVEY_HYGIENE_FAILED)

    rep.finalize()
    rep.set_meta(build_meta(
        command="scene-survey-hygiene", pack=None, strict=strict, status=rep.status,
        record_count=len(scripts), records_total=len(scripts),
        report_type="wf.scene_survey.hygiene.v1"))
    SREP.mkdir(parents=True, exist_ok=True)
    rep.write(SREP, "scene_survey_hygiene_report.json")
    rep.print_summary("scene-survey-hygiene")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
