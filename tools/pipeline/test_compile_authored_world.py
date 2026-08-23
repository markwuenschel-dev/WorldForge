#!/usr/bin/env python3
"""Focused public-CLI tests for the generic authored-world compiler."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PIPELINE = Path(__file__).resolve().parent
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

import compile_authored_world as compiler  # noqa: E402


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "world_id", "input_version", "seed", "authored_anchors",
        "points_of_interest", "terrain_slice", "reactive_categories",
        "world_state_scenarios",
    ],
    "properties": {
        "world_id": {"type": "string"},
        "input_version": {"type": "string"},
        "seed": {"type": "integer"},
        "authored_anchors": {"type": "array", "items": {}},
        "points_of_interest": {"type": "array", "items": {}},
        "terrain_slice": {"type": "object"},
        "reactive_categories": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "values"],
                "properties": {"id": {"type": "string"}, "values": {}},
            },
        },
        "world_state_scenarios": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "state_values"],
                "properties": {
                    "id": {"type": "string"},
                    "state_values": {"type": "object"},
                },
            },
        },
    },
}

SPEC = {
    "world_id": "world_alpha",
    "input_version": "caller-v3",
    "seed": 1447,
    "authored_anchors": [{"caller_ref": "anchor-west"}, "anchor-east"],
    "points_of_interest": [{"caller_ref": "poi-ridge"}],
    "terrain_slice": {"caller_terrain": "terrain-ref-7"},
    "reactive_categories": [
        {"id": "category_alpha", "values": {"caller_value": "a"}},
        {"id": "category_beta", "values": {"caller_value": "b"}},
    ],
    "world_state_scenarios": [
        {"id": "scenario_clear", "state_values": {"caller_state": "clear"}},
        {"id": "scenario_changed", "state_values": {"caller_state": "changed"}},
    ],
}


class CompileAuthoredWorldTests(unittest.TestCase):
    def _write_inputs(self, root, spec=None, schema=None):
        spec_path = root / "caller-world.json"
        schema_path = root / "caller-world.schema.json"
        spec_path.write_text(json.dumps(SPEC if spec is None else spec, indent=2), encoding="utf-8")
        schema_path.write_text(json.dumps(SCHEMA if schema is None else schema, indent=2), encoding="utf-8")
        return spec_path, schema_path

    def _run(self, spec_path, schema_path, output_root, force_stdlib=False):
        stderr = io.StringIO()
        patcher = (mock.patch.object(compiler, "_load_jsonschema", return_value=None)
                   if force_stdlib else contextlib.nullcontext())
        with patcher, contextlib.redirect_stderr(stderr):
            rc = compiler.main([
                "--spec", str(spec_path), "--schema", str(schema_path),
                "--output-root", str(output_root),
            ])
        return rc, stderr.getvalue()

    def test_cli_emits_deterministic_honest_generic_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path, schema_path = self._write_inputs(root)
            first, second = root / "first", root / "second"
            before_spec, before_schema = spec_path.read_bytes(), schema_path.read_bytes()
            self.assertEqual(0, self._run(spec_path, schema_path, first, force_stdlib=True)[0])
            self.assertEqual(0, self._run(spec_path, schema_path, second, force_stdlib=True)[0])
            self.assertEqual(before_spec, spec_path.read_bytes())
            self.assertEqual(before_schema, schema_path.read_bytes())

            expected = {"manifest.json", "terrain-slice.json", "poi-descriptors.json",
                        "placement-variants.json", "material-variants.json", "survey-requests.json"}
            self.assertEqual(expected, {path.name for path in first.iterdir()})
            self.assertEqual(
                {path.name: path.read_bytes() for path in first.iterdir()},
                {path.name: path.read_bytes() for path in second.iterdir()},
            )
            manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("1970-01-01T00:00:00Z", manifest["generated_at_utc"])
            self.assertEqual("world_alpha", manifest["world"]["world_id"])
            self.assertEqual("caller-v3", manifest["world"]["input_version"])
            self.assertEqual(1447, manifest["world"]["seed"])
            self.assertEqual(hashlib.sha256(spec_path.read_bytes()).hexdigest(),
                             manifest["sources"]["spec"]["sha256"])
            self.assertEqual(hashlib.sha256(schema_path.read_bytes()).hexdigest(),
                             manifest["sources"]["schema"]["sha256"])
            self.assertIn("source_commit", manifest["worldforge_provenance"])
            self.assertIn("source_tree_dirty", manifest["worldforge_provenance"])
            self.assertEqual("not_materialized", manifest["execution_status"])

            placements = json.loads((first / "placement-variants.json").read_text(encoding="utf-8"))
            materials = json.loads((first / "material-variants.json").read_text(encoding="utf-8"))
            pois = json.loads((first / "poi-descriptors.json").read_text(encoding="utf-8"))
            surveys = json.loads((first / "survey-requests.json").read_text(encoding="utf-8"))
            self.assertEqual(4, len(placements["variants"]))
            self.assertEqual(4, len(materials["variants"]))
            self.assertEqual(SPEC["points_of_interest"],
                             [item["opaque_reference"] for item in pois["descriptors"]])
            self.assertEqual(7, len(surveys["requests"]))
            self.assertTrue(all(request["status"] == "planned" and
                                request["observation"] == "not_observed"
                                for request in surveys["requests"]))
            self.assertEqual(
                {item["id"] for item in SPEC["reactive_categories"]},
                {item["reactive_category"]["id"] for item in placements["variants"]},
            )
            self.assertEqual(
                {item["state_values"]["caller_state"] for item in SPEC["world_state_scenarios"]},
                {item["world_state_scenario"]["state_values"]["caller_state"]
                 for item in placements["variants"]},
            )

    def test_schema_rejection_and_unknown_category_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bad_type = copy.deepcopy(SPEC)
            bad_type["seed"] = "not-an-integer"
            spec_path, schema_path = self._write_inputs(root, spec=bad_type)
            rc, error = self._run(spec_path, schema_path, root / "schema-out", force_stdlib=True)
            self.assertEqual(2, rc)
            self.assertIn("schema validation failed", error)

            ref_schema = {"$defs": {"world": copy.deepcopy(SCHEMA)}, "$ref": "#/$defs/world"}
            spec_path, schema_path = self._write_inputs(root, schema=ref_schema)
            self.assertEqual(0, self._run(spec_path, schema_path, root / "ref-out", force_stdlib=True)[0])

            unsupported_schema = copy.deepcopy(SCHEMA)
            unsupported_schema["allOf"] = []
            spec_path, schema_path = self._write_inputs(root, schema=unsupported_schema)
            rc, error = self._run(spec_path, schema_path, root / "unsupported-out", force_stdlib=True)
            self.assertEqual(2, rc)
            self.assertIn("unsupported JSON Schema keyword", error)

            unknown = copy.deepcopy(SPEC)
            unknown["reactive_categories"][0]["unexpected"] = "reject-me"
            spec_path, schema_path = self._write_inputs(root, spec=unknown)
            rc, error = self._run(spec_path, schema_path, root / "unknown-out", force_stdlib=True)
            self.assertEqual(2, rc)
            self.assertIn("schema validation failed", error)

    def test_duplicate_ids_and_traversal_ids_cannot_escape_output_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            duplicate = copy.deepcopy(SPEC)
            duplicate["reactive_categories"][1]["id"] = "category_alpha"
            spec_path, schema_path = self._write_inputs(root, spec=duplicate)
            output = root / "duplicate-out"
            rc, error = self._run(spec_path, schema_path, output, force_stdlib=True)
            self.assertEqual(2, rc)
            self.assertIn("duplicate reactive category id", error)
            self.assertFalse(output.exists())

            traversal = copy.deepcopy(SPEC)
            traversal["world_id"] = "../escape"
            spec_path, schema_path = self._write_inputs(root, spec=traversal)
            output = root / "safe-output"
            rc, error = self._run(spec_path, schema_path, output, force_stdlib=True)
            self.assertEqual(2, rc)
            self.assertIn("unsafe world id", error)
            self.assertFalse(output.exists())

            absolute = copy.deepcopy(SPEC)
            absolute["world_id"] = "C:\\outside"
            spec_path, schema_path = self._write_inputs(root, spec=absolute)
            output = root / "absolute-output"
            rc, error = self._run(spec_path, schema_path, output, force_stdlib=True)
            self.assertEqual(2, rc)
            self.assertIn("unsafe world id", error)
            self.assertFalse(output.exists())

    def test_input_output_name_collision_fails_before_any_generated_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "output"
            output_root.mkdir()
            spec_path = output_root / "manifest.json"
            schema_path = output_root / "terrain-slice.json"
            spec_path.write_text(json.dumps(SPEC, indent=2), encoding="utf-8")
            schema_path.write_text(json.dumps(SCHEMA, indent=2), encoding="utf-8")
            before = {path.name: path.read_bytes() for path in output_root.iterdir()}

            rc, error = self._run(spec_path, schema_path, output_root, force_stdlib=True)

            self.assertEqual(2, rc)
            self.assertIn("input path collides with generated output", error)
            self.assertEqual(before, {path.name: path.read_bytes() for path in output_root.iterdir()})
            self.assertEqual({"manifest.json", "terrain-slice.json"},
                             {path.name for path in output_root.iterdir()})

    def test_source_hygiene_and_stdlib_fallback_are_honest(self):
        source = Path(compiler.__file__).read_text(encoding="utf-8").lower()
        for forbidden in ("gloamstead", "cycle2", "veilheart"):
            self.assertNotIn(forbidden, source)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path, schema_path = self._write_inputs(root)
            run = subprocess.run(
                [sys.executable, str(Path(compiler.__file__)), "--spec", str(spec_path),
                 "--schema", str(schema_path), "--output-root", str(root / "out")],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, run.returncode, run.stderr)
            self.assertTrue((root / "out" / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
