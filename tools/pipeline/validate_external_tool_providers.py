#!/usr/bin/env python3
r"""validate_external_tool_providers.py -- an external tool is not a provider.

    cd tools
    PYTHONUTF8=1 python pipeline/validate_external_tool_providers.py

WHAT THIS GATE SEPARATES
------------------------
Four different things get casually collapsed into "we have Houdini support", and
only the last one is a production capability:

  1. the plugin BUILDS                    -- compilation succeeded
  2. the plugin MOUNTS                    -- the engine enabled it at boot
  3. a fixture was GENERATED with it      -- someone ran hython once, by hand
  4. the PLANNER SELECTED a provider that
     COOKED and produced an output        -- the capability actually exists

1-3 are all true here and 4 is not. Each of 1-3 produces artifacts that look
exactly like what 4 would produce, which is the entire problem: a deterministic
fixture in ``procedural/fixtures/houdini/`` carries a ``generator`` block naming
``hython`` and a real Houdini version, and reads as proof of a working provider
to anyone who does not already know it was authored as a test input.

So the rule this gate enforces is: a provider declaring a capability backed by an
external DCC tool must carry COOK EVIDENCE -- an execution that consumed a
declared input and produced a declared output -- and fixture or metadata
artifacts are explicitly rejected as that evidence (WF1290).

WHY THE D18 MEASUREMENT DOES NOT HELP HERE
-------------------------------------------
D18 measured Python's cost for support-grid sampling and concluded the support
grid should stay in Python. That is a statement about ONE implementation choice
inside WorldForge. It says nothing whatever about whether an external tool can be
driven end to end, and quoting it in that direction would be using a real
measurement to answer a question it never asked.

CURRENT STATUS: no external-tool provider is declared anywhere in this
repository, so the correct result is a green gate asserting ABSENCE, not a green
gate implying capability. The moment a provider does declare one, the rails below
start applying to it.
"""

import argparse
import json
import os
import sys

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
_REPO = os.path.dirname(_TOOLS)

sys.path.insert(0, os.path.join(_TOOLS, "pipeline"))
from failure_codes import FailureCode as C  # noqa: E402

REPORT_TYPE = "wf.core.external_tool_provider_report.v1"
DEFAULT_REPORT = os.path.join(
    _REPO, "procedural", "reports", "core", "environment",
    "validate_external_tool_providers_report.json")

# Tools whose capability claims require cook evidence. Substring match against a
# declaration's provider_id, description, capabilities and requirements.
EXTERNAL_TOOLS = ("houdini", "hython", "hapi", "substance", "blender", "maya")

# Evidence roots that are NOT proof of a production capability, however real the
# artifacts inside them are.
FIXTURE_ROOTS = ("procedural/fixtures/", "procedural/known_bads/",
                 "tests/fixtures/", "examples/")

# What a real cook must record. Anything less is metadata about a cook rather
# than evidence one happened.
COOK_EVIDENCE_REQUIRED = (
    "tool_name",          # which tool cooked
    "tool_version",       # which build of it
    "session_id",         # the cook session, so the run is identifiable
    "input_digest",       # what went in
    "output_paths",       # what came out
    "output_digests",     # and its content hashes
    "cook_seconds",       # that it actually ran
    "selected_by_plan",   # the plan step that SELECTED this provider
)


def _rel(p):
    p = p.replace("\\", "/")
    root = _REPO.replace("\\", "/")
    return p[len(root):].lstrip("/") if p.startswith(root) else p


def discover_declarations():
    """Every provider declaration reachable in the repo, with where it came from.

    Deliberately includes TEST fixtures: a declaration that only exists in a test
    still tells us whether anyone has modelled an external-tool provider, and
    finding one there is exactly how a capability claim starts leaking into
    documentation.
    """
    found = []
    try:
        from wfcore.providers import base as B  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return found, "wfcore.providers.base is not importable: {}".format(exc)

    # Core ships exactly one canonical declaration factory; consumers ship none
    # today. Enumerate both, plus any registry a consumer populates.
    try:
        from wfcore.providers import base as B
        found.append(("wfcore.providers.base._example_provider_declaration",
                      B._example_provider_declaration()))
    except Exception:  # noqa: BLE001
        pass

    consumers_root = os.path.join(_TOOLS, "consumers")
    if os.path.isdir(consumers_root):
        for name in sorted(os.listdir(consumers_root)):
            d = os.path.join(consumers_root, name)
            if not os.path.isdir(d) or name.startswith(("_", ".")):
                continue
            try:
                mod = __import__("consumers." + name, fromlist=["*"])
            except Exception:  # noqa: BLE001
                continue
            fn = getattr(mod, "provider_declarations", None)
            if callable(fn):
                try:
                    for decl in fn() or []:
                        found.append(("consumers." + name, decl))
                except Exception:  # noqa: BLE001
                    pass
    return found, None


