#!/usr/bin/env python3
"""Prepare a generic Unreal/NeoStack materialization request.

The compiler output is an intentionally inert hand-off.  This module validates
that hand-off, preserves the caller-owned descriptors, and emits a deterministic
request for a later editor adapter.  It never writes Unreal content, starts an
editor, loads a map, or turns a planned survey into an observation.
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
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXED_GENERATED_AT_UTC = "1970-01-01T00:00:00Z"
INPUT_FILES = (
    "manifest.json",
    "terrain-slice.json",
    "poi-descriptors.json",
    "placement-variants.json",
    "material-variants.json",
    "survey-requests.json",
)
EXPECTED_ARTIFACTS = INPUT_FILES[1:]
EXPECTED_ARTIFACT_KINDS = {
    "terrain-slice.json": "generic_terrain_slice_descriptor",
    "poi-descriptors.json": "generic_point_of_interest_descriptors",
    "placement-variants.json": "generic_placement_variant_descriptors",
    "material-variants.json": "generic_material_variant_descriptors",
    "survey-requests.json": "generic_survey_requests",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]+$")
UNREAL_PACKAGE_ROOT = re.compile(r"^/Game(?:/[A-Za-z0-9_.-]+)+$")


class PrepareError(ValueError):
    """A caller-facing validation or output-safety failure."""


def _reject_constant(value: str) -> None:
    raise PrepareError("non-finite JSON constants are not accepted: {}".format(value))


def _no_duplicate_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PrepareError("duplicate JSON object key: {!r}".format(key))
        value[key] = item
    return value


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle, object_pairs_hook=_no_duplicate_object,
                              parse_constant=_reject_constant)
    except OSError as error:
        raise PrepareError("cannot read {}: {}".format(label, error)) from error
    except json.JSONDecodeError as error:
        raise PrepareError("invalid {} JSON: {}".format(label, error)) from error
    if not isinstance(value, dict):
        raise PrepareError("{} must be a JSON object".format(label))
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


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


def _expect_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PrepareError("{} must be an object".format(label))
    return value


def _expect_array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise PrepareError("{} must be an array".format(label))
    return value


def _expect_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown:
        raise PrepareError("unknown {} field(s): {}".format(label, ", ".join(unknown)))
    if missing:
        raise PrepareError("{} missing field(s): {}".format(label, ", ".join(missing)))


def _safe_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or not SAFE_IDENTIFIER.fullmatch(value):
        raise PrepareError("{} must be a safe non-empty identifier".format(label))
    return value


def _sha_field(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise PrepareError("{} must be a lowercase SHA-256 digest".format(label))
    return value


def _validate_reference(value: Any, label: str) -> None:
    # References are caller-owned opaque JSON.  Reject only non-JSON values,
    # which strict loading has already excluded, and preserve the value exactly.
    try:
        _canonical_json(value)
    except (TypeError, ValueError) as error:
        raise PrepareError("{} is not JSON serializable".format(label)) from error


def _validate_category(value: Any, label: str) -> dict[str, Any]:
    category = _expect_object(value, label)
    _expect_keys(category, {"id", "values"}, label)
    _safe_identifier(category["id"], "{}.id".format(label))
    _validate_reference(category["values"], "{}.values".format(label))
    return category


def _validate_scenario(value: Any, label: str) -> dict[str, Any]:
    scenario = _expect_object(value, label)
    _expect_keys(scenario, {"id", "state_values"}, label)
    _safe_identifier(scenario["id"], "{}.id".format(label))
    if not isinstance(scenario["state_values"], dict):
        raise PrepareError("{}.state_values must be an object".format(label))
    _validate_reference(scenario["state_values"], "{}.state_values".format(label))
    return scenario


def _validate_manifest(manifest: dict[str, Any]) -> None:
    _expect_keys(manifest, {
        "artifact_kind", "generated_at_utc", "execution_status", "world", "sources",
        "worldforge_provenance", "artifacts",
    }, "manifest")
    if manifest["artifact_kind"] != "authored_world_compile_manifest":
        raise PrepareError("manifest has an unexpected artifact_kind")
    if manifest["execution_status"] != "not_materialized":
        raise PrepareError("manifest must remain not_materialized")
    if not isinstance(manifest["generated_at_utc"], str) or not manifest["generated_at_utc"]:
        raise PrepareError("manifest.generated_at_utc must be a non-empty string")

    world = _expect_object(manifest["world"], "manifest.world")
    _expect_keys(world, {"world_id", "input_version", "seed"}, "manifest.world")
    _safe_identifier(world["world_id"], "manifest.world.world_id")
    if not isinstance(world["input_version"], str) or not world["input_version"]:
        raise PrepareError("manifest.world.input_version must be a non-empty string")
    if not isinstance(world["seed"], int) or isinstance(world["seed"], bool):
        raise PrepareError("manifest.world.seed must be an integer")

    sources = _expect_object(manifest["sources"], "manifest.sources")
    _expect_keys(sources, {"spec", "schema"}, "manifest.sources")
    for label in ("spec", "schema"):
        source = _expect_object(sources[label], "manifest.sources.{}".format(label))
        _expect_keys(source, {"path_label", "sha256"}, "manifest.sources.{}".format(label))
        if not isinstance(source["path_label"], str) or not source["path_label"]:
            raise PrepareError("manifest.sources.{}.path_label must be a non-empty string".format(label))
        _sha_field(source["sha256"], "manifest.sources.{}.sha256".format(label))

    provenance = _expect_object(manifest["worldforge_provenance"], "manifest.worldforge_provenance")
    _expect_keys(provenance, {"source_commit", "source_tree_dirty"}, "manifest.worldforge_provenance")
    if not isinstance(provenance["source_commit"], str) or not provenance["source_commit"]:
        raise PrepareError("manifest.worldforge_provenance.source_commit must be a string")
    if not isinstance(provenance["source_tree_dirty"], bool):
        raise PrepareError("manifest.worldforge_provenance.source_tree_dirty must be boolean")

    artifacts = _expect_array(manifest["artifacts"], "manifest.artifacts")
    if artifacts != list(EXPECTED_ARTIFACTS):
        raise PrepareError("manifest.artifacts must exactly list the compiler artifacts")


def _validate_terrain(document: dict[str, Any]) -> dict[str, Any]:
    _expect_keys(document, {"artifact_kind", "terrain_slice"}, "terrain artifact")
    if document["artifact_kind"] != EXPECTED_ARTIFACT_KINDS["terrain-slice.json"]:
        raise PrepareError("terrain artifact has an unexpected artifact_kind")
    terrain = _expect_object(document["terrain_slice"], "terrain_slice")
    _validate_reference(terrain, "terrain_slice")
    return terrain


def _validate_pois(document: dict[str, Any]) -> list[dict[str, Any]]:
    _expect_keys(document, {"artifact_kind", "descriptors"}, "point-of-interest artifact")
    if document["artifact_kind"] != EXPECTED_ARTIFACT_KINDS["poi-descriptors.json"]:
        raise PrepareError("point-of-interest artifact has an unexpected artifact_kind")
    descriptors = _expect_array(document["descriptors"], "point-of-interest descriptors")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, item in enumerate(descriptors):
        descriptor = _expect_object(item, "point-of-interest descriptor {}".format(index))
        _expect_keys(descriptor, {"descriptor_id", "descriptor_kind", "opaque_reference", "source_input_path"},
                     "point-of-interest descriptor")
        identifier = _safe_identifier(descriptor["descriptor_id"], "point-of-interest descriptor_id")
        if identifier in seen:
            raise PrepareError("duplicate point-of-interest descriptor_id: {!r}".format(identifier))
        seen.add(identifier)
        if descriptor["descriptor_kind"] != "point_of_interest":
            raise PrepareError("point-of-interest descriptor has an unexpected descriptor_kind")
        if (not isinstance(descriptor["source_input_path"], str) or
                not re.fullmatch(r"points_of_interest\[[0-9]+\]", descriptor["source_input_path"])):
            raise PrepareError("point-of-interest descriptor has an unsafe source_input_path")
        _validate_reference(descriptor["opaque_reference"], "point-of-interest opaque_reference")
        result.append(descriptor)
    return result


def _validate_variants(document: dict[str, Any], filename: str, kind: str) -> list[dict[str, Any]]:
    _expect_keys(document, {"artifact_kind", "variants"}, "{} artifact".format(kind))
    if document["artifact_kind"] != EXPECTED_ARTIFACT_KINDS[filename]:
        raise PrepareError("{} artifact has an unexpected artifact_kind".format(kind))
    variants = _expect_array(document["variants"], "{} variants".format(kind))
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    expected_kind = "{}_variant".format(kind)
    for index, item in enumerate(variants):
        variant = _expect_object(item, "{} variant {}".format(kind, index))
        _expect_keys(variant, {"descriptor_id", "descriptor_kind", "reactive_category", "world_state_scenario"},
                     "{} variant".format(kind))
        identifier = _safe_identifier(variant["descriptor_id"], "{} descriptor_id".format(kind))
        if identifier in seen:
            raise PrepareError("duplicate {} descriptor_id: {!r}".format(kind, identifier))
        seen.add(identifier)
        if variant["descriptor_kind"] != expected_kind:
            raise PrepareError("{} variant has an unexpected descriptor_kind".format(kind))
        _validate_category(variant["reactive_category"], "{} reactive_category".format(kind))
        _validate_scenario(variant["world_state_scenario"], "{} world_state_scenario".format(kind))
        result.append(variant)
    return result


def _validate_surveys(document: dict[str, Any]) -> list[dict[str, Any]]:
    _expect_keys(document, {"artifact_kind", "requests"}, "survey artifact")
    if document["artifact_kind"] != EXPECTED_ARTIFACT_KINDS["survey-requests.json"]:
        raise PrepareError("survey artifact has an unexpected artifact_kind")
    requests = _expect_array(document["requests"], "survey requests")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, item in enumerate(requests):
        request = _expect_object(item, "survey request {}".format(index))
        base = {"request_id", "subject_kind", "status", "observation"}
        _expect_keys(request, base | ({"reactive_category", "world_state_scenario"}
                                      if request.get("subject_kind") == "category_state"
                                      else {"opaque_reference"}), "survey request")
        identifier = _safe_identifier(request["request_id"], "survey request_id")
        if identifier in seen:
            raise PrepareError("duplicate survey request_id: {!r}".format(identifier))
        seen.add(identifier)
        if request["subject_kind"] not in {"category_state", "authored_anchor", "point_of_interest"}:
            raise PrepareError("survey request has an unsupported subject_kind")
        if request["status"] != "planned" or request["observation"] != "not_observed":
            raise PrepareError("survey request must remain planned and not_observed")
        if request["subject_kind"] == "category_state":
            _validate_category(request["reactive_category"], "survey reactive_category")
            _validate_scenario(request["world_state_scenario"], "survey world_state_scenario")
        else:
            _validate_reference(request["opaque_reference"], "survey opaque_reference")
        result.append(request)
    return result


def _validate_input_root(input_root: Path) -> tuple[Path, dict[str, dict[str, Any]], dict[str, str]]:
    resolved = input_root.resolve()
    if not resolved.is_dir():
        raise PrepareError("input root must be an existing directory")
    actual = {path.name for path in resolved.iterdir()}
    expected = set(INPUT_FILES)
    if actual != expected:
        extra = sorted(actual - expected)
        missing = sorted(expected - actual)
        details = []
        if extra:
            details.append("unexpected entries: {}".format(", ".join(extra)))
        if missing:
            details.append("missing entries: {}".format(", ".join(missing)))
        raise PrepareError("input root is not an exact compiler output: {}".format("; ".join(details)))
    documents: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    for filename in INPUT_FILES:
        path = resolved / filename
        if path.is_symlink() or not path.is_file():
            raise PrepareError("input artifact must be a regular file: {}".format(filename))
        documents[filename] = _load_json(path, filename)
        hashes[filename] = _sha256(path)
    manifest = documents["manifest.json"]
    _validate_manifest(manifest)
    for filename in EXPECTED_ARTIFACTS:
        document = documents[filename]
        if document.get("artifact_kind") != EXPECTED_ARTIFACT_KINDS[filename]:
            raise PrepareError("{} has an unexpected artifact_kind".format(filename))
    return resolved, documents, hashes


def _validate_generated_root(value: str) -> str:
    if not isinstance(value, str) or not UNREAL_PACKAGE_ROOT.fullmatch(value.rstrip("/")):
        raise PrepareError("generated root must be a /Game Unreal package path")
    canonical = value.rstrip("/")
    if ".." in canonical.split("/") or "\\" in canonical or ":" in canonical:
        raise PrepareError("generated root contains unsafe path traversal")
    return canonical


def _preflight_output(input_root: Path, output_path: Path) -> tuple[Path, Path]:
    resolved_input = input_root.resolve()
    resolved_output = output_path.resolve()
    if resolved_output.exists():
        raise PrepareError("output request already exists; refusing stale reuse")
    if resolved_output == resolved_input:
        raise PrepareError("output request cannot be the input root")
    try:
        resolved_output.relative_to(resolved_input)
    except ValueError:
        pass
    else:
        raise PrepareError("output request cannot be inside the input root")
    if resolved_output.name != "materialization-request.json":
        raise PrepareError("output file must be named materialization-request.json")
    return resolved_input, resolved_output


def _operation(operation_id: str, kind: str, filename: str, target_root: str,
               descriptor: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "operation_kind": kind,
        "source_artifact": filename,
        "target_root": target_root,
        "descriptor": descriptor,
    }


def _build_request(documents: dict[str, dict[str, Any]], hashes: dict[str, str],
                   generated_root: str) -> dict[str, Any]:
    manifest = documents["manifest.json"]
    terrain = _validate_terrain(documents["terrain-slice.json"])
    pois = _validate_pois(documents["poi-descriptors.json"])
    placements = _validate_variants(documents["placement-variants.json"],
                                    "placement-variants.json", "placement")
    materials = _validate_variants(documents["material-variants.json"],
                                   "material-variants.json", "material")
    surveys = _validate_surveys(documents["survey-requests.json"])

    operations = [_operation("terrain-slice", "terrain_slice", "terrain-slice.json",
                             generated_root, terrain)]
    operations.extend(_operation(item["descriptor_id"], "point_of_interest",
                                 "poi-descriptors.json", generated_root, item)
                      for item in sorted(pois, key=lambda value: value["descriptor_id"]))
    operations.extend(_operation(item["descriptor_id"], "placement_variant",
                                 "placement-variants.json", generated_root, item)
                      for item in sorted(placements, key=lambda value: value["descriptor_id"]))
    operations.extend(_operation(item["descriptor_id"], "material_variant",
                                 "material-variants.json", generated_root, item)
                      for item in sorted(materials, key=lambda value: value["descriptor_id"]))
    survey_requests = [
        {
            "request_id": item["request_id"],
            "subject_kind": item["subject_kind"],
            "source_artifact": "survey-requests.json",
            "target_root": generated_root,
            "request": item,
        }
        for item in sorted(surveys, key=lambda value: value["request_id"])
    ]

    return {
        "artifact_kind": "authored_world_materialization_request",
        "schema_version": "worldforge.authored_world_materialization_request.v1",
        "generated_at_utc": FIXED_GENERATED_AT_UTC,
        "execution_status": "not_materialized",
        "observation_status": "not_observed",
        "materialization_claim": "none",
        "materialization_mode": "unreal_neostack_editor",
        "generated_root": generated_root,
        "world": manifest["world"],
        "input": {
            "manifest_sha256": hashes["manifest.json"],
            "artifact_sha256": {name: hashes[name] for name in INPUT_FILES},
            "compiler_artifacts": list(EXPECTED_ARTIFACTS),
        },
        "operations": operations,
        "survey_requests": survey_requests,
        "provenance": {
            "compiler_sources": manifest["sources"],
            "compiler_provenance": manifest["worldforge_provenance"],
            "request_tool": _source_provenance(),
        },
        "scope": {
            "authority": "generic_worldforge_execution_request",
            "claims": [
                "request_prepared_only",
                "no_unreal_execution",
                "no_neostack_activity",
                "no_map_load",
                "no_observed_survey",
            ],
        },
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".materialization-request-",
                                                  suffix=".tmp", dir=str(path.parent))
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


def prepare_materialization_request(input_root: Path, generated_root: str,
                                    output_path: Path) -> dict[str, Any]:
    resolved_input, resolved_output = _preflight_output(input_root, output_path)
    generated = _validate_generated_root(generated_root)
    _, documents, hashes = _validate_input_root(resolved_input)
    request = _build_request(documents, hashes, generated)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(resolved_output, request)
    return request


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a generic inert Unreal/NeoStack materialization request.")
    parser.add_argument("--input-root", required=True, type=Path,
                        help="exact output directory from the authored-world compiler")
    parser.add_argument("--generated-root", required=True,
                        help="caller-supplied Unreal /Game package root")
    parser.add_argument("--output", required=True, type=Path,
                        help="new materialization-request.json path")
    args = parser.parse_args(argv)
    try:
        request = prepare_materialization_request(args.input_root, args.generated_root, args.output)
    except PrepareError as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        return 2
    print("PREPARED: {} operations and {} survey requests under {}".format(
        len(request["operations"]), len(request["survey_requests"]), args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
