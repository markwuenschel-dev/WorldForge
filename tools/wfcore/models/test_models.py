#!/usr/bin/env python3
"""wfcore.models.test_models -- negative-first suite for the typed world models.

Run from ``tools/``::

    PYTHONUTF8=1 python -m wfcore.models.test_models

WHAT THIS SUITE IS FOR
----------------------
A validator that accepts its own canonical example proves almost nothing -- the
example was written to pass. What proves a validator is the set of KNOWN-BADS it
rejects, and rejecting them FOR THE RIGHT CODE: a rejection for an unrelated
reason is coverage of the wrong rail and will not survive the next edit.

So every validator here gets one positive and at least three distinct
known-bads, each asserted against its owning failure code.

Two tests are load-bearing beyond ordinary coverage and are named as such:

  * ``test_observed_world_rejects_unbacked_values`` -- an observed model whose
    fields claim values without evidence provenance MUST be rejected. This is
    the failure mode the whole models package exists to make impossible.
  * ``test_unknown_reachability_is_not_reported_as_unreachable`` -- a node whose
    reachability could not be determined must never appear as unreachable, in
    the verdict map, in the helper lists, or in any emitted failure code.
"""

import copy
import sys

from .. import tri
from ..failure import FailureCode as C
from . import desired_world as DW
from . import graphs as G
from . import observed_world as OW

_FAILURES = []
_RAN = []


# --------------------------------------------------------------------------- #
# harness
# --------------------------------------------------------------------------- #
def _failing(checks):
    return [(n, d, code) for (n, ok, d, code) in checks if not ok]


def _codes(checks):
    return {code for (_n, ok, _d, code) in checks if not ok and code}


def expect_pass(label, checks):
    bad = _failing(checks)
    if bad:
        _FAILURES.append("{}: expected all checks to pass, {} failed:\n    {}"
                         .format(label, len(bad),
                                 "\n    ".join("{} [{}] {}".format(n, c, d)
                                               for (n, d, c) in bad[:6])))


def expect_code(label, checks, code):
    got = _codes(checks)
    if code not in got:
        _FAILURES.append(
            "{}: expected failure code {}, got {} (failing checks: {})"
            .format(label, code, sorted(got) or "none",
                    [n for (n, _d, _c) in _failing(checks)][:6]))


def expect_code_absent(label, checks, code):
    got = _codes(checks)
    if code in got:
        _FAILURES.append(
            "{}: failure code {} must NOT be emitted, but it was (checks: {})"
            .format(label, code,
                    [n for (n, _d, c) in _failing(checks) if c == code]))


def expect(label, condition, detail):
    if not condition:
        _FAILURES.append("{}: {}".format(label, detail))


def expect_eq(label, got, want):
    if got != want:
        _FAILURES.append("{}: expected {!r}, got {!r}".format(label, want, got))


def test(fn):
    _RAN.append(fn)
    return fn


# --------------------------------------------------------------------------- #
# desired world
# --------------------------------------------------------------------------- #
@test
def test_desired_world_example_is_valid():
    expect_pass("desired canonical",
                DW.validate_desired_world(DW._example_desired_world(),
                                          strict=True))


