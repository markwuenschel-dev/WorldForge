#!/usr/bin/env python3
r"""validate_execution_environment.py -- declare the plugin environment, then prove it.

    cd tools
    PYTHONUTF8=1 python pipeline/validate_execution_environment.py --probe   # live boot
    PYTHONUTF8=1 python pipeline/validate_execution_environment.py           # grade evidence

WHY THIS EXISTS
---------------
Two plugin descriptors in this project were renamed to ``.uplugin.disabled`` so
the UE 5.8 build could succeed. That is an explicit environment change, and an
environment change recorded only in prose is indistinguishable from one nobody
made: the next reader cannot tell whether a plugin is absent by decision, by
accident, or not absent at all.

So the environment is DECLARED here, per plugin, with a disposition and a reason,
and the declaration is graded against a LIVE OBSERVATION of what the engine
actually mounted. A disagreement in either direction is a failure:

  * a plugin declared REQUIRED that did not mount  -> the plan cannot run
  * a plugin declared DISABLED that mounted anyway -> the record is a fiction
  * a plugin observed mounted that nothing declares -> an undeclared dependency

THE DIRECTORY IS THE POINT, NOT THE NAME
-----------------------------------------
``NeoStackAI`` resolves to two copies on disk: a project-local v3.0.3 whose
``ThirdParty/Lua`` and ``sol2`` headers are absent, and a complete engine
marketplace v2.0.45. Reporting "NeoStackAI is enabled" would be true and useless --
it reads identically whichever copy answered. The declaration therefore pins the
expected base directory, and the gate fails if the mounted copy is not the one
declared. That is what makes "we disabled the project-local duplicate" a checkable
statement rather than a note.

WHAT "REQUIRED" MEANS HERE
--------------------------
Required BY THE SELECTED EXECUTION PLAN -- the set of operations WorldForge Core
actually performs -- not merely enabled in the .uproject. Those are different
questions and conflating them is how a project accumulates dependencies nobody can
remove: ``NeoStackAI`` is enabled in ``WorldForge.uproject`` yet no Core operation
calls it, and both facts are recorded rather than one being allowed to imply the
other.
"""

import argparse
import json
import os
import subprocess
import sys

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

_REPO = os.path.dirname(_TOOLS)

REPORT_TYPE = "wf.core.execution_environment_report.v1"

DEFAULT_EVIDENCE = os.path.join(
    _REPO, "procedural", "reports", "core", "environment",
    "execution_environment_observation.json")
DEFAULT_REPORT = os.path.join(
    _REPO, "procedural", "reports", "core", "environment",
    "validate_execution_environment_report.json")

# Forward slashes, deliberately. A Windows path handed to -ExecutePythonScript
# is escape-processed by the engine's command-line parser, so "\tools" arrives as
# a literal TAB and the file "cannot be loaded" for a reason the message does not
# reveal. Measured: the engine reported
#   Could not load Python file 'D:/Unreal Projects/WorldForge<TAB>ools/unreal/...'
FAR_SIDE = os.path.join(_TOOLS, "unreal",
                        "wfcore_environment_far_side.py").replace("\\", "/")

# --------------------------------------------------------------------------- #
# dispositions
# --------------------------------------------------------------------------- #
REQUIRED = "required_by_plan"
NOT_REQUIRED = "present_not_required_by_plan"
DISABLED = "deliberately_disabled"
DISPOSITIONS = (REQUIRED, NOT_REQUIRED, DISABLED)

