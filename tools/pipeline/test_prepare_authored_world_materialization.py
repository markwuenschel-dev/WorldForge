#!/usr/bin/env python3
"""Focused tests for the generic materialization-request preparation seam."""

from __future__ import annotations

import copy
import hashlib
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
import prepare_authored_world_materialization as prepare  # noqa: E402


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


class PrepareMaterializationTests(unittest.TestCase):
    def _compile(self, root: Path, spec: dict | None = None) -> Path:
        spec_path = root / "caller-world.json"
        schema_path = root / "caller-world.schema.json"
        spec_path.write_text(json.dumps(SPEC if spec is None else spec, indent=2), encoding="utf-8")
        schema_path.write_text(json.dumps(SCHEMA, indent=2), encoding="utf-8")
        output = root / "compiled"
        compiler.compile_authored_world(spec_path, schema_path, output)
        return output

    def test_request_is_deterministic_honest_and_provenance_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = self._compile(root)
            first = root / "first" / "materialization-request.json"
            second = root / "second" / "materialization-request.json"
            prepare.prepare_materialization_request(compiled, "/Game/Generated/WorldAlpha/", first)
            prepare.prepare_materialization_request(compiled, "/Game/Generated/WorldAlpha", second)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            request = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual("authored_world_materialization_request", request["artifact_kind"])
            self.assertEqual("worldforge.authored_world_materialization_request.v1",
                             request["schema_version"])
            self.assertEqual("not_materialized", request["execution_status"])
            self.assertEqual("not_observed", request["observation_status"])
            self.assertEqual("none", request["materialization_claim"])
            self.assertEqual("/Game/Generated/WorldAlpha", request["generated_root"])
            self.assertEqual(10, len(request["operations"]))
            self.assertEqual(7, len(request["survey_requests"]))
            self.assertEqual(
                ["request_prepared_only", "no_unreal_execution", "no_neostack_activity",
                 "no_map_load", "no_observed_survey"],
                request["scope"]["claims"],
            )
            self.assertEqual(
                hashlib.sha256((compiled / "manifest.json").read_bytes()).hexdigest(),
                request["input"]["manifest_sha256"],
            )
            self.assertEqual(
                {name: hashlib.sha256((compiled / name).read_bytes()).hexdigest()
                 for name in prepare.INPUT_FILES},
                request["input"]["artifact_sha256"],
            )
            self.assertEqual(SPEC["points_of_interest"], [
                item["descriptor"]["opaque_reference"]
                for item in request["operations"] if item["operation_kind"] == "point_of_interest"
            ])
            self.assertTrue(all(item["request"]["status"] == "planned" and
                                item["request"]["observation"] == "not_observed"
                                for item in request["survey_requests"]))

    def test_stale_collision_traversal_and_extra_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = self._compile(root)
            existing = root / "existing" / "materialization-request.json"
            existing.parent.mkdir()
            existing.write_text("old\n", encoding="utf-8")
            with self.assertRaisesRegex(prepare.PrepareError, "already exists"):
                prepare.prepare_materialization_request(compiled, "/Game/Generated/WorldAlpha", existing)

            inside = compiled / "materialization-request.json"
            with self.assertRaisesRegex(prepare.PrepareError, "inside the input root"):
                prepare.prepare_materialization_request(compiled, "/Game/Generated/WorldAlpha", inside)

            for index, bad_root in enumerate(("/Game/../Outside", "C:/Outside", "/Content/World")):
                with self.assertRaisesRegex(prepare.PrepareError, "generated root"):
                    prepare.prepare_materialization_request(
                        compiled, bad_root, root / "bad{}".format(index) / "materialization-request.json")

            (compiled / "stale.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(prepare.PrepareError, "exact compiler output"):
                prepare.prepare_materialization_request(
                    compiled, "/Game/Generated/WorldAlpha", root / "extra" / "materialization-request.json")

    def test_duplicate_json_is_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = self._compile(root)
            manifest = compiled / "manifest.json"
            original = manifest.read_text(encoding="utf-8")
            manifest.write_text('{"artifact_kind":"x","artifact_kind":"y"}\n', encoding="utf-8")
            output = root / "duplicate" / "materialization-request.json"
            with self.assertRaisesRegex(prepare.PrepareError, "duplicate JSON object key"):
                prepare.prepare_materialization_request(compiled, "/Game/Generated/WorldAlpha", output)
            self.assertFalse(output.exists())
            manifest.write_text(original, encoding="utf-8")

    def test_atomic_write_failure_leaves_no_partial_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = self._compile(root)
            output = root / "atomic" / "materialization-request.json"
            with mock.patch.object(prepare.os, "replace", side_effect=OSError("simulated replace failure")):
                with self.assertRaises(OSError):
                    prepare.prepare_materialization_request(compiled, "/Game/Generated/WorldAlpha", output)
            self.assertFalse(output.exists())
            self.assertEqual([], list(output.parent.glob(".materialization-request-*.tmp")))

    def test_source_hygiene_and_public_cli(self):
        source = Path(prepare.__file__).read_text(encoding="utf-8").lower()
        for forbidden in ("gloamstead", "cycle2", "veilheart"):
            self.assertNotIn(forbidden, source)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            compiled = self._compile(root)
            output = root / "cli" / "materialization-request.json"
            run = subprocess.run(
                [sys.executable, "-B", str(Path(prepare.__file__)),
                 "--input-root", str(compiled),
                 "--generated-root", "/Game/Generated/WorldAlpha",
                 "--output", str(output)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(0, run.returncode, run.stderr)
            self.assertTrue(output.is_file())
            self.assertIn("PREPARED:", run.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