@test
def test_desired_world_known_bads():
    code = C.CORE_DESIRED_WORLD_INVALID

    # 1. a spatial relation whose endpoint names no declared entity.
    bad = DW._example_desired_world(spatial_relations=[
        {"relation_id": "relation_1", "relation": DW.REACHABLE_FROM,
         "subject_ref": "anchor_objective", "object_ref": "entity_that_is_not_declared"}])
    expect_code("desired dangling relation endpoint",
                DW.validate_desired_world(bad), code)

    # 2. an id reused across two sections -- one flat namespace.
    bad = DW._example_desired_world(gameplay_anchors=[
        {"anchor_id": "landmark_a", "role": "entry_point", "required": True}])
    expect_code("desired duplicate id across sections",
                DW.validate_desired_world(bad), code)

    # 3. a relation kind outside the closed vocabulary.
    bad = DW._example_desired_world(spatial_relations=[
        {"relation_id": "relation_1", "relation": "vaguely_by",
         "subject_ref": "anchor_objective", "object_ref": "anchor_entry"}])
    expect_code("desired unknown relation kind",
                DW.validate_desired_world(bad), code)

    # 4. THE category error: an observed record edited into a request.
    bad = DW._example_desired_world(semantic_landmarks=[
        {"landmark_id": "landmark_a", "role": "orientation_reference",
         "intent": "a reference", "provenance": "measured",
         "observed_by": "entity_enumerator", "collection_ok": True}])
    expect_code("desired carrying observation provenance",
                DW.validate_desired_world(bad), code)

    # 5. a desired world declaring nothing differences to "no change".
    bad = DW._example_desired_world(semantic_landmarks=[], gameplay_anchors=[],
                                    population=[], environmental_state=[],
                                    spatial_relations=[])
    expect_code("desired declares nothing",
                DW.validate_desired_world(bad), code)

    # 6. an anchor whose requiredness is implicit.
    bad = DW._example_desired_world(gameplay_anchors=[
        {"anchor_id": "anchor_entry", "role": "entry_point", "required": "yes"}])
    expect_code("desired anchor required not a bool",
                DW.validate_desired_world(bad), code)


@test
def test_provenance_key_lists_agree():
    """The desired-side rail must know every provenance key observed defines.

    A new key in ``OBSERVED_FIELD_ALLOWED`` that ``OBSERVATION_ONLY_FIELDS``
    does not know about is a hole: an observed record carrying only that key
    would pass the "no observation provenance" rail on the desired side.
    """
    carriers = set(OW.OBSERVED_FIELD_ALLOWED) - {"value", "detail"}
    missing = sorted(carriers - set(DW.OBSERVATION_ONLY_FIELDS))
    expect("provenance key lists agree", not missing,
           "OBSERVED_FIELD_ALLOWED key(s) {} are not listed in "
           "DW.OBSERVATION_ONLY_FIELDS, so a desired world could carry them "
           "undetected".format(missing))


# --------------------------------------------------------------------------- #
# observed world
# --------------------------------------------------------------------------- #
@test
def test_observed_world_example_is_valid():
    expect_pass("observed canonical",
                OW.validate_observed_world(OW._example_observed_world(),
                                           strict=True))


@test
def test_observed_world_rejects_unbacked_values():
    """LOAD-BEARING: a value with no evidence provenance must be REJECTED.

    Three shapes of the same lie, because they arrive by three different
    routes: a zero-filled count, a False-defaulted flag, and a copy of the
    requested value pasted into a field nobody measured.
    """
    code = C.CORE_OBSERVED_WORLD_UNBACKED

    # a. zero-filled count on an unsupported observation.
    bad = OW._example_observed_world()
    bad["population"]["entities"]["population_group_a"]["count"] = dict(
        OW.observation_unsupported("cannot count members",
                                   "operation_enumerate", "entity_enumerator"),
        value=0)
    expect_code("observed unbacked value: zero-filled count",
                OW.validate_observed_world(bad), code)

    # b. False-defaulted flag on a field nobody looked at.
    bad = OW._example_observed_world()
    bad["gameplay_anchors"]["entities"]["anchor_objective"]["role"] = dict(
        OW.not_observed("role attribution was not part of this pass"),
        value=False)
    expect_code("observed unbacked value: False default",
                OW.validate_observed_world(bad), code)

    # c. a failed observation that still produced an answer.
    bad = OW._example_observed_world()
    bad["semantic_landmarks"]["entities"]["landmark_a"]["role"] = dict(
        OW.observation_failed("enumeration raised", "operation_enumerate",
                              "entity_enumerator"),
        value="orientation_reference")
    expect_code("observed unbacked value: failed observation with a value",
                OW.validate_observed_world(bad), code)

    # d. and the positive control: the SAME fields, honestly unbacked, pass.
    expect_pass("observed honest gaps are legal",
                OW.validate_observed_world(OW._example_observed_world(),
                                           strict=True))


