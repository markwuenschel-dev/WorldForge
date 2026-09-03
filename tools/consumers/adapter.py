#!/usr/bin/env python3
"""consumers.adapter -- what a thin consumer adapter must expose, and must not be.

THE ONE SENTENCE
----------------
An adapter DECLARES the consumer's world; it never DECIDES how a world is made.

Everything below is machinery for making that sentence falsifiable, because as a
sentence it is worthless: every adapter ever written would claim to satisfy it,
and the one that did not would be discovered years later when a second consumer
could not reuse the capability that had quietly been shaped around the first.

WHAT AN ADAPTER MAY EXPOSE
--------------------------
    project_identity        engine + project + the subject root it authors into
    semantic_landmarks      the places that MEAN something to this game
    gameplay_anchors        what the space must let a player DO
    player_metrics          the body the consumer's character actually has
    camera_metrics          the lens it actually looks through
    approved_catalog_ids    which catalogs Core is authorised to build from
    protected_identities    what a revision must not touch
    runtime_state_access    HOW live state can be read back -- a channel, not a reader
    acceptance_hooks        WHICH evidence answers WHICH constraint

Every one of those is a FACT ABOUT THE CONSUMER. None of them is a decision about
terrain, placement, scatter, composition or repair. That asymmetry is the whole
contract: Core can consume any adapter because an adapter contains nothing Core
has to special-case.

WHY "NO GENERATION LOGIC" IS TWO CHECKS AND NOT ONE
---------------------------------------------------
A deny-list of field names (:data:`GENERATION_LOGIC_FIELDS`) catches the obvious
form -- an adapter carrying a ``placement_algorithm`` or a ``scatter_rule``. It
catches nothing at all when the logic lives in the adapter's Python instead of in
its record, which is where it would actually be written.

So the second check parses the adapter MODULE and looks at two structural facts
that no amount of naming discipline can hide:

  * what it IMPORTS. An adapter may import the contract vocabulary
    (``wfcore.contracts``, ``wfcore.constraints``, ``wfcore.tri``) because it has
    to speak it. An adapter that imports ``wfcore.planning``,
    ``wfcore.analysis``, ``wfcore.providers``, ``wfcore.transaction`` or
    ``wfcore.repair`` is reaching for the machinery that decides HOW -- and there
    is no innocent reason to hold the planner while claiming to be a declaration.
  * what it DEFINES. A function named ``generate_terrain`` or ``scatter_cover``
    is generation logic wherever it sits. ``build_``/``declare_`` prefixes are
    deliberately NOT forbidden: an adapter's whole job is to build its own
    profile, request and catalog records, and forbidding that would force every
    consumer to smuggle its declarations through a name nobody recognises.

Both checks are mechanical and both are cheap. Neither is complete -- a
sufficiently determined adapter can inline a scatter solver into a function
called ``declare_landmarks`` and this module will not notice. That residual is
stated rather than papered over: the check that actually closes it is
``core_boundary_proof.py``, which does not care what the adapter contains because
it measures the only thing that matters -- whether Core had to change.

WHY PROVENANCE IS A REQUIRED FIELD
----------------------------------
The demonstration consumers in this package were authored by WorldForge. If
WorldForge then presented their requests as though a real external game had made
them, every downstream artifact would be real evidence answering a question
nobody asked -- WF1288, and the most expensive kind of wrong, because it looks
exactly like success. So origination is a validated enum, not a comment, and
:func:`validate_run_provenance` refuses to let a run be LABELLED
caller-originated when the adapter admits it is not.
"""

import ast
from typing import Any, Dict, List, Optional, Sequence

from wfcore import constraints as K
from wfcore import tri
from wfcore.contracts import (Check, check_bool, check_enum, check_is_object,
                              check_measure, check_no_unknown,
                              check_object_field, check_required,
                              check_schema_version, check_str, check_str_list,
                              require_caller_owned)
from wfcore.contracts.acceptance_criteria import EVIDENCE_KINDS
from wfcore.contracts.consumer_profile import (CAMERA_METRIC_FIELDS,
                                               CAMERA_MODES,
                                               PLAYER_METRIC_FIELDS)
from wfcore.contracts.world_request import AFFORDANCE_KINDS, LANDMARK_ROLES
from wfcore.failure import FailureCode as C

RT_CONSUMER_ADAPTER = "wf.core.consumer_adapter.v1"
RT_ADAPTER_SOURCE_SCAN = "wf.core.adapter_source_scan.v1"

# --------------------------------------------------------------------------- #
# provenance -- who actually authored the intent this adapter carries
# --------------------------------------------------------------------------- #
# The honest admission. A consumer under this package that WorldForge wrote to
# demonstrate the platform declares this, and every run driven by it is labelled
# as a demonstration for the rest of its life.
ORIGINATION_WORLDFORGE_DEMO = "worldforge_authored_demonstration"
# A real importing game stated this intent. ONLY the external caller may claim
# it; see validate_run_provenance for the one place that is enforced.
ORIGINATION_CALLER = "caller_originated"
ORIGINATIONS = (ORIGINATION_WORLDFORGE_DEMO, ORIGINATION_CALLER)

