#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""WorldForge v2.6 — deterministic export of the caller-facing scene-survey contracts.

The Python contract spine (`scene_survey_contracts.py`) and the request dataclass
(`bridge.schema.BridgeRequest`) are the source of truth. A caller in another
repository must not have to reverse-engineer Python dicts to author a request, so
this exporter emits JSON Schema + example artifacts FROM those definitions.

Anti-drift design (the point of this file):

  * Every STRUCTURAL fact is read from the live module — the field lists come from
    `SUBJECT_REQUIRED` / `REPORT_REQUIRED` / `*_ALLOWED` / `_*_NULLABLE`, the enums
    from `ANCHOR_MODES` / `CAMERA_KINDS` / `RUNTIME_MODES` / `SURVEY_STATUS` /
    `SUBJECT_KINDS` / `SUBJECT_RESOLVERS`, the schema_version consts from `RT_*`,
    the request fields from `dataclasses.fields(BridgeRequest)`, and the tolerance
    from the live signature default of `validate_subject_binding`. Nothing here is
    a hand-copied list, so a field added upstream cannot be silently missed.

  * The one thing JSON Schema cannot introspect is a field's TYPE, because the
    types live inside hand-written rail functions. Those are declared in
    `_SUBJECT_FIELDS` / `_REPORT_FIELDS` below and then PROVEN: `--check` runs a
    mutation battery through both the JSON Schema and the real Python validator
    and fails if they ever disagree in the direction that matters.

  * Byte-stability: sort_keys, indent=2, trailing newline, and newline="\\n". The
    repo is checked out with `*.json text eol=lf` (.gitattributes), so writing
    with Python's default translation would emit CRLF and make `--check` report
    drift on Windows that git does not see. This is the trap; newline="\\n" is
    the fix.

  * Deliberately NOT stamped with the WorldForge commit. A committed artifact that
    embeds HEAD would need regenerating on every unrelated commit, which turns the
    drift gate into noise. Identity is carried by `contract_surface_sha256`, which
    changes exactly when the contract surface changes. The commit belongs in the
    RUNTIME evidence (which is per-run), not in a versioned spec artifact.

What the exported schema can and cannot say is recorded honestly in each file's
`x-worldforge-rails` block: cross-field arithmetic (`support_samples_valid <=
support_samples_total`) and cross-DOCUMENT binding (request <-> report) are not
expressible in JSON Schema. A caller that validates only against the schema has
NOT satisfied the contract; the runtime rails still apply.

Acceptance:
    PYTHONUTF8=1 python tools/pipeline/export_scene_survey_contracts.py
    PYTHONUTF8=1 python tools/pipeline/export_scene_survey_contracts.py --check