@test
def test_observed_world_backing_is_cross_record():
    """A forged field must also forge an operation and an evidence entry."""
    code = C.CORE_OBSERVED_WORLD_UNBACKED

    # 1. cites an operation this model does not declare.
    bad = OW._example_observed_world()
    bad["semantic_landmarks"]["entities"]["landmark_a"]["present"][
        "operation_id"] = "operation_that_was_never_declared"
    expect_code("observed cites undeclared operation",
                OW.validate_observed_world(bad), code)

    # 2. measured out of an operation that reports ok=False.
    bad = OW._example_observed_world()
    for op in bad["observation_operations"]:
        if op["operation_id"] == "operation_enumerate":
            op["ok"] = False
    expect_code("observed measured from a failed operation",
                OW.validate_observed_world(bad), code)

    # 3. cites an evidence ref that resolves to nothing.
    bad = OW._example_observed_world()
    bad["semantic_landmarks"]["entities"]["landmark_a"]["present"][
        "evidence_refs"] = ["record#no_such_entry"]
    expect_code("observed dangling evidence ref",
                OW.validate_observed_world(bad), code)

    # 4. measured but citing no evidence at all.
    bad = OW._example_observed_world()
    bad["semantic_landmarks"]["entities"]["landmark_a"]["present"][
        "evidence_refs"] = []
    expect_code("observed measured with no evidence refs",
                OW.validate_observed_world(bad), code)

    # 5. measured but collection_ok is not True.
    bad = OW._example_observed_world()
    bad["semantic_landmarks"]["entities"]["landmark_a"]["present"][
        "collection_ok"] = False
    expect_code("observed measured with collection_ok=False",
                OW.validate_observed_world(bad), code)


@test
def test_observed_world_derivations_must_bottom_out():
    code = C.CORE_OBSERVED_WORLD_UNBACKED
    path = ["spatial_relations", "entities", "relation_2", "holds_both_ways"]

    def _field(model):
        node = model
        for key in path:
            node = node[key]
        return node

    # 1. a derivation naming no inputs.
    bad = OW._example_observed_world()
    _field(bad)["derived_from"] = []
    expect_code("observed derivation with no inputs",
                OW.validate_observed_world(bad), code)

    # 2. a derivation whose input is not a field of this model.
    bad = OW._example_observed_world()
    _field(bad)["derived_from"] = ["some_other_document.some_field"]
    expect_code("observed derivation leaving the document",
                OW.validate_observed_world(bad), code)

    # 3. a derivation from an UNBACKED field: unknown in, unknown out.
    bad = OW._example_observed_world()
    _field(bad)["derived_from"] = [
        "population.entities.population_group_a.count"]
    expect_code("observed derivation from an unbacked input",
                OW.validate_observed_world(bad), code)

    # 4. a field deriving from itself.
    bad = OW._example_observed_world()
    _field(bad)["derived_from"] = [
        "spatial_relations.entities.relation_2.holds_both_ways"]
    expect_code("observed self-derivation",
                OW.validate_observed_world(bad), code)


@test
def test_observed_world_structural_known_bads():
    code = C.CORE_OBSERVED_WORLD_INVALID

    # 1. an entity outside the extent the enumeration measured.
    bad = OW._example_observed_world()
    bad["semantic_landmarks"]["entities"]["landmark_never_enumerated"] = {
        "present": OW.measured(True, "operation_enumerate", "entity_enumerator",
                               ("record#enumeration",))}
    expect_code("observed entity outside measured extent",
                OW.validate_observed_world(bad), code)

    # 2. an operation whose outcome is implicit.
    bad = OW._example_observed_world()
    bad["observation_operations"][0]["ok"] = "true"
    expect_code("observed operation ok is not a bool",
                OW.validate_observed_world(bad), code)

    # 3. an unrecognised provenance.
    bad = OW._example_observed_world()
    bad["semantic_landmarks"]["entities"]["landmark_a"]["present"][
        "provenance"] = "probably_fine"
    expect_code("observed unknown provenance",
                OW.validate_observed_world(bad), code)

    # 4. an evidence entry with no locator.
    bad = OW._example_observed_world()
    bad["evidence_index"]["record#enumeration"] = {
        "evidence_kind": OW.EVIDENCE_RECORD, "locator": ""}
    expect_code("observed evidence entry with no locator",
                OW.validate_observed_world(bad), code)

    # 5. wrong schema version.
    expect_code("observed wrong schema_version",
                OW.validate_observed_world(
                    OW._example_observed_world(schema_version="wf.core.x.v9")),
                code)


