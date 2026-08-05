#!/usr/bin/env python3
"""wfcore.models.graphs -- the experience graph, the environmental-state graph,
and honest three-valued reachability over both.

TWO GRAPHS, ONE REACHABILITY
----------------------------
``ExperienceGraph``    ordered consumer-facing beats and how they connect. It
                       answers "can the consumer actually get from the entry to
                       everything the request asked for".
``EnvStateGraph``      environmental states and the transitions between them
                       that are PERMITTED. It answers "can the world actually
                       reach the state the request asked for".

Structurally they are the same object -- nodes, directed edges, declared
sources -- so reachability is written ONCE, in :func:`reachability`, and both
graphs call it. A second copy would drift, and the copy that drifted would be
the one nobody tested.

WHY REACHABILITY IS THREE-VALUED
--------------------------------
A boolean reachability answer cannot distinguish::

    "no path exists to this node"
    "we could not determine whether a path exists"

and collapsing them is worse than useless in both directions:

* an undetermined node reported as UNREACHABLE sends a repair planner to build a
  connection that may already exist, against a graph nobody finished measuring;
* an undetermined node reported as REACHABLE is fake-green of the purest kind --
  the consumer is told they can get somewhere nobody checked.

So every node carries an ``existence`` tri-value and every edge a
``traversable`` tri-value, and the verdict per node is a ``wfcore.tri`` value:

    SATISFIED  a path exists using ONLY determined nodes and edges
    UNKNOWN    no such determined path, but one exists once undetermined nodes
               and edges are optimistically admitted -- reachability HINGES on
               something unmeasured
    VIOLATED   no path exists even when every undetermined element is admitted;
               the node is unreachable, and no further measurement can change it

That last clause is what makes VIOLATED safe to act on. It is computed from the
OPTIMISTIC closure, so a node is only ever called unreachable when it would
still be unreachable under the most generous reading of everything unknown.
Calling it from the pessimistic closure would report "unreachable" for nodes
that are merely unmeasured -- exactly the lie this design exists to prevent.

FAILURE CODES, AND THE ONE THIS FILE REFUSES TO MISUSE
------------------------------------------------------
``CORE_GRAPH_UNREACHABLE_NODE`` is emitted ONLY for VIOLATED nodes. An UNKNOWN
node blocks acceptance too, but it is reported under
``CORE_GRAPH_REACHABILITY_NOT_DETERMINED`` (WF1223) -- a dedicated code meaning
"the query ran and could not decide", distinct from WF1202, which means a
constraint nothing evaluated at all. Attaching the unreachable code to an
undetermined node would publish, in the evidence, a claim of unreachability that
nobody established, and would send repair to build connectivity that may already
be there.
"""

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .. import tri
from ..failure import FailureCode as C

# --------------------------------------------------------------------------- #
# schema identity
# --------------------------------------------------------------------------- #
RT_EXPERIENCE_GRAPH = "wf.core.experience_graph.v1"
RT_ENV_STATE_GRAPH = "wf.core.env_state_graph.v1"

GRAPH_KIND_EXPERIENCE = "experience"
GRAPH_KIND_ENV_STATE = "env_state"
GRAPH_KINDS = (GRAPH_KIND_EXPERIENCE, GRAPH_KIND_ENV_STATE)

# --------------------------------------------------------------------------- #
# Experience-graph vocabulary.
# --------------------------------------------------------------------------- #
CONNECTION_SEQUENTIAL = "sequential"
CONNECTION_BRANCH = "branch"
CONNECTION_OPTIONAL_DETOUR = "optional_detour"
CONNECTION_RETURN = "return"

BEAT_CONNECTION_KINDS = (CONNECTION_SEQUENTIAL, CONNECTION_BRANCH,
                         CONNECTION_OPTIONAL_DETOUR, CONNECTION_RETURN)

# Kinds that assert forward progress through the ordering. A ``sequential`` edge
# that runs from a higher ordinal to a lower one claims the order and then
# contradicts it, and a reader trusting either half is wrong.
ORDER_ASSERTING_KINDS = (CONNECTION_SEQUENTIAL,)