# --------------------------------------------------------------------------- #
# THE DECLARATION. Every entry states a disposition, a reason, and -- where the
# name is ambiguous on disk -- which copy is expected to answer.
# --------------------------------------------------------------------------- #
DECLARED = {
    "WorldForge": {
        "disposition": REQUIRED,
        "expect_base_dir_contains": "WorldForge/Plugins/WorldForge",
        "reason": "WorldForgeCore supplies SceneSurveyStatics and the runtime "
                  "identity surface that every observation depends on.",
    },
    "PythonScriptPlugin": {
        "disposition": REQUIRED,
        "reason": "the entire near-side/far-side bridge is -ExecutePythonScript.",
    },
    "EditorScriptingUtilities": {
        "disposition": REQUIRED,
        "reason": "EditorAssetLibrary / actor subsystem calls the mutation sink "
                  "uses to author and to compensate.",
    },
    "PCG": {
        "disposition": NOT_REQUIRED,
        "reason": "enabled in WorldForge.uproject and mounted, but no provider "
                  "declaration currently offers a PCG capability, so the "
                  "selected plan never routes to it.",
    },
    "GeometryScripting": {
        "disposition": NOT_REQUIRED,
        "reason": "mounted; no Core operation calls it today.",
    },
    # ---- the two deliberately disabled descriptors -------------------------- #
    "NeoStackAI": {
        # Enabled in WorldForge.uproject, and it DOES mount -- but from the
        # ENGINE marketplace copy, because the project-local duplicate's
        # descriptor is renamed to .uplugin.disabled. Both halves are stated.
        "disposition": NOT_REQUIRED,
        # base_dir comes back ENGINE-RELATIVE ("../../../Engine/..."), never
        # absolute, so the discriminator is the Engine/Marketplace segment --
        # which is exactly what separates it from the project-local copy.
        "expect_base_dir_contains": "Engine/Plugins/Marketplace",
        "must_not_load_from": "WorldForge/Plugins/NeoStackAI",
        "reason": "ENVIRONMENT CHANGE. Two plugins on disk share this name: a "
                  "project-local v3.0.3 missing its ThirdParty/Lua and sol2 "
                  "headers, and a complete engine marketplace v2.0.45. UBT "
                  "selected the engine descriptor together with the project's "
                  "module rules, which cannot build. The project-local "
                  "descriptor is renamed to .uplugin.disabled so exactly one "
                  "copy resolves. NeoStackAI is enabled in WorldForge.uproject "
                  "and mounts from the engine copy; no WorldForge Core "
                  "operation calls it, so the selected execution plan does not "
                  "require it. REVERSE WITH: mv "
                  "Plugins/NeoStackAI/NeoStackAI.uplugin.disabled "
                  "Plugins/NeoStackAI/NeoStackAI.uplugin -- note the build then "
                  "fails again until the missing ThirdParty headers are supplied.",
    },
    "UELLMToolkit": {
        "disposition": DISABLED,
        "reason": "ENVIRONMENT CHANGE. EngineVersion 5.6.0; uses APIs changed in "
                  "5.8 (IKRetargetBatchOperation::DuplicateAndRetarget signature, "
                  "moved RigVMModel/RigVMVariableDescription.h). It is untracked "
                  "in git and NOT referenced by WorldForge.uproject -- it built "
                  "only via EnabledByDefault. No WorldForge Core operation calls "
                  "it, so the selected execution plan does not require it. "
                  "REVERSE WITH: mv "
                  "Plugins/UELLMToolkit/UELLMToolkit.uplugin.disabled "
                  "Plugins/UELLMToolkit/UELLMToolkit.uplugin -- the 5.8 build "
                  "then fails again.",
    },
    # ---- Houdini: mounted, but NOT a production provider -------------------- #
    "HoudiniEngine": {
        "disposition": NOT_REQUIRED,
        "reason": "the module builds and mounts, which proves ONLY that. No "
                  "Houdini provider is registered in the capability registry, "
                  "no plan step has ever selected one, and no cook has been "
                  "executed. A mounted plugin is not a production provider; see "
                  "docs/contracts/wfcore_houdini_provider_status.md.",
    },
    "HoudiniNiagara": {
        "disposition": NOT_REQUIRED,
        "reason": "enabled in WorldForge.uproject; mounted; unused by Core.",
    },
    "HoudiniLiveLink": {
        "disposition": NOT_REQUIRED,
        "reason": "ships in Plugins/ alongside HoudiniEngine and mounts; no Core "
                  "operation calls it and no provider offers a live-link "
                  "capability.",
    },
    "CoreTerrainMaterials": {
        "disposition": NOT_REQUIRED,
        "reason": "content-only plugin shipped in Plugins/; supplies terrain "
                  "material assets. No Core operation references it, and no "
                  "consumer catalog approves an asset from it.",
    },
}

Check = tuple


def _repo_rel(path):
    if not path:
        return None
    p = path.replace("\\", "/")
    root = _REPO.replace("\\", "/")
    return p[len(root):].lstrip("/") if p.startswith(root) else p