@test
def test_observed_readers_never_invent_a_value():
    unbacked = OW.not_observed("nobody looked")
    has, value = OW.read(unbacked)
    expect_eq("read(unbacked).has_value", has, False)
    expect_eq("read(unbacked).value", value, None)
    expect_eq("field_evidence(unbacked)", OW.field_evidence(unbacked),
              tri.UNKNOWN)
    expect("field_evidence never returns VIOLATED",
           OW.field_evidence(unbacked) != tri.VIOLATED,
           "an unmeasured field must be UNKNOWN, not a violation")

    raised = False
    try:
        OW.require_value(unbacked, "some.path")
    except OW.UnbackedFieldError:
        raised = True
    expect("require_value raises on an unbacked field", raised,
           "require_value returned a value for a field with no measurement")

    backed = OW.measured(7, "operation_x", "collector_x", ("record#x",))
    expect_eq("read(backed)", OW.read(backed), (True, 7))
    expect_eq("field_evidence(backed)", OW.field_evidence(backed),
              tri.SATISFIED)


# --------------------------------------------------------------------------- #
# the desired <-> observed pair
# --------------------------------------------------------------------------- #
@test
def test_model_pair_matching_identity_is_differenceable():
    d = DW._example_desired_world()
    o = OW._example_observed_world()
    expect_eq("same_world on a matching pair", OW.same_world(d, o),
              tri.SATISFIED)
    expect_pass("pair rails on a matching pair", OW.validate_model_pair(d, o))


@test
def test_model_pair_identity_mismatch():
    d = DW._example_desired_world()

    # 1. a different world entirely.
    o = OW._example_observed_world()
    o["world_identity"]["value"]["world_id"] = "world_0002"
    expect_eq("same_world on a different world", OW.same_world(d, o),
              tri.VIOLATED)
    expect_code("pair different world_id", OW.validate_model_pair(d, o),
                C.CORE_MODEL_IDENTITY_MISMATCH)

    # 2. a stale observation: right world, earlier revision.
    o = OW._example_observed_world()
    o["world_identity"]["value"]["revision"] = 0
    expect_code("pair revision drift", OW.validate_model_pair(d, o),
                C.CORE_MODEL_IDENTITY_MISMATCH)

    # 3. a different request against the same world id.
    o = OW._example_observed_world()
    o["world_identity"]["value"]["request_id"] = "request_0002"
    expect_code("pair different request_id", OW.validate_model_pair(d, o),
                C.CORE_MODEL_IDENTITY_MISMATCH)


@test
def test_model_pair_unmeasured_identity_is_not_a_mismatch():
    """UNKNOWN identity blocks, but must never be reported as a MISMATCH.

    They lead to opposite repairs: a mismatch means stop and re-target, an
    unknown means go bind the world and observe. Reporting the first when the
    second happened sends the caller to fix a targeting bug that does not exist.
    """
    d = DW._example_desired_world()
    o = OW._example_observed_world()
    o["world_identity"] = OW.not_observed(
        "the world was never bound, so no identity was read back")

    expect_eq("same_world with an unmeasured identity", OW.same_world(d, o),
              tri.UNKNOWN)
    expect("unmeasured identity blocks differencing",
           not tri.accepts(OW.differenceable(d, o)),
           "an unidentified observation must not be differenceable")

    checks = OW.validate_model_pair(d, o)
    expect_code("pair unmeasured identity is UNBACKED", checks,
                C.CORE_OBSERVED_WORLD_UNBACKED)
    expect_code_absent("pair unmeasured identity is not a MISMATCH", checks,
                       C.CORE_MODEL_IDENTITY_MISMATCH)