BEAT_REQUIRED = ("beat_id", "ordinal", "role", "existence")
BEAT_ALLOWED = BEAT_REQUIRED + ("anchor_ref", "detail")

CONNECTION_REQUIRED = ("connection_id", "from_beat", "to_beat",
                       "connection_kind", "traversable")
CONNECTION_ALLOWED = CONNECTION_REQUIRED + ("detail",)

EXPERIENCE_GRAPH_REQUIRED = ("graph_id", "world_id", "beats", "entry_beats",
                             "connections", "schema_version")
EXPERIENCE_GRAPH_ALLOWED = EXPERIENCE_GRAPH_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes")

# --------------------------------------------------------------------------- #
# Environmental-state-graph vocabulary.
# --------------------------------------------------------------------------- #
TRIGGER_CONSUMER_ACTION = "consumer_action"
TRIGGER_ELAPSED_TIME = "elapsed_time"
TRIGGER_STATE_CONDITION = "state_condition"
TRIGGER_EXTERNAL_SIGNAL = "external_signal"

TRANSITION_TRIGGERS = (TRIGGER_CONSUMER_ACTION, TRIGGER_ELAPSED_TIME,
                       TRIGGER_STATE_CONDITION, TRIGGER_EXTERNAL_SIGNAL)

STATE_REQUIRED = ("state_id", "state_dimension", "state_value", "existence")
STATE_ALLOWED = STATE_REQUIRED + ("detail",)

TRANSITION_REQUIRED = ("transition_id", "from_state", "to_state", "trigger",
                       "traversable")
TRANSITION_ALLOWED = TRANSITION_REQUIRED + ("detail",)

ENV_STATE_GRAPH_REQUIRED = ("graph_id", "world_id", "states", "initial_states",
                            "transitions", "schema_version")
ENV_STATE_GRAPH_ALLOWED = ENV_STATE_GRAPH_REQUIRED + (
    "meta", "report_type", "created_by", "created_at", "notes")

Check = Tuple[str, bool, str, Optional[str]]

_XP = "xg::"
_EP = "eg::"
_RP = "reach::"

# Per graph kind: (node section, node id field, edge section, edge id field,
# edge from field, edge to field, sources field, failure code, schema id).
_KIND_SPEC = {
    GRAPH_KIND_EXPERIENCE: ("beats", "beat_id", "connections", "connection_id",
                            "from_beat", "to_beat", "entry_beats",
                            C.CORE_EXPERIENCE_GRAPH_INVALID,
                            RT_EXPERIENCE_GRAPH),
    GRAPH_KIND_ENV_STATE: ("states", "state_id", "transitions", "transition_id",
                           "from_state", "to_state", "initial_states",
                           C.CORE_ENV_STATE_GRAPH_INVALID, RT_ENV_STATE_GRAPH),
}


# --------------------------------------------------------------------------- #
# reachability -- ONE implementation, used by both graphs
# --------------------------------------------------------------------------- #
def _closure(nodes: Dict[str, str], edges: List[Tuple[str, str, str]],
             sources: Iterable[str], admitted: Tuple[str, ...]) -> Set[str]:
    """Nodes reachable from ``sources`` using only elements whose tri is in
    ``admitted``. A source whose own existence is not admitted seeds nothing."""
    adjacency: Dict[str, List[Tuple[str, str]]] = {}
    for (a, b, traversable) in edges:
        adjacency.setdefault(a, []).append((b, traversable))

    reached = {s for s in sources if nodes.get(s) in admitted}
    frontier = list(reached)
    while frontier:
        current = frontier.pop()
        for (nxt, traversable) in adjacency.get(current, ()):
            if traversable not in admitted:
                continue
            if nodes.get(nxt) not in admitted:
                continue
            if nxt not in reached:
                reached.add(nxt)
                frontier.append(nxt)
    return reached