# --------------------------------------------------------------------------- #
# probing
# --------------------------------------------------------------------------- #
def descriptor_fingerprint():
    """Hash the project's plugin-descriptor SET: which exist, and their contents.

    This is the staleness rail. Without it the gate grades whatever observation
    happens to be committed, so someone could disable a plugin, re-run the shield,
    and read green off evidence taken before the change -- which is exactly the
    "graded an eight-day-old artifact" failure this repository has already paid
    for once.

    Content-hashed, not mtime-based: an mtime is not a freshness signal (an
    artifact in this repo was observed moving between dates with identical bytes).
    Enabling a descriptor, disabling one, or editing one all move this hash, and
    any of the three means the committed observation no longer describes the tree.
    """
    import hashlib
    entries = []
    root = os.path.join(_REPO, "Plugins")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("Binaries", "Intermediate", "Content")]
        for fn in sorted(filenames):
            if fn.endswith((".uplugin", ".uplugin.disabled")):
                full = os.path.join(dirpath, fn)
                try:
                    with open(full, "rb") as fh:
                        body = hashlib.sha256(fh.read()).hexdigest()
                except OSError:
                    body = "unreadable"
                entries.append((_repo_rel(full), body))
    h = hashlib.sha256()
    for (rel, body) in sorted(entries):
        h.update(rel.encode("utf-8")); h.update(b"\0")
        h.update(body.encode("utf-8")); h.update(b"\n")
    return {"descriptor_count": len(entries),
            "fingerprint": "sha256:" + h.hexdigest(),
            "descriptors": [r for (r, _b) in sorted(entries)]}