PROVENANCE_REQUIRED = ("origination", "authored_by", "statement")

# --------------------------------------------------------------------------- #
# STRUCTURED ATTESTATION -- the part of provenance a machine can go and check.
#
# ``authored_by`` and ``statement`` are prose. They are for the human who reads
# the report, and they are the right shape for that job. What they are NOT is
# evidence: a caller that names its repository and commit inside a sentence has
# volunteered the single independently-resolvable fact in the whole record, and
# a rail that only asserts "this string is non-empty" throws it away.
#
# These two fields are OPTIONAL, and that is deliberate rather than lax. Making
# them required would invalidate every adapter written before they existed --
# including adapters in repositories WorldForge does not own and must never
# edit -- which would turn a strictly-better check into a breaking change
# imposed on a caller. Optional-but-graded is the honest construction: an
# adapter that supplies them can be checked, an adapter that does not is
# reported as UNCHECKED, and the two never render identically.
#
# What is NOT here: resolution. Deciding whether a commit really exists means
# reading a repository on disk, which is an environment fact and not a contract
# fact. Core states the shape; tools/pipeline/verify_caller_attestation.py does
# the resolving. Core stays pure and stdlib-only, and a caller cannot make its
# own claim come true by asserting it harder.
PROVENANCE_ATTESTATION_FIELDS = ("repository", "commit_sha")
PROVENANCE_ALLOWED = PROVENANCE_REQUIRED + PROVENANCE_ATTESTATION_FIELDS

# The attestation states, closed. ``ABSENT`` is not a failure and not a pass --
# it is the honest third answer, and it is why this is a three-member set and
# not a boolean.
ATTESTATION_ABSENT = "absent"          # neither field supplied; nothing to check
ATTESTATION_DECLARED = "declared"      # both supplied and well-formed, unresolved
ATTESTATION_MALFORMED = "malformed"    # supplied but not checkable as given
ATTESTATION_STATES = (ATTESTATION_ABSENT, ATTESTATION_DECLARED,
                      ATTESTATION_MALFORMED)

# A git object name: hex, and long enough to be worth resolving. Seven is git's
# own default abbreviation; sixty-four admits sha256 object format. The range is
# a SHAPE test only -- a well-formed sha that names nothing is still malformed
# in the only sense that matters, and only resolution can say so.
_SHA_MIN_LEN = 7
_SHA_MAX_LEN = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


def _is_commit_sha(value: Any) -> bool:
    """Shape-only: a hex object name of a plausible length. Never resolution."""
    if not isinstance(value, str):
        return False
    v = value.strip().lower()
    if not (_SHA_MIN_LEN <= len(v) <= _SHA_MAX_LEN):
        return False
    return all(ch in _HEX_DIGITS for ch in v)

# How live state can be read back. A CHANNEL the consumer offers, never a reader
# Core implements: "none" is a legal and common answer, and it is materially
# different from omitting the field, which would leave Core to assume a channel
# exists and report every unmeasured constraint as a defect.
RUNTIME_ACCESS_KINDS = (
    "none",
    "editor_query",
    "runtime_probe",
    "telemetry_report",
    "external_measurement",
)

PROJECT_IDENTITY_FIELDS = ("engine_version", "project_identifier", "subject_root")

LANDMARK_REQUIRED = ("landmark_id", "role", "must_be_reachable")
ANCHOR_REQUIRED = ("anchor_id", "anchor_kind", "required")
ACCEPTANCE_HOOK_REQUIRED = ("constraint_id", "evidence_kind", "hook_reference")
RUNTIME_ACCESS_REQUIRED = ("access_kind", "detail")

ADAPTER_REQUIRED = (
    "adapter_id",
    "consumer_id",
    "provenance",
    "project_identity",
    "semantic_landmarks",
    "gameplay_anchors",
    "player_metrics",
    "camera_metrics",
    "approved_catalog_ids",
    "protected_identities",
    "runtime_state_access",
    "acceptance_hooks",
    "schema_version",
)
ADAPTER_ALLOWED = ADAPTER_REQUIRED + (
    "display_name",
    "created_by",
    "created_at",
    "report_type",
    "meta",
    "notes",
)

# Every one of these names something inside the consumer's project or states the
# consumer's intent. ``provenance`` is caller-owned for the sharpest reason in
# this module: a default origination would let Core decide, on the consumer's
# behalf, who authored the ask.
CALLER_OWNED_FIELDS = (
    "adapter_id",
    "consumer_id",
    "provenance",
    "project_identity",
    "approved_catalog_ids",
    "protected_identities",
)

