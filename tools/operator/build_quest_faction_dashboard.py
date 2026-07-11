#!/usr/bin/env python3
"""build_quest_faction_dashboard.py — v2.2 Wave 4 operator quest/faction dashboard.

Renders the Wave-4 quest/faction index into an inspectable static site under
procedural/reports/operator/quests|factions:

  quests/index.html            quest matrix (archetype / requesting faction / outcome)
  quests/<quest_id>.html       one quest: step statuses, deltas, ledger viewer, links
  factions/index.html          faction roster (class / standing trend)
  factions/<faction_id>.html   one faction: standing/influence/trust/alarm history,
                               quest history, state paths

Every quest page embeds its ConsequenceLedger (the ledger viewer) and links the
runtime report + save/load proof so an operator can trace the whole chain. Pages are
DERIVED from the contract-validated views — this builder does not re-assert outcomes.

FAIL-CLOSED: absent quest_views.json / faction_views.json -> RED
(run operator-quest-faction-index first).

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/build_quest_faction_dashboard.py --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_view as V
from failure_codes import FailureCode as F
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport

INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
QUESTS_OUT = REPO_ROOT / "procedural" / "reports" / "operator" / "quests"
FACTIONS_OUT = REPO_ROOT / "procedural" / "reports" / "operator" / "factions"
CONSEQ_DIR = REPO_ROOT / "procedural" / "generated" / "consequences"
REPORT_DIR = REPO_ROOT / "procedural" / "reports" / "operator"


def _page(title, body, sha, back=None):
    """v2.2 operator page shell reusing the operator_view CSS/helpers."""
    html = V.page(title, body, subtitle="v2.2 QuestForge + FactionStateForge",
                  git_sha=sha, back=back)
    return html.replace("WorldForge v2.1 OperatorForge", "WorldForge v2.2 OperatorForge")


def _write(path, html):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def _rel_to_repo(from_page, repo_rel):
    """Relative href from an operator page back to a repo-relative artifact path."""
    up = "../" * (len(from_page.relative_to(REPORT_DIR).parts) - 1 + 1)
    return up + "../../" + repo_rel


def _quest_page(qv, sha):
    body = V.kv("archetype", V.badge(qv["quest_archetype"]))
    body += V.kv("requesting faction",
                 V.link("../factions/{}.html".format(qv["requesting_faction_id"]),
                        qv["requesting_faction_id"]))
    body += V.kv("affected factions", ", ".join(qv["affected_faction_ids"]))
    body += V.kv("scenario", ", ".join(qv["scenario_ids"]))
    body += V.kv("outcome", V.badge(qv["runtime_outcomes"][0] if qv["runtime_outcomes"] else "?"))
    body += V.kv("save/load", V.badge(qv["save_load_status"]))
    body += V.kv("next-mission hooks", ", ".join(qv["next_mission_hooks"]) or "(none)")
    # step statuses
    rows = "".join("<tr><td>{}</td><td>{}</td></tr>".format(
        V.esc(s["step_id"]), V.badge(s["status"])) for s in qv["step_statuses"])
    body += "<h2>steps</h2><table><tr><th>step</th><th>status</th></tr>{}</table>".format(rows)
    # faction deltas
    body += "<h2>faction deltas</h2><p>{}</p>".format(
        ", ".join(V.esc(d) for d in qv["faction_deltas"]) or "(none)")
    # consequence ledger viewer (embed the ledger)
    for lp in qv["consequence_ledger_paths"]:
        lpath = REPO_ROOT / lp
        if lpath.is_file():
            led = json.loads(lpath.read_text(encoding="utf-8"))
            body += "<h2>consequence ledger</h2>"
            body += V.kv("ledger id", led["ledger_id"])
            body += V.kv("pre faction hash", "<code>{}</code>".format(V.esc(led["pre_faction_state_hash"])))
            body += V.kv("post faction hash", "<code>{}</code>".format(V.esc(led["post_faction_state_hash"])))
            body += V.kv("hash changed",
                         V.badge("yes" if led["pre_faction_state_hash"] != led["post_faction_state_hash"] else "no"))
            body += V.kv("applied deltas", str(len(led["applied_deltas"])))
            body += V.kv("reward events", ", ".join(led["reward_events"]) or "(none)")
            body += V.kv("save/load", V.badge(led["save_load_result"]))
    return _page("quest {}".format(qv["quest_id"]), body, sha,
                 back=("index.html", "quests"))


def _faction_page(fv, sha):
    body = V.kv("faction id", fv["faction_id"])
    body += V.kv("definition", V.esc(fv["definition_path"]))
    body += V.kv("quests touched", str(len(fv["quest_history"])))
    body += V.kv("state snapshots", str(len(fv["state_paths"])))

    def trend(name, series):
        if not series:
            return ""
        arrow = "→"
        if series[-1] > series[0]:
            arrow = "↑"
        elif series[-1] < series[0]:
            arrow = "↓"
        return V.kv(name, "{} {} {} (n={})".format(series[0], arrow, series[-1], len(series)))

    body += "<h2>state history</h2>"
    body += trend("standing", fv["standing_history"])
    body += trend("influence", fv["influence_history"])
    body += trend("trust", fv["trust_history"])
    body += trend("alarm", fv["alarm_history"])
    body += "<h2>quest history</h2><p>{}</p>".format(
        ", ".join(V.esc(q) for q in fv["quest_history"]) or "(none)")
    return _page("faction {}".format(fv["faction_id"]), body, sha,
                 back=("index.html", "factions"))


def build(rep, sha):
    qv_path = INDEX_DIR / "quest_views.json"
    fv_path = INDEX_DIR / "faction_views.json"
    rep.check("dash::quest_views_present", qv_path.is_file(),
              "quest_views.json missing (run operator-quest-faction-index)",
              code=F.QUEST_FACTION_OPERATOR_VIEW_INVALID)
    rep.check("dash::faction_views_present", fv_path.is_file(),
              "faction_views.json missing", code=F.QUEST_FACTION_OPERATOR_VIEW_INVALID)
    if not (qv_path.is_file() and fv_path.is_file()):
        return 0
    quest_views = json.loads(qv_path.read_text(encoding="utf-8"))
    faction_views = json.loads(fv_path.read_text(encoding="utf-8"))

    # quest matrix index
    rows = ""
    for qv in sorted(quest_views, key=lambda v: v["quest_id"]):
        rows += "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            V.link("{}.html".format(qv["quest_id"]), qv["quest_id"]),
            V.badge(qv["quest_archetype"]), V.esc(qv["requesting_faction_id"]),
            V.badge(qv["runtime_outcomes"][0] if qv["runtime_outcomes"] else "?"),
            V.badge(qv["save_load_status"]))
    qindex = "<table><tr><th>quest</th><th>archetype</th><th>requester</th>" \
             "<th>outcome</th><th>save/load</th></tr>{}</table>".format(rows)
    _write(QUESTS_OUT / "index.html",
           _page("quests ({})".format(len(quest_views)), qindex, sha,
                 back=("../dashboard/index.html", "dashboard")))
    for qv in quest_views:
        _write(QUESTS_OUT / "{}.html".format(qv["quest_id"]), _quest_page(qv, sha))

    # faction roster index
    frows = ""
    for fv in sorted(faction_views, key=lambda v: v["faction_id"]):
        sh = fv["standing_history"]
        frows += "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            V.link("{}.html".format(fv["faction_id"]), fv["faction_id"]),
            str(len(fv["quest_history"])),
            "{} → {}".format(sh[0], sh[-1]) if sh else "-")
    findex = "<table><tr><th>faction</th><th>quests</th><th>standing</th></tr>{}</table>".format(frows)
    _write(FACTIONS_OUT / "index.html",
           _page("factions ({})".format(len(faction_views)), findex, sha,
                 back=("../dashboard/index.html", "dashboard")))
    for fv in faction_views:
        _write(FACTIONS_OUT / "{}.html".format(fv["faction_id"]), _faction_page(fv, sha))

    rep.check("dash::quest_pages_written",
              (QUESTS_OUT / "index.html").is_file()
              and all((QUESTS_OUT / "{}.html".format(v["quest_id"])).is_file() for v in quest_views),
              "all quest pages must be written", code=F.QUEST_FACTION_OPERATOR_VIEW_INVALID)
    rep.check("dash::faction_pages_written",
              (FACTIONS_OUT / "index.html").is_file()
              and all((FACTIONS_OUT / "{}.html".format(v["faction_id"])).is_file() for v in faction_views),
              "all faction pages must be written", code=F.QUEST_FACTION_OPERATOR_VIEW_INVALID)
    return len(quest_views) + len(faction_views)


def _git_sha():
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO_ROOT),
                              capture_output=True, text=True).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.2 operator quest/faction dashboard.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("suite", "quest_faction_operator_dashboard", strict=strict)
    n = build(rep, _git_sha())

    rep.finalize()
    rep.set_meta(build_meta(
        command="operator-quest-faction-dashboard", pack=None, strict=strict,
        status=rep.status, record_count=n, records_total=n,
        report_type="wf.quest_faction.operator_dashboard.v1"))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rep.write(REPORT_DIR, "build_quest_faction_dashboard_report.json")
    rep.print_summary("operator-quest-faction-dashboard")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