def probe(uproject=None, ue_cmd=None, evidence_path=DEFAULT_EVIDENCE, timeout=900):
    """Boot the editor and write a live observation document."""
    uproject = uproject or os.path.join(_REPO, "WorldForge.uproject")
    ue_cmd = ue_cmd or os.environ.get("WF_UE_CMD") or \
        "D:/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe"

    if os.path.isfile(evidence_path):
        # Never grade a stale document by accident.
        os.remove(evidence_path)

    env = dict(os.environ)
    env["WF_ENV_OUT"] = evidence_path
    env["PYTHONUTF8"] = "1"
    argv = [ue_cmd, os.path.abspath(uproject),
            "-ExecutePythonScript=" + FAR_SIDE,
            "-unattended", "-nopause", "-nosplash", "-nullrhi", "-stdout"]
    proc = subprocess.run(argv, env=env, capture_output=True, text=True,
                          timeout=timeout)

    # Stamp the observation with the descriptor set it was taken against, so a
    # later grade can tell whether the tree has moved underneath it. Written by
    # the NEAR side because the far side cannot see the repository layout.
    if os.path.isfile(evidence_path):
        try:
            with open(evidence_path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
            doc["descriptor_fingerprint_at_probe"] = descriptor_fingerprint()
            with open(evidence_path, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2, sort_keys=True)
        except Exception as exc:  # noqa: BLE001
            print("WARNING: could not stamp the descriptor fingerprint: "
                  "{}".format(exc))
    return proc.returncode, evidence_path


# --------------------------------------------------------------------------- #
# grading
# --------------------------------------------------------------------------- #
def grade(observation):
    """Compare DECLARED against a live observation. Returns check tuples."""
    checks = []

    def add(name, ok, detail):
        checks.append((name, bool(ok), detail))

    if not isinstance(observation, dict):
        add("observation_is_a_document", False,
            "no observation document was supplied; nothing was measured, and "
            "an unmeasured environment must never grade as declared")
        return checks

    errors = observation.get("errors") or []
    add("observation_has_no_fatal_errors", not errors,
        "far-side errors: {}".format(errors[:3]) if errors
        else "far side reported no errors")

    # STALENESS. The committed observation only speaks for the descriptor set it
    # was taken against. If that set has moved, the observation describes a tree
    # that no longer exists and must not be graded as though it does.
    now = descriptor_fingerprint()
    stamped = observation.get("descriptor_fingerprint_at_probe") or {}
    stamped_fp = stamped.get("fingerprint")
    if not stamped_fp:
        add("observation_is_fingerprinted", False,
            "this observation carries no descriptor fingerprint, so whether it "
            "still describes the current plugin tree is UNKNOWN. Re-take it with "
            "--probe rather than grading evidence of unknown currency.")
    else:
        fresh = stamped_fp == now["fingerprint"]
        add("observation_is_current", fresh,
            "descriptor fingerprint at probe {} vs now {} ({} descriptors); a "
            "plugin descriptor was added, removed or edited since this "
            "observation was taken, so re-run with --probe".format(
                stamped_fp[:23], now["fingerprint"][:23], now["descriptor_count"])
            if not fresh else
            "descriptor set unchanged since the observation was taken "
            "({} descriptors, {})".format(now["descriptor_count"],
                                          now["fingerprint"][:23]))

    plugins = observation.get("plugins")
    enabled = observation.get("enabled_plugin_names")
    if not isinstance(plugins, dict) or enabled is None:
        add("observation_enumerated_plugins", False,
            "the observation carries no plugin enumeration, so nothing about "
            "the environment was actually observed")
        return checks
    add("observation_enumerated_plugins", True,
        "{} plugin(s) enumerated".format(len(enabled)))

    for name, decl in sorted(DECLARED.items()):
        disp = decl["disposition"]
        rec = plugins.get(name)
        # ACTIVE means the engine ENABLED it. Deliberately not is_plugin_mounted:
        # that reports whether the plugin's CONTENT is mounted into the asset
        # path, so a code-only plugin like EditorScriptingUtilities is fully
        # active while reporting mounted=False. Grading on the wrong signal
        # produced a confident false failure the first time this ran.
        active = rec is not None
        mounted = bool(rec and rec.get("mounted"))
        base = (rec or {}).get("base_dir")
        ver = (rec or {}).get("version_name")

        if disp == REQUIRED:
            add("required.{}.enabled".format(name), active,
                "declared REQUIRED by the plan; enabled={} version={} "
                "content_mounted={} base_dir={}".format(active, ver, mounted, base))
        elif disp == DISABLED:
            add("disabled.{}.not_enabled".format(name), not active,
                "declared DELIBERATELY DISABLED; enabled={}. A plugin the engine "
                "enables while the record says it is disabled makes the record a "
                "fiction".format(active))
        else:  # NOT_REQUIRED -- active or not is fine, but it must be RECORDED
            add("not_required.{}.recorded".format(name), True,
                "declared PRESENT-BUT-NOT-REQUIRED; enabled={} version={} "
                "base_dir={}".format(active, ver, base))

        # Where the declaration pins a copy, the mounted copy must be that one.
        want = decl.get("expect_base_dir_contains")
        if want and active:
            ok = bool(base) and want.replace("\\", "/").lower() in base.lower()
            add("copy.{}.loaded_from_declared_location".format(name), ok,
                "expected base_dir to contain {!r}, observed {!r}".format(want, base))

        forbid = decl.get("must_not_load_from")
        if forbid and active:
            ok = not (base and forbid.replace("\\", "/").lower() in base.lower())
            add("copy.{}.did_not_load_from_disabled_copy".format(name), ok,
                "must NOT load from {!r}; observed base_dir {!r}".format(forbid, base))

    # An undeclared plugin that WorldForge ships is an undeclared dependency.
    project_shipped = [n for n in enabled
                       if isinstance(plugins.get(n), dict)
                       and (plugins[n].get("base_dir") or "").replace("\\", "/")
                       .lower().find("/worldforge/plugins/") >= 0]
    undeclared = sorted(n for n in project_shipped if n not in DECLARED)
    add("no_undeclared_project_plugins", not undeclared,
        "project-shipped plugin(s) with no declaration: {}".format(undeclared)
        if undeclared else
        "every project-shipped mounted plugin is declared")

    return checks


def _disabled_descriptors_on_disk():
    out = []
    root = os.path.join(_REPO, "Plugins")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("Binaries", "Intermediate")]
        for fn in filenames:
            if fn.endswith(".uplugin.disabled"):
                out.append(_repo_rel(os.path.join(dirpath, fn)))
    return sorted(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--probe", action="store_true",
                   help="boot the editor and take a fresh observation first")
    p.add_argument("--evidence", default=DEFAULT_EVIDENCE)
    p.add_argument("--report", default=DEFAULT_REPORT)
    p.add_argument("--ue-cmd", default=None)
    args = p.parse_args(argv)

    if args.probe:
        rc, path = probe(ue_cmd=args.ue_cmd, evidence_path=args.evidence)
        print("probe: editor exited {} -> {}".format(rc, _repo_rel(path)))

    observation = None
    if os.path.isfile(args.evidence):
        try:
            with open(args.evidence, "r", encoding="utf-8") as fh:
                observation = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            print("evidence at {} is unreadable: {}".format(args.evidence, exc))

    checks = grade(observation)
    failed = [c for c in checks if not c[1]]

    disabled_files = _disabled_descriptors_on_disk()

    print("WorldForge execution environment")
    print("  evidence : {}".format(_repo_rel(args.evidence)))
    print("  disabled descriptors on disk:")
    for f in disabled_files or ["(none)"]:
        print("    - {}".format(f))
    print("")
    for (name, ok, detail) in checks:
        print("  [{}] {:52} {}".format("PASS" if ok else "FAIL", name, detail[:88]))
    print("")
    print("  GATE {}".format("GREEN" if not failed else "RED"))

    report = {
        "report_type": REPORT_TYPE,
        "declared": DECLARED,
        "disabled_descriptors_on_disk": disabled_files,
        "observation_present": observation is not None,
        "checks": [{"check": n, "ok": ok, "detail": d} for (n, ok, d) in checks],
        "failed": len(failed),
        "green": not failed,
    }
    d = os.path.dirname(os.path.abspath(args.report))
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    print("  report -> {}".format(_repo_rel(args.report)))

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