# --------------------------------------------------------------------------- #
# the generation-logic deny-lists
# --------------------------------------------------------------------------- #
# Record keys that ARE generation logic regardless of what they contain. An
# adapter carrying any of these has stopped describing its game and started
# describing how to build one.
GENERATION_LOGic_UNUSED = None  # (kept out of the namespace; see below)

GENERATION_LOGIC_FIELDS = (
    "placement_algorithm",
    "placement_rules",
    "scatter_rule",
    "scatter_rules",
    "terrain_algorithm",
    "heightfield_function",
    "noise_parameters",
    "generation_steps",
    "plan_steps",
    "plan_template",
    "solver",
    "solver_config",
    "composition_algorithm",
    "repair_strategy",
    "provider_selection",
    "mutation_sequence",
)

# Core subpackages an adapter may import. Contract vocabulary only.
PERMITTED_CORE_IMPORTS = (
    "wfcore.contracts",
    "wfcore.constraints",
    "wfcore.tri",
    "wfcore.failure",
)

# Core subpackages that DECIDE how a world is made. An adapter importing one of
# these is holding the machinery it claims not to contain.
FORBIDDEN_CORE_IMPORTS = (
    "wfcore.planning",
    "wfcore.analysis",
    "wfcore.providers",
    "wfcore.transaction",
    "wfcore.repair",
    "wfcore.acceptance",
    "wfcore.models",
)

# Function-name prefixes that name an act of world generation. ``build_`` and
# ``declare_`` are deliberately absent -- see the module docstring.
GENERATION_DEF_PREFIXES = (
    "generate_",
    "synthesize_",
    "synthesise_",
    "scatter_",
    "place_",
    "carve_",
    "sculpt_",
    "populate_",
    "solve_",
    "plan_",
    "author_world",
    "build_world",
    "build_terrain",
    "build_plan",
    "make_world",
    "apply_delta",
    "select_provider",
    "reconcile",
    "repair",
)

_P = "ad::"


# --------------------------------------------------------------------------- #
# shape
# --------------------------------------------------------------------------- #
def validate_adapter(obj: Any, strict: bool = False) -> List[Check]:
    """Validate the SHAPE of an adapter record. WF1286 on every failure.

    Shape only. Whether the adapter is generative is a different question with a
    different failure code, asked by :func:`validate_adapter_has_no_generation_logic`
    -- keeping them apart matters because "your record is malformed" and "your
    record is well-formed and you are not allowed to be doing this" are different
    conversations with the consumer.
    """
    code = C.CORE_ADAPTER_INVALID
    ch = check_is_object(obj, code, _P, "consumer_adapter")
    if ch:
        return ch

    ch += check_required(obj, ADAPTER_REQUIRED, code, _P)
    ch += check_no_unknown(obj, ADAPTER_ALLOWED, code, _P, strict)
    ch += check_str(obj, "adapter_id", code, _P)
    ch += check_str(obj, "consumer_id", code, _P)
    ch += check_schema_version(obj, RT_CONSUMER_ADAPTER, code, _P)

    ch += _rail_provenance(obj, code)
    ch += _rail_project_identity(obj, code)
    ch += _rail_metrics(obj, code)
    ch += _rail_landmarks(obj, code)
    ch += _rail_anchors(obj, code)
    ch += _rail_catalogs_and_protection(obj, code)
    ch += _rail_runtime_state_access(obj, code)
    ch += _rail_acceptance_hooks(obj, code)
    return ch


def _rail_provenance(obj: Dict[str, Any], code: str) -> List[Check]:
    """Origination is declared, in the closed vocabulary, and attributed."""
    out: List[Check] = []
    out += check_object_field(obj, "provenance", PROVENANCE_REQUIRED, code, _P)
    prov = obj.get("provenance")
    if not isinstance(prov, dict):
        return out

    out += check_enum(prov, "origination", ORIGINATIONS, code, _P + "provenance.")
    out += check_str(prov, "authored_by", code, _P + "provenance.")
    out += check_str(prov, "statement", code, _P + "provenance.")

    # Structured attestation. Supplying NEITHER field is legal and common, so
    # this rail never fires on absence. Supplying one of the two, or supplying
    # something no resolver could ever look up, IS a failure -- a half-written
    # attestation is worse than none, because it reads like evidence in a report
    # while being unresolvable in fact.
    state = attestation_of(obj)
    if state != ATTESTATION_ABSENT:
        got = attestation_fields(obj)
        out.append((_P + "provenance.attestation_is_resolvable_shape",
                    state == ATTESTATION_DECLARED,
                    "provenance supplies structured attestation, so BOTH {} must "
                    "be present and well-formed: repository a non-empty string "
                    "and commit_sha a {}-{} character hex object name. Got "
                    "repository={!r} commit_sha={!r} (state={}). A partial "
                    "attestation cannot be resolved by anything and must not sit "
                    "in a report looking as though it could".format(
                        list(PROVENANCE_ATTESTATION_FIELDS), _SHA_MIN_LEN,
                        _SHA_MAX_LEN, got["repository"], got["commit_sha"],
                        state),
                    None if state == ATTESTATION_DECLARED else code))

    # A demonstration consumer must SAY so in prose as well as in the enum. The
    # enum is what machines read; the statement is what a human reads in a report
    # six months from now, and a report that carries the enum alone will be
    # skimmed as though it came from a real game.
    if prov.get("origination") == ORIGINATION_WORLDFORGE_DEMO:
        statement = prov.get("statement")
        ok = (isinstance(statement, str)
              and "demonstration" in statement.lower()
              and "worldforge" in statement.lower())
        out.append((_P + "demo_statement_is_explicit", ok,
                    "origination={!r} so statement must say, in words, that "
                    "WorldForge authored this as a demonstration (got {!r}); the "
                    "enum is for machines and the sentence is for the human who "
                    "skims the report".format(ORIGINATION_WORLDFORGE_DEMO,
                                              statement),
                    None if ok else code))
    return out