# --------------------------------------------------------------------------- #
# graphs: documents
# --------------------------------------------------------------------------- #
@test
def test_experience_graph_example_is_valid():
    expect_pass("experience graph canonical",
                G.validate_experience_graph(G._example_experience_graph(),
                                            strict=True))


@test
def test_experience_graph_known_bads():
    code = C.CORE_EXPERIENCE_GRAPH_INVALID

    # 1. a connection pointing at a beat that does not exist.
    bad = copy.deepcopy(G._example_experience_graph())
    bad["connections"][1]["to_beat"] = "beat_that_does_not_exist"
    expect_code("experience dangling connection",
                G.validate_experience_graph(bad), code)

    # 2. an entry beat that is not a declared beat.
    bad = G._example_experience_graph(entry_beats=["beat_that_does_not_exist"])
    expect_code("experience dangling entry beat",
                G.validate_experience_graph(bad), code)

    # 3. a sequential connection running backwards through the ordering.
    bad = copy.deepcopy(G._example_experience_graph())
    bad["connections"][1]["from_beat"] = "beat_objective"
    bad["connections"][1]["to_beat"] = "beat_middle"
    expect_code("experience sequential runs backwards",
                G.validate_experience_graph(bad), code)

    # 4. two beats sharing one position in the order.
    bad = copy.deepcopy(G._example_experience_graph())
    bad["beats"][2]["ordinal"] = 1
    expect_code("experience duplicate ordinal",
                G.validate_experience_graph(bad), code)

    # 5. existence as a boolean -- two-valued thinking sneaking back in.
    bad = copy.deepcopy(G._example_experience_graph())
    bad["beats"][1]["existence"] = True
    expect_code("experience existence is a bool",
                G.validate_experience_graph(bad), code)

    # 6. an edge from a beat to itself.
    bad = copy.deepcopy(G._example_experience_graph())
    bad["connections"][0]["to_beat"] = "beat_entry"
    expect_code("experience self connection",
                G.validate_experience_graph(bad), code)


@test
def test_env_state_graph_example_is_valid():
    expect_pass("env state graph canonical",
                G.validate_env_state_graph(G._example_env_state_graph(),
                                           strict=True))


@test
def test_env_state_graph_known_bads():
    code = C.CORE_ENV_STATE_GRAPH_INVALID

    # 1. a transition from a state to itself permits nothing.
    bad = copy.deepcopy(G._example_env_state_graph())
    bad["transitions"][0]["to_state"] = "state_illumination_high"
    expect_code("env self transition", G.validate_env_state_graph(bad), code)

    # 2. a trigger nothing can fire.
    bad = copy.deepcopy(G._example_env_state_graph())
    bad["transitions"][0]["trigger"] = "eventually"
    expect_code("env unknown trigger", G.validate_env_state_graph(bad), code)

    # 3. two initial states on one axis.
    bad = G._example_env_state_graph(initial_states=[
        "state_illumination_high", "state_illumination_low",
        "state_visibility_unobstructed"])
    expect_code("env two initial states on one dimension",
                G.validate_env_state_graph(bad), code)

    # 4. an axis with states but no starting value.
    bad = G._example_env_state_graph(initial_states=["state_illumination_high"])
    expect_code("env uninitialised dimension",
                G.validate_env_state_graph(bad), code)

    # 5. an initial state that is not a declared state.
    bad = G._example_env_state_graph(
        initial_states=["state_that_does_not_exist"])
    expect_code("env dangling initial state",
                G.validate_env_state_graph(bad), code)

    # 6. traversable as a boolean.
    bad = copy.deepcopy(G._example_env_state_graph())
    bad["transitions"][0]["traversable"] = True
    expect_code("env traversable is a bool",
                G.validate_env_state_graph(bad), code)


