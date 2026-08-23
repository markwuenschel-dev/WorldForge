#!/usr/bin/env python3
"""Compile a caller-owned authored-world JSON document into generic artifacts.

This is deliberately an authoring compiler, not a materializer.  It validates
only the caller's document and emits deterministic plans/provenance; it does
not start Unreal, load a map, or claim any observation occurred.

The supplied JSON Schema is validated with :mod:`jsonschema` when available.
The small standard-library fallback accepts only the strict subset documented
in ``_SUPPORTED_SCHEMA_KEYS`` and rejects every other validation keyword.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXED_GENERATED_AT_UTC = "1970-01-01T00:00:00Z"
OUTPUT_FILES = (
    "manifest.json",
    "terrain-slice.json",
    "poi-descriptors.json",
    "placement-variants.json",
    "material-variants.json",
    "survey-requests.json",
)
REQUIRED_FIELDS = {
    "world_id", "input_version", "seed", "authored_anchors", "points_of_interest",
    "terrain_slice", "reactive_categories", "world_state_scenarios",
}
_SUPPORTED_SCHEMA_KEYS = {
    "$schema", "$id", "$defs", "$ref", "title", "description", "type", "required",
    "properties", "additionalProperties", "const", "items", "minItems", "maxItems",
    "uniqueItems",
}


class CompileError(ValueError):
    """A caller-facing validation or output-safety failure."""


def _reject_constant(value: str) -> None:
    raise CompileError("non-finite JSON constants are not accepted: {}".format(value))


def _no_duplicate_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CompileError("duplicate JSON object key: {!r}".format(key))
        value[key] = item
    return value


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle, object_pairs_hook=_no_duplicate_object,
                              parse_constant=_reject_constant)
    except OSError as error:
        raise CompileError("cannot read {}: {}".format(label, error)) from error
    except json.JSONDecodeError as error:
        raise CompileError("invalid {} JSON: {}".format(label, error)) from error
    if not isinstance(value, dict):
        raise CompileError("{} must be a JSON object".format(label))
    return value


def _load_jsonschema():
    try:
        import jsonschema
    except ImportError:
        return None
    return jsonschema


def _json_pointer(path: tuple[Any, ...]) -> str:
    if not path:
        return "$"
    return "$" + "".join("[{}]".format(part) if isinstance(part, int)
                        else ".{}".format(part) for part in path)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _fallback_schema_error(message: str, path: tuple[Any, ...] = ()) -> CompileError:
    return CompileError("schema validation failed at {}: {}".format(_json_pointer(path), message))


def _resolve_ref(root_schema: dict[str, Any], ref: str) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not ref.startswith(prefix) or not ref[len(prefix):] or "/" in ref[len(prefix):]:
        raise CompileError("unsupported JSON Schema reference: {!r}".format(ref))
    target = root_schema.get("$defs", {}).get(ref[len(prefix):])
    if not isinstance(target, dict):
        raise CompileError("unresolvable JSON Schema reference: {!r}".format(ref))
    return target


def _validate_fallback_schema_shape(schema: Any, root_schema: dict[str, Any], seen: set[int] | None = None) -> None:
    if not isinstance(schema, dict):
        raise CompileError("JSON Schema nodes must be objects")
    seen = set() if seen is None else seen
    marker = id(schema)
    if marker in seen:
        return
    seen.add(marker)
    unknown = sorted(set(schema) - _SUPPORTED_SCHEMA_KEYS)
    if unknown:
        raise CompileError("unsupported JSON Schema keyword(s): {}".format(", ".join(unknown)))
    if "$ref" in schema:
        if not isinstance(schema["$ref"], str):
            raise CompileError("JSON Schema $ref must be a string")
        _validate_fallback_schema_shape(_resolve_ref(root_schema, schema["$ref"]), root_schema, seen)
    if "type" in schema and schema["type"] not in {"object", "array", "string", "integer", "number", "boolean", "null"}:
        raise CompileError("unsupported JSON Schema type: {!r}".format(schema["type"]))
    if "required" in schema and (not isinstance(schema["required"], list) or
                                  not all(isinstance(item, str) for item in schema["required"])):
        raise CompileError("JSON Schema required must be an array of strings")
    if "properties" in schema:
        if not isinstance(schema["properties"], dict):
            raise CompileError("JSON Schema properties must be an object")
        for child in schema["properties"].values():
            _validate_fallback_schema_shape(child, root_schema, seen)
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
        raise CompileError("only boolean additionalProperties is supported by the stdlib validator")
    if "items" in schema:
        _validate_fallback_schema_shape(schema["items"], root_schema, seen)
    if "$defs" in schema:
        if not isinstance(schema["$defs"], dict):
            raise CompileError("JSON Schema $defs must be an object")
        for child in schema["$defs"].values():
            _validate_fallback_schema_shape(child, root_schema, seen)
    for key in ("minItems", "maxItems"):
        if key in schema and (not isinstance(schema[key], int) or isinstance(schema[key], bool) or schema[key] < 0):
            raise CompileError("JSON Schema {} must be a non-negative integer".format(key))
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        raise CompileError("JSON Schema uniqueItems must be boolean")


def _fallback_validate(value: Any, schema: dict[str, Any], root_schema: dict[str, Any],
                       path: tuple[Any, ...] = (), ref_stack: tuple[str, ...] = ()) -> None:
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref in ref_stack:
            raise CompileError("cyclic JSON Schema reference: {!r}".format(ref))
        _fallback_validate(value, _resolve_ref(root_schema, ref), root_schema, path, ref_stack + (ref,))
        schema = {key: item for key, item in schema.items() if key not in {"$ref", "$defs"}}
    if "const" in schema and value != schema["const"]:
        raise _fallback_schema_error("value does not equal const", path)
    expected = schema.get("type")
    type_checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected and not type_checks[expected](value):
        raise _fallback_schema_error("expected type {}".format(expected), path)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                raise _fallback_schema_error("missing required property {!r}".format(required), path)
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    raise _fallback_schema_error("unknown property {!r}".format(key), path)
        for key in sorted(value):
            if key in properties:
                _fallback_validate(value[key], properties[key], root_schema, path + (key,), ref_stack)
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise _fallback_schema_error("array has fewer than minItems", path)
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise _fallback_schema_error("array has more than maxItems", path)
        if schema.get("uniqueItems"):
            values = [_canonical_json(item) for item in value]
            if len(values) != len(set(values)):
                raise _fallback_schema_error("array items are not unique", path)
        if "items" in schema:
            for index, item in enumerate(value):
                _fallback_validate(item, schema["items"], root_schema, path + (index,), ref_stack)


def _validate_against_schema(spec: dict[str, Any], schema: dict[str, Any]) -> None:
    jsonschema = _load_jsonschema()
    if jsonschema is None:
        _validate_fallback_schema_shape(schema, schema)
        _fallback_validate(spec, schema, schema)
        return
    try:
        validator_type = jsonschema.validators.validator_for(schema)
        validator_type.check_schema(schema)
        errors = sorted(validator_type(schema).iter_errors(spec),
                        key=lambda error: (_json_pointer(tuple(error.absolute_path)), error.message))
    except Exception as error:
        schema_error = getattr(jsonschema, "exceptions", None)
        if schema_error and isinstance(error, schema_error.SchemaError):
            raise CompileError("invalid JSON Schema: {}".format(error.message)) from error
        raise CompileError("JSON Schema validator failed closed: {}".format(error)) from error
    if errors:
        first = errors[0]
        raise CompileError("schema validation failed at {}: {}".format(
            _json_pointer(tuple(first.absolute_path)), first.message))


def _require_safe_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise CompileError("{} must be a non-empty string".format(label))
    if (value in {".", ".."} or "/" in value or "\\" in value or ":" in value or
            Path(value).is_absolute() or PureWindowsPath(value).is_absolute() or
            re.match(r"^[A-Za-z]:", value)):
        raise CompileError("unsafe {}: path traversal or absolute name is not allowed".format(label))
    return value


def _validate_contract(spec: dict[str, Any]) -> None:
    unknown = sorted(set(spec) - REQUIRED_FIELDS)
    missing = sorted(REQUIRED_FIELDS - set(spec))
    if unknown:
        raise CompileError("unknown authored-world field(s): {}".format(", ".join(unknown)))
    if missing:
        raise CompileError("missing authored-world field(s): {}".format(", ".join(missing)))
    _require_safe_identifier(spec["world_id"], "world id")
    if not isinstance(spec["input_version"], str) or not spec["input_version"]:
        raise CompileError("input_version must be a non-empty string")
    if not isinstance(spec["seed"], int) or isinstance(spec["seed"], bool):
        raise CompileError("seed must be an integer")
    for name in ("authored_anchors", "points_of_interest", "reactive_categories", "world_state_scenarios"):
        if not isinstance(spec[name], list):
            raise CompileError("{} must be an array".format(name))
    if not isinstance(spec["terrain_slice"], dict):
        raise CompileError("terrain_slice must be an object")
    _validate_keyed_records(spec["reactive_categories"], "reactive category", "values")
    _validate_keyed_records(spec["world_state_scenarios"], "world-state scenario", "state_values")


def _validate_keyed_records(records: list[Any], label: str, payload_field: str) -> None:
    identifiers: set[str] = set()
    expected = {"id", payload_field}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise CompileError("{} at index {} must be an object".format(label, index))
        unknown = sorted(set(record) - expected)
        missing = sorted(expected - set(record))
        if unknown:
            raise CompileError("unknown {} field(s): {}".format(label, ", ".join(unknown)))
        if missing:
            raise CompileError("{} missing field(s): {}".format(label, ", ".join(missing)))
        identifier = _require_safe_identifier(record["id"], "{} id".format(label))
        if identifier in identifiers:
            raise CompileError("duplicate {} id: {!r}".format(label, identifier))
        identifiers.add(identifier)
    if label == "world-state scenario":
        for record in records:
            if not isinstance(record[payload_field], dict):
                raise CompileError("world-state scenario state_values must be an object")


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return cleaned[:48] or "id"


def _descriptor_id(kind: str, *identifiers: str) -> str:
    raw = "\x1f".join(identifiers)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return "{}-{}-{}".format(kind, "-".join(_slug(item) for item in identifiers), digest)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-c", "safe.directory={}".format(REPO_ROOT.as_posix()), *args],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def _source_provenance() -> dict[str, Any]:
    return {
        "source_commit": _git("rev-parse", "HEAD") or "unknown",
        "source_tree_dirty": bool(_git("status", "--porcelain")),
    }


def _sorted_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda item: item["id"])


def _build_artifacts(spec: dict[str, Any], spec_path: Path, schema_path: Path) -> dict[str, dict[str, Any]]:
    categories = _sorted_records(spec["reactive_categories"])
    scenarios = _sorted_records(spec["world_state_scenarios"])
    placements, materials, surveys = [], [], []
    for category in categories:
        for scenario in scenarios:
            shared = {
                "reactive_category": category,
                "world_state_scenario": scenario,
            }
            placements.append({
                "descriptor_id": _descriptor_id("placement", category["id"], scenario["id"]),
                "descriptor_kind": "placement_variant",
                **shared,
            })
            materials.append({
                "descriptor_id": _descriptor_id("material", category["id"], scenario["id"]),
                "descriptor_kind": "material_variant",
                **shared,
            })
            surveys.append({
                "request_id": _descriptor_id("survey-category-state", category["id"], scenario["id"]),
                "subject_kind": "category_state",
                "reactive_category": category,
                "world_state_scenario": scenario,
                "status": "planned",
                "observation": "not_observed",
            })
    for subject_kind, references in (("authored_anchor", spec["authored_anchors"]),
                                    ("point_of_interest", spec["points_of_interest"])):
        for index, reference in enumerate(references):
            surveys.append({
                "request_id": _descriptor_id("survey-{}".format(subject_kind), str(index)),
                "subject_kind": subject_kind,
                "opaque_reference": reference,
                "status": "planned",
                "observation": "not_observed",
            })
    surveys.sort(key=lambda item: item["request_id"])
    poi_descriptors = [
        {
            "descriptor_id": _descriptor_id("poi", str(index)),
            "descriptor_kind": "point_of_interest",
            "opaque_reference": reference,
            "source_input_path": "points_of_interest[{}]".format(index),
        }
        for index, reference in enumerate(spec["points_of_interest"])
    ]
    artifacts = {
        "terrain-slice.json": {
            "artifact_kind": "generic_terrain_slice_descriptor",
            "terrain_slice": spec["terrain_slice"],
        },
        "poi-descriptors.json": {
            "artifact_kind": "generic_point_of_interest_descriptors",
            "descriptors": poi_descriptors,
        },
        "placement-variants.json": {
            "artifact_kind": "generic_placement_variant_descriptors",
            "variants": placements,
        },
        "material-variants.json": {
            "artifact_kind": "generic_material_variant_descriptors",
            "variants": materials,
        },
        "survey-requests.json": {
            "artifact_kind": "generic_survey_requests",
            "requests": surveys,
        },
    }
    artifacts["manifest.json"] = {
        "artifact_kind": "authored_world_compile_manifest",
        "generated_at_utc": FIXED_GENERATED_AT_UTC,
        "execution_status": "not_materialized",
        "world": {
            "world_id": spec["world_id"],
            "input_version": spec["input_version"],
            "seed": spec["seed"],
        },
        "sources": {
            "spec": {"path_label": spec_path.name, "sha256": _sha256(spec_path)},
            "schema": {"path_label": schema_path.name, "sha256": _sha256(schema_path)},
        },
        "worldforge_provenance": _source_provenance(),
        "artifacts": list(OUTPUT_FILES[1:]),
    }
    return artifacts


def _safe_output_path(output_root: Path, relative_name: str) -> Path:
    if relative_name not in OUTPUT_FILES or Path(relative_name).name != relative_name:
        raise CompileError("unsafe generated output name: {!r}".format(relative_name))
    candidate = (output_root / relative_name).resolve()
    try:
        candidate.relative_to(output_root)
    except ValueError as error:
        raise CompileError("generated output escapes output root: {!r}".format(relative_name)) from error
    return candidate


def _preflight_output_paths(spec_path: Path, schema_path: Path, output_root: Path) -> tuple[Path, Path, Path]:
    """Resolve every path and refuse to turn either input into an output target."""
    resolved_spec = spec_path.resolve()
    resolved_schema = schema_path.resolve()
    resolved_root = output_root.resolve()
    if resolved_root == Path(resolved_root.anchor):
        raise CompileError("output root must not be a filesystem root")
    for input_label, input_path in (("specification", resolved_spec), ("schema", resolved_schema)):
        if input_path == resolved_root:
            raise CompileError("output root is the same path as the {} input".format(input_label))
        for relative_name in OUTPUT_FILES:
            if input_path == _safe_output_path(resolved_root, relative_name):
                raise CompileError(
                    "{} input path collides with generated output: {}".format(input_label, relative_name))
    return resolved_spec, resolved_schema, resolved_root


def _write_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".authored-world-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def compile_authored_world(spec_path: Path, schema_path: Path, output_root: Path) -> dict[str, dict[str, Any]]:
    resolved_spec, resolved_schema, resolved_root = _preflight_output_paths(
        spec_path, schema_path, output_root)
    spec = _load_json_object(resolved_spec, "specification")
    schema = _load_json_object(resolved_schema, "schema")
    _validate_against_schema(spec, schema)
    _validate_contract(spec)
    artifacts = _build_artifacts(spec, resolved_spec, resolved_schema)
    resolved_root.mkdir(parents=True, exist_ok=True)
    for relative_name in OUTPUT_FILES:
        _write_json(_safe_output_path(resolved_root, relative_name), artifacts[relative_name])
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile a caller-authored world specification without materializing it.")
    parser.add_argument("--spec", required=True, type=Path, help="caller-owned JSON world specification")
    parser.add_argument("--schema", required=True, type=Path, help="caller-owned JSON Schema for --spec")
    parser.add_argument("--output-root", required=True, type=Path, help="directory that will receive only compiler artifacts")
    args = parser.parse_args(argv)
    try:
        artifacts = compile_authored_world(args.spec, args.schema, args.output_root)
    except CompileError as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        return 2
    print("COMPILED: {} deterministic artifacts under {}".format(len(artifacts), args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