def _rail_project_identity(obj: Dict[str, Any], code: str) -> List[Check]:
    out: List[Check] = []
    out += check_object_field(obj, "project_identity", PROJECT_IDENTITY_FIELDS,
                              code, _P)
    ident = obj.get("project_identity")
    if isinstance(ident, dict):
        for fld in PROJECT_IDENTITY_FIELDS:
            out += check_str(ident, fld, code, _P + "project_identity.")
    return out


def _rail_metrics(obj: Dict[str, Any], code: str) -> List[Check]:
    """Metrics are positive numbers or an honest ``unknown``. Never a zero.

    Delegates to ``contracts.check_measure`` rather than re-deriving the rule: an
    adapter that measured its metrics differently from the profile built out of
    them would produce a profile that validates and a world built for a body the
    consumer does not have.
    """
    out: List[Check] = []
    out += check_object_field(obj, "player_metrics", PLAYER_METRIC_FIELDS, code, _P)
    pm = obj.get("player_metrics")
    if isinstance(pm, dict):
        for fld in PLAYER_METRIC_FIELDS:
            out += check_measure(pm, fld, code, _P + "player_metrics.")

    out += check_object_field(obj, "camera_metrics", CAMERA_METRIC_FIELDS, code, _P)
    cm = obj.get("camera_metrics")
    if isinstance(cm, dict):
        out += check_enum(cm, "camera_mode", CAMERA_MODES, code,
                          _P + "camera_metrics.")
        for fld in ("horizontal_fov_deg", "near_clip_cm", "far_clip_cm"):
            out += check_measure(cm, fld, code, _P + "camera_metrics.")
    return out


def _rail_landmarks(obj: Dict[str, Any], code: str) -> List[Check]:
    """Landmarks are well-formed, uniquely identified, and include an entry.

    The entry rail is the same one ``world_request`` enforces, applied one step
    earlier. Reachability is measured FROM somewhere; an adapter with no entry
    landmark can only ever produce requests whose reachability constraints fold
    UNKNOWN forever, and it would look complete the entire time.
    """
    out: List[Check] = []
    landmarks = obj.get("semantic_landmarks")
    if not isinstance(landmarks, (list, tuple)):
        return [(_P + "semantic_landmarks_is_list", False,
                 "semantic_landmarks must be a list, got {}".format(
                     type(landmarks).__name__), code)]

    for idx, lm in enumerate(landmarks):
        p = "{}landmark[{}].".format(_P, idx)
        if not isinstance(lm, dict):
            out.append((p + "is_object", False,
                        "landmark must be an object, got {}".format(
                            type(lm).__name__), code))
            continue
        out += check_required(lm, LANDMARK_REQUIRED, code, p)
        out += check_str(lm, "landmark_id", code, p)
        out += check_enum(lm, "role", LANDMARK_ROLES, code, p)
        out += check_bool(lm, "must_be_reachable", code, p)

    ids = [lm.get("landmark_id") for lm in landmarks if isinstance(lm, dict)]
    dupes = sorted({i for i in ids if i is not None and ids.count(i) > 1})
    ok = not dupes
    out.append((_P + "landmark_ids_unique", ok,
                "duplicate landmark_id(s) {}".format(dupes) if dupes
                else "all landmark_ids unique", None if ok else code))

    entries = [lm for lm in landmarks
               if isinstance(lm, dict) and lm.get("role") == "entry"]
    ok = len(entries) > 0
    out.append((_P + "adapter_declares_an_entry_landmark", ok,
                "{} landmark(s) with role 'entry'; reachability is measured FROM "
                "somewhere, so an adapter with no entry can only author requests "
                "whose reachability constraints fold UNKNOWN forever".format(
                    len(entries)), None if ok else code))
    return out