def reachability(nodes: Dict[str, str], edges: List[Tuple[str, str, str]],
                 sources: Iterable[str]) -> Dict[str, str]:
    """Per-node reachability as a ``wfcore.tri`` value.

    Args:
        nodes:   ``{node_id: existence_tri}``
        edges:   ``[(from_id, to_id, traversable_tri), ...]``
        sources: node ids reachability starts from

    Two closures are computed and their DIFFERENCE is the honest unknown:

        certain  = closure admitting only SATISFIED nodes/edges
        possible = closure admitting SATISFIED and UNKNOWN

    ``certain`` is a subset of ``possible`` by construction, so the three
    outcomes partition the node set with no overlap and no gap:

        in certain                -> SATISFIED
        in possible, not certain  -> UNKNOWN   (hinges on something unmeasured)
        in neither                -> VIOLATED  (unreachable even optimistically)

    Deriving VIOLATED from ``possible`` rather than ``certain`` is the load-
    bearing choice. It guarantees that a node is only ever called unreachable
    when NO amount of further measurement could connect it -- an unmeasured edge
    can never produce a false "unreachable".
    """
    certain = _closure(nodes, edges, sources, (tri.SATISFIED,))
    possible = _closure(nodes, edges, sources, (tri.SATISFIED, tri.UNKNOWN))
    verdicts: Dict[str, str] = {}
    for node_id in nodes:
        if node_id in certain:
            verdicts[node_id] = tri.SATISFIED
        elif node_id in possible:
            verdicts[node_id] = tri.UNKNOWN
        else:
            verdicts[node_id] = tri.VIOLATED
    return verdicts


def reachable_nodes(verdicts: Dict[str, str]) -> List[str]:
    """Nodes PROVEN reachable. Never includes an undetermined node."""
    return sorted(n for n, v in verdicts.items() if v == tri.SATISFIED)


def unreachable_nodes(verdicts: Dict[str, str]) -> List[str]:
    """Nodes PROVEN unreachable. Never includes an undetermined node.

    The exclusion is the point: this list is what a repair planner acts on, and
    an undetermined node in it would send repair to build connectivity nobody
    established was missing.
    """
    return sorted(n for n, v in verdicts.items() if v == tri.VIOLATED)


def undetermined_nodes(verdicts: Dict[str, str]) -> List[str]:
    """Nodes whose reachability could not be determined. Distinct from both."""
    return sorted(n for n, v in verdicts.items() if v == tri.UNKNOWN)


def reachability_verdict(verdicts: Dict[str, str]) -> str:
    """Fold per-node verdicts into ONE tri-value via ``tri.conj``.

    Kleene AND: a single VIOLATED is decisive, and any UNKNOWN with no VIOLATED
    yields UNKNOWN, which blocks acceptance without claiming a failure.
    """
    return tri.conj(verdicts[n] for n in sorted(verdicts))


# --------------------------------------------------------------------------- #
# graph -> reachability inputs
# --------------------------------------------------------------------------- #
def _graph_reachability_inputs(graph: Any, kind: str):
    (node_sec, node_id_f, edge_sec, _edge_id_f, from_f, to_f, src_f,
     _code, _rt) = _KIND_SPEC[kind]

    nodes: Dict[str, str] = {}
    raw_nodes = graph.get(node_sec) if isinstance(graph, dict) else None
    if isinstance(raw_nodes, list):
        for n in raw_nodes:
            if not isinstance(n, dict):
                continue
            nid = n.get(node_id_f)
            if isinstance(nid, str) and nid:
                existence = n.get("existence")
                # An unrecognised existence value is treated as UNKNOWN here,
                # never as present. The document validator is what rejects it;
                # reachability must not meanwhile assume the generous reading.
                nodes[nid] = existence if existence in tri.TRI_VALUES \
                    else tri.UNKNOWN

    edges: List[Tuple[str, str, str]] = []
    raw_edges = graph.get(edge_sec) if isinstance(graph, dict) else None
    if isinstance(raw_edges, list):
        for e in raw_edges:
            if not isinstance(e, dict):
                continue
            a, b = e.get(from_f), e.get(to_f)
            if not (isinstance(a, str) and isinstance(b, str)):
                continue
            traversable = e.get("traversable")
            edges.append((a, b, traversable if traversable in tri.TRI_VALUES
                          else tri.UNKNOWN))

    raw_sources = graph.get(src_f) if isinstance(graph, dict) else None
    sources = [s for s in raw_sources if isinstance(s, str)] \
        if isinstance(raw_sources, list) else []
    return nodes, edges, sources