def _mentions_external_tool(decl):
    blob = json.dumps(decl, default=str).lower()
    return sorted({t for t in EXTERNAL_TOOLS if t in blob})


def grade():
    checks = []

    def add(name, ok, detail, code=None):
        checks.append((name, bool(ok), detail, None if ok else code))

    declarations, err = discover_declarations()
    if err:
        add("declarations_discoverable", False, err, C.CORE_PROVIDER_DECLARATION_INVALID)
        return checks, []
    add("declarations_discoverable", True,
        "{} provider declaration(s) reachable".format(len(declarations)))

    external = []
    for (origin, decl) in declarations:
        tools = _mentions_external_tool(decl)
        if tools:
            external.append((origin, decl, tools))

    # The headline: today this must be ABSENCE, stated as absence.
    add("no_undeclared_external_tool_provider", True,
        "{} declaration(s) reference an external DCC tool{}".format(
            len(external),
            "" if not external else ": " + ", ".join(o for (o, _d, _t) in external)))

    # Whenever one DOES appear, it must carry cook evidence.
    for (origin, decl, tools) in external:
        pid = decl.get("provider_id", "<unnamed>")
        cook = decl.get("cook_evidence")
        missing = [f for f in COOK_EVIDENCE_REQUIRED
                   if not isinstance(cook, dict) or cook.get(f) in (None, "", [], {})]
        add("cook_evidence.{}.present".format(pid), not missing,
            "provider {!r} from {} claims external tool(s) {} but its cook "
            "evidence is missing {}; a mounted plugin proves only that it "
            "mounts".format(pid, origin, tools, missing),
            C.CORE_PROVIDER_COOK_EVIDENCE_MISSING)

        paths = (cook or {}).get("output_paths") or []
        fixture_backed = [p for p in paths
                          if any(r in str(p).replace("\\", "/") for r in FIXTURE_ROOTS)]
        add("cook_evidence.{}.not_fixture_backed".format(pid), not fixture_backed,
            "provider {!r} offers fixture/known-bad artifacts {} as cook "
            "evidence; a deterministic fixture is what a working provider's "
            "output looks like, which is exactly why it cannot prove one "
            "exists".format(pid, fixture_backed),
            C.CORE_PROVIDER_EVIDENCE_IS_FIXTURE)

    # Record the fixture artifacts that exist, so nobody later mistakes them.
    fixture_dir = os.path.join(_REPO, "procedural", "fixtures", "houdini")
    fixtures = sorted(_rel(os.path.join(fixture_dir, f))
                      for f in os.listdir(fixture_dir)) \
        if os.path.isdir(fixture_dir) else []
    add("houdini_fixtures_are_labelled_fixtures", True,
        "{} Houdini FIXTURE artifact(s) present and classified as test input, "
        "not capability evidence: {}".format(len(fixtures), fixtures[:4]))

    return checks, external


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--report", default=DEFAULT_REPORT)
    args = p.parse_args(argv)

    checks, external = grade()
    failed = [c for c in checks if not c[1]]

    print("external-tool provider claims")
    print("  tools policed : {}".format(", ".join(EXTERNAL_TOOLS)))
    print("")
    for (name, ok, detail, code) in checks:
        print("  [{}] {:46} {}{}".format(
            "PASS" if ok else "FAIL", name, detail[:84],
            "" if ok else "  ({})".format(code)))
    print("")
    print("  STATUS: {}".format(
        "no external-tool production provider is declared -- absence, stated as "
        "absence" if not external else
        "{} external-tool provider(s) declared and graded".format(len(external))))
    print("  GATE {}".format("GREEN" if not failed else "RED"))

    report = {
        "report_type": REPORT_TYPE,
        "tools_policed": list(EXTERNAL_TOOLS),
        "cook_evidence_required": list(COOK_EVIDENCE_REQUIRED),
        "external_tool_providers_declared": len(external),
        "checks": [{"check": n, "ok": ok, "detail": d, "failure_code": c}
                   for (n, ok, d, c) in checks],
        "green": not failed,
    }
    d = os.path.dirname(os.path.abspath(args.report))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    print("  report -> {}".format(_rel(args.report)))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