def _rail_anchors(obj: Dict[str, Any], code: str) -> List[Check]:
    out: List[Check] = []
    anchors = obj.get("gameplay_anchors")
    if not isinstance(anchors, (list, tuple)):
        return [(_P + "gameplay_anchors_is_list", False,
                 "gameplay_anchors must be a list, got {}".format(
                     type(anchors).__name__), code)]

    for idx, an in enumerate(anchors):
        p = "{}anchor[{}].".format(_P, idx)
        if not isinstance(an, dict):
            out.append((p + "is_object", False,
                        "anchor must be an object, got {}".format(
                            type(an).__name__), code))
            continue
        out += check_required(an, ANCHOR_REQUIRED, code, p)
        out += check_str(an, "anchor_id", code, p)
        out += check_enum(an, "anchor_kind", AFFORDANCE_KINDS, code, p)
        out += check_bool(an, "required", code, p)

    ids = [an.get("anchor_id") for an in anchors if isinstance(an, dict)]
    dupes = sorted({i for i in ids if i is not None and ids.count(i) > 1})
    ok = not dupes
    out.append((_P + "anchor_ids_unique", ok,
                "duplicate anchor_id(s) {}".format(dupes) if dupes
                else "all anchor_ids unique", None if ok else code))
    return out


def _rail_catalogs_and_protection(obj: Dict[str, Any], code: str) -> List[Check]:
    out: List[Check] = []
    out += check_str_list(obj, "approved_catalog_ids", code, _P, min_len=1)
    out += check_str_list(obj, "protected_identities", code, _P, min_len=0)
    return out


def _rail_runtime_state_access(obj: Dict[str, Any], code: str) -> List[Check]:
    """The channel is declared, including the honest "there isn't one"."""
    out: List[Check] = []
    out += check_object_field(obj, "runtime_state_access", RUNTIME_ACCESS_REQUIRED,
                              code, _P)
    rsa = obj.get("runtime_state_access")
    if not isinstance(rsa, dict):
        return out
    out += check_enum(rsa, "access_kind", RUNTIME_ACCESS_KINDS, code,
                      _P + "runtime_state_access.")
    out += check_str(rsa, "detail", code, _P + "runtime_state_access.")
    return out


def _rail_acceptance_hooks(obj: Dict[str, Any], code: str) -> List[Check]:
    """Hooks name WHICH evidence answers WHICH constraint -- and nothing more.

    A hook is a REFERENCE (a probe name, a report key, a reviewer). It is
    deliberately not a callable: an adapter that shipped a function here would be
    supplying the evaluator as well as the question, and Core would be grading a
    world against a measurement the consumer wrote and Core never saw.
    """
    out: List[Check] = []
    hooks = obj.get("acceptance_hooks")
    if not isinstance(hooks, (list, tuple)):
        return [(_P + "acceptance_hooks_is_list", False,
                 "acceptance_hooks must be a list (use [] to state that this "
                 "adapter offers none), got {}".format(type(hooks).__name__),
                 code)]

    for idx, hk in enumerate(hooks):
        p = "{}hook[{}].".format(_P, idx)
        if not isinstance(hk, dict):
            out.append((p + "is_object", False,
                        "acceptance hook must be an object, got {}".format(
                            type(hk).__name__), code))
            continue
        out += check_required(hk, ACCEPTANCE_HOOK_REQUIRED, code, p)
        out += check_str(hk, "constraint_id", code, p)
        out += check_enum(hk, "evidence_kind", EVIDENCE_KINDS, code, p)
        out += check_str(hk, "hook_reference", code, p)

    callables = sorted(
        str(hk.get("constraint_id")) for hk in hooks
        if isinstance(hk, dict) and callable(hk.get("hook_reference")))
    ok = not callables
    out.append((_P + "hook_reference_is_a_reference_not_an_evaluator", ok,
                "hook(s) {} carry a CALLABLE hook_reference; a hook names the "
                "evidence that answers a constraint, and an adapter that ships "
                "the evaluator too would have Core grade a world against a "
                "measurement it never saw".format(callables) if callables
                else "every hook_reference is a reference, not an evaluator",
                None if ok else code))
    return out