def graph_reachability(graph: Any, kind: str) -> Dict[str, str]:
    """Per-node reachability for a whole graph document."""
    if kind not in GRAPH_KINDS:
        raise ValueError("graph kind must be one of {} (got {!r})".format(
            GRAPH_KINDS, kind))
    nodes, edges, sources = _graph_reachability_inputs(graph, kind)
    return reachability(nodes, edges, sources)


# --------------------------------------------------------------------------- #
# shared structural rails
# --------------------------------------------------------------------------- #
def _required(obj: Dict[str, Any], fields: Tuple[str, ...], code: str,
              prefix: str, label: str) -> List[Check]:
    out: List[Check] = []
    for fld in fields:
        present = obj.get(fld) is not None and obj.get(fld) != ""
        out.append((prefix + label + "has_" + fld, present,
                    "{} required field {!r} {}".format(
                        label, fld, "present" if present else "missing/empty"),
                    None if present else code))
    return out


def _tri_field(obj: Dict[str, Any], field: str, code: str, prefix: str,
               label: str) -> List[Check]:
    v = obj.get(field)
    ok = v in tri.TRI_VALUES
    return [(prefix + label + field + "_is_tri", ok,
             "{}{} must be one of {} (got {!r}); a boolean here cannot say "
             "'we did not determine this', which is the whole reason "
             "reachability is three-valued".format(label, field,
                                                   tri.TRI_VALUES, v),
             None if ok else code)]


