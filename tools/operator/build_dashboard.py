#!/usr/bin/env python3
"""build_dashboard.py — v2.1 OperatorForge static dashboard builder (Wave 3).

Turns the Wave-2 operator index + evidence graph into an inspectable static site:

  index/pack_cards.json            (list[OperatorPackCard], contract-validated)
  index/scenario_cards.json        (list[OperatorScenarioCard], contract-validated)
  dashboard/index.html             (pack overview + scenario matrix)
  dashboard/packs/<pack>.html      (one pack page)
  dashboard/scenarios/<ssid>.html  (one scenario detail page per v2.0 scenario)

Every scenario card's per-facet status is DERIVED from the evidence graph (not
re-asserted): a card can only say a facet 'pass' when the corresponding
EvidenceTrace verdict is pass. Cards are validated against their contracts before
render — a card that fails its schema turns this builder RED (fail-closed).

FAIL-CLOSED: absent index/graph -> RED (run operator-index-reports first).

Acceptance:
    PYTHONUTF8=1 STRICT=1 python tools/operator/build_dashboard.py --strict
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "operator"))

import operator_contracts as OX
import operator_view as V

INDEX_DIR = REPO_ROOT / "procedural" / "reports" / "operator" / "index"
MANIFEST = REPO_ROOT / "procedural/generated/slice/manifest.json"
PACKAGE_REPORT = REPO_ROOT / "procedural/reports/slice/package/slice_package_worldforge_vertical_slice.json"
PACKAGE_REPORT_REL = "procedural/reports/slice/package/slice_package_worldforge_vertical_slice.json"
EVIDENCE_INDEX_REL = "procedural/reports/slice/integrity/slice_evidence_index_worldforge_vertical_slice.json"

# claim -> the scenario-card facet it certifies.
CLAIM_FACET = {
    "scenario completed": "runtime_status",
    "grounded traversal succeeded": "traversal_status",
    "npc pressure occurred": "npc_status",
    "combat damage occurred": "combat_status",
    "reward granted": "reward_status",
    "save/load roundtrip passed": "save_load_status",
    "package includes map": "package_status",
}


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def build_scenario_cards(manifest, graph, package):
    """Derive one contract-valid OperatorScenarioCard per scenario from the graph."""
    by_scn = {}
    for t in graph.get("traces", []):
        by_scn.setdefault(t["scenario_id"], []).append(t)

    cards, failures = [], []
    for ssid in sorted(manifest.get("scenarios", [])):
        traces = by_scn.get(ssid, [])
        facets = {f: "absent" for f in CLAIM_FACET.values()}
        report_paths, telemetry = set(), set()
        codes = []
        for t in traces:
            facet = CLAIM_FACET.get(t.get("claim"))
            if facet:
                facets[facet] = t.get("verdict", "absent")
            for p in t.get("supporting_reports", []):
                report_paths.add(p)
            for p in t.get("supporting_telemetry", []):
                telemetry.add(p)
            codes.extend(t.get("failure_codes", []))

        rrel = "procedural/reports/slice/runtime/slice_runtime_{}.json".format(ssid)
        runtime = _load(REPO_ROOT / rrel) if (REPO_ROOT / rrel).is_file() else {}
        card = OX._example_scenario_card(
            scenario_id=ssid,
            pack_id=manifest.get("pack_id", "encounter_loop_world"),
            map_id=runtime.get("map_id", ssid),
            biome=runtime.get("biome", "unknown"),
            mission_archetype=runtime.get("mission_archetype", "unknown"),
            pressure_profile=runtime.get("encounter_profile", "unknown"),
            seed=int(runtime.get("seed", 0)),
            runtime_status=facets["runtime_status"],
            traversal_status=facets["traversal_status"],
            npc_status=facets["npc_status"],
            combat_status=facets["combat_status"],
            reward_status=facets["reward_status"],
            save_load_status=facets["save_load_status"],
            package_status=facets["package_status"],
            telemetry_paths=sorted(telemetry),
            report_paths=sorted(report_paths),
            failure_codes=sorted(set(codes)),
        )
        fails = [c for c in OX.validate_scenario_card(card, strict=True) if not c[1]]
        if fails:
            failures.append((ssid, [c[0] for c in fails][:3]))
        cards.append(card)
    return cards, failures


def build_pack_card(manifest, package, index):
    integrity = index.get("integrity_result", "blocked")
    scn = manifest.get("scenarios", [])
    card = OX._example_pack_card(
        pack_id=manifest.get("slice_id", "worldforge_vertical_slice"),
        pack_name="WorldForge Vertical Slice",
        version="2.0",
        source_milestone="v2.0",
        scenario_count=len(scn),
        map_count=len(manifest.get("maps", [])),
        biomes=list(manifest.get("biomes", [])),
        mission_archetypes=list(manifest.get("mission_archetypes", [])),
        pressure_profiles=list(manifest.get("encounter_profiles", [])),
        package_report_path=PACKAGE_REPORT_REL,
        package_exists=package.get("package_exists") is True,
        package_size_bytes=int(package.get("package_size_bytes", 0)),
        runtime_result_summary="{}/{} slice_completed_runtime".format(
            len(scn) - len(index.get("missing_evidence", [])), len(scn)),
        shield_result_summary="evidence integrity_result={}".format(integrity),
        evidence_index_path=EVIDENCE_INDEX_REL,
        failure_codes=[] if integrity == "pass" else ["WF686_SLICE_PARTIAL_MATRIX"],
    )
    fails = [c for c in OX.validate_pack_card(card, strict=True) if not c[1]]
    return card, [c[0] for c in fails][:4]


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #
def render_scenario_page(card, traces, sha):
    rows = ""
    facet_labels = [("runtime_status", "runtime"), ("traversal_status", "traversal"),
                    ("npc_status", "npc"), ("combat_status", "combat"),
                    ("reward_status", "reward"), ("save_load_status", "save/load"),
                    ("package_status", "package")]
    body = '<h2>Facet status</h2><div class="card">'
    for f, lbl in facet_labels:
        body += V.kv(lbl, V.badge(card[f]))
    body += "</div>"

    body += '<h2>Evidence traces</h2><div class="scroll"><table><tr><th>claim</th>'\
            '<th>verdict</th><th>supporting</th><th>milestone</th></tr>'
    for t in sorted(traces, key=lambda x: x.get("claim", "")):
        sup = t.get("supporting_reports", []) + t.get("supporting_package_proofs", [])
        links = " ".join(V.link("../../../../../" + p, Path(p).name) for p in sup[:2])
        body += "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            V.esc(t.get("claim")), V.badge(t.get("verdict")), links or "<span class='muted'>—</span>",
            V.esc(", ".join(t.get("source_milestones", []))))
    body += "</table></div>"

    meta = '<h2>Scenario</h2><div class="card">'
    for k in ("scenario_id", "map_id", "biome", "mission_archetype", "pressure_profile", "seed"):
        meta += V.kv(k, card[k])
    meta += "</div>"
    return V.page("Scenario · {}".format(card["scenario_id"]), meta + body,
                  subtitle="{} · {} · {}".format(card["biome"], card["mission_archetype"],
                                                 card["pressure_profile"]),
                  git_sha=sha, back=("../index.html", "dashboard"))


def render_index_page(pack_card, scenario_cards, index, sha):
    ok = sum(1 for c in scenario_cards if c["runtime_status"] == "pass")
    body = '<h2>Pack</h2><div class="grid">'
    body += '<div class="card"><h3>{}</h3>'.format(V.esc(pack_card["pack_name"]))
    for k in ("scenario_count", "map_count", "runtime_result_summary",
              "shield_result_summary"):
        body += V.kv(k, pack_card[k])
    body += V.kv("package_exists", V.badge("pass" if pack_card["package_exists"] else "fail"))
    body += V.kv("pack page", V.link("packs/{}.html".format(pack_card["pack_id"]), "open"))
    body += "</div></div>"

    body += '<h2>Operator views</h2><div class="card">'
    body += V.kv("failure-code explorer", V.link("failures/index.html", "open"))
    body += V.kv("asset ownership inspector", V.link("assets/index.html", "open"))
    body += V.kv("route / walkability viewer", V.link("routes/index.html", "open"))
    body += "</div>"

    body += '<h2>Scenario matrix ({}/{} runtime pass)</h2><div class="scroll"><table>'.format(
        ok, len(scenario_cards))
    body += ("<tr><th>scenario</th><th>biome</th><th>mission</th><th>profile</th>"
             "<th>run</th><th>trav</th><th>npc</th><th>combat</th><th>reward</th>"
             "<th>save</th><th>pkg</th></tr>")
    for c in scenario_cards:
        body += "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td>".format(
            V.link("scenarios/{}.html".format(c["scenario_id"]), c["scenario_id"]),
            V.esc(c["biome"]), V.esc(c["mission_archetype"]), V.esc(c["pressure_profile"]))
        for f in ("runtime_status", "traversal_status", "npc_status", "combat_status",
                  "reward_status", "save_load_status", "package_status"):
            body += "<td>{}</td>".format(V.badge(c[f]))
        body += "</tr>"
    body += "</table></div>"
    return V.page("WorldForge Operator Dashboard", body,
                  subtitle="index integrity_result={} · {} reports · {} scenarios".format(
                      index.get("integrity_result"), index.get("report_count"),
                      index.get("scenario_count")),
                  git_sha=sha)


def render_pack_page(pack_card, scenario_cards, sha):
    body = '<h2>Overview</h2><div class="card">'
    for k in ("pack_id", "version", "source_milestone", "scenario_count", "map_count",
              "package_report_path", "package_size_bytes", "runtime_result_summary",
              "shield_result_summary", "evidence_index_path"):
        body += V.kv(k, pack_card[k])
    body += "</div>"
    body += '<h2>Biomes / archetypes / profiles</h2><div class="card">'
    body += V.kv("biomes", ", ".join(pack_card["biomes"]))
    body += V.kv("mission_archetypes", ", ".join(pack_card["mission_archetypes"]))
    body += V.kv("pressure_profiles", ", ".join(pack_card["pressure_profiles"]))
    body += "</div>"
    body += '<p class="muted">{} scenarios · {}</p>'.format(
        len(scenario_cards), V.link("../index.html", "back to matrix"))
    return V.page("Pack · {}".format(pack_card["pack_id"]), body,
                  git_sha=sha, back=("../index.html", "dashboard"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="v2.1 operator static dashboard builder.")
    ap.add_argument("--strict", action="store_true")
    args, _ = ap.parse_known_args(argv)

    idx_file = INDEX_DIR / "operator_report_index.json"
    graph_file = INDEX_DIR / "evidence_graph.json"
    if not (idx_file.is_file() and graph_file.is_file()):
        print("[operator-dashboard] FAIL — operator index missing; run operator-index-reports")
        sys.exit(1)
    index = _load(idx_file)
    graph = _load(graph_file)
    manifest = _load(MANIFEST)
    package = _load(PACKAGE_REPORT) if PACKAGE_REPORT.is_file() else {}
    sha = index.get("git_sha", "unknown")

    scenario_cards, scn_fail = build_scenario_cards(manifest, graph, package)
    pack_card, pack_fail = build_pack_card(manifest, package, index)

    # fail-closed: a card that violates its own contract cannot be published.
    if scn_fail or pack_fail:
        print("[operator-dashboard] FAIL — card schema violations:")
        for ssid, errs in scn_fail[:5]:
            print("  scenario {}: {}".format(ssid, errs))
        if pack_fail:
            print("  pack: {}".format(pack_fail))
        sys.exit(1)

    # write validated card JSON
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    (INDEX_DIR / "scenario_cards.json").write_text(
        json.dumps(scenario_cards, indent=2, sort_keys=True), encoding="utf-8")
    (INDEX_DIR / "pack_cards.json").write_text(
        json.dumps([pack_card], indent=2, sort_keys=True), encoding="utf-8")

    # render HTML
    by_scn = {}
    for t in graph.get("traces", []):
        by_scn.setdefault(t["scenario_id"], []).append(t)
    V.write_page("index.html", render_index_page(pack_card, scenario_cards, index, sha))
    V.write_page("packs/{}.html".format(pack_card["pack_id"]),
                 render_pack_page(pack_card, scenario_cards, sha))
    for c in scenario_cards:
        V.write_page("scenarios/{}.html".format(c["scenario_id"]),
                     render_scenario_page(c, by_scn.get(c["scenario_id"], []), sha))

    print("[operator-dashboard] built dashboard: 1 index + 1 pack + {} scenario pages"
          .format(len(scenario_cards)))
    print("  -> procedural/reports/operator/dashboard/index.html")
    sys.exit(0)


if __name__ == "__main__":
    main()