# --------------------------------------------------------------------------- #
# the generation-logic gate (WF1287)
# --------------------------------------------------------------------------- #
def scan_source_for_generation_logic(source_text: str,
                                     module_name: str = "<adapter>"
                                     ) -> Dict[str, Any]:
    """Parse an adapter module and report the generative constructs in it.

    AST, not regex. A regex over source cannot tell ``import wfcore.planning``
    from the word "planning" in a docstring, and a gate that fires on prose is a
    gate that gets suppressed. Unparseable source is itself a finding: an adapter
    nobody can parse is an adapter nobody can check.
    """
    report: Dict[str, Any] = {
        "report_type": RT_ADAPTER_SOURCE_SCAN,
        "module": module_name,
        "parsed": False,
        "forbidden_imports": [],
        "generative_definitions": [],
        "parse_error": None,
    }
    try:
        tree = ast.parse(source_text or "", filename=module_name)
    except SyntaxError as exc:
        report["parse_error"] = "{}: {}".format(type(exc).__name__, exc)
        return report
    report["parsed"] = True

    def _record_import(dotted: Optional[str], lineno: int) -> None:
        if not dotted:
            return
        for forbidden in FORBIDDEN_CORE_IMPORTS:
            # Prefix match on a dotted boundary so ``wfcore.planning.plan`` is
            # caught and a hypothetical ``wfcore.planningsomething`` is not.
            if dotted == forbidden or dotted.startswith(forbidden + "."):
                report["forbidden_imports"].append(
                    {"module": dotted, "line": lineno})

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _record_import(alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            # ``from wfcore.planning import plan`` -> node.module is the package.
            # Relative imports (level > 0) carry no absolute module name and are
            # not resolvable here; they are reported as unresolved rather than
            # assumed innocent.
            if node.level == 0:
                _record_import(node.module, node.lineno)
            for alias in node.names:
                if node.level == 0 and node.module:
                    _record_import(
                        "{}.{}".format(node.module, alias.name), node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            bare = name.lstrip("_")
            for prefix in GENERATION_DEF_PREFIXES:
                if bare == prefix or bare.startswith(prefix):
                    report["generative_definitions"].append(
                        {"name": name, "line": node.lineno, "matched": prefix})
                    break

    report["forbidden_imports"].sort(key=lambda d: (d["line"], d["module"]))
    report["generative_definitions"].sort(key=lambda d: (d["line"], d["name"]))
    return report


def validate_adapter_has_no_generation_logic(
        adapter: Any,
        source_text: Optional[str] = None,
        module_name: str = "<adapter>") -> List[Check]:
    """Reject an adapter that carries world-generation logic. WF1287.

    ``source_text=None`` means the source was not supplied. That is reported as
    NOT CHECKED rather than as a pass: a gate that reports "clean" over source it
    never read is the exact fake-green this repository is built against, and it
    would read identically to a real result in every report that quotes it.
    """
    code = C.CORE_ADAPTER_CONTAINS_GENERATION_LOGIC
    out: List[Check] = []

    # --- layer 1: the record --------------------------------------------------
    if isinstance(adapter, dict):
        present = sorted(f for f in GENERATION_LOGIC_FIELDS if f in adapter)
        ok = not present
        out.append((_P + "record_carries_no_generation_logic", ok,
                    "adapter record carries generation-logic field(s) {}; an "
                    "adapter states what the consumer's world IS, and the moment "
                    "it states how one is MADE that capability stops being "
                    "generic and the next consumer cannot reuse it".format(present)
                    if present else "adapter record carries no generation-logic "
                                    "field", None if ok else code))
    else:
        out.append((_P + "record_carries_no_generation_logic", False,
                    "adapter must be an object to be checked, got {}".format(
                        type(adapter).__name__), C.CORE_ADAPTER_INVALID))

    # --- layer 2: the module --------------------------------------------------
    if source_text is None:
        out.append((_P + "source_scanned", False,
                    "no adapter source was supplied, so the module was NOT "
                    "checked for generative imports or definitions. This is not "
                    "a pass: an unscanned adapter and a clean one are "
                    "indistinguishable in every report that quotes this check",
                    code))
        return out

    scan = scan_source_for_generation_logic(source_text, module_name)

    ok = bool(scan["parsed"])
    out.append((_P + "source_parses", ok,
                "adapter source parsed" if ok
                else "adapter source at {} could not be parsed ({}); an adapter "
                     "nobody can parse is an adapter nobody can check".format(
                         module_name, scan["parse_error"]),
                None if ok else code))
    if not ok:
        return out

    bad_imports = scan["forbidden_imports"]
    ok = not bad_imports
    out.append((_P + "imports_no_generation_machinery", ok,
                "adapter imports {}; those subpackages DECIDE how a world is "
                "made, and there is no innocent reason for a declaration to hold "
                "the planner. Permitted Core imports are {}".format(
                    ["{}:{}".format(d["module"], d["line"]) for d in bad_imports],
                    list(PERMITTED_CORE_IMPORTS)) if bad_imports
                else "adapter imports no generation machinery",
                None if ok else code))

    bad_defs = scan["generative_definitions"]
    ok = not bad_defs
    out.append((_P + "defines_no_generation_functions", ok,
                "adapter defines {}; a function that generates, places, scatters "
                "or plans is generation logic wherever it sits".format(
                    ["{}():{} (matched {!r})".format(d["name"], d["line"],
                                                     d["matched"])
                     for d in bad_defs]) if bad_defs
                else "adapter defines no generation functions",
                None if ok else code))
    return out


# --------------------------------------------------------------------------- #
# provenance (WF1288)
# --------------------------------------------------------------------------- #
def origination_of(adapter: Dict[str, Any]) -> Optional[str]:
    prov = adapter.get("provenance") if isinstance(adapter, dict) else None
    return prov.get("origination") if isinstance(prov, dict) else None


def is_caller_originated(adapter: Dict[str, Any]) -> bool:
    """True ONLY when the adapter declares a real external caller authored it.

    Absence is not caller-originated. An adapter with no provenance has not
    established that anybody outside WorldForge asked for anything, and defaulting
    that to "yes" is precisely WF1288.
    """
    return origination_of(adapter) == ORIGINATION_CALLER


def caller_provenance_verdict(adapter: Dict[str, Any]) -> str:
    """Tri-verdict for "did a real external caller originate this intent?".

    SATISFIED for a declared external caller, VIOLATED for a declared WorldForge
    demonstration, UNKNOWN when nothing was declared at all -- because then
    nothing has been stated in either direction and Core answering on the
    consumer's behalf is the failure this module exists to prevent.
    """
    origination = origination_of(adapter)
    if origination is None:
        return tri.UNKNOWN
    return tri.from_bool(origination == ORIGINATION_CALLER, measured=True)


def attestation_fields(adapter: Dict[str, Any]) -> Dict[str, Any]:
    """The structured attestation as supplied, with missing fields as ``None``.

    Returns what the adapter SAID, never a normalised or repaired version of it:
    a caller that wrote a sha with trailing whitespace should see that fact in
    the record rather than have Core quietly tidy it into something checkable.
    """
    prov = adapter.get("provenance") if isinstance(adapter, dict) else None
    if not isinstance(prov, dict):
        return {f: None for f in PROVENANCE_ATTESTATION_FIELDS}
    return {f: prov.get(f) for f in PROVENANCE_ATTESTATION_FIELDS}


def attestation_of(adapter: Dict[str, Any]) -> str:
    """Which of the three attestation states this adapter is in.

    Deliberately NOT a verdict about the caller. An adapter can be honestly
    caller-originated and carry no structured attestation at all -- that is
    ``ABSENT``, and it means "nobody has checked", which is a different sentence
    from "this was checked and it held". Collapsing those two is the whole class
    of defect this function exists to keep visible.
    """
    got = attestation_fields(adapter)
    supplied = [f for f, v in got.items() if v is not None]
    if not supplied:
        return ATTESTATION_ABSENT
    if len(supplied) != len(PROVENANCE_ATTESTATION_FIELDS):
        return ATTESTATION_MALFORMED
    repo = got["repository"]
    if not (isinstance(repo, str) and repo.strip()):
        return ATTESTATION_MALFORMED
    if not _is_commit_sha(got["commit_sha"]):
        return ATTESTATION_MALFORMED
    return ATTESTATION_DECLARED


def validate_run_provenance(adapter: Dict[str, Any],
                            claimed_origination: str) -> List[Check]:
    """Refuse a run LABELLED caller-originated when the adapter says otherwise.

    This is the check that makes the honesty requirement structural. A flow
    runner calls it before it writes its report, so the label on the report is
    the adapter's own admission rather than the runner's choice -- and a runner
    that wanted to lie would have to edit the consumer, where the lie is a diff
    somebody reviews rather than a default nobody sees.
    """
    code = C.CORE_CALLER_PROVENANCE_FABRICATED
    out: List[Check] = []

    ok = claimed_origination in ORIGINATIONS
    out.append((_P + "claimed_origination_in_vocabulary", ok,
                "claimed origination {!r} must be one of {}".format(
                    claimed_origination, ORIGINATIONS),
                None if ok else code))
    if not ok:
        return out

    declared = origination_of(adapter)
    ok = declared == claimed_origination
    out.append((_P + "run_label_matches_adapter_provenance", ok,
                "this run is labelled {!r} while the adapter declares {!r}. "
                "WorldForge must never present a request as originating from a "
                "real external game when it authored that request itself: the "
                "evidence produced would be genuine and would answer a question "
                "nobody asked".format(claimed_origination, declared),
                None if ok else code))

    # The asymmetric rail. Under-claiming (a real caller's run labelled a
    # demonstration) is merely wrong; over-claiming is the failure with a code.
    over_claimed = (claimed_origination == ORIGINATION_CALLER
                    and declared != ORIGINATION_CALLER)
    out.append((_P + "no_upgrade_to_caller_originated", not over_claimed,
                "a run may never be UPGRADED to {!r}; only the external caller "
                "can state that, and this adapter declares {!r}".format(
                    ORIGINATION_CALLER, declared) if over_claimed
                else "this run does not claim more provenance than the adapter "
                     "declares", code if over_claimed else None))
    return out


# --------------------------------------------------------------------------- #
# construction
# --------------------------------------------------------------------------- #
def build_adapter(**over: Any) -> Dict[str, Any]:
    """Build an adapter record. ``CALLER_OWNED_FIELDS`` are REQUIRED -- no defaults.

    The defaults cover only Core's own schema identity and the empty-but-stated
    shape of the declaration lists. Nothing here invents an identity, a catalog,
    a protection set, or -- above all -- a provenance.
    """
    require_caller_owned(over, CALLER_OWNED_FIELDS, "consumer_adapter")
    d: Dict[str, Any] = dict(
        semantic_landmarks=[],
        gameplay_anchors=[],
        acceptance_hooks=[],
        runtime_state_access={
            "access_kind": "none",
            "detail": "this adapter offers no runtime state channel",
        },
        schema_version=RT_CONSUMER_ADAPTER,
        report_type=RT_CONSUMER_ADAPTER,
    )
    d.update(over)
    return d


def demo_provenance(authored_by: str, what: str) -> Dict[str, Any]:
    """The provenance block every WorldForge-authored demonstration must carry.

    A helper rather than a convention, so the admission is spelled identically by
    every demonstration consumer and cannot be quietly softened in one of them.
    """
    return {
        "origination": ORIGINATION_WORLDFORGE_DEMO,
        "authored_by": authored_by,
        "statement": (
            "This consumer is a WorldForge-authored DEMONSTRATION, not a real "
            "importing game. WorldForge wrote {} itself to exercise the Core "
            "flow and to prove that a substantially different consumer needs no "
            "change to Core. No external caller asked for any of it, and no run "
            "driven by this adapter may be labelled caller-originated."
        ).format(what),
    }


def adapter_summary(adapter: Dict[str, Any]) -> Dict[str, Any]:
    """A compact, report-safe digest. States provenance FIRST, deliberately."""
    prov = adapter.get("provenance") or {}
    return {
        "adapter_id": adapter.get("adapter_id"),
        "consumer_id": adapter.get("consumer_id"),
        "origination": prov.get("origination"),
        "authored_by": prov.get("authored_by"),
        "provenance_statement": prov.get("statement"),
        "caller_originated": is_caller_originated(adapter),
        "caller_provenance_verdict": caller_provenance_verdict(adapter),
        "landmark_count": len(adapter.get("semantic_landmarks") or []),
        "anchor_count": len(adapter.get("gameplay_anchors") or []),
        "approved_catalog_ids": list(adapter.get("approved_catalog_ids") or []),
        "protected_identities": list(adapter.get("protected_identities") or []),
        "runtime_access_kind": (
            (adapter.get("runtime_state_access") or {}).get("access_kind")),
        "acceptance_hook_count": len(adapter.get("acceptance_hooks") or []),
    }


def failing(checks: Sequence[Check]) -> List[Check]:
    """The failing subset, for callers that only need to know what broke."""
    return [c for c in checks if not c[1]]


def _example_adapter(**over: Any) -> Dict[str, Any]:
    """Canonical-valid adapter. ``**over`` spawns the known-bads.

    Every value naming a consumer is a neutral placeholder: this fixture lives in
    the contract module, and a plausible-looking name here would be the first
    place a real consumer's identity leaked into shared code.
    """
    d: Dict[str, Any] = dict(
        adapter_id="adapter_placeholder",
        consumer_id="consumer_placeholder",
        provenance=demo_provenance("WorldForge", "this placeholder fixture"),
        project_identity={
            "engine_version": "0.0.0",
            "project_identifier": "project_placeholder",
            "subject_root": "consumer://subject/placeholder",
        },
        semantic_landmarks=[
            {
                "landmark_id": "landmark_entry_placeholder",
                "role": "entry",
                "must_be_reachable": True,
            },
        ],
        gameplay_anchors=[
            {
                "anchor_id": "anchor_traversal_placeholder",
                "anchor_kind": "traversal",
                "required": True,
            },
        ],
        player_metrics={
            "capsule_height_cm": 180.0,
            "capsule_radius_cm": 42.0,
            "eye_height_cm": 165.0,
            "max_step_height_cm": 45.0,
            "max_walk_slope_deg": 44.0,
            "max_jump_height_cm": 120.0,
        },
        camera_metrics={
            "camera_mode": "third_person_close",
            "horizontal_fov_deg": 90.0,
            "near_clip_cm": 10.0,
            "far_clip_cm": 200000.0,
        },
        approved_catalog_ids=["catalog_placeholder"],
        protected_identities=[],
        runtime_state_access={
            "access_kind": "none",
            "detail": "placeholder adapter offers no runtime channel",
        },
        acceptance_hooks=[
            {
                "constraint_id": "c_placeholder",
                "evidence_kind": "static_analysis",
                "hook_reference": "placeholder_probe",
            },
        ],
    )
    d.update(over)
    return build_adapter(**d)


# ``K`` is imported for the constraint vocabulary consumers build against; it is
# referenced here so the import is not mistaken for an unused one and removed.
_CONSTRAINT_VOCABULARY = K.CONSTRAINT_CLASSES