Reports -> specs/scene_survey/scene_survey_contract_manifest.json
"""

import argparse
import hashlib
import inspect
import json
import sys
from dataclasses import MISSING, fields as dataclass_fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import scene_survey_contracts as SS  # noqa: E402
from bridge.schema import BridgeRequest  # noqa: E402
from bridge import capability_ops as OPS  # noqa: E402

SPEC_DIR = REPO_ROOT / "specs" / "scene_survey"
EXAMPLE_DIR = REPO_ROOT / "examples" / "scene_survey"

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_BASE = "https://worldforge.local/specs/scene_survey/"

GENERATOR = "tools/pipeline/export_scene_survey_contracts.py"

# The caller-facing example vocabulary is deliberately neutral. WorldForge owns
# capability, the caller owns intent, so no target-game proper noun may appear in
# a WorldForge artifact (scene_survey_hygiene.py enforces this on the surface).
EXAMPLE_REPO = "TargetGameRepo"
EXAMPLE_PROJECT = "TargetGameProject"
EXAMPLE_MAP = "/Game/Maps/ExampleSurveyLevel"
EXAMPLE_COMMIT = "0" * 40


# --------------------------------------------------------------------------- #
# JSON Schema fragment builders — the parity-critical encodings.
# --------------------------------------------------------------------------- #
# Parity notes, each mirroring a rail in runtime_schema.py / scene_survey_contracts.py:
#   _str  -> check_type(str) + bool(v.strip()); "\\S" == "has a non-whitespace char".
#   _int  -> is_number and float(v).is_integer(); accepts 3.0, rejects 3.5 and bools.
#            {"type":"integer"} would REJECT 3.0, so it is wrong here; number+
#            multipleOf:1 is the faithful encoding.
#   is_number excludes bool, and JSON Schema "number" excludes true/false, so the
#            bool-is-not-a-number rail carries over for free.
def _s_str():
    return {"type": "string", "pattern": "\\S"}


def _s_str_any():
    return {"type": "string"}


def _s_bool():
    return {"type": "boolean"}


def _s_int_ge0():
    return {"type": "number", "multipleOf": 1, "minimum": 0}


def _s_vec3():
    return {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}


def _s_nullable(frag):
    return {"anyOf": [frag, {"type": "null"}]}


def _s_enum(values):
    return {"enum": list(values)}


def _s_const(value):
    return {"const": value}


def _s_array_of(frag):
    return {"type": "array", "items": frag}


def _s_meta_open():
    return {}


# --------------------------------------------------------------------------- #
# Declared field types — the only hand-written part, and the part `--check` proves.
# --------------------------------------------------------------------------- #
def _subject_fields():
    return {
        "subject_id": _s_str(),
        "subject_kind": _s_enum(SS.SUBJECT_KINDS),
        "map_asset_path": _s_str(),
        "anchor_mode": _s_enum(SS.ANCHOR_MODES),
        "anchor_location": _s_nullable(_s_vec3()),
        "anchor_rotation": _s_nullable(_s_vec3()),
        "anchor_object_path": _s_nullable(_s_str_any()),
        "resolved_by": _s_enum(SS.SUBJECT_RESOLVERS),
        "schema_version": _s_const(SS.RT_SUBJECT),
    }


def _report_fields():
    known_codes = sorted(SS._all_wf_codes())
    return {
        "report_id": _s_str(),
        "operation_id": _s_str(),
        "map_asset_path": _s_str(),
        "subject_id": _s_str(),
        "observed_anchor_location": _s_nullable(_s_vec3()),
        "observed_anchor_object_path": _s_nullable(_s_str_any()),
        # NB: the report rail is a hard equality against "caller" (sr::
        # subject_resolved_by_caller), not a check_enum, so const is exact.
        "subject_resolved_by": _s_const("caller"),
        "captures_requested": _s_array_of(_s_enum(SS.CAMERA_KINDS)),
        "camera_capture_ok": _s_bool(),
        "actor_bounds_valid": _s_bool(),
        "support_samples_total": _s_int_ge0(),
        # Nullable: nothing in the current pass observes these, and a fabricated 0 /
        # False would be a populated field with no observation chain. Null means
        # unknown; sr::unobserved_forbids_pass makes unknown incompatible with a
        # pass. Drop the nullable wrapper the moment a real channel exists.
        "support_samples_valid": _s_nullable(_s_int_ge0()),
        "unsupported_regions": _s_nullable(_s_int_ge0()),
        "edge_regions": _s_nullable(_s_int_ge0()),
        "proxy_owners": _s_nullable(_s_int_ge0()),
        "proxies_disabled": _s_nullable(_s_bool()),
        "temporary_placements_grounded": _s_int_ge0(),
        "overlap_count": _s_int_ge0(),
        "player_clearance_valid": _s_bool(),
        "cleanup_verified": _s_bool(),
        "determinism_hash": _s_str(),
        "runtime_mode": _s_enum(SS.RUNTIME_MODES),
        "runtime_executed": _s_bool(),
        "evidence_paths": _s_array_of(_s_str_any()),
        "failure_codes": _s_array_of(_s_enum(known_codes)),
        "status": _s_enum(SS.SURVEY_STATUS),
        # Acceptance eligibility. The reason MUST be nullable-encoded: a plain enum
        # would reject the null an eligible report carries, and the false-rejection
        # rail would fire on the module's own valid example.
        "acceptance_eligible": _s_bool(),
        "acceptance_ineligibility_reason": _s_nullable(
            _s_enum(SS.ACCEPTANCE_INELIGIBILITY_REASONS)),
        "schema_version": _s_const(SS.RT_SURVEY_REPORT),
    }


# --------------------------------------------------------------------------- #
# Structural drift guard — declared fields must equal the live tuples, exactly.
# --------------------------------------------------------------------------- #
def _structural_drift(label, declared, required, allowed, nullable):
    """Return a list of drift problems between the declared table and the module."""
    problems = []
    declared_keys = set(declared)
    req = set(required)
    allow = set(allowed)
    meta = set(SS._META_FIELDS)

    missing = sorted(req - declared_keys)
    if missing:
        problems.append(
            "{}: field(s) {} are in {}_REQUIRED but have no declared JSON type — "
            "the upstream contract grew and this exporter did not".format(
                label, missing, label.upper()))

    extra = sorted(declared_keys - req)
    if extra:
        problems.append(
            "{}: declared JSON type(s) for {} which are NOT in {}_REQUIRED — "
            "the exporter is describing a field the validator no longer has".format(
                label, extra, label.upper()))

    if allow != req | meta:
        problems.append(
            "{}: {}_ALLOWED is not exactly {}_REQUIRED + _META_FIELDS (unexpected "
            "extra optional key(s) {}) — the exporter's additionalProperties:false "
            "surface would be wrong".format(
                label, label.upper(), label.upper(), sorted(allow - (req | meta))))

    unknown_nullable = sorted(set(nullable) - req)
    if unknown_nullable:
        problems.append(
            "{}: nullable tuple names {} which are not required fields".format(
                label, unknown_nullable))

    # Every nullable field must be encoded as accepting null, and no non-nullable
    # field may accept null. This is the rail that keeps required-vs-nullable honest.
    for name, frag in sorted(declared.items()):
        accepts_null = _accepts_null(frag)
        should = name in set(nullable)
        if accepts_null and not should:
            problems.append(
                "{}::{}: declared type accepts null but the field is not in the "
                "nullable tuple".format(label, name))
        if should and not accepts_null:
            problems.append(
                "{}::{}: field is nullable upstream but the declared type refuses "
                "null".format(label, name))
    return problems


def _accepts_null(frag):
    if frag.get("type") == "null":
        return True
    for branch in frag.get("anyOf", []) + frag.get("oneOf", []):
        if _accepts_null(branch):
            return True
    return False


# --------------------------------------------------------------------------- #
# Schema assembly.
# --------------------------------------------------------------------------- #
def _properties(declared):
    props = dict(declared)
    for m in SS._META_FIELDS:
        props[m] = _s_meta_open()
    return props


def _tolerance_cm():
    """Read the live default rather than copying the number."""
    sig = inspect.signature(SS.validate_subject_binding)
    return sig.parameters["tolerance_cm"].default


def build_subject_schema():
    declared = _subject_fields()
    vec3 = _s_vec3()
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": SCHEMA_BASE + "scene_survey_subject.schema.json",
        "title": "SceneSurveySubject",
        "description": (
            "The caller-resolved subject of a scene survey. WorldForge never "
            "produces one of these; it receives one and verifies it. Every field "
            "is caller-owned."),
        "x-worldforge-contract-version": SS.CONTRACT_VERSION,
        "x-worldforge-schema-version": SS.RT_SUBJECT,
        "type": "object",
        "additionalProperties": False,
        "required": sorted(SS.SUBJECT_REQUIRED),
        "properties": _properties(declared),
        # Rails R1/R2/R3: mode-keyed completeness AND exclusivity in one shape.
        # explicit_transform => vec3 location and a null object path.
        # actor_object_path  => non-blank object path and a null location.
        "oneOf": [
            {
                "title": "explicit_transform",
                "properties": {
                    "anchor_mode": {"const": "explicit_transform"},
                    "anchor_location": vec3,
                    "anchor_object_path": {"type": "null"},
                },
                "required": ["anchor_mode", "anchor_location", "anchor_object_path"],
            },
            {
                "title": "actor_object_path",
                "properties": {
                    "anchor_mode": {"const": "actor_object_path"},
                    "anchor_object_path": _s_str(),
                    "anchor_location": {"type": "null"},
                },
                "required": ["anchor_mode", "anchor_object_path", "anchor_location"],
            },
        ],
        "x-worldforge-rails": [
            {
                "rail": "ss::mode_exclusive",
                "code": "WF1106_SCENE_SURVEY_SUBJECT_UNRESOLVED",
                "detail": ("exactly one of anchor_location / anchor_object_path may "
                           "carry a value; zero means the caller never resolved the "
                           "subject, two means WorldForge would have to choose. "
                           "Encoded above as oneOf."),
                "expressible_in_json_schema": True,
            },
            {
                "rail": "ss::resolved_by_caller",
                "code": "WF1108_SCENE_SURVEY_SUBJECT_INFERRED",
                "detail": ("resolved_by must be 'caller'. WorldForge refuses to run a "
                           "survey whose subject it resolved itself."),
                "expressible_in_json_schema": True,
            },
            {
                "rail": "anchor_rotation",
                "code": None,
                "detail": ("anchor_rotation is [pitch, yaw, roll] or null and is NOT "
                           "part of the exclusivity rail; it may be present or null in "
                           "either mode. It is never compared during binding."),
                "expressible_in_json_schema": True,
            },
        ],
    }


def build_report_schema():
    declared = _report_fields()
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": SCHEMA_BASE + "scene_survey_report.schema.json",
        "title": "SceneSurveyReport",
        "description": (
            "The machine-readable result of a scene survey. Necessary but not "
            "sufficient: see x-worldforge-rails for the constraints JSON Schema "
            "cannot express."),
        "x-worldforge-contract-version": SS.CONTRACT_VERSION,
        "x-worldforge-schema-version": SS.RT_SURVEY_REPORT,
        "type": "object",
        "additionalProperties": False,
        "required": sorted(SS.REPORT_REQUIRED),
        "properties": _properties(declared),
        "allOf": [
            {
                # Rail sr::observed_anchor_present — an executed run must carry a
                # real observed anchor, in EITHER anchor mode.
                "if": {
                    "properties": {"runtime_executed": {"const": True}},
                    "required": ["runtime_executed"],
                },
                "then": {
                    "properties": {"observed_anchor_location": _s_vec3()},
                    "required": ["observed_anchor_location"],
                },
            },
            {
                # Rail sr::live_mode_executed — a live-mode claim needs execution
                # and at least one evidence path.
                "if": {
                    "properties": {
                        "runtime_mode": {"enum": list(SS.LIVE_RUNTIME_MODES)}},
                    "required": ["runtime_mode"],
                },
                "then": {
                    "properties": {
                        "runtime_executed": {"const": True},
                        "evidence_paths": {"type": "array", "minItems": 1},
                    },
                    "required": ["runtime_executed", "evidence_paths"],
                },
            },
        ],
        "x-worldforge-rails": [
            {
                "rail": "sr::valid_le_total",
                "code": "WF1062_SCENE_SURVEY_REPORT_INVALID",
                "detail": ("support_samples_valid <= support_samples_total. Comparing "
                           "two sibling fields is not expressible in JSON Schema; the "
                           "runtime rail still applies."),
                "expressible_in_json_schema": False,
            },
            {
                "rail": "sr::clean_requires_evidence",
                "code": "WF1097_SCENE_SURVEY_EVIDENCE_MISSING",
                "detail": ("status=='pass' with an empty failure_codes list requires "
                           "actor_bounds_valid, support_samples_total>0, "
                           "cleanup_verified, a non-empty evidence_paths, and "
                           "camera_capture_ok whenever captures_requested is "
                           "non-empty. Multi-field conjunction; runtime rail only."),
                "expressible_in_json_schema": False,
            },
            {
                "rail": "sr::observed_anchor_present",
                "code": "WF1106_SCENE_SURVEY_SUBJECT_UNRESOLVED",
                "detail": "encoded above as an if/then on runtime_executed.",
                "expressible_in_json_schema": True,
            },
            {
                "rail": "sr::live_mode_executed",
                "code": "WF1095_SCENE_SURVEY_RUNTIME_SIMULATED_OVERCLAIM",
                "detail": "encoded above as an if/then on runtime_mode.",
                "expressible_in_json_schema": True,
            },
            {
                "rail": "subject_binding",
                "code": "WF1107_SCENE_SURVEY_SUBJECT_MISMATCH",
                "detail": ("The report must BIND to the request that produced it: "
                           "subject_id and map_asset_path must match the request "
                           "subject exactly; an explicit_transform subject must have "
                           "observed_anchor_location within {} cm (Euclidean, "
                           "inclusive) of the requested anchor_location; an "
                           "actor_object_path subject must have an exactly equal "
                           "observed_anchor_object_path. Cross-DOCUMENT and therefore "
                           "outside any single schema.".format(_tolerance_cm())),
                "expressible_in_json_schema": False,
            },
        ],
    }


def _request_field_types():
    """Derive the request property types from the live dataclass annotations."""
    frags = {}
    required = []
    for f in dataclass_fields(BridgeRequest):
        has_default = (f.default is not MISSING) or (f.default_factory is not MISSING)  # noqa: E501
        if not has_default:
            required.append(f.name)
        ann = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "")
        if f.name == "subject":
            frags[f.name] = _s_nullable(
                {"$ref": "scene_survey_subject.schema.json"})
        elif f.name == "requested_operation":
            frags[f.name] = _s_const(OPS.OP_SCENE_SURVEY)
        elif f.name == "required_plugin_source_hash":
            frags[f.name] = _s_nullable({"type": "string",
                                         "pattern": "^[0-9a-f]{64}$"})
        elif "int" in ann:
            frags[f.name] = {"type": "number", "multipleOf": 1, "minimum": 0}
        elif f.name == "target_map":
            # "" is a legal explicit "no map needed"; a scene survey always needs one,
            # which the target_map<->subject agreement rail enforces at runtime.
            frags[f.name] = {"type": "string"}
        else:
            frags[f.name] = {"type": "string"}
    return frags, sorted(required)


def build_request_schema():
    frags, required = _request_field_types()
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": SCHEMA_BASE + "scene_survey_request.schema.json",
        "title": "SceneSurveyRequest",
        "description": (
            "A BridgeRequest carrying requested_operation='scene_survey'. The "
            "caller authors this; it is the ONLY way to state a survey subject. "
            "--map and --anchor are refused by the operation, not defaulted."),
        "x-worldforge-contract-version": SS.CONTRACT_VERSION,
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": frags,
        "x-worldforge-rails": [
            {
                "rail": "request::target_map_agrees_with_subject",
                "code": "WF1107_SCENE_SURVEY_SUBJECT_MISMATCH",
                "detail": ("when target_map is non-empty it must equal "
                           "subject.map_asset_path exactly. Cross-field equality is "
                           "not expressible in JSON Schema."),
                "expressible_in_json_schema": False,
            },
            {
                "rail": "request::plugin_source_pin",
                "code": "WF1026_BRIDGE_STALE_PLUGIN",
                "detail": ("required_plugin_source_hash must be stated and must equal "
                           "the sha256 of the target's Plugins/WorldForge/Source tree. "
                           "An UNSTATED pin fails closed — it is not treated as "
                           "'no requirement'. Checked before the editor boots."),
                "expressible_in_json_schema": False,
            },
            {
                "rail": "request::subject_required_for_scene_survey",
                "code": "WF1106_SCENE_SURVEY_SUBJECT_UNRESOLVED",
                "detail": ("subject is Optional on the BridgeRequest dataclass because "
                           "other operations do not take one, but the scene_survey "
                           "operation refuses a request whose subject is absent."),
                "expressible_in_json_schema": False,
            },
        ],
    }


# --------------------------------------------------------------------------- #
# Examples — real, contract-valid requests. NOT acceptance artifacts.
# --------------------------------------------------------------------------- #
def _observed_plugin_source_hash():
    """Hash the in-repo plugin so the examples carry a runnable, real pin."""
    try:
        from bridge import paths as P
        return P.hash_plugin_source(REPO_ROOT / "Plugins" / "WorldForge"), True
    except Exception:
        return "0" * 64, False


def _example_request(subject, operation_id, pin):
    return {
        "operation_id": operation_id,
        "source_repository": "WorldForge",
        "source_commit": "HEAD",
        "target_repository": EXAMPLE_REPO,
        "target_commit": EXAMPLE_COMMIT,
        "target_engine": "5.8",
        "target_project": EXAMPLE_PROJECT,
        "target_map": subject["map_asset_path"],
        "required_plugin": "WorldForge",
        "required_plugin_version": "0.1.0",
        "required_plugin_source_hash": pin,
        "requested_operation": OPS.OP_SCENE_SURVEY,
        "output_location": "procedural/reports/scene_survey/runtime",
        "timeout_seconds": 900,
        "subject": subject,
    }


def build_examples(pin):
    actor_subject = {
        "subject_id": "example_actor_subject",
        "subject_kind": "actor",
        "map_asset_path": EXAMPLE_MAP,
        "anchor_mode": "actor_object_path",
        "anchor_location": None,
        "anchor_rotation": None,
        "anchor_object_path": (
            "/Game/Maps/ExampleSurveyLevel.ExampleSurveyLevel:PersistentLevel."
            "ExampleAnchorActor_0"),
        "resolved_by": "caller",
        "schema_version": SS.RT_SUBJECT,
        "report_type": SS.RT_SUBJECT,
        "created_by": "example.caller",
        "created_at": SS.AUTHORING_TS,
    }
    transform_subject = {
        "subject_id": "example_transform_subject",
        "subject_kind": "point",
        "map_asset_path": EXAMPLE_MAP,
        "anchor_mode": "explicit_transform",
        "anchor_location": [1200.0, -450.0, 310.0],
        "anchor_rotation": [0.0, 90.0, 0.0],
        "anchor_object_path": None,
        "resolved_by": "caller",
        "schema_version": SS.RT_SUBJECT,
        "report_type": SS.RT_SUBJECT,
        "created_by": "example.caller",
        "created_at": SS.AUTHORING_TS,
    }
    return {
        "caller_resolved_actor_request.json": _example_request(
            actor_subject, "op_example_scene_survey_actor", pin),
        "caller_resolved_transform_request.json": _example_request(
            transform_subject, "op_example_scene_survey_transform", pin),
    }


# --------------------------------------------------------------------------- #
# Serialization.
# --------------------------------------------------------------------------- #
def _canonical(obj):
    """Byte-stable JSON text. LF is written explicitly by the caller."""
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" is load-bearing: .gitattributes pins *.json to eol=lf, and the
    # default translation on Windows would emit CRLF and fake a drift.
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _read(path):
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


# --------------------------------------------------------------------------- #
# Schema<->validator equivalence proof.
# --------------------------------------------------------------------------- #
def _jsonschema_validator():
    try:
        import jsonschema
    except ImportError:
        return None
    return jsonschema


def _schema_accepts(js, schema, doc, registry_docs):
    """True if the document satisfies the schema (resolving local $refs)."""
    resolver_store = {s["$id"]: s for s in registry_docs}

    def _retrieve(uri):
        from referencing import Resource
        return Resource.from_contents(resolver_store[uri])

    try:
        from referencing import Registry
        registry = Registry(retrieve=_retrieve)
        validator = js.Draft202012Validator(schema, registry=registry)
    except Exception:
        validator = js.Draft202012Validator(schema)
    try:
        errors = list(validator.iter_errors(doc))
    except Exception as exc:  # a schema that cannot even run is a drift problem
        return None, "schema failed to execute: {}".format(exc)
    return (not errors), "; ".join(e.message for e in errors[:3])


def _mutations(good, declared, nullable):
    """Generate (label, doc, must_be_rejected) probes for a record."""
    out = []
    for name in sorted(declared):
        d = dict(good)
        d.pop(name, None)
        out.append(("drop::" + name, d, True))

        d = dict(good)
        d[name] = {"unexpected": "object"}
        out.append(("wrongtype::" + name, d, True))

        if name not in set(nullable):
            d = dict(good)
            d[name] = None
            out.append(("null::" + name, d, True))

    d = dict(good)
    d["totally_unknown_key"] = 1
    out.append(("unknown_key", d, True))

    d = dict(good)
    d["schema_version"] = "wf.scene_survey.not_a_real_version.v1"
    out.append(("bad_schema_version", d, True))
    return out


def _python_rejects(validate_fn, doc):
    fails = [c for c in validate_fn(doc, strict=True) if not c[1]]
    return len(fails) > 0


def prove_equivalence(schemas, verbose=False):
    """Prove the exported schemas agree with the live Python validators.

    The claim proven is directional and stated honestly:
      * NO FALSE REJECTION — anything the Python validator accepts, the schema
        must accept. A schema stricter than the runtime would reject a legal
        caller request, which is worse than useless.
      * NO SILENT ACCEPTANCE on schema-expressible vectors — for every mutation
        the Python validator rejects, the schema must also reject it UNLESS the
        vector is one of the declared inexpressible rails.
    """
    js = _jsonschema_validator()
    problems = []
    checked = 0
    if js is None:
        return ["jsonschema is not importable — the schema<->validator equivalence "
                "proof could NOT be run. The exported artifacts are unproven."], 0

    registry_docs = [schemas["subject"], schemas["report"], schemas["request"]]

    cases = [
        ("SceneSurveySubject", schemas["subject"],
         SS.validate_scene_survey_subject,
         SS._example_scene_survey_subject(),
         _subject_fields(), SS._SUBJECT_NULLABLE),
        ("SceneSurveyReport", schemas["report"],
         SS.validate_scene_survey_report,
         SS._example_scene_survey_report(),
         _report_fields(), SS._REPORT_NULLABLE),
    ]

    for label, schema, validate_fn, good, declared, nullable in cases:
        # Positive control: the module's own good example must satisfy both.
        py_bad = _python_rejects(validate_fn, good)
        ok, detail = _schema_accepts(js, schema, good, registry_docs)
        checked += 1
        if py_bad:
            problems.append(
                "{}: the module's own valid example fails its Python validator — "
                "the contract spine is broken, not the export".format(label))
        if ok is None:
            problems.append("{}: {}".format(label, detail))
            continue
        if not ok:
            problems.append(
                "{}: FALSE REJECTION — the exported schema rejects the module's own "
                "valid example ({})".format(label, detail))

        for mlabel, doc, _must in _mutations(good, declared, nullable):
            checked += 1
            py_rejects = _python_rejects(validate_fn, doc)
            s_ok, s_detail = _schema_accepts(js, schema, doc, registry_docs)
            if s_ok is None:
                problems.append("{}::{}: {}".format(label, mlabel, s_detail))
                continue
            schema_rejects = not s_ok
            if py_rejects and not schema_rejects:
                problems.append(
                    "{}::{}: the Python validator rejects this but the exported "
                    "schema ACCEPTS it — the schema is weaker than the runtime on a "
                    "vector it should express".format(label, mlabel))
            if schema_rejects and not py_rejects:
                problems.append(
                    "{}::{}: the exported schema rejects this but the Python "
                    "validator ACCEPTS it — FALSE REJECTION of a legal document "
                    "({})".format(label, mlabel, s_detail))
            if verbose:
                print("    {}::{} py_reject={} schema_reject={}".format(
                    label, mlabel, py_rejects, schema_rejects))

    # Anchor-mode exclusivity, both directions, proven against the real validator.
    subj = SS._example_scene_survey_subject()
    both = dict(subj)
    both["anchor_mode"] = "explicit_transform"
    both["anchor_location"] = [0.0, 0.0, 0.0]
    both["anchor_object_path"] = "/Game/X.X:PersistentLevel.Y"
    neither = dict(subj)
    neither["anchor_location"] = None
    neither["anchor_object_path"] = None
    for mlabel, doc in (("anchor::both_channels", both),
                        ("anchor::neither_channel", neither)):
        checked += 1
        py_rejects = _python_rejects(SS.validate_scene_survey_subject, doc)
        s_ok, s_detail = _schema_accepts(js, schemas["subject"], doc, registry_docs)
        if not py_rejects:
            problems.append(
                "{}: the Python validator ACCEPTS a subject that violates anchor "
                "exclusivity — Wave 1 protection is gone".format(mlabel))
        if s_ok:
            problems.append(
                "{}: the exported schema accepts a subject that violates anchor "
                "exclusivity".format(mlabel))

    return problems, checked


# --------------------------------------------------------------------------- #
# Manifest.
# --------------------------------------------------------------------------- #
def build_manifest(artifacts, pin_observed, equivalence_checked):
    entries = {}
    for rel, text in sorted(artifacts.items()):
        entries[rel] = {
            "sha256": _sha256_text(text),
            "bytes": len(text.encode("utf-8")),
        }
    surface = _sha256_text("".join(
        text for _rel, text in sorted(artifacts.items())))
    return {
        "$schema": SCHEMA_DIALECT,
        "title": "SceneSurveyContractManifest",
        "contract_version": SS.CONTRACT_VERSION,
        "generator": GENERATOR,
        "generator_provenance": {
            "generated_from": [
                "tools/pipeline/scene_survey_contracts.py",
                "tools/bridge/schema.py",
                "tools/bridge/capability_ops.py",
            ],
            "commit_stamped": False,
            "commit_omitted_because": (
                "a committed artifact that embeds HEAD would need regenerating on "
                "every unrelated commit, turning the drift gate into noise. Identity "
                "is carried by contract_surface_sha256 instead, which changes exactly "
                "when the contract surface changes. The WorldForge commit IS stamped "
                "on runtime evidence, which is per-run."),
        },
        "contract_surface_sha256": surface,
        "artifacts": entries,
        "operation": {
            "operation": OPS.OP_SCENE_SURVEY,
            "summary": OPS.CAPABILITY_OPS[OPS.OP_SCENE_SURVEY].summary,
            "far_side_script": OPS.CAPABILITY_OPS[OPS.OP_SCENE_SURVEY].far_side_script,
            "payload_keys": list(
                OPS.CAPABILITY_OPS[OPS.OP_SCENE_SURVEY].payload_keys),
        },
        "vocabulary": {
            "anchor_modes": list(SS.ANCHOR_MODES),
            "subject_kinds": list(SS.SUBJECT_KINDS),
            "subject_resolvers": list(SS.SUBJECT_RESOLVERS),
            "camera_kinds": list(SS.CAMERA_KINDS),
            "runtime_modes": list(SS.RUNTIME_MODES),
            "live_runtime_modes": list(SS.LIVE_RUNTIME_MODES),
            "survey_status": list(SS.SURVEY_STATUS),
        },
        "binding": {
            "transform_tolerance_cm": _tolerance_cm(),
            "transform_tolerance_metric": "euclidean_l2_inclusive",
            "rotation_compared": False,
            "scale_compared": False,
        },
        "failure_codes_owned": sorted(SS.SCENE_SURVEY_CODES),
        "example_plugin_source_hash_observed": pin_observed,
        "equivalence_probes_run": equivalence_checked,
        "honest_limitations": [
            "JSON Schema cannot express cross-field arithmetic or cross-document "
            "binding; each schema's x-worldforge-rails block names the rails that "
            "remain runtime-only. Schema validity is necessary, not sufficient.",
            "The examples are WorldForge-authored contract-test artifacts. They are "
            "valid requests, but a WorldForge-authored request can never satisfy the "
            "caller-originated acceptance gate.",
        ],
    }


# --------------------------------------------------------------------------- #
# Main.
# --------------------------------------------------------------------------- #
def generate():
    pin, pin_observed = _observed_plugin_source_hash()
    schemas = {
        "subject": build_subject_schema(),
        "report": build_report_schema(),
        "request": build_request_schema(),
    }
    artifacts = {
        "specs/scene_survey/scene_survey_subject.schema.json":
            _canonical(schemas["subject"]),
        "specs/scene_survey/scene_survey_request.schema.json":
            _canonical(schemas["request"]),
        "specs/scene_survey/scene_survey_report.schema.json":
            _canonical(schemas["report"]),
    }
    for name, doc in sorted(build_examples(pin).items()):
        artifacts["examples/scene_survey/" + name] = _canonical(doc)
    return schemas, artifacts, pin_observed


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Export the caller-facing scene-survey contract artifacts.")
    ap.add_argument("--check", action="store_true",
                    help="verify committed artifacts match a fresh export; write nothing")
    ap.add_argument("--verbose", action="store_true")
    args, _unknown = ap.parse_known_args(argv)

    problems = []

    # 1. Structural drift: declared types vs the live module tuples.
    problems += _structural_drift(
        "subject", _subject_fields(), SS.SUBJECT_REQUIRED, SS.SUBJECT_ALLOWED,
        SS._SUBJECT_NULLABLE)
    problems += _structural_drift(
        "report", _report_fields(), SS.REPORT_REQUIRED, SS.REPORT_ALLOWED,
        SS._REPORT_NULLABLE)

    # 2. Wave 1 protections must still be in place, or the export is meaningless.
    if hasattr(SS, "ANCHOR_TOKENS") or hasattr(SS, "SURVEY_ANCHORS"):
        problems.append(
            "Wave 1 protection removed: an anchor vocabulary constant reappeared in "
            "scene_survey_contracts.py — WorldForge must not own anchor semantics")
    if tuple(SS.SUBJECT_RESOLVERS) != ("caller",):
        problems.append(
            "Wave 1 protection removed: SUBJECT_RESOLVERS is {} — 'caller' must be "
            "the only resolver".format(tuple(SS.SUBJECT_RESOLVERS)))

    schemas, artifacts, pin_observed = generate()

    # 3. Prove the schemas agree with the live validators.
    eq_problems, checked = prove_equivalence(schemas, verbose=args.verbose)
    problems += eq_problems

    manifest_rel = "specs/scene_survey/scene_survey_contract_manifest.json"
    artifacts[manifest_rel] = _canonical(
        build_manifest(artifacts, pin_observed, checked))

    if problems:
        print("[export-scene-survey-contracts] FAIL — implementation and export "
              "disagree ({} problem(s)):".format(len(problems)))
        for p in problems:
            print("  - {}".format(p))
        return 1

    if args.check:
        drift = []
        for rel, text in sorted(artifacts.items()):
            on_disk = _read(REPO_ROOT / rel)
            if on_disk is None:
                drift.append("{}: MISSING — never exported".format(rel))
            elif on_disk != text:
                drift.append("{}: DRIFT — committed bytes differ from a fresh "
                             "export (committed sha256 {}, fresh {})".format(
                                 rel, _sha256_text(on_disk)[:12],
                                 _sha256_text(text)[:12]))
        if drift:
            print("[export-scene-survey-contracts] FAIL — {} artifact(s) drifted; "
                  "re-run without --check to regenerate:".format(len(drift)))
            for d in drift:
                print("  - {}".format(d))
            return 1
        print("[export-scene-survey-contracts] PASS — {} artifact(s) match a fresh "
              "export; {} schema/validator equivalence probes agreed".format(
                  len(artifacts), checked))
        return 0

    for rel, text in sorted(artifacts.items()):
        _write(REPO_ROOT / rel, text)
        print("[export] {} ({} bytes)".format(rel, len(text.encode("utf-8"))))
    print("[export-scene-survey-contracts] PASS — {} artifact(s) written; {} "
          "schema/validator equivalence probes agreed; contract_version={}".format(
              len(artifacts), checked, SS.CONTRACT_VERSION))
    return 0


if __name__ == "__main__":
    sys.exit(main())