# --------------------------------------------------------------------------- #
# graphs: reachability
# --------------------------------------------------------------------------- #
@test
def test_reachability_partitions_into_three():
    nodes = {"n_source": tri.SATISFIED, "n_certain": tri.SATISFIED,
             "n_hinges": tri.SATISFIED, "n_isolated": tri.SATISFIED}
    edges = [("n_source", "n_certain", tri.SATISFIED),
             ("n_certain", "n_hinges", tri.UNKNOWN)]
    verdicts = G.reachability(nodes, edges, ["n_source"])

    expect_eq("source is reachable", verdicts["n_source"], tri.SATISFIED)
    expect_eq("determined path is reachable", verdicts["n_certain"],
              tri.SATISFIED)
    expect_eq("path through an unknown edge is UNKNOWN", verdicts["n_hinges"],
              tri.UNKNOWN)
    expect_eq("node with no path at all is VIOLATED", verdicts["n_isolated"],
              tri.VIOLATED)

    # the three helper lists must partition the node set with no overlap.
    r = set(G.reachable_nodes(verdicts))
    u = set(G.unreachable_nodes(verdicts))
    d = set(G.undetermined_nodes(verdicts))
    expect("reachability lists are disjoint",
           not (r & u) and not (r & d) and not (u & d),
           "reachable={} unreachable={} undetermined={}".format(r, u, d))
    expect_eq("reachability lists cover every node", r | u | d, set(nodes))


@test
def test_unknown_reachability_is_not_reported_as_unreachable():
    """LOAD-BEARING: undetermined is not unreachable, anywhere in the output."""
    nodes = {"n_source": tri.SATISFIED, "n_hinges": tri.SATISFIED}
    edges = [("n_source", "n_hinges", tri.UNKNOWN)]
    verdicts = G.reachability(nodes, edges, ["n_source"])

    expect_eq("undetermined node's verdict", verdicts["n_hinges"], tri.UNKNOWN)
    expect("undetermined node is NOT in unreachable_nodes",
           "n_hinges" not in G.unreachable_nodes(verdicts),
           "unreachable_nodes returned {}".format(G.unreachable_nodes(verdicts)))
    expect("undetermined node IS in undetermined_nodes",
           "n_hinges" in G.undetermined_nodes(verdicts),
           "undetermined_nodes returned {}".format(
               G.undetermined_nodes(verdicts)))

    # an UNKNOWN must still BLOCK: tri.accepts, never `!= VIOLATED`.
    folded = G.reachability_verdict(verdicts)
    expect_eq("folded verdict with an undetermined node", folded, tri.UNKNOWN)
    expect("an undetermined node blocks acceptance", not tri.accepts(folded),
           "folded verdict {} accepted".format(folded))

    # and the same must hold through the emitted CHECKS: no unreachable code.
    graph = G._example_experience_graph()
    graph["connections"][1]["traversable"] = tri.UNKNOWN  # -> beat_objective
    checks = G.validate_graph_reachability(graph, G.GRAPH_KIND_EXPERIENCE)
    expect_code_absent("undetermined reachability emits no UNREACHABLE code",
                       checks, C.CORE_GRAPH_UNREACHABLE_NODE)
    expect_code("undetermined reachability is reported as not-determined",
                checks, C.CORE_GRAPH_REACHABILITY_NOT_DETERMINED)
    # ...and NOT as a constraint nobody evaluated. WF1202 means "no evaluation
    # happened at all"; here the reachability query ran and could not decide.
    # Keeping them distinct is what lets repair tell "go measure this edge" from
    # "go evaluate this constraint".
    expect_code_absent("undetermined reachability is not WF1202",
                       checks, C.CORE_CONSTRAINT_NOT_EVALUATED)
    expect("the undetermined beat is named in a check",
           any("beat_objective::undetermined" in n
               for (n, _d, _c) in _failing(checks)),
           "no undetermined check for beat_objective: {}".format(
               [n for (n, _d, _c) in _failing(checks)]))