def _validate_graph_common(obj: Any, kind: str, strict: bool) -> List[Check]:
    """Rails identical for both graphs: shape, id uniqueness, edge resolution."""
    (node_sec, node_id_f, edge_sec, edge_id_f, from_f, to_f, src_f, code,
     rt) = _KIND_SPEC[kind]
    prefix = _XP if kind == GRAPH_KIND_EXPERIENCE else _EP
    required = (EXPERIENCE_GRAPH_REQUIRED if kind == GRAPH_KIND_EXPERIENCE
                else ENV_STATE_GRAPH_REQUIRED)
    allowed = (EXPERIENCE_GRAPH_ALLOWED if kind == GRAPH_KIND_EXPERIENCE
               else ENV_STATE_GRAPH_ALLOWED)
    node_req = (BEAT_REQUIRED if kind == GRAPH_KIND_EXPERIENCE
                else STATE_REQUIRED)
    edge_req = (CONNECTION_REQUIRED if kind == GRAPH_KIND_EXPERIENCE
                else TRANSITION_REQUIRED)

    checks: List[Check] = []

    if not isinstance(obj, dict):
        return [(prefix + "is_object", False,
                 "graph must be an object, got {}".format(type(obj).__name__),
                 code)]

    for fld in required:
        present = obj.get(fld) is not None
        checks.append((prefix + "has_" + fld, present,
                       "required field {!r} {}".format(
                           fld, "present" if present else "missing"),
                       None if present else code))

    if strict:
        unknown = sorted(set(obj) - set(allowed))
        checks.append((prefix + "no_unknown_fields", not unknown,
                       "unexpected field(s) {}".format(unknown) if unknown
                       else "no unexpected fields",
                       None if not unknown else code))

    sv = obj.get("schema_version")
    checks.append((prefix + "schema_version", sv == rt,
                   "schema_version must be {!r} (got {!r})".format(rt, sv),
                   None if sv == rt else code))

    for fld in ("graph_id", "world_id"):
        v = obj.get(fld)
        ok = isinstance(v, str) and bool(v.strip())
        checks.append((prefix + fld + "_nonempty", ok,
                       "{} must be a non-empty string (got {!r}); a graph that "
                       "names no world cannot be checked against the world it "
                       "describes".format(fld, v),
                       None if ok else code))

    nodes = obj.get(node_sec)
    nodes_ok = isinstance(nodes, list) and all(isinstance(n, dict)
                                               for n in nodes)
    checks.append((prefix + node_sec + "_list_of_objects", nodes_ok,
                   "{} must be a list of objects".format(node_sec),
                   None if nodes_ok else code))
    node_list = [n for n in nodes if isinstance(n, dict)] \
        if isinstance(nodes, list) else []

    checks.append((prefix + node_sec + "_nonempty", len(node_list) > 0,
                   "{} must declare at least one node; an empty graph is "
                   "vacuously reachable and would accept any world".format(
                       node_sec),
                   None if node_list else code))

    node_ids: List[str] = []
    for idx, n in enumerate(node_list):
        label = "{}[{}].".format(node_sec, idx)
        checks.extend(_required(n, node_req, code, prefix, label))
        checks.extend(_tri_field(n, "existence", code, prefix, label))
        nid = n.get(node_id_f)
        if isinstance(nid, str) and nid:
            node_ids.append(nid)
    dupes = sorted({i for i in node_ids if node_ids.count(i) > 1})
    checks.append((prefix + node_sec + "_ids_unique", not dupes,
                   "duplicate {} {}; an edge naming a duplicated id resolves "
                   "to two different nodes".format(node_id_f, dupes) if dupes
                   else "node ids unique",
                   None if not dupes else code))
    node_id_set = set(node_ids)

    edges = obj.get(edge_sec)
    edges_ok = isinstance(edges, list) and all(isinstance(e, dict)
                                               for e in edges)
    checks.append((prefix + edge_sec + "_list_of_objects", edges_ok,
                   "{} must be a list of objects".format(edge_sec),
                   None if edges_ok else code))
    edge_list = [e for e in edges if isinstance(e, dict)] \
        if isinstance(edges, list) else []

    edge_ids: List[str] = []
    for idx, e in enumerate(edge_list):
        label = "{}[{}].".format(edge_sec, idx)
        checks.extend(_required(e, edge_req, code, prefix, label))
        checks.extend(_tri_field(e, "traversable", code, prefix, label))
        for endpoint in (from_f, to_f):
            ref = e.get(endpoint)
            ok = ref in node_id_set
            checks.append((prefix + label + endpoint + "_resolves", ok,
                           "{} {!r} names no declared node; a dangling edge "
                           "silently disappears from reachability while still "
                           "reading as connectivity".format(endpoint, ref),
                           None if ok else code))
        a, b = e.get(from_f), e.get(to_f)
        ok = not (a is not None and a == b)
        checks.append((prefix + label + "endpoints_distinct", ok,
                       "{} and {} are both {!r}; an edge from a node to itself "
                       "permits no movement while reading as permission"
                       .format(from_f, to_f, a),
                       None if ok else code))
        eid = e.get(edge_id_f)
        if isinstance(eid, str) and eid:
            edge_ids.append(eid)
    dupes = sorted({i for i in edge_ids if edge_ids.count(i) > 1})
    checks.append((prefix + edge_sec + "_ids_unique", not dupes,
                   "duplicate {} {}".format(edge_id_f, dupes) if dupes
                   else "edge ids unique",
                   None if not dupes else code))

    sources = obj.get(src_f)
    src_ok = isinstance(sources, list) and len(sources) > 0
    checks.append((prefix + src_f + "_nonempty", src_ok,
                   "{} must name at least one node; with no source every node "
                   "is unreachable and the graph says nothing".format(src_f),
                   None if src_ok else code))
    if isinstance(sources, list):
        dangling = sorted(s for s in sources if s not in node_id_set)
        checks.append((prefix + src_f + "_resolve", not dangling,
                       "{} names {} which are not declared nodes".format(
                           src_f, dangling) if dangling
                       else "every source resolves",
                       None if not dangling else code))

    return checks


