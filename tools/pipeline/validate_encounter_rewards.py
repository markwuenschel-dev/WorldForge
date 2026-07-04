#!/usr/bin/env python3
"""validate_encounter_rewards.py — WorldForge v1.4 encounter reward-hook validator (Lane C).

Proves brief §8 "rewards fire on resolution, never before": every encounter
declares well-formed, uniquely-identified reward hooks whose reward_type is a
known v1.3 reward vocabulary entry, and every hook fires on
"encounter_resolved" (the v1.4 contract point). resource_contest encounters
must actually stake a contestable resource (a resource_grant hook + non-empty
resource_nodes whose node ids are wired into objective_links); no encounter
may grant a resource it does not physically have; and the completion state
that gates every reward must be persisted so rewards survive save/load.
Violations block with ENCOUNTER_REWARD_FAILURE.

Usage:
    python tools/pipeline/validate_encounter_rewards.py --pack encounter_loop_world [--strict]
Writes: procedural/reports/encounters/validate_encounter_rewards/validate_encounter_rewards_report.json
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))

import encounter_contract as EC
import mission_contract as MC
from encounter_catalog import load_encounter_catalog
from report_meta import build_meta, strict_from_env
from validation_report import ValidationReport
from failure_codes import FailureCode

FIRES_ON_RESOLVED = "encounter_resolved"


def check_rewards(rep, eid, enc):
    """Importable core: add reward-hook checks for one encounter to ``rep``."""
    code = FailureCode.ENCOUNTER_REWARD_FAILURE

    def c(name, ok, detail=""):
        return rep.check("{}::{}".format(eid, name), ok, detail, code=code)

    hooks = enc.get("reward_hooks") or []
    c("reward_hooks_present", bool(hooks),
      "no reward hooks — encounter resolution grants nothing")

    ids = []
    for i, h in enumerate(hooks):
        shape_ok = isinstance(h, dict) and all(k in h for k in EC.REWARD_HOOK_REQUIRED)
        c("reward_{}_shape".format(i), shape_ok,
          "reward hook {} missing required keys {}".format(i, EC.REWARD_HOOK_REQUIRED))
        if not shape_ok:
            continue
        ids.append(h["reward_id"])
        c("reward_{}_type_known".format(i), h.get("reward_type") in MC.REWARD_TYPES,
          "unknown reward_type '{}' (allowed: {})".format(
              h.get("reward_type"), MC.REWARD_TYPES))
        # v1.4 contract: rewards fire on resolution, never before.
        c("reward_{}_fires_on_resolution".format(i),
          h.get("fires_on") == FIRES_ON_RESOLVED,
          "fires_on '{}' != '{}' — reward would fire without contest "
          "resolution".format(h.get("fires_on"), FIRES_ON_RESOLVED))

    c("reward_ids_unique", len(ids) == len(set(ids)),
      "duplicate reward ids: {}".format(sorted({r for r in ids if ids.count(r) > 1})))

    node_ids = [n.get("id") for n in enc.get("resource_nodes") or []
                if isinstance(n, dict) and n.get("id")]
    links = enc.get("objective_links") or []
    grants_resource = any(isinstance(h, dict) and h.get("reward_type") == "resource_grant"
                          for h in hooks)

    if enc.get("encounter_archetype") == "resource_contest":
        # A resource contest must stake an actual, reachable resource.
        c("resource_contest_has_resource_grant", grants_resource,
          "resource_contest without a resource_grant reward hook")
        c("resource_contest_has_resource_nodes", bool(node_ids),
          "resource_contest with no resource_nodes — nothing to contest")
        unlinked = [nid for nid in node_ids if nid not in links]
        c("resource_nodes_in_objective_links", bool(node_ids) and not unlinked,
          "resource nodes not wired into objective_links: {}".format(
              unlinked or "(no resource nodes)"))

    # No encounter may grant a resource it does not physically have.
    c("no_phantom_resource_grant", (not grants_resource) or bool(node_ids),
      "resource_grant reward hook but resource_nodes is empty")

    # Reward state persistence: the completion state key(s) that gate every
    # hook must be persisted, or rewards evaporate across save/load.
    if hooks:
        persist = (enc.get("save_load_contract") or {}).get("persist_keys") or []
        comp_keys = sorted({cc.get("state_key")
                            for cc in enc.get("completion_conditions") or []
                            if isinstance(cc, dict) and cc.get("state_key")})
        unpersisted = [k for k in comp_keys if k not in persist]
        c("reward_state_persisted", not unpersisted,
          "completion state keys gating rewards are not persisted: {}".format(
              unpersisted))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate v1.4 encounter reward hooks (brief §8).")
    ap.add_argument("--pack", default="encounter_loop_world")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    strict = args.strict or strict_from_env()

    rep = ValidationReport("pack", args.pack, strict=strict)
    catalog = load_encounter_catalog(REPO_ROOT)
    eids = sorted((catalog.get("encounters") or {}).keys())
    if not eids:
        rep.error("no encounters — run 'make create-encounters' first")
    n = 0
    for eid in eids:
        enc, err = EC.load_encounter(eid)
        if enc is None:
            rep.check("{}::loads".format(eid), False, err,
                      code=FailureCode.ENCOUNTER_REWARD_FAILURE)
            continue
        check_rewards(rep, eid, enc)
        n += 1
    rep.finalize()
    rep.set_meta(build_meta(command="validate-encounter-rewards", pack=args.pack,
                            strict=strict, status=rep.status, record_count=n))
    rep.write(REPO_ROOT / EC.ENCOUNTER_REPORTS_REL / "validate_encounter_rewards",
              "validate_encounter_rewards_report.json")
    rep.print_summary("validate-encounter-rewards")
    sys.exit(rep.exit_code)


if __name__ == "__main__":
    main()