@test
def test_genuinely_unreachable_node_is_reported():
    """The other half: a node unreachable even optimistically MUST be named."""
    graph = copy.deepcopy(G._example_experience_graph())
    graph["beats"].append({"beat_id": "beat_orphan", "ordinal": 3,
                           "role": "intermediate", "existence": tri.SATISFIED})
    checks = G.validate_graph_reachability(graph, G.GRAPH_KIND_EXPERIENCE)
    expect_code("orphan beat is reported unreachable", checks,
                C.CORE_GRAPH_UNREACHABLE_NODE)

    verdicts = G.graph_reachability(graph, G.GRAPH_KIND_EXPERIENCE)
    expect_eq("orphan beat's verdict", verdicts["beat_orphan"], tri.VIOLATED)
    expect("orphan beat is in unreachable_nodes",
           "beat_orphan" in G.unreachable_nodes(verdicts),
           "unreachable_nodes returned {}".format(G.unreachable_nodes(verdicts)))


@test
def test_absent_node_is_unreachable_not_unknown():
    """A node established as ABSENT is unreachable; that is a measured fact."""
    nodes = {"n_source": tri.SATISFIED, "n_absent": tri.VIOLATED}
    edges = [("n_source", "n_absent", tri.SATISFIED)]
    verdicts = G.reachability(nodes, edges, ["n_source"])
    expect_eq("an absent node is unreachable", verdicts["n_absent"],
              tri.VIOLATED)


@test
def test_canonical_graphs_are_fully_reachable():
    for (graph, kind, label) in (
            (G._example_experience_graph(), G.GRAPH_KIND_EXPERIENCE,
             "experience"),
            (G._example_env_state_graph(), G.GRAPH_KIND_ENV_STATE,
             "env state")):
        verdicts = G.graph_reachability(graph, kind)
        expect_eq("{} canonical folded verdict".format(label),
                  G.reachability_verdict(verdicts), tri.SATISFIED)
        expect_pass("{} canonical reachability rails".format(label),
                    G.validate_graph_reachability(graph, kind))


# --------------------------------------------------------------------------- #
# hygiene: Core owns no consumer's vocabulary
# --------------------------------------------------------------------------- #
@test
def test_examples_are_domain_neutral():
    """No proper noun from any consumer may appear in a Core example.

    Checked as an ALLOW-list over the id vocabulary rather than a deny-list of
    known game words: a deny-list only catches the games somebody thought of,
    and the next consumer's vocabulary would sail through it.
    """
    import re
    allowed_token = re.compile(
        r"^(world|request|landmark|anchor|population|group|state|relation|beat|"
        r"connection|transition|experience|graph|env|operation|record|"
        r"observation|entry|objective|middle|orientation|reference|ambient|"
        r"agent|point|illumination|visibility|high|low|unobstructed|obstructed|"
        r"intermediate|derivation|derive|enumeration|enumerate|bind|read|"
        r"relations|"
        r"a|b|[0-9]+)$")

    def ids_of(obj, out):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and k.endswith("_id") \
                        and isinstance(v, str):
                    out.append(v)
                ids_of(v, out)
        elif isinstance(obj, list):
            for v in obj:
                ids_of(v, out)
        return out

    found = []
    for example in (DW._example_desired_world(), OW._example_observed_world(),
                    G._example_experience_graph(),
                    G._example_env_state_graph()):
        ids_of(example, found)

    offenders = sorted({
        ident for ident in found
        if any(not allowed_token.match(tok) for tok in ident.split("_"))})
    expect("example ids are domain-neutral", not offenders,
           "id(s) {} contain tokens outside the neutral vocabulary; a Core "
           "example naming a consumer's content has already chosen a subject "
           "nobody asked for".format(offenders))


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #
def main():
    for fn in _RAN:
        try:
            fn()
        except Exception as exc:  # a crashing test is a failing test
            _FAILURES.append("{}: raised {}: {}".format(
                fn.__name__, type(exc).__name__, exc))
    print("wfcore.models.test_models: ran {} tests".format(len(_RAN)))
    if _FAILURES:
        print("FAILED ({} problem(s)):".format(len(_FAILURES)))
        for f in _FAILURES:
            print("  - {}".format(f))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