# --------------------------------------------------------------------------- #
# experience graph
# --------------------------------------------------------------------------- #
def validate_experience_graph(obj: Any, strict: bool = False) -> List[Check]:
    """Validate ONE experience graph: shape, ordering, and connectivity refs."""
    code = C.CORE_EXPERIENCE_GRAPH_INVALID
    checks = _validate_graph_common(obj, GRAPH_KIND_EXPERIENCE, strict)
    if not isinstance(obj, dict):
        return checks

    beats = [b for b in (obj.get("beats") or []) if isinstance(b, dict)]

    # ordinals must be integers and unique: an "ordered" set of beats with two
    # beats at the same position has no order, and every reader breaks the tie
    # differently.
    ordinals: List[Any] = []
    for idx, b in enumerate(beats):
        o = b.get("ordinal")
        ok = isinstance(o, int) and not isinstance(o, bool) and o >= 0
        checks.append((_XP + "beats[{}].ordinal_integer".format(idx), ok,
                       "ordinal must be a non-negative integer (got {!r})"
                       .format(o), None if ok else code))
        if isinstance(o, int) and not isinstance(o, bool):
            ordinals.append(o)
    dupes = sorted({o for o in ordinals if ordinals.count(o) > 1})
    checks.append((_XP + "ordinals_unique", not dupes,
                   "duplicate ordinal(s) {}; beats sharing a position make the "
                   "declared order unresolvable".format(dupes) if dupes
                   else "beat ordinals unique",
                   None if not dupes else code))

    ordinal_of = {b.get("beat_id"): b.get("ordinal") for b in beats
                  if isinstance(b.get("beat_id"), str)}

    for idx, conn in enumerate(
            [c for c in (obj.get("connections") or []) if isinstance(c, dict)]):
        kind = conn.get("connection_kind")
        ok = kind in BEAT_CONNECTION_KINDS
        checks.append((_XP + "connections[{}].kind_known".format(idx), ok,
                       "connection_kind {!r} is not one of {}".format(
                           kind, BEAT_CONNECTION_KINDS),
                       None if ok else code))
        # An order-asserting edge must respect the order it asserts.
        if kind in ORDER_ASSERTING_KINDS:
            a = ordinal_of.get(conn.get("from_beat"))
            b = ordinal_of.get(conn.get("to_beat"))
            forward = (isinstance(a, int) and isinstance(b, int)
                       and not isinstance(a, bool) and not isinstance(b, bool)
                       and a < b)
            checks.append((
                _XP + "connections[{}].sequential_is_forward".format(idx),
                forward,
                "a {} connection runs from ordinal {!r} to {!r}; it asserts "
                "forward progress and then contradicts the ordering it "
                "asserted. Use {} or {} for a backward edge".format(
                    kind, a, b, CONNECTION_OPTIONAL_DETOUR, CONNECTION_RETURN),
                None if forward else code))

    entries = obj.get("entry_beats")
    if isinstance(entries, list) and entries:
        # An entry beat must not be the target of a sequential edge: something
        # ordered before the entry means the entry is not the entry.
        seq_targets = {c.get("to_beat") for c in (obj.get("connections") or [])
                       if isinstance(c, dict)
                       and c.get("connection_kind") == CONNECTION_SEQUENTIAL}
        bad = sorted(e for e in entries if e in seq_targets)
        checks.append((_XP + "entry_beats_are_not_sequential_targets", not bad,
                       "entry beat(s) {} are the target of a sequential "
                       "connection, so something is ordered before the entry"
                       .format(bad) if bad else "entry beats have no ordered "
                       "predecessor", None if not bad else code))

    return checks


def _example_experience_graph(**over: Any) -> Dict[str, Any]:
    """Canonical-valid experience graph. Domain-neutral ids and roles."""
    d: Dict[str, Any] = {
        "graph_id": "experience_graph_0001",
        "world_id": "world_0001",
        "beats": [
            {"beat_id": "beat_entry", "ordinal": 0, "role": "entry",
             "existence": tri.SATISFIED, "anchor_ref": "anchor_entry"},
            {"beat_id": "beat_middle", "ordinal": 1, "role": "intermediate",
             "existence": tri.SATISFIED},
            {"beat_id": "beat_objective", "ordinal": 2, "role": "objective",
             "existence": tri.SATISFIED, "anchor_ref": "anchor_objective"},
        ],
        "entry_beats": ["beat_entry"],
        "connections": [
            {"connection_id": "connection_1", "from_beat": "beat_entry",
             "to_beat": "beat_middle", "connection_kind": CONNECTION_SEQUENTIAL,
             "traversable": tri.SATISFIED},
            {"connection_id": "connection_2", "from_beat": "beat_middle",
             "to_beat": "beat_objective",
             "connection_kind": CONNECTION_SEQUENTIAL,
             "traversable": tri.SATISFIED},
            {"connection_id": "connection_3", "from_beat": "beat_objective",
             "to_beat": "beat_entry", "connection_kind": CONNECTION_RETURN,
             "traversable": tri.SATISFIED},
        ],
        "created_by": "wfcore.models",
        "schema_version": RT_EXPERIENCE_GRAPH,
        "report_type": RT_EXPERIENCE_GRAPH,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# environmental-state graph
# --------------------------------------------------------------------------- #
def validate_env_state_graph(obj: Any, strict: bool = False) -> List[Check]:
    """Validate ONE environmental-state graph."""
    code = C.CORE_ENV_STATE_GRAPH_INVALID
    checks = _validate_graph_common(obj, GRAPH_KIND_ENV_STATE, strict)
    if not isinstance(obj, dict):
        return checks

    states = [s for s in (obj.get("states") or []) if isinstance(s, dict)]

    for idx, trans in enumerate(
            [t for t in (obj.get("transitions") or []) if isinstance(t, dict)]):
        trigger = trans.get("trigger")
        ok = trigger in TRANSITION_TRIGGERS
        checks.append((_EP + "transitions[{}].trigger_known".format(idx), ok,
                       "trigger {!r} is not one of {}; a transition nothing "
                       "can fire is not a permitted change".format(
                           trigger, TRANSITION_TRIGGERS),
                       None if ok else code))

    # A state axis may hold exactly one value at a time, so the world cannot
    # START in two values of the same dimension. Two initial states on one axis
    # is a contradiction that reads, in a report, as thorough initialisation.
    dimension_of = {s.get("state_id"): s.get("state_dimension") for s in states}
    initials = obj.get("initial_states")
    if isinstance(initials, list):
        seen: Dict[Any, List[str]] = {}
        for s in initials:
            dim = dimension_of.get(s)
            if dim is not None:
                seen.setdefault(dim, []).append(s)
        clashes = sorted(d for d, members in seen.items() if len(members) > 1)
        checks.append((_EP + "initial_states_one_per_dimension", not clashes,
                       "dimension(s) {} declare more than one initial state {}; "
                       "a state axis holds one value at a time, so the world "
                       "cannot begin in two of them".format(
                           clashes, {d: seen[d] for d in clashes}) if clashes
                       else "at most one initial state per dimension",
                       None if not clashes else code))

        # Every dimension that HAS states must have an initial state, or the
        # world's starting value on that axis is undefined and each reader
        # invents a different default.
        all_dims = {s.get("state_dimension") for s in states
                    if s.get("state_dimension") is not None}
        uninitialised = sorted(all_dims - set(seen))
        checks.append((_EP + "every_dimension_initialised", not uninitialised,
                       "dimension(s) {} declare states but no initial state; an "
                       "uninitialised axis has no starting value and every "
                       "reader picks a different one".format(uninitialised)
                       if uninitialised else "every dimension is initialised",
                       None if not uninitialised else code))

    return checks


def _example_env_state_graph(**over: Any) -> Dict[str, Any]:
    """Canonical-valid environmental-state graph. Domain-neutral throughout."""
    d: Dict[str, Any] = {
        "graph_id": "env_state_graph_0001",
        "world_id": "world_0001",
        "states": [
            {"state_id": "state_illumination_high", "state_dimension":
             "illumination", "state_value": "high",
             "existence": tri.SATISFIED},
            {"state_id": "state_illumination_low", "state_dimension":
             "illumination", "state_value": "low", "existence": tri.SATISFIED},
            {"state_id": "state_visibility_unobstructed", "state_dimension":
             "visibility", "state_value": "unobstructed",
             "existence": tri.SATISFIED},
            {"state_id": "state_visibility_obstructed", "state_dimension":
             "visibility", "state_value": "obstructed",
             "existence": tri.SATISFIED},
        ],
        "initial_states": ["state_illumination_high",
                           "state_visibility_unobstructed"],
        "transitions": [
            {"transition_id": "transition_1",
             "from_state": "state_illumination_high",
             "to_state": "state_illumination_low",
             "trigger": TRIGGER_ELAPSED_TIME, "traversable": tri.SATISFIED},
            {"transition_id": "transition_2",
             "from_state": "state_illumination_low",
             "to_state": "state_illumination_high",
             "trigger": TRIGGER_ELAPSED_TIME, "traversable": tri.SATISFIED},
            {"transition_id": "transition_3",
             "from_state": "state_visibility_unobstructed",
             "to_state": "state_visibility_obstructed",
             "trigger": TRIGGER_STATE_CONDITION, "traversable": tri.SATISFIED},
            {"transition_id": "transition_4",
             "from_state": "state_visibility_obstructed",
             "to_state": "state_visibility_unobstructed",
             "trigger": TRIGGER_STATE_CONDITION, "traversable": tri.SATISFIED},
        ],
        "created_by": "wfcore.models",
        "schema_version": RT_ENV_STATE_GRAPH,
        "report_type": RT_ENV_STATE_GRAPH,
    }
    d.update(over)
    return d


# --------------------------------------------------------------------------- #
# reachability rails
# --------------------------------------------------------------------------- #
def validate_graph_reachability(graph: Any, kind: str,
                                strict: bool = False) -> List[Check]:
    """Emit reachability checks WITHOUT ever calling an unknown an unreachable.

    Three groups of checks:
      * ``reach::<id>::unreachable``   -- VIOLATED only. CORE_GRAPH_UNREACHABLE_NODE.
      * ``reach::<id>::undetermined``  -- UNKNOWN only. CORE_GRAPH_REACHABILITY_NOT_DETERMINED,
        because the honest statement is "nothing evaluated this", and the
        remedy is measurement, not construction.
      * ``reach::all_nodes_reachable`` -- the folded verdict via ``tri.accepts``,
        so an UNKNOWN blocks exactly as a VIOLATED does, while the code attached
        still names which fact actually occurred.
    """
    if kind not in GRAPH_KINDS:
        raise ValueError("graph kind must be one of {} (got {!r})".format(
            GRAPH_KINDS, kind))

    verdicts = graph_reachability(graph, kind)
    unreachable = unreachable_nodes(verdicts)
    undetermined = undetermined_nodes(verdicts)
    checks: List[Check] = []

    for node_id in unreachable:
        checks.append((
            "{}{}::unreachable".format(_RP, node_id), False,
            "node {!r} is unreachable: no path exists from the declared "
            "sources even when every undetermined node and edge is admitted, "
            "so no further measurement can connect it".format(node_id),
            C.CORE_GRAPH_UNREACHABLE_NODE))

    for node_id in undetermined:
        checks.append((
            "{}{}::undetermined".format(_RP, node_id), False,
            "node {!r} has UNDETERMINED reachability: every path to it passes "
            "through a node or edge whose state was never established. This is "
            "NOT unreachability -- the remedy is to measure, not to build "
            "connectivity nobody showed was missing".format(node_id),
            C.CORE_GRAPH_REACHABILITY_NOT_DETERMINED))

    folded = reachability_verdict(verdicts)
    ok = tri.accepts(folded)
    checks.append((
        _RP + "all_nodes_reachable", ok,
        "folded reachability is {} (reachable={}, unreachable={}, "
        "undetermined={})".format(folded, len(reachable_nodes(verdicts)),
                                  unreachable, undetermined),
        None if ok else (C.CORE_GRAPH_UNREACHABLE_NODE if unreachable
                         else C.CORE_GRAPH_REACHABILITY_NOT_DETERMINED)))

    return checks
